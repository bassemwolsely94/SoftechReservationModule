"""
apps/finance/recon_filters.py

ONE filter definition for every reconciliation list, report, export and bulk
action, so a screen, its totals and its Excel always agree:

  party_type                    supplier | customer
  personcodes                   multi-select suppliers (CSV: ?personcodes=4471,3068;
                                legacy single ?personcode= still accepted)
  inv_date_from / inv_date_to   the INVOICE date (stktransm.docdate)
  pay_date_from / pay_date_to   the PAYMENT / voucher date (cheques.cheqdate)
  amount_min / amount_max       the document value — invoice value / voucher amount /
                                proposed amount (per list, see FIELDS)

Invoice and payment dates are distinct (owner, 2026-09-26): each range filters only
its own side; a match / exception carries both and must satisfy both when set.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db.models import Q


@dataclass
class Filters:
    party_type: str = ''
    personcodes: list = field(default_factory=list)
    inv_date_from: datetime.date | None = None
    inv_date_to: datetime.date | None = None
    pay_date_from: datetime.date | None = None
    pay_date_to: datetime.date | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None

    @property
    def any_doc_filter(self) -> bool:
        return any([self.inv_date_from, self.inv_date_to, self.pay_date_from, self.pay_date_to,
                    self.amount_min is not None, self.amount_max is not None])


def _d(v):
    try:
        return datetime.date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _n(v):
    if v in (None, ''):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def parse(params, default_party_type: str = '') -> Filters:
    """Read filters from query params (GET) or request.data (POST)."""
    get = params.get
    codes = []
    raw = get('personcodes')
    if isinstance(raw, (list, tuple)):
        codes = [str(c).strip() for c in raw if str(c).strip()]
    elif raw:
        codes = [c.strip() for c in str(raw).split(',') if c.strip()]
    if get('personcode') and str(get('personcode')).strip() not in codes:
        codes.append(str(get('personcode')).strip())
    return Filters(party_type=get('party_type') or default_party_type, personcodes=codes,
                   inv_date_from=_d(get('inv_date_from')), inv_date_to=_d(get('inv_date_to')),
                   pay_date_from=_d(get('pay_date_from')), pay_date_to=_d(get('pay_date_to')),
                   amount_min=_n(get('amount_min')), amount_max=_n(get('amount_max')))


# which model fields each list filters on (None = that side does not exist here)
FIELDS = {
    'invoice':    {'party': 'party', 'inv_date': 'docdate', 'pay_date': None, 'amounts': ('doc_value',)},
    'payment':    {'party': 'party', 'inv_date': None, 'pay_date': 'voucher_date', 'amounts': ('amount',)},
    'candidate':  {'party': 'party', 'inv_date': 'invoice__docdate', 'pay_date': 'payment__voucher_date',
                   'amounts': ('proposed_amount',)},
    'exception':  {'party': 'party', 'inv_date': 'invoice__docdate', 'pay_date': 'payment__voucher_date',
                   'amounts': ('invoice__doc_value', 'payment__amount')},
    'allocation': {'party': 'invoice__party', 'inv_date': 'invoice__docdate',
                   'pay_date': 'payment__voucher_date', 'amounts': ('amount',)},
    'party':      {'party': '', 'inv_date': None, 'pay_date': None, 'amounts': ('softech_balance',)},
}


def _range(fld, lo, hi) -> Q:
    q = Q()
    if lo:
        q &= Q(**{f'{fld}__gte': lo})
    if hi:
        q &= Q(**{f'{fld}__lte': hi})
    return q


def apply(qs, f: Filters, kind: str):
    spec = FIELDS[kind]
    pp = spec['party']
    pre = f'{pp}__' if pp else ''
    if f.party_type:
        qs = qs.filter(**{f'{pre}party_type': f.party_type})
    if f.personcodes:
        qs = qs.filter(**{f'{pre}softech_personcode__in': f.personcodes})
    if spec['inv_date'] and (f.inv_date_from or f.inv_date_to):
        qs = qs.filter(_range(spec['inv_date'], f.inv_date_from, f.inv_date_to))
    if spec['pay_date'] and (f.pay_date_from or f.pay_date_to):
        qs = qs.filter(_range(spec['pay_date'], f.pay_date_from, f.pay_date_to))
    if spec['amounts'] and (f.amount_min is not None or f.amount_max is not None):
        q = Q()
        for fld in spec['amounts']:
            part = Q()
            if f.amount_min is not None:
                part &= Q(**{f'{fld}__gte': f.amount_min})
            if f.amount_max is not None:
                part &= Q(**{f'{fld}__lte': f.amount_max})
            q |= part
        qs = qs.filter(q)
    return qs
