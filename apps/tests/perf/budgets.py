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
    'sync/status': Budget('poll', 5, 'measured 3 on 2026-11-19'),
    'sync/freshness': Budget('poll', 49, 'measured 47 on 2026-11-19; Stage 3 target ≤ 8'),
    'dashboard/summary': Budget('poll', 36, 'measured 34 on 2026-11-19; Stage 3 target ≤ 10'),
}
