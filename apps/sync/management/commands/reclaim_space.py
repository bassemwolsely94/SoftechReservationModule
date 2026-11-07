"""
Report empty space in PostgreSQL tables and, by hand, compact one table with VACUUM FULL.

Data lifecycle design, Stage 2. Dry run by default. Run by hand only, never from the scheduler:
VACUUM FULL blocks every read and write on the table while it rewrites it.

Restoring a dump at the VPS cutover compacts every table without this command, so measure after
the restore first. Do not use --apply on the office database just before cutover.

No index is dropped here. Dropping needs 30 days of VPS data and owner approval of the list.
"""
import logging
import shutil
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection
from django.utils import timezone
from psycopg2 import sql

from apps.purchasing.models import DemandCalculationRun

logger = logging.getLogger(__name__)

# --apply is allowed from 01:00 up to 07:00 Cairo time, ending before the 07:30 morning chain. This
# is the builder's choice of business hours, so the owner can move it. Nightly jobs still fall inside
# it: they wait while the table is locked, and LOCK_TIMEOUT_MS stops this command queueing behind a
# running one, which would hold up everyone else as well.
WINDOW_START_HOUR = 1
WINDOW_END_HOUR = 7
LOCK_TIMEOUT_MS = 30_000

# A rewrite needs room for the new copy while the old one still exists, and the rewrite also
# writes WAL. The current size is the worst case for the copy; the margin covers the rest.
DISK_MARGIN_BYTES = 1024 ** 3

LIST_FLOOR_BYTES = 20 * 1024 ** 2  # the design's "large table" line
SAMPLE_BYTES = 16 * 1024 ** 2      # read at most this much of a table for the estimate
ROW_POINTER_BYTES = 4
BTREE_ENTRY_OVERHEAD_BYTES = 12    # index tuple header + line pointer
BTREE_FILL = 0.9
LOCAL_HOSTS = {'', 'localhost', '127.0.0.1', '::1'}


@dataclass
class TableInfo:
    name: str
    total_bytes: int
    heap_bytes: int
    index_bytes: int
    real_bytes: int      # estimated size of the live rows
    expected_gain: int   # estimated bytes VACUUM FULL would give back


def local_now():
    return timezone.localtime()


def in_business_hours(now):
    return not WINDOW_START_HOUR <= now.hour < WINDOW_END_HOUR


def running_engine_run():
    return DemandCalculationRun.objects.filter(status='running').order_by('started_at').first()


def compact_index_bytes(actual_bytes, access_method, is_special, rows, key_width):
    """
    Estimated size of an index after a rebuild, never above its current size.

    Only a plain btree can be estimated from row count and column widths. For the rest (GIN,
    expression and partial indexes) this returns the current size, so they claim no gain.
    """
    if access_method != 'btree' or is_special:
        return actual_bytes
    aligned_key = (int(key_width) + 7) // 8 * 8
    return min(actual_bytes, int(rows * (BTREE_ENTRY_OVERHEAD_BYTES + aligned_key) / BTREE_FILL))


def _live_row_estimate(cur, table, heap_bytes):
    """Sample the table's pages. Returns (live rows, bytes of live rows); only visible rows are counted."""
    percent = 100.0 if heap_bytes <= SAMPLE_BYTES else SAMPLE_BYTES * 100.0 / heap_bytes
    cur.execute(
        sql.SQL(
            'SELECT count(*), coalesce(sum(pg_column_size(t.*)), 0) FROM {} AS t TABLESAMPLE SYSTEM (%s)'
        ).format(sql.Identifier(table)),
        [percent],
    )
    sampled_rows, sampled_bytes = cur.fetchone()
    scale = 100.0 / percent
    return sampled_rows * scale, (int(sampled_bytes) + sampled_rows * ROW_POINTER_BYTES) * scale


