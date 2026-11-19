"""Top-10 C02: the «اليوم» section of the branch morning brief (and the /me widget) — return-window
lots to send to HQ, slow stock to move, near-expiry stock to rescue. Built from existing engines only."""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from apps.tests.test_return_window import _entry, _seed_policies, _stock

D = dt.date
TODAY = D(2027, 1, 5)          # 565's window for a 2026-12 expiry closes 2027-01-31 → «تُغلق هذا الشهر»


class Base(TestCase):

    def setUp(self):
        from apps.catalog.models import Item
        from apps.tests.factories import make_branch
        self.hq = make_branch('الرئيسي', '100')
        self.b130 = make_branch('فرع 130', '130')
        self.b140 = make_branch('فرع 140', '140')
        for code, name in (('A', 'صنف أ'), ('B', 'صنف ب'), ('C', 'صنف ج'), ('M', 'صنف راكد')):
            Item.objects.create(softech_id=code, name=name, cost_price=Decimal('10'))
        _seed_policies()

    def acts(self, branch=None):
        from apps.insights import today
        return today.actions(branch or self.b130, TODAY)

    def snapshot(self, *lines):
        from apps.catalog.models import Item
        from apps.purchasing.models import DeadStockLine, DeadStockSnapshot, DemandCalculationRun
        run = DemandCalculationRun.objects.create(status='success')
        snap = DeadStockSnapshot.objects.create(run=run, as_of=TODAY)
        for n, (item, branch, lane, targets, move_value, flags) in enumerate(lines):
            DeadStockLine.objects.create(snapshot=snap, item=Item.objects.get(softech_id=item), branch_code=branch,
                                         lane=lane, location='branches_only', qty=Decimal('5'), value=Decimal('50'),
                                         targets=targets, move_value=Decimal(move_value), flags=flags, rank=n)
        return snap


class ActionsTests(Base):

    def test_return_lot_closing_this_month_with_send_by(self):
        _entry('A', '565', D(2026, 12, 15))
        _stock('A', exp=D(2026, 12, 15), qty='3')
        r = self.acts()['returns']
        self.assertEqual([(x['item_code'], x['send_by'], x['value'], x['late']) for x in r],
                         [('A', '2027-01-17', 30.0, False)])                      # closes 01-31 − 14 days

    def test_moves_out_skip_small_conflicting_and_targetless(self):
        snap = self.snapshot(('M', '130', 'move', [{'branch': '140', 'qty': 4}], '400', {}),
                             ('A', '130', 'move', [{'branch': '140', 'qty': 1}], '50', {'below_threshold': True}),
                             ('B', '130', 'move', [{'branch': '140', 'qty': 2}], '300', {'conflict': 'TR-9'}),
                             ('C', '130', 'move', [], '0', {}),
                             ('C', '140', 'move', [{'branch': '130', 'qty': 2}], '200', {}))   # another branch
        with mock.patch('apps.purchasing.dead_stock.latest_snapshot', return_value=snap):
            m = self.acts()['moves']
        self.assertEqual([(x['item_code'], x['targets'], x['value']) for x in m],
                         [('M', [{'branch': 'فرع 140', 'qty': 4}], 400.0)])

    def test_rescue_within_60_days_not_expired_not_already_a_return(self):
        _entry('A', '565', D(2026, 12, 15))
        _stock('A', exp=D(2026, 12, 15), qty='3')                 # listed as a return → not rescue
        _stock('B', exp=D(2027, 2, 1), qty='20', batch='L2')      # 27 days → rescue, value 200
        _stock('C', exp=D(2027, 1, 20), qty='1', batch='L3')      # rescue, value 10
        _stock('C', exp=D(2027, 6, 1), qty='9', batch='L4')       # too far
        _stock('C', exp=D(2027, 1, 1), qty='9', batch='L5')       # already expired
        r = self.acts()['rescue']
        self.assertEqual([(x['item_code'], x['expiry'], x['value']) for x in r],
                         [('B', '2027-02-01', 200.0), ('C', '2027-01-20', 10.0)])

    def test_closed_branch_gets_nothing(self):
        from apps.branches.models import Branch
        _stock('B', branch='140', exp=D(2027, 2, 1), qty='20')
        Branch.objects.filter(pk=self.b140.pk).update(kind=Branch.KIND_CLOSED)
        self.b140.refresh_from_db()
        self.assertEqual(self.acts(self.b140), {'returns': [], 'moves': [], 'rescue': []})


