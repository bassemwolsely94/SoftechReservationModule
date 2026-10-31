"""
apps/batches/return_calendar.py

P-29 (docs/product-review/06_SPEC_P-29_return_window_calendar.md): which supplier should take back
which batch, and by when.

  • stock     = StockExpiryBalance, live stores + store 105 (P-26 roles). 102 / 103 / closed are not
                return lines (owner: 102 is unreturnable; 110 is excluded everywhere).
  • supplier  = PurchaseExpiryEntry with the same item and expiry month (a heuristic — every line
                carries its confidence; a person confirms).
  • window    = return_window.window_for with the supplier's SupplierReturnPolicy offsets.
  • actions   = ExpiryDisposalRecord(decision='return_supplier', source='return_window'); the
                supplier's answer is recorded per line and builds the acceptance history.
  • auto-close from procurement.PurchaseLine doc 120 (return to supplier), each line used once.

Advisory only: nothing here writes to SOFTECH (owner rule 2026-09-15). The return itself and any
transfer to HQ are posted natively in SOFTECH.
"""
import datetime as dt
import logging
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .return_window import (DEFAULT_CLOSE_OFFSET, DEFAULT_OPEN_OFFSET, STATE_LABELS, window_for)
from .store_roles import LIVE, RETURN

logger = logging.getLogger('elrezeiky.batches')

RETURN_ROLES = (LIVE, RETURN)
OPEN_STATUSES = ('draft', 'approved')
ANSWERS = ('accepted', 'partial', 'rejected')
IN_WINDOW = ('open', 'closes_this_month')
CONFIDENCE_LABELS = {'exact': 'مطابق', 'month': 'نفس الشهر', 'ambiguous': 'أكثر من مورد',
                     'none': 'مورد غير معروف'}
LOCATIONS = ('shelf', 'hq', '105')
# Roles that see every branch's lines; everyone else sees their own branch's shelf only.
ALL_BRANCH_ROLES = {'admin', 'purchasing', 'quality_manager', 'supervisor'}


def _today():
    return timezone.localdate()


def _audit(action, staff, obj, **data):
    from apps.audit.models import AuditLog
    AuditLog.log(action, user=staff, obj=obj, **data)


def _setting(key, default):
    try:
        from apps.config.models import SystemSetting
        return SystemSetting.get(key, default)
    except Exception:
        return default


def lead_days():
    try:
        return max(0, int(_setting('return_window_branch_lead_days', 14)))
    except (TypeError, ValueError):
        return 14


def policies():
    from apps.procurement.models import SupplierReturnPolicy
    return {p.supplier_code: p for p in SupplierReturnPolicy.objects.filter(accepts_expiry_returns=True)}


def _hq_codes():
    from apps.branches.models import Branch
    codes = set(Branch.objects.filter(kind=Branch.KIND_HQ).values_list('softech_branch_id', flat=True))
    return codes or {'100'}


def location_of(branch_code, role, hq_codes):
    if role == RETURN:
        return '105'
    return 'hq' if branch_code in hq_codes else 'shelf'


# ── Attribution ──────────────────────────────────────────────────────────────

def attribute(pairs):
    """{(item_code, expiry_date): {confidence, suppliers (with a policy), others (without), names}}."""
    from .models import PurchaseExpiryEntry
    pairs = set(pairs)
    pol = policies()
    out = {}
    if not pairs:
        return out
    months = {(ic, exp.year, exp.month) for ic, exp in pairs}
    found = defaultdict(lambda: defaultdict(set))           # (item, y, m) → supplier → {exact dates}
    names = {}
    for ic, sup, name, exp in (PurchaseExpiryEntry.objects.filter(item_code__in={ic for ic, _ in pairs})
                               .values_list('item_code', 'supplier_code', 'supplier_name', 'entered_expiry')):
        key = (ic, exp.year, exp.month)
        if key in months:
            found[key][sup].add(exp)
            if name:
                names[sup] = name
    for ic, exp in pairs:
        by_sup = found.get((ic, exp.year, exp.month), {})
        with_policy = sorted(s for s in by_sup if s in pol)
        others = sorted(s for s in by_sup if s not in pol)
        if not with_policy:
            conf = 'none'
        elif len(with_policy) > 1:
            conf = 'ambiguous'
        else:
            conf = 'exact' if exp in by_sup[with_policy[0]] else 'month'
        out[(ic, exp)] = {'confidence': conf, 'suppliers': with_policy, 'others': others,
                          'names': {s: names.get(s, '') for s in by_sup}}
    return out


