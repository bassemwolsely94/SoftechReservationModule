"""
Mass assignment — "who" fields and records after posting (Batch 4, Z-10c).

Before: an HR requester could nominate themselves as the approver of their own request and
then approve it; a procurement alert's resolver was free text from the client (the screens sent
"dashboard_user"); a bank-statement import's uploader and an item→ingredient mapping's author
could be rewritten by PATCH; a supplier invoice's header and lines stayed editable after it was
queued for or posted to SOFTECH; and editing a payment left no trace in its log.

Now: the server records who did it, a requester cannot approve their own request through the
nominated step, a queued / posted invoice is frozen, and each payment edit is logged before→after.

Z-11j/k (overblock review): editing a *confirmed* (or push-failed) supplier invoice sends it back
to review, so a second confirm — the push's precondition — follows any change; the reopen is
audited (who, what action, from which status).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings

from apps.approvals.models import ApprovalRequest
from apps.catalog.models import Item
from apps.chronic.models import ActiveIngredient, ItemIngredientMap
from apps.invoices.models import SupplierInvoice
from apps.payments.models import BankStatementImport, ExternalPayment
from apps.procurement.models import ProcurementAlert
from apps.tests.factories import make_branch, make_user
from apps.tests.test_hr import HrBase
from core.middleware import module_access

from .fixtures import bearer_client, seed_code_matrix


class HrSelfApprovalTests(HrBase):

    def _permit(self, approver_ids):
        return self.emp_c.post('/api/hr/permits/submit/', {
            'permit_type': 'mamoriya', 'date': '2026-07-10', 'time_from': '10:00', 'time_to': '13:00',
            'destination': 'المخزن', 'reason': 'توصيل', 'approver_ids': approver_ids,
        }, format='json')

    def test_a_requester_cannot_nominate_themselves(self):
        r = self._permit([self.emp.pk])
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ApprovalRequest.objects.exists())

    def test_someone_else_is_still_nominated(self):
        _, nom, _ = make_user('z10c_nom', role='pharmacist', branch=self.branch)
        self.assertEqual(self._permit([nom.pk]).status_code, 201)


@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.branch = make_branch()
        self.admin_user, self.admin_profile, _ = make_user('z10c_admin', role='admin', branch=self.branch,
                                                           access_all=True)
        _, self.other, _ = make_user('z10c_other', role='purchasing', branch=self.branch)
        self.c = bearer_client(self.admin_user)

    def tearDown(self):
        module_access.clear_cache()


class WhoFieldTests(_Base):

    def test_an_alert_is_resolved_in_the_callers_name(self):
        a = ProcurementAlert.objects.create(alert_type='price_spike', title='t', message='m')
        r = self.c.patch(f'/api/procurement/alerts/{a.pk}/resolve/', {'resolved_by': 'someone else'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        a.refresh_from_db()
        self.assertEqual(a.resolved_by, self.admin_profile.full_name[:100])

    def test_a_statement_uploader_is_not_rewritten(self):
        s = BankStatementImport.objects.create(branch=self.branch, bank_name='b', statement_from=date(2026, 10, 1),
                                               statement_to=date(2026, 10, 31), imported_by=self.admin_profile)
        r = self.c.patch(f'/api/payments/audit/statements/{s.pk}/', {'imported_by': self.other.pk}, format='multipart')
        self.assertEqual(r.status_code, 200, r.data)
        s.refresh_from_db()
        self.assertEqual(s.imported_by_id, self.admin_profile.pk)

    def test_an_ingredient_mapping_records_its_real_editor(self):
        m = ItemIngredientMap.objects.create(item=Item.objects.create(softech_id='Z10C1', name='i'),
                                             active_ingredient=ActiveIngredient.objects.create(name='x'),
                                             mapped_by=self.other)
        r = self.c.patch(f'/api/chronic/item-maps/{m.pk}/', {'mapped_by': self.other.pk, 'is_primary': True},
                         format='json')
        self.assertEqual(r.status_code, 200, r.data)
        m.refresh_from_db()
        self.assertEqual(m.mapped_by_id, self.admin_profile.pk)


class PostedInvoiceTests(_Base):

    def _invoice(self, status):
        return SupplierInvoice.objects.create(branch=self.branch, supplier_name='S', invoice_number='1', status=status)

    def test_a_posted_invoice_is_frozen(self):
        for st in ('queued', 'finalized'):
            inv = self._invoice(st)
            url = f'/api/invoices/invoices/{inv.pk}/'
            self.assertEqual(self.c.patch(f'{url}update-header/', {'supplier_name': 'X'}, format='json').status_code,
                             409, st)
            self.assertEqual(self.c.post(f'{url}add-line/', {'manual_name': 'n', 'quantity': 1},
                                         format='json').status_code, 409, st)
            inv.refresh_from_db()
            self.assertEqual((inv.supplier_name, inv.lines.count()), ('S', 0))

    def test_an_invoice_in_review_is_still_edited(self):
        inv = self._invoice('review')
        self.assertEqual(self.c.patch(f'/api/invoices/invoices/{inv.pk}/update-header/', {'supplier_name': 'X'},
                                      format='json').status_code, 200)


class PaymentEditLogTests(_Base):

    def test_a_payment_edit_is_logged_before_and_after(self):
        p = ExternalPayment.objects.create(branch=self.branch, method=ExternalPayment.METHOD_INSTAPAY,
                                           amount=Decimal('250.00'), payment_date=date(2026, 10, 27), customer_name='Z')
        r = self.c.patch(f'/api/payments/{p.pk}/', {'amount': '200.00'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        log = p.reconciliation_logs.get(action='edited')
        self.assertEqual(log.performed_by_id, self.admin_user.pk)
        self.assertIn('250.00', log.notes)
        self.assertIn('200.00', log.notes)


class ConfirmedInvoiceEditTests(_Base):

    def _invoice(self, status):
        return SupplierInvoice.objects.create(branch=self.branch, supplier_name='S', invoice_number='1', status=status)

    def test_editing_a_confirmed_invoice_sends_it_back_to_review(self):
        from apps.audit.models import AuditLog
        for st in ('confirmed', 'push_failed'):
            inv = self._invoice(st)
            r = self.c.patch(f'/api/invoices/invoices/{inv.pk}/update-header/', {'supplier_name': 'X'}, format='json')
            self.assertEqual(r.status_code, 200, st)
            inv.refresh_from_db()
            self.assertEqual((inv.status, inv.supplier_name), ('review', 'X'), st)
            self.assertTrue(AuditLog.objects.filter(action='invoice_reopened', object_id=str(inv.pk)).exists(), st)

    def test_a_failed_edit_does_not_reopen_and_review_stays_review(self):
        inv = self._invoice('confirmed')
        self.assertEqual(self.c.post(f'/api/invoices/invoices/{inv.pk}/add-line/', {'quantity': 'x'},
                                     format='json').status_code // 100, 4)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'confirmed')
        inv2 = self._invoice('review')
        self.c.patch(f'/api/invoices/invoices/{inv2.pk}/update-header/', {'supplier_name': 'Y'}, format='json')
        inv2.refresh_from_db()
        self.assertEqual(inv2.status, 'review')
