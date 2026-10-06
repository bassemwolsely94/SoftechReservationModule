"""
apps/supply/execution.py — turning approved recommendations into actions (doc 24 Phase 5).

Owner decisions (2026-09-27):
  1. Approving an internal allocation creates DRAFT TransferRequests. The transfers team
     submits / approves / sends to ERP in their normal flow — this module never skips it.
  2. External purchasing produces a WhatsApp / Excel ORDER LIST only. ISR generation stays
     OFF until validated against real data.
Nothing here writes to SOFTECH.

Safety rails on every consequential action (§31 / §32 / §40):
  • idempotency key — a retried or double-clicked submission replays the first result
  • per-item serialization — a transaction-scoped Postgres advisory lock, so two approvals
    for the same item can never both draw the same branch surplus
  • live revalidation — surplus is re-checked against LIVE stock minus what open transfer
    drafts already claim; a stale plan is rejected, not silently executed
  • overrides — a decision that deviates from the recommendation is flagged, and one that
    moves or buys MORE than the recommendation requires a reason
  • all-or-nothing — an order list is validated in full before any line is recorded
"""
from __future__ import annotations

import logging
import uuid

from django.db import IntegrityError, connection, transaction

from . import cases as case_svc
from .engine import recommend
from .engine.allocation import transferable_surplus
from .engine.sourcing import effective_unit_cost
from .models import AvailabilityBatch, AvailabilityLine, SupplyCase, SupplyDecision

logger = logging.getLogger('elrezeiky.supply')

_LOCK_NAMESPACE = 24024        # doc 24 — namespaces our advisory locks
_TOL = 0.001


class ExecutionError(ValueError):
    pass


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _lock_item(item_id):
    """Serialize all supply execution for one item until the transaction ends."""
    with connection.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s, %s)', [_LOCK_NAMESPACE, int(item_id)])


def _audit(action, obj, *, staff=None, changes=None, note='', extra=None, request=None):
    try:
        from apps.audit.models import AuditLog
        AuditLog.log(action, user=staff, obj=obj, changes=changes,
                     note=(note or '')[:255], extra=extra, request=request)
    except Exception:
        logger.warning('supply execution audit failed for %s', getattr(obj, 'pk', None))


def _exceeds_need(qty, recommended) -> bool:
    """Buying up to the next WHOLE unit above the need is normal ordering (you can't buy
    3.67 boxes) — only quantities beyond that count as buying more than needed."""
    import math
    allowed = math.ceil(max(0.0, _f(recommended)) - 1e-9)
    return _f(qty) > allowed + _TOL


def _is_override(qty, recommended) -> bool:
    """Deviation from the recommendation: more than the rounded-up need, or less than it."""
    return _exceeds_need(qty, recommended) or _f(qty) < _f(recommended) - _TOL


def _qty_text(q) -> str:
    q = _f(q)
    return str(int(q)) if abs(q - round(q)) < _TOL else f'{q:.2f}'.rstrip('0').rstrip('.')


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Internal transfer → DRAFT TransferRequest(s)
# ═══════════════════════════════════════════════════════════════════════════════

