"""
apps/tests/test_pos_contract_history.py — POS Speed Wave Task 4: read-only contract (تعاقد)
entry assist: per-contract config, patient autocomplete, last prescriptions (revalidated),
field-value suggestions and the approval-number reuse check. No SOFTECH access.
"""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.insurance import models as im
from apps.pos_orders import contract_history as ch
from apps.pos_orders.models import ContractEntryConfig, SoftechSalesOrder, SoftechSalesOrderLine
from .factories import make_branch, make_branch2, make_item, make_user

PC = '4474'


def _order(branch, personcode=PC, raw=None, day=date(2026, 10, 1), lines=()):
    o = SoftechSalesOrder.objects.create(
        branch=branch, softech_branchcode=branch.softech_branch_id, store_code='101',
        cust_branch_code=personcode, channel='contract', source_companies_raw=raw or {},
        doc_date=day)
    for item, qty in lines:
        SoftechSalesOrderLine.objects.create(
            order=o, item=item, softech_itemcode=item.softech_id, qty=qty,
            trans_price_total=Decimal('10.00') * qty)
    return o


def _insurance_rx(personcode=PC, name='أحمد علي', docdate=date(2026, 9, 1), item=None, qty=1):
    client = im.InsuranceClient.objects.create(name='جهة')
    sub = im.InsuranceSubClient.objects.create(client=client, name='فئة')
    claim = im.InsuranceClaim.objects.create(
        claim_number='C-%s-%s' % (docdate, personcode), subclient=sub,
        period_from=docdate, period_to=docdate)
    rx = im.InsuranceClaimPrescription.objects.create(
        claim=claim, softech_docnumber='9', softech_docdate=docdate,
        softech_personcode=personcode, patient_name=name, net_after=Decimal('55.00'))
    if item:
        im.InsuranceClaimLine.objects.create(
            prescription=rx, softech_itemcode=item.softech_id, item_name=item.name, quantity=qty)
    return rx


class EntryConfigTests(TestCase):
    def test_entry_config_global_default(self):
        cfg = ch.entry_config('9999')
        self.assertEqual(cfg['per_visit_columns'], ['roshettano', 'examdate'])
        self.assertEqual(cfg['approval_column'], 'roshettano')

    def test_entry_config_contract_override(self):
        ContractEntryConfig.objects.create(
            personcode=PC, per_visit_columns=['comment'], approval_column='comment')
        cfg = ch.entry_config(PC)
        self.assertEqual(cfg, {'per_visit_columns': ['comment'], 'approval_column': 'comment'})

    def test_config_rejects_unknown_column(self):
        with self.assertRaises(ValidationError):
            ContractEntryConfig(personcode='1', per_visit_columns=['nope'],
                                approval_column='roshettano').full_clean()
        with self.assertRaises(ValidationError):
            ContractEntryConfig(personcode='2', per_visit_columns=['comment'],
                                approval_column='nope').full_clean()


class PatientSuggestTests(TestCase):
    def setUp(self):
        self.b1, self.b2 = make_branch(), make_branch2()

    def test_patient_suggest_unions_sources_and_dedupes(self):
        _order(self.b1, raw={'patientname': 'أحمد علي', 'fileno': 'F1'}, day=date(2026, 10, 1))
        _insurance_rx(name='أحمد علي', docdate=date(2026, 9, 1))
        res = ch.patient_suggest(PC, 'احمد')
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['source'], 'pos')
        self.assertEqual(res[0]['last_date'], '2026-10-01')

    def test_dedupe_keeps_latest_insurance(self):
        _order(self.b1, raw={'patientname': 'أحمد علي'}, day=date(2026, 8, 1))
        _insurance_rx(name='احمد على', docdate=date(2026, 9, 1))
        res = ch.patient_suggest(PC, 'احمد')
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['source'], 'insurance')
        self.assertEqual(res[0]['fields'], {})

    def test_patient_suggest_arabic_variants(self):
        _order(self.b1, raw={'patientname': 'أحمد علي'})
        self.assertEqual(len(ch.patient_suggest(PC, 'احمد على')), 1)
        _order(self.b1, raw={'patientname': 'منى الهادى'}, day=date(2026, 10, 2))
        self.assertEqual(len(ch.patient_suggest(PC, 'مني الهادي')), 1)   # ى/ي folded
        _order(self.b1, raw={'patientname': 'فاطمة'}, day=date(2026, 10, 3))
        self.assertEqual(len(ch.patient_suggest(PC, 'فاطمه')), 1)        # ة/ه folded

    def test_patient_suggest_excludes_per_visit_fields(self):
        _order(self.b1, raw={'patientname': 'سارة', 'roshettano': 'R1',
                             'examdate': {'__dt__': '2026-10-01 00:00:00'},
                             'fileno': 'F9', 'membershipno': 'M1'})
        f = ch.patient_suggest(PC, 'سارة')[0]['fields']
        self.assertNotIn('roshettano', f)
        self.assertNotIn('examdate', f)
        self.assertNotIn('patientname', f)
        self.assertEqual(f['fileno'], 'F9')
        self.assertEqual(f['membershipno'], 'M1')

    def test_patient_suggest_scoped_to_contract(self):
        _order(self.b1, personcode='5555', raw={'patientname': 'أحمد علي'})
        _insurance_rx(personcode='5555', name='أحمد علي')
        self.assertEqual(ch.patient_suggest(PC, 'احمد'), [])