def _compact_indexes_bytes(cur, relid, table, rows):
    cur.execute(
        """
        SELECT pg_relation_size(i.indexrelid), am.amname,
               i.indexprs IS NOT NULL OR i.indpred IS NOT NULL,
               (SELECT coalesce(sum(coalesce(s.avg_width, 8)), 0)
                  FROM unnest(i.indkey) AS k
                  JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k
                  LEFT JOIN pg_stats s ON s.schemaname = current_schema()
                       AND s.tablename = %s AND s.attname = a.attname)
          FROM pg_index i
          JOIN pg_class c ON c.oid = i.indexrelid
          JOIN pg_am am ON am.oid = c.relam
         WHERE i.indrelid = %s
        """,
        [table, relid],
    )
    return sum(
        compact_index_bytes(actual, method, special, rows, width)
        for actual, method, special, width in cur.fetchall()
    )


def table_info(table):
    """Sizes and estimated gain for one of our tables, or None if no such table exists."""
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT relid, pg_total_relation_size(relid), pg_relation_size(relid), pg_indexes_size(relid)
              FROM pg_stat_user_tables
             WHERE schemaname = current_schema() AND relname = %s
            """,
            [table],
        )
        found = cur.fetchone()
        if found is None:
            return None
        relid, total, heap, indexes = found
        rows, real = _live_row_estimate(cur, table, heap)
        compact_indexes = _compact_indexes_bytes(cur, relid, table, rows)
    # TOAST is left out of the gain, so the figure leans low rather than high.
    gain = max(0, heap - int(real)) + max(0, indexes - compact_indexes)
    return TableInfo(table, total, heap, indexes, int(real), gain)


def large_tables():
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT relname FROM pg_stat_user_tables
             WHERE schemaname = current_schema() AND pg_total_relation_size(relid) >= %s
            """,
            [LIST_FLOOR_BYTES],
        )
        return [row[0] for row in cur.fetchall()]


def free_disk_bytes(data_dir=None):
    """
    Free bytes on the database's disk, or None if that cannot be measured reliably.

    Without data_dir the server's own data_directory is asked for, which only means something
    when the server is on this machine, and which some database accounts may not read.
    """
    if not data_dir:
        if connection.settings_dict.get('HOST', '') not in LOCAL_HOSTS:
            return None
        try:
            with connection.cursor() as cur:
                cur.execute('SHOW data_directory')
                data_dir = cur.fetchone()[0]
        except DatabaseError:
            return None
    try:
        return shutil.disk_usage(data_dir).free
    except OSError:
        return None


def _mb(size):
    return f'{size / 1024 ** 2:,.0f} MB'


def _time_and_engine_refusals():
    reasons = []
    now = local_now()
    if in_business_hours(now):
        reasons.append(
            f'inside business hours: it is {now:%H:%M}; allowed from '
            f'{WINDOW_START_HOUR:02d}:00 to {WINDOW_END_HOUR:02d}:00 Cairo time.'
        )
    run = running_engine_run()
    if run is not None:
        reasons.append(
            f'demand engine run #{run.pk} is marked running (last activity {run.updated_at:%Y-%m-%d %H:%M}). '
            'If it is dead, opening the engine dashboard expires it after 20 idle minutes.'
        )
    return reasons


def _disk_refusal(info, data_dir):
    needed = info.total_bytes + DISK_MARGIN_BYTES
    free = free_disk_bytes(data_dir)
    if free is None:
        return 'free disk space could not be measured: pass --data-dir with the PostgreSQL data folder.'
    if free < needed:
        return f'not enough disk: {_mb(free)} free, {_mb(needed)} needed for a copy of the table.'
    return None


def _refusals(info, data_dir):
    reasons = _time_and_engine_refusals()
    disk = _disk_refusal(info, data_dir)
    if disk:
        reasons.append(disk)
    return reasons


