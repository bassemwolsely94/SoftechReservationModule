"""P-26: StockExpiryBalance.store_role, back-filled from the default store-role map (no SOFTECH access)."""
from django.db import migrations, models


def backfill(apps, schema_editor):
    from apps.batches.store_roles import DEFAULT_MAP, LIVE
    Balance = apps.get_model('batches', 'StockExpiryBalance')
    Branch = apps.get_model('branches', 'Branch')
    closed = list(Branch.objects.filter(kind='closed').values_list('softech_branch_id', flat=True))
    Balance.objects.update(store_role=LIVE)
    for key, role in DEFAULT_MAP.items():
        node, store = key.split(':')
        qs = Balance.objects.filter(store_code=store)
        if node != '*':
            qs = qs.filter(branch_code=node)
        qs.update(store_role=role)
    if closed:
        Balance.objects.filter(branch_code__in=closed).update(store_role='closed')


class Migration(migrations.Migration):

    dependencies = [
        ('batches', '0005_expirydisposalrecord'),
        ('branches', '0006_branch_kind_branch_pos_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='stockexpirybalance',
            name='store_role',
            field=models.CharField(blank=True, db_index=True, default='', max_length=20,
                                   verbose_name='دور المخزن'),
        ),
        # DB default: a process still on the old code (between migrate and restart) inserts rows
        # without the column (docs: postgres schema drift lesson).
        migrations.RunSQL("ALTER TABLE batches_stockexpirybalance ALTER COLUMN store_role SET DEFAULT ''",
                          migrations.RunSQL.noop),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
