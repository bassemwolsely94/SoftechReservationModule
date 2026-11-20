"""
check_schema_drift — READ-ONLY: compare every managed model with the PostgreSQL database it runs on.

A database built fresh from migrations matches the models by construction, so drift only shows on
a real, long-lived database (office, VPS). Three incidents came from that gap: notifications 0008
(legacy NOT NULL column), notifications 0028 (FK pointing at the wrong table) and users 0008
(CREATE TABLE IF NOT EXISTS skipped a column, 2026-11-03). Round-2 plan R0 step 3.

Reports, per managed model:
  missing table · missing column · NULL-ability differs · extra NOT NULL column without a default
  (a legacy column inserts will fail on) · column narrower than the model (`column_width`: a
  varchar(n) below a CharField's max_length, or a varchar(n) where the model has a TextField —
  users 0008 left users_useractivitylog.action at varchar(20) vs max_length=30, UAT W8 2026-11-20;
  repaired by users 0063). A column WIDER than the model is reported as harmless.

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
from django.db import connection as default_connection
from django.db import models


def _width_finding(f, table, label, db_width):
    """A `column_width` finding when the database column's character length differs from the
    model's, else None. `db_width` is information_schema.character_maximum_length (None = no limit)."""
    if db_width is None:
        return None                                  # text / unlimited: never narrower
    if isinstance(f, models.TextField):
        model_width = None                           # unlimited in the model
    elif isinstance(f, models.CharField) and f.max_length:
        model_width = f.max_length
    else:
        return None
    if model_width is None or db_width < model_width:
        shown = 'text' if model_width is None else f'max_length={model_width}'
        return {'kind': 'column_width', 'table': table, 'column': f.column,
                'detail': f'{label}.{f.name}: model {shown}, database varchar({db_width}) '
                          f'(BREAKS WRITES — longer values are refused)',
                'breaks': True, 'model_width': model_width, 'db_width': db_width}
    if db_width > model_width:
        return {'kind': 'column_width', 'table': table, 'column': f.column,
                'detail': f'{label}.{f.name}: model max_length={model_width}, database '
                          f'varchar({db_width}) (harmless — the database is wider than the code)',
                'breaks': False, 'model_width': model_width, 'db_width': db_width}
    return None


def collect_drift(connection=None):
    """[{'kind', 'table', 'column', 'detail', 'breaks'}] for the database `connection` points at
    (the default database when None)."""
    connection = connection or default_connection
    with connection.cursor() as cur:
        cur.execute("""
            SELECT table_name, column_name, is_nullable, column_default, character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = current_schema()
        """)
        db = {}
        widths = {}
        for table, column, nullable, default, width in cur.fetchall():
            db.setdefault(table, {})[column] = (nullable == 'YES', default)
            widths[(table, column)] = width

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
            width = _width_finding(f, table, meta.label, widths.get((table, f.column)))
            if width:
                found.append(width)
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
            self.stdout.write(self.style.SUCCESS(f'No drift in {default_connection.settings_dict["NAME"]}.'))
        else:
            self.stdout.write(f'{len(found)} difference(s) in {default_connection.settings_dict["NAME"]}:')
            for d in found:
                self.stdout.write(f"  [{d['kind']}] {d['table']}.{d['column']} — {d['detail']}")
        if any(d['breaks'] for d in found) or (found and opts['strict']):
            raise SystemExit(1)
