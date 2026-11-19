"""
Audit S-8 / decision D-10: SOFTECH document lookups are keyed on (branchcode, doccode, docnumber).

SOFTECH numbers every document type separately per branch, so docnumber 500 exists at
every branch and for several doctypes at once. A bare-docnumber lookup confirmed a
reservation (or transfer) against another branch's sale and merged lines of unrelated
documents. Each test below plants the same number at two branches (and/or two doctypes)
and checks that nothing crosses over.

The fake SOFTECH answers each query only with the documents its WHERE clause selects — a
query missing the branch or doccode filter gets every same-numbered document back, as the
real one would.
"""
import ast
import datetime
import re
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.insurance import importer
from apps.insurance import models as m
from apps.insurance.validation import validate_claim_readiness
from apps.reservations.erp_matcher import ReservationERPMatcher
from apps.reservations.models import Reservation
from apps.tests.factories import make_branch, make_item, make_user
from apps.tests.test_insurance import _add_rx, _mk_claim
from apps.tests.test_insurance_doccode_lookups import BRANCH as INS_BRANCH
from apps.tests.test_insurance_doccode_lookups import DOC as INS_DOC
from apps.tests.test_insurance_doccode_lookups import HEADERS as INS_HEADERS
from apps.tests.test_insurance_doccode_lookups import LINES as INS_LINES
from apps.tests.test_insurance_doccode_lookups import _conn as ins_conn
from apps.transfers.erp_matcher import ERPMatcher
from apps.transfers.models import TransferRequest, TransferRequestItem

TODAY = timezone.localdate()
NOW = datetime.datetime.combine(TODAY, datetime.time(11, 0))

_COND = re.compile(r"\b(?:sm|st)\.(\w+)\s*(=|>=|<=)\s*(\?|'[^']*')")


def doc(number, branch, doccode, items, header=True, day=None):
    return {'docnumber': number, 'branchcode': branch, 'doccode': doccode, 'items': items,
            'header': header, 'docdate': datetime.datetime.combine(day or TODAY, datetime.time())}


class FakeSoftech:
    """stktransm/stktrans as a list of documents; every query is answered by its WHERE clause."""

    def __init__(self, docs):
        self.docs, self.queries = docs, []

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        pass


class _FakeCursor:
    def __init__(self, conn):
        self.conn, self.rows, self.description = conn, [], []

    def execute(self, sql, params=None):
        self.rows = []
        if 'dbo.stktrans' not in sql:          # SET ROWCOUNT, users, localcustomers
            return
        params, conds = list(params or []), []
        for col, op, val in _COND.findall(sql):
            conds.append((col, op, params.pop(0) if val == '?' else val.strip("'")))
        self.conn.queries.append((sql, conds))

        def keep(d):
            for col, op, v in conds:
                have = d['docdate'].date().isoformat() if col == 'docdate' else d[col]
                if col == 'docnumber':
                    have, v = int(have), int(v)
                else:
                    have, v = str(have).strip(), str(v).strip()
                if (op == '=' and have != v) or (op == '>=' and have < v) or (op == '<=' and have > v):
                    return False
            return True

        hits = [d for d in self.conn.docs if keep(d)]
        if 'SELECT st.itemcode' in sql:
            self.rows = [(code, qty, qty * 10, 'S1', None) for d in hits for code, qty in d['items']]
        elif 'stktransm sm' in sql:
            self.rows = [(d['docnumber'], d['doccode'], d['branchcode'], d['docdate'], 100.0, '', 'S1', '')
                         for d in hits if d['header']]
        else:                                  # header derived from stktrans lines
            self.rows = [(d['docnumber'], d['doccode'], d['branchcode'], None, None, None, 'S1')
                         for d in hits if d['items']]

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def close(self):
        pass


# ── Transfer matcher (apps/transfers/erp_matcher.py) ─────────────────────────

