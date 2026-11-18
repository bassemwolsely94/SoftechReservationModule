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
from unittest import mock

import openpyxl
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl.styles import Font
from openpyxl.worksheet.table import Table

from apps.tax_invoicing import egs_sheet, eta_recon
from apps.tax_invoicing.models import (EtaCodeUsage, TaxAuditEvent, TaxCodingDecision, TaxEgsSheetVersion,
                                      TaxIssuerProfile, TaxItemProfile)

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
        with self.captureOnCommitCallbacks(execute=True):
            versions = [egs_sheet.store(make_sheet(ROWS[:1] * (n + 1)), source='build') for n in range(12)]
        self.assertEqual([v.number for v in versions], list(range(1, 13)))
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 12)
        on_disk = sorted(os.listdir(self.store_dir))
        self.assertEqual(on_disk, sorted(v.file_name for v in versions[2:]))
        with self.assertRaises(egs_sheet.SheetError):
            egs_sheet.open_version(versions[0])
        self.assertEqual(egs_sheet.latest().number, 12)

    def test_no_file_is_pruned_before_the_commit(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            for n in range(12):
                egs_sheet.store(make_sheet(ROWS[:1] * (n + 1)), source='build')
        self.assertEqual(len(os.listdir(self.store_dir)), 12)
        self.assertTrue(callbacks)

    def test_a_rolled_back_store_keeps_every_old_file_and_leaves_no_new_one(self):
        with self.captureOnCommitCallbacks(execute=True):
            for n in range(10):
                egs_sheet.store(make_sheet(ROWS[:1] * (n + 1)), source='build')
        before = sorted(os.listdir(self.store_dir))
        version = None
        with self.assertRaises(RuntimeError):
            with self.captureOnCommitCallbacks(execute=True):
                try:
                    with transaction.atomic():
                        version = egs_sheet.store(make_sheet(ROWS), source='build')
                        raise RuntimeError('audit failed')
                except RuntimeError:
                    egs_sheet.discard_file(version)
                    raise
        self.assertEqual(sorted(os.listdir(self.store_dir)), before)
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 10)

    def test_a_formula_in_j_is_not_an_itemcode(self):
        wb = openpyxl.load_workbook(io.BytesIO(make_sheet(ROWS)))
        wb['DataEntry']['J2'] = '=1+1'          # no cached value: reads as empty, never as the formula text
        buf = io.BytesIO()
        wb.save(buf)
        counts = egs_sheet.read_counts(buf.getvalue())
        self.assertNotIn('=1+1', counts['coded_itemcodes'])
        self.assertEqual(counts['total_rows'], 3)

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

    def test_an_audit_failure_rolls_back_and_keeps_every_old_file(self):
        with self.captureOnCommitCallbacks(execute=True):
            for n in range(10):
                egs_sheet.store(make_sheet(ROWS[:1] * (n + 1)), source='build')
        before = sorted(os.listdir(self.store_dir))
        with mock.patch('apps.tax_invoicing.management.commands.egs_sheet_seed.audit',
                        side_effect=RuntimeError('audit down')):
            with self.assertRaises(RuntimeError), self.captureOnCommitCallbacks(execute=True):
                call_command('egs_sheet_seed', self.src, '--force-new', stdout=io.StringIO())
        self.assertEqual(sorted(os.listdir(self.store_dir)), before)
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 10)
        self.assertFalse(TaxAuditEvent.objects.filter(action='egs_sheet_seed').exists())

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

    def test_an_empty_version_is_logged_and_counts_nothing_as_coded(self):
        egs_sheet.store(make_sheet(ROWS[:1]), source='build', coded_itemcodes=[])
        with self.assertLogs('apps.tax_invoicing.eta_recon', level='WARNING'):
            self.assertEqual(eta_recon.coded_items(), set())


# ── S3 Task 2: build + checks ──────────────────────────────────────────────────────────────────

def _wb(data):
    return openpyxl.load_workbook(io.BytesIO(data))


def _row_values(ws, n):
    return [ws.cell(n, c).value for c in range(1, 17)]