def approve_internal_transfer(case, *, idempotency_key, staff=None, transfers=None,
                              reason='', request=None) -> dict:
    """Approve a case's internal allocation → one DRAFT TransferRequest per source branch.

    ``transfers`` (optional) overrides the plan: [{'from_branch_id', 'qty'}]. Without it the
    LIVE recommendation is used. Returns {'decision', 'transfer_requests', 'replayed'}."""
    key = (idempotency_key or '').strip()
    if not key:
        raise ExecutionError('مفتاح منع التكرار (idempotency_key) مطلوب.')
    reason = (reason or '').strip()

    with transaction.atomic():
        _lock_item(case.item_id)

        # Idempotency — checked INSIDE the item lock so a concurrent retry sees the first.
        prior = SupplyDecision.objects.filter(idempotency_key=key).first()
        if prior is not None:
            return {'decision': prior, 'transfer_requests': _trs(prior), 'replayed': True}

        case = SupplyCase.objects.select_for_update().get(pk=case.pk)
        if not case.is_open:
            raise ExecutionError('الحالة مغلقة — لا يمكن اعتماد تحويل لها.')
        if case.branch_id is None:
            raise ExecutionError('حالة على مستوى الشبكة ليس لها فرع مستلم — لا يمكن إنشاء تحويل.')

        # Live revalidation: need + surplus right now (live stock − open-draft claims).
        live = recommend(case.item_id, branch_id=case.branch_id, live=True)
        live_plan = {t['from_branch_id']: t['qty'] for t in live['allocation']['transfers']}
        recommended_total = sum(live_plan.values())
        available = {s['branch_id']: s for s in
                     transferable_surplus(case.item_id, exclude_branch_id=case.branch_id, live=True)}

        if transfers is None:
            plan = dict(live_plan)
        else:
            plan = {}
            for t in transfers:
                src, qty = int(t['from_branch_id']), _f(t.get('qty'))
                if qty <= 0:
                    continue
                if src == case.branch_id:
                    raise ExecutionError('لا يمكن التحويل من الفرع إلى نفسه.')
                src_avail = _f((available.get(src) or {}).get('surplus'))
                if qty > src_avail + _TOL:
                    raise ExecutionError(
                        f'الفائض تغيّر: المتاح الآن من الفرع {src} هو {src_avail:.1f} فقط '
                        f'(بعد حجوزات التحويلات المفتوحة ورصيد الأمان).')
                plan[src] = plan.get(src, 0.0) + qty

        decided_total = sum(plan.values())
        if decided_total < _TOL:
            raise ExecutionError('لا يوجد فائض قابل للتحويل الآن — راجع الحالة (البيانات تغيّرت).')

        is_override = (set(plan) != set(live_plan)
                       or any(abs(plan[b] - live_plan.get(b, 0.0)) > _TOL for b in plan))
        if is_override and decided_total > recommended_total + _TOL and not reason:
            raise ExecutionError('تحويل كمية أكبر من التوصية يتطلب ذكر السبب.')

        from apps.transfers.models import TransferRequest, TransferRequestItem, TransferRequestMessage
        trs = []
        for src, qty in sorted(plan.items()):
            tr = TransferRequest.objects.create(
                requesting_branch_id=case.branch_id, supplying_branch_id=src,
                status='draft', created_by=staff,
                notes=(f'مسودة من التوريد الذكي — حالة نقص #{case.pk}'
                       + (f' — {reason}' if reason else '')),
            )
            TransferRequestItem.objects.create(
                request=tr, item_id=case.item_id, quantity=round(qty, 3),
                notes=f'حالة نقص #{case.pk}')
            TransferRequestMessage.log_system(
                tr, f'أُنشئت المسودة من وحدة التوريد الذكي (حالة #{case.pk}) — '
                    f'بانتظار تقديمها واعتمادها في مسار التحويلات المعتاد.')
            trs.append(tr)

        try:
            decision = SupplyDecision.objects.create(
                kind=SupplyDecision.KIND_INTERNAL_TRANSFER, case=case,
                item_id=case.item_id, branch_id=case.branch_id,
                recommended_qty=round(recommended_total, 3), decided_qty=round(decided_total, 3),
                is_override=is_override, override_reason=reason[:255],
                recommendation_snapshot=case.last_ledger or {},
                revalidation={
                    'live_required': live['quantity_ledger']['required'],
                    'live_plan': {str(k): v for k, v in live_plan.items()},
                    'snapshot_internal': (case.last_ledger or {}).get('internally_allocated'),
                },
                result_refs={'transfer_requests': [t.pk for t in trs],
                             'request_numbers': [t.request_number for t in trs]},
                idempotency_key=key, created_by=staff,
            )
        except IntegrityError:     # a concurrent twin won the key — replay it
            raise ExecutionError('تم تنفيذ هذا الطلب بالفعل.')

        refs = dict(case.execution_refs or {})
        refs['transfer_requests'] = list(refs.get('transfer_requests', [])) + [t.pk for t in trs]
        case.execution_refs = refs
        case.save(update_fields=['execution_refs', 'updated_at'])

    if case.status != SupplyCase.STATUS_TRANSFER_PENDING and \
            SupplyCase.STATUS_TRANSFER_PENDING in case_svc.allowed_targets(case):
        case_svc.transition(case, SupplyCase.STATUS_TRANSFER_PENDING, staff=staff,
                            reason='اعتماد تحويل داخلي (مسودة)', request=request)

    _audit('supply_transfer_drafted', case, staff=staff, request=request,
           note=reason or 'approved recommendation',
           extra={'decision': decision.pk, 'transfer_requests': [t.request_number for t in trs],
                  'recommended_qty': recommended_total, 'decided_qty': decided_total,
                  'is_override': is_override})
    return {'decision': decision, 'transfer_requests': trs, 'replayed': False}


