import datetime as _dt

import jpype
import jpype.imports
from django.conf import settings
import logging

logger = logging.getLogger('elrezeiky.sync')

JCONN_JAR = r'C:\sybase\jConnect-6_0\classes\jconn3.jar'
JDBC_DRIVER = 'com.sybase.jdbc3.jdbc.SybDriver'


def _ensure_jvm():
    if not jpype.isJVMStarted():
        jpype.startJVM(
            jpype.getDefaultJVMPath(),
            '-Djava.class.path=' + JCONN_JAR,
            convertStrings=False,
        )


def get_sybase_connection():
    host = settings.SYBASE_HOST
    port = getattr(settings, 'SYBASE_PORT', '5000')
    user = settings.SYBASE_USER
    password = settings.SYBASE_PASSWORD
    _ensure_jvm()
    jpype.imports.registerDomain('com')
    from com.sybase.jdbc3.jdbc import SybDriver
    from java.util import Properties
    props = Properties()
    props.setProperty('user', user)
    props.setProperty('password', password)
    jdbc_url = 'jdbc:sybase:Tds:' + host + ':' + str(port) + '/SOFTECHDB9'
    driver = SybDriver()
    return ConnectionWrapper(driver.connect(jdbc_url, props))


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
    Java's .getTime() returns milliseconds since the Unix epoch.
    Returns None if the value is null or conversion fails.
    """
    if val is None:
        return None
    try:
        # java.sql.Timestamp / java.util.Date both have .getTime() → milliseconds
        millis = int(val.getTime())
        return _dt.datetime.fromtimestamp(millis / 1000.0, tz=_dt.timezone.utc)
    except Exception:
        # Fallback: Sybase sometimes exposes a string-like ISO representation
        try:
            return _dt.datetime.fromisoformat(str(val)[:19])
        except Exception:
            return None


class CursorWrapper:
    def __init__(self, java_conn):
        self._conn = java_conn
        self._rs = None
        self._stmt = None

    def execute(self, sql, params=None):
        self._stmt = self._conn.createStatement()
        self._rs = self._stmt.executeQuery(sql)

    @staticmethod
    def _build_type_sets(meta, col_count):
        col_types = [str(meta.getColumnTypeName(i)).lower() for i in range(1, col_count + 1)]
        return col_types

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

    def fetchall(self):
        rows = []
        meta = self._rs.getMetaData()
        col_count = meta.getColumnCount()
        col_types = self._build_type_sets(meta, col_count)
        while self._rs.next():
            rows.append(self._convert_row(col_types))
        return rows

    def fetchone(self):
        meta = self._rs.getMetaData()
        col_count = meta.getColumnCount()
        col_types = self._build_type_sets(meta, col_count)
        if self._rs.next():
            return self._convert_row(col_types)
        return None

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

    def close(self):
        self._conn.close()
