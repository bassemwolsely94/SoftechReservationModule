"""
Security Batch 5 (owner decision 3): `allowed_branches` is the one extra-branch list.
Copy every UserBranchAccess row into StaffProfile.allowed_branches so core.branch_scope can read
only that field. Additive and idempotent; the old rows are kept (the reverse is a no-op).
"""
from django.db import migrations


def fold(apps, schema_editor):
    UserBranchAccess = apps.get_model('users', 'UserBranchAccess')
    StaffProfile = apps.get_model('users', 'StaffProfile')
    Through = StaffProfile.allowed_branches.through
    existing = set(Through.objects.values_list('staffprofile_id', 'branch_id'))
    new = {
        (staff_id, branch_id)
        for staff_id, branch_id in UserBranchAccess.objects.values_list('staff_id', 'branch_id')
        if (staff_id, branch_id) not in existing
    }
    Through.objects.bulk_create([Through(staffprofile_id=s, branch_id=b) for s, b in new])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0032_grant_supervisor_stockcount_chronic_edit'),
    ]

    operations = [
        migrations.RunPython(fold, migrations.RunPython.noop),
    ]
