"""
Phase-2 tests for the supplier-PUSH Availability Inbox (doc 24 §2/§3/§4/§12/§29/§32).

Covers the deterministic economics parser, content fingerprint + duplicate detection,
line ingestion with catalog resolution, vendor-scoped alias learning on confirmation,
and the batch API (paste create + add-line + confirm + matches).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.supply.availability import (
    parse_availability_line, compute_fingerprint, find_duplicate_batch,
    ingest_batch, confirm_line,
)
from apps.supply.models import AvailabilityBatch, AvailabilityLine

User = get_user_model()


# ── Deterministic economics parser ─────────────────────────────────────────────

class ParseAvailabilityLineTests(TestCase):
    def test_prompt_example_english_qty(self):
        p = parse_availability_line('Recormon 4000 available 10')
        self.assertEqual(p.name_part, 'Recormon 4000')
        self.assertEqual(p.supplier_qty, 10.0)

    def test_prompt_example_arabic_digits_and_keyword(self):
        p = parse_availability_line('كريون ٢٥٠٠٠ متاح ٢٠')
        self.assertIn('25000', p.name_part)         # Arabic-Indic digits folded
        self.assertIn('كريون', p.name_part)
        self.assertEqual(p.supplier_qty, 20.0)

    def test_prompt_example_dash_and_boxes(self):
        p = parse_availability_line('Cellcept 500 — 5 boxes')
        self.assertEqual(p.name_part, 'Cellcept 500')
        self.assertEqual(p.supplier_qty, 5.0)

    def test_prompt_example_no_quantity_is_allowed(self):
        p = parse_availability_line('Ozempic 1 mg موجود')
        self.assertIsNone(p.supplier_qty)           # missing qty is valid (§4)
        self.assertIn('Ozempic', p.name_part)

    def test_prompt_example_trailing_qty(self):
        p = parse_availability_line('Xgeva 120mg 3')
        self.assertEqual(p.name_part, 'Xgeva 120mg')
        self.assertEqual(p.supplier_qty, 3.0)

    def test_foc_n_plus_m(self):
        # «10+2» is a bonus: buy 10 get 2 (owner 2026-10-07) — not "10 available"
        p = parse_availability_line('Zinnat 250 10+2')
        self.assertIsNone(p.supplier_qty)
        self.assertEqual((p.bonus_buy, p.foc_qty, p.bonus_tiers), (10.0, 2.0, [[10.0, 2.0]]))
        self.assertEqual(p.name_part, 'Zinnat 250')

    def test_price_marker(self):
        p = parse_availability_line('Augmentin 1g 5 @ 90')
        self.assertEqual(p.price, 90.0)
        self.assertEqual(p.supplier_qty, 5.0)
        self.assertEqual(p.name_part, 'Augmentin 1g')

    def test_discount_percent(self):
        p = parse_availability_line('Concor 5 10 15%')
        self.assertEqual(p.discount_pct, 15.0)
        self.assertEqual(p.supplier_qty, 10.0)

    def test_foc_word_and_currency(self):
        p = parse_availability_line('Nexium 20 +2 foc @ 100 egp')
        self.assertEqual(p.foc_qty, 2.0)
        self.assertEqual(p.price, 100.0)
        self.assertEqual(p.bonus_buy, 20.0)
        self.assertNotIn('foc', p.name_part.lower())    # keyword stripped from name

    def test_expiry_extracted(self):
        p = parse_availability_line('Lipitor 20 5 exp 06/2026')
        self.assertEqual(p.expiry, '06/2026')
        self.assertEqual(p.supplier_qty, 5.0)


# ── Fingerprint + duplicate detection ──────────────────────────────────────────

class FingerprintTests(TestCase):
    def test_fingerprint_ignores_whitespace_and_digit_script(self):
        a = compute_fingerprint('Recormon 4000  available 10')
        b = compute_fingerprint('recormon 4000 available 10')
        self.assertEqual(a, b)
        self.assertNotEqual(a, compute_fingerprint('something else'))

    def test_find_duplicate_batch_warns_not_blocks(self):
        fp = compute_fingerprint('Item A 5\nItem B 3')
        b1 = AvailabilityBatch.objects.create(source='whatsapp', raw_fingerprint=fp)
        dup = find_duplicate_batch(fp)
        self.assertEqual(dup.id, b1.id)
        self.assertIsNone(find_duplicate_batch(compute_fingerprint('unrelated content')))


# ── Ingestion + vendor-scoped alias learning ───────────────────────────────────

class IngestionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        cls.item = Item.objects.create(softech_id='400001', name='RECORMON 4000 IU', is_active=True)

    def test_ingest_batch_creates_lines_with_economics_and_match(self):
        batch = AvailabilityBatch.objects.create(source='whatsapp')
        raw = 'Recormon 4000 available 10\nTotallyUnknownXyz 3'
        lines = ingest_batch(batch, raw)
        self.assertEqual(len(lines), 2)
        recormon = batch.lines.get(raw_text__startswith='Recormon')
        self.assertEqual(recormon.item_id, self.item.id)      # auto-matched
        self.assertEqual(float(recormon.supplier_qty), 10.0)
        self.assertFalse(recormon.is_unmatched)
        unknown = batch.lines.get(raw_text__startswith='Totally')
        self.assertTrue(unknown.is_unmatched)

    def test_confirm_line_learns_vendor_scoped_alias(self):
        from apps.catalog.models import Item, ItemAlias
        from apps.invoices.models import VendorProfile
        vendor = VendorProfile.objects.create(name='PHARMA OVER SEAS', softech_personcode='565')
        batch = AvailabilityBatch.objects.create(source='whatsapp', supplier=vendor,
                                                 supplier_name='PHARMA OVER SEAS')
        line = AvailabilityLine.objects.create(batch=batch, raw_text='ريكورمون 4000', is_unmatched=True)
        confirm_line(line, self.item, vendor_code='565')
        line.refresh_from_db()
        self.assertTrue(line.is_confirmed)
        self.assertEqual(line.item_id, self.item.id)
        # The vendor-scoped alias now exists for supplier 565.
        self.assertTrue(ItemAlias.objects.filter(item=self.item, vendor_code='565').exists())


# ── API ─────────────────────────────────────────────────────────────────────────

class AvailabilityApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from .factories import make_user
        cls.item = Item.objects.create(softech_id='410001', name='OZEMPIC 1MG', is_active=True)
        # Endpoints are RBAC-gated (purchasing/view + purchasing/edit) since Phase 4.
        cls.user, _, _ = make_user('op_purchasing', role='purchasing')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_create_batch_from_paste_ingests_lines(self):
        resp = self.client.post('/api/supply/availability/', {
            'source': 'whatsapp', 'supplier_name': 'Ibn Sina',
            'raw_content': 'Ozempic 1mg 3\nUnknownThing 5',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertEqual(len(data['lines']), 2)
        self.assertIn('duplicate_of', data)
        ozempic = next(l for l in data['lines'] if l['raw_text'].startswith('Ozempic'))
        self.assertEqual(ozempic['item'], self.item.id)
        self.assertEqual(float(ozempic['supplier_qty']), 3.0)

    def test_duplicate_import_is_flagged_not_blocked(self):
        payload = {'source': 'whatsapp', 'raw_content': 'Ozempic 1mg 3'}
        r1 = self.client.post('/api/supply/availability/', payload, format='json')
        r2 = self.client.post('/api/supply/availability/', payload, format='json')
        self.assertEqual(r2.status_code, 201)                 # NOT blocked (§32)
        self.assertEqual(r2.json()['duplicate_of'], r1.json()['id'])

    def test_add_line_and_confirm_match(self):
        batch = AvailabilityBatch.objects.create(source='whatsapp')
        # add a line
        r = self.client.post(f'/api/supply/availability/{batch.id}/add-line/',
                             {'raw_text': 'ozempic 1mg 4'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        line_id = r.json()['id']
        # confirm it against the catalog item
        r2 = self.client.patch(f'/api/supply/availability/{batch.id}/lines/{line_id}/',
                              {'item': self.item.id, 'is_confirmed': True}, format='json')
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertTrue(r2.json()['is_confirmed'])

    def test_line_matches_endpoint(self):
        batch = AvailabilityBatch.objects.create(source='whatsapp')
        line = AvailabilityLine.objects.create(batch=batch, raw_text='ozempic 1mg')
        r = self.client.get(f'/api/supply/availability/{batch.id}/lines/{line.id}/matches/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(m['item_id'] == self.item.id for m in r.json()))

    def test_check_duplicate_endpoint(self):
        r = self.client.post('/api/supply/availability/check-duplicate/',
                             {'raw_content': 'nothing here yet'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()['duplicate_of'])
