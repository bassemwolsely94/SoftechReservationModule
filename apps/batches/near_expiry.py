"""
apps/batches/near_expiry.py

Top-10 C04 / P-28 (docs/product-review/06_SPEC_P-28_near_expiry_worklist.md): the near-expiry action
worklist — lots that will NOT sell before they expire, ONE suggested action per lot, the action a person
chose, and N days later what really happened to the lot.

Deterministic rules (nothing here is decided by a model, and nothing writes to SOFTECH):
  • lots      = StockExpiryBalance, live stores (P-26), qty > 0, today ≤ expiry ≤ today + horizon,
                retail branches only (HQ has no sales rate) — optional pilot list
                SystemSetting `near_expiry_worklist_branches` (CSV of SOFTECH codes; empty = every branch).
  • at risk   = stock_expiry.fefo_at_risk_lots — the one FEFO rule shared with the P-26 KPIs and
                rebalance.plan (rate = qty_90d / 90). A lot is listed when ≥ 1 pack is at risk.
  • action    = the owner's fixed order (P-28 §2.3); each step takes what it can:
                  1 return       supplier with a return policy, window opens next month / open /
                                 closes this month, and the branch can still send it to HQ in time
                                 (return_calendar.calendar's send_by ≥ today) → takes the whole at-risk qty
                  2 move         rebalance.plan found a branch that sells it in time (not fridge items,
                                 not strategic-hold items)
                  3 sell_first   «ركن قرب الانتهاء» — a shelf/counter FLAG only, never a price change; never
                                 for a sale-blocked or return-only item, and not below
                                 `near_expiry_sell_first_min_days` (30) days left
                  4 accept_loss  what is left
  • choose    = NearExpiryAction, one OPEN row per lot (DB constraint); choosing again updates it (audited).
  • return    = return_calendar.request_returns (idempotent P-29 record), linked to the action.
  • move      = a DRAFT transfer through the existing /transfers/ API, linked after a server check.
  • outcome   = after `near_expiry_outcome_days` (30), at expiry, or when the lot is gone: the qty drop
                is explained from the stock ledger mirror (115/80 − 30 sold, 125 moved / sent to HQ,
                160/150 written off), each ledger line used once; what is left is «expired» (past expiry)
                or «on hand». Saved value counts only the at-risk part.
"""
import datetime as dt
import logging
from collections import defaultdict
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.batches')

ACTIONS = ('return', 'move', 'sell_first', 'accept_loss')
ACTION_LABELS = {'return': 'مرتجع للمورد', 'move': 'نقل لفرع يبيعه',
                 'sell_first': 'ركن قرب الانتهاء / بيع أولاً', 'accept_loss': 'قبول الخسارة'}
RETURN_STATES = ('opens_next_month', 'open', 'closes_this_month')
SALE_DOCS, SALE_RETURN_DOCS, MOVE_DOCS, WRITE_OFF_DOCS = ('115', '80'), ('30',), ('125',), ('160', '150')
LEDGER_DOCS = SALE_DOCS + SALE_RETURN_DOCS + MOVE_DOCS + WRITE_OFF_DOCS
SAVED_CLASSES = ('returned', 'moved', 'sold')
DOMINANT_SHARE = 0.9
MIN_PACKS = 1.0


def _setting(key, default):
    try:
        from apps.config.models import SystemSetting
        v = SystemSetting.get(key, default)
        return default if v in (None, '') else v
    except Exception:
        return default


def _int_setting(key, default):
    try:
        return max(0, int(_setting(key, default)))
    except (TypeError, ValueError):
        return default


def config():
    from .rebalance import _cfg
    return {'horizon_days': _cfg('HORIZON_DAYS', 180),
            'sell_first_min_days': _int_setting('near_expiry_sell_first_min_days', 30),
            'outcome_days': _int_setting('near_expiry_outcome_days', 30) or 30}


def pilot_branches():
    """SOFTECH codes from `near_expiry_worklist_branches`; an empty set = every retail branch."""
    raw = _setting('near_expiry_worklist_branches', '')
    if isinstance(raw, (list, tuple)):
        vals = raw
    else:
        vals = str(raw).split(',')
    return {str(v).strip() for v in vals if str(v).strip()}


