import datetime as _dt
import os
import pathlib
import threading
import time

import jpype
import jpype.imports
from django.conf import settings
import logging

logger = logging.getLogger('elrezeiky.sync')

JDBC_DRIVER = 'com.sybase.jdbc3.jdbc.SybDriver'

# ── JAR discovery (VPS-safe) ─────────────────────────────────────────────────
# Resolution order:
#   1. SYBASE_JCONN_JAR env var  (explicit override for any deployment)
#   2. <project_root>/libs/jconn3.jar  (bundled — committed to repo)
#   3. Legacy Windows dev-machine path  (backward compat on workstations)
_HERE      = pathlib.Path(__file__).resolve().parent          # config/
_PROJ_ROOT = _HERE.parent                                      # project root
_BUNDLED   = _PROJ_ROOT / 'libs' / 'jconn3.jar'
_LEGACY    = pathlib.Path(r'C:\sybase\jConnect-6_0\classes\jconn3.jar')


def _resolve_jconn_jar() -> str:
    """
    Return the absolute path to jconn3.jar, checking three locations in order.
    Raises FileNotFoundError with a clear message if none exist so the
    developer knows exactly what to fix on a new deployment.
    """
    # 1. Explicit env var (highest priority — set this on VPS if needed)
    env_path = os.environ.get('SYBASE_JCONN_JAR', '').strip()
    if env_path:
        p = pathlib.Path(env_path)
        if p.exists():
            return str(p)
        logger.warning('SYBASE_JCONN_JAR=%s set but file not found — trying fallbacks', env_path)

    # 2. Bundled JAR inside the project repo (works on any OS after git clone)
    if _BUNDLED.exists():
        return str(_BUNDLED)

    # 3. Legacy workstation install path (Windows dev machines with SOFTECH)
    if _LEGACY.exists():
        return str(_LEGACY)

    raise FileNotFoundError(
        'jconn3.jar not found. Checked:\n'
        f'  1. SYBASE_JCONN_JAR env var: {env_path or "(not set)"}\n'
        f'  2. Bundled: {_BUNDLED}\n'
        f'  3. Legacy:  {_LEGACY}\n\n'
        'Fix: copy jconn3.jar to the project\'s libs/ directory, '
        'or set SYBASE_JCONN_JAR=/absolute/path/to/jconn3.jar in your .env'
    )


JCONN_JAR = _resolve_jconn_jar()


# Serialise JVM startup: jpype.startJVM() raises if the JVM is already running,
# so two threads that both pass the isJVMStarted() check and both call startJVM()
# would race — the loser threw "JVM is already started". This surfaced when the
# personal dashboard fires several live-SOFTECH widget queries concurrently on
# first load. The lock + re-check makes first-connection thread-safe.
_JVM_START_LOCK = threading.Lock()


def _ensure_jvm():
    if jpype.isJVMStarted():
        return
    with _JVM_START_LOCK:
        # Re-check inside the lock: another thread may have started it while we
        # were blocked on the lock.
        if jpype.isJVMStarted():
            return
        try:
            jpype.startJVM(
                jpype.getDefaultJVMPath(),
                '-Djava.class.path=' + JCONN_JAR,
                convertStrings=False,
            )
        except Exception:
            # Lost a race we couldn't see (or a benign double-start) — tolerate
            # it as long as the JVM is actually up; otherwise re-raise.
            if not jpype.isJVMStarted():
                raise


# Seconds to wait for the TCP/login handshake before giving up.
# Without this, an unreachable Sybase host (offline branch, VPN down, firewalled
# port) causes driver.connect() to block at the OS level for minutes — which
# hangs APScheduler jobs (max_instances=1 → every later tick is skipped forever).
# Bounding only the LOGIN handshake (not query reads) lets dead hosts fail fast
# and be caught by the caller's try/except, while long-running queries are
# unaffected.
SYBASE_LOGIN_TIMEOUT_SECONDS = int(getattr(settings, 'SYBASE_LOGIN_TIMEOUT', 15))


def _apply_login_timeout(props):
    """Set jConnect LOGIN_TIMEOUT (in seconds) on the connection properties."""
    props.setProperty('LOGIN_TIMEOUT', str(SYBASE_LOGIN_TIMEOUT_SECONDS))


