# Speed up the shared catalog matcher (apps/shortage/matching.find_best_matches).
# Its candidate prefilter is Django `icontains`, which PostgreSQL runs as
#   UPPER("catalog_item"."name"::text) LIKE UPPER('%…%')
# — no b-tree helps, so every lookup scanned all ~51k items (0.85–1.5 s per query,
# measured 2026-10-04). A trigram GIN index on exactly that expression lets PostgreSQL
# answer '%…%' patterns from the index.

from django.db import migrations

SQL = [
    'CREATE INDEX IF NOT EXISTS catalog_item_upper_name_trgm '
    'ON catalog_item USING gin (UPPER(name::text) gin_trgm_ops)',
    'CREATE INDEX IF NOT EXISTS catalog_item_upper_sci_trgm '
    'ON catalog_item USING gin (UPPER(name_scientific::text) gin_trgm_ops)',
]
REVERSE = [
    'DROP INDEX IF EXISTS catalog_item_upper_name_trgm',
    'DROP INDEX IF EXISTS catalog_item_upper_sci_trgm',
]


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0040_alias_fold_digits'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE),
    ]
