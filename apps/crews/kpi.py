"""
apps/crews/kpi.py

A call-center crew's monthly KPIs from its members' dated identities (piece 2b). The math is the
legacy CC rollup's, reused, not rewritten:
  sales / profit / beauty / orders / PICs = KpiResolver.compute_call_center_month's expressions
                                            over the same base querysets, narrowed to
                                            "seller (PurchaseHistory.softech_user, never the
                                            cashier) is a member identity on the invoice day"
  net of returns                          = apps.crews.softech_returns.returns_for_codes over the
                                            seller codes active in the month (owner ruling B: the
                                            old cc_softech rule, no membership date on the original
                                            sale, plus o.docdate = r_docdate when r_docdate is set)
  call_count                              = forecasting.callcount.count_calls over CDR rows whose
                                            src extension is a member identity on the call day

With every span covering the whole month the sales figures equal the legacy rollup bit for bit;
returns differ from cc_softech only on a return whose r_docdate does not match the sale's date
(a reused document number). build_crew_rollups writes the results to KpiActualRollup (crew set,
branch NULL). A figure that cannot be computed is left out and named in `notes`, never zero.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import reduce
from operator import or_

from django.db.models import Q, Sum

from apps.forecasting.callcount import count_calls
from apps.forecasting.kpi import KpiResolver, _PROFIT_EXPR
from apps.forecasting.models import KpiActualRollup as K
from config.issabel import cdr_configured, fetch_cdr_rows

from . import softech_returns
from .membership import identities

Span = tuple[str, date, date]       # (value, valid_from, valid_to) — both inclusive

SALES_METRICS = (K.M_CASH_DELIVERY, K.M_GROSS_PROFIT, K.M_BEAUTY, K.M_CUSTOMERS, K.M_PIC_COUNT)

NOTE_NO_MEMBERS = 'no_members'                  # no seller and no extension identity
NOTE_NO_SELLERS = 'no_sellers'                  # extensions only: sales metrics not computed
NOTE_RETURNS_UNREACHABLE = 'returns_unreachable'
NOTE_RETURNS_NOT_DEDUCTED = 'returns_not_deducted'  # returns=False (--no-returns): gross figures
NOTE_CDR_UNAVAILABLE = 'cdr_unavailable'        # no CDR configured and no CSV given
NOTE_CDR_UNREACHABLE = 'cdr_unreachable'        # configured, but the pull failed


def _spans(ids, kind) -> list:
    return [(i.value, i.valid_from, i.valid_to) for i in ids if i.kind == kind]


def seller_spans(crew, start: date, end: date) -> list:
    return _spans(identities(crew, start, end), 'softech_user')


def extension_spans(crew, start: date, end: date) -> list:
    return _spans(identities(crew, start, end), 'extension')


def sales_q(spans, prefix: str = '') -> Q:
    """Seller = a span's usercode AND invoice day inside that span. Empty → matches nothing."""
    if not spans:
        return Q(pk__in=[])
    return reduce(or_, (Q(**{f'{prefix}softech_user': v,
                             f'{prefix}invoice_date__date__gte': frm,
                             f'{prefix}invoice_date__date__lte': to})
                        for v, frm, to in spans))


def _zeros() -> dict:
    return {m: Decimal('0') for m in SALES_METRICS}


def compute_sales(year: int, month: int, spans, resolver: KpiResolver | None = None) -> dict:
    """The five metrics of compute_call_center_month, same expressions, base querysets narrowed
    by sales_q(spans)."""
    if not spans:
        return _zeros()
    r = resolver or KpiResolver()
    start, end = r.month_bounds(year, month)
    ph = r._ph_qs(None, start, end).filter(sales_q(spans))
    lines = r._line_qs(None, start, end).filter(sales_q(spans, 'purchase__'))

    def net(qs, doc_field, expr):
        sale = qs.filter(**{doc_field: '115'}).aggregate(s=Sum(expr))['s'] or 0
        ret = qs.filter(**{doc_field: '30'}).aggregate(s=Sum(expr))['s'] or 0
        return Decimal(str(sale)) - Decimal(str(ret))

    if r.beauty_types:
        beauty = net(lines.filter(item__medicine_type__in=r.beauty_types),
                     'purchase__doc_code', 'line_total')
    else:
        beauty = Decimal('0')
    orders = ph.filter(doc_code__in=['115', '30']).values('softech_invoice_id').distinct().count()
    pics = (ph.filter(doc_code='115').exclude(softech_phcode='')
            .values('softech_phcode').distinct().count())
    return {
        K.M_CASH_DELIVERY: net(ph, 'doc_code', 'total_amount'),
        K.M_GROSS_PROFIT: net(lines, 'purchase__doc_code', _PROFIT_EXPR),
        K.M_BEAUTY: beauty,
        K.M_CUSTOMERS: Decimal(orders),
        K.M_PIC_COUNT: Decimal(pics),
    }