class HistoryTests(TestCase):
    def test_recent_prescriptions_revalidates(self):
        b = make_branch()
        item = make_item(name='Panadol', softech_id='CH1')
        _order(b, raw={'patientname': 'أحمد علي'}, lines=[(item, Decimal('2'))])
        _insurance_rx(name='أحمد علي', item=item, qty=1)
        cards = ch.recent_prescriptions(PC, 'احمد على', branch_id=b.id)
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]['source'], 'pos')          # newest first
        for c in cards:
            self.assertIn('summary', c['revalidated'])
            self.assertEqual(c['revalidated']['lines'][0]['status'], 'out_of_stock')
        self.assertEqual(cards[0]['total'], 20.0)
        self.assertEqual(cards[1]['total'], 55.0)

    def test_recent_prescriptions_unknown_itemcode_flagged_missing(self):
        rx = _insurance_rx(name='س')
        im.InsuranceClaimLine.objects.create(prescription=rx, softech_itemcode='ZZZ', quantity=1)
        cards = ch.recent_prescriptions(PC, 'س', branch_id=None)
        self.assertEqual(cards[0]['revalidated']['lines'][0]['status'], 'missing')


class FieldValueTests(TestCase):
    def test_field_values_rejects_unknown_column(self):
        with self.assertRaises(ValueError):
            ch.field_values(PC, 'password', '')

    def test_field_values_most_used_first(self):
        b = make_branch()
        for v in ('B', 'A', 'A', ''):
            _order(b, raw={'deptname': v})
        _order(b, personcode='1', raw={'deptname': 'A'})
        self.assertEqual(ch.field_values(PC, 'deptname', ''), ['A', 'B'])
        self.assertEqual(ch.field_values(PC, 'deptname', 'b'), ['B'])


class ApprovalTests(TestCase):
    def test_approval_reused_across_branches(self):
        b1, b2 = make_branch(), make_branch2()
        o1 = _order(b1, raw={'roshettano': 'R-77', 'patientname': 'منى'})
        o2 = _order(b2, raw={'roshettano': 'R-77'}, day=date(2026, 10, 3))
        res = ch.approval_reused(PC, 'R-77')
        self.assertEqual({r['order_id'] for r in res}, {o1.id, o2.id})
        res = ch.approval_reused(PC, 'R-77', exclude_order_id=o2.id)
        self.assertEqual([r['order_id'] for r in res], [o1.id])
        self.assertEqual(res[0]['branch_id'], b1.id)
        self.assertEqual(res[0]['patientname'], 'منى')
        self.assertEqual(ch.approval_reused(PC, 'other'), [])

    def test_approval_reused_blank_is_empty(self):
        _order(make_branch(), raw={'roshettano': ''})
        self.assertEqual(ch.approval_reused(PC, ''), [])
        self.assertEqual(ch.approval_reused(PC, '   '), [])

    def test_approval_uses_configured_column(self):
        ContractEntryConfig.objects.create(
            personcode=PC, per_visit_columns=['comment'], approval_column='comment')
        _order(make_branch(), raw={'comment': 'X1', 'roshettano': 'X1x'})
        self.assertEqual(len(ch.approval_reused(PC, 'X1')), 1)
        self.assertEqual(ch.approval_reused(PC, 'X1x'), [])


class ApiTests(TestCase):
    def test_contract_assist_requires_pos_permission(self):
        User = get_user_model()
        u = User.objects.create_user('noprofile', password='x')   # no active staff profile
        c = APIClient()
        c.force_authenticate(u)
        for url in ('config/?customer=1', 'patients/?customer=1&q=a', 'history/?customer=1&patient=a',
                    'field-values/?customer=1&column=fileno', 'approval-check/?customer=1&value=1'):
            self.assertEqual(c.get('/api/pos-orders/contract-assist/' + url).status_code, 403, url)

    def test_endpoints_happy_path(self):
        _, _, client = make_user('seller_ch', role='salesperson')
        b = make_branch()
        _order(b, raw={'patientname': 'أحمد علي', 'roshettano': 'R1', 'deptname': 'D'})
        base = '/api/pos-orders/contract-assist/'
        r = client.get(base + 'config/?customer=%s' % PC)
        self.assertEqual(r.data['approval_column'], 'roshettano')
        r = client.get(base + 'patients/?customer=%s&q=احمد' % PC)
        self.assertEqual(r.data['results'][0]['patientname'], 'أحمد علي')
        r = client.get(base + 'history/?customer=%s&patient=أحمد علي&branch=%s' % (PC, b.id))
        self.assertEqual(len(r.data['results']), 1)
        r = client.get(base + 'field-values/?customer=%s&column=deptname' % PC)
        self.assertEqual(r.data['results'], ['D'])
        self.assertEqual(client.get(base + 'field-values/?customer=%s&column=bad' % PC).status_code, 400)
        r = client.get(base + 'approval-check/?customer=%s&value=R1' % PC)
        self.assertTrue(r.data['reused'])
        self.assertEqual(len(r.data['matches']), 1)