# Max seconds any single query may run before the driver aborts it.  Without
# this, a slow/blocked query (unindexed scan, branch-local docnumber not on HQ,
# a lock) hangs the HTTP request forever.  JDBC Statement.setQueryTimeout makes
# the driver cancel the statement and raise instead.
SYBASE_QUERY_TIMEOUT_SECONDS = int(getattr(settings, 'SYBASE_QUERY_TIMEOUT', 30))


def _apply_query_timeout(stmt, timeout=None):
    """
    Bound a single statement's run time.

    NOTE: jConnect implements setQueryTimeout by arming a SOCKET read timeout,
    so when it fires it surfaces as `JZ0T3: Read operation timed out` during
    fetch — NOT as a query-cancelled error. The default (30s) is tuned for
    interactive HTTP requests; heavy background jobs (the full sync's stktrans
    scan) must pass a larger `timeout` or they get killed mid-fetchall().

    `timeout` (seconds) overrides the global default for this statement only.
    """
    secs = SYBASE_QUERY_TIMEOUT_SECONDS if timeout is None else int(timeout)
    try:
        stmt.setQueryTimeout(secs)
    except Exception:
        pass  # not all drivers honor it; LOGIN_TIMEOUT still bounds connect


# Branch Sybase servers reach HQ over an intermittent VPN/link, so driver.connect()
# fails transiently ~half the time and then succeeds on a retry. Bound, short-backoff
# retries smooth that over without masking a genuinely-down host (each attempt is still
# capped by LOGIN_TIMEOUT). Tunable via settings.
SYBASE_CONNECT_ATTEMPTS    = int(getattr(settings, 'SYBASE_CONNECT_ATTEMPTS', 3))
SYBASE_CONNECT_RETRY_DELAY = float(getattr(settings, 'SYBASE_CONNECT_RETRY_DELAY', 1.5))


def _connect_with_retry(driver, jdbc_url, props, label=''):
    """driver.connect() with bounded retries for the flaky branch link."""
    last_exc = None
    for attempt in range(1, SYBASE_CONNECT_ATTEMPTS + 1):
        try:
            return driver.connect(jdbc_url, props)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                '[sybase] connect attempt %d/%d failed%s: %s',
                attempt, SYBASE_CONNECT_ATTEMPTS,
                f' [{label}]' if label else '', str(exc)[:120],
            )
            if attempt < SYBASE_CONNECT_ATTEMPTS:
                time.sleep(SYBASE_CONNECT_RETRY_DELAY)
    raise last_exc


def get_sybase_connection(charset=None):
    host = settings.SYBASE_HOST
    port = getattr(settings, 'SYBASE_PORT', '5000')
    user = settings.SYBASE_USER
    password = settings.SYBASE_PASSWORD
    _ensure_jvm()
    jpype.imports.registerDomain('com')
    from com.sybase.jdbc3.jdbc import SybDriver
    from java.util import Properties
    from java.sql import DriverManager
    props = Properties()
    props.setProperty('user', user)
    props.setProperty('password', password)
    # Opt-in connection charset (e.g. 'cp1256') so Arabic writes encode correctly.
    # Default (None) is unchanged — used only by the writeback path.
    if charset:
        props.setProperty('CHARSET', charset)
    _apply_login_timeout(props)
    # Belt-and-suspenders: also bound the timeout at the DriverManager level.
    try:
        DriverManager.setLoginTimeout(SYBASE_LOGIN_TIMEOUT_SECONDS)
    except Exception:
        pass
    jdbc_url = 'jdbc:sybase:Tds:' + host + ':' + str(port) + '/SOFTECHDB9'
    driver = SybDriver()
    return ConnectionWrapper(_connect_with_retry(driver, jdbc_url, props, label='HQ'))


