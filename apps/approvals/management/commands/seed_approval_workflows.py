"""
python manage.py seed_approval_workflows

Seeds default ApprovalWorkflowDefinition + ApprovalStepDefinition rows
for all platform modules that use the generic approval engine.

Safe to re-run:  uses update_or_create on (code, order).
"""
from django.core.management.base import BaseCommand
from apps.approvals.models import ApprovalWorkflowDefinition, ApprovalStepDefinition


WORKFLOWS = [
    # ── HR Module ────────────────────────────────────────────────────────────
    {
        'code':             'leave_request',
        'name':             'Leave Request',
        'name_ar':          'طلب إجازة',
        'description':      'Annual, sick, emergency and unpaid leave requests.',
        'reject_terminates': True,
        'sla_hours':        48,
        'steps': [
            {
                'order': 1, 'name': 'Branch Manager Approval', 'name_ar': 'موافقة مدير الفرع',
                'approver_role': 'supervisor', 'restrict_to_branch': True,
                'escalation_hours': 24, 'on_reject': 'terminate',
            },
            {
                'order': 2, 'name': 'HR Final Approval', 'name_ar': 'الاعتماد النهائي من HR',
                'approver_role': 'admin', 'restrict_to_branch': False,
                'escalation_hours': 24, 'on_reject': 'terminate',
            },
        ],
    },
    {
        'code':             'emergency_leave',
        'name':             'Emergency Leave',
        'name_ar':          'إجازة طارئة',
        'description':      'Single-step fast approval for same-day emergencies.',
        'reject_terminates': True,
        'sla_hours':        4,
        'steps': [
            {
                'order': 1, 'name': 'Supervisor Approval', 'name_ar': 'موافقة المشرف',
                'approver_role': 'supervisor', 'restrict_to_branch': True,
                'escalation_hours': 2, 'on_reject': 'terminate',
            },
        ],
    },
    {
        'code':             'salary_advance',
        'name':             'Salary Advance',
        'name_ar':          'سلفة راتب',
        'description':      'Employee salary advance requests.',
        'reject_terminates': True,
        'sla_hours':        72,
        'steps': [
            {
                'order': 1, 'name': 'Supervisor Approval', 'name_ar': 'موافقة المشرف',
                'approver_role': 'supervisor', 'restrict_to_branch': True,
                'escalation_hours': 24, 'on_reject': 'terminate',
            },
            {
                'order': 2, 'name': 'Finance Approval', 'name_ar': 'موافقة المالية',
                'approver_role': 'purchasing', 'restrict_to_branch': False,
                'escalation_hours': 24, 'on_reject': 'terminate',
            },
        ],
    },
    {
        'code':             'expense_claim',
        'name':             'Expense Claim',
        'name_ar':          'مطالبة مصروفات',
        'description':      'Employee expense reimbursement requests (receipts required).',
        'reject_terminates': True,
        'sla_hours':        96,
        'steps': [
            {
                'order': 1, 'name': 'Branch Manager Review', 'name_ar': 'مراجعة مدير الفرع',
                'approver_role': 'supervisor', 'restrict_to_branch': True,
                'escalation_hours': 48, 'on_reject': 'terminate',
            },
            {
                'order': 2, 'name': 'Finance Final Approval', 'name_ar': 'الاعتماد النهائي من المالية',
                'approver_role': 'purchasing', 'restrict_to_branch': False,
                'escalation_hours': 48, 'on_reject': 'terminate',
            },
        ],
    },
    {
        'code':             'mamoriya',
        'name':             'Business Trip',
        'name_ar':          'مأمورية',
        'description':      'Business trip authorization and expense settlement.',
        'reject_terminates': True,
        'sla_hours':        48,
        'steps': [
            {
                'order': 1, 'name': 'Supervisor Authorization', 'name_ar': 'تفويض المشرف',
                'approver_role': 'supervisor', 'restrict_to_branch': True,
                'escalation_hours': 24, 'on_reject': 'terminate',
            },
            {
                'order': 2, 'name': 'Finance Settlement', 'name_ar': 'تسوية المالية',
                'approver_role': 'purchasing', 'restrict_to_branch': False,
                'escalation_hours': 48, 'on_reject': 'terminate',
                'is_optional': True,
            },
        ],
    },
    {
        'code':             'overtime',
        'name':             'Overtime Request',
        'name_ar':          'طلب عمل إضافي',
        'description':      'Employee overtime authorization.',
        'reject_terminates': True,
        'sla_hours':        24,
        'steps': [
            {
                'order': 1, 'name': 'Supervisor Approval', 'name_ar': 'موافقة المشرف',
                'approver_role': 'supervisor', 'restrict_to_branch': True,
                'escalation_hours': 12, 'on_reject': 'terminate',
            },
        ],
    },
    {
        'code':             'mission_permit',
        'name':             'Mission Permit',
        'name_ar':          'اذن مأمورية',
        'description':      'Permission to leave the branch for a work errand (time window).',
        'reject_terminates': True,
        'sla_hours':        8,
        'steps': [
            {
                'order': 1, 'name': 'Supervisor Approval', 'name_ar': 'موافقة المشرف',
                'approver_role': 'supervisor', 'restrict_to_branch': True,
                'escalation_hours': 4, 'on_reject': 'terminate',
            },
        ],
    },
    {
        'code':             'shift_change',
        'name':             'Shift Change Permit',
        'name_ar':          'اذن تعديل شيفت',
        'description':      'Request to modify the working period on a given day; approved output is the shift-modification notice.',
        'reject_terminates': True,
        'sla_hours':        24,
        'steps': [
            {
                'order': 1, 'name': 'Branch Manager Approval', 'name_ar': 'موافقة مدير الفرع',
                'approver_role': 'supervisor', 'restrict_to_branch': True,
                'escalation_hours': 12, 'on_reject': 'terminate',
            },
            {
                'order': 2, 'name': 'HR / Admin Approval', 'name_ar': 'اعتماد الإدارة',
                'approver_role': 'admin', 'restrict_to_branch': False,
                'escalation_hours': 24, 'on_reject': 'terminate',
            },
        ],
    },

    # ── Finance / Payment Module ──────────────────────────────────────────────
    {
        'code':             'payment_exception',
        'name':             'Payment Exception Review',
        'name_ar':          'مراجعة استثناء مدفوعات',
        'description':      'Flagged payment exceptions requiring manual review and resolution.',
        'reject_terminates': False,
        'sla_hours':        24,
        'steps': [
            {
                'order': 1, 'name': 'Branch Supervisor Review', 'name_ar': 'مراجعة مشرف الفرع',
                'approver_role': 'supervisor', 'restrict_to_branch': True,
                'escalation_hours': 12, 'on_reject': 'next_step',
            },
            {
                'order': 2, 'name': 'Finance Resolution', 'name_ar': 'حل من المالية',
                'approver_role': 'purchasing', 'restrict_to_branch': False,
                'escalation_hours': 12, 'on_reject': 'terminate',
            },
        ],
    },

    # ── FEFO / Batch Module ───────────────────────────────────────────────────
    {
        'code':             'supplier_claim',
        'name':             'Supplier Expiry Claim',
        'name_ar':          'مطالبة مورد — منتهية الصلاحية',
        'description':      'Near-expiry or expired batch return/claim to supplier.',
        'reject_terminates': True,
        'sla_hours':        120,
        'steps': [
            {
                'order': 1, 'name': 'Pharmacist Review', 'name_ar': 'مراجعة الصيدلاني',
                'approver_role': 'pharmacist', 'restrict_to_branch': True,
                'escalation_hours': 48, 'on_reject': 'terminate',
            },
            {
                'order': 2, 'name': 'Purchasing Approval', 'name_ar': 'موافقة المشتريات',
                'approver_role': 'purchasing', 'restrict_to_branch': False,
                'escalation_hours': 48, 'on_reject': 'terminate',
            },
        ],
    },
    {
        'code':             'batch_quarantine',
        'name':             'Batch Quarantine Authorization',
        'name_ar':          'تفويض عزل دفعة',
        'description':      'Authorize quarantining a batch pending investigation.',
        'reject_terminates': True,
        'sla_hours':        8,
        'steps': [
            {
                'order': 1, 'name': 'Quality Manager Approval', 'name_ar': 'موافقة مدير الجودة',
                'approver_role': 'quality_manager', 'restrict_to_branch': False,
                'escalation_hours': 4, 'on_reject': 'terminate',
            },
        ],
    },
]


