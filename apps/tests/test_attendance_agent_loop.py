"""Task 5: the attendance agent's spool, uploader and collection loop.

No machine and no ERP are contacted: machines are fakes, and the uploader talks to
a throwaway HTTP server on 127.0.0.1 that plays the Task 3 contract.
"""
import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import date, datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from attendance_agent import __main__ as agent_main
from attendance_agent import collector
from attendance_agent.collector import (
    AgentLoop,
    collect_device,
    drain,
    load_config,
    run_forever,
)
from attendance_agent.spool import Spool
from attendance_agent.uploader import Uploader, UploadError
from attendance_agent.zk_client import (
    ClockInvalid,
    CommKeyRequired,
    DeviceUserRow,
    LogRow,
    Sizes,
    UnexpectedRecordSize,
    ZkProtocolError,
)

SECRET = 'S3CRET-AGENT-VALUE-xyz'
COMM_KEY = '987123'
NOW = datetime(2026, 11, 7, 10, 0, 0)
RUN_KEYS = {
    'device_serial', 'started_at', 'finished_at', 'records_read', 'oldest_date',
    'newest_date', 'drift_seconds', 'device_log_count', 'status', 'error',
}


def device(serial='SN1', ip='192.0.2.1'):
    return {'serial': serial, 'name': serial, 'ip': ip, 'port': 4370}


def log_row(index=0, code='1001', day=date(2026, 11, 6)):
    return LogRow(code, 1000 + index, day, time(9, 0, 0), 4, 1)


class FakeClient:
    """Stands in for ZkClient, as a context manager with the same read methods."""

    def __init__(self, serial='SN1', logs=None, users=None, clock=NOW, log_count=None,
                 logs_error=None, clock_error=None, users_error=None,
                 device_serial='use-serial'):
        self.reported_serial = serial if device_serial == 'use-serial' else device_serial
        self.logs = [log_row()] if logs is None else logs
        self.users = [DeviceUserRow('1001', 'SamerSami', False)] if users is None else users
        self.clock = clock
        self.log_count = len(self.logs) if log_count is None else log_count
        self.logs_error = logs_error
        self.clock_error = clock_error
        self.users_error = users_error
        self.calls = []
        self.exited = False

    def __enter__(self):
        self.calls.append('enter')
        return self

    def __exit__(self, exc_type, exc, tb):
        self.calls.append('exit')
        self.exited = True
        return False

    def read_serial(self):
        self.calls.append('serial')
        return self.reported_serial

    def read_time(self):
        self.calls.append('time')
        if self.clock_error:
            raise self.clock_error
        return self.clock

    def read_sizes(self):
        self.calls.append('sizes')
        return Sizes(len(self.users), self.log_count, 1000, 100000)

    def read_users(self):
        self.calls.append('users')
        if self.users_error:
            raise self.users_error
        return self.users

    def read_logs(self):
        self.calls.append('logs')
        if self.logs_error:
            raise self.logs_error
        return self.logs


class FakeUploader:
    """Plays the ERP: records what arrived, and can refuse at a chosen send."""

    def __init__(self, devices=None, collect_now=False, fail_on=None, on_send=None):
        self.devices = devices if devices is not None else [device()]
        self.collect_now = collect_now
        self.config_down = False
        self.fail_on = fail_on  # zero-based send number that answers 500
        self.on_send = on_send
        self.sent = []
        self.attempts = 0

    def get_config(self):
        if self.config_down:
            raise UploadError('sever unreachable')
        return {'agent': 'office', 'collect_now': self.collect_now, 'devices': self.devices}

    def send(self, kind, payload):
        if self.on_send:
            self.on_send(kind, payload)
        attempt = self.attempts
        self.attempts += 1
        if self.fail_on == attempt:
            raise UploadError('HTTP 500')
        self.sent.append((kind, payload))

    def of_kind(self, kind):
        return [payload for sent_kind, payload in self.sent if sent_kind == kind]