def get_branch_connection(db_host, db_port=5000, db_name='SOFTECHDB9', charset=None):
    """
    Open a jConnect connection to a branch-specific Sybase server.

    Each pharmacy branch runs its own Sybase ASE instance.
    Same credentials as HQ (SYBASE_USER / SYBASE_PASSWORD).

    Usage:
        conn = get_branch_connection('192.168.1.5')          # branch 160
        conn = get_branch_connection('192.168.30.12')        # branch 130

    Returns a ConnectionWrapper (same interface as get_sybase_connection).
    Raises on connection failure.
    """
    _ensure_jvm()
    jpype.imports.registerDomain('com')
    from com.sybase.jdbc3.jdbc import SybDriver
    from java.util import Properties

    user     = settings.SYBASE_USER
    password = settings.SYBASE_PASSWORD
    props    = Properties()
    props.setProperty('user', user)
    props.setProperty('password', password)
    # Opt-in connection charset (e.g. 'cp1256') so Arabic writes encode correctly.
    # Default behaviour (charset=None) is unchanged — used only by the writeback path.
    if charset:
        props.setProperty('CHARSET', charset)
    _apply_login_timeout(props)
    # Branch servers are the ones most likely to be offline — bound the login
    # handshake so an unreachable branch raises quickly instead of hanging the
    # whole CRM sync job.
    try:
        from java.sql import DriverManager
        DriverManager.setLoginTimeout(SYBASE_LOGIN_TIMEOUT_SECONDS)
    except Exception:
        pass
    jdbc_url = f'jdbc:sybase:Tds:{db_host}:{db_port}/{db_name}'
    driver   = SybDriver()
    return ConnectionWrapper(_connect_with_retry(driver, jdbc_url, props, label=f'branch {db_host}'))


def probe_connection(host, port=5000, db_name='SOFTECHDB9', login_timeout=None):
    """
    Fast, SINGLE-attempt reachability probe for one Sybase node (HQ or a branch).

    Unlike get_branch_connection (which retries 3× for the flaky VPN and is meant
    for real work), this makes ONE connect attempt with a short login timeout and
    runs `SELECT 1`, so a health sweep of all nodes fails fast on a down host
    instead of spending ~45s on retries. Never raises — returns a result dict:

        {'ok': bool, 'elapsed_ms': float, 'error': str | None}
    """
    _ensure_jvm()
    jpype.imports.registerDomain('com')
    from com.sybase.jdbc3.jdbc import SybDriver
    from java.util import Properties

    lt = int(login_timeout if login_timeout is not None else SYBASE_LOGIN_TIMEOUT_SECONDS)
    props = Properties()
    props.setProperty('user', settings.SYBASE_USER)
    props.setProperty('password', settings.SYBASE_PASSWORD)
    props.setProperty('LOGIN_TIMEOUT', str(lt))

    jdbc_url = f'jdbc:sybase:Tds:{host}:{port}/{db_name}'
    t0 = time.time()
    conn = None
    try:
        try:
            from java.sql import DriverManager
            DriverManager.setLoginTimeout(lt)
        except Exception:
            pass
        conn = SybDriver().connect(jdbc_url, props)   # single attempt (no retry)
        stmt = conn.createStatement()
        _apply_query_timeout(stmt, lt)
        rs = stmt.execute('SELECT 1')
        try:
            stmt.close()
        except Exception:
            pass
        return {'ok': True, 'elapsed_ms': round((time.time() - t0) * 1000, 1), 'error': None}
    except Exception as exc:
        return {'ok': False, 'elapsed_ms': round((time.time() - t0) * 1000, 1),
                'error': str(exc)[:200]}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def test_connection():
    try:
        conn = get_sybase_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT GETDATE()')
        result = cursor.fetchone()
        conn.close()
        return True, 'Connected. Server time: ' + str(result[0])
    except Exception as e:
        return False, str(e)


def _decode_value(val):
    """
    Sybase ASE 12.5 returns Arabic text as Windows-1256 (cp1256) byte arrays
    via jConnect. This function decodes them to proper Python Unicode strings.
    """
    if val is None:
        return val
    # JPype byte array from Java
    if hasattr(val, '__class__') and 'byte' in str(type(val)).lower():
        try:
            return bytes(val).decode('cp1256')
        except Exception:
            return str(val)
    # Java String object from JPype
    if hasattr(val, 'toString'):
        raw = str(val)
        # If it looks like garbled latin (mojibake), re-encode as latin-1 then decode as cp1256
        try:
            return raw.encode('latin-1').decode('cp1256')
        except Exception:
            return raw
    # Plain Python string that might be mojibake
    if isinstance(val, str):
        try:
            return val.encode('latin-1').decode('cp1256')
        except Exception:
            return val
    return val


def _safe_str(val):
    """Convert a Sybase value to a clean Python string, fixing Arabic encoding."""
    if val is None:
        return val
    decoded = _decode_value(val)
    if isinstance(decoded, str):
        # Strip null bytes and extra whitespace
        return decoded.replace('\x00', '').strip()
    return decoded


