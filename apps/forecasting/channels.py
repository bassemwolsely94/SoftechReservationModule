"""
apps/forecasting/channels.py  (piece 4 — item & channel codes)
==============================================================
One reader for what a SOFTECH customer-channel code means. The data lives on
ChannelBucketMap (owner-editable); this module reads it, caches it, and seeds
the owner-approved table when the map has no customer (person_type '10') rows.

The KPI columns (bucket / subtype / counts_customer / include_in_profit) are the
validated 2026-07-29 defaults that used to live in seed_kpi_config.PT10_DEFAULTS;
they are unchanged. Unknown codes are «غير مصنف (<code>)», never contract, never
favoured. Blank codes are blank (callers show «عميل» / — as before).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger('elrezeiky.forecasting')

CUSTOMER_PT = '10'
CACHE_KEY = 'codes:channels:v1'
CACHE_TTL = 600  # 10 min

# Owner-approved channel meanings (spec §2) + validated KPI defaults (doc 16).
CHANNEL_DEFAULTS: dict[str, dict] = {
    '91': {'group': 'cash',         'is_contract_sale': False, 'followup_rank': 1,
           'bucket': 'cash',      'subtype': '',         'counts_customer': True,  'include_in_profit': True},   # عميل نقدى
    '90': {'group': 'delivery',     'is_contract_sale': False, 'followup_rank': 1,
           'bucket': 'cash',      'subtype': 'delivery', 'counts_customer': True,  'include_in_profit': True},   # عميل Delivery
    '30': {'group': 'permanent',    'is_contract_sale': False, 'followup_rank': 2,
           'bucket': 'cash',      'subtype': 'regular',  'counts_customer': False, 'include_in_profit': True},   # عميل دائم
    '99': {'group': 'vip',          'is_contract_sale': False, 'followup_rank': 2,
           'bucket': 'exclude',   'subtype': '',         'counts_customer': False, 'include_in_profit': False},  # Vip (owner to map)
    '10': {'group': 'contract',     'is_contract_sale': True,  'followup_rank': 3,
           'bucket': 'credit',    'subtype': '',         'counts_customer': False, 'include_in_profit': False},  # تعاقدات / آجل
    '33': {'group': 'contract',     'is_contract_sale': True,  'followup_rank': 3,
           'bucket': 'credit',    'subtype': '',         'counts_customer': False, 'include_in_profit': False},  # تعاقد - سداد آجل - خصم يدوي
    '11': {'group': 'employee',     'is_contract_sale': True,  'followup_rank': 3,
           'bucket': 'cash',      'subtype': '',         'counts_customer': False, 'include_in_profit': True},   # موظفيين شركة الرزيقي
    '12': {'group': 'card',         'is_contract_sale': False, 'followup_rank': 3,
           'bucket': 'cash',      'subtype': '',         'counts_customer': False, 'include_in_profit': True},   # إيصال إلكترونى بالبطاقة
    '15': {'group': 'insurance',    'is_contract_sale': True,  'followup_rank': 4,
           'bucket': 'insurance', 'subtype': '',         'counts_customer': False, 'include_in_profit': False},  # تأمين صحي
    '16': {'group': 'donation',     'is_contract_sale': False, 'followup_rank': 4,
           'bucket': 'exclude',   'subtype': '',         'counts_customer': False, 'include_in_profit': False},  # تبرعات
    '17': {'group': 'compensation', 'is_contract_sale': True,  'followup_rank': 4,
           'bucket': 'exclude',   'subtype': '',         'counts_customer': False, 'include_in_profit': False},  # تعويضات الشركات — not normal sales
    '31': {'group': 'settlement',   'is_contract_sale': False, 'followup_rank': 4,
           'bucket': 'credit',    'subtype': '',         'counts_customer': False, 'include_in_profit': False},  # مقاصات (owner to confirm)
}

# Follow-up priorities the owner may pick (server rule; served to the UI as choices.ranks).
FOLLOWUP_RANKS = (1, 2, 3, 4)
MEANING_FIELDS = ('group', 'is_contract_sale', 'followup_rank')
KPI_FIELDS = ('bucket', 'subtype', 'counts_customer', 'include_in_profit')

GROUP_LABELS: dict[str, str] = {
    'cash': 'نقدي', 'delivery': 'توصيل', 'permanent': 'عميل دائم',
    'contract': 'تعاقد', 'employee': 'موظفين', 'insurance': 'تأمين',
    'card': 'بطاقة شخصية', 'donation': 'تبرعات', 'compensation': 'تعويضات',
    'settlement': 'مقاصات', 'vip': 'VIP', 'other': 'أخرى',
    'unclassified': 'غير مصنف',
}


@dataclass(frozen=True)
class ChannelInfo:
    code: str
    group: str
    group_label: str
    label: str
    bucket: str
    followup_rank: int | None
    is_contract_sale: bool
    known: bool


_BLANK = ChannelInfo(code='', group='', group_label='', label='', bucket='exclude',
                     followup_rank=None, is_contract_sale=False, known=False)

# (person_type, channel) → ChannelInfo ; None = not loaded. The module copy also
# expires after CACHE_TTL so another process's edit shows up (LocMem is per process).
_local: dict = {'map': None, 'at': 0.0}


def _unknown(code: str) -> ChannelInfo:
    return ChannelInfo(code=code, group='unclassified',
                       group_label=GROUP_LABELS['unclassified'],
                       label=f'غير مصنف ({code})', bucket='exclude',
                       followup_rank=None, is_contract_sale=False, known=False)


def invalidate_cache(*_args, **_kwargs) -> None:
    """Drop both caches. Connected to ChannelBucketMap post_save / post_delete."""
    _local['map'] = None
    try:
        from django.core.cache import cache
        cache.delete(CACHE_KEY)
    except Exception as exc:  # cache backend down must not break a save
        logger.warning('channels cache delete failed: %s', exc)


def _softech_labels() -> dict:
    try:
        from apps.sync.models import SoftechPersonClassif
        return {(r.ptcode, r.ptclassifcode): r.ptclassifdescr or ''
                for r in SoftechPersonClassif.objects.all()}
    except Exception:
        return {}


def ensure_defaults() -> int:
    """Seed the approved pt-10 table when the map has NO pt-10 row. Returns rows created.

    Only when the pt-10 set is empty, so a test or an owner that already created
    its own rows is never touched (and no unique-constraint clash)."""
    from django.db import IntegrityError, transaction
    from apps.forecasting.models import ChannelBucketMap

    if ChannelBucketMap.objects.filter(person_type=CUSTOMER_PT).exists():
        return 0
    labels = _softech_labels()
    rows = [
        ChannelBucketMap(person_type=CUSTOMER_PT, channel=code,
                         label=labels.get((CUSTOMER_PT, code), ''), **vals)
        for code, vals in CHANNEL_DEFAULTS.items()
    ]
    try:
        with transaction.atomic():
            ChannelBucketMap.objects.bulk_create(rows)
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
        from apps.forecasting.models import ChannelBucketMap
        data = {}
        for r in ChannelBucketMap.objects.all():
            group = r.group or 'unclassified'
            # An unclassified row (e.g. a code SOFTECH added later) reads «غير مصنف (<code>)»
            # until the owner gives it a meaning, followed by SOFTECH's name when it has one.
            if group == 'unclassified':
                label = f'غير مصنف ({r.channel})' + (f' — {r.label}' if r.label else '')
            else:
                label = r.label or ''
            data[(r.person_type, r.channel)] = ChannelInfo(
                code=r.channel, group=group,
                group_label=GROUP_LABELS.get(group, group),
                label=label, bucket=r.bucket,
                followup_rank=r.followup_rank,
                is_contract_sale=bool(r.is_contract_sale), known=True,
            )
        try:
            cache.set(CACHE_KEY, data, CACHE_TTL)
        except Exception:
            pass
    _local['map'] = data
    _local['at'] = time.monotonic()
    return data


def channel(code: str, person_type: str = CUSTOMER_PT) -> ChannelInfo:
    code = (code or '').strip()
    if not code:
        return _BLANK
    return _load().get((person_type, code)) or _unknown(code)


def _customer_infos() -> list[ChannelInfo]:
    return [i for (pt, _c), i in _load().items() if pt == CUSTOMER_PT]


def contract_codes() -> tuple[str, ...]:
    return tuple(sorted(i.code for i in _customer_infos() if i.is_contract_sale))


def favoured_codes() -> set[str]:
    return {i.code for i in _customer_infos()
            if i.followup_rank is not None and 1 <= i.followup_rank <= 2}


def rank_map() -> dict[str, int]:
    return {i.code: i.followup_rank for i in _customer_infos()
            if i.followup_rank is not None}


def customer_channels() -> list[ChannelInfo]:
    big = 10 ** 6
    return sorted(_customer_infos(),
                  key=lambda i: (i.followup_rank if i.followup_rank is not None else big, i.code))


def ensure_channel_rows(notify: bool = True) -> list[str]:
    """Called after the SOFTECH person-classif sync. Adds a ChannelBucketMap row for
    every SOFTECH pair it lacks (approved defaults for known pt-10 codes, else
    unclassified/exclude), refreshes labels, and tells admins once about new
    unclassified pt-10 codes. Returns those codes. Never raises."""
    try:
        from apps.forecasting.models import ChannelBucketMap
        from apps.sync.models import SoftechPersonClassif

        existing = {(r.person_type, r.channel): r for r in ChannelBucketMap.objects.all()}
        new_unclassified: list[str] = []
        created = False
        for c in SoftechPersonClassif.objects.all():
            pt, ch = (c.ptcode or '').strip(), (c.ptclassifcode or '').strip()
            if not pt or not ch:
                continue
            if pt != CUSTOMER_PT and (pt, ch) not in existing:
                continue          # only customer pairs are auto-inserted (others: seed_kpi_config)
            label = c.ptclassifdescr or ''
            row = existing.get((pt, ch))
            if row is None:
                default = CHANNEL_DEFAULTS.get(ch) if pt == CUSTOMER_PT else None
                vals = dict(default) if default else {'group': 'unclassified', 'bucket': 'exclude'}
                row = ChannelBucketMap.objects.create(person_type=pt, channel=ch,
                                                      label=label, **vals)
                existing[(pt, ch)] = row
                created = True
                if default is None and pt == CUSTOMER_PT:
                    new_unclassified.append(ch)
            elif label and row.label != label:
                row.label = label
                row.save(update_fields=['label'])
        if created:
            invalidate_cache()
        new_unclassified.sort()
        if new_unclassified and notify:
            _notify_admins(new_unclassified, existing)
        return new_unclassified
    except Exception as exc:
        logger.warning('ensure_channel_rows failed: %s', exc)
        return []


def _notify_admins(codes: list[str], rows: dict) -> None:
    try:
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile
        admins = list(StaffProfile.objects.filter(role='admin', is_active=True))
        title = 'قناة بيع جديدة من SOFTECH'
        for code in codes:
            row = rows.get((CUSTOMER_PT, code))
            label = getattr(row, 'label', '') or ''
            body = (f'كود القناة {code}' + (f' — {label}' if label else '')
                    + ' — غير مصنف. حدّد معناه من ربط قنوات البيع.')
            for sp in admins:
                Notification.send_to_user(sp, 'system', title, body,
                                          dedup_key=f'code_map_channel_{code}',
                                          dedup_once=True)
    except Exception as exc:
        logger.warning('channel notify skipped: %s', exc)
