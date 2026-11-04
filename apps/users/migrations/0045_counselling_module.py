"""Project 4 (owner 2026-11-03): the «إرشادات الاستخدام» module.

Pharmacists write and approve the customer-facing counselling sheets (view, create, edit, approve);
counter roles read them. supervisor is the call-center supervisor, not a clinician: read only.
Sending a card and the drug assistant are POS actions (`pos` module), not this one.
"""
from django.db import migrations, models

ROLES = ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'delivery', 'viewer',
         'supervisor', 'quality_manager']
ACTIONS = ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize']
GRANTS = {
    'admin': set(ACTIONS),
    'pharmacist': {'view', 'create', 'edit', 'approve'},
    'salesperson': {'view'}, 'call_center': {'view'}, 'supervisor': {'view'}, 'quality_manager': {'view'},
}


def forwards(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    for role in ROLES:
        for action in ACTIONS:
            RMA.objects.get_or_create(role=role, module='counselling', action=action,
                                      defaults={'is_allowed': action in GRANTS.get(role, set())})


def backwards(apps, schema_editor):
    apps.get_model('users', 'RoleModuleAccess').objects.filter(module='counselling').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0044_bulk_read_block'),
    ]

    operations = [
        migrations.AlterField(
            model_name='rolemoduleaccess',
            name='module',
            field=models.CharField(choices=[('pos', 'نقطة البيع (POS)'), ('reservations', 'الحجوزات'), ('demand', 'الطلب الضائع / المبيعات المفقودة'), ('transfers', 'طلبات التحويل'), ('followups', 'متابعة المزمن'), ('delivery', 'توصيل الطلبات'), ('customers', 'العملاء'), ('chronic', 'الأدوية المزمنة'), ('campaigns', 'حملات واتساب'), ('vouchers', 'القسائم'), ('catalog', 'كتالوج الأدوية'), ('stockcount', 'الجرد الفعلي'), ('shortage', 'النواقص'), ('offers', 'العروض والتخفيضات'), ('purchasing', 'ذكاء المشتريات'), ('invoices', 'فواتير الموردين'), ('incentives', 'الحوافز'), ('cheques', 'تخطيط الشيكات'), ('finance', 'الذكاء المالي'), ('callcenter', 'مركز الاتصال'), ('hr', 'الموارد البشرية'), ('approvals', 'صندوق الموافقات'), ('insurance', 'مطالبات التأمين'), ('replacement', 'بدل الروشتة / شراء أدوية العملاء'), ('commerce', 'المستندات التجارية'), ('analytics', 'التحليلات والتقارير'), ('dashboard', 'لوحة المتابعة'), ('audit', 'المراجعة والأمان'), ('sync', 'مزامنة البيانات'), ('settings', 'الإعدادات'), ('users', 'إدارة المستخدمين'), ('admin', 'إدارة النظام'), ('help', 'دليل الاستخدام (تعديل الشرح)'), ('gamification', 'التحفيز — النقاط والمستويات (تقارير وإعدادات)'), ('stock_audit', 'تدقيق حركات المخزون'), ('pic_analytics', 'تحليلات العملاء'), ('tasks', 'المهام'), ('counselling', 'إرشادات الاستخدام')], db_index=True, max_length=30),
        ),
        migrations.RunPython(forwards, backwards),
    ]
