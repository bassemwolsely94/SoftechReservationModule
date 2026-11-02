"""
SOFTECH re-price guard + plan flow (preview → typed confirmation → apply).

Motivating incident (2026-11-01): receipt number 931120 typed as the price of item
111062 on receipt #931120 → written to SOFTECH at 931,120 (+772,692.65).
SOFTECH is mocked throughout — nothing here touches a real node.
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.insurance import models as m
from apps.insurance import reprice_service as rs
from apps.insurance import softech_guard as g


def _issues(**kw):
    base = dict(docno='931120', new_prices={'111062': '240'}, softech_prices={'111062': Decimal('165')},
                claim_prices={'111062': Decimal('240')}, catalog_prices={'111062': Decimal('240')},
                net_delta=Decimal('62'), known_numbers={'931120', '930995'})
    base.update(kw)
    return g.check_receipt(**base)


def _codes(issues, level):
    return {i['code'] for i in issues if i['level'] == level}


class GuardRuleTests(TestCase):
    def test_correct_price_matching_claim_passes_clean(self):
        self.assertEqual(_issues(), [])

    def test_receipt_number_typed_as_price_is_blocked(self):
        iss = _issues(new_prices={'111062': '931120'}, net_delta=Decimal('772692.65'))
        self.assertIn('looks_like_id', _codes(iss, 'block'))
        self.assertIn('hard_ratio', _codes(iss, 'block'))
        self.assertIn('receipt_delta', _codes(iss, 'block'))

    def test_other_claim_receipt_number_is_blocked(self):
        self.assertIn('looks_like_id', _codes(_issues(new_prices={'111062': '930995'}), 'block'))

    def test_double_price_blocked_unless_it_matches_our_reference(self):
        off = _issues(new_prices={'111062': '400'}, claim_prices={}, catalog_prices={})
        self.assertIn('ratio', _codes(off, 'block'))
        ok = _issues(new_prices={'111062': '400'}, claim_prices={'111062': Decimal('400')})
        self.assertNotIn('ratio', _codes(ok, 'block'))
        self.assertIn('big_ratio', _codes(ok, 'warn'))

    def test_price_off_reference_needs_reason(self):
        iss = _issues(new_prices={'111062': '200'})
        self.assertEqual(_codes(iss, 'block'), set())
        self.assertIn('off_reference', _codes(iss, 'warn'))

    def test_decrease_warns(self):
        self.assertIn('decrease', _codes(_issues(new_prices={'111062': '150'},
                                                 claim_prices={'111062': Decimal('150')}), 'warn'))

    def test_item_not_on_receipt_blocked(self):
        self.assertIn('not_on_receipt', _codes(_issues(new_prices={'999999': '50'}), 'block'))

    def test_invalid_and_zero_prices_blocked(self):
        for bad in ('0', '-5', 'abc', '12.345'):
            iss = _issues(new_prices={'111062': bad})
            self.assertTrue(_codes(iss, 'block'), bad)

    def test_receipt_and_plan_delta_thresholds(self):
        self.assertIn('receipt_delta', _codes(_issues(net_delta=Decimal('600')), 'warn'))
        self.assertIn('receipt_delta', _codes(_issues(net_delta=Decimal('3500')), 'block'))
        self.assertEqual(g.check_plan_total(Decimal('1999')), [])
        self.assertEqual(g.check_plan_total(Decimal('-2500'))[0]['level'], 'warn')

    def test_reason_length(self):
        self.assertFalse(g.reason_ok('ok'))
        self.assertTrue(g.reason_ok('سعر الكتالوج الجديد'))


# ── plan flow with SOFTECH mocked ────────────────────────────────────────────

def _line(code, price, qty='1'):
    p = Decimal(price)
    return {'itemcode': code, 'transqty': Decimal(qty), 'itemsaleprice': p, 'itemsaleprice_tax': p,
            'itemsalestax': Decimal('0'), 'transprice': p * Decimal('0.83'),
            'transprice_total': p * Decimal('0.83') * Decimal(qty), 'additionaldiscp': Decimal('0'),
            'custdiscp': Decimal('17'), 'newcostprice': Decimal('0'), 'bonusqty': Decimal('0'),
            'dblitemflag': Decimal('1')}


RECEIPTS = {
    ('931120', '160'): ([_line('111062', '165')],
                        {'docvalue': Decimal('2435.63'), 'docvalue1': Decimal('2851'),
                         'docvalue2': Decimal('0'), 'docvalue3': Decimal('0'), 'cust_branch_code': '4227',
                         'trans_time': None}),
    ('930593', '160'): ([_line('80052', '200'), _line('124793', '700')],
                        {'docvalue': Decimal('747'), 'docvalue1': Decimal('900'),
                         'docvalue2': Decimal('0'), 'docvalue3': Decimal('0'), 'cust_branch_code': '4227',
                         'trans_time': None}),
}


def _fake_read(cur, docno, branch, doccode):
    return RECEIPTS.get((str(docno), str(branch)), ([], None))


@override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=True, WRITER_INSTANCE=True)
class PlanFlowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='p1', password='x', is_staff=True, is_superuser=True)
        self.other = User.objects.create_user(username='p2', password='x', is_staff=True, is_superuser=True)
        client = m.InsuranceClient.objects.create(name='جنوب')
        sub = m.InsuranceSubClient.objects.create(client=client, name='العاملين')
        self.claim = m.InsuranceClaim.objects.create(
            claim_number='MT-PG-1', subclient=sub, period_from=date(2026, 10, 1),
            period_to=date(2026, 10, 31))
        for (d, b), (lines, _h) in RECEIPTS.items():
            rx = m.InsuranceClaimPrescription.objects.create(
                claim=self.claim, softech_docnumber=d, softech_branchcode=b, patient_name='مريض',
                softech_docdate=date(2026, 10, 3))
            for ln in lines:
                price = {'111062': '240', '80052': '210', '124793': '770'}[ln['itemcode']]
                m.InsuranceClaimLine.objects.create(prescription=rx, softech_itemcode=ln['itemcode'],
                                                    item_name='صنف', unit_price=price)
        self.p_conn = mock.patch('apps.insurance.importer._get_connection')
        self.p_read = mock.patch.object(rs, '_read_receipt', side_effect=_fake_read)
        self.p_conn.start(); self.p_read.start()
        self.addCleanup(self.p_conn.stop); self.addCleanup(self.p_read.stop)

    def _preview(self, receipts, user=None):
        return rs.preview_plan(self.claim, receipts, user=user or self.user, source='item')

    def test_preview_groups_items_of_one_receipt_and_is_clean(self):
        plan = self._preview([{'docno': '930593', 'branch': '160', 'prices': {'80052': '210'}},
                              {'docno': '930593', 'branch': '160', 'prices': {'124793': '770'}}])
        self.assertEqual(plan.receipt_count, 1)
        self.assertEqual(plan.plan[0]['prices'], {'80052': '210', '124793': '770'})
        self.assertFalse(plan.blocked)

    def test_receipt_number_as_price_blocks_the_plan_and_apply(self):
        plan = self._preview([{'docno': '931120', 'branch': '160', 'prices': {'111062': '931120'}}])
        self.assertTrue(plan.blocked)
        with mock.patch.object(rs, 'apply_reprice') as ar:
            with self.assertRaises(rs.RepriceError):
                rs.apply_plan(plan, user=self.user, confirm_count=1)
        ar.assert_not_called()

    def _ok_plan(self):
        plan = self._preview([{'docno': '931120', 'branch': '160', 'prices': {'111062': '240'}}])
        self.assertFalse(plan.blocked, plan.preview)
        return plan

    def test_wrong_typed_count_refused(self):
        plan = self._ok_plan()
        with mock.patch.object(rs, 'apply_reprice') as ar:
            for typed in (None, '', '2', '0'):
                with self.assertRaises(rs.RepriceError):
                    rs.apply_plan(plan, user=self.user, confirm_count=typed)
        ar.assert_not_called()

    def test_apply_once_only_and_runs_carry_preview_snapshot(self):
        plan = self._ok_plan()
        with mock.patch.object(rs, 'apply_reprice', return_value={'run_id': 1, 'net_delta': '62'}) as ar:
            res = rs.apply_plan(plan, user=self.user, confirm_count='1')
            self.assertEqual(res['applied'], 1)
            self.assertEqual(ar.call_args.kwargs['expected_docvalue'], '2435.63')
            with self.assertRaises(rs.RepriceError):
                rs.apply_plan(plan, user=self.user, confirm_count='1')
        self.assertEqual(ar.call_count, 1)

    def test_expired_preview_refused(self):
        plan = self._ok_plan()
        m.SoftechWritePlan.objects.filter(pk=plan.pk).update(
            created_at=timezone.now() - timedelta(seconds=g.PREVIEW_TTL_SECONDS + 5))
        plan.refresh_from_db()
        with self.assertRaises(rs.RepriceError):
            rs.apply_plan(plan, user=self.user, confirm_count='1')

    def test_other_user_cannot_apply_my_preview(self):
        plan = self._ok_plan()
        with self.assertRaises(rs.RepriceError):
            rs.apply_plan(plan, user=self.other, confirm_count='1')

    def test_warning_needs_reason(self):
        plan = self._preview([{'docno': '931120', 'branch': '160', 'prices': {'111062': '200'}}])
        self.assertTrue(plan.needs_reason and not plan.blocked)
        with mock.patch.object(rs, 'apply_reprice', return_value={'run_id': 1, 'net_delta': '29'}) as ar:
            with self.assertRaises(rs.RepriceError):
                rs.apply_plan(plan, user=self.user, confirm_count='1', reason='x')
            rs.apply_plan(plan, user=self.user, confirm_count='1', reason='سعر متفق عليه مع الشركة')
        self.assertEqual(ar.call_args.kwargs['reason'], 'سعر متفق عليه مع الشركة')

    def test_non_draft_claim_refused(self):
        plan = self._ok_plan()
        self.claim.status = m.InsuranceClaim.STATUS_SUBMITTED
        self.claim.save(update_fields=['status'])
        plan.refresh_from_db()
        with self.assertRaises(rs.RepriceError):
            rs.apply_plan(plan, user=self.user, confirm_count='1')


@override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=True, WRITER_INSTANCE=True)
class ApplyRepriceLastLineTests(TestCase):
    """apply_reprice itself re-checks the live receipt, whatever path calls it."""

    def setUp(self):
        client = m.InsuranceClient.objects.create(name='ج')
        sub = m.InsuranceSubClient.objects.create(client=client, name='ف')
        self.claim = m.InsuranceClaim.objects.create(claim_number='MT-PG-2', subclient=sub,
                                                     period_from=date(2026, 10, 1), period_to=date(2026, 10, 31))
        rx = m.InsuranceClaimPrescription.objects.create(claim=self.claim, softech_docnumber='931120',
                                                         softech_branchcode='160',
                                                         softech_docdate=date(2026, 10, 3))
        m.InsuranceClaimLine.objects.create(prescription=rx, softech_itemcode='111062', unit_price='240')
        self.hq, self.br = mock.MagicMock(), mock.MagicMock()
        patches = [
            mock.patch.object(rs, 'build_preview', return_value={
                'branch_consistency': {'reachable': True}, 'cust_branch_code': '4227', 'net_delta': '0'}),
            mock.patch.object(rs, '_hq_conn', return_value=self.hq),
            mock.patch.object(rs, '_open_branch', return_value=self.br),
            mock.patch.object(rs, '_read_receipt', side_effect=_fake_read),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def _wrote(self):
        sql = [str(c.args[0]) for conn in (self.hq, self.br)
               for c in conn.cursor.return_value.execute.call_args_list]
        return any('UPDATE' in q for q in sql)

    def test_receipt_number_price_refused_before_any_write(self):
        with self.assertRaises(rs.RepriceError) as cm:
            rs.apply_reprice(self.claim, '931120', '160', {'111062': '931120'}, confirm=True)
        self.assertIn('مرفوض', str(cm.exception))
        self.assertFalse(self._wrote())
        self.assertFalse(m.SoftechRepriceRun.objects.exists())

    def test_changed_since_preview_refused(self):
        with self.assertRaises(rs.RepriceError) as cm:
            rs.apply_reprice(self.claim, '931120', '160', {'111062': '240'}, confirm=True,
                             expected_docvalue='2400.00')
        self.assertIn('تغيّر', str(cm.exception))
        self.assertFalse(self._wrote())

    def test_warning_without_reason_refused(self):
        with self.assertRaises(rs.RepriceError) as cm:
            rs.apply_reprice(self.claim, '931120', '160', {'111062': '200'}, confirm=True)
        self.assertIn('سبب', str(cm.exception))
        self.assertFalse(self._wrote())
