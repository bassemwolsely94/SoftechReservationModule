"""
Tax Invoicing (apps/tax_invoicing, doc 36). ETA is replaced by mocks here: these tests prove our
behaviour around ETA's documented answers, not ETA's acceptance of our documents.
"""
import datetime as dt
import io
import json
import threading
from decimal import Decimal
from unittest import mock

import openpyxl
import requests
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connections, transaction
from django.db.models import F
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.insurance.models import (InsuranceClaim, InsuranceClaimLine, InsuranceClaimManualRx,
                                   InsuranceClaimPrescription, InsuranceClient, InsuranceSubClient)
from apps.tax_invoicing import eta_client, fiscal, item_import, receipts, services, signing, submission
from apps.tax_invoicing.models import (TaxBuyerProfile, TaxChannelRule, TaxDocument, TaxDocumentLine,
                                       TaxExclusionBasis, TaxIssuerProfile, TaxItemProfile, TaxLineReview, TaxReceipt,
                                       TaxReceiptBranchConfig, TaxSubmissionAttempt)
from apps.tests.factories import make_branch, make_user

LIVE = dict(TAX_ETA_SUBMIT_ENABLED=True, WRITER_INSTANCE=True, TAX_ALLOW_MOCK_SIGNER=True,
            TAX_ERECEIPT_SUBMIT_ENABLED=True, TAX_SIGNER_CLASS='apps.tests.test_tax_invoicing.FakeSigner')
ACCEPTED = {'submissionUUID': 'SUB1', 'acceptedDocuments': [{'uuid': 'UUID1', 'longId': 'LONG1', 'internalId': None}],
            'rejectedDocuments': []}


class FakeSigner:
    is_mock = True
    needs_certification = False

    def sign(self, canonical_text):
        return 'U0lH'


def accepted_for(doc):
    body = json.loads(json.dumps(ACCEPTED))
    body['acceptedDocuments'][0]['internalId'] = doc.internal_id
    return 202, body