class TempDirTestCase(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='attendance-agent-test-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.spool = Spool(self.root / 'spool')


class SpoolTests(TempDirTestCase):
    def test_put_returns_a_file_listed_as_pending(self):
        path = self.spool.put('punches', {'a': 1})
        self.assertTrue(path.exists())
        self.assertEqual(self.spool.pending(), [path])
        self.assertEqual(self.spool.read(path), ('punches', {'a': 1}))

    def test_pending_is_oldest_first_beyond_nine_files(self):
        paths = [self.spool.put('punches', {'n': n}) for n in range(12)]
        self.assertEqual(self.spool.pending(), paths)

    def test_order_survives_a_restart(self):
        spool = self.spool
        for _ in range(5):
            first = spool.put('punches', {'n': 1})
            spool = Spool(self.root / 'spool')
            second = spool.put('punches', {'n': 2})
            self.assertLess(first.name.split('-')[0], second.name.split('-')[0])
            self.assertEqual(spool.pending()[-2:], [first, second])

    def test_ack_removes_only_that_file(self):
        first = self.spool.put('punches', {'n': 1})
        second = self.spool.put('punches', {'n': 2})
        self.spool.ack(first)
        self.assertEqual(self.spool.pending(), [second])

    def test_crash_mid_write_ignored(self):
        (self.root / 'spool' / '000000000001-punches-abcd.tmp').write_text('{"half')
        self.assertEqual(self.spool.pending(), [])

    def test_failed_rename_leaves_nothing_pending(self):
        with mock.patch('attendance_agent.spool.os.replace', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.spool.put('punches', {'n': 1})
        self.assertEqual(self.spool.pending(), [])

    def test_file_is_flushed_to_disk_before_it_becomes_visible(self):
        events = []
        real_fsync, real_replace = os.fsync, os.replace

        def fsync(handle):
            events.append('fsync')
            real_fsync(handle)

        def replace(source, target):
            events.append('replace')
            real_replace(source, target)

        with mock.patch('attendance_agent.spool.os.fsync', side_effect=fsync), \
                mock.patch('attendance_agent.spool.os.replace', side_effect=replace):
            self.spool.put('punches', {'n': 1})
        self.assertEqual(events, ['fsync', 'replace'])

    def test_brief_file_lock_on_rename_is_retried(self):
        # Antivirus often holds a just-closed file on Windows.
        real_replace = os.replace
        calls = []

        def replace(source, target):
            calls.append(source)
            if len(calls) < 3:
                raise PermissionError('locked')
            real_replace(source, target)

        with mock.patch('attendance_agent.spool.os.replace', side_effect=replace), \
                mock.patch('attendance_agent.spool.time.sleep'):
            path = self.spool.put('punches', {'n': 1})
        self.assertEqual(self.spool.pending(), [path])

    def test_failed_write_leaves_no_partial_file(self):
        with mock.patch('attendance_agent.spool.json.dump', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.spool.put('punches', {'n': 1})
        self.assertEqual(list((self.root / 'spool').iterdir()), [])

    def test_foreign_file_is_ignored_and_does_not_break_startup(self):
        (self.root / 'spool' / 'notes.json').write_text('{}', encoding='utf-8')
        again = Spool(self.root / 'spool')
        self.assertEqual(again.pending(), [])
        path = again.put('runs', {})
        self.assertEqual(again.pending(), [path])


class DrainTests(TempDirTestCase):
    def test_spool_written_before_send(self):
        seen = []
        uploader = FakeUploader(
            on_send=lambda kind, payload: seen.append(
                [self.spool.read(path) for path in self.spool.pending()]
            ),
        )
        self.spool.put('punches', {'n': 1})
        drain(self.spool, uploader)
        self.assertEqual(seen, [[('punches', {'n': 1})]])

    def test_erp_500_keeps_file_and_resends_in_order(self):
        for n in range(3):
            self.spool.put('punches', {'n': n})
        uploader = FakeUploader(fail_on=1)
        with self.assertLogs('attendance_agent', level='WARNING'):
            drain(self.spool, uploader)
        self.assertEqual(uploader.of_kind('punches'), [{'n': 0}])
        self.assertEqual(len(self.spool.pending()), 2)

        uploader.fail_on = None
        drain(self.spool, uploader)
        self.assertEqual(uploader.of_kind('punches'), [{'n': 0}, {'n': 1}, {'n': 2}])
        self.assertEqual(self.spool.pending(), [])

    def test_failed_ack_leaves_file_to_be_resent(self):
        # Resending is safe (the ERP is idempotent); losing a file is not.
        self.spool.put('punches', {'n': 1})
        uploader = FakeUploader()
        with mock.patch.object(self.spool, 'ack', side_effect=PermissionError('locked')):
            with self.assertLogs('attendance_agent', level='WARNING'):
                drain(self.spool, uploader)
        self.assertEqual(len(self.spool.pending()), 1)
        drain(self.spool, uploader)
        self.assertEqual(uploader.attempts, 2)
        self.assertEqual(self.spool.pending(), [])

    def refusing(self, refused_n):
        uploader = FakeUploader()

        def send(kind, payload):
            if payload['n'] == refused_n:
                raise UploadError('HTTP 403', permanent=True)
            uploader.sent.append((kind, payload))

        uploader.send = send
        return uploader

    def test_refused_file_stays_and_others_still_go(self):
        # A 403 for one reassigned machine must not hold back the other machines.
        refused = self.spool.put('punches', {'n': 0})
        for n in (1, 2):
            self.spool.put('punches', {'n': n})
        uploader = self.refusing(0)
        with self.assertLogs('attendance_agent', level='WARNING') as captured:
            drain(self.spool, uploader)
        self.assertEqual(uploader.of_kind('punches'), [{'n': 1}, {'n': 2}])
        self.assertEqual(self.spool.pending(), [refused])
        self.assertIn('HTTP 403', '\n'.join(captured.output))

    def test_refused_file_goes_once_the_erp_accepts_it(self):
        self.spool.put('punches', {'n': 0})
        with self.assertLogs('attendance_agent', level='WARNING'):
            drain(self.spool, self.refusing(0))
        uploader = FakeUploader()
        drain(self.spool, uploader)
        self.assertEqual(self.spool.pending(), [])

    def test_unreadable_file_stays_and_others_still_go(self):
        damaged = self.spool.put('punches', {'n': 0})
        damaged.write_bytes(b'')
        self.spool.put('punches', {'n': 1})
        uploader = FakeUploader()
        with self.assertLogs('attendance_agent', level='WARNING'):
            drain(self.spool, uploader)
        self.assertEqual(uploader.of_kind('punches'), [{'n': 1}])
        self.assertEqual(self.spool.pending(), [damaged])

    def test_long_backlog_stops_at_the_time_budget(self):
        # Reading machines must not wait hours behind a large upload backlog.
        for n in range(10):
            self.spool.put('punches', {'n': n})
        ticks = iter(range(0, 10000, 100))  # 100 seconds pass between checks
        uploader = FakeUploader()
        drain(self.spool, uploader, budget_seconds=300, clock=lambda: next(ticks))
        self.assertEqual(len(uploader.sent), 2)
        self.assertEqual(len(self.spool.pending()), 8)


class CollectDeviceTests(TempDirTestCase):
    def collect(self, client, target=None, **kwargs):
        collect_device(target or device(), lambda d: client, self.spool, lambda: NOW, **kwargs)
        return [self.spool.read(path) for path in self.spool.pending()]

    def run_payload(self, files):
        return [payload for kind, payload in files if kind == 'runs'][0]

    def test_read_order_and_disconnect_before_spool(self):
        client = FakeClient()
        order = []
        real_put = self.spool.put

        def tracking_put(kind, payload):
            order.append(client.exited)
            return real_put(kind, payload)

        with mock.patch.object(self.spool, 'put', side_effect=tracking_put):
            self.collect(client)
        self.assertEqual(client.calls, ['enter', 'serial', 'time', 'sizes', 'users', 'logs', 'exit'])
        self.assertTrue(all(order), 'spooled while still connected')

    def test_batches_at_2000(self):
        files = self.collect(FakeClient(logs=[log_row(i) for i in range(4500)]))
        batches = [payload for kind, payload in files if kind == 'punches']
        self.assertEqual([len(b['punches']) for b in batches], [2000, 2000, 500])
        stamps = [p['raw_stamp'] for b in batches for p in b['punches']]
        self.assertEqual(len(set(stamps)), 4500)

    def test_exactly_2000_is_one_file(self):
        files = self.collect(FakeClient(logs=[log_row(i) for i in range(2000)]))
        self.assertEqual(len([1 for kind, _p in files if kind == 'punches']), 1)

    def test_identical_rows_are_sent_once_but_counted_as_read(self):
        # The database keeps one row per identity, and the ERP's counts must add up to
        # what was sent. The same second with another state or user is a different punch.
        same = log_row(0)
        other_state = same._replace(state=5)
        other_user = same._replace(user_code='1002')
        files = self.collect(FakeClient(logs=[same, same, other_state, other_user]))
        punches = [p for kind, p in files if kind == 'punches'][0]['punches']
        self.assertEqual(len(punches), 3)
        self.assertEqual(self.run_payload(files)['records_read'], 4)

    def test_punch_payload_matches_the_contract(self):
        files = self.collect(FakeClient())
        payload = [p for kind, p in files if kind == 'punches'][0]
        self.assertEqual(payload, {
            'device_serial': 'SN1',
            'punches': [{
                'user_code': '1001', 'raw_stamp': 1000, 'date': '2026-11-06',
                'time': '09:00:00', 'state': 4, 'verify_mode': 1,
            }],
        })

    def test_undecodable_date_is_sent_as_null_not_dropped(self):
        bad = LogRow('1001', 123, None, None, 0, 1)
        files = self.collect(FakeClient(logs=[bad]))
        punch = [p for kind, p in files if kind == 'punches'][0]['punches'][0]
        self.assertEqual((punch['raw_stamp'], punch['date'], punch['time']), (123, None, None))

    def test_roster_payload_matches_the_contract(self):
        files = self.collect(FakeClient())
        self.assertEqual(
            [p for kind, p in files if kind == 'roster'][0],
            {'device_serial': 'SN1',
             'users': [{'user_code': '1001', 'name': 'SamerSami', 'is_admin': False}]},
        )

    def test_success_run_matches_the_contract_and_is_sent_last(self):
        logs = [log_row(0, day=date(2026, 11, 1)), log_row(1, day=date(2026, 11, 6))]
        files = self.collect(FakeClient(logs=logs, log_count=2))
        self.assertEqual(files[-1][0], 'runs')
        run = files[-1][1]
        self.assertEqual(set(run), RUN_KEYS)
        self.assertEqual(run['status'], 'success')
        self.assertEqual(run['error'], '')
        self.assertEqual(run['records_read'], 2)
        self.assertEqual(run['device_log_count'], 2)
        self.assertEqual(run['oldest_date'], '2026-11-01')
        self.assertEqual(run['newest_date'], '2026-11-06')
        self.assertEqual(run['started_at'], NOW.isoformat())

    def test_drift_reported(self):
        files = self.collect(FakeClient(clock=NOW - timedelta(seconds=180)))
        self.assertEqual(self.run_payload(files)['drift_seconds'], -180)

    def test_drift_ahead_is_positive(self):
        files = self.collect(FakeClient(clock=NOW + timedelta(seconds=90)))
        self.assertEqual(self.run_payload(files)['drift_seconds'], 90)

    def test_machine_with_empty_log_still_reports_a_run(self):
        files = self.collect(FakeClient(logs=[], users=[]))
        self.assertEqual([kind for kind, _p in files], ['roster', 'runs'])
        run = self.run_payload(files)
        self.assertEqual(run['status'], 'success')
        self.assertIsNone(run['oldest_date'])

    def test_read_failure_reports_a_failed_run_and_stores_no_part(self):
        files = self.collect(FakeClient(logs_error=TimeoutError('192.0.2.1 timed out')))
        self.assertEqual([kind for kind, _p in files], ['runs'])
        run = files[0][1]
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'TimeoutError')
        self.assertEqual(run['records_read'], 0)

    def test_comm_key_needed_is_named_in_the_failed_run(self):
        def factory(_device):
            raise CommKeyRequired('this machine needs a comm key')

        collect_device(device(), factory, self.spool, lambda: NOW)
        run = self.spool.read(self.spool.pending()[0])[1]
        self.assertEqual(run['status'], 'failed')
        self.assertIn('comm key', run['error'])

    def test_wrong_serial_stores_no_punch_under_this_device(self):
        # The IP now answers as another machine. Filing its punches under this serial
        # would corrupt the evidence.
        files = self.collect(FakeClient(device_serial='OTHER'))
        self.assertEqual([kind for kind, _p in files], ['runs'])
        run = files[0][1]
        self.assertEqual(run['status'], 'failed')
        self.assertIn('OTHER', run['error'])

    def test_unanswered_serial_does_not_block_collection(self):
        with self.assertLogs('attendance_agent', level='WARNING'):
            files = self.collect(FakeClient(device_serial=None))
        self.assertEqual(self.run_payload(files)['status'], 'success')
        self.assertIn('punches', [kind for kind, _p in files])

    def test_impossible_machine_clock_still_collects_the_log(self):
        files = self.collect(FakeClient(clock_error=ClockInvalid('impossible')))
        run = self.run_payload(files)
        self.assertEqual(run['status'], 'success')
        self.assertIsNone(run['drift_seconds'])
        self.assertIn('punches', [kind for kind, _p in files])

    def test_failed_save_reports_a_failed_run_and_raises(self):
        real_put = self.spool.put

        def put(kind, payload):
            if kind == 'punches':
                raise OSError('locked')
            return real_put(kind, payload)

        with mock.patch.object(self.spool, 'put', side_effect=put):
            with self.assertRaises(OSError):
                collect_device(device(), lambda d: FakeClient(), self.spool, lambda: NOW)
        run = [p for kind, p in map(self.spool.read, self.spool.pending()) if kind == 'runs'][0]
        self.assertEqual(run['status'], 'failed')
        self.assertIn('save', run['error'])

    def test_refused_clock_read_still_collects_the_log(self):
        files = self.collect(FakeClient(clock_error=ZkProtocolError('clock read answered 2001')))
        run = self.run_payload(files)
        self.assertEqual(run['status'], 'success')
        self.assertIsNone(run['drift_seconds'])
        self.assertIn('punches', [kind for kind, _p in files])

    def test_roster_timeout_still_collects_the_log_on_a_new_connection(self):
        # After a failed roster read the session may be out of step.
        client = FakeClient(users_error=TimeoutError('192.0.2.1'))
        files = self.collect(client)
        self.assertEqual(client.calls.count('enter'), 2)
        self.assertLess(client.calls.index('exit'), client.calls.index('logs'))
        self.assertEqual([kind for kind, _p in files], ['punches', 'runs'])
        self.assertNotIn('192.0.2.1', self.run_payload(files)['error'])

    def test_second_connection_also_checks_the_serial(self):
        answers = iter(['SN1', 'OTHER'])
        client = FakeClient(users_error=TimeoutError('x'))
        client.read_serial = lambda: next(answers)
        files = self.collect(client)
        self.assertEqual([kind for kind, _p in files], ['runs'])

    def test_unreadable_roster_does_not_block_the_log(self):
        client = FakeClient(users_error=UnexpectedRecordSize('100 bytes for 1 records'))
        files = self.collect(client)
        self.assertEqual([kind for kind, _p in files], ['punches', 'runs'])
        run = self.run_payload(files)
        self.assertEqual(run['status'], 'success')
        self.assertIn('roster', run['error'])

    def undecodable_error(self, raw):
        error = UnexpectedRecordSize('64 bytes for 2 records')
        error.raw_table = raw
        return error

    def quarantined(self):
        return sorted((self.root / 'spool' / 'quarantine').glob('*.bin'))

    def test_undecodable_log_is_kept_in_quarantine(self):
        raw = b'\x40\0\0\0' + b'\xAB' * 64
        files = self.collect(FakeClient(logs_error=self.undecodable_error(raw)))
        self.assertEqual([kind for kind, _p in files], ['runs'])
        self.assertEqual(files[0][1]['status'], 'failed')
        kept = self.quarantined()
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].read_bytes(), raw)

    def test_same_undecodable_log_is_kept_once(self):
        raw = b'\x40\0\0\0' + b'\xAB' * 64
        self.collect(FakeClient(logs_error=self.undecodable_error(raw)))
        self.collect(FakeClient(logs_error=self.undecodable_error(raw)))
        self.assertEqual(len(self.quarantined()), 1)

    def test_changed_undecodable_log_is_kept_again(self):
        self.collect(FakeClient(logs_error=self.undecodable_error(b'first')))
        self.collect(FakeClient(logs_error=self.undecodable_error(b'second')))
        self.assertEqual(len(self.quarantined()), 2)

    def test_quarantine_file_name_is_safe_from_an_odd_serial(self):
        client = FakeClient(logs_error=self.undecodable_error(b'x'), serial='..\\x/y')
        self.collect(client, target=device('..\\x/y'))
        kept = self.quarantined()
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].parent, self.root / 'spool' / 'quarantine')

    def test_full_disk_on_quarantine_still_reports_the_failed_run(self):
        client = FakeClient(logs_error=self.undecodable_error(b'x'))
        with mock.patch.object(self.spool, 'quarantine', side_effect=OSError('disk')):
            files = self.collect(client)
        self.assertEqual(files[0][1]['status'], 'failed')

    def test_collect_done_only_when_asked(self):
        without = self.run_payload(self.collect(FakeClient()))
        self.assertNotIn('collect_done', without)
        for path in self.spool.pending():
            self.spool.ack(path)
        with_flag = self.run_payload(self.collect(FakeClient(), collect_done=True))
        self.assertIs(with_flag['collect_done'], True)


