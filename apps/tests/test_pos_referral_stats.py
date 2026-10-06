"""
apps/tests/test_pos_referral_stats.py — referring-doctor performance aggregation.

Committed sales grouped by referral doctor; drafts / cancellations / no-doctor excluded.
"""
from decimal import Decimal
from django.test import TestCase

from apps.pos_orders.models import SoftechSalesOrder
from .factories import make_branch, make_user


def _order(doctor_name='', doctor_code='', net='100', pic='P1',
           status=SoftechSalesOrder.STATUS_PUSHED, branch=None):
    br = branch or make_branch()
    return SoftechSalesOrder.objects.create(
        branch=br, softech_branchcode=br.softech_branch_id, store_code='130', channel='cash',
        status=status, referral_doctor_name=doctor_name, referral_doctor_code=doctor_code,
        doc_value=Decimal(net), softech_pic=pic)


class ReferralStatsTests(TestCase):
    def setUp(self):
        _, _, self.client_api = make_user('ref_user', role='pharmacist')

    def test_groups_by_doctor(self):
        _order('Dr Ali', 'D1', '100', pic='PA')
        _order('Dr Ali', 'D1', '200', pic='PB')       # same doctor, different patient
        _order('Dr Sara', 'D2', '50', pic='PC')
        r = self.client_api.get('/api/pos-orders/referral-stats/')
        self.assertEqual(r.status_code, 200)
        by = {x['doctor_code']: x for x in r.data['results']}
        self.assertEqual(by['D1']['orders'], 2)
        self.assertEqual(by['D1']['total_net'], 300.0)
        self.assertEqual(by['D1']['patients'], 2)
        self.assertEqual(by['D2']['orders'], 1)
        self.assertEqual(r.data['summary']['doctors'], 2)
        self.assertEqual(r.data['summary']['orders'], 3)

    def test_excludes_no_doctor_and_drafts(self):
        _order('', '', '100')                                            # no doctor
        _order('Dr Ali', 'D1', '100', status=SoftechSalesOrder.STATUS_DRAFT)   # draft
        _order('Dr Ali', 'D1', '100', status=SoftechSalesOrder.STATUS_CANCELLED)
        r = self.client_api.get('/api/pos-orders/referral-stats/')
        self.assertEqual(r.data['results'], [])
        self.assertEqual(r.data['summary']['orders'], 0)

    def test_ranked_by_orders(self):
        for i in range(3):
            _order('Dr Ali', 'D1', '10', pic=f'A{i}')
        _order('Dr Sara', 'D2', '10', pic='S0')
        r = self.client_api.get('/api/pos-orders/referral-stats/')
        self.assertEqual(r.data['results'][0]['doctor_code'], 'D1')   # most orders first