def lot_key(branch, store, item, batch, expiry):
    from .return_calendar import _key
    return _key(branch, store, item, batch, expiry)


def _round(v, d=3):
    return round(float(v or 0), d)


# ── Pure rules (unit-tested without the DB) ──────────────────────────────────

def suggest(lot, *, ret=None, move_qty=0.0, sellable=True, can_move=True, sell_first_min_days=30):
    """The owner's fixed order for one lot. lot: {at_risk_qty, days_left}; ret: the return line or None.
    Returns (suggested_action, split {action: qty}) — split sums to the at-risk qty."""
    at_risk = float(lot['at_risk_qty'])
    if ret is not None:
        return 'return', {'return': _round(at_risk)}
    split, left = {}, at_risk
    moving = min(left, float(move_qty or 0)) if can_move else 0.0
    if moving >= MIN_PACKS:
        split['move'] = _round(moving)
        left -= moving
    if left > 1e-9:
        if sellable and lot['days_left'] >= sell_first_min_days:
            split['sell_first'] = _round(left)
        else:
            split['accept_loss'] = _round(left)
    first = next((a for a in ACTIONS if split.get(a, 0) >= MIN_PACKS), None)
    return first or max(split, key=split.get), split


def classify(*, t0_qty, at_risk_qty, now_qty, expired, evidence, unit_cost):
    """What happened to a lot. evidence: ledger qty per class {returned, moved, sold, written_off} (≥ 0).
    The qty drop is explained in that order, each class capped by what is left of the drop; the rest of
    the drop is «unexplained» (never saved). The qty still there is «expired» past the expiry date,
    else «on_hand». Saved = returned + moved + sold, capped at the at-risk qty (sales the lot would
    have made anyway are not a rescue). One class with ≥ 90% of the lot names the outcome, else «mixed»."""
    t0, now = max(0.0, float(t0_qty)), max(0.0, float(now_qty))
    drop, alloc = max(0.0, t0 - now), {}
    left = drop
    for cls in ('returned', 'moved', 'sold', 'written_off'):
        take = min(left, max(0.0, float(evidence.get(cls) or 0)))
        if take > 1e-9:
            alloc[cls] = take
            left -= take
    if left > 1e-9:
        alloc['unexplained'] = left
    remain = min(now, t0)
    if remain > 1e-9:
        alloc['expired' if expired else 'on_hand'] = remain
    total = sum(alloc.values())
    saved_qty = min(sum(alloc.get(c, 0.0) for c in SAVED_CLASSES), max(0.0, float(at_risk_qty)))
    lost_qty = alloc.get('written_off', 0.0) + alloc.get('expired', 0.0)
    if total <= 1e-9:
        outcome = 'unexplained'
    else:
        top = max(alloc, key=lambda c: (alloc[c], c))
        outcome = top if alloc[top] >= DOMINANT_SHARE * total else 'mixed'
    cost = float(unit_cost or 0)
    return {'outcome': outcome, 'qty': {c: _round(q) for c, q in alloc.items()},
            'saved_qty': _round(saved_qty), 'saved_value': round(saved_qty * cost, 2),
            'lost_qty': _round(lost_qty), 'lost_value': round(lost_qty * cost, 2)}


# ── The worklist ─────────────────────────────────────────────────────────────

def _branches(scope_codes):
    """{code: Branch} — retail branches, narrowed by the pilot list and the caller's scope (None = all)."""
    from apps.branches.models import Branch
    out = {b.softech_branch_id: b for b in Branch.objects.retail()}
    pilot = pilot_branches()
    if pilot:
        out = {c: b for c, b in out.items() if c in pilot}
    if scope_codes is not None:
        allowed = {str(c) for c in scope_codes}
        out = {c: b for c, b in out.items() if c in allowed}
    return out


