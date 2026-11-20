"""Decide parked mixed journal groups by pattern (spec docs/superpowers/specs/2026-11-20-gl-mixed-patterns-design.md).

Synthetic groups only, parked through the real importer. Nothing here is approved or sent to SOFTECH.
"""
from unittest import mock

from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.finance.gl import mixed_patterns as mp
from apps.finance.gl.ledger import LedgerError
from apps.finance.gl.plan2_adapter import MIXED_MANUAL_KIND
from apps.finance.models import GLSourceDoc, LedgerEntry, SourceException
from apps.tests.factories import make_user
from apps.tests.test_gl_manual_import import BASE, D2, GLManualBase, row

PATTERNS = BASE + 'exceptions/mixed-patterns/'
DECIDE = PATTERNS + 'decide/'


class PatternBase(GLManualBase):
    def park(self):
        """Three groups on pattern cash|3280|1302 (one carries the link account) + one on cash|1296|6002."""
        res = self.run_import([
            row('1302', debit=50, desc='ا'), row('3280', credit=50, desc='ا'),
            row('1302', debit=30, desc='ب'), row('3280', credit=30, desc='ب'),
            row('1302', debit=20, desc='ج', date=D2), row('3280', credit=15, desc='ج', date=D2),
            row('2354', credit=5, desc='ج', date=D2),
            row('6002', debit=9, desc='د'), row('1296', credit=9, desc='د'),
        ])
        self.assertEqual(res['parked'], 4)

    def open_rows(self):
        return SourceException.objects.filter(kind=MIXED_MANUAL_KIND, status='open')

    def by_pattern(self):
        return {p['pattern']: p for p in mp.list_patterns()}


class ServiceTests(PatternBase):
    def test_groups_by_book_manual_and_softech_accounts(self):
        self.park()
        pats = self.by_pattern()
        self.assertEqual(set(pats), {'cash|3280|1302', 'cash|1296|6002'})
        p = pats['cash|3280|1302']
        self.assertEqual((p['count'], p['manual_accounts'], p['softech_accounts'], p['book']),
                         (3, ['3280'], ['1302'], 'cash'))
        self.assertEqual(str(p['debit']), '100.00')
        self.assertEqual(len(p['samples']), 3)
        self.assertEqual(list(pats)[0], 'cash|3280|1302')   # most groups first

    def test_import_all_creates_drafts_and_resolves(self):
        self.park()
        res = mp.decide(pattern='cash|3280|1302', decision='import', expected_count=3, note='', user=self.staff)
        self.assertEqual((res['imported'], res['failed']), (3, []))
        entries = LedgerEntry.objects.filter(source_type='manual_import')
        self.assertEqual(entries.count(), 3)
        self.assertTrue(all(e.status == 'draft' for e in entries))
        self.assertTrue(all(ln.branch_id == self.branch.pk for e in entries for ln in e.lines.all()))
        self.assertEqual(self.open_rows().count(), 1)    # the other pattern is untouched
        self.assertEqual(GLSourceDoc.objects.filter(source_type='manual_import', status='drafted').count(), 3)

    def test_ignore_all_needs_a_note_and_ignores(self):
        self.park()
        with self.assertRaises(mp.PatternError) as c:
            mp.decide(pattern='cash|1296|6002', decision='ignore', expected_count=1, note='  ', user=self.staff)
        self.assertEqual(c.exception.code, 'note_required')
        res = mp.decide(pattern='cash|1296|6002', decision='ignore', expected_count=1,
                        note='سوفتيك بيغطيه', user=self.staff)
        self.assertEqual(res['ignored'], 1)
        e = SourceException.objects.get(kind=MIXED_MANUAL_KIND, status='ignored')
        self.assertEqual(e.resolution_note, 'سوفتيك بيغطيه')
        self.assertFalse(LedgerEntry.objects.filter(source_type='manual_import').exists())

    def test_count_changed_refused_and_nothing_changes(self):
        self.park()
        with self.assertRaises(mp.PatternError) as c:
            mp.decide(pattern='cash|3280|1302', decision='import', expected_count=2, note='', user=self.staff)
        self.assertEqual(c.exception.code, 'count_changed')
        with self.assertRaises(mp.PatternError) as c:
            mp.decide(pattern='cash|9|9', decision='import', expected_count=0, note='', user=self.staff)
        self.assertEqual(c.exception.code, 'unknown_pattern')
        with self.assertRaises(mp.PatternError) as c:
            mp.decide(pattern='cash|3280|1302', decision='approve', expected_count=3, note='', user=self.staff)
        self.assertEqual(c.exception.code, 'bad_decision')
        self.assertEqual(self.open_rows().count(), 4)

    def test_a_refused_draft_leaves_its_group_open_others_import(self):
        self.park()
        real = mp.save_draft
        calls = []

        def flaky(**kw):
            calls.append(1)
            if len(calls) == 2:
                raise LedgerError('period_closed')
            return real(**kw)
        with mock.patch.object(mp, 'save_draft', side_effect=flaky):
            res = mp.decide(pattern='cash|3280|1302', decision='import', expected_count=3, note='', user=self.staff)
        self.assertEqual((res['imported'], [f['code'] for f in res['failed']]), (2, ['period_closed']))
        self.assertEqual(self.by_pattern()['cash|3280|1302']['count'], 1)

    def test_already_live_key_is_settled_not_duplicated(self):
        self.park()
        e = self.open_rows().filter(source_doc__attrs__description='ا').get()
        mp.decide(pattern='cash|3280|1302', decision='import', expected_count=3, note='', user=self.staff)
        e.refresh_from_db()
        self.assertEqual(e.status, 'resolved')
        # a re-import of the same file finds them live: nothing new
        again = self.run_import([row('1302', debit=50, desc='ا'), row('3280', credit=50, desc='ا')])
        self.assertEqual((again['already_imported'], again['parked']), (1, 0))
        self.assertEqual(LedgerEntry.objects.filter(source_type='manual_import').count(), 3)

    def test_summary_audit_row(self):
        self.park()
        mp.decide(pattern='cash|3280|1302', decision='import', expected_count=3, note='', user=self.staff)
        a = AuditLog.objects.get(action='gl_mixed_pattern_decided')
        self.assertEqual(a.new_data['imported'], 3)
        self.assertEqual(a.new_data['pattern'], 'cash|3280|1302')


