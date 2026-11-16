# The item search `starts` tier (apps/catalog/wildcard._rank_name_ids) asks
# FOLD(name) LIKE 'TAB%'. The trigram indexes (0044) answer that poorly — pg_trgm pads every
# WORD, so 'TAB%' also fetches every name with a word starting TA… (≈3,000 rows rechecked).
# A b-tree on the same folded expression with text_pattern_ops answers a prefix LIKE as a
# range scan. Same (frozen) FOLD_SQL expression as the lookups, or PostgreSQL won't use the index.
# Catalog only; nothing here touches SOFTECH sync.

from django.db import migrations

# FROZEN copy of apps.catalog.wildcard.FOLD_SQL (with tashkeel / tatweel deletion), pasted
# here so a later edit of the app constant cannot silently change what this migration builds.
# apps/tests/test_wildcard_search.FoldSqlFrozenTests asserts the two are equal: any change to
# FOLD_SQL must come with a NEW migration that drops and rebuilds these indexes.
FOLD_NAME = ("regexp_replace(translate(upper(coalesce(name,'')), "
     "'أإآٱةىؤئ"
     "\u0640\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0653\u0654\u0655\u0656\u0657\u0658\u0659\u065a\u065b\u065c\u065d\u065e\u065f\u0670\u06d6\u06d7\u06d8\u06d9\u06da\u06db\u06dc\u06dd\u06de\u06df\u06e0\u06e1\u06e2\u06e3\u06e4\u06e5\u06e6\u06e7\u06e8\u06e9\u06ea\u06eb\u06ec\u06ed"
     r"', 'ااااهيوي'), '\s+', ' ', 'g')")
FOLD_SCI = ("regexp_replace(translate(upper(coalesce(name_scientific,'')), "
     "'أإآٱةىؤئ"
     "\u0640\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0653\u0654\u0655\u0656\u0657\u0658\u0659\u065a\u065b\u065c\u065d\u065e\u065f\u0670\u06d6\u06d7\u06d8\u06d9\u06da\u06db\u06dc\u06dd\u06de\u06df\u06e0\u06e1\u06e2\u06e3\u06e4\u06e5\u06e6\u06e7\u06e8\u06e9\u06ea\u06eb\u06ec\u06ed"
     r"', 'ااااهيوي'), '\s+', ' ', 'g')")

SQL = [
    'CREATE INDEX IF NOT EXISTS catalog_item_name_fold_prefix '
    'ON catalog_item ((' + FOLD_NAME + ') text_pattern_ops)',
    'CREATE INDEX IF NOT EXISTS catalog_item_sci_fold_prefix '
    'ON catalog_item ((' + FOLD_SCI + ') text_pattern_ops)',
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
