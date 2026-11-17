"""Task 8: device tokens, claim / lease / report / screenshot, operator resolve.

The claim path is what stops the robot ever typing the same document into SOFTECH twice, so the
tests here pin: one claim per document (row lock, skip_locked), a document already in SOFTECH is
marked posted and never handed out, an expired lease goes to a person (never back to the queue),
and a repeated report changes nothing.
"""
import datetime
import hashlib
import io
import shutil
import tempfile
import threading
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.rpa import dispatch
from apps.rpa.auth import issue_device
from apps.rpa.models import RpaDevice, RpaDocument, RpaJob, RpaLine, RpaRecipe, RpaRun, RpaScreen, RpaScreenshot
from apps.tests.factories import make_branch, make_user

ON = dict(WRITER_INSTANCE=True, RPA_SOFTECH_ENTRY_ENABLED=True)
HEADER = 'HTTP_X_ELR_RPA_AGENT'
FIND = 'apps.rpa.dispatch.find_issue_document'
VERIFY = 'apps.rpa.dispatch.verify_issue_document'
KEYS = lambda v: {'kind': 'keys', 'value': v}
FIELD = lambda v: {'kind': 'field', 'value': v}


def _png(size=(4, 4)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', size, (10, 20, 30)).save(buf, format='PNG')
    return buf.getvalue()


def _upload(data, name='shot.png'):
    f = io.BytesIO(data)
    f.name = name            # the test client sends a nameless BytesIO as a plain field, not a file
    return f


class _World:
    """Screen, approved recipe, branches and helpers shared by both test case kinds."""

    def build_world(self, prefix):
        # the rpa matrix rows (users.0058): a TransactionTestCase flush in the kept DB wipes them
        import importlib

        from django.apps import apps as real_apps

        from core.middleware import module_access
        importlib.import_module('apps.users.migrations.0058_rpa_module').forwards(real_apps, None)
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        self.screen, _ = RpaScreen.objects.get_or_create(key='issue_125', defaults={'title_ar': 'إذن صرف'})
        self.screen.enabled = True
        self.screen.save()
        self.src = make_branch(f'{prefix} مصدر', f'{prefix}A')
        self.dst = make_branch(f'{prefix} مستلم', f'{prefix}B')
        self.src.db_host = '10.0.0.1'            # the verifier searches the source branch's server
        self.src.save(update_fields=['db_host'])
        _, self.staff, _ = make_user(f'{prefix}_op', role='supervisor', branch=self.src, access_all=True)
        self.recipe = RpaRecipe.objects.create(
            screen=self.screen, version=RpaRecipe.objects.filter(screen=self.screen).count() + 1,
            status='approved', created_by=self.staff, window_title='إذن صرف',
            line_cells=[FIELD('itemcode'), KEYS(r'\{TAB}'), FIELD('qty'), KEYS(r'\{ENTER}')],
            ref_cells=[FIELD('reference')], save_keys=[KEYS(r'\{F10}')], cancel_keys=[KEYS(r'\{ESC}')])

    def make_doc(self, staff=None, *, dry_run=True, status='approved'):
        staff = staff or self.staff
        job = RpaJob.objects.create(
            screen=self.screen, branch=self.src, target_branch=self.dst, recipe=self.recipe,
            created_by=staff, approved_by=staff, status='approved', dry_run=dry_run,
            approved_at=timezone.now())
        doc = RpaDocument.objects.create(job=job, seq=1, status=status)
        RpaLine.objects.create(document=doc, row_no=1, itemcode='52', qty=Decimal('2'),
                               expiry=datetime.date(2027, 5, 1))
        return doc

    def device(self, staff=None, label='جهاز'):
        return issue_device(staff=staff or self.staff, label=label, created_by=self.staff)


@override_settings(**ON)
class AgentApiTests(_World, TestCase):

    def setUp(self):
        self.build_world('T8')
        self.dev, self.secret = self.device()
        self.client = APIClient()
        self.client.credentials(**{HEADER: self.secret})
        p = mock.patch(FIND, return_value=None)
        self.find = p.start()
        self.addCleanup(p.stop)

    def claim(self, client=None):
        return (client or self.client).post('/api/rpa/agent/claim/')

    # ── device tokens ────────────────────────────────────────────────────────────────────────

    def test_issue_device_stores_only_the_hash(self):
        self.assertEqual(self.dev.token_hash, hashlib.sha256(self.secret.encode()).hexdigest())
        self.assertGreaterEqual(len(self.secret), 40)
        self.assertFalse(RpaDevice.objects.filter(token_hash=self.secret).exists())
        self.assertTrue(AuditLog.objects.filter(action='rpa_device_issued').exists())
        self.assertNotIn(self.secret, str(AuditLog.objects.filter(action='rpa_device_issued')
                                          .values_list('new_data', 'note').first()))

    def test_revoked_device_401(self):
        self.make_doc()
        RpaDevice.objects.filter(pk=self.dev.pk).update(revoked_at=timezone.now())
        self.assertEqual(self.claim().status_code, 401)
        stranger = APIClient()
        stranger.credentials(**{HEADER: 'not-a-token'})
        self.assertEqual(self.claim(stranger).status_code, 401)
        self.assertEqual(self.claim(APIClient()).status_code, 401)
        self.assertFalse(RpaRun.objects.exists())

    def test_inactive_operator_401(self):
        self.staff.is_active = False
        self.staff.save()
        self.assertEqual(self.claim().status_code, 401)

    def test_staff_login_does_not_open_agent_endpoints(self):
        from apps.tests.security.fixtures import bearer_client
        user, _, forced = make_user('t8_jwt', role='admin', access_all=True)
        self.make_doc()
        # a real staff JWT is not a device secret: the agent auth ignores it
        self.assertEqual(bearer_client(user).post('/api/rpa/agent/claim/').status_code, 401)
        # even a session forced onto the request has no device, so HasRpaDevice refuses it
        self.assertEqual(forced.post('/api/rpa/agent/claim/').status_code, 403)
        self.assertFalse(RpaRun.objects.exists())

    def test_last_seen_updated(self):
        self.claim()
        self.dev.refresh_from_db()
        self.assertIsNotNone(self.dev.last_seen_at)

    # ── claim ────────────────────────────────────────────────────────────────────────────────

    def test_claim_returns_run_and_keyplan(self):
        doc = self.make_doc()
        r = self.claim()
        self.assertEqual(r.status_code, 200)
        run = RpaRun.objects.get(document=doc)
        self.assertEqual(r.json()['run_id'], run.pk)
        self.assertEqual(r.json()['mode'], 'dry_run')
        self.assertEqual(r.json()['keyplan']['document'], doc.pk)
        self.assertEqual(r.json()['keyplan']['steps'][-1]['send'], '{ESC}')
        self.assertEqual((run.device_id, run.recipe_id, run.mode), (self.dev.pk, self.recipe.pk, 'dry_run'))
        self.assertIsNotNone(run.started_at)
        doc.refresh_from_db()
        self.assertEqual((doc.status, doc.claimed_by_id), ('in_progress', self.dev.pk))
        self.assertAlmostEqual((doc.lease_until - timezone.now()).total_seconds(), 600, delta=30)
        self.assertTrue(AuditLog.objects.filter(action='rpa_document_claimed').exists())
        self.assertEqual(self.claim().status_code, 204)

    def test_device_only_gets_own_staff_jobs(self):
        _, other, _ = make_user('t8_other', role='supervisor', branch=self.src, access_all=True)
        theirs = self.make_doc(other)                    # older: would be first if not filtered
        mine = self.make_doc()
        r = self.claim()
        self.assertEqual(r.json()['keyplan']['document'], mine.pk)
        self.assertEqual(self.claim().status_code, 204)
        theirs.refresh_from_db()
        self.assertEqual((theirs.status, theirs.claimed_by_id), ('approved', None))
        self.assertFalse(RpaRun.objects.filter(document=theirs).exists())
        # their device sees only theirs
        other_dev, other_secret = self.device(other, 'جهاز آخر')
        c = APIClient()
        c.credentials(**{HEADER: other_secret})
        r2 = self.claim(c)
        self.assertEqual(r2.json()['keyplan']['document'], theirs.pk)
        # and neither device can heartbeat / report / screenshot the other's document or run
        mine_run = RpaRun.objects.get(document=mine)
        self.assertEqual(c.post(f'/api/rpa/agent/documents/{mine.pk}/heartbeat/').status_code, 404)
        self.assertEqual(c.post(f'/api/rpa/agent/documents/{mine.pk}/report/',
                                {'run_id': mine_run.pk, 'mode': 'dry_run', 'outcome': 'error', 'steps': []},
                                format='json').status_code, 404)
        self.assertEqual(c.post(f'/api/rpa/agent/runs/{mine_run.pk}/screenshot/',
                                {'step_index': '1', 'image': _upload(_png())}).status_code, 404)
        mine.refresh_from_db()
        self.assertEqual(mine.status, 'in_progress')

    def test_cancelled_or_unapproved_job_not_claimed(self):
        doc = self.make_doc()
        RpaJob.objects.filter(pk=doc.job_id).update(status='cancelled')
        self.make_doc(status='pending')
        self.assertEqual(self.claim().status_code, 204)

    def test_switch_off_claims_nothing(self):
        doc = self.make_doc()
        with override_settings(RPA_SOFTECH_ENTRY_ENABLED=False):
            self.assertEqual(self.claim().status_code, 204)
        with override_settings(WRITER_INSTANCE=False):
            self.assertEqual(self.claim().status_code, 204)
        self.screen.enabled = False
        self.screen.save()
        self.assertEqual(self.claim().status_code, 204)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'approved')
        self.assertFalse(RpaRun.objects.exists())
        self.find.assert_not_called()

    def test_already_in_softech_marked_posted_not_typed(self):
        first = self.make_doc()
        second = self.make_doc()
        found = {'docnumber': 4711, 'usercode': 'u', 'cust_branch_code': 'T8B', 'matched_by': 'reference',
                 'lines': []}
        self.find.side_effect = lambda d: found if d.pk == first.pk else None
        with mock.patch(VERIFY, return_value={'ok': True, 'problems': []}):
            r = self.claim()
        self.assertEqual(r.json()['keyplan']['document'], second.pk)
        first.refresh_from_db()
        self.assertEqual((first.status, first.softech_docnumber), ('posted', 4711))
        self.assertEqual(first.verify_result['ok'], True)
        self.assertFalse(RpaRun.objects.filter(document=first).exists())
        self.assertTrue(AuditLog.objects.filter(action='rpa_document_verified', object_id=str(first.pk)).exists())

    def test_softech_lookup_failure_claims_nothing(self):
        doc = self.make_doc()
        self.find.side_effect = ConnectionError('host 10.0.0.9 password=hunter2')
        with self.assertLogs('apps.rpa.dispatch', 'WARNING') as logs:
            r = self.claim()
        self.assertEqual(r.status_code, 204)
        self.assertNotIn('hunter2', ''.join(logs.output))
        self.assertNotIn('10.0.0.9', ''.join(logs.output))
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'approved')

    def test_job_cancelled_after_selection_never_claimed(self):
        """The job row is not locked with the document: a cancel that lands between the candidate
        query's snapshot and the lock must still stop the claim."""
        doc = self.make_doc()
        real = dispatch._candidates

        class CancelAfterSelect:
            def __init__(self, qs):
                self.qs = qs

            def first(self):
                found = self.qs.first()
                if found is not None:
                    RpaJob.objects.filter(pk=found.job_id).update(status='cancelled')
                return found

        with mock.patch('apps.rpa.dispatch._candidates', side_effect=lambda d: CancelAfterSelect(real(d))):
            self.assertIsNone(dispatch.claim_next(self.dev))
        doc.refresh_from_db()
        self.assertEqual((doc.status, doc.claimed_by_id), ('approved', None))
        self.assertFalse(RpaRun.objects.exists())
        self.find.assert_not_called()

    def test_job_cancelled_during_softech_lookup_never_claimed(self):
        doc = self.make_doc()

        def cancel_meanwhile(document):
            RpaJob.objects.filter(pk=document.job_id).update(status='cancelled')
            return None

        self.find.side_effect = cancel_meanwhile
        self.assertIsNone(dispatch.claim_next(self.dev))
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'approved')
        self.assertFalse(RpaRun.objects.exists())

    def test_unexpected_keyplan_error_goes_to_person_and_queue_moves_on(self):
        first = self.make_doc()
        second = self.make_doc()
        real = dispatch.build_keyplan

        def boom(document, *, mode):
            if document.pk == first.pk:
                raise KeyError('secret-ish internal text')
            return real(document, mode=mode)

        with mock.patch('apps.rpa.dispatch.build_keyplan', side_effect=boom), \
                self.assertLogs('elrezeiky.errors', 'ERROR'):
            r = self.claim()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['keyplan']['document'], second.pk)
        first.refresh_from_db()
        self.assertEqual(first.status, 'needs_person')
        self.assertNotIn('secret-ish', first.needs_person_reason)
        self.assertIn('مرجع', first.needs_person_reason)
        self.assertTrue(AuditLog.objects.filter(action='rpa_document_needs_person',
                                                object_id=str(first.pk)).exists())

    def test_unbuildable_keyplan_goes_to_person(self):
        doc = self.make_doc()
        RpaRecipe.objects.filter(pk=self.recipe.pk).update(cancel_keys=[])
        self.assertEqual(self.claim().status_code, 204)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'needs_person')
        self.assertTrue(doc.needs_person_reason)
        self.assertFalse(RpaRun.objects.exists())

    def test_expired_lease_goes_to_needs_person_not_queue(self):
        doc = self.make_doc()
        run_id = self.claim().json()['run_id']
        RpaDocument.objects.filter(pk=doc.pk).update(lease_until=timezone.now() - datetime.timedelta(seconds=1))
        self.assertEqual(self.claim().status_code, 204)      # sweep runs, nothing requeued
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'needs_person')
        self.assertEqual(doc.needs_person_reason, 'انقطع الروبوت قبل الإبلاغ')
        run = RpaRun.objects.get(pk=run_id)
        self.assertEqual(run.outcome, 'timeout')
        self.assertIsNotNone(run.finished_at)
        self.assertTrue(AuditLog.objects.filter(action='rpa_document_needs_person', object_id=str(doc.pk)).exists())
        self.assertEqual(self.claim().status_code, 204)
        self.assertEqual(self.client.post(f'/api/rpa/agent/documents/{doc.pk}/heartbeat/').status_code, 409)
        # the late report changes nothing
        r = self.client.post(f'/api/rpa/agent/documents/{doc.pk}/report/',
                             {'run_id': run_id, 'mode': 'dry_run', 'outcome': 'dry_run_ok', 'steps': []},
                             format='json')
        self.assertEqual(r.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'needs_person')

    def test_sweep_runs_even_when_switched_off(self):
        doc = self.make_doc()
        self.claim()
        RpaDocument.objects.filter(pk=doc.pk).update(lease_until=timezone.now() - datetime.timedelta(seconds=1))
        with override_settings(RPA_SOFTECH_ENTRY_ENABLED=False):
            self.claim()
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'needs_person')

    # ── heartbeat ────────────────────────────────────────────────────────────────────────────

    def test_heartbeat_extends_lease(self):
        doc = self.make_doc()
        self.claim()
        soon = timezone.now() + datetime.timedelta(minutes=2)
        RpaDocument.objects.filter(pk=doc.pk).update(lease_until=soon)
        r = self.client.post(f'/api/rpa/agent/documents/{doc.pk}/heartbeat/')
        self.assertEqual(r.status_code, 200)
        doc.refresh_from_db()
        self.assertGreater(doc.lease_until, soon + datetime.timedelta(minutes=7))

    # ── report ───────────────────────────────────────────────────────────────────────────────

    def _report(self, doc, run_id, outcome, mode='dry_run', steps=None):
        return self.client.post(f'/api/rpa/agent/documents/{doc.pk}/report/',
                                {'run_id': run_id, 'mode': mode, 'outcome': outcome,
                                 'steps': steps if steps is not None else
                                 [{'i': 1, 'label': 'سطر 1', 'at': '2026-11-17T10:00:00+00:00',
                                   'ok': False, 'note': 'unknown_popup: خطأ'}]},
                                format='json')

    def test_unknown_popup_report_needs_person(self):
        doc = self.make_doc()
        run_id = self.claim().json()['run_id']
        r = self._report(doc, run_id, 'unknown_popup')
        self.assertEqual(r.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'needs_person')
        self.assertIn('unknown_popup', doc.needs_person_reason)
        self.assertIsNone(doc.lease_until)
        run = RpaRun.objects.get(pk=run_id)
        self.assertEqual(run.outcome, 'unknown_popup')
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(run.steps[0]['label'], 'سطر 1')
        audits = AuditLog.objects.filter(action='rpa_run_reported').count()
        # the agent retries: a second report is 200 and changes nothing
        r2 = self._report(doc, run_id, 'dry_run_ok', steps=[])
        self.assertEqual(r2.status_code, 200)
        doc.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual((doc.status, run.outcome, len(run.steps)), ('needs_person', 'unknown_popup', 1))
        self.assertEqual(AuditLog.objects.filter(action='rpa_run_reported').count(), audits)

    def test_dry_run_ok_report(self):
        doc = self.make_doc()
        run_id = self.claim().json()['run_id']
        self.assertEqual(self._report(doc, run_id, 'dry_run_ok').status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'dry_run_ok')
        self.assertEqual(RpaRun.objects.count(), 1)

    def test_saved_on_a_dry_run_goes_to_person(self):
        doc = self.make_doc()
        run_id = self.claim().json()['run_id']
        self._report(doc, run_id, 'saved', mode='live')
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'needs_person')
        self.find.assert_called_once()                    # only the claim-time lookup

    def test_lease_lost_report_goes_to_person(self):
        doc = self.make_doc()
        run_id = self.claim().json()['run_id']
        self.assertEqual(self._report(doc, run_id, 'lease_lost').status_code, 200)
        doc.refresh_from_db()
        self.assertEqual((doc.status, doc.needs_person_reason), ('needs_person', 'انقطع الروبوت قبل الإبلاغ'))
        self.assertEqual(RpaRun.objects.get(pk=run_id).outcome, 'timeout')

    def test_device_revoked_mid_run_401(self):
        doc = self.make_doc()
        run_id = self.claim().json()['run_id']
        RpaDevice.objects.filter(pk=self.dev.pk).update(revoked_at=timezone.now())
        self.assertEqual(self.client.post(f'/api/rpa/agent/documents/{doc.pk}/heartbeat/').status_code, 401)
        self.assertEqual(self._report(doc, run_id, 'dry_run_ok').status_code, 401)
        self.assertEqual(self.client.post(f'/api/rpa/agent/runs/{run_id}/screenshot/',
                                          {'step_index': '1', 'image': _upload(_png())}).status_code, 401)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'in_progress')     # its lease runs out → a person, as any lost run
        self.assertIsNone(RpaRun.objects.get(pk=run_id).finished_at)

    def test_unknown_outcome_recorded_as_error(self):
        doc = self.make_doc()
        run_id = self.claim().json()['run_id']
        self.assertEqual(self._report(doc, run_id, 'kaboom').status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'needs_person')
        self.assertEqual(RpaRun.objects.get(pk=run_id).outcome, 'error')

    def test_report_for_wrong_run_refused(self):
        doc = self.make_doc()
        self.claim()
        self.assertEqual(self._report(doc, 999999, 'dry_run_ok').status_code, 404)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'in_progress')

    def test_live_saved_verified_is_posted(self):
        self.screen.live = True
        self.screen.save()
        doc = self.make_doc(dry_run=False)
        r = self.claim()
        self.assertEqual(r.json()['mode'], 'live')
        self.assertEqual(r.json()['keyplan']['steps'][-1]['send'], '{F10}')
        found = {'docnumber': 812, 'usercode': 'u', 'cust_branch_code': 'T8B', 'matched_by': 'reference',
                 'lines': []}
        self.find.return_value = found
        with mock.patch(VERIFY, return_value={'ok': True, 'problems': []}):
            self._report(doc, r.json()['run_id'], 'saved', mode='live')
        doc.refresh_from_db()
        self.assertEqual((doc.status, doc.softech_docnumber), ('posted', 812))

    def test_live_saved_not_verified_goes_to_person(self):
        self.screen.live = True
        self.screen.save()
        doc = self.make_doc(dry_run=False)
        r = self.claim()
        self.find.return_value = {'docnumber': 813, 'usercode': 'x', 'cust_branch_code': 'T8B',
                                  'matched_by': 'reference', 'lines': []}
        with mock.patch(VERIFY, return_value={'ok': False, 'problems': ['مستخدم SOFTECH لا يطابق']}):
            self._report(doc, r.json()['run_id'], 'saved', mode='live')
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'needs_person')
        self.assertEqual(doc.softech_docnumber, 813)

    # ── screenshots ──────────────────────────────────────────────────────────────────────────

    def test_screenshot_type_and_size_limits(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, True)
        doc = self.make_doc()
        run_id = self.claim().json()['run_id']
        url = f'/api/rpa/agent/runs/{run_id}/screenshot/'
        with override_settings(MEDIA_ROOT=media):
            ok = self.client.post(url, {'step_index': '3', 'image': _upload(_png())})
            self.assertEqual(ok.status_code, 201)
            from PIL import Image
            raw_jpg = io.BytesIO()
            Image.new('RGB', (4, 4)).save(raw_jpg, format='JPEG')
            jpg = self.client.post(url, {'step_index': '4', 'image': _upload(raw_jpg.getvalue(), 'shot.jpg')})
            self.assertEqual(jpg.status_code, 201)
            raw = io.BytesIO()
            Image.new('RGB', (4, 4)).save(raw, format='GIF')
            gif = _upload(raw.getvalue(), 'shot.gif')
            self.assertEqual(self.client.post(url, {'step_index': '1', 'image': gif}).status_code, 400)
            self.assertEqual(self.client.post(url, {'step_index': '1',
                                                    'image': _upload(b'not an image')}).status_code, 400)
            big = _upload(b'\x89PNG\r\n\x1a\n' + b'0' * (2 * 1024 * 1024))
            self.assertEqual(self.client.post(url, {'step_index': '1', 'image': big}).status_code, 400)
            self.assertEqual(self.client.post(url, {'step_index': 'x',
                                                    'image': _upload(_png())}).status_code, 400)
            # a finished run takes no more pictures
            self._report(doc, run_id, 'dry_run_ok')
            self.assertEqual(self.client.post(url, {'step_index': '9',
                                                    'image': _upload(_png())}).status_code, 409)
        shots = list(RpaScreenshot.objects.order_by('step_index').values_list('run_id', 'step_index'))
        self.assertEqual(shots, [(run_id, 3), (run_id, 4)])
        self.assertTrue(RpaScreenshot.objects.get(step_index=4).image.name.endswith('.jpg'))

    # ── middleware: the agent path reaches DRF ──────────────────────────────────────────────

    def test_agent_path_passes_the_public_gate_and_module_access(self):
        doc = self.make_doc()
        with override_settings(PUBLIC_API_ENFORCEMENT='enforce', RBAC_ENFORCEMENT='enforce',
                               NETWORK_POLICY_ENFORCEMENT='enforce'):
            r = self.claim()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['keyplan']['document'], doc.pk)

    def test_public_gate_still_refuses_other_anonymous_paths(self):
        from apps.access.public_paths import is_public
        self.assertTrue(is_public('/api/rpa/agent/claim/', 'POST'))
        self.assertFalse(is_public('/api/rpa/jobs/', 'POST'))
        self.assertFalse(is_public('/api/rpa/', 'GET'))

    def test_operator_without_rpa_create_refused(self):
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        _, viewer, _ = make_user('t8_viewer', role='viewer', branch=self.src, access_all=True)
        RoleModuleAccess.objects.update_or_create(role='viewer', module='rpa', action='create',
                                                  defaults={'is_allowed': False})
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        self.make_doc(viewer)
        _, secret = self.device(viewer, 'جهاز مشاهد')
        c = APIClient()
        c.credentials(**{HEADER: secret})
        self.assertEqual(self.claim(c).status_code, 403)
        self.assertFalse(RpaRun.objects.exists())