def _save(wb):
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class _BuildMixin(_TempDirMixin):
    """Version 1 = make_sheet(ROWS) (+ a table and an autofilter over A1:P5), then items with codes on ETA."""
    def setUp(self):
        super().setUp()
        TaxIssuerProfile.objects.create(pk=1, tax_id='499-336-534')
        self.seed(self.sheet_bytes())

    def sheet_bytes(self, rows=ROWS, table=True, trailing=0):
        wb = _wb(make_sheet(rows))
        ws = wb['DataEntry']
        last = len(rows) + 1
        for n in range(last + 1, last + 1 + trailing):      # empty rows carrying only the formulas
            ws[f'L{n}'] = f'=IF(AND(K{n}=0%,A{n}="EGS",I{n}<>0,G{n}<>""),1,0)'
            ws[f'P{n}'] = f'=IF(O{n}=0,"v003","v009")'
        if table:
            ws.add_table(Table(displayName='DataEntryTable', ref=f'A1:P{last}'))
        ws.auto_filter.ref = f'A1:P{last}'
        for c in range(1, 17):
            ws.cell(last, c).font = Font(bold=True)          # the row above an appended row
        ws.cell(last, 7).number_format = 'mm-dd-yy'
        return _save(wb)

    def seed(self, data):
        counts = egs_sheet.read_counts(data)
        self.held = egs_sheet.store(data, source='seed', **counts)
        self.held_bytes = data

    def profile(self, code, *, status='approved', env='production', code_type='EGS', eta_code=None, gpc='',
                treatment='taxable', rate=14, confirmed=True, decision='code', brick='', names=None):
        p = TaxItemProfile.objects.create(
            softech_itemcode=code, coding_status=status, coding_env=env, code_type=code_type,
            eta_code=eta_code if eta_code is not None else (f'EG-499336534-{code}' if code_type == 'EGS' else ''),
            gpc_code=gpc, item_name=f'ITEM {code}', item_name_ar=f'صنف {code}', tax_treatment=treatment,
            vat_rate=rate, treatment_confirmed_at=timezone.now() if confirmed else None)
        if decision is not None:
            TaxCodingDecision.objects.create(profile=p, decision=decision, brick=brick, **(names or {}))
        return p

    def usage(self, code, item_code, *, code_type='EGS', gpc='10000044', status='Approved',
              active_from=dt.date(2026, 3, 1), name='ETA NAME'):
        return EtaCodeUsage.objects.create(system='production', code_type=code_type, item_code=item_code,
                                           code_name=name, active_from=active_from, status=status, gpc=gpc,
                                           itemcode=code)

    def build(self, **kw):
        with self.captureOnCommitCallbacks(execute=True):
            return egs_sheet.build(None, **kw)


