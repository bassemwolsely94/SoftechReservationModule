"""Role review 2026-11-20: ten tool modules split out of their parents (forecast, recommendations,
catalog_tools, stock, loyalty, dispatch, rider, reconciliation, access_control, code_maps).
Inserts a row for every role x module x action (explicit False too); get_or_create, so a grant the
owner changed since is kept. The only existing rows touched: purchasing/settings -> not allowed
(owner, role review). GRANTS is a frozen copy of seed_permissions.PERMISSIONS for these modules.
"""
from django.db import migrations, models

ROLES = ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'delivery', 'viewer',
         'supervisor', 'quality_manager', 'accountant']
ACTIONS = ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize']

GRANTS = {
    'forecast': {
        'admin': ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'],
        'purchasing': ['view', 'edit', 'delete', 'export'],
        'supervisor': ['view', 'edit', 'delete', 'export'],
        'quality_manager': ['view', 'export'],
    },
    'recommendations': {
        'admin': ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'],
        'call_center': ['view'],
        'pharmacist': ['view'],
        'purchasing': ['view', 'edit', 'delete', 'export'],
        'supervisor': ['view', 'edit', 'delete', 'export'],
        'quality_manager': ['view', 'export'],
    },
    'catalog_tools': {
        'admin': ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'],
        'call_center': ['view'],
        'purchasing': ['view', 'edit', 'approve', 'export'],
        'supervisor': ['view'],
    },
    'stock': {
        'admin': ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'],
        'call_center': ['view'],
        'pharmacist': ['view', 'edit', 'export'],
        'salesperson': ['view'],
        'purchasing': ['view', 'edit', 'approve', 'export'],
        'supervisor': ['view'],
        'quality_manager': ['view'],
    },
    'loyalty': {
        'admin': ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'],
        'call_center': ['view', 'edit'],
        'pharmacist': ['view', 'edit'],
        'salesperson': ['view'],
        'supervisor': ['view', 'edit', 'export'],
        'quality_manager': ['view', 'export'],
    },
    'dispatch': {
        'admin': ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'],
        'call_center': ['view', 'create', 'assign'],
        'pharmacist': ['view', 'create', 'edit', 'approve', 'finalize'],
        'salesperson': ['view', 'create'],
        'supervisor': ['view', 'create', 'edit', 'approve', 'export', 'assign'],
        'quality_manager': ['view', 'export'],
    },
    'rider': {
        'admin': ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'],
        'call_center': ['view', 'create', 'assign'],
        'delivery': ['view', 'edit'],
        'supervisor': ['view', 'create', 'edit', 'approve', 'export', 'assign'],
    },
    'reconciliation': {
        'admin': ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'],
        'purchasing': ['view', 'create', 'edit', 'approve', 'export', 'finalize'],
        'supervisor': ['view'],
        'quality_manager': ['view'],
        'accountant': ['view', 'export'],
    },
    'access_control': {
        'admin': ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'],
    },
    'code_maps': {
        'admin': ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'],
        'purchasing': ['view'],
        'supervisor': ['view'],
    },
}


def forwards(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    for module, by_role in GRANTS.items():
        for role in ROLES:
            allowed = set(by_role.get(role, []))
            for action in ACTIONS:
                RMA.objects.get_or_create(role=role, module=module, action=action,
                                          defaults={'is_allowed': action in allowed})
    RMA.objects.filter(role='purchasing', module='settings', is_allowed=True).update(is_allowed=False)


def backwards(apps, schema_editor):
    """No-op: the rows are harmless and the owner may have edited them."""


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0060_alerts_module'),
    ]

    operations = [
        migrations.AlterField(
            model_name='rolemoduleaccess',
            name='module',
            field=models.CharField(choices=[('pos', 'نقطة البيع (POS)'), ('reservations', 'الحجوزات'), ('demand', 'الطلب الضائع / المبيعات المفقودة'), ('transfers', 'طلبات التحويل'), ('followups', 'متابعة المزمن'), ('delivery', 'توصيل الطلبات'), ('customers', 'العملاء'), ('chronic', 'الأدوية المزمنة'), ('campaigns', 'حملات واتساب'), ('vouchers', 'القسائم'), ('catalog', 'كتالوج الأدوية'), ('stockcount', 'الجرد الفعلي'), ('shortage', 'النواقص'), ('offers', 'العروض والتخفيضات'), ('purchasing', 'ذكاء المشتريات'), ('invoices', 'فواتير الموردين'), ('incentives', 'الحوافز'), ('cheques', 'تخطيط الشيكات'), ('finance', 'الذكاء المالي'), ('callcenter', 'مركز الاتصال'), ('hr', 'الموارد البشرية'), ('approvals', 'صندوق الموافقات'), ('insurance', 'مطالبات التأمين'), ('replacement', 'بدل الروشتة / شراء أدوية العملاء'), ('commerce', 'المستندات التجارية'), ('analytics', 'التحليلات والتقارير'), ('dashboard', 'لوحة المتابعة'), ('audit', 'المراجعة والأمان'), ('sync', 'مزامنة البيانات'), ('settings', 'الإعدادات'), ('users', 'إدارة المستخدمين'), ('admin', 'إدارة النظام'), ('help', 'دليل الاستخدام (تعديل الشرح)'), ('gamification', 'التحفيز — النقاط والمستويات (تقارير وإعدادات)'), ('stock_audit', 'تدقيق حركات المخزون'), ('pic_analytics', 'تحليلات العملاء'), ('tasks', 'المهام'), ('ledger', 'الحسابات العامة'), ('tax_invoicing', 'الفواتير الضريبية'), ('counselling', 'إرشادات الاستخدام'), ('usage_print', 'طباعة طريقة الاستخدام'), ('marketplace', 'المنصات والتطبيقات'), ('hr_attendance', 'الحضور والبصمة'), ('data_health', 'صحة البيانات'), ('crews', 'الأطقم'), ('rpa', 'روبوت الإدخال'), ('alerts', 'التنبيهات والإعلانات'), ('forecast', 'التنبؤ والسيناريوهات'), ('recommendations', 'التوصيات'), ('catalog_tools', 'أدوات الأصناف'), ('stock', 'المخزون والتشغيلات'), ('loyalty', 'الولاء والإحالة'), ('dispatch', 'توزيع التوصيل'), ('rider', 'شاشة المندوب'), ('reconciliation', 'المطابقة المالية'), ('access_control', 'الشبكات والأجهزة'), ('code_maps', 'جداول الأكواد')], db_index=True, max_length=30),
        ),
        migrations.RunPython(forwards, backwards),
    ]
