"""Read-only reader for the Linked Gates HR portal (SQL Server) and its upload loop.

Linked Gates is a second source of fingerprint punches. This module can only SELECT:
every statement is one of ALLOWED_QUERIES, and `_run` is the single place SQL runs, so
no caller-supplied SQL ever reaches the database. The portal's private columns (pay,
phone, email, photo, passwords, user and permission tables) are never named here.

Logs hold counts only, never enroll numbers, names, connection strings or passwords.
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from .uploader import UploadError

logger = logging.getLogger('attendance_agent')

BATCH_LIMIT = 5000           # the TOP in the punch queries
MAX_BATCHES_PER_TICK = 200   # a safety stop; the next tick carries on
REREAD_DAYS = 45             # the nightly re-read covers this many days back
MIN_RUN_GAP_SECONDS = 900    # one pass per 15 minutes at most (a collect-now request skips it)
QUERY_TIMEOUT_SECONDS = 60   # a query that runs longer is cancelled; the login has its own 15 s

# The TOP in the two punch queries below is the literal 5000 (= BATCH_LIMIT; a test
# pins them together): the allow-list is plain literals so no SQL is ever built.
ALLOWED_QUERIES = {
    'punches_after': (
        'SELECT TOP 5000 EmployeeCheckID, EnrollNo, INOutMode, CheckTime, DeviceID, '
        'CreatedBy, EditBy, EditOn FROM dbo.EmployeeCheck '
        'WHERE EmployeeCheckID > ? ORDER BY EmployeeCheckID'
    ),
    # Paged by id as well, so a long window is read in batches without a gap.
    'punches_since': (
        'SELECT TOP 5000 EmployeeCheckID, EnrollNo, INOutMode, CheckTime, DeviceID, '
        'CreatedBy, EditBy, EditOn FROM dbo.EmployeeCheck '
        'WHERE CheckTime >= ? AND EmployeeCheckID > ? ORDER BY EmployeeCheckID'
    ),
    'devices': 'SELECT DeviceID, DeviceName, IPAddress, Status FROM dbo.Device',
    'employees': (
        'SELECT EmployeeID, EnrollNo, HRCode, EmployeeFirstName, EmployeeLastName, '
        'DepartmentID, ShiftType, IsManager, Status FROM dbo.Employee'
    ),
    'departments': 'SELECT DepartmentID, DepartmentName FROM dbo.Department',
}


def _iso(value):
    """A naive 'YYYY-MM-DDTHH:MM:SS' string (Cairo wall clock, no offset), or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0, tzinfo=None).isoformat()
    return str(value)[:19].replace(' ', 'T')


def _int_or_none(value):
    return None if value is None else int(value)


