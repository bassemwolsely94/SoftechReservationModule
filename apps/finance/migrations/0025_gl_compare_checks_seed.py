from decimal import Decimal

from django.db import migrations

# blocks_close=False where finance's own figure is not reproduced from SOFTECH (doc 35, Source verification):
# sales (card tender), purchases (returns), expenses (dailyexpenses is petty cash only, not the expense groups);
# supplier balances never block (spec §11a). Stock does not block either: before a close 1390 is 0 by design, a
# missing snapshot is blocked by the close checklist's own stock item, and after the close the line reads ~0.
CHECKS = [
    dict(key='sales', label='المبيعات', kind='movement', account_codes=[], group_names=['المبيعات'],
         source='sales', sign='credit', per_party=False, blocks_close=False, order=10),
    dict(key='purchases', label='المشتريات', kind='movement', account_codes=[],
         group_names=['تكلفة المبيعات'], source='purchases', sign='debit', per_party=False,
         blocks_close=False, order=20),
    dict(key='stock_at_cost', label='المخزون بالتكلفة', kind='balance', account_codes=['1390'],
         group_names=[], source='stock_at_cost', sign='debit', per_party=False, blocks_close=False,
         order=30),
    dict(key='expenses', label='المصروفات', kind='movement', account_codes=[],
         group_names=['المصروفات العموميه', 'مصروفات بيع وتوزيع', 'مصروفات التشغيل'],
         source='expenses', sign='debit', per_party=False, blocks_close=False, order=40),
    dict(key='supplier_balance', label='أرصدة الموردين', kind='balance', account_codes=['2341'],
         group_names=[], source='supplier_balance', sign='credit', per_party=True, blocks_close=False,
         order=50),
]


def seed(apps, schema_editor):
    Check = apps.get_model('finance', 'GLSoftechCheck')
    for c in CHECKS:
        Check.objects.update_or_create(key=c['key'], defaults={**c, 'tolerance': Decimal('1.00')})


def unseed(apps, schema_editor):
    apps.get_model('finance', 'GLSoftechCheck').objects.filter(key__in=[c['key'] for c in CHECKS]).delete()


class Migration(migrations.Migration):

    dependencies = [('finance', '0024_gl_close')]

    operations = [migrations.RunPython(seed, unseed)]
