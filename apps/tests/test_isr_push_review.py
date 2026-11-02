"""
W3 ISR push review: before an approved draft is written to SOFTECH it is re-checked
against SOFTECH now (item master + stock) — missing / archived items are refused,
odd quantities / stale drafts need a reason, and a person confirms the line count.
SOFTECH is faked.
"""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.purchasing import isr_guards as G
from apps.purchasing.models import IsrPush as P


def _conn(master, stock):
    """master: {code: (archive, nomoreuse)}, stock: {code: nowqty}"""
    class Cur:
        def execute(self, sql, params):
            if 'FROM items' in sql:
                self.rows = [(c, *master[c]) for c in params if c in master]
            else:
                self.rows = [(c, stock[c]) for c in params[1:] if c in stock]

        def fetchall(self):
            return self.rows
    conn = mock.MagicMock()
    conn.cursor.side_effect = Cur
    return conn


def _line(code, qty, gap, nowqty=0, cost=10):
    return {'itemcode': code, 'item_name': code, 'itemqty': qty, 'gap': gap, 'nowqty': nowqty,
            'itemcostprice': cost}


class IsrPushReviewTests(TestCase):
    _branch = iter(range(100, 999))

    def _p(self, lines, days=0):
        b = str(next(self._branch))    # one live draft per route — a new route per draft
        p = P.objects.create(branchcode=b, dest_branchcode=b, status=P.STATUS_APPROVED, lines_snapshot=lines)
        if days:
            P.objects.filter(pk=p.pk).update(created_at=timezone.now() - timedelta(days=days))
            p.refresh_from_db()
        return p

    def _codes(self, review, level):
        return {i['code'] for i in review['issues'] if i['level'] == level}

    def test_clean_draft(self):
        r = G.review_push(self._p([_line('A', 5, 5), _line('B', 0, 0)]), _conn({'A': ('0', '0')}, {'A': 0}))
        self.assertEqual((r['line_count'], r['total_qty'], r['issues']), (1, 5, []))

    def test_missing_and_archived_items_block(self):
        r = G.review_push(self._p([_line('A', 5, 5), _line('Z', 2, 2)]), _conn({'A': ('1', '0')}, {}))
        self.assertEqual(self._codes(r, 'block'), {'item_archived', 'item_missing'})
        with self.assertRaises(ValueError):
            G.enforce_review(r, confirm_count=2, push_reason='سبب طويل بما يكفى')

    def test_warnings_need_reason_and_count(self):
        p = self._p([_line('A', 40, 5), _line('B', 3, 0), _line('C', 6, 6, nowqty=1)], days=5)
        r = G.review_push(p, _conn({'A': ('0', '0'), 'B': ('0', '0'), 'C': ('0', '0')}, {'C': 9}))
        self.assertEqual(self._codes(r, 'warn'), {'qty_over_gap', 'no_gap', 'stock_arrived', 'stale'})
        with self.assertRaises(ValueError):
            G.enforce_review(r, confirm_count=3, push_reason='قصير')
        with self.assertRaises(ValueError):
            G.enforce_review(r, confirm_count=2, push_reason='سبب طويل بما يكفى')
        G.enforce_review(r, confirm_count='3', push_reason='سبب طويل بما يكفى')

    def test_unattended_push_never_overrides_a_warning(self):
        r = G.review_push(self._p([_line('A', 40, 5)]), _conn({'A': ('0', '0')}, {}))
        with self.assertRaises(ValueError):
            G.enforce_review(r, unattended=True)
        clean = G.review_push(self._p([_line('A', 5, 5)]), _conn({'A': ('0', '0')}, {}))
        G.enforce_review(clean, unattended=True)
