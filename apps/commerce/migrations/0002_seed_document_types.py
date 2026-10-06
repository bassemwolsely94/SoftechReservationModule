from decimal import Decimal

from django.db import migrations


TYPES = [
    # code, name, prefix, pricing_profile, is_allocation, lifecycle
    ('quotation', 'عرض سعر', 'QT', 'manual_line', False,
     [{'code': 'draft', 'label': 'مسودة'}, {'code': 'sent', 'label': 'مُرسل'},
      {'code': 'accepted', 'label': 'مقبول'}, {'code': 'rejected', 'label': 'مرفوض'}]),
    ('retail_invoice', 'فاتورة بيع', 'INV', 'manual_line', False,
     [{'code': 'draft', 'label': 'مسودة'}, {'code': 'issued', 'label': 'صادرة'},
      {'code': 'paid', 'label': 'مدفوعة'}, {'code': 'cancelled', 'label': 'ملغاة'}]),
    ('allocation', 'شبكة توزيع', 'ALC', 'manual_line', True,
     [{'code': 'draft', 'label': 'مسودة'}, {'code': 'confirmed', 'label': 'مؤكدة'}]),
]


def seed(apps, schema_editor):
    DocumentType = apps.get_model('commerce', 'DocumentType')
    for code, name, prefix, pricing, is_alloc, lifecycle in TYPES:
        DocumentType.objects.update_or_create(
            code=code,
            defaults={
                'name': name, 'number_prefix': prefix, 'pricing_profile': pricing,
                'is_allocation': is_alloc, 'lifecycle': lifecycle,
                'default_vat_rate': Decimal('14.00'), 'is_active': True,
            },
        )


def unseed(apps, schema_editor):
    DocumentType = apps.get_model('commerce', 'DocumentType')
    DocumentType.objects.filter(code__in=[t[0] for t in TYPES]).delete()


class Migration(migrations.Migration):
    dependencies = [('commerce', '0001_initial')]
    operations = [migrations.RunPython(seed, unseed)]