class TransferMatcherKeyingTests(TestCase):

    def setUp(self):
        self.src, self.dst = make_branch('مصدر', '130'), make_branch('طالب', '140')
        _, staff, _ = make_user('dk_tr', role='pharmacist', branch=self.dst)
        self.item = make_item('صنف مفتاح', 'DK1')
        self.tr = TransferRequest.objects.create(
            requesting_branch=self.dst, supplying_branch=self.src, created_by=staff,
            status='sent_to_erp', erp_match_status='pending', erp_reference='500')
        TransferRequestItem.objects.create(request=self.tr, item=self.item, quantity=5)

    def run_with(self, docs):
        return ERPMatcher(self.tr, conn=FakeSoftech(docs)).run()

    def test_lines_come_only_from_the_supplying_branchs_125(self):
        r = self.run_with([doc(500, '130', '125', [('DK1', 5)]),
                           doc(500, '150', '125', [('DK1', 40)]),
                           doc(500, '130', '115', [('DK1', 99)])])
        self.assertEqual(r['status'], 'matched')
        self.assertTrue(r['branch_matched'])
        self.assertEqual(r['matched_items'][0]['erp_qty'], 5.0)

    def test_batch_rows_of_one_document_are_summed(self):
        r = self.run_with([doc(500, '130', '125', [('DK1', 2), ('DK1', 3)])])
        self.assertEqual(r['status'], 'matched')
        self.assertEqual(r['matched_items'][0]['erp_qty'], 5.0)

    def test_line_only_document_is_read_with_its_doccode(self):
        r = self.run_with([doc(500, '130', '125', [('DK1', 5)], header=False),
                           doc(500, '130', '115', [('DK1', 99)], header=False)])
        self.assertEqual(r['status'], 'matched')
        self.assertEqual(r['matched_items'][0]['erp_qty'], 5.0)

    def test_another_branchs_125_is_never_a_full_match(self):
        r = self.run_with([doc(500, '150', '125', [('DK1', 5)])])
        self.assertEqual(r['status'], 'partial')
        self.assertFalse(r['branch_matched'])
        self.assertEqual(r['actual_branch'], '150')

    def test_two_other_branches_with_the_number_refuse_to_guess(self):
        r = self.run_with([doc(500, '150', '125', [('DK1', 5)]),
                           doc(500, '160', '125', [('DK1', 5)])])
        self.assertEqual(r['status'], 'not_found')
        self.assertIn('150', r['detail'])
        self.assertIn('160', r['detail'])

    def test_same_number_as_another_doctype_is_not_the_transfer(self):
        r = self.run_with([doc(500, '130', '115', [('DK1', 5)]),
                           doc(500, '150', '30', [('DK1', 5)])])
        self.assertEqual(r['status'], 'not_found')

    def test_other_branch_outside_the_date_window_is_ignored(self):
        old = TODAY - datetime.timedelta(days=60)
        r = self.run_with([doc(500, '150', '125', [('DK1', 5)], day=old)])
        self.assertEqual(r['status'], 'not_found')

    def test_auto_search_scores_lines_with_the_candidates_doccode(self):
        self.tr.erp_reference = ''
        self.tr.save(update_fields=['erp_reference'])
        r = self.run_with([doc(700, '130', '125', [('DK1', 5)]),
                           doc(700, '130', '115', [('DK1', 50)])])
        self.assertEqual(r['discovered_doc'], '700')
        self.assertEqual(r['matched_items'][0]['erp_qty'], 5.0)

    def test_every_stktrans_query_carries_branch_and_doccode(self):
        conn = FakeSoftech([doc(500, '150', '125', [('DK1', 5)])])
        ERPMatcher(self.tr, conn=conn).run()
        for sql, conds in conn.queries:
            cols = {c for c, _, _ in conds}
            self.assertIn('doccode', cols, sql)
            self.assertTrue('branchcode' in cols or 'docdate' in cols, sql)


