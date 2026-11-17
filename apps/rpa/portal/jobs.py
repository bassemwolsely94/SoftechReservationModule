"""Portal jobs: create from a buy list, approve (need check + four-eyes), cut into baskets.

Nothing here writes SOFTECH. Portal jobs are company level: ordered for HQ.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.rpa.models import BuyListLine, PortalBasket, PortalJob, PortalLine
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


def create_job(buylist, *, portal, account, staff):
    if not staff.can_do('rpa', 'create'):
        raise PermissionDenied('لا تملك صلاحية إنشاء مهام المواقع')
    if account.portal_id != portal.pk:
        raise JobError('الحساب لا يخص هذا الموقع')
    if buylist.status != 'open':
        raise JobError('القائمة مغلقة')
    if not buylist.lines.filter(chosen_supplier=str(portal.supplier_code), remaining_qty__gt=0).exists():
        raise JobError('لا توجد أسطر مختارة لهذا المورد')
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
        if job.status != 'draft':
            raise JobError('المهمة ليست مسودة')
        lines = _job_lines(job)
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
        value = Decimal(str(sum((r.get('line_value') or 0) for r in prev['lines'])))
        limit = _four_eyes_limit()
        if limit is not None and value > limit:
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
            basket = PortalBasket.objects.create(
                job=job, seq=n, status='ready' if all(keys) else 'pending')
            PortalLine.objects.bulk_create([
                PortalLine(basket=basket, buyline=ln, item=ln.item, wanted_qty=ln.remaining_qty,
                           supplier_key=k, supplier_key_padded=padded_sku(k))
                for ln, k in zip(chunk, keys)])
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
