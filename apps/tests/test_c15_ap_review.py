"""Top-10 C15: A/P reconciliation exception review — bulk decisions, sticky against re-scans,
never releasing a held match by itself, and the weekly finance digest. Mirror only (no SOFTECH)."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase, override_settings

from apps.finance import recon_actions as A
from apps.finance import recon_review as R
from apps.finance.models import (APInvoice, MatchCandidate, Payment, ReconAuditEvent, ReconException,
                                 ReconParty)

T0 = date(2026, 6, 1)


class Base(TestCase):

    def setUp(self):
        self.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='S 4471')
        self.n = 0

    def pair(self, value='500'):
        self.n += 1
        inv = APInvoice.objects.create(party=self.party, branchcode='130', doccode='10',
                                       docnumber=str(1000 + self.n), docdate=T0,
                                       doc_value=D(value), doc_value_pay=D('0'), party_type='supplier')
        pay = Payment.objects.create(party=self.party, branchcode='130', cheqsno=5000 + self.n,
                                     direction='out', party_type='supplier', voucher_date=T0 + timedelta(days=5),
                                     amount=D(value), is_unallocated=True, cheqno=inv.docnumber)
        cand = MatchCandidate.objects.create(party=self.party, invoice=inv, payment=pay, proposed_amount=D(value),
                                             confidence_class='high', confidence_score=D('90'), strategy='pairwise')
        return inv, pay, cand

    def exc(self, etype=ReconException.TYPE_DUPLICATE_PAYMENT, payment=None, invoice=None, severity='critical'):
        return ReconException.objects.create(party=self.party, payment=payment, invoice=invoice,
                                             exception_type=etype, severity=severity, detail='x')


class DecideTests(Base):

    def test_resolved_and_dismissed_need_a_note(self):
        e = self.exc()
        for action in ('resolved', 'dismissed'):
            with self.assertRaises(R.ReviewError):
                R.decide([e.pk], action, note='  ')
        with self.assertRaises(R.ReviewError):
            R.decide([e.pk], 'deleted', note='x')

    def test_decide_stamps_audits_and_reopen_clears(self):
        e1, e2 = self.exc(), self.exc(etype=ReconException.TYPE_ANOMALY, severity='warning')
        res = R.decide([e1.pk, e2.pk, 999999], 'dismissed', note='سند واحد مكرر في الإدخال فقط')
        self.assertEqual((res['changed'], res['missing']), (2, [999999]))
        e1.refresh_from_db()
        self.assertEqual(e1.status, 'dismissed')
        self.assertIsNotNone(e1.resolved_at)
        self.assertIn('ليس خطأ: سند واحد مكرر', e1.resolution_notes)
        ev = ReconAuditEvent.objects.filter(action='exception_dismissed').order_by('pk').first()
        self.assertEqual((ev.before_state['status'], ev.after_state['status']), ('open', 'dismissed'))
        R.decide([e1.pk], 'open')
        e1.refresh_from_db()
        self.assertEqual((e1.status, e1.resolved_at), ('open', None))
        self.assertEqual(R.decide([e1.pk], 'open')['unchanged'], 1)

    def test_at_most_max_ids(self):
        with self.assertRaises(R.ReviewError):
            R.decide(list(range(1, R.MAX_IDS + 2)), 'investigating')


class StickyTests(Base):

    def test_a_person_decision_is_not_raised_again_but_an_auto_close_is(self):
        from apps.finance.recon_anomalies import _upsert_exc
        _, pay, _ = self.pair()
        e = self.exc(payment=pay)
        R.decide([e.pk], 'dismissed', note='ليس مكرراً')
        self.assertFalse(_upsert_exc(self.party, ReconException.TYPE_DUPLICATE_PAYMENT, 'critical', payment=pay))
        # the scanner's own auto-close (no resolved_at) → the same facts may be raised again
        e2 = self.exc(etype=ReconException.TYPE_OVERPAYMENT, payment=pay)
        ReconException.objects.filter(pk=e2.pk).update(status='resolved', resolution_notes='أُغلق تلقائيًا')
        self.assertTrue(_upsert_exc(self.party, ReconException.TYPE_OVERPAYMENT, 'critical', payment=pay))

    def test_engine_upsert_respects_investigating(self):
        from apps.finance.recon_engine import _upsert_exc
        _, pay, _ = self.pair()
        e = self.exc(etype=ReconException.TYPE_ORPHAN_PAYMENT, payment=pay, severity='warning')
        R.decide([e.pk], 'investigating')
        _upsert_exc(None, self.party, ReconException.TYPE_ORPHAN_PAYMENT, 'warning', payment=pay)
        self.assertEqual(ReconException.objects.filter(exception_type=ReconException.TYPE_ORPHAN_PAYMENT).count(), 1)


@override_settings(AP_RECONCILE_AUTO_APPROVE=True)
class HoldTests(Base):
    """A person's decision never releases a held match by itself (no new path to a SOFTECH write)."""

    def status(self, c):
        c.refresh_from_db()
        return c.status

    def test_investigating_and_person_decided_flags_keep_holding(self):
        cands = []
        for action in ('investigating', 'dismissed', 'resolved'):
            _, pay, c = self.pair()
            R.decide([self.exc(payment=pay).pk], action, note='مراجعة')
            cands.append(c)
        A.auto_approve()
        self.assertEqual([self.status(c) for c in cands], ['proposed'] * 3)

    def test_only_the_scanner_auto_close_releases(self):
        _, pay, c = self.pair()
        e = self.exc(payment=pay)
        ReconException.objects.filter(pk=e.pk).update(status='resolved', resolution_notes='أُغلق تلقائيًا')
        A.auto_approve()
        self.assertEqual(self.status(c), 'approved')


