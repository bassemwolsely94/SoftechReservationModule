"""S3 Task 1: the bulk EGS sheet's versions (doc 36) — storage, seed command, and the recon's source switch.
Every test works on a tiny workbook built here with the real sheet's DataEntry header and formulas, in a temp
folder (TAX_EGS_SHEET_DIR overridden): never the owner's 15 MB file."""
import datetime as dt
import hashlib
import io
import os
import shutil
import tempfile
from pathlib import Path

import openpyxl
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.tax_invoicing import egs_sheet, eta_recon
from apps.tax_invoicing.models import TaxAuditEvent, TaxEgsSheetVersion, TaxItemProfile

L_HEADER = 'VAT 0% "=1"\nVAT 14% "=0"'


def make_sheet(rows, path=None):
    """A workbook shaped like the owner's: DataEntry (16 columns, formulas L/N/O/P), two more sheets. `rows` are
    (A, B, C, G, I, J, K) tuples. Returns the bytes, and writes them to `path` when given."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'DataEntry'
    ws.append(['CodeType', 'ItemCode', 'CodeName', 'CodeName2Ar', 'Description', 'DescriptionAr', 'ActiveFrom',
               'ActiveTo', 'GPCItemLinked', 'EGSRelatedCode', 'VAT %', L_HEADER, None, 'Blacklist', 'VAT % in Value',
               'VAT Code'])
    for n, (a, b, c, g, i, j, k) in enumerate(rows, start=2):
        ws.append([a, b, c, None, c, None, g, None, i, j, k,
                   f'=IF(AND(K{n}=0%,A{n}="EGS",I{n}<>0,G{n}<>""),1,0)', None,
                   f'=IF(AND(A{n}="",G{n}=""), "1","0")', f'=K{n}*100', f'=IF(O{n}=0,"v003","v009")'])
    wb.create_sheet('GPC Bricks Cleaned')
    wb.create_sheet('ElRezeiky GPC Applied')
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    if path:
        Path(path).write_bytes(data)
    return data


D = dt.datetime(2025, 1, 1)
ROWS = [('EGS', 'EG-499336534-100', 'A', D, 10000000, 100, 0.14),         # coded, J stored as a number
        ('GS1', '6221000000001', 'B', D, 10000001, '0200', 0),             # coded, text J keeps its leading zero
        (None, 'EG-499336534-300', 'C', None, 0, 300, 0),                  # not coded
        ('EGS', 'EG-499336534-400', 'D', None, 0, 400, 0.14)]              # A without G: not coded


class _TempDirMixin:
    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp(prefix='egs_test_')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.store_dir = os.path.join(self.dir, 'store')
        o = override_settings(TAX_EGS_SHEET_DIR=Path(self.store_dir))
        o.enable()
        self.addCleanup(o.disable)


class ReadCountsTests(TestCase):
    def test_counts_coded_rows_and_itemcodes_as_text(self):
        counts = egs_sheet.read_counts(make_sheet(ROWS))
        self.assertEqual(counts['total_rows'], 4)
        self.assertEqual(counts['coded_rows'], 2)
        self.assertEqual(counts['coded_itemcodes'], ['0200', '100'])

    def test_a_different_header_is_refused(self):
        wb = openpyxl.load_workbook(io.BytesIO(make_sheet(ROWS)))
        wb['DataEntry']['K1'] = 'VAT'
        buf = io.BytesIO()
        wb.save(buf)
        with self.assertRaises(egs_sheet.SheetError):
            egs_sheet.read_counts(buf.getvalue())

    def test_a_workbook_without_dataentry_is_refused(self):
        wb = openpyxl.Workbook()
        buf = io.BytesIO()
        wb.save(buf)
        with self.assertRaises(egs_sheet.SheetError):
            egs_sheet.read_counts(buf.getvalue())


class StoreTests(_TempDirMixin, TestCase):
    def test_store_writes_the_file_and_the_row(self):
        data = make_sheet(ROWS)
        v = egs_sheet.store(data, source='seed', coded_rows=2, total_rows=4, coded_itemcodes=['100'])
        self.assertEqual(v.number, 1)
        self.assertEqual(v.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(v.size, len(data))
        self.assertEqual(egs_sheet.open_version(v), data)
        self.assertEqual(egs_sheet.latest(), v)
        self.assertTrue(os.path.isfile(os.path.join(self.store_dir, v.file_name)))

    def test_keeps_the_newest_ten_files_and_every_row(self):
        versions = [egs_sheet.store(make_sheet(ROWS[:1] * (n + 1)), source='build') for n in range(12)]
        self.assertEqual([v.number for v in versions], list(range(1, 13)))
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 12)
        on_disk = sorted(os.listdir(self.store_dir))
        self.assertEqual(on_disk, sorted(v.file_name for v in versions[2:]))
        with self.assertRaises(egs_sheet.SheetError):
            egs_sheet.open_version(versions[0])
        self.assertEqual(egs_sheet.latest().number, 12)

    def test_latest_is_none_with_no_versions(self):
        self.assertIsNone(egs_sheet.latest())


class SeedCommandTests(_TempDirMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.src = os.path.join(self.dir, 'owner.xlsx')
        make_sheet(ROWS, self.src)
        self.src_bytes = Path(self.src).read_bytes()

    def test_seed_stores_version_one_with_counts_and_is_audited(self):
        call_command('egs_sheet_seed', self.src, stdout=io.StringIO())
        v = TaxEgsSheetVersion.objects.get()
        self.assertEqual((v.number, v.source, v.coded_rows, v.total_rows), (1, 'seed', 2, 4))
        self.assertEqual(v.coded_itemcodes, ['0200', '100'])
        self.assertEqual((v.added, v.coded, v.skipped), ([], [], []))
        self.assertEqual(v.file_name and egs_sheet.open_version(v), self.src_bytes)
        ev = TaxAuditEvent.objects.get(action='egs_sheet_seed')
        self.assertEqual((ev.entity, ev.entity_id), ('egs_sheet', '1'))
        self.assertEqual(ev.after['coded_rows'], 2)
        self.assertEqual(Path(self.src).read_bytes(), self.src_bytes)      # the owner's file is never written

    def test_seed_refuses_when_a_version_exists(self):
        call_command('egs_sheet_seed', self.src, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command('egs_sheet_seed', self.src, stdout=io.StringIO())
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 1)

    def test_force_new_adds_the_next_version(self):
        call_command('egs_sheet_seed', self.src, stdout=io.StringIO())
        call_command('egs_sheet_seed', self.src, '--force-new', stdout=io.StringIO())
        self.assertEqual(list(TaxEgsSheetVersion.objects.order_by('number').values_list('number', flat=True)), [1, 2])

    def test_a_missing_or_wrong_file_is_refused(self):
        with self.assertRaises(CommandError):
            call_command('egs_sheet_seed', os.path.join(self.dir, 'nope.xlsx'), stdout=io.StringIO())
        bad = os.path.join(self.dir, 'bad.xlsx')
        openpyxl.Workbook().save(bad)
        with self.assertRaises(CommandError):
            call_command('egs_sheet_seed', bad, stdout=io.StringIO())
        self.assertFalse(TaxEgsSheetVersion.objects.exists())


class CodedItemsSourceTests(_TempDirMixin, TestCase):
    def test_without_a_version_the_workbook_import_rule_holds(self):
        TaxItemProfile.objects.create(softech_itemcode='SHEET', eta_code='EG-1-S', list_status='white')
        self.assertEqual(eta_recon.coded_items(), {'SHEET'})

    def test_with_a_version_its_coded_itemcodes_are_the_source(self):
        TaxItemProfile.objects.create(softech_itemcode='SHEET', eta_code='EG-1-S', list_status='white')
        egs_sheet.store(make_sheet(ROWS), source='seed', coded_itemcodes=['0200', '100'])
        egs_sheet.store(make_sheet(ROWS[:1]), source='build', coded_itemcodes=['0200', '100', '500'])
        self.assertEqual(eta_recon.coded_items(), {'0200', '100', '500'})
