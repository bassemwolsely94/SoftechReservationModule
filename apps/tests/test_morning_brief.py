"""09:00 branch morning brief over WhatsApp (phone alerts, Task 9)."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.branches.models import Branch, BranchSettings
from apps.catalog.models import Category, Item
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.forecasting import kpi_board
from apps.forecasting.models import ChannelBucketMap, KpiActualRollup as K
from apps.incentives.models import SalesTarget
from apps.insights.models import InsightFinding, InsightRecipient, InsightRun
from apps.notifications.phone_alerts.models import PhoneAlert, PhoneAlertPolicy
from apps.reservations.models import Reservation
from apps.transfers.models import TransferRequest, TransferRequestItem

TODAY = date(2026, 11, 3)          # a Tuesday: yesterday = Mon 2 Nov, same weekday last week = Mon 26 Oct
YESTERDAY = date(2026, 11, 2)
LAST_WEEK = date(2026, 10, 26)


def _when(d):
    return timezone.make_aware(datetime(d.year, d.month, d.day, 12, 0))


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(softech_branch_id='961', code='961', name='B961',
                                           name_ar='فرع الزيتون')
        cls.other = Branch.objects.create(softech_branch_id='962', code='962', name='B962',
                                          name_ar='فرع المعادي')
        ChannelBucketMap.objects.create(person_type='10', channel='91', label='c', bucket='cash',
                                        counts_customer=True, include_in_profit=True, active=True)
        cat = Category.objects.create(softech_id='CAT-MB', name='c')
        cls.item = Item.objects.create(softech_id='MB1', name='باراسيتامول', category=cat)
        cls.cust = Customer.objects.create(name='ع', softech_pic='PICMB', softech_id='C-MB')

    def _sale(self, ref, d, total, branch=None):
        ph = PurchaseHistory.objects.create(
            customer=self.cust, softech_invoice_id=ref, branch=branch or self.branch, doc_code='115',
            total_amount=Decimal(total), invoice_date=_when(d), sales_channel='91',
            sales_person_type='10', softech_phcode=ref)
        PurchaseHistoryLine.objects.create(purchase=ph, item=self.item, quantity=Decimal(1),
                                           unit_price=Decimal(total), line_total=Decimal(total),
                                           cost_at_sale=Decimal(1))


def _compose(branch, day=TODAY):
    from apps.insights import brief
    with mock.patch.object(kpi_board, 'latest_complete_date', return_value=YESTERDAY):
        return brief.compose(branch, day)


class ComposeTests(_Base):
    def setUp(self):
        self._sale('Y1', YESTERDAY, 1000)
        self._sale('Y2', YESTERDAY, 500)         # yesterday: 1500 over 2 invoices → basket 750
        self._sale('W1', LAST_WEEK, 1200)        # same weekday last week: 1200 → +25%
        self._sale('X1', YESTERDAY, 99999, branch=self.other)    # other branch never leaks in
        K.objects.create(branch=self.branch, year=2026, month=11, metric=K.M_CASH_DELIVERY,
                         value=Decimal('3000'))
        SalesTarget.objects.create(scope_type='branch', branch=self.branch, metric=K.M_CASH_DELIVERY,
                                   period_start=date(2026, 11, 1), period_end=date(2026, 11, 30),
                                   target_value=Decimal('30000'))

    def _run_with_findings(self):
        run = InsightRun.objects.create(domain='sales', period_type='day', period_start=YESTERDAY,
                                        period_end=YESTERDAY)
        for sev, msg in (('warning', 'تراجع ب'), ('critical', 'تراجع أ'), ('info', 'معلومة'),
                         ('warning', 'تراجع ج'), ('warning', 'تراجع د')):
            InsightFinding.objects.create(run=run, rule_code='r', category='volume', severity=sev,
                                          scope_type='branch', scope_key='961', message_ar=msg,
                                          message_en=msg)
        InsightFinding.objects.create(run=run, rule_code='r', category='volume', severity='critical',
                                      scope_type='branch', scope_key='962', message_ar='فرع آخر',
                                      message_en='x')
        return run

    def test_compose_sections_order_and_values(self):
        self._run_with_findings()
        Reservation.objects.create(branch=self.branch, item=self.item, customer=self.cust, status='pending',
                                   contact_phone='0100', contact_name='س', quantity_requested=1,
                                   follow_up_date=TODAY - timedelta(days=1))
        c = _compose(self.branch)
        t = c.text
        heads = ['أمس', 'الشهر حتى الآن', 'أهم 3 تراجعات', 'متابعة اليوم']
        pos = [t.index(h) for h in heads]
        self.assertEqual(pos, sorted(pos))
        self.assertIn('فرع الزيتون', t)
        self.assertIn('1,500', t)                    # yesterday cash + delivery (board bucket)
        self.assertIn('• نقدى + توصيل: 1,500', t)     # the board's label, not «صافي المبيعات» (M3)
        self.assertNotIn('صافي المبيعات', t)
        self.assertIn('750', t)                      # average basket
        self.assertIn('2', t)
        self.assertIn('+25', t)                      # vs same weekday last week
        self.assertIn('3,000', t)                    # MTD actual (from branch_mtd)
        self.assertIn('150%', t)                     # MTD pct = 3000 / (30000 * 2/30)
        self.assertIn('964', t)                      # daily needed = (30000-3000)/28
        self.assertEqual(c.headline_vars[2], '150%')
        self.assertNotIn('99,999', t)
        # top-3 negatives: critical first, then warnings; info and other branches excluded
        self.assertIn('تراجع أ', t)
        self.assertNotIn('معلومة', t)
        self.assertNotIn('فرع آخر', t)
        self.assertEqual(sum(t.count(x) for x in ('تراجع ب', 'تراجع ج', 'تراجع د', 'تراجع أ')), 3)
        self.assertIn(f'#{Reservation.objects.get().pk} — باراسيتامول', t)
        # template variables: branch, yesterday net sales, MTD %, all single-line
        self.assertEqual(len(c.headline_vars), 3)
        self.assertEqual(c.headline_vars[0], 'فرع الزيتون')
        self.assertIn('1,500', c.headline_vars[1])
        self.assertIn('%', c.headline_vars[2])
        self.assertTrue(all('\n' not in v for v in c.headline_vars))

    def test_drops_only_genuine_declines_ordered_by_magnitude(self):
        run = InsightRun.objects.create(domain='sales', period_type='day', period_start=YESTERDAY,
                                        period_end=YESTERDAY)
        for cat, sev, val, msg in (('coverage', 'critical', 999, 'لا توصيل'),
                                   ('discount', 'critical', 999, 'خصم'),
                                   ('comparison', 'warning', -10, 'صغير'),
                                   ('volume', 'warning', -40, 'كبير'),
                                   ('volume', 'critical', -5, 'حرج')):
            InsightFinding.objects.create(run=run, rule_code='r', category=cat, severity=sev, value=val,
                                          scope_type='branch', scope_key='961', message_ar=msg, message_en=msg)
        t = _compose(self.branch).text
        self.assertNotIn('لا توصيل', t)
        self.assertNotIn('خصم', t)
        self.assertLess(t.index('حرج'), t.index('كبير'))
        self.assertLess(t.index('كبير'), t.index('صغير'))

    def test_transfer_followups_do_not_query_per_transfer(self):
        def make(n):
            for i in range(n):
                tr = TransferRequest.objects.create(requesting_branch=self.branch, status='pending',
                                                    request_number=f'TQ-{n}-{i}')
                TransferRequestItem.objects.create(request=tr, item=self.item, quantity=1)
            TransferRequest.objects.update(updated_at=_when(TODAY - timedelta(days=5)))
        make(2)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as small:
            _compose(self.branch)
        make(20)
        with CaptureQueriesContext(connection) as big:
            _compose(self.branch)
        self.assertEqual(len(big), len(small))

    def test_compose_without_data_still_works(self):
        c = _compose(self.other)
        self.assertIn('فرع المعادي', c.text)
        self.assertNotIn('None', c.text)
        self.assertEqual(len(c.headline_vars), 3)

    def test_compose_caps_followups_at_5(self):
        for i in range(7):
            Reservation.objects.create(branch=self.branch, item=self.item, customer=self.cust,
                                       status='available', contact_phone='0100', contact_name='س',
                                       quantity_requested=1, follow_up_date=TODAY - timedelta(days=2))
        for i in range(6):
            tr = TransferRequest.objects.create(requesting_branch=self.branch, supplying_branch=self.other,
                                                status='pending', request_number=f'TR-9{i}')
            TransferRequestItem.objects.create(request=tr, item=self.item, quantity=1)
        TransferRequest.objects.update(updated_at=_when(TODAY - timedelta(days=5)))
        t = _compose(self.branch).text
        self.assertEqual(t.count('باراسيتامول'), 10)        # 5 reservations + 5 transfers
        self.assertIn('+2 أخرى', t)
        self.assertIn('+1 أخرى', t)
        self.assertIn('TR-90 — باراسيتامول', t)

    def test_closed_and_fresh_records_not_followed_up(self):
        Reservation.objects.create(branch=self.branch, item=self.item, customer=self.cust,
                                   status='fulfilled', contact_phone='0100', contact_name='س',
                                   quantity_requested=1, follow_up_date=TODAY - timedelta(days=9))
        TransferRequest.objects.create(requesting_branch=self.branch, status='pending',
                                       request_number='TR-FRESH')
        t = _compose(self.branch).text
        self.assertNotIn('TR-FRESH', t)
        self.assertNotIn('باراسيتامول', t)


@override_settings(MORNING_BRIEF_SEND_ENABLED=False)
class SendAllTests(_Base):
    def setUp(self):
        InsightRecipient.objects.create(name='مدير', wa_number='01011111111', branch=self.branch,
                                        morning_brief=True)
        BranchSettings.objects.create(branch=self.branch, alert_mobile='01022222222')

    def _send(self, day=TODAY):
        from apps.insights import brief
        with mock.patch.object(kpi_board, 'latest_complete_date', return_value=YESTERDAY):
            return brief.send_all(day=day)

    def test_send_all_targets_manager_and_branch_mobile(self):
        # noise: no brief flag, inactive, implausible, dup of the manager, branch with only a mobile
        InsightRecipient.objects.create(name='x', wa_number='01033333333', branch=self.branch)
        InsightRecipient.objects.create(name='y', wa_number='01044444444', branch=self.branch,
                                        morning_brief=True, active=False)
        InsightRecipient.objects.create(name='z', wa_number='12', branch=self.branch, morning_brief=True)
        InsightRecipient.objects.create(name='dup', wa_number='+20 101 111 1111', branch=self.branch,
                                        morning_brief=True)
        BranchSettings.objects.create(branch=self.other, alert_mobile='01055555555')
        self.assertEqual(self._send(), 2)
        rows = PhoneAlert.objects.filter(kind='brief')
        self.assertEqual(sorted(rows.values_list('phone', flat=True)), ['201011111111', '201022222222'])
        for a in rows:
            self.assertEqual(a.event, 'morning_brief')
            self.assertEqual(a.source, self.branch)
            self.assertEqual(a.status, 'sent')

    def test_brief_dry_run_when_switch_off(self):
        self._send()
        for a in PhoneAlert.objects.filter(kind='brief'):
            self.assertEqual([x.result for x in a.attempts.all()], ['dry_run'])

    @override_settings(PHONE_ALERTS_SEND_ENABLED=True, MORNING_BRIEF_SEND_ENABLED=False)
    def test_brief_follows_its_own_switch_not_the_phone_alerts_one(self):
        from apps.omni.models import ChannelAccount
        from apps.config.models import SystemSetting
        acc = ChannelAccount.objects.create(channel='whatsapp', name='staff', is_active=True)
        SystemSetting.objects.update_or_create(key='phone_alerts_channel_account',
                                               defaults={'value': str(acc.pk)})
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as WA:
            WA.return_value.is_configured = True
            self.assertEqual(self._send(), 2)
        WA.return_value.send_template.assert_not_called()
        for a in PhoneAlert.objects.filter(kind='brief'):
            self.assertEqual([x.result for x in a.attempts.all()], ['dry_run'])

    @override_settings(MORNING_BRIEF_SEND_ENABLED=True)
    def test_template_sent_with_brief_payload_when_on(self):
        from apps.omni.models import ChannelAccount
        from apps.config.models import SystemSetting
        acc = ChannelAccount.objects.create(channel='whatsapp', name='staff', is_active=True)
        SystemSetting.objects.update_or_create(key='phone_alerts_channel_account',
                                               defaults={'value': str(acc.pk)})
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as WA:
            WA.return_value.is_configured = True
            WA.return_value.send_template.return_value = {'messages': [{'id': 'wamid.B'}]}
            self.assertEqual(self._send(), 2)
        calls = WA.return_value.send_template.call_args_list
        self.assertEqual(len(calls), 2)
        for c in calls:
            kw = c.kwargs
            self.assertEqual(kw['template_name'], 'morning_brief')
            token = PhoneAlert.objects.get(phone=kw['wa_id']).token
            self.assertEqual(kw['quick_reply_payloads'], [f'brief:{token}'])
            self.assertEqual(len(kw['variables']), 3)

    def test_send_all_is_once_per_calendar_day(self):
        today = timezone.localdate()
        self.assertEqual(self._send(day=today), 2)
        self.assertEqual(self._send(day=today), 0)
        self.assertEqual(PhoneAlert.objects.filter(kind='brief').count(), 2)
        # a brief created on an earlier Cairo day does not block today's
        PhoneAlert.objects.filter(kind='brief').update(created_at=timezone.now() - timedelta(days=1))
        self.assertEqual(self._send(day=today), 2)

    def test_dedup_is_calendar_day_not_rolling_window(self):
        today = timezone.localdate()
        self._send(day=today)
        midnight = timezone.make_aware(datetime(today.year, today.month, today.day))
        PhoneAlert.objects.filter(kind='brief').update(created_at=midnight - timedelta(minutes=1))
        # 09:00 the next morning: the old brief is only 9 h 1 min old, but it is yesterday's
        with mock.patch.object(timezone, 'now', return_value=midnight + timedelta(hours=9)):
            self.assertEqual(self._send(day=today), 2)

    def test_one_branch_failure_does_not_stop_the_others(self):
        InsightRecipient.objects.create(name='o', wa_number='01066666666', branch=self.other,
                                        morning_brief=True)
        from apps.insights import brief
        real = brief.compose

        def flaky(branch, day):
            if branch.pk == self.branch.pk:
                raise RuntimeError('boom')
            return real(branch, day)
        with mock.patch.object(brief, 'compose', flaky):
            self.assertEqual(self._send(), 1)
        self.assertEqual(PhoneAlert.objects.get(kind='brief').phone, '201066666666')


class BriefTapTests(_Base):
    def setUp(self):
        InsightRecipient.objects.create(name='مدير', wa_number='01011111111', branch=self.branch,
                                        morning_brief=True)
        from apps.insights import brief
        with mock.patch.object(kpi_board, 'latest_complete_date', return_value=YESTERDAY):
            brief.send_all(day=TODAY)
        self.alert = PhoneAlert.objects.get(kind='brief')
        self.payload = f'brief:{self.alert.token}'

    def _tap(self, wa_id='201011111111', payload=None):
        from apps.notifications.phone_alerts import inbound
        with mock.patch.object(kpi_board, 'latest_complete_date', return_value=YESTERDAY):
            return inbound.handle_brief_tap(wa_id=wa_id, payload=payload or self.payload,
                                            context_wamid='', account=object())

    @override_settings(MORNING_BRIEF_SEND_ENABLED=True)
    def test_brief_tap_sends_full_text(self):
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as WA:
            WA.return_value.is_configured = True
            self.assertEqual(self._tap(), 'sent')
            body = WA.return_value.send_text.call_args.kwargs['body']
            self.assertEqual(WA.return_value.send_text.call_args.kwargs['wa_id'], '201011111111')
            self.assertIn('فرع الزيتون', body)
            self.assertIn('الشهر حتى الآن', body)
            self.assertEqual(self._tap(), 'sent')                      # a second tap re-sends
            self.assertEqual(WA.return_value.send_text.call_count, 2)
        self.alert.refresh_from_db()
        self.assertIsNotNone(self.alert.ack_at)
        # audit: each free-text send is an attempt (the first is the dry-run template send)
        self.assertEqual([a.result for a in self.alert.attempts.order_by('pk')],
                         ['dry_run', 'sent', 'sent'])

    @override_settings(MORNING_BRIEF_SEND_ENABLED=True)
    def test_tap_composes_for_the_alerts_own_day(self):
        old = timezone.make_aware(datetime(2026, 10, 20, 9, 0))
        PhoneAlert.objects.filter(pk=self.alert.pk).update(created_at=old)
        from apps.insights import brief
        with mock.patch('apps.whatsapp.sender.WhatsAppSender'), \
                mock.patch.object(brief, 'compose', wraps=brief.compose) as comp:
            self._tap()
        self.assertEqual(comp.call_args.args[1], date(2026, 10, 20))

    @override_settings(MORNING_BRIEF_SEND_ENABLED=True)
    def test_tap_failure_recorded(self):
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as WA:
            WA.return_value.is_configured = True
            WA.return_value.send_text.side_effect = RuntimeError('x')
            self.assertEqual(self._tap(), 'failed')
        self.assertEqual(self.alert.attempts.order_by('pk').last().result, 'failed')

    @override_settings(MORNING_BRIEF_SEND_ENABLED=True)
    def test_tap_from_other_phone_or_unknown_token_sends_nothing(self):
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as WA:
            self.assertEqual(self._tap(wa_id='201099999999'), 'wrong_sender')
            self.assertEqual(self._tap(payload='brief:nope'), 'unknown')
            self.assertEqual(self._tap(payload='alert:x:ack'), 'not_ours')
            WA.return_value.send_text.assert_not_called()

    @override_settings(MORNING_BRIEF_SEND_ENABLED=False)
    def test_tap_dry_run_when_switch_off(self):
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as WA:
            self.assertEqual(self._tap(), 'dry_run')
            WA.return_value.send_text.assert_not_called()

    def test_brief_prefix_registered(self):
        from apps.whatsapp import button_registry
        from apps.notifications.phone_alerts import inbound
        self.assertIs(button_registry._HANDLERS.get('brief:'), inbound.handle_brief_tap)


class OtherJobsTests(_Base):
    def _insight_send(self, run, account=True, switch=True):
        from apps.insights.management.commands.generate_insights import Command
        cmd = Command()
        cmd.stdout, cmd.stderr = StringIO(), StringIO()
        acct = mock.Mock() if account else None
        with override_settings(MORNING_BRIEF_SEND_ENABLED=switch), \
                mock.patch('apps.notifications.phone_alerts.sender.staff_account', return_value=acct), \
                mock.patch('apps.whatsapp.sender.WhatsAppSender') as WA:
            cmd._send(run)
        return sorted(c.kwargs['wa_id'] for c in WA.return_value.send_text.call_args_list)

    def _run(self, domain='sales', period='day'):
        run = InsightRun.objects.create(domain=domain, period_type=period, period_start=YESTERDAY,
                                        period_end=YESTERDAY)
        InsightFinding.objects.create(run=run, rule_code='r', category='volume', severity='warning',
                                      scope_type='branch', scope_key='961', message_ar='م', message_en='m')
        return run

    def _recipients(self, brief_branch=True):
        InsightRecipient.objects.create(name='brief', wa_number='201011111111',
                                        branch=self.branch if brief_branch else None, morning_brief=True)
        InsightRecipient.objects.create(name='plain', wa_number='201022222222', branch=self.branch)

    def test_insights_0730_skips_brief_recipients_only_when_brief_goes_out(self):
        self._recipients()
        run = self._run()
        self.assertEqual(self._insight_send(run), ['201022222222'])

    def test_insights_0730_switch_off_or_no_account_keeps_recipient(self):
        self._recipients()
        run = self._run()
        self.assertEqual(self._insight_send(run, switch=False), ['201011111111', '201022222222'])
        self.assertEqual(self._insight_send(run, account=False), ['201011111111', '201022222222'])

    def test_insights_0730_recipient_without_branch_keeps_report(self):
        self._recipients(brief_branch=False)
        run = self._run()
        InsightRecipient.objects.filter(name='plain').delete()
        self.assertEqual(self._insight_send(run), ['201011111111'])

    def test_insights_0730_purchasing_and_other_periods_still_go(self):
        self._recipients()
        # the purchasing daily report is not part of the brief (sales only)
        self.assertEqual(self._insight_send(self._run(domain='purchasing')),
                         ['201011111111', '201022222222'])
        self.assertEqual(self._insight_send(self._run(period='week')),
                         ['201011111111', '201022222222'])

    def test_tick_never_reminds_or_escalates_briefs(self):
        from apps.notifications.phone_alerts import jobs
        PhoneAlertPolicy.objects.filter(event='reservation_sourcing').update(
            remind_after_min=1, escalate_after_min=2)
        a = PhoneAlert.objects.create(event='reservation_sourcing', kind='brief', phone='201011111111',
                                      status='sent', source=self.branch)
        old = timezone.now() - timedelta(hours=3)
        PhoneAlert.objects.filter(pk=a.pk).update(created_at=old, last_sent_at=old)
        self.assertEqual(jobs.tick(), {'reminded': 0, 'escalated': 0, 'expired': 0})
        a.refresh_from_db()
        self.assertEqual((a.status, a.reminders_sent), ('sent', 0))

    def test_morning_brief_flag_exists_default_off(self):
        r = InsightRecipient.objects.create(name='n', wa_number='1')
        self.assertIs(r.morning_brief, False)
