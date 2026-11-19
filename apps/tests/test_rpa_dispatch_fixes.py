"""Final-review fixes on the claim / report path (never double post, dry run never saves).

- a SOFTECH document carrying our reference is the document even when its lines differ: it goes
  to a person, never back to "not found";
- after a dry_run_ok report SOFTECH is asked whether anything was saved;
- the operator sees why the agent is idle when SOFTECH cannot be searched;
- a DB error while building the keyplan cannot poison the claim.
"""
import datetime
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.rpa import dispatch
from apps.rpa.models import RpaDevice, RpaDocument, RpaRun
from apps.tests.test_rpa_agent_api import FIND, ON, _World


def _found(docnumber, lines):
    return {'docnumber': docnumber, 'usercode': '', 'cust_branch_code': 'FXB', 'matched_by': 'reference',
            'lines': lines}


@override_settings(**ON)
class DispatchFixTests(_World, TestCase):

    def setUp(self):
        self.build_world('FX')
        self.dev, _ = self.device()
        p = mock.patch(FIND, return_value=None)
        self.find = p.start()
        self.addCleanup(p.stop)

    def _claimed(self):
        doc = self.make_doc()
        claim = dispatch.claim_next(self.dev)
        self.assertEqual(claim.document.pk, doc.pk)
        return doc, claim.run

    def _report(self, doc, run, outcome='dry_run_ok'):
        dispatch.report_run(doc, self.dev, {'run_id': run.pk, 'outcome': outcome, 'steps': []})
        doc.refresh_from_db()
        run.refresh_from_db()
        return AuditLog.objects.filter(action='rpa_run_reported', object_id=str(doc.pk)).latest('id')

    # ── reference hit with differing lines (spec 5.3) ─────────────────────────────────────────

    def test_reference_hit_with_other_lines_goes_to_person_not_typed(self):
        doc = self.make_doc()
        other = [{'itemcode': '52', 'qty': Decimal('1'), 'expiry': datetime.date(2027, 5, 1)}]
        self.find.return_value = _found(4100, other)
        self.assertIsNone(dispatch.claim_next(self.dev))
        doc.refresh_from_db()
        self.assertEqual((doc.status, doc.softech_docnumber), ('needs_person', 4100))
        self.assertIn('لا يطابق', doc.needs_person_reason)
        self.assertFalse(RpaRun.objects.exists())

    # ── dry run must leave nothing in SOFTECH ─────────────────────────────────────────────────

    def test_dry_run_ok_with_clean_softech_stays_dry_run_ok(self):
        doc, run = self._claimed()
        log = self._report(doc, run)
        self.assertEqual(doc.status, 'dry_run_ok')
        self.assertEqual(log.new_data['softech_check'], 'clear')
        self.assertEqual(self.find.call_count, 2)          # once at claim, once after the dry run

    def test_dry_run_that_saved_goes_to_person(self):
        doc, run = self._claimed()
        self.find.return_value = _found(4200, [])
        log = self._report(doc, run)
        self.assertEqual((doc.status, doc.softech_docnumber), ('needs_person', 4200))
        self.assertIn('تشغيل تجريبي', doc.needs_person_reason)
        self.assertEqual(log.new_data['softech_check'], 'found')
        self.assertEqual(run.outcome, 'dry_run_ok')
        verified = AuditLog.objects.get(action='rpa_document_verified', object_id=str(doc.pk))
        self.assertIs(verified.new_data['saved_in_dry_run'], True)

    def test_dry_run_ok_with_softech_down_is_kept_but_marked_unchecked(self):
        doc, run = self._claimed()
        self.find.side_effect = ConnectionError('host 10.0.0.9 password=hunter2')
        with self.assertLogs('apps.rpa.dispatch', 'WARNING') as logs:
            log = self._report(doc, run)
        self.assertNotIn('hunter2', ''.join(logs.output))
        self.assertEqual(doc.status, 'dry_run_ok')
        self.assertEqual(log.new_data['softech_check'], 'not_checked')
        self.assertEqual(run.steps[-1]['note'], dispatch.NOT_CHECKED_NOTE)
        self.assertFalse(run.steps[-1]['ok'])

    # ── operator sees why nothing happens ────────────────────────────────────────────────────

    def test_softech_down_is_shown_on_status_then_cleared(self):
        self.make_doc()
        self.find.side_effect = ConnectionError('down')
        with self.assertLogs('apps.rpa.dispatch', 'WARNING'):
            self.assertIsNone(dispatch.claim_next(self.dev))
        self.dev.refresh_from_db()
        self.assertEqual(self.dev.last_claim_error, dispatch.SOFTECH_DOWN)
        self.assertIsNotNone(self.dev.last_claim_error_at)
        RpaDevice.objects.filter(pk=self.dev.pk).update(last_seen_at=timezone.now())
        staff = APIClient()
        staff.force_authenticate(user=self.staff.user)
        r = staff.get('/api/rpa/status/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['last_claim_error'], dispatch.SOFTECH_DOWN)
        self.assertEqual(r.data['my_devices_online'][0]['last_claim_error'], dispatch.SOFTECH_DOWN)
        self.find.side_effect = None
        self.find.return_value = None
        self.assertIsNotNone(dispatch.claim_next(self.dev))
        self.dev.refresh_from_db()
        self.assertEqual((self.dev.last_claim_error, self.dev.last_claim_error_at), ('', None))

    # ── claim guards ─────────────────────────────────────────────────────────────────────────

    def test_db_error_while_building_keyplan_goes_to_person(self):
        first = self.make_doc()
        second = self.make_doc()
        real = dispatch.build_keyplan

        def broken(document, *, mode):
            if document.pk == first.pk:
                with connection.cursor() as cur:
                    cur.execute('SELECT * FROM rpa_no_such_table')
            return real(document, mode=mode)

        with mock.patch('apps.rpa.dispatch.build_keyplan', side_effect=broken), \
                self.assertLogs('elrezeiky.errors', 'ERROR'):
            claim = dispatch.claim_next(self.dev)
        self.assertEqual(claim.document.pk, second.pk)
        first.refresh_from_db()
        self.assertEqual(first.status, 'needs_person')
        self.assertNotIn('rpa_no_such_table', first.needs_person_reason)

    def test_branch_without_softech_server_goes_to_person_unsearched(self):
        doc = self.make_doc()
        self.src.db_host = ''
        self.src.save(update_fields=['db_host'])
        self.assertIsNone(dispatch.claim_next(self.dev))
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'needs_person')
        self.assertIn('سيرفر', doc.needs_person_reason)
        self.find.assert_not_called()
        self.assertEqual(RpaDocument.objects.get(pk=doc.pk).claimed_by_id, None)


