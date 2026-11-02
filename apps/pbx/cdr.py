"""
apps/pbx/cdr.py — Issabel CDR mirror → CdrCall, linked to PICs.

The PBX's own CDR table (asteriskcdrdb.cdr, read-only via config/issabel.py) is the
authority for call history: it records every call even while our AMI bridge is down.
This module copies the customer-facing legs into pbx.CdrCall and links each to a PIC.

Classification of one CDR row (Issabel/FreePBX dialplan):
  • channel is a gateway (GoIP / Grandstream / DAHDI) → INBOUND; customer = src
      - no dstchannel → the caller hung up in the IVR/queue before any agent → abandoned
      - agent extension = peer of dstchannel (SIP/15 → 15, Local/170@from-queue → 170)
  • dstchannel is a gateway → OUTBOUND; customer = dst minus the route prefix
      (8201003118567 → 01003118567); agent extension = peer of channel
  • neither → internal ext↔ext call → skipped
  • dcontext from-internal-xfer → a transfer leg (stored, never counted as a new call)

PIC link (shared numbers): a phone on several PICs is counted ONCE, on the PIC that
bought most recently on/before the call date ('shared_latest'); if none bought before,
the first to buy after it ('shared_next'); never bought → no PIC ('shared_unresolved').
Every PIC on the number is kept in CdrCall.shared_pics for display.
"""
import hashlib
import logging
import re
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Max, Q
from django.utils import timezone

logger = logging.getLogger('elrezeiky.pbx.cdr')

BACKFILL_FROM = '2024-08-01'          # sales history starts here (customers.PurchaseHistory)
OVERLAP = timedelta(hours=3)          # CDR rows land at hang-up, stamped with the START time
SALE_DOC = '115'

_PEER_RE = re.compile(r'^(?:SIP|PJSIP|IAX2|DAHDI|Local)/([^-@/;]+)', re.I)
_ROUTE_RE = re.compile(r'^8\d(0\d{8,10})$')     # outbound route prefix 81/82/83… + national number
_GATEWAY_HINTS = ('goip', 'grandstream', 'trunk')


# ── pure helpers (unit-tested) ─────────────────────────────────────────────────

def peer_of(channel: str) -> str:
    m = _PEER_RE.match(channel or '')
    return m.group(1) if m else ''


def is_gateway(channel: str, gateways=frozenset()) -> bool:
    if not channel:
        return False
    if channel.upper().startswith('DAHDI/'):
        return True
    peer = peer_of(channel)
    return bool(peer) and (peer in gateways or peer.lower().startswith(_GATEWAY_HINTS))


def phone_key(number: str) -> str:
    """Comparable key for a phone: digits, no country code / leading zeros, last 10.
    '01003118567', '+201003118567', '1003118567' → '1003118567'; too short → ''."""
    d = re.sub(r'\D', '', number or '')
    if d.startswith('0020'):
        d = d[4:]
    elif d.startswith('20') and len(d) == 12:
        d = d[2:]
    d = d.lstrip('0')
    return d[-10:] if len(d) >= 7 else ''


def outbound_number(dst: str) -> str:
    d = re.sub(r'\D', '', dst or '')
    m = _ROUTE_RE.match(d)
    return m.group(1) if m else d


def inbound_number(src: str, meta=None) -> str:
    num = (src or '').strip()
    if not re.search(r'\d', num):          # 'unknown', 'anonymous', withheld
        return ''
    if meta:
        if meta.get('prefix') and num.startswith(meta['prefix']):
            num = num[len(meta['prefix']):]
        if meta.get('suffix') and num.endswith(meta['suffix']):
            num = num[:-len(meta['suffix'])]
    return re.sub(r'[^\d+]', '', num)


_DISPOSITION = {'ANSWERED': 'answered', 'BUSY': 'busy', 'NO ANSWER': 'no_answer'}


