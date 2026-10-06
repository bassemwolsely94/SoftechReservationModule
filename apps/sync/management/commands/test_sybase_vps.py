"""
python manage.py test_sybase_vps

End-to-end connectivity diagnostic for the Sybase / SOFTECH connection.
Designed to run on a VPS that does NOT have SOFTECH installed locally.

Checks (in order):
  1.  Java / JVM availability
  2.  jconn3.jar location and readability
  3.  JPype JVM startup
  4.  TCP reachability of the Sybase host (raw socket)
  5.  JDBC driver load (com.sybase.jdbc3.jdbc.SybDriver)
  6.  Full JDBC login  (SELECT GETDATE())
  7.  Database existence  (USE SOFTECHDB9)
  8.  Critical table access  (localcustomers, picpoints, localcustomerspoints)
  9.  Write path sanity  (INSERT permission on picpoints — dry-run, rolled back)
  10. Full round-trip  (INSERT → trigger → readback from localcustomerspoints)

Output goes to a UTF-8 file so Arabic text and box-drawing chars survive
Windows console encoding issues.
"""
import os
import pathlib
import socket
import time
from django.core.management.base import BaseCommand

REPORT_PATH = pathlib.Path('sybase_vps_test.txt')
INDENT = '   '


class Report:
    def __init__(self):
        self._lines = []

    def h(self, text):
        self._lines.append('')
        self._lines.append('=' * 60)
        self._lines.append(f'  {text}')
        self._lines.append('=' * 60)

    def ok(self, label, detail=''):
        self._lines.append(f'[PASS] {label}' + (f'  ({detail})' if detail else ''))

    def fail(self, label, detail=''):
        self._lines.append(f'[FAIL] {label}' + (f'\n       {detail}' if detail else ''))

    def info(self, text):
        self._lines.append(f'{INDENT}{text}')

    def warn(self, text):
        self._lines.append(f'[WARN] {text}')

    def write_file(self, path):
        path.write_text('\n'.join(self._lines) + '\n', encoding='utf-8')

    def print_all(self, stdout):
        for line in self._lines:
            try:
                stdout.write(line)
            except UnicodeEncodeError:
                stdout.write(line.encode('ascii', errors='replace').decode())


