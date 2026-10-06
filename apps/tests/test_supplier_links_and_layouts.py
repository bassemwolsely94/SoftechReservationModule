"""
Owner batch 2026-10-05 (2):
  • itemssuppliers mirror (catalog.ItemSupplierLink) — upsert / prune, ambiguous codes never
    resolved, availability + "supplier carries it" work without SOFTECH
  • supplier Excel column layouts — suggested once, remembered, imported directly after
"""
import io
import json

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.catalog import supplier_links as sl
from apps.supply import availability as av
from apps.supply import file_layouts as fl
from apps.supply.models import AvailabilityBatch, AvailabilityLine, SupplierFileLayout


class MirrorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.invoices.models import VendorProfile
        cls.a = Item.objects.create(softech_id='630001', name='CONCOR 5MG 30TAB', is_active=True)
        cls.b = Item.objects.create(softech_id='630002', name='CONCOR 10MG 30TAB', is_active=True)
        cls.c = Item.objects.create(softech_id='630003', name='CONCOR AM 5/5', is_active=True)
        cls.vendor = VendorProfile.objects.create(name='MEC', softech_personcode='156')

    def test_sync_upserts_and_prunes(self):
        out = sl.sync_from_rows([('630001', '156', 'C5', '1'), ('630002', '156', 'C10', '0'),
                                 ('630003', '156', 'X', None), ('630003', '260', 'X', None)])
        self.assertEqual((out['created'], out['with_code']), (4, 4))
        out = sl.sync_from_rows([('630001', '156', 'C5', '1'), ('630002', '156', 'C10B', '0')])
        self.assertEqual((out['updated'], out['deleted']), (1, 2))
        from apps.catalog.models import ItemSupplierLink
        link = ItemSupplierLink.objects.get(item_code='630002', supp_code='156')
        self.assertEqual((link.supp_item_code, link.item_id), ('C10B', self.b.id))
        self.assertTrue(ItemSupplierLink.objects.get(item_code='630001').is_main)

    def test_ambiguous_code_is_never_resolved(self):
        sl.sync_from_rows([('630001', '156', 'DUP', '0'), ('630002', '156', 'DUP', '0'),
                           ('630003', '156', 'ONE', '0')])
        self.assertEqual(sl.resolve_codes('156', ['DUP', 'ONE', 'NONE']), {'ONE': '630003'})

    def test_availability_uses_mirror_offline_and_marks_carried(self):
        sl.sync_from_rows([('630002', '156', 'C10', '0'), ('630001', '156', '', '0')])
        batch = AvailabilityBatch.objects.create(source='whatsapp', supplier=self.vendor)
        line = av.build_line(batch, 'كونكور عشرة code C10 qty 4', vendor_code='156')
        self.assertEqual((line.item_id, line.match_reason['via']), (self.b.id, 'vendor_code'))
        other = AvailabilityLine.objects.create(batch=batch, raw_text='concor 5', item=self.a, match_score=0.8,
                                                match_reason={'name_part': 'concor 5'})
        row = av.analyze_rows(batch, [other.pk])[0]
        self.assertTrue(row['carried'])
        self.assertEqual(row['trust'], 85)                               # 80 + 5 carried

    def test_link_code_keeps_one_item_per_code(self):
        sl.sync_from_rows([('630001', '156', 'K1', '0'), ('630002', '156', '', '0')])
        sl.link_code('156', '630002', 'K1')
        self.assertEqual(sl.resolve_codes('156', ['K1']), {'K1': '630002'})


def _xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile('offer.xlsx', buf.getvalue(),
                              content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


ROWS = [
    ['Pharma Overseas — available items', None, None, None, None, None],
    ['كود', 'اسم الصنف', 'الباركود', 'الكمية المتاحة', 'سعر الصيدلي', 'سعر الجمهور'],
    ['ZN25', 'Zinnat 250mg 10 tab', '6221234567890', 12, 95.5, 120],
    ['C5', 'Concor 5', None, 30, 40, 52],
    [None, 'إجمالي', None, None, None, None],
]


class LayoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.invoices.models import VendorProfile
        from .factories import make_user
        cls.zinnat = Item.objects.create(softech_id='630101', name='ZINNAT 250MG 10TAB', is_active=True,
                                         barcode='6221234567890')
        cls.vendor = VendorProfile.objects.create(name='PHARMA OVER SEAS', softech_personcode='565')
        cls.user, _, _ = make_user('op_layout', role='purchasing')

    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def test_header_detection_and_suggestion(self):
        self.assertEqual(fl.detect_header(ROWS), 1)
        self.assertEqual(fl.suggest(ROWS[1]), {'0': 'code', '1': 'name', '2': 'barcode', '3': 'qty',
                                               '4': 'price', '5': 'ignore'})
        self.assertIsNone(fl.detect_header([['Zinnat 250 10'], ['Concor 5 30']]))

    def test_first_file_asks_then_remembers(self):
        b1 = AvailabilityBatch.objects.create(source='excel', supplier=self.vendor)
        url = f'/api/supply/availability/{b1.id}/import-file/'
        r = self.c.post(url, {'file': _xlsx(ROWS)}, format='multipart')
        self.assertTrue(r.json()['needs_mapping'])
        self.assertEqual(b1.lines.count(), 0)                                   # nothing imported yet
        mapping = r.json()['suggested']
        r = self.c.post(url, {'file': _xlsx(ROWS), 'mapping': json.dumps(mapping), 'header_row': 1},
                        format='multipart')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['created'], 2)                                 # the total row skipped
        z = b1.lines.get(supplier_item_code='ZN25')
        self.assertEqual((z.item_id, z.match_reason['via']), (self.zinnat.id, 'barcode'))
        self.assertEqual((float(z.supplier_qty), float(z.price)), (12.0, 95.5))  # pharmacy price, not public
        self.assertEqual(SupplierFileLayout.objects.count(), 1)
        # second file from the same supplier → imported directly with the remembered layout
        b2 = AvailabilityBatch.objects.create(source='excel', supplier=self.vendor)
        r = self.c.post(f'/api/supply/availability/{b2.id}/import-file/', {'file': _xlsx(ROWS)}, format='multipart')
        self.assertEqual(r.json()['created'], 2)
        self.assertTrue(r.json()['layout']['remembered'])
        # forget → asked again
        self.c.post(f"/api/supply/availability/layouts/{r.json()['layout']['id']}/forget/")
        b3 = AvailabilityBatch.objects.create(source='excel', supplier=self.vendor)
        r = self.c.post(f'/api/supply/availability/{b3.id}/import-file/', {'file': _xlsx(ROWS)}, format='multipart')
        self.assertTrue(r.json()['needs_mapping'])

    def test_bad_mapping_rejected(self):
        b = AvailabilityBatch.objects.create(source='excel', supplier=self.vendor)
        url = f'/api/supply/availability/{b.id}/import-file/'
        for bad in ({'0': 'code'}, {'1': 'name', '2': 'name'}, {'1': 'name', '99': 'qty'}, {'1': 'bogus'}):
            r = self.c.post(url, {'file': _xlsx(ROWS), 'mapping': json.dumps(bad), 'header_row': 1},
                            format='multipart')
            self.assertEqual(r.status_code, 400, bad)

    def test_sheet_without_header_still_imports_as_text(self):
        b = AvailabilityBatch.objects.create(source='excel', supplier=self.vendor)
        r = self.c.post(f'/api/supply/availability/{b.id}/import-file/',
                        {'file': _xlsx([['Zinnat 250', 'متاح 5'], ['Concor 5', 'متاح 3']])}, format='multipart')
        self.assertEqual(r.json()['created'], 2)