def _trs(decision):
    from apps.transfers.models import TransferRequest
    ids = (decision.result_refs or {}).get('transfer_requests', [])
    return list(TransferRequest.objects.filter(pk__in=ids))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. External purchase → WhatsApp / Excel order list (+ recorded decision)
# ═══════════════════════════════════════════════════════════════════════════════

_HEADERS = {'ar': 'مطلوب:', 'en': 'Required:'}


def _resolve_lines(lines) -> list:
    """Normalise request lines → [{'item', 'qty', 'branch_id', 'case', 'offer', 'reason'}]."""
    from apps.catalog.models import Item
    out = []
    for raw in lines or []:
        qty = _f(raw.get('qty'))
        if qty <= 0:
            continue
        offer = None
        if raw.get('availability_line_id'):
            offer = (AvailabilityLine.objects.select_related('batch', 'batch__supplier', 'item')
                     .filter(pk=raw['availability_line_id']).first())
        item_id = raw.get('item_id') or (offer.item_id if offer else None)
        if not item_id:
            raise ExecutionError('كل سطر يحتاج صنفاً مطابقاً (item_id) قبل الطلب.')
        try:
            item = Item.objects.get(pk=item_id)
        except Item.DoesNotExist:
            raise ExecutionError(f'الصنف {item_id} غير موجود.')
        case = None
        if raw.get('case_id'):
            case = SupplyCase.objects.filter(pk=raw['case_id']).first()
        branch_id = raw.get('branch_id', case.branch_id if case else None)
        out.append({'item': item, 'qty': qty, 'branch_id': branch_id, 'case': case,
                    'offer': offer, 'reason': (raw.get('reason') or '').strip()})
    if not out:
        raise ExecutionError('لا توجد أصناف بكمية أكبر من صفر.')
    return out


def build_order_text(resolved, *, lang='ar') -> str:
    """The copy-to-WhatsApp message: header + '<catalog name> — <qty>' per line (§17).
    Uses the clean catalog name (supplier item code appended when known)."""
    rows = [_HEADERS.get(lang, _HEADERS['ar'])]
    for ln in resolved:
        name = ' '.join((ln['item'].name or '').split())   # SOFTECH names carry runs of spaces
        code = (ln['offer'].supplier_item_code if ln['offer'] else '') or ''
        rows.append(f'{name}{f" [{code}]" if code else ""} — {_qty_text(ln["qty"])}')
    return '\n'.join(rows)


def preview_order(lines, *, lang='ar') -> dict:
    """Read-only preview: the WhatsApp text + each line vs the LIVE residual gap, so the
    operator sees which quantities exceed what we actually need before committing."""
    resolved = _resolve_lines(lines)
    rows = []
    for ln in resolved:
        live = recommend(ln['item'].id, branch_id=ln['branch_id'],
                         availability_lines=[ln['offer']] if ln['offer'] else None)
        residual = live['quantity_ledger']['residual_gap']
        price = _f(ln['offer'].price) if ln['offer'] and ln['offer'].price is not None else None
        rows.append({
            'item_id': ln['item'].id, 'item_name': ln['item'].name,
            'item_softech_id': ln['item'].softech_id, 'branch_id': ln['branch_id'],
            'qty': ln['qty'], 'recommended_qty': residual,
            'exceeds_need': _exceeds_need(ln['qty'], residual),
            'unit_price': price,
            'line_value': round(price * ln['qty'], 2) if price is not None else None,
        })
    return {'text': build_order_text(resolved, lang=lang), 'lines': rows,
            'total_qty': sum(r['qty'] for r in rows),
            'estimated_value': round(sum(r['line_value'] or 0 for r in rows), 2)}