class LoopTests(TempDirTestCase):
    def make_loop(self, uploader, factory=None):
        self.clock_value = 0
        self.collected = []

        def default_factory(target):
            self.collected.append(target['serial'])
            return FakeClient(serial=target['serial'])

        return AgentLoop(
            uploader=uploader,
            spool=self.spool,
            client_factory=factory or default_factory,
            now=lambda: NOW,
            clock=lambda: self.clock_value,
            cache_path=self.root / 'devices.json',
        )

    def test_first_tick_collects_and_sends_everything(self):
        uploader = FakeUploader()
        self.make_loop(uploader).tick()
        self.assertEqual(self.collected, ['SN1'])
        self.assertEqual(self.spool.pending(), [])
        self.assertEqual([kind for kind, _p in uploader.sent], ['roster', 'punches', 'runs'])

    def test_one_bad_machine_does_not_stop_others(self):
        uploader = FakeUploader(devices=[device('BAD'), device('GOOD')])

        def factory(target):
            if target['serial'] == 'BAD':
                raise TimeoutError('no answer')
            return FakeClient(serial='GOOD')

        self.make_loop(uploader, factory).tick()
        runs = {r['device_serial']: r for r in uploader.of_kind('runs')}
        self.assertEqual(runs['BAD']['status'], 'failed')
        self.assertEqual(runs['GOOD']['status'], 'success')
        self.assertEqual(len(uploader.of_kind('punches')), 1)

    def test_unexpected_crash_on_one_machine_does_not_stop_others(self):
        uploader = FakeUploader(devices=[device('BAD'), device('GOOD')])
        real_put = self.spool.put

        def put(kind, payload):
            if payload['device_serial'] == 'BAD':
                raise OSError('disk full')
            return real_put(kind, payload)

        def factory(target):
            return FakeClient(serial=target['serial'])

        loop = self.make_loop(uploader, factory)
        with mock.patch.object(self.spool, 'put', side_effect=put):
            with self.assertLogs('attendance_agent', level='ERROR'):
                loop.tick()
        self.assertEqual(
            [p['device_serial'] for p in uploader.of_kind('punches')], ['GOOD'],
        )

    def test_hourly_schedule(self):
        uploader = FakeUploader()
        loop = self.make_loop(uploader)
        loop.tick()
        self.assertEqual(len(self.collected), 1)
        self.clock_value = 60
        loop.tick()
        self.clock_value = 3599
        loop.tick()
        self.assertEqual(len(self.collected), 1)
        self.clock_value = 3600
        loop.tick()
        self.assertEqual(len(self.collected), 2)

    def test_new_machine_is_collected_without_waiting_an_hour(self):
        uploader = FakeUploader(devices=[device('A')])
        loop = self.make_loop(uploader)
        loop.tick()
        uploader.devices = [device('A'), device('B')]
        self.clock_value = 60
        loop.tick()
        self.assertEqual(self.collected, ['A', 'B'])

    def test_collect_now_triggers_run(self):
        uploader = FakeUploader()
        loop = self.make_loop(uploader)
        loop.tick()
        self.clock_value = 300
        uploader.collect_now = True
        loop.tick()
        self.assertEqual(len(self.collected), 2)

    def test_collect_now_waits_for_the_minimum_gap(self):
        uploader = FakeUploader()
        loop = self.make_loop(uploader)
        loop.tick()
        self.clock_value = 299
        uploader.collect_now = True
        loop.tick()
        self.assertEqual(len(self.collected), 1)
        self.assertEqual(uploader.of_kind('runs')[-1].get('collect_done'), None)

    def test_collect_now_with_a_failing_spool_does_not_hammer_machines(self):
        uploader = FakeUploader(collect_now=True)
        loop = self.make_loop(uploader)
        with mock.patch.object(self.spool, 'put', side_effect=OSError('disk full')), \
                self.assertLogs('attendance_agent', level='ERROR'):
            for minute in range(5):
                self.clock_value = minute * 60
                loop.tick()
        self.assertEqual(len(self.collected), 1)

    def test_failed_save_is_retried_soon_not_in_an_hour(self):
        uploader = FakeUploader()
        loop = self.make_loop(uploader)
        real_put = self.spool.put
        failures = iter([True])

        def put(kind, payload):
            if next(failures, False):
                raise OSError('locked')
            return real_put(kind, payload)

        with mock.patch.object(self.spool, 'put', side_effect=put), \
                self.assertLogs('attendance_agent', level='ERROR'):
            loop.tick()
        self.clock_value = 299
        loop.tick()
        self.assertEqual(len(self.collected), 1)
        self.clock_value = 300
        loop.tick()
        self.assertEqual(len(self.collected), 2)

    def test_malformed_machine_entry_does_not_stop_the_others(self):
        uploader = FakeUploader(devices=[{'name': 'no serial'}, 'junk', device('GOOD')])
        with self.assertLogs('attendance_agent', level='ERROR'):
            self.make_loop(uploader).tick()
        self.assertEqual(self.collected, ['GOOD'])
        self.assertEqual(uploader.of_kind('punches')[0]['device_serial'], 'GOOD')

    def test_only_serial_reads_one_machine(self):
        uploader = FakeUploader(devices=[device('A'), device('B')])
        loop = self.make_loop(uploader)
        loop._only_serial = 'B'
        loop.tick()
        self.assertEqual(self.collected, ['B'])

    def test_empty_answer_does_not_wipe_the_saved_list(self):
        uploader = FakeUploader()
        self.make_loop(uploader).tick()
        uploader.devices = []
        with self.assertLogs('attendance_agent', level='WARNING'):
            self.make_loop(uploader).tick()
        down = FakeUploader()
        down.config_down = True
        with self.assertLogs('attendance_agent', level='WARNING'):
            self.make_loop(down).tick()
        self.assertEqual(self.collected, ['SN1'])

    def test_unchanged_list_is_written_only_once(self):
        uploader = FakeUploader()
        loop = self.make_loop(uploader)
        loop.tick()
        with mock.patch('attendance_agent.collector.os.replace') as replace:
            self.clock_value = 60
            loop.tick()
        replace.assert_not_called()

    def test_collect_done_goes_on_the_last_machine_only(self):
        uploader = FakeUploader(devices=[device('A'), device('B')], collect_now=True)
        self.make_loop(uploader).tick()
        runs = uploader.of_kind('runs')
        self.assertEqual(len(self.collected), 2)
        self.assertNotIn('collect_done', runs[0])
        self.assertIs(runs[1]['collect_done'], True)

    def test_collect_done_sent_even_if_the_last_machine_fails(self):
        uploader = FakeUploader(devices=[device('A')], collect_now=True)

        def factory(_target):
            raise TimeoutError('no answer')

        self.make_loop(uploader, factory).tick()
        run = uploader.of_kind('runs')[0]
        self.assertEqual(run['status'], 'failed')
        self.assertIs(run['collect_done'], True)

    def test_hourly_run_does_not_clear_collect_request(self):
        uploader = FakeUploader()
        self.make_loop(uploader).tick()
        self.assertNotIn('collect_done', uploader.of_kind('runs')[0])

    def test_stuck_spool_does_not_hammer_machines_on_collect_now(self):
        # The request stays set while the ERP refuses uploads. Without this guard the
        # agent would re-read every machine each minute.
        uploader = FakeUploader(collect_now=True)
        uploader.send = mock.Mock(side_effect=UploadError('HTTP 500'))
        loop = self.make_loop(uploader)
        with self.assertLogs('attendance_agent', level='WARNING'):
            loop.tick()
        self.clock_value = 60
        with self.assertLogs('attendance_agent', level='WARNING'):
            loop.tick()
        self.assertEqual(len(self.collected), 1)

    def test_hourly_collection_continues_while_uploads_fail(self):
        # Logs may be cleared at any time, so a stuck upload never stops collection.
        uploader = FakeUploader()
        uploader.send = mock.Mock(side_effect=UploadError('HTTP 500'))
        loop = self.make_loop(uploader)
        with self.assertLogs('attendance_agent', level='WARNING'):
            loop.tick()
        self.clock_value = 3600
        with self.assertLogs('attendance_agent', level='WARNING'):
            loop.tick()
        self.assertEqual(len(self.collected), 2)
        self.assertGreater(len(self.spool.pending()), 3)

    def test_erp_down_still_collects_from_saved_machine_list(self):
        uploader = FakeUploader()
        self.make_loop(uploader).tick()

        # The PC restarts while the ERP is down: a new loop, same state folder.
        down = FakeUploader()
        down.config_down = True
        down.send = mock.Mock(side_effect=UploadError('unreachable'))
        with self.assertLogs('attendance_agent', level='WARNING'):
            self.make_loop(down).tick()
        self.assertEqual(self.collected, ['SN1'])
        self.assertEqual(len(self.spool.pending()), 3)

    def test_erp_down_with_no_saved_list_does_not_crash(self):
        uploader = FakeUploader()
        uploader.config_down = True
        with self.assertLogs('attendance_agent', level='WARNING'):
            self.make_loop(uploader).tick()
        self.assertEqual(self.collected, [])

    def test_damaged_saved_list_does_not_crash(self):
        (self.root / 'devices.json').write_text('{half', encoding='utf-8')
        uploader = FakeUploader()
        uploader.config_down = True
        with self.assertLogs('attendance_agent', level='WARNING'):
            self.make_loop(uploader).tick()
        self.assertEqual(self.collected, [])



