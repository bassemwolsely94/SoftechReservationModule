"""Task 3: the agent's read-only Linked Gates reader.

No SQL Server and no pyodbc: the connection is a fake that hands back canned rows.
"""
import inspect
import json
import logging
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from attendance_agent import collector, lg_reader
from attendance_agent.collector import AgentLoop, load_config
from attendance_agent.lg_reader import ALLOWED_QUERIES, LinkedGatesReader, LinkedGatesSync
from attendance_agent.uploader import UploadError

NOW = datetime(2026, 11, 20, 10, 0, 0)
PUNCH_COLUMNS = [
    'EmployeeCheckID', 'EnrollNo', 'INOutMode', 'CheckTime', 'DeviceID', 'CreatedBy',
    'EditBy', 'EditOn',
]


def punch_row(check_id):
    return (check_id, 7000 + check_id % 50, 0, datetime(2026, 11, 19, 8, 30, 15, 999),
            3, None, None, None)


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self._rows = []

    def execute(self, sql, *params):
        self.conn.executed.append((sql, params))
        name = next(n for n, q in ALLOWED_QUERIES.items() if q == sql)
        self.description = [(c,) for c in self.conn.columns[name]]
        self._rows = self.conn.answer(name, params)

    def fetchall(self):
        return self._rows


class FakeConnection:
    columns = {
        'punches_after': PUNCH_COLUMNS, 'punches_since': PUNCH_COLUMNS,
        'devices': ['DeviceID', 'DeviceName', 'IPAddress', 'Status'],
        'employees': ['EmployeeID', 'EnrollNo', 'HRCode', 'EmployeeFirstName',
                      'EmployeeLastName', 'DepartmentID', 'ShiftType', 'IsManager', 'Status'],
        'departments': ['DepartmentID', 'DepartmentName'],
    }

    def __init__(self, answer, executed):
        self.answer = answer
        self.executed = executed
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


class FakeDatabase:
    """Rows 1..total, served in pages like the real TOP query."""

    def __init__(self, total=0, page=5000, bad_ids=()):
        self.bad_ids = set(bad_ids)
        self.total = total
        self.page = page
        self.executed = []

    def connect(self):
        return FakeConnection(self.answer, self.executed)

    def answer(self, name, params):
        if name in ('punches_after', 'punches_since'):
            after = params[-1]
            ids = [i for i in range(after + 1, self.total + 1)][:self.page]
            return [punch_row(i) if i not in self.bad_ids
                    else (i, None, 'x', None, 3, None, None, None) for i in ids]
        if name == 'devices':
            return [(3, 'Gate 1', '10.0.0.5', 1)]
        if name == 'employees':
            return [(11, 7001, 'H-11', 'Sami', 'Samer', 2, 1, 0, 1)]
        return [(2, 'Sales')]

    def reader(self):
        return LinkedGatesReader(self.connect)


class FakeUploader:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.attempts = 0
        self.sent = []

    def send(self, kind, payload):
        attempt = self.attempts
        self.attempts += 1
        if self.fail_on == attempt:
            raise UploadError('HTTP 500')
        self.sent.append((kind, payload))

    def of(self, kind):
        return [p for k, p in self.sent if k == kind]