def commit_order(lines, *, idempotency_key, supplier=None, supplier_name='', staff=None,
                 lang='ar', request=None) -> dict:
    """Record the order: one SupplyDecision per line (pending incoming), cases → ordered,
    source offers' batches → actioned. Validated in full first; all-or-nothing.
    Buying MORE than the live residual gap (or buying with no recorded need) needs a reason."""
    key = (idempotency_key or '').strip()
    if not key:
        raise ExecutionError('مفتاح منع التكرار (idempotency_key) مطلوب.')

    prior = list(SupplyDecision.objects.filter(order_ref=key).select_related('item'))
    if prior:
        return {'order_ref': key, 'decisions': prior, 'replayed': True,
                'text': _replay_text(prior, lang)}

    resolved = _resolve_lines(lines)
    touched_cases = []
    with transaction.atomic():
        for item_id in sorted({ln['item'].id for ln in resolved}):   # stable lock order
            _lock_item(item_id)
        if SupplyDecision.objects.filter(order_ref=key).exists():     # lost a race → replay
            prior = list(SupplyDecision.objects.filter(order_ref=key).select_related('item'))
            return {'order_ref': key, 'decisions': prior, 'replayed': True,
                    'text': _replay_text(prior, lang)}

        # Pass 1 — validate every line against the LIVE residual before writing anything.
        for ln in resolved:
            live = recommend(ln['item'].id, branch_id=ln['branch_id'],
                             availability_lines=[ln['offer']] if ln['offer'] else None)
            ln['live'] = live
            ln['recommended'] = live['quantity_ledger']['residual_gap']
            if _exceeds_need(ln['qty'], ln['recommended']) and not ln['reason']:
                raise ExecutionError(
                    f'«{ln["item"].name}»: الكمية {_qty_text(ln["qty"])} أكبر من الاحتياج الحالي '
                    f'{_qty_text(ln["recommended"])} — اذكر السبب لتجاوز التوصية.')
            if ln['case'] is None:
                ln['case'] = case_svc._open_case_qs(ln['item'].id, ln['branch_id']).first()

        # Pass 2 — record decisions (nothing reaches SOFTECH).
        decisions = []
        for i, ln in enumerate(resolved):
            offer = ln['offer']
            price = offer.price if offer else None
            foc = offer.foc_qty if offer else None
            eff = (effective_unit_cost(price, ln['qty'],
                                       (_f(foc) / _f(offer.supplier_qty) * ln['qty'])
                                       if (offer and offer.supplier_qty and foc) else 0)
                   if price is not None else None)
            sup = supplier or (offer.batch.supplier if offer and offer.batch.supplier_id else None)
            d = SupplyDecision.objects.create(
                kind=SupplyDecision.KIND_PURCHASE, case=ln['case'], item=ln['item'],
                branch_id=ln['branch_id'],
                recommended_qty=round(ln['recommended'], 3), decided_qty=round(ln['qty'], 3),
                is_override=_is_override(ln['qty'], ln['recommended']),
                override_reason=ln['reason'][:255],
                supplier=sup,
                supplier_name=(supplier_name or (sup.name if sup else '')
                               or (offer.batch.supplier_name if offer else '')),
                availability_line=offer, unit_price=price, foc_qty=foc, effective_cost=eff,
                receipt_status=SupplyDecision.RECEIPT_OPEN,
                recommendation_snapshot=ln['live']['quantity_ledger'],
                order_ref=key, idempotency_key=f'{key}:{i}', created_by=staff,
            )
            decisions.append(d)

            if ln['case'] is not None:
                c = ln['case']
                refs = dict(c.execution_refs or {})
                refs['orders'] = list(refs.get('orders', [])) + [key]
                ledger = dict(c.last_ledger or {})
                ledger['approved_purchase'] = _f(ledger.get('approved_purchase')) + ln['qty']
                c.execution_refs, c.last_ledger = refs, ledger
                c.save(update_fields=['execution_refs', 'last_ledger', 'updated_at'])
                touched_cases.append(c)

            if offer is not None and offer.batch.status in (AvailabilityBatch.STATUS_OPEN,
                                                             AvailabilityBatch.STATUS_REVIEWED):
                AvailabilityBatch.objects.filter(pk=offer.batch_id).update(
                    status=AvailabilityBatch.STATUS_ACTIONED)

    for c in {c.pk: c for c in touched_cases}.values():
        c.refresh_from_db()
        if c.status != SupplyCase.STATUS_ORDERED and \
                SupplyCase.STATUS_ORDERED in case_svc.allowed_targets(c):
            case_svc.transition(c, SupplyCase.STATUS_ORDERED, staff=staff,
                                reason=f'طلب شراء {key}', request=request)

    for d in decisions:
        _audit('supply_purchase_ordered', d, staff=staff, request=request,
               note=d.override_reason or f'order {key}',
               extra={'order_ref': key, 'item': d.item_id, 'recommended_qty': _f(d.recommended_qty),
                      'decided_qty': _f(d.decided_qty), 'is_override': d.is_override,
                      'supplier': d.supplier_name})
    return {'order_ref': key, 'decisions': decisions, 'replayed': False,
            'text': build_order_text(resolved, lang=lang)}