class TextTests(Base):

    def test_lines_cap_late_and_totals(self):
        from apps.insights import today
        acts = {'returns': [{'item': 'صنف أ', 'qty': 3, 'send_by': '2027-01-01', 'supplier': 'PHARMA',
                             'value': 30.0, 'late': True}],
                'moves': [],
                'rescue': [{'item': f'صنف {i}', 'qty': 1, 'expiry': '2027-02-01', 'value': 100.0} for i in range(5)]}
        text = '\n'.join(today.lines(acts))
        self.assertTrue(text.startswith('*اليوم*'))
        self.assertIn('متأخر (كان قبل 2027-01-01) أرسل الآن', text)
        self.assertIn('ينتهي خلال 60 يوم — بِع أو انقل — 5 (500 ج.م)', text)
        self.assertIn('+2 أخرى', text)                 # 3 lines shown of 5
        self.assertNotIn('راكد', text)                  # empty part left out

    def test_nothing_to_do_means_no_section(self):
        from apps.insights import today
        self.assertEqual(today.lines({'returns': [], 'moves': [], 'rescue': []}), [])


class BriefTests(Base):

    def test_compose_puts_today_first_and_survives_a_failure(self):
        from apps.forecasting import kpi_board
        from apps.insights import brief
        _stock('B', exp=D(2027, 2, 1), qty='20')
        with mock.patch.object(kpi_board, 'latest_complete_date', return_value=TODAY - dt.timedelta(days=1)):
            t = brief.compose(self.b130, TODAY).text
            self.assertLess(t.index('*اليوم*'), t.index('*أمس*'))
            # the lot's name comes from the stock-expiry mirror (SOFTECH's item name); the fixture stores the code
            self.assertIn('• B — كمية 20 — ينتهي 2027-02-01 (200 ج.م)', t)
            with mock.patch('apps.insights.today.actions', side_effect=RuntimeError('boom')):
                t2 = brief.compose(self.b130, TODAY).text
        self.assertNotIn('*اليوم*', t2)
        self.assertIn('*أمس*', t2)

    @override_settings(MORNING_BRIEF_SEND_ENABLED=False)
    def test_send_still_follows_its_switch(self):
        """The section changes the text only — with the switch off nothing leaves (dry run)."""
        from apps.insights import brief
        from apps.insights.models import InsightRecipient
        from apps.notifications.phone_alerts.models import PhoneAlert
        from apps.forecasting import kpi_board
        InsightRecipient.objects.create(name='مدير', wa_number='01011111111', branch=self.b130, morning_brief=True)
        _stock('B', exp=D(2027, 2, 1), qty='20')
        with mock.patch.object(kpi_board, 'latest_complete_date', return_value=TODAY - dt.timedelta(days=1)):
            brief.send_all(day=TODAY)
        alerts = PhoneAlert.objects.filter(kind='brief')
        self.assertTrue(alerts.exists())
        for a in alerts:
            self.assertEqual([x.result for x in a.attempts.all()], ['dry_run'])


class WidgetTests(Base):

    def test_branch_today_widget_is_own_branch_only(self):
        from apps.tests.factories import make_user
        from apps.personal.models import PersonalWidget
        _stock('B', exp=D(2027, 2, 1), qty='20')
        _stock('C', branch='140', exp=D(2027, 2, 1), qty='20', batch='L9')
        _, staff, client = make_user('c02_pharm', role='pharmacist', branch=self.b130)
        w = PersonalWidget.objects.create(staff=staff, widget_type='branch_today')
        with mock.patch('django.utils.timezone.localdate', return_value=TODAY):
            r = client.get(f'/api/personal/widgets/{w.pk}/data/', {'refresh': '1'})
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()['data'] if 'data' in r.json() else r.json()
        self.assertEqual([x['item_code'] for x in data['rescue']], ['B'])          # not branch 140's C
        self.assertEqual(data['totals']['rescue'], 200.0)
