"""
check_schema_drift (round-2 R0): a fresh test database has no drift, and each kind of drift the
three real incidents had is reported. DDL inside a TestCase is rolled back with the transaction
(PostgreSQL DDL is transactional), so the test database is left as it was.
"""
import io
import json

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from apps.sync.management.commands.check_schema_drift import collect_drift


class SchemaDriftTests(TestCase):
    def _kinds(self, table):
        return {(d['kind'], d['column']) for d in collect_drift() if d['table'] == table}

    def test_fresh_database_has_no_drift(self):
        self.assertEqual(collect_drift(), [])

    def test_missing_column_is_reported(self):
        # users 0008, 2026-11-03: CREATE TABLE IF NOT EXISTS skipped ip_address
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE users_useractivitylog DROP COLUMN ip_address')
        self.assertIn(('missing_column', 'ip_address'), self._kinds('users_useractivitylog'))

    def test_legacy_not_null_column_is_reported(self):
        # notifications 0008: a NOT NULL column the model no longer knows makes inserts fail
        with connection.cursor() as cur:
            cur.execute("ALTER TABLE notifications_notification ADD COLUMN legacy_message text NOT NULL DEFAULT ''")
            cur.execute('ALTER TABLE notifications_notification ALTER COLUMN legacy_message DROP DEFAULT')
        self.assertIn(('legacy_not_null', 'legacy_message'), self._kinds('notifications_notification'))

    def test_nullability_difference_is_reported(self):
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE users_useractivitylog ALTER COLUMN note DROP NOT NULL')
        self.assertIn(('nullability', 'note'), self._kinds('users_useractivitylog'))

    def test_repair_migration_fixes_the_office_drift(self):
        # the office database had these two NOT NULL (2026-11-05); customers 0032 makes them nullable
        import importlib
        repair = importlib.import_module('apps.customers.migrations.0032_repair_drifted_not_null')
        with connection.cursor() as cur:
            for table, column in repair.REPAIRS:
                cur.execute(f'DELETE FROM "{table}"')
                cur.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET NOT NULL')
        self.assertTrue({('nullability', 'target_user_id'), ('nullability', 'invoice_date')}
                        <= {(d['kind'], d['column']) for d in collect_drift()})
        repair.forwards(None, connection.schema_editor())
        repair.forwards(None, connection.schema_editor())            # idempotent
        self.assertEqual(collect_drift(), [])

    def test_command_exits_1_and_prints_json_when_drift_found(self):
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE users_useractivitylog DROP COLUMN ip_address')
        out = io.StringIO()
        with self.assertRaises(SystemExit) as stop:
            call_command('check_schema_drift', '--json', stdout=out)
        self.assertEqual(stop.exception.code, 1)
        self.assertIn('ip_address', [d['column'] for d in json.loads(out.getvalue())])

    def test_harmless_difference_is_reported_but_passes_the_gate(self):
        # the office keeps two of these on purpose (notifications body, staffprofile updated_at):
        # the database allows an empty value the code never saves, so nothing can break
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE users_useractivitylog ALTER COLUMN note DROP NOT NULL')
        found = [d for d in collect_drift() if d['column'] == 'note']
        self.assertEqual([d['breaks'] for d in found], [False])
        out = io.StringIO()
        call_command('check_schema_drift', stdout=out)                 # no SystemExit
        self.assertIn('harmless', out.getvalue())
        with self.assertRaises(SystemExit) as stop:
            call_command('check_schema_drift', '--strict', stdout=io.StringIO())
        self.assertEqual(stop.exception.code, 1)

    def test_not_null_the_code_does_not_expect_fails_the_gate(self):
        with connection.cursor() as cur:
            cur.execute('DELETE FROM users_useractivitylog')
            cur.execute('ALTER TABLE users_useractivitylog ALTER COLUMN target_user_id SET NOT NULL')
        found = [d for d in collect_drift() if d['column'] == 'target_user_id']
        self.assertEqual([d['breaks'] for d in found], [True])
        with self.assertRaises(SystemExit) as stop:
            call_command('check_schema_drift', stdout=io.StringIO())
        self.assertEqual(stop.exception.code, 1)

    def test_command_reads_only(self):
        # every statement the command sends is a SELECT
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as q:
            call_command('check_schema_drift', stdout=io.StringIO())
        self.assertTrue(q.captured_queries)
        self.assertTrue(all(x['sql'].lstrip().upper().startswith('SELECT') for x in q.captured_queries),
                        [x['sql'][:60] for x in q.captured_queries])


def _width(table, column):
    with connection.cursor() as cur:
        cur.execute('SELECT character_maximum_length FROM information_schema.columns '
                    'WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s',
                    [table, column])
        return cur.fetchone()[0]


