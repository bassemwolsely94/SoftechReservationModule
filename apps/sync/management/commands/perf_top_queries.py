"""
manage.py perf_top_queries — the heaviest queries on OUR Postgres, from pg_stat_statements.

Performance stage 1 (docs/superpowers/specs/2026-11-19-performance-boost-design.md):
measure before optimising. Read-only; `--reset --confirm` is the only write and only
clears the statistics counters. Never touches SOFTECH.

    python manage.py perf_top_queries                    # top 20 by total time
    python manage.py perf_top_queries --sort mean --limit 10
    python manage.py perf_top_queries --sort calls
    python manage.py perf_top_queries --reset --confirm  # clear the counters

When the extension is missing or not preloaded (CI, dev, the office PC before the owner
runs docs/deploy/2026-11-office-pg-query-stats.md) it prints a hint and exits 0.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

HINT = 'pg_stat_statements is not enabled — see docs/deploy/2026-11-office-pg-query-stats.md'

# --sort value → complete, literal query. Fixed map: user input never reaches the SQL text.
ORDER_BY = {
    'total': ('SELECT calls, total_exec_time, mean_exec_time, rows, query FROM pg_stat_statements '
              'WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) '
              'ORDER BY total_exec_time DESC LIMIT %s'),
    'mean': ('SELECT calls, total_exec_time, mean_exec_time, rows, query FROM pg_stat_statements '
             'WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) '
             'ORDER BY mean_exec_time DESC LIMIT %s'),
    'calls': ('SELECT calls, total_exec_time, mean_exec_time, rows, query FROM pg_stat_statements '
              'WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) '
              'ORDER BY calls DESC LIMIT %s'),
}

SQL_WIDTH = 160


def _enabled():
    """True when the extension exists in this database AND the library is preloaded
    (the view raises "must be loaded via shared_preload_libraries" otherwise)."""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'")
            if cur.fetchone() is None:
                return False
        # the trial read can fail; a savepoint keeps an outer transaction usable
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute('SELECT 1 FROM pg_stat_statements LIMIT 1')
            cur.fetchall()
        return True
    except Exception:  # not Postgres, not preloaded, no permission → treat as not enabled
        return False


def _fetch(sort, limit):
    with connection.cursor() as cur:
        cur.execute(ORDER_BY[sort], [limit])
        return cur.fetchall()


def _one_line(sql):
    return re.sub(r'\s+', ' ', sql or '').strip()[:SQL_WIDTH]


class Command(BaseCommand):
    help = 'Top queries on our Postgres from pg_stat_statements (read-only; --reset needs --confirm).'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20)
        parser.add_argument('--sort', default='total',
                            help='total (default) | mean | calls')
        parser.add_argument('--reset', action='store_true',
                            help='clear the statistics counters (needs --confirm)')
        parser.add_argument('--confirm', action='store_true')

    def handle(self, *args, **opts):
        sort = opts['sort']
        if sort not in ORDER_BY:
            raise CommandError(f'--sort must be one of: {", ".join(ORDER_BY)}')
        if opts['reset'] and not opts['confirm']:
            raise CommandError('--reset clears the query statistics; add --confirm to do it.')
        limit = max(1, min(int(opts['limit']), 500))

        if not _enabled():
            self.stdout.write(HINT)
            return

        if opts['reset']:
            with connection.cursor() as cur:
                cur.execute('SELECT pg_stat_statements_reset()')
            self.stdout.write('pg_stat_statements counters cleared.')
            return

        rows = _fetch(sort, limit)
        if not rows:
            self.stdout.write('No statistics yet — use the app for a while and run again.')
            return
        self.stdout.write(f'{"calls":>9} {"total s":>10} {"mean ms":>10} {"rows":>10}  query  (sorted by {sort})')
        for calls, total_ms, mean_ms, nrows, sql in rows:
            self.stdout.write(f'{calls:>9} {total_ms / 1000:>10.1f} {mean_ms:>10.1f} {nrows:>10}  {_one_line(sql)}')
