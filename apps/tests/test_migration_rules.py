"""
Round 2, R6 step 2 — static rules for new migrations.

Three incidents came from migrations that were fine on a fresh test database and broke the live one:
  • 2026-08-16 and 2026-10-28: a NOT NULL column was added with a Django-side default only. Django
    fills old rows and then drops the default, so every writer that does not name the new column
    (a raw INSERT, the sync's bulk SQL, a process still on the old code) failed with a NOT NULL error.
  • 2026-11-03 (users 0008 drift): `CREATE TABLE IF NOT EXISTS` met a table that already existed with
    fewer columns. The statement did nothing, and the missing columns were never added.

So for every migration newer than the ones on `main` at 2026-11-05 (`LEGACY_LAST`):
  1. an `AddField` of a NOT NULL column carries a server default (`db_default=`);
  2. a `CREATE TABLE IF NOT EXISTS` is followed by `ADD COLUMN IF NOT EXISTS` for each column.
A migration that has to break a rule goes in `EXEMPT` with its reason.
"""
import re

from django.db import models
from django.db.migrations import operations as ops
from django.db.migrations.loader import MigrationLoader
from django.db.models.fields import NOT_PROVIDED
from django.test import SimpleTestCase

# Highest migration number per app directory on origin/main when round 2 R6 ran (2026-11-05).
# Everything above it is checked. Do not raise these numbers to let a migration through.
LEGACY_LAST = {
    'access': 7, 'approvals': 5, 'audit': 37, 'batches': 7, 'branches': 12, 'callcenter': 10,
    'campaigns': 3, 'catalog': 43, 'cheques': 2, 'chronic': 5, 'commerce': 2, 'composition': 4,
    'config': 3, 'counselling': 3, 'customers': 31, 'delivery': 10, 'demand': 10,
    'discount_approvals': 6, 'enrichment': 4, 'erp': 1, 'finance': 22, 'followups': 16,
    'forecasting': 13, 'gamification': 3, 'help': 12, 'hr': 6, 'images': 3, 'incentives': 11,
    'insights': 4, 'insurance': 35, 'invoices': 22, 'lineage': 1, 'loyalty': 3, 'notifications': 42,
    'offers': 7, 'omni': 4, 'payments': 3, 'pbx': 9, 'personal': 4, 'pic_analytics': 5, 'portal': 1,
    'pos_orders': 17, 'procurement': 14, 'product_experience': 2, 'purchasing': 43, 'qa': 2,
    'recommendations': 2, 'referral': 1, 'replacement': 8, 'reservations': 23, 'shortage': 4,
    'social': 1, 'stock_audit': 4, 'stockcount': 4, 'supply': 11, 'sync': 7, 'tasks': 3, 'trace': 1,
    'transfers': 11, 'transits': 8, 'usage_print': 2, 'users': 51, 'vision': 2, 'vouchers': 8,
    'whatsapp': 3,
}

# '<app dir>/<migration name>': 'reason'
EXEMPT = {
    # pushed to main without a server default; pbx 0011 adds db_default to both columns
    'pbx/0010_agent_webrtc': 'server defaults added by pbx/0011_webrtc_db_default',
}

_CREATE = re.compile(r'create\s+table\s+if\s+not\s+exists\s+("?[\w.]+"?)\s*\((.*?)\)\s*;',
                     re.I | re.S)
_CONSTRAINT_HEADS = ('constraint', 'primary', 'unique', 'foreign', 'check', 'exclude')


def _split_top(text):
    parts, depth, cur = [], 0, ''
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    return parts + [cur]


def _sql_texts(op):
    if not isinstance(op, ops.RunSQL):
        return []
    out = []
    for sql in (op.sql if isinstance(op.sql, (list, tuple)) else [op.sql]):
        if isinstance(sql, (list, tuple)):
            sql = sql[0]
        if isinstance(sql, str):
            out.append(sql)
    return out


def not_null_without_server_default(operations):
    """AddField ops adding a NOT NULL column with no db_default -> ['model.field', ...]."""
    bad = []
    for op in operations:
        if not isinstance(op, ops.AddField):
            continue
        f = op.field
        if f.many_to_many or f.null or isinstance(f, models.GeneratedField):
            continue
        if getattr(f, 'db_default', NOT_PROVIDED) is NOT_PROVIDED:
            bad.append(f'{op.model_name}.{op.name}')
    return bad


