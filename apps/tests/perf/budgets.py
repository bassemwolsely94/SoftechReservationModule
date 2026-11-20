"""
Query budgets per guarded endpoint (performance stage 1, design
docs/superpowers/specs/2026-11-19-performance-boost-design.md §4 and §6 Stage 1).

`ceiling` = the most SQL queries one call may run in the budget test. It is "measured on the date in
`note` + a small margin", not a goal: Stage 3 lowers the ceilings as the screens get faster.
`kind` maps to the speed target the route is measured against on the VPS (wall time is not asserted
in CI): poll ≤ 300 ms, list ≤ 800 ms, report ≤ 2 s, track ≤ 100 ms (p95 at 40 users).

Every new list / report endpoint gets a row here and a test in apps/tests/perf/ (CLAUDE.md, definition
of done item 9).
"""
from typing import Literal, NamedTuple


class Budget(NamedTuple):
    kind: Literal['poll', 'list', 'report', 'track']
    ceiling: int
    note: str


TARGET_MS = {'poll': 300, 'list': 800, 'report': 2000, 'track': 100}

BUDGETS: dict[str, Budget] = {
    # ── polled by every open screen ──────────────────────────────────────────────
    'notifications/': Budget('poll', 4, 'measured 2 on 2026-11-19'),
    'notifications/category-counts': Budget('poll', 4, 'measured 2 on 2026-11-19'),
    'notifications/?view=action': Budget('poll', 4, 'C26 2026-11-20: the bell default; same scan as the '
                                                    'list + a type filter (+ auth)'),
    'sync/status': Budget('poll', 5, 'measured 3 on 2026-11-19'),
    'sync/freshness': Budget('poll', 8, 'measured 47 on 2026-11-19; 5 core queries after Stage 3 (+ auth)'),
    'dashboard/summary': Budget('poll', 12, 'measured 34 on 2026-11-19; 8 core queries after Stage 3 (+ auth)'),
    # ── lists and search ─────────────────────────────────────────────────────────
    'reservations': Budget('list', 11, 'measured 9 on 2026-11-19'),
    'customers': Budget('list', 9, 'measured 7 on 2026-11-19 (pharmacist, branch-scoped, phone masking)'),
    'customers?search': Budget('list', 9, 'measured 7 on 2026-11-19'),
    'items?search': Budget('list', 8, 'measured 6 on 2026-11-19'),
    'search/universal': Budget('list', 20, 'measured 18 on 2026-11-19'),
    'supply/cases': Budget('list', 7, 'measured 5 on 2026-11-19'),
    'pos-orders': Budget('list', 9, 'measured 7 on 2026-11-19'),
    'insurance/claims': Budget('list', 10, 'measured 8 on 2026-11-19'),
    'purchasing/metrics': Budget('list', 7, 'measured 5 on 2026-11-19'),
    'purchasing/filter-options': Budget('list', 14, 'measured 12 on 2026-11-19'),
    # ── reports on screen ────────────────────────────────────────────────────────
    'batches/stock-expiry/summary': Budget('report', 7, 'measured 33 on 2026-11-19; 2 core queries after Stage 3 (+ auth)'),
    'incentives/targets': Budget('report', 14, 'measured 12 → 52 with 10 targets on 2026-11-19; flat after Stage 3 '
                                               '(one KpiResolver + one grouped query per metric and period)'),
    # ── export jobs (Stage 4): the start answers ≤ 1 s, the status is polled every 1.5 s ─────
    'export-jobs/<id>': Budget('poll', 8, 'Stage 4, 2026-11-19: own job + stale check (+ auth)'),
    'purchasing/export/jobs': Budget('list', 16, 'Stage 4, 2026-11-19: validate + housekeeping + one insert, '
                                                 'no export query (+ auth)'),
    # ── tracking ─────────────────────────────────────────────────────────────────
    'audit/screen-view': Budget('track', 5, 'measured 3 on 2026-11-19'),
}
