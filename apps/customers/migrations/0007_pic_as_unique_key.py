"""
Migration 0007 — Make softech_pic the unique customer key.

softech_id (branchcustcode) is NOT globally unique — the same number exists
for different customers in different branches.  softech_pic (phcode, e.g.
"12HD28") IS globally unique.

Steps in the correct order:
  1. Drop unique constraint on softech_id (keep it as a plain index).
  2. Make softech_pic nullable (drop its NOT NULL constraint first).
  3. Convert existing softech_pic='' rows to NULL.
  4. Add unique constraint on softech_pic (NULLs are excluded from uniqueness
     in PostgreSQL, so customers without a PIC don't collide).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0006_customer_softech_pic'),
    ]

    operations = [
        # 1. Remove unique from softech_id — keep the index, drop the constraint
        migrations.AlterField(
            model_name='customer',
            name='softech_id',
            field=models.CharField(
                blank=True, db_index=True, max_length=13, null=True,
            ),
        ),

        # 2. Make softech_pic nullable FIRST (the column is currently NOT NULL)
        migrations.AlterField(
            model_name='customer',
            name='softech_pic',
            field=models.CharField(
                blank=True, db_index=True, max_length=30, null=True,
                verbose_name='كود العميل (PIC)',
                help_text='الكود المركب: {كودالفرع}HD{رقمالعميل} — مثال: 01HD14 أو 130HD9969',
            ),
        ),

        # 3. Convert empty strings to NULL — safe now that the column allows NULL
        migrations.RunSQL(
            sql="UPDATE customers_customer SET softech_pic = NULL WHERE softech_pic = '';",
            reverse_sql=migrations.RunSQL.noop,
        ),

        # 4. Add unique constraint (PostgreSQL allows multiple NULLs in a unique
        #    column, so customers without a PIC never collide with each other)
        migrations.AlterField(
            model_name='customer',
            name='softech_pic',
            field=models.CharField(
                blank=True, db_index=True, max_length=30, null=True, unique=True,
                verbose_name='كود العميل (PIC)',
                help_text='الكود المركب: {كودالفرع}HD{رقمالعميل} — مثال: 01HD14 أو 130HD9969',
            ),
        ),
    ]
