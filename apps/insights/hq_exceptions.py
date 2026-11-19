"""
apps/insights/hq_exceptions.py

C32 (docs/full-project-audit/08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md §C32): one weekly HQ exception
digest — the top 10 open items by EGP across the engines that already exist, each with who acts and a
link. Nothing new is computed: every adapter reads one engine's stored output, read-only.

  returns   batches.return_calendar.calendar()      lines that close this month or were already missed
  dead      purchasing.dead_stock.latest_snapshot()  «move» and «return» lines, open buyer decisions hidden
  audit     stock_audit.StockAuditFinding            open / escalated findings, value_egp
  recon     finance.ReconException                   open / investigating, the money the flag names
  receipts  procurement.ReceiptCheck (P-31)          open / return requested, value

An adapter returns items {source, key, title, egp, owner_role, link, since, branch_code}. Within one engine
the lines of the same item × branch are summed (several batches of one item are one decision); across
engines the same item × branch is kept once, at its higher value, with every source listed. An engine
that fails is reported in `errors` and the others still rank.

Company-level: items from every branch, so only all-branch users see it (core.branch_scope.sees_everything).
PostgreSQL only — no SOFTECH read or write.
"""
import datetime as dt
import logging
from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

from apps.users.roles import ROLE_BY_KEY, role_label

logger = logging.getLogger('elrezeiky.insights')

TOP_N = 10
PER_SOURCE = 50            # each engine's biggest items that enter the ranking
CACHE_SECONDS = 15 * 60

# who acts — keys from the role registry (apps/users/roles.py), never literal lists
OWNER_PURCHASING = ROLE_BY_KEY['purchasing'].key
OWNER_QUALITY = ROLE_BY_KEY['quality_manager'].key
OWNER_FINANCE = ROLE_BY_KEY['accountant'].key

SOURCE_LABELS = {
    'returns': {'ar': 'مرتجع للمورد', 'en': 'Supplier return'},
    'dead': {'ar': 'مخزون راكد', 'en': 'Dead stock'},
    'audit': {'ar': 'تدقيق المخزون', 'en': 'Stock audit'},
    'recon': {'ar': 'تسوية الموردين', 'en': 'A/P reconciliation'},
    'receipts': {'ar': 'شراء رغم تغطية عالية', 'en': 'Bought despite cover'},
}
LINKS = {
    'returns': '/batches?tab=return_window',
    'dead': '/cash-optimization?tab=dead',
    'audit': '/stock-audit',
    'recon': '/reconciliation?tab=exceptions',
    'receipts': '/supply?tab=receipts',
}
RETURN_STATES = ('closes_this_month', 'missed')
RETURN_STATE_AR = {'closes_this_month': 'تُغلق هذا الشهر', 'missed': 'فاتت نافذتها'}
DEAD_LANES = ('move', 'return')
DEAD_LANE_AR = {'move': 'يُباع بفرع آخر', 'return': 'مرتجع للمورد'}
AUDIT_OPEN = ('open', 'escalated')
RECON_OPEN = ('open', 'investigating')     # 'investigating' is the C15 review state
RECEIPT_OPEN = ('open', 'return_requested')


def _d(v):
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return timezone.localtime(v).date().isoformat() if timezone.is_aware(v) else v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v)[:10] or None


def _money(v):
    return round(abs(float(v or 0)), 2)


def _item(source, key, title, egp, owner, since, branch_code='', item_code=''):
    return {'source': source, 'key': key, 'title': title, 'egp': _money(egp), 'owner_role': owner,
            'link': LINKS[source], 'since': _d(since), 'branch_code': branch_code or '', 'item_code': item_code or ''}


def _item_key(item_code, branch_code):
    return f'item:{item_code}|{branch_code}'


def _summed(rows):
    """Sum one engine's rows per key (item × branch): value added, earliest `since`, first title."""
    out = {}
    for r in rows:
        cur = out.get(r['key'])
        if cur is None:
            out[r['key']] = dict(r, count=1)
            continue
        cur['egp'] = round(cur['egp'] + r['egp'], 2)
        cur['count'] += 1
        if r['since'] and (not cur['since'] or r['since'] < cur['since']):
            cur['since'] = r['since']
    items = sorted(out.values(), key=lambda x: (-x['egp'], x['key']))
    return [i for i in items if i['egp'] > 0][:PER_SOURCE]


# ── Adapters (one per engine, read-only) ─────────────────────────────────────

