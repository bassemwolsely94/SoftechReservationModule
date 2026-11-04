"""Finance GL: the `accountant` role gets an explicit row for every module × action.

0045 seeded only the accountant's granted modules (ledger, finance, cheques, dashboard, tasks).
Every other module had no accountant row at all: denied in effect, but «الصلاحيات» showed gaps and
seed_permissions' "every (role, module, action) is explicit" promise did not hold. This adds
is_allowed=False rows for all of them. get_or_create: a grant the owner made since is kept.

Owner ruling: accountant = finance department — ledger {view, create, approve, export},
finance {view, export}, cheques {view}, dashboard {view}, tasks (as every role); nothing else.
"""
from django.db import migrations

ACTIONS = ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize']
# Frozen copy of seed_permissions.ALL_MODULES on 2026-11-04.
MODULES = [
    'pos', 'reservations', 'demand', 'transfers', 'followups', 'delivery',
    'customers', 'chronic', 'campaigns', 'vouchers', 'catalog', 'stockcount', 'shortage', 'offers',
    'purchasing', 'invoices', 'incentives', 'cheques', 'finance', 'insurance', 'commerce', 'replacement',
    'callcenter', 'hr', 'approvals', 'analytics', 'dashboard', 'audit', 'sync', 'settings', 'users',
    'admin', 'help', 'gamification', 'stock_audit', 'pic_analytics', 'tasks', 'ledger', 'counselling',
    'usage_print',
]
GRANTED = {
    'ledger': {'view', 'create', 'approve', 'export'},
    'finance': {'view', 'export'},
    'cheques': {'view'},
    'dashboard': {'view'},
    'tasks': {'view', 'create', 'edit', 'delete', 'assign', 'finalize'},
}


def forwards(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    for module in MODULES:
        for action in ACTIONS:
            RMA.objects.get_or_create(role='accountant', module=module, action=action,
                                      defaults={'is_allowed': action in GRANTED.get(module, set())})


def backwards(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    RMA.objects.filter(role='accountant', is_allowed=False).exclude(module__in=list(GRANTED)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0050_staffprofile_alerts_only_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
