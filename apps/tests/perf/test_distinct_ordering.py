"""
A model's default `Meta.ordering` silently widens `values()/values_list(...).distinct()`.

Django adds every ORDER BY column to a SELECT DISTINCT (PostgreSQL requires it), so on a model
with `Meta.ordering = ['-created_at']`, `values_list('lane', flat=True).distinct()` becomes
`SELECT DISTINCT lane, created_at ... ORDER BY created_at DESC` - one row per record instead of
one per distinct value. It happened twice before this guard: PERF-5 (purchasing filter options,
fixed 7694b905) and the sync failing-lanes heartbeat (~3,000 queries a minute, PR 291, found by
pg_stat_statements on 2026-11-21). The fix is `.order_by()` (clears the default ordering) or an
`order_by` on the selected fields when the order matters.

`DistinctOrderingGuard` walks apps/ with `ast` and fails on a `values/values_list(...)...distinct()`
chain with no `order_by(` in it, unless the queryset's model is known to have no Meta.ordering, the
result goes straight into `.count()` / `.exists()` (Django clears the ordering there), or the site is
on ALLOWED with a reason. A queryset the guard cannot trace to a model counts as ordered: add
`.order_by()` (harmless when there is no ordering) or an ALLOWED line.
"""
import ast
import os

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

APPS_DIR = os.path.join(settings.BASE_DIR, 'apps')
SKIP_DIRS = {'migrations', 'tests', '__pycache__', 'node_modules'}
CONSUMED = {'count', 'exists'}            # Django clears the ordering before running these

# Reviewed sites, keyed by (path under the repo, enclosing function) -> why it may stay as it is.
ALLOWED = {
    ('apps/sync/maintenance.py', 'alert_failing_lanes'):
        'widened (SyncRun -started_at); fixed by PR 291, which adds the .order_by() here',
    ('apps/offers/usage.py', 'precheck_order'):
        'widened (one offer id per order line) but harmless: the same offer is re-checked. POS '
        'checkout path - change held for owner approval (CLAUDE.md: stop and ask)',
    ('apps/offers/usage.py', 'consume_offer_uses'):
        'widened (one offer id per order line) but harmless: a repeat is skipped by the '
        'idempotency check. POS checkout path - change held for owner approval (CLAUDE.md)',
    ('apps/vouchers/coupon_guard.py', 'open_orders_holding'):
        'widened (SoftechSalesOrderLine id): an order holding the serial on 2 lines is listed '
        'twice in held_by_orders. POS order validation - change held for owner approval (CLAUDE.md)',
    ('apps/rpa/portal/queue.py', '_pull_other_baskets'):
        'selects pk: the extra job_id/seq columns belong to the same row, so no extra rows; '
        'keeps the (job, seq) processing order',
    ('apps/offers/views.py', 'field_values'):
        'ordered later by label_col (a selected field) before it is read',
    ('apps/pic_analytics/queries/options.py', 'filter_options'):
        'facts = PicDayFact / its annotations: no Meta.ordering',
    ('apps/pic_analytics/queries/overview.py', '*'):
        'facts = PicDayFact: no Meta.ordering',
    ('apps/pic_analytics/queries/retention.py', '*'):
        'facts = PicDayFact: no Meta.ordering',
}


def _ordered_model_names():
    """Class name -> True when any model of that name has a default ordering."""
    out = {}
    for m in apps.get_models():
        out[m.__name__] = out.get(m.__name__, False) or bool(m._meta.ordering)
    return out


def _chain(node):
    """(root expression, method names from the root outwards) of a call/attribute chain."""
    names = []
    while True:
        if isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
            node = node.value
        else:
            return node, list(reversed(names))


