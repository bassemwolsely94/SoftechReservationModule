"""
📅 SOFTECH receipt-date edit: date guard + preview → typed receipt number → apply.
SOFTECH is mocked; nothing here touches a real node.
"""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.insurance import date_service as ds
from apps.insurance import models as m
from apps.insurance import softech_guard as g

TODAY = date(2026, 11, 1)


def _codes(issues, level):
    return {i['code'] for i in issues if i['level'] == level}


class DateGuardTests(TestCase):
    def chk(self, old, new, **kw):
        return g.check_date(old=old, new=new, today=TODAY, **kw)

    def test_normal_backdate_is_clean(self):
        self.assertEqual(self.chk(date(2026, 10, 30), date(2026, 10, 24),
                                  period_from=date(2026, 10, 1), period_to=date(2026, 10, 31)), [])

    def test_blocks(self):
        self.assertIn('date_future', _codes(self.chk(date(2026, 10, 30), TODAY + timedelta(days=1)), 'block'))
        self.assertIn('date_same', _codes(self.chk(date(2026, 10, 30), date(2026, 10, 30)), 'block'))
        self.assertIn('date_far', _codes(self.chk(date(2026, 10, 30), date(2026, 8, 20)), 'block'))
        self.assertIn('date_invalid', _codes(self.chk(date(2026, 10, 30), None), 'block'))

    def test_warnings(self):
        self.assertIn('date_shift', _codes(self.chk(date(2026, 10, 30), date(2026, 10, 10)), 'warn'))
        self.assertIn('date_later', _codes(self.chk(date(2026, 10, 20), date(2026, 10, 25)), 'warn'))
        self.assertIn('date_outside_period', _codes(self.chk(
            date(2026, 10, 3), date(2026, 9, 28), period_from=date(2026, 10, 1), period_to=date(2026, 10, 31)), 'warn'))


@override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=True, WRITER_INSTANCE=True)
class DatePlanTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='d1', password='x')
        self.other = User.objects.create_user(username='d2', password='x')
        client = m.InsuranceClient.objects.create(name='ج')
        sub = m.InsuranceSubClient.objects.create(client=client, name='ف')
        self.claim = m.InsuranceClaim.objects.create(
            claim_number='MT-DG-1', subclient=sub, period_from=date(2026, 10, 1), period_to=date(2026, 10, 31))
        m.InsuranceClaimPrescription.objects.create(
            claim=self.claim, softech_docnumber='936034', softech_branchcode='160', sequence=219,
            softech_docdate=date(2026, 10, 30), patient_name='مريض')
        self.pv = mock.patch.object(ds, 'date_preview', side_effect=lambda d, b, nd, k='115': {
            'docnumber': d, 'branch': b, 'doccode': k, 'current_date': '2026-10-30',
            'new_date': nd.isoformat() if nd else '', 'branch_reachable': True, 'write_enabled': True})
        self.today = mock.patch.object(timezone, 'localdate', return_value=TODAY)
        self.pv.start(); self.today.start()
        self.addCleanup(self.pv.stop); self.addCleanup(self.today.stop)

    def _plan(self, new='2026-10-24', user=None):
        return ds.preview_date_plan(self.claim, '936034', '160', new, user=user or self.user)

    def test_preview_carries_sequence_and_is_clean(self):
        plan = self._plan()
        self.assertFalse(plan.blocked or plan.needs_reason)
        self.assertEqual(plan.preview['sequence'], 219)

    def test_typed_receipt_number_required_and_applied_once(self):
        plan = self._plan()
        with mock.patch.object(ds, 'apply_date_edit', return_value={'run_id': 1, 'old_date': '2026-10-30',
                                                                     'new_date': '2026-10-24'}) as ap:
            for bad in ('', '936035', '1'):
                with self.assertRaises(ds.RepriceError):
                    ds.apply_date_plan(plan, user=self.user, confirm_text=bad)
            ds.apply_date_plan(plan, user=self.user, confirm_text='#936034')
            self.assertEqual(ap.call_args.kwargs['expected_old'], '2026-10-30')
            with self.assertRaises(ds.RepriceError):
                ds.apply_date_plan(plan, user=self.user, confirm_text='936034')
        self.assertEqual(ap.call_count, 1)

    def test_future_date_blocked_and_other_user_refused(self):
        with mock.patch.object(ds, 'apply_date_edit') as ap:
            with self.assertRaises(ds.RepriceError):
                ds.apply_date_plan(self._plan('2026-11-05'), user=self.user, confirm_text='936034')
            with self.assertRaises(ds.RepriceError):
                ds.apply_date_plan(self._plan(), user=self.other, confirm_text='936034')
        ap.assert_not_called()

    def test_warning_needs_reason(self):
        plan = self._plan('2026-10-10')          # 20 days back → warn
        self.assertTrue(plan.needs_reason and not plan.blocked)
        with mock.patch.object(ds, 'apply_date_edit', return_value={'run_id': 1, 'old_date': 'a', 'new_date': 'b'}) as ap:
            with self.assertRaises(ds.RepriceError):
                ds.apply_date_plan(plan, user=self.user, confirm_text='936034', reason='x')
            ds.apply_date_plan(plan, user=self.user, confirm_text='936034', reason='تاريخ الروشتة الفعلى')
        self.assertEqual(ap.call_args.kwargs['reason'], 'تاريخ الروشتة الفعلى')

    def test_open_edit_on_receipt_blocks_preview(self):
        m.SoftechDateEditRun.objects.create(docnumber='936034', branchcode='160', doccode='115',
                                            old_date=date(2026, 10, 30), new_date=date(2026, 10, 25),
                                            nodes=['HQ', '160'], status=m.SoftechDateEditRun.STATUS_APPLIED)
        self.assertIn('date_open', _codes(self._plan().preview['issues'], 'block'))


@override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=True, WRITER_INSTANCE=True)
class ApplyDateLastLineTests(TestCase):
    """apply_date_edit re-checks the live date, whatever path calls it."""

    def setUp(self):
        self.hq = mock.MagicMock()
        for p in (mock.patch.object(ds, '_hq_conn', return_value=self.hq),
                  mock.patch.object(ds, '_open_branch'),
                  mock.patch.object(ds, '_read_docdate', return_value=date(2026, 10, 30)),
                  mock.patch.object(timezone, 'localdate', return_value=TODAY)):
            p.start(); self.addCleanup(p.stop)

    def _wrote(self):
        return any('UPDATE' in str(c.args[0]) for c in self.hq.cursor.return_value.execute.call_args_list)

    def test_future_date_refused_before_write(self):
        with self.assertRaises(ds.RepriceError):
            ds.apply_date_edit(None, '936034', '160', '2026-12-01', confirm=True)
        self.assertFalse(self._wrote())
        self.assertFalse(m.SoftechDateEditRun.objects.exists())

    def test_changed_since_preview_refused(self):
        with self.assertRaises(ds.RepriceError) as cm:
            ds.apply_date_edit(None, '936034', '160', '2026-10-24', confirm=True, expected_old='2026-10-29')
        self.assertIn('تغيّر', str(cm.exception))
        self.assertFalse(self._wrote())