class BuildTests(_BuildMixin, TestCase):
    def test_codes_an_existing_uncoded_row(self):
        self.profile('300', brick='10000043', names={'code_name': 'CN', 'code_name_ar': 'اسم', 'description': 'DS',
                                                      'description_ar': 'وصف'})
        v = self.build(note='first')
        self.assertIsInstance(v, TaxEgsSheetVersion)
        self.assertEqual((v.number, v.source, v.coded, v.added), (2, 'build', ['300'], []))
        ws = _wb(egs_sheet.open_version(v))['DataEntry']
        r = _row_values(ws, 4)
        self.assertEqual(r[:11], ['EGS', 'EG-499336534-300', 'CN', 'اسم', 'DS', 'وصف',
                                  dt.datetime(dt.date.today().year, 1, 1), None, 10000043, 300, 0.14])
        self.assertEqual(r[11:], [0, None, '0', 14, 'v009'])            # the formulas' values, not formulas
        self.assertEqual((v.coded_rows, v.total_rows), (3, 4))
        self.assertEqual(v.coded_itemcodes, ['0200', '100', '300'])
        ev = TaxAuditEvent.objects.get(action='egs_sheet_built')
        self.assertEqual((ev.entity, ev.entity_id, ev.reason), ('egs_sheet', '2', 'first'))
        self.assertEqual(ev.after['coded'], ['300'])

    def test_carries_coded_rows_untouched(self):
        self.profile('300', brick='10000043')
        self.profile('100', brick='10000043', rate=0, treatment='exempt')    # coded in the sheet and on ETA
        v = self.build()
        o, n = _wb(self.held_bytes)['DataEntry'], _wb(egs_sheet.open_version(v))['DataEntry']
        for row in (2, 3, 5):
            self.assertEqual(_row_values(n, row)[:11], _row_values(o, row)[:11])
        # L/N/O/P keep their effective value, written as a value: 100 (EGS, 14%), 0200 (GS1, 0%), 400 (A, no G)
        self.assertEqual([_row_values(n, row)[11:] for row in (2, 3, 5)],
                         [[0, None, '0', 14, 'v009'], [0, None, '0', 0, 'v003'], [0, None, '0', 14, 'v009']])
        self.assertEqual((v.coded, v.added), (['300'], []))
        self.assertEqual(n.max_row, o.max_row)

    def test_appends_a_missing_item_inside_the_table_with_the_row_style(self):
        self.usage('500', 'EG-499336534-500')
        self.profile('500', status='missing', env='', decision=None, treatment='exempt', rate=0)
        v = self.build()
        self.assertEqual((v.added, v.coded), (['500'], []))
        ws = _wb(egs_sheet.open_version(v))['DataEntry']
        r = _row_values(ws, 6)
        self.assertEqual(r[:11], ['EGS', 'EG-499336534-500', 'ETA NAME', 'ETA NAME', 'ETA NAME', 'ETA NAME',
                                  dt.datetime(2026, 3, 1), None, 10000044, 500, 0])
        self.assertEqual(r[11:], [1, None, '0', 0, 'v003'])
        self.assertTrue(ws.cell(6, 1).font.bold)
        self.assertEqual(ws.cell(6, 7).number_format, 'mm-dd-yy')
        self.assertEqual(ws.tables['DataEntryTable'].ref, 'A1:P6')
        self.assertEqual(ws.auto_filter.ref, 'A1:P6')
        self.assertEqual((v.coded_rows, v.total_rows), (3, 5))

    def test_appends_after_the_last_item_row_over_trailing_formula_rows(self):
        TaxEgsSheetVersion.objects.all().delete()
        self.seed(self.sheet_bytes(trailing=3, table=False))
        self.profile('500', brick='10000043')
        self.profile('501', brick='10000043')
        v = self.build()
        ws = _wb(egs_sheet.open_version(v))['DataEntry']
        self.assertEqual((ws['J6'].value, ws['J7'].value), (500, 501))
        self.assertEqual([ws[f'{c}7'].value for c in 'LNOP'], [0, '0', 14, 'v009'])
        self.assertEqual(ws.auto_filter.ref, 'A1:P7')

    def test_keep_out_is_excluded(self):
        self.profile('300', brick='10000043', decision='keep_out')
        self.usage('600', 'EG-499336534-600')
        self.profile('600', status='missing', env='', decision='keep_out')
        self.assertEqual(egs_sheet.candidates(), [])
        self.assertEqual(self.build(), self.held)

    def test_unconfirmed_vat_and_missing_brick_are_skipped_with_a_reason(self):
        self.profile('300', brick='10000043', confirmed=False)
        self.profile('500')                                     # no brick anywhere
        self.profile('501', brick='10000043', treatment='zero_rated', rate=0)
        self.profile('502', brick='10000043')
        v = self.build()
        self.assertEqual(v.added, ['502'])
        why = {s['itemcode']: s['why'] for s in v.skipped}
        self.assertEqual(set(why), {'300', '500', '501'})
        self.assertIn('الضريبية', why['300'])
        self.assertIn('GPC', why['500'])
        self.assertIn('الضريبية', why['501'])
        ws = _wb(egs_sheet.open_version(v))['DataEntry']
        self.assertEqual([ws.cell(n, 10).value for n in range(2, ws.max_row + 1)], [100, '0200', 300, 400, 502])
        self.assertIsNone(ws['A4'].value)

    def test_preprod_and_unapproved_codes_are_not_candidates(self):
        self.profile('300', brick='10000043', env='preprod')
        self.profile('500', brick='10000043', status='pending')
        self.usage('501', 'EG-499336534-501', status='Submitted')
        self.profile('501', status='missing', env='', brick='10000043')
        self.usage('502', 'EG-499336534-502')
        EtaCodeUsage.objects.filter(itemcode='502').update(system='preprod')       # a test-system code only
        self.profile('502', status='missing', env='', brick='10000043')
        self.assertEqual(egs_sheet.candidates(), [])

    def test_gs1_row(self):
        self.usage('900', '6221111111111', code_type='GS1', gpc='10000050')
        self.profile('900', status='missing', env='', code_type='', eta_code='', decision=None)
        v = self.build()
        ws = _wb(egs_sheet.open_version(v))['DataEntry']
        self.assertEqual(_row_values(ws, 6)[:2], ['GS1', '6221111111111'])
        self.assertEqual(ws['I6'].value, 10000050)

    def test_gs1_from_the_profile(self):
        self.profile('900', code_type='GS1', eta_code='6221111111112', brick='10000043')
        v = self.build()
        self.assertEqual(_row_values(_wb(egs_sheet.open_version(v))['DataEntry'], 6)[:2], ['GS1', '6221111111112'])

    def test_brick_order_decision_then_eta_then_profile(self):
        self.usage('500', 'EG-499336534-500', gpc='10000044')
        self.profile('500', status='missing', env='', gpc='10000045', brick='10000046')
        self.usage('501', 'EG-499336534-501', gpc='10000044')
        self.profile('501', status='missing', env='', gpc='10000045')
        self.profile('502', gpc='10000045')
        ws = _wb(egs_sheet.open_version(self.build()))['DataEntry']
        self.assertEqual([ws.cell(n, 9).value for n in (6, 7, 8)], [10000046, 10000044, 10000045])

    def test_no_formula_is_left_in_a_built_file(self):
        self.profile('300', brick='10000043')
        self.profile('500', brick='10000043')
        ws = _wb(egs_sheet.open_version(self.build()))['DataEntry']
        formulas = [c.coordinate for row in ws.iter_rows() for c in row
                    if isinstance(c.value, str) and c.value.startswith('=')]
        self.assertEqual(formulas, [])
        self.assertEqual([ws[f'{c}2'].value for c in 'LNOP'], [0, '0', 14, 'v009'])     # untouched coded row
        self.assertEqual([ws[f'{c}4'].value for c in 'LNOP'], [0, '0', 14, 'v009'])     # newly coded row
        self.assertEqual([ws[f'{c}6'].value for c in 'LNOP'], [0, '0', 14, 'v009'])     # appended row

    def test_a_typed_value_equal_to_the_formula_is_kept(self):
        wb = _wb(self.sheet_bytes())
        wb['DataEntry']['N3'] = 0               # the owner typed 0 where the formula gives "0"
        TaxEgsSheetVersion.objects.all().delete()
        self.seed(_save(wb))
        self.profile('300', brick='10000043')
        ws = _wb(egs_sheet.open_version(self.build()))['DataEntry']
        self.assertEqual(ws['N3'].value, 0)
        self.assertEqual(ws['N2'].value, '0')

    def test_a_typed_value_other_than_the_formula_is_kept_on_an_untouched_row(self):
        wb = _wb(self.sheet_bytes())
        wb['DataEntry']['N2'] = 1               # like item 114109 in the real sheet: N typed 1, formula gives "0"
        wb['DataEntry']['N4'] = 1               # on the row this build codes: replaced by the formula's value
        TaxEgsSheetVersion.objects.all().delete()
        self.seed(_save(wb))
        self.profile('300', brick='10000043')
        v = self.build()
        self.assertIsInstance(v, TaxEgsSheetVersion)
        ws = _wb(egs_sheet.open_version(v))['DataEntry']
        self.assertEqual((ws['N2'].value, ws['N4'].value), (1, '0'))

    def test_a_build_with_nothing_new_returns_the_latest_and_stores_nothing(self):
        self.assertEqual(self.build(), self.held)
        self.profile('300', brick='10000043')
        v2 = self.build()
        self.assertEqual(v2.number, 2)
        self.assertEqual(self.build(), v2)
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 2)
        self.assertEqual(TaxAuditEvent.objects.filter(action='egs_sheet_built').count(), 1)

    def test_text_itemcode_matches_a_numeric_j(self):
        # J 100 is a number in the sheet: item '100' is the same row, never appended again.
        self.usage('100', 'EG-499336534-100')
        self.profile('100', status='missing', env='', decision=None)
        self.assertEqual(egs_sheet.candidates(), [])
        self.assertEqual(self.build(), self.held)

    def test_a_leading_zero_itemcode_stays_text(self):
        self.profile('0300', brick='10000043')
        v = self.build()
        self.assertEqual(_wb(egs_sheet.open_version(v))['DataEntry']['J6'].value, '0300')

    def test_a_failed_check_stores_nothing(self):
        self.profile('300', brick='10000043')
        with mock.patch.object(egs_sheet, 'checks', return_value=['سبب']):
            out = self.build()
        self.assertEqual(out['refused'], ['سبب'])
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 1)
        self.assertFalse(TaxAuditEvent.objects.filter(action='egs_sheet_built').exists())

    def test_a_reread_mismatch_is_refused(self):
        self.profile('300', brick='10000043')
        real = egs_sheet.read_counts
        calls = []

        def fake(data):
            calls.append(1)
            counts = real(data)
            if len(calls) > 1:          # the saved file's re-read
                counts['coded_rows'] -= 1
            return counts
        with mock.patch.object(egs_sheet, 'read_counts', side_effect=fake):
            out = self.build()
        self.assertTrue(out['refused'])
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 1)

    def test_an_audit_failure_leaves_no_version_and_no_file(self):
        self.profile('300', brick='10000043')
        before = sorted(os.listdir(self.store_dir))
        with mock.patch.object(egs_sheet, 'audit', side_effect=RuntimeError('audit down')):
            with self.assertRaises(RuntimeError):
                self.build()
        self.assertEqual(sorted(os.listdir(self.store_dir)), before)
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 1)

    def test_no_held_version_is_refused(self):
        TaxEgsSheetVersion.objects.all().delete()
        self.assertTrue(egs_sheet.build(None)['refused'])


