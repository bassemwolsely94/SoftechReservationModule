"""Collection loop: read each machine, spool to disk, send to the ERP.

Logs hold counts and machine serials only, never names, user codes or secrets.
"""
import configparser
import json
import logging
import logging.handlers
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .spool import Spool
from .uploader import Uploader, UploadError
from .zk_client import ZkClient, ZkError, ZkProtocolError

logger = logging.getLogger('attendance_agent')

BATCH_SIZE = 2000  # the ERP refuses more than this per request
POLL_SECONDS = 60
COLLECT_EVERY_SECONDS = 3600
# While the agent runs, no machine is read more often than this, however often it's asked
# or a read fails. These are old machines, and the ZK program may be connected at the same
# time. Measured from the end of the last read.
MIN_READ_GAP_SECONDS = 300
DRAIN_BUDGET_SECONDS = 300  # a long backlog must not keep machines waiting
REFUSED_RETRY_SECONDS = 900  # a file the ERP refused waits, so newer files go first
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 5


class SerialMismatch(ZkError):
    """The address answered as another machine."""


@dataclass
class AgentConfig:
    erp_url: str
    secret: str = field(repr=False)
    state_dir: Path = None
    comm_keys: dict = field(default_factory=dict, repr=False)


def load_config(path) -> AgentConfig:
    # No interpolation, because a secret may hold '%'. Keys keep their case, because
    # comm keys are listed by machine serial. utf-8-sig, because Notepad can add a BOM.
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        found = parser.read(path, encoding='utf-8-sig')
    except configparser.Error:
        # configparser's message quotes the bad line, which may be the secret.
        raise ValueError('the settings file is malformed') from None
    if not found:
        raise ValueError('cannot read the settings file')
    erp_url = parser.get('erp', 'url', fallback='').strip()
    secret = parser.get('erp', 'secret', fallback='').strip()
    if not erp_url or not secret:
        raise ValueError('the settings file needs [erp] url and secret')
    state_dir = parser.get('agent', 'state_dir', fallback='').strip()
    comm_keys = dict(parser['comm_keys']) if parser.has_section('comm_keys') else {}
    return AgentConfig(
        erp_url=erp_url,
        secret=secret,
        state_dir=Path(state_dir) if state_dir else Path(path).parent / 'agent_state',
        comm_keys=comm_keys,
    )


def configure_logging(config, console=False) -> None:
    config.state_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    handlers = [logging.handlers.RotatingFileHandler(
        config.state_dir / 'agent.log',
        maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding='utf-8',
    )]
    if console:
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def make_client_factory(comm_keys):
    def factory(device):
        return ZkClient(
            device['ip'], device.get('port', 4370),
            comm_key=comm_keys.get(device['serial']),
        )
    return factory


def _safe_error(exc) -> str:
    """Our own messages are safe. Anything else may quote an address or a value, so
    only its class name leaves this machine."""
    if isinstance(exc, (ZkError, UploadError)):
        return str(exc)
    return type(exc).__name__


def _punch_payload(row):
    return {
        'user_code': row.user_code,
        'raw_stamp': row.raw_stamp,
        'date': row.date.isoformat() if row.date else None,
        'time': row.time.isoformat() if row.time else None,
        'state': row.state,
        'verify_mode': row.verify_mode,
    }


def _rows_to_spool(logs, waiting):
    """One row per punch identity, skipping any already waiting on disk.

    The database holds one row per identity, and the ERP's accepted + duplicate must add
    up to what was sent. Each read holds the whole log, so without the `waiting` check an
    outage would store a full copy per hour. Once a file has been delivered its punches
    are sent again by the next read, and the ERP's uniqueness makes that safe.
    """
    seen = set(waiting)
    rows = []
    for row in logs:
        identity = (row.user_code, row.raw_stamp, row.state)
        if identity not in seen:
            seen.add(identity)
            rows.append(row)
    return rows


def _waiting_identities(serial, spool):
    """Punch identities for this machine in files not yet delivered. An unreadable file
    counts for nothing, so its punches are spooled again."""
    waiting = set()
    for path in spool.pending():
        if '-punches-' not in path.name:
            continue
        try:
            _kind, payload = spool.read(path)
            if payload['device_serial'] == serial:
                waiting.update(
                    (p['user_code'], p['raw_stamp'], p['state']) for p in payload['punches']
                )
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return waiting


def _check_serial(client, serial):
    reported = client.read_serial()
    if reported is None:
        logger.warning('device %s: serial not answered, cannot confirm identity', serial)
    elif reported != serial:
        raise SerialMismatch(f'this address answered as machine {reported}')


def _read_drift(client, serial, now):
    """Device clock minus this PC's clock, in seconds. A clock problem shows as a
    missing drift. The log is the evidence, so it must still be collected."""
    try:
        device_time = client.read_time()
    except ZkProtocolError as exc:
        logger.warning('device %s: clock not read: %s', serial, _safe_error(exc))
        return None
    return round((device_time - now()).total_seconds())


