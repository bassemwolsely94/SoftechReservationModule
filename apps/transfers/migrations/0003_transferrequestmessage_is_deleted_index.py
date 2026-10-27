"""
Migration: transfers 0007  (logically after 0006 in this codebase)

Add db_index=True to TransferRequestMessage.is_deleted.

Chatter fetches filter is_deleted=False for every request detail load;
without the index this is a full-table scan on the messages table.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transfers', '0006_transferrequestmessage_soft_delete'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transferrequestmessage',
            name='is_deleted',
            field=models.BooleanField(
                default=False,
                db_index=True,
                verbose_name='محذوف',
            ),
        ),
    ]