class PrivacyTests(TempDirTestCase):
    def test_secret_never_logged(self):
        uploader = Uploader('http://127.0.0.1:9', SECRET)
        client = FakeClient(logs_error=OSError(f'boom {SECRET} {COMM_KEY}'))
        with self.assertLogs('attendance_agent', level='DEBUG') as captured:
            logging.getLogger('attendance_agent').debug('start')
            collect_device(device(), lambda d: client, self.spool, lambda: NOW)
            drain(self.spool, uploader)
        text = '\n'.join(captured.output)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(COMM_KEY, text)

    def test_failure_text_sent_to_erp_holds_no_secret(self):
        client = FakeClient(logs_error=OSError(f'boom {SECRET}'))
        collect_device(device(), lambda d: client, self.spool, lambda: NOW)
        raw = self.spool.pending()[0].read_text(encoding='utf-8')
        self.assertNotIn(SECRET, raw)

    def test_logs_have_counts_only_no_names_or_codes(self):
        client = FakeClient(users=[DeviceUserRow('77123', 'SamerSami', False)],
                            logs=[log_row(code='77123')])
        with self.assertLogs('attendance_agent', level='DEBUG') as captured:
            logging.getLogger('attendance_agent').debug('start')
            collect_device(device(), lambda d: client, self.spool, lambda: NOW)
        text = '\n'.join(captured.output)
        self.assertNotIn('SamerSami', text)
        self.assertNotIn('77123', text)