def returns_items(today=None):
    from apps.batches.return_calendar import calendar
    rows = []
    for l in calendar(today=today)['lines']:
        if l['state'] not in RETURN_STATES:
            continue
        if l['record'] and l['record']['status'] in ('done', 'cancelled'):
            continue
        name = l['item_name'] or l['item_code']
        title = f"{name} — {RETURN_STATE_AR[l['state']]}"
        if l['supplier_name'] or l['supplier_code']:
            title += f" ({l['supplier_name'] or l['supplier_code']})"
        rows.append(_item('returns', _item_key(l['item_code'], l['branch_code']), title, l['value'],
                          OWNER_PURCHASING, l['closes'], l['branch_code'], l['item_code']))
    return _summed(rows)


def dead_items(today=None):
    from apps.purchasing import dead_stock as DS
    from apps.purchasing.dead_stock_views import _decided, _open_decisions
    snap = DS.latest_snapshot()
    if snap is None:
        return []
    decided = _decided(_open_decisions(today or timezone.localdate()))
    rows = []
    for l in snap.lines.filter(lane__in=DEAD_LANES).select_related('item'):
        if decided.get((l.item_id, l.branch_code)) or decided.get((l.item_id, '')):
            continue                      # a buyer already decided (excluded / kept) — the tab hides it too
        code = l.item.softech_id
        rows.append(_item('dead', _item_key(code, l.branch_code), f'{l.item.name} — {DEAD_LANE_AR[l.lane]}',
                          l.value, OWNER_PURCHASING, l.last_sale_date or l.oldest_arrival_date, l.branch_code, code))
    return _summed(rows)


def audit_items(today=None):
    from apps.stock_audit.models import StockAuditFinding
    rows = []
    qs = (StockAuditFinding.objects.filter(status__in=AUDIT_OPEN, value_egp__gt=0)
          .select_related('item').order_by('-value_egp')[:PER_SOURCE * 4])
    for f in qs:
        name = f.item.name if f.item_id else (f.itemcode or '')
        title = (f.message_ar or f.rule_code).strip()
        if name and name not in title:
            title = f'{name} — {title}'
        key = _item_key(f.itemcode, f.branchcode) if f.itemcode else f'audit:{f.pk}'
        rows.append(_item('audit', key, title[:200], f.value_egp, OWNER_QUALITY, f.first_seen, f.branchcode,
                          f.itemcode))
    return _summed(rows)


def recon_money(exc):
    """The money the flag names: the payment it points at, else the invoice."""
    if exc.payment_id:
        return exc.payment.amount
    if exc.invoice_id:
        return exc.invoice.doc_value
    return 0


def recon_items(today=None):
    from apps.finance.recon_models import ReconException
    rows = []
    qs = (ReconException.objects.filter(status__in=RECON_OPEN)
          .select_related('party', 'invoice', 'payment').order_by('-created_at'))
    for e in qs.iterator(chunk_size=500):
        party = e.party.name if e.party_id else ''
        title = e.get_exception_type_display() + (f' — {party}' if party else '')
        branch = (e.invoice.branchcode if e.invoice_id else '') or (e.payment.branchcode if e.payment_id else '')
        rows.append(_item('recon', f'recon:{e.pk}', title, recon_money(e), OWNER_FINANCE, e.created_at, branch))
    return _summed(rows)


def receipt_items(today=None):
    from apps.catalog.models import Item
    from apps.procurement.models import ReceiptCheck
    checks = list(ReceiptCheck.objects.filter(status__in=RECEIPT_OPEN, value__gt=0).order_by('-value')[:PER_SOURCE * 4])
    names = dict(Item.objects.filter(softech_id__in={c.item_code for c in checks}).values_list('softech_id', 'name'))
    rows = [_item('receipts', _item_key(c.item_code, c.branch_code),
                  f"{names.get(c.item_code, c.item_code)} — {c.get_flag_display()}", c.value, OWNER_PURCHASING,
                  c.doc_date, c.branch_code, c.item_code) for c in checks]
    return _summed(rows)


# (source, adapter name) — looked up at call time so one engine can be stubbed in tests
ADAPTERS = (('returns', 'returns_items'), ('dead', 'dead_items'), ('audit', 'audit_items'),
            ('recon', 'recon_items'), ('receipts', 'receipt_items'))


# ── Ranking ─────────────────────────────────────────────────────────────────

def rank(items, top=TOP_N):
    """Merge the engines' items: one row per key at its highest value, every source listed (biggest first),
    then the top `top` by EGP."""
    by_key = defaultdict(list)
    for i in items:
        by_key[i['key']].append(i)
    merged = []
    for key, group in by_key.items():
        group.sort(key=lambda x: (-x['egp'], x['source']))
        best = dict(group[0])
        best['sources'] = [{'source': g['source'], 'egp': g['egp'], 'link': g['link'],
                            'owner_role': g['owner_role']} for g in group]
        merged.append(best)
    merged.sort(key=lambda x: (-x['egp'], x['source'], x['key']))
    return merged[:top]