def _open_transfers(item_codes):
    """{(item, source branch): {id, number}} — open transfers (rebalance.OPEN_TRANSFER) out of a branch."""
    from apps.transfers.models import TransferRequestItem
    from .rebalance import OPEN_TRANSFER
    out = {}
    if not item_codes:
        return out
    for ic, src, rid, num in (TransferRequestItem.objects
                              .filter(item__softech_id__in=item_codes, request__status__in=OPEN_TRANSFER)
                              .values_list('item__softech_id', 'request__supplying_branch__softech_branch_id',
                                           'request_id', 'request__request_number')):
        out.setdefault((str(ic), str(src)), {'id': rid, 'number': num})
    return out


def _moves(today, horizon):
    """{(item, branch, batch_no, expiry): [{to, qty, target_rate}]} from rebalance.plan (network-wide)."""
    from .rebalance import _cfg, _load, plan
    batches, rates, target_stock, meta, hq, _ = _load(today, horizon)
    lines, _b = plan(batches, rates, target_stock, today=today, horizon=horizon,
                     min_days=_cfg('MIN_DAYS', 30), transit=_cfg('TRANSIT_DAYS', 7), hq_codes=frozenset(hq))
    out = defaultdict(list)
    for l in lines:
        out[(l['item'], l['from'], l['batch_no'], l['expiry'])].append(
            {'to': l['to'], 'to_id': meta[l['to']].id if l['to'] in meta else None,
             'to_name': (meta[l['to']].name_ar or meta[l['to']].name) if l['to'] in meta else l['to'],
             'qty': l['qty'], 'target_rate_month': round(l['target_rate'] * 30, 2)})
    return out


def _returns(today, codes):
    """{lot key: return line} for branch-shelf lots the return step can take (P-29 calendar)."""
    from .return_calendar import calendar
    if not codes:
        return {}
    out = {}
    for l in calendar(today=today, branch_codes=sorted(codes), location='shelf')['lines']:
        if l['state'] not in RETURN_STATES or not l['supplier_code']:
            continue
        if not l['send_by'] or l['send_by'] < today.isoformat():
            continue
        if l['record'] and l['record']['status'] in ('done', 'cancelled'):
            continue
        out[l['key']] = l
    return out


