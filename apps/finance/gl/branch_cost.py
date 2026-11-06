"""SOFTECH branch sales and cost of sales for the branch P&L (Rulings P33 / P34) - report-time only,
posts nothing.

stktransm.docvalue2 on a sale (doccode 115) or a sales return (doccode 30) = sum of qty x
newcostprice of the document, so a branch's cost of sales for a month = sum docvalue2(115) -
sum docvalue2(30); the same difference of docvalue is its sale value, on one basis with that cost
(as SOFTECH holds it, VAT-inclusive). ``sync_branch_cost`` reads both (SELECT only) for every whole
month covering a range and upserts ``GLBranchCost``; an empty month read never deletes what is there.
"""
from contextlib import ExitStack
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.finance.models import GLBranchCost
from apps.finance.queries import sybase_gl

from .sources.sales import code, q


def whole_months(date_from: date, date_to: date):
    """(first, last) of every calendar month touching [date_from, date_to]."""
    first = date_from.replace(day=1)
    nxt = date(date_to.year + (date_to.month == 12), date_to.month % 12 + 1, 1)
    return list(sybase_gl.month_chunks(first, nxt - timedelta(days=1)))


def sync_branch_cost(date_from: date, date_to: date, *, fetch=None) -> int:
    """Upsert GLBranchCost for the whole months covering the range; returns rows written."""
    written = 0
    with ExitStack() as stack:
        if fetch is None:
            fetch = stack.enter_context(sybase_gl.open_fetch())
        for d1, d2 in whole_months(date_from, date_to):
            per: dict = {}
            for r in fetch(sybase_gl.sql_branch_cost(d1, d2)):
                slot = per.setdefault(code(r['branchcode']), {'115': [Decimal(0), Decimal(0)],
                                                              '30': [Decimal(0), Decimal(0)]})
                doccode = code(r['doccode'])
                if doccode in slot:
                    slot[doccode][0] += Decimal(str(r['cost'] or 0))
                    slot[doccode][1] += Decimal(str(r['docval'] or 0))
            if not per:   # a silent / empty read must never wipe a month
                continue
            now = timezone.now()
            with transaction.atomic():
                for branch, v in per.items():
                    sales, returns = q(v['115'][0]), q(v['30'][0])
                    sold, returned = q(v['115'][1]), q(v['30'][1])
                    GLBranchCost.objects.update_or_create(
                        year=d1.year, month=d1.month, branch_code=branch,
                        defaults={'sales_cost': sales, 'return_cost': returns, 'net_cost': sales - returns,
                                  'sales_value': sold, 'return_value': returned, 'net_value': sold - returned,
                                  'synced_at': now})
                    written += 1
                GLBranchCost.objects.filter(year=d1.year, month=d1.month).exclude(
                    branch_code__in=list(per)).delete()
    return written


def month_keys(date_from: date, date_to: date) -> list:
    return [(d1.year, d1.month) for d1, _ in whole_months(date_from, date_to)]
