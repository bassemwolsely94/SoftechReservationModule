"""
apps/finance/supplier_terms.py

P-42 «شروط الموردين» (docs/product-review/06_SPEC_P-42_supplier_terms.md). Read-only toward SOFTECH.

  recompute(personcode=None)  each open supplier invoice → APInvoiceSlice per item category (local / imported /
                              unclassified), shares from its purchase lines, Σ slices = open exactly, due date from the
                              term in force on the invoice date (category term, else the supplier-wide `any` term;
                              no term → no due date, never guessed). Idempotent.
  calendar(as_of, weeks)      real suppliers by week (Saturday–Friday) × supplier × category; overdue / no terms /
                              unclassified buckets; internal accounts apart.
  on_time(as_of)              invoices fully settled through native SOFTECH links: value-weighted days paid vs terms,
                              always with the allocation coverage % (linked ÷ paid).
  early_pay(as_of)            open early-pay opportunities ranked by annualised return + foregone value.
  residue(as_of)              open items more than 365 days old, real vs internal.
  supplier_outflows / early_pay_by_week   the P-40 13-week cash view interfaces.

Internal / virtual accounts (gift coupons, patient buy-back, replacement entitlements) come from SystemSetting
`finance_internal_supplier_codes` and are never mixed with real supplier debt.
"""
import calendar as _cal
import datetime as dt
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

RULES_VERSION = 'p42-v1'
ZERO = Decimal('0')
CENT = Decimal('0.01')
TOL = Decimal('0.01')
RESIDUE_DAYS = 365
ON_TIME_WINDOW_DAYS = 365
DEFAULT_INTERNAL_CODES = '1268,3068,4469,4470,4471,4472'
CATEGORIES = ('local', 'imported', 'unclassified')


def internal_codes():
    from apps.config.models import SystemSetting
    raw = SystemSetting.get('finance_internal_supplier_codes', DEFAULT_INTERNAL_CODES) or ''
    return {c.strip() for c in str(raw).split(',') if c.strip()}


def week_start(day):
    """The Saturday on or before `day` (the pharmacy's week starts Saturday)."""
    return day - dt.timedelta(days=(day.weekday() - 5) % 7)


def _month_end(day):
    return day.replace(day=_cal.monthrange(day.year, day.month)[1])


def _from(term, day):
    return _month_end(day) if term.days_from == term.FROM_MONTH_END else day


def due_date(term, docdate):
    return _from(term, docdate) + dt.timedelta(days=term.credit_days) if term else None


def early_deadline(term, docdate):
    return _from(term, docdate) + dt.timedelta(days=term.early_pay_days) if term.early_pay_days is not None else None