def _trace(root, func, lineno, depth=0):
    """Follow `qs = Model.objects...; qs = qs.filter(...)` back to the first root in `func`."""
    if not isinstance(root, ast.Name) or func is None or depth > 6:
        return root, []
    best = None
    for n in ast.walk(func):
        if isinstance(n, ast.Assign) and n.lineno < lineno and any(
                isinstance(t, ast.Name) and t.id == root.id for t in n.targets):
            if best is None or n.lineno > best.lineno:
                best = n
    if best is None:
        return root, []
    r, names = _chain(best.value)
    r2, more = _trace(r, func, best.lineno, depth + 1)
    return r2, more + names


def _model_name(root, aliases):
    """`Item.objects` / `Item._default_manager` / an import alias -> 'Item', else None."""
    if isinstance(root, ast.Name):
        name = aliases.get(root.id, root.id)
        return name if name[:1].isupper() else None
    return None


def find_widened(source, path, ordered=None):
    """Return [(path, line, function)] for unguarded values(...).distinct() chains in `source`."""
    ordered = _ordered_model_names() if ordered is None else ordered
    tree = ast.parse(source)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    aliases = {a.asname: a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
               for a in n.names if a.asname}
    hits = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == 'distinct' and not n.args):
            continue
        func = parents.get(n)
        while func is not None and not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = parents.get(func)
        root, names = _chain(n.func.value)
        root, pre = _trace(root, func, n.lineno)
        names = pre + names
        if not {'values', 'values_list'} & set(names):
            continue
        after, cur = [], n                   # methods called on the distinct() result
        while isinstance(parents.get(cur), ast.Attribute) and isinstance(parents.get(parents[cur]), ast.Call):
            after.append(parents[cur].attr)
            cur = parents[parents[cur]]
        if 'order_by' in names or 'order_by' in after or (after and after[0] in CONSUMED):
            continue
        model = _model_name(root, aliases)
        if model is not None and model in ordered and not ordered[model]:
            continue                         # a model with no Meta.ordering
        hits.append((path, n.lineno, func.name if func is not None else '<module>'))
    return hits


def _scan():
    ordered = _ordered_model_names()
    hits = []
    for dirpath, dirnames, filenames in os.walk(APPS_DIR):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith('.py') or fn.startswith('test'):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, settings.BASE_DIR).replace(os.sep, '/')
            with open(full, encoding='utf-8-sig') as fh:
                hits += find_widened(fh.read(), rel, ordered)
    return hits


def _allowed(path, func):
    return (path, func) in ALLOWED or (path, '*') in ALLOWED


class DistinctOrderingGuard(SimpleTestCase):

    def test_no_values_distinct_widened_by_meta_ordering(self):
        bad = [h for h in _scan() if not _allowed(h[0], h[2])]
        self.assertEqual(bad, [], (
            'values()/values_list().distinct() on a model with Meta.ordering: the ordering columns '
            'join the DISTINCT and it returns one row per record. Add .order_by() before .distinct() '
            '(or .order_by(<the selected fields>) when the order matters), or a reasoned ALLOWED entry '
            'in apps/tests/perf/test_distinct_ordering.py.\n' +
            '\n'.join(f'  {p}:{line} in {fn}()' for p, line, fn in bad)))

    def test_guard_catches_and_passes(self):
        ordered = {'Item': True, 'Fact': False}
        src = (
            'def a():\n    return Item.objects.values_list("x", flat=True).distinct()\n'          # 2 bad
            'def b():\n    return Item.objects.values("x").order_by().distinct()\n'
            'def c():\n    return Item.objects.values("x").distinct().order_by("x")\n'
            'def d():\n    return Item.objects.values("x").distinct().count()\n'
            'def e():\n    return Fact.objects.values("x").distinct()\n'
            'def f():\n    qs = Item.objects.filter(y=1)\n    qs = qs.exclude(z=2)\n'
            '    return list(qs.values_list("x").distinct())\n'                                    # 14 bad
            'def g(qs):\n    return qs.values("x").distinct()\n'                                   # 16 bad
            'def h():\n    return Item.objects.filter(y=1).distinct()\n'                            # rows
            'def i():\n    qs = Item.objects.order_by()\n    return qs.values("x").distinct()\n'
        )
        self.assertEqual([h[1] for h in find_widened(src, 'x.py', ordered)], [2, 14, 16])

    def test_allowed_entries_name_real_files(self):
        for path, _ in ALLOWED:
            self.assertTrue(os.path.exists(os.path.join(settings.BASE_DIR, path)), path)

    def test_the_mechanism_is_real(self):
        """Documents why: Item.Meta.ordering ('name') joins the DISTINCT unless cleared."""
        from apps.catalog.models import Item
        self.assertEqual(list(Item._meta.ordering), ['name'])
        widened = str(Item.objects.values_list('supplier_code', flat=True).distinct().query)
        fixed = str(Item.objects.values_list('supplier_code', flat=True).order_by().distinct().query)
        self.assertIn('"catalog_item"."name"', widened.split(' FROM ')[0])
        self.assertNotIn('"catalog_item"."name"', fixed.split(' FROM ')[0])


