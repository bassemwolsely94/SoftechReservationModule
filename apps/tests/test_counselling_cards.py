"""Project 4 — staff-sent WhatsApp counselling card. No real WhatsApp call: the sender is a fake."""
import uuid

from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.counselling import cards, services
from apps.counselling.models import CounselCardItem, CounselCardOptOut, CounselCardSend
from apps.customers.models import Customer
from apps.whatsapp.models import WATemplate

from .factories import make_branch, make_item, make_user

ON = dict(COUNSELLING_CONTENT_ENABLED=True, COUNSEL_CARD_SEND_ENABLED=True)


class FakeSender:
    def __init__(self, fail=False):
        self.fail, self.templates, self.texts = fail, [], []

    def send_template(self, **kw):
        if self.fail:
            raise RuntimeError('meta 400')
        self.templates.append(kw)
        return {'messages': [{'id': f'wamid.{len(self.templates)}'}]}

    def send_text(self, **kw):
        self.texts.append(kw)
        return {'messages': [{'id': 'wamid.t'}]}


@override_settings(**ON)
class CardTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.ph, self.ph_c = make_user('ph_cd', role='pharmacist', branch=self.branch)
        _, self.sp, self.sp_c = make_user('sp_cd', role='salesperson', branch=self.branch)
        self.cust = Customer.objects.create(name='منى أحمد علي', phone='01012345678', softech_pic='PC1')
        self.item = make_item('أوجمنتين 1 جم', 'CD001')
        self.item2 = make_item('بنادول', 'CD002')
        sheet = services.create_sheet(self.ph, {'how_to_use_ar': 'بعد الأكل', 'dose_ar': 'قرص'}, [self.item.pk])
        services.approve(self.ph, sheet)
        WATemplate.objects.create(name='counsel_card', status='approved', body_text='x')
        self.fake = FakeSender()

    def _send(self, key=None, **kw):
        args = dict(customer=self.cust, phone='', item_ids=[self.item.pk], actor=self.sp, branch=self.branch,
                    idempotency_key=key or uuid.uuid4().hex, sender=self.fake)
        args.update(kw)
        return cards.send_card(**args)

    @override_settings(COUNSEL_CARD_SEND_ENABLED=False)
    def test_nothing_stored_or_sent_when_switch_off(self):
        with self.assertRaises(Exception):
            self._send()
        self.assertFalse(CounselCardSend.objects.exists())
        self.assertEqual(self.fake.templates, [])

    def test_same_idempotency_key_sends_once(self):
        a = self._send('k1')
        b = self._send('k1')
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(len(self.fake.templates), 1)
        self.assertEqual(CounselCardSend.objects.count(), 1)

    def test_phone_formats_normalise_to_one_hash(self):
        forms = ['01012345678', '+201012345678', '201012345678', '010 1234 5678', '0020-1012345678']
        self.assertEqual({cards.normalise_phone(f) for f in forms}, {'201012345678'})
        self.assertEqual(len({cards.phone_hash(cards.normalise_phone(f)) for f in forms}), 1)
        self.assertIsNone(cards.normalise_phone('0223456789'))       # landline
        self.assertIsNone(cards.normalise_phone('0101234'))

    def test_opted_out_phone_blocked(self):
        CounselCardOptOut.objects.create(phone_hash=cards.phone_hash('201012345678'))
        s = self._send(phone='+20 101 234 5678', customer=None)
        self.assertEqual(s.status, 'blocked_optout')
        self.assertEqual(self.fake.templates, [])

    def test_opted_out_customer_blocked_on_other_phone(self):
        CounselCardOptOut.objects.create(customer=self.cust, phone_hash='x')
        self.assertEqual(self._send(phone='01112345678').status, 'blocked_optout')

    def test_only_approved_versions_pinned(self):
        services.create_sheet(self.ph, {'dose_ar': 'مسودة'}, [self.item2.pk])      # draft only
        s = self._send(item_ids=[self.item.pk, self.item2.pk])
        lines = list(CounselCardItem.objects.filter(send=s))
        self.assertEqual([l.item_id for l in lines], [self.item.pk])
        self.assertEqual(lines[0].version.version, 1)

    def test_no_approved_items_refused(self):
        with self.assertRaises(Exception):
            self._send(item_ids=[self.item2.pk])
        self.assertFalse(CounselCardSend.objects.exists())

    def test_recent_item_skipped_unless_resend(self):
        self._send()
        with self.assertRaises(Exception):
            self._send()
        self.assertEqual(self._send(resend=True).status, 'sent')
        self.assertEqual(len(self.fake.templates), 2)

    @override_settings(COUNSEL_CARD_DAILY_CAP=1)
    def test_daily_cap(self):
        self._send()
        with self.assertRaises(Exception):
            self._send(resend=True)

    def test_template_has_no_item_name(self):
        self._send()
        sent = repr(self.fake.templates)
        self.assertNotIn('أوجمنتين', sent)
        self.assertNotIn('CD001', sent)
        call = self.fake.templates[0]
        self.assertEqual(call['variables'], [{'type': 'text', 'text': 'منى'}])
        self.assertEqual(len(call['url_button_params']), 1)

    def test_template_not_approved_marks_failed(self):
        WATemplate.objects.all().update(status='pending')
        s = self._send()
        self.assertEqual((s.status, s.fail_reason), ('failed', 'template_not_approved'))

    def test_provider_error_marks_failed(self):
        s = self._send(sender=FakeSender(fail=True))
        self.assertEqual(s.status, 'failed')

    def test_audit_written(self):
        s = self._send()
        log = AuditLog.objects.get(action='counsel_card_sent', object_id=str(s.pk))
        self.assertEqual(log.user_id, self.sp.pk)
        self.assertEqual(log.new_data['items'][0]['version'], 1)
        self.assertEqual(s.phone_masked, '010*****678')

    def test_preview_never_writes(self):
        r = self.sp_c.post('/api/counselling/cards/preview/',
                           {'customer_id': self.cust.pk, 'item_ids': [self.item.pk, self.item2.pk]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([l['has_guidance'] for l in r.data['lines']], [True, False])
        self.assertEqual(r.data['phone'], '010*****678')
        self.assertFalse(CounselCardSend.objects.exists())

    def test_salesperson_can_send_via_api(self):
        from unittest import mock
        with mock.patch('apps.whatsapp.sender.WhatsAppSender', return_value=self.fake):
            r = self.sp_c.post('/api/counselling/cards/send/', {
                'customer_id': self.cust.pk, 'item_ids': [self.item.pk], 'branch_id': self.branch.pk,
                'idempotency_key': 'api-1'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'sent')

    def test_delivery_role_cannot_send(self):
        _, _, d_c = make_user('dl_cd', role='delivery', branch=self.branch)
        r = d_c.post('/api/counselling/cards/send/', {'customer_id': self.cust.pk, 'item_ids': [self.item.pk],
                                                      'branch_id': self.branch.pk, 'idempotency_key': 'd'},
                     format='json')
        self.assertEqual(r.status_code, 403)


class SenderUrlButtonTests(TestCase):
    def test_sender_url_button_component_shape(self):
        from unittest import mock
        from apps.whatsapp.sender import WhatsAppSender
        s = WhatsAppSender.__new__(WhatsAppSender)
        with mock.patch.object(WhatsAppSender, '_post', return_value={}) as post, \
                mock.patch.object(WhatsAppSender, '_base', return_value={'to': '201'}), \
                mock.patch.object(WhatsAppSender, '_record_outbound'):
            s.send_template(wa_id='201', template_name='t', quick_reply_payloads=['a'], url_button_params=['TOK'])
        comps = post.call_args[0][0]['template']['components']
        self.assertEqual(comps[-1], {'type': 'button', 'sub_type': 'url', 'index': '1',
                                     'parameters': [{'type': 'text', 'text': 'TOK'}]})
