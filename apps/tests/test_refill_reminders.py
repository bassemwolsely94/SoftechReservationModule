"""
B1 — WhatsApp refill reminders (apps/followups/refill_reminders.py). No real WhatsApp call:
the sender is a fake; the webhook test drives process_webhook with a Meta-shaped payload.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.catalog.models import Item, ItemStock
from apps.customers.models import Customer
from apps.followups import refill_reminders as RR
from apps.followups.models import FollowUpTask, RefillReminder, RefillReminderOptOut
from apps.reservations.models import Reservation

from .factories import make_branch, make_user

TODAY = timezone.localdate()


class FakeSender:
    def __init__(self, fail=False):
        self.fail, self.calls, self.texts = fail, [], []

    def send_template(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError('meta 400')
        return {'messages': [{'id': f'wamid.{len(self.calls)}'}]}

    def send_text(self, **kw):
        self.texts.append(kw)
        return {}


class _Base(TestCase):
    def setUp(self):
        self.branch = make_branch('النزهة', '130')
        self.branch.is_operational = True
        self.branch.save()
        self.item = Item.objects.create(softech_id='500001', name='CONCOR 5MG', pack_price=Decimal('120'), is_active=True)
        self.cust = self.customer('أحمد محمد علي', '01001234567', 'P1')

    def customer(self, name, phone, pic):
        return Customer.objects.create(name=name, phone=phone, softech_pic=pic, preferred_branch=self.branch)

    def task(self, cust=None, due=0, status='pending', task_type='refill', item=True):
        return FollowUpTask.objects.create(customer=cust or self.cust, item=self.item if item else None,
                                           branch=self.branch, task_type=task_type, status=status,
                                           due_date=TODAY + dt.timedelta(days=due))


class EligibilityTests(_Base):
    def test_window_status_and_type(self):
        ok = self.task(due=2)
        self.task(self.customer('ب', '01001234568', 'P2'), due=9)                      # too far ahead
        self.task(self.customer('ج', '01001234569', 'P3'), due=-5)                     # too long overdue
        self.task(self.customer('د', '01001234570', 'P4'), status='done')
        self.task(self.customer('هـ', '01001234571', 'P5'), task_type='demand')
        to_send, skipped, _ = RR.candidates()
        self.assertEqual([c['task'].pk for c in to_send], [ok.pk])
        self.assertEqual(to_send[0]['phone'], '01001234567')

    def test_skip_reasons(self):
        RefillReminderOptOut.objects.create(customer=self.customer('opt', '01011111111', 'O1'))
        self.task(RefillReminderOptOut.objects.get().customer)
        self.task(self.customer('nophone', '123', 'N1'))
        two = self.customer('two', '01022222222', 'T1')
        self.task(two, due=0)
        self.task(two, due=1)                                                         # same customer
        oos = Item.objects.create(softech_id='500002', name='OOS', is_active=True)
        ItemStock.objects.create(item=oos, branch=self.branch, quantity_on_hand=0)
        t = self.task(self.customer('oos', '01033333333', 'S1'))
        t.item = oos
        t.save()
        closed = make_branch('مغلق', '999')
        closed.is_operational = False
        closed.save()
        nb = self.customer('nobranch', '01044444444', 'B1')
        nb.preferred_branch = closed
        nb.save()
        FollowUpTask.objects.create(customer=nb, item=self.item, branch=closed, task_type='refill',
                                    status='pending', due_date=TODAY)
        _, skipped, rows = RR.candidates()
        self.assertEqual(dict(skipped), {'opted_out': 1, 'no_phone': 1, 'same_customer': 1,
                                         'out_of_stock': 1, 'no_branch': 1})
        self.assertTrue(all(r['reason_label'] for r in rows))

    def test_recent_reminder_and_cap(self):
        t = self.task()
        RefillReminder.objects.create(task=self.task(due=-1), customer=self.cust, phone='01001234567',
                                      due_date=TODAY, status='sent', sent_at=timezone.now())
        _, skipped, _ = RR.candidates()
        self.assertEqual(skipped['recent_reminder'], 1)
        self.assertNotIn(t.pk, [c['task'].pk for c in RR.candidates()[0]])
        for i in range(3):
            self.task(self.customer(f'c{i}', f'0105555555{i}', f'C{i}'))
        to_send, skipped, _ = RR.candidates(cap=2)
        self.assertEqual((len(to_send), skipped['over_cap']), (2, 1))


class SendTests(_Base):
    def test_gate_off_is_preview_only(self):
        self.task()
        out = RR.run(sender=FakeSender())
        self.assertEqual((out['send_enabled'], out['candidates'], out['sent']), (False, 1, 0))
        self.assertFalse(RefillReminder.objects.exists())
        pv = RR.preview()
        self.assertEqual(pv['to_send'][0]['phone'], '••••4567')                      # masked

    @override_settings(REFILL_REMINDER_SEND_ENABLED=True)
    def test_sends_template_once_with_variables_and_payloads(self):
        t = self.task(due=3)
        s = FakeSender()
        out = RR.run(sender=s)
        self.assertEqual((out['sent'], out['failed']), (1, 0))
        call = s.calls[0]
        self.assertEqual((call['template_name'], call['language'], call['wa_id']), ('refill_reminder', 'ar', '01001234567'))
        due = TODAY + dt.timedelta(days=3)
        self.assertEqual([v['text'] for v in call['variables']],
                         ['أحمد', f'{due.day} {RR.AR_MONTHS[due.month - 1]}', 'النزهة'])
        rem = RefillReminder.objects.get(task=t)
        self.assertEqual(call['quick_reply_payloads'],
                         [f'refill:{rem.pk}:branch', f'refill:{rem.pk}:delivery', f'refill:{rem.pk}:stop'])
        self.assertEqual((rem.status, rem.wamid), ('sent', 'wamid.1'))
        self.assertNotIn('CONCOR', str(call))                                         # medicine never named
        self.assertEqual(RR.run(sender=s)['sent'], 0)                                 # never twice
        self.assertEqual(len(s.calls), 1)

    @override_settings(REFILL_REMINDER_SEND_ENABLED=True, REFILL_REMINDER_MAX_ATTEMPTS=2)
    def test_failure_is_recorded_and_retried_up_to_the_limit(self):
        t = self.task()
        self.assertEqual(RR.run(sender=FakeSender(fail=True))['failed'], 1)
        rem = RefillReminder.objects.get(task=t)
        self.assertEqual(rem.status, 'failed')
        self.assertIn('meta 400', rem.error)
        self.assertEqual(RR.run(sender=FakeSender(fail=True))['failed'], 1)            # 2nd attempt
        self.assertEqual(RR.run(sender=FakeSender())['candidates'], 0)                # limit reached
        self.assertEqual(RefillReminder.objects.get(task=t).attempts, 2)


@override_settings(REFILL_REMINDER_SEND_ENABLED=True)
class ReplyTests(_Base):
    def setUp(self):
        super().setUp()
        self.t = self.task()
        RR.run(sender=FakeSender())
        self.rem = RefillReminder.objects.get(task=self.t)

    def reply(self, choice, wa_id='201001234567'):
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as WS:
            out = RR.handle_button_reply(wa_id=wa_id, payload=f'refill:{self.rem.pk}:{choice}')
        return out, WS

    def test_branch_pickup_creates_one_reservation(self):
        out, WS = self.reply('branch')
        self.assertEqual(out, 'branch')
        res = Reservation.objects.get()
        self.assertEqual((res.customer_id, res.item_id, res.branch_id, res.order_source, res.fulfillment_method,
                          res.status), (self.cust.pk, self.item.pk, self.branch.pk, 'cc_whatsapp', 'pickup', 'pending'))
        self.rem.refresh_from_db()
        self.assertEqual((self.rem.status, self.rem.reply_choice, self.rem.reservation_id), ('replied', 'branch', res.pk))
        self.assertIn('رد واتساب', FollowUpTask.objects.get(pk=self.t.pk).notes)
        WS.return_value.send_text.assert_called_once()                                # confirmation
        self.assertEqual(self.reply('delivery')[0], 'duplicate')                      # first answer wins
        self.assertEqual(Reservation.objects.count(), 1)

    def test_delivery_and_stop(self):
        self.assertEqual(self.reply('delivery')[0], 'delivery')
        self.assertEqual(Reservation.objects.get().fulfillment_method, 'delivery')
        other = self.customer('سارة', '01009999999', 'P9')
        t2 = self.task(other)
        RR.run(sender=FakeSender())
        rem2 = RefillReminder.objects.get(task=t2)
        with mock.patch('apps.whatsapp.sender.WhatsAppSender'):
            self.assertEqual(RR.handle_button_reply(wa_id='201009999999', payload=f'refill:{rem2.pk}:stop'), 'stop')
        self.assertTrue(RefillReminderOptOut.objects.filter(customer=other).exists())
        self.assertEqual(Reservation.objects.count(), 1)
        self.task(other, due=1)
        self.assertEqual(RR.candidates()[1]['opted_out'], 1)

    def test_foreign_or_unknown_payloads_are_ignored(self):
        self.assertEqual(self.reply('branch', wa_id='201555555555')[0], 'wrong_sender')
        self.assertEqual(RR.handle_button_reply(wa_id='201001234567', payload='something else'), 'not_ours')
        self.assertEqual(RR.handle_button_reply(wa_id='201001234567', payload='refill:999999:branch'), 'unknown')
        self.assertFalse(Reservation.objects.exists())

    @override_settings(REFILL_REMINDER_SEND_ENABLED=False)
    def test_webhook_button_tap_end_to_end(self):
        from apps.whatsapp.models import WAMessage
        from apps.whatsapp.webhook import process_webhook
        process_webhook({'object': 'whatsapp_business_account', 'entry': [{'id': 'E', 'changes': [{'value': {
            'metadata': {'phone_number_id': ''},
            'messages': [{'from': '201001234567', 'id': 'wamid.IN1', 'type': 'button', 'timestamp': '1',
                          'context': {'id': self.rem.wamid},
                          'button': {'text': 'جهّزوا طلبي في الفرع', 'payload': f'refill:{self.rem.pk}:branch'}}]}}]}]})
        self.assertEqual(WAMessage.objects.get(wamid='wamid.IN1').body, 'جهّزوا طلبي في الفرع')
        self.assertEqual(Reservation.objects.get().fulfillment_method, 'pickup')


class ApiTests(_Base):
    def test_permissions_and_preview(self):
        self.task()
        _, _, cc = make_user('cc1', role='call_center')
        _, _, sup = make_user('sup1', role='supervisor')
        _, _, ph = make_user('ph1', role='pharmacist')
        r = cc.get('/api/followups/refill-reminders/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['can_run'])
        self.assertEqual(len(cc.get('/api/followups/refill-reminders/preview/').data['to_send']), 1)
        self.assertEqual(cc.post('/api/followups/refill-reminders/run/').status_code, 403)
        self.assertEqual(ph.get('/api/followups/refill-reminders/').status_code, 403)
        r = sup.post('/api/followups/refill-reminders/run/')
        self.assertEqual((r.status_code, r.data['send_enabled'], r.data['candidates']), (200, False, 1))
        self.assertFalse(RefillReminder.objects.exists())