def _read_machine(device, client_factory, run, now):
    serial = device['serial']
    with client_factory(device) as client:
        _check_serial(client, serial)
        run['drift_seconds'] = _read_drift(client, serial, now)
        run['device_log_count'] = client.read_sizes().records
        try:
            users = client.read_users()
        except (ZkError, OSError) as exc:
            # The roster is a convenience and the log is the evidence, so one can't
            # block the other.
            run['error'] = f'roster not read: {_safe_error(exc)}'
            logger.warning('device %s: %s', serial, run['error'])
        else:
            return users, client.read_logs()
    # After a failed read the session may be out of step, so use a new connection.
    with client_factory(device) as client:
        _check_serial(client, serial)
        return None, client.read_logs()


def _quarantine_raw_log(exc, serial, spool):
    raw = getattr(exc, 'raw_table', None)
    if raw is None:
        return
    try:
        spool.quarantine(serial, raw)
        logger.error('device %s: undecoded log of %d bytes kept', serial, len(raw))
    except OSError as disk_error:
        logger.error('device %s: could not keep the log: %s', serial, _safe_error(disk_error))


def _spool_results(serial, users, logs, spool, run):
    if users is not None:
        spool.put('roster', {
            'device_serial': serial,
            'users': [
                {'user_code': u.user_code, 'name': u.name, 'is_admin': u.is_admin}
                for u in users
            ],
        })
    rows = _rows_to_spool(logs, _waiting_identities(serial, spool))
    batches = 0
    for start in range(0, len(rows), BATCH_SIZE):
        spool.put('punches', {
            'device_serial': serial,
            'punches': [_punch_payload(r) for r in rows[start:start + BATCH_SIZE]],
        })
        batches += 1
    dates = [row.date for row in logs if row.date]
    run['records_read'] = len(logs)
    run['oldest_date'] = min(dates).isoformat() if dates else None
    run['newest_date'] = max(dates).isoformat() if dates else None
    logger.info(
        'device %s read: %d users, %d records, %d files',
        serial, len(users or ()), len(logs), batches,
    )


def collect_device(device, client_factory, spool, now, collect_done=False) -> None:
    """Read one machine, disconnect, then spool. `now` is called, not a fixed time,
    because earlier machines may have taken minutes and drift must stay accurate.

    A failed read spools only a failed run, so a part-read log is never reported as
    complete. The machine still holds its log for the next run. A failed save raises,
    so the caller can try the machine again soon.
    """
    serial = device['serial']
    run = {
        'device_serial': serial, 'started_at': now().isoformat(), 'finished_at': None,
        'records_read': 0, 'oldest_date': None, 'newest_date': None,
        'drift_seconds': None, 'device_log_count': None, 'status': 'success', 'error': '',
        'spool_waiting': 0,
    }
    if collect_done:
        run['collect_done'] = True
    users = logs = None
    try:
        users, logs = _read_machine(device, client_factory, run, now)
    except Exception as exc:  # any machine failure is reported, and must not stop others
        run['status'] = 'failed'
        run['error'] = _safe_error(exc)
        logger.warning('device %s failed: %s', serial, run['error'])
        _quarantine_raw_log(exc, serial, spool)

    try:
        if logs is not None:
            _spool_results(serial, users, logs, spool, run)
        run['finished_at'] = now().isoformat()
        run['spool_waiting'] = len(spool.pending())
        spool.put('runs', run)
    except OSError as exc:
        run['status'] = 'failed'
        run['error'] = f'could not save to disk: {_safe_error(exc)}'
        run['finished_at'] = now().isoformat()
        try:
            run['spool_waiting'] = len(spool.pending())
            spool.put('runs', run)
        except OSError:
            pass  # the same disk problem; the raise below is what gets logged
        raise


def drain(spool, uploader, budget_seconds=DRAIN_BUDGET_SECONDS, clock=time.monotonic,
          held=None) -> None:
    """Send oldest first. A file is removed only after the ERP has accepted it, and
    resending is safe.

    If the ERP or the network is the problem, stop until the next pass. If the ERP
    refuses one file, or it can't be read, the file stays and waits in `held` (path to
    next try) before being tried again. The rest go on, so one machine's problem can't
    hold back the others.
    """
    held = {} if held is None else held
    started = clock()
    sent = kept = 0
    reason = ''
    stopped = False
    for path in spool.pending():
        now = clock()
        if now - started >= budget_seconds:
            break
        if held.get(path, now) > now:
            continue
        try:
            kind, payload = spool.read(path)
            uploader.send(kind, payload)
            spool.ack(path)
            held.pop(path, None)
            sent += 1
        except UploadError as exc:
            reason = _safe_error(exc)
            if not exc.permanent:
                stopped = True
                break
            held[path] = now + REFUSED_RETRY_SECONDS
            kept += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            reason = _safe_error(exc)
            held[path] = now + REFUSED_RETRY_SECONDS
            kept += 1
    if reason:
        logger.warning(
            'upload: %d sent, %d kept, %d waiting%s: %s',
            sent, kept, len(spool.pending()), ', stopped' if stopped else '', reason,
        )
    elif sent:
        logger.info('upload: %d sent', sent)


