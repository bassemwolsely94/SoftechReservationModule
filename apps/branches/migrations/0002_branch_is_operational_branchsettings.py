"""
Migration: branches 0002
  - Add Branch.is_operational  (temporarily suspended flag)
  - Add Branch.is_active verbose_name / Meta
  - Create BranchSettings model (per-branch feature flags + notification gate)
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('branches', '0001_initial'),
    ]

    operations = [
        # ── Branch.is_operational ─────────────────────────────────────────────
        migrations.AddField(
            model_name='branch',
            name='is_operational',
            field=models.BooleanField(
                default=True,
                verbose_name='قيد التشغيل',
                help_text='إيقاف مؤقت — لا يمكن إنشاء معاملات جديدة لكن البيانات التاريخية تبقى متاحة',
            ),
        ),

        # ── BranchSettings ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='BranchSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('branch', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='settings',
                    to='branches.branch',
                    verbose_name='الفرع',
                )),
                ('allow_reservations', models.BooleanField(default=True, verbose_name='الحجوزات')),
                ('allow_transfers',    models.BooleanField(default=True, verbose_name='التحويلات')),
                ('allow_vouchers',     models.BooleanField(default=True, verbose_name='القسائم')),
                ('allow_stockcount',   models.BooleanField(default=True, verbose_name='الجرد')),
                ('allow_shortage',     models.BooleanField(default=True, verbose_name='قائمة النواقص')),
                ('notifications_enabled', models.BooleanField(
                    default=True,
                    verbose_name='تفعيل الإشعارات',
                    help_text='إلغاء التفعيل يوقف جميع إشعارات الفرع',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name':        'إعدادات الفرع',
                'verbose_name_plural': 'إعدادات الفروع',
            },
        ),
    ]
