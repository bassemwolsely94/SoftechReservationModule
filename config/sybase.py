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


class CursorWrapper:
    def __init__(self, java_conn):
        self._conn = java_conn
        self._rs = None
        self._stmt = None

    def execute(self, sql, params=None):
        self._stmt = self._conn.createStatement()
        self._rs = self._stmt.executeQuery(sql)

    def fetchall(self):
        rows = []
        meta = self._rs.getMetaData()
        col_count = meta.getColumnCount()
        # Pre-build column type list — convert Java String to Python str once
        col_types = [str(meta.getColumnTypeName(i)).lower() for i in range(1, col_count + 1)]
        str_types = {'varchar', 'char', 'nvarchar', 'nchar', 'text', 'sysname'}
        while self._rs.next():
            row = []
            for i in range(1, col_count + 1):
                val = self._rs.getObject(i)
                if col_types[i - 1] in str_types:
                    val = _safe_str(val)
                row.append(val)
            rows.append(row)
        return rows

    def fetchone(self):
        meta = self._rs.getMetaData()
        col_count = meta.getColumnCount()
        col_types = [str(meta.getColumnTypeName(i)).lower() for i in range(1, col_count + 1)]
        str_types = {'varchar', 'char', 'nvarchar', 'nchar', 'text', 'sysname'}
        if self._rs.next():
            row = []
            for i in range(1, col_count + 1):
                val = self._rs.getObject(i)
                if col_types[i - 1] in str_types:
                    val = _safe_str(val)
                row.append(val)
            return row
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