def _valid_devices(devices):
    valid = [
        d for d in devices
        if isinstance(d, dict) and d.get('serial') and d.get('ip')
    ]
    if len(valid) != len(devices):
        logger.error('%d machine entries are malformed and skipped', len(devices) - len(valid))
    return valid


class AgentLoop:
    def __init__(self, uploader, spool, client_factory, now, clock, cache_path, only_serial=None):
        self._uploader = uploader
        self._spool = spool
        self._client_factory = client_factory
        self._now = now
        self._clock = clock
        self._cache_path = Path(cache_path)
        self._only_serial = only_serial
        self._last_read = {}
        self._next_due = {}
        self._saved_devices = None
        self._held = {}
        self._collect_done_file = None

    def tick(self) -> None:
        devices, collect_now = self._fetch_config()
        if self._only_serial is not None:
            devices = [d for d in devices if d['serial'] == self._only_serial]
            if not devices:
                logger.error('machine %s is not assigned to this agent', self._only_serial)
        clock = self._clock()
        run_all = self._should_run_all(devices, collect_now, clock)
        targets = devices if run_all else [d for d in devices if self._is_due(d, clock)]
        for index, device in enumerate(targets):
            serial = device['serial']
            try:
                collect_device(
                    device, self._client_factory, self._spool, self._now,
                    collect_done=run_all and index == len(targets) - 1,
                )
                self._next_due[serial] = clock + COLLECT_EVERY_SECONDS
            except Exception as exc:  # e.g. disk full: the next machine still gets its turn
                logger.error('device %s run failed: %s', serial, _safe_error(exc))
                self._next_due[serial] = clock + MIN_READ_GAP_SECONDS
            self._last_read[serial] = self._clock()
        if run_all and targets:
            pending = self._spool.pending()
            self._collect_done_file = pending[-1] if pending else None
        drain(self._spool, self._uploader, clock=self._clock, held=self._held)

    def _should_run_all(self, devices, collect_now, clock):
        """A collect-now request stays set until collect_done reaches the ERP. So once
        this cycle has spooled it, don't read again until that file has gone, and the
        minimum gap covers a run that couldn't even spool it. Reading one machine by
        hand must never answer a request meant for all of them."""
        if not collect_now or self._only_serial is not None:
            return False
        if self._collect_done_file is not None and self._collect_done_file.exists():
            return False
        return all(self._gap_passed(d, clock) for d in devices)

    def _gap_passed(self, device, clock):
        last = self._last_read.get(device['serial'])
        return last is None or clock - last >= MIN_READ_GAP_SECONDS

    def _is_due(self, device, clock):
        due = self._next_due.get(device['serial'])
        return due is None or clock >= due

    def _fetch_config(self):
        try:
            config = self._uploader.get_config()
        except UploadError as exc:
            # The ERP being down must not stop collection, even after a PC restart.
            logger.warning('ERP config unavailable: %s', _safe_error(exc))
            return self._load_devices(), False
        devices = _valid_devices(config['devices'])
        self._save_devices(devices)
        return devices, bool(config.get('collect_now'))

    def _load_devices(self):
        try:
            with open(self._cache_path, encoding='utf-8') as handle:
                devices = json.load(handle)
            return _valid_devices(devices)
        except (OSError, ValueError, TypeError) as exc:
            logger.error('no saved machine list, nothing to collect: %s', _safe_error(exc))
            return []

    def _save_devices(self, devices):
        if devices == self._saved_devices:
            return
        if not devices and self._cache_path.exists():
            # One bad answer must not leave nothing to collect in a later outage.
            logger.warning('the ERP lists no machines; the saved list is kept')
            return
        temporary = self._cache_path.with_name(f'{self._cache_path.name}.tmp')
        try:
            with open(temporary, 'w', encoding='utf-8') as handle:
                json.dump(devices, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._cache_path)
            self._saved_devices = devices
        except OSError as exc:
            logger.warning('could not save the machine list: %s', _safe_error(exc))


def _build_loop(config, only_serial=None):
    config.state_dir.mkdir(parents=True, exist_ok=True)
    return AgentLoop(
        uploader=Uploader(config.erp_url, config.secret),
        spool=Spool(config.state_dir / 'spool'),
        client_factory=make_client_factory(config.comm_keys),
        now=datetime.now,
        clock=time.monotonic,
        cache_path=config.state_dir / 'devices.json',
        only_serial=only_serial,
    )


def run_once(config, serial=None) -> None:
    _build_loop(config, only_serial=serial).tick()


def run_forever(config) -> None:
    loop = None
    while True:
        try:
            # Built here, so a folder that isn't ready at boot is retried, not fatal.
            if loop is None:
                loop = _build_loop(config)
            loop.tick()
        except Exception as exc:  # the agent must outlive any single bad pass
            logger.error('pass failed: %s', _safe_error(exc))
        time.sleep(POLL_SECONDS)
