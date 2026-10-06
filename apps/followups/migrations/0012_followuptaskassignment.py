# FollowUpTaskAssignment — many-to-many through table for multi-user assignments.
# Replaces the single assigned_to FK as the source of truth for "who is working this task".
# The assigned_to FK is preserved for backward-compat filtering; it holds the lead assignee.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
        ('followups', '0011_followuptask_transaction_detail'),
    ]

    operations = [
        migrations.CreateModel(
            name='FollowUpTaskAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('assignment_reason', models.CharField(
                    default='direct', max_length=20, verbose_name='سبب الإسناد',
                )),
                ('assigned_at', models.DateTimeField(
                    auto_now_add=True, verbose_name='وقت الإسناد',
                )),
                ('task', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='assignments',
                    to='followups.followuptask',
                    verbose_name='المهمة',
                )),
                ('staff', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='followup_assignments',
                    to='users.staffprofile',
                    verbose_name='الموظف',
                )),
                ('assigned_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='assigned_followup_tasks',
                    to='users.staffprofile',
                    verbose_name='عيّنها',
                )),
            ],
            options={
                'verbose_name': 'إسناد مهمة',
                'verbose_name_plural': 'إسنادات المهام',
                'ordering': ['assigned_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='followuptaskassignment',
            constraint=models.UniqueConstraint(
                fields=['task', 'staff'],
                name='unique_followup_task_assignment',
            ),
        ),
    ]
