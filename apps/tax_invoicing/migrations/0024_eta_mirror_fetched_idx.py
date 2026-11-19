"""
Performance Stage 3: the freshness bar reads the newest fetched_at per ETA system on every poll;
without an index that was a scan of the mirror (0.5 s for production receipts). CONCURRENTLY so the
history loader is never blocked while the index builds.
"""
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('tax_invoicing', '0023_eta_code_usage_itemcode_length'),
    ]

    operations = [
        AddIndexConcurrently(
            model_name='etamirrordocument',
            index=models.Index(fields=['system', 'fetched_at'], name='eta_mirror_doc_fetched'),
        ),
        AddIndexConcurrently(
            model_name='etamirrorreceipt',
            index=models.Index(fields=['system', 'fetched_at'], name='eta_mirror_rcpt_fetched'),
        ),
    ]
