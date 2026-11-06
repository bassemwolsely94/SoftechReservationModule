"""Round 2 R3 owner answers (2026-11-05, docs/security/round2/R3_enforce_readiness.md):

  Q-7c  supervisor and purchasing get analytics edit / delete — forecasting and sales targets are
        written by the analyst roles (Z-7b / Z-9a); now the matrix says so too.
  Q-7e  `delete` where the role is the module's operator and really removes records: purchasing on
        purchasing (supply availability) and transfers (transit pick config, Z-7c), purchasing and
        quality manager on incentives (payroll owner decision 2026-11-03: full payroll actions).

Turns only these rows on; every other row, and any admin override, is untouched.
"""
from django.db import migrations

GRANTS = {
    'supervisor':      {'analytics': ['edit', 'delete']},
    'purchasing':      {'analytics': ['edit', 'delete'], 'purchasing': ['delete'], 'transfers': ['delete'],
                        'incentives': ['delete']},
    'quality_manager': {'incentives': ['delete']},
}
NEW = {(r, m, a) for r, mods in GRANTS.items() for m, acts in mods.items() for a in acts}


def grant(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    # Only a matrix already seeded for the module (see 0032). "Seeded" is what module_access.seeded_modules()
    # means: a row of a role outside RBAC_ENFORCED_ROLES (the accountant's deny rows from 0051 do not count).
    # On an unseeded module a grant row would end every other role's fail-open and lock them out;
    # seed_permissions writes the full code matrix (these grants included) there instead.
    # Read once, before any write, so one grant here never counts as seeding for the next.
    from core.middleware.module_access import enforced_roles
    enforced = enforced_roles()
    seeded = set(RMA.objects.exclude(role__in=enforced).values_list('module', flat=True).distinct())
    for role, module, action in sorted(NEW):
        if module in seeded:
            RMA.objects.update_or_create(role=role, module=module, action=action, defaults={'is_allowed': True})


def revoke(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    for role, module, action in NEW:
        RMA.objects.filter(role=role, module=module, action=action).update(is_allowed=False)


class Migration(migrations.Migration):
    dependencies = [('users', '0051_accountant_explicit_denials')]
    operations = [migrations.RunPython(grant, revoke)]
