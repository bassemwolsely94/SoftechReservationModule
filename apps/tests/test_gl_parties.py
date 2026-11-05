"""Plan 2 / Task 2: finance party codes <-> SOFTECH persons."""
import os
import tempfile

import openpyxl
from django.contrib.auth.models import User
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.finance.gl import parties as P
from apps.finance.models import GLParty, ReconParty
from apps.users.models import StaffProfile


def _workbook(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'الموردين'
    ws.append(['suppliar code', 'Suppliar name', 'Credit', 'Debt', 'Grand Total'])
    ws.append([92, 'فارما اوفرسيز ', -1, 2, 1])
    ws.append([105.0, 'شركة النيل للادويه', 5, 0, 5])
    ws.append([None, None, 'الرصيد الافتتاحى', -5, None])
    ws.append([None, None, 3, -1, 2])
    ws.append([1, None, 4, 0, 4])           # code with blank name -> skipped
    ws.append(['Total', None, 105, 0, 105])
    ws2 = wb.create_sheet('مشتريات الموردين')
    ws2.append(['suppliar code', 'Suppliar name', 'MONTH', 'Credit', 'Debt', 'Grand Total'])
    ws2.append([92, 'فارما اوفرسيز', 1, 3, 0, 3])
    ws2.append([None, None, 2, 3, 0, 3])
    ws2.append([300, 'دائن اخر', 1, 3, 0, 3])
    ws2.append([None, None, 1, 1, 0, 1])    # month number 1 must not become party 1
    ws2.append(['Grand Total', None, None, 6, 0, 6])
    ws3 = wb.create_sheet('العملاء')
    ws3.append(['customer code', 'customer name', 'Credit', 'Debt', 'Grand Total'])
    ws3.append([92, 'عميل تسعة', 7, 0, 7])
    ws3.append(['Total', None, 7, 0, 7])
    wb.create_sheet('other').append(['nothing', 'here'])
    wb.save(path)


class PartyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(username='fin')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=cls.user)

    def _rows(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'w.xlsx')
        _workbook(p)
        return P.parse_party_sheets(p)

    def test_sheets_parsed_by_header_and_totals_skipped(self):
        rows = self._rows()
        got = {(r.party_type, r.code, r.name) for r in rows}
        self.assertIn(('supplier', '92', 'فارما اوفرسيز'), got)
        self.assertIn(('supplier', '105', 'شركة النيل للادويه'), got)
        self.assertIn(('supplier', '300', 'دائن اخر'), got)
        self.assertIn(('customer', '92', 'عميل تسعة'), got)
        self.assertEqual(len(rows), 4)
        self.assertFalse([r for r in rows if r.code in ('1', '2', '3', '5')])
        self.assertTrue(all(r.name and not r.name.isdigit() for r in rows))

    def test_same_code_in_suppliers_and_creditors_is_one_party(self):
        res = P.import_parties(self._rows(), user=self.staff)
        self.assertEqual(GLParty.objects.filter(party_type='supplier', code='92').count(), 1)
        self.assertEqual(GLParty.objects.filter(party_type='customer', code='92').count(), 1)
        self.assertEqual(res['created'], 4)
        self.assertEqual(GLParty.objects.get(party_type='supplier', code='92').name, 'فارما اوفرسيز')
        res2 = P.import_parties(self._rows(), user=self.staff)
        self.assertEqual(res2['created'], 0)
        self.assertTrue(AuditLog.objects.filter(action='gl_parties_imported').exists())

    def _gl(self, code, name, t='supplier'):
        return GLParty.objects.create(party_type=t, code=code, name=name)

    def test_exact_name_proposal(self):
        ReconParty.objects.create(party_type='supplier', softech_personcode='5001',
                                  name='فارما أوفرسيز')
        g = self._gl('92', 'فارما اوفرسيز ')
        res = P.propose_matches(user=self.staff)
        g.refresh_from_db()
        self.assertEqual((g.status, g.proposal_basis, g.softech_personcode),
                         ('proposed', 'exact', '5001'))
        self.assertEqual(res['exact'], 1)

    def test_token_proposal_ignores_stop_words(self):
        ReconParty.objects.create(party_type='supplier', softech_personcode='5002',
                                  name='النيل شركة للادويه')
        g = self._gl('105', 'شركة النيل')
        P.propose_matches(user=self.staff)
        g.refresh_from_db()
        self.assertEqual((g.status, g.proposal_basis), ('proposed', 'tokens'))

    def test_two_candidates_leave_party_unmapped(self):
        ReconParty.objects.create(party_type='supplier', softech_personcode='5003', name='النيل شركة')
        ReconParty.objects.create(party_type='supplier', softech_personcode='5004',
                                  name='شركة النيل')
        g = self._gl('106', 'النيل')
        res = P.propose_matches(user=self.staff)
        g.refresh_from_db()
        self.assertEqual(g.status, 'unmapped')
        self.assertEqual(res['none'], 1)

    def test_type_must_match(self):
        ReconParty.objects.create(party_type='customer', softech_personcode='6001', name='س')
        g = self._gl('1', 'س', 'supplier')
        P.propose_matches(user=self.staff)
        g.refresh_from_db()
        self.assertEqual(g.status, 'unmapped')

    def test_resolve_party_ignores_proposed(self):
        ReconParty.objects.create(party_type='supplier', softech_personcode='5001', name='ا ب')
        g = self._gl('92', 'ا ب')
        P.propose_matches(user=self.staff)
        self.assertIsNone(P.resolve_party('supplier', '5001'))
        P.confirm_party(g.pk, user=self.staff, personcode='5001')
        self.assertEqual(P.resolve_party('supplier', '5001').pk, g.pk)
        g.is_active = False
        g.save()
        self.assertIsNone(P.resolve_party('supplier', '5001'))

    def test_confirm_requires_unique_personcode(self):
        a, b = self._gl('1', 'a'), self._gl('2', 'b')
        P.confirm_party(a.pk, user=self.staff, personcode='777')
        with self.assertRaises(ValueError) as cm:
            P.confirm_party(b.pk, user=self.staff, personcode='777')
        self.assertRegex(str(cm.exception), r'[\u0600-\u06FF]')
        b.refresh_from_db()
        self.assertEqual(b.status, 'unmapped')
        a.refresh_from_db()
        self.assertEqual((a.status, a.confirmed_by_id), ('confirmed', self.staff.pk))
        self.assertTrue(AuditLog.objects.filter(action='gl_party_confirmed').exists())

    def test_reject_and_create_from_personcode(self):
        g = self._gl('3', 'c')
        P.reject_party(g.pk, user=self.staff)
        g.refresh_from_db()
        self.assertEqual(g.status, 'rejected')
        n = P.create_party_from_personcode(user=self.staff, party_type='supplier', code='900',
                                           personcode='888')
        self.assertTrue(n.is_confirmed)
        self.assertEqual(P.resolve_party('supplier', '888').pk, n.pk)

    def test_recon_party_lookup_is_type_scoped(self):
        ReconParty.objects.create(party_type='customer', softech_personcode='9100', name='x')
        g = self._gl('9', 'x', 'supplier')
        P.confirm_party(g.pk, user=self.staff, personcode='9100')
        g.refresh_from_db()
        self.assertIsNone(g.recon_party)

    def test_confirm_to_different_personcode_refused_same_is_noop(self):
        g = self._gl('4', 'd')
        P.confirm_party(g.pk, user=self.staff, personcode='111')
        P.confirm_party(g.pk, user=self.staff, personcode='111')
        with self.assertRaises(ValueError):
            P.confirm_party(g.pk, user=self.staff, personcode='222')
        with self.assertRaises(ValueError):
            P.create_party_from_personcode(user=self.staff, party_type='supplier', code='4',
                                           personcode='222')
        g.refresh_from_db()
        self.assertEqual(g.softech_personcode, '111')