# ── Reservation matcher (apps/reservations/erp_matcher.py) ───────────────────

class ReservationMatcherKeyingTests(TestCase):

    def setUp(self):
        self.branch = make_branch('فرع الحجز', '130')
        _, self.staff, _ = make_user('dk_res', role='pharmacist', branch=self.branch)
        self.item = make_item('صنف مفتاح', 'DK1')
        self.res = Reservation.objects.create(
            item=self.item, branch=self.branch, quantity_requested=Decimal('5'),
            contact_name='زبون', contact_phone='01000000009', created_by=self.staff,
            erp_reference='500')

    def run_with(self, docs):
        conn = FakeSoftech(docs)
        with mock.patch('config.sybase.get_sybase_connection', lambda: conn):
            return ReservationERPMatcher(self.res).run(), conn

    def test_lines_come_only_from_the_reservation_branchs_sale(self):
        r, _ = self.run_with([doc(500, '130', '115', [('DK1', 5)]),
                              doc(500, '150', '115', [('DK1', 40)]),
                              doc(500, '130', '30', [('DK1', 99)])])
        self.assertEqual(r['status'], 'matched')
        self.assertTrue(r['branch_matched'])
        self.assertEqual(r['matched_items'][0]['erp_qty'], 5.0)
        self.assertEqual([ln['qty'] for ln in r['receipt_lines']], [5.0])

    def test_another_branchs_sale_is_never_a_full_match(self):
        r, _ = self.run_with([doc(500, '150', '115', [('DK1', 5)])])
        self.assertEqual(r['status'], 'partial')
        self.assertFalse(r['branch_matched'])
        self.assertEqual(r['actual_branch'], '150')

    def test_two_other_branches_with_the_number_refuse_to_guess(self):
        r, _ = self.run_with([doc(500, '150', '115', [('DK1', 5)]),
                              doc(500, '160', '115', [('DK1', 5)])])
        self.assertEqual(r['status'], 'not_found')
        self.assertIn('150', r['detail'])

    def test_same_number_as_another_doctype_is_not_the_sale(self):
        r, _ = self.run_with([doc(500, '130', '125', [('DK1', 5)]),
                              doc(500, '150', '10', [('DK1', 5)])])
        self.assertEqual(r['status'], 'not_found')

    def test_line_only_sale_is_read_with_its_doccode(self):
        r, _ = self.run_with([doc(500, '130', '115', [('DK1', 5)], header=False),
                              doc(500, '130', '30', [('DK1', 99)], header=False)])
        self.assertEqual(r['status'], 'matched')
        self.assertEqual(r['matched_items'][0]['erp_qty'], 5.0)

    def test_auto_search_scores_lines_with_the_candidates_doccode(self):
        self.res.erp_reference = ''
        self.res.save(update_fields=['erp_reference'])
        r, conn = self.run_with([doc(700, '130', '115', [('DK1', 5)]),
                                 doc(700, '130', '30', [('DK1', 50)])])
        self.assertEqual(r['discovered_doc'], '700')
        self.assertEqual(r['matched_items'][0]['erp_qty'], 5.0)
        for sql, conds in conn.queries:
            self.assertIn('doccode', {c for c, _, _ in conds}, sql)


# ── Insurance: cross-claim duplicate check (apps/insurance/validation.py) ────

class InsuranceDuplicateCheckKeyingTests(TestCase):

    def _dupes(self, other_branch):
        mine = _mk_claim(number='MT-DK-1')
        _add_rx(mine, '6100', local=100, branch='140')
        other = _mk_claim(number='MT-DK-2', sub=mine.subclient)
        _add_rx(other, '6100', local=100, branch=other_branch)
        checks = {c['key']: c for c in validate_claim_readiness(mine)['checks']}
        return checks['cross_claim_duplicates']

    def test_same_number_at_another_branch_is_not_a_double_bill(self):
        self.assertEqual(self._dupes('150')['severity'], 'ok')

    def test_same_receipt_at_the_same_branch_is_a_double_bill(self):
        self.assertEqual(self._dupes('140')['severity'], 'error')


