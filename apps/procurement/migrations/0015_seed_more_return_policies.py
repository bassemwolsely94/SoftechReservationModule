"""C03 follow-up (owner 2026-11-19: «Same as Pharma Overseas»): the named suppliers on the return
calendar's «no policy» list take expiry returns with the same −2 / +1 month window as 565 / 260.
Purchasing corrects any of them later in the policy editor (every edit is audited).

get_or_create only: a policy purchasing already entered is never overwritten. self_entry stays
False — whether a supplier lets us enter returns in its own system is not known for these.
"""
from django.db import migrations

SEED = (
    ('30', 'RAMCO PHARM'),
    ('118', 'قنديل للصناعة والتجارة'),
    ('3226', 'PARKVILLE PHARMA EGYPT'),
    ('156', 'MEC - Middle East Chemicals'),
    ('4327', 'EGY DRUG-ZAYTOUN'),
    ('786', 'EGY DRUG -SHERIF'),
)


def seed(apps, schema_editor):
    Policy = apps.get_model('procurement', 'SupplierReturnPolicy')
    Profile = apps.get_model('procurement', 'SupplierProfile')
    for code, name in SEED:
        prof = Profile.objects.filter(supplier_code=code).first()
        Policy.objects.get_or_create(supplier_code=code, defaults={
            'supplier_name': (prof.supplier_name if prof and prof.supplier_name else name),
            'accepts_expiry_returns': True, 'open_offset': -2, 'close_offset': 1, 'self_entry': False,
            'notes': 'نافذة مبدئية مثل فارما أوفرسيز (المالك 2026-11-19) — راجعها المشتريات'})


class Migration(migrations.Migration):

    dependencies = [
        ('procurement', '0014_receiptcheck_sheet_cover_alter_receiptcheck_flag'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
