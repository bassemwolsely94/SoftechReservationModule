"""
apps/data_lifecycle/reports.py

The payloads of /api/data-health/ (design §6 Stage 5, §9). Read-only: everything here reads stored snapshots,
run lines and held-file rows; only views.refresh recomputes. views.py stays thin and calls these.

Company-level by nature, no branch scoping: sizes, counts and rule settings belong to no branch. Who may see
it (§7): admin, supervisor and quality manager see growth and problems; rules and held files are admin only
(views.py checks). No SOFTECH reads or writes. Customer data is counts only. A held file's row never carries its
paths, hash or `rows` (they name files and records); see held_row.
"""
import datetime
import math

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Sum
from django.utils import timezone

from . import policy
from .models import DataHealthSnapshot, HeldFile, LifecycleRulePolicy, LifecycleRunLine, TableSizeSnapshot
from .problems import PROBLEMS
from .register import KIND_FILE, KIND_P56, KIND_ROW, RULES

REFRESH_KEY = 'data_health_refreshing'
FORECAST_WINDOW_DAYS = 30
FORECAST_MIN_SPAN_DAYS = 7    # fewer days of history give no rate (Review Focus 2)
SERIES_DAYS = 180
GROWTH_WINDOW_DAYS = 30
HELD_LIMIT = 500

# The tables each P-56 step of apps/sync/maintenance.py prunes, so they count as classified on the Growth tab.
P56_TABLES = {
    'p56_engine': ('purchasing.ItemDemandMetrics', 'purchasing.ItemDemandAggregated'),
    'p56_notifications': ('notifications.Notification',),
    'p56_pbx': ('pbx.PBXEvent',),
    'p56_audit': ('audit.AuditLog',),
    'p56_slow': ('sync.SlowRequest',),
    'p56_screen_views': ('audit.ScreenView',),
}

# Thumbnails are an allowlist (design §7, Review Focus 1): item images only. Prescriptions, pos_rx samples,
# conversations, orphans and anything unknown get none.
THUMBNAIL_RULES = frozenset({'images_rejected', 'images_unreviewed', 'images_obsolete'})
THUMBNAIL_MODELS = frozenset({'images.ImageCandidate', 'product_experience.ProductMedia'})
UNREFERENCED_LABEL_AR = 'ملفات لا يستخدمها أي سجل'


def is_refreshing():
    return cache.get(REFRESH_KEY) is not None


def _iso(value):
    return value.isoformat() if value is not None else None


def _staff_name(staff):
    if staff is None:
        return None
    return getattr(staff, 'full_name', None) or str(staff)


def _model_label_ar(label):
    """The model's verbose_name for 'app.Model', blank when there is none or it does not resolve."""
    if not label:
        return ''
    try:
        return str(apps.get_model(label)._meta.verbose_name)
    except (LookupError, ValueError):
        return ''


# ── Growth ───────────────────────────────────────────────────────────────────

def _forecast(latest, today):
    level = settings.DATA_HEALTH_DISK_LEVEL_PERCENT     # the disk level the forecast counts the days to
    out = {'level_percent': level, 'daily_bytes': None, 'days_to_level': None}
    if latest is None:
        return out
    window = DataHealthSnapshot.objects.filter(day__gte=today - datetime.timedelta(days=FORECAST_WINDOW_DAYS))
    oldest = window.order_by('day').first()
    if oldest is None or latest.day <= oldest.day:
        return out
    span = (latest.day - oldest.day).days
    if span < FORECAST_MIN_SPAN_DAYS:
        return out
    delta = (latest.db_bytes + latest.media_bytes) - (oldest.db_bytes + oldest.media_bytes)
    rate = delta / span
    out['daily_bytes'] = round(rate)
    if rate <= 0 or latest.disk_total_bytes <= 0:
        return out
    used = latest.disk_total_bytes - latest.disk_free_bytes
    left = level * latest.disk_total_bytes / 100 - used
    out['days_to_level'] = max(0, math.floor(left / rate))
    return out


def _table_labels():
    """{db_table: rule label_ar} for every table a row rule or a P-56 step prunes."""
    labels = {}
    for key, models in P56_TABLES.items():
        for label in models:
            try:
                labels[apps.get_model(label)._meta.db_table] = RULES[key].label_ar
            except LookupError:
                continue
    for rule in RULES.values():          # row rules win over P-56 for the same table
        if rule.kind != KIND_ROW:
            continue
        for label in rule.targets:
            try:
                labels[apps.get_model(label)._meta.db_table] = rule.label_ar
            except LookupError:
                continue
    return labels


