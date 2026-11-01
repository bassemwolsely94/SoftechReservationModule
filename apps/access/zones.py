"""
Access zones (N3): where a signed-in request comes from (network) x what it comes on (device).

Z1 internal + approved device, Z2 internal + any other device, Z3 external + approved device,
Z4 external + any other device. Only an approved device is trusted; pending, blocked, retired or
no device at all is unknown.
"""
from .network import INTERNAL

Z1, Z2, Z3, Z4 = 'Z1', 'Z2', 'Z3', 'Z4'

ZONE_LABELS = {
    Z1: 'داخل الشبكة — جهاز معتمد',
    Z2: 'داخل الشبكة — جهاز غير معتمد',
    Z3: 'خارج الشبكة — جهاز معتمد',
    Z4: 'خارج الشبكة — جهاز غير معتمد',
}


def zone_for(network_zone, device_status):
    trusted = device_status == 'approved'
    if network_zone == INTERNAL:
        return Z1 if trusted else Z2
    return Z3 if trusted else Z4


def current_zone():
    """The zone of the request being served, or None (anonymous / no request)."""
    from . import context   # context imports this module
    acc = context.current()
    return acc.zone if acc is not None else None
