"""
Mass assignment — SOFTECH and money records (Batch 4, Z-10a; owner sign-off item).

Before: the generic update endpoints took fields that only the workflow should set. A PATCH
could re-open a finalized supplier invoice and clear its SOFTECH docnumber (the writer's only
"already posted" check), so the next push posts it to SOFTECH twice; change a confirmed payment's
amount; resolve a payment exception without the resolve action; post a POS order into another
branch's SOFTECH ledger or re-attribute it to another seller / cashier; set an insurance claim's
status and billed totals past its lock; move a supplement onto another claim; un-clear a cleared
cheque; change a delivered order's value; re-price a used voucher or hand it to a customer
without the assign grant.

Now: those fields are read-only or server-set; status changes only through the workflow actions
(confirm / push / resolve / change-status / activate …), which already check the right grant.
Pricing, posting and redemption logic are unchanged. Each attack runs as admin — the fields are
closed to everyone, not just to the wrong role.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings

from apps.cheques.models import ChequeInstalment, ChequePlan
from apps.delivery.models import DeliveryOrder
from apps.insurance import models as im
from apps.invoices.models import SupplierInvoice
from apps.payments.models import ExternalPayment, PaymentException
from apps.pos_orders.models import SoftechSalesOrder
from apps.tests.factories import make_branch, make_branch2, make_customer, make_user
from apps.vouchers.models import Voucher
from core.middleware import module_access

from .fixtures import bearer_client, seed_code_matrix


@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.branch = make_branch()
        _, self.admin_profile, _ = make_user('z10a_admin', role='admin', branch=self.branch, access_all=True)
        self.c = bearer_client(self.admin_profile.user)

    def tearDown(self):
        module_access.clear_cache()


class SupplierInvoiceTests(_Base):

    def setUp(self):
        super().setUp()
        self.inv = SupplierInvoice.objects.create(branch=self.branch, supplier_name='S', invoice_number='1',
                                                  status='finalized', softech_docnumber=4711)
        self.url = f'/api/invoices/invoices/{self.inv.pk}/'

    def test_a_finalized_invoice_cannot_be_reopened_for_a_second_push(self):
        for method in ('patch', 'put'):
            r = getattr(self.c, method)(self.url, {'status': 'confirmed', 'softech_docnumber': None,
                                                   'branch': self.branch.pk}, format='json')
            self.assertEqual(r.status_code, 405, method)
        self.inv.refresh_from_db()
        self.assertEqual((self.inv.status, self.inv.softech_docnumber), ('finalized', 4711))

    def test_the_header_is_still_edited_through_update_header(self):
        self.inv.status = 'review'
        self.inv.save()
        r = self.c.patch(f'{self.url}update-header/', {'supplier_name': 'S2'}, format='json')
        self.assertEqual(r.status_code, 200)


class PaymentTests(_Base):

    def _payment(self, status):
        return ExternalPayment.objects.create(branch=self.branch, method=ExternalPayment.METHOD_INSTAPAY,
                                              amount=Decimal('250.00'), payment_date=date(2026, 10, 27),
                                              customer_name='Z10', status=status)

    def test_a_confirmed_payment_cannot_be_edited(self):
        p = self._payment(ExternalPayment.STATUS_CONFIRMED)
        r = self.c.patch(f'/api/payments/{p.pk}/', {'amount': '1.00'}, format='json')
        self.assertEqual(r.status_code, 409)
        p.refresh_from_db()
        self.assertEqual(p.amount, Decimal('250.00'))

    def test_a_reconciled_payment_cannot_be_deleted(self):
        p = self._payment(ExternalPayment.STATUS_RECONCILED)
        self.assertEqual(self.c.delete(f'/api/payments/{p.pk}/').status_code, 409)
        self.assertTrue(ExternalPayment.objects.filter(pk=p.pk).exists())

    def test_a_pending_payment_is_still_editable(self):
        p = self._payment(ExternalPayment.STATUS_PENDING)
        self.assertEqual(self.c.patch(f'/api/payments/{p.pk}/', {'amount': '200.00'}, format='json').status_code, 200)


class PaymentExceptionTests(_Base):

    def test_an_exception_is_resolved_only_through_resolve(self):
        exc = PaymentException.objects.create(exception_type=PaymentException.TYPE_MISSING)
        url = f'/api/payments/audit/exceptions/{exc.pk}/'
        r = self.c.patch(url, {'status': 'resolved', 'resolved_by': self.admin_profile.pk}, format='json')
        self.assertEqual(r.status_code, 405)
        exc.refresh_from_db()
        self.assertEqual((exc.status, exc.resolved_by_id), ('open', None))
        self.assertEqual(self.c.post('/api/payments/audit/exceptions/', {'exception_type': 'missing'},
                                     format='json').status_code, 405)


class PosOrderTests(_Base):

    def test_an_order_posts_to_its_own_branch_and_cashier_is_not_client_set(self):
        r = self.c.post('/api/pos-orders/', {
            'branch': self.branch.pk, 'channel': 'cash', 'doc_kind': 'sale', 'customer_name': 'T',
            'softech_branchcode': make_branch2().softech_branch_id, 'cashier_usercode': '77777',
            'lines': [{'softech_itemcode': '107295', 'item_name': 'I1', 'qty': 1, 'item_sale_price': 108}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        o = SoftechSalesOrder.objects.get(pk=r.data['id'])
        self.assertEqual((o.softech_branchcode, o.cashier_usercode), (self.branch.softech_branch_id, ''))

    def test_a_draft_order_cannot_be_moved_or_re_attributed(self):
        o = SoftechSalesOrder.objects.create(branch=self.branch, softech_branchcode=self.branch.softech_branch_id,
                                             store_code='B01', seller_usercode='11111', channel='cash')
        r = self.c.patch(f'/api/pos-orders/{o.pk}/', {
            'branch': make_branch2().pk, 'softech_branchcode': 'B02', 'store_code': 'B02',
            'seller_usercode': '99999', 'cashier_usercode': '99999', 'channel': 'contract', 'notes': 'n',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        o.refresh_from_db()
        self.assertEqual((o.branch_id, o.softech_branchcode, o.store_code, o.seller_usercode,
                          o.cashier_usercode, o.channel),
                         (self.branch.pk, self.branch.softech_branch_id, 'B01', '11111', '', 'cash'))
        self.assertEqual(o.notes, 'n')


class InsuranceTests(_Base):

    def setUp(self):
        super().setUp()
        client = im.InsuranceClient.objects.create(name='جهة')
        self.sub = im.InsuranceSubClient.objects.create(client=client, name='فئة')
        self.claim = self._claim('Z10-1', 'submitted')

    def _claim(self, number, status):
        return im.InsuranceClaim.objects.create(claim_number=number, subclient=self.sub, status=status,
                                                period_from=date(2026, 8, 1), period_to=date(2026, 8, 31),
                                                final_net_after=Decimal('1000'))

    def test_claim_status_and_totals_change_only_through_the_workflow(self):
        url = f'/api/insurance/claims/{self.claim.pk}/'
        for method in ('patch', 'put'):
            r = getattr(self.c, method)(url, {'status': 'draft', 'final_net_after': '99999',
                                              'claim_number': 'Z10-1'}, format='json')
            self.assertEqual(r.status_code, 405, method)
        self.claim.refresh_from_db()
        self.assertEqual((self.claim.status, self.claim.final_net_after), ('submitted', Decimal('1000')))

    def test_a_claim_is_not_created_with_a_forged_status(self):
        # already safe today: the claim create takes only subclient / contract / period / notes
        r = self.c.post('/api/insurance/claims/', {'subclient': self.sub.pk, 'status': 'paid',
                                                   'final_net_after': '99999',
                                                   'period_from': '2026-09-01', 'period_to': '2026-09-30'},
                        format='json')
        self.assertEqual(r.status_code, 201, r.data)
        claim = im.InsuranceClaim.objects.get(pk=r.data['id'])
        self.assertEqual((claim.status, claim.final_net_after), ('draft', Decimal('0')))

    def test_a_supplement_cannot_be_moved_onto_another_claim(self):
        draft = self._claim('Z10-2', 'draft')
        sup = im.InsuranceClaimSupplement.objects.create(claim=draft, supplement_type='within_claim',
                                                         local_before=100, net_after=100)
        r = self.c.patch(f'/api/insurance/claims/{draft.pk}/supplements/{sup.pk}/',
                         {'claim': self.claim.pk, 'notes': 'n'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        sup.refresh_from_db()
        self.assertEqual(sup.claim_id, draft.pk)


class ChequeTests(_Base):

    def _instalment(self, plan_status, status):
        plan = ChequePlan.objects.create(title='خطة', payee_name='مورد', total_amount=Decimal('1000'),
                                         first_due_date=date(2026, 11, 1), status=plan_status)
        return ChequeInstalment.objects.create(plan=plan, instalment_no=1, amount=Decimal('1000'), status=status,
                                               nominal_date=date(2026, 11, 1), due_date=date(2026, 11, 1))

    def _patch(self, inst, data):
        return self.c.patch(f'/api/cheques/plans/{inst.plan_id}/instalments/{inst.pk}/', data, format='json')

    def test_a_cleared_cheque_cannot_go_back_to_pending(self):
        inst = self._instalment('active', 'cleared')
        self.assertEqual(self._patch(inst, {'status': 'pending', 'cleared_at': None}).status_code, 409)
        inst.refresh_from_db()
        self.assertEqual(inst.status, 'cleared')

    def test_cheques_of_a_plan_that_is_not_active_cannot_change(self):
        inst = self._instalment('draft', 'pending')
        self.assertEqual(self._patch(inst, {'status': 'cleared'}).status_code, 409)
        inst.refresh_from_db()
        self.assertEqual(inst.status, 'pending')

    def test_an_active_plans_cheque_is_still_issued(self):
        inst = self._instalment('active', 'pending')
        self.assertEqual(self._patch(inst, {'status': 'issued', 'cheque_number': '123'}).status_code, 200)


class DeliveryTests(_Base):

    def _order(self, status):
        return DeliveryOrder.objects.create(branch=self.branch, customer_name='عميل', status=status,
                                            total_value=Decimal('300'), delivery_fees=Decimal('20'),
                                            payment_method='cash')

    def test_a_delivered_orders_money_is_closed(self):
        o = self._order('delivered')
        r = self.c.patch(f'/api/delivery/{o.pk}/', {'total_value': '1', 'delivery_fees': '0',
                                                    'softech_doc_ref': 999}, format='json')
        self.assertEqual(r.status_code, 409)
        o.refresh_from_db()
        self.assertEqual((o.total_value, o.delivery_fees), (Decimal('300'), Decimal('20')))

    def test_an_order_out_for_delivery_keeps_its_value(self):
        o = self._order('out_for_delivery')
        r = self.c.patch(f'/api/delivery/{o.pk}/', {'total_value': '1', 'notes': 'n'}, format='json')
        self.assertEqual(r.status_code, 409)
        o.refresh_from_db()
        self.assertEqual(o.total_value, Decimal('300'))

    def test_a_new_order_is_still_editable(self):
        o = self._order('created')
        self.assertEqual(self.c.patch(f'/api/delivery/{o.pk}/', {'total_value': '310'},
                                      format='json').status_code, 200)


class VoucherTests(_Base):

    def _voucher(self, times_used=0):
        return Voucher.objects.create(code=Voucher.generate_code(), title='ق', voucher_type='discount_pct',
                                      discount_pct=10, branch=self.branch, created_by=self.admin_profile,
                                      status='active', max_uses=10, times_used=times_used,
                                      valid_from=date.today())

    def test_a_voucher_is_handed_to_a_customer_only_through_assign(self):
        v = self._voucher()
        r = self.c.patch(f'/api/vouchers/vouchers/{v.pk}/', {'customer': make_customer().pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        v.refresh_from_db()
        self.assertIsNone(v.customer_id)

    def test_a_used_vouchers_value_cannot_change(self):
        v = self._voucher(times_used=1)
        r = self.c.patch(f'/api/vouchers/vouchers/{v.pk}/', {'discount_pct': '90', 'max_uses': 1000},
                         format='json')
        self.assertEqual(r.status_code, 409)
        v.refresh_from_db()
        self.assertEqual((v.discount_pct, v.max_uses), (Decimal('10'), 10))

    def test_an_unused_voucher_is_still_corrected(self):
        v = self._voucher()
        self.assertEqual(self.c.patch(f'/api/vouchers/vouchers/{v.pk}/', {'discount_pct': '15'},
                                      format='json').status_code, 200)