class ApiTests(PatternBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.pharm_user, _, _ = make_user('t9p_pharm', role='pharmacist')

    def setUp(self):
        self.acct = APIClient()
        self.acct.force_authenticate(self.staff.user)
        self.pharm = APIClient()
        self.pharm.force_authenticate(self.pharm_user)

    def test_list_and_decide_api(self):
        self.park()
        r = self.acct.get(PATTERNS)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([p['count'] for p in r.data['results']], [3, 1])
        self.assertEqual(self.pharm.get(PATTERNS).status_code, 403)
        body = {'pattern': 'cash|3280|1302', 'decision': 'import', 'expected_count': 3}
        self.assertEqual(self.pharm.post(DECIDE, body, format='json').status_code, 403)
        r = self.acct.post(DECIDE, body, format='json')
        self.assertEqual((r.status_code, r.data['imported']), (200, 3))

    def test_decide_409_on_count_changed(self):
        self.park()
        r = self.acct.post(DECIDE, {'pattern': 'cash|3280|1302', 'decision': 'import', 'expected_count': 5},
                           format='json')
        self.assertEqual((r.status_code, r.data['code']), (409, 'count_changed'))

    def test_decide_400_on_bad_input(self):
        self.park()
        for body in ({'pattern': 'cash|3280|1302', 'decision': 'x', 'expected_count': 3},
                     {'pattern': 'cash|1296|6002', 'decision': 'ignore', 'expected_count': 1},
                     {'pattern': 'cash|1296|6002', 'decision': 'ignore', 'expected_count': 1, 'note': 'x' * 2001},
                     {'pattern': 'cash|1296|6002', 'decision': 'ignore', 'expected_count': 'one', 'note': 'x'}):
            self.assertEqual(self.acct.post(DECIDE, body, format='json').status_code, 400, body)
        self.assertEqual(self.open_rows().count(), 4)
