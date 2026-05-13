"""
apps/followups/management/commands/generate_followup_tasks.py

Usage:
    python manage.py generate_followup_tasks              # today's due tasks only
    python manage.py generate_followup_tasks --dry-run    # preview only
    python manage.py generate_followup_tasks --branch 5   # one branch
    python manage.py generate_followup_tasks --infer      # infer chronic profiles first
    python manage.py generate_followup_tasks --grace-days 9999  # generate retroactively
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate follow-up tasks for chronic medication refills from ERP history'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run',    action='store_true',
            help='Preview only — do not create tasks')
        parser.add_argument('--branch',     type=int, default=None,
            help='Branch ID to limit scope')
        parser.add_argument('--infer',      action='store_true',
            help='Infer chronic profiles from ERP first')
        parser.add_argument('--grace-days', type=int, default=14,
            help='Days past refill to still create tasks (default 14, use 9999 for retroactive)')

    def handle(self, *args, **options):
        from apps.followups.services import (
            generate_followup_tasks_bulk,
            infer_chronic_profiles_from_erp,
            auto_close_followup_tasks_from_erp,
        )
        from apps.branches.models import Branch

        dry_run    = options['dry_run']
        branch_id  = options['branch']
        grace_days = options['grace_days']
        branch     = None

        if branch_id:
            try:
                branch = Branch.objects.get(pk=branch_id)
                self.stdout.write(f'  Branch filter: {branch.name_ar or branch.name}')
            except Branch.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Branch {branch_id} not found'))
                return

        if options['infer']:
            self.stdout.write('→ Inferring chronic profiles from ERP history...')
            count = infer_chronic_profiles_from_erp()
            self.stdout.write(self.style.SUCCESS(f'  ✓ {count} profiles created/updated'))

        self.stdout.write(
            f'→ Generating follow-up tasks'
            f'{"  [DRY RUN]" if dry_run else ""} '
            f'(grace window: {grace_days} days)...'
        )
        count = generate_followup_tasks_bulk(
            branch=branch, dry_run=dry_run, grace_days=grace_days
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'  Would create {count} tasks (dry run — nothing saved)')
            )
        else:
            self.stdout.write(self.style.SUCCESS(f'  ✓ {count} tasks created'))

        if not dry_run:
            self.stdout.write('→ Auto-closing tasks from recent ERP sales...')
            closed = auto_close_followup_tasks_from_erp(since_minutes=60 * 24)
            self.stdout.write(self.style.SUCCESS(f'  ✓ {closed} tasks auto-closed'))
