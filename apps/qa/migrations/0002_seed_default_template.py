from django.db import migrations


DEFAULT_ITEMS = [
    {'key': 'cleanliness',   'label': 'نظافة الفرع والرفوف'},
    {'key': 'expiry',        'label': 'فحص الصلاحيات (لا أصناف منتهية معروضة)'},
    {'key': 'fefo',          'label': 'ترتيب الأقرب انتهاءً للأمام (FEFO)'},
    {'key': 'labeling',      'label': 'وضوح الأسعار والملصقات'},
    {'key': 'fridge',        'label': 'درجة حرارة الثلاجة مسجّلة وضمن النطاق'},
    {'key': 'controlled',    'label': 'سجل المخدرات/المراقبة محدّث ومؤمّن'},
    {'key': 'storage',       'label': 'التخزين السليم (بعيداً عن الشمس/الرطوبة)'},
    {'key': 'staff_uniform', 'label': 'مظهر وزي الموظفين'},
    {'key': 'safety',        'label': 'طفاية الحريق ومخارج الطوارئ سليمة'},
    {'key': 'pos',           'label': 'نظافة وترتيب منطقة الكاشير'},
]


def seed(apps, schema_editor):
    Template = apps.get_model('qa', 'QAChecklistTemplate')
    if not Template.objects.filter(name='branch_walkthrough').exists():
        Template.objects.create(
            name='branch_walkthrough',
            name_ar='جولة مراجعة الفرع',
            items=DEFAULT_ITEMS,
            is_active=True,
        )


def unseed(apps, schema_editor):
    Template = apps.get_model('qa', 'QAChecklistTemplate')
    Template.objects.filter(name='branch_walkthrough').delete()


class Migration(migrations.Migration):
    dependencies = [('qa', '0001_initial')]
    operations = [migrations.RunPython(seed, unseed)]