class ChecksTests(_BuildMixin, TestCase):
    def held_counts(self):
        counts = egs_sheet.read_counts(self.held_bytes)
        counts['sheetnames'] = ['DataEntry', 'GPC Bricks Cleaned', 'ElRezeiky GPC Applied']
        return counts

    def check(self, edit):
        wb = _wb(self.held_bytes)
        egs_sheet._fill_values(wb['DataEntry'])
        edit(wb['DataEntry'], wb)
        return egs_sheet.checks(wb, self.held_counts())

    def test_the_held_sheet_passes(self):
        self.assertEqual(self.check(lambda ws, wb: None), [])

    def test_each_rule_refuses(self):
        def put(**cells):
            def edit(ws, wb):
                for ref, value in cells.items():
                    ws[ref] = value
            return edit
        cases = {
            'sheet names': lambda ws, wb: wb.create_sheet('Extra'),
            'header': put(K1='VAT'),
            'duplicate J 100 vs "100"': put(J4='100'),
            'duplicate coded B': put(B3='EG-499336534-100'),
            'A': put(A2='XYZ'),
            'B empty': put(B2=None),
            'I zero': put(I2=0),
            'K': put(K2=0.07),
            'fewer coded rows': put(G2=None),
            'L value': put(L3=1),
            'N value': put(N2='1'),
            'O value': put(O2=0.14),
            'P value': put(P3='v009'),
            'a formula left in O': put(O2='=K2*100'),
        }
        for name, edit in cases.items():
            with self.subTest(name):
                self.assertTrue(self.check(edit), name)

    def test_a_mismatched_row_is_named(self):
        problems = self.check(lambda ws, wb: ws.__setitem__('P2', 'v003'))
        self.assertEqual(len(problems), 1)
        self.assertIn('100', problems[0])

    def test_formula_values_follow_excel(self):
        def vals(a=None, g=None, i=None, k=None):
            r = [None] * 16
            r[0], r[6], r[8], r[10] = a, g, i, k
            return egs_sheet._formula_values(r)
        self.assertEqual(vals('egs', D, 10000043, 0), (1, '0', 0, 'v003'))         # Excel text compare ignores case
        self.assertEqual(vals('EGS', D, 0, 0), (0, '0', 0, 'v003'))
        self.assertEqual(vals('EGS', D, None, 0), (0, '0', 0, 'v003'))
        self.assertEqual(vals('EGS', None, 10000043, 0), (0, '0', 0, 'v003'))
        self.assertEqual(vals('GS1', D, 10000043, 0), (0, '0', 0, 'v003'))
        self.assertEqual(vals('EGS', D, 10000043, None), (1, '0', 0, 'v003'))      # blank K is 0
        self.assertEqual(vals(), (0, '1', 0, 'v003'))
        self.assertEqual(vals('EGS', D, 10000043, 0.14), (0, '0', 14, 'v009'))
        self.assertIsInstance(vals(k=0.14)[2], int)

    def test_a_newly_coded_keep_out_item_refuses(self):
        self.profile('300', decision='keep_out')

        def code_300(ws, wb):
            ws['A4'], ws['G4'], ws['I4'] = 'EGS', D, 10000043
            egs_sheet._fill_values(ws, [4])
        problems = self.check(code_300)
        self.assertEqual(len(problems), 1)
        self.assertIn('300', problems[0])