@override_settings(**ON)
class ScheduledLeaseSweepTests(_World, TestCase):
    """A lost robot's document goes to a person on the 5-minute scheduler job, not only when some
    device next asks for work (claim_next): with every agent down nothing else would sweep it."""

    def setUp(self):
        self.build_world('SW')
        self.dev, _ = self.device()
        p = mock.patch(FIND, return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def test_scheduler_registers_the_lease_sweep_every_5_minutes(self):
        from apps.tests.test_scheduler_locks import _registered
        job = _registered()['rpa_expire_leases']
        self.assertEqual(job.get('minutes'), 5)
        self.assertEqual((job.get('max_instances'), job.get('coalesce')), (1, True))

    def test_scheduled_run_sends_an_expired_lease_to_a_person(self):
        from apps.sync import tasks
        doc = self.make_doc()
        run = dispatch.claim_next(self.dev).run
        RpaDocument.objects.filter(pk=doc.pk).update(lease_until=timezone.now() - datetime.timedelta(seconds=1))
        with override_settings(RPA_SOFTECH_ENTRY_ENABLED=False):     # the sweep never needs the switch
            tasks._run_rpa_expire_leases()
        doc.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual((doc.status, run.outcome), ('needs_person', 'timeout'))
        tasks._run_rpa_expire_leases()                                # a second run finds nothing
        self.assertEqual(AuditLog.objects.filter(action='rpa_document_needs_person',
                                                 object_id=str(doc.pk)).count(), 1)

    def test_a_failing_sweep_is_logged_not_raised(self):
        from apps.sync import tasks
        with mock.patch('apps.rpa.dispatch.sweep_expired_leases', side_effect=RuntimeError('db 01012345678')), \
                self.assertLogs('elrezeiky.sync', 'ERROR') as logs:
            tasks._run_rpa_expire_leases()
        self.assertNotIn('01012345678', '\n'.join(logs.output))     # type only, never the message text
