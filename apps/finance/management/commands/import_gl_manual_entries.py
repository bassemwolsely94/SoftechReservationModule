"""python manage.py import_gl_manual_entries <xlsx> [--sheet NAME] [--book cash|credit] [--preview]
[--include-mixed KEY ...] [--user USERNAME]"""
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from apps.finance.gl.drafting import system_user
from apps.finance.gl.manual_import import ParseError, import_entries, preview
from apps.users.models import StaffProfile


def _pairs(d) -> str:
    return ' '.join(f'{k}={v}' for k, v in d.items())


class Command(BaseCommand):
    help = ("Import finance's manual-only journal entries as drafts. Mixed groups are parked in the "
            'exceptions inbox; nothing is approved. --preview saves nothing.')

    def add_arguments(self, parser):
        parser.add_argument('xlsx')
        parser.add_argument('--sheet', default=None)
        parser.add_argument('--book', choices=('cash', 'credit'), default=None,
                            help='for a file without an «اليومية» column and without the book in its name')
        parser.add_argument('--preview', action='store_true', help='counts and the account list; saves nothing')
        parser.add_argument('--include-mixed', nargs='+', default=[], metavar='KEY',
                            help='import these parked groups with all their lines')
        parser.add_argument('--user', default=None,
                            help='username the drafts are created by (default: the drafting system user)')

    def handle(self, *args, **opts):
        try:
            if opts['preview']:
                self.show_preview(preview(opts['xlsx'], sheet_name=opts['sheet'], book=opts['book']))
            else:
                self.show_import(import_entries(opts['xlsx'], user=self.staff(opts['user']),
                                                include_mixed=opts['include_mixed'],
                                                sheet_name=opts['sheet'], book=opts['book']))
        except ParseError as e:
            raise CommandError(str(e))

    def staff(self, username):
        if not username:
            return system_user()
        staff = StaffProfile.objects.filter(user__username=username).first()
        if staff is None:
            raise CommandError(f'no staff profile for user {username!r}')
        return staff

    def show_skipped(self, skipped):
        if skipped:
            self.stdout.write(f"skipped rows: {_pairs(Counter(s['reason'] for s in skipped))}")

    def show_preview(self, res):
        totals = res['totals']
        self.stdout.write(f"book={res['book']} rows={totals['rows']} groups={totals['groups']} "
                          f"balanced={res['balanced_count']} merged={res['merged_count']} "
                          f"skipped_zero={res['skipped_zero']} debit={totals['debit']} credit={totals['credit']}")
        self.stdout.write(_pairs(res['counts']))
        self.show_skipped(res['skipped'])
        for ln in res['link_accounts']:
            self.stdout.write(f"link {_pairs(ln)}")
        self.stdout.write('manual accounts: ' + ' '.join(a['code'] for a in res['manual_accounts']))
        for g in res['groups']:
            if g['status'] == 'mixed':
                self.stdout.write(f"mixed {g['key']} {g['date']} accounts={','.join(g['accounts'])}")
        for w in res['warnings']:
            self.stdout.write(self.style.WARNING(f'warning: {w}'))

    def show_import(self, res):
        keys = ('book', 'imported', 'included', 'already_imported', 'parked', 'parked_existing', 'softech',
                'unbalanced', 'unknown_account', 'unknown_branch', 'before_opening', 'skipped_zero')
        self.stdout.write(_pairs({k: res[k] for k in keys}))
        self.show_skipped(res['skipped'])
        for key in res['parked_keys']:
            self.stdout.write(f'parked {key}')
        for key in res['include_unmatched']:
            self.stdout.write(self.style.WARNING(f'--include-mixed: not a mixed group in this file: {key}'))
        for f in res['failed']:
            self.stdout.write(self.style.ERROR(f"refused {f['key']}: {f['code']}"))
        for w in res['warnings']:
            self.stdout.write(self.style.WARNING(f'warning: {w}'))
