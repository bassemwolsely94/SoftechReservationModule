"""
Migration 0008 — Add sales_channel to PurchaseHistory.

Denormalize the customer's channel classification (softech_ptclassifcode) onto
each invoice row so analytics can group by channel without joining through the
Customer FK (which is unreliable because branchcustcode is not globally unique).

After adding the column we backfill it from the already-linked customer FK so
all existing records get their channel immediately — no need to wait for the
next sync run.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0007_pic_as_unique_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchasehistory',
            name='sales_channel',
            field=models.CharField(
                max_length=5, blank=True, default='',
                db_index=True,
                verbose_name='قناة البيع',
                help_text="'90'=توصيل  '91'=كاش  '15'=تأمين  ''=غير محدد",
            ),
        ),
        # Backfill from the already-joined customer record
        migrations.RunSQL(
            sql="""
                UPDATE customers_purchasehistory ph
                SET    sales_channel = c.softech_ptclassifcode
                FROM   customers_customer c
                WHERE  ph.customer_id = c.id
                  AND  ph.sales_channel = ''
                  AND  c.softech_ptclassifcode IS NOT NULL
                  AND  c.softech_ptclassifcode != '';
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
