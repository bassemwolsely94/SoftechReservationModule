"""
Seed the بدل defaults (doc 25 §16.1, owner D2) — idempotent, never overwrites an owner edit:

  • ReplacementRule v1 rows (only created when the rule_key has NO version yet)
  • approval workflows replacement_supervisor (1 step) / replacement_manager (2 steps)

    python manage.py seed_replacement
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.replacement.models import ReplacementRule

A, B1, B2 = 'insurance_rx', 'insurance_external', 'client_buyback'

# rule_key, name, source, mode, shortage_only, pct, supplier
DEFAULT_RULES = [
    ('A_PRODUCTS_SHORTAGE', 'روشتة تأمين — صنف ناقص/لا يمكن توفيره — منتجات', A, 'products', True,  '25', '4472'),
    ('A_PRODUCTS',          'روشتة تأمين — منتجات',                          A, 'products', False, '30', '4471'),
    ('A_CASH',              'روشتة تأمين — نقدي',                             A, 'cash',     False, '40', '4470'),
    ('B1_PRODUCTS',         'أدوية تأمين من خارج صرفنا — منتجات',             B1, 'products', False, '40', '4470'),
    ('B1_CASH',             'أدوية تأمين من خارج صرفنا — نقدي',               B1, 'cash',     False, '50', '4469'),
    # B2 rates confirmed by the owner 2026-10-03 (products 40 %, cash 50 %); cash → 4069 «مورد عام 50%».
    ('B2_PRODUCTS',         'عميل غير تأمين يبيع أدوية — منتجات',              B2, 'products', False, '40', '3068'),
    ('B2_CASH',             'عميل غير تأمين يبيع أدوية — نقدي',                B2, 'cash',     False, '50', '4069'),
]

WORKFLOWS = [
    ('replacement_supervisor', 'Replacement — supervisor', 'اعتماد بدل الروشتة — مشرف الفرع',
     [(1, 'supervisor', True, 'مشرف الفرع')]),
    ('replacement_manager', 'Replacement — manager', 'اعتماد بدل الروشتة — مشرف ثم مدير',
     [(1, 'supervisor', True, 'مشرف الفرع'), (2, 'admin', False, 'المدير')]),
]


class Command(BaseCommand):
    help = 'Seed بدل الروشتة default rules + approval workflows (idempotent).'

    def handle(self, *args, **o):
        from apps.approvals.models import ApprovalStepDefinition, ApprovalWorkflowDefinition
        made = 0
        for key, name, src, mode, short, pct, sup in DEFAULT_RULES:
            if ReplacementRule.objects.filter(rule_key=key).exists():
                continue
            ReplacementRule.objects.create(
                rule_key=key, version=1, name=name, source_type=src, settlement_mode=mode, shortage_only=short,
                deduction_pct=Decimal(pct), supplier_personcode=sup, effective_from=date(2025, 1, 1),
                priority=50 if short else 100, is_active=True)
            made += 1
        for code, name, name_ar, steps in WORKFLOWS:
            wf, _ = ApprovalWorkflowDefinition.objects.get_or_create(
                code=code, defaults={'name': name, 'name_ar': name_ar, 'category': 'finance',
                                     'reject_terminates': True, 'sla_hours': 24})
            for order, role, branch_only, step_name in steps:
                ApprovalStepDefinition.objects.get_or_create(
                    workflow=wf, order=order,
                    defaults={'name': step_name, 'name_ar': step_name, 'approver_role': role,
                              'restrict_to_branch': branch_only})
        self.stdout.write(self.style.SUCCESS(f'seed_replacement: {made} rule(s) created; workflows ensured.'))
