"""
Doc 25 Phase 1 — live بدل workflow: rules, per-employee authorization, maker-checker, locking,
optimistic versioning, anti-splitting approval routing, legs through the EXISTING writers,
idempotency, post-write verification, and the live case ↔ nightly reconstruction hand-off.
No test can reach SOFTECH: REPLACEMENT_POSTING_ENABLED is forced off under `manage.py test` and
the writers are mocked where a "live" post is exercised.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.replacement import legs as LG
from apps.replacement import rules as RULES
from apps.replacement import workflow as W
from apps.replacement.models import (CaseException as X, EntitlementLedgerEntry as E, PostingOperation as Op,
                                     ReplacementCase as RC, ReplacementGrant, ReplacementItem)

from .factories import make_user

D = Decimal
PIC = '130HD16564'


# Routing scenarios below are written against explicit 2,000 / 6,000 limits; the owner's real
# limits (500 / 500) are covered by OwnerDecisionTests.
@override_settings(REPLACEMENT_APPROVAL_AUTO_MAX=D('2000'), REPLACEMENT_APPROVAL_MANAGER_ABOVE=D('6000'))
class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.branches.models import Branch
        from apps.catalog.models import Item
        from apps.customers.models import Customer
        call_command('seed_replacement', verbosity=0)
        cls.branch = Branch.objects.create(softech_branch_id='130', name='النزهة', name_ar='النزهة')
        cls.other = Branch.objects.create(softech_branch_id='140', name='B140')
        cls.lokelma = Item.objects.create(softech_id='100186', name='LOKELMA 5MG', pack_price=D('8027'), is_active=True)
        cls.cream = Item.objects.create(softech_id='200001', name='CREAM', pack_price=D('300'), is_active=True)
        cls.small = Item.objects.create(softech_id='200002', name='VIT', pack_price=D('1000'), is_active=True)
        Customer.objects.create(softech_pic=PIC, name='محمد صالح سمره', phone='0100')

    def setUp(self):
        _, self.maker, self.maker_api = make_user('maker', role='pharmacist', branch=self.branch)
        _, self.sup, self.sup_api = make_user('sup130', role='supervisor', branch=self.branch)
        _, self.sup2, _ = make_user('sup140', role='supervisor', branch=self.other)
        _, self.admin, self.admin_api = make_user('boss', role='admin', access_all=True)

    def new_case(self, item=None, qty=1, mode='products', shortage=False, source='insurance_rx', user=None):
        return W.create_case(user=user or self.maker, branch=self.branch, source_type=source,
                             settlement_mode=mode, softech_pic=PIC, contract_personcode='4479',
                             items=[{'item_id': (item or self.lokelma).pk, 'qty': qty}], is_shortage_item=shortage)

    def calc(self, case, user=None, **kw):
        return W.calculate(case.pk, user=user or self.maker, version=RC.objects.get(pk=case.pk).version, **kw)

    def submit(self, case, user=None):
        return W.submit(case.pk, user=user or self.maker, version=RC.objects.get(pk=case.pk).version)


# ═══════════════════════════════════════════════════════════════════════════════
class RuleAndCalculationTests(_Base):
    def test_products_rule_30pct_on_4471_per_unit_exact(self):
        c = self.calc(self.new_case())
        self.assertEqual(c.status, RC.STATUS_CALCULATED)
        self.assertEqual(c.supplier_personcode, '4471')
        self.assertEqual(c.applied_deduction_pct, D('30.00'))
        self.assertEqual(c.entitlement, D('5618.90'))            # 8027 × 0.70
        self.assertEqual(c.current_calc.lines[0]['unit_net'], '5618.900')
        self.assertTrue(AuditLog.objects.filter(action='replacement_case_calculated', object_id=str(c.pk)).exists())

    def test_shortage_cash_and_external_rules(self):
        self.assertEqual(self.calc(self.new_case(shortage=True)).supplier_personcode, '4472')     # 25 %
        self.assertEqual(self.calc(self.new_case(mode='cash')).entitlement, D('4816.20'))       # 40 % → 4470
        e = self.calc(self.new_case(source='insurance_external', mode='cash'))
        self.assertEqual((e.supplier_personcode, e.applied_deduction_pct), ('4469', D('50.00')))

    def test_b2_rules_owner_rates(self):
        p = self.calc(self.new_case(item=self.small, source='client_buyback'))
        self.assertEqual((p.supplier_personcode, p.applied_deduction_pct, p.entitlement), ('3068', D('40.00'), D('600.00')))
        c = self.calc(self.new_case(item=self.small, source='client_buyback', mode='cash'))
        self.assertEqual((c.supplier_personcode, c.applied_deduction_pct, c.entitlement), ('4069', D('50.00'), D('500.00')))

    def test_rounding_down_is_absorbed_by_the_largest_line(self):
        res = RULES.compute([{'itemcode': 'a', 'qty': '3', 'public_price': '333.33'},
                             {'itemcode': 'b', 'qty': '1', 'public_price': '100'}], D('30'), 'floor_50')
        self.assertEqual(res['entitlement'] % 50, 0)
        posted = sum(D(l['unit_net']) * D(l['qty']) for l in res['lines'])
        self.assertEqual(posted.quantize(D('0.01')), res['entitlement'])   # exactly what the purchase will carry

    def test_rule_new_version_does_not_change_existing_calculation(self):
        from apps.replacement.models import ReplacementRule
        c = self.calc(self.new_case())
        old = ReplacementRule.objects.get(rule_key='A_PRODUCTS', version=1)
        ReplacementRule.objects.create(rule_key='A_PRODUCTS', version=2, name='v2', source_type=old.source_type,
                                       settlement_mode='products', deduction_pct=D('35'), supplier_personcode='4471',
                                       effective_from=date(2025, 1, 1))
        c.refresh_from_db()
        self.assertEqual(c.current_calc.rule.version, 1)
        self.assertEqual(c.entitlement, D('5618.90'))
        self.assertEqual(self.calc(self.new_case()).current_calc.rule.version, 2)       # new cases use v2

    def test_override_limits_reason_and_grant(self):
        case = self.new_case()
        with self.assertRaises(ValidationError):                 # reason required
            self.calc(case, override_pct=D('28'))
        with self.assertRaises(ValidationError):                 # pharmacist may lower 0 pp
            self.calc(case, override_pct=D('28'), override_reason='rounding')
        ReplacementGrant.objects.create(staff=self.maker, max_override_pp=D('2'))
        c = self.calc(case, override_pct=D('28'), override_reason='تقريب')
        self.assertEqual(c.applied_deduction_pct, D('28.00'))
        self.assertEqual(self.calc(case, override_pct=D('45'), override_reason='x').applied_deduction_pct,
                         D('45.00'))                              # pharmacy-favourable always allowed

    def test_snapshot_is_immutable(self):
        c = self.calc(self.new_case())
        snap = c.current_calc
        snap.entitlement = D('1')
        with self.assertRaises(ValidationError):
            snap.save()


# ═══════════════════════════════════════════════════════════════════════════════
class AuthorizationTests(_Base):
    def test_roles_and_branch_scope(self):
        _, sales, _ = make_user('sales1', role='salesperson', branch=self.branch)
        with self.assertRaises(PermissionDenied):
            self.new_case(user=sales)
        _, ph140, _ = make_user('ph140', role='pharmacist', branch=self.other)
        case = self.new_case()
        with self.assertRaises(PermissionDenied):                  # other branch
            W.calculate(case.pk, user=ph140, version=case.version)

    def test_grant_restricts_sources_and_case_size(self):
        ReplacementGrant.objects.create(staff=self.maker, allowed_sources=['insurance_rx'],
                                        max_case_entitlement=D('1000'))
        with self.assertRaises(PermissionDenied):
            self.new_case(source='insurance_external')
        with self.assertRaises(PermissionDenied):                  # 5,618.90 > 1,000
            self.calc(self.new_case())
        ReplacementGrant.objects.filter(staff=self.maker).update(can_create=False)
        from apps.users.models import StaffProfile
        fresh = StaffProfile.objects.get(pk=self.maker.pk)            # each request loads a fresh profile
        with self.assertRaises(PermissionDenied):
            self.new_case(item=self.small, user=fresh)


# ═══════════════════════════════════════════════════════════════════════════════
class ApprovalAndLockingTests(_Base):
    def test_small_products_case_auto_approves_and_locks(self):
        c = self.submit(self.calc(self.new_case(item=self.small)))     # 700 ≤ 2000
        self.assertEqual(c.status, RC.STATUS_APPROVED)
        self.assertIsNotNone(c.locked_at)
        with self.assertRaises(ValidationError):
            W.set_items(c.pk, user=self.maker, version=c.version, items=[{'item_id': self.cream.pk, 'qty': 1}])

    def test_large_case_goes_to_supervisor_with_maker_checker(self):
        c = self.submit(self.calc(self.new_case()))
        self.assertEqual(c.status, RC.STATUS_AWAITING_APPROVAL)
        self.assertEqual(c.approval_request.workflow.code, 'replacement_supervisor')
        with self.assertRaises(PermissionDenied):                     # creator can't approve (role too)
            W.decide(c.pk, user=self.maker, version=c.version, approve=True)
        with self.assertRaises(PermissionDenied):                     # other-branch supervisor not eligible
            W.decide(c.pk, user=self.sup2, version=c.version, approve=True)
        c = W.decide(c.pk, user=self.sup, version=c.version, approve=True, note='ok')
        self.assertEqual(c.status, RC.STATUS_APPROVED)
        self.assertEqual(c.approved_by, self.sup)

    def test_self_approval_through_generic_inbox_is_refused(self):
        from apps.approvals.models import ApprovalDecision
        from apps.approvals.service import ApprovalService
        c = W.create_case(user=self.sup, branch=self.branch, source_type='insurance_rx', settlement_mode='products',
                          softech_pic=PIC, contract_personcode='4479', items=[{'item_id': self.lokelma.pk, 'qty': 1}])
        c = self.submit(self.calc(c, user=self.sup), user=self.sup)
        ApprovalService.decide(request=c.approval_request, decision=ApprovalDecision.DECISION_APPROVED,
                               decided_by=self.sup)                 # the approvals app itself allows this…
        c.refresh_from_db()
        self.assertNotEqual(c.status, RC.STATUS_APPROVED)           # …the case does not
        self.assertTrue(c.exceptions.filter(exception_type='self_approval', severity='high').exists())

    def test_reject_returns_to_maker_unlocked(self):
        c = self.submit(self.calc(self.new_case()))
        with self.assertRaises(ValidationError):
            W.decide(c.pk, user=self.sup, version=c.version, approve=False)       # reason required
        c = W.decide(c.pk, user=self.sup, version=c.version, approve=False, note='صورة الروشتة ناقصة')
        self.assertEqual(c.status, RC.STATUS_CALCULATED)
        self.assertIsNone(c.locked_at)

    def test_cash_always_needs_approval_and_big_goes_to_manager(self):
        c = self.submit(self.calc(self.new_case(item=self.small, mode='cash')))
        self.assertEqual(c.status, RC.STATUS_AWAITING_APPROVAL)
        big = self.submit(self.calc(self.new_case(qty=2)))             # 11,237.80 > 6,000
        self.assertEqual(big.approval_request.workflow.code, 'replacement_manager')

    def test_threshold_splitting_is_aggregated_per_patient(self):
        first = self.submit(self.calc(self.new_case(item=self.small, qty=2)))    # 1,400 → auto
        self.assertEqual(first.status, RC.STATUS_APPROVED)
        second = self.submit(self.calc(self.new_case(item=self.small, qty=1)))   # 700 alone, 2,100 rolling
        self.assertEqual(second.status, RC.STATUS_AWAITING_APPROVAL)
        self.assertIn('إجمالي أرصدة المريض', ' '.join(second.approval_request.context_data['reasons']))

    def test_stale_version_conflict(self):
        c = self.calc(self.new_case())
        with self.assertRaises(W.StaleVersion):
            W.calculate(c.pk, user=self.maker, version=c.version - 1)

    def test_cancel_withdraws_pending_approval(self):
        c = self.submit(self.calc(self.new_case()))
        req = c.approval_request
        W.cancel(c.pk, user=self.maker, version=c.version, reason='المريض تراجع')
        req.refresh_from_db()
        self.assertEqual(req.status, 'cancelled')

    def test_reopen_and_cancel_only_before_posting(self):
        c = self.submit(self.calc(self.new_case(item=self.small)))
        c = W.reopen(c.pk, user=self.sup, version=c.version, reason='تصحيح الكمية')
        self.assertEqual((c.status, c.locked_at), (RC.STATUS_DRAFT, None))
        c = W.cancel(c.pk, user=self.maker, version=c.version, reason='المريض عدل')
        self.assertEqual(c.status, RC.STATUS_CANCELLED)


# ═══════════════════════════════════════════════════════════════════════════════
def _fake_push_final(docnumber=12500, tamper=None):
    def push(invoice, *, dry_run=True, force=False):
        from django.utils import timezone
        if dry_run:
            return {'mode': 'dry_run', 'wrote_to_softech': False, 'plan': {'ok': True}}
        if tamper:
            tamper(invoice)
        invoice.status, invoice.softech_docnumber = 'finalized', docnumber
        invoice.softech_docdate, invoice.erp_readback = timezone.localdate(), {'ok': True}
        invoice.save()
        return {'mode': 'commit', 'wrote_to_softech': True, 'ok': True, 'docnumber': docnumber}
    return push


class LegTests(_Base):
    def approved(self, **kw):
        c = self.submit(self.calc(self.new_case(**kw)))
        if c.status != RC.STATUS_APPROVED:
            c = W.decide(c.pk, user=self.sup, version=c.version, approve=True)
        return c

    def test_prepare_purchase_builds_exact_invoice_and_is_idempotent(self):
        c = self.approved()
        op = LG.prepare_purchase(c.pk, user=self.sup, version=c.version)
        inv = op.supplier_invoice
        self.assertEqual(inv.vendor.softech_personcode, '4471')
        self.assertEqual(inv.invoice_number, f'9{c.pk:07d}')
        line = inv.lines.get()
        self.assertEqual((line.unit_price, line.quantity, line.public_price), (D('5618.900'), D('1'), D('8027')))
        again = LG.prepare_purchase(c.pk, user=self.sup, version=RC.objects.get(pk=c.pk).version)
        self.assertEqual(again.pk, op.pk)

    def test_maker_cannot_post_and_posting_is_dry_run_by_default(self):
        c = self.approved()
        with self.assertRaises(PermissionDenied):
            LG.prepare_purchase(c.pk, user=self.maker, version=c.version)
        op = LG.prepare_purchase(c.pk, user=self.sup, version=c.version)
        op = LG.post(c.pk, op.op_id, user=self.sup, version=RC.objects.get(pk=c.pk).version)
        self.assertEqual(op.status, Op.ST_DRY_RUN)
        self.assertEqual(op.supplier_invoice.status, 'confirmed')
        self.assertFalse(E.objects.filter(case_id=c.pk).exists())

    @override_settings(REPLACEMENT_POSTING_ENABLED=True)
    def test_live_post_verifies_creates_entitlement_and_never_double_posts(self):
        c = self.approved()
        op = LG.prepare_purchase(c.pk, user=self.sup, version=c.version)
        with mock.patch('apps.invoices.writer.push_final', side_effect=_fake_push_final()) as pf:
            op = LG.post(c.pk, op.op_id, user=self.sup, version=RC.objects.get(pk=c.pk).version)
            op2 = LG.post(c.pk, op.op_id, user=self.sup, version=RC.objects.get(pk=c.pk).version)
        self.assertEqual(pf.call_count, 1)                                # retry never re-writes
        self.assertEqual((op.status, op2.status), (Op.ST_VERIFIED, Op.ST_VERIFIED))
        c.refresh_from_db()
        self.assertEqual(c.status, RC.STATUS_ENTITLEMENT_ACTIVE)
        self.assertEqual(c.purchase_ref.docnumber, '12500')
        self.assertEqual(c.ledger.get(entry_type=E.TYPE_CREATED).amount, D('5618.90'))
        self.assertEqual(c.outstanding, D('5618.90'))
        with self.assertRaises(ValidationError):                          # posted → no reopen
            W.reopen(c.pk, user=self.sup, version=c.version, reason='x')

    @override_settings(REPLACEMENT_POSTING_ENABLED=True)
    def test_post_write_verification_failure_is_an_exception_not_success(self):
        c = self.approved()
        op = LG.prepare_purchase(c.pk, user=self.sup, version=c.version)

        def tamper(inv):
            l = inv.lines.get()
            l.unit_price = D('6000')
            l.save()
        with mock.patch('apps.invoices.writer.push_final', side_effect=_fake_push_final(tamper=tamper)):
            op = LG.post(c.pk, op.op_id, user=self.sup, version=RC.objects.get(pk=c.pk).version)
        self.assertEqual(op.status, Op.ST_FAILED)
        self.assertTrue(X.objects.filter(case_id=c.pk, exception_type='posting_failed', severity='high').exists())
        self.assertFalse(E.objects.filter(case_id=c.pk).exists())

    def test_product_sale_respects_available_and_topup_cap(self):
        c = self.approved(item=self.small)                                  # entitlement 700
        with self.assertRaises(ValidationError):                            # 9 × 300 = 2,700 ≫ 700 + 50 %
            LG.prepare_product_sale(c.pk, user=self.sup, version=c.version, channel='cash',
                                    items=[{'item_id': self.cream.pk, 'qty': 9}])
        op = LG.prepare_product_sale(c.pk, user=self.sup, version=RC.objects.get(pk=c.pk).version, channel='delivery',
                                     items=[{'item_id': self.cream.pk, 'qty': 3}])      # 900 = 700 + 200 top-up
        self.assertEqual(op.expected_value, D('700.00'))
        self.assertEqual(op.result['customer_topup'], '200.00')
        self.assertEqual(op.sales_order.channel, 'delivery')
        self.assertEqual(LG.available(RC.objects.get(pk=c.pk))['available'], D('0'))

    def test_contract_sale_leg_drafts_whole_prescription(self):
        c = self.approved()
        op = LG.prepare_contract_sale(c.pk, user=self.sup, version=c.version, claim={'patientname': 'محمد'})
        o = op.sales_order
        self.assertEqual((o.channel, o.cust_branch_code, o.softech_pic), ('contract', '4479', PIC))
        self.assertEqual(o.lines.count(), 1)

    @override_settings(REPLACEMENT_POSTING_ENABLED=True)
    def test_nightly_reconstruction_attaches_to_the_live_case(self):
        from apps.finance.recon_models import APInvoice, ReconParty
        from apps.replacement import reconstruct as R
        c = self.approved()
        op = LG.prepare_purchase(c.pk, user=self.sup, version=c.version)
        with mock.patch('apps.invoices.writer.push_final', side_effect=_fake_push_final()):
            LG.post(c.pk, op.op_id, user=self.sup, version=RC.objects.get(pk=c.pk).version)
        c.refresh_from_db()
        party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد شركات 30')
        inv = APInvoice.objects.create(party=party, party_type='supplier', branchcode='130', doccode='10',
                                       docnumber='12500', docdate=c.purchase_date, doc_value=D('5618.90'))
        out = R.reconstruct_invoice(inv)
        self.assertFalse(out['created'])
        self.assertEqual(out['case'].pk, c.pk)
        self.assertEqual(RC.objects.count(), 1)
        c.refresh_from_db()
        self.assertEqual(c.origin, RC.ORIGIN_LIVE)
        self.assertEqual(c.items.filter(disposition=ReplacementItem.DISP_REPLACED).count(), 1)   # untouched
        self.assertEqual(c.ledger.filter(entry_type=E.TYPE_CREATED).count(), 1)                 # no double credit
        self.assertFalse(c.exceptions.filter(exception_type='purchase_value_mismatch').exists())


# ═══════════════════════════════════════════════════════════════════════════════
class OwnerDecisionTests(_Base):
    """Owner 2026-10-03: auto-approve ≤ 500, manager above 500 (no override → real config)."""
    @override_settings(REPLACEMENT_APPROVAL_AUTO_MAX=D('500'), REPLACEMENT_APPROVAL_MANAGER_ABOVE=D('500'))
    def test_owner_limits_small_products_auto(self):
        small = self.submit(self.calc(self.new_case(item=self.cream, mode='products')))     # 300 × 0.70 = 210
        self.assertEqual(small.status, RC.STATUS_APPROVED)

    @override_settings(REPLACEMENT_APPROVAL_AUTO_MAX=D('500'), REPLACEMENT_APPROVAL_MANAGER_ABOVE=D('500'))
    def test_owner_limits_above_500_goes_to_manager(self):
        big = self.submit(self.calc(self.new_case(item=self.small)))                         # 700 > 500
        self.assertEqual(big.approval_request.workflow.code, 'replacement_manager')

    @override_settings(REPLACEMENT_APPROVAL_AUTO_MAX=D('500'), REPLACEMENT_APPROVAL_MANAGER_ABOVE=D('500'))
    def test_owner_limits_small_cash_goes_to_supervisor(self):
        cash = self.submit(self.calc(self.new_case(item=self.cream, mode='cash')))           # 180 cash ≤ 500
        self.assertEqual(cash.approval_request.workflow.code, 'replacement_supervisor')

    def test_shipped_defaults_are_the_owner_values(self):
        from apps.replacement import config as C
        self.assertEqual((C.APPROVAL_AUTO_MAX, C.APPROVAL_MANAGER_ABOVE), (D('500'), D('500')))


class FromSaleTests(_Base):
    def test_case_from_contract_sale_aggregates_presplit_lines(self):
        from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
        from django.utils import timezone
        ph = PurchaseHistory.objects.create(
            customer=Customer.objects.get(softech_pic=PIC), branch=self.branch, doc_code='115', total_amount=D('9000'),
            softech_invoice_id='130-115-457389-20260817', docnumber='457389', sales_channel='10',
            softech_phcode=PIC, cust_branch_code='4479', invoice_date=timezone.now())
        for q in ('1', '1'):                                     # same item split over two lines
            PurchaseHistoryLine.objects.create(purchase=ph, item=self.lokelma, quantity=D(q), unit_price=D('7545.38'),
                                               line_total=D('7545.38'), list_price=D('8027'))
        r = self.maker_api.get('/api/replacement/cases/patient-sales/', {'pic': PIC})
        self.assertEqual([(l['itemcode'], D(l['qty'])) for l in r.data['results'][0]['lines']], [('100186', D('2'))])
        c = W.create_case(user=self.maker, branch=self.branch, source_type='insurance_rx', settlement_mode='products',
                          items=[{'item_id': self.lokelma.pk, 'qty': 2}], from_sale=ph)
        self.assertEqual(c.items.count(), 1)
        it = c.items.get()
        self.assertEqual((it.qty_prescribed, it.qty_replaced, it.disposition),
                         (D('2'), D('2'), ReplacementItem.DISP_REPLACED))
        self.assertEqual((c.softech_pic, c.contract_personcode), (PIC, '4479'))
        self.assertTrue(c.documents.filter(role='contract_sale', status='confirmed').exists())


class WorkflowApiTests(_Base):
    def test_end_to_end_over_the_api(self):
        r = self.maker_api.post('/api/replacement/cases/', {
            'branch': self.branch.pk, 'source_type': 'insurance_rx', 'settlement_mode': 'products',
            'softech_pic': PIC, 'contract_personcode': '4479',
            'items': [{'item_id': self.lokelma.pk, 'qty': 1}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        cid, v = r.data['id'], r.data['version']
        r = self.maker_api.post(f'/api/replacement/cases/{cid}/calculate/', {'version': v}, format='json')
        self.assertEqual((r.status_code, r.data['entitlement']), (200, '5618.90'))
        stale = self.maker_api.post(f'/api/replacement/cases/{cid}/submit/', {'version': v}, format='json')
        self.assertEqual(stale.status_code, 409)
        r = self.maker_api.post(f'/api/replacement/cases/{cid}/submit/', {'version': r.data['version']}, format='json')
        self.assertEqual(r.data['status'], RC.STATUS_AWAITING_APPROVAL)
        self.assertFalse(r.data['workflow']['can']['approve'])
        r2 = self.maker_api.post(f'/api/replacement/cases/{cid}/approve/', {'version': r.data['version']}, format='json')
        self.assertEqual(r2.status_code, 403)
        r = self.sup_api.post(f'/api/replacement/cases/{cid}/approve/', {'version': r.data['version']}, format='json')
        self.assertEqual(r.data['status'], RC.STATUS_APPROVED)
        r = self.sup_api.post(f'/api/replacement/cases/{cid}/prepare-purchase/', {'version': r.data['version']},
                              format='json')
        op = r.data['operations'][0]
        r = self.sup_api.post(f'/api/replacement/cases/{cid}/operations/{op["op_id"]}/post/',
                              {'version': r.data['version']}, format='json')
        self.assertEqual(r.data['operations'][0]['status'], Op.ST_DRY_RUN)
        self.assertFalse(r.data['workflow']['posting_enabled'])

    def test_grants_are_admin_only(self):
        r = self.sup_api.post('/api/replacement/grants/', {'staff': self.maker.pk, 'max_override_pp': '3'},
                              format='json')
        self.assertEqual(r.status_code, 403)
        r = self.admin_api.post('/api/replacement/grants/', {'staff': self.maker.pk, 'max_override_pp': '3'},
                                format='json')
        self.assertEqual(r.status_code, 201)
