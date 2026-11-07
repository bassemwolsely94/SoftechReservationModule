"""Channel rules as the owner stated them on 2026-11-06. Marked unconfirmed: the accountant confirms or
changes them on the screen. Any channel not listed stays undecided, so its sales are held."""
from django.db import migrations

RULES = [
    ('91', 'عميل نقدى', 'receipt'),
    ('90', 'عميل Delivery', 'receipt'),
    ('12', 'إيصال إلكترونى بالبطاقة الشخصية', 'receipt'),
    ('16', 'تبرعات', 'receipt'),
    ('10', 'تعاقدات / آجل', 'invoice'),
]
NOTE = 'من كلام المالك 2026-11-06، بانتظار تأكيد المحاسب'


def seed(apps, schema_editor):
    TaxChannelRule = apps.get_model('tax_invoicing', 'TaxChannelRule')
    for code, label, mode in RULES:
        TaxChannelRule.objects.get_or_create(ptclassifcode=code, defaults={'label': label, 'mode': mode, 'note': NOTE})


def unseed(apps, schema_editor):
    apps.get_model('tax_invoicing', 'TaxChannelRule').objects.filter(ptclassifcode__in=[r[0] for r in RULES], confirmed_at__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [('tax_invoicing', '0002_seed_tax_invoicing_permissions')]
    operations = [migrations.RunPython(seed, unseed)]
