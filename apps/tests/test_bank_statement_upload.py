"""
Bank-statement upload on /payment-audit (2026-11-05): the form's fields, the file parser
(apps/payments/statement_parser.py), all-or-nothing lines, failed imports, branch scope, audit,
and «تشغيل المطابقة» over the parsed lines. Synthetic in-memory files only.
"""
import io
import shutil
import tempfile
from unittest import mock
from datetime import date, datetime
from decimal import Decimal

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from apps.audit.models import AuditLog
from apps.payments.models import BankStatementImport, BankStatementLine, ExternalPayment
from apps.payments.statement_parser import (
    MAX_STATEMENT_BYTES, UNREADABLE_FILE, StatementParseError, parse_amount, parse_date, parse_statement,
)
from apps.tests.factories import make_branch, make_branch2, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

URL = '/api/payments/audit/statements/'
D1, D2 = date(2026, 10, 1), date(2026, 10, 31)


def _csv(text, encoding='utf-8'):
    return io.BytesIO(text.encode(encoding))


def _xlsx_bytes(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class ParserTests(SimpleTestCase):

    def test_arabic_headers_under_a_title_row(self):
        text = ('بنك مصر — كشف حساب,,,,\n'
                'رقم الحساب 123,,,,\n'
                ',,,,\n'
                'التاريخ,البيان,رقم المرجع,مدين,دائن,الرصيد\n'
                '05/10/2026,تحويل وارد,TX1,,"1,250.50 ج.م","10,000"\n'
                '07/10/2026,رسوم,,(15),,9985\n'
                ',الإجمالي,,15,1250.50,\n')
        lines, warnings = parse_statement(_csv(text), 's.csv', D1, D2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]['transaction_date'], date(2026, 10, 5))        # dd/mm
        self.assertEqual(lines[0]['credit'], Decimal('1250.50'))
        self.assertEqual(lines[0]['reference'], 'TX1')
        self.assertEqual(lines[0]['balance'], Decimal('10000.00'))
        # the column decides the side: (15) in «مدين» is still a debit
        self.assertEqual((lines[1]['debit'], lines[1]['credit']), (Decimal('15.00'), Decimal('0')))
        self.assertEqual(warnings, [])

    def test_sign_never_moves_a_value_to_the_other_column(self):
        text = 'Date,Debit,Credit\n01/10/2026,-200,\n02/10/2026,,-300\n03/10/2026,5,7\n'
        lines, _ = parse_statement(_csv(text), 's.csv', D1, D2)
        self.assertEqual([(l['debit'], l['credit']) for l in lines],
                         [(Decimal('200.00'), Decimal('0')), (Decimal('0'), Decimal('300.00')),
                          (Decimal('5.00'), Decimal('7.00'))])

    def test_english_headers_and_signed_amount(self):
        text = ('Txn Date,Ref No.,Narrative,Amount,Balance\n'
                '2026-10-02,A1,Deposit,500,500\n'
                '2026-10-03,A2,ATM,-200.25,299.75\n'
                '2026-10-04,A3,Fee,(10),289.75\n'
                'Closing balance,,,,289.75\n')
        lines, _ = parse_statement(_csv(text), 's.csv', D1, D2)
        self.assertEqual([(l['debit'], l['credit']) for l in lines],
                         [(Decimal('0'), Decimal('500.00')), (Decimal('200.25'), Decimal('0')),
                          (Decimal('10.00'), Decimal('0'))])
        self.assertEqual(lines[0]['reference'], 'A1')

    def test_arabic_indic_digits_and_cp1256(self):
        text = 'تاريخ الحركة,إيداع,سحب\n٠٥/١٠/٢٠٢٦,"١٬٢٣٤٫٥٠",\n'
        lines, _ = parse_statement(_csv(text), 's.csv', D1, D2)
        self.assertEqual(lines[0]['transaction_date'], date(2026, 10, 5))
        self.assertEqual(lines[0]['credit'], Decimal('1234.50'))
        # an Excel "CSV (Arabic)" export: Windows-1256 bytes
        lines, _ = parse_statement(_csv('التاريخ,له,منه\n05/10/2026,,75\n', 'cp1256'), 's.csv', D1, D2)
        self.assertEqual(lines[0]['debit'], Decimal('75.00'))

    def test_xlsx_with_datetime_and_serial_dates(self):
        data = _xlsx_bytes([
            ['National Bank of Egypt'],
            [],
            ['Posting Date', 'Value Date', 'Description', 'Debit', 'Credit', 'Balance'],
            [datetime(2026, 10, 9), 46304, 'Transfer', None, 750, 750],
            [46305, None, 'Fee', 5, None, 745],
            ['Total', None, None, 5, 750, None],
        ])
        lines, _ = parse_statement(io.BytesIO(data), 's.xlsx', D1, D2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]['transaction_date'], date(2026, 10, 9))
        self.assertEqual(lines[0]['value_date'], date(2026, 10, 9))               # serial 46304
        self.assertEqual(lines[1]['transaction_date'], date(2026, 10, 10))
        self.assertEqual(lines[1]['debit'], Decimal('5.00'))

    def test_out_of_period_rows_are_kept_with_a_warning(self):
        text = 'Date,Credit\n30/09/2026,100\n01/10/2026,200\n'
        lines, warnings = parse_statement(_csv(text), 's.csv', D1, D2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(len(warnings), 1)
        self.assertIn('1 سطر', warnings[0])

    def test_unknown_headers_list_what_was_found(self):
        with self.assertRaises(StatementParseError) as cm:
            parse_statement(_csv('Foo,Bar,Baz\n1,2,3\n'), 's.csv', D1, D2)
        self.assertIn('«Foo»', str(cm.exception))
        self.assertIn('«Baz»', str(cm.exception))

    def test_bad_date_on_a_money_row_fails_the_whole_file(self):
        with self.assertRaises(StatementParseError) as cm:
            parse_statement(_csv('Date,Credit\n01/10/2026,5\nyesterday,10\n'), 's.csv', D1, D2)
        self.assertIn('السطر 3', str(cm.exception))

    def test_xls_without_xlrd_and_other_types(self):
        try:
            import xlrd  # noqa: F401
        except ImportError:
            with self.assertRaisesRegex(StatementParseError, 'xlsx أو csv'):
                parse_statement(io.BytesIO(b'junk'), 's.xls')
        with self.assertRaises(StatementParseError):
            parse_statement(io.BytesIO(b'junk'), 's.pdf')

    def test_value_helpers(self):
        self.assertEqual(parse_date('2026/10/05'), date(2026, 10, 5))
        self.assertEqual(parse_date('05-10-2026'), date(2026, 10, 5))
        self.assertEqual(parse_date('05/10/2026 14:30'), date(2026, 10, 5))
        self.assertEqual(parse_date('05 Oct 2026'), date(2026, 10, 5))
        self.assertIsNone(parse_date('31/02/2026'))
        self.assertEqual(parse_amount('EGP 1,000.005'), Decimal('1000.01'))
        self.assertEqual(parse_amount('250-'), Decimal('-250.00'))
        with self.assertRaises(ValueError):
            parse_amount('abc')


GRANTS = {
    ('purchasing', 'finance'): {'view', 'create', 'edit', 'approve'},
    ('pharmacist', 'finance'): {'view', 'create'},
}


class UploadApiTests(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix='stmt-test-')
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        module_access.clear_cache()
        for (role, module), actions in GRANTS.items():
            for a in actions:
                RoleModuleAccess.objects.create(role=role, module=module, action=a)
        self.branch, self.other = make_branch(), make_branch2()
        _, self.fin_profile, self.fin = make_user('stmt_fin', role='purchasing', branch=self.branch)
        _, _, self.pharm = make_user('stmt_pharm', role='pharmacist', branch=self.branch)

    def tearDown(self):
        module_access.clear_cache()

    def _post(self, client, content, name='s.csv', **over):
        data = {'branch': self.branch.pk, 'bank_name': 'بنك مصر', 'account_number': '',
                'payment_method': 'bank_transfer', 'statement_from': '2026-10-01',
                'statement_to': '2026-10-31',
                'raw_file': SimpleUploadedFile(name, content)}
        data.update(over)
        data = {k: v for k, v in data.items() if v is not None}
        return client.post(URL, data, format='multipart')

    CSV = ('بنك مصر,,\nالتاريخ,رقم المرجع,دائن,مدين\n'
           '05/10/2026,TX-77,"1,500.00",\n06/10/2026,,,"20"\nالإجمالي,,1500,20\n').encode('utf-8')

    def test_upload_creates_the_lines_and_an_audit_entry(self):
        r = self._post(self.fin, self.CSV)
        self.assertEqual(r.status_code, 201, r.data)
        stmt = BankStatementImport.objects.get(pk=r.data['id'])
        self.assertEqual(stmt.status, 'pending')
        self.assertEqual(stmt.total_lines, 2)
        self.assertEqual(stmt.imported_by, self.fin_profile)
        self.assertEqual(BankStatementLine.objects.filter(statement_import=stmt, match_method='unmatched').count(), 2)
        log = AuditLog.objects.get(action='bank_statement_uploaded', object_id=str(stmt.pk))
        self.assertEqual(log.user, self.fin_profile)
        self.assertEqual(log.extra['lines'], 2)
        self.assertEqual(log.extra['file_name'], 's.csv')

    def test_xlsx_upload(self):
        data = _xlsx_bytes([['Date', 'Amount'], ['01/10/2026', 10], ['02/10/2026', -3]])
        r = self._post(self.fin, data, name='s.xlsx')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['total_lines'], 2)

    def test_missing_fields_answer_field_errors(self):
        r = self.fin.post(URL, {'raw_file': SimpleUploadedFile('s.csv', self.CSV)}, format='multipart')
        self.assertEqual(r.status_code, 400)
        for f in ('branch', 'bank_name', 'payment_method', 'statement_from', 'statement_to'):
            self.assertIn(f, r.data)
        self.assertNotIn('account_number', r.data)
        self.assertFalse(BankStatementImport.objects.exists())

    def test_period_must_run_forward(self):
        r = self._post(self.fin, self.CSV, statement_from='2026-10-31', statement_to='2026-10-01')
        self.assertEqual(r.status_code, 400)
        self.assertIn('statement_to', r.data)

    def test_branch_user_cannot_upload_for_another_branch(self):
        r = self._post(self.pharm, self.CSV, branch=self.other.pk)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(BankStatementImport.objects.exists())
        self.assertEqual(self._post(self.pharm, self.CSV).status_code, 201)

    def test_unknown_headers_keep_a_failed_import_without_lines(self):
        r = self._post(self.fin, b'Foo,Bar\n1,2\n')
        self.assertEqual(r.status_code, 400)
        self.assertIn('«Foo»', r.data['detail'])
        stmt = BankStatementImport.objects.get()
        self.assertEqual(stmt.status, 'failed')
        self.assertIn('«Foo»', stmt.error_message)
        self.assertFalse(stmt.lines.exists())
        self.assertEqual(self.fin.post(f'{URL}{stmt.pk}/run-matching/').status_code, 400)

    def test_nul_byte_csv_fails_cleanly(self):
        r = self._post(self.fin, b'Date,Credit\n01/10/2026,5\x00\n')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['detail'], UNREADABLE_FILE)
        stmt = BankStatementImport.objects.get()
        self.assertEqual((stmt.status, stmt.total_lines), ('failed', 0))
        self.assertFalse(stmt.lines.exists())

    def test_unexpected_error_rolls_back_the_lines(self):
        with mock.patch.object(BankStatementLine.objects, 'bulk_create', side_effect=RuntimeError('disk full')), \
                self.assertLogs('elrezeiky', level='ERROR'):
            r = self._post(self.fin, self.CSV)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['detail'], UNREADABLE_FILE)
        stmt = BankStatementImport.objects.get()
        self.assertEqual((stmt.status, stmt.total_lines), ('failed', 0))
        self.assertFalse(stmt.lines.exists())

    def test_half_good_file_leaves_no_lines(self):
        r = self._post(self.fin, b'Date,Credit\n01/10/2026,5\nnot-a-date,10\n')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(BankStatementLine.objects.exists())

    def test_wrong_type_and_too_big_are_rejected(self):
        r = self._post(self.fin, b'%PDF-1.4', name='s.pdf')
        self.assertEqual(r.status_code, 400)
        self.assertIn('raw_file', r.data)
        r = self._post(self.fin, b'a' * (MAX_STATEMENT_BYTES + 1))
        self.assertEqual(r.status_code, 400)
        self.assertIn('raw_file', r.data)
        self.assertFalse(BankStatementImport.objects.exists())

    def test_form_options(self):
        BankStatementImport.objects.create(branch=self.branch, bank_name='CIB', payment_method='instapay',
                                           statement_from=D1, statement_to=D2)
        r = self.pharm.get(f'{URL}form-options/')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([b['id'] for b in r.data['branches']], [self.branch.pk])
        self.assertEqual(r.data['default_branch'], self.branch.pk)
        self.assertIn({'value': 'bank_transfer', 'label': 'تحويل بنكي'}, r.data['payment_methods'])
        self.assertEqual(r.data['bank_names'], ['CIB'])
        all_ids = {b['id'] for b in self.fin.get(f'{URL}form-options/').data['branches']}
        self.assertTrue({self.branch.pk, self.other.pk} <= all_ids)

    def test_run_matching_matches_a_recorded_payment(self):
        pay = ExternalPayment.objects.create(branch=self.branch, method='bank_transfer', amount=Decimal('1500'),
                                             reference_number='TX-77', payment_date=date(2026, 10, 5))
        r = self._post(self.fin, self.CSV)
        self.assertEqual(r.status_code, 201, r.data)
        m = self.fin.post(f'{URL}{r.data["id"]}/run-matching/')
        self.assertEqual(m.status_code, 200, m.data)
        self.assertEqual(m.data['matched_exact'], 1)
        line = BankStatementLine.objects.get(statement_import_id=r.data['id'], credit=Decimal('1500'))
        self.assertEqual((line.matched_payment, line.match_method), (pay, 'auto_exact'))
        stmt = BankStatementImport.objects.get(pk=r.data['id'])
        self.assertEqual((stmt.status, stmt.matched_lines, stmt.total_lines), ('completed', 1, 2))