class SkipReasonTests(_BuildMixin, TestCase):
    def test_a_confirmed_rate_other_than_14_has_its_own_reason(self):
        self.profile('300', brick='10000043', rate=5)                   # taxable, confirmed at 5 %
        self.profile('500', brick='10000043', confirmed=False)          # not confirmed
        why = {c['itemcode']: c['why'] for c in egs_sheet.candidates()}
        self.assertEqual(why, {'300': egs_sheet.OTHER_RATE, '500': egs_sheet.NO_TREATMENT})


class WorkbookPartsKeptTests(_BuildMixin, TestCase):
    def test_a_built_file_keeps_the_defined_name_and_the_other_sheets(self):
        from openpyxl.workbook.defined_name import DefinedName
        wb = _wb(self.sheet_bytes())
        wb['GPC Bricks Cleaned']['A1'] = 'brick'
        wb.defined_names['CodeTypes'] = DefinedName('CodeTypes', attr_text="'GPC Bricks Cleaned'!$A$1:$A$2")
        TaxEgsSheetVersion.objects.all().delete()
        self.seed(_save(wb))
        self.profile('300', brick='10000043')
        built = _wb(egs_sheet.open_version(self.build()))
        self.assertIn('CodeTypes', built.defined_names)
        self.assertEqual(built.defined_names['CodeTypes'].attr_text, "'GPC Bricks Cleaned'!$A$1:$A$2")
        self.assertEqual(built.sheetnames, ['DataEntry', 'GPC Bricks Cleaned', 'ElRezeiky GPC Applied'])
        self.assertEqual(built['GPC Bricks Cleaned']['A1'].value, 'brick')