class Command(BaseCommand):
    help = (
        'Show each large table\'s size, real data size and expected gain (dry run). '
        '--apply --table X runs VACUUM FULL on that one table; it locks the table, so it is refused '
        'during business hours or while the demand engine runs. By hand only. Do not apply on the '
        'office database just before cutover.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--table', help='Database table name, e.g. purchasing_itemdemandmetrics.')
        parser.add_argument('--apply', action='store_true', help='Run VACUUM FULL on --table.')
        parser.add_argument(
            '--data-dir',
            help='A folder on the PostgreSQL data disk, for the free-space check, when the database '
                 'account cannot read data_directory or the server is on another machine.',
        )

    def handle(self, *args, **options):
        table, data_dir = options['table'], options['data_dir']
        if options['apply'] and not table:
            raise CommandError('--apply needs --table: one table at a time.')
        if table:
            info = table_info(table)
            if info is None:
                raise CommandError(f'Table not found: {table}')
            if options['apply']:
                self._apply(info, data_dir)
                return
            self._report([info], _refusals(info, data_dir))
            return
        infos = [table_info(name) for name in large_tables()]
        infos.sort(key=lambda item: item.expected_gain, reverse=True)
        self._report(infos, _time_and_engine_refusals())
        free = free_disk_bytes(data_dir)
        self.stdout.write('Free disk: ' + (_mb(free) if free is not None else 'could not be measured'))

    def _report(self, infos, refusals):
        self.stdout.write('Dry run: nothing was changed. Real data and expected gain are estimates.')
        if infos:
            header = f'{"Table":<45}{"Total":>12}{"Rows area":>12}{"Indexes":>12}{"Real data":>12}{"Gain":>12}'
            self.stdout.write(header)
            for item in infos:
                self.stdout.write(
                    f'{item.name:<45}{_mb(item.total_bytes):>12}{_mb(item.heap_bytes):>12}'
                    f'{_mb(item.index_bytes):>12}{_mb(item.real_bytes):>12}{_mb(item.expected_gain):>12}'
                )
            self.stdout.write(f'Expected gain in total: {_mb(sum(item.expected_gain for item in infos))}')
        else:
            self.stdout.write(f'No table is over {_mb(LIST_FLOOR_BYTES)}.')
        if refusals:
            self.stdout.write('--apply would be refused now:')
            for reason in refusals:
                self.stdout.write(f'  - {reason}')

    def _apply(self, info, data_dir):
        refusals = _refusals(info, data_dir)
        if refusals:
            raise CommandError('Refused:\n  - ' + '\n  - '.join(refusals))
        if connection.in_atomic_block:
            raise CommandError('VACUUM FULL cannot run inside a transaction.')

        self.stdout.write(f'Running VACUUM FULL on {info.name} ({_mb(info.total_bytes)}). The table is locked until it ends.')
        with connection.cursor() as cur:
            cur.execute("SELECT set_config('lock_timeout', %s, false)", [f'{LOCK_TIMEOUT_MS}ms'])
            try:
                cur.execute(sql.SQL('VACUUM FULL ANALYZE {}').format(sql.Identifier(info.name)))
            except DatabaseError as exc:
                if getattr(exc.__cause__, 'pgcode', None) == '55P03':  # lock_not_available
                    raise CommandError(f'{info.name} is busy, so nothing was changed. Try again later.') from exc
                raise CommandError(f'VACUUM FULL failed on {info.name}: {exc}') from exc
            finally:
                cur.execute('RESET lock_timeout')
            cur.execute('SELECT pg_total_relation_size(%s::regclass)', [info.name])
            after = cur.fetchone()[0]
        logger.info('[reclaim_space] VACUUM FULL %s: %d -> %d bytes', info.name, info.total_bytes, after)
        self.stdout.write(self.style.SUCCESS(
            f'Reclaimed {_mb(info.total_bytes - after)} from {info.name}: '
            f'{_mb(info.total_bytes)} -> {_mb(after)} (estimated gain was {_mb(info.expected_gain)}).'
        ))
        if info.total_bytes - after < info.expected_gain / 2:
            # VACUUM FULL keeps rows deleted after the oldest transaction on the whole server began,
            # including transactions in other databases.
            self.stdout.write(self.style.WARNING(
                'That is under half the estimate. An open transaction on this PostgreSQL server, in any '
                'database, can keep deleted rows. Check pg_stat_activity for old transactions, then run again.'
            ))
