"""
apps/tests/test_manual_offer_detection.py

Phase-3 exec step 2 (READ-ONLY, no SOFTECH): detect historical MANUAL promos in
the sales mirror and classify them (exact-offer / cheapest-unit BXGY / unmapped).
Writes only ManualOfferMatch provenance rows; never touches SOFTECH or the invoice.
"""
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.offers.models import Offer, ManualOfferMatch
from apps.offers.detection import detect_manual_offers
from .factories import make_branch, make_item, make_user

_INV = [0]


def _item(code, pos_discp):
    it = make_item(name=code, softech_id=code)
    it.pos_discp = Decimal(str(pos_discp))
    it.save(update_fields=['pos_discp'])
    return it


def _invoice(customer, branch, doc='115'):
    _INV[0] += 1
    return PurchaseHistory.objects.create(
        customer=customer, softech_invoice_id=f'INV{_INV[0]}', branch=branch,
        doc_code=doc, total_amount=0, invoice_date=timezone.now())


def _phline(inv, item, qty, unit_price, disc_pct, line_total):
    return PurchaseHistoryLine.objects.create(
        purchase=inv, item=item, quantity=qty, unit_price=unit_price,
        list_price=unit_price, disc_customer_pct=disc_pct, line_total=line_total)


class DetectionTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.cust = Customer.objects.create(name='C', phone='0100')

    def test_exact_offer_match(self):
        it = _item('EX1', 50)
        offer = Offer.objects.create(name='Half', offer_type='percent', status='active',
                                     target_all=True, authorization_source='item_card')
        inv = _invoice(self.cust, self.branch)
        _phline(inv, it, 1, 100, disc_pct=50, line_total=50)   # 50% matches posdiscp 50
        counts = detect_manual_offers()
        self.assertEqual(counts['exact_offer'], 1)
        m = ManualOfferMatch.objects.get()
        self.assertEqual(m.pattern, 'exact_offer')
        self.assertEqual(m.confidence, 'high')
        self.assertEqual(m.matched_offer_id, offer.id)

    def test_bxgy_cheapest_fingerprint(self):
        dear = _item('DEAR', 0)
        cheap = _item('CHEAP', 0)
        inv = _invoice(self.cust, self.branch)
        _phline(inv, dear, 1, 100, disc_pct=0, line_total=100)     # dearer, no discount
        _phline(inv, cheap, 1, 60, disc_pct=100, line_total=0)     # cheaper, free (1+1)
        counts = detect_manual_offers()
        self.assertEqual(counts['bxgy_cheapest'], 1)
        m = ManualOfferMatch.objects.get()
        self.assertEqual(m.pattern, 'bxgy_cheapest')
        self.assertEqual(m.confidence, 'medium')
        self.assertEqual(m.detail.get('shape'), '1+1')

    def test_half_shape_detected(self):
        dear = _item('D2', 0); cheap = _item('C2', 0)
        inv = _invoice(self.cust, self.branch)
        _phline(inv, dear, 1, 100, disc_pct=0, line_total=100)
        _phline(inv, cheap, 1, 60, disc_pct=50, line_total=30)     # cheaper, half off
        detect_manual_offers()
        m = ManualOfferMatch.objects.get(item=cheap)
        self.assertEqual(m.detail.get('shape'), '1+½')

    def test_unmapped_discount(self):
        it = _item('U1', 0)
        inv = _invoice(self.cust, self.branch)
        _phline(inv, it, 1, 100, disc_pct=7, line_total=93)        # odd manual discount
        counts = detect_manual_offers()
        self.assertEqual(counts['unmapped_discount'], 1)
        self.assertEqual(ManualOfferMatch.objects.get().confidence, 'low')

    def test_only_scans_sales_not_returns(self):
        it = _item('R1', 0)
        inv = _invoice(self.cust, self.branch, doc='30')           # a return
        _phline(inv, it, 1, 100, disc_pct=50, line_total=50)
        counts = detect_manual_offers()
        self.assertEqual(counts['scanned'], 0)

    def test_idempotent(self):
        it = _item('ID1', 0)
        inv = _invoice(self.cust, self.branch)
        _phline(inv, it, 1, 100, disc_pct=7, line_total=93)
        detect_manual_offers()
        detect_manual_offers()   # re-run
        self.assertEqual(ManualOfferMatch.objects.count(), 1)

    def test_dry_run_persists_nothing(self):
        it = _item('DR1', 0)
        inv = _invoice(self.cust, self.branch)
        _phline(inv, it, 1, 100, disc_pct=7, line_total=93)
        detect_manual_offers(persist=False)
        self.assertEqual(ManualOfferMatch.objects.count(), 0)


class DetectionApiTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.cust = Customer.objects.create(name='C', phone='0100')
        it = _item('AP1', 0)
        inv = _invoice(self.cust, self.branch)
        _phline(inv, it, 1, 100, disc_pct=7, line_total=93)
        detect_manual_offers()

    def test_list_matches(self):
        _, _, client = make_user('det_user', role='pharmacist')
        r = client.get('/api/offers/manual-matches/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('summary', r.data)
        self.assertGreaterEqual(r.data['count'], 1)

    def test_run_detection_gated(self):
        _, _, viewer = make_user('det_viewer', role='viewer')
        r = viewer.post('/api/offers/detect-manual/', {}, format='json')
        self.assertEqual(r.status_code, 403)
        _, _, admin = make_user('det_admin', role='admin')
        r2 = admin.post('/api/offers/detect-manual/', {}, format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertIn('scanned', r2.data)