def count_calls_spans(rows, spans) -> int:
    """count_calls over the rows whose src is a span's extension and whose call day
    (calldate[:10]) is inside that span."""
    by_ext = {}
    for v, frm, to in spans:
        by_ext.setdefault(str(v), []).append((frm.isoformat(), to.isoformat()))
    kept = []
    for row in rows:
        windows = by_ext.get(str(row.get('src')))
        if windows:
            day = str(row.get('calldate'))[:10]
            if any(frm <= day <= to for frm, to in windows):
                kept.append(row)
    return count_calls(kept, set(by_ext))


@dataclass
class CrewMonth:
    kpis: dict
    per_member: dict = field(default_factory=dict)     # Identity.member_key -> {metric: Decimal}
    notes: list = field(default_factory=list)
    gross: dict = field(default_factory=dict)          # the five sales metrics before returns
    returns: dict | None = None                        # returns_for_codes result; None = not run/unreachable


def _by_member(ids) -> dict:
    out = {}
    for i in ids:
        out.setdefault(i.member_key, []).append(i)
    return out


def _codes(spans) -> list:
    return sorted({str(v) for v, _frm, _to in spans})


def _subtract_returns(kpis: dict, ret: dict):
    kpis[K.M_CASH_DELIVERY] = kpis[K.M_CASH_DELIVERY] - ret['amount']
    kpis[K.M_GROSS_PROFIT] = kpis[K.M_GROSS_PROFIT] - ret['profit']


def _cdr_rows(year, month, notes):
    if not cdr_configured():
        notes.append(NOTE_CDR_UNAVAILABLE)
        return None
    start = date(year, month, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    try:
        return fetch_cdr_rows(start, nxt)
    except Exception:       # PBX unreachable: mark it, never count it as zero calls
        notes.append(NOTE_CDR_UNREACHABLE)
        return None


def compute_crew_month(crew, year: int, month: int, *, returns: bool = True, cdr_rows=None,
                       per_member: bool = False) -> CrewMonth:
    """kpis = net figures (+ call_count); gross = the five sales metrics before returns;
    returns = the crew's returns_for_codes result, None when not run or unreachable.
    Returns are asked for the seller codes with any span in the month (per member: that member's
    codes); the original sale's date is not tied to the membership.
    No seller AND no extension identity in the month → kpis {} + 'no_members'; no seller only →
    the five sales metrics are skipped ('no_sellers') and call_count is still computed."""
    resolver = KpiResolver()
    start, end = resolver.month_bounds(year, month)
    ids = identities(crew, start, end)
    sellers = _spans(ids, 'softech_user')
    extensions = _spans(ids, 'extension')
    if not sellers and not extensions:
        return CrewMonth(kpis={}, notes=[NOTE_NO_MEMBERS])
    notes = []
    members = _by_member(ids) if per_member else {}
    if sellers:
        kpis = compute_sales(year, month, sellers, resolver)
        per = {key: compute_sales(year, month, _spans(mids, 'softech_user'), resolver)
               for key, mids in members.items()}
    else:
        notes.append(NOTE_NO_SELLERS)
        kpis, per = {}, {key: {} for key in members}
    gross = dict(kpis)
    ret_total = None

    if returns and sellers:
        try:    # fetch everything first, so a failure half-way subtracts nothing
            total = softech_returns.returns_for_codes(year, month, _codes(sellers))
            each = {key: softech_returns.returns_for_codes(
                        year, month, _codes(_spans(members[key], 'softech_user'))) for key in per}
        except Exception:   # SOFTECH unreachable: the figures stay gross and say so
            notes.append(NOTE_RETURNS_UNREACHABLE)
        else:
            ret_total = total
            _subtract_returns(kpis, total)
            for key, ret in each.items():
                _subtract_returns(per[key], ret)
    elif sellers:       # --no-returns: the money figures are gross and the row must say so
        notes.append(NOTE_RETURNS_NOT_DEDUCTED)

    rows = cdr_rows if cdr_rows is not None else _cdr_rows(year, month, notes)
    if rows is not None:
        rows = list(rows)
        kpis[K.M_CALL_COUNT] = Decimal(count_calls_spans(rows, extensions))
        for key, mids in members.items():
            per[key][K.M_CALL_COUNT] = Decimal(count_calls_spans(rows, _spans(mids, 'extension')))
    return CrewMonth(kpis=kpis, per_member=per, notes=notes, gross=gross, returns=ret_total)


def _months_overlapping(start: date, end: date) -> Q:
    """Q over (year, month) for every calendar month that overlaps [start, end]."""
    lo, hi = start.year * 12 + start.month - 1, end.year * 12 + end.month - 1
    if hi < lo:
        return Q(pk__in=[])
    return reduce(or_, (Q(year=i // 12, month=i % 12 + 1) for i in range(lo, hi + 1)))


def crew_actual(crew, metric: str, start: date, end: date) -> float:
    """The board figure for a crew (owner ruling D): Σ KpiActualRollup(crew, metric) over the
    months overlapping [start, end]. A month with no row adds nothing."""
    total = (K.objects.filter(_months_overlapping(start, end), crew=crew, metric=metric)
             .aggregate(s=Sum('value'))['s'])
    return float(total or 0)