def create_if_not_exists_without_add_column(operations):
    """CREATE TABLE IF NOT EXISTS columns with no ADD COLUMN IF NOT EXISTS -> ['table.col', ...]."""
    sql = '\n'.join(s for op in operations for s in _sql_texts(op))
    bad = []
    for table, body in _CREATE.findall(sql):
        table = table.strip('"').split('.')[-1]
        for col_def in _split_top(body):
            col_def = col_def.strip()
            if not col_def or col_def.lower().startswith(_CONSTRAINT_HEADS):
                continue
            if 'primary key' in col_def.lower():
                continue                       # the table exists, so its key does too
            col = col_def.split()[0].strip('"')
            add = re.compile(rf'alter\s+table\s+(if\s+exists\s+)?"?{re.escape(table)}"?\s+[^;]*'
                             rf'add\s+column\s+if\s+not\s+exists\s+"?{re.escape(col)}"?\b', re.I | re.S)
            if not add.search(sql):
                bad.append(f'{table}.{col}')
    return bad


def _new_migrations():
    loader = MigrationLoader(None, ignore_no_migrations=True, load=True)
    out = []
    for (label, name), mig in loader.disk_migrations.items():
        module = type(mig).__module__
        if not module.startswith('apps.'):
            continue
        app_dir = module.split('.')[1]
        m = re.match(r'(\d{4})_', name)
        if not m:
            continue
        # an app born after the cutoff has no LEGACY_LAST entry: all its migrations are new
        if int(m.group(1)) > LEGACY_LAST.get(app_dir, 0):
            out.append((f'{app_dir}/{name}', mig))
    return sorted(out, key=lambda t: t[0])


class MigrationRuleTests(SimpleTestCase):

    def test_new_not_null_columns_have_a_server_default(self):
        bad = [f'{key}: {f}' for key, mig in _new_migrations() if key not in EXEMPT
               for f in not_null_without_server_default(mig.operations)]
        self.assertEqual(bad, [], 'NOT NULL AddField without db_default=:\n' + '\n'.join(bad))

    def test_create_table_if_not_exists_adds_every_column(self):
        bad = [f'{key}: {c}' for key, mig in _new_migrations() if key not in EXEMPT
               for c in create_if_not_exists_without_add_column(mig.operations)]
        self.assertEqual(bad, [], 'CREATE TABLE IF NOT EXISTS without ADD COLUMN IF NOT EXISTS:\n'
                         + '\n'.join(bad))

    def test_exemptions_are_reasoned_and_current(self):
        keys = {k for k, _ in _new_migrations()}
        for key, reason in EXEMPT.items():
            self.assertTrue(reason.strip(), key)
            self.assertIn(key, keys, f'stale exemption {key}')

    def test_legacy_numbers_are_frozen_to_existing_files(self):
        loader = MigrationLoader(None, ignore_no_migrations=True, load=True)
        have = {}
        for (label, name), mig in loader.disk_migrations.items():
            module = type(mig).__module__
            m = re.match(r'(\d{4})_', name)
            if module.startswith('apps.') and m:
                d = module.split('.')[1]
                have.setdefault(d, set()).add(int(m.group(1)))
        for app_dir, last in LEGACY_LAST.items():
            self.assertIn(last, have.get(app_dir, set()), app_dir)


class RuleSelfTests(SimpleTestCase):
    """The rules catch the shapes of the three incidents."""

    def test_rule_1_flags_a_django_side_default_only(self):
        flagged = not_null_without_server_default([
            ops.AddField('purchasehistory', 'sales_channel', models.CharField(max_length=10, default='')),
            ops.AddField('purchasehistory', 'ok_null', models.CharField(max_length=10, null=True)),
            ops.AddField('purchasehistory', 'ok_db', models.CharField(max_length=10, db_default='')),
        ])
        self.assertEqual(flagged, ['purchasehistory.sales_channel'])

    def test_rule_2_flags_a_create_if_not_exists_without_add_column(self):
        sql = ('CREATE TABLE IF NOT EXISTS users_x (id bigserial PRIMARY KEY, a int NOT NULL, '
               'b varchar(10) DEFAULT \'\', CONSTRAINT u UNIQUE (a));'
               'ALTER TABLE users_x ADD COLUMN IF NOT EXISTS a int;')
        self.assertEqual(create_if_not_exists_without_add_column([ops.RunSQL(sql)]), ['users_x.b'])
        fixed = sql + 'ALTER TABLE users_x ADD COLUMN IF NOT EXISTS b varchar(10);'
        self.assertEqual(create_if_not_exists_without_add_column([ops.RunSQL(fixed)]), [])

    def test_rule_2_reads_list_and_reverse_pair_forms(self):
        sql = 'CREATE TABLE IF NOT EXISTS t (id serial PRIMARY KEY, c text);'
        self.assertEqual(create_if_not_exists_without_add_column(
            [ops.RunSQL([(sql, None)], reverse_sql='DROP TABLE t;')]), ['t.c'])
