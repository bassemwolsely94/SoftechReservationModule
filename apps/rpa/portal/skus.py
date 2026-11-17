"""Supplier SKU helpers for the portal robot (Task 5 adds discovery on top of these)."""
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