def _convert_date(val):
    """
    Convert a Java Timestamp / Date object (from jConnect) to a Python datetime.

    Use the WALL-CLOCK components (getYear/getMonth/getDate/…) exactly as stored
    in Sybase — NOT getTime()/epoch.  getTime() interprets the value in the JVM's
    local timezone (Africa/Cairo, UTC+2) and we then rendered it as UTC, which
    shifted every midnight date back one day (e.g. 2026-06-01 → 2026-05-31) and
    every datetime back two hours.  Reading the components avoids that double
    timezone shift and matches the value's own toString().

    Returns None if the value is null or conversion fails.
    """
    if val is None:
        return None
    # Preferred: wall-clock components (java.util.Date API, present on
    # java.sql.Date and java.sql.Timestamp).  These are the stored local values.
    try:
        y  = int(val.getYear()) + 1900
        mo = int(val.getMonth()) + 1
        d  = int(val.getDate())
        try:
            h  = int(val.getHours())
            mi = int(val.getMinutes())
            s  = int(val.getSeconds())
        except Exception:
            h = mi = s = 0
        return _dt.datetime(y, mo, d, h, mi, s)
    except Exception:
        pass
    # Fallback 1: ISO-ish string representation ("2026-06-01 00:00:00.0").
    try:
        return _dt.datetime.fromisoformat(str(val)[:19].replace(' ', 'T'))
    except Exception:
        pass
    # Fallback 2: epoch millis rendered in LOCAL time (no UTC shift).
    try:
        millis = int(val.getTime())
        return _dt.datetime.fromtimestamp(millis / 1000.0)
    except Exception:
        return None


class CursorWrapper:
    def __init__(self, java_conn):
        self._conn      = java_conn
        self._rs        = None
        self._stmt      = None
        # Cached column-type list — populated lazily after execute(); persists
        # across fetchmany() calls so the metadata is read only once per query.
        self._col_types = None

    # ── Query execution ───────────────────────────────────────────────────────

    def execute(self, sql, params=None, timeout=None):
        """
        Execute `sql`.  Handles both SELECT queries (returns ResultSet) and
        non-SELECT statements like SET ROWCOUNT (no ResultSet).

        Uses stmt.execute() (returns bool) instead of executeQuery() so that
        Sybase ASE 12.5 SET statements work without raising JZ0R2.

        When `params` is provided, use a PreparedStatement so that JDBC
        substitutes `?` placeholders before sending the SQL to Sybase.

        `timeout` (seconds) overrides the global query timeout for THIS statement
        only — heavy background scans (the full sync's stktrans query) pass a
        larger value so jConnect's socket read-timeout doesn't abort fetchall()
        with JZ0T3. Omit for the default 30s (interactive HTTP requests).
        """
        self._col_types = None   # reset cached metadata for the new result set
        self._rs        = None   # default: no result set until confirmed

        if params:
            # PreparedStatement: driver substitutes ? at the JDBC level
            self._stmt = self._conn.prepareStatement(sql)
            _apply_query_timeout(self._stmt, timeout)
            for i, param in enumerate(params, start=1):
                if isinstance(param, int):
                    self._stmt.setInt(i, param)
                elif isinstance(param, float):
                    self._stmt.setDouble(i, param)
                elif isinstance(param, str):
                    self._stmt.setString(i, param)
                else:
                    # Fallback: let JDBC infer the type
                    self._stmt.setObject(i, param)
            has_rs = bool(self._stmt.execute())
        else:
            # Plain Statement — no parameters
            self._stmt = self._conn.createStatement()
            _apply_query_timeout(self._stmt, timeout)
            has_rs = bool(self._stmt.execute(sql))

        if has_rs:
            self._rs = self._stmt.getResultSet()

    # ── Metadata helpers ──────────────────────────────────────────────────────

    @property
    def description(self):
        """
        DB-API 2.0 cursor.description — list of 7-item tuples per column.
        Returns [] when there is no current result set (e.g. after SET ROWCOUNT).
        """
        if self._rs is None:
            return []
        meta  = self._rs.getMetaData()
        count = meta.getColumnCount()
        return [
            (str(meta.getColumnName(i)), None, None, None, None, None, None)
            for i in range(1, count + 1)
        ]

    @staticmethod
    def _build_type_sets(meta, col_count):
        return [str(meta.getColumnTypeName(i)).lower() for i in range(1, col_count + 1)]

    def _ensure_col_types(self):
        """Lazily build and cache column-type list from the current ResultSet."""
        if self._col_types is None:
            meta = self._rs.getMetaData()
            self._col_types = self._build_type_sets(meta, meta.getColumnCount())
        return self._col_types

    # ── Row conversion ────────────────────────────────────────────────────────

    def _convert_row(self, col_types):
        """Read one ResultSet row, converting all Java types to Python types."""
        str_types     = {'varchar', 'char', 'nvarchar', 'nchar', 'text', 'sysname'}
        date_types    = {'datetime', 'smalldatetime', 'timestamp', 'date', 'time'}
        # Sybase numeric/decimal returns java.math.BigDecimal via jConnect
        decimal_types = {'numeric', 'decimal', 'money', 'smallmoney'}
        int_types     = {'int', 'smallint', 'tinyint', 'bigint'}
        float_types   = {'float', 'real', 'double'}
        row = []
        for i, col_type in enumerate(col_types, start=1):
            val = self._rs.getObject(i)
            if val is None:
                row.append(None)
                continue
            if col_type in str_types:
                val = _safe_str(val)
            elif col_type in date_types:
                val = _convert_date(val)
            elif col_type in decimal_types:
                try:
                    val = float(str(val))
                except Exception:
                    pass
            elif col_type in int_types:
                try:
                    val = int(str(val))
                except Exception:
                    pass
            elif col_type in float_types:
                try:
                    val = float(str(val))
                except Exception:
                    pass
            row.append(val)
        return row

    # ── Fetch methods ─────────────────────────────────────────────────────────

    def fetchmany(self, size=1):
        """
        Fetch up to `size` rows from the current result set.
        Returns an empty list when the result set is exhausted or absent.
        Metadata is cached from the first call so subsequent calls
        do not re-read ResultSet.getMetaData().
        """
        if self._rs is None:
            return []
        col_types = self._ensure_col_types()
        rows = []
        for _ in range(size):
            if not self._rs.next():
                break
            rows.append(self._convert_row(col_types))
        return rows

    def fetchall(self):
        """Fetch all remaining rows from the current result set."""
        if self._rs is None:
            return []
        col_types = self._ensure_col_types()
        rows = []
        while self._rs.next():
            rows.append(self._convert_row(col_types))
        return rows

    def fetchone(self):
        """Fetch the next single row, or None if exhausted or absent."""
        if self._rs is None:
            return None
        col_types = self._ensure_col_types()
        if self._rs.next():
            return self._convert_row(col_types)
        return None

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def close(self):
        if self._rs:
            self._rs.close()
        if self._stmt:
            self._stmt.close()