class _ErpHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self):
        server = self.server
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else b''
        server.requests.append({
            'method': self.command, 'path': self.path,
            'secret': self.headers.get('X-ElR-Attendance-Agent'),
            'body': json.loads(body) if body else None,
        })
        status, headers, reply = server.script
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    do_GET = do_POST = _reply


class UploaderTests(SimpleTestCase):
    def setUp(self):
        self.server = HTTPServer(('127.0.0.1', 0), _ErpHandler)
        self.server.requests = []
        self.server.script = (200, {}, b'{}')
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.uploader = Uploader(f'http://127.0.0.1:{self.server.server_port}/', SECRET)
        self.punches = {'device_serial': 'SN1', 'punches': [{'raw_stamp': 1}, {'raw_stamp': 2}]}

    def answer(self, status=200, body=b'{}', headers=None):
        self.server.script = (status, headers or {}, body)

    def test_get_config_uses_the_contract_path_and_header(self):
        config = {'agent': 'office', 'collect_now': True, 'devices': [device()]}
        self.answer(body=json.dumps(config).encode())
        self.assertEqual(self.uploader.get_config(), config)
        request = self.server.requests[0]
        self.assertEqual(request['method'], 'GET')
        self.assertEqual(request['path'], '/api/hr-attendance/agent/config/')
        self.assertEqual(request['secret'], SECRET)

    def test_send_posts_each_kind_to_its_endpoint(self):
        for kind in ('roster', 'runs'):
            self.uploader.send(kind, {'device_serial': 'SN1'})
        self.assertEqual(
            [r['path'] for r in self.server.requests],
            ['/api/hr-attendance/agent/roster/', '/api/hr-attendance/agent/runs/'],
        )
        self.assertEqual(self.server.requests[0]['body'], {'device_serial': 'SN1'})

    def test_punches_acknowledged_with_matching_counts(self):
        self.answer(body=b'{"accepted": 1, "duplicate": 1}')
        self.uploader.send('punches', self.punches)
        self.assertEqual(self.server.requests[0]['path'], '/api/hr-attendance/agent/punches/')

    def test_500_raises(self):
        self.answer(status=500, body=b'{"detail": "boom"}')
        with self.assertRaises(UploadError):
            self.uploader.send('punches', self.punches)

    def test_401_raises_with_no_secret_in_the_message(self):
        self.answer(status=401, body=b'{}')
        with self.assertRaises(UploadError) as caught:
            self.uploader.send('runs', {})
        self.assertNotIn(SECRET, str(caught.exception))

    def test_html_200_is_not_an_acknowledgement(self):
        # A front-end fallback page answering 200 must not delete the spool file.
        self.answer(body=b'<!doctype html><html></html>')
        with self.assertRaises(UploadError):
            self.uploader.send('punches', self.punches)
        with self.assertRaises(UploadError):
            self.uploader.send('roster', {})

    def test_empty_or_non_object_answer_is_not_an_acknowledgement(self):
        # A runs file holds the log count, the evidence of clearing.
        for body in (b'', b'"ok"', b'[]'):
            with self.subTest(body=body):
                self.answer(body=body)
                with self.assertRaises(UploadError):
                    self.uploader.send('runs', {})

    def test_which_failures_are_permanent(self):
        for status, permanent in [(400, True), (403, True), (404, True), (413, True),
                                  (401, False), (408, False), (429, False),
                                  (500, False), (503, False)]:
            with self.subTest(status=status):
                self.answer(status=status)
                with self.assertRaises(UploadError) as caught:
                    self.uploader.send('runs', {})
                self.assertEqual(caught.exception.permanent, permanent)

    def test_unreachable_is_not_permanent(self):
        with self.assertRaises(UploadError) as caught:
            Uploader('http://127.0.0.1:9', SECRET).send('runs', {})
        self.assertFalse(caught.exception.permanent)

    def test_counts_that_do_not_add_up_are_not_an_acknowledgement(self):
        self.answer(body=b'{"accepted": 1, "duplicate": 0}')
        with self.assertRaises(UploadError):
            self.uploader.send('punches', self.punches)

    def test_redirect_is_refused_and_not_followed(self):
        # urllib would turn a redirected POST into a GET that answers 200, and it
        # would carry the secret to wherever the redirect points.
        self.answer(status=302, headers={'Location': '/login/'})
        with self.assertRaises(UploadError):
            self.uploader.send('runs', {})
        self.assertEqual(len(self.server.requests), 1)

    def test_unreachable_erp_raises_upload_error(self):
        dead = Uploader('http://127.0.0.1:9', SECRET)
        with self.assertRaises(UploadError):
            dead.send('runs', {})

    def test_bad_config_shape_raises(self):
        self.answer(body=b'[]')
        with self.assertRaises(UploadError):
            self.uploader.get_config()

    def test_only_http_and_https_are_accepted(self):
        with self.assertRaises(ValueError):
            Uploader('file:///c:/windows/win.ini', SECRET)

    def test_system_proxy_is_not_used(self):
        with mock.patch.dict('os.environ', {'HTTP_PROXY': 'http://127.0.0.1:9',
                                            'http_proxy': 'http://127.0.0.1:9'}):
            uploader = Uploader(f'http://127.0.0.1:{self.server.server_port}', SECRET)
            uploader.send('runs', {})
        self.assertEqual(len(self.server.requests), 1)

    def test_timeout_is_sixty_seconds(self):
        with mock.patch.object(self.uploader, '_opener') as opener:
            opener.open.side_effect = OSError('stop')
            with self.assertRaises(UploadError):
                self.uploader.send('runs', {})
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 60)


