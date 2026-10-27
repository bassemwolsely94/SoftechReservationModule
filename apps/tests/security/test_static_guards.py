"""
apps/tests/security/test_static_guards.py

Source-code guards over the whole repo (no database, no network):

  * SQL built from text that reaches execute()          → baselines/sql_from_text.txt
  * SOFTECH connections outside config/sybase.py's guard  → baselines/raw_softech_connect.txt
  * every SOFTECH write site registered in the manifest   → softech_write_manifest.py
  * SOFTECH write switches that default to ON             → baselines/write_flags_default_true.txt
  * secrets committed to tracked files                    → baselines/tracked_secrets.txt
  * /api/ prefixes the role matrix doesn't classify       → baselines/unclassified_api_prefixes.txt
"""
import ast
import textwrap

from django.conf import settings
from django.test import SimpleTestCase

from . import static_scan
from .baseline import assert_matches_baseline


def _tree(src):
    return ast.parse(textwrap.dedent(src))


class StaticScanUnitTests(SimpleTestCase):

    def test_fstring_execute_flagged(self):
        t = _tree('''
            def f(x):
                cur.execute(f"select * from t where a = '{x}'")
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::f'})

    def test_variable_then_execute_flagged(self):
        t = _tree('''
            def f(x):
                sql = "select * from t where a = '%s'" % x
                cur.execute(sql)
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::f'})

    def test_format_and_concat_flagged(self):
        t = _tree('''
            def g(x):
                cur.execute("select {}".format(x))
            def h(x):
                cur.execute("select " + x)
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::g', 't.py::h'})

    def test_template_format_kwargs_flagged(self):
        t = _tree('''
            SQL = "select * from t where b = '{branch}'"
            class Engine:
                def run(self, branch):
                    return _run(SQL.format(branch=branch))
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::Engine.run'})

    def test_parameterised_not_flagged(self):
        t = _tree('''
            def f(x):
                cur.execute("select * from t where a = ?", [x])
                cur.execute("select 1")
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), set())

    def test_constant_only_concat_not_flagged(self):
        t = _tree('''
            def f():
                cur.execute("select a " + "from t")
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), set())

    # ── shapes from the final review (Critical 1) ──
    def test_sql_literal_passed_to_any_helper_flagged(self):
        t = _tree('''
            def _exec_insert(conn, table, row):
                _exec(conn, f"INSERT INTO {table} (a) VALUES ({row})")
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::_exec_insert'})

    def test_sql_variable_passed_to_any_helper_flagged(self):
        t = _tree('''
            def inject(jst, code):
                batch = f"update itemssuppliers set code = '{code}' where x = 1"
                return _run_batch_lastrow(jst, batch)
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::inject'})

    def test_helper_whose_param_reaches_execute_becomes_sink(self):
        t = _tree('''
            def _exec(conn, sql, params=None):
                conn.cursor().execute(sql, params or [])
            def push(conn, t):
                q = "a " + t
                _exec(conn, q)
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::push'})

    def test_conditional_expression_flagged(self):
        t = _tree('''
            def run_proc(cur, name, placeholders):
                sql = f'EXEC {name} {placeholders}' if placeholders else f'EXEC {name}'
                cur.execute(sql)
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::run_proc'})

    def test_keyword_and_wrapped_and_other_sinks_flagged(self):
        t = _tree('''
            import textwrap
            def a(x):
                run(sql=f"select * from t where a = '{x}'")
            def b(x):
                cur.execute(f"select * from t where a = '{x}'".strip())
            def c(x):
                cur.execute(textwrap.dedent(f"select * from t where a = {x}"))
            def d(cur, rows, t):
                cur.executemany("insert into " + t + " values (?)", rows)
            def e(conn, tbl):
                conn.execute_query(f"select name from sysobjects where name = '{tbl}'")
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'),
                         {'t.py::a', 't.py::b', 't.py::c', 't.py::d', 't.py::e'})

    def test_annotated_tuple_attribute_and_closure_targets_flagged(self):
        t = _tree('''
            def a(x):
                sql: str = f"select * from t where a = {x}"
                cur.execute(sql)
            def b(x):
                sql, n = f"select * from t where a = {x}", 1
                cur.execute(sql)
            class K:
                def c(self, x):
                    self.sql = "select * from t where a = " + x
                    self.cur.execute(self.sql)
            def d(x):
                sql = f"select * from t where a = {x}"
                def inner():
                    cur.execute(sql)
                inner()
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'),
                         {'t.py::a', 't.py::b', 't.py::K.c', 't.py::d.inner'})

    # ── safe fillers: placeholders, constants (Batch 1) ──
    def test_format_with_placeholder_markers_and_constants_not_flagged(self):
        t = _tree('''
            _EXCLUDED = "('102','103')"
            SQL = "select a from t where b = ? and c in ({codes}) and d not in {excluded} {extra}"
            def _marks(values):
                return ', '.join('?' for _ in values)
            def f(codes, flag):
                extra = 'and e = ?' if flag else ''
                if flag:
                    join = "join x on x.a = t.a"
                else:
                    join = ''
                sql = SQL.format(codes=_marks(codes), excluded=_EXCLUDED, extra=extra)
                cur.execute(sql + join, [1] + codes)
                cur.execute(SQL.format(codes=','.join('?' * len(codes)), excluded=_EXCLUDED,
                                       extra=','.join(['?'] * 2)), codes)
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), set())

    def test_format_with_a_parameter_still_flagged(self):
        t = _tree('''
            SQL = "select a from t where b = '{branch}' and c in ({codes})"
            def _marks(values):
                return ', '.join('?' for _ in values)
            def f(branch, codes):
                cur.execute(SQL.format(branch=branch, codes=_marks(codes)), codes)
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::f'})

    def test_local_reassigned_from_parameter_is_not_safe(self):
        t = _tree('''
            SQL = "select a from t where b = {x}"
            def f(user):
                x = '1'
                x = user
                cur.execute(SQL.format(x=x))
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::f'})

    def test_fstring_of_safe_clauses_not_flagged(self):
        t = _tree('''
            def _marks(values):
                return ', '.join('?' for _ in values)
            def f(codes, stores, zero):
                qty_sql = '' if zero else 'AND q > 0'
                store_sql = f"AND s IN ({_marks(stores)})" if stores else ''
                cur.execute(f"select a from t where d >= ? {qty_sql} {store_sql} "
                            f"and c in ({_marks(codes)})", [1] + stores + codes)
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), set())

    def test_numeric_conversions_are_safe(self):
        t = _tree('''
            def f(limit, rows):
                n = max(1, min(int(limit or 100), 10000))
                cur.execute(f'SET ROWCOUNT {n}')
                cur.execute(f'SET ROWCOUNT {len(rows)}')
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), set())

    def test_max_of_a_raw_parameter_is_not_safe(self):
        t = _tree('''
            def f(limit):
                cur.execute(f'SET ROWCOUNT {max(1, limit)}')
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::f'})

    # ── final-review false negatives (Batch 1) ──
    def test_loop_with_walrus_except_comprehension_targets_are_not_safe(self):
        t = _tree('''
            def a(request):
                code = ''
                for code in request.data['codes']:
                    cur.execute(f"select a from t where c = '{code}'")
            def b(path):
                name = ''
                with open(path) as name:
                    cur.execute(f"select a from t where c = '{name}'")
            def c(data):
                v = ''
                if (v := data.get('x')):
                    cur.execute(f"select a from t where c = '{v}'")
            def d(rows):
                r = ''
                [cur.execute(f"select a from t where c = '{r}'") for r in rows]
            def e():
                err = ''
                try:
                    pass
                except Exception as err:
                    cur.execute(f"select a from t where c = '{err}'")
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'),
                         {'t.py::a', 't.py::b', 't.py::c', 't.py::d', 't.py::e'})

    def test_parameter_shadowing_a_safe_outer_name_is_not_safe(self):
        t = _tree('''
            def outer():
                code = 'X'
                def inner(code):
                    cur.execute(f"select a from t where c = '{code}'")
                return inner
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::outer.inner'})

    def test_replace_with_a_parameter_is_built(self):
        t = _tree('''
            TEMPLATE = "select a from t where b = '{branch}'"
            def f(b):
                sql = TEMPLATE.replace('{branch}', b)
                cur.execute(sql)
            def g():
                cur.execute(TEMPLATE.replace('{branch}', '100'))
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::f'})

    def test_only_exact_marks_helpers_are_trusted(self):
        t = _tree('''
            def f(obj, codes):
                cur.execute(f"select a from t where c in ({obj.remarks(codes)})")
            def g(codes):
                cur.execute(f"select a from t where c in ({_marks(codes)})", codes)
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::f'})

    def test_join_must_be_only_question_marks(self):
        t = _tree('''
            def f(codes, user_codes, flag):
                cur.execute(f"select a from t where c in ({','.join(['?'] * len(codes) + user_codes)})")
                cur.execute(f"select a from t where c in ({','.join('?' if flag else c for c in codes)})")
            def g(codes):
                cur.execute(f"select a from t where c in ({','.join('?' for _ in codes)})", codes)
                cur.execute(f"select a from t where c in ({','.join(['?'] * len(codes))})", codes)
                cur.execute(f"select a from t where c in ({','.join('?' * len(codes))})", codes)
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::f'})

    def test_date_formatting_is_safe(self):
        t = _tree('''
            def f(d1, d2):
                cur.execute(f"select a from t where d >= '{d1.isoformat()} 00:00:00' "
                            f"and d < '{d2.strftime('%Y-%m-%d')}'")
            def g(d, fmt):
                cur.execute(f"select a from t where d >= '{d.strftime(fmt)}'")
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::g'})

    def test_fstring_with_a_parameter_still_flagged(self):
        t = _tree('''
            def f(code):
                clause = f"AND c = '{code}'"
                cur.execute(f"select a from t where d >= ? {clause}", [1])
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::f'})

    def test_conditional_with_a_parameter_branch_is_not_safe(self):
        t = _tree('''
            SQL = "select a from t where b = {x}"
            def f(user, c):
                x = user if c else '1'
                cur.execute(SQL.format(x=x))
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), {'t.py::f'})

    def test_prose_with_sql_words_not_flagged(self):
        t = _tree('''
            def f(x):
                logger.info(f"update failed for {x}")
                raise ValueError(f"select a branch first ({x})")
                cur.execute(sql_param)
        ''')
        self.assertEqual(static_scan.sql_from_text_sites(t, 't.py'), set())

    def test_raw_connect_flagged_outside_sybase(self):
        src = '''
            def _connect(u, p):
                from com.sybase.jdbc3.jdbc import SybDriver
                return SybDriver().connect(u, p)
        '''
        self.assertEqual(static_scan.raw_connect_sites(_tree(src), 'apps/x.py'),
                         {'apps/x.py::_connect'})

    def test_raw_connect_allowed_in_guarded_sybase_functions(self):
        src = '''
            def get_sybase_connection():
                from com.sybase.jdbc3.jdbc import SybDriver
                driver = SybDriver()
            def sneaky():
                return SybDriver().connect('u', {})
        '''
        self.assertEqual(static_scan.raw_connect_sites(_tree(src), 'config/sybase.py'),
                         {'config/sybase.py::sneaky'})

    def test_write_literal_detected_in_softech_module(self):
        src = '''
            from config.sybase import get_sybase_connection
            def push():
                sql = """
                    INSERT INTO SOFTECHDB9.dbo.picpoints (a) VALUES (?)
                """
            def read():
                sql = "select * from items"
        '''
        self.assertEqual(static_scan.softech_write_sites(_tree(src), 'm.py'), {'m.py::push'})

    def test_write_literal_ignored_outside_softech_modules(self):
        src = '''
            def migrate():
                cursor.execute("UPDATE catalog_item SET x = 1")
        '''
        self.assertEqual(static_scan.softech_write_sites(_tree(src), 'm.py'), set())

    def test_update_set_and_delete_detected(self):
        src = '''
            from config import sybase
            def a():
                q = "update items set itemmodified = ? where itemcode = ?"
            def b():
                q = f"DELETE FROM stktrans5 WHERE docnumber = {n}"
        '''
        self.assertEqual(static_scan.softech_write_sites(_tree(src), 'm.py'), {'m.py::a', 'm.py::b'})

    def test_update_with_interpolated_table_detected(self):
        src = '''
            from config.sybase import get_branch_connection
            def push(DB, set_sql, table, col):
                cur.execute(f'UPDATE {DB}.localcustomers SET {set_sql} WHERE phcode = ?', [1])
            def note(table, col):
                cur.execute(f"UPDATE {table} SET {col} = ? WHERE a = ?", [1, 2])
        '''
        self.assertEqual(static_scan.softech_write_sites(_tree(src), 'm.py'),
                         {'m.py::push', 'm.py::note'})

    def test_softechdb_literal_counts_without_connection_import(self):
        src = '''
            def edit(cur, table):
                cur.execute(f"UPDATE SOFTECHDB9.dbo.{table} SET docdate=? WHERE x=?", [1, 2])
        '''
        self.assertEqual(static_scan.softech_write_sites(_tree(src), 'm.py'), {'m.py::edit'})

    def test_tsql_write_forms_detected(self):
        src = '''
            from config.sybase import get_sybase_connection
            def a():
                q = "insert itemssuppliers (a, b) values (?, ?)"
            def b():
                q = "delete stktrans5 where docnumber = ?"
            def c():
                q = "UPDATE %s SET x = ?" % t
            def d():
                q = "UPDATE {} SET x = ?".format(t)
            def e():
                q = "truncate table tmp_x"
            def f():
                q = "UPDATE SOFTECHDB9.dbo.items " + "SET itemmodified = ? WHERE itemcode = ?"
            def g():
                msg = "please insert the card and delete the draft"
            def h():
                help_a = "the stktrans purchase line insert land (rolls back)"
                help_b = "run the rollback INSERT rehearsal (still requires --confirm)"
        '''
        self.assertEqual(static_scan.softech_write_sites(_tree(src), 'm.py'),
                         {'m.py::a', 'm.py::b', 'm.py::c', 'm.py::d', 'm.py::e', 'm.py::f'})

    def test_default_true_flags_found(self):
        src = '''
            A_ENABLED = config('A_ENABLED', default=True, cast=bool)
            B_ENABLED = config('B_ENABLED', default=False, cast=bool)
            C_WRITE = config('C_WRITE', cast=bool, default=True)
            OTHER = config('OTHER', default=True)
        '''
        self.assertEqual(static_scan.default_true_flags(_tree(src)), {'A_ENABLED', 'C_WRITE'})

    def test_secret_patterns(self):
        text = 'ADMIN_PASS = "hunter2hunter"\nx = 1\nkey = "AIza' + 'A' * 35 + '"\n'
        self.assertEqual(static_scan.secret_hits(text),
                         {'password-literal', 'google-api-key'})

    def test_test_modules_skipped_by_secret_scan(self):
        for rel in ('apps/portal/tests.py', 'apps/users/tests_mfa.py', 'apps/tests/factories.py'):
            self.assertTrue(static_scan.skip_for_secrets(rel), rel)
        for rel in ('scripts/smoke_api_live.py', 'apps/users/views.py', 'config/settings.py'):
            self.assertFalse(static_scan.skip_for_secrets(rel), rel)

    def test_bom_file_parses(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'bom.py'
            p.write_bytes(b'\xef\xbb\xbfx = 1\n')
            self.assertIsInstance(static_scan.parse_file(p), ast.Module)

    def test_secret_patterns_ignore_env_reads(self):
        text = 'PASSWORD = os.environ.get("ADMIN_PASS", "")\npassword = config("X")\n'
        self.assertEqual(static_scan.secret_hits(text), set())


class StaticGuardTests(SimpleTestCase):

    def test_no_sql_built_from_text(self):
        assert_matches_baseline(self, 'sql_from_text', static_scan.repo_sites(
            static_scan.sql_from_text_sites))

    def test_sql_baseline_lines_are_all_explained(self):
        """Every remaining text-built SQL site sits under a '# reason:' (reviewed safe)
        or '# Owner: Batch 2' (SOFTECH write path awaiting the owner) header."""
        from .baseline import BASELINE_DIR
        lines = (BASELINE_DIR / 'sql_from_text.txt').read_text(encoding='utf-8').splitlines()
        header, unexplained = None, []
        for ln in lines:
            s = ln.strip()
            if s.startswith('# reason:') or s.startswith('# Owner: Batch 2'):
                header = s                      # a block lasts until the next header
            elif s and not s.startswith('#') and header is None:
                unexplained.append(s)
        self.assertEqual(unexplained, [], 'unexplained SQL sites:\n' + '\n'.join(unexplained))

    def test_no_raw_softech_connections(self):
        assert_matches_baseline(self, 'raw_softech_connect', static_scan.repo_sites(
            static_scan.raw_connect_sites))

    def test_every_softech_write_site_is_registered(self):
        from .softech_write_manifest import WRITE_SITES
        found = static_scan.repo_sites(static_scan.softech_write_sites)
        unregistered = sorted(found - set(WRITE_SITES))
        stale = sorted(set(WRITE_SITES) - found)
        self.assertEqual((unregistered, stale), ([], []),
                         'SOFTECH write sites out of step with softech_write_manifest.py\n'
                         'UNREGISTERED (add a WriteSite entry):\n' + '\n'.join(unregistered) +
                         '\nSTALE (remove the entry):\n' + '\n'.join(stale))

    def test_manifest_flags_exist(self):
        from .softech_write_manifest import WRITE_SITES
        missing = sorted({s.flag for s in WRITE_SITES.values()
                          if s.flag and not hasattr(settings, s.flag)})
        self.assertEqual(missing, [])

    def test_softech_write_flags_default_false(self):
        tree = ast.parse((static_scan.REPO_ROOT / 'config' / 'settings.py').read_text(encoding='utf-8'))
        assert_matches_baseline(self, 'write_flags_default_true', static_scan.default_true_flags(tree))

    def test_no_hardcoded_secrets_in_tracked_files(self):
        files = static_scan.tracked_files()
        if files is None:
            self.skipTest('git not available — secrets guard needs `git ls-files`')
        assert_matches_baseline(self, 'tracked_secrets', static_scan.tracked_secret_sites(files))

    def test_every_api_prefix_is_classified(self):
        from core.middleware.module_access import (EXEMPT_PREFIXES, MODULE_BY_PREFIX,
                                                   READ_OPEN_PREFIXES)
        from .routes import api_routes
        known = set(MODULE_BY_PREFIX) | set(READ_OPEN_PREFIXES) | set(EXEMPT_PREFIXES)
        prefixes = {p.split('/')[2] for p, _ in api_routes()}
        assert_matches_baseline(self, 'unclassified_api_prefixes', prefixes - known)
