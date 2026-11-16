# The folded name (apps/catalog/wildcard.FOLD_SQL) now deletes only the marks the catalog
# holds — tatweel U+0640 and the harakat U+064B–U+0652 — instead of ~55 marks. translate()
# scans its from-list for every character, and the long list slowed every folded LIKE
# on the real catalog ('%1%cream' via item_search ≈92 ms; ≈57 ms after). PostgreSQL uses an
# expression index only for the same expression, so the four fold
# indexes of 0044 (trigram) and 0045 (prefix) are dropped and built again on the v2 expression.
# 0044 / 0045 stay as they are (history); the reverse here rebuilds the v1 indexes.
# Catalog only; nothing here touches SOFTECH sync.

from django.db import migrations

# FROZEN copies — the v2 expression is apps.catalog.wildcard.FOLD_SQL, pasted here so a later
# edit of the app constant cannot silently change what this migration builds.
# apps/tests/test_wildcard_search.FoldSqlFrozenTests asserts FOLD_NAME / FOLD_SCI equal
# FOLD_SQL: any change to FOLD_SQL must come with a NEW migration that rebuilds these indexes.
FOLD_NAME = ("regexp_replace(translate(upper(coalesce(name,'')), "
     "'أإآٱةىؤئ"
     "ـًٌٍَُِّْ"
     r"', 'ااااهيوي'), '\s+', ' ', 'g')")
FOLD_SCI = ("regexp_replace(translate(upper(coalesce(name_scientific,'')), "
     "'أإآٱةىؤئ"
     "ـًٌٍَُِّْ"
     r"', 'ااااهيوي'), '\s+', ' ', 'g')")

# v1 — the expression of 0044 / 0045, for the reverse
FOLD_NAME_V1 = ("regexp_replace(translate(upper(coalesce(name,'')), "
     "'أإآٱةىؤئ"
     "ـًٌٍَُِّْٰٕٖٜٟٓٔٗ٘ٙٚٛٝٞۖۗۘۙۚۛۜ۝۞ۣ۟۠ۡۢۤۥۦۧۨ۩۪ۭ۫۬"
     r"', 'ااااهيوي'), '\s+', ' ', 'g')")
FOLD_SCI_V1 = ("regexp_replace(translate(upper(coalesce(name_scientific,'')), "
     "'أإآٱةىؤئ"
     "ـًٌٍَُِّْٰٕٖٜٟٓٔٗ٘ٙٚٛٝٞۖۗۘۙۚۛۜ۝۞ۣ۟۠ۡۢۤۥۦۧۨ۩۪ۭ۫۬"
     r"', 'ااااهيوي'), '\s+', ' ', 'g')")


def _create(name_expr, sci_expr):
    return [
        'CREATE INDEX IF NOT EXISTS catalog_item_name_fold_trgm '
        'ON catalog_item USING gin ((' + name_expr + ') gin_trgm_ops)',
        'CREATE INDEX IF NOT EXISTS catalog_item_sci_fold_trgm '
        'ON catalog_item USING gin ((' + sci_expr + ') gin_trgm_ops)',
        'CREATE INDEX IF NOT EXISTS catalog_item_name_fold_prefix '
        'ON catalog_item ((' + name_expr + ') text_pattern_ops)',
        'CREATE INDEX IF NOT EXISTS catalog_item_sci_fold_prefix '
        'ON catalog_item ((' + sci_expr + ') text_pattern_ops)',
    ]


DROP = [
    'DROP INDEX IF EXISTS catalog_item_name_fold_trgm',
    'DROP INDEX IF EXISTS catalog_item_sci_fold_trgm',
    'DROP INDEX IF EXISTS catalog_item_name_fold_prefix',
    'DROP INDEX IF EXISTS catalog_item_sci_fold_prefix',
]
CREATE = _create(FOLD_NAME, FOLD_SCI)              # v2 (search_probe --with-temp-indexes uses these)
CREATE_V1 = _create(FOLD_NAME_V1, FOLD_SCI_V1)

SQL = DROP + CREATE
REVERSE = DROP + CREATE_V1


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0046_code_part_trgm'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE),
    ]
