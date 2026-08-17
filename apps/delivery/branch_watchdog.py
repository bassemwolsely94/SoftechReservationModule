"""
apps/delivery/branch_watchdog.py

Lightweight reachability watchdog for branch Sybase servers.

Persists a small JSON health map in config.SystemSetting (key='crm_branch_health')
— NO new table, NO migration.  Tracks, per branch host:

    consecutive_failures   how many runs in a row it has been unreachable
    first_failed_at        ISO timestamp the current outage streak began
    last_ok_at             ISO timestamp it was last reachable
    last_error             last connection error message
    last_elapsed_ms        last connect attempt duration (ms)

After each CRM sync run, call record_run() with the per-branch outcomes.
It updates the map and returns a human-readable summary that highlights any
branch that has been down for >= CHRONIC_THRESHOLD consecutive runs — so a
chronically-offline branch is obvious at a glance in the logs.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger('elrezeiky.delivery')

_SETTING_KEY    = 'crm_branch_health'
CHRONIC_THRESHOLD = 3   # consecutive failed runs before a branch is "chronic"

# HQ / cross-branch operational roles that should always hear about outages.
_HQ_OPS_ROLES   = ['admin', 'call_center', 'purchasing', 'supervisor']
# Branch-level roles notified at OTHER branches when an outage is confirmed.
_BRANCH_EXCLUDE = ['salesperson', 'viewer', 'delivery']


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _load_health() -> dict:
    """Load the persisted health map (host → record). Empty dict if unset."""
    try:
        from apps.config.models import SystemSetting
        s = SystemSetting.objects.filter(key=_SETTING_KEY).first()
        if s:
            val = s.typed_value()
            if isinstance(val, dict):
                return val
    except Exception as exc:
        logger.debug('[watchdog] load failed: %s', exc)
    return {}


def _save_health(health: dict):
    """Persist the health map as JSON in SystemSetting (upsert)."""
    import json
    try:
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(
            key=_SETTING_KEY,
            defaults={
                'value':      json.dumps(health, ensure_ascii=False),
                'value_type': 'json',
                'label':      'حالة اتصال فروع الـ CRM',
                'description': 'يُحدَّث تلقائياً بعد كل مزامنة — تتبّع الفروع غير المتصلة',
                'category':   'general',
            },
        )
    except Exception as exc:
        logger.warning('[watchdog] save failed: %s', exc)


def _notify_branch_event(branch_id, host, kind, streak=0, since=None,
                         broadcast_branches=False):
    """
    Fire a branch-connectivity notification (reuses the platform Notification
    model — no new notification system).

    kind: 'down' | 'chronic' | 'recovered'
      down       → HQ ops roles only (may be a transient blip)
      chronic    → HQ ops + every OTHER branch (confirmed outage)
      recovered  → HQ ops + every OTHER branch (close the loop)

    Wrapped by the caller in try/except so notification errors never break sync.
    """
    from apps.notifications.models import Notification
    from apps.branches.models import Branch

    if kind == 'down':
        title = f'⚠️ تعذّر الاتصال بفرع {branch_id}'
        body  = f'خادم الفرع ({host}) لا يستجيب. قد يكون انقطاعاً مؤقتاً — ستتم إعادة المحاولة تلقائياً.'
    elif kind == 'chronic':
        title = f'🔴 فرع {branch_id} منقطع عن الشبكة'
        body  = (f'خادم الفرع ({host}) غير متصل منذ {streak} محاولات متتالية'
                 + (f' (منذ {since})' if since else '')
                 + '. يُرجى التأكد من تشغيل الخادم والشبكة بالفرع.')
    else:  # recovered
        title = f'✅ عاد اتصال فرع {branch_id}'
        body  = f'خادم الفرع ({host}) يعمل الآن بشكل طبيعي.'

    dedup = f'branchconn_{kind}_{branch_id}_{since or "now"}'

    # 1) HQ / cross-branch operations roles — one network-wide call
    Notification.send_to_roles(
        roles=_HQ_OPS_ROLES,
        notification_type='branch_connectivity',
        title=title, body=body, dedup_key=dedup,
    )

    # 2) Confirmed outage / recovery → inform the OTHER branches too
    if broadcast_branches:
        others = Branch.objects.filter(is_active=True).exclude(softech_branch_id=str(branch_id))
        for b in others:
            Notification.send_to_branch(
                branch=b,
                notification_type='branch_connectivity',
                title=title, body=body,
                exclude_roles=_BRANCH_EXCLUDE,
                include_admins=False,        # admins already covered via HQ roles
                dedup_key=dedup,
            )


def record_run(results: dict) -> str:
    """
    Update the persisted health map from one sync run's outcomes and return a
    log-ready summary string.

    Args:
        results: { host: {
                       'branch_id': str,
                       'ok':        bool,
                       'elapsed_ms': float,
                       'error':     str | None,
                   }, ... }

    Returns:
        Multi-line summary string (also logged at WARNING if any host is down).
    """
    if not results:
        return '[watchdog] no branches to check'

    health = _load_health()
    now    = _now_iso()
    down_now, chronic, recovered = [], [], []
    # Transition events to notify on AFTER state is persisted:
    #   ('down'|'chronic'|'recovered', branch_id, host, streak, since)
    transitions = []

    for host, r in results.items():
        rec = health.get(host, {})
        branch_id  = r.get('branch_id', '?')
        elapsed_ms = round(r.get('elapsed_ms', 0) or 0, 1)
        prev_fails = rec.get('consecutive_failures', 0) or 0

        if r.get('ok'):
            # Was it previously down? note recovery
            if prev_fails > 0:
                recovered.append((branch_id, host, prev_fails))
                transitions.append(('recovered', branch_id, host, prev_fails, None))
            health[host] = {
                'branch_id':            branch_id,
                'consecutive_failures': 0,
                'first_failed_at':      None,
                'last_ok_at':           now,
                'last_checked_at':      now,   # every probe, ok or not
                'last_error':           None,
                'last_elapsed_ms':      elapsed_ms,
            }
        else:
            streak    = prev_fails + 1
            first_bad = rec.get('first_failed_at') or now
            health[host] = {
                'branch_id':            branch_id,
                'consecutive_failures': streak,
                'first_failed_at':      first_bad,
                'last_ok_at':           rec.get('last_ok_at'),
                'last_checked_at':      now,   # every probe, ok or not
                'last_error':           (r.get('error') or '')[:200],
                'last_elapsed_ms':      elapsed_ms,
            }
            entry = (branch_id, host, streak, first_bad)
            down_now.append(entry)
            if streak >= CHRONIC_THRESHOLD:
                chronic.append(entry)
            # Fire on the exact transition tick only (naturally one-shot):
            if streak == 1:
                transitions.append(('down', branch_id, host, streak, first_bad))
            if streak == CHRONIC_THRESHOLD:
                transitions.append(('chronic', branch_id, host, streak, first_bad))

    _save_health(health)

    # ── Notify on transitions (down → HQ; chronic/recovered → HQ + branches) ──
    for kind, bid, host, streak, since in transitions:
        try:
            _notify_branch_event(
                bid, host, kind, streak=streak, since=since,
                broadcast_branches=(kind in ('chronic', 'recovered')),
            )
        except Exception as exc:
            logger.warning('[watchdog] notify failed (%s branch %s): %s', kind, bid, exc)

    # ── Build summary ─────────────────────────────────────────────────────────
    total = len(results)
    ok_count = total - len(down_now)
    lines = [f'[watchdog] branches reachable {ok_count}/{total}']

    # ASCII-only markers — Windows consoles default to cp1256 and would crash
    # on emoji when the summary is written to stdout.
    for branch_id, host, streak, since in sorted(down_now, key=lambda x: -x[2]):
        tag = '[CHRONIC]' if streak >= CHRONIC_THRESHOLD else '[DOWN]'
        lines.append(f'  {tag} branch {branch_id} ({host}) -- '
                     f'{streak} run(s) in a row since {since}')

    for branch_id, host, prev_streak in recovered:
        lines.append(f'  [RECOVERED] branch {branch_id} ({host}) '
                     f'(was down {prev_streak} run(s))')

    summary = '\n'.join(lines)

    if chronic:
        logger.warning(summary)
    elif down_now:
        logger.info(summary)
    else:
        logger.info(lines[0])

    return summary


def get_health_snapshot() -> dict:
    """Return the current persisted health map (for an API/status endpoint)."""
    return _load_health()
