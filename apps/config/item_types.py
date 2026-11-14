"""
apps/config/item_types.py  (piece 4 — item & channel codes)
===========================================================
One reader for what a SOFTECH item-category code (Item.medicine_type) means. Data
lives on MedicineTypeMap (owner-editable); this module reads and caches it and
seeds the owner-approved table when the map is empty. Unknown codes are
«غير مصنف (<code>)»: never medicine, never excluded from planning.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger('elrezeiky.config')

CACHE_KEY = 'codes:item_types:v1'
CACHE_TTL = 600  # 10 min

# Owner-approved item categories (spec §3).
ITEM_TYPE_DEFAULTS: dict[str, dict] = {
    '10': {'group': 'medicine',      'is_medicine': True,  'excluded_from_planning': False},
    '50': {'group': 'cosmetics',     'is_medicine': False, 'excluded_from_planning': False},
    '20': {'group': 'others',        'is_medicine': False, 'excluded_from_planning': False},
    '30': {'group': 'body_building', 'is_medicine': False, 'excluded_from_planning': False},
    '40': {'group': 'veterinary',    'is_medicine': False, 'excluded_from_planning': False},
    '60': {'group': 'gift',          'is_medicine': False, 'excluded_from_planning': True},
    '70': {'group': 'service',       'is_medicine': False, 'excluded_from_planning': False},
    '00': {'group': 'na',            'is_medicine': False, 'excluded_from_planning': False},
}

# code → (label, group, is_medicine, excluded) ; None = not loaded. The module copy
# also expires after CACHE_TTL so another process's edit shows up.
_local: dict = {'map': None, 'at': 0.0}


def invalidate_cache(*_args, **_kwargs) -> None:
    """Drop both caches. Connected to MedicineTypeMap post_save / post_delete."""
    _local['map'] = None
    try:
        from django.core.cache import cache
        cache.delete(CACHE_KEY)
    except Exception as exc:  # a cache backend outage must not break a save
        logger.warning('item_types cache delete failed: %s', exc)


def ensure_defaults() -> int:
    """Seed the approved table when the map is empty. Returns rows created."""
    from django.db import IntegrityError, transaction
    from apps.config.models import MedicineTypeMap

    if MedicineTypeMap.objects.exists():
        return 0
    rows = [MedicineTypeMap(code=code, **vals) for code, vals in ITEM_TYPE_DEFAULTS.items()]
    try:
        with transaction.atomic():
            MedicineTypeMap.objects.bulk_create(rows)
    except IntegrityError:  # another process seeded at the same moment
        return 0
    invalidate_cache()
    return len(rows)


def _load() -> dict:
    if _local['map'] is not None and time.monotonic() - _local['at'] < CACHE_TTL:
        return _local['map']
    from django.core.cache import cache
    data = None
    try:
        data = cache.get(CACHE_KEY)
    except Exception:
        data = None
    if data is None:
        ensure_defaults()
        from apps.config.models import MedicineTypeMap
        data = {r.code: (r.label or r.get_group_display(), r.group,
                         bool(r.is_medicine), bool(r.excluded_from_planning))
                for r in MedicineTypeMap.objects.all()}
        try:
            cache.set(CACHE_KEY, data, CACHE_TTL)
        except Exception:
            pass
    _local['map'] = data
    _local['at'] = time.monotonic()
    return data


def medicine_codes() -> list[str]:
    return sorted(c for c, v in _load().items() if v[2])


def planning_excluded_codes() -> list[str]:
    return sorted(c for c, v in _load().items() if v[3])


def label(code) -> str:
    code = (code or '').strip()
    if not code:
        return ''
    v = _load().get(code)
    return v[0] if v else f'غير مصنف ({code})'


def all_types() -> list:
    from apps.config.models import MedicineTypeMap
    ensure_defaults()
    return list(MedicineTypeMap.objects.order_by('code'))


def sync_item_types(names: dict, notify: bool = True) -> list[str]:
    """Called after the SOFTECH itemstree load. Adds an unclassified row for every
    code the map lacks, refreshes labels (never the owner's flags), and tells
    admins once about new codes. Returns the new codes. Never raises."""
    try:
        from apps.config.models import MedicineTypeMap

        ensure_defaults()
        existing = {r.code: r for r in MedicineTypeMap.objects.all()}
        new_codes: list[str] = []
        changed = False
        for code, (en, ar) in (names or {}).items():
            code = (code or '').strip()
            if not code:
                continue
            lbl = (ar or en or '')[:100]
            row = existing.get(code)
            if row is None:
                existing[code] = MedicineTypeMap.objects.create(code=code, label=lbl)
                new_codes.append(code)
                changed = True
            elif lbl and row.label != lbl:
                row.label = lbl
                row.save(update_fields=['label', 'updated_at'])
                changed = True
        if changed:
            invalidate_cache()
        new_codes.sort()
        if new_codes and notify:
            _notify_admins(new_codes, existing)
        return new_codes
    except Exception as exc:
        logger.warning('sync_item_types failed: %s', exc)
        return []


def _notify_admins(codes: list[str], rows: dict) -> None:
    try:
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile
        admins = list(StaffProfile.objects.filter(role='admin', is_active=True))
        title = 'تصنيف صنف جديد من SOFTECH'
        for code in codes:
            lbl = getattr(rows.get(code), 'label', '') or ''
            body = (f'كود التصنيف {code}' + (f' — {lbl}' if lbl else '')
                    + ' — غير مصنف. حدّد معناه من ربط تصنيفات الأصناف.')
            for sp in admins:
                Notification.send_to_user(sp, 'system', title, body,
                                          dedup_key=f'code_map_item_type_{code}',
                                          dedup_once=True)
    except Exception as exc:
        logger.warning('item type notify skipped: %s', exc)