class WriterFlagTextTests(TestCase):
    def test_rpa_flag_protects_text(self):
        from config.writers import WRITER_FLAGS
        self.assertEqual(WRITER_FLAGS['RPA_SOFTECH_ENTRY_ENABLED']['protects'],
                         'روبوت إدخال SOFTECH (إذن صرف، جرد، مشتريات، مرتجع)')


@override_settings(**ON)
class ResolveTests(_World, TestCase):

    def setUp(self):
        self.build_world('T8R')
        p = mock.patch(FIND, return_value=None)  # retry asks SOFTECH first; nothing there
        p.start()
        self.addCleanup(p.stop)
        self.doc = self.make_doc(status='needs_person')
        RpaDocument.objects.filter(pk=self.doc.pk).update(needs_person_reason='unknown_popup')
        self.doc.refresh_from_db()

    def test_resolve_requires_reason_and_edit_right(self):
        _, buyer, _ = make_user('t8_buyer', role='purchasing', branch=self.src, access_all=True)
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        self.assertFalse(RoleModuleAccess.objects.get(role='purchasing', module='rpa', action='edit').is_allowed)
        module_access.clear_cache()
        with self.assertRaises(PermissionDenied):
            dispatch.resolve_document(self.doc, buyer, 'retry', 'جربنا تاني')
        for blank in ('', '   ', None):
            with self.assertRaises(ValidationError):
                dispatch.resolve_document(self.doc, self.staff, 'retry', blank)
        with self.assertRaises(ValidationError):
            dispatch.resolve_document(self.doc, self.staff, 'delete-it', 'سبب')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, 'needs_person')
        dispatch.resolve_document(self.doc, self.staff, 'retry', 'أغلقنا النافذة')
        self.doc.refresh_from_db()
        self.assertEqual((self.doc.status, self.doc.claimed_by_id, self.doc.needs_person_reason),
                         ('approved', None, ''))
        log = AuditLog.objects.filter(action='rpa_document_resolved').get()
        self.assertIn('أغلقنا النافذة', log.note + str(log.new_data))
        # only from needs_person
        with self.assertRaises(ValidationError):
            dispatch.resolve_document(self.doc, self.staff, 'cancelled', 'سبب')

    def test_resolve_posted_needs_softech_to_find_it(self):
        with mock.patch(FIND, return_value=None):
            with self.assertRaises(ValidationError):
                dispatch.resolve_document(self.doc, self.staff, 'posted', 'دخل يدوي')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, 'needs_person')
        found = {'docnumber': 77, 'usercode': 'u', 'cust_branch_code': 'T8RB', 'matched_by': 'fingerprint',
                 'lines': []}
        with mock.patch(FIND, return_value=found), \
                mock.patch(VERIFY, return_value={'ok': True, 'problems': []}):
            dispatch.resolve_document(self.doc, self.staff, 'posted', 'دخل يدوي')
        self.doc.refresh_from_db()
        self.assertEqual((self.doc.status, self.doc.softech_docnumber), ('posted', 77))

    def test_resolve_posted_records_failed_verification(self):
        found = {'docnumber': 78, 'usercode': 'x', 'cust_branch_code': 'T8RB', 'matched_by': 'fingerprint',
                 'lines': []}
        with mock.patch(FIND, return_value=found), \
                mock.patch(VERIFY, return_value={'ok': False, 'problems': ['مستخدم SOFTECH لا يطابق']}):
            dispatch.resolve_document(self.doc, self.staff, 'posted', 'راجعته بنفسي')
        log = AuditLog.objects.get(action='rpa_document_resolved')
        self.assertIs(log.new_data['verify_ok'], False)
        self.assertEqual(log.new_data['verify_problems'], ['مستخدم SOFTECH لا يطابق'])
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.verify_result['ok'], False)

    def test_resolve_cancelled(self):
        dispatch.resolve_document(self.doc, self.staff, 'cancelled', 'لا داعي')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, 'cancelled')

    def test_resolve_outside_branches_refused(self):
        other = make_branch('T8R بعيد', 'T8RZ')
        _, local, _ = make_user('t8_local', role='supervisor', branch=other)
        local.restricted_branches.add(self.src)          # supervisors see all but a restricted branch
        with self.assertRaises(PermissionDenied):
            dispatch.resolve_document(self.doc, local, 'retry', 'سبب')


