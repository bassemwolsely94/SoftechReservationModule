"""Recording what the portal robot saw: availability checks (dry run) and placed orders.

record_check  — a clean dry run: each PortalLine gets the site's answer (accepted qty, status,
                price, discount, bonus, expiry, message) and its flags (short_expiry, price_jump;
                shown, never acted on), and the checked lines become one AvailabilityBatch
                (source portal). Nothing is ordered.
record_order  — an order number was read: the quantities Order History shows are recorded once
                through commit_order (key `portal-basket-<pk>`), the buy list gets the rest back
                as a remainder, and the difference from the handed-over cart is kept on the basket.

What stops an order being recorded twice:
  • the basket row is locked, and only a `submitted` basket is recorded; a `recorded` one with the
    same order number is returned unchanged, with another number it goes to a person (409);
  • commit_order replays on its key, and a replay whose quantities differ is refused;
  • a buy line already credited with this basket (its `tried` names the basket) is not credited
    again;
  • the portal's order number (`portal_key`) is unique, so one order never sits on two baskets;
  • empty Order History lines never mean "everything was removed": that needs a person; and
    History rows the basket cannot account for (a code not in it, an unreadable code or qty)
    send it to a person before anything is recorded or handed back as a remainder.

Nothing here writes SOFTECH.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.rpa.models import BuyList, BuyListLine, PortalBasket, PortalJob
from apps.rpa.portal.skus import canonical_sku, vendor_for

SUPPLIER_NAME = 'فارما أوفرسيز'
# a basket in one of these will not change again: when all of a job's baskets are, the job is done
TERMINAL = ('dry_run_ok', 'recorded', 'cancelled')
_ANSWER_STATUSES = ('ok', 'short', 'out', 'not_found', 'removed')


class RecordError(ValueError):
    """The order cannot be recorded as reported; a person decides (409)."""
    status_code = 409


def _audit(action, obj, *, user, old=None, new=None, note=''):
    AuditLog.log(action, user=user, obj=obj, old_data=old, new_data=new, note=str(note)[:255])


# ── parsing the robot's answers ──────────────────────────────────────────────────────────────

def _decimal(v):
    if v is None or v == '':
        return None
    try:
        d = Decimal(str(v).replace(',', '').strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _date(v):
    """'YYYY-MM-DD', or 'YYYY-MM' (the 1st of that month: the earlier date flags sooner)."""
    s = str(v or '').strip()[:10]
    if not s:
        return None
    try:
        return date.fromisoformat(s if len(s) == 10 else f'{s[:7]}-01')
    except ValueError:
        return None


def _add_months(d, months):
    from dateutil.relativedelta import relativedelta
    return d + relativedelta(months=months)


def _last_costs(items):
    """{item_code: unit_cost} — the most recent purchase cost from any supplier."""
    from apps.supply.comparison import purchase_history
    latest = {}
    for (code, _supplier), h in purchase_history({i.softech_id for i in items}).items():
        last = h.get('last')
        if last and last.get('unit_cost') and (code not in latest or last['date'] > latest[code]['date']):
            latest[code] = last
    return {code: Decimal(str(rec['unit_cost'])) for code, rec in latest.items()}


def _flags(line, portal, last_cost, today):
    flags = []
    if line.supplier_expiry and line.supplier_expiry < _add_months(today, portal.short_expiry_months):
        flags.append('short_expiry')
    if line.price is not None and last_cost and last_cost > 0:
        net = line.price * (1 - (line.discount_pct or 0) / Decimal('100'))
        if net >= last_cost * (1 + Decimal(str(portal.price_jump_pct)) / Decimal('100')):
            flags.append('price_jump')
    return flags


def _save_answer(line, row):
    try:
        qty = int(row.get('accepted_qty'))
    except (TypeError, ValueError):
        qty = None
    if qty is not None and qty >= 0:
        line.accepted_qty = qty
    if row.get('status') in _ANSWER_STATUSES:
        line.status = row['status']
    line.price = _decimal(row.get('price'))
    line.discount_pct = _decimal(row.get('discount_pct'))
    line.bonus_text = str(row.get('bonus_text') or '')[:120]
    line.supplier_expiry = _date(row.get('supplier_expiry'))
    line.message = str(row.get('message') or '')[:255]
    if row.get('supplier_name_seen'):
        line.supplier_name_seen = str(row['supplier_name_seen'])[:255]


def _signals(status):
    return {'short': ['short'], 'out': ['out_of_stock']}.get(status, [])


# ── record_check ─────────────────────────────────────────────────────────────────────────────

def record_check(basket, lines_payload):
    """A dry run ended clean. Saves each line's answer and flags, writes one portal
    AvailabilityBatch (one line per checked item), and marks the basket dry_run_ok."""
    from apps.supply.models import AvailabilityBatch, AvailabilityLine
    with transaction.atomic():
        b = PortalBasket.objects.select_for_update().select_related('job__portal').get(pk=basket.pk)
        if b.status != 'in_progress':
            raise RecordError('السلة ليست قيد التنفيذ')
        portal = b.job.portal
        vendor = vendor_for(portal)
        mine = {ln.pk: ln for ln in b.lines.select_related('item')}
        rows = [(mine[r['line_id']], r) for r in lines_payload or []
                if isinstance(r, dict) and r.get('line_id') in mine]
        costs = _last_costs([ln.item for ln, _ in rows])
        today = timezone.localdate()
        batch = AvailabilityBatch.objects.create(
            supplier=vendor, supplier_name=vendor.name, source=AvailabilityBatch.SOURCE_PORTAL,
            notes=f'portal check basket {b.pk}')
        seen = set()
        for line, row in rows:
            if line.pk in seen:
                continue
            seen.add(line.pk)
            _save_answer(line, row)
            line.flags = _flags(line, portal, costs.get(line.item.softech_id), today)
            av = AvailabilityLine.objects.create(
                batch=batch, raw_text=(line.supplier_name_seen or line.item.name or '')[:300],
                item=line.item, supplier_qty=line.accepted_qty, price=line.price,
                discount_pct=line.discount_pct,
                expiry=(line.supplier_expiry.isoformat() if line.supplier_expiry
                        else str(row.get('supplier_expiry') or '')[:20]),
                supplier_item_code=line.supplier_key, signals=_signals(line.status),
                notes=line.bonus_text[:300],
                match_reason={'portal_line_id': line.pk, 'basket_id': b.pk, 'job_id': b.job_id})
            line.availability_line = av
            line.save(update_fields=['accepted_qty', 'status', 'price', 'discount_pct', 'bonus_text',
                                     'supplier_expiry', 'message', 'supplier_name_seen', 'flags',
                                     'availability_line'])
        b.status = 'dry_run_ok'
        b.save(update_fields=['status'])
        finish_job_if_done(b.job_id, staff=None)
    return batch


# ── record_order ─────────────────────────────────────────────────────────────────────────────

def parse_qty(v):
    """A whole, non-negative quantity (4, '4', '4.000', 4.0 → 4), else None. Never truncates:
    2.5 or 'four' is None."""
    if isinstance(v, bool):
        return None
    d = _decimal(v)
    if d is None or d < 0 or d != d.to_integral_value():
        return None
    return int(d)


def _history_map(history_lines):
    """({canonical sku: qty}, [rows a person must read]). A row with qty 0 is dropped; a row
    whose sku is not a supplier code or whose qty is not a whole number is kept aside, never
    taken as "not ordered"."""
    out, unreadable = {}, []
    for row in history_lines or []:
        if not isinstance(row, dict):
            unreadable.append({'sku': '', 'qty': str(row)[:20]})
            continue
        qty = parse_qty(row.get('qty'))
        if qty == 0:
            continue
        sku = canonical_sku(row.get('sku'))
        if sku and qty is not None:
            out[sku] = out.get(sku, 0) + qty
        else:
            unreadable.append({'sku': str(row.get('sku') or '')[:40],
                               'qty': qty if qty is not None else str(row.get('qty'))[:20]})
    return out, unreadable


def _needs_person(b, reason, *, staff, now, note='', extra=None):
    old = {'status': b.status, 'needs_person_reason': b.needs_person_reason}
    b.status = 'needs_person'
    b.needs_person_reason = str(reason)[:255]
    b.needs_person_at = now
    b.lease_until = None
    b.save(update_fields=['status', 'needs_person_reason', 'needs_person_at', 'lease_until'])
    _audit('rpa_portal_needs_person', b, user=staff, old=old,
           new={'status': b.status, 'needs_person_reason': b.needs_person_reason, **(extra or {})},
           note=note or f'basket {b.pk}: {b.needs_person_reason}')


def record_order(basket, *, order_ref: str, history_lines: list, staff):
    """Record the order the robot (or a person) read for this `submitted` basket. See the module
    docstring. Raises RecordError when it cannot be recorded as reported."""
    ref = str(order_ref or '').strip()[:60]
    if not ref:
        raise RecordError('رقم الطلب مطلوب')
    with transaction.atomic():
        b = (PortalBasket.objects.select_for_update().select_related('job__portal', 'job__account')
             .get(pk=basket.pk))
        if b.status == 'recorded':
            if b.portal_ref == ref:
                return b
            _needs_person(b, f'order_ref_conflict:{b.portal_ref}/{ref}', staff=staff, now=timezone.now())
        elif b.status != 'submitted':
            raise RecordError('السلة ليست في انتظار التسجيل')
        else:
            return _record(b, ref, history_lines, staff)
    # the conflict is committed (needs_person) before raising; a caller's own rollback undoes it
    raise RecordError(f'السلة مسجلة بالفعل برقم الطلب {b.portal_ref}، وليس {ref}')


def _record(b, ref, history_lines, staff):
    from apps.branches.models import Branch, hq_code
    from apps.supply.execution import ExecutionError, commit_order
    from apps.supply.models import SupplyDecision
    now = timezone.now()
    job, portal, account = b.job, b.job.portal, b.job.account
    PortalJob.objects.select_for_update().get(pk=job.pk)       # lock order: basket, job, list, lines
    BuyList.objects.select_for_update().get(pk=job.buylist_id)

    history, unreadable = _history_map(history_lines)
    if not history and not unreadable:
        raise RecordError('لا توجد أسطر من سجل الطلبات — راجع الطلب في الموقع قبل التسجيل')
    portal_key = f'{portal.key}:{ref}'
    other = PortalBasket.objects.filter(portal_key=portal_key).exclude(pk=b.pk).values_list('pk', flat=True).first()
    if other:
        raise RecordError(f'رقم الطلب {ref} مسجل على سلة أخرى ({other})')

    lines = list(b.lines.select_related('item', 'buyline').order_by('pk'))
    by_sku = {}
    for ln in lines:
        if ln.supplier_key:
            if ln.supplier_key in by_sku:
                raise RecordError(f'كود المورد {ln.supplier_key} مكرر في السلة')
            by_sku[ln.supplier_key] = ln

    diff = {'added': [], 'removed': [], 'qty_changed': []}
    recorded = {}                                   # PortalLine pk -> recorded qty
    for sku, ln in by_sku.items():
        handed, rec = ln.accepted_qty or 0, history.get(sku, 0)
        recorded[ln.pk] = rec
        if handed > 0 and rec == 0:
            diff['removed'].append({'line_id': ln.pk, 'item_id': ln.item_id, 'sku': sku, 'qty': handed})
        elif rec != handed:
            diff['qty_changed'].append({'line_id': ln.pk, 'item_id': ln.item_id, 'sku': sku,
                                        'handed_over': handed, 'recorded': rec})
    diff['added'] = [{'sku': sku, 'qty': qty} for sku, qty in history.items() if sku not in by_sku] + unreadable

    hq = Branch.objects.get(softech_branch_id=hq_code())
    order = [{'item_id': ln.item_id, 'qty': recorded[ln.pk], 'branch_id': hq.pk,
              'reason': ln.buyline.reason} for ln in by_sku.values() if recorded[ln.pk] > 0]
    key = f'portal-basket-{b.pk}'
    prior = {d.item_id: d.decided_qty for d in SupplyDecision.objects.filter(order_ref=key)}
    if prior and prior != {o['item_id']: Decimal(o['qty']) for o in order}:
        raise RecordError('الطلب مسجل من قبل بكميات مختلفة — راجع السجل')

    b.portal_ref, b.portal_key, b.diff = ref, portal_key, diff
    if diff['added']:
        # Order History holds rows this basket cannot account for (a code not in the basket, an
        # unreadable code or qty). Nothing is recorded until a person reconciles them (link_order
        # with corrected lines): an unmatched basket line may really have been ordered under
        # another code, and handing it back as a remainder would order it twice. Nothing is
        # committed either, so the reconciled lines are recorded once, by one commit_order.
        b.save(update_fields=['portal_ref', 'portal_key', 'diff'])
        _needs_person(b, f'history_unmatched:{ref}', staff=staff, now=now, extra={'diff': diff})
        return b
    decisions, replayed = [], bool(prior)
    if order:
        try:
            with transaction.atomic():
                res = commit_order(order, idempotency_key=key, supplier=vendor_for(portal),
                                   supplier_name=SUPPLIER_NAME, staff=staff)
        except ExecutionError as exc:
            # the order WAS placed on the site: keep its number, a person settles the need check
            b.save(update_fields=['portal_ref', 'portal_key', 'diff'])
            _needs_person(b, f'need_check:{ref}', staff=staff, now=now,
                          note=f'basket {b.pk}: need check — {exc}')
            return b
        decisions, replayed = res['decisions'], res['replayed']
        refs = {'account': account.label, 'order_ref': ref, 'basket': b.pk}
        for d in decisions:
            if (d.result_refs or {}).get('portal') != refs:
                d.result_refs = {**(d.result_refs or {}), 'portal': refs}
                d.save(update_fields=['result_refs'])

    _apply_results(b, lines, recorded, portal.supplier_code)
    removed = [r['line_id'] for r in diff['removed']]
    if removed:
        b.lines.filter(pk__in=removed).update(status='removed')

    old = {'status': b.status}
    b.order_ref = key
    b.status = 'recorded'
    b.save(update_fields=['portal_ref', 'portal_key', 'order_ref', 'diff', 'status'])
    _audit('rpa_portal_basket_recorded', b, user=staff, old=old,
           new={'status': b.status, 'portal_ref': ref, 'order_ref': key, 'account': account.label,
                'decisions': len(decisions), 'replayed': replayed, 'diff': diff},
           note=f'basket {b.pk}: order {ref}')
    finish_job_if_done(job.pk, staff=staff)
    return b


def _apply_results(b, lines, recorded, supplier_code):
    """apply_result once per buy line for this basket: the recorded qty, 0 for the rest."""
    from apps.rpa.portal.buylist import apply_result
    locked = {bl.pk: bl for bl in BuyListLine.objects.select_for_update()
              .filter(pk__in=[ln.buyline_id for ln in lines]).order_by('pk')}
    for ln in lines:
        bl = locked[ln.buyline_id]
        if any(isinstance(t, dict) and t.get('basket') == b.pk for t in bl.tried or []):
            continue                                # already credited with this basket
        apply_result(bl, supplier_code=supplier_code, accepted=recorded.get(ln.pk, 0), basket_id=b.pk)


# ── job and list close-out ───────────────────────────────────────────────────────────────────

def finish_job_if_done(job_id, *, staff):
    """approved → done when every basket is terminal; then close the buy list when nothing is
    left to order and no other job is live on it (its lines leave the open-list guard)."""
    with transaction.atomic():
        job = PortalJob.objects.select_for_update().get(pk=job_id)
        if job.status != 'approved' or job.baskets.exclude(status__in=TERMINAL).exists():
            return job
        job.status = 'done'
        job.save(update_fields=['status'])
        _audit('rpa_portal_job_done', job, user=staff, old={'status': 'approved'},
               new={'status': 'done'}, note=f'job {job.pk}: every basket finished')
        bl = BuyList.objects.select_for_update().get(pk=job.buylist_id)
        if (bl.status == 'open' and not bl.lines.filter(remaining_qty__gt=0).exists()
                and not PortalJob.objects.filter(buylist=bl, status__in=('draft', 'approved')).exists()):
            bl.status = 'closed'
            bl.save(update_fields=['status'])
            bl.lines.update(open_guard=False)
            _audit('rpa_portal_buylist_closed', bl, user=staff, old={'status': 'open'},
                   new={'status': 'closed'}, note=f'buy list {bl.pk}: nothing left to order')
        return job
