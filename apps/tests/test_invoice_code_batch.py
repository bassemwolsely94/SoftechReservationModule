"""
Invoice reader: the batch number (رقم التشغيلة) must never land in the supplier item-code
field (owner 2026-10-05). apps/invoices/ocr.separate_code_and_batch + both parse paths +
the learning guard + the repair command.
"""
import io

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.invoices import ocr


class SeparateTests(SimpleTestCase):
    def test_rules(self):
        S = ocr.separate_code_and_batch
        self.assertEqual(S('2442687', '2442687'), ('', '2442687', 'same'))      # copied into both
        self.assertEqual(S('AT24 0457', 'at240457'), ('', 'at240457', 'same'))  # spaces / case ignored
        self.assertEqual(S('240808A', '24080'), ('', '240808A', 'cut'))         # batch cut short
        self.assertEqual(S('AT240457', 'AT24'), ('', 'AT240457', 'cut'))
        self.assertEqual(S('87', '24426'), ('', '2442687', 'split'))            # one value split in two
        self.assertEqual(S('24', '07508'), ('', '0750824', 'split'))

    def test_real_code_left_alone(self):
        S = ocr.separate_code_and_batch
        self.assertEqual(S('643352', '2442687'), ('643352', '2442687', ''))     # code + different batch
        self.assertEqual(S('6594', ''), ('6594', '', ''))                       # only a code
        self.assertEqual(S('', '240808A'), ('', '240808A', ''))                 # only a batch
        self.assertEqual(S('12', '240808A'), ('12', '240808A', ''))             # 7-char batch: not a split

    def test_both_parse_paths_clean(self):
        rows = ocr.parse_lines('ايفيروسبان 100 ملى شراب | ماركيول | 25 | 2442687 | 2442687 | 08.2027 | 55 | 25 | 0 | 36.18 | 14 | 0 | 0')
        self.assertEqual((rows[0]['vendor_item_code'], rows[0]['batch_number']), ('', '2442687'))
        self.assertIn('التشغيلة', rows[0]['notes'])
        _h, lines = ocr.parse_structured({'lines': [
            {'item_name': 'AGNATIX SYRUP 60 ML', 'vendor_item_code': '240808A', 'batch_number': '24080', 'quantity': 3},
            {'item_name': 'REAL CODE ITEM', 'vendor_item_code': '643352', 'batch_number': '2442687', 'quantity': 1}]})
        self.assertEqual((lines[0]['vendor_item_code'], lines[0]['batch_number']), ('', '240808A'))
        self.assertEqual(lines[0]['read_as'], {'vendor_item_code': '240808A', 'batch_number': '24080'})
        self.assertEqual((lines[1]['vendor_item_code'], lines[1]['batch_number']), ('643352', '2442687'))

    def test_instructions_no_longer_teach_the_mistake(self):
        self.assertNotIn('| 2442687 | 2442687 |', ocr._OCR_INVOICE_PROMPT)
        self.assertNotIn('"AT240457", "DEG075"', ocr._OCR_JSON_PROMPT)
        self.assertIn('never copy', ocr._OCR_INVOICE_PROMPT)


class RepairCommandTests(TestCase):
    def test_dry_run_then_commit(self):
        from apps.branches.models import Branch
        from apps.catalog.models import Item
        from apps.invoices.models import InvoiceLine, SupplierInvoice, VendorItemMapping, VendorProfile
        v = VendorProfile.objects.create(name='PHARMA OVER SEAS', softech_personcode='565')
        item = Item.objects.create(softech_id='650001', name='IVYROSPAN SYRUP', is_active=True)
        inv = SupplierInvoice.objects.create(vendor=v, supplier_name='PO', branch=Branch.objects.create(
            softech_branch_id='100', name='HQ'))
        bad = InvoiceLine.objects.create(invoice=inv, item=item, vendor_item_code='87', batch_number='24426')
        good = InvoiceLine.objects.create(invoice=inv, item=item, vendor_item_code='643352', batch_number='2442687')
        m = VendorItemMapping.objects.create(vendor=v, raw_name_normalized='ivyrospan', vendor_item_code='2442687', item=item)
        call_command('fix_invoice_code_batch', stdout=io.StringIO())
        bad.refresh_from_db()
        self.assertEqual(bad.vendor_item_code, '87')                           # dry run writes nothing
        call_command('fix_invoice_code_batch', '--commit', stdout=io.StringIO())
        bad.refresh_from_db(); good.refresh_from_db(); m.refresh_from_db()
        self.assertEqual((bad.vendor_item_code, bad.batch_number), ('', '2442687'))
        self.assertIn('كود «87» تشغيلة «24426»', bad.notes)                    # the old values kept
        self.assertEqual((good.vendor_item_code, good.batch_number), ('643352', '2442687'))
        self.assertEqual(m.vendor_item_code, '')                               # learned batch-as-code cleared
        self.assertEqual(m.item_id, item.id)                                   # name learning kept