# ── History ──────────────────────────────────────────────────────────────────

def answer_history():
    """{(supplier_code, item_code): {accepted, partial, rejected, last, last_allowed}} from recorded
    answers — deterministic counts, used only to sort and hint (no line is hidden by it)."""
    from .models import ExpiryDisposalRecord
    out = {}
    rows = (ExpiryDisposalRecord.objects.filter(decision='return_supplier').exclude(supplier_answer='')
            .order_by('answered_at', 'created_at', 'pk')
            .values_list('supplier_code', 'item_code', 'supplier_answer', 'allowed_expiry'))
    for sup, ic, ans, allowed in rows:
        h = out.setdefault((sup, ic), {'accepted': 0, 'partial': 0, 'rejected': 0, 'last': '', 'last_allowed': None})
        h[ans] = h.get(ans, 0) + 1
        h['last'] = ans
        if allowed:
            h['last_allowed'] = allowed.isoformat()
    return out


def _history_hint(h):
    if not h:
        return ''
    if h['last'] == 'rejected':
        return 'رُفض آخر مرة'
    total = h['accepted'] + h['partial'] + h['rejected']
    return f"قُبل {h['accepted'] + h['partial']} من {total}"


# ── Calendar ─────────────────────────────────────────────────────────────────

def _key(branch, store, item, batch, expiry):
    return f'{branch}|{store}|{item}|{batch}|{expiry.isoformat() if expiry else ""}'


def calendar(today=None, month=None, supplier=None, location=None, branch_codes=None, state=None):
    """The tab's data. `month` (a date in the month to view) moves the reference date to the 1st of
    that month when it is not the current month."""
    from .models import ExpiryDisposalRecord, StockExpiryBalance
    from .expiry_audit import _item_attr_map

    today = today or _today()
    ref = today
    if month and (month.year, month.month) != (today.year, today.month):
        ref = month.replace(day=1)
    qs = StockExpiryBalance.objects.filter(qty__gt=0, store_role__in=RETURN_ROLES)
    if branch_codes is not None:
        qs = qs.filter(branch_code__in=list(branch_codes))
    rows = list(qs.values('branch_code', 'store_code', 'item_code', 'item_name', 'batch_no', 'expiry_date',
                          'qty', 'store_role'))
    att = attribute({(r['item_code'], r['expiry_date']) for r in rows})
    pol = policies()
    costs = _item_attr_map(list({r['item_code'] for r in rows}))
    history = answer_history()
    hq = _hq_codes()
    lead = dt.timedelta(days=lead_days())
    records = {}
    for rec in (ExpiryDisposalRecord.objects.filter(source='return_window', decision='return_supplier')
                .order_by('created_at', 'pk')):
        records[_key(rec.branch_code, rec.store_code, rec.item_code, rec.batch_no, rec.expiry_date)] = rec  # latest wins

    lines, summary, no_policy = [], {}, defaultdict(float)
    for r in rows:
        a = att[(r['item_code'], r['expiry_date'])]
        key = _key(r['branch_code'], r['store_code'], r['item_code'], r['batch_no'], r['expiry_date'])
        rec = records.get(key)
        sup = a['suppliers'][0] if len(a['suppliers']) == 1 else ''
        if not sup and rec and rec.supplier_code in a['suppliers']:
            sup = rec.supplier_code               # an ambiguous line where a person already picked the supplier
        p = pol.get(sup)
        w = window_for(r['expiry_date'], ref,
                       p.open_offset if p else DEFAULT_OPEN_OFFSET, p.close_offset if p else DEFAULT_CLOSE_OFFSET)
        if w['state'] == 'later':
            continue
        loc = location_of(r['branch_code'], r['store_role'], hq)
        if location and loc != location:
            continue
        if supplier and supplier != sup and supplier not in a['suppliers']:
            continue
        if state and w['state'] != state:
            continue
        qty = float(r['qty'])
        value = round(qty * (costs.get(r['item_code'], {}).get('unit_cost') or 0), 2)
        if a['confidence'] == 'none':
            if w['state'] in IN_WINDOW:
                no_policy[a['others'][0] if a['others'] else ''] += value
        elif sup:
            s = summary.setdefault(sup, {'supplier_name': (p.supplier_name if p else '') or a['names'].get(sup, ''),
                                         **{st: {'value': 0.0, 'lines': 0} for st in STATE_LABELS if st != 'later'}})
            s[w['state']]['value'] = round(s[w['state']]['value'] + value, 2)
            s[w['state']]['lines'] += 1
        h = history.get((sup, r['item_code'])) if sup else None
        lines.append({
            'key': key, 'branch_code': r['branch_code'], 'store_code': r['store_code'], 'location': loc,
            'item_code': r['item_code'], 'item_name': r['item_name'] or costs.get(r['item_code'], {}).get('name', ''),
            'batch_no': r['batch_no'], 'expiry_date': r['expiry_date'].isoformat(),
            'qty': qty, 'unit_cost': costs.get(r['item_code'], {}).get('unit_cost'), 'value': value,
            'opens': w['opens'].isoformat(), 'closes': w['closes'].isoformat(),
            'state': w['state'], 'state_label': STATE_LABELS[w['state']],
            'supplier_code': sup, 'supplier_name': a['names'].get(sup, '') if sup else '',
            'candidates': [{'code': s, 'name': a['names'].get(s, '')} for s in a['suppliers']],
            'confidence': a['confidence'], 'confidence_label': CONFIDENCE_LABELS[a['confidence']],
            'self_entry': bool(p and p.self_entry),
            'send_by': ((w['closes'] - lead).isoformat() if loc == 'shelf' else None),
            'history': _history_hint(h),
            'record': ({'id': rec.pk, 'status': rec.status, 'status_display': rec.get_status_display(),
                        'answer': rec.supplier_answer, 'accepted_qty': float(rec.accepted_qty)
                        if rec.accepted_qty is not None else None,
                        'allowed_expiry': rec.allowed_expiry.isoformat() if rec.allowed_expiry else None,
                        'returned_qty': float(rec.returned_qty)} if rec else None),
        })
    order = {'closes_this_month': 0, 'open': 1, 'opens_next_month': 2, 'missed': 3}
    lines.sort(key=lambda l: (order[l['state']], l['closes'], -l['value'], l['item_code']))
    names = {}
    if no_policy:
        from .models import PurchaseExpiryEntry
        names = dict(PurchaseExpiryEntry.objects.filter(supplier_code__in=[s for s in no_policy if s])
                     .exclude(supplier_name='').values_list('supplier_code', 'supplier_name').distinct())
    return {
        'today': ref.isoformat(),
        'lead_days': lead.days,
        'lines': lines,
        'suppliers': summary,
        'no_policy': sorted(({'supplier_code': s, 'supplier_name': names.get(s, '') if s else 'مورد غير معروف',
                              'value': round(v, 2)} for s, v in no_policy.items()),
                            key=lambda x: (-x['value'], x['supplier_code'])),
    }


