"""
apps/supply/engine/recommend.py — the orchestrator.

Chains the read-only engines into ONE explainable recommendation for an item (optionally a
requesting branch, optionally against live supplier offers):

    net_demand  →  internal allocation  →  residual gap  →  supplier sourcing

and returns the explicit QUANTITY LEDGER (§20) — every distinct quantity modelled
separately, never one generic `qty` — plus a human-readable reason list (§19). It computes
nothing itself beyond wiring: every number traces to an authoritative engine.

This phase PROPOSES only. Persisting a recommendation as a case, and executing transfers /
purchase orders, come in later phases through the existing gated channels.
"""
from __future__ import annotations

from .demand import net_demand
from .allocation import allocate_internal, network_internal_cover
from .sourcing import supplier_options


def _round(v, n=3):
    return round(float(v or 0), n)


def recommend(item_id, *, branch_id=None, availability_lines=None, live=False) -> dict:
    """Full sourcing recommendation for one item. Read-only; proposes nothing to SOFTECH.
    ``live=True`` revalidates internal surplus against live stock (execution time, §31)."""
    item_id = int(item_id)
    availability_lines = list(availability_lines or [])

    # 1. Net demand (authoritative gap ∨ uncovered ledger). `required` is ALREADY net of
    #    on-hand stock and in-transit — do NOT subtract incoming again below.
    nd = net_demand(item_id, branch_id=branch_id)
    required = nd['required']

    # 2. Internal allocation (branch-scoped only — a transfer needs a destination).
    if branch_id is not None:
        alloc = allocate_internal(item_id, required, to_branch_id=branch_id, live=live)
    else:
        # Company scope (e.g. a supplier's availability offer): stock ABOVE target at
        # over-stocked branches covers deficits elsewhere before anything is bought (§9).
        # No single destination, so no concrete transfers — the per-branch cases carry those.
        cover = network_internal_cover(item_id)
        internal = min(required, cover['overstock'])
        alloc = {
            'need': required,
            'internally_allocated': round(internal, 3),
            'total_surplus_available': cover['overstock'],
            'transfers': [],
            'donors': cover['donors'],
            'fully_covered_internally': required > 0 and internal >= required,
            'scope': 'network',
        }

    return _assemble(item_id, nd, alloc, availability_lines, branch_id)


def _assemble(item_id, nd, alloc, availability_lines, branch_id, extra=None) -> dict:
    """Shared tail: internal allocation → residual gap → sourcing → explicit ledger."""
    required = nd['required']
    incoming = nd['confirmed_incoming']        # informational only (already netted)
    internally_allocated = alloc['internally_allocated']

    # 3. Residual external procurement gap (required is already net of stock + in-transit).
    residual_gap = max(0.0, required - internally_allocated)
    proposed_purchase = residual_gap    # before MOQ / pack rounding (applied at order time)

    # 4. Supplier sourcing for the residual.
    src = supplier_options(item_id, residual_gap, availability_lines=availability_lines)

    supplier_offered = sum(float(l.supplier_qty) for l in availability_lines
                           if l.supplier_qty is not None) or None

    # 5. The explicit quantity ledger (§20) — distinct quantities, never overloaded.
    ledger = {
        'supplier_offered':     supplier_offered,
        'calculated_demand':    _round(nd['calculated_demand']),
        'ledger_demand':        _round(nd['ledger_demand']),
        'ledger_need':          _round(nd['ledger_need']),
        'gross_requirement':    _round(nd['gross_requirement']),
        'pending_internal_in':  _round(nd['pending_internal_in']),
        'pending_orders':       _round(nd['pending_orders']),
        'required':             _round(required),
        'customer_demand':      _round(nd['customer_demand']),
        'branch_request':       _round(nd['branch_request']),
        'current_stock':        _round(nd['current_stock']),
        'confirmed_incoming':   _round(incoming),
        'transferable_surplus': _round(alloc['total_surplus_available']),
        'internally_allocated': _round(internally_allocated),
        'residual_gap':         _round(residual_gap),
        'proposed_purchase':    _round(proposed_purchase),
        # filled in later phases:
        'approved_purchase':    None,
        'confirmed_supplier':   None,
        'received':             None,
        'unfulfilled':          None,
    }

    out = {
        'item_id': item_id,
        'branch_id': branch_id,
        'quantity_ledger': ledger,
        'net_demand': nd,
        'allocation': alloc,
        'sourcing': src,
        'scarcity': _scarcity(nd, ledger),
        'reasons': _reasons(nd, ledger, alloc, src),
        'has_run': nd['has_run'],
    }
    if extra:
        out.update(extra)
    return out


def _scarcity(nd, ledger) -> dict:
    """A light scarcity flag — NOT raw sales volume (§15). A zero-stock item with a waiting
    customer and a real residual gap is high priority even if it sells slowly."""
    zero_stock = ledger['current_stock'] <= 0
    waiting_customer = nd['customer_demand'] > 0
    in_market_shortage = nd['statistical'] > 0
    residual = ledger['residual_gap'] > 0
    score = sum([zero_stock, waiting_customer, in_market_shortage, residual])
    return {
        'score': score,
        'zero_stock': zero_stock,
        'waiting_customer': waiting_customer,
        'in_market_shortage': in_market_shortage,
        'has_residual_gap': residual,
        'urgent': zero_stock and (waiting_customer or in_market_shortage),
    }


