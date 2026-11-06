"""python manage.py gl_validate_workbook <xlsx> [--through 2026-08-31] [--out report.xlsx]

Compare the ledger (approved + reversed entries, 2026-01-01..through) with finance's workbook:
per account and branch, per month, and per supplier / creditor / customer / employee. Read-only.
Exit 1 while any difference or unmapped branch remains.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.finance.gl.validation import DEFAULT_THROUGH, WorkbookError, export_validation, validate


def _date(text):
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise CommandError('--through must be a date as YYYY-MM-DD')


class Command(BaseCommand):
    help = "Validate the ledger against finance's workbook (.xlsx only). Exit 1 while differences remain."

    def add_arguments(self, parser):
        parser.add_argument('xlsx')
        parser.add_argument('--through', type=_date, default=DEFAULT_THROUGH)
        parser.add_argument('--out', default=None, help='write the differences as an xlsx for finance')

    def handle(self, *args, **opts):
        try:
            res = validate(opts['xlsx'], through=opts['through'])
        except WorkbookError as e:
            raise CommandError(e.message)
        totals = res['totals']
        self.stdout.write(f"through={res['through']} differences={totals['differences']} "
                          f"(branch={len(res['ytd'])} monthly={len(res['monthly'])} parties={len(res['parties'])})")
        for t in totals['parties']:
            self.stdout.write(f"{t['kind']} account={t['account']} ledger={t['ledger']} workbook={t['workbook']} "
                              f"difference={t['difference']}")
        for label in res['unmapped_branches']:
            self.stdout.write(self.style.WARNING(f'unmapped branch: {label}'))
        for code in res['unknown_accounts']:
            self.stdout.write(self.style.WARNING(f'unknown account: {code}'))
        for sheet in res['missing_sheets']:
            self.stdout.write(self.style.WARNING(f'party sheet not in the file: {sheet}'))
        if res['unmapped_parties']:
            self.stdout.write(self.style.WARNING(f"workbook parties without a GLParty row: {len(res['unmapped_parties'])}"))
        if opts['out']:
            with open(opts['out'], 'wb') as f:
                f.write(export_validation(res))
            self.stdout.write(f"report written to {opts['out']}")
        if totals['differences'] or res['unmapped_branches']:
            raise CommandError('differences remain between the ledger and the workbook')