def _q(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def _docno(v):
    return str(v or '').split('.')[0].strip()


# ── terms ────────────────────────────────────────────────────────────────────

def _terms_by_party(party_ids):
    from .models import SupplierTerm
    out = defaultdict(list)
    for t in SupplierTerm.objects.filter(party_id__in=party_ids).order_by('-effective_from'):
        out[t.party_id].append(t)
    return out


def term_for(terms, category, docdate):
    """The term in force on `docdate`: the category's own, else the supplier-wide `any` term."""
    def pick(cat):
        for t in terms:                                     # newest effective_from first
            if t.category == cat and t.effective_from <= docdate and (t.effective_to is None
                                                                       or t.effective_to >= docdate):
                return t
        return None
    return (pick(category) if category in ('local', 'imported') else None) or pick('any')


# ── category line values ─────────────────────────────────────────────────────

def line_values(invoices):
    """{invoice_id: {category: Σ line net_value}} from procurement.PurchaseLine (doc 10, same 4-part key). FOC lines
    carry no value and so no weight. An invoice with no valued lines is absent."""
    from apps.procurement.models import PurchaseLine
    out = {}
    invoices = list(invoices)
    for i in range(0, len(invoices), 500):
        chunk = invoices[i:i + 500]
        key = {(str(v.branchcode).strip(), str(v.party.softech_personcode).strip(), _docno(v.docnumber), v.docdate): v.id
               for v in chunk}
        nos = {_docno(v.docnumber) for v in chunk} | {str(v.docnumber).strip() for v in chunk}
        rows = (PurchaseLine.objects.filter(doccode='10', doc_number__in=nos,
                                            doc_date__in={v.docdate for v in chunk},
                                            supplier_code__in={k[1] for k in key})
                .values_list('branch_code', 'supplier_code', 'doc_number', 'doc_date', 'item_id',
                             'item__is_imported', 'net_value'))
        for br, sup, no, day, item_id, imported, value in rows:
            inv_id = key.get((str(br).strip(), str(sup).strip(), _docno(no), day))
            if inv_id is None or not value or value <= 0:
                continue
            cat = 'unclassified' if item_id is None else ('imported' if imported else 'local')
            bucket = out.setdefault(inv_id, defaultdict(lambda: ZERO))
            bucket[cat] += value
    return out


def split(amount, values):
    """Split `amount` by `values` ({category: weight}) to the piastre; the remainder goes to the largest slice so the
    parts add up to `amount` exactly. No weight → one unclassified part."""
    amount = _q(amount)
    total = sum(values.values(), ZERO) if values else ZERO
    if total <= 0:
        return {'unclassified': (ZERO, Decimal('1'), amount)}
    parts = {c: (v, (v / total).quantize(Decimal('0.000001')), _q(amount * v / total)) for c, v in values.items()}
    largest = max(parts, key=lambda c: (parts[c][0], c))
    diff = amount - sum(p[2] for p in parts.values())
    v, s, a = parts[largest]
    parts[largest] = (v, s, a + diff)
    return parts


# ── recompute ────────────────────────────────────────────────────────────────

def recompute(personcode=None):
    """Rebuild the slices of every open supplier invoice (or one supplier's). Returns the number of slices."""
    from .models import APInvoice, APInvoiceSlice
    from .recon_reports import unpaid_invoices
    rows = unpaid_invoices(party_type='supplier', personcode=personcode)
    open_by_id = {r['invoice_id']: r['open_in_softech'] for r in rows}
    invoices = list(APInvoice.objects.filter(id__in=open_by_id).select_related('party'))
    values = line_values(invoices)
    terms = _terms_by_party({v.party_id for v in invoices})
    new = []
    for inv in invoices:
        for cat, (lv, share, amount) in split(open_by_id[inv.id], values.get(inv.id)).items():
            t = term_for(terms.get(inv.party_id, []), cat, inv.docdate)
            new.append(APInvoiceSlice(invoice=inv, category=cat, line_value=lv, share=share, open_amount=amount,
                                      due_date=due_date(t, inv.docdate), term=t, rules_version=RULES_VERSION))
    with transaction.atomic():
        old = APInvoiceSlice.objects.filter(invoice__party__party_type='supplier')
        if personcode:
            old = old.filter(invoice__party__softech_personcode=personcode)
        old.delete()
        APInvoiceSlice.objects.bulk_create(new, batch_size=1000)
    return len(new)


def _slices():
    from .models import APInvoiceSlice
    return (APInvoiceSlice.objects.filter(invoice__party__party_type='supplier')
            .select_related('invoice__party', 'term'))


# ── payment calendar ─────────────────────────────────────────────────────────

def calendar(as_of, weeks=13):
    start = week_start(as_of)
    bounds = [(start + dt.timedelta(days=7 * i), start + dt.timedelta(days=7 * i + 6)) for i in range(weeks)]
    horizon_end = bounds[-1][1]
    internal = internal_codes()
    week_tot = [ZERO] * weeks
    totals = {'overdue': ZERO, 'no_terms': ZERO, 'unclassified': ZERO, 'later': ZERO, 'internal': ZERO}
    rows, internal_rows = {}, {}
    for s in _slices():
        p = s.invoice.party
        pc, amt = p.softech_personcode, s.open_amount
        if pc in internal:
            r = internal_rows.setdefault(pc, {'personcode': pc, 'supplier': p.name, 'open': ZERO, 'invoices': set()})
            r['open'] += amt
            r['invoices'].add(s.invoice_id)
            totals['internal'] += amt
            continue
        r = rows.setdefault((pc, s.category), {
            'personcode': pc, 'supplier': p.name, 'category': s.category, 'overdue': ZERO, 'no_terms': ZERO,
            'weeks': [ZERO] * weeks, 'later': ZERO, 'open': ZERO})
        r['open'] += amt
        if s.category == 'unclassified':
            totals['unclassified'] += amt
        if s.due_date is None:
            r['no_terms'] += amt
            totals['no_terms'] += amt
        elif s.due_date < as_of:
            r['overdue'] += amt
            totals['overdue'] += amt
        elif s.due_date > horizon_end:
            r['later'] += amt
            totals['later'] += amt
        else:
            i = (s.due_date - start).days // 7
            r['weeks'][i] += amt
            week_tot[i] += amt
    return {
        'as_of': as_of, 'weeks': [{'start': a, 'end': b, 'due': week_tot[i]} for i, (a, b) in enumerate(bounds)],
        **totals,
        'rows': sorted(rows.values(), key=lambda r: (-r['open'], r['personcode'], r['category'])),
        'internal_rows': sorted(({**r, 'invoices': len(r['invoices'])} for r in internal_rows.values()),
                                key=lambda r: -r['open']),
    }


def terms_coverage():
    """% of open real payables whose slice has a due date (i.e. a term)."""
    internal = internal_codes()
    total = covered = ZERO
    for s in _slices():
        if s.invoice.party.softech_personcode in internal:
            continue
        total += s.open_amount
        if s.due_date:
            covered += s.open_amount
    return {'open_real': total, 'with_terms': covered,
            'coverage_pct': (covered * 100 / total).quantize(Decimal('0.1')) if total else None}


# ── early payment ────────────────────────────────────────────────────────────

def _opportunities():
    """One row per (invoice, term) with early-pay days set — the slices it covers summed."""
    internal = internal_codes()
    agg = {}
    for s in _slices().filter(term__early_pay_days__isnull=False):
        p = s.invoice.party
        if p.softech_personcode in internal:
            continue
        r = agg.setdefault((s.invoice_id, s.term_id), {
            'invoice_id': s.invoice_id, 'personcode': p.softech_personcode, 'supplier': p.name,
            'branchcode': s.invoice.branchcode, 'docnumber': _docno(s.invoice.docnumber), 'docdate': s.invoice.docdate,
            'categories': [], 'open_amount': ZERO, 'due_date': s.due_date,
            'deadline': early_deadline(s.term, s.invoice.docdate),
            'discount_pct': s.term.early_pay_discount_pct, 'bonus_note': s.term.early_pay_bonus_note or ''})
        r['categories'].append(s.category)
        r['open_amount'] += s.open_amount
    for r in agg.values():
        pct = r['discount_pct']
        r['discount_value'] = _q(r['open_amount'] * pct / 100) if pct else None
        r['days_gained'] = max((r['due_date'] - r['deadline']).days, 1) if r['due_date'] else None
        r['annualised_return_pct'] = (
            _q(pct / (100 - pct) * Decimal(365) / r['days_gained'] * 100)
            if pct and r['days_gained'] and pct < 100 else None)
    return list(agg.values())


def early_pay(as_of):
    open_, foregone = [], ZERO
    for r in _opportunities():
        if r['deadline'] >= as_of:
            open_.append(r)
        elif r['discount_value']:
            foregone += r['discount_value']
    open_.sort(key=lambda r: (r['annualised_return_pct'] is None, -(r['annualised_return_pct'] or 0),
                              -(r['discount_value'] or 0), r['deadline']))
    return {'as_of': as_of, 'open': open_, 'foregone_value': foregone,
            'available_value': sum((r['discount_value'] or ZERO for r in open_), ZERO)}


def early_pay_by_week(as_of, weeks=13):
    """P-40: per week (Saturday–Friday) the discount on offer if paid by its deadline, and the cash it needs."""
    start = week_start(as_of)
    out = [{'start': start + dt.timedelta(days=7 * i), 'end': start + dt.timedelta(days=7 * i + 6),
            'available_value': ZERO, 'pay_amount': ZERO} for i in range(weeks)]
    e = early_pay(as_of)
    for r in e['open']:
        i = (r['deadline'] - start).days // 7
        if 0 <= i < weeks and r['discount_value']:
            out[i]['available_value'] += r['discount_value']
            out[i]['pay_amount'] += r['open_amount']
    return {'weeks': out, 'foregone_value': e['foregone_value']}


def supplier_outflows(as_of, weeks=13):
    """P-40: per week the real supplier money due (by supplier), plus overdue, no-terms and internal, by supplier."""
    c = calendar(as_of, weeks)
    by = lambda key: {pc: v for pc, v in _sum_by(c['rows'], key).items() if v}      # noqa: E731
    return {
        'weeks': [{'start': w['start'], 'end': w['end'], 'due_real': w['due'],
                   'by_supplier': {pc: v for pc, v in _sum_by(c['rows'], lambda r, i=i: r['weeks'][i]).items() if v}}
                  for i, w in enumerate(c['weeks'])],
        'overdue_real': c['overdue'], 'overdue_by_supplier': by(lambda r: r['overdue']),
        'no_terms_real': c['no_terms'], 'no_terms_by_supplier': by(lambda r: r['no_terms']),
        'internal': c['internal'], 'internal_by_supplier': {r['personcode']: r['open'] for r in c['internal_rows']},
    }


def _sum_by(rows, get):
    out = defaultdict(lambda: ZERO)
    for r in rows:
        out[r['personcode']] += get(r)
    return out


# ── paid on time ─────────────────────────────────────────────────────────────

def on_time(as_of):
    """Per real supplier: value-weighted days paid vs terms over the invoices fully settled through native SOFTECH
    links in the last year, with the allocation coverage % (linked payments ÷ all payments) next to it."""
    from django.db.models import Max, Sum
    from .models import Allocation, APInvoice, Payment
    since = as_of - dt.timedelta(days=ON_TIME_WINDOW_DAYS)
    internal = internal_codes()
    native = ('softech', 'written')
    voided = ('reversed', 'reversal')              # a payment cancelled by a receipt settles nothing (doc 23 §17)
    paid = {r['party__softech_personcode']: r['s'] or ZERO for r in
            Payment.objects.filter(party_type='supplier', direction='out', voucher_date__gt=since,
                                   voucher_date__lte=as_of)
            .exclude(chain_role__in=voided)
            .values('party__softech_personcode').annotate(s=Sum('amount'))}
    linked = {r['payment__party__softech_personcode']: r['s'] or ZERO for r in
              Allocation.objects.filter(origin__in=native, payment__direction='out',
                                        payment__party_type='supplier', payment__voucher_date__gt=since,
                                        payment__voucher_date__lte=as_of)
              .exclude(payment__chain_role__in=voided)
              .values('payment__party__softech_personcode').annotate(s=Sum('amount'))}
    settled = {r['invoice_id']: r for r in
               Allocation.objects.filter(origin__in=native, invoice__party__party_type='supplier',
                                         invoice__is_return=False)
               .exclude(payment__chain_role__in=voided)
               .values('invoice_id').annotate(s=Sum('amount'), paid_on=Max('payment__voucher_date'))}
    invoices = [v for v in APInvoice.objects.filter(id__in=settled).select_related('party')
                if v.doc_value > 0 and settled[v.id]['s'] >= v.doc_value - TOL
                and since < settled[v.id]['paid_on'] <= as_of and v.party.softech_personcode not in internal]
    values = line_values(invoices)
    terms = _terms_by_party({v.party_id for v in invoices})
    acc = defaultdict(lambda: {'value': ZERO, 'weighted': ZERO, 'invoices': set(), 'no_terms_value': ZERO})
    names = {}
    for inv in invoices:
        pc = inv.party.softech_personcode
        names[pc] = inv.party.name
        for cat, (_, _, amount) in split(inv.doc_value, values.get(inv.id)).items():
            t = term_for(terms.get(inv.party_id, []), cat, inv.docdate)
            a = acc[(pc, cat)]
            if t is None:
                a['no_terms_value'] += amount
                continue
            a['value'] += amount
            a['weighted'] += amount * (settled[inv.id]['paid_on'] - due_date(t, inv.docdate)).days
            a['invoices'].add(inv.id)

    def cov(pc):
        return (linked.get(pc, ZERO) * 100 / paid[pc]).quantize(Decimal('0.1')) if paid.get(pc) else None

    out = {}
    for (pc, cat), a in acc.items():
        r = out.setdefault(pc, {'personcode': pc, 'supplier': names[pc], 'value': ZERO, 'weighted': ZERO,
                                'no_terms_value': ZERO, 'by_category': [],
                                'paid_value': paid.get(pc, ZERO), 'linked_value': linked.get(pc, ZERO),
                                'coverage_pct': cov(pc)})
        r['value'] += a['value']
        r['weighted'] += a['weighted']
        r['no_terms_value'] += a['no_terms_value']
        r['by_category'].append({
            'category': cat, 'value': a['value'], 'invoices': len(a['invoices']), 'no_terms_value': a['no_terms_value'],
            'days_vs_terms': (a['weighted'] / a['value']).quantize(Decimal('0.1')) if a['value'] else None})
    for pc in paid:                                    # suppliers paid with nothing settled through a link
        if pc not in out and pc not in internal:
            out[pc] = {'personcode': pc, 'supplier': '', 'value': ZERO, 'weighted': ZERO, 'no_terms_value': ZERO,
                       'by_category': [], 'paid_value': paid[pc], 'linked_value': linked.get(pc, ZERO),
                       'coverage_pct': cov(pc)}
    for r in out.values():
        r['days_vs_terms'] = (r['weighted'] / r['value']).quantize(Decimal('0.1')) if r['value'] else None
        del r['weighted']
    if any(not r['supplier'] for r in out.values()):
        from .models import ReconParty
        nm = dict(ReconParty.objects.filter(softech_personcode__in=list(out)).values_list('softech_personcode', 'name'))
        for r in out.values():
            r['supplier'] = r['supplier'] or nm.get(r['personcode'], '')
    return sorted(out.values(), key=lambda r: -r['paid_value'])


# ── residue ──────────────────────────────────────────────────────────────────

def residue(as_of):
    """Open supplier items more than a year old — real vs internal accounts. Finance closes them in SOFTECH."""
    from .recon_reports import unpaid_invoices
    cutoff = as_of - dt.timedelta(days=RESIDUE_DAYS)
    internal = internal_codes()
    rows, tot = [], {'real': ZERO, 'internal': ZERO}
    for r in unpaid_invoices(party_type='supplier'):
        if r['docdate'] >= cutoff:
            continue
        cls = 'internal' if r['personcode'] in internal else 'real'
        tot[cls] += r['open_in_softech']
        rows.append({**r, 'account_class': cls, 'age_days': (as_of - r['docdate']).days})
    rows.sort(key=lambda r: (r['account_class'], -r['open_in_softech']))
    return {'as_of': as_of, **tot, 'rows': rows}
