# Item search matches on a FOLDED name (apps/catalog/wildcard.FOLD_SQL): Arabic letter
# variants (أإآ→ا ة→ه ى→ي ؤ→و ئ→ي), upper case, space runs collapsed. A trigram GIN index on
# exactly that expression lets '%…%' patterns be answered from the index. The expression is
# the SAME constant the `fulike` lookup renders — PostgreSQL only uses an expression index
# when the query's expression matches it. Catalog only; nothing here touches SOFTECH sync.

from django.db import migrations

from apps.catalog.wildcard import FOLD_SQL

SQL = [
    'CREATE INDEX IF NOT EXISTS catalog_item_name_fold_trgm '
    'ON catalog_item USING gin ((' + FOLD_SQL.format(col='name') + ') gin_trgm_ops)',
    'CREATE INDEX IF NOT EXISTS catalog_item_sci_fold_trgm '
    'ON catalog_item USING gin ((' + FOLD_SQL.format(col='name_scientific') + ') gin_trgm_ops)',
]
REVERSE = [
    'DROP INDEX IF EXISTS catalog_item_name_fold_trgm',
    'DROP INDEX IF EXISTS catalog_item_sci_fold_trgm',
]


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0043_item_shortage_softech_before'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE),
    ]
