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
    'pos-orders/missed-sales': Budget('list', 12, 'C28, 2026-11-20: first ceiling (pos-orders 9 + the '
                                                  'bought-in-cart order + its lines prefetch + the matrix '
                                                  'check); lower it to CI\'s measure + 2'),
    'insurance/claims': Budget('list', 10, 'measured 8 on 2026-11-19'),
    'purchasing/metrics': Budget('list', 7, 'measured 5 on 2026-11-19'),
    'purchasing/filter-options': Budget('list', 14, 'measured 12 on 2026-11-19'),
    'delivery/payouts/rides': Budget('list', 12, 'C22, 2026-11-20: estimate (scope + count + one joined page); '
                                                 'set from the first CI run'),
    'delivery/payouts/periods': Budget('list', 12, 'C22, 2026-11-20: estimate (scope + count + one joined page); '
                                                   'set from the first CI run'),
    'personal/saved-views': Budget('list', 6, 'C23, 2026-11-20: own + role-shared views in one query (+ auth); '
                                              'not measured locally yet — CI first run'),
    'purchasing/phantom/monthly': Budget('list', 8, 'C30, 2026-11-20: one item query (+ auth); not measured '
                                                    'locally (shared PC), CI is the first run'),
    'purchasing/aggregated': Budget('list', 9, 'C16 2026-11-20: not measured yet (CI first run); '
                                               'the cover limit is read once per response, not per row'),
    'delivery/stuck-orders': Budget('list', 14, 'C21, 2026-11-20: 3 settings + count + one joined page '
                                                '(+ auth); first measured in CI'),
    'qa/fridge-readings': Budget('list', 12, 'C31, 2026-11-20: page + count, fridge/recorder joined (+ auth); '
                                             'first measured in CI'),
    'finance/gl/exceptions/mixed-patterns': Budget('list', 9, 'measured 7 on 2026-11-20'),
    'hr-attendance-lg-devices': Budget('list', 5, 'HR Linked Gates task 7, 2026-11-20: measured 3 (access + one joined '
                                                  'device query); CI confirms'),
    # ── reports on screen ────────────────────────────────────────────────────────
    'hr-attendance-month': Budget('report', 16, 'HR Linked Gates final review, 2026-11-21: not measured yet '
                                                '(test slot closed); access + employees + LG month totals + '
                                                'month_rows punches/leave, flat as employees grow; CI confirms'),
    'hr-attendance-lg-compare': Budget('report', 13, 'HR Linked Gates task 7, 2026-11-20: measured 11 (access + employees + '
                                                     'compare_month 5 + machine_day_counts 3); CI '
                                                     'confirms'),
    'batches/stock-expiry/summary': Budget('report', 7, 'measured 33 on 2026-11-19; 2 core queries after Stage 3 (+ auth)'),
    'delivery/small-orders': Budget('report', 8, 'C20, 2026-11-20: invoice heads + one grouped line query '
                                                  '(+ auth); not measured locally, CI is the first run'),
    'analytics/margin-board': Budget('report', 16, 'C19 2026-11-20: measured 7 warm in CI (10 cold); one '
                                                   'grouped line query + branches + delivery fees + auth'),
    'supply/missing-bonus': Budget('report', 16, 'C18 2026-11-20: not measured yet (CI first run); branches, '
                                                 'lines, profiles, history, items + auth + scope'),
    'supply/out-here': Budget('report', 16, 'C06 2026-11-20: not measured yet (CI first run); six fixed queries '
                                            '(branches, run, candidates, stock, metrics, items) + auth + scope'),
    'supply/bought-dearer': Budget('report', 14, 'C17, 2026-11-20: lines + suppliers + items + buyers + branches + '
                                                 'refresh marker (+ auth); not measured locally, CI is the first run'),
    'stockcount/variance-report': Budget('report', 10, 'C14, 2026-11-20: session + snapshots + item costs + one '
                                                       'grouped sales query (+ auth); CI is the first run'),
    'qa/fridges/<id>/month': Budget('report', 10, 'C31, 2026-11-20: fridge + one month of readings (+ auth); '
                                                  'first measured in CI'),
    'stock-audit/discount-policy': Budget('report', 20, 'C07, 2026-11-20: rule row + ledger window + invoices + '
                                                       'items + branches + user names (+ auth); first measured in CI'),
    'incentives/targets': Budget('report', 14, 'measured 12 → 52 with 10 targets on 2026-11-19; flat after Stage 3 '
                                               '(one KpiResolver + one grouped query per metric and period)'),
    # ── export jobs (Stage 4): the start answers ≤ 1 s, the status is polled every 1.5 s ─────
    'export-jobs/<id>': Budget('poll', 8, 'Stage 4, 2026-11-19: own job + stale check (+ auth)'),
    'purchasing/export/jobs': Budget('list', 16, 'Stage 4, 2026-11-19: validate + housekeeping + one insert, '
                                                 'no export query (+ auth)'),
    # ── tracking ─────────────────────────────────────────────────────────────────
    'audit/screen-view': Budget('track', 5, 'measured 3 on 2026-11-19'),
    'sync/delta-shadow': Budget('report', 12, 'doc 40 shadow report, 2026-11-20: aggregates + watermarks + last 20 (+ auth)'),
}
