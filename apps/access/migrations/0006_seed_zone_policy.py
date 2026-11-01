"""Seed the zone policy table from the owner's external-access decisions (N3, table 7.3)."""
from django.db import migrations

ROLES = ['admin', 'supervisor', 'purchasing', 'quality_manager', 'call_center', 'delivery',
         'pharmacist', 'salesperson', 'viewer']
# MODULE_BY_PREFIX values for /api/callcenter/, /api/demand/, /api/reservations/, /api/customers/
CALL_CENTER_MODULES = ['callcenter', 'demand', 'reservations', 'customers']


def _row(role, zone):
    row = dict(role=role, zone=zone, modules=[], view_only=False, export=False,
               softech_read=False, softech_write=False, require_mfa=False, max_session_hours=None)
    if zone == 'Z1':
        row.update(access='full', export=True, softech_read=True, softech_write=True)
        return row
    if zone == 'Z2':
        row.update(access='read_only', softech_read=True)
        return row
    # Z3 / Z4: 2FA always, 8 h session cap (delivery 12 h)
    row.update(require_mfa=True, max_session_hours=12 if role == 'delivery' else 8)
    if role == 'delivery':
        row['access'] = 'rider'
    elif zone == 'Z4':
        row['access'] = 'none'
    elif role == 'admin':
        # all modules; export / SOFTECH write only via the per-user flags
        row.update(access='full', softech_read=True)
    elif role in ('supervisor', 'purchasing', 'quality_manager'):
        # "their modules, view-only" = every module the role matrix already grants, read only
        row.update(access='read_only', softech_read=True)
    elif role == 'call_center':
        row.update(access='listed', modules=list(CALL_CENTER_MODULES), softech_read=True)
    else:
        row['access'] = 'none'
    return row


def seed(apps, schema_editor):
    ZonePolicy = apps.get_model('access', 'ZonePolicy')
    for role in ROLES:
        for zone in ('Z1', 'Z2', 'Z3', 'Z4'):
            row = _row(role, zone)
            ZonePolicy.objects.get_or_create(role=role, zone=zone, defaults=row)


def unseed(apps, schema_editor):
    apps.get_model('access', 'ZonePolicy').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('access', '0005_zone_policy'),
    ]

    operations = [migrations.RunPython(seed, unseed)]
