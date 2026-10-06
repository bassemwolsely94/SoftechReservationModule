"""
python manage.py seed_hr_config

Seeds default LeaveType rows.
Safe to re-run — uses update_or_create on code.
"""
from django.core.management.base import BaseCommand
from apps.hr.models import LeaveType

LEAVE_TYPES = [
    {
        'code': 'annual',
        'name': 'Annual Leave',
        'name_ar': 'إجازة سنوية',
        'is_paid': True,
        'accrues_balance': True,
        'max_days_per_year': 21,
        'max_days_per_request': 14,
        'approval_workflow_code': 'leave_request',
    },
    {
        'code': 'sick',
        'name': 'Sick Leave',
        'name_ar': 'إجازة مرضية',
        'is_paid': True,
        'accrues_balance': True,
        'max_days_per_year': 180,
        'max_days_per_request': 30,
        'approval_workflow_code': 'leave_request',
    },
    {
        'code': 'emergency',
        'name': 'Emergency Leave',
        'name_ar': 'إجازة طارئة',
        'is_paid': True,
        'accrues_balance': False,
        'max_days_per_year': 6,
        'max_days_per_request': 3,
        'approval_workflow_code': 'emergency_leave',
    },
    {
        'code': 'unpaid',
        'name': 'Unpaid Leave',
        'name_ar': 'إجازة بدون مرتب',
        'is_paid': False,
        'accrues_balance': False,
        'max_days_per_year': 90,
        'max_days_per_request': 30,
        'approval_workflow_code': 'leave_request',
    },
    {
        'code': 'study',
        'name': 'Study Leave',
        'name_ar': 'إجازة دراسية',
        'is_paid': True,
        'accrues_balance': False,
        'max_days_per_year': 30,
        'max_days_per_request': 14,
        'approval_workflow_code': 'leave_request',
    },
    {
        'code': 'maternity',
        'name': 'Maternity Leave',
        'name_ar': 'إجازة أمومة',
        'is_paid': True,
        'accrues_balance': False,
        'max_days_per_year': 90,
        'max_days_per_request': 90,
        'approval_workflow_code': 'leave_request',
    },
    {
        'code': 'hajj',
        'name': 'Hajj Leave',
        'name_ar': 'إجازة الحج',
        'is_paid': True,
        'accrues_balance': False,
        'max_days_per_year': 30,
        'max_days_per_request': 30,
        'approval_workflow_code': 'leave_request',
    },
]


class Command(BaseCommand):
    help = 'Seed default HR leave types'

    def handle(self, *args, **options):
        created = updated = 0
        for data in LEAVE_TYPES:
            code = data.pop('code')
            _, was_created = LeaveType.objects.update_or_create(
                code=code, defaults=data,
            )
            data['code'] = code          # restore for safety
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(self.style.SUCCESS(
            f'Done — {created} leave types created, {updated} updated.'
        ))