def classify(row: dict, gateways=frozenset(), gw_meta=None):
    """One CDR row → CdrCall field dict, or None for an internal call."""
    ch, dch = row.get('channel') or '', row.get('dstchannel') or ''
    disp = (row.get('disposition') or '').upper()
    dcontext = row.get('dcontext') or ''
    if is_gateway(ch, gateways):
        direction, gateway = 'inbound', peer_of(ch)
        number = inbound_number(row.get('src'), (gw_meta or {}).get(gateway))
        agent_ext = peer_of(dch)
        agent_name = row.get('dst_cnam') or ''
        status = 'abandoned' if not dch else _DISPOSITION.get(disp, 'failed')
    elif is_gateway(dch, gateways):
        direction, gateway = 'outbound', peer_of(dch)
        number = outbound_number(row.get('dst'))
        agent_ext = peer_of(ch) or (row.get('src') or '')[:20]
        agent_name = row.get('cnam') or ''
        status = _DISPOSITION.get(disp, 'failed')
    else:
        return None
    duration = int(row.get('duration') or 0)
    billsec = int(row.get('billsec') or 0)
    return {
        'direction': direction,
        'status': status,
        'is_transfer': dcontext.startswith('from-internal-xfer'),
        'customer_number': number[:30],
        'phone_key': phone_key(number),
        'agent_ext': agent_ext[:20],
        'agent_name': agent_name[:100],
        'queue': (row.get('dst') or '')[:50] if dcontext == 'ext-queues' else '',
        'gateway': gateway[:30],
        'duration_seconds': max(0, duration),
        'billable_seconds': max(0, billsec),
        'recording_file': (row.get('recordingfile') or '')[:255],
        'src': (row.get('src') or '')[:80], 'dst': (row.get('dst') or '')[:80],
        'dcontext': dcontext[:80], 'channel': ch[:80], 'dstchannel': dch[:80],
        'lastapp': (row.get('lastapp') or '')[:80], 'disposition': disp[:45],
        'unique_id': (row.get('uniqueid') or '')[:50],
    }


def cdr_key(row: dict) -> str:
    ident = '|'.join(str(row.get(k) or '') for k in
                     ('uniqueid', 'calldate', 'channel', 'dstchannel', 'dst'))
    return hashlib.sha1(ident.encode('utf-8'), usedforsecurity=False).hexdigest()


def pick_latest_buyer(pics, purchase_dates, on_date):
    """(pic, match) for a number shared by `pics` — see module docstring."""
    best = None
    for p in pics:
        ds = purchase_dates.get(p, ())
        i = bisect_right(ds, on_date)
        if i and (best is None or ds[i - 1] > best[0]):
            best = (ds[i - 1], p)
    if best:
        return best[1], 'shared_latest'
    nxt = None
    for p in pics:
        ds = purchase_dates.get(p, ())
        i = bisect_right(ds, on_date)
        if i < len(ds) and (nxt is None or ds[i] < nxt[0]):
            nxt = (ds[i], p)
    if nxt:
        return nxt[1], 'shared_next'
    return '', 'shared_unresolved'


# ── PIC resolver ───────────────────────────────────────────────────────────────

class PicResolver:
    """phone_key → PICs, plus the purchase dates of PICs that share a number.
    `keys` limits the load to those numbers (live bridge: one call)."""

    def __init__(self, keys=None):
        from apps.customers.models import Customer, PurchaseHistory
        qs = (Customer.objects.filter(is_account_placeholder=False, merged_into_pic='')
              .exclude(softech_pic__isnull=True).exclude(softech_pic=''))
        if keys is not None:
            keys = {k for k in keys if k}
            if not keys:
                qs = qs.none()
            else:
                cond = Q()
                for k in keys:
                    cond |= Q(phone__endswith=k) | Q(phone_alt__endswith=k) | Q(whatsapp_phone__endswith=k)
                qs = qs.filter(cond)
        self.by_key = defaultdict(set)
        self.customer_id = {}
        for cid, pic, *phones in qs.values_list('id', 'softech_pic', 'phone', 'phone_alt', 'whatsapp_phone').iterator(chunk_size=5000):
            self.customer_id[pic] = cid
            for ph in phones:
                k = phone_key(ph)
                if k and (keys is None or k in keys):
                    self.by_key[k].add(pic)
        shared = sorted({p for v in self.by_key.values() if len(v) > 1 for p in v})
        dates = defaultdict(set)
        for i in range(0, len(shared), 5000):
            for pic, d in (PurchaseHistory.objects
                           .filter(softech_phcode__in=shared[i:i + 5000], doc_code=SALE_DOC,
                                   invoice_date__isnull=False)
                           .values_list('softech_phcode', 'invoice_date')):
                dates[pic].add(timezone.localtime(d).date())
        self.purchase_dates = {p: sorted(ds) for p, ds in dates.items()}

    def resolve(self, key, on_date):
        """→ (pic, customer_id, match, shared_pics)."""
        if not key:
            return '', None, 'no_number', []
        pics = self.by_key.get(key)
        if not pics:
            return '', None, 'none', []
        if len(pics) == 1:
            pic = next(iter(pics))
            return pic, self.customer_id.get(pic), 'single', []
        ordered = sorted(pics)
        pic, match = pick_latest_buyer(ordered, self.purchase_dates, on_date)
        return pic, self.customer_id.get(pic), match, ordered


