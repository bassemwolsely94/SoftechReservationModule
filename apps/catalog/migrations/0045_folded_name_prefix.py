# The item search `starts` tier (apps/catalog/wildcard._rank_name_ids) asks
# FOLD(name) LIKE 'TAB%'. The trigram indexes (0044) answer that poorly — pg_trgm pads every
# WORD, so 'TAB%' also fetches every name with a word starting TA… (≈3,000 rows rechecked).
# A b-tree on the same folded expression with text_pattern_ops answers a prefix LIKE as a
# range scan. Same FOLD_SQL constant as the lookups, or PostgreSQL won't use the index.
# Catalog only; nothing here touches SOFTECH sync.

from django.db import migrations

from apps.catalog.wildcard import FOLD_SQL

SQL = [
    'CREATE INDEX IF NOT EXISTS catalog_item_name_fold_prefix '
    'ON catalog_item ((' + FOLD_SQL.format(col='name') + ') text_pattern_ops)',
    'CREATE INDEX IF NOT EXISTS catalog_item_sci_fold_prefix '
    'ON catalog_item ((' + FOLD_SQL.format(col='name_scientific') + ') text_pattern_ops)',
]
REVERSE = [
    'DROP INDEX IF EXISTS catalog_item_name_fold_prefix',
    'DROP INDEX IF EXISTS catalog_item_sci_fold_prefix',
]


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0044_folded_name_trgm'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE),
    ]
