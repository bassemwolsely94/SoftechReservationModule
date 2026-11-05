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

    def test_command_exits_1_and_prints_json_when_drift_found(self):
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE users_useractivitylog DROP COLUMN ip_address')
        out = io.StringIO()
        with self.assertRaises(SystemExit) as stop:
            call_command('check_schema_drift', '--json', stdout=out)
        self.assertEqual(stop.exception.code, 1)
        self.assertIn('ip_address', [d['column'] for d in json.loads(out.getvalue())])

    def test_command_reads_only(self):
        # every statement the command sends is a SELECT
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as q:
            call_command('check_schema_drift', stdout=io.StringIO())
        self.assertTrue(q.captured_queries)
        self.assertTrue(all(x['sql'].lstrip().upper().startswith('SELECT') for x in q.captured_queries),
                        [x['sql'][:60] for x in q.captured_queries])
