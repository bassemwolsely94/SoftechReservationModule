"""
Performance stage 1, Task 4: `manage.py perf_top_queries` reads pg_stat_statements.
The extension is absent in CI, dev and on the office server until the owner enables it,
so the command must say so and exit cleanly; `--reset` is the only write and needs
`--confirm`.
"""
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.sync.management.commands import perf_top_queries as cmd


class PerfTopQueriesTests(TestCase):

    def _run(self, *args):
        out = StringIO()
        call_command('perf_top_queries', *args, stdout=out)
        return out.getvalue()

    def test_not_enabled_prints_hint_and_exits_zero(self):
        # the test database never has the extension preloaded
        with mock.patch.object(cmd, '_enabled', return_value=False):
            text = self._run()
        self.assertIn('not enabled', text)
        self.assertIn('docs/deploy/2026-11-office-pg-query-stats.md', text)

    def test_real_detection_does_not_crash(self):
        # whatever the test server has, detection itself must never raise
        text = self._run('--limit', '1')
        self.assertTrue(text.strip())

    def test_reset_requires_confirm(self):
        with self.assertRaises(CommandError):
            call_command('perf_top_queries', '--reset', stdout=StringIO())

    def test_unknown_sort_rejected(self):
        with self.assertRaises(CommandError):
            call_command('perf_top_queries', '--sort', 'total; drop table x', stdout=StringIO())

    def test_rows_printed_when_enabled(self):
        rows = [(12, 3456.7, 288.06, 40, 'SELECT  *\n FROM catalog_item WHERE id = $1')]
        with mock.patch.object(cmd, '_enabled', return_value=True), \
             mock.patch.object(cmd, '_fetch', return_value=rows) as fetch:
            text = self._run('--sort', 'calls', '--limit', '5')
        fetch.assert_called_once_with('calls', 5)
        self.assertIn('SELECT * FROM catalog_item WHERE id = $1', text)
        self.assertIn('3.5', text)   # total seconds

    def test_order_by_comes_from_fixed_map(self):
        self.assertEqual(set(cmd.ORDER_BY), {'total', 'mean', 'calls'})