def resolve_number(number, at=None):
    """Single-call PIC resolution (live AMI bridge)."""
    key = phone_key(number)
    at = timezone.localtime(at or timezone.now()).date()
    return PicResolver(keys={key}).resolve(key, at)


# ── sync ──────────────────────────────────────────────────────────────────────

def _gateway_registry():
    from apps.pbx.models import AgentExtension
    gateways, meta = set(), {}
    for ae in AgentExtension.objects.filter(extension_type=AgentExtension.TYPE_GATEWAY):
        for name in filter(None, (ae.extension, ae.sip_peer)):
            gateways.add(name)
            meta[name] = {'prefix': ae.call_prefix or '', 'suffix': ae.call_suffix or ''}
    return frozenset(gateways), meta


def _fetch(start, end):
    from decouple import config
    from config.issabel import get_cdr_connection
    table = config('ISSABEL_CDR_TABLE', default='cdr')
    if not re.fullmatch(r'\w+', table):      # an identifier can't be bound — validate the .env value
        raise ValueError(f'ISSABEL_CDR_TABLE is not a table name: {table!r}')
    sql = f'SELECT * FROM {table} WHERE calldate >= %s AND calldate < %s ORDER BY calldate'  # nosec B608 — validated identifier, values bound
    conn = get_cdr_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql,
                        (start.strftime('%Y-%m-%d %H:%M:%S'), end.strftime('%Y-%m-%d %H:%M:%S')))
            return cur.fetchall()
    finally:
        conn.close()


_UPDATE_FIELDS = ['unique_id', 'call_at', 'direction', 'status', 'is_transfer', 'customer_number',
                  'phone_key', 'agent_ext', 'agent_name', 'queue', 'gateway', 'duration_seconds',
                  'billable_seconds', 'recording_file', 'src', 'dst', 'dcontext', 'channel',
                  'dstchannel', 'lastapp', 'disposition', 'customer', 'pic', 'pic_match',
                  'shared_pics', 'synced_at']


def store_rows(rows, resolver, gateways=frozenset(), gw_meta=None):
    """Classify + resolve + upsert CDR rows. Returns (stored, names Counter)."""
    from apps.pbx.models import CdrCall
    tz = timezone.get_current_timezone()
    objs, names = [], Counter()
    for row in rows:
        f = classify(row, gateways, gw_meta)
        if f is None:
            continue
        calldate = row.get('calldate')
        if isinstance(calldate, str):
            calldate = datetime.strptime(calldate[:19], '%Y-%m-%d %H:%M:%S')
        call_at = timezone.make_aware(calldate, tz) if timezone.is_naive(calldate) else calldate
        pic, cid, match, shared = resolver.resolve(f['phone_key'], timezone.localtime(call_at).date())
        if f['direction'] == 'outbound' and f['agent_ext'] and f['agent_name']:
            names[(f['agent_ext'], f['agent_name'])] += 1
        objs.append(CdrCall(cdr_key=cdr_key(row), call_at=call_at, customer_id=cid, pic=pic,
                            pic_match=match, shared_pics=shared, synced_at=timezone.now(), **f))
    if objs:
        CdrCall.objects.bulk_create(objs, batch_size=1000, update_conflicts=True,
                                    unique_fields=['cdr_key'], update_fields=_UPDATE_FIELDS)
    return len(objs), names


def _record_pbx_names(names: Counter):
    """Most-used CDR caller name per extension → AgentExtension.pbx_name (staff suggestions)."""
    from apps.pbx.models import AgentExtension
    best = {}
    for (ext, name), n in names.most_common():
        best.setdefault(ext, name)
    for ae in AgentExtension.objects.filter(extension__in=list(best)):
        if ae.pbx_name != best[ae.extension]:
            ae.pbx_name = best[ae.extension]
            ae.save(update_fields=['pbx_name', 'updated_at'])


