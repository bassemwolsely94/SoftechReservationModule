"""
Add DB-level DEFAULTs to catalog_item's NOT NULL boolean columns.

Django's BooleanField(default=…) applies the default in PYTHON only — the
Postgres column is created NOT NULL with no server default. That means ANY
INSERT path that omits one of these columns fails with a not-null violation and
aborts the whole 50k-row items bulk_create (cascading the entire slow-sync lane).

This bit us when a long-running sync process ran a tasks.py from before
`no_more_use` was added to the Item(...) build: after migration 0025 made the
column NOT NULL, that stale process's INSERT sent null → the sync failed. A fresh
process sets the field correctly, so it couldn't be reproduced afterward.

Setting a server DEFAULT that matches each model default makes the schema
self-healing: an insert that omits the column gets the correct default and the
next correct sync updates it via ON CONFLICT. Reversible (DROP DEFAULT).
"""
from django.db import migrations

# column → SQL default (matches the model field default=)
_DEFAULTS = {
    'no_more_use':    'false',
    'item_archive':   'false',
    'is_active':      'true',
    'is_stockable':   'true',
    'is_fast_moving': 'false',
    'is_imported':    'false',
    'requires_fridge':'false',
    'has_points':     'false',
}


def _set_defaults(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        for col, val in _DEFAULTS.items():
            c.execute(f'ALTER TABLE catalog_item ALTER COLUMN {col} SET DEFAULT {val}')


def _drop_defaults(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        for col in _DEFAULTS:
            c.execute(f'ALTER TABLE catalog_item ALTER COLUMN {col} DROP DEFAULT')


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0026_item_item_archive'),
    ]
    operations = [
        migrations.RunPython(_set_defaults, _drop_defaults),
    ]
