"""
apps/batches/store_roles.py

P-26: one place that decides what a SOFTECH store holds, for every expiry number.

    store_role('100', '110')  →  'closed'

Roles: live · return_candidate (105) · write_off (102) · cosmetics_expired (103) · closed (HQ 110,
plus every store on a branch whose kind is 'closed'). Closed stores are excluded from every number,
screen and export (owner, 2026-10-31).

The map is keyed node + store ("100:110"); '*' as the node means any node — the quarantine stores
were treated that way before this map existed. Admins can override entries with the SystemSetting
`expiry_store_roles` (JSON object); an invalid setting or entry falls back to the defaults.
"""
import logging

logger = logging.getLogger('elrezeiky.batches')

LIVE, RETURN, WRITE_OFF, COSMETICS, CLOSED = 'live', 'return_candidate', 'write_off', 'cosmetics_expired', 'closed'
QUARANTINE_ROLES = (RETURN, WRITE_OFF, COSMETICS)

ROLE_LABELS = {
    LIVE:      'مخزون قابل للبيع',
    RETURN:    'مرشح للمرتجع (105)',
    WRITE_OFF: 'إتلاف / شطب (102)',
    COSMETICS: 'تجميل منتهي (103)',
    CLOSED:    'فرع مغلق (110)',
}

DEFAULT_MAP = {
    '*:105':   RETURN,
    '*:102':   WRITE_OFF,
    '*:103':   COSMETICS,
    '100:110': CLOSED,
}


def _role_map():
    roles = dict(DEFAULT_MAP)
    try:
        from apps.config.models import SystemSetting
        custom = SystemSetting.get('expiry_store_roles')
    except Exception:
        custom = None
    if custom is None:
        return roles
    if not isinstance(custom, dict):
        logger.warning('[StoreRoles] expiry_store_roles is not a JSON object — using the defaults')
        return roles
    for key, role in custom.items():
        if isinstance(key, str) and key.count(':') == 1 and role in ROLE_LABELS:
            roles[key.strip()] = role
        else:
            logger.warning('[StoreRoles] ignored expiry_store_roles entry %r → %r', key, role)
    return roles


def _closed_nodes():
    from apps.branches.models import Branch
    return set(Branch.objects.filter(kind=Branch.KIND_CLOSED).values_list('softech_branch_id', flat=True))


def resolver():
    """A store_role(node, store) function with the map and closed branches loaded once — for loops."""
    roles, closed = _role_map(), _closed_nodes()

    def role(node, store):
        node, store = str(node or '').strip(), str(store or '').strip()
        if node in closed:
            return CLOSED
        return roles.get(f'{node}:{store}') or roles.get(f'*:{store}') or LIVE
    return role


def store_role(node, store):
    return resolver()(node, store)