def _master_workbook(path):
    """Synthetic copy of the shape of finance's 2020 master sheets (Ruling P26)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'الموردين '
    ws.append(['دليل الموردين', None, None])
    ws.append(['الكود', 'اسم المورد ', 'التليفون '])          # header on row 2, trailing spaces
    ws.append([92, 'فارما اوفرسيز - اسم 2020', '0100'])
    ws.append([501.0, 'مورد نقدي جديد', None])
    ws.append([None, None, None])
    ws.append(['x', 'ليس كوداً', None])
    ws.append([502, 12345, None])                             # numeric name -> skipped
    ws2 = wb.create_sheet('الموظفين')
    ws2.append(['كود الموظف ', 'Name in Arabic', 'الفرع '])
    ws2.append([7, 'أحمد محمد', 'عين شمس'])
    ws2.append([8, '   ', 'الجيزة'])                          # blank name -> skipped
    ws3 = wb.create_sheet('العملاء')
    ws3.append(['كود العميل', 'اسم العميل', 'الرصيد'])
    ws3.append([3001, 'شركة تأمين', 5])
    ws4 = wb.create_sheet('لا شيء')
    ws4.append(['الكود', 'بيان'])                              # 'الكود' alone is not a master header
    ws4.append([1, 'سطر'])
    wb.save(path)


class MasterSheetP26Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(username='fin26')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=cls.user)

    def _rows(self):
        p = os.path.join(tempfile.mkdtemp(), 'm.xlsx')
        _master_workbook(p)
        return P.parse_party_sheets(p)

    def test_master_headers_recognised(self):
        got = {(r.party_type, r.code, r.name) for r in self._rows()}
        self.assertEqual(got, {('supplier', '92', 'فارما اوفرسيز - اسم 2020'),
                               ('supplier', '501', 'مورد نقدي جديد'),
                               ('employee', '7', 'أحمد محمد'),
                               ('customer', '3001', 'شركة تأمين')})

    def test_create_only_never_renames_existing(self):
        GLParty.objects.create(party_type='supplier', code='92', name='فارما اوفرسيز', status='confirmed',
                               softech_personcode='5001')
        res = P.import_parties(self._rows(), user=self.staff, create_only=True)
        self.assertEqual((res['created'], res['updated']), (3, 0))
        g = GLParty.objects.get(party_type='supplier', code='92')
        self.assertEqual((g.name, g.status, g.softech_personcode), ('فارما اوفرسيز', 'confirmed', '5001'))
        self.assertEqual(GLParty.objects.get(party_type='employee', code='7').status, 'unmapped')
        log = AuditLog.objects.filter(action='gl_parties_imported').latest('id')
        self.assertTrue(log.extra['create_only'])

    def test_default_mode_skips_and_reports_master_sheets(self):
        """Review minor 8: master sheets only count in create_only mode."""
        GLParty.objects.create(party_type='supplier', code='92', name='فارما اوفرسيز')
        rows = self._rows()
        self.assertTrue(all(r.master for r in rows))
        res = P.import_parties(rows, user=self.staff)
        self.assertEqual((res['created'], res['updated'], res['master_skipped']), (0, 0, 4))
        self.assertEqual(res['master_sheets'], ['العملاء', 'الموردين ', 'الموظفين'])
        self.assertEqual(GLParty.objects.get(party_type='supplier', code='92').name, 'فارما اوفرسيز')
        self.assertEqual(GLParty.objects.count(), 1)

    def test_master_row_never_hides_a_sub_ledger_row(self):
        p = os.path.join(tempfile.mkdtemp(), 'mix.xlsx')
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'الموردين '
        ws.append(['الكود', 'اسم المورد '])
        ws.append([92, 'اسم 2020'])
        ws2 = wb.create_sheet('pivot')
        ws2.append(['suppliar code', 'Suppliar name'])
        ws2.append([92, 'اسم 2026'])
        wb.save(p)
        res = P.import_parties(P.parse_party_sheets(p), user=self.staff)
        self.assertEqual((res['created'], res['master_skipped']), (1, 1))
        self.assertEqual(GLParty.objects.get(party_type='supplier', code='92').name, 'اسم 2026')

    def test_command_default_mode_reports_skipped_master_sheets(self):
        from io import StringIO
        from django.core.management import call_command
        p = os.path.join(tempfile.mkdtemp(), 'm.xlsx')
        _master_workbook(p)
        out = StringIO()
        call_command('import_gl_parties', p, stdout=out)
        self.assertIn('created=0 updated=0', out.getvalue())
        self.assertIn('skipped 4 master-sheet rows', out.getvalue())
        self.assertFalse(GLParty.objects.exists())

    def test_command_create_only(self):
        from io import StringIO
        from django.core.management import call_command
        GLParty.objects.create(party_type='supplier', code='92', name='اسم 2026')
        p = os.path.join(tempfile.mkdtemp(), 'm.xlsx')
        _master_workbook(p)
        out = StringIO()
        call_command('import_gl_parties', p, '--create-only', stdout=out)
        self.assertIn('created=3 updated=0', out.getvalue())
        self.assertEqual(GLParty.objects.get(party_type='supplier', code='92').name, 'اسم 2026')


class CodeCellTests(TestCase):
    def test_non_finite_numbers_are_skipped_never_raise(self):
        for v in ('nan', 'NaN', 'inf', '-inf', 'Infinity', float('nan'), float('inf')):
            self.assertIsNone(P._code(v), v)
        self.assertEqual((P._code(12.0), P._code('34'), P._code(' 56.0 '), P._code(7)), ('12', '34', '56', '7'))
        self.assertIsNone(P._code(1.5))
        self.assertIsNone(P._code(True))