class ConfigTests(TempDirTestCase):
    def write_ini(self, text):
        path = self.root / 'agent.ini'
        path.write_text(text, encoding='utf-8')
        return path

    def test_reads_settings_keeping_serial_case_and_percent_signs(self):
        config = load_config(self.write_ini(
            f'[erp]\nurl = http://192.0.2.5:8000\nsecret = ab%cd{SECRET}\n'
            f'[agent]\nstate_dir = {self.root / "state"}\n'
            f'[comm_keys]\nA2NC173961011 = {COMM_KEY}\n'
        ))
        self.assertEqual(config.erp_url, 'http://192.0.2.5:8000')
        self.assertEqual(config.secret, f'ab%cd{SECRET}')
        self.assertEqual(config.comm_keys, {'A2NC173961011': COMM_KEY})
        self.assertEqual(config.state_dir, self.root / 'state')

    def test_state_folder_defaults_next_to_the_ini(self):
        config = load_config(self.write_ini(f'[erp]\nurl = http://x\nsecret = {SECRET}\n'))
        self.assertEqual(config.state_dir, self.root / 'agent_state')

    def test_repr_hides_secret_and_comm_keys(self):
        config = load_config(self.write_ini(
            f'[erp]\nurl = http://x\nsecret = {SECRET}\n[comm_keys]\nSN1 = {COMM_KEY}\n'
        ))
        self.assertNotIn(SECRET, repr(config))
        self.assertNotIn(COMM_KEY, repr(config))

    def test_missing_secret_is_refused(self):
        with self.assertRaises(ValueError):
            load_config(self.write_ini('[erp]\nurl = http://x\nsecret =\n'))

    def test_notepad_byte_order_mark_is_accepted(self):
        path = self.root / 'agent.ini'
        path.write_bytes(f'[erp]\nurl = http://x\nsecret = {SECRET}\n'.encode('utf-8-sig'))
        self.assertEqual(load_config(path).erp_url, 'http://x')

    def test_malformed_file_error_does_not_quote_the_secret(self):
        with self.assertRaises(ValueError) as caught:
            load_config(self.write_ini(f'secret = {SECRET}\n[erp]\nurl = http://x\n'))
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_missing_file_is_refused(self):
        with self.assertRaises(ValueError):
            load_config(self.root / 'nothing.ini')

    def test_example_file_parses_and_holds_no_real_values(self):
        example = Path(collector.__file__).parent / 'agent.ini.example'
        config = load_config(example)
        self.assertTrue(config.erp_url.startswith('http://192.0.2.'))  # documentation range
        self.assertEqual(config.secret, 'paste-the-agent-secret-here')
        self.assertEqual(config.comm_keys, {})

    def test_comm_key_reaches_only_its_own_machine(self):
        factory = collector.make_client_factory({'SN1': COMM_KEY})
        with mock.patch.object(collector, 'ZkClient') as client:
            factory(device('SN1'))
            factory(device('SN2'))
        self.assertEqual(client.call_args_list[0].kwargs['comm_key'], COMM_KEY)
        self.assertIsNone(client.call_args_list[1].kwargs['comm_key'])