# HR workflows live in their own bucket so the operational approvals inbox can
# exclude them. Everything else defaults to 'operational'.
HR_CODES = {
    'leave_request', 'emergency_leave', 'salary_advance',
    'expense_claim', 'mamoriya', 'overtime',
    'mission_permit', 'shift_change',
}


class Command(BaseCommand):
    help = 'Seed default approval workflow definitions and steps'

    def handle(self, *args, **options):
        created_wf = updated_wf = created_steps = updated_steps = 0

        for wf_data in WORKFLOWS:
            # Work on copies so the module-level WORKFLOWS list is never mutated
            # (keeps the command re-entrant — safe to call repeatedly in one process,
            # e.g. across test setUps).
            wf_fields = {k: v for k, v in wf_data.items() if k != 'steps'}
            wf_fields.setdefault('category', 'hr' if wf_data['code'] in HR_CODES else 'operational')

            wf, created = ApprovalWorkflowDefinition.objects.update_or_create(
                code=wf_data['code'],
                defaults=wf_fields,
            )
            if created:
                created_wf += 1
            else:
                updated_wf += 1

            # Every HR workflow keeps its mandatory role-based manager step(s) and
            # gains a requester-nominated approver step LAST (any one nominee
            # approves; auto-skipped when none picked, so the common self-service
            # case behaves exactly as before).
            steps = wf_data['steps']
            if wf_data['code'] in HR_CODES:
                last_order = max(s['order'] for s in steps)
                nominated = {
                    'order': last_order + 1, 'name': 'Chosen Approver', 'name_ar': 'المعتمِد المختار',
                    'escalation_hours': 0, 'on_reject': 'terminate',
                    'use_nominated_approvers': True,
                }
                steps = steps + [nominated]

            for step_data in steps:
                sd = dict(step_data)
                order = sd.pop('order')
                is_opt = sd.pop('is_optional', False)
                # Always set use_nominated_approvers explicitly so role steps are
                # reset to False on re-seed (update_or_create only touches defaults).
                use_nom = sd.pop('use_nominated_approvers', False)
                _, step_created = ApprovalStepDefinition.objects.update_or_create(
                    workflow=wf,
                    order=order,
                    defaults={**sd, 'is_optional': is_opt, 'use_nominated_approvers': use_nom},
                )
                if step_created:
                    created_steps += 1
                else:
                    updated_steps += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done — workflows: {created_wf} created / {updated_wf} updated | '
            f'steps: {created_steps} created / {updated_steps} updated'
        ))