# ── Actions ──────────────────────────────────────────────────────────────────

def _parse_date(v):
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def request_returns(lines, staff, branch_scope=None, today=None):
    """«طلب مرتجع» on ticked lines → draft return records. Quantities and costs come from the
    mirror, never from the request. Idempotent: one open record per supplier + location + item +
    batch + expiry. branch_scope: allowed branch codes (None = all)."""
    from .models import ExpiryDisposalRecord, StockExpiryBalance
    from .expiry_audit import _item_attr_map

    today = today or _today()
    pol = policies()
    created = 0
    for raw in lines or []:
        branch = str(raw.get('branch_code') or '').strip()
        store = str(raw.get('store_code') or '').strip()
        item = str(raw.get('item_code') or '').strip()
        batch = str(raw.get('batch_no') or '').strip()
        expiry = _parse_date(raw.get('expiry_date'))
        sup = str(raw.get('supplier_code') or '').strip()
        if not (branch and item and expiry) or sup not in pol:
            continue
        if branch_scope is not None and branch not in branch_scope:
            continue
        stock = (StockExpiryBalance.objects.filter(branch_code=branch, store_code=store, item_code=item,
                                                   batch_no=batch, expiry_date=expiry, qty__gt=0,
                                                   store_role__in=RETURN_ROLES).first())
        if stock is None:
            continue
        a = attribute([(item, expiry)])[(item, expiry)]
        if a['suppliers'] and sup not in a['suppliers']:
            continue
        p = pol[sup]
        w = window_for(expiry, today, p.open_offset, p.close_offset)
        with transaction.atomic():
            if ExpiryDisposalRecord.objects.select_for_update().filter(
                    decision='return_supplier', source='return_window', status__in=OPEN_STATUSES,
                    supplier_code=sup, branch_code=branch, store_code=store, item_code=item,
                    batch_no=batch, expiry_date=expiry).exists():
                continue
            unit_cost = _item_attr_map([item]).get(item, {}).get('unit_cost') or 0
            rec = ExpiryDisposalRecord.objects.create(
                item_code=item, item_name=stock.item_name, branch_code=branch, store_code=store,
                batch_no=batch, expiry_date=expiry, qty=stock.qty, unit_cost=unit_cost,
                value=round(float(stock.qty) * unit_cost, 2), decision='return_supplier',
                supplier_code=sup, supplier_name=p.supplier_name or a['names'].get(sup, ''),
                source='return_window', window_opens=w['opens'], window_closes=w['closes'],
                match_confidence=a['confidence'], created_by=staff)
            _audit('return_requested', staff, rec, new_data={
                'supplier': sup, 'branch': branch, 'store': store, 'item': item, 'batch': batch,
                'expiry': expiry.isoformat(), 'qty': str(stock.qty), 'closes': w['closes'].isoformat(),
                'confidence': a['confidence']})
        created += 1
    return created


