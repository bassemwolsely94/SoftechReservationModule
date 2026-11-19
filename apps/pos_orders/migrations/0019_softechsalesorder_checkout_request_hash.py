# D-18 server checkout (doc 39 §2.5, S2): one nullable PostgreSQL-only column. Not synced to SOFTECH.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pos_orders', '0018_poslivecheckgap'),
    ]

    operations = [
        migrations.AddField(
            model_name='softechsalesorder',
            name='checkout_request_hash',
            field=models.CharField(blank=True, editable=False, max_length=64, null=True),
        ),
    ]