def worklist(*, scope_codes=None, branch=None, action=None, today=None):
    """The tab's data: one row per at-risk lot, ranked by at-risk value. scope_codes: the caller's
    branches (None = all); branch: optional filter (one code or a list)."""
    from apps.catalog.models import Item
    from apps.catalog.safety import item_safety_flags
    from .expiry_audit import _item_attr_map
    from .models import NearExpiryAction, StockExpiryBalance
    from .stock_expiry import _daily_rates, fefo_at_risk_lots
    from .store_roles import LIVE

    today = today or timezone.localdate()
    cfg = config()
    horizon = cfg['horizon_days']
    branches = _branches(scope_codes)
    wanted = {str(b) for b in ([branch] if isinstance(branch, (str, int)) else (branch or [])) if str(b)}
    if wanted:
        branches = {c: b for c, b in branches.items() if c in wanted}
    empty = {'rows': [], 'totals': {a: {'lines': 0, 'value': 0.0} for a in ACTIONS},
             'settings': cfg, 'branches': [{'code': c, 'name': b.name_ar or b.name} for c, b in sorted(branches.items())],
             'pilot': sorted(pilot_branches()), 'have_rates': False}
    if not branches:
        return empty

    stock = (StockExpiryBalance.objects.filter(store_role=LIVE, qty__gt=0, branch_code__in=list(branches),
                                               expiry_date__gte=today,
                                               expiry_date__lte=today + dt.timedelta(days=horizon))
             .values('branch_code', 'store_code', 'item_code', 'item_name', 'batch_no', 'expiry_date', 'qty'))
    grouped, info = defaultdict(list), {}
    for r in stock:
        k = lot_key(r['branch_code'], r['store_code'], r['item_code'], r['batch_no'], r['expiry_date'])
        if k in info:                                    # same lot twice in the mirror: one line
            info[k]['qty'] += float(r['qty'])
            continue
        info[k] = {**r, 'qty': float(r['qty'])}
    for k, r in info.items():
        grouped[(r['item_code'], r['branch_code'])].append((r['expiry_date'], r['qty'], k))
    rates = _daily_rates(set(grouped))
    lots = []
    for (ic, bc), batch_list in grouped.items():
        for lot in fefo_at_risk_lots(batch_list, rates.get((ic, bc), 0.0), today, horizon):
            if lot['at_risk_qty'] >= MIN_PACKS:
                lots.append({**info[lot['ref']], **lot, 'key': lot['ref'], 'rate': rates.get((ic, bc), 0.0)})
    if not lots:
        return {**empty, 'have_rates': bool(rates)}

    codes = {l['item_code'] for l in lots}
    items = {i.softech_id: i for i in Item.objects.filter(softech_id__in=codes)}
    costs = _item_attr_map(list(codes))
    rets = _returns(today, {l['branch_code'] for l in lots})
    moves = _moves(today, horizon)
    open_tr = _open_transfers(codes)
    actions = {lot_key(a.branch_code, a.store_code, a.item_code, a.batch_no, a.expiry_date): a
               for a in NearExpiryAction.objects.filter(status='open', branch_code__in=list(branches))
               .select_related('transfer_request', 'disposal_record')}
    move_left = {k: sum(m['qty'] for m in v) for k, v in moves.items()}

    rows = []
    for l in sorted(lots, key=lambda x: (x['expiry'], x['key'])):
        it = items.get(l['item_code'])
        flags = item_safety_flags(it) if it else []
        codes_ = {f['code'] for f in flags}
        sellable = it is not None and not any(f['severity'] == 'block' for f in flags) and 'return_only' not in codes_
        fridge = bool(it and it.requires_fridge)
        hold = bool(it and getattr(it, 'strategic_hold', False))
        mk = (l['item_code'], l['branch_code'], l['batch_no'] or '', l['expiry'])
        ret = rets.get(l['key'])
        can_move = not fridge and not hold
        mq = min(move_left.get(mk, 0.0), l['at_risk_qty']) if can_move and ret is None else 0.0
        suggested, split = suggest(l, ret=ret, move_qty=mq, sellable=sellable, can_move=can_move,
                                   sell_first_min_days=cfg['sell_first_min_days'])
        if split.get('move'):
            move_left[mk] = move_left.get(mk, 0.0) - split['move']
        unit_cost = float(costs.get(l['item_code'], {}).get('unit_cost') or 0)
        detail = {}
        if ret is not None:
            detail['return'] = {'supplier_code': ret['supplier_code'], 'supplier_name': ret['supplier_name'],
                                'confidence': ret['confidence'], 'confidence_label': ret['confidence_label'],
                                'closes': ret['closes'], 'send_by': ret['send_by'], 'state_label': ret['state_label'],
                                'history': ret['history'], 'record': ret['record']}
        if split.get('move'):
            detail['move'] = [m for m in moves.get(mk, [])][:3]
        tr = open_tr.get((l['item_code'], l['branch_code']))
        act = actions.get(l['key'])
        rows.append({
            'key': l['key'], 'branch_code': l['branch_code'], 'store_code': l['store_code'],
            'item_code': l['item_code'], 'item_id': it.id if it else None,
            'item_name': l['item_name'] or (it.name if it else l['item_code']),
            'batch_no': l['batch_no'], 'expiry_date': l['expiry'].isoformat(), 'days_left': l['days_left'],
            'qty': _round(l['qty']), 'rate_month': round(l['rate'] * 30, 2), 'at_risk_qty': _round(l['at_risk_qty']),
            'unit_cost': unit_cost, 'at_risk_value': round(l['at_risk_qty'] * unit_cost, 2),
            'suggested_action': suggested, 'suggested_label': ACTION_LABELS[suggested], 'split': split,
            'detail': detail, 'source_branch_id': branches[l['branch_code']].id,
            'safety': [{'code': f['code'], 'severity': f['severity'], 'label': f['label_ar']} for f in flags],
            'fridge': fridge, 'strategic_hold': hold,
            'open_transfer': tr,
            'action': ({'id': act.pk, 'chosen_action': act.chosen_action,
                        'chosen_label': ACTION_LABELS.get(act.chosen_action, ''), 'note': act.note,
                        'due_date': act.due_date.isoformat(),
                        'transfer': act.transfer_request.request_number if act.transfer_request_id else '',
                        'disposal_record_id': act.disposal_record_id} if act else None),
        })
    totals = {a: {'lines': 0, 'value': 0.0} for a in ACTIONS}       # the chips count every line
    for r in rows:
        t = totals[r['suggested_action']]
        t['lines'] += 1
        t['value'] = round(t['value'] + r['at_risk_value'], 2)
    if action in ACTIONS:
        rows = [r for r in rows if r['suggested_action'] == action]
    rows.sort(key=lambda r: (-r['at_risk_value'], r['expiry_date'], r['key']))
    return {**empty, 'rows': rows, 'totals': totals, 'have_rates': bool(rates)}


