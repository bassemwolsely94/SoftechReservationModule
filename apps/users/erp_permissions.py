"""
SOFTECH → platform permission inheritance (Stages B–D).

Pipeline:
  ErpGroupPermission (group × screen × 12 flags)   ← mirrored from SOFTECH
        │  aggregate over screens of the mapped systems
        ▼
  ErpGroupModulePermission (group × module × 6 actions + cost gate)  ← DERIVED
        │  resolve user → ERP group
        ▼
  user_module_permissions(user)  →  effective permissions used for enforcement

Bundle rules (business-approved):
  • SOFTECH authoritative — rebuilt nightly; Django overrides reset.
  • Smart flag→action:
        view    = enable | show | retrieve
        edit    = save
        create  = save           (SOFTECH "save" covers add+modify)
        delete  = save           (no separate SOFTECH delete flag)
        export  = print
        approve = (not derived — native/role-governed)
        see_cost = money | cost  (financial gate)
  • Collapse to 6 actions + see_cost.
  • Native modules stay role-governed and are NOT mapped (see NATIVE_MODULES).
"""
import logging

logger = logging.getLogger('elrezeiky.users')

# Platform modules that map to SOFTECH systems (governed by inherited perms).
# Native modules below are intentionally excluded (Django-role governed).
NATIVE_MODULES = {
    'reservations', 'demand', 'pricing-approvals', 'analytics', 'dashboard',
}

# Default SOFTECH-system → platform-module map. Seeded into SoftechSystemMap;
# admins can edit afterwards. (system, module, note)
DEFAULT_SYSTEM_MAP = [
    ('IM', 'catalog',     'Items Basic Data'),
    ('AR', 'customers',   'A/R + Cash Discounts'),
    ('AR', 'vouchers',    'Cash Discounts'),
    ('AP', 'purchasing',  'Imports / Purchasing'),
    ('AP', 'invoices',    'Supplier invoices'),
    ('MB', 'transfers',   'Sales to Branch'),          # ambiguous — confirm
    ('BC', 'sync',        'Download MAIN→Branch'),
    ('DR', 'sync',        'Replication Scheduler'),
    ('CS', 'callcenter',  'Customer Care / Call Center'),
    ('DM', 'delivery',    'Delivery Task Force'),
    ('ET', 'invoices',    'e-Tax'),
    ('GL', 'finance',     'General Ledger'),
    ('FA', 'finance',     'Fixed Assets'),
    ('BD', 'finance',     'Budget'),
    ('OM', 'finance',     'Cost Centers'),
    ('MI', 'insurance',   'Service Provider Statement'),
    ('HC', 'insurance',   'Health insurance forms'),
    ('IM', 'stockcount',  'Items / stock'),
    ('IM', 'shortage',    'Items / stock'),
]


def seed_system_map(force=False):
    """Insert default system→module rows (only if table empty, unless force)."""
    from .models import SoftechSystemMap
    if not force and SoftechSystemMap.objects.exists():
        return 0
    n = 0
    for system, module, note in DEFAULT_SYSTEM_MAP:
        _, created = SoftechSystemMap.objects.get_or_create(
            system=system, django_module=module, defaults={'note': note}
        )
        n += int(created)
    return n


def derive_group_permissions():
    """
    Rebuild ErpGroupModulePermission for every group from the current
    ErpGroupPermission + SoftechSystemMap. SOFTECH-authoritative.
    Returns the number of (group × module) rows written.
    """
    from django.db.models import Q
    from .models import (
        ErpUserGroup, ErpScreen, ErpGroupPermission,
        SoftechSystemMap, ErpGroupModulePermission,
    )

    # module → set(systems)
    module_systems = {}
    for m in SoftechSystemMap.objects.filter(is_active=True):
        module_systems.setdefault(m.django_module, set()).add(m.system)

    # system → set(mitemname)
    sys_screens = {}
    for s in ErpScreen.objects.all():
        sys_screens.setdefault(s.system, set()).add(s.mitemname)

    rows = []
    for group in ErpUserGroup.objects.all():
        # all this group's screen perms in memory (one query per group)
        gperms = {
            p.mitemname: p
            for p in ErpGroupPermission.objects.filter(group=group)
        }
        for module, systems in module_systems.items():
            screens = set()
            for sysc in systems:
                screens |= sys_screens.get(sysc, set())
            view = create = edit = delete = export = see_cost = False
            counted = 0
            for sc in screens:
                p = gperms.get(sc)
                if not p:
                    continue
                counted += 1
                if p.can_enable or p.can_show or p.can_retrieve:
                    view = True
                if p.can_save:
                    edit = create = delete = True
                if p.can_print:
                    export = True
                if p.can_money or p.can_cost:
                    see_cost = True
            rows.append(ErpGroupModulePermission(
                group=group, module=module,
                can_view=view, can_create=create, can_edit=edit, can_delete=delete,
                can_approve=False, can_export=export, can_see_cost=see_cost,
                screens_count=counted,
            ))

    # replace-all for a clean nightly rebuild
    ErpGroupModulePermission.objects.all().delete()
    if rows:
        ErpGroupModulePermission.objects.bulk_create(rows, batch_size=500)
    logger.info(f"[erp-perms] derived {len(rows)} group×module permissions")
    return len(rows)


def user_erp_group(user):
    """Resolve a Django user → their SOFTECH ErpUserGroup (or None)."""
    from .models import ERPUser, ErpUserGroup
    sp = getattr(user, 'staff_profile', None)
    if not sp or not (sp.softech_user_id or '').strip():
        return None
    code = sp.softech_user_id.strip()
    # ERPUser.username is the SOFTECH usercode; user_group is the group id
    erp = ERPUser.objects.filter(username=code).values_list('user_group', flat=True).first()
    if erp is None or str(erp).strip() == '':
        return None
    try:
        return ErpUserGroup.objects.filter(usergroup=int(erp)).first()
    except (ValueError, TypeError):
        return None


def user_module_permissions(user):
    """
    Effective platform permissions for a user, inherited from their SOFTECH
    group. Native modules are omitted (role-governed). Admin/superuser get all.
    Returns: { module: {view, create, edit, delete, approve, export, see_cost} }
    """
    # Platform admins keep full access regardless of SOFTECH group
    try:
        is_admin = user.is_superuser or user.staff_profile.role == 'admin'
    except Exception:
        is_admin = user.is_superuser
    if is_admin:
        return {'_is_admin': True}

    from .models import ErpGroupModulePermission
    group = user_erp_group(user)
    if not group:
        return {}
    out = {}
    for p in ErpGroupModulePermission.objects.filter(group=group):
        out[p.module] = {
            'view': p.can_view, 'create': p.can_create, 'edit': p.can_edit,
            'delete': p.can_delete, 'approve': p.can_approve,
            'export': p.can_export, 'see_cost': p.can_see_cost,
        }
    return out


def user_can(user, module, action='view'):
    """Convenience check. Native modules / admins → True (role-governed)."""
    if module in NATIVE_MODULES:
        return True
    perms = user_module_permissions(user)
    if perms.get('_is_admin'):
        return True
    return bool(perms.get(module, {}).get(action, False))
