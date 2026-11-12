# «التوزيعة» plan ledger + IsrPush.route_tag (doc 30 phases B–D, owner 2026-11-10).
# Foreign keys sit inside CreateModel so no NOT NULL column is added to an existing table.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0045_rate_push_seasonal_factor'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DistributionPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('built', 'محسوبة'), ('generated', 'وُلّدت منها الطلبات'), ('superseded', 'استُبدلت بخطة أحدث')], db_index=True, default='built', max_length=12)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('inputs', models.JSONField(blank=True, default=dict)),
                ('totals', models.JSONField(blank=True, default=dict)),
                ('documents', models.JSONField(blank=True, default=list)),
                ('generated_at', models.DateTimeField(blank=True, null=True)),
                ('run', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='distribution_plans', to='purchasing.demandcalculationrun')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='distribution_plans', to=settings.AUTH_USER_MODEL)),
                ('generated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'خطة توزيعة',
                'ordering': ['-created_at'],
            },
        ),
        migrations.RemoveConstraint(
            model_name='isrpush',
            name='isrpush_one_live_draft_per_route',
        ),
        migrations.AddField(
            model_name='isrpush',
            name='route_tag',
            field=models.CharField(blank=True, db_default='', db_index=True, default='', max_length=16),
        ),
        migrations.AddConstraint(
            model_name='isrpush',
            constraint=models.UniqueConstraint(condition=models.Q(('origin_isr__isnull', True), ('origin_request__isnull', True), ('origin_shortage_list__isnull', True), ('status__in', ['proposed', 'approved'])), fields=('kind', 'branchcode', 'dest_branchcode', 'route_tag'), name='isrpush_one_live_draft_per_route_tag'),
        ),
        migrations.CreateModel(
            name='PlannedMove',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('itemcode', models.CharField(db_index=True, max_length=20)),
                ('item_name', models.CharField(blank=True, max_length=255)),
                ('from_code', models.CharField(max_length=10)),
                ('to_code', models.CharField(max_length=10)),
                ('qty', models.IntegerField(default=0)),
                ('unit_cost', models.DecimalField(decimal_places=3, default=0, max_digits=14)),
                ('value', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('wave', models.PositiveSmallIntegerField(default=0)),
                ('rank', models.PositiveIntegerField(default=0)),
                ('category', models.CharField(blank=True, max_length=20)),
                ('reasons', models.JSONField(blank=True, default=list)),
                ('status', models.CharField(choices=[('planned', 'مخطط'), ('conflict', 'متعارض'), ('below_line', 'أقل من حد السطر'), ('folded', 'مؤجل للتشغيل القادم'), ('not_allowed', 'غير مسموح من هذا المصدر'), ('blocked', 'المسار مشغول')], db_index=True, default='planned', max_length=12)),
                ('status_note', models.CharField(blank=True, max_length=255)),
                ('conflicts', models.JSONField(blank=True, default=list)),
                ('position', models.JSONField(blank=True, default=dict)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='moves', to='purchasing.distributionplan')),
                ('isr_push', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='planned_moves', to='purchasing.isrpush')),
                ('feeder_push', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='purchasing.isrpush')),
            ],
            options={
                'verbose_name': 'حركة مخططة',
                'ordering': ['wave', 'rank'],
                'indexes': [models.Index(fields=['plan', 'status', 'wave'], name='purchasing__plan_id_989a38_idx')],
            },
        ),
    ]
