"""
apps/delivery/migrations/0004_delivery_fix_unique_constraints.py

Fix two uniqueness bugs discovered during full branch sync:

1. softech_crm_order_no unique constraint removed.
   crmorderno is NOT globally unique — it is only unique per branch.
   Branch 130 orderno=166399 can collide with HQ orderno=166399.
   Replaced with a composite UniqueConstraint (softech_crm_branch, softech_crm_order_no).

2. order_number changed from blank unique to nullable unique.
   During bulk import, multiple rows had order_number='' simultaneously,
   violating the unique constraint on the blank string.
   PostgreSQL unique indexes ignore NULL values, so null=True fixes this.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('delivery', '0003_delivery_softech_crm_fields'),
    ]

    operations = [
        # ── 1. Fix order_number: blank unique → nullable unique ───────────────
        migrations.AlterField(
            model_name='deliveryorder',
            name='order_number',
            field=models.CharField(
                blank=True, null=True, db_index=True, max_length=20, unique=True,
                verbose_name='رقم الطلب',
            ),
        ),

        # ── 2. Remove the single-column unique constraint on softech_crm_order_no ─
        migrations.AlterField(
            model_name='deliveryorder',
            name='softech_crm_order_no',
            field=models.IntegerField(
                blank=True, null=True, db_index=True,
                verbose_name='رقم طلب CRM (SOFTECH)',
                help_text='piccrmorders.crmorderno — فريد فقط بالتركيب مع softech_crm_branch',
            ),
        ),

        # Remove the old single-column index added in migration 0003
        migrations.RemoveIndex(
            model_name='deliveryorder',
            name='del_order_crm_no',
        ),

        # ── 3. Add composite unique constraint ────────────────────────────────
        migrations.AddConstraint(
            model_name='deliveryorder',
            constraint=models.UniqueConstraint(
                fields=['softech_crm_branch', 'softech_crm_order_no'],
                condition=models.Q(softech_crm_order_no__isnull=False),
                name='del_order_crm_branch_orderno_uniq',
            ),
        ),
    ]