class RunForeverTests(TempDirTestCase):
    def config(self):
        path = self.root / 'agent.ini'
        path.write_text(
            f'[erp]\nurl = http://127.0.0.1:9\nsecret = {SECRET}\n'
            f'[agent]\nstate_dir = {self.root / "state"}\n',
            encoding='utf-8',
        )
        return load_config(path)

    def test_polls_every_sixty_seconds_and_survives_a_crash(self):
        loop = mock.Mock()
        loop.tick.side_effect = [RuntimeError(f'boom {SECRET}'), None, None]
        with mock.patch.object(collector, '_build_loop', return_value=loop), \
                mock.patch.object(collector.time, 'sleep',
                                  side_effect=[None, None, KeyboardInterrupt]) as sleep, \
                self.assertLogs('attendance_agent', level='ERROR') as captured, \
                self.assertRaises(KeyboardInterrupt):
            run_forever(self.config())
        self.assertEqual(loop.tick.call_count, 3)
        sleep.assert_called_with(60)
        self.assertNotIn(SECRET, '\n'.join(captured.output))

    def test_failure_building_the_loop_is_retried_and_logged(self):
        loop = mock.Mock()
        with mock.patch.object(collector, '_build_loop', side_effect=[OSError('locked'), loop]), \
                mock.patch.object(collector.time, 'sleep', side_effect=[None, KeyboardInterrupt]), \
                self.assertLogs('attendance_agent', level='ERROR'), \
                self.assertRaises(KeyboardInterrupt):
            run_forever(self.config())
        loop.tick.assert_called_once()

    def test_main_runs_the_loop_from_an_ini_path(self):
        path = self.config()
        with mock.patch.object(agent_main, 'load_config', return_value=path) as load, \
                mock.patch.object(agent_main, 'configure_logging'), \
                mock.patch.object(agent_main, 'run_forever') as forever:
            agent_main.main(['some.ini'])
        load.assert_called_once_with('some.ini')
        forever.assert_called_once_with(path)

    def test_main_once_runs_a_single_pass(self):
        path = self.config()
        with mock.patch.object(agent_main, 'load_config', return_value=path), \
                mock.patch.object(agent_main, 'configure_logging'), \
                mock.patch.object(agent_main, 'run_forever') as forever, \
                mock.patch.object(agent_main, 'run_once') as once:
            agent_main.main(['some.ini', '--once'])
        once.assert_called_once_with(path, serial=None)
        forever.assert_not_called()

    def test_main_once_can_target_one_machine(self):
        path = self.config()
        with mock.patch.object(agent_main, 'load_config', return_value=path), \
                mock.patch.object(agent_main, 'configure_logging'), \
                mock.patch.object(agent_main, 'run_once') as once:
            agent_main.main(['some.ini', '--once', '--serial', 'SN1'])
        once.assert_called_once_with(path, serial='SN1')

    def test_serial_without_once_is_refused(self):
        with mock.patch('sys.stderr'), self.assertRaises(SystemExit):
            agent_main.main(['some.ini', '--serial', 'SN1'])

    def test_main_reports_a_bad_settings_file_without_the_secret(self):
        path = self.root / 'bad.ini'
        path.write_text(f'secret = {SECRET}\n', encoding='utf-8')
        with mock.patch('sys.stderr') as stderr:
            self.assertEqual(agent_main.main([str(path)]), 2)
        written = ''.join(str(call) for call in stderr.mock_calls)
        self.assertNotIn(SECRET, written)

    def test_real_factory_never_logs_the_comm_key(self):
        with self.assertLogs('attendance_agent', level='DEBUG') as captured:
            logging.getLogger('attendance_agent').debug('start')
            collect_device(
                device(), collector.make_client_factory({'SN1': 'not-a-number'}),
                self.spool, lambda: NOW,
            )
        self.assertNotIn('not-a-number', '\n'.join(captured.output))
        run = self.spool.read(self.spool.pending()[0])[1]
        self.assertEqual(run['status'], 'failed')

    def test_log_file_rotates(self):
        config = self.config()
        logger = logging.getLogger('attendance_agent')
        before = list(logger.handlers)
        self.addCleanup(lambda: setattr(logger, 'handlers', before))
        collector.configure_logging(config)
        added = [h for h in logger.handlers if h not in before]
        self.addCleanup(lambda: [h.close() for h in added])
        self.assertEqual(type(added[0]).__name__, 'RotatingFileHandler')
        self.assertGreater(added[0].maxBytes, 0)
        self.assertGreater(added[0].backupCount, 0)
