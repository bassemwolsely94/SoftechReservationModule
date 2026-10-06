"""
DUP-004 (strategy B): de-collide the FollowUpTask class name.

Renames model demand.FollowUpTask → demand.DemandFollowUp at the *state* level
only. The database table is pinned to its original name (`demand_followuptask`)
via Meta.db_table, so NO DDL runs and existing rows are untouched — this is a
pure code-level rename. The model has no incoming FKs, so nothing else changes.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('demand', '0009_alter_demandrecord_source'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],   # table already exists as demand_followuptask
            state_operations=[
                migrations.RenameModel(
                    old_name='FollowUpTask',
                    new_name='DemandFollowUp',
                ),
                migrations.AlterModelTable(
                    name='DemandFollowUp',
                    table='demand_followuptask',
                ),
                migrations.AlterModelOptions(
                    name='DemandFollowUp',
                    options={
                        'ordering': ['due_date'],
                        'verbose_name': 'متابعة طلب',
                        'verbose_name_plural': 'متابعات الطلبات',
                    },
                ),
            ],
        ),
    ]
