"""
One-time HR employee import from the payroll workbook. Dry-run by default; --apply writes.
Prints counts and errors only, never names or other workbook values.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.hr.attendance import employee_import


class Command(BaseCommand):
    help = 'Import the HR employee list from the payroll workbook (dry-run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--apply', action='store_true', help='Write the employees (default: dry-run).')

    def handle(self, *args, **opts):
        try:
            preview = employee_import.read_workbook(opts['path'])
        except OSError as exc:
            raise CommandError(f'Cannot open workbook: {type(exc).__name__}')
        self.stdout.write(f'rows: {len(preview.rows)}, errors: {len(preview.errors)}')
        for err in preview.errors:
            self.stdout.write(f'  {err}')
        if preview.errors:
            raise CommandError('Fix the errors above first; nothing was written.')
        if not opts['apply']:
            self.stdout.write('Dry-run: nothing written. Re-run with --apply to import.')
            return
        res = employee_import.apply(preview, None)
        self.stdout.write(f"created {res['created']}, updated {res['updated']}, "
                          f"branch matched {res['branch_matched']}")
