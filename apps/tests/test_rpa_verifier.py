"""apps/rpa identity + verifier: read-only SOFTECH lookups, driven through a fake connection."""
import ast
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.personal.models import SoftechIdentityClaim
from apps.rpa import verifier
from apps.rpa.identity import expected_softech_usercode
from apps.rpa.models import RpaDocument, RpaJob, RpaLine, RpaScreen
from apps.tests.factories import make_branch, make_branch2
from apps.tests.security import static_scan
from apps.users.models import StaffProfile


class _Cur:
    def __init__(self, conn):
        self.conn, self._rows = conn, []

    def execute(self, sql, params=None, **kw):
        params = list(params or [])
        assert sql.count('?') == len(params), sql
        self.conn.calls.append((sql, params))
        m = re.match(r'SET ROWCOUNT (\d+)', sql)
        if m:                                   # the session keeps the cap until it is reset
            self.conn.rowcount = int(m.group(1))
        if 'dbo.stktransm' in sql:
            self._rows = self.conn.headers_for(sql)
        elif 'dbo.stktrans ' in sql:
            self._rows = self.conn.lines.get(params[2], [])
        else:
            self._rows = []

    def fetchall(self):
        cap = self.conn.rowcount                # applies to every SELECT, lines included
        return list(self._rows)[:cap] if cap else list(self._rows)

    def close(self):
        pass


class _Conn:
    def __init__(self, by_ref=(), by_print=(), lines=None):
        self.by_ref, self.by_print, self.lines = list(by_ref), list(by_print), lines or {}
        self.calls, self.closed, self.rowcount = [], False, 0

    def headers_for(self, sql):
        return self.by_ref if 'LIKE' in sql else self.by_print

    def cursor(self):
        return _Cur(self)

    def close(self):
        self.closed = True


def _hdr(num, user='5014', target='B02', comments='RPA'):
    return (num, user, target, date(2026, 11, 17), comments)


class VerifierTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username='rpa_t6', password='x')
        self.staff = StaffProfile.objects.get_or_create(user=user, defaults={'role': 'admin'})[0]
        SoftechIdentityClaim.objects.create(staff=self.staff, kind='salesperson', person_code='5014',
                                            status='approved')
        self.src, self.dst = make_branch('Src', 'B01'), make_branch2('Dst', 'B02')
        self.job = RpaJob.objects.create(
            screen=RpaScreen.objects.get(key='issue_125'), branch=self.src, target_branch=self.dst,
            created_by=self.staff, status='approved', approved_at=timezone.now())
        self.doc = RpaDocument.objects.create(job=self.job, seq=1)
        RpaLine.objects.create(document=self.doc, row_no=1, itemcode='100', qty=Decimal('2'),
                               expiry=date(2027, 5, 1))
        RpaLine.objects.create(document=self.doc, row_no=2, itemcode='200', qty=Decimal('1.5'))

    def _find(self, conn):
        with mock.patch('config.sybase.get_branch_connection', return_value=conn):
            return verifier.find_issue_document(self.doc)

    def _good_lines(self):
        return [('100', Decimal('2'), date(2027, 5, 1)), ('200', Decimal('1.50000'), None)]

    def test_found_by_reference(self):
        conn = _Conn(by_ref=[_hdr(77, comments=self.doc.reference)], lines={77: self._good_lines()})
        found = self._find(conn)
        self.assertEqual((found['docnumber'], found['matched_by']), (77, 'reference'))
        self.assertEqual(conn.calls[0][1], ['B01', f'%{self.doc.reference}%'])
        self.assertTrue(conn.closed)

    def test_found_by_fingerprint_when_no_reference(self):
        conn = _Conn(by_print=[_hdr(78)], lines={78: self._good_lines()})
        found = self._find(conn)
        self.assertEqual((found['docnumber'], found['matched_by']), (78, 'fingerprint'))
        sql, params = [c for c in conn.calls if 'ORDER BY docnumber DESC' in c[0]][0]
        self.assertIn('SET ROWCOUNT 50', sql)
        self.assertEqual(params[:3], ['B01', '5014', 'B02'])
        self.assertEqual(params[3], timezone.localtime(self.job.approved_at).date())   # R1 window start
        self.assertEqual(params[4], timezone.localdate())

    def test_candidate_with_extra_line_is_not_a_match(self):
        conn = _Conn(by_ref=[_hdr(79, comments=self.doc.reference)], lines={79: self._good_lines() + [('300', Decimal('1'), None)]})
        self.assertIsNone(self._find(conn))

    def test_lines_queried_with_branch_and_doccode(self):
        conn = _Conn(by_ref=[_hdr(77, comments=self.doc.reference)], lines={77: self._good_lines()})
        self._find(conn)
        sql, params = [c for c in conn.calls if 'dbo.stktrans ' in c[0]][0]
        self.assertEqual(params, ['B01', '125', 77])
        self.assertIn('branchcode=?', sql)
        self.assertIn('doccode=?', sql)

    def test_long_document_is_not_truncated_by_the_header_row_cap(self):
        for i in range(3, 9):
            RpaLine.objects.create(document=self.doc, row_no=i, itemcode=f'9{i}', qty=Decimal('1'))
        lines = self._good_lines() + [(f'9{i}', Decimal('1'), None) for i in range(3, 9)]
        found = self._find(_Conn(by_ref=[_hdr(77, comments=self.doc.reference)], lines={77: lines}))
        self.assertEqual((found['docnumber'], len(found['lines'])), (77, 8))
        found = self._find(_Conn(by_print=[_hdr(78)], lines={78: lines}))
        self.assertEqual(len(found['lines']), 8)

    def test_reference_prefix_does_not_match_longer_reference(self):
        other = f'{self.doc.reference}0'
        conn = _Conn(by_ref=[_hdr(80, comments=other)], lines={80: self._good_lines()})
        self.assertIsNone(self._find(conn))

    def test_fingerprint_skips_document_naming_another_rpa_reference(self):
        conn = _Conn(by_print=[_hdr(81, comments='RPA-99999')], lines={81: self._good_lines()})
        self.assertIsNone(self._find(conn))

    def test_wrong_usercode_is_a_problem(self):
        found = self._find(_Conn(by_ref=[_hdr(77, user='9999', comments=self.doc.reference)], lines={77: self._good_lines()}))
        res = verifier.verify_issue_document(self.doc, found)
        self.assertFalse(res['ok'])
        self.assertEqual(len(res['problems']), 1)

    def test_all_good_and_expiry_and_target_problems(self):
        found = self._find(_Conn(by_ref=[_hdr(77, comments=self.doc.reference)], lines={77: self._good_lines()}))
        self.assertEqual(verifier.verify_issue_document(self.doc, found), {'ok': True, 'problems': []})
        found['lines'][0]['expiry'] = date(2028, 1, 1)
        found['cust_branch_code'] = 'B09'
        self.assertEqual(len(verifier.verify_issue_document(self.doc, found)['problems']), 2)

    def test_identity_fallbacks(self):
        self.assertEqual(expected_softech_usercode(self.staff), '5014')
        SoftechIdentityClaim.objects.all().delete()
        self.assertIsNone(expected_softech_usercode(self.staff))
        self.staff.softech_username = 'aya'
        self.assertEqual(expected_softech_usercode(self.staff), 'aya')
        self.staff.softech_user_id = '42'
        self.assertEqual(expected_softech_usercode(self.staff), '42')

    def test_no_write_sql_in_module(self):
        for name in ('verifier.py', 'identity.py'):
            path = Path(verifier.__file__).with_name(name)
            self.assertEqual(static_scan.softech_write_sites(ast.parse(path.read_text(encoding='utf-8')), name),
                             set())
        text = Path(verifier.__file__).read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'\b(INSERT|UPDATE|DELETE|EXEC)\b', text.replace('SET ROWCOUNT', '')))