# ── Choosing and acting ──────────────────────────────────────────────────────

def _audit(action, staff, obj, **data):
    from apps.audit.models import AuditLog
    AuditLog.log(action, user=staff, obj=obj, **data)


def _rows_for(lots, scope_codes, today):
    """The server's own worklist rows for the requested lot keys (quantities never come from the client)."""
    keys = {str(x.get('key') if isinstance(x, dict) else x) for x in (lots or [])}
    codes = {k.split('|', 1)[0] for k in keys if '|' in k}
    if scope_codes is not None:
        codes &= {str(c) for c in scope_codes}
    if not codes:
        return {}
    data = worklist(scope_codes=scope_codes, branch=sorted(codes), today=today)
    return {r['key']: r for r in data['rows'] if r['key'] in keys}


def _set_action(row, chosen, note, staff, today, **links):
    """Create or change the one open action for a lot. Returns (action, created?)."""
    from .models import NearExpiryAction
    ident = {'branch_code': row['branch_code'], 'store_code': row['store_code'], 'item_code': row['item_code'],
             'batch_no': row['batch_no'], 'expiry_date': dt.date.fromisoformat(row['expiry_date'])}
    with transaction.atomic():
        act = NearExpiryAction.objects.select_for_update().filter(status='open', **ident).first()
        if act is not None:
            before = {'chosen_action': act.chosen_action, 'note': act.note,
                      'transfer_request': act.transfer_request_id, 'disposal_record': act.disposal_record_id}
            act.chosen_action, act.chosen_by = chosen, staff
            if note:
                act.note = note
            for k, v in links.items():
                setattr(act, k, v)
            act.save()
            after = {'chosen_action': act.chosen_action, 'note': act.note,
                     'transfer_request': act.transfer_request_id, 'disposal_record': act.disposal_record_id}
            if after != before:
                _audit('near_expiry_action_changed', staff, act, old_data=before, new_data=after)
            return act, False
        try:
            with transaction.atomic():
                act = NearExpiryAction.objects.create(
                    **ident, item_name=row['item_name'][:255], t0_qty=Decimal(str(row['qty'])),
                    t0_at_risk_qty=Decimal(str(row['at_risk_qty'])), t0_unit_cost=Decimal(str(row['unit_cost'])),
                    t0_value=Decimal(str(row['at_risk_value'])),
                    t0_daily_rate=Decimal(str(round(row['rate_month'] / 30, 4))),
                    suggested_action=row['suggested_action'], split=row['split'], suggest_detail=row['detail'],
                    chosen_action=chosen, note=note or '', chosen_by=staff,
                    due_date=min(today + dt.timedelta(days=config()['outcome_days']), ident['expiry_date']
                                 + dt.timedelta(days=1)), **links)
        except IntegrityError:                       # a parallel click opened it first: change that one
            return _set_action(row, chosen, note, staff, today, **links)
    _audit('near_expiry_action_chosen', staff, act, new_data={
        'lot': row['key'], 'chosen_action': chosen, 'suggested_action': row['suggested_action'],
        'at_risk_qty': row['at_risk_qty'], 'at_risk_value': row['at_risk_value'], 'note': note or '',
        **{k: getattr(v, 'pk', v) for k, v in links.items()}})
    return act, True