class ConnectionWrapper:
    def __init__(self, java_conn):
        self._conn = java_conn

    def cursor(self):
        return CursorWrapper(self._conn)

    # ── Real transaction control (opt-in; used only by audited writeback paths) ──
    # Reads remain autocommit. A caller that needs atomicity wraps its statements:
    #   conn.begin(); try: ...; conn.commit(); except: conn.rollback()
    def begin(self):
        """Turn OFF autocommit so subsequent DML is one transaction."""
        self._conn.setAutoCommit(False)

    def commit(self):
        """Commit the open transaction and restore autocommit."""
        try:
            self._conn.commit()
        finally:
            self._conn.setAutoCommit(True)

    def rollback(self):
        """Roll back the open transaction and restore autocommit."""
        try:
            self._conn.rollback()
        finally:
            self._conn.setAutoCommit(True)

    def close(self):
        self._conn.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SoftechConnector — profile-aware service abstraction
#
# Wraps get_sybase_connection() / get_branch_connection() behind a clean
# interface that supports dev / test / prod profiles and can execute stored
# procedures.  All callers should prefer this class over calling
# get_sybase_connection() directly so VPS migration only requires changing the
# profile env vars, not touching every call site.
#
# Usage:
#   with SoftechConnector() as conn:
#       rows = conn.execute_query("SELECT TOP 1 GETDATE()")
#
# Profile selection (checked in order):
#   1. profile argument passed to connect()
#   2. SOFTECH_PROFILE env var  ('dev' | 'test' | 'prod')
#   3. Falls back to settings.SYBASE_HOST / SYBASE_PORT (existing behaviour)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SoftechConnector:
    """
    Profile-aware SOFTECH connection service.

    Profiles are configured via environment variables:
        SOFTECH_DEV_HOST  / SOFTECH_DEV_PORT
        SOFTECH_TEST_HOST / SOFTECH_TEST_PORT
        SOFTECH_PROD_HOST / SOFTECH_PROD_PORT

    When no profile-specific vars are set the connector falls back to the
    legacy SYBASE_HOST / SYBASE_PORT pair (zero migration effort).
    """

    _LOG_TABLE = 'SoftechConnector'

    def __init__(self, profile: str | None = None):
        import os
        self._profile = (
            profile
            or os.environ.get('SOFTECH_PROFILE', 'prod')
        ).lower()
        self._conn: ConnectionWrapper | None = None

    # ── Connection lifecycle ──────────────────────────────────────────────────

    def connect(self) -> 'SoftechConnector':
        import os
        prefix = {
            'dev':  'SOFTECH_DEV_',
            'test': 'SOFTECH_TEST_',
            'prod': 'SOFTECH_PROD_',
        }.get(self._profile, 'SOFTECH_PROD_')

        host = os.environ.get(f'{prefix}HOST') or settings.SYBASE_HOST
        port = os.environ.get(f'{prefix}PORT') or getattr(settings, 'SYBASE_PORT', '5000')

        _ensure_jvm()
        jpype.imports.registerDomain('com')
        from com.sybase.jdbc3.jdbc import SybDriver
        from java.util import Properties
        from java.sql import DriverManager

        props = Properties()
        props.setProperty('user', settings.SYBASE_USER)
        props.setProperty('password', settings.SYBASE_PASSWORD)
        _apply_login_timeout(props)
        try:
            DriverManager.setLoginTimeout(SYBASE_LOGIN_TIMEOUT_SECONDS)
        except Exception:
            pass

        jdbc_url = f'jdbc:sybase:Tds:{host}:{port}/SOFTECHDB9'
        driver = SybDriver()
        java_conn = _connect_with_retry(driver, jdbc_url, props, label=f'profile {self._profile}')
        self._conn = ConnectionWrapper(java_conn)
        logger.debug('[SoftechConnector] connected profile=%s host=%s', self._profile, host)
        return self

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> 'SoftechConnector':
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ── Query helpers ─────────────────────────────────────────────────────────

    def _cursor(self):
        if self._conn is None:
            raise RuntimeError('SoftechConnector: not connected — call connect() first')
        return self._conn.cursor()

    def execute_query(self, sql: str, params: list | None = None) -> list:
        """Execute a SELECT and return all rows as a list of lists."""
        cur = self._cursor()
        cur.execute(sql, params)
        return cur.fetchall()

    def execute_one(self, sql: str, params: list | None = None):
        """Execute a SELECT and return the first row, or None."""
        cur = self._cursor()
        cur.execute(sql, params)
        return cur.fetchone()

    def execute_stored_procedure(self, name: str, params: list | None = None) -> list:
        """
        Execute a SOFTECH stored procedure and return all result rows.

        ABSOLUTE RULE: Only call read-only stored procedures.
        Never call a procedure that performs INSERT/UPDATE/DELETE on Sybase.

        Usage:
            rows = conn.execute_stored_procedure('sp_GetItemStock', ['001234'])
        """
        placeholders = ', '.join(['?' for _ in (params or [])])
        sql = f'EXEC {name} {placeholders}' if placeholders else f'EXEC {name}'
        cur = self._cursor()
        cur.execute(sql, params or [])
        return cur.fetchall()

    # ── Transaction helpers (PostgreSQL-side only — never Sybase) ─────────────
    # SOFTECH is read-only. These helpers exist only for the rare case where
    # a subclass needs to wrap multiple PostgreSQL writes that depend on a
    # Sybase read result.  They are no-ops on the Sybase connection itself.

    def begin_transaction(self):
        """No-op on Sybase (read-only). Provided for interface completeness."""
        logger.debug('[SoftechConnector] begin_transaction — no-op on Sybase')

    def commit(self):
        """No-op on Sybase (read-only)."""
        logger.debug('[SoftechConnector] commit — no-op on Sybase')

    def rollback(self):
        """No-op on Sybase (read-only)."""
        logger.debug('[SoftechConnector] rollback — no-op on Sybase')

    # ── Health check ──────────────────────────────────────────────────────────

    def ping(self) -> bool:
        """Return True if the connection is alive."""
        try:
            row = self.execute_one('SELECT 1')
            return row is not None
        except Exception:
            return False
