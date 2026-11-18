"""S5 Task 2: the seal PC agent's side of the bulk EGS sheet jobs (deploy/tax_signing_agent/agent.py).

Plain unit tests: temporary folders stand in for D:\\invoicer_mini, a fake HTTP object for the server, a patched
os.replace for a sheet Invoicer holds open, and a recording sleep. Nothing touches a database.
"""
import builtins
import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

AGENT_DIR = Path(settings.BASE_DIR) / 'deploy' / 'tax_signing_agent'


def _load_agent():
    """agent.py is a script beside its copy of cades.py, so it is loaded the way Python runs it."""
    with mock.patch.object(sys, 'path', [str(AGENT_DIR), *sys.path]), mock.patch.dict(sys.modules):
        sys.modules.pop('cades', None)
        spec = importlib.util.spec_from_file_location('tax_signing_agent_side', AGENT_DIR / 'agent.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


agent_module = _load_agent()
LIVE = b'PK\x03\x04 the live sheet as Invoicer has it'
NEW = b'PK\x03\x04 version 7 of the sheet, built on the server'
NOW = dt.datetime(2026, 11, 18, 3, 0, 5)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FakeResponse:
    def __init__(self, status_code, body=None, content=b'', headers=None):
        self.status_code, self._body, self.content, self.headers = status_code, body, content, headers or {}

    def json(self):
        if self._body is None:
            raise ValueError('not json')
        return self._body


class FakeHttp:
    """Sign-in answers with tokens; next/ answers from `jobs`; download/ from `downloads`; result/ records."""

    def __init__(self, jobs=(), downloads=(), results=()):
        self.jobs, self.downloads, self.results = list(jobs), list(downloads), list(results)
        self.calls = []
        self.cookies = {}

    def post(self, url, *, headers, timeout, allow_redirects, verify, json=None, data=None, files=None):
        self.calls.append({'method': 'post', 'url': url, 'headers': headers, 'json': json, 'data': data,
                           'files': files, 'timeout': timeout})
        if url.endswith('/auth/login/'):
            return FakeResponse(200, {'access': 'A1', 'refresh': 'R1'})
        if url.endswith('/next/'):
            return FakeResponse(200, {'job': self.jobs.pop(0) if self.jobs else None})
        answer = self.results.pop(0) if self.results else FakeResponse(200, {'ok': True})
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def get(self, url, *, headers, timeout, allow_redirects, verify):
        self.calls.append({'method': 'get', 'url': url, 'headers': headers, 'timeout': timeout})
        answer = self.downloads.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def file_results(self):
        out = []
        for call in self.calls:
            if call['method'] == 'post' and '/files/' in call['url']:
                if call['files'] is not None:
                    out.append({'status': call['data']['status'], 'result': json.loads(call['data']['result']),
                                'error': call['data']['error'], 'file': call['files']['file'][1]})
                else:
                    out.append({**call['json'], 'file': None})
        return out


def download(data=NEW, *, sha256=None, mode='write', status=200):
    headers = {'X-Content-SHA256': sha(NEW) if sha256 is None else sha256, 'X-Job-Mode': mode}
    return FakeResponse(status, {'detail': 'refused'} if status != 200 else None, data if status == 200 else b'',
                        headers)


def write_job(*, mode='write', live_sha256=None, job_id=41):
    return {'id': job_id, 'kind': 'egs_write', 'mode': mode, 'result_url': f'/x/{job_id}/result/',
            'download_url': f'/x/{job_id}/download/', 'sha256': sha(NEW), 'size': len(NEW),
            'live_sha256': sha(LIVE) if live_sha256 is None else live_sha256, 'version': 7}


class SheetTestCase(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='invoicer_mini_'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.live = self.root / agent_module.LIVE_NAME
        self.live.write_bytes(LIVE)
        self.sleeps = []

    def agent(self, http, invoicer_dir=None):
        server = agent_module.Server('https://server.test', 'a' * 40, username='tax_signing_agent',
                                     password='pw', http=http)
        return agent_module.Agent(None, server, sleep=self.sleeps.append, now=lambda: NOW,
                                  invoicer_dir=str(self.root) if invoicer_dir is None else invoicer_dir)

    def run_job(self, job, *, downloads=(), results=(), invoicer_dir=None):
        http = FakeHttp(downloads=downloads, results=results)
        done = self.agent(http, invoicer_dir).handle(job)
        sent = http.file_results()
        self.assertEqual(len(sent), 1)
        return done, sent[0], http

    def folder_listing(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))

    def backups(self):
        folder = self.root / agent_module.BACKUP_FOLDER
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


class WriteTests(SheetTestCase):
    def test_write_swaps_the_new_sheet_in_with_a_backup(self):
        done, sent, http = self.run_job(write_job(), downloads=[download()])
        self.assertTrue(done)
        self.assertEqual(sent['status'], 'done', sent)
        self.assertEqual(self.live.read_bytes(), NEW)
        self.assertEqual(self.backups(), ['ElRezeiky_Bulk_EGS_Items.20261118-030005.xlsx'])
        self.assertEqual((self.root / 'backup' / self.backups()[0]).read_bytes(), LIVE)
        self.assertFalse((self.root / agent_module.NEW_NAME).exists())
        r = sent['result']
        self.assertEqual((r['backup'], r['live_sha256_before'], r['live_sha256_after'], r['written']),
                         (self.backups()[0], sha(LIVE), sha(NEW), True))
        # the download and the result go to URLs built from the job id, never the ones in the job
        urls = [c['url'] for c in http.calls if '/files/' in c['url']]
        self.assertEqual(urls, ['https://server.test/api/tax-invoicing/signing-agent/files/41/download/',
                                'https://server.test/api/tax-invoicing/signing-agent/files/41/result/'])
        for call in http.calls:
            if call['url'].startswith('https://server.test/api/tax-invoicing/'):
                self.assertEqual(call['headers']['X-Tax-Agent-Version'], '2')

    def test_backups_are_pruned_to_the_newest_30(self):
        folder = self.root / 'backup'
        folder.mkdir()
        old = [f'ElRezeiky_Bulk_EGS_Items.20261001-12{minute:02d}00.xlsx' for minute in range(35)]
        for name in old:
            (folder / name).write_bytes(b'old')
        (folder / 'notes.txt').write_bytes(b'not ours')
        done, sent, _ = self.run_job(write_job(), downloads=[download()])
        self.assertTrue(done)
        names = self.backups()
        ours = [n for n in names if n != 'notes.txt']
        self.assertEqual(len(ours), 30)
        self.assertIn('ElRezeiky_Bulk_EGS_Items.20261118-030005.xlsx', ours)
        self.assertIn('notes.txt', names)
        self.assertEqual(sent['result']['backups_removed'], 6)
        self.assertFalse(set(old[:6]) & set(names))      # the six oldest went
        self.assertTrue(set(old[6:]) <= set(names))

    def test_hash_mismatch_writes_nothing(self):
        before = self.folder_listing()
        for label, response in (('truncated', download(NEW[:-3])),
                                ('header differs', download(sha256='0' * 64)),
                                ('changed body', download(b'something else'))):
            with self.subTest(label):
                done, sent, _ = self.run_job(write_job(), downloads=[response])
                self.assertFalse(done)
                self.assertEqual(sent['status'], 'failed')
                self.assertIn('SHA-256', sent['error'])
                self.assertEqual(self.live.read_bytes(), LIVE)
                self.assertEqual(self.folder_listing(), before)

    def test_a_refused_download_writes_nothing(self):
        before = self.folder_listing()
        for code in (409, 404):
            with self.subTest(code):
                done, sent, _ = self.run_job(write_job(), downloads=[download(status=code)])
                self.assertEqual((done, sent['status']), (False, 'failed'))
                self.assertIn(str(code), sent['error'])
                self.assertEqual(self.folder_listing(), before)

    def test_mode_mismatch_is_a_preview(self):
        before = self.folder_listing()
        for job_mode, header_mode in (('write', 'preview'), ('preview', 'write'), ('write', ''), ('preview', 'preview')):
            with self.subTest(job=job_mode, header=header_mode):
                done, sent, _ = self.run_job(write_job(mode=job_mode), downloads=[download(mode=header_mode)])
                self.assertTrue(done)
                self.assertEqual(sent['status'], 'done')
                r = sent['result']
                self.assertIs(r['preview'], True)
                self.assertIs(r['would_write'], True)
                self.assertEqual((r['live_sha256_before'], r['live_size'], r['locked']), (sha(LIVE), len(LIVE), False))
                self.assertIs(r['backup_dir_writable'], True)
                self.assertNotIn('backup', r)
                self.assertEqual(self.live.read_bytes(), LIVE)
                self.assertEqual(self.folder_listing(), before)

    def test_preview_reports_a_changed_live_sheet_and_writes_nothing(self):
        before = self.folder_listing()
        done, sent, _ = self.run_job(write_job(mode='preview', live_sha256='f' * 64), downloads=[download(mode='preview')])
        self.assertTrue(done)
        self.assertEqual((sent['result']['would_write'], sent['result']['live_changed']), (False, True))
        self.assertEqual(self.folder_listing(), before)

    def test_live_changed_since_the_fetch_is_refused(self):
        self.live.write_bytes(LIVE + b' edited by hand after the fetch')
        before = self.folder_listing()
        done, sent, _ = self.run_job(write_job(), downloads=[download()])
        self.assertEqual((done, sent['status']), (False, 'failed'))
        self.assertIn('live_changed', sent['error'])
        self.assertIs(sent['result']['live_changed'], True)
        self.assertEqual(self.live.read_bytes(), LIVE + b' edited by hand after the fetch')
        self.assertEqual(self.folder_listing(), before)

    def test_live_sheet_missing_is_refused_in_write_mode(self):
        self.live.unlink()
        done, sent, _ = self.run_job(write_job(), downloads=[download()])
        self.assertEqual(sent['status'], 'failed')
        self.assertEqual(self.folder_listing(), [])

    def test_held_for_the_whole_retry_window_is_busy(self):
        real_replace = os.replace
        calls = []

        def locked(src, dst):
            calls.append(Path(dst).name)
            raise PermissionError(32, 'in use by another process')

        with mock.patch.object(agent_module.os, 'replace', side_effect=locked):
            done, sent, _ = self.run_job(write_job(), downloads=[download()])
        self.assertIs(os.replace, real_replace)
        self.assertFalse(done)
        self.assertEqual(sent['status'], 'busy')
        self.assertEqual(len(calls), 6)                     # the first try and 5 retries
        self.assertEqual(self.sleeps, [24] * 5)             # about two minutes
        self.assertEqual(self.live.read_bytes(), LIVE)
        self.assertFalse((self.root / agent_module.NEW_NAME).exists())
        self.assertIs(sent['result']['locked'], True)
        self.assertIn('untouched', sent['error'])

    def test_released_within_the_window_is_written(self):
        real_replace = os.replace
        state = {'left': 2}

        def sometimes(src, dst):
            if state['left']:
                state['left'] -= 1
                raise PermissionError(32, 'in use')
            return real_replace(src, dst)

        with mock.patch.object(agent_module.os, 'replace', side_effect=sometimes):
            done, sent, _ = self.run_job(write_job(), downloads=[download()])
        self.assertTrue(done)
        self.assertEqual((sent['status'], sent['result']['retries']), ('done', 2))
        self.assertEqual(self.sleeps, [24, 24])
        self.assertEqual(self.live.read_bytes(), NEW)

    def test_an_edit_saved_while_waiting_for_the_swap_is_kept(self):
        edited = LIVE + b' saved in Excel while the agent waited'
        calls = []

        def held_then_saved(src, dst):
            calls.append(1)
            self.live.write_bytes(edited)        # the user saves and closes Excel during the retry window
            raise PermissionError(32, 'in use')

        with mock.patch.object(agent_module.os, 'replace', side_effect=held_then_saved):
            done, sent, _ = self.run_job(write_job(), downloads=[download()])
        self.assertEqual((done, sent['status']), (False, 'failed'))
        self.assertIn('live_changed', sent['error'])
        self.assertEqual(len(calls), 1)                  # never replaced over the new edit
        self.assertEqual(self.live.read_bytes(), edited)
        self.assertFalse((self.root / agent_module.NEW_NAME).exists())

    def test_a_stale_new_file_is_removed_in_write_mode_only(self):
        stale = self.root / agent_module.NEW_NAME
        stale.write_bytes(b'left by a crash')
        done, sent, _ = self.run_job(write_job(mode='preview'), downloads=[download(mode='preview')])
        self.assertTrue(stale.exists())                  # a preview writes nothing, not even a delete
        self.assertIs(sent['result']['stale_new'], True)
        with mock.patch.object(agent_module.os, 'replace', side_effect=OSError(5, 'disk')):
            done, sent, _ = self.run_job(write_job(), downloads=[download()])
        self.assertIs(sent['result']['stale_new_removed'], True)
        self.assertFalse(stale.exists())

    def test_a_backup_that_fails_midway_leaves_no_partial_file(self):
        real_copy = shutil.copyfile

        def partial(src, dst, *args, **kwargs):
            if Path(dst).parent.name == agent_module.BACKUP_FOLDER:
                Path(dst).write_bytes(b'half')
                raise OSError(28, 'disk full')
            return real_copy(src, dst, *args, **kwargs)

        with mock.patch.object(agent_module.shutil, 'copyfile', side_effect=partial):
            done, sent, _ = self.run_job(write_job(), downloads=[download()])
        self.assertEqual(sent['status'], 'failed')
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.live.read_bytes(), LIVE)
        self.assertFalse((self.root / agent_module.NEW_NAME).exists())

    def test_any_other_failure_leaves_the_live_sheet(self):
        with mock.patch.object(agent_module.os, 'replace', side_effect=OSError(5, 'disk')):
            done, sent, _ = self.run_job(write_job(), downloads=[download()])
        self.assertEqual((done, sent['status']), (False, 'failed'))
        self.assertEqual(self.live.read_bytes(), LIVE)
        self.assertFalse((self.root / agent_module.NEW_NAME).exists())

    def test_a_failed_backup_writes_nothing_over_the_live_sheet(self):
        (self.root / 'backup').write_bytes(b'a file where the folder should be')
        done, sent, _ = self.run_job(write_job(), downloads=[download()])
        self.assertEqual(sent['status'], 'failed')
        self.assertEqual(self.live.read_bytes(), LIVE)
        self.assertFalse((self.root / agent_module.NEW_NAME).exists())

    def test_no_invoicer_dir_touches_nothing(self):
        for value in ('', str(self.root / 'missing')):
            with self.subTest(value=value):
                http = FakeHttp(downloads=[download()])
                self.agent(http, invoicer_dir=value).handle(write_job())
                sent = http.file_results()
                self.assertEqual(sent[0]['status'], 'failed')
                self.assertIn('invoicer_dir', sent[0]['error'])
                self.assertFalse([c for c in http.calls if c['method'] == 'get'])
        self.assertEqual(self.live.read_bytes(), LIVE)