def distinct_select_lists(ctx):
    """The column list of every SELECT DISTINCT captured in `ctx`."""
    return [q['sql'].split(' FROM ')[0] for q in ctx.captured_queries
            if q['sql'].lstrip().upper().startswith('SELECT DISTINCT')]


class FixedSitesDistinctSqlTests(TestCase):
    """Regression per fixed module: the ordering column no longer joins the DISTINCT."""

    def test_batches_stock_expiry_report_and_stores(self):
        import datetime as dt
        from decimal import Decimal
        from apps.batches.models import StockExpiryBalance
        from apps.batches.stock_expiry import stock_expiry_report, stock_expiry_stores
        today = dt.date.today()
        for i in range(3):       # one item, one store, three expiry dates
            StockExpiryBalance.objects.create(branch_code='130', store_code='101', item_code='SX1',
                                              item_name='SX1', batch_no=f'b{i}', qty=Decimal('1'),
                                              expiry_date=today - dt.timedelta(days=10 + i))
        with CaptureQueriesContext(connection) as ctx:
            rows = stock_expiry_report(mode='all')
            stores = stock_expiry_stores()
        selects = distinct_select_lists(ctx)
        self.assertTrue(selects)
        for s in selects:
            self.assertNotIn('expiry_date', s)
        self.assertEqual([r['item_code'] for r in rows], ['SX1'])
        self.assertEqual([(s['branch_code'], s['store_code']) for s in stores], [('130', '101')])

    def test_help_done_tours(self):
        from apps.help.models import HelpEvent
        from apps.help.onboarding_views import _done_tours
        from ..factories import make_salesperson
        _, profile, _ = make_salesperson('distinct_tours')
        for _ in range(3):
            HelpEvent.objects.create(kind=HelpEvent.KIND_TOUR, screen_key='pos', query='done', staff=profile)
        with CaptureQueriesContext(connection) as ctx:
            done = _done_tours(profile)
        self.assertEqual(done, {'pos'})
        for s in distinct_select_lists(ctx):
            self.assertNotIn('created_at', s)

    def test_purchasing_operational_branches_one_row_per_branch(self):
        import datetime as dt
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        from apps.purchasing.shortage import operational_branches
        from ..factories import make_branch, make_item
        self.assertEqual(list(ItemDemandMetrics._meta.ordering), ['-priority'])
        run = DemandCalculationRun.objects.create(status='success', calc_date=dt.date.today())
        branch = make_branch()
        for i, prio in enumerate((10, 20, 30)):     # three items, three priorities, one branch
            ItemDemandMetrics.objects.create(run=run, item=make_item(f'دواء {i}', f'DX{i}'), branch=branch,
                                             calc_date=dt.date.today(), priority=prio)
        with CaptureQueriesContext(connection) as ctx:
            rows = operational_branches()
        self.assertEqual(rows, [(branch.id, branch.code)])
        selects = distinct_select_lists(ctx)
        self.assertTrue(selects)
        for s in selects:
            self.assertNotIn('priority', s)