def _labelled(rows):
    from apps.branches.models import Branch
    names = dict(Branch.objects.values_list('softech_branch_id', 'name'))
    for n, r in enumerate(rows, 1):
        r['rank'] = n
        r['branch_name'] = names.get(r['branch_code'], r['branch_code']) if r['branch_code'] else ''
        r['owner_label'] = role_label(r['owner_role'])
        r['owner_label_en'] = role_label(r['owner_role'], 'en')
        r['source_label'] = SOURCE_LABELS[r['source']]['ar']
        r['source_label_en'] = SOURCE_LABELS[r['source']]['en']
        for s in r.get('sources', []):
            s['label'] = SOURCE_LABELS[s['source']]['ar']
    return rows


def build(today=None, top=TOP_N):
    """{'as_of', 'items': [top N], 'totals': {source: {count, egp}}, 'errors': [source]}."""
    today = today or timezone.localdate()
    every, totals, errors = [], {}, []
    for source, name in ADAPTERS:
        try:
            got = globals()[name](today=today)
        except Exception as exc:                    # one broken engine must not hide the others
            logger.warning('[hq exceptions] %s adapter failed: %s', source, exc)
            errors.append(source)
            continue
        every.extend(got)
        totals[source] = {'count': len(got), 'egp': round(sum(i['egp'] for i in got), 2),
                          'label': SOURCE_LABELS[source]['ar'], 'link': LINKS[source]}
    return {'as_of': today.isoformat(), 'items': _labelled(rank(every, top)), 'totals': totals, 'errors': errors}


def cached(refresh=False):
    from django.core.cache import cache
    key = f'hq_exceptions:{timezone.localdate().isoformat()}'
    data = None if refresh else cache.get(key)
    if data is None:
        data = build()
        cache.set(key, data, CACHE_SECONDS)
    return data


# ── Weekly digest (Sunday) ───────────────────────────────────────────────────

def _setting(key, default):
    try:
        from apps.config.models import SystemSetting
        return SystemSetting.get(key, default)
    except Exception:
        return default


def digest_recipients():
    """SystemSetting hq_exception_digest_recipients (StaffProfile ids), else the roles registry's HQ digest
    roles. Company-level money, so only all-branch users ever receive it."""
    from apps.users.models import StaffProfile
    from apps.users.roles import HQ_DIGEST_ROLES
    from core.branch_scope import sees_everything
    ids = _setting('hq_exception_digest_recipients', None)
    if isinstance(ids, list) and ids:
        qs = StaffProfile.objects.filter(pk__in=ids, is_active=True)
    else:
        qs = StaffProfile.objects.filter(role__in=sorted(HQ_DIGEST_ROLES), is_active=True)
    return [p for p in qs.select_related('user') if sees_everything(p)]


def digest_body(data):
    lines = [f"{r['rank']}. {r['title']} — {round(r['egp']):,} ج"
             + (f" — {r['branch_name']}" if r['branch_name'] else '')
             + f" — يتصرّف: {r['owner_label']}"
             + (f" (يظهر أيضًا في {'، '.join(s['label'] for s in r['sources'][1:])})" if len(r['sources']) > 1 else '')
             for r in data['items']]
    total = round(sum(r['egp'] for r in data['items']))
    body = '\n'.join(lines) + f"\n\nالإجمالي {total:,} ج."
    if data['errors']:
        body += '\nلم يُقرأ: ' + '، '.join(SOURCE_LABELS[s]['ar'] for s in data['errors']) + '.'
    return body + '\nافتح «التقارير السردية» ← «💰 استثناءات الأسبوع» للروابط.'


def week_start(day):
    """The Sunday that starts `day`'s week. The digest week runs Sunday → Saturday: an ISO week ends ON
    Sunday, so a Sunday send and a Monday re-run (misfire grace, by hand) would fall in two ISO weeks."""
    return day - dt.timedelta(days=(day.weekday() + 1) % 7)


def send_weekly(today=None):
    """Sunday: one digest per recipient, once per Sunday-start week. Returns the count sent."""
    from apps.notifications.models import Notification
    today = today or timezone.localdate()
    data = build(today=today)
    if not data['items']:
        return 0
    week = week_start(today)
    title = f"💰 أكبر {len(data['items'])} استثناءات بالجنيه — أسبوع {week.isoformat()}"
    body = digest_body(data)
    sent = 0
    for staff in digest_recipients():
        n = Notification.send_to_user(staff, 'hq_exception_digest', title, body,
                                      dedup_key=f'hq_exception_digest_{week.isoformat()}', dedup_once=True)
        sent += int(n is not None)
    return sent