def choose(lots, chosen, staff, *, note='', scope_codes=None, today=None):
    """Bulk choose one action for the ticked lots. Lots off the worklist (or outside scope) are skipped."""
    if chosen not in ACTIONS:
        raise ValueError('إجراء غير معروف')
    note = (note or '').strip()
    if chosen == 'accept_loss' and not note:
        raise ValueError('اكتب سبب قبول الخسارة')
    today = today or timezone.localdate()
    rows = _rows_for(lots, scope_codes, today)
    created = updated = 0
    for row in rows.values():
        _, new = _set_action(row, chosen, note, staff, today)
        created, updated = created + new, updated + (not new)
    return {'created': created, 'updated': updated, 'skipped': len(lots or []) - len(rows)}


def request_return(lots, staff, *, scope_codes=None, today=None):
    """«طلب مرتجع» for ticked lots whose suggestion is a return: the P-29 record (idempotent — an open record
    for the same lot is linked, never duplicated) + the action set to «return»."""
    from .models import ExpiryDisposalRecord
    from .return_calendar import OPEN_STATUSES, request_returns
    today = today or timezone.localdate()
    rows = _rows_for(lots, scope_codes, today)
    created = linked = 0
    for row in rows.values():
        ret = row['detail'].get('return')
        if not ret:
            continue
        created += request_returns([{'branch_code': row['branch_code'], 'store_code': row['store_code'],
                                     'item_code': row['item_code'], 'batch_no': row['batch_no'],
                                     'expiry_date': row['expiry_date'], 'supplier_code': ret['supplier_code']}],
                                   staff, branch_scope=scope_codes, today=today)
        rec = (ExpiryDisposalRecord.objects.filter(
            source='return_window', decision='return_supplier', status__in=OPEN_STATUSES,
            supplier_code=ret['supplier_code'], branch_code=row['branch_code'], store_code=row['store_code'],
            item_code=row['item_code'], batch_no=row['batch_no'], expiry_date=row['expiry_date'])
            .order_by('-created_at').first())
        if rec is None:
            continue
        _set_action(row, 'return', '', staff, today, disposal_record=rec)
        linked += 1
    return {'created': created, 'linked': linked, 'skipped': len(lots or []) - linked}


def link_transfer(lot, transfer_id, staff, *, scope_codes=None, today=None):
    """Link a draft/open transfer to a lot after checking it really moves this item out of this branch."""
    from apps.transfers.models import TransferRequest
    from .rebalance import OPEN_TRANSFER
    today = today or timezone.localdate()
    rows = _rows_for([lot], scope_codes, today)
    if not rows:
        raise LookupError('السطر غير موجود في قائمة العمل')
    row = next(iter(rows.values()))
    tr = (TransferRequest.objects.select_related('supplying_branch', 'requesting_branch')
          .filter(pk=transfer_id).first())
    if tr is None or tr.status not in OPEN_TRANSFER:
        raise ValueError('طلب التحويل غير موجود أو مُقفل')
    if str(getattr(tr.supplying_branch, 'softech_branch_id', '')) != row['branch_code'] \
            or tr.requesting_branch_id == tr.supplying_branch_id:
        raise ValueError('طلب التحويل ليس من فرع هذه التشغيلة')
    if not tr.items.filter(item__softech_id=row['item_code']).exists():
        raise ValueError('طلب التحويل لا يحتوي هذا الصنف')
    act, _ = _set_action(row, 'move', '', staff, today, transfer_request=tr)
    return act


# ── Outcome check ────────────────────────────────────────────────────────────

def _line_key(l):
    exp = l['itemexpirydate'].isoformat() if l['itemexpirydate'] else ''
    return f"{l['branchcode']}|{l['doccode']}|{l['docnumber']}|{l['docdate'].isoformat()}|{l['itemcode']}|{exp}"


def _class_of(line, chosen, hq_codes):
    doc = line['doccode']
    if doc in SALE_DOCS:
        return 'sold'
    if doc in SALE_RETURN_DOCS:
        return 'sale_return'
    if doc in WRITE_OFF_DOCS:
        return 'written_off'
    if doc in MOVE_DOCS:
        to_hq = str(line['storecode2'] or '').strip() in hq_codes
        return 'returned' if (to_hq and chosen == 'return') else 'moved'
    return None


