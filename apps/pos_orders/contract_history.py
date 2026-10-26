"""
apps/pos_orders/contract_history.py — read-only assist for fast contract (تعاقد) entry.

Remembers, per contract account (personcode = SoftechSalesOrder.cust_branch_code):
  • which claim columns change every visit vs. stay with the patient (ContractEntryConfig),
  • patients seen before (our POS orders' source_companies_raw + the insurance mirror),
  • a patient's last prescriptions, revalidated against today's price / stock / safety,
  • previously used values of a claim column, and re-use of an approval number.

Pure PG reads — never SOFTECH. The cashier decides; nothing here fills or blocks anything.
"""
import re
from collections import Counter

from apps.catalog.wildcard import text_matches
from apps.customers.repeat_order import revalidate_lines

from .contract_fields import SLOT_COLUMN
from .models import ContractEntryConfig, SoftechSalesOrder

COLUMNS = tuple(SLOT_COLUMN.values())
_SCAN_CAP = 5000          # newest-first rows examined per query (a contract's history is small)

_AR_FOLD = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ى': 'ي', 'ة': 'ه', 'ـ': ''})
_DIACRITICS = re.compile('[ً-ٰٟ]')


def _norm(s):
    """Arabic-insensitive form (أ/إ/آ→ا, ى→ي, ة→ه, no tashkeel/tatweel, single spaces)."""
    s = _DIACRITICS.sub('', str(s or '')).translate(_AR_FOLD)
    return ' '.join(s.split()).lower()


def _matches(text, q):
    return text_matches(_norm(text), _norm(q))


def _val(raw, col):
    """A claim value as plain text (examdate is stored as {'__dt__': 'YYYY-MM-DD 00:00:00'})."""
    v = (raw or {}).get(col)
    if isinstance(v, dict):
        v = v.get('__dt__', '')[:10]
    return str(v).strip() if v not in (None, '') else ''


def _orders(personcode):
    return (SoftechSalesOrder.objects
            .filter(cust_branch_code=str(personcode).strip())
            .exclude(status=SoftechSalesOrder.STATUS_CANCELLED)
            .order_by('-created_at'))


def _order_date(o):
    return o.doc_date or o.created_at.date()


def entry_config(personcode):
    """Contract row, else the global default ('' row), else the built-in default."""
    pc = str(personcode or '').strip()
    row = (ContractEntryConfig.objects.filter(personcode=pc).first() if pc else None) \
        or ContractEntryConfig.objects.filter(personcode='').first()
    if row:
        return {'per_visit_columns': list(row.per_visit_columns), 'approval_column': row.approval_column}
    return {'per_visit_columns': ['roshettano', 'examdate'], 'approval_column': 'roshettano'}


def _insurance_rx(personcode):
    from apps.insurance.models import InsuranceClaimPrescription
    return InsuranceClaimPrescription.objects.filter(softech_personcode=str(personcode).strip())


def patient_suggest(personcode, q, limit=10):
    cfg = entry_config(personcode)
    stable = [c for c in COLUMNS if c not in cfg['per_visit_columns'] and c != 'patientname']
    best = {}                                                    # norm name → candidate (latest wins)

    def offer(name, d, source, fields):
        key = _norm(name)
        if not key or not _matches(name, q):
            return
        cur = best.get(key)
        if cur is None or d > cur['_d']:
            best[key] = {'patientname': str(name).strip(), 'fields': fields,
                         'last_date': d.isoformat(), 'source': source, '_d': d}

    qs = _orders(personcode).filter(source_companies_raw__has_key='patientname')
    for o in qs[:_SCAN_CAP]:
        raw = o.source_companies_raw or {}
        fields = {c: _val(raw, c) for c in stable if _val(raw, c)}
        offer(_val(raw, 'patientname'), _order_date(o), 'pos', fields)
    for rx in _insurance_rx(personcode).exclude(patient_name='').order_by('-softech_docdate')[:_SCAN_CAP]:
        offer(rx.patient_name, rx.softech_docdate, 'insurance', {})

    out = sorted(best.values(), key=lambda r: r['_d'], reverse=True)[:limit]
    for r in out:
        r.pop('_d')
    return out


def _order_total(o, lines):
    net = sum((l.trans_price_total or 0) for l in lines)
    if net:
        return round(float(net), 2)
    return round(float(sum((l.qty or 0) * (l.item_sale_price_tax or l.item_sale_price or 0)
                           for l in lines)), 2)


def recent_prescriptions(personcode, patientname, *, branch_id=None, limit=5):
    key = _norm(patientname)
    if not key:
        return []
    cards = []
    qs = (_orders(personcode).filter(source_companies_raw__has_key='patientname')
          .prefetch_related('lines'))
    for o in qs[:_SCAN_CAP]:
        if _norm(_val(o.source_companies_raw, 'patientname')) != key:
            continue
        lines = list(o.lines.all())
        cards.append({'_d': _order_date(o), 'date': _order_date(o).isoformat(), 'source': 'pos',
                      'ref': o.id, 'total': _order_total(o, lines),
                      '_lines': [{'item_id': l.item_id, 'softech_itemcode': l.softech_itemcode,
                                  'qty': l.qty,
                                  'unit_price': l.item_sale_price_tax or l.item_sale_price}
                                 for l in lines]})
    rxs = (_insurance_rx(personcode).exclude(patient_name='')
           .order_by('-softech_docdate').prefetch_related('lines'))
    for rx in rxs[:_SCAN_CAP]:
        if _norm(rx.patient_name) != key:
            continue
        cards.append({'_d': rx.softech_docdate, 'date': rx.softech_docdate.isoformat(),
                      'source': 'insurance', 'ref': rx.softech_docnumber,
                      'total': float(rx.net_after or 0),
                      '_lines': [{'softech_itemcode': l.softech_itemcode, 'qty': l.quantity,
                                  'unit_price': l.unit_price} for l in rx.lines.all()]})
    cards.sort(key=lambda c: c['_d'], reverse=True)
    out = cards[:limit]
    for c in out:
        c['revalidated'] = revalidate_lines(c.pop('_lines'), branch_id=branch_id)
        c.pop('_d')
    return out


def field_values(personcode, column, q, limit=10):
    if column not in COLUMNS:
        raise ValueError('unknown contract column: %r' % (column,))
    counts = Counter()
    for o in _orders(personcode).filter(**{'source_companies_raw__has_key': column})[:_SCAN_CAP]:
        v = _val(o.source_companies_raw, column)
        if v and _matches(v, q):
            counts[v] += 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [v for v, _ in ranked[:limit]]


def approval_reused(personcode, value, *, exclude_order_id=None):
    value = str(value or '').strip()
    if not value:
        return []
    col = entry_config(personcode)['approval_column']
    qs = _orders(personcode).filter(**{'source_companies_raw__%s__icontains' % col: value})
    if exclude_order_id:
        qs = qs.exclude(pk=exclude_order_id)
    out = []
    for o in qs.order_by('-created_at')[:_SCAN_CAP]:
        raw = o.source_companies_raw or {}
        if _val(raw, col) != value:
            continue
        out.append({'order_id': o.id, 'date': _order_date(o).isoformat(),
                    'branch_id': o.branch_id, 'patientname': _val(raw, 'patientname')})
    return out