class ApiTests(Base):
    URL = '/api/finance/reconciliation/exceptions/decide/'

    def setUp(self):
        super().setUp()
        from django.core.management import call_command
        from apps.tests.factories import make_admin, make_user
        call_command('seed_permissions', verbosity=0)
        _, _, self.admin = make_admin('c15_admin')
        _, _, self.viewer = make_user('c15_viewer', role='viewer')
        _, _, self.accountant = make_user('c15_accountant', role='accountant')

    def test_the_accountant_decides_exceptions_but_still_cannot_approve_a_match(self):
        # owner 2026-11-19: the accountant reviews exceptions; matches stay with admin / pharmacist
        e = self.exc()
        r = self.accountant.post(self.URL, {'ids': [e.pk], 'action': 'dismissed', 'note': 'مراجعة المحاسب'},
                                 format='json')
        self.assertEqual(r.status_code, 200, r.content)
        e.refresh_from_db()
        self.assertEqual(e.status, 'dismissed')
        _, _, cand = self.pair()
        r = self.accountant.post(f'/api/finance/reconciliation/candidates/{cand.pk}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 403)
        cand.refresh_from_db()
        self.assertEqual(cand.status, 'proposed')

    def test_admin_decides_viewer_cannot(self):
        e = self.exc()
        r = self.admin.post(self.URL, {'ids': [e.pk], 'action': 'investigating'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['changed'], 1)
        e.refresh_from_db()
        self.assertEqual(e.status, 'investigating')
        r = self.viewer.post(self.URL, {'ids': [e.pk], 'action': 'open'}, format='json')
        self.assertEqual(r.status_code, 403)
        e.refresh_from_db()
        self.assertEqual(e.status, 'investigating')

    def test_missing_note_is_400(self):
        e = self.exc()
        r = self.admin.post(self.URL, {'ids': [e.pk], 'action': 'resolved', 'note': ''}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_list_filters_by_status_and_shows_the_note(self):
        e = self.exc()
        R.decide([e.pk], 'dismissed', note='سبب')
        r = self.admin.get('/api/finance/reconciliation/exceptions/', {'status': 'dismissed'})
        rows = r.json()['results']
        self.assertEqual([x['id'] for x in rows], [e.pk])
        self.assertIn('سبب', rows[0]['resolution_notes'])


class DigestTests(Base):

    def test_weekly_digest_once_per_week_to_accountants(self):
        from apps.notifications.models import Notification
        from apps.tests.factories import make_user
        _, acc, _ = make_user('c15_acc', role='accountant')
        _, pay, c = self.pair('1250')
        self.exc(payment=pay)
        MatchCandidate.objects.filter(pk=c.pk).update(decision_note='السند عليه تنبيه')
        self.assertEqual(R.weekly_digest(today=date(2026, 11, 22))['sent'], 1)
        self.assertEqual(R.weekly_digest(today=date(2026, 11, 22))['sent'], 0)          # same ISO week
        n = Notification.objects.get(recipient=acc, notification_type='ap_review_digest')
        self.assertIn('سند مكرر', n.body)
        self.assertIn('1,250', n.body)
        self.assertIn('مطابقات موقوفة للمراجعة: 1', n.body)

    def test_scheduler_has_the_job(self):
        import inspect
        from apps.sync import tasks
        self.assertIn("id='ap_review_digest'", inspect.getsource(tasks))