def api(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
    return c


class Fixture:
    def build(self, tag='a'):
        self.branch = make_branch(softech_id=f'T{tag}')
        from core.middleware import module_access
        module_access.clear_cache()
        from apps.users.models import RoleModuleAccess
        for action in ('view', 'create', 'edit', 'approve'):   # same rows as the seed; a kept test DB may be flushed
            RoleModuleAccess.objects.get_or_create(role='accountant', module='tax_invoicing', action=action,
                                                   defaults={'is_allowed': True})
        with override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher']):
            self.accountant, _, _ = make_user(f'acct_{tag}', role='accountant', branch=self.branch)
            self.accountant2, _, _ = make_user(f'acct2_{tag}', role='accountant', branch=self.branch)
            self.admin, _, _ = make_user(f'tadmin_{tag}', role='admin', branch=self.branch)
            self.pharmacist, _, _ = make_user(f'ph_{tag}', role='pharmacist', branch=self.branch)
        self.client_row = InsuranceClient.objects.create(name=f'شركة {tag}')
        self.sub = InsuranceSubClient.objects.create(client=self.client_row, name='فئة')
        i = TaxIssuerProfile.load()
        for k, v in dict(name='الرزيقى', tax_id='100200300', activity_code='4772', governate='القاهرة',
                         region_city='القاهرة', street='شارع', building_number='1', default_unit_type='EA',
                         vat_tax_type='T1', subtype_taxable='VT', subtype_exempt='VE', subtype_zero_rated='VZ',
                         vat_basis_confirmed_at=timezone.now(), prices_include_vat=True).items():
            setattr(i, k, v)
        i.save()
        TaxBuyerProfile.objects.create(client=self.client_row, tax_id='999888777', legal_name='شركة', governate='الجيزة',
                                       region_city='الدقي', street='شارع', building_number='2',
                                       presentation_mode=TaxBuyerProfile.MODE_DETAILED)

    def make_claim(self, number='MT-1', lines=(('T1', 114, 114), ('E1', 200, 200)), status='submitted'):
        total = sum(Decimal(str(n)) for _, _, n in lines)
        claim = InsuranceClaim.objects.create(claim_number=number, subclient=self.sub, period_from=dt.date(2026, 10, 1),
                                              period_to=dt.date(2026, 10, 31), final_net_after=total, status=status)
        rx = InsuranceClaimPrescription.objects.create(claim=claim, softech_docnumber=f'{number}-D', softech_docdate=dt.date(2026, 10, 2),
                                                       softech_branchcode='150', net_after=total)
        for code, gross, net in lines:
            InsuranceClaimLine.objects.create(prescription=rx, softech_itemcode=code, item_name=f'صنف {code}', quantity=1,
                                              unit_price=gross, line_total=gross, discount_amt=Decimal(str(gross)) - Decimal(str(net)),
                                              net_amount=net)
        return claim

    def coded(self, code, treatment='taxable', rate=14, **extra):
        return TaxItemProfile.objects.update_or_create(softech_itemcode=code, defaults=dict(
            eta_code=f'EG-100200300-{code}', code_type='EGS', coding_status='approved', tax_treatment=treatment,
            vat_rate=rate if treatment == 'taxable' else 0, treatment_confirmed_at=timezone.now(), **extra))[0]

    def ready_doc(self, number='MT-1'):
        self.coded('T1')
        self.coded('E1', 'exempt')
        doc, _ = services.open_or_create_invoice(self.make_claim(number), self.accountant)
        return services.revalidate(doc)


class ImportAndUniquenessTests(Fixture, TestCase):
    def setUp(self):
        self.build()

    def test_import_keeps_source_lines_and_links_claim(self):
        doc = self.ready_doc()
        self.assertEqual(doc.claim.claim_number, 'MT-1')
        self.assertEqual(len(doc.source_snapshot['lines']), 2)
        self.assertEqual(doc.source_snapshot['lines'][0]['docnumber'], 'MT-1-D')
        self.assertEqual(doc.lines.count(), 2)
        self.assertNotIn('patient', json.dumps(doc.source_snapshot))

    def test_unfinalized_claim_is_refused(self):
        with self.assertRaises(services.TaxRuleError):
            services.open_or_create_invoice(self.make_claim('MT-D', status='draft'), self.accountant)

    def test_reopening_returns_the_same_draft(self):
        claim = self.make_claim()
        first, created = services.open_or_create_invoice(claim, self.accountant)
        again, created2 = services.open_or_create_invoice(claim, self.accountant)
        self.assertTrue(created)
        self.assertFalse(created2)
        self.assertEqual(first.pk, again.pk)

    def test_database_refuses_second_original(self):
        doc = self.ready_doc()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaxDocument.objects.create(claim=doc.claim, internal_id='INV-X')

    def test_lost_race_opens_the_winner(self):
        claim = self.make_claim()
        winner, _ = services.open_or_create_invoice(claim, self.accountant)
        real = TaxDocument.objects.filter
        calls = []

        def first_empty(*a, **k):
            qs = real(*a, **k)
            if not calls:
                calls.append(1)
                return qs.none()
            return qs
        with mock.patch.object(TaxDocument.objects, 'filter', side_effect=first_empty):
            doc, created = services.open_or_create_invoice(claim, self.accountant)
        self.assertFalse(created)
        self.assertEqual(doc.pk, winner.pk)

    def test_fiscal_status_is_visible_from_the_claim_with_insurance_access(self):
        doc = self.ready_doc()
        r = api(self.admin).get(f'/api/insurance/claims/{doc.claim_id}/fiscal-status/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['documents'][0]['internal_id'], doc.internal_id)


class ClaimReturnTests(Fixture, TestCase):
    """Real claims: a return prescription has negative totals over positive item lines."""

    def setUp(self):
        self.build()
        self.coded('T1')
        self.coded('E1', 'exempt')

    def claim_with_return(self, returned=('T1', 57), number='MT-R'):
        claim = self.make_claim(number)
        code, amount = returned
        rx = InsuranceClaimPrescription.objects.create(
            claim=claim, softech_docnumber=f'{number}-RET', softech_docdate=dt.date(2026, 10, 5), softech_branchcode='150',
            gross_before=-amount, net_after=-amount)
        # A part of the pack back: 57 of 114 is half the quantity.
        InsuranceClaimLine.objects.create(prescription=rx, softech_itemcode=code, item_name=f'صنف {code}',
                                          quantity=Decimal(amount) / 114, unit_price=114, line_total=amount, net_amount=amount)
        InsuranceClaim.objects.filter(pk=claim.pk).update(final_net_after=F('final_net_after') - amount)
        return InsuranceClaim.objects.get(pk=claim.pk)

    def test_return_lines_subtract_and_the_claim_reconciles(self):
        doc, _ = services.open_or_create_invoice(self.claim_with_return(), self.accountant)
        rec = services.reconciliation(doc)
        self.assertEqual(Decimal(rec['source_total']), Decimal('257'))
        self.assertEqual(Decimal(rec['proposed_total']), Decimal('257.00000'))
        self.assertTrue(rec['within_tolerance'])
        self.assertEqual(doc.lines.count(), 3)   # the source stays complete, return line included
        self.assertEqual(doc.lines.filter(quantity__lt=0).count(), 1)

    def test_item_with_a_return_goes_to_eta_as_one_positive_line(self):
        doc, _ = services.open_or_create_invoice(self.claim_with_return(), self.accountant)
        body = json.loads(services.approve(doc.pk, self.accountant).payload_text)
        by_code = {l['internalCode']: l for l in body['invoiceLines']}
        self.assertEqual(by_code['T1']['netTotal'], 50.0)
        self.assertEqual(by_code['T1']['taxableItems'][0]['amount'], 7.0)
        self.assertEqual(body['totalAmount'], 257.0)
        self.assertTrue(all(l['quantity'] > 0 for l in body['invoiceLines']))

    def test_fully_returned_item_leaves_no_line(self):
        doc, _ = services.open_or_create_invoice(self.claim_with_return(('T1', 114), 'MT-F'), self.accountant)
        body = json.loads(services.approve(doc.pk, self.accountant).payload_text)
        self.assertEqual([l['internalCode'] for l in body['invoiceLines']], ['E1'])

    def test_more_returned_than_sold_blocks(self):
        claim = self.make_claim('MT-X')
        for i in (1, 2):
            rx = InsuranceClaimPrescription.objects.create(
                claim=claim, softech_docnumber=f'RET{i}', softech_docdate=dt.date(2026, 10, 5), gross_before=-114, net_after=-114)
            InsuranceClaimLine.objects.create(prescription=rx, softech_itemcode='T1', quantity=1, unit_price=114, line_total=114, net_amount=114)
        InsuranceClaim.objects.filter(pk=claim.pk).update(final_net_after=86)
        doc, _ = services.open_or_create_invoice(InsuranceClaim.objects.get(pk=claim.pk), self.accountant)
        with self.assertRaises(services.TaxBlocked) as caught:
            services.approve(doc.pk, self.accountant)
        self.assertIn('quantity', [i['code'] for i in caught.exception.issues])


class ConcurrentCreationTests(Fixture, TransactionTestCase):
    def test_two_simultaneous_requests_make_one_invoice(self):
        self.build('c')
        claim = self.make_claim('MT-C')
        barrier = threading.Barrier(2)
        results, errors = [], []

        def worker():
            try:
                barrier.wait(timeout=10)
                results.append(services.open_or_create_invoice(claim, self.accountant))
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(TaxDocument.objects.filter(claim=claim).count(), 1)
        self.assertEqual({d.pk for d, _ in results}, {TaxDocument.objects.get(claim=claim).pk})


class MixedClaimTests(Fixture, TestCase):
    def setUp(self):
        self.build()

    def test_mixed_taxable_and_exempt_claim(self):
        doc = self.ready_doc()
        self.assertEqual(services.blockers(doc), [])
        doc = services.approve(doc.pk, self.accountant)
        body = json.loads(doc.payload_text)
        self.assertEqual(len(body['invoiceLines']), 2)
        by_code = {l['internalCode']: l for l in body['invoiceLines']}
        self.assertEqual(by_code['T1']['netTotal'], 100.0)
        self.assertEqual(by_code['T1']['taxableItems'][0]['amount'], 14.0)
        self.assertEqual(by_code['T1']['taxableItems'][0]['subType'], 'VT')
        # Exempt status alone does not remove the line: it is on the invoice at no VAT.
        self.assertEqual(by_code['E1']['netTotal'], 200.0)
        self.assertEqual(by_code['E1']['taxableItems'][0]['amount'], 0.0)
        self.assertEqual(by_code['E1']['taxableItems'][0]['subType'], 'VE')
        self.assertEqual(body['totalAmount'], 314.0)
        self.assertEqual(body['taxTotals'], [{'taxType': 'T1', 'amount': 14.0}])

    def test_treatment_unconfirmed_holds_the_line(self):
        self.coded('T1')
        self.coded('E1', 'unclassified')
        TaxItemProfile.objects.filter(softech_itemcode='E1').update(treatment_confirmed_at=None)
        doc, _ = services.open_or_create_invoice(self.make_claim(), self.accountant)
        self.assertEqual(doc.lines.get(softech_itemcode='E1').status, TaxDocumentLine.ST_PENDING)
        with self.assertRaises(services.TaxBlocked):
            services.approve(doc.pk, self.accountant)

    def test_no_vat_due_is_presented(self):
        self.coded('E1', 'exempt')
        doc, _ = services.open_or_create_invoice(self.make_claim('MT-E', lines=(('E1', 200, 200),)), self.accountant)
        doc = services.approve(doc.pk, self.accountant)
        r = api(self.accountant).get(f'/api/tax-invoicing/documents/{doc.pk}/print/')
        self.assertTrue(r.data['no_vat_due'])
        self.assertEqual(Decimal(r.data['totals']['vat']), 0)

    def test_vat_comes_from_the_confirmed_treatment_not_the_source(self):
        self.coded('T1', rate=14)
        doc, _ = services.open_or_create_invoice(self.make_claim('MT-V', lines=(('T1', 114, 114),)), self.accountant)
        self.assertEqual(doc.vat_amount, Decimal('14.00000'))
        api(self.accountant).patch(f'/api/tax-invoicing/items/{TaxItemProfile.objects.get(softech_itemcode="T1").pk}/',
                                   {'tax_treatment': 'exempt', 'treatment_reference': 'REF'}, format='json')
        doc.refresh_from_db()
        self.assertEqual(doc.vat_amount, 0)


class UncodedItemTests(Fixture, TestCase):
    def setUp(self):
        self.build()

    def test_uncoded_item_blocks_shows_drafts_then_resolves(self):
        self.coded('T1')
        doc, _ = services.open_or_create_invoice(self.make_claim(), self.accountant)
        doc2, _ = services.open_or_create_invoice(self.make_claim('MT-2'), self.accountant)
        self.assertEqual(doc.lines.get(softech_itemcode='E1').status, TaxDocumentLine.ST_UNCODED)
        issue = next(i for i in services.blockers(doc) if i['code'] == 'uncoded')
        self.assertEqual(issue['skus'], ['E1'])

        r = api(self.accountant).get('/api/tax-invoicing/exceptions/')
        row = next(x for x in r.data if x['itemcode'] == 'E1')
        self.assertEqual({d['id'] for d in row['drafts']}, {doc.pk, doc2.pk})

        # No partial upload: nothing gets approved, no payload exists.
        with self.assertRaises(services.TaxBlocked):
            services.approve(doc.pk, self.accountant)
        doc.refresh_from_db()
        self.assertEqual(doc.payload_text, '')

        r = api(self.accountant).post('/api/tax-invoicing/items/', {
            'itemcode': 'E1', 'eta_code': 'EG-100200300-E1', 'code_type': 'EGS', 'coding_status': 'approved',
            'tax_treatment': 'exempt', 'treatment_reference': 'REF-1'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['revalidated_drafts'], 2)
        doc.refresh_from_db()
        self.assertEqual(doc.lines.get(softech_itemcode='E1').status, TaxDocumentLine.ST_EXEMPT)
        self.assertEqual(services.approve(doc.pk, self.accountant).status, TaxDocument.APPROVED)
        self.assertEqual(len(json.loads(TaxDocument.objects.get(pk=doc.pk).payload_text)['invoiceLines']), 2)

    def test_pending_and_rejected_codes_block_too(self):
        self.coded('T1')
        for state, expected in (('pending', TaxDocumentLine.ST_PENDING), ('rejected', TaxDocumentLine.ST_UNCODED)):
            self.coded('E1', 'exempt')
            TaxItemProfile.objects.filter(softech_itemcode='E1').update(coding_status=state)
            doc, _ = services.open_or_create_invoice(self.make_claim(f'MT-{state}'), self.accountant)
            self.assertEqual(doc.lines.get(softech_itemcode='E1').status, expected)
            with self.assertRaises(services.TaxBlocked):
                services.approve(doc.pk, self.accountant)


class ThreeFieldsAndListTests(Fixture, TestCase):
    def setUp(self):
        self.build()

    def test_fields_change_independently(self):
        p = self.coded('T1')
        c = api(self.accountant)
        c.patch(f'/api/tax-invoicing/items/{p.pk}/', {'coding_status': 'pending'}, format='json')
        p.refresh_from_db()
        self.assertEqual((p.coding_status, p.tax_treatment, p.disposition), ('pending', 'taxable', 'include'))
        c.patch(f'/api/tax-invoicing/items/{p.pk}/', {'disposition': 'review'}, format='json')
        p.refresh_from_db()
        self.assertEqual((p.coding_status, p.tax_treatment, p.disposition), ('pending', 'taxable', 'review'))

    def test_blacklist_routes_to_review_and_does_not_remove_the_line(self):
        self.coded('T1', list_status='black', disposition='review', listed_reason='مصدر غير رسمي')
        self.coded('E1', 'exempt')
        doc, _ = services.open_or_create_invoice(self.make_claim(), self.accountant)
        line = doc.lines.get(softech_itemcode='T1')
        self.assertEqual(line.status, TaxDocumentLine.ST_PENDING)
        self.assertIn('مصدر غير رسمي', line.status_reason)
        with self.assertRaises(services.TaxBlocked):
            services.approve(doc.pk, self.accountant)
        self.assertEqual(doc.lines.count(), 2)


class ExclusionTests(Fixture, TestCase):
    def setUp(self):
        self.build()
        self.doc = self.ready_doc()
        self.line = self.doc.lines.get(softech_itemcode='T1')
        self.basis = TaxExclusionBasis.objects.create(title='قرار', reference_number='R-9', issued_by='جهة', applies_to='نطاق')

    def ask(self, **kw):
        return services.request_review(self.line, self.accountant, 'exclusion', 'سبب مكتوب', **kw)

    def test_unresolved_exclusion_holds_the_whole_draft(self):
        self.ask(supporting_reference='REF', basis_id=self.basis.pk)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.lines.get(pk=self.line.pk).status, TaxDocumentLine.ST_PENDING)
        with self.assertRaises(services.TaxBlocked):
            services.approve(self.doc.pk, self.accountant)
        self.assertEqual(TaxDocument.objects.get(pk=self.doc.pk).payload_text, '')

    def test_exclusion_without_basis_cannot_be_accepted(self):
        review = self.ask(supporting_reference='REF')
        with self.assertRaises(services.TaxRuleError):
            services.decide_review(review.pk, self.accountant2, True)
        self.assertEqual(TaxLineReview.objects.get(pk=review.pk).state, TaxLineReview.OPEN)

    def test_exclusion_without_reference_or_with_inactive_basis_cannot_be_accepted(self):
        review = self.ask(basis_id=self.basis.pk)
        with self.assertRaises(services.TaxRuleError):
            services.decide_review(review.pk, self.accountant2, True)
        TaxLineReview.objects.filter(pk=review.pk).update(supporting_reference='REF')
        TaxExclusionBasis.objects.filter(pk=self.basis.pk).update(is_active=False)
        with self.assertRaises(services.TaxRuleError):
            services.decide_review(review.pk, self.accountant2, True)

    def test_requester_cannot_accept_their_own_exclusion(self):
        review = self.ask(supporting_reference='REF', basis_id=self.basis.pk)
        with self.assertRaises(services.TaxRuleError):
            services.decide_review(review.pk, self.accountant, True)

    def test_accepted_exclusion_records_everything_and_shows_impact(self):
        review = self.ask(supporting_reference='REF', basis_id=self.basis.pk)
        self.assertEqual((review.effect_net, review.effect_vat, review.effect_gross),
                         (Decimal('100.00000'), Decimal('14.00000'), Decimal('114.00000')))
        decided = services.decide_review(review.pk, self.accountant2, True)
        self.assertEqual(decided.reviewed_by, self.accountant2)
        self.assertIsNotNone(decided.reviewed_at)
        doc = TaxDocument.objects.get(pk=self.doc.pk)
        self.assertEqual(doc.total_amount, Decimal('200.00000'))
        rec = services.reconciliation(doc)
        self.assertEqual(Decimal(rec['source_total']), Decimal('314'))
        self.assertEqual(Decimal(rec['excluded_total']), Decimal('114'))
        self.assertTrue(any(r['kind'] == 'excluded' and 'T1' in r['ref'] for r in rec['rows']))
        self.assertTrue(rec['within_tolerance'])
        self.assertEqual(doc.lines.count(), 2)   # the source stays complete

    def test_declined_exclusion_puts_the_line_back_on_the_invoice(self):
        review = self.ask(supporting_reference='REF', basis_id=self.basis.pk)
        services.decide_review(review.pk, self.accountant2, False, 'لا ينطبق')
        self.assertEqual(TaxDocument.objects.get(pk=self.doc.pk).total_amount, Decimal('314.00000'))


class ReviewViewTests(Fixture, TestCase):
    def setUp(self):
        self.build()

    def test_filter_changes_only_the_display(self):
        self.coded('T1')
        self.coded('E1', 'exempt')
        self.coded('B1', list_status='black', disposition='review')
        doc, _ = services.open_or_create_invoice(
            self.make_claim(lines=(('T1', 114, 114), ('E1', 200, 200), ('B1', 114, 114), ('U1', 50, 50))), self.accountant)
        c = api(self.accountant)
        narrow = c.get(f'/api/tax-invoicing/documents/{doc.pk}/')
        wide = c.get(f'/api/tax-invoicing/documents/{doc.pk}/?view=all')
        self.assertEqual({l['status'] for l in narrow.data['lines']}, {'approved'})
        self.assertEqual({l['status'] for l in wide.data['lines']}, {'approved', 'exempt', 'pending', 'uncoded'})
        self.assertEqual(len(wide.data['lines']), 4)   # every original SOFTECH line
        self.assertEqual(narrow.data['counts']['exempt'], 1)
        self.assertTrue(all(l['reason'] for l in wide.data['lines'] if l['status'] in ('pending', 'uncoded')))
        for key in ('counts', 'totals', 'reconciliation', 'blockers'):
            self.assertEqual(narrow.data[key], wide.data[key], key)
        self.assertEqual(narrow.data['counts']['unresolved'], 2)

    def test_same_payload_from_either_view(self):
        doc = self.ready_doc()
        doc = services.approve(doc.pk, self.accountant)
        c = api(self.accountant)
        first = TaxDocument.objects.get(pk=doc.pk).payload_hash
        c.get(f'/api/tax-invoicing/documents/{doc.pk}/?view=all')
        c.get(f'/api/tax-invoicing/documents/{doc.pk}/')
        a = c.post(f'/api/tax-invoicing/documents/{doc.pk}/preview/')
        b = c.post(f'/api/tax-invoicing/documents/{doc.pk}/preview/?view=all')
        self.assertEqual(a.data['payload_text'], b.data['payload_text'])
        self.assertEqual(a.data['payload_hash'], first)

    def test_all_lines_needs_authority_on_the_server(self):
        doc = self.ready_doc()
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.get_or_create(role='pharmacist', module='tax_invoicing', action='view',
                                               defaults={'is_allowed': True})
        c = api(self.pharmacist)
        self.assertEqual(c.get(f'/api/tax-invoicing/documents/{doc.pk}/').status_code, 200)
        self.assertEqual(c.get(f'/api/tax-invoicing/documents/{doc.pk}/?view=all').status_code, 403)


class SingleLineTests(Fixture, TestCase):
    def setUp(self):
        self.build()
        TaxBuyerProfile.objects.filter(client=self.client_row).update(presentation_mode='summary')

    def validated_rule(self):
        TaxIssuerProfile.objects.filter(pk=1).update(
            summary_code_type='EGS', summary_item_code='EG-100200300-CLAIM', summary_treatment='exempt',
            summary_vat_rate=0, summary_validated_at=timezone.now())

    def test_layout_does_not_change_the_eta_payload_without_a_rule(self):
        doc = self.ready_doc()
        self.assertEqual(services.fiscal_mode(doc)[0], 'detailed')
        doc = services.approve(doc.pk, self.accountant)
        self.assertEqual(len(json.loads(doc.payload_text)['invoiceLines']), 2)
        r = api(self.accountant).get(f'/api/tax-invoicing/documents/{doc.pk}/print/')
        self.assertEqual(len(r.data['rows']), 1)
        self.assertEqual(Decimal(r.data['totals']['total']), Decimal('314'))
        self.assertEqual(doc.lines.count(), 2)

    def test_uniform_claim_under_a_validated_rule_sends_one_line(self):
        self.validated_rule()
        self.coded('E1', 'exempt')
        self.coded('E2', 'exempt')
        doc, _ = services.open_or_create_invoice(self.make_claim('MT-U', lines=(('E1', 100, 100), ('E2', 50, 50))), self.accountant)
        self.assertEqual(services.fiscal_mode(doc)[0], 'summary')
        doc = services.approve(doc.pk, self.accountant)
        body = json.loads(doc.payload_text)
        self.assertEqual(len(body['invoiceLines']), 1)
        self.assertEqual(body['invoiceLines'][0]['itemCode'], 'EG-100200300-CLAIM')
        self.assertEqual(body['totalAmount'], 150.0)
        self.assertEqual(doc.lines.count(), 2)   # breakdown retained

    def test_mixed_treatments_fall_back_to_detail_even_with_a_rule(self):
        self.validated_rule()
        doc = self.ready_doc()
        self.assertEqual(services.fiscal_mode(doc)[0], 'detailed')
        self.assertEqual(len(json.loads(services.approve(doc.pk, self.accountant).payload_text)['invoiceLines']), 2)


class SubmissionGateTests(Fixture, TestCase):
    def setUp(self):
        self.build()
        self.doc = services.approve(self.ready_doc().pk, self.accountant)

    def test_flag_is_off_by_default_and_nothing_goes_out(self):
        with mock.patch('requests.post') as post:
            with self.assertRaises(services.TaxRuleError):
                submission.submit(self.doc.pk, self.admin, self.doc.internal_id)
        post.assert_not_called()

    @override_settings(TAX_ETA_SUBMIT_ENABLED=True, WRITER_INSTANCE=False)
    def test_non_writer_instance_cannot_send(self):
        with self.assertRaises(services.TaxRuleError):
            submission.submit(self.doc.pk, self.admin, self.doc.internal_id)

    def test_endpoint_is_a_dry_run_by_default(self):
        with mock.patch('requests.post') as post:
            r = api(self.admin).post(f'/api/tax-invoicing/documents/{self.doc.pk}/submit/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['dry_run'])
        post.assert_not_called()
        self.assertEqual(TaxDocument.objects.get(pk=self.doc.pk).status, TaxDocument.APPROVED)

    @override_settings(TAX_ETA_SUBMIT_ENABLED=True, WRITER_INSTANCE=True)
    def test_unconfigured_signer_refuses_and_nothing_is_sent(self):
        with mock.patch('requests.post') as post:
            with self.assertRaises(services.TaxRuleError):
                submission.submit(self.doc.pk, self.admin, self.doc.internal_id)
        post.assert_not_called()
        self.assertEqual(TaxDocument.objects.get(pk=self.doc.pk).status, TaxDocument.APPROVED)

    @override_settings(**LIVE)
    def test_wrong_confirmation_is_refused(self):
        with self.assertRaises(services.TaxRuleError):
            submission.submit(self.doc.pk, self.admin, 'wrong')

    @override_settings(RBAC_ENFORCEMENT='enforce')   # tests default to off, where the matrix refuses nobody
    def test_permissions_on_the_server(self):
        url = f'/api/tax-invoicing/documents/{self.doc.pk}/'
        self.assertEqual(api(self.pharmacist).get(url).status_code, 403)
        self.assertEqual(api(self.accountant).get(url).status_code, 200)
        self.assertEqual(api(self.accountant).post(url + 'submit/', {}, format='json').status_code, 403)
        self.assertEqual(api(self.accountant).post(url + 'reconcile/', {}, format='json').status_code, 403)

    def test_module_is_enforced_for_other_roles_from_the_migration_alone(self):
        """Rows of an enforced role alone would make the matrix fail open for everyone else."""
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        self.assertTrue(RoleModuleAccess.objects.filter(role='admin', module='tax_invoicing', action='finalize').exists())
        module_access.clear_cache()
        self.assertIn('tax_invoicing', module_access.seeded_modules())

    def test_only_admin_may_record_an_exclusion_basis(self):
        body = {'title': 'x', 'reference_number': 'y', 'issued_by': 'z', 'applies_to': 'w'}
        self.assertEqual(api(self.accountant).post('/api/tax-invoicing/bases/', body, format='json').status_code, 403)
        self.assertEqual(api(self.admin).post('/api/tax-invoicing/bases/', body, format='json').status_code, 201)
        self.assertEqual(TaxExclusionBasis.objects.count(), 1)

    def test_no_exclusion_basis_is_seeded(self):
        self.assertEqual(TaxExclusionBasis.objects.count(), 0)


@override_settings(**LIVE)
class TimeoutAndRetryTests(Fixture, TestCase):
    def setUp(self):
        self.build()
        self.doc = services.approve(self.ready_doc().pk, self.accountant)

    def send(self):
        return submission.submit(self.doc.pk, self.admin, self.doc.internal_id)

    def timed_out(self):
        with mock.patch.object(eta_client, 'submit_documents', side_effect=eta_client.EtaUncertain('timeout')):
            doc = self.send()
        self.assertEqual(doc.status, TaxDocument.UNCERTAIN)
        return doc

    def test_timeout_blocks_resubmission_until_reconciled(self):
        self.timed_out()
        with mock.patch.object(eta_client, 'submit_documents') as sent:
            with self.assertRaises(services.TaxRuleError):
                self.send()
        sent.assert_not_called()

    def test_reconcile_finds_it_at_eta_and_never_sends_again(self):
        self.timed_out()
        row = {'uuid': 'UUID9', 'longId': 'L9', 'submissionUUID': 'S9', 'status': 'Valid', 'internalId': self.doc.internal_id}
        with mock.patch.object(eta_client, 'find_by_internal_id', return_value=row), \
                mock.patch.object(eta_client, 'submit_documents') as sent:
            doc = submission.reconcile(self.doc.pk, self.admin)
        sent.assert_not_called()
        self.assertEqual((doc.status, doc.eta_uuid), (TaxDocument.VALID, 'UUID9'))
        self.assertEqual(TaxDocument.objects.filter(claim=doc.claim, doc_type='i').count(), 1)

    def test_not_found_too_soon_stays_uncertain(self):
        self.timed_out()
        with mock.patch.object(eta_client, 'find_by_internal_id', return_value=None):
            doc = submission.reconcile(self.doc.pk, self.admin)
        self.assertEqual(doc.status, TaxDocument.UNCERTAIN)

    def test_could_not_ask_changes_nothing(self):
        self.timed_out()
        TaxSubmissionAttempt.objects.update(started_at=timezone.now() - dt.timedelta(hours=1))
        with mock.patch.object(eta_client, 'find_by_internal_id', side_effect=eta_client.EtaUncertain('down')):
            with self.assertRaises(services.TaxRuleError):
                submission.reconcile(self.doc.pk, self.admin)
        self.assertEqual(TaxDocument.objects.get(pk=self.doc.pk).status, TaxDocument.UNCERTAIN)

    def test_not_found_after_the_wait_allows_retry_with_the_same_identity(self):
        before = self.timed_out()
        TaxSubmissionAttempt.objects.update(started_at=timezone.now() - dt.timedelta(hours=1))
        with mock.patch.object(eta_client, 'find_by_internal_id', return_value=None):
            doc = submission.reconcile(self.doc.pk, self.admin)
        self.assertEqual(doc.status, TaxDocument.APPROVED)
        with mock.patch.object(eta_client, 'submit_documents', return_value=accepted_for(doc)) as sent:
            doc = self.send()
        self.assertEqual(doc.status, TaxDocument.SUBMITTED)
        self.assertEqual(doc.internal_id, before.internal_id)
        self.assertEqual(doc.payload_hash, before.payload_hash)
        self.assertIn(before.internal_id, sent.call_args[0][0])
        self.assertEqual(TaxDocument.objects.filter(claim=doc.claim, doc_type='i').count(), 1)

    def test_stale_submitting_is_reconciled_not_resent(self):
        TaxDocument.objects.filter(pk=self.doc.pk).update(status=TaxDocument.SUBMITTING)
        with self.assertRaises(services.TaxRuleError):
            self.send()
        TaxSubmissionAttempt.objects.create(document=self.doc, payload_hash='x')
        with self.assertRaises(services.TaxRuleError):
            submission.reconcile(self.doc.pk, self.admin)   # still inside the wait

    def test_second_click_cannot_send_twice(self):
        with mock.patch.object(eta_client, 'submit_documents', return_value=accepted_for(self.doc)) as sent:
            self.send()
            with self.assertRaises(services.TaxRuleError):
                self.send()
        self.assertEqual(sent.call_count, 1)

    def test_rejected_document_reopens_with_the_same_number(self):
        body = {'submissionUUID': 'S', 'acceptedDocuments': [],
                'rejectedDocuments': [{'internalId': self.doc.internal_id, 'error': {'code': 'X'}}]}
        with mock.patch.object(eta_client, 'submit_documents', return_value=(202, body)):
            doc = self.send()
        self.assertEqual(doc.status, TaxDocument.REJECTED)
        doc = services.reopen(doc.pk, self.accountant, 'تصحيح')
        self.assertEqual(doc.status, TaxDocument.DRAFT)
        doc = services.approve(doc.pk, self.accountant)
        self.assertEqual(doc.internal_id, self.doc.internal_id)

    def test_exact_approved_text_is_what_gets_sent(self):
        with mock.patch.object(eta_client, 'submit_documents', return_value=accepted_for(self.doc)) as sent:
            self.send()
        text = sent.call_args[0][0]
        self.assertTrue(text.startswith(self.doc.payload_text[:-1]))
        self.assertEqual(json.loads(text)['signatures'][0]['value'], 'U0lH')


@override_settings(**LIVE)
class NoteTests(Fixture, TestCase):
    def setUp(self):
        self.build()
        self.doc = services.approve(self.ready_doc().pk, self.accountant)

    def accepted(self):
        with mock.patch.object(eta_client, 'submit_documents', return_value=accepted_for(self.doc)):
            submission.submit(self.doc.pk, self.admin, self.doc.internal_id)
        row = {'uuid': 'UUID1', 'status': 'Valid', 'internalId': self.doc.internal_id}
        with mock.patch.object(eta_client, 'find_by_internal_id', return_value=row):
            return submission.reconcile(self.doc.pk, self.admin)

    def test_note_refused_before_acceptance(self):
        line = self.doc.lines.first()
        with self.assertRaises(services.TaxRuleError):
            services.create_note(self.doc.pk, self.accountant, 'c', 'سبب', [{'line_id': line.pk, 'amount': '10'}])

    def test_credit_note_after_acceptance_links_and_preserves_the_original(self):
        doc = self.accepted()
        frozen = (doc.payload_text, doc.total_amount)
        line = doc.lines.get(softech_itemcode='T1')
        note = services.create_note(doc.pk, self.accountant, 'c', 'مرتجع', [{'line_id': line.pk, 'amount': '57'}])
        self.assertEqual((note.original_id, note.claim_id, note.reason), (doc.pk, doc.claim_id, 'مرتجع'))
        self.assertTrue(note.internal_id.startswith('CN-'))
        self.assertEqual(note.total_amount, Decimal('57.00000'))
        self.assertEqual(note.vat_amount, Decimal('7.00000'))
        note = services.approve(note.pk, self.accountant)
        body = json.loads(note.payload_text)
        self.assertEqual(body['documentType'], 'c')
        self.assertEqual(body['references'], ['UUID1'])
        doc = TaxDocument.objects.get(pk=doc.pk)
        self.assertEqual((doc.payload_text, doc.total_amount, doc.status), (*frozen, TaxDocument.VALID))

    def test_debit_note(self):
        doc = self.accepted()
        note = services.create_note(doc.pk, self.accountant, 'd', 'فرق', [{'line_id': doc.lines.first().pk, 'amount': '10'}])
        self.assertEqual(json.loads(services.approve(note.pk, self.accountant).payload_text)['documentType'], 'd')

    def test_credit_cannot_exceed_the_line(self):
        doc = self.accepted()
        line = doc.lines.get(softech_itemcode='T1')
        services.create_note(doc.pk, self.accountant, 'c', 'أ', [{'line_id': line.pk, 'amount': '100'}])
        with self.assertRaises(services.TaxRuleError):
            services.create_note(doc.pk, self.accountant, 'c', 'ب', [{'line_id': line.pk, 'amount': '15'}])

    def test_note_needs_a_reason_and_an_amount(self):
        doc = self.accepted()
        line = doc.lines.first()
        for reason, items in (('', [{'line_id': line.pk, 'amount': '1'}]), ('س', []), ('س', [{'line_id': line.pk, 'amount': '0'}])):
            with self.assertRaises(services.TaxRuleError):
                services.create_note(doc.pk, self.accountant, 'c', reason, items)

    def test_accepted_original_cannot_be_reopened_or_changed(self):
        doc = self.accepted()
        with self.assertRaises(services.TaxRuleError):
            services.reopen(doc.pk, self.accountant, 'سبب')
        doc.total_amount = Decimal('1')
        with self.assertRaises(ValidationError):
            doc.save()


class ReconciliationTests(Fixture, TestCase):
    def setUp(self):
        self.build()

    def test_claim_amount_without_item_lines_is_shown_and_blocks(self):
        doc = self.ready_doc()
        InsuranceClaimManualRx.objects.create(claim=doc.claim, softech_docnumber='M1', softech_docdate=dt.date(2026, 10, 3),
                                              net_after=500)
        InsuranceClaim.objects.filter(pk=doc.claim_id).update(final_net_after=814)
        services.refresh_source(doc, self.accountant, 'إضافة يدوية')
        doc = TaxDocument.objects.get(pk=doc.pk)
        rec = services.reconciliation(doc)
        self.assertEqual(Decimal(rec['difference']), Decimal('500'))
        self.assertTrue(any(r['kind'] == 'no_lines' and r['ref'] == 'M1' for r in rec['rows']))
        self.assertFalse(rec['within_tolerance'])
        with self.assertRaises(services.TaxBlocked):
            services.approve(doc.pk, self.accountant)

    def test_changed_claim_is_caught(self):
        doc = self.ready_doc()
        first = doc.source_snapshot
        InsuranceClaimLine.objects.filter(prescription__claim=doc.claim, softech_itemcode='T1').update(net_amount=100)
        self.assertIn('source_changed', [i['code'] for i in services.blockers(doc)])
        services.refresh_source(doc, self.accountant, 'تعديل')
        doc = TaxDocument.objects.get(pk=doc.pk)
        self.assertEqual(doc.source_snapshot, first)   # the first snapshot is preserved

    def test_audit_trail_records_who_and_what(self):
        doc = services.approve(self.ready_doc().pk, self.accountant)
        actions = set(doc.events.values_list('action', flat=True))
        self.assertTrue({'draft_created', 'status_change', 'payload_frozen'} <= actions)
        event = doc.events.filter(action='payload_frozen').first()
        self.assertEqual(event.actor, self.accountant)
        event.reason = 'x'
        with self.assertRaises(ValidationError):
            event.save()


class FormatTests(SimpleTestCase):
    """Against the rules on ETA's document-serialization page. Not yet checked against ETA itself."""

    def test_canonical_form(self):
        text = '{"a":"x","b":1.50000,"c":{"d":"y"},"lines":[{"e":0.0},{"e":2}],"signatures":[{"value":"s"}]}'
        self.assertEqual(fiscal.canonical(text),
                         '"A""x""B""1.50000""C""D""y""LINES""LINES""E""0.0""LINES""E""2"')

    def test_canonical_keeps_arabic_and_escapes(self):
        self.assertEqual(fiscal.canonical('{"a":"ع\\"ب"}'), '"A""ع\\"ب"')

    def test_signature_leaves_the_text_untouched(self):
        text = '{"a":1.50000}'
        signed = fiscal.with_signature(text, 'QQ==')
        self.assertTrue(signed.startswith('{"a":1.50000,'))
        self.assertEqual(fiscal.canonical(signed), fiscal.canonical(text))

    def test_vat_split(self):
        self.assertEqual(fiscal.split_vat('114', 14, True), (Decimal('100.00000'), Decimal('14.00000')))
        self.assertEqual(fiscal.split_vat('100', 14, False), (Decimal('100.00000'), Decimal('14.00000')))
        self.assertEqual(fiscal.split_vat('200', 0, True), (Decimal('200.00000'), Decimal('0.00000')))


@override_settings(TAX_ETA_API_BASE_URL='https://api.example.test', TAX_ETA_ID_BASE_URL='https://id.example.test',
                   TAX_ETA_CLIENT_ID='id', TAX_ETA_CLIENT_SECRET='secret')
class EtaClientTests(SimpleTestCase):
    def setUp(self):
        eta_client.reset_token()
        self.addCleanup(eta_client.reset_token)

    def resp(self, code, body=None):
        r = mock.Mock(status_code=code)
        r.json.return_value = body or {}
        return r

    def post(self, *answers):
        token = self.resp(200, {'access_token': 'T', 'expires_in': 3600})
        return mock.patch('requests.post', side_effect=[token, *answers])

    def test_timeout_is_uncertain(self):
        with self.post(requests.Timeout()):
            with self.assertRaises(eta_client.EtaUncertain):
                eta_client.submit_documents('{}')

    def test_server_error_and_duplicate_are_uncertain(self):
        for code in (500, 503, 422, 429):
            eta_client.reset_token()
            with self.post(self.resp(code)):
                with self.assertRaises(eta_client.EtaUncertain):
                    eta_client.submit_documents('{}')

    def test_client_error_is_a_refusal(self):
        with self.post(self.resp(400, {'error': 'bad'})):
            with self.assertRaises(eta_client.EtaRefused):
                eta_client.submit_documents('{}')

    def test_login_failure_is_a_refusal(self):
        with mock.patch('requests.post', return_value=self.resp(401)):
            with self.assertRaises(eta_client.EtaRefused):
                eta_client.submit_documents('{}')

    def test_accepted(self):
        with self.post(self.resp(202, {'submissionUUID': 'S'})) as post:
            code, body = eta_client.submit_documents('{"a":1.50000}')
        self.assertEqual((code, body['submissionUUID']), (202, 'S'))
        self.assertIn(b'1.50000', post.call_args.kwargs['data'])
        self.assertFalse(post.call_args.kwargs['allow_redirects'])

    @override_settings(TAX_ETA_API_BASE_URL='')
    def test_unconfigured_cannot_reach_anything(self):
        with mock.patch('requests.post', return_value=self.resp(200, {'access_token': 'T'})) as post:
            with self.assertRaises(eta_client.EtaNotConfigured):
                eta_client.submit_documents('{}')
        self.assertEqual(post.call_count, 1)  # only the login was attempted, no document


class ZeroVatBasisTests(Fixture, TestCase):
    def setUp(self):
        self.build()

    def test_claim_level_zero_vat_only_with_a_documented_basis(self):
        doc = self.ready_doc()
        self.assertEqual(doc.vat_amount, Decimal('14.00000'))
        wrong = TaxExclusionBasis.objects.create(title='x', reference_number='E', issued_by='y', applies_to='z')
        c = api(self.admin)
        r = c.post('/api/tax-invoicing/buyers/', {'client_id': self.client_row.pk, 'zero_vat_basis_id': wrong.pk}, format='json')
        self.assertEqual(r.status_code, 400)   # an exclusion basis is not a VAT determination
        right = TaxExclusionBasis.objects.create(kind='zero_vat', title='x', reference_number='Z', issued_by='y', applies_to='z')
        r = c.post('/api/tax-invoicing/buyers/', {'client_id': self.client_row.pk, 'zero_vat_basis_id': right.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        doc = TaxDocument.objects.get(pk=doc.pk)
        self.assertEqual(doc.vat_amount, 0)
        self.assertEqual(doc.total_amount, Decimal('314.00000'))
        self.assertEqual(json.loads(services.approve(doc.pk, self.accountant).payload_text)['invoiceLines'][0]['taxableItems'][0]['subType'], 'VZ')

    def test_accountant_cannot_set_it(self):
        right = TaxExclusionBasis.objects.create(kind='zero_vat', title='x', reference_number='Z', issued_by='y', applies_to='z')
        r = api(self.accountant).post('/api/tax-invoicing/buyers/', {'client_id': self.client_row.pk, 'zero_vat_basis_id': right.pk}, format='json')
        self.assertEqual(r.status_code, 403)


def workbook(rows, header=('Item', 'Code', 'Type', 'Black', 'Rate', 'VatCode')):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'DataEntry'
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = 'codes.xlsx'
    return buf


OPTIONS = {'sheet': 'DataEntry', 'mapping': {'itemcode': 0, 'eta_code': 1, 'code_type': 2, 'list_flag': 3, 'vat_rate': 4, 'vat_code': 5},
           'black_values': ['1'], 'white_values': ['0']}


class ImportMappingTests(Fixture, TestCase):
    def setUp(self):
        self.build()

    def test_inspect_shows_the_real_headers_and_guesses_nothing(self):
        out = item_import.inspect_workbook(workbook([('1', 'EG-1-1', 'EGS', '0', 0, 'v003')]))
        self.assertEqual([c['header'] for c in out['sheets'][0]['columns']][:2], ['Item', 'Code'])
        with self.assertRaises(services.TaxRuleError):
            item_import.preview(workbook([]), {'sheet': 'DataEntry', 'mapping': {}})

    def test_preview_writes_nothing_and_reports_row_problems(self):
        out = item_import.preview(workbook([
            ('X1', 'EG-1-X1', 'EGS', '0', 0.14, 'v009'),
            ('X2', 'EG-1-X2', 'BAD', '0', 0, 'v003'),
            ('X3', 'EG-1-X3', 'EGS', '?', 0, 'v003'),
            ('X4', 'EG-1-DUP', 'EGS', '0', 0, 'v003'),
            ('X5', 'EG-1-DUP', 'EGS', '0', 0, 'v003'),
            ('X6', 'EG-1-X6', 'EGS', '0', 0, 'v003'),
            ('X6', 'EG-1-X6B', 'EGS', '0', 0, 'v003'),
            ('X7', 'EG-1-X7', 'EGS', '0', 200, 'v003'),
            ('X8', 'EG-1-OTHER', 'EGS', '1', 0, 'v003'),
        ]), OPTIONS)
        codes = out['issue_counts']
        for expected in ('bad_code_type', 'bad_list_flag', 'duplicate_eta_code', 'duplicate_item', 'bad_vat', 'code_mismatch', 'black_but_coded', 'not_in_catalog'):
            self.assertIn(expected, codes)
        self.assertTrue(out['dry_run'])
        self.assertEqual(TaxItemProfile.objects.count(), 0)
        self.assertEqual(out['sample'][0]['vat_rate'], '14.00')   # 0.14 in the sheet is 14%

    def test_leading_zeros_stay_and_numeric_codes_are_flagged(self):
        out = item_import.preview(workbook([('0123', '06224002879073', 'GS1', '0', 0, 'v003'), (45, 6224002879097, 'GS1', '0', 0, 'v003')]), OPTIONS)
        self.assertEqual(out['sample'][0]['itemcode'], '0123')
        self.assertEqual(out['sample'][0]['eta_code'], '06224002879073')
        self.assertEqual(out['sample'][1]['eta_code'], '6224002879097')
        self.assertIn('numeric_code', out['issue_counts'])

    def test_apply_needs_the_previewed_hash_and_loads_inputs_not_decisions(self):
        file = workbook([('X1', 'EG-1-X1', 'EGS', '0', 0.14, 'v009'), ('X2', 'EG-1-X2', '', '1', 0, 'v003'), ('X3', '', '', '1', 0, 'v003')])
        with self.assertRaises(services.TaxRuleError):
            item_import.apply(file, OPTIONS, self.accountant, 'wrong')
        h = item_import.preview(file, OPTIONS)['preview_hash']
        self.assertEqual(item_import.apply(file, OPTIONS, self.accountant, h)['written'], 3)
        x1, x2 = TaxItemProfile.objects.get(softech_itemcode='X1'), TaxItemProfile.objects.get(softech_itemcode='X2')
        self.assertEqual((x1.coding_status, x1.list_status, x1.disposition, x1.tax_treatment, x1.source_vat_rate, x1.source_vat_code),
                         ('pending', 'white', 'include', 'unclassified', Decimal('14.00'), 'v009'))
        self.assertIsNone(x1.treatment_confirmed_at)
        self.assertEqual((x2.coding_status, x2.list_status, x2.disposition), ('missing', 'black', 'review'))
        self.assertEqual(x2.eta_code, '')       # a code with no type is not kept: nothing to check at ETA

    def test_changed_mapping_or_file_needs_a_new_preview(self):
        file = workbook([('X1', 'EG-1-X1', 'EGS', '0', 0, 'v003')])
        h = item_import.preview(file, OPTIONS)['preview_hash']
        with self.assertRaises(services.TaxRuleError):
            item_import.apply(file, {**OPTIONS, 'coded_status': 'approved'}, self.accountant, h)
        with self.assertRaises(services.TaxRuleError):
            item_import.apply(workbook([('X9', 'EG-1-X9', 'EGS', '0', 0, 'v003')]), OPTIONS, self.accountant, h)

    def test_conflicts_are_reported_and_kept_unless_overwritten(self):
        self.coded('X1')
        file = workbook([('X1', 'EG-1-NEW', 'EGS', '0', 0, 'v003')])
        out = item_import.preview(file, OPTIONS)
        self.assertEqual(out['counts']['conflicts'], 1)
        result = item_import.apply(file, OPTIONS, self.accountant, out['preview_hash'])
        self.assertEqual(result['conflicts_skipped'], 1)
        self.assertEqual(TaxItemProfile.objects.get(softech_itemcode='X1').eta_code, 'EG-100200300-X1')
        over = {**OPTIONS, 'overwrite_conflicts': True}
        item_import.apply(file, over, self.accountant, out['preview_hash'])
        self.assertEqual(TaxItemProfile.objects.get(softech_itemcode='X1').eta_code, 'EG-1-NEW')

    def test_apply_is_for_approvers_preview_for_editors(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.get_or_create(role='pharmacist', module='tax_invoicing', action='edit', defaults={'is_allowed': True})
        file = workbook([('X1', 'EG-1-X1', 'EGS', '0', 0, 'v003')])
        c = api(self.pharmacist)
        r = c.post('/api/tax-invoicing/items/import/preview/', {'file': file, 'options': json.dumps(OPTIONS)}, format='multipart')
        self.assertEqual(r.status_code, 200, r.data)
        file.seek(0)
        r2 = c.post('/api/tax-invoicing/items/import/apply/', {'file': file, 'options': json.dumps(OPTIONS), 'preview_hash': r.data['preview_hash']}, format='multipart')
        self.assertEqual(r2.status_code, 403)

    def test_accountant_confirms_vat_by_code(self):
        file = workbook([('X1', 'EG-1-X1', 'EGS', '0', 0.14, 'v009'), ('X2', 'EG-1-X2', 'EGS', '0', 0, 'v003')])
        item_import.apply(file, OPTIONS, self.accountant, item_import.preview(file, OPTIONS)['preview_hash'])
        r = api(self.accountant).post('/api/tax-invoicing/items/confirm-vat/',
                                      {'vat_code': 'v009', 'tax_treatment': 'taxable', 'treatment_reference': 'REF'}, format='json')
        self.assertEqual(r.data['confirmed'], 1)
        x1 = TaxItemProfile.objects.get(softech_itemcode='X1')
        self.assertEqual((x1.tax_treatment, x1.vat_rate), ('taxable', Decimal('14.00')))
        self.assertIsNone(TaxItemProfile.objects.get(softech_itemcode='X2').treatment_confirmed_at)


def row(number, item='T1', total='114', channel='91', doccode='115', vat='14', qty='1', ref=None, day=dt.datetime(2026, 11, 1), branch='150'):
    return (branch, doccode, number, day, channel, total, item, f'صنف {item}', qty, total, total, vat,
            dt.datetime(2026, 11, 1, 10, 30), ref[0] if ref else None, ref[1] if ref else None, ref[2] if ref else None)


@override_settings(**LIVE)
class ReceiptTests(Fixture, TestCase):
    def setUp(self):
        self.build()
        self.coded('T1')
        self.coded('E1', 'exempt')
        TaxChannelRule.objects.update_or_create(ptclassifcode='91', defaults={'mode': 'receipt'})
        TaxChannelRule.objects.update_or_create(ptclassifcode='10', defaults={'mode': 'invoice'})
        TaxChannelRule.objects.filter(ptclassifcode='77').delete()
        self.config = TaxReceiptBranchConfig.objects.create(
            softech_branchcode='150', is_enabled=True, seller_branch_code='0', device_serial='POS1', activity_code='4772',
            governate='القاهرة', region_city='عين شمس', street='شارع', building_number='1', payment_method='C', client_id='c',
            secret_env='X_SECRET', preshared_key_env='X_PSK', chain_start='fresh', send_from=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc))

    def one(self, number='7'):
        return TaxReceipt.objects.get(docnumber=number)

    def test_import_is_idempotent_on_the_document_key(self):
        rows = [row(7), row(7, item='E1', total='50', vat='0')]
        self.assertEqual(receipts.import_rows(rows)['created'], 1)
        self.assertEqual(receipts.import_rows(rows)['created'], 0)
        self.assertEqual(TaxReceipt.objects.count(), 1)
        self.assertEqual(self.one().lines.count(), 2)

    def test_same_number_on_another_date_is_another_document(self):
        receipts.import_rows([row(7), row(7, day=dt.datetime(2026, 11, 2))])
        self.assertEqual(TaxReceipt.objects.filter(docnumber='7').count(), 2)

    def test_database_refuses_a_second_receipt_for_one_document(self):
        receipts.import_rows([row(7)])
        r = self.one()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaxReceipt.objects.create(softech_branchcode=r.softech_branchcode, doccode=r.doccode, docnumber=r.docnumber,
                                      docdate=r.docdate, sold_at=r.sold_at)

    def test_channel_rules_decide_and_unknown_is_held_not_dropped(self):
        receipts.import_rows([row(1), row(2, channel='10'), row(3, channel='77')])
        self.assertEqual(self.one('1').status, TaxReceipt.READY)
        self.assertEqual(self.one('2').status, TaxReceipt.BY_INVOICE)
        self.assertEqual(self.one('3').status, TaxReceipt.HELD)
        self.assertEqual(self.one('3').hold_reasons[0]['code'], 'no_channel_rule')

    def test_uncoded_item_holds_the_whole_sale_with_no_partial_receipt(self):
        receipts.import_rows([row(7), row(7, item='NEW', total='10', vat='0')])
        self.assertEqual(self.one().status, TaxReceipt.HELD)
        self.assertEqual(receipts.issue_next('150', self.accountant)['issued'], 0)
        self.assertEqual(self.one().payload_text, '')
        api(self.accountant).post('/api/tax-invoicing/items/', {
            'itemcode': 'NEW', 'eta_code': 'EG-1-NEW', 'code_type': 'EGS', 'coding_status': 'approved',
            'tax_treatment': 'exempt', 'treatment_reference': 'R'}, format='json')
        self.assertEqual(self.one().status, TaxReceipt.READY)

    def test_blacklisted_item_holds_the_sale(self):
        self.coded('B1', list_status='black', disposition='review', listed_reason='مقيد')
        receipts.import_rows([row(7), row(7, item='B1', total='10')])
        receipt = self.one()
        self.assertEqual(receipt.status, TaxReceipt.HELD)
        self.assertEqual(receipt.lines.count(), 2)
        self.assertTrue(any('مقيد' in i['message'] for i in receipt.hold_reasons))

    def test_softech_vat_differs_from_confirmed_is_held(self):
        receipts.import_rows([row(7, vat='10')])
        self.assertEqual(self.one().status, TaxReceipt.HELD)

    def test_chain_links_receipts_oldest_first_and_uuid_is_reproducible(self):
        receipts.import_rows([row(1), row(2, total='228')])
        self.assertEqual(receipts.issue_next('150', self.accountant)['issued'], 2)
        a, b = TaxReceipt.objects.order_by('issued_at', 'id')
        self.assertEqual(a.previous_uuid, '')
        self.assertEqual(b.previous_uuid, a.uuid)
        body = json.loads(b.payload_text, parse_float=Decimal)
        self.assertEqual(body['header']['previousUUID'], a.uuid)
        self.assertEqual(body['seller']['deviceSerialNumber'], 'POS1')
        self.assertEqual(body['documentType'], {'receiptType': 's', 'typeVersion': '1.2'})
        again = json.loads(b.payload_text)
        again['header']['uuid'] = ''
        self.assertEqual(len(b.uuid), 64)
        # Same text with the uuid blanked gives the same hash.
        blanked = b.payload_text.replace(b.uuid, '', 1)
        self.assertEqual(fiscal.sha256_hex(fiscal.canonical(blanked)), b.uuid)
        self.assertEqual(TaxReceiptBranchConfig.objects.get(pk=self.config.pk).last_uuid, b.uuid)

    def test_each_branch_has_its_own_chain_and_config(self):
        TaxReceiptBranchConfig.objects.create(softech_branchcode='160', is_enabled=True, seller_branch_code='1', device_serial='POS2',
                                              activity_code='4772', governate='g', region_city='r', street='s', building_number='1', payment_method='C',
                                              chain_start='fresh', send_from=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc))
        receipts.import_rows([row(1), row(2, branch='160')])
        receipts.issue_next('150', self.accountant)
        receipts.issue_next('160', self.accountant)
        self.assertEqual(TaxReceipt.objects.get(softech_branchcode='160').previous_uuid, '')
        self.assertIn('POS2', TaxReceipt.objects.get(softech_branchcode='160').payload_text)

    def test_disabled_branch_cannot_issue(self):
        TaxReceiptBranchConfig.objects.filter(pk=self.config.pk).update(is_enabled=False)
        with self.assertRaises(services.TaxRuleError):
            receipts.issue_next('150', self.accountant)

    def test_return_needs_its_original_issued_here(self):
        receipts.import_rows([row(9, doccode='30', ref=('115', 1, dt.datetime(2026, 11, 1)))])
        self.assertEqual(self.one('9').status, TaxReceipt.HELD)
        receipts.import_rows([row(1)])
        receipts.issue_next('150', self.accountant)
        original = self.one('1')
        receipts.evaluate(self.one('9'))
        self.assertEqual(self.one('9').status, TaxReceipt.READY)
        receipts.issue_next('150', self.accountant)
        body = json.loads(self.one('9').payload_text)
        self.assertEqual(body['documentType']['receiptType'], 'r')
        self.assertEqual(body['header']['referenceUUID'], original.uuid)

    def test_return_with_softech_blank_or_zero_reference_type_matches_the_sale(self):
        receipts.import_rows([row(1)])
        receipts.issue_next('150', self.accountant)
        for number, kind in ((8, '0'), (9, '')):
            receipts.import_rows([row(number, doccode='30', ref=(kind, 1, dt.datetime(2026, 11, 1)))])
        # blank type with a number is still a reference
        self.assertEqual(self.one('8').status, TaxReceipt.READY)
        self.assertEqual(self.one('9').status, TaxReceipt.READY)
        receipts.import_rows([row(10, doccode='30', ref=('50', 1, dt.datetime(2026, 11, 1)))])
        self.assertEqual(self.one('10').status, TaxReceipt.HELD)

    def test_submit_and_status_flow(self):
        receipts.import_rows([row(1), row(2), row(3)])
        receipts.issue_next('150', self.accountant)
        ids = {r.docnumber: r.uuid for r in TaxReceipt.objects.all()}
        answer = (202, {'submissionId': 'SUB', 'acceptedDocuments': [{'uuid': ids['1']}, {'uuid': ids['2']}],
                        'rejectedDocuments': [{'uuid': ids['3'], 'error': {'code': 'X'}}]})
        with mock.patch.object(eta_client, 'submit_receipts', return_value=answer) as sent:
            result = receipts.submit_branch('150', self.admin, '150')
        self.assertEqual(result['count'], 3)
        order = sent.call_args[0][1]
        self.assertEqual(ids['1'] in order[0], True)
        self.assertEqual(self.one('1').status, TaxReceipt.SUBMITTED)
        self.assertEqual(self.one('3').status, TaxReceipt.REJECTED)
        with mock.patch.object(eta_client, 'get_receipt_status', return_value={'status': 'Valid'}):
            receipts.reconcile_branch('150', self.admin)
        self.assertEqual(self.one('1').status, TaxReceipt.ACCEPTED)

    def test_timeout_stops_the_branch_until_reconciled_and_never_resends_blind(self):
        receipts.import_rows([row(1)])
        receipts.issue_next('150', self.accountant)
        uuid_before = self.one('1').uuid
        with mock.patch.object(eta_client, 'submit_receipts', side_effect=eta_client.EtaUncertain('timeout')):
            self.assertEqual(receipts.submit_branch('150', self.admin, '150')['status'], 'uncertain')
        self.assertEqual(self.one('1').status, TaxReceipt.UNCERTAIN)
        with mock.patch.object(eta_client, 'submit_receipts') as sent:
            with self.assertRaises(services.TaxRuleError):
                receipts.submit_branch('150', self.admin, '150')
        sent.assert_not_called()
        with mock.patch.object(eta_client, 'get_receipt_status', return_value=None):
            receipts.reconcile_branch('150', self.admin)
        self.assertEqual(self.one('1').status, TaxReceipt.UNCERTAIN)   # inside the wait
        from apps.tax_invoicing.models import TaxReceiptAttempt
        TaxReceiptAttempt.objects.update(started_at=timezone.now() - dt.timedelta(hours=1))
        with mock.patch.object(eta_client, 'get_receipt_status', return_value=None):
            receipts.reconcile_branch('150', self.admin)
        self.assertEqual(self.one('1').status, TaxReceipt.ISSUED)
        self.assertEqual(self.one('1').uuid, uuid_before)

    def test_could_not_ask_changes_nothing(self):
        receipts.import_rows([row(1)])
        receipts.issue_next('150', self.accountant)
        with mock.patch.object(eta_client, 'submit_receipts', side_effect=eta_client.EtaUncertain('timeout')):
            receipts.submit_branch('150', self.admin, '150')
        with mock.patch.object(eta_client, 'get_receipt_status', side_effect=eta_client.EtaUncertain('down')):
            with self.assertRaises(services.TaxRuleError):
                receipts.reconcile_branch('150', self.admin)
        self.assertEqual(self.one('1').status, TaxReceipt.UNCERTAIN)

    def test_list_filters_by_date_and_reports_the_total(self):
        receipts.import_rows([row(1), row(2, day=dt.datetime(2026, 11, 2))])
        c = api(self.accountant)
        r = c.get('/api/tax-invoicing/receipts/?from=2026-11-02')
        self.assertEqual([x['docnumber'] for x in r.data], ['2'])
        self.assertEqual(r['X-Total-Count'], '1')
        self.assertEqual(c.get('/api/tax-invoicing/receipts/?from=nonsense').status_code, 400)

    def test_channels_seen_lists_what_arrived_with_its_rule(self):
        receipts.import_rows([row(1), row(2, channel='77')])
        by = {r['channel']: r for r in api(self.accountant).get('/api/tax-invoicing/receipts/channels/seen/').data}
        self.assertEqual((by['91']['mode'], by['91']['documents']), ('receipt', 1))
        self.assertEqual(by['77']['mode'], 'undecided')

    def test_summary_is_by_branch(self):
        receipts.import_rows([row(1), row(2, channel='77'), row(3, branch='160', channel='10')])
        by = {r['branch']: r for r in api(self.accountant).get('/api/tax-invoicing/receipts/summary/').data['branches']}
        self.assertEqual(by['150']['by_status'], {'ready': 1, 'held': 1})
        self.assertEqual(by['160']['by_status'], {'by_invoice': 1})

    @override_settings(RBAC_ENFORCEMENT='enforce')   # tests default to off, where the matrix refuses nobody
    def test_permissions(self):
        self.assertEqual(api(self.pharmacist).get('/api/tax-invoicing/receipts/summary/').status_code, 403)
        self.assertEqual(api(self.accountant).post('/api/tax-invoicing/receipts/branch/150/submit/', {}, format='json').status_code, 403)
        r = api(self.admin).post('/api/tax-invoicing/receipts/branch/150/submit/', {}, format='json')
        self.assertTrue(r.data['dry_run'])


class AgentAccessTests(Fixture, TestCase):
    """No anonymous path: the agent signs in with a dedicated account and also presents the token."""
    TOKEN = 't' * 40

    def setUp(self):
        self.build()

    def post(self, client, token=None):
        headers = {'HTTP_X_TAX_AGENT_TOKEN': token} if token else {}
        return client.post('/api/tax-invoicing/signing-agent/next/', {}, format='json', **headers)

    def test_anonymous_is_refused_even_with_the_token(self):
        with override_settings(TAX_SIGNING_AGENT_TOKEN=self.TOKEN):
            self.assertIn(self.post(APIClient(), self.TOKEN).status_code, (401, 403))

    def test_account_without_finalize_is_refused(self):
        with override_settings(TAX_SIGNING_AGENT_TOKEN=self.TOKEN):
            self.assertEqual(self.post(api(self.accountant), self.TOKEN).status_code, 403)

    def test_account_with_finalize_still_needs_the_token(self):
        with override_settings(TAX_SIGNING_AGENT_TOKEN=self.TOKEN):
            self.assertEqual(self.post(api(self.admin)).status_code, 403)
            self.assertEqual(self.post(api(self.admin), 'wrong').status_code, 403)
            ok = self.post(api(self.admin), self.TOKEN)
        self.assertEqual((ok.status_code, ok.data['job']), (200, None))

    def test_short_or_empty_server_token_never_matches(self):
        for value in ('', 'short'):
            with override_settings(TAX_SIGNING_AGENT_TOKEN=value):
                self.assertEqual(self.post(api(self.admin), value or 'x').status_code, 403)


class ReceiptBranchScopeTests(Fixture, TestCase):
    def setUp(self):
        self.build()
        from apps.users.models import RoleModuleAccess
        for action in ('view', 'create'):
            RoleModuleAccess.objects.get_or_create(role='pharmacist', module='tax_invoicing', action=action, defaults={'is_allowed': True})
        TaxChannelRule.objects.update_or_create(ptclassifcode='91', defaults={'mode': 'receipt'})
        receipts.import_rows([row(1, branch='OTHER'), row(2, branch=self.branch.softech_branch_id or 'T')])

    def test_branch_user_sees_only_their_branch(self):
        c = api(self.pharmacist)
        listed = c.get('/api/tax-invoicing/receipts/').data
        self.assertEqual({r['branch'] for r in listed}, {self.branch.softech_branch_id})
        summary = c.get('/api/tax-invoicing/receipts/summary/').data['branches']
        self.assertNotIn('OTHER', {r['branch'] for r in summary})
        other = TaxReceipt.objects.get(softech_branchcode='OTHER')
        self.assertEqual(c.get(f'/api/tax-invoicing/receipts/{other.pk}/').status_code, 404)
        self.assertEqual(c.post('/api/tax-invoicing/receipts/import/', {'branch': 'OTHER', 'date': '2026-11-01'}, format='json').status_code, 403)

    def test_channels_seen_counts_only_their_branch(self):
        seen = api(self.pharmacist).get('/api/tax-invoicing/receipts/channels/seen/').data
        self.assertEqual(sum(r['documents'] for r in seen), 1)

    def test_all_branch_role_sees_everything(self):
        self.assertEqual(len(api(self.accountant).get('/api/tax-invoicing/receipts/').data), 2)


class ReceiptGateTests(Fixture, TestCase):
    def test_flag_off_by_default_nothing_goes_out(self):
        self.build()
        with mock.patch('requests.post') as post:
            with self.assertRaises(services.TaxRuleError):
                receipts.submit_branch('150', self.admin, '150')
        post.assert_not_called()

    def test_seeded_channels_are_what_the_owner_stated_and_unconfirmed(self):
        rules = {r.ptclassifcode: r for r in TaxChannelRule.objects.all()}
        for code in ('91', '90', '12', '16'):
            self.assertEqual(rules[code].mode, 'receipt')
        self.assertEqual(rules['10'].mode, 'invoice')
        self.assertTrue(all(r.confirmed_at is None for r in rules.values()))


class SigningGateTests(TestCase):
    def test_default_signer_refuses(self):
        with self.assertRaises(signing.SigningUnavailable):
            signing.get_signer().sign('x')
        with self.assertRaises(signing.SigningUnavailable):
            signing.assert_ready_for_live()

    @override_settings(TAX_SIGNER_CLASS='apps.tax_invoicing.signing.MockSigner')
    def test_mock_signer_is_refused_outside_test_mode(self):
        with self.assertRaises(signing.SigningUnavailable):
            signing.assert_ready_for_live()

    @override_settings(TAX_SIGNER_CLASS='apps.tax_invoicing.signing.MockSigner', TAX_ALLOW_MOCK_SIGNER=True,
                       TAX_ETA_API_BASE_URL='https://api.invoicing.eta.gov.eg')
    def test_mock_signer_can_never_reach_production(self):
        with self.assertRaises(signing.SigningUnavailable):
            signing.assert_ready_for_live()
