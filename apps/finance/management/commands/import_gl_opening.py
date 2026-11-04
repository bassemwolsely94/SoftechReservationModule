"""python manage.py import_gl_opening <xlsx> --closing-stock N --user USERNAME [--sheet NAME] [--dry-run]"""
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from apps.finance.gl.coa_import import parse_trial_balance_sheet_with_warnings
from apps.finance.gl.ledger import LedgerError
from apps.finance.gl.opening import _check_closing_stock, build_opening_lines, post_opening
from apps.users.models import StaffProfile


class Command(BaseCommand):
    help = 'Post the 1-1-2026 opening entry from the 31-12-2025 trial balance.'

    def add_arguments(self, parser):
        parser.add_argument('xlsx')
        parser.add_argument('--closing-stock', required=True)
        parser.add_argument('--user', required=True, help='username of the posting staff member')
        parser.add_argument('--sheet', default=None)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        try:
            closing = _check_closing_stock(Decimal(opts['closing_stock']))
        except (InvalidOperation, LedgerError):
            raise CommandError('--closing-stock must be a positive number with at most 2 decimals')
        staff = StaffProfile.objects.filter(user__username=opts['user']).first()
        if staff is None:
            raise CommandError(f"no staff profile for user {opts['user']!r}")
        try:
            rows, warnings = parse_trial_balance_sheet_with_warnings(opts['xlsx'], opts['sheet'])
            for w in warnings:
                self.stdout.write(self.style.WARNING(f'warning: {w}'))
            if opts['dry_run']:
                lines = build_opening_lines(rows, closing)
                for ln in lines:
                    self.stdout.write(f"{ln['account_code']}  debit={ln['debit']}  credit={ln['credit']}")
                self.stdout.write(
                    f"[dry-run] lines={len(lines)} total debit={sum(l['debit'] for l in lines)} "
                    f"total credit={sum(l['credit'] for l in lines)}")
                return
            entry = post_opening(opts['xlsx'], closing_stock=closing, user=staff,
                                 sheet_name=opts['sheet'])
        except LedgerError as e:
            raise CommandError(f'{e} {e.detail}')
        self.stdout.write(f'posted opening entry {entry.number} ({entry.lines.count()} lines)')
