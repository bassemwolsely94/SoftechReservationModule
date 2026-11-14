"""Go-live seed of the dated assignment history (crews final review F1).

Every Employee with no EmployeeAssignment row gets one open row from start_date, else
2020-01-01 (SEED_EPOCH): these people were already here when the history began. Running it in
the migration keeps the order safe — the seed always happens before the first import after
go-live, which (since F1) starts a new hire's row on the import day instead of in 2020.
Idempotent; the `seed_employee_assignments` command does the same later if ever needed.
Reverse is a no-op: the rows are dropped with the table if 0012 is reversed.
"""
from datetime import date

from django.db import migrations

SEED_EPOCH = date(2020, 1, 1)
FIELDS = ('job_title', 'branch_id', 'department', 'section', 'softech_usercode', 'pbx_extensions')


def seed(apps, schema_editor):
    Employee = apps.get_model('hr', 'Employee')
    EmployeeAssignment = apps.get_model('hr', 'EmployeeAssignment')
    rows = [
        EmployeeAssignment(employee_id=e['id'], valid_from=e['start_date'] or SEED_EPOCH, valid_to=None,
                           source='seed', **{**{f: e[f] for f in FIELDS},
                                             'pbx_extensions': list(e['pbx_extensions'] or [])})
        for e in Employee.objects.filter(assignments__isnull=True).values('id', 'start_date', *FIELDS)
    ]
    EmployeeAssignment.objects.bulk_create(rows, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0013_assignment_identity_snapshot'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