def evaluate_outcomes(today=None):
    """The scheduler / button entry: one transaction that row-locks the open actions, so a second
    concurrent run waits, then re-reads them as closed and does nothing (no ledger line used twice)."""
    with transaction.atomic():
        return _evaluate_outcomes(today)


def _evaluate_outcomes(today=None):
    """Close the open actions that are due (N days passed, expiry passed, or the lot left the mirror).
    Each ledger line is used once across all actions (ledger_refs keeps {line key: qty used}); lots of
    the same item at a branch take lines earliest expiry first (FEFO), and a line that carries an
    expiry date only explains the lot with that expiry. Re-running changes nothing already closed."""
    from apps.stock_audit.models import StockLedgerLine
    from .models import NearExpiryAction, StockExpiryBalance
    from .return_calendar import _hq_codes
    from .store_roles import LIVE

    today = today or timezone.localdate()
    open_acts = list(NearExpiryAction.objects.select_for_update().filter(status='open').order_by('pk'))
    if not open_acts:
        return {'closed': 0, 'open': 0}
    now_qty = defaultdict(float)
    for r in (StockExpiryBalance.objects.filter(store_role=LIVE, qty__gt=0,
                                                branch_code__in={a.branch_code for a in open_acts},
                                                item_code__in={a.item_code for a in open_acts})
              .values('branch_code', 'store_code', 'item_code', 'batch_no', 'expiry_date', 'qty')):
        now_qty[lot_key(r['branch_code'], r['store_code'], r['item_code'], r['batch_no'], r['expiry_date'])] += float(r['qty'])

    def key_of(a):
        return lot_key(a.branch_code, a.store_code, a.item_code, a.batch_no, a.expiry_date)

    due = [a for a in open_acts if today >= a.due_date or today > a.expiry_date or now_qty.get(key_of(a), 0.0) <= 0]
    if not due:
        return {'closed': 0, 'open': len(open_acts)}
    used = defaultdict(float)
    for refs in NearExpiryAction.objects.filter(status='closed').exclude(ledger_refs={}).values_list('ledger_refs', flat=True):
        for k, q in (refs or {}).items():
            used[k] += float(q or 0)
    hq = _hq_codes()
    by_group = defaultdict(list)
    for a in due:
        by_group[(a.branch_code, a.item_code)].append(a)
    closed = 0
    for (bc, ic), acts in by_group.items():
        since = min(a.created_at for a in acts).date()
        lines = list(StockLedgerLine.objects.filter(branchcode=bc, itemcode=ic, doccode__in=LEDGER_DOCS,
                                                    docdate__gte=since, docdate__lte=today)
                     .order_by('docdate', 'docnumber', 'pk')
                     .values('branchcode', 'doccode', 'docnumber', 'docdate', 'itemcode', 'itemexpirydate',
                             'storecode2', 'transqty'))
        avail = defaultdict(float)
        for l in lines:
            avail[_line_key(l)] += abs(float(l['transqty'] or 0))
        for k in list(avail):
            avail[k] = max(0.0, avail[k] - used.get(k, 0.0))
        for a in sorted(acts, key=lambda x: (x.expiry_date, x.pk)):
            start = a.created_at.date()
            pool = defaultdict(list)                 # class → [line key]
            for l in lines:
                if l['docdate'] < start or (l['itemexpirydate'] and l['itemexpirydate'] != a.expiry_date):
                    continue
                cls = _class_of(l, a.chosen_action, hq)
                k = _line_key(l)
                if cls and avail[k] > 1e-9 and k not in pool[cls]:
                    pool[cls].append(k)
            ret_qty = sum(avail[k] for k in pool['sale_return'])
            evidence = {c: sum(avail[k] for k in pool[c]) for c in ('returned', 'moved', 'written_off')}
            evidence['sold'] = max(0.0, sum(avail[k] for k in pool['sold']) - ret_qty)
            res = classify(t0_qty=float(a.t0_qty), at_risk_qty=float(a.t0_at_risk_qty),
                           now_qty=now_qty.get(key_of(a), 0.0), expired=today > a.expiry_date,
                           evidence=evidence, unit_cost=float(a.t0_unit_cost))
            refs = {}

            def consume(keys, qty):
                for k in keys:
                    if qty <= 1e-9:
                        break
                    take = min(avail[k], qty)
                    if take > 1e-9:
                        avail[k] -= take
                        refs[k] = round(refs.get(k, 0.0) + take, 5)
                        qty -= take
            for c in ('returned', 'moved', 'written_off'):
                consume(pool[c], res['qty'].get(c, 0.0))
            if res['qty'].get('sold'):
                consume(pool['sale_return'], ret_qty)        # the returns netted out of the sales
                consume(pool['sold'], res['qty']['sold'] + ret_qty)
            a.status, a.outcome, a.outcome_qty = 'closed', res['outcome'], res['qty']
            a.saved_value, a.lost_value = Decimal(str(res['saved_value'])), Decimal(str(res['lost_value']))
            a.outcome_at, a.ledger_refs = timezone.now(), refs
            a.save(update_fields=['status', 'outcome', 'outcome_qty', 'saved_value', 'lost_value',
                                  'outcome_at', 'ledger_refs', 'updated_at'])
            _audit('near_expiry_outcome', None, a, new_data={
                'outcome': res['outcome'], 'qty': res['qty'], 'saved_value': res['saved_value'],
                'lost_value': res['lost_value'], 'ledger_lines': len(refs)})
            closed += 1
    return {'closed': closed, 'open': len(open_acts) - closed}