def _tables(latest_snapshot, now):
    latest_at = TableSizeSnapshot.objects.order_by('-taken_at').values_list('taken_at', flat=True).first()
    if latest_at is None:
        return []
    older_at = (TableSizeSnapshot.objects.filter(taken_at__gte=now - datetime.timedelta(days=GROWTH_WINDOW_DAYS))
                .order_by('taken_at').values_list('taken_at', flat=True).first())
    older = {}
    if older_at is not None and older_at != latest_at:
        older = dict(TableSizeSnapshot.objects.filter(taken_at=older_at).values_list('table', 'total_bytes'))
    empty = (latest_snapshot.empty_by_table if latest_snapshot else None) or {}
    labels = _table_labels()
    rows = []
    for t in TableSizeSnapshot.objects.filter(taken_at=latest_at).order_by('-total_bytes', 'table'):
        rows.append({
            'table': t.table, 'total_bytes': t.total_bytes, 'heap_bytes': t.heap_bytes,
            'index_bytes': t.index_bytes, 'row_estimate': t.row_estimate,
            'growth_bytes': (t.total_bytes - older[t.table]) if t.table in older else None,
            'empty_bytes': int(empty.get(t.table) or 0),
            'classified': t.table in labels, 'rule_label_ar': labels.get(t.table, ''),
        })
    return rows


def _snapshot_near(days_ago, today, latest):
    """The snapshot closest to `days_ago` days old, other than `latest`; None when there is no other."""
    target = today - datetime.timedelta(days=days_ago)
    others = DataHealthSnapshot.objects.exclude(pk=latest.pk) if latest else DataHealthSnapshot.objects.none()
    before = others.filter(day__lte=target).order_by('-day').first()
    after = others.filter(day__gt=target).order_by('day').first()
    candidates = [s for s in (before, after) if s is not None]
    return min(candidates, key=lambda s: abs((s.day - target).days)) if candidates else None


def _media_rows(current, previous, key_name, label):
    """`previous` None means no older snapshot: every growth is None, as it is for a key the older one lacks."""
    rows = []
    for key, entry in (current or {}).items():
        old = previous.get(key) if previous is not None else None
        row = {key_name: key}
        if label:
            row['label_ar'] = label(key)
        row.update({'bytes': int(entry.get('bytes') or 0), 'files': int(entry.get('files') or 0),
                    'growth_bytes': (int(entry.get('bytes') or 0) - int(old.get('bytes') or 0)) if old else None})
        rows.append(row)
    rows.sort(key=lambda r: (-r['bytes'], str(r[key_name])))
    return rows


def _type_label(key):
    if key == 'unreferenced':
        return UNREFERENCED_LABEL_AR
    return _model_label_ar(key.rsplit('.', 1)[0]) if '.' in key else ''


def _missed_retention_days(today):
    from apps.sync.models import SyncRun
    first = DataHealthSnapshot.objects.order_by('day').values_list('day', flat=True).first()
    if first is None:
        return 0
    days = [today - datetime.timedelta(days=n) for n in range(1, GROWTH_WINDOW_DAYS + 1)]
    days = [d for d in days if d >= first]
    if not days:
        return 0
    since = timezone.make_aware(datetime.datetime.combine(min(days), datetime.time.min))
    ok = {timezone.localdate(at) for at in SyncRun.objects.filter(lane='retention', status='success',
                                                                    started_at__gte=since)
          .values_list('started_at', flat=True)}
    return sum(1 for d in days if d not in ok)


def _measures(now, today):
    since = now - datetime.timedelta(days=GROWTH_WINDOW_DAYS)
    removed = (LifecycleRunLine.objects.filter(is_preview=False, run__started_at__gte=since)
               .values('rule_key').annotate(count=Sum('count'), bytes=Sum('bytes')).order_by('rule_key'))
    return {
        'removed': [{'rule_key': r['rule_key'],
                     'label_ar': RULES[r['rule_key']].label_ar if r['rule_key'] in RULES else r['rule_key'],
                     'count': int(r['count'] or 0), 'bytes': int(r['bytes'] or 0)} for r in removed],
        'restores': HeldFile.objects.filter(restored_at__gte=since).count(),
        'missed_retention_days': _missed_retention_days(today),
    }


def growth_payload():
    now, today = timezone.now(), timezone.localdate()
    latest = DataHealthSnapshot.objects.order_by('-day').first()
    held = HeldFile.objects.filter(restored_at__isnull=True, purged_at__isnull=True).aggregate(
        n=Count('pk'), b=Sum('size'))
    snap_fields = ('db_bytes', 'media_bytes', 'media_files', 'empty_bytes', 'disk_total_bytes', 'disk_free_bytes')
    current = {f: (getattr(latest, f) if latest else None) for f in snap_fields}
    current.update({'held_bytes': int(held['b'] or 0), 'held_files': held['n']})
    series = list(DataHealthSnapshot.objects.order_by('-day').values('day', 'db_bytes', 'media_bytes',
                                                                      'empty_bytes')[:SERIES_DAYS])
    series.reverse()
    previous = _snapshot_near(GROWTH_WINDOW_DAYS, today, latest)
    return {
        'as_of': _iso(latest.taken_at) if latest else None,
        'refreshing': is_refreshing(),
        'current': current,
        'series': [{**s, 'day': s['day'].isoformat()} for s in series],
        'forecast': _forecast(latest, today),
        'tables': _tables(latest, now),
        'types': _media_rows(latest.media_by_type if latest else {},
                             previous.media_by_type if previous else None, 'key', _type_label),
        'folders': _media_rows(latest.media_by_folder if latest else {},
                               previous.media_by_folder if previous else None, 'folder', None),
        'measures': _measures(now, today),
    }


