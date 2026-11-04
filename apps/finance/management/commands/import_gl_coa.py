"""python manage.py import_gl_coa <xlsx> [--sheet NAME] [--dry-run]"""
from django.core.management.base import BaseCommand

from apps.finance.gl.coa_import import import_coa, parse_trial_balance_sheet_with_warnings


class Command(BaseCommand):
    help = "Import the GL chart of accounts from finance's trial-balance workbook."

    def add_arguments(self, parser):
        parser.add_argument('xlsx')
        parser.add_argument('--sheet', default=None)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        rows, warnings = parse_trial_balance_sheet_with_warnings(opts['xlsx'], opts['sheet'])
        for w in warnings:
            self.stdout.write(self.style.WARNING(w))
        res = import_coa(rows, user=None, dry_run=opts['dry_run'])
        prefix = '[dry-run] ' if opts['dry_run'] else ''
        self.stdout.write(f'{prefix}rows={len(rows)} created={res.created} updated={res.updated}')
        if res.unknown_groups:
            self.stdout.write(self.style.WARNING(f'unknown groups: {res.unknown_groups}'))
