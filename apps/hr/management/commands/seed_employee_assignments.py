"""
Give every employee that has no assignment history its first row (from start_date, else
SEED_EPOCH). Idempotent: employees that already have rows are skipped.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.hr import assignments
from apps.hr.models import Employee


class Command(BaseCommand):
    help = 'Seed the first employee assignment row for employees that have none (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Count only; write nothing.')

    def handle(self, *args, **opts):
        total = Employee.objects.count()
        seeded = 0
        for emp in Employee.objects.filter(assignments__isnull=True):
            if not opts['dry_run']:
                assignments.record_assignment(emp, on=timezone.localdate(), source='seed')
            seeded += 1
        verb = 'would seed' if opts['dry_run'] else 'seeded'
        self.stdout.write(f'{verb} {seeded} of {total} employees')
