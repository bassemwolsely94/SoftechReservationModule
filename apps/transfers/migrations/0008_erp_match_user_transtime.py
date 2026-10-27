"""
apps/transfers/migrations/0008_erp_match_user_transtime.py

Add ERP user identity fields and transaction timestamp to TransferRequest.
All fields are additive — no drops, no renames, safe on live data.

New fields:
  erp_match_user_id    — userid (login name) from SOFTECH users table
  erp_match_user_name  — full display name from SOFTECH users table
  erp_match_trans_time — exact trans_time from stktrans (datetime, not date-only)
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transfers', '0007_erp_match_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='transferrequest',
            name='erp_match_user_id',
            field=models.CharField(
                blank=True, max_length=100,
                verbose_name='اسم مستخدم ERP (userid)',
            ),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_match_user_name',
            field=models.CharField(
                blank=True, max_length=200,
                verbose_name='الاسم الكامل للمستخدم (ERP)',
            ),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_match_trans_time',
            field=models.DateTimeField(
                blank=True, null=True,
                verbose_name='وقت تنفيذ المعاملة (ERP)',
            ),
        ),
    ]