class TempTestCase(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.state = self.root / 'lg_cursor.json'

    def sync(self, db, now=lambda: NOW, first_load_from=None):
        return LinkedGatesSync(db.reader(), self.state, now, first_load_from)

    def cursor(self):
        return json.loads(self.state.read_text())


class SqlSafetyTests(SimpleTestCase):
    KEYWORDS = ['INSERT', 'UPDATE', 'DELETE', 'EXEC', 'MERGE', 'DROP', 'ALTER', 'CREATE']
    PRIVATE = ['Salary', 'Phone', 'Email', 'EmployeeImage', 'Password', 'Users',
               'UserPermissions']

    def test_only_allowed_sql(self):
        self.assertTrue(ALLOWED_QUERIES)
        for name, sql in ALLOWED_QUERIES.items():
            self.assertTrue(sql.lstrip().upper().startswith('SELECT'), name)
            self.assertNotIn(';', sql, name)
            for word in self.KEYWORDS:
                self.assertIsNone(
                    re.search(rf'\b{word}\b', sql, re.IGNORECASE), f'{name} contains {word}',
                )
            for word in self.PRIVATE:
                self.assertNotIn(word.lower(), sql.lower(), f'{name} names {word}')

    def test_no_other_execute(self):
        source = inspect.getsource(lg_reader)
        self.assertEqual(source.count('.execute('), 1)
        run_source = inspect.getsource(LinkedGatesReader._run)
        self.assertEqual(run_source.count('.execute('), 1)

    def test_run_refuses_sql_that_is_not_listed(self):
        db = FakeDatabase()
        with self.assertRaises(KeyError):
            db.reader()._run('DELETE FROM dbo.EmployeeCheck')
        self.assertEqual(db.executed, [])

    def test_connection_is_closed_after_each_read(self):
        db = FakeDatabase(total=2)
        opened = []
        reader = LinkedGatesReader(lambda: opened.append(db.connect()) or opened[-1])
        reader.read_new(0)
        self.assertTrue(opened[0].closed)


class ReaderTests(SimpleTestCase):
    def test_punch_rows_use_the_agreed_keys_and_naive_seconds(self):
        row = FakeDatabase(total=1).reader().read_new(0)[0]
        self.assertEqual(set(row), {
            'lg_check_id', 'enroll_no', 'in_out_mode', 'check_time', 'lg_device_id',
            'created_by', 'edit_by', 'edit_on',
        })
        self.assertEqual(row['check_time'], '2026-11-19T08:30:15')
        self.assertIsNone(row['edit_on'])

    def test_reference_keys(self):
        ref = FakeDatabase().reader().read_reference()
        self.assertEqual(set(ref), {'devices', 'employees', 'departments'})
        self.assertEqual(set(ref['devices'][0]), {'lg_device_id', 'name', 'ip', 'status'})
        self.assertEqual(set(ref['employees'][0]), {
            'lg_employee_id', 'enroll_no', 'hr_code', 'first_name', 'last_name',
            'department_id', 'shift_type', 'is_manager', 'status',
        })
        self.assertEqual(ref['departments'], [{'department_id': 2, 'name': 'Sales'}])


class SyncTests(TempTestCase):
    def test_incremental_batches(self):
        db = FakeDatabase(total=6200)
        uploader = FakeUploader()
        self.sync(db).run(uploader)
        punches = uploader.of('lg_punches')
        live = [p for p in punches if not p['reread']]
        self.assertEqual([len(p['rows']) for p in live], [5000, 1200])
        # first load pages 5000, 1200, then an empty read: three reads before the re-read
        self.assertEqual(self.cursor()['last_check_id'], 6200)
        reads = [e for e in db.executed if e[1] and isinstance(e[1][-1], int)]
        self.assertGreaterEqual(len(reads), 3)
        # the next pass reads only what is newer
        db.total = 6203
        uploader2 = FakeUploader()
        self.sync(db).run(uploader2)
        self.assertEqual(
            [r['lg_check_id'] for p in uploader2.of('lg_punches') if not p['reread']
             for r in p['rows']], [6201, 6202, 6203],
        )
        self.assertEqual(self.cursor()['last_check_id'], 6203)

    def test_first_load_defaults_to_the_first_of_last_month(self):
        db = FakeDatabase(total=3)
        self.sync(db).run(FakeUploader())
        first = [e for e in db.executed if e[0] == ALLOWED_QUERIES['punches_since']][0]
        self.assertEqual(first[1][0], datetime(2026, 10, 1))
        db2 = FakeDatabase(total=3)
        LinkedGatesSync(
            db2.reader(), self.root / 'b.json', lambda: datetime(2027, 1, 5, 9),
        ).run(FakeUploader())
        since = [e for e in db2.executed if e[0] == ALLOWED_QUERIES['punches_since']][0]
        self.assertEqual(since[1][0], datetime(2026, 12, 1))

    def test_empty_first_load_keeps_first_load_state(self):
        db = FakeDatabase(total=0)
        self.sync(db).run(FakeUploader())
        self.assertNotIn('last_check_id', self.cursor())
        db.total = 4
        db.executed.clear()
        self.sync(db).run(FakeUploader())
        queries = [e[0] for e in db.executed]
        self.assertIn(ALLOWED_QUERIES['punches_since'], queries)
        self.assertNotIn(ALLOWED_QUERIES['punches_after'], queries)
        since = [e for e in db.executed if e[0] == ALLOWED_QUERIES['punches_since']][0]
        self.assertEqual(since[1][0], datetime(2026, 10, 1))
        self.assertEqual(self.cursor()['last_check_id'], 4)

    def test_first_load_marks_today_as_reread(self):
        db = FakeDatabase(total=5)
        uploader = FakeUploader()
        self.sync(db).run(uploader)
        self.assertEqual([p for p in uploader.of('lg_punches') if p['reread']], [])
        self.assertEqual(self.cursor()['last_full_reread'][:10], '2026-11-20')

    def test_bad_rows_are_skipped_and_the_cursor_passes_them(self):
        db = FakeDatabase(total=5, bad_ids={5})
        uploader = FakeUploader()
        with self.assertLogs('attendance_agent', level=logging.INFO) as captured:
            self.sync(db).run(uploader)
        sent = [r['lg_check_id'] for p in uploader.of('lg_punches') for r in p['rows']]
        self.assertEqual(sent, [1, 2, 3, 4])
        self.assertEqual(self.cursor()['last_check_id'], 5)
        self.assertIn('1 rows skipped', ' '.join(captured.output))

    def test_a_batch_of_only_bad_rows_still_moves_the_cursor(self):
        db = FakeDatabase(total=3, bad_ids={1, 2, 3})
        uploader = FakeUploader()
        self.sync(db).run(uploader)
        self.assertEqual(uploader.of('lg_punches'), [])
        self.assertEqual(self.cursor()['last_check_id'], 3)

    def test_reference_failure_does_not_stop_punches(self):
        db = FakeDatabase(total=3)
        reader = db.reader()

        def broken():
            raise RuntimeError('Server=SECRET')
        reader.read_reference = broken
        uploader = FakeUploader()
        with self.assertLogs('attendance_agent', level='WARNING') as captured:
            LinkedGatesSync(reader, self.state, lambda: NOW).run(uploader)
        self.assertEqual(uploader.of('lg_reference'), [])
        self.assertTrue(uploader.of('lg_punches'))
        self.assertIn('RuntimeError', ' '.join(captured.output))
        self.assertNotIn('SECRET', ' '.join(captured.output))

    def test_connection_string_wraps_values(self):
        seen = []

        def fake_connect(connection_string, **kwargs):
            seen.append(connection_string)
            return object()
        fake = mock.Mock(connect=fake_connect)
        with mock.patch.dict('sys.modules', {'pyodbc': fake}):
            lg_reader.make_lg_connect({
                'server': r'.\SQL;EXPRESS', 'database': 'd}x', 'trusted': False,
                'user': 'u', 'password': 'p};q',
            })()
        self.assertIn(r'SERVER={.\SQL;EXPRESS}', seen[0])
        self.assertIn('DATABASE={d}}x}', seen[0])
        self.assertIn('PWD={p}};q}', seen[0])

    def test_three_reads_after_the_first_load(self):
        db = FakeDatabase(total=6200)
        self.sync(db).run(FakeUploader())
        db.executed.clear()
        db.total = 12400
        uploader = FakeUploader()
        self.sync(db).run(uploader)
        incremental = [e for e in db.executed if e[0] == ALLOWED_QUERIES['punches_after']]
        self.assertEqual(len(incremental), 3)  # 5000, 1200, then none
        self.assertEqual(self.cursor()['last_check_id'], 12400)

    def test_resume_after_failed_batch(self):
        db = FakeDatabase(total=6200)
        # sends: 0 reference, 1 first batch, 2 second batch (fails)
        failing = FakeUploader(fail_on=2)
        self.sync(db).run(failing)
        self.assertEqual(self.cursor()['last_check_id'], 5000)
        ok = FakeUploader()
        self.sync(db).run(ok)
        live = [p for p in ok.of('lg_punches') if not p['reread']]
        self.assertEqual(live[0]['rows'][0]['lg_check_id'], 5001)
        self.assertEqual(self.cursor()['last_check_id'], 6200)

    def test_reference_is_sent_once_per_day(self):
        db = FakeDatabase(total=3)
        first, second = FakeUploader(), FakeUploader()
        self.sync(db).run(first)
        self.sync(db).run(second)
        self.assertEqual(len(first.of('lg_reference')), 1)
        self.assertEqual(second.of('lg_reference'), [])
        third = FakeUploader()
        self.sync(db, now=lambda: NOW + timedelta(days=1)).run(third)
        self.assertEqual(len(third.of('lg_reference')), 1)

    def test_nightly_reread_once_per_day(self):
        db = FakeDatabase(total=10)
        first = FakeUploader()
        self.sync(db).run(first)  # day one: the first load already covered the window
        self.assertEqual([p for p in first.of('lg_punches') if p['reread']], [])

        again = FakeUploader()
        self.sync(db, now=lambda: NOW + timedelta(hours=3)).run(again)
        self.assertEqual([p for p in again.of('lg_punches') if p['reread']], [])

        tomorrow = FakeUploader()
        later = NOW + timedelta(days=1)
        self.sync(db, now=lambda: later).run(tomorrow)
        rereads = [p for p in tomorrow.of('lg_punches') if p['reread']]
        # the data batch, then an empty final batch with no upper bound (trailing deletions)
        self.assertEqual(len(rereads), 2)
        self.assertEqual(len(rereads[0]['rows']), 10)
        since_text = '2026-10-07T00:00:00'
        self.assertEqual(rereads[0]['window'], {'from_id': 0, 'to_id': 10, 'since': since_text})
        self.assertEqual(rereads[1]['rows'], [])
        self.assertEqual(rereads[1]['window'], {'from_id': 10, 'to_id': None, 'since': since_text})
        since = [e[1][0] for e in db.executed if 'CheckTime >= ?' in e[0]][-1]
        self.assertEqual(since, datetime(2026, 11, 21) - timedelta(days=45))

        same_day = FakeUploader()
        self.sync(db, now=lambda: later + timedelta(hours=2)).run(same_day)
        self.assertEqual([p for p in same_day.of('lg_punches') if p['reread']], [])

    def test_reread_does_not_move_the_cursor(self):
        db = FakeDatabase(total=10)
        self.sync(db).run(FakeUploader())
        state = self.cursor()
        self.assertEqual(state['last_check_id'], 10)
        self.assertIn('last_full_reread', state)

    def test_sql_failure_is_contained_and_logged_by_class_only(self):
        def boom():
            raise RuntimeError('Server=SECRETHOST;PWD=hunter2')
        sync = LinkedGatesSync(LinkedGatesReader(boom), self.state, lambda: NOW)
        with self.assertLogs('attendance_agent', level='WARNING') as captured:
            sync.run(FakeUploader())
        text = ' '.join(captured.output)
        self.assertIn('RuntimeError', text)
        self.assertNotIn('SECRETHOST', text)
        self.assertNotIn('hunter2', text)

    def test_logs_have_no_codes(self):
        db = FakeDatabase(total=12)
        with self.assertLogs('attendance_agent', level=logging.INFO) as captured:
            self.sync(db).run(FakeUploader())
        text = ' '.join(captured.output)
        self.assertIn('12 punches', text)
        for secret in ('7001', 'Sami', 'Samer', 'H-11', 'Gate 1', '10.0.0.5', 'Linked_ERP'):
            self.assertNotIn(secret, text)


class ConfigAndLoopTests(TempTestCase):
    def ini(self, extra=''):
        path = self.root / 'agent.ini'
        path.write_text(
            '[erp]\nurl = http://127.0.0.1:8000\nsecret = s\n' + extra, encoding='utf-8')
        return path

    def test_no_section_means_no_linked_gates(self):
        self.assertIsNone(load_config(self.ini()).linkedgates)

    def test_section_is_read(self):
        lg = load_config(self.ini(
            '[linkedgates]\nserver = .\\SQLEXPRESS\ndatabase = Linked_ERP_HR_v1\n'
            'trusted = yes\nfirst_load_from = 2026-10-01\n')).linkedgates
        self.assertEqual(lg['server'], '.\\SQLEXPRESS')
        self.assertTrue(lg['trusted'])
        self.assertEqual(lg['first_load_from'], datetime(2026, 10, 1))

    def test_section_needs_server_and_database(self):
        with self.assertRaises(ValueError):
            load_config(self.ini('[linkedgates]\nserver = x\n'))

    def test_connect_factory_needs_no_pyodbc_until_called(self):
        connect = lg_reader.make_lg_connect(
            {'server': 's', 'database': 'd', 'trusted': True, 'user': '', 'password': ''})
        self.assertTrue(callable(connect))

    def test_loop_runs_the_reader_only_when_the_erp_says_so(self):
        class Spy:
            calls = 0

            def run(self, uploader):
                Spy.calls += 1

        class Up:
            def __init__(self, flag):
                self.flag = flag

            def get_config(self):
                config = {'agent': 'a', 'collect_now': False, 'devices': []}
                if self.flag is not None:
                    config['linkedgates'] = self.flag
                return config

            def send(self, kind, payload):
                pass

        from attendance_agent.spool import Spool
        for flag, expected in ((True, 1), (False, 0), (None, 0)):
            Spy.calls = 0
            loop = AgentLoop(
                uploader=Up(flag), spool=Spool(self.root / f'sp{flag}'),
                client_factory=None, now=lambda: NOW, clock=lambda: 0,
                cache_path=self.root / 'devices.json', lg_sync=Spy(),
            )
            loop.tick()
            self.assertEqual(Spy.calls, expected, flag)
        # and never when the ini has no section
        Spy.calls = 0
        AgentLoop(
            uploader=Up(True), spool=Spool(self.root / 'sp'), client_factory=None,
            now=lambda: NOW, clock=lambda: 0, cache_path=self.root / 'devices.json',
        ).tick()
        self.assertEqual(Spy.calls, 0)
