"""
Give customers_customer.merged_into_pic a DB-level DEFAULT '' (P-56 §4).

0027 added the column NOT NULL with only a Python-side default, so a process started
before 0027 (the long-lived run_scheduler) would insert Customer rows without it → null
→ the slow-lane customer upsert aborts. Same fix and pattern as customers 0029 / sync
0005. '' already means "not merged". Reversible (DROP DEFAULT).
"""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('customers', '0029_purchasehistory_personcode_db_default'),
    ]
    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE customers_customer ALTER COLUMN merged_into_pic SET DEFAULT '';",
            reverse_sql="ALTER TABLE customers_customer ALTER COLUMN merged_into_pic DROP DEFAULT;",
        ),
    ]
