"""Grant RBAC module `usage_print` (Project 5) and seed the quick-pick presets.
Only usage_print rows are created — no other module's permissions are touched
(seed_permissions carries the same matrix for fresh installs). Presets are editable afterwards."""
from django.db import migrations

GRANTS = {
    'pharmacist':  ['view', 'create'],
    'salesperson': ['view', 'create'],
    'supervisor':  ['view', 'create', 'edit'],
}

PRESETS = {
    'amount': ['قرص واحد', 'نصف قرص', 'قرصين', 'كبسولة واحدة', 'كيس واحد', 'ملعقة صغيرة (5 مل)',
               'ملعقة كبيرة (15 مل)', 'نقطتين', 'بخة واحدة', 'دهان طبقة رقيقة', 'حقنة واحدة'],
    'frequency': ['مرة يوميا', 'مرتين يوميا', '3 مرات يوميا', 'كل 8 ساعات', 'كل 12 ساعة',
                  'مرة أسبوعيا', 'عند اللزوم'],
    'timing': ['صباحا', 'مساء', 'قبل النوم', 'قبل الأكل', 'بعد الأكل', 'صباحا بعد الفطار',
               'على معدة فارغة', 'مع الأكل'],
    'phrase': ['قرص واحد مرتين يوميا بعد الأكل', 'قرص واحد صباحا بعد الفطار',
               'قرص واحد يوميا قبل النوم', 'كبسولة واحدة كل 12 ساعة لمدة 5 أيام',
               'يحفظ في الثلاجة'],
}


def seed(apps, schema_editor):
    RoleModuleAccess = apps.get_model('users', 'RoleModuleAccess')
    for role, actions in GRANTS.items():
        for action in actions:
            RoleModuleAccess.objects.get_or_create(role=role, module='usage_print', action=action,
                                                   defaults={'is_allowed': True})
    UsagePreset = apps.get_model('usage_print', 'UsagePreset')
    if not UsagePreset.objects.exists():
        UsagePreset.objects.bulk_create([
            UsagePreset(kind=kind, text=text, sort_order=i)
            for kind, texts in PRESETS.items() for i, text in enumerate(texts)
        ])


def unseed(apps, schema_editor):
    apps.get_model('users', 'RoleModuleAccess').objects.filter(module='usage_print').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('usage_print', '0001_initial'),
        ('users', '0045_alter_rolemoduleaccess_module'),
    ]
    operations = [migrations.RunPython(seed, unseed)]
