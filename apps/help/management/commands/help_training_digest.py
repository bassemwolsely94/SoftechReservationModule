"""Send the weekly training digest to supervisors (help/edit). Runs from the scheduler
every Sunday; --dry-run prints what each supervisor would get without sending."""
from django.core.management.base import BaseCommand

from apps.help import digest


class Command(BaseCommand):
    help = 'Weekly training digest for supervisors (who finished, who is stuck, failed quizzes).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        sent = digest.send_weekly(dry_run=opts['dry_run'])
        for sup, title, body in sent:
            self.stdout.write(f'--- {sup} ---\n{title}\n{body}\n')
        self.stdout.write(f"{len(sent)} digest(s) {'prepared (dry run)' if opts['dry_run'] else 'sent'}.")