class Command(BaseCommand):
    help = 'VPS-safe end-to-end Sybase connectivity diagnostic'

    def add_arguments(self, parser):
        parser.add_argument(
            '--write-test', action='store_true',
            help='Also run the write-path dry-run test (INSERT rolled back)',
        )
        parser.add_argument(
            '--output', default=str(REPORT_PATH),
            help='Path to write the UTF-8 report file (default: sybase_vps_test.txt)',
        )

    def handle(self, *args, **options):
        report = Report()
        report.h('Sybase / SOFTECH VPS Connection Diagnostic')
        report.info(f'Date: {time.strftime("%Y-%m-%d %H:%M:%S")}')

        all_ok = True

        # ── 1. Java / JVM ─────────────────────────────────────────────────────
        report.h('1. Java / JVM')
        try:
            import jpype
            jvm_path = jpype.getDefaultJVMPath()
            report.ok('jpype installed', f'version {jpype.__version__}')
            report.ok('JVM found', jvm_path)
            report.info(f'JVM path: {jvm_path}')
        except ImportError as e:
            report.fail('jpype not installed', str(e))
            report.info('Fix: pip install JPype1')
            all_ok = False
        except Exception as e:
            report.fail('JVM not found', str(e))
            report.info('Fix: install OpenJDK 11+ and ensure JAVA_HOME is set')
            all_ok = False

        # ── 2. jconn3.jar ────────────────────────────────────────────────────
        report.h('2. jconn3.jar location')
        try:
            from config.sybase import JCONN_JAR, _BUNDLED, _LEGACY
            jar_path = pathlib.Path(JCONN_JAR)
            if jar_path.exists():
                size_kb = jar_path.stat().st_size // 1024
                report.ok('jconn3.jar found', f'{jar_path}  ({size_kb} KB)')
                # Tell the user where it came from
                if str(jar_path) == str(_BUNDLED):
                    report.info('Source: bundled in project libs/ (VPS-ready)')
                elif str(jar_path) == str(_LEGACY):
                    report.info('Source: legacy C:\\sybase\\ install (dev machine only)')
                    report.warn('This path will NOT exist on a VPS — '
                                'commit libs/jconn3.jar to the repo or set SYBASE_JCONN_JAR')
                else:
                    report.info(f'Source: SYBASE_JCONN_JAR env var = {jar_path}')
            else:
                report.fail('jconn3.jar resolved but does not exist', str(jar_path))
                all_ok = False
        except FileNotFoundError as e:
            report.fail('jconn3.jar not found anywhere', str(e))
            all_ok = False

        if not all_ok:
            self._finish(report, options, all_ok)
            return

        # ── 3. JVM startup ───────────────────────────────────────────────────
        report.h('3. JVM startup')
        try:
            from config.sybase import _ensure_jvm, JCONN_JAR
            import jpype
            _ensure_jvm()
            report.ok('JVM started successfully')
            report.info(f'Classpath: {JCONN_JAR}')
        except Exception as e:
            report.fail('JVM startup failed', str(e))
            all_ok = False
            self._finish(report, options, all_ok)
            return

        # ── 4. TCP reachability ──────────────────────────────────────────────
        report.h('4. TCP reachability (raw socket)')
        from django.conf import settings
        host = settings.SYBASE_HOST
        port = int(getattr(settings, 'SYBASE_PORT', 5000))
        report.info(f'Target: {host}:{port}')
        try:
            t0 = time.time()
            s = socket.create_connection((host, port), timeout=10)
            s.close()
            ms = int((time.time() - t0) * 1000)
            report.ok(f'TCP connected to {host}:{port}', f'{ms} ms')
        except socket.timeout:
            report.fail(f'TCP timeout connecting to {host}:{port}',
                        'Firewall or server offline. '
                        'Ensure port 5000 is open between VPS and Sybase host.')
            all_ok = False
        except ConnectionRefusedError:
            report.fail(f'TCP connection refused on {host}:{port}',
                        'Sybase ASE not listening. Check if ASE service is running.')
            all_ok = False
        except OSError as e:
            report.fail(f'TCP error: {e}', 'Check network / VPN / firewall rules.')
            all_ok = False

        if not all_ok:
            self._finish(report, options, all_ok)
            return

        # ── 5. JDBC driver load ──────────────────────────────────────────────
        report.h('5. JDBC driver class load')
        try:
            import jpype.imports
            jpype.imports.registerDomain('com')
            from com.sybase.jdbc3.jdbc import SybDriver
            report.ok('com.sybase.jdbc3.jdbc.SybDriver loaded')
        except Exception as e:
            report.fail('JDBC driver class not found', str(e))
            report.info('This means the JAR was not added to the JVM classpath correctly.')
            all_ok = False
            self._finish(report, options, all_ok)
            return

        # ── 6. JDBC login ────────────────────────────────────────────────────
        report.h('6. JDBC login (SELECT GETDATE())')
        conn = None
        try:
            from config.sybase import get_sybase_connection
            t0 = time.time()
            conn = get_sybase_connection()
            ms = int((time.time() - t0) * 1000)
            report.ok(f'JDBC login successful', f'{ms} ms')

            cur = conn.cursor()
            cur.execute('SELECT GETDATE()')
            row = cur.fetchone()
            report.ok('SELECT GETDATE()', str(row[0]) if row else '(null)')
            report.info(f'Sybase server time: {row[0]}')
        except Exception as e:
            report.fail('JDBC login failed', str(e))
            _hint_login_error(str(e), report)
            all_ok = False
            self._finish(report, options, all_ok)
            return

        # ── 7. Database access ───────────────────────────────────────────────
        report.h('7. Database access (SOFTECHDB9)')
        try:
            cur = conn.cursor()
            cur.execute('SELECT DB_NAME()')
            row = cur.fetchone()
            report.ok('Connected to database', str(row[0]) if row else '(null)')
        except Exception as e:
            report.fail('Database query failed', str(e))
            all_ok = False

        # ── 8. Critical table access ─────────────────────────────────────────
        report.h('8. Critical table access')
        tables = [
            ('SOFTECHDB9.dbo.localcustomers',       'SELECT count(*) FROM SOFTECHDB9.dbo.localcustomers'),
            ('SOFTECHDB9.dbo.localcustomerspoints',  'SELECT count(*) FROM SOFTECHDB9.dbo.localcustomerspoints'),
            ('SOFTECHDB9.dbo.picpoints',             'SELECT count(*) FROM SOFTECHDB9.dbo.picpoints'),
        ]
        for table_name, sql in tables:
            try:
                cur = conn.cursor()
                cur.execute(sql)
                row = cur.fetchone()
                count = row[0] if row else '?'
                report.ok(table_name, f'{count:,} rows' if isinstance(count, int) else str(count))
            except Exception as e:
                report.fail(table_name, str(e))
                all_ok = False

        # ── 9. SET ROWCOUNT (Sybase ASE 12.5 syntax) ────────────────────────
        report.h('9. SET ROWCOUNT (Sybase ASE 12.5 syntax check)')
        try:
            cur = conn.cursor()
            cur.execute('SET ROWCOUNT 1')
            cur.execute('SELECT phcode FROM SOFTECHDB9.dbo.localcustomers WHERE picpoints = 1')
            row = cur.fetchone()
            cur.execute('SET ROWCOUNT 0')
            if row:
                report.ok('SET ROWCOUNT works', f'sample phcode={row[0]}')
            else:
                report.warn('SET ROWCOUNT worked but no enrolled customer found (picpoints=1)')
        except Exception as e:
            report.fail('SET ROWCOUNT failed', str(e))
            all_ok = False

        # ── 10. Write-path dry-run (optional) ────────────────────────────────
        if options.get('write_test'):
            report.h('10. Write-path dry-run (INSERT + rollback)')
            _run_write_test(conn, report)
        else:
            report.h('10. Write-path dry-run')
            report.info('Skipped. Run with --write-test to include INSERT dry-run.')

        conn.close()
        conn = None

        # ── Summary ───────────────────────────────────────────────────────────
        report.h('SUMMARY')
        if all_ok:
            report.info('ALL checks PASSED. Connection is VPS-ready.')
        else:
            report.info('One or more checks FAILED. See [FAIL] lines above.')

        self._finish(report, options, all_ok)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _finish(self, report, options, all_ok):
        out_path = pathlib.Path(options['output'])
        report.write_file(out_path)
        report.print_all(self.stdout)
        self.stdout.write('')
        if all_ok:
            self.stdout.write(self.style.SUCCESS(
                f'All checks passed. Full report: {out_path}'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f'Some checks failed. Full report: {out_path}'
            ))