# ── Insurance: cache enrichment (apps/insurance/importer.py) ─────────────────

class InsuranceEnrichmentKeyingTests(TestCase):

    def _cache(self, branch, roshetta):
        m.CompaniesItemsCache.objects.create(branchcode=branch, docnumber='6200', doccode='115',
                                             roshettano=roshetta)

    def test_another_branchs_prescription_does_not_enrich(self):
        claim = _mk_claim(number='MT-DK-3')
        rx = _add_rx(claim, '6200', local=10, branch='140')
        self._cache('150', 'R-OTHER')
        self._cache('160', 'R-THIRD')
        importer.enrich_prescriptions_from_cache(claim)
        rx.refresh_from_db()
        self.assertEqual(rx.roshetta_no, '')

    def test_own_branch_wins_over_another_branch(self):
        claim = _mk_claim(number='MT-DK-4')
        rx = _add_rx(claim, '6200', local=10, branch='140')
        self._cache('150', 'R-OTHER')
        self._cache('140', 'R-MINE')
        importer.enrich_prescriptions_from_cache(claim)
        rx.refresh_from_db()
        self.assertEqual(rx.roshetta_no, 'R-MINE')


# ── Insurance: parent-code guard on a manual add (apps/insurance/importer.py) ─

class InsuranceMotalbaGuardKeyingTests(TestCase):

    def setUp(self):
        client = m.InsuranceClient.objects.create(name='عميل')
        self.sub = m.InsuranceSubClient.objects.create(client=client, name='فئة', softech_personcode='5008')
        self.claim = m.InsuranceClaim.objects.create(
            claim_number='MT-DK-5', subclient=self.sub,
            period_from=datetime.date(2026, 10, 1), period_to=datetime.date(2026, 10, 31))

    def _motalba(self, branch):
        m.MotalbaCache.objects.create(personcode='X999', ppersoncode='X999', motalbano=1, branchcode=branch,
                                      docnumber=INS_DOC, doccode='30', docdate=datetime.date(2026, 10, 21))

    def _add(self):
        with mock.patch.object(importer, '_get_connection', return_value=ins_conn(INS_LINES, INS_HEADERS)):
            return importer.fetch_single_rx_from_softech(INS_DOC, self.claim, branchcode=INS_BRANCH)

    def test_another_branchs_motalba_row_does_not_block_the_receipt(self):
        self._motalba('150')
        self.assertEqual([ln['itemcode'] for ln in self._add()['lines']], ['RET'])

    def test_own_branchs_foreign_motalba_row_still_blocks(self):
        self._motalba(INS_BRANCH)
        with self.assertRaisesRegex(importer.InsuranceImportError, 'X999'):
            self._add()


# ── Static guard: shared SOFTECH read SQL ────────────────────────────────────

class SharedQueryKeyingTests(TestCase):
    """Every stktrans/stktransm query in apps/sync/sybase_queries.py that looks a document up
    by docnumber also filters doccode, and either the branch or (for the one cross-branch
    lookup) a docdate window."""

    def test_no_bare_docnumber_lookup(self):
        path = Path(__file__).resolve().parents[1] / 'sync' / 'sybase_queries.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        checked = 0
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                continue
            sql = node.value.value
            if 'stktrans' not in sql or not re.search(r'\b(?:sm|st)\.docnumber\s*=\s*\?', sql):
                continue
            name = node.targets[0].id
            checked += 1
            self.assertRegex(sql, r'\b(?:sm|st)\.doccode\b', name)
            self.assertTrue(re.search(r'\b(?:sm|st)\.branchcode\s*=\s*\?', sql)
                            or re.search(r'\bsm\.docdate\s*>=\s*\?', sql), name)
        self.assertGreaterEqual(checked, 4)
