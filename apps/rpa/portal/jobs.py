"""Portal jobs: create from a buy list, approve (need check + four-eyes), cut into baskets.

Nothing here writes SOFTECH. Portal jobs are company level: ordered for HQ.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.rpa.models import BuyList, BuyListLine, PortalBasket, PortalJob, PortalLine
from apps.rpa.portal.buylist import BuyListError, _audit


class JobError(ValueError):
    pass


def assert_line_not_frozen(line):
    """Approval freezes a line's qty/supplier. Called by buylist.pick (not by apply_result,
    which is how robot results come back)."""
    # Frozen only while the line is still pointed at the approved job's supplier; once the
    # robot's result clears chosen_supplier (a remainder) the buyer may re-pick it.
    if line.chosen_supplier and PortalLine.objects.filter(
            buyline_id=line.pk, basket__job__status='approved',
            basket__job__portal__supplier_code=line.chosen_supplier).exists():
        raise BuyListError('السطر داخل مهمة معتمدة — لا يمكن تعديله')


def _job_lines(job):
    return list(BuyListLine.objects.select_related('item').filter(
        buylist=job.buylist, chosen_supplier=str(job.portal.supplier_code),
        remaining_qty__gt=0).order_by('seq', 'pk'))


LIVE_STATUSES = ('draft', 'approved')


def _other_live_jobs(buylist, portal, exclude_pk=None, statuses=LIVE_STATUSES):
    qs = PortalJob.objects.filter(buylist=buylist, portal=portal, status__in=statuses)
    return qs.exclude(pk=exclude_pk) if exclude_pk else qs


def estimate_value(lines):
    """(value, unpriced_item_names): sum of qty x unit cost. Unit cost = the item's most recent
    purchase cost (comparison.purchase_history), else its public pack_price; an item with
    neither is unpriced (and adds nothing to the value)."""
    from apps.supply.comparison import purchase_history
    hist = purchase_history({ln.item.softech_id for ln in lines})
    latest = {}
    for (code, _supplier), h in hist.items():
        last = h.get('last')
        if last and (code not in latest or last['date'] > latest[code]['date']):
            latest[code] = last
    total = Decimal('0')
    unpriced = []
    for ln in lines:
        unit = None
        rec = latest.get(ln.item.softech_id)
        if rec and rec.get('unit_cost'):
            unit = Decimal(str(rec['unit_cost']))
        elif ln.item.pack_price:
            unit = Decimal(str(ln.item.pack_price))
        if unit is None or unit <= 0:
            unpriced.append(ln.item.name)
            continue
        total += unit * ln.remaining_qty
    return total, unpriced


def create_job(buylist, *, portal, account, staff):
    if not staff.can_do('rpa', 'create'):
        raise PermissionDenied('لا تملك صلاحية إنشاء مهام المواقع')
    if account.portal_id != portal.pk:
        raise JobError('الحساب لا يخص هذا الموقع')
    if not account.active:
        raise JobError('الحساب غير مفعل')
    if not (account.identity_text or '').strip():
        # the robot checks the logged-in account against this text: without it, any account passes
        raise JobError('اكتب اسم الحساب كما يظهر في الموقع قبل إنشاء مهمة')
    if buylist.status != 'open':
        raise JobError('القائمة مغلقة')
    if not buylist.lines.filter(chosen_supplier=str(portal.supplier_code), remaining_qty__gt=0).exists():
        raise JobError('لا توجد أسطر مختارة لهذا المورد')
    if _other_live_jobs(buylist, portal).exists():
        raise JobError('توجد مهمة أخرى لنفس القائمة والموقع — ألغِها أو أكملها أولا')
    job = PortalJob.objects.create(portal=portal, account=account, buylist=buylist,
                                   dry_run=not portal.live, created_by=staff)
    _audit('rpa_portal_job_created', job, staff=staff, note=f'{portal.key} list {buylist.pk}')
    return job


def _four_eyes_limit():
    from apps.config.models import SystemSetting
    row = SystemSetting.objects.filter(key='portal_four_eyes_above').first()
    if row is None or not (row.value or '').strip():
        return None
    try:
        return Decimal(row.value.strip())
    except Exception:
        return None


def approve_job(job, *, staff, reasons=None):
    from apps.branches.models import Branch, hq_code
    from apps.supply.execution import preview_order
    if not staff.can_do('rpa', 'create'):
        raise PermissionDenied('لا تملك صلاحية اعتماد مهام المواقع')
    reasons = {int(k): (v or '').strip() for k, v in (reasons or {}).items()}
    with transaction.atomic():
        job = PortalJob.objects.select_for_update().get(pk=job.pk)
        # Serialise approvals of the same buy list, then re-check nobody else holds these lines.
        BuyList.objects.select_for_update().get(pk=job.buylist_id)
        if job.status != 'draft':
            raise JobError('المهمة ليست مسودة')
        lines = _job_lines(job)
        if (_other_live_jobs(job.buylist, job.portal, exclude_pk=job.pk, statuses=('approved',)).exists()
                or PortalLine.objects.filter(
                    buyline__in=lines, basket__job__status='approved',
                    basket__job__portal=job.portal).exclude(basket__job=job).exists()):
            raise JobError('أسطر هذه المهمة داخل مهمة أخرى معتمدة')
        if not lines:
            raise JobError('لا توجد أسطر في المهمة')
        hq = Branch.objects.get(softech_branch_id=hq_code())
        prev = preview_order([{'item_id': ln.item_id, 'qty': ln.remaining_qty, 'branch_id': hq.pk}
                              for ln in lines])
        rows = {r['item_id']: r for r in prev['lines']}
        missing = [ln for ln in lines
                   if rows.get(ln.item_id, {}).get('exceeds_need') and not reasons.get(ln.pk)]
        if missing:
            names = '، '.join(ln.item.name for ln in missing)
            raise JobError(f'الكمية أكبر من الاحتياج الحالي — اذكر السبب: {names}')
        value, unpriced = estimate_value(lines)
        limit = _four_eyes_limit()
        if limit is not None and (value > limit or unpriced):   # unpriced line: fail safe
            if not staff.can_do('rpa', 'approve'):
                raise PermissionDenied('القيمة تتطلب اعتماد شخص مخوّل بالموافقة')
            if staff.pk == job.created_by_id:
                raise PermissionDenied('القيمة تتطلب اعتماد شخص آخر غير منشئ المهمة')
        for ln in lines:
            if reasons.get(ln.pk):
                ln.reason = reasons[ln.pk][:255]
                ln.save(update_fields=['reason'])
        job.status = 'approved'
        job.approved_by = staff
        job.approved_at = timezone.now()
        job.estimated_value = value
        job.save(update_fields=['status', 'approved_by', 'approved_at', 'estimated_value'])
        build_baskets(job)
    _audit('rpa_portal_job_approved', job, staff=staff, extra={'estimated_value': str(value)})
    return job


def promote_basket(basket):
    """The ONE ready rule: a pending basket is ready when every line has a supplier key or is
    not_found, and at least one line has a key (an all-not_found basket has nothing to order)."""
    if basket.status != 'pending':
        return False
    lines = list(basket.lines.values_list('supplier_key', 'status'))
    if any(not k and st != 'not_found' for k, st in lines) or not any(k for k, _ in lines):
        return False
    basket.status = 'ready'
    basket.save(update_fields=['status'])
    return True


def build_baskets(job):
    """Cut the job's lines into baskets of portal.basket_size in seq order. Idempotent: a job
    that already has baskets gets them back untouched."""
    from apps.rpa.portal.skus import canonical_sku, known_key, padded_sku
    existing = list(job.baskets.all())
    if existing:
        return existing
    size = max(1, job.portal.basket_size)
    lines = _job_lines(job)
    out = []
    with transaction.atomic():
        for n, start in enumerate(range(0, len(lines), size), start=1):
            chunk = lines[start:start + size]
            keys = [canonical_sku(known_key(job.portal, ln.item)) for ln in chunk]
            basket = PortalBasket.objects.create(job=job, seq=n, status='pending')
            PortalLine.objects.bulk_create([
                PortalLine(basket=basket, buyline=ln, item=ln.item, wanted_qty=ln.remaining_qty,
                           supplier_key=k, supplier_key_padded=padded_sku(k))
                for ln, k in zip(chunk, keys)])
            promote_basket(basket)
            out.append(basket)
    return out


def cancel_job(job, *, staff, reason):
    if not staff.can_do('rpa', 'create'):
        raise PermissionDenied('لا تملك صلاحية إلغاء مهام المواقع')
    with transaction.atomic():
        job = PortalJob.objects.select_for_update().get(pk=job.pk)
        if job.status in ('cancelled', 'done'):
            raise JobError('المهمة منتهية')
        if job.baskets.exclude(status__in=['pending', 'ready']).exists():
            raise JobError('لا يمكن الإلغاء بعد أن بدأ الروبوت العمل على سلة')
        job.baskets.update(status='cancelled')
        job.status = 'cancelled'
        job.save(update_fields=['status'])
    _audit('rpa_portal_job_cancelled', job, staff=staff, note=(reason or '')[:255])
    return job
