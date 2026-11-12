"""
check_schema_drift — READ-ONLY: compare every managed model with the PostgreSQL database it runs on.

A database built fresh from migrations matches the models by construction, so drift only shows on
a real, long-lived database (office, VPS). Three incidents came from that gap: notifications 0008
(legacy NOT NULL column), notifications 0028 (FK pointing at the wrong table) and users 0008
(CREATE TABLE IF NOT EXISTS skipped a column, 2026-11-03). Round-2 plan R0 step 3.

Reports, per managed model:
  missing table · missing column · NULL-ability differs · extra NOT NULL column without a default
  (a legacy column inserts will fail on).

Only SELECTs on information_schema. Exit status 1 when a finding BREAKS writes (missing table or
column, a NOT NULL the code does not expect), so it can gate a deploy. A database looser than the
code (it allows an empty value the model never saves) is reported but harmless: exit 0, unless
--strict.

    python manage.py check_schema_drift            # human report
    python manage.py check_schema_drift --json     # machine report
    python manage.py check_schema_drift --strict   # exit 1 on any difference, harmless ones too
"""
import json

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


def collect_drift():
    """[{'kind', 'table', 'column', 'detail'}] for the database `connection` points at."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT table_name, column_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = current_schema()
        """)
        db = {}
        for table, column, nullable, default in cur.fetchall():
            db.setdefault(table, {})[column] = (nullable == 'YES', default)

    found = []
    for model in apps.get_models():
        meta = model._meta
        if not meta.managed or meta.proxy or meta.swapped:
            continue
        table = meta.db_table
        cols = db.get(table)
        if cols is None:
            found.append({'kind': 'missing_table', 'table': table, 'column': '',
                          'detail': meta.label, 'breaks': True})
            continue
        known = set()
        for f in meta.local_concrete_fields:
            known.add(f.column)
            if f.column not in cols:
                found.append({'kind': 'missing_column', 'table': table, 'column': f.column,
                              'detail': f'{meta.label}.{f.name}', 'breaks': True})
                continue
            db_nullable = cols[f.column][0]
            if db_nullable != f.null and not f.primary_key:
                risk = ('BREAKS INSERTS — the database refuses an empty value the code may save'
                        if f.null else 'harmless — the database is looser than the code')
                found.append({'kind': 'nullability', 'table': table, 'column': f.column,
                              'detail': f'model null={f.null}, database null={db_nullable} ({risk})',
                              'breaks': f.null})
        for column, (nullable, default) in cols.items():
            if column not in known and not nullable and default is None:
                found.append({'kind': 'legacy_not_null', 'table': table, 'column': column,
                              'detail': 'NOT NULL, no default, unknown to the model — inserts fail',
                              'breaks': True})
    return sorted(found, key=lambda d: (d['table'], d['kind'], d['column']))


class Command(BaseCommand):
    help = 'READ-ONLY: report where the database differs from the Django models (round-2 R0).'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Print the findings as JSON.')
        parser.add_argument('--strict', action='store_true',
                            help='Exit 1 on any difference, harmless ones (database looser than the code) too.')

    def handle(self, *args, **opts):
        found = collect_drift()
        if opts['json']:
            self.stdout.write(json.dumps(found, ensure_ascii=False, indent=2))
        elif not found:
            self.stdout.write(self.style.SUCCESS(f'No drift in {connection.settings_dict["NAME"]}.'))
        else:
            self.stdout.write(f'{len(found)} difference(s) in {connection.settings_dict["NAME"]}:')
            for d in found:
                self.stdout.write(f"  [{d['kind']}] {d['table']}.{d['column']} — {d['detail']}")
        if any(d['breaks'] for d in found) or (found and opts['strict']):
            raise SystemExit(1)