# ── Problems ─────────────────────────────────────────────────────────────────

def problems_payload():
    """Counts only, from the stored snapshots. `previous_count` is the snapshot before the latest one."""
    latest, previous = (list(DataHealthSnapshot.objects.order_by('-day')[:2]) + [None, None])[:2]
    now_counts = (latest.problems if latest else None) or {}
    old_counts = (previous.problems if previous else None) or {}
    rows = []
    for p in PROBLEMS:
        count, before = now_counts.get(p.key), old_counts.get(p.key)
        rows.append({
            'key': p.key, 'label_ar': p.label_ar, 'label_en': p.label_en, 'owner_role_ar': p.owner_role_ar,
            'link': p.link, 'note_ar': p.note_ar, 'count': count, 'previous_count': before,
            'change': (count - before) if count is not None and before is not None else None,
        })
    return {'as_of': _iso(latest.taken_at) if latest else None, 'refreshing': is_refreshing(), 'problems': rows}


# ── Rules (admin) ────────────────────────────────────────────────────────────

def file_rules_locked():
    return not settings.LIFECYCLE_FILE_RULES_ENABLED


def _line(line, preview):
    if line is None:
        return None
    out = {'at': _iso(line.run.finished_at or line.run.started_at), 'count': line.count, 'bytes': line.bytes,
           'error': line.error}
    if preview:
        out['skipped_shared'] = line.skipped_shared
    else:
        out['stopped_by_breaker'] = line.stopped_by_breaker
    return out


def rule_row(key, stored=None):
    """One register rule as the Rules tab shows it. `stored` is its LifecycleRulePolicy when already loaded."""
    rule = RULES[key]
    if stored is None:
        stored = LifecycleRulePolicy.objects.select_related('changed_by', 'changed_by__user').filter(
            rule_key=key).first()
    lines = LifecycleRunLine.objects.filter(rule_key=key).select_related('run').order_by('-pk')
    return {
        'key': key, 'label_ar': rule.label_ar, 'label_en': rule.label_en, 'kind': rule.kind, 'reason': rule.reason,
        'keep_days': policy.keep_days(key), 'minimum_days': policy.minimum_days(rule),
        'can_change_days': rule.default_days is not None and rule.kind != KIND_P56,
        'mode': policy.get_mode(key), 'stored_mode': stored.mode if stored else None,
        'locked': rule.kind == KIND_FILE and file_rules_locked(),
        'changeable': rule.kind != KIND_P56,
        'last_real': _line(lines.filter(is_preview=False).first(), preview=False),
        'last_preview': _line(lines.filter(is_preview=True).first(), preview=True),
        'preview_fresh': policy.has_fresh_preview(key),
        'changed_by': _staff_name(stored.changed_by) if stored else None,
        'changed_at': _iso(stored.changed_at) if stored else None,
        'policy_reason': stored.reason if stored else '',
    }


def rules_payload():
    stored = {p.rule_key: p for p in LifecycleRulePolicy.objects.select_related('changed_by', 'changed_by__user')}
    return {'file_rules_locked': file_rules_locked(),
            'rules': [rule_row(key, stored.get(key)) for key in RULES]}


# ── Held files (admin) ───────────────────────────────────────────────────────

def can_thumbnail(held):
    return held.rule_key in THUMBNAIL_RULES and held.primary_model in THUMBNAIL_MODELS


def held_row(held):
    """Never `hold_path`, `original_path`, `sha256` or `rows`: they name files and records."""
    rule = RULES.get(held.rule_key)
    deleted_by = getattr(held, 'deleted_by', None)      # Stage 4 adds who deleted a staff-deleted file
    return {
        'id': held.pk, 'rule_key': held.rule_key, 'rule_label_ar': rule.label_ar if rule else held.rule_key,
        'record_type_ar': _model_label_ar(held.primary_model), 'record_id': held.primary_pk or None,
        'size': held.size, 'moved_at': _iso(held.moved_at), 'purge_after': _iso(held.purge_after),
        'restored_at': _iso(held.restored_at), 'purged_at': _iso(held.purged_at),
        'deleted_by': _staff_name(deleted_by),
        'can_restore': held.restored_at is None and held.purged_at is None,
        'has_thumbnail': can_thumbnail(held),
    }


def held_payload(state='held'):
    qs = HeldFile.objects.order_by('-moved_at', '-pk')
    if state != 'all':
        qs = qs.filter(restored_at__isnull=True, purged_at__isnull=True)
    return {'total': qs.count(), 'rows': [held_row(h) for h in qs[:HELD_LIMIT]]}
