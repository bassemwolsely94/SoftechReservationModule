"""S5 Task 1: file jobs for the seal PC's agent (apps/tax_invoicing/egs_agent.py) — the version handshake, the exact
download, the fetched copy and its comparison, held writes on hand edits, the write switch (preview when off), the
import of a fetched copy, and the nightly chain. Tiny workbooks built here, in a temp TAX_EGS_SHEET_DIR."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.tax_invoicing import egs_agent, egs_sheet
from apps.tax_invoicing.models import TaxAgentFileJob, TaxAuditEvent, TaxEgsSheetVersion, TaxSigningJob
from apps.tests.test_egs_sheet import D, ROWS, _TempDirMixin, make_sheet
from apps.tests.test_tax_signing import AGENT_TOKEN, NEXT_URL, agent_account, make_job

SWITCH_ON = {'WRITER_INSTANCE': True, 'TAX_EGS_SHEET_AGENT_WRITE_ENABLED': True}
HAND_EDITED = ROWS + [('EGS', 'EG-499336534-900', 'Z', D, 10000043, 900, 0.14)]     # a row coded by hand


def client(version=2, token=AGENT_TOKEN):
    headers = {'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(agent_account())}'}
    if token is not None:
        headers['HTTP_X_TAX_AGENT_TOKEN'] = token
    if version is not None:
        headers['HTTP_X_TAX_AGENT_VERSION'] = str(version)
    c = APIClient()
    c.credentials(**headers)
    return c


def files_url(job, what):
    return f'/api/tax-invoicing/signing-agent/files/{job.pk}/{what}/'


def actions():
    return list(TaxAuditEvent.objects.filter(entity__in=(egs_agent.ENTITY, 'egs_sheet'))
                .order_by('id').values_list('action', flat=True))


@override_settings(TAX_SIGNING_AGENT_TOKEN=AGENT_TOKEN)
class _Base(_TempDirMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.data = make_sheet(ROWS)
        self.v1 = egs_sheet.store(self.data, source=TaxEgsSheetVersion.SOURCE_SEED, **egs_sheet.read_counts(self.data))
        self.actor = agent_account()

    def add_version(self, rows):
        data = make_sheet(rows)
        return egs_sheet.store(data, source=TaxEgsSheetVersion.SOURCE_BUILD, **egs_sheet.read_counts(data))

    def fetch(self, data, then_write=False, status='done'):
        """A fetch job taken by the agent and answered with `data` as the live file."""
        job = egs_agent.request_fetch(self.actor, then_write=then_write)
        self.assertEqual(client().post(NEXT_URL).json()['job']['id'], job.pk)
        with self.captureOnCommitCallbacks(execute=True):
            r = client().post(files_url(job, 'result'), {
                'status': status, 'result': json.dumps({'copied': True}),
                'file': SimpleUploadedFile('live.xlsx', data)}, format='multipart')
        job.refresh_from_db()
        return job, r


class HandshakeTests(_Base):
    def test_old_agents_never_get_a_file_job(self):
        job = egs_agent.request_fetch(self.actor)
        for version in (None, 1, 'x'):
            self.assertIsNone(client(version).post(NEXT_URL).json()['job'], version)
        job.refresh_from_db()
        self.assertEqual(job.status, TaxAgentFileJob.PENDING)

    def test_signing_jobs_come_first_and_unchanged(self):
        fetch = egs_agent.request_fetch(self.actor)
        sign = make_job()
        body = client().post(NEXT_URL).json()['job']
        self.assertEqual(set(body), {'id', 'kind', 'canonical_text', 'sha256'})
        self.assertEqual(body['id'], sign.pk)
        body = client().post(NEXT_URL).json()['job']
        self.assertEqual((body['id'], body['kind'], body['mode']), (fetch.pk, 'egs_fetch', 'preview'))
        self.assertNotIn('download_url', body)
        self.assertIsNone(client().post(NEXT_URL).json()['job'])

    def test_last_seen_and_version_are_recorded(self):
        from django.core.cache import cache
        cache.clear()
        client(2).post(NEXT_URL)
        self.assertEqual(egs_agent.agent_seen()['version'], 2)

    def test_file_endpoints_refuse_old_agents_bad_tokens_and_unclaimed_jobs(self):
        job = egs_agent.request_fetch(self.actor)
        for c in (client(None), client(1), client(token='wrong')):
            self.assertEqual(c.post(files_url(job, 'result'), {'status': 'done'}, format='json').status_code, 403)
        self.assertEqual(client().post(files_url(job, 'result'), {'status': 'done'}, format='json').status_code, 404)
        self.assertEqual(client().get(files_url(job, 'download')).status_code, 404)

    def test_the_file_paths_are_not_public(self):
        from apps.access import public_paths
        for what in ('download', 'result'):
            for method in ('GET', 'POST'):
                self.assertFalse(public_paths.is_public(f'/api/tax-invoicing/signing-agent/files/1/{what}/', method))


class FetchTests(_Base):
    def test_fetched_copy_is_stored_and_matches_the_version(self):
        job, r = self.fetch(self.data)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(job.status, TaxAgentFileJob.DONE)
        stored = Path(self.store_dir) / 'fetched' / job.fetched_file
        self.assertEqual(stored.read_bytes(), self.data)
        self.assertEqual(job.result['live']['sha256'], hashlib.sha256(self.data).hexdigest())
        self.assertEqual((job.result['matches_version'], job.result['hand_edits']), (1, False))
        self.assertEqual(set(job.result['coded_itemcodes']), {'100', '0200'})
        self.assertEqual(job.result['agent'], {'copied': True})
        self.assertIn('egs_sheet_fetched', actions())

    def test_hand_edits_are_reported_against_the_latest_version(self):
        job, _ = self.fetch(make_sheet(HAND_EDITED))
        self.assertTrue(job.result['hand_edits'])
        self.assertIsNone(job.result['matches_version'])
        self.assertEqual((job.result['added_vs_latest'], job.result['removed_vs_latest']), (['900'], []))

    def test_a_resaved_file_with_the_same_codes_is_still_the_version(self):
        job, _ = self.fetch(make_sheet([(*ROWS[0][:2], 'renamed', *ROWS[0][3:])] + ROWS[1:]))
        self.assertEqual((job.result['matches_version'], job.result['hand_edits']), (1, False))

    def test_not_an_xlsx_fails_the_job(self):
        job, r = self.fetch(b'not a workbook')
        self.assertEqual(r.status_code, 400)
        self.assertEqual((job.status, job.error), (TaxAgentFileJob.FAILED, egs_agent.UPLOAD_NOT_XLSX))
        self.assertFalse((Path(self.store_dir) / 'fetched').exists() and any((Path(self.store_dir) / 'fetched').iterdir()))
        self.assertIn('egs_sheet_failed', actions())

    def test_an_xlsx_without_the_dataentry_header_fails_the_job(self):
        import io

        import openpyxl
        buf = io.BytesIO()
        openpyxl.Workbook().save(buf)
        job, r = self.fetch(buf.getvalue())
        self.assertEqual((r.status_code, job.status), (400, TaxAgentFileJob.FAILED))

    def test_a_declared_body_over_the_cap_fails_the_job_before_reading(self):
        with mock.patch.object(egs_agent, 'MAX_UPLOAD', -1024 * 1024):
            job, r = self.fetch(self.data)
        self.assertEqual(r.status_code, 413)
        self.assertEqual((job.status, job.error), (TaxAgentFileJob.FAILED, egs_agent.UPLOAD_TOO_BIG))

    def test_a_file_that_unpacks_too_big_is_refused(self):
        with mock.patch.object(egs_agent, 'MAX_UNPACKED', 1000):
            job, r = self.fetch(self.data)
        self.assertEqual((r.status_code, job.status, job.error),
                         (400, TaxAgentFileJob.FAILED, egs_agent.UPLOAD_UNPACKS_TOO_BIG))

    def test_an_upload_over_the_cap_is_refused(self):
        with mock.patch.object(egs_agent, 'MAX_UPLOAD', 100):
            job, r = self.fetch(self.data)
        self.assertEqual(r.status_code, 413)
        self.assertEqual((job.status, job.error), (TaxAgentFileJob.FAILED, egs_agent.UPLOAD_TOO_BIG))

    def test_a_done_fetch_without_a_file_fails(self):
        job = egs_agent.request_fetch(self.actor)
        client().post(NEXT_URL)
        r = client().post(files_url(job, 'result'), {'status': 'done'}, format='json')
        job.refresh_from_db()
        self.assertEqual((r.status_code, job.status), (400, TaxAgentFileJob.FAILED))

    def test_busy_fetch_is_recorded(self):
        job = egs_agent.request_fetch(self.actor)
        client().post(NEXT_URL)
        client().post(files_url(job, 'result'), {'status': 'busy', 'error': 'locked'}, format='json')
        job.refresh_from_db()
        self.assertEqual((job.status, job.error), (TaxAgentFileJob.BUSY, 'locked'))
        self.assertIn('egs_sheet_busy', actions())

    def test_only_the_newest_fetched_copies_are_kept(self):
        with mock.patch.object(egs_agent, 'KEEP_FETCHED', 2):
            jobs = [self.fetch(self.data)[0] for _ in range(3)]
        folder = Path(self.store_dir) / 'fetched'
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(j.fetched_file for j in jobs[1:]))

    def test_one_open_fetch_at_a_time(self):
        self.assertEqual(egs_agent.request_fetch(self.actor).pk, egs_agent.request_fetch(None, then_write=True).pk)
        self.assertTrue(TaxAgentFileJob.objects.get().then_write)


class WriteTests(_Base):
    def claim(self):
        body = client().post(NEXT_URL).json()['job']
        return TaxAgentFileJob.objects.get(pk=body['id']), body

    def test_no_fetch_yet_refuses(self):
        self.add_version(HAND_EDITED)
        with self.assertRaisesMessage(egs_agent.EgsAgentError, egs_agent.NO_FETCH):
            egs_agent.request_write(self.actor)

    def test_nothing_to_write_when_the_live_file_is_the_latest_version(self):
        self.fetch(self.data)
        self.assertIsNone(egs_agent.request_write(self.actor))

    def test_switch_off_creates_a_preview_and_the_download_is_exact(self):
        self.fetch(self.data)
        v2 = self.add_version(HAND_EDITED)
        job = egs_agent.request_write(self.actor)
        self.assertEqual((job.mode, job.version, job.sha256), ('preview', v2, v2.sha256))
        self.assertEqual(job.live_sha256, hashlib.sha256(self.data).hexdigest())
        job, body = self.claim()
        self.assertEqual((body['kind'], body['mode'], body['sha256'], body['version']),
                         ('egs_write', 'preview', v2.sha256, 2))
        self.assertNotIn('path', json.dumps(body).lower().replace('_url', ''))
        r = client().get(body['download_url'])
        self.assertEqual(r.status_code, 200)
        served = b''.join(r.streaming_content) if r.streaming else r.content
        self.assertEqual(hashlib.sha256(served).hexdigest(), job.sha256)
        self.assertEqual(served, (Path(self.store_dir) / v2.file_name).read_bytes())
        self.assertEqual(r['X-Content-SHA256'], job.sha256)
        self.assertEqual(r['Content-Type'], 'application/octet-stream')
        self.assertEqual(r['X-Job-Mode'], 'preview')
        self.assertIn('egs_sheet_served', actions())

    @override_settings(**SWITCH_ON)
    def test_switch_on_creates_a_write(self):
        self.fetch(self.data)
        self.add_version(HAND_EDITED)
        self.assertEqual(egs_agent.request_write(self.actor).mode, 'write')
        self.assertEqual(self.claim()[1]['mode'], 'write')

    def test_a_write_made_with_the_switch_on_is_claimed_as_preview_once_it_is_off(self):
        self.fetch(self.data)
        self.add_version(HAND_EDITED)
        with override_settings(**SWITCH_ON):
            job = egs_agent.request_write(self.actor)
        self.assertEqual(job.mode, 'write')
        job, body = self.claim()
        self.assertEqual((body['mode'], job.mode, job.result['switch_off_at_claim']), ('preview', 'preview', True))
        self.assertIn('egs_sheet_switch_off_at_claim', actions())

    def test_a_write_claimed_with_the_switch_on_is_not_served_once_it_is_off(self):
        self.fetch(self.data)
        self.add_version(HAND_EDITED)
        with override_settings(**SWITCH_ON):
            egs_agent.request_write(self.actor)
            job, body = self.claim()
            self.assertEqual(client().get(body['download_url'])['X-Job-Mode'], 'write')
        r = client().get(body['download_url'])
        job.refresh_from_db()
        self.assertEqual((r.status_code, job.status, job.error),
                         (409, TaxAgentFileJob.FAILED, egs_agent.SWITCH_OFF_AT_SERVE))
        self.assertIn('egs_sheet_switch_off_at_serve', actions())

    def test_a_changed_version_file_fails_the_download(self):
        self.fetch(self.data)
        v2 = self.add_version(HAND_EDITED)
        egs_agent.request_write(self.actor)
        job, body = self.claim()
        (Path(self.store_dir) / v2.file_name).write_bytes(b'tampered')
        r = client().get(body['download_url'])
        job.refresh_from_db()
        self.assertEqual((r.status_code, job.status), (409, TaxAgentFileJob.FAILED))

    def test_outcomes_are_audited(self):
        fetched, _ = self.fetch(self.data)
        self.add_version(HAND_EDITED)
        with override_settings(**SWITCH_ON):
            egs_agent.request_write(self.actor)
            job, _ = self.claim()
        report = {'backup': 'b.xlsx', 'written': True, 'live_sha256_after': job.sha256}
        client().post(files_url(job, 'result'), {'status': 'done', 'result': report}, format='json')
        job.refresh_from_db()
        self.assertEqual((job.status, job.result['agent']), (TaxAgentFileJob.DONE, report))
        self.assertIn('egs_sheet_written', actions())
        # the live file is now the latest version: nothing more to write until the next build
        self.assertIsNone(egs_agent.request_write(self.actor))
        # and the fetch taken before that write can no longer be imported (it would undo the write)
        with self.assertRaisesMessage(egs_agent.EgsAgentError, egs_agent.FETCH_NOT_CURRENT):
            egs_agent.import_fetched(self.actor, fetched)

    def test_a_write_done_without_a_matching_read_back_is_failed(self):
        self.fetch(self.data)
        v2 = self.add_version(HAND_EDITED)
        for report in ({'backup': 'b.xlsx'}, {'written': True, 'live_sha256_after': ''},
                       {'written': True, 'live_sha256_after': '0' * 64},
                       {'written': 'yes', 'live_sha256_after': v2.sha256}):
            with self.subTest(report=report), override_settings(**SWITCH_ON):
                egs_agent.request_write(self.actor)
                job, _ = self.claim()
                r = client().post(files_url(job, 'result'), {'status': 'done', 'result': report}, format='json')
                job.refresh_from_db()
                self.assertEqual((r.status_code, job.status, job.error),
                                 (200, TaxAgentFileJob.FAILED, egs_agent.WRITE_UNCONFIRMED))
        self.assertEqual(actions().count('egs_sheet_write_anomaly'), 4)
        self.assertNotIn('egs_sheet_written', actions())

    def test_preview_done_is_not_a_write(self):
        self.fetch(self.data)
        self.add_version(HAND_EDITED)
        egs_agent.request_write(self.actor)
        job, _ = self.claim()
        client().post(files_url(job, 'result'), {'status': 'done'}, format='json')
        self.assertIn('egs_sheet_previewed', actions())
        self.assertNotIn('egs_sheet_written', actions())
        self.assertIsNotNone(egs_agent.request_write(self.actor))     # the live file did not change

    def test_busy_and_failed_writes(self):
        self.fetch(self.data)
        self.add_version(HAND_EDITED)
        for status, action in (('busy', 'egs_sheet_busy'), ('failed', 'egs_sheet_failed')):
            egs_agent.request_write(self.actor)
            job, _ = self.claim()
            client().post(files_url(job, 'result'), {'status': status, 'error': 'x'}, format='json')
            job.refresh_from_db()
            self.assertEqual(job.status, status)
            self.assertIn(action, actions())

    def test_unknown_status_is_refused(self):
        self.fetch(self.data)
        self.add_version(HAND_EDITED)
        egs_agent.request_write(self.actor)
        job, _ = self.claim()
        r = client().post(files_url(job, 'result'), {'status': 'signed'}, format='json')
        job.refresh_from_db()
        self.assertEqual((r.status_code, job.status), (400, TaxAgentFileJob.CLAIMED))


class HeldTests(_Base):
    def setUp(self):
        super().setUp()
        self.fetched, _ = self.fetch(make_sheet(HAND_EDITED))      # the owner coded 900 by hand
        self.v2 = self.add_version(ROWS + [(None, 'x', 'C', None, 0, 500, 0)])

    def test_hand_edits_hold_the_write_and_the_agent_never_sees_it(self):
        job = egs_agent.request_write(None)
        self.assertEqual(job.status, TaxAgentFileJob.HELD)
        self.assertEqual((job.result['fetch_job'], job.result['added']), (self.fetched.pk, ['900']))
        self.assertIn('egs_sheet_write_held', actions())
        self.assertIsNone(client().post(NEXT_URL).json()['job'])

    def test_the_same_hold_is_not_recorded_twice(self):
        self.assertEqual(egs_agent.request_write(None).pk, egs_agent.request_write(None).pk)
        self.assertEqual(TaxAgentFileJob.objects.filter(status=TaxAgentFileJob.HELD).count(), 1)
        self.assertEqual(actions().count('egs_sheet_write_held'), 1)

    def test_only_the_newest_fetch_may_be_imported(self):
        self.fetch(make_sheet(HAND_EDITED))
        with self.assertRaisesMessage(egs_agent.EgsAgentError, egs_agent.FETCH_NOT_CURRENT):
            egs_agent.import_fetched(self.actor, self.fetched)

    def test_an_import_that_drops_coded_items_needs_an_explicit_yes(self):
        fewer, _ = self.fetch(make_sheet([ROWS[0], ROWS[2], ROWS[3], HAND_EDITED[-1]]))     # 0200 gone
        with self.assertRaisesMessage(egs_agent.EgsAgentError, egs_agent.IMPORT_REMOVES):
            egs_agent.import_fetched(self.actor, fewer)
        version = egs_agent.import_fetched(self.actor, fewer, allow_removals=True)
        self.assertNotIn('0200', version.coded_itemcodes)
        event = TaxAuditEvent.objects.filter(action='egs_sheet_imported').get()
        self.assertEqual((event.after['allow_removals'], event.after['removed']), (True, ['0200']))

    def test_a_person_may_write_over_them(self):
        job = egs_agent.request_write(self.actor, override=True, note='owner asked')
        self.assertEqual((job.status, job.override, job.mode), (TaxAgentFileJob.PENDING, True, 'preview'))
        self.assertIn('egs_sheet_write_override', actions())

    def test_override_needs_a_person(self):
        with self.assertRaisesMessage(egs_agent.EgsAgentError, egs_agent.OVERRIDE_NEEDS_PERSON):
            egs_agent.request_write(None, override=True)

    def test_import_is_refused_while_a_write_is_open(self):
        egs_agent.request_write(self.actor, override=True, note='owner asked')     # pending write
        with self.assertRaisesMessage(egs_agent.EgsAgentError, egs_agent.WRITE_OPEN):
            egs_agent.import_fetched(self.actor, self.fetched)
        self.assertEqual(TaxEgsSheetVersion.objects.count(), 2)
        self.assertNotIn('egs_sheet_imported', actions())

    def test_import_makes_the_live_file_a_version(self):
        v3 = egs_agent.import_fetched(self.actor, self.fetched)
        self.assertEqual((v3.number, v3.source, v3.sha256), (3, 'fetch', self.fetched.result['live']['sha256']))
        self.assertIn('900', v3.coded_itemcodes)
        self.assertIn('egs_sheet_imported', actions())
        self.assertIsNone(egs_agent.request_write(self.actor))     # the live file is the latest version now
        with self.assertRaisesMessage(egs_agent.EgsAgentError, egs_agent.ALREADY_LATEST):
            egs_agent.import_fetched(self.actor, self.fetched)

    def test_after_an_import_a_new_build_is_written_not_held(self):
        egs_agent.import_fetched(self.actor, self.fetched)
        self.add_version(HAND_EDITED + [('EGS', 'EG-499336534-950', 'Y', D, 10000043, 950, 0.14)])
        self.assertEqual(egs_agent.request_write(self.actor).status, TaxAgentFileJob.PENDING)

    def test_import_refuses_a_changed_or_missing_copy(self):
        path = Path(self.store_dir) / 'fetched' / self.fetched.fetched_file
        path.write_bytes(make_sheet(ROWS))
        with self.assertRaisesMessage(egs_agent.EgsAgentError, egs_agent.FETCHED_CHANGED):
            egs_agent.import_fetched(self.actor, self.fetched)
        os.remove(path)
        with self.assertRaisesMessage(egs_agent.EgsAgentError, egs_agent.FETCHED_GONE):
            egs_agent.import_fetched(self.actor, self.fetched)


class NightlyAndStaleTests(_Base):
    def test_nightly_with_the_switch_off_only_fetches(self):
        job = egs_agent.nightly()
        self.assertEqual((job.kind, job.then_write), ('egs_fetch', False))

    @override_settings(**SWITCH_ON)
    def test_nightly_with_the_switch_on_writes_after_the_fetch(self):
        self.add_version(HAND_EDITED)
        egs_agent.nightly()
        job = TaxAgentFileJob.objects.get()
        self.assertTrue(job.then_write)
        self.assertEqual(client().post(NEXT_URL).json()['job']['id'], job.pk)
        with self.captureOnCommitCallbacks(execute=True):
            client().post(files_url(job, 'result'), {'status': 'done', 'file': SimpleUploadedFile('l.xlsx', self.data)},
                          format='multipart')
        write = TaxAgentFileJob.objects.get(kind='egs_write')
        self.assertEqual((write.mode, write.version.number, write.requested_by), ('write', 2, None))

    def test_stale_jobs_fail(self):
        fetch = egs_agent.request_fetch(self.actor)
        TaxAgentFileJob.objects.filter(pk=fetch.pk).update(created_at=timezone.now() - dt.timedelta(hours=25))
        egs_agent.expire_stale()
        fetch.refresh_from_db()
        self.assertEqual((fetch.status, fetch.error), (TaxAgentFileJob.FAILED, egs_agent.NO_STALE_PENDING))
        fresh = egs_agent.request_fetch(self.actor)
        self.assertNotEqual(fresh.pk, fetch.pk)
        client().post(NEXT_URL)
        TaxAgentFileJob.objects.filter(pk=fresh.pk).update(claimed_at=timezone.now() - dt.timedelta(minutes=31))
        egs_agent.expire_stale()
        fresh.refresh_from_db()
        self.assertEqual(fresh.status, TaxAgentFileJob.FAILED)

    def test_a_signing_job_is_never_starved(self):
        egs_agent.request_fetch(self.actor)
        sign = make_job()
        self.assertEqual(client(2).post(NEXT_URL).json()['job']['id'], sign.pk)
        self.assertEqual(TaxSigningJob.objects.get(pk=sign.pk).status, TaxSigningJob.CLAIMED)


AGENT_STATE_URL = '/api/tax-invoicing/codes/sheet/agent/'


class PanelApiTests(_Base):
    """S5 Task 3: the person-facing endpoints behind the panel's «الجهاز المحلي» part."""

    def setUp(self):
        from apps.tax_invoicing.models import TaxIssuerProfile
        from apps.tests.test_tax_invoicing import Fixture
        from apps.users.models import RoleModuleAccess
        super().setUp()
        Fixture.build(self, 'egsa')
        TaxIssuerProfile.objects.filter(pk=1).update(tax_id='499-336-534')
        RoleModuleAccess.objects.update_or_create(role='pharmacist', module='tax_invoicing', action='view',
                                                  defaults={'is_allowed': False})
        self.api = self.person(self.accountant)

    def person(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_state_before_anything(self):
        r = self.api.get(AGENT_STATE_URL)
        self.assertEqual(r.status_code, 200, r.content)
        d = r.data
        self.assertEqual((d['switch'], d['last_fetch'], d['held'], d['live'], d['jobs'], d['busy']),
                         (False, None, None, None, [], False))
        self.assertTrue(d['agent']['outdated'])
        self.assertTrue(d['can_approve'])

    def test_an_old_agent_is_shown_as_outdated_and_a_new_one_is_not(self):
        from django.core.cache import cache
        cache.clear()      # the last-seen throttle of other tests
        client(None).post(NEXT_URL)
        self.assertTrue(self.api.get(AGENT_STATE_URL).data['agent']['outdated'])
        client(2).post(NEXT_URL)
        agent = self.api.get(AGENT_STATE_URL).data['agent']
        self.assertEqual((agent['version'], agent['outdated']), (2, False))
        self.assertTrue(agent['at'])

    def test_fetch_button_makes_one_job_and_the_state_polls_it(self):
        r = self.api.post(AGENT_STATE_URL + 'fetch/')
        self.assertEqual(r.status_code, 201, r.content)
        again = self.api.post(AGENT_STATE_URL + 'fetch/')
        self.assertEqual(again.data['job']['id'], r.data['job']['id'])
        from django.core.cache import cache
        cache.clear()      # the last-seen throttle of other tests
        egs_agent.record_seen(2)
        d = self.api.get(AGENT_STATE_URL).data
        self.assertTrue(d['busy'])
        self.assertEqual((d['jobs'][0]['kind'], d['jobs'][0]['status'], d['jobs'][0]['requested_by']),
                         ('egs_fetch', 'pending', self.accountant.get_full_name() or self.accountant.username))

    def test_a_job_an_outdated_agent_cannot_take_stops_the_polling(self):
        from django.core.cache import cache
        cache.clear()
        egs_agent.record_seen(0)            # the seal PC still runs the old agent
        old = egs_agent.request_fetch(self.actor)
        TaxAgentFileJob.objects.filter(pk=old.pk).update(created_at=timezone.now() - dt.timedelta(hours=25))
        d = self.api.get(AGENT_STATE_URL).data
        old.refresh_from_db()
        self.assertEqual(old.status, TaxAgentFileJob.FAILED)        # expired by the GET itself
        egs_agent.request_fetch(self.actor)                          # a fresh pending job
        d = self.api.get(AGENT_STATE_URL).data
        self.assertTrue(d['agent']['outdated'])
        self.assertFalse(d['busy'])

    def test_last_fetch_shows_the_difference_and_a_hold(self):
        fetched, _ = self.fetch(make_sheet(HAND_EDITED))
        self.add_version(ROWS + [(None, 'x', 'C', None, 0, 500, 0)])
        r = self.api.post(AGENT_STATE_URL + 'write/', {}, format='json')
        self.assertEqual((r.status_code, r.data['job']['status']), (200, 'held'))
        d = self.api.get(AGENT_STATE_URL).data
        f = d['last_fetch']
        self.assertEqual((f['id'], f['hand_edits'], f['current'], f['importable'], f['import_removes']),
                         (fetched.pk, True, True, True, 0))
        self.assertEqual(f['added_vs_latest'], {'count': 1, 'items': ['900']})
        self.assertEqual(d['held']['added'], {'count': 1, 'items': ['900']})
        self.assertEqual(d['jobs'][0]['result'], {'added': 1, 'removed': 0})

    def test_write_over_needs_a_reason_and_is_audited(self):
        self.fetch(make_sheet(HAND_EDITED))
        self.add_version(ROWS + [(None, 'x', 'C', None, 0, 500, 0)])
        r = self.api.post(AGENT_STATE_URL + 'write/', {'override': True}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(TaxAgentFileJob.objects.filter(kind='egs_write').exists())
        r = self.api.post(AGENT_STATE_URL + 'write/', {'override': True, 'note': 'المالك طلب'}, format='json')
        self.assertEqual((r.status_code, r.data['job']['status'], r.data['job']['mode'], r.data['job']['override']),
                         (200, 'pending', 'preview', True))
        event = TaxAuditEvent.objects.get(action='egs_sheet_write_override')
        self.assertEqual(event.reason, 'المالك طلب')
        self.assertIsNone(self.api.get(AGENT_STATE_URL).data['held'])

    def test_write_without_a_fetch_and_with_nothing_to_write(self):
        r = self.api.post(AGENT_STATE_URL + 'write/', {}, format='json')
        self.assertEqual((r.status_code, r.data['detail']), (400, egs_agent.NO_FETCH))
        self.fetch(self.data)
        r = self.api.post(AGENT_STATE_URL + 'write/', {}, format='json')
        self.assertEqual((r.status_code, r.data['job']), (200, None))

    def test_import_with_and_without_removals(self):
        fewer, _ = self.fetch(make_sheet([ROWS[0], ROWS[2], ROWS[3], HAND_EDITED[-1]]))
        self.assertEqual(self.api.get(AGENT_STATE_URL).data['last_fetch']['import_removes'], 1)
        r = self.api.post(AGENT_STATE_URL + 'import/', {'job': fewer.pk}, format='json')
        self.assertEqual((r.status_code, r.data['detail']), (400, egs_agent.IMPORT_REMOVES))
        r = self.api.post(AGENT_STATE_URL + 'import/', {'job': fewer.pk, 'allow_removals': True}, format='json')
        self.assertEqual((r.status_code, r.data['version']['number']), (201, 2))
        self.assertTrue(TaxAuditEvent.objects.filter(action='egs_sheet_imported').exists())
        self.assertFalse(self.api.get(AGENT_STATE_URL).data['last_fetch']['importable'])
        self.assertEqual(self.api.post(AGENT_STATE_URL + 'import/', {'job': 'x'}, format='json').status_code, 400)
        self.assertEqual(self.api.post(AGENT_STATE_URL + 'import/', {'job': 99999}, format='json').status_code, 404)

    def test_pharmacist_403_and_viewer_reads_only(self):
        from apps.tests.factories import make_user
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        ph = self.person(self.pharmacist)
        self.assertEqual(ph.get(AGENT_STATE_URL).status_code, 403)
        for what in ('fetch/', 'write/', 'import/'):
            self.assertEqual(ph.post(AGENT_STATE_URL + what, {}, format='json').status_code, 403)
        RoleModuleAccess.objects.update_or_create(role='viewer', module='tax_invoicing', action='view',
                                                  defaults={'is_allowed': True})
        RoleModuleAccess.objects.filter(role='viewer', module='tax_invoicing').exclude(action='view').delete()
        module_access.clear_cache()
        viewer, _, _ = make_user('viewer_egsa', role='viewer', branch=self.branch)
        c = self.person(viewer)
        r = c.get(AGENT_STATE_URL)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['can_approve'])
        for what in ('fetch/', 'write/', 'import/'):
            self.assertEqual(c.post(AGENT_STATE_URL + what, {}, format='json').status_code, 403)
        self.assertFalse(TaxAgentFileJob.objects.exists())

    @override_settings(**SWITCH_ON)
    def test_switch_on_is_shown_and_writes_are_real(self):
        self.fetch(self.data)
        self.add_version(HAND_EDITED)
        self.assertTrue(self.api.get(AGENT_STATE_URL).data['switch'])
        r = self.api.post(AGENT_STATE_URL + 'write/', {}, format='json')
        self.assertEqual(r.data['job']['mode'], 'write')
