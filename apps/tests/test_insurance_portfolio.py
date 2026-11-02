"""
«تقارير المطالبات» (apps/insurance/portfolio.py): selection by period overlap, gross
profit from SOFTECH sale-time cost, patient share, per-category GP, the value bridge
and receipts moved between motalbas, plus the JSON / Excel endpoint.
"""
import io
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.insurance import models as m
from apps.insurance.portfolio import build_report, select_claims
from apps.stock_audit.models import StockLedgerLine

_n = iter(range(5000, 99999))


def _sub(name):
    c = m.InsuranceClient.objects.create(name=name)
    return m.InsuranceSubClient.objects.create(client=c, name='العاملين')


def _claim(sub, start, end, **kw):
    return m.InsuranceClaim.objects.create(claim_number=f'MT-P-{next(_n)}', subclient=sub,
                                           period_from=start, period_to=end, **kw)


def _rx(claim, *, net, softech_net=None, lines=(), docno=None, branch='160'):
    rx = m.InsuranceClaimPrescription.objects.create(
        claim=claim, softech_docnumber=str(docno or next(_n)), softech_branchcode=branch,
        softech_docdate=claim.period_from, patient_name=f'مريض {next(_n)}', net_after=Decimal(net),
        softech_net=Decimal(softech_net if softech_net is not None else net))
    for code, cat, gross, lnet in lines:
        m.InsuranceClaimLine.objects.create(prescription=rx, softech_itemcode=code, item_category=cat,
                                            line_total=Decimal(gross), net_amount=Decimal(lnet))
    return rx


def _sold(rx, code, qty, cost, total, user='1509'):
    StockLedgerLine.objects.create(branchcode=rx.softech_branchcode, doccode='115',
                                   docnumber=int(rx.softech_docnumber), docdate=rx.softech_docdate,
                                   itemcode=code, transqty=qty, newcostprice=cost, transprice_total=total,
                                   usercode=user)


class PortfolioTests(TestCase):
    def setUp(self):
        self.sub = _sub('جهة أ')
        self.oct = _claim(self.sub, date(2026, 10, 1), date(2026, 10, 31),
                          final_net_after=Decimal('200'), final_gross_before=Decimal('240'),
                          final_local_before=Decimal('120'), final_imported_before=Decimal('120'))
        self.rx1 = _rx(self.oct, net=100, lines=[('A', 'local', 120, 100)])
        self.rx2 = _rx(self.oct, net=100, softech_net=90, lines=[('B', 'imported', 120, 100)])
        _sold(self.rx1, 'A', 1, 70, 100)
        _sold(self.rx2, 'B', 2, 30, 100)          # receipt 100 in SOFTECH, insurer pays 90 → patient 10

    def test_period_overlap_selection(self):
        _claim(self.sub, date(2026, 9, 1), date(2026, 9, 30))
        _claim(self.sub, date(2026, 9, 27), date(2026, 10, 2))
        got = select_claims(date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(len(got), 2)               # October + the one spanning into October

    def test_gp_patient_share_and_categories(self):
        r = build_report([self.oct])
        row = r['motalbas'][0]
        self.assertEqual(row['cost'], 130.0)        # 1×70 + 2×30
        self.assertEqual(row['patient_share'], 10.0)
        self.assertEqual(row['revenue'], 210.0)
        self.assertEqual(row['gp'], 80.0)
        self.assertEqual((row['local_gp'], row['imported_gp']), (30.0, 40.0))
        self.assertEqual(r['sellers'][0]['usercode'], '1509')
        self.assertEqual(r['branches'][0]['rx'], 2)

    def test_value_bridge_balances_and_counts_moves(self):
        rx3 = _rx(self.oct, net=50)
        m.InsuranceClaimExclusion.objects.create(prescription=rx3, reason='تخصيص خاطئ ← جهة ب')
        other = _claim(_sub('جهة ب'), date(2026, 10, 1), date(2026, 10, 31), final_net_after=Decimal('50'))
        m.InsuranceClaimManualRx.objects.create(
            claim=other, softech_docnumber=rx3.softech_docnumber, softech_branchcode='160',
            softech_docdate=date(2026, 10, 5), patient_name='منقول', net_after=Decimal('50'))
        r = build_report([self.oct, other])
        a = next(x for x in r['motalbas'] if x['claim_id'] == self.oct.pk)['bridge']
        self.assertEqual((a['import_net'], a['excluded_count'], a['wrong_allocation']), (250.0, 1, 1))
        self.assertEqual(a['other_adjustments'], 0.0)          # 250 − 50 = 200 = final
        b = next(x for x in r['motalbas'] if x['claim_id'] == other.pk)['bridge']
        self.assertEqual((b['from_other_count'], b['from_other_net']), (1, 50.0))
        self.assertEqual(r['moves'][0]['from_claims'], [self.oct.claim_number])

    def test_endpoint_json_order_and_excel(self):
        u = get_user_model().objects.create_user(username='p', password='x', is_staff=True, is_superuser=True)
        api = APIClient(); api.force_authenticate(u)
        later = _claim(self.sub, date(2026, 10, 10), date(2026, 10, 20))
        r = api.get('/api/insurance/portfolio/', {'from': '2026-10-01', 'to': '2026-10-31',
                                                   'order': f'{later.pk},{self.oct.pk}'})
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual([x['claim_id'] for x in r.json()['motalbas']], [later.pk, self.oct.pk])
        x = api.get('/api/insurance/portfolio/', {'from': '2026-10-01', 'to': '2026-10-31', 'format': 'xlsx',
                                                   'group_by_client': '1'})
        self.assertEqual(x.status_code, 200)
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(x.content))
        self.assertIn('جسر القيمة', wb.sheetnames)
        self.assertIn('البائعون', wb.sheetnames)


class PortfolioAccessTests(TestCase):
    """The claims report compares every branch's motalbas and gross profit — owner decision B-1:
    cross-branch money boards are for all-branch roles only (canary sweep, 2026-11-02)."""

    def setUp(self):
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        from .factories import make_branch, make_user
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        for role in ('pharmacist', 'supervisor'):
            RoleModuleAccess.objects.create(role=role, module='insurance', action='view', is_allowed=True)
        _, _, self.branch_c = make_user('pf_pharm', role='pharmacist', branch=make_branch())
        _, _, self.sup_c = make_user('pf_sup', role='supervisor', access_all=True)

    def test_branch_user_refused(self):
        r = self.branch_c.get('/api/insurance/portfolio/')
        self.assertEqual(r.status_code, 403)

    def test_all_branch_user_allowed(self):
        self.assertEqual(self.sup_c.get('/api/insurance/portfolio/').status_code, 200)
