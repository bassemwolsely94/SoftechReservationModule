"""
apps/followups/management/commands/generate_followup_tasks.py

Usage:
    python manage.py generate_followup_tasks              # full pipeline
    python manage.py generate_followup_tasks --dry-run    # preview only
    python manage.py generate_followup_tasks --branch 5   # one branch
    python manage.py generate_followup_tasks --infer      # infer chronic profiles first
    python manage.py generate_followup_tasks --grace-days 9999   # retroactive
    python manage.py generate_followup_tasks --escalate-only     # escalate overdue → missed only
    python manage.py generate_followup_tasks --overdue-days 5    # custom escalation threshold

Pipeline (runs in order):
  1. [optional] Infer ChronicMedicationProfile from ERP history
  2. Generate new FollowUpTask rows for customers whose refill is due
  3. Auto-close tasks where ERP confirms the patient already bought
  4. Escalate overdue pending/called tasks → 'missed'
     ↑ This step is what feeds the churn score in segment_customers.
       Without it, missed refills never reach Customer.churn_score.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate, auto-close, and escalate chronic refill follow-up tasks'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run',        action='store_true',
            help='Preview only — do not write anything')
        parser.add_argument('--branch',         type=int, default=None,
            help='Limit to a single branch ID')
        parser.add_argument('--infer',          action='store_true',
            help='Infer chronic profiles from ERP purchase history first')
        parser.add_argument('--grace-days',     type=int, default=14,
            help='Days past refill date to still create a task (default 14; 9999 = retroactive)')
        parser.add_argument('--escalate-only',  action='store_true',
            help='Skip task generation — only escalate overdue tasks to missed')
        parser.add_argument('--overdue-days',   type=int, default=3,
            help='Days past due_date before a task is marked missed (default 3)')

    def handle(self, *args, **options):
        from apps.followups.services import (
            generate_followup_tasks_bulk,
            infer_chronic_profiles_from_erp,
            auto_close_followup_tasks_from_erp,
            escalate_overdue_tasks,
        )
        from apps.branches.models import Branch

        dry_run       = options['dry_run']
        branch_id     = options['branch']
        grace_days    = options['grace_days']
        overdue_days  = options['overdue_days']
        escalate_only = options['escalate_only']
        branch        = None

        if branch_id:
            try:
                branch = Branch.objects.get(pk=branch_id)
                self.stdout.write(f'  Branch: {branch.name_ar or branch.name}')
            except Branch.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Branch {branch_id} not found'))
                return

        # ── Step 1: Infer chronic profiles ────────────────────────────────────
        if options['infer'] and not escalate_only:
            self.stdout.write('→ Inferring chronic profiles from ERP history…')
            count = infer_chronic_profiles_from_erp()
            self.stdout.write(self.style.SUCCESS(f'  ✓ {count} profiles created/updated'))

        # ── Step 2: Generate new tasks ────────────────────────────────────────
        if not escalate_only:
            tag = '  [DRY RUN]' if dry_run else ''
            self.stdout.write(f'→ Generating follow-up tasks{tag} (grace: {grace_days}d)…')
            count = generate_followup_tasks_bulk(
                branch=branch, dry_run=dry_run, grace_days=grace_days,
            )
            if dry_run:
                self.stdout.write(self.style.WARNING(
                    f'  Would create {count} tasks — nothing saved'
                ))
            else:
                self.stdout.write(self.style.SUCCESS(f'  ✓ {count} tasks created'))

        # ── Step 3: Auto-close tasks (ERP confirmed purchase) ─────────────────
        if not dry_run and not escalate_only:
            self.stdout.write('→ Auto-closing tasks from recent ERP sales…')
            closed = auto_close_followup_tasks_from_erp(since_minutes=60 * 24)
            self.stdout.write(self.style.SUCCESS(f'  ✓ {closed} tasks auto-closed'))

        # ── Step 4: Escalate overdue → missed ────────────────────────────────
        # This is the most important step for churn scoring accuracy.
        # Tasks that sit pending past overdue_days with no response = missed refill.
        self.stdout.write(
            f'→ Escalating overdue tasks → missed '
            f'(threshold: {overdue_days}d past due){"  [DRY RUN]" if dry_run else ""}…'
        )
        result = escalate_overdue_tasks(overdue_days=overdue_days, dry_run=dry_run)
        verb = 'Would escalate' if dry_run else 'Escalated'
        self.stdout.write(self.style.SUCCESS(
            f'  ✓ {verb} {result["escalated"]} tasks → missed '
            f'(total missed in DB: {result["already_missed"] + (0 if dry_run else result["escalated"])})'
        ))