# ── S3 Task 3: endpoints ───────────────────────────────────────────────────────────────────────

SHEET_URL = '/api/tax-invoicing/codes/sheet/'


def _sync_thread(target, *, args=(), kwargs=None, name=None, **_):
    """start_thread in tests: the build runs here, on the test's connection (build_thread's close is skipped)."""
    assert target is egs_sheet.build_thread
    egs_sheet.run_build(*args, **(kwargs or {}))


class SheetApiTests(_BuildMixin, TestCase):
    def setUp(self):
        from apps.tests.test_tax_invoicing import Fixture
        from apps.users.models import RoleModuleAccess
        super().setUp()
        Fixture.build(self, 'egs')                   # users; it also rewrites the issuer, so its tax id is put back
        TaxIssuerProfile.objects.filter(pk=1).update(tax_id='499-336-534')
        RoleModuleAccess.objects.update_or_create(role='pharmacist', module='tax_invoicing', action='view',
                                                  defaults={'is_allowed': False})
        self.api = self.client_for(self.accountant)

    def client_for(self, user):
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(user)
        return c

    def post_build(self, client=None):
        with mock.patch('apps.tax_invoicing.egs_sheet_views.start_thread', side_effect=_sync_thread):
            return (client or self.api).post(SHEET_URL + 'build/', {'note': 'n'}, format='json')

    def test_list_shows_versions_pending_and_the_idle_build(self):
        self.profile('300', brick='10000043')
        self.profile('500', brick='10000043', confirmed=False)
        r = self.api.get(SHEET_URL)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([v['number'] for v in r.data['versions']], [1])
        v = r.data['versions'][0]
        self.assertEqual((v['source'], v['coded_rows'], v['total_rows'], v['has_file']), ('seed', 2, 4, True))
        self.assertEqual(r.data['pending'], {'ready': 1, 'skipped': [{'itemcode': '500',
                                                                      'why': egs_sheet.NO_TREATMENT}]})
        self.assertEqual(r.data['build'], {'state': 'idle'})
        self.assertTrue(r.data['can_build'])

    def test_build_runs_in_the_background_and_reports_the_new_version(self):
        self.profile('300', brick='10000043')
        r = self.post_build()
        self.assertEqual(r.status_code, 202, r.content)
        self.assertEqual(egs_sheet.latest().number, 2)
        b = self.api.get(SHEET_URL).data
        self.assertEqual((b['build']['state'], b['build']['version'], b['build']['by']),
                         ('built', 2, self.accountant.username))
        self.assertTrue(b['build']['finished_at'])
        self.assertEqual(b['versions'][0]['coded'], 1)
        self.assertEqual(b['pending']['ready'], 0)

    def test_nothing_new_reports_unchanged(self):
        self.assertEqual(self.post_build().status_code, 202)
        self.assertEqual(egs_sheet.build_state()['state'], 'unchanged')
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 1)

    def test_a_thread_that_cannot_start_leaves_an_error_not_running(self):
        with mock.patch('apps.tax_invoicing.egs_sheet_views.start_thread', side_effect=RuntimeError('no thread')), \
                self.assertLogs('elrezeiky', level='ERROR'):
            r = self.api.post(SHEET_URL + 'build/', {}, format='json')
        self.assertEqual(r.status_code, 503)
        state = egs_sheet.build_state()
        self.assertEqual((state['state'], state['error']), ('error', egs_sheet.BUILD_NOT_STARTED))
        self.assertEqual(self.post_build().status_code, 202)        # not blocked

    def test_a_name_starting_with_equals_stays_text_in_both_files(self):
        import zipfile
        names = {'code_name': '=1+1', 'code_name_ar': '=HYPERLINK("x")', 'description': '=1+1',
                 'description_ar': 'وصف'}
        self.profile('300', brick='10000043', names=names)
        self.profile('500', brick='10000043', names=names)
        self.post_build()
        full = egs_sheet.open_version(egs_sheet.latest())
        new = b''.join(self.api.get(SHEET_URL + '2/download/', {'kind': 'new'}).streaming_content)
        for data in (full, new):
            ws = _wb(data)['DataEntry']
            rows = [n for n in range(2, ws.max_row + 1) if ws.cell(n, 10).value in (300, 500)]
            self.assertEqual(len(rows), 2)
            for n in rows:
                for col, want in ((3, '=1+1'), (4, '=HYPERLINK("x")'), (5, '=1+1')):
                    cell = ws.cell(n, col)
                    self.assertEqual((cell.value, cell.data_type), (want, 's'))
            xml = zipfile.ZipFile(io.BytesIO(data)).read('xl/worksheets/sheet1.xml').decode()
            self.assertNotIn('<f>', xml)

    def test_no_held_version_is_400_and_starts_nothing(self):
        TaxEgsSheetVersion.objects.all().delete()
        with mock.patch('apps.tax_invoicing.egs_sheet_views.start_thread') as started:
            r = self.api.post(SHEET_URL + 'build/', {}, format='json')
        self.assertEqual((r.status_code, r.data['detail']), (400, egs_sheet.NO_HELD))
        started.assert_not_called()
        self.assertEqual(egs_sheet.build_state(), {'state': 'idle'})

    def test_a_second_build_while_one_runs_is_409(self):
        self.assertTrue(egs_sheet.claim_build(self.accountant))
        r = self.post_build()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data['detail'], egs_sheet.BUILD_BUSY)

    def test_a_stale_running_build_does_not_block(self):
        from apps.config.models import SystemSetting
        self.assertTrue(egs_sheet.claim_build(self.accountant))
        row = SystemSetting.objects.get(key=egs_sheet.BUILD_KEY)
        old = (timezone.now() - egs_sheet.BUILD_STALE - dt.timedelta(minutes=1)).isoformat()
        egs_sheet._save_state(row, {'state': 'running', 'started_at': old})
        self.assertEqual(self.post_build().status_code, 202)

    def test_a_duplicate_itemcode_in_the_held_sheet_is_reported_as_the_refusal(self):
        TaxEgsSheetVersion.objects.all().delete()
        self.seed(self.sheet_bytes(rows=ROWS + [(None, '', 'X', None, 0, 300, 0)]))      # 300 twice in J
        self.profile('300', brick='10000043')
        self.assertEqual(self.post_build().status_code, 202)
        b = self.api.get(SHEET_URL).data['build']
        self.assertEqual(b['state'], 'refused')
        self.assertTrue(any('مكرر' in why and '300' in why for why in b['refused']), b['refused'])
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 1)

    def test_a_failure_in_the_build_is_recorded_not_raised(self):
        from django.db import IntegrityError
        with mock.patch.object(egs_sheet, 'build', side_effect=RuntimeError('boom')), \
                self.assertLogs('elrezeiky', level='ERROR'):
            self.assertEqual(self.post_build().status_code, 202)
        state = egs_sheet.build_state()
        self.assertEqual(state['state'], 'error')
        self.assertIn('مرجع', state['error'])
        with mock.patch.object(egs_sheet, 'build', side_effect=IntegrityError('number')):
            self.assertEqual(self.post_build().status_code, 202)
        state = egs_sheet.build_state()
        self.assertEqual((state['state'], state['error']), ('error', egs_sheet.BUILD_RACE))

    def test_full_download_is_the_stored_workbook_and_audited(self):
        r = self.api.get(SHEET_URL + '1/download/', {'kind': 'full'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('ElRezeiky_Bulk_EGS_Items.xlsx', r['Content-Disposition'])
        self.assertEqual(r['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        got = _wb(b''.join(r.streaming_content))
        held = _wb(self.held_bytes)
        self.assertEqual(got.sheetnames, held.sheetnames)
        for n in range(1, 6):
            self.assertEqual(_row_values(got['DataEntry'], n), _row_values(held['DataEntry'], n))
        ev = TaxAuditEvent.objects.get(action='egs_sheet_download')
        self.assertEqual((ev.entity, ev.entity_id, ev.after['kind'], ev.actor),
                         ('egs_sheet', '1', 'full', self.accountant))

    def test_new_download_holds_only_the_rows_the_version_wrote(self):
        self.profile('300', brick='10000043')
        self.profile('500', brick='10000043')
        self.post_build()
        r = self.api.get(SHEET_URL + '2/download/', {'kind': 'new'})
        self.assertEqual(r.status_code, 200)
        ws = _wb(b''.join(r.streaming_content))['DataEntry']
        self.assertEqual([ws.cell(1, c).value for c in range(1, 12)], egs_sheet.HEADER[:11])
        self.assertEqual([ws.cell(n, 10).value for n in range(2, ws.max_row + 1)], [300, 500])
        self.assertEqual(_row_values(ws, 2)[11:], [0, None, '0', 14, 'v009'])
        self.assertEqual(TaxAuditEvent.objects.get(action='egs_sheet_download').after['kind'], 'new')

    def test_download_errors(self):
        self.assertEqual(self.api.get(SHEET_URL + '1/download/', {'kind': 'csv'}).status_code, 400)
        self.assertEqual(self.api.get(SHEET_URL + '9/download/').status_code, 404)
        os.remove(os.path.join(self.store_dir, self.held.file_name))
        self.assertEqual(self.api.get(SHEET_URL + '1/download/').status_code, 404)
        self.assertFalse(TaxAuditEvent.objects.filter(action='egs_sheet_download').exists())

    def test_pharmacist_403_everywhere(self):
        c = self.client_for(self.pharmacist)
        self.assertEqual(c.get(SHEET_URL).status_code, 403)
        self.assertEqual(self.post_build(c).status_code, 403)
        self.assertEqual(c.get(SHEET_URL + '1/download/').status_code, 403)

    def test_viewer_lists_but_cannot_build_or_download(self):
        from apps.tests.factories import make_user
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        RoleModuleAccess.objects.update_or_create(role='viewer', module='tax_invoicing', action='view',
                                                  defaults={'is_allowed': True})
        RoleModuleAccess.objects.filter(role='viewer', module='tax_invoicing').exclude(action='view').delete()
        module_access.clear_cache()
        viewer, _, _ = make_user('viewer_egs', role='viewer', branch=self.branch)
        c = self.client_for(viewer)
        r = c.get(SHEET_URL)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['can_build'])
        self.assertEqual(self.post_build(c).status_code, 403)
        self.assertEqual(c.get(SHEET_URL + '1/download/', {'kind': 'full'}).status_code, 403)
        self.assertEqual(c.get(SHEET_URL + '1/download/', {'kind': 'new'}).status_code, 403)
        self.assertEqual(egs_sheet.build_state(), {'state': 'idle'})
        self.assertFalse(TaxAuditEvent.objects.filter(action='egs_sheet_download').exists())
