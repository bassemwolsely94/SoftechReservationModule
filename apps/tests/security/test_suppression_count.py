"""
Round-2 rule 3 (docs/security/2026-11-05-full-project-test-plan.md §3): no inline suppression
without a reviewed reason, and the number of suppressions only goes down.

- every `# nosec` names its bandit rule (B<digits>) and gives a reason after it;
- the counts of `# nosec` and `# noqa` lines may not grow. Lower the number below when one goes
  away; raise it only in a reviewed change that says why.

Measured 2026-11-05 (round-2 R0): 8 nosec (all with rule + reason), 126 noqa.
Raised to 10 the same day, reviewed: Finance GL Plan 2 added two B608 query builders in
apps/finance/queries/sybase_gl.py (sql_transfer_legs_pointing_at, sql_bank_transfer_partners) —
every interpolated code passes _digits() (digits only, else ValueError) and dates go through
date.isoformat(), so no free text reaches the SQL.
Raised to 12 on 2026-11-06, for review with the batch: the Q3 finance batch added two read-only B608
query builders in the same file (sql_purchase_vat, sql_branch_cost); only date.isoformat() values and
module constants are interpolated.
Raised to 17 on 2026-11-08, reviewed: Finance GL Plan 3 added five B608 SELECT-only readers in the same
file (storebal_rows, storebal_snapshots, store_names, sales_net_by_day, expense_rows) — only the module
constant DB and date.isoformat() values are interpolated; storebal dates are bound params.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

MAX_NOSEC = 17
MAX_NOQA = 126
ROOTS = ('apps', 'core', 'config')
NOSEC = re.compile(r'#\s*nosec\b(.*)$')
NOSEC_WITH_REASON = re.compile(r'^\s*B\d{3}\b\s*[—–-]+\s*\S.{4,}')
NOQA = re.compile(r'#\s*noqa\b')


def _source_lines():
    base = Path(settings.BASE_DIR)
    for root in ROOTS:
        for path in (base / root).rglob('*.py'):
            if 'migrations' in path.parts or (root == 'apps' and 'tests' in path.parts):
                continue
            for n, line in enumerate(path.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
                yield path.relative_to(base).as_posix(), n, line


class SuppressionRatchetTests(SimpleTestCase):
    def test_every_nosec_names_its_rule_and_reason(self):
        bad = [f'{p}:{n}' for p, n, line in _source_lines()
               if (m := NOSEC.search(line)) and not NOSEC_WITH_REASON.match(m.group(1))]
        self.assertEqual(bad, [], 'write `# nosec B<nnn> — <why it is safe>`')

    def test_nosec_count_does_not_grow(self):
        n = sum(1 for _, _, line in _source_lines() if NOSEC.search(line))
        self.assertLessEqual(n, MAX_NOSEC, f'{n} nosec lines (max {MAX_NOSEC}) — prefer a reviewed '
                             'bandit-baseline.json entry, or raise MAX_NOSEC with a reason')

    def test_noqa_count_does_not_grow(self):
        n = sum(1 for _, _, line in _source_lines() if NOQA.search(line))
        self.assertLessEqual(n, MAX_NOQA, f'{n} noqa lines (max {MAX_NOQA}) — fix the lint finding instead')