def _safe_int(value):
    """An int, or None when the portal holds something that isn't one (a reference field only
    informs; it must never make the ERP refuse the whole reference upload)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


_TRUE_TEXT = frozenset({'1', 'true', 't', 'yes', 'y', 'active'})


def _flag(value, default):
    """A real bool for a portal bit/flag column (SQL Server may hand back 0/1, text or NULL)."""
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_TEXT
    return bool(value)


class Batch(list):
    """The usable punches of one read, plus what the read itself saw: `max_id` is the
    highest id in the raw rows (0 when the read was empty) and `skipped` counts rows that
    were left out because EnrollNo or INOutMode was missing or not a number. The cursor
    moves by `max_id`, so a bad row never blocks collection."""

    max_id = 0
    skipped = 0


class LinkedGatesReader:
    def __init__(self, connect):
        self._connect = connect

    def _run(self, name, *params):
        """The only place SQL executes. `name` must be a key of ALLOWED_QUERIES."""
        sql = ALLOWED_QUERIES[name]
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(sql, *params)
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            try:
                connection.close()
            except Exception:  # closing must not hide the real outcome
                pass

    @staticmethod
    def _punch(row):
        return {
            'lg_check_id': int(row['EmployeeCheckID']),
            'enroll_no': int(row['EnrollNo']),
            'in_out_mode': int(row['INOutMode']),
            'check_time': _iso(row['CheckTime']),
            'lg_device_id': _int_or_none(row['DeviceID']),
            'created_by': _int_or_none(row['CreatedBy']),
            'edit_by': _int_or_none(row['EditBy']),
            'edit_on': _iso(row['EditOn']),
        }

    @classmethod
    def _batch(cls, raw):
        batch = Batch()
        for row in raw:
            batch.max_id = max(batch.max_id, int(row['EmployeeCheckID']))
            try:
                batch.append(cls._punch(row))
            except (TypeError, ValueError):
                batch.skipped += 1
        return batch

    def read_new(self, after_id):
        """One batch of punches with an id above `after_id`, oldest id first."""
        return self._batch(self._run('punches_after', after_id))

    def read_since(self, since, after_id=0):
        """One batch of punches checked at or after `since`, with an id above `after_id`."""
        return self._batch(self._run('punches_since', since, after_id))

    def read_reference(self):
        return {
            'devices': [
                {
                    'lg_device_id': int(r['DeviceID']), 'name': r['DeviceName'],
                    'ip': r['IPAddress'], 'status': _flag(r['Status'], True),
                }
                for r in self._run('devices')
            ],
            'employees': [
                {
                    'lg_employee_id': int(r['EmployeeID']),
                    'enroll_no': _int_or_none(r['EnrollNo']), 'hr_code': r['HRCode'],
                    'first_name': r['EmployeeFirstName'], 'last_name': r['EmployeeLastName'],
                    'department_id': _int_or_none(r['DepartmentID']),
                    'shift_type': _safe_int(r['ShiftType']),
                    'is_manager': _flag(r['IsManager'], False),
                    'status': _flag(r['Status'], True),
                }
                for r in self._run('employees')
            ],
            'departments': [
                {'department_id': int(r['DepartmentID']), 'name': r['DepartmentName']}
                for r in self._run('departments')
            ],
        }


def make_lg_connect(lg):
    """A function that opens a read-only connection to Linked Gates. pyodbc is imported
    here, so an agent without [linkedgates] never needs it. Nothing about the connection
    (server, user, password) is logged."""
    def wrap(value):
        return '{' + value.replace('}', '}}') + '}'   # a ';' or '}' in a value stays inside

    parts = [
        'DRIVER={ODBC Driver 18 for SQL Server}', f"SERVER={wrap(lg['server'])}",
        f"DATABASE={wrap(lg['database'])}", 'Encrypt=no',
    ]
    parts += (['Trusted_Connection=yes'] if lg['trusted']
              else [f"UID={wrap(lg['user'])}", f"PWD={wrap(lg['password'])}"])
    connection_string = ';'.join(parts)

    def connect():
        import pyodbc  # lazy: only an agent with [linkedgates] needs it
        connection = pyodbc.connect(connection_string, readonly=True, timeout=15)
        connection.timeout = QUERY_TIMEOUT_SECONDS   # `timeout=` above covers the login only
        return connection
    return connect


class LinkedGatesSync:
    """Reads new Linked Gates punches and sends them. The cursor file moves forward only
    after the ERP has accepted a batch, so a failed send is read again from the same place."""

    def __init__(self, reader, state_path, now, first_load_from=None, clock=time.monotonic):
        self._reader = reader
        self._state_path = Path(state_path)
        self._now = now
        self._first_load_from = first_load_from  # a datetime, or None for the 1st of last month
        self._clock = clock
        self._last_run = None    # clock value of the last pass; None = none yet

    def _load(self):
        try:
            with open(self._state_path, encoding='utf-8') as handle:
                state = json.load(handle)
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, state):
        temporary = self._state_path.with_name(f'{self._state_path.name}.tmp')
        with open(temporary, 'w', encoding='utf-8') as handle:
            json.dump(state, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._state_path)

    def run(self, uploader, force=False) -> None:
        """One pass, at most once per MIN_RUN_GAP_SECONDS unless `force` (a collect-now
        request). Never raises: a failure is logged (class name only) and the next pass tries
        again from the saved cursor."""
        clock = self._clock()
        if not force and self._last_run is not None and clock - self._last_run < MIN_RUN_GAP_SECONDS:
            return
        self._last_run = clock
        try:
            state = self._load()
            today = self._now().date().isoformat()
            self._reference(uploader, state, today)
            self._incremental(uploader, state)
            if str(state.get('last_full_reread', ''))[:10] != today:
                self._reread(uploader, state, today)
        except UploadError as exc:
            logger.warning('linked gates: upload stopped: %s', exc)
        except Exception as exc:  # a SQL Server or disk problem must not stop the ZK work
            logger.warning('linked gates: pass failed: %s', type(exc).__name__)

    def _reference(self, uploader, state, today):
        """Devices, employees and departments, once a day. A read failure or a refusal by the
        ERP is logged and must not stop the punches. An ERP that can't be reached still stops
        the pass, because the punches can't go either."""
        if state.get('last_reference') == today:
            return
        try:
            reference = self._reader.read_reference()
        except Exception as exc:
            logger.warning('linked gates: reference not read: %s', type(exc).__name__)
            return
        try:
            uploader.send('lg_reference', reference)
        except UploadError as exc:
            if not exc.permanent:
                raise                  # the ERP or the network is down: the pass stops, as for punches
            # The ERP answered and refused this reference. The punches must still go, and the same
            # refusal must not repeat every tick: the attempt counts as today's.
            logger.warning('linked gates: reference refused: %s', type(exc).__name__)
            state['last_reference'] = today
            self._save(state)
            return
        state['last_reference'] = today
        self._save(state)
        logger.info('linked gates: reference data sent')

    def _first_load_since(self):
        if self._first_load_from:
            return self._first_load_from
        first_of_month = self._now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return (first_of_month - timedelta(days=1)).replace(day=1)

    def _incremental(self, uploader, state):
        first_load = 'last_check_id' not in state
        cursor = int(state.get('last_check_id', 0))
        since = self._first_load_since()
        sent = skipped = batches = 0
        while batches < MAX_BATCHES_PER_TICK:
            rows = (
                self._reader.read_since(since, cursor) if first_load
                else self._reader.read_new(cursor)
            )
            if not rows.max_id:
                break
            if rows:
                uploader.send('lg_punches', {'rows': list(rows), 'reread': False})
            cursor = max(cursor, rows.max_id)
            state['last_check_id'] = cursor
            self._save(state)
            sent += len(rows)
            skipped += rows.skipped
            batches += 1
        else:
            logger.info('linked gates: batch limit reached, the rest follows next pass')
            return
        if first_load and 'last_check_id' in state:
            # The first load is done, and it covered the re-read window: not sent twice today.
            state['last_full_reread'] = self._now().replace(microsecond=0).isoformat()
            self._save(state)
        if skipped:
            logger.warning('linked gates: %d rows skipped, not usable punches', skipped)
        if sent:
            logger.info('linked gates: %d punches sent in %d batches', sent, batches)

    def _reread(self, uploader, state, today):
        """Once per calendar day: read the last 45 days again, so a punch edited or added
        late in the portal reaches the ERP. The cursor is not touched."""
        since = self._now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=REREAD_DAYS
        )
        since_text = since.replace(microsecond=0).isoformat()
        after = sent = batches = 0
        while batches < MAX_BATCHES_PER_TICK:
            rows = self._reader.read_since(since, after)
            # Adjacent windows share an edge (this batch's to_id is the next one's from_id), and
            # the empty final batch has no upper bound, so rows deleted at a batch edge or after
            # the last batch are still seen by the ERP.
            window = {'from_id': after, 'to_id': rows.max_id or None, 'since': since_text}
            uploader.send('lg_punches', {'rows': list(rows), 'reread': True, 'window': window})
            if not rows.max_id:
                break
            after = rows.max_id
            sent += len(rows)
            batches += 1
        else:
            logger.info('linked gates: re-read limit reached, it restarts next pass')
            return
        state['last_full_reread'] = self._now().replace(microsecond=0).isoformat()
        self._save(state)
        logger.info('linked gates: re-read of %d days sent %d punches', REREAD_DAYS, sent)
