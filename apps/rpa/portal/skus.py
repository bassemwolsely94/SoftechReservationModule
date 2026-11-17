"""Supplier SKU helpers for the portal robot: keys, and code discovery (a person confirms)."""
from __future__ import annotations


class PortalSetupError(Exception):
    pass


def canonical_sku(raw) -> str:
    """Digits only, leading zeros stripped. '' when the value is not all digits."""
    s = str(raw or '').strip().replace(' ', '')
    if not s.isdigit():
        return ''
    return s.lstrip('0')


def padded_sku(canonical: str) -> str:
    return str(canonical).zfill(18) if canonical else ''


def vendor_for(portal):
    from apps.invoices.models import VendorProfile
    vendor = VendorProfile.objects.filter(softech_personcode=str(portal.supplier_code)).first()
    if vendor is None:
        raise PortalSetupError(f'لا يوجد ملف مورد للكود {portal.supplier_code}')
    return vendor


def known_key(portal, item) -> str:
    """The canonical SKU we already know for this vendor and item, else ''."""
    from apps.catalog.models import ItemSupplierLink
    from apps.invoices.models import VendorItemMapping
    vendor = vendor_for(portal)
    for code in (VendorItemMapping.objects.filter(vendor=vendor, item=item)
                 .exclude(vendor_item_code='').order_by('-use_count')
                 .values_list('vendor_item_code', flat=True)):
        key = canonical_sku(code)
        if key:
            return key
    for code in (ItemSupplierLink.objects.filter(item_code=item.softech_id,
                                                 supp_code=str(portal.supplier_code))
                 .exclude(supp_item_code='').values_list('supp_item_code', flat=True)):
        key = canonical_sku(code)
        if key:
            return key
    return ''


# ── discovery: the robot reports candidates, a person confirms one ─────────────

def record_discovery(job, results, *, run):
    """Store the robot's candidate products as one portal AvailabilityBatch, one line per
    candidate. Nothing is picked here: a person confirms (confirm_discovery)."""
    from django.db import transaction
    from apps.supply.models import AvailabilityBatch, AvailabilityLine
    vendor = vendor_for(job.portal)
    with transaction.atomic():
        batch = AvailabilityBatch.objects.create(
            supplier=vendor, supplier_name=vendor.name, source=AvailabilityBatch.SOURCE_PORTAL,
            notes=f'portal discovery job {job.pk} run {getattr(run, "pk", "")}')
        for res in results or []:
            for cand in res.get('candidates') or []:
                sku = canonical_sku(cand.get('sku'))
                if not sku:
                    continue
                AvailabilityLine.objects.create(
                    batch=batch, raw_text=str(cand.get('name') or '')[:300],
                    supplier_item_code=sku, price=cand.get('price'),
                    signals=['out_of_stock'] if cand.get('stock_mark') else [],
                    match_reason={'buyline_id': res.get('buyline_id'), 'job_id': job.pk})
    return batch


def _promote_ready(job):
    """Pending baskets whose every line now has a key become ready (the same rule
    jobs.build_baskets applies at build time)."""
    from apps.rpa.models import PortalBasket
    for basket in PortalBasket.objects.filter(job=job, status='pending'):
        if not basket.lines.filter(supplier_key='').exists():
            basket.status = 'ready'
            basket.save(update_fields=['status'])


def confirm_discovery(availability_line, *, staff):
    """A person confirmed this candidate for the buy line's item: learn the code, write it on
    the job's portal lines, ready the baskets that now have every key. When the code is
    already confirmed for another item the conflict stays on the line for a person."""
    from django.db import transaction
    from apps.rpa.models import BuyListLine, PortalJob, PortalLine
    from apps.rpa.portal.buylist import _audit
    from apps.supply.availability import confirm_line
    from apps.supply.models import AvailabilityLine
    with transaction.atomic():
        line = AvailabilityLine.objects.select_for_update().select_related('batch').get(
            pk=availability_line.pk)
        mr = line.match_reason or {}
        buyline = BuyListLine.objects.select_related('item').get(pk=mr['buyline_id'])
        sku = canonical_sku(line.supplier_item_code)
        confirm_line(line, buyline.item, staff=staff, vendor_code=sku)
        line.refresh_from_db()
        if (line.match_reason or {}).get('vendor_code_conflict'):
            return
        job_id = mr.get('job_id')
        lines = PortalLine.objects.filter(item=buyline.item, supplier_key='',
                                          basket__status__in=['pending', 'ready'])
        if job_id:
            lines = lines.filter(basket__job_id=job_id)
        lines.update(supplier_key=sku, supplier_key_padded=padded_sku(sku))
        if job_id:
            _promote_ready(PortalJob.objects.get(pk=job_id))
        _audit('rpa_portal_code_learnt', line, staff=staff,
               note=f'item {buyline.item_id} code {sku}',
               extra={'item_id': buyline.item_id, 'sku': sku, 'buyline_id': buyline.pk})


def reject_discovery(buyline, *, staff):
    """None of these: the portal lines become not_found and the buy line returns to the buyer."""
    from django.db import transaction
    from apps.rpa.models import BuyListLine, PortalLine
    from apps.rpa.portal.buylist import _audit, apply_result
    with transaction.atomic():
        locked = BuyListLine.objects.select_for_update().get(pk=buyline.pk)
        supplier = locked.chosen_supplier
        PortalLine.objects.filter(buyline=locked, supplier_key='').update(
            status='not_found', message='لا يوجد كود مطابق في موقع المورد')
        apply_result(locked, supplier_code=supplier, accepted=0, basket_id=None)
        _audit('rpa_portal_code_learnt', locked, staff=staff, note='none of the candidates',
               extra={'rejected': True})