def _reasons(nd, ledger, alloc, src) -> list:
    """Human-readable justification for the recommendation (§19)."""
    r = []
    r.append(f"الاحتياج {ledger['gross_requirement']:.1f} = "
             f"أكبر من (فجوة المحرك {ledger['calculated_demand']:.1f}، "
             f"طلبات غير مغطاة {ledger['ledger_need']:.1f} من {ledger['ledger_demand']:.1f})")
    if ledger['pending_internal_in'] or ledger['pending_orders']:
        r.append(f"مُخصوم ما هو قيد التنفيذ: تحويلات واردة {ledger['pending_internal_in']:.1f} "
                 f"+ طلبات شراء مفتوحة {ledger['pending_orders']:.1f} "
                 f"→ الصافي {ledger['required']:.1f}")
    r.append(f"الرصيد الحالي {ledger['current_stock']:.1f}"
             + (f" + بالطريق {ledger['confirmed_incoming']:.1f} (محسوب مسبقاً)"
                if ledger['confirmed_incoming'] else ''))
    if ledger['internally_allocated']:
        r.append(f"تحويل داخلي {ledger['internally_allocated']:.1f} من "
                 f"{len(alloc['transfers'])} فرع (فائض متاح {ledger['transferable_surplus']:.1f})")
    elif ledger['transferable_surplus']:
        r.append(f"فائض داخلي متاح {ledger['transferable_surplus']:.1f}")
    r.append(f"فجوة الشراء الخارجي {ledger['residual_gap']:.1f}")
    if src.get('best'):
        b = src['best']
        r.append(f"أفضل مصدر: {b.get('supplier_name') or b.get('supplier_code') or '—'} "
                 f"بتكلفة فعلية {b['effective_cost']:.2f}")
    if src.get('better_historical_deal'):
        h = src['better_historical_deal']
        r.append(f"⚠ صفقة تاريخية أفضل: {h['effective_cost']:.2f} "
                 f"(الحالي أعلى بـ {h['gap_pct']:.0f}%)")
    if nd['double_count_avoided']:
        r.append(f"مُنع ازدواج طلب بمقدار {nd['double_count_avoided']:.1f}")
    return r


# ── A SET of branches (a supplier that delivers only near some branches) ─────────
_SUM_KEYS = ('required', 'gross_requirement', 'pending_internal_in', 'pending_orders',
             'calculated_demand', 'ledger_demand', 'ledger_need', 'customer_demand',
             'branch_request', 'current_stock', 'confirmed_incoming', 'double_count_avoided')


def demand_for_branches(item_ids, branch_ids) -> dict:
    """{item_id: {branch_id: net_demand}} — batched per branch (each branch's own figures)."""
    from .demand import net_demand_many
    out: dict = {int(i): {} for i in item_ids}
    for b in branch_ids:
        for iid, nd in net_demand_many(item_ids, branch_id=int(b)).items():
            out[iid][int(b)] = nd
    return out


def recommend_for_branches(item_id, branch_ids, *, per_branch=None, availability_lines=None) -> dict:
    """recommend() for a chosen SET of branches (e.g. a medical warehouse that delivers only
    to Abbasia and Ramsis). The need is the SUM of each chosen branch's own net demand;
    internal cover comes from any branch's transferable surplus (stock − safety − already
    claimed) — never from a chosen branch that itself needs the item. Same ledger, same
    sourcing as recommend(); `branches` adds the per-branch breakdown."""
    from .allocation import transferable_surplus
    item_id = int(item_id)
    branch_ids = [int(b) for b in branch_ids]
    availability_lines = list(availability_lines or [])
    per = per_branch if per_branch is not None else demand_for_branches([item_id], branch_ids)[item_id]

    nd = {k: sum(float(per[b][k] or 0) for b in branch_ids) for k in _SUM_KEYS}
    nd.update(item_id=item_id, branch_id=None, branch_ids=branch_ids,
              statistical=max((float(per[b]['statistical'] or 0) for b in branch_ids), default=0.0),
              has_run=any(per[b]['has_run'] for b in branch_ids),
              provenance=[p for b in branch_ids for p in per[b]['provenance']])

    needing = {b for b in branch_ids if per[b]['required'] > 0}
    donors = [s for s in transferable_surplus(item_id) if s['branch_id'] not in needing]
    surplus = sum(s['surplus'] for s in donors)
    internal = min(nd['required'], surplus)
    alloc = {
        'need': nd['required'],
        'internally_allocated': round(internal, 3),
        'total_surplus_available': round(surplus, 3),
        'transfers': [],
        'donors': [{'branch_id': s['branch_id'], 'branch_name': s['branch_name'],
                    'over_target': s['surplus']} for s in donors],
        'fully_covered_internally': nd['required'] > 0 and internal >= nd['required'],
        'scope': 'branches',
    }
    breakdown = [{'branch_id': b, 'required': round(per[b]['required'], 3),
                  'current_stock': round(per[b]['current_stock'], 3),
                  'customer_demand': round(per[b]['customer_demand'], 3)} for b in branch_ids]
    return _assemble(item_id, nd, alloc, availability_lines, None, extra={'branches': breakdown})
