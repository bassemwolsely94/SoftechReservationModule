"""
apps/data_lifecycle/health.py

The daily DataHealthSnapshot (design §6 Stage 5): database size, reclaimable empty space, media size by folder
and by type, disk space and the problem counts. Company-level; sizes and counts only. Reads PostgreSQL's
catalog, the media folder and local mirrors; no SOFTECH. take_snapshot never raises: a missing snapshot must not
fail the daily retention run.
"""
import logging
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import problems, runner
from .models import DataHealthSnapshot
from .references import build_reference_index, normalise

logger = logging.getLogger('elrezeiky.sync')

UNREFERENCED = 'unreferenced'
BUNDLE_PAGES = 'invoice_bundles/pages'


def _folder_of(rel):
    if rel.startswith(BUNDLE_PAGES + '/'):
        return BUNDLE_PAGES
    parts = rel.split('/')
    return parts[0] if len(parts) > 1 else '.'


def _type_key(rel, index):
    refs = index.get(rel)
    if not refs:
        return UNREFERENCED
    first = sorted(refs, key=lambda r: (r.model, r.field, str(r.pk)))[0]
    return f'{first.model}.{first.field}'


def _add(bucket, key, size):
    entry = bucket.setdefault(key, {'bytes': 0, 'files': 0})
    entry['bytes'] += size
    entry['files'] += 1


def scan_media(index):
    """(total_bytes, files, by_folder, by_type) for everything under MEDIA_ROOT. A missing root gives zeros."""
    root = str(settings.MEDIA_ROOT)
    total, files, by_folder, by_type = 0, 0, {}, {}
    if not os.path.isdir(root):
        return total, files, by_folder, by_type
    stack = [(root, '')]
    while stack:
        directory, prefix = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    rel = f'{prefix}{entry.name}'
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append((entry.path, rel + '/'))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        size = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
                    norm = normalise(rel)
                    total += size
                    files += 1
                    _add(by_folder, _folder_of(norm), size)
                    _add(by_type, _type_key(norm, index), size)
        except OSError:
            logger.warning('[data-health] could not read a media folder')
    return total, files, by_folder, by_type


def _db_bytes():
    with connection.cursor() as cur:
        cur.execute('SELECT pg_database_size(current_database())')
        return int(cur.fetchone()[0])


def _empty_space():
    """(total, {table: bytes}) from reclaim_space's estimate, tables at or above the snapshot minimum."""
    from apps.sync.management.commands.reclaim_space import table_info
    with connection.cursor() as cur:
        cur.execute(
            """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE c.relkind = 'r' AND n.nspname = current_schema()
                 AND pg_total_relation_size(c.oid) >= %s ORDER BY 1""", [runner.TABLE_SIZE_MIN_BYTES])
        tables = [row[0] for row in cur.fetchall()]
    by_table = {}
    for table in tables:
        try:
            info = table_info(table)
        except Exception as exc:
            logger.error('[data-health] empty space for %s failed: %s', table, type(exc).__name__)
            continue
        if info is not None and info.expected_gain > 0:
            by_table[table] = int(info.expected_gain)
    return sum(by_table.values()), by_table


def _disk():
    """(total, free) of the disk holding MEDIA_ROOT, measured at its nearest existing folder (a fresh install may
    not have created it yet). (0, 0) means unknown; the screen then shows no disk figure and no forecast date."""
    try:
        path = Path(settings.MEDIA_ROOT).resolve()
        while not path.exists() and path.parent != path:
            path = path.parent
        usage = shutil.disk_usage(str(path))
        return usage.total, usage.free
    except Exception:
        return 0, 0


def take_snapshot(include_tables=False):
    """Today's DataHealthSnapshot (update_or_create on the local date), or None when it failed. Never raises.
    include_tables=True first refreshes the table sizes: used by the forced refresh only."""
    try:
        if include_tables:
            runner.snapshot_table_sizes()
        total, files, by_folder, by_type = scan_media(build_reference_index())
        empty_total, empty_by_table = _empty_space()
        disk_total, disk_free = _disk()
        snapshot, _ = DataHealthSnapshot.objects.update_or_create(day=timezone.localdate(), defaults={
            'taken_at': timezone.now(),
            'db_bytes': _db_bytes(),
            'empty_bytes': empty_total,
            'media_bytes': total,
            'media_files': files,
            'disk_total_bytes': disk_total,
            'disk_free_bytes': disk_free,
            'empty_by_table': empty_by_table,
            'media_by_folder': by_folder,
            'media_by_type': by_type,
            'problems': problems.count_all(),
        })
        return snapshot
    except Exception:
        logger.exception('[data-health] snapshot failed')
        return None