# ── standalone helpers ────────────────────────────────────────────────────────

def _hint_login_error(err_str, report):
    err_l = err_str.lower()
    if 'jz00l' in err_l or 'login failed' in err_l:
        report.info('Hint: wrong SYBASE_USER or SYBASE_PASSWORD in .env')
    elif 'connect' in err_l and 'refused' in err_l:
        report.info('Hint: Sybase ASE not listening on that host:port')
    elif 'timeout' in err_l:
        report.info('Hint: network timeout — check VPN / firewall rules')
    elif 'could not find' in err_l or 'jz0c0' in err_l:
        report.info('Hint: server name (SYBASE_DSN) not found — '
                    'Sybase TDS requires the server name in the JDBC URL. '
                    'Check SYBASE_HOST and SYBASE_PORT.')
    elif 'jconn' in err_l or 'class' in err_l:
        report.info('Hint: JDBC driver class not loaded — '
                    'verify jconn3.jar is on the classpath')


def _run_write_test(conn, report):
    """
    INSERT one row into picpoints then immediately ROLLBACK.
    Verifies INSERT permission and trigger existence without leaving
    any permanent data.
    """
    from datetime import datetime
    from apps.loyalty.pic_bridge import read_softech_points, is_softech_points_enrolled

    # Find a test PIC that is enrolled
    try:
        cur = conn.cursor()
        cur.execute('SET ROWCOUNT 1')
        cur.execute(
            "SELECT phcode FROM SOFTECHDB9.dbo.localcustomers "
            "WHERE picpoints = 1 AND phcode IS NOT NULL"
        )
        row = cur.fetchone()
        cur.execute('SET ROWCOUNT 0')
    except Exception as e:
        report.fail('Could not find a test PIC', str(e))
        return

    if not row:
        report.warn('No enrolled customer (picpoints=1) found — skipping write test')
        return

    test_pic = str(row[0]).strip()
    report.info(f'Test PIC: {test_pic}')

    # Read current balance
    try:
        balance_before = read_softech_points(test_pic)
        report.info(f'Balance before: {balance_before}')
    except Exception as e:
        report.fail('read_softech_points failed', str(e))
        return

    # INSERT into picpoints (same pattern as pic_bridge.py)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    insert_sql = """
        INSERT INTO SOFTECHDB9.dbo.picpoints
               (phcode, transdate, points, branchcode,
                doccode, docnumber, docdate, vf1, vf2)
        VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
    """
    params = [
        test_pic,
        now_str,     # transdate
        1,           # points  (tiny test delta)
        'HQ',        # branchcode
        'TST',       # doccode
        now_str,     # docdate
        'VPS_DRY_RUN_TEST',
        'CRM_DIAG',
    ]

    # We need raw Java connection to do explicit ROLLBACK
    java_conn = conn._conn  # unwrap ConnectionWrapper
    try:
        java_conn.setAutoCommit(False)
        cur = conn.cursor()
        cur.execute(insert_sql, params)
        report.ok('INSERT into picpoints succeeded (not yet committed)')

        # Balance after INSERT (trigger should have fired within the txn)
        try:
            balance_after = read_softech_points(test_pic)
            delta = balance_after - balance_before
            report.info(f'Balance after INSERT (in txn): {balance_after}  (delta={delta:+d})')
            if delta == 1:
                report.ok('Trigger fired correctly inside the transaction')
            else:
                report.warn(f'Expected delta=+1, got delta={delta:+d} — trigger may not have fired in-txn')
        except Exception as e:
            report.info(f'(Could not re-read balance in txn: {e})')

        # ROLLBACK — leave no trace
        java_conn.rollback()
        report.ok('ROLLBACK successful — no data written to Sybase')
        java_conn.setAutoCommit(True)

        # Confirm balance returned to original
        balance_final = read_softech_points(test_pic)
        report.info(f'Balance after rollback: {balance_final}')
        if balance_final == balance_before:
            report.ok('Balance restored correctly after rollback')
        else:
            report.warn(
                f'Balance mismatch after rollback: '
                f'before={balance_before} after={balance_final}'
            )

    except Exception as e:
        report.fail('Write-path test failed', str(e))
        try:
            java_conn.rollback()
            java_conn.setAutoCommit(True)
        except Exception:
            pass