def record_answer(rec, answer, staff, accepted_qty=None, allowed_expiry=None):
    """The supplier's answer for one line. rejected → cancelled «رفض المورد». Raises ValueError."""
    if answer not in ANSWERS:
        raise ValueError('رد غير صالح.')
    if rec.decision != 'return_supplier' or rec.status in ('done', 'cancelled'):
        raise ValueError('لا يمكن تسجيل رد على هذا السجل.')
    qty = None
    if answer == 'partial':
        try:
            qty = Decimal(str(accepted_qty))
        except Exception:
            raise ValueError('الكمية المقبولة مطلوبة.')
        if qty <= 0 or qty > rec.qty:
            raise ValueError('الكمية المقبولة يجب أن تكون بين صفر وكمية السطر.')
    elif answer == 'accepted':
        qty = rec.qty
    before = {'answer': rec.supplier_answer, 'status': rec.status,
              'accepted_qty': str(rec.accepted_qty) if rec.accepted_qty is not None else None}
    rec.supplier_answer = answer
    rec.accepted_qty = qty
    rec.allowed_expiry = _parse_date(allowed_expiry) if allowed_expiry else None
    rec.answered_by = staff
    rec.answered_at = timezone.now()
    if answer == 'rejected':
        rec.status = 'cancelled'
        rec.reason = (rec.reason + '\nرفض المورد').strip()
    rec.save(update_fields=['supplier_answer', 'accepted_qty', 'allowed_expiry', 'answered_by', 'answered_at',
                            'status', 'reason'])
    _audit('return_answered', staff, rec, old_data=before, new_data={
        'answer': answer, 'status': rec.status, 'accepted_qty': str(qty) if qty is not None else None,
        'allowed_expiry': rec.allowed_expiry.isoformat() if rec.allowed_expiry else None})
    return rec


# ── Auto-close from SOFTECH doc 120 ──────────────────────────────────────────

def _line_key(pl):
    return f'{pl.branch_code}|{pl.supplier_code}|{pl.doc_number}|{pl.doc_date.isoformat()}|{pl.item_code}|{pl.doccode}'


