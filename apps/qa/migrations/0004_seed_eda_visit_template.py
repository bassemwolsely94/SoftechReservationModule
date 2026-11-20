"""C31: the EDA (هيئة الدواء المصرية) visit checklist as a QA template, on the existing inspections.
The item list is a first draft for the owner to confirm (PR owner question); it can be edited in the
admin site without a migration."""
from django.db import migrations

EDA_ITEMS = [
    {'key': 'license',        'label': 'ترخيص الصيدلية واسم المدير الفني معلّقين وساريين'},
    {'key': 'pharmacist',     'label': 'صيدلي مُسجَّل متواجد طوال ساعات العمل'},
    {'key': 'fridge_log',     'label': 'سجل حرارة الثلاجة مكتمل آخر 30 يوم (قراءتين يومياً)'},
    {'key': 'fridge_range',   'label': 'الثلاجة بين 2 و8 °م وبها ترمومتر يعمل'},
    {'key': 'room_temp',      'label': 'حرارة المكان أقل من 25 °م ومفيش رطوبة أو شمس مباشرة على الأصناف'},
    {'key': 'expired',        'label': 'لا أصناف منتهية على الرفوف؛ المنتهي معزول ومُعلَّم'},
    {'key': 'controlled',     'label': 'دفتر المخدرات والجداول محدّث والدولاب مقفول'},
    {'key': 'rx_register',    'label': 'دفتر الروشتات / صرف الأدوية المقيدة محدّث'},
    {'key': 'unregistered',   'label': 'لا أصناف غير مسجلة أو مهربة أو عينات مجانية للبيع'},
    {'key': 'prices',         'label': 'الأسعار مطابقة للتسعيرة الرسمية وواضحة'},
    {'key': 'invoices',       'label': 'فواتير الشراء من موردين مرخّصين متاحة'},
    {'key': 'cleanliness',    'label': 'النظافة ومكافحة الحشرات (عقد / آخر رشّ)'},
    {'key': 'medical_waste',  'label': 'التخلص من النفايات الطبية (عقد / إيصالات)'},
    {'key': 'staff_docs',     'label': 'شهادات صحية وكارنيهات العاملين سارية'},
]


def seed(apps, schema_editor):
    Template = apps.get_model('qa', 'QAChecklistTemplate')
    if not Template.objects.filter(name='eda_visit').exists():
        Template.objects.create(name='eda_visit', name_ar='تجهيز زيارة هيئة الدواء', items=EDA_ITEMS,
                                is_active=True)


def unseed(apps, schema_editor):
    apps.get_model('qa', 'QAChecklistTemplate').objects.filter(name='eda_visit').delete()


class Migration(migrations.Migration):
    dependencies = [('qa', '0003_c31_fridge_log')]
    operations = [migrations.RunPython(seed, unseed)]
