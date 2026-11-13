"""Snapshot SOFTECH user code + PBX extensions on EmployeeAssignment (crews piece 2a review):
past crew identities stay dated. Existing rows are backfilled from their Employee (today's values
are the best we know for the past, as with the job/branch seed)."""
from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def backfill(apps, schema_editor):
    Employee = apps.get_model('hr', 'Employee')
    EmployeeAssignment = apps.get_model('hr', 'EmployeeAssignment')
    emp = Employee.objects.filter(pk=OuterRef('employee_id'))
    EmployeeAssignment.objects.update(
        softech_usercode=Subquery(emp.values('softech_usercode')[:1]),
        pbx_extensions=Subquery(emp.values('pbx_extensions')[:1]))


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0012_employee_assignment_pbx_extensions'),
    ]

    operations = [
        migrations.AddField(
            model_name='employeeassignment',
            name='softech_usercode',
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name='employeeassignment',
            name='pbx_extensions',
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
