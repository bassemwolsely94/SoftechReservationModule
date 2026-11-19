# C13 — stock-audit finding → assigned task + targeted count.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock_audit', '0004_seed_stock_audit_permissions'),
        ('stockcount', '0004_daily_count'),
        ('tasks', '0003_operationaltask_phone_alert'),
        ('users', '0030_alter_rolemoduleaccess_module'),
    ]

    operations = [
        migrations.CreateModel(
            name='StockAuditFindingTask',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('item_codes', models.JSONField(default=list, verbose_name='أصناف الجرد')),
                ('status', models.CharField(choices=[('open', 'مفتوحة'), ('closed', 'مغلقة')], db_index=True,
                                            default='open', max_length=10)),
                ('outcome', models.CharField(blank=True, choices=[('match', 'الجرد مطابق'), ('variance', 'الجرد به فروق'),
                                                                  ('cancelled', 'أُلغيت المهمة أو الجرد')], max_length=10)),
                ('result', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                  related_name='+', to='users.staffprofile')),
                ('count_session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                    related_name='audit_finding_tasks', to='stockcount.stockcountsession')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                 related_name='+', to='users.staffprofile')),
                ('finding', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tasks',
                                              to='stock_audit.stockauditfinding')),
                ('task', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                           related_name='+', to='tasks.operationaltask')),
            ],
            options={
                'verbose_name': 'مهمة ملاحظة تدقيق',
                'verbose_name_plural': 'مهام ملاحظات التدقيق',
                'ordering': ['-created_at'],
                'constraints': [models.UniqueConstraint(condition=models.Q(('status', 'open')), fields=('finding',),
                                                        name='uniq_open_task_per_finding')],
            },
        ),
    ]
