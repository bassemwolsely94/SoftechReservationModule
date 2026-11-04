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
    ws.append(['title row'])
    ws.append(['suppliar code', 'Supplier', 'Balance'])
    ws.append([92, 'فارما اوفرسيز ', 100])
    ws.append([105.0, 'شركة النيل للادويه', 5])
    ws.append(['', 'blank code', 1])
    ws.append(['الرصيد الافتتاحى', None, 9])
    ws.append(['Total', None, 105])
    ws2 = wb.create_sheet('الدائنون')
    ws2.append(['suppliar code', 'name', 'Balance'])
    ws2.append([92, 'فارما اوفرسيز', 3])
    ws2.append([300, 'دائن اخر', 3])
    ws2.append(['Grand Total', None, 6])
    ws3 = wb.create_sheet('العملاء')
    ws3.append(['customer code', 'name', 'Balance'])
    ws3.append([92, 'عميل تسعة', 7])
    ws3.append(['Total', None, 7])
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
        self.assertFalse([r for r in rows if r.code in ('', 'Total', 'Grand Total')
                          or 'الرصيد' in r.code])

    def test_same_code_in_suppliers_and_creditors_is_one_party(self):
        res = P.import_parties(self._rows(), user=self.staff)
        self.assertEqual(GLParty.objects.filter(party_type='supplier', code='92').count(), 1)
        self.assertEqual(GLParty.objects.filter(party_type='customer', code='92').count(), 1)
        self.assertEqual(res['created'], 4)
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
