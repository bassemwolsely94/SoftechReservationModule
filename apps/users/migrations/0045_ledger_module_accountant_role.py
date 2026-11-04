"""Finance GL (plan 1): the `accountant` role and the `ledger` RBAC module.

- ledger: every existing role gets a row per action; only `accountant` is allowed
  view / create (manual drafts) / approve / export. edit (chart of accounts, rules) and finalize
  (period close) stay off for everyone — admin bypasses the matrix, the owner grants the rest in
  «الصلاحيات».
- accountant also gets finance {view, export}, cheques {view}, dashboard {view}, and tasks like
  every other role.
"""
from django.db import migrations, models

ROLES = ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'delivery', 'viewer',
         'supervisor', 'quality_manager', 'accountant']
ACTIONS = ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize']
ACCOUNTANT = {
    'ledger': {'view', 'create', 'approve', 'export'},
    'finance': {'view', 'export'},
    'cheques': {'view'},
    'dashboard': {'view'},
    'tasks': {'view', 'create', 'edit', 'delete', 'assign', 'finalize'},   # as every role (seed_permissions)
}


def forwards(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    for role in ROLES:
        for action in ACTIONS:
            RMA.objects.get_or_create(
                role=role, module='ledger', action=action,
                defaults={'is_allowed': role == 'accountant' and action in ACCOUNTANT['ledger']})
    for module, allowed in ACCOUNTANT.items():
        if module == 'ledger':
            continue
        for action in ACTIONS:
            RMA.objects.get_or_create(role='accountant', module=module, action=action,
                                      defaults={'is_allowed': action in allowed})


def backwards(apps, schema_editor):
    apps.get_model('users', 'RoleModuleAccess').objects.filter(module='ledger').delete()
    apps.get_model('users', 'RoleModuleAccess').objects.filter(role='accountant').delete()
    apps.get_model('users', 'StaffProfile').objects.filter(role='accountant').update(role='viewer')


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0044_bulk_read_block'),
    ]

    operations = [
        migrations.AlterField(
            model_name='rolemoduleaccess',
            name='role',
            field=models.CharField(choices=[('admin', 'Admin — Full Access'), ('call_center', 'Call Center — All Branches'), ('pharmacist', 'Pharmacist — Own Branch'), ('salesperson', 'Sales Person — Own Branch'), ('purchasing', 'Purchasing — HQ Only'), ('delivery', 'Delivery'), ('viewer', 'Viewer — Read Only'), ('supervisor', 'Supervisor — Call Center Supervisor'), ('quality_manager', 'Quality Manager — QA & Scoring'), ('accountant', 'Accountant — General Ledger')], db_index=True, max_length=20),
        ),
        migrations.AlterField(
            model_name='staffprofile',
            name='role',
            field=models.CharField(choices=[('admin', 'Admin — Full Access'), ('call_center', 'Call Center — All Branches'), ('pharmacist', 'Pharmacist — Own Branch'), ('salesperson', 'Sales Person — Own Branch'), ('purchasing', 'Purchasing — HQ Only'), ('delivery', 'Delivery'), ('viewer', 'Viewer — Read Only'), ('supervisor', 'Supervisor — Call Center Supervisor'), ('quality_manager', 'Quality Manager — QA & Scoring'), ('accountant', 'Accountant — General Ledger')], default='salesperson', max_length=20, verbose_name='الدور'),
        ),
        migrations.AlterField(
            model_name='rolemoduleaccess',
            name='module',
            field=models.CharField(choices=[('pos', 'نقطة البيع (POS)'), ('reservations', 'الحجوزات'), ('demand', 'الطلب الضائع / المبيعات المفقودة'), ('transfers', 'طلبات التحويل'), ('followups', 'متابعة المزمن'), ('delivery', 'توصيل الطلبات'), ('customers', 'العملاء'), ('chronic', 'الأدوية المزمنة'), ('campaigns', 'حملات واتساب'), ('vouchers', 'القسائم'), ('catalog', 'كتالوج الأدوية'), ('stockcount', 'الجرد الفعلي'), ('shortage', 'النواقص'), ('offers', 'العروض والتخفيضات'), ('purchasing', 'ذكاء المشتريات'), ('invoices', 'فواتير الموردين'), ('incentives', 'الحوافز'), ('cheques', 'تخطيط الشيكات'), ('finance', 'الذكاء المالي'), ('callcenter', 'مركز الاتصال'), ('hr', 'الموارد البشرية'), ('approvals', 'صندوق الموافقات'), ('insurance', 'مطالبات التأمين'), ('replacement', 'بدل الروشتة / شراء أدوية العملاء'), ('commerce', 'المستندات التجارية'), ('analytics', 'التحليلات والتقارير'), ('dashboard', 'لوحة المتابعة'), ('audit', 'المراجعة والأمان'), ('sync', 'مزامنة البيانات'), ('settings', 'الإعدادات'), ('users', 'إدارة المستخدمين'), ('admin', 'إدارة النظام'), ('help', 'دليل الاستخدام (تعديل الشرح)'), ('gamification', 'التحفيز — النقاط والمستويات (تقارير وإعدادات)'), ('stock_audit', 'تدقيق حركات المخزون'), ('pic_analytics', 'تحليلات العملاء'), ('tasks', 'المهام'), ('ledger', 'الحسابات العامة')], db_index=True, max_length=30),
        ),
        migrations.RunPython(forwards, backwards),
    ]
