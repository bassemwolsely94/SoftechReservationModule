# The folded name (apps/catalog/wildcard.FOLD_SQL) now deletes only the marks the catalog
# holds — tatweel U+0640 and the harakat U+064B–U+0652 — instead of ~55 marks. translate()
# scans its from-list for every character, and the long list slowed every folded LIKE
# on the real catalog ('%1%cream' via item_search ≈92 ms; ≈57 ms after). PostgreSQL uses an
# expression index only for the same expression, so the four fold
# indexes of 0044 (trigram) and 0045 (prefix) are built again on the v2 expression.
# Lock window: the new indexes are built FIRST under temporary names (CREATE INDEX holds only a
# SHARE lock — reads go on, writes wait); only then are the old ones dropped and the new ones
# renamed to the final names. DROP INDEX takes ACCESS EXCLUSIVE on catalog_item, so that lock
# now covers only the instant drops + renames, not the four builds.
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


NAMES = ('catalog_item_name_fold_trgm', 'catalog_item_sci_fold_trgm',
         'catalog_item_name_fold_prefix', 'catalog_item_sci_fold_prefix')
TMP = '_v_new'                                     # the build name: <final name> + TMP


def _create(name_expr, sci_expr, suffix=''):
    n = [x + suffix for x in NAMES]
    return [
        'CREATE INDEX IF NOT EXISTS ' + n[0] + ' '
        'ON catalog_item USING gin ((' + name_expr + ') gin_trgm_ops)',
        'CREATE INDEX IF NOT EXISTS ' + n[1] + ' '
        'ON catalog_item USING gin ((' + sci_expr + ') gin_trgm_ops)',
        'CREATE INDEX IF NOT EXISTS ' + n[2] + ' '
        'ON catalog_item ((' + name_expr + ') text_pattern_ops)',
        'CREATE INDEX IF NOT EXISTS ' + n[3] + ' '
        'ON catalog_item ((' + sci_expr + ') text_pattern_ops)',
    ]


DROP = ['DROP INDEX IF EXISTS ' + n for n in NAMES]
DROP_TMP = ['DROP INDEX IF EXISTS ' + n + TMP for n in NAMES]    # a leftover of a failed run
RENAME = ['ALTER INDEX ' + n + TMP + ' RENAME TO ' + n for n in NAMES]
# the FINAL-name statements — what the indexes are once this migration has run
# (search_probe --with-temp-indexes builds and compares these)
CREATE = _create(FOLD_NAME, FOLD_SCI)              # v2
CREATE_V1 = _create(FOLD_NAME_V1, FOLD_SCI_V1)

# build under the temporary names, THEN drop the old + rename (the short exclusive part)
SQL = DROP_TMP + _create(FOLD_NAME, FOLD_SCI, TMP) + DROP + RENAME
REVERSE = DROP_TMP + _create(FOLD_NAME_V1, FOLD_SCI_V1, TMP) + DROP + RENAME


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0046_code_part_trgm'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE),
    ]