@override_settings(**ON)
class ConcurrentClaimTests(_World, TransactionTestCase):
    """Two agents claiming at once never share a document (real transactions on separate
    connections). This proves "no shared claim", not that skip_locked was used: a blocking lock
    would pass too, only slower."""
    serialized_rollback = True      # put the data-migration rows (screens, matrix) back after the flush

    def setUp(self):
        self.build_world('T8C')
        self.docs = [self.make_doc(), self.make_doc()]
        self.dev_a, _ = self.device(label='أ')
        self.dev_b, _ = self.device(label='ب')

    def test_concurrent_claims_never_share(self):
        results, errors = {}, []
        barrier = threading.Barrier(2)
        gate = threading.Event()
        real_find = dispatch.find_issue_document

        def slow_find(document):
            gate.wait(2)            # hold the first claim's lock while the other one runs
            return None

        def worker(name, device):
            try:
                barrier.wait(5)
                claim = dispatch.claim_next(device)
                results[name] = claim.document.pk if claim else None
            except Exception as exc:   # noqa: BLE001 - surfaced by the assertion below
                errors.append(exc)
            finally:
                connection.close()

        with mock.patch(FIND, side_effect=slow_find):
            threads = [threading.Thread(target=worker, args=(n, d))
                       for n, d in (('a', self.dev_a), ('b', self.dev_b))]
            for t in threads:
                t.start()
            threading.Timer(0.5, gate.set).start()
            for t in threads:
                t.join(15)
            self.assertEqual(errors, [])
            self.assertEqual(sorted(results.values()), sorted(d.pk for d in self.docs))
            self.assertIsNone(dispatch.claim_next(self.dev_a))
        self.assertIs(dispatch.find_issue_document, real_find)
        self.assertEqual(RpaRun.objects.count(), 2)
        self.assertEqual(set(RpaDocument.objects.values_list('status', flat=True)), {'in_progress'})
