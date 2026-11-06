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


def _set(RMA, rows, allowed):
    for role, module, action in rows:
        # only a matrix already seeded for the module (see 0032): on a fresh install seed_permissions
        # writes the full code matrix, these changes included
        if not RMA.objects.filter(module=module).exclude(role=role).exists():
            continue
        RMA.objects.update_or_create(role=role, module=module, action=action, defaults={'is_allowed': allowed})


def forwards(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    _set(RMA, GRANT, True)
    _set(RMA, REVOKE, False)


def backwards(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    _set(RMA, GRANT, False)
    _set(RMA, REVOKE, True)


class Migration(migrations.Migration):
    dependencies = [('users', '0051_accountant_explicit_denials')]
    operations = [migrations.RunPython(forwards, backwards)]
