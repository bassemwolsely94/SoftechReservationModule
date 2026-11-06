"""R8 menu-vs-API owner decisions (2026-11-06, docs/security/2026-11-05-r8-frontend-report.md):

  viewer           loses callcenter view (customer conversations) and approvals view
                   (approvals, pricing approvals, discount alignment).
  accountant       gets hr view + create: own leave and permit requests. Its 0051 deny rows turn on.
  supervisor       gets purchasing view, which /supply needs.

Changes only these rows; every other row, and any admin override, is untouched.
"""
from django.db import migrations

GRANT = [('accountant', 'hr', 'view'), ('accountant', 'hr', 'create'), ('supervisor', 'purchasing', 'view')]
REVOKE = [('viewer', 'callcenter', 'view'), ('viewer', 'approvals', 'view')]


def _set(RMA, rows, allowed, seeded):
    for role, module, action in rows:
        if module in seeded:
            RMA.objects.update_or_create(role=role, module=module, action=action, defaults={'is_allowed': allowed})


def _seeded(RMA):
    # Only a matrix already seeded for the module, as in 0052: a row of a role outside RBAC_ENFORCED_ROLES.
    # On an unseeded module one row here would lock every other role out; seed_permissions writes the
    # full code matrix there instead. Read once, so a row written here never counts as seeding.
    from core.middleware.module_access import enforced_roles
    return set(RMA.objects.exclude(role__in=enforced_roles()).values_list('module', flat=True).distinct())


def forwards(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    seeded = _seeded(RMA)
    _set(RMA, GRANT, True, seeded)
    _set(RMA, REVOKE, False, seeded)


def backwards(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    seeded = _seeded(RMA)
    _set(RMA, GRANT, False, seeded)
    _set(RMA, REVOKE, True, seeded)


class Migration(migrations.Migration):
    dependencies = [('users', '0052_round2_owner_grants_delete_analytics')]
    operations = [migrations.RunPython(forwards, backwards)]
