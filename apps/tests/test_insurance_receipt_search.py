"""
«بحث برقم الروشتة» on مطالبات التأمين (apps/insurance/receipt_search.py + claims/find-receipt/):
where a SOFTECH receipt sits — every claim, active or excluded, how it came in — plus the
SOFTECH motalba cache. Read-only. Receipt numbers repeat across branches, so hits never merge.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.insurance import models as m
from apps.insurance.audit import record_audit
from apps.insurance.receipt_search import find_receipt

_n = iter(range(7000, 99999))
OCT = (date(2026, 10, 1), date(2026, 10, 31))


def _claim(name='جهة أ', **kw):
    c = m.InsuranceClient.objects.create(name=name)
    sub = m.InsuranceSubClient.objects.create(client=c, name='العاملين')
    return m.InsuranceClaim.objects.create(claim_number=f'MT-R-{next(_n)}', subclient=sub,
                                           period_from=OCT[0], period_to=OCT[1], **kw)


def _rx(claim, docno, branch='140', **kw):
    return m.InsuranceClaimPrescription.objects.create(
        claim=claim, softech_docnumber=docno, softech_branchcode=branch, softech_docdate=date(2026, 10, 12),
        patient_name='أحمد محمد علي حسن', net_after=Decimal('412.50'), **kw)


class FindReceiptTests(TestCase):
    def test_active_and_excluded_listed(self):
        a, b = _claim(softech_motalba_no='71'), _claim('جهة ب')
        _rx(a, '923035')
        old = _rx(b, '923035')
        m.InsuranceClaimExclusion.objects.create(prescription=old, reason='نقلت للمطالبة 97')
        res = find_receipt('923035')
        self.assertEqual(len(res), 1)
        apps = {x['claim_id']: x for x in res[0]['appearances']}
        self.assertTrue(apps[a.id]['active'])
        self.assertEqual(apps[a.id]['origin'], 'import')
        self.assertEqual(apps[a.id]['softech_motalba_no'], '71')
        self.assertFalse(apps[b.id]['active'])
        self.assertEqual(apps[b.id]['excluded_reason'], 'نقلت للمطالبة 97')
        self.assertEqual(res[0]['branch'], '140')
        self.assertEqual(res[0]['net'], '412.50')

    def test_same_number_two_branches_kept_apart(self):
        c = _claim()
        _rx(c, '5001', branch='140')
        _rx(_claim('جهة ب'), '5001', branch='160')
        res = find_receipt('5001')
        self.assertEqual(sorted(r['branch'] for r in res), ['140', '160'])
        self.assertTrue(all(len(r['appearances']) == 1 for r in res))

    def test_manual_rx_origin_and_exclusion(self):
        c = _claim()
        m.InsuranceClaimManualRx.objects.create(
            claim=c, softech_docnumber='8800', softech_branchcode='150', softech_docdate=date(2026, 10, 3),
            patient_name='منى', net_after=Decimal('90'), is_excluded=True, reason='روشتة متأخرة')
        res = find_receipt('8800')
        ap = res[0]['appearances'][0]
        self.assertEqual((ap['kind'], ap['origin'], ap['origin_reason'], ap['active']),
                         ('manual', 'manual', 'روشتة متأخرة', False))

    def test_detailed_manual_prescription_origin(self):
        c = _claim()
        _rx(c, '8801', is_manual=True, manual_reason='لم تُستورد')
        ap = find_receipt('8801')[0]['appearances'][0]
        self.assertEqual((ap['kind'], ap['origin'], ap['origin_reason']), ('rx', 'manual', 'لم تُستورد'))

    def test_resync_origin_from_audit(self):
        c = _claim()
        _rx(c, '7700')
        record_audit(c, 'resync_add', summary='x', target_type='prescription', target_ref='7700')
        self.assertEqual(find_receipt('7700')[0]['appearances'][0]['origin'], 'resync')

    def test_cache_only_hit(self):
        m.MotalbaCache.objects.create(personcode='P1', motalbano=69, branchcode='140', docnumber='6600',
                                      docdate=date(2026, 10, 5), doccode='115')
        res = find_receipt('6600')
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['appearances'], [])
        self.assertEqual(res[0]['softech'][0]['motalbano'], 69)

    def test_cache_joins_our_receipt(self):
        c = _claim()
        _rx(c, '6601')
        m.MotalbaCache.objects.create(personcode='P1', motalbano=70, branchcode='140', docnumber='6601',
                                      docdate=date(2026, 10, 5), doccode='115')
        res = find_receipt('6601')
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['softech'][0]['motalbano'], 70)

    def test_trimmed_and_branch_filter(self):
        _rx(_claim(), '4400', branch='140')
        _rx(_claim('جهة ب'), '4400', branch='160')
        self.assertEqual(len(find_receipt('  4400 ')), 2)
        self.assertEqual([r['branch'] for r in find_receipt('4400', branch='160')], ['160'])
        self.assertEqual(find_receipt('4401'), [])


class FindReceiptEndpointTests(TestCase):
    def test_endpoint_and_empty_400(self):
        _rx(_claim(), '3300')
        u = get_user_model().objects.create_user(username='rs', password='x', is_staff=True, is_superuser=True)
        api = APIClient(); api.force_authenticate(u)
        r = api.get('/api/insurance/claims/find-receipt/', {'docnumber': '3300'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['results'][0]['docnumber'], '3300')
        r = api.get('/api/insurance/claims/find-receipt/', {'docnumber': '  '})
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.json())

    def test_refused_without_insurance_module(self):
        from core.middleware import module_access
        from .factories import make_user
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        _, _, client = make_user('rs_pharm', role='pharmacist')
        r = client.get('/api/insurance/claims/find-receipt/', {'docnumber': '3300'})
        self.assertEqual(r.status_code, 403)