class ColumnWidthDriftTests(TestCase):
    """UAT W8 (2026-11-20): users_useractivitylog.action was varchar(20) on the office database
    while the model says max_length=30 (users 0008, CREATE TABLE IF NOT EXISTS). 'mfa_devices_forgotten'
    (21 chars) could not be stored and forget-devices answered 500. users 0063 repairs it."""

    def _repair(self):
        import importlib
        return importlib.import_module('apps.users.migrations.0063_repair_activitylog_column_widths')

    def _width_findings(self):
        return {(d['table'], d['column']): d for d in collect_drift() if d['kind'] == 'column_width'}

    def test_fresh_database_columns_are_as_wide_as_the_models(self):
        self.assertEqual(self._width_findings(), {})

    def test_narrow_varchar_is_reported_and_breaks(self):
        with connection.cursor() as cur:
            cur.execute('DELETE FROM users_useractivitylog')
            cur.execute('ALTER TABLE users_useractivitylog ALTER COLUMN action TYPE varchar(20)')
        d = self._width_findings()[('users_useractivitylog', 'action')]
        self.assertTrue(d['breaks'])
        self.assertEqual((d['model_width'], d['db_width']), (30, 20))

    def test_textfield_stored_as_varchar_is_reported(self):
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE users_useractivitylog ALTER COLUMN note TYPE varchar(255)')
        d = self._width_findings()[('users_useractivitylog', 'note')]
        self.assertTrue(d['breaks'])
        self.assertIsNone(d['model_width'])

    def test_wider_column_is_harmless(self):
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE users_useractivitylog ALTER COLUMN network TYPE varchar(40)')
        d = self._width_findings()[('users_useractivitylog', 'network')]
        self.assertFalse(d['breaks'])
        call_command('check_column_widths', stdout=io.StringIO())     # no SystemExit

    def test_repair_migration_widens_the_drifted_columns_and_is_idempotent(self):
        repair = self._repair()
        with connection.cursor() as cur:
            cur.execute('DELETE FROM users_useractivitylog')
            cur.execute('ALTER TABLE users_useractivitylog ALTER COLUMN action TYPE varchar(20)')
            cur.execute('ALTER TABLE users_useractivitylog ALTER COLUMN note TYPE varchar(255)')
        repair.forwards(None, connection.schema_editor())
        self.assertEqual(_width('users_useractivitylog', 'action'), 30)
        self.assertIsNone(_width('users_useractivitylog', 'note'))
        repair.forwards(None, connection.schema_editor())            # idempotent
        self.assertEqual(_width('users_useractivitylog', 'action'), 30)
        self.assertEqual(self._width_findings(), {})

    def test_repair_migration_is_a_noop_on_a_fresh_database(self):
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as q:
            self._repair().forwards(None, connection.schema_editor())
        self.assertFalse([x['sql'] for x in q.captured_queries if 'ALTER' in x['sql'].upper()])
        self.assertEqual(_width('users_useractivitylog', 'action'), 30)

    def test_repair_never_narrows(self):
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE users_useractivitylog ALTER COLUMN action TYPE varchar(40)')
        self._repair().forwards(None, connection.schema_editor())
        self.assertEqual(_width('users_useractivitylog', 'action'), 40)

    def test_forget_devices_works_after_the_repair(self):
        from apps.tests.factories import make_user
        from apps.users.models import UserActivityLog
        with connection.cursor() as cur:
            cur.execute('DELETE FROM users_useractivitylog')
            cur.execute('ALTER TABLE users_useractivitylog ALTER COLUMN action TYPE varchar(20)')
        self._repair().forwards(None, connection.schema_editor())
        _, profile, _ = make_user('w8_target', role='purchasing')
        _, admin_profile, admin = make_user('w8_admin', role='admin')
        r = admin.post(f'/api/users/{profile.id}/forget-devices/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        row = UserActivityLog.objects.get(action='mfa_devices_forgotten')
        self.assertEqual((row.target_user, row.changed_by), (profile, admin_profile))

    def test_width_command_exits_1_on_narrow_column_and_reads_only(self):
        from django.test.utils import CaptureQueriesContext
        with connection.cursor() as cur:
            cur.execute('DELETE FROM users_useractivitylog')
            cur.execute('ALTER TABLE users_useractivitylog ALTER COLUMN action TYPE varchar(20)')
        out = io.StringIO()
        with CaptureQueriesContext(connection) as q:
            with self.assertRaises(SystemExit) as stop:
                call_command('check_column_widths', '--json', stdout=out)
        self.assertEqual(stop.exception.code, 1)
        self.assertEqual([d['column'] for d in json.loads(out.getvalue())], ['action'])
        self.assertTrue(all(x['sql'].lstrip().upper().startswith('SELECT') for x in q.captured_queries))
