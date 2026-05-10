import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_alter_staffprofile_role'),
        ('branches', '0001_initial'),
    ]

    operations = [
        # ── StaffProfile additions ────────────────────────────────────────────
        migrations.AddField(
            model_name='staffprofile',
            name='has_global_access',
            field=models.BooleanField(
                default=False,
                verbose_name='وصول شامل لجميع الفروع',
                help_text='يتجاوز قيود الفرع بغض النظر عن الدور',
            ),
        ),

        # ── UserBranchAccess ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='UserBranchAccess',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('granted_at', models.DateTimeField(auto_now_add=True)),
                ('staff', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='extra_branches',
                    to='users.staffprofile',
                )),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='extra_staff_access',
                    to='branches.branch',
                )),
                ('granted_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='granted_branch_access',
                    to='users.staffprofile',
                )),
            ],
            options={
                'verbose_name': 'وصول إضافي للفرع',
                'verbose_name_plural': 'وصول إضافي للفروع',
                'unique_together': {('staff', 'branch')},
            },
        ),

        # ── RoleModuleAccess ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='RoleModuleAccess',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('role', models.CharField(
                    choices=[
                        ('admin', 'Admin — Full Access'),
                        ('call_center', 'Call Center — All Branches'),
                        ('pharmacist', 'Pharmacist — Own Branch'),
                        ('salesperson', 'Sales Person — Own Branch'),
                        ('purchasing', 'Purchasing — HQ Only'),
                        ('delivery', 'Delivery'),
                        ('viewer', 'Viewer — Read Only'),
                    ],
                    db_index=True,
                    max_length=20,
                )),
                ('module', models.CharField(
                    choices=[
                        ('reservations', 'الحجوزات'),
                        ('demand', 'طلبات العملاء / المبيعات المفقودة'),
                        ('transfers', 'طلبات التحويل'),
                        ('customers', 'العملاء'),
                        ('catalog', 'كتالوج الأدوية'),
                        ('dashboard', 'لوحة المتابعة'),
                        ('sync', 'مزامنة البيانات'),
                        ('purchasing', 'لوحة المشتريات'),
                        ('chronic', 'الأدوية المزمنة'),
                        ('admin', 'إدارة النظام'),
                    ],
                    db_index=True,
                    max_length=30,
                )),
                ('action', models.CharField(
                    choices=[
                        ('view', 'عرض'),
                        ('create', 'إنشاء'),
                        ('edit', 'تعديل'),
                        ('delete', 'حذف'),
                        ('approve', 'اعتماد'),
                        ('export', 'تصدير'),
                    ],
                    max_length=10,
                )),
                ('is_allowed', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='users.staffprofile',
                )),
            ],
            options={
                'verbose_name': 'صلاحية دور',
                'verbose_name_plural': 'صلاحيات الأدوار',
                'ordering': ['role', 'module', 'action'],
                'unique_together': {('role', 'module', 'action')},
            },
        ),
    ]