def outcomes(*, scope_codes=None, branch=None, date_from=None, date_to=None):
    """«ماذا حدث؟»: closed actions with their outcome + totals, and the still-open ones with their due date."""
    from .models import NearExpiryAction
    qs = NearExpiryAction.objects.select_related('chosen_by__user', 'transfer_request')
    if scope_codes is not None:
        qs = qs.filter(branch_code__in=[str(c) for c in scope_codes])
    wanted = [str(b) for b in ([branch] if isinstance(branch, (str, int)) else (branch or [])) if str(b)]
    if wanted:
        qs = qs.filter(branch_code__in=wanted)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    rows, totals = [], {'saved_value': 0.0, 'lost_value': 0.0, 't0_value': 0.0, 'closed': 0, 'open': 0,
                        'by_outcome': defaultdict(int), 'by_action': defaultdict(int)}
    labels = dict(NearExpiryAction.OUTCOME_CHOICES)
    for a in qs.order_by('-created_at')[:2000]:
        rows.append({'id': a.pk, 'branch_code': a.branch_code, 'item_code': a.item_code, 'item_name': a.item_name,
                     'batch_no': a.batch_no, 'expiry_date': a.expiry_date.isoformat(),
                     'chosen_action': a.chosen_action, 'chosen_label': ACTION_LABELS.get(a.chosen_action, ''),
                     'suggested_action': a.suggested_action, 'chosen_at': a.created_at.isoformat(),
                     'chosen_by': getattr(a.chosen_by, 'full_name', '') or '',
                     'due_date': a.due_date.isoformat(), 'status': a.status,
                     't0_qty': float(a.t0_qty), 't0_at_risk_qty': float(a.t0_at_risk_qty), 't0_value': float(a.t0_value),
                     'outcome': a.outcome, 'outcome_label': labels.get(a.outcome, ''), 'outcome_qty': a.outcome_qty,
                     'saved_value': float(a.saved_value), 'lost_value': float(a.lost_value),
                     'transfer': a.transfer_request.request_number if a.transfer_request_id else '',
                     'disposal_record_id': a.disposal_record_id})
        totals['by_action'][a.chosen_action] += 1
        totals['t0_value'] += float(a.t0_value)
        if a.status == 'closed':
            totals['closed'] += 1
            totals['saved_value'] += float(a.saved_value)
            totals['lost_value'] += float(a.lost_value)
            totals['by_outcome'][a.outcome] += 1
        else:
            totals['open'] += 1
    for k in ('saved_value', 'lost_value', 't0_value'):
        totals[k] = round(totals[k], 2)
    totals['by_outcome'], totals['by_action'] = dict(totals['by_outcome']), dict(totals['by_action'])
    return {'rows': rows, 'totals': totals, 'outcome_labels': labels}
