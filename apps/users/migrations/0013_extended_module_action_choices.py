# Generated 2026-06-05 — Extended MODULE_CHOICES + ACTION_CHOICES for full RBAC

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0012_alter_rolemoduleaccess_role_alter_staffprofile_role'),
    ]

    operations = [
        migrations.AlterField(
            model_name='rolemoduleaccess',
            name='module',
            field=models.CharField(
                choices=[
                    ('reservations', 'الحجوزات'),
                    ('demand',       'الطلب الضائع / المبيعات المفقودة'),
                    ('transfers',    'طلبات التحويل'),
                    ('followups',    'متابعة المزمن'),
                    ('delivery',     'توصيل الطلبات'),
                    ('customers',    'العملاء'),
                    ('chronic',      'الأدوية المزمنة'),
                    ('campaigns',    'حملات واتساب'),
                    ('vouchers',     'القسائم'),
                    ('catalog',      'كتالوج الأدوية'),
                    ('stockcount',   'الجرد الفعلي'),
                    ('shortage',     'النواقص'),
                    ('purchasing',   'ذكاء المشتريات'),
                    ('invoices',     'فواتير الموردين'),
                    ('incentives',   'الحوافز'),
                    ('cheques',      'تخطيط الشيكات'),
                    ('finance',      'الذكاء المالي'),
                    ('callcenter',   'مركز الاتصال'),
                    ('analytics',    'التحليلات والتقارير'),
                    ('dashboard',    'لوحة المتابعة'),
                    ('audit',        'المراجعة والأمان'),
                    ('sync',         'مزامنة البيانات'),
                    ('settings',     'الإعدادات'),
                    ('users',        'إدارة المستخدمين'),
                    ('admin',        'إدارة النظام'),
                ],
                db_index=True,
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name='rolemoduleaccess',
            name='action',
            field=models.CharField(
                choices=[
                    ('view',     'عرض'),
                    ('create',   'إنشاء'),
                    ('edit',     'تعديل'),
                    ('delete',   'حذف'),
                    ('approve',  'اعتماد'),
                    ('export',   'تصدير'),
                    ('assign',   'تعيين'),
                    ('finalize', 'إغلاق / إنهاء'),
                ],
                max_length=10,
            ),
        ),
    ]
