"""Crews piece 2a (spec 2026-11-13 §6.5, §10): the «الأطقم» module (/crews, /api/crews/).

Only `view` and `edit` are used by the views. admin everything; every other role an explicit denial
row (grants are the owner's call in «الصلاحيات»). get_or_create: a grant the owner made since is kept.
"""
from django.db import migrations, models

ROLES = ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'delivery', 'viewer',
         'supervisor', 'quality_manager', 'accountant']
ACTIONS = ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize']
GRANTS = {
    'admin': set(ACTIONS),
}


def forwards(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    for role in ROLES:
        for action in ACTIONS:
            RMA.objects.get_or_create(role=role, module='crews', action=action,
                                      defaults={'is_allowed': action in GRANTS.get(role, set())})


def backwards(apps, schema_editor):
    apps.get_model('users', 'RoleModuleAccess').objects.filter(module='crews').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0056_alter_rolemoduleaccess_module'),
    ]

    operations = [
        migrations.AlterField(
            model_name='rolemoduleaccess',
            name='module',
            field=models.CharField(choices=[('pos', 'نقطة البيع (POS)'), ('reservations', 'الحجوزات'), ('demand', 'الطلب الضائع / المبيعات المفقودة'), ('transfers', 'طلبات التحويل'), ('followups', 'متابعة المزمن'), ('delivery', 'توصيل الطلبات'), ('customers', 'العملاء'), ('chronic', 'الأدوية المزمنة'), ('campaigns', 'حملات واتساب'), ('vouchers', 'القسائم'), ('catalog', 'كتالوج الأدوية'), ('stockcount', 'الجرد الفعلي'), ('shortage', 'النواقص'), ('offers', 'العروض والتخفيضات'), ('purchasing', 'ذكاء المشتريات'), ('invoices', 'فواتير الموردين'), ('incentives', 'الحوافز'), ('cheques', 'تخطيط الشيكات'), ('finance', 'الذكاء المالي'), ('callcenter', 'مركز الاتصال'), ('hr', 'الموارد البشرية'), ('approvals', 'صندوق الموافقات'), ('insurance', 'مطالبات التأمين'), ('replacement', 'بدل الروشتة / شراء أدوية العملاء'), ('commerce', 'المستندات التجارية'), ('analytics', 'التحليلات والتقارير'), ('dashboard', 'لوحة المتابعة'), ('audit', 'المراجعة والأمان'), ('sync', 'مزامنة البيانات'), ('settings', 'الإعدادات'), ('users', 'إدارة المستخدمين'), ('admin', 'إدارة النظام'), ('help', 'دليل الاستخدام (تعديل الشرح)'), ('gamification', 'التحفيز — النقاط والمستويات (تقارير وإعدادات)'), ('stock_audit', 'تدقيق حركات المخزون'), ('pic_analytics', 'تحليلات العملاء'), ('tasks', 'المهام'), ('ledger', 'الحسابات العامة'), ('tax_invoicing', 'الفواتير الضريبية'), ('counselling', 'إرشادات الاستخدام'), ('usage_print', 'طباعة طريقة الاستخدام'), ('hr_attendance', 'الحضور والبصمة'), ('data_health', 'صحة البيانات'), ('crews', 'الأطقم')], db_index=True, max_length=30),
        ),
        migrations.RunPython(forwards, backwards),
    ]