def reconcile_returns():
    """Close open return records from doc 120 lines (same supplier + item, dated on/after the record).
    Oldest record first; each PurchaseLine is used once (kept in softech_doc_refs), so a re-run
    changes nothing. doc 120 lines carry no expiry (expiry splits are collapsed), so the match is
    supplier + item only — stated in the help."""
    from apps.procurement.models import PurchaseLine
    from .models import ExpiryDisposalRecord

    open_recs = list(ExpiryDisposalRecord.objects.filter(
        source='return_window', decision='return_supplier', status__in=OPEN_STATUSES).order_by('created_at', 'pk'))
    if not open_recs:
        return {'closed': 0, 'partial': 0, 'lines_used': 0}
    used = set()
    for refs in ExpiryDisposalRecord.objects.exclude(softech_doc_refs=[]).values_list('softech_doc_refs', flat=True):
        used.update(refs or [])
    pairs = {(r.supplier_code, r.item_code) for r in open_recs}
    earliest = min(r.created_at for r in open_recs).date()
    by_pair = defaultdict(list)
    for pl in (PurchaseLine.objects.filter(doccode='120', doc_date__gte=earliest,
                                           supplier_code__in={s for s, _ in pairs},
                                           item_code__in={i for _, i in pairs})
               .order_by('doc_date', 'doc_number', 'pk')):
        if (pl.supplier_code, pl.item_code) in pairs and _line_key(pl) not in used:
            by_pair[(pl.supplier_code, pl.item_code)].append(pl)

    closed = partial = lines_used = 0
    for rec in open_recs:
        avail = by_pair.get((rec.supplier_code, rec.item_code), [])
        took = []
        for pl in list(avail):
            if rec.returned_qty >= rec.qty:
                break
            if pl.doc_date < rec.created_at.date():
                continue
            avail.remove(pl)
            took.append(pl)
            rec.returned_qty += abs(pl.raw_qty or Decimal('0'))
        if not took:
            continue
        lines_used += len(took)
        rec.softech_doc_refs = list(rec.softech_doc_refs or []) + [_line_key(pl) for pl in took]
        fields = ['returned_qty', 'softech_doc_refs']
        if rec.returned_qty >= rec.qty:
            rec.status = 'done'
            rec.closed_by_ledger_at = timezone.now()
            fields += ['status', 'closed_by_ledger_at']
            closed += 1
        else:
            partial += 1
        rec.save(update_fields=fields)
        _audit('return_closed_by_ledger', None, rec, new_data={
            'doc_lines': [_line_key(pl) for pl in took], 'returned_qty': str(rec.returned_qty),
            'status': rec.status})
    return {'closed': closed, 'partial': partial, 'lines_used': lines_used}


# ── Notifications + monthly KPI snapshot ─────────────────────────────────────

def branch_send_lines(branch_code, today=None):
    """«أرسل للرئيسي للمرتجع قبل …» lines for one branch's shelf — added to the weekly expiry worklist."""
    c = calendar(today=today, branch_codes=[branch_code], location='shelf')
    out = []
    for l in c['lines']:
        if l['state'] in IN_WINDOW and l['supplier_code'] and not (l['record'] and l['record']['status'] == 'done'):
            out.append(f"{l['item_name'] or l['item_code']} — كمية {l['qty']:g} — "
                       f"أرسل للرئيسي للمرتجع قبل {l['send_by']}")
    return out


def digest_recipients():
    from apps.users.models import StaffProfile
    ids = _setting('return_window_recipients', None)
    if isinstance(ids, list) and ids:
        qs = StaffProfile.objects.filter(pk__in=ids, is_active=True)
    else:
        qs = StaffProfile.objects.filter(role='purchasing', is_active=True)
        if not qs.exists():
            qs = StaffProfile.objects.filter(role='admin', is_active=True)
    return list(qs)


def monthly_digest(today=None):
    """1st of the month: snapshot each supplier's window values (once) and send one digest per
    recipient (dedup per month)."""
    from apps.notifications.models import Notification
    from .models import ReturnWindowMonthly

    today = today or _today()
    month = today.replace(day=1)
    c = calendar(today=today)
    snapshots = 0
    for sup, s in c['suppliers'].items():
        _, made = ReturnWindowMonthly.objects.get_or_create(supplier_code=sup, month=month, defaults={
            'opens_next_month_value': Decimal(str(s['opens_next_month']['value'])),
            'open_value': Decimal(str(s['open']['value'])),
            'closes_this_month_value': Decimal(str(s['closes_this_month']['value'])),
            'missed_value': Decimal(str(s['missed']['value']))})
        snapshots += int(made)
    if not c['suppliers']:
        return {'sent': 0, 'snapshots': 0}
    body_lines = [f"{s['supplier_name'] or sup}: داخل النافذة {round(s['open']['value']):,} ج · "
                  f"تُغلق هذا الشهر {round(s['closes_this_month']['value']):,} ج · "
                  f"تفتح الشهر القادم {round(s['opens_next_month']['value']):,} ج"
                  for sup, s in sorted(c['suppliers'].items())]
    body = '\n'.join(body_lines) + '\n\nافتح «الصلاحية» ← «📆 تقويم المرتجع».'
    sent = 0
    for staff in digest_recipients():
        n = Notification.send_to_user(staff, 'return_window_digest',
                                      f"📆 نوافذ مرتجع الموردين — {month.strftime('%Y-%m')}", body,
                                      dedup_key=f"return_window_{month.strftime('%Y-%m')}", dedup_once=True)
        sent += int(n is not None)
    return {'sent': sent, 'snapshots': snapshots}
