from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    """
    Trigram index on patient_name to speed up the motalba name-autocomplete
    lookups (icontains / similarity) as history grows.  pg_trgm is already used
    elsewhere (catalog.Item.search_name); TrigramExtension is idempotent.
    """

    dependencies = [
        ('insurance', '0024_insuranceclaimline_softech_line_net'),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name='insuranceclaimprescription',
            index=GinIndex(fields=['patient_name'],
                           name='ins_rx_pname_trgm',
                           opclasses=['gin_trgm_ops']),
        ),
        migrations.AddIndex(
            model_name='insuranceclaimmanualrx',
            index=GinIndex(fields=['patient_name'],
                           name='ins_mrx_pname_trgm',
                           opclasses=['gin_trgm_ops']),
        ),
    ]