def _replay_text(decisions, lang) -> str:
    rows = [_HEADERS.get(lang, _HEADERS['ar'])]
    for d in decisions:
        rows.append(f'{" ".join((d.item.name or "").split())} — {_qty_text(d.decided_qty)}')
    return '\n'.join(rows)


def close_open_orders_for_case(case, *, received: bool):
    """When a case is received / fulfilled (or cancelled), its open purchase decisions stop
    counting as pending incoming — otherwise they'd be subtracted again after stock lands."""
    status = SupplyDecision.RECEIPT_RECEIVED if received else SupplyDecision.RECEIPT_CANCELLED
    return (SupplyDecision.objects
            .filter(case=case, kind=SupplyDecision.KIND_PURCHASE,
                    receipt_status=SupplyDecision.RECEIPT_OPEN)
            .update(receipt_status=status))


def new_idempotency_key() -> str:
    return uuid.uuid4().hex


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Excel order sheet (reuses the shortage export's house style)
# ═══════════════════════════════════════════════════════════════════════════════

def export_order_excel(lines, *, supplier_name='') -> bytes:
    import io
    from datetime import datetime
    import openpyxl
    from apps.shortage.export import (_header_row, _set_col_widths, _style,
                                      _NORMAL_FONT, _RTL_ALIGN, _CENTER_ALIGN)

    preview = preview_order(lines)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'طلب شراء'
    ws.sheet_view.rightToLeft = True
    ws.cell(row=1, column=1,
            value=f'طلب شراء — {supplier_name or "مورد"} — {datetime.now():%Y-%m-%d %H:%M}')
    _header_row(ws, 3, ['#', 'كود الصنف', 'الصنف', 'الكمية المطلوبة', 'الاحتياج الموصى به',
                        'السعر', 'القيمة'])
    for i, r in enumerate(preview['lines'], start=1):
        row = 3 + i
        vals = [i, r['item_softech_id'], r['item_name'], r['qty'], r['recommended_qty'],
                r['unit_price'], r['line_value']]
        for col, v in enumerate(vals, start=1):
            _style(ws.cell(row=row, column=col, value=v), font=_NORMAL_FONT,
                   align=_RTL_ALIGN if col == 3 else _CENTER_ALIGN)
    _set_col_widths(ws, [5, 12, 45, 14, 16, 10, 12])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