def sync_cdr(since=None, until=None, chunk_days=7, log=None):
    """Copy CDR rows in [since, until) (default: from the newest stored call − 3 h, or
    BACKFILL_FROM on an empty mirror, to now). Idempotent upsert on cdr_key."""
    from apps.pbx.models import CdrCall, CdrSyncRun
    tz = timezone.get_current_timezone()
    now = timezone.localtime().replace(tzinfo=None)
    if since is None:
        newest = CdrCall.objects.aggregate(m=Max('call_at'))['m']
        since = (timezone.localtime(newest).replace(tzinfo=None) - OVERLAP) if newest else \
            datetime.strptime(getattr(settings, 'PBX_CDR_BACKFILL_FROM', BACKFILL_FROM), '%Y-%m-%d')
    until = until or now
    run = CdrSyncRun.objects.create(window_from=timezone.make_aware(since, tz),
                                    window_to=timezone.make_aware(until, tz))
    try:
        gateways, gw_meta = _gateway_registry()
        resolver = PicResolver()
        names = Counter()
        start = since
        while start < until:
            end = min(start + timedelta(days=chunk_days), until)
            rows = _fetch(start, end)
            stored, n = store_rows(rows, resolver, gateways, gw_meta)
            run.fetched += len(rows)
            run.stored += stored
            names.update(n)
            run.save(update_fields=['fetched', 'stored'])
            if log:
                log(f'{start:%Y-%m-%d} → {end:%Y-%m-%d}: {len(rows)} CDR rows, {stored} customer calls')
            start = end
        _record_pbx_names(names)
        run.status = 'success'
    except Exception as exc:
        run.status, run.error = 'failed', str(exc)[:2000]
        logger.warning('CDR sync failed: %s', exc)
    run.finished_at = timezone.now()
    run.save()
    return run


def relink_all(resolver=None, log=None):
    """Re-resolve every stored call's PIC (new customers / new purchases change the
    answer for unmatched and shared numbers). Returns the number of changed rows."""
    from apps.pbx.models import CdrCall
    resolver = resolver or PicResolver()
    changed, batch = 0, []
    fields = ('id', 'phone_key', 'call_at', 'pic', 'pic_match', 'shared_pics', 'customer_id')
    for cid, key, call_at, pic, match, shared, cust in CdrCall.objects.values_list(*fields).iterator(chunk_size=5000):
        npic, ncust, nmatch, nshared = resolver.resolve(key, timezone.localtime(call_at).date())
        if (npic, nmatch, nshared, ncust) != (pic, match, shared, cust):
            batch.append(CdrCall(id=cid, pic=npic, pic_match=nmatch, shared_pics=nshared, customer_id=ncust))
        if len(batch) >= 2000:
            CdrCall.objects.bulk_update(batch, ['pic', 'pic_match', 'shared_pics', 'customer'])
            changed += len(batch)
            batch = []
    if batch:
        CdrCall.objects.bulk_update(batch, ['pic', 'pic_match', 'shared_pics', 'customer'])
        changed += len(batch)
    if log:
        log(f'relinked {changed} calls')
    return changed


# ── bridge watch ──────────────────────────────────────────────────────────────

SILENCE_MINUTES = 30


def bridge_silent_while_pbx_busy(now=None):
    """True when the PBX logged customer calls in the last SILENCE_MINUTES (its CDR) but
    the AMI bridge heard nothing in that time — the live screens (call pop-up, wallboard)
    are blind. Quiet hours raise nothing: no calls in the CDR → no alarm."""
    from apps.pbx.models import CdrCall, PBXBridgeStatus
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=SILENCE_MINUTES)
    if not CdrCall.objects.filter(call_at__gte=cutoff).exists():
        return False
    st = PBXBridgeStatus.current()
    return not (st and st.last_event_at and st.last_event_at >= cutoff)


def notify_bridge_silence(now=None):
    """Alert admins + supervisors once per hour while the bridge is silent."""
    if not bridge_silent_while_pbx_busy(now):
        return 0
    from apps.notifications.models import Notification
    from apps.pbx.models import PBXBridgeStatus
    from apps.users.models import StaffProfile
    local = timezone.localtime(now or timezone.now())
    st = PBXBridgeStatus.current()
    last = timezone.localtime(st.last_event_at).strftime('%Y-%m-%d %H:%M') if st and st.last_event_at else '—'
    sent = 0
    for staff in StaffProfile.objects.filter(role__in=['admin', 'supervisor'], is_active=True):
        if Notification.send_to_user(
                staff, 'system', '📞 جسر السنترال لا يستقبل المكالمات',
                f'السنترال سجّل مكالمات عملاء خلال آخر {SILENCE_MINUTES} دقيقة، لكن الجسر لم يستلم أي حدث '
                f'منذ {last}. نافذة المكالمة المنبثقة ولوحة المشرف لا تعملان — أعد تشغيل run_ami_bridge. '
                f'تقارير المكالمات لا تتأثر (تُقرأ من سجل السنترال).',
                dedup_key=f'pbx_bridge_silent_{local:%Y%m%d%H}', dedup_once=True):
            sent += 1
    return sent
