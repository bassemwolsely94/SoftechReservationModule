"""
check_column_widths — READ-ONLY: list every column whose character length differs from the model.

The `column_width` slice of `check_schema_drift` (UAT W8, 2026-11-20: users_useractivitylog.action
was varchar(20) on the office database while the model says max_length=30, so 'mfa_devices_forgotten'
could not be stored and forget-devices answered 500). Narrower than the model BREAKS writes (exit 1);
wider is harmless and only reported.

Only SELECTs on information_schema.

    python manage.py check_column_widths                  # default database
    python manage.py check_column_widths --database other # any alias in DATABASES
    python manage.py check_column_widths --json
"""
import json

from django.core.management.base import BaseCommand
from django.db import connections

from .check_schema_drift import collect_drift


def collect_widths(connection=None):
    return [d for d in collect_drift(connection) if d['kind'] == 'column_width']


class Command(BaseCommand):
    help = 'READ-ONLY: report columns whose varchar width differs from the model max_length.'

    def add_arguments(self, parser):
        parser.add_argument('--database', default='default', help='DATABASES alias to check.')
        parser.add_argument('--json', action='store_true', help='Print the findings as JSON.')

    def handle(self, *args, **opts):
        conn = connections[opts['database']]
        found = collect_widths(conn)
        name = conn.settings_dict['NAME']
        if opts['json']:
            self.stdout.write(json.dumps(found, ensure_ascii=False, indent=2))
        elif not found:
            self.stdout.write(self.style.SUCCESS(f'Every column is at least as wide as its model in {name}.'))
        else:
            self.stdout.write(f'{len(found)} width difference(s) in {name}:')
            for d in found:
                self.stdout.write(f"  {d['table']}.{d['column']} — {d['detail']}")
        if any(d['breaks'] for d in found):
            raise SystemExit(1)