class FetchTests(SheetTestCase):
    def test_fetch_uploads_a_copy_and_never_opens_the_live_sheet_for_writing(self):
        os.utime(self.live, (1_700_000_000, 1_700_000_000))
        before = self.live.stat().st_mtime
        opened, real_open = [], builtins.open

        def recording_open(file, mode='r', *args, **kwargs):
            opened.append((os.path.abspath(os.fspath(file)) if not isinstance(file, int) else file, mode))
            return real_open(file, mode, *args, **kwargs)

        with mock.patch.object(builtins, 'open', side_effect=recording_open):
            done, sent, http = self.run_job({'id': 9, 'kind': 'egs_fetch', 'mode': 'preview', 'result_url': '/x/'})
        self.assertTrue(done)
        self.assertEqual(sent['status'], 'done')
        self.assertEqual(sent['file'], LIVE)
        self.assertEqual((sent['result']['live_sha256'], sent['result']['live_size']), (sha(LIVE), len(LIVE)))
        upload = [c for c in http.calls if c['files'] is not None][0]
        self.assertEqual(upload['url'], 'https://server.test/api/tax-invoicing/signing-agent/files/9/result/')
        self.assertEqual(upload['files']['file'][0], agent_module.LIVE_NAME)
        self.assertGreaterEqual(upload['timeout'], 120)
        live_opens = [mode for path, mode in opened if path == os.path.abspath(self.live)]
        self.assertTrue(live_opens)
        self.assertTrue(all(set(mode) <= {'r', 'b'} for mode in live_opens), live_opens)
        self.assertFalse([p for p, mode in opened if isinstance(p, str) and p.startswith(str(self.root)) and 'r' not in mode])
        self.assertEqual(self.live.stat().st_mtime, before)
        self.assertEqual(self.folder_listing(), [agent_module.LIVE_NAME])

    def test_fetch_of_a_held_sheet_is_busy(self):
        with mock.patch.object(agent_module.shutil, 'copyfile', side_effect=PermissionError(32, 'in use')):
            done, sent, _ = self.run_job({'id': 9, 'kind': 'egs_fetch', 'mode': 'preview'})
        self.assertEqual((done, sent['status'], sent['file']), (False, 'busy', None))
        self.assertEqual(self.sleeps, [24] * 5)

    def test_fetch_without_the_sheet_fails(self):
        self.live.unlink()
        done, sent, _ = self.run_job({'id': 9, 'kind': 'egs_fetch', 'mode': 'preview'})
        self.assertEqual((done, sent['status']), (False, 'failed'))

    def test_a_refused_upload_is_not_retried(self):
        http = FakeHttp(results=[FakeResponse(400, {'detail': 'not an xlsx'})])
        self.assertFalse(self.agent(http).handle({'id': 9, 'kind': 'egs_fetch', 'mode': 'preview'}))
        self.assertEqual(len(http.file_results()), 1)


class SigningUnchangedTests(SheetTestCase):
    def test_a_signing_job_still_goes_to_the_signing_path(self):
        http = FakeHttp()
        agent = self.agent(http)
        text = 'canonical'
        job = {'id': 3, 'kind': 'document', 'canonical_text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest()}
        with mock.patch.object(agent, 'handle_signing', return_value=True) as signing, \
                mock.patch.object(agent, 'handle_file') as files:
            self.assertTrue(agent.handle(job))
        signing.assert_called_once_with(job)
        files.assert_not_called()
        self.assertEqual(self.folder_listing(), [agent_module.LIVE_NAME])

    def test_signing_result_body_is_unchanged(self):
        http = FakeHttp()
        agent = self.agent(http)
        agent.server.post_result(5, signature='c2ln')
        call = [c for c in http.calls if c['url'].endswith('/jobs/5/result/')][0]
        self.assertEqual(call['json'], {'signature': 'c2ln'})
        self.assertIsNone(call['files'])
