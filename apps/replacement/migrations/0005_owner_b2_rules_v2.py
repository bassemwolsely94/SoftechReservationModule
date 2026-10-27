"""
Owner decision 2026-10-03: non-insurance client (B2) rates confirmed — products 40 %, cash 50 %.

Rules are versioned and never edited: where the inactive v1 placeholders exist (seeded
2026-10-02), add ACTIVE v2 rows; v1 stays for history. Cash goes to 4069 «مورد عام 50%».
No-op on a database where seed_replacement has not run yet (the seed itself now has the rates).
"""
from datetime import date
from decimal import Decimal

from django.db import migrations

V2 = [
    ('B2_PRODUCTS', 'عميل غير تأمين يبيع أدوية — منتجات', 'products', Decimal('40'), '3068'),
    ('B2_CASH',     'عميل غير تأمين يبيع أدوية — نقدي',   'cash',     Decimal('50'), '4069'),
]


def forwards(apps, schema_editor):
    Rule = apps.get_model('replacement', 'ReplacementRule')
    for key, name, mode, pct, sup in V2:
        latest = Rule.objects.filter(rule_key=key).order_by('-version').first()
        if latest is None or (latest.is_active and latest.deduction_pct == pct and latest.supplier_personcode == sup):
            continue
        Rule.objects.create(rule_key=key, version=latest.version + 1, name=name, source_type='client_buyback',
                            settlement_mode=mode, shortage_only=False, deduction_pct=pct, supplier_personcode=sup,
                            rounding=latest.rounding, priority=latest.priority, effective_from=date(2026, 10, 3),
                            is_active=True)


def backwards(apps, schema_editor):
    Rule = apps.get_model('replacement', 'ReplacementRule')
    # only remove v2 rows nobody has calculated with (calculations PROTECT their rule)
    for key, *_ in V2:
        for r in Rule.objects.filter(rule_key=key, version__gte=2, effective_from=date(2026, 10, 3)):
            if not r.calculations.exists():
                r.delete()


class Migration(migrations.Migration):
    dependencies = [('replacement', '0004_replacementcase_approval_no_and_more')]
    operations = [migrations.RunPython(forwards, backwards)]
