"""
Query-budget harness (performance stage 1). A guarded endpoint is called once, `grow()` adds many
rows, and it is called again: both calls must succeed, the second must really carry the rows, the
query count must not grow with the rows (no per-row queries) and must stay under the route's ceiling
in apps/tests/perf/budgets.py. Counts are asserted, not milliseconds: CI timings are not stable.
"""
import os
import re
from collections import Counter
from typing import Callable

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core import branch_scope

from .budgets import BUDGETS

SLACK = 1   # after M3 (fresh user per call) the only gaps left are real first-call queries (1)
_LITERALS =re.compile(r"'(?:[^']|'')*'|\b\d+(?:\.\d+)?\b")


def default_rows(resp) -> int:
    data = getattr(resp, 'data', None)
    if isinstance(data, dict) and isinstance(data.get('results'), list):
        return len(data['results'])
    if isinstance(data, list):
        return len(data)
    return 0


def measure(client, url: str, *, method: str = 'get', data=None):
    """(query count, response) for one call, with every cache that could hide a query cleared.

    The forced user is reloaded from the database before each call: force_authenticate keeps one
    in-memory User across requests, so its cached staff_profile hid ~1 query on the second call
    that every real (JWT) request runs (Stage 1 review, M3)."""
    cache.clear()
    branch_scope.bump_generation()
    forced = getattr(getattr(client, 'handler', None), '_force_user', None)
    if forced is not None:
        client.force_authenticate(user=type(forced).objects.get(pk=forced.pk))
    with CaptureQueriesContext(connection) as ctx:
        if method == 'get':
            resp = client.get(url, data or {})
        else:
            resp = getattr(client, method)(url, data or {}, format='json')
    return len(ctx.captured_queries), resp, ctx.captured_queries


def _top_shapes(queries, n=5) -> str:
    shapes = Counter(_LITERALS.sub('?', q['sql'])[:200] for q in queries)
    return '\n'.join(f'  {c}× {s}' for s, c in shapes.most_common(n))


def assert_budget(testcase, name: str, client, url: str, *, grow: Callable[[], None], min_rows: int,
                  rows_of: Callable = default_rows, method: str = 'get', data=None) -> None:
    budget = BUDGETS[name]
    before, resp1, _ = measure(client, url, method=method, data=data)
    testcase.assertIn(resp1.status_code, (200, 201, 204), f'{name}: first call returned {resp1.status_code}')
    grow()
    after, resp2, queries = measure(client, url, method=method, data=data)
    testcase.assertIn(resp2.status_code, (200, 201, 204), f'{name}: second call returned {resp2.status_code}')
    testcase.assertGreaterEqual(rows_of(resp2), min_rows,
                                f'{name}: grow() rows did not reach the response — the test proves nothing')
    if os.environ.get('PERF_BUDGET_REPORT'):   # baseline table: PERF_BUDGET_REPORT=1 manage.py test apps.tests.perf
        print(f'\nPERF {name} | {budget.kind} | {before} → {after} queries | ceiling {budget.ceiling}')
    # SLACK absorbs one-off queries (a first-call setting seed, a dedupe row); a per-row query adds one
    # per grown row, which is always far more than SLACK because grow() adds 10+ rows.
    testcase.assertLessEqual(abs(after - before), SLACK, f'{name}: queries grow with rows ({before} → {after}):\n'
                                                         f'{_top_shapes(queries)}')
    # the dearer of the two calls must fit (a de-duplicating tracker inserts on the first call only;
    # Stage 1 review, M2)
    worst = max(before, after)
    testcase.assertLessEqual(worst, budget.ceiling, f'{name}: {worst} queries > ceiling {budget.ceiling}:\n'
                                                    f'{_top_shapes(queries)}')
