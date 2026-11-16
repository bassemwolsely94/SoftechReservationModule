# Item search matches on a FOLDED name (apps/catalog/wildcard.FOLD_SQL): Arabic letter
# variants (أإآ→ا ة→ه ى→ي ؤ→و ئ→ي), tashkeel / tatweel deleted, upper case, space runs
# collapsed. A trigram GIN index on exactly that expression lets '%…%' patterns be answered
# from the index. The expression is a frozen copy of the constant the `fulike` lookup
# renders — PostgreSQL only uses an expression index when the query's expression matches
# it. Catalog only; nothing here touches SOFTECH sync.

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
    'CREATE INDEX IF NOT EXISTS catalog_item_name_fold_trgm '
    'ON catalog_item USING gin ((' + FOLD_NAME + ') gin_trgm_ops)',
    'CREATE INDEX IF NOT EXISTS catalog_item_sci_fold_trgm '
    'ON catalog_item USING gin ((' + FOLD_SCI + ') gin_trgm_ops)',
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
