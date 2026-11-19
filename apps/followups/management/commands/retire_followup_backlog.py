"""
Retire an old open follow-up backlog (Top-10 C09) — DRY RUN unless --apply.

    python manage.py retire_followup_backlog                          # what would close (nothing saved)
    python manage.py retire_followup_backlog --older-than-days 30     # due more than 30 days ago
    python manage.py retire_followup_backlog --created-before 2026-06-01
    python manage.py retire_followup_backlog --apply                  # do it

Open generated refill / chronic tasks only (never call-list or pinned tasks). Each first gets the normal
ERP auto-close; the rest are CANCELLED with a reason (never deleted; not counted as "missed"). One
AuditLog row lists the closed task ids. Local DB only — no SOFTECH, no messages.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Close (cancel, with a reason) old open refill follow-up tasks. Dry run unless --apply.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Really close them (default: dry run)')
        parser.add_argument('--dry-run', action='store_true', help='Explicit dry run (the default)')
        parser.add_argument('--older-than-days', type=int, default=60,
                            help='Due date passed more than this many days ago (default 60)')
        parser.add_argument('--created-before', default='', help='Only tasks created before YYYY-MM-DD')

    def handle(self, *args, **opts):
        from apps.followups.services import retire_backlog
        if opts['apply'] and opts['dry_run']:
            raise CommandError('--apply and --dry-run together: choose one')
        if opts['older_than_days'] < 1:
            raise CommandError('--older-than-days must be at least 1')
        created_before = None
        if opts['created_before']:
            try:
                created_before = dt.date.fromisoformat(opts['created_before'])
            except ValueError as exc:
                raise CommandError('--created-before must be YYYY-MM-DD') from exc
        res = retire_backlog(older_than_days=opts['older_than_days'], created_before=created_before,
                             dry_run=not opts['apply'])
        self.stdout.write(f'due before {res["cutoff"]}: {res["open_matching"]} open tasks '
                          f'(by month created: {res["by_created_month"]})')
        if res['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN — nothing saved. ERP auto-close would close {res["would_auto_close"]} open task(s) '
                f'with a later sale; the rest of the {res["open_matching"]} would be cancelled. Re-run with --apply.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'auto-closed (bought) {res["auto_closed"]} · cancelled {res["cancelled"]} — audited'))
