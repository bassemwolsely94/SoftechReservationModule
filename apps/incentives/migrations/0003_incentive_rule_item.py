"""
Migration 0003 — add IncentiveRuleItem (multi-item rule support)
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        (
            'incentives',
            '0002_rename_incv_prog_period_idx_incentives__program_9054fe_idx_and_more',
        ),
    ]

    operations = [
        migrations.CreateModel(
            name='IncentiveRuleItem',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name='ID',
                    ),
                ),
                (
                    'item_code',
                    models.CharField(
                        db_index=True, max_length=50, verbose_name='كود الصنف',
                    ),
                ),
                (
                    'item_name',
                    models.CharField(blank=True, max_length=300, verbose_name='اسم الصنف'),
                ),
                (
                    'incentive_override',
                    models.DecimalField(
                        blank=True,
                        decimal_places=4,
                        help_text='إذا تُرك فارغاً يُستخدم incentive_value من القاعدة الأصلية',
                        max_digits=10,
                        null=True,
                        verbose_name='قيمة حافز خاصة (override)',
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'rule',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='rule_items',
                        to='incentives.incentiverule',
                        verbose_name='القاعدة',
                    ),
                ),
            ],
            options={
                'verbose_name':        'صنف القاعدة',
                'verbose_name_plural': 'أصناف القاعدة',
                'ordering':            ['item_code'],
                'unique_together':     {('rule', 'item_code')},
            },
        ),
    ]
