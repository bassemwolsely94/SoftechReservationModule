"""
B7 merge queue — duplicate customer codes (PIC) proposed for merging (doc 27). READ-ONLY vs SOFTECH.

Matching reuses the probe's rules (investigate_pic_merge): codes are grouped by a real shared phone number
(mobileno / branchcustphone / personphones, placeholder numbers and numbers on > 10 codes excluded); two
codes on one number are the same customer only when the names are the same or similar — different names on
one phone are a family and are never proposed. Pairs are joined into groups (union-find).

Main code of a group (owner 2026-10-07): 1) older creation date, 2) higher points balance, 3) most recent
sale. A closed ('0') / deceased / entity (locked) code is never the main; a group with no eligible code is
skipped; deceased and entity codes are never merged at all. Every other code in the group becomes one
MergeCandidate old → main:
    strong = same name + same address (structured street/home/floor/apartment, or the same address text)
    medium = same name · review = similar name (or only linked through another code)

rebuild() upserts by old code and keeps reviewers' decisions: approved / merged / rejected rows are left
alone, open rows not found again become 'stale', and a swapped main is kept while still eligible.
"""
import logging

from django.db import transaction
from django.utils import timezone

from apps.customers.management.commands.investigate_pic_merge import (
    PLACEHOLDER_GROUP, _mask, _name_match, _norm_phone, _norm_text, _placeholder)

logger = logging.getLogger(__name__)
DB = 'SOFTECHDB9.dbo'
LOCK_KEY = 7_301_004

Q_CUSTOMERS = (f'SELECT phcode, branchcustname, mobileno, branchcustphone, branchcustaddress1, streetname1, homeno, '
               f'floorno, apartmentno, custdate, phcodestatus, piclock, picdied, picpoints, branchcode '
               f'FROM {DB}.localcustomers')
Q_PHONES = f'SELECT personcode, phoneno FROM {DB}.personphones WHERE phoneblock = 0'
Q_BALANCES = f'SELECT phcode, sum(totpoints - conpoints) FROM {DB}.localcustomerspoints GROUP BY phcode'


def _s(v):
    return str(v).strip() if v is not None else ''


def _flag(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 1 if _s(v) else 0


def load(conn):
    """HQ customers {pic: {...}}, phones {pic: set(normalized)}, balances {pic: int}."""
    cur = conn.cursor()
    cur.execute(Q_CUSTOMERS)
    custs, phones = {}, {}
    for (pic, name, m1, m2, addr, street, home, floor, apt, custdate, status, lock, died, points,
         branch) in cur.fetchall():
        pic = _s(pic)
        if not pic:
            continue
        custs[pic] = {'name': name or '', 'addr': addr or '', 'street': _s(street), 'home': _s(home),
                      'floor': _s(floor), 'apt': _s(apt), 'custdate': custdate, 'status': _s(status),
                      'locked': bool(_flag(lock)), 'died': bool(_flag(died)), 'points': bool(_flag(points)),
                      'branch': _s(branch)}
        phones[pic] = {k for k in (_norm_phone(m1), _norm_phone(m2)) if k}
    cur = conn.cursor()
    cur.execute(Q_PHONES)
    for pic, p in cur.fetchall():
        k = _norm_phone(p)
        if k and _s(pic) in phones:
            phones[_s(pic)].add(k)
    cur = conn.cursor()
    cur.execute(Q_BALANCES)
    balances = {_s(pic): int(b or 0) for pic, b in cur.fetchall()}
    return custs, phones, balances


def mergeable(c):
    """Deceased and entity codes are never merged (they mean something else)."""
    return not (c['died'] or c['status'] == '5' or c['locked'])


def eligible_main(c):
    return mergeable(c) and c['status'] != '0'


def same_address(a, b):
    if a['street'] and a['home'] and all(a[k] == b[k] for k in ('street', 'home', 'floor', 'apt')) \
            and _norm_text(a['street']) == _norm_text(b['street']):
        return True
    na = _norm_text(a['addr'])
    return bool(na) and na == _norm_text(b['addr'])


def groups(custs, phones):
    """[(sorted pics, {pic: shared masked phones})] — same/similar name on a real shared phone."""
    by_phone = {}
    for pic, ks in phones.items():
        if pic in custs and mergeable(custs[pic]):
            for k in ks:
                by_phone.setdefault(k, set()).add(pic)
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for k, pics in by_phone.items():
        if len(pics) < 2 or len(pics) > PLACEHOLDER_GROUP or _placeholder(k):
            continue
        g = sorted(pics)
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                if _name_match(custs[g[i]]['name'], custs[g[j]]['name']):
                    parent[find(g[i])] = find(g[j])
    out = {}
    for pic in parent:
        out.setdefault(find(pic), []).append(pic)
    return [sorted(v) for v in out.values() if len(v) > 1]


def _date_key(d):
    return d.isoformat() if hasattr(d, 'isoformat') else '9999'


def choose_main(pics, custs, balances, last_sale):
    """Owner's rule; None when no code in the group may be the main."""
    ok = [p for p in pics if eligible_main(custs[p])]
    if not ok:
        return None
    return min(ok, key=lambda p: (custs[p]['custdate'] is None, _date_key(custs[p]['custdate']),
                                  -balances.get(p, 0), -(last_sale.get(p).timestamp() if last_sale.get(p) else 0), p))


def strength(old, main):
    nm = _name_match(old['name'], main['name'])
    if nm == 'same':
        return 'strong' if same_address(old, main) else 'medium'
    return 'review'


def _card(pic, c, balances, last_sale):
    d = c['custdate']
    ls = last_sale.get(pic)
    return {'pic': pic, 'status': c['status'], 'branch': c['branch'], 'points_enrolled': c['points'],
            'created': d.isoformat()[:10] if hasattr(d, 'isoformat') else '', 'balance': balances.get(pic, 0),
            'last_sale': ls.isoformat()[:10] if ls else ''}


def last_sales(pics):
    from django.db.models import Max
    from .models import PurchaseHistory
    out = {}
    pics = list(pics)
    for i in range(0, len(pics), 500):
        for r in (PurchaseHistory.objects.filter(customer__softech_pic__in=pics[i:i + 500], doc_code='115')
                  .values('customer__softech_pic').annotate(last=Max('invoice_date'))):
            if r['last']:
                out[r['customer__softech_pic']] = r['last']
    return out


def build(custs, phones, balances, last_sale=None, swapped=None):
    """Pure. [{old_pic, main_pic, main_auto_pic, main_swapped, cluster, strength, facts}]."""
    swapped = swapped or {}
    gs = groups(custs, phones)
    if last_sale is None:
        last_sale = last_sales({p for g in gs for p in g})
    rows = []
    for g in gs:
        auto = choose_main(g, custs, balances, last_sale)
        if auto is None:
            continue
        main = next((swapped[p] for p in g if p in swapped and swapped[p] in g
                     and eligible_main(custs[swapped[p]])), None) or auto
        m = custs[main]
        for pic in g:
            if pic == main:
                continue
            c = custs[pic]
            shared = sorted(phones[pic] & phones[main])
            rows.append({'old_pic': pic, 'main_pic': main, 'main_auto_pic': auto, 'main_swapped': main != auto,
                         'cluster': g[0], 'strength': strength(c, m),
                         'facts': {'group': g, 'name_match': _name_match(c['name'], m['name']) or 'linked',
                                   'same_address': same_address(c, m),
                                   'shared_phones': [_mask(k) for k in shared] or ['(through another code)'],
                                   'old': _card(pic, c, balances, last_sale),
                                   'main': _card(main, m, balances, last_sale)}})
    return rows


def rebuild(conn):
    """Read HQ, rebuild the queue. Returns counts."""
    from .models import MergeCandidate as MC
    custs, phones, balances = load(conn)
    swapped = {r.old_pic: r.main_pic for r in MC.objects.filter(main_swapped=True, status__in=MC.OPEN)}
    rows = build(custs, phones, balances, swapped=swapped)
    counts = {'hq_codes': len(custs), 'candidates': len(rows), 'new': 0, 'updated': 0, 'kept': 0, 'stale': 0}
    seen = set()
    with transaction.atomic():
        existing = {r.old_pic: r for r in MC.objects.select_for_update().filter(old_pic__in=[x['old_pic'] for x in rows])}
        for x in rows:
            seen.add(x['old_pic'])
            r = existing.get(x['old_pic'])
            if r is None:
                MC.objects.create(**x)
                counts['new'] += 1
            elif r.status in (MC.APPROVED, MC.MERGED, MC.REJECTED, MC.FAILED):
                counts['kept'] += 1           # a decision stands; part 2 re-reads SOFTECH before writing
            else:
                changed = r.main_pic != x['main_pic']
                for k, v in x.items():
                    setattr(r, k, v)
                if changed or r.status == MC.STALE:      # a different pair → the old mark no longer applies
                    r.status, r.marked_by, r.marked_at = MC.PROPOSED, None, None
                r.save()
                counts['updated'] += 1
        counts['stale'] = (MC.objects.filter(status__in=MC.OPEN).exclude(old_pic__in=seen)
                           .update(status=MC.STALE, updated_at=timezone.now()))
    counts['by_strength'] = {s: sum(1 for x in rows if x['strength'] == s) for s in ('strong', 'medium', 'review')}
    return counts


def rebuild_locked():
    from apps.vouchers.coupon_dashboard import pg_lock
    from config.sybase import get_sybase_connection
    with pg_lock(LOCK_KEY) as got:
        if not got:
            return None
        conn = get_sybase_connection()
        try:
            return rebuild(conn)
        finally:
            conn.close()


# ── review (maker-checker) ─────────────────────────────────────────────────────
class ReviewError(Exception):
    pass


def roles():
    from django.conf import settings
    return list(getattr(settings, 'CUSTOMER_MERGE_ROLES', ['admin', 'supervisor', 'call_center']))


def _audit(rec, user, note, old=None, new=None):
    try:
        from apps.audit.models import AuditLog
        AuditLog.log('customer_updated', user=user, obj=rec, old_data=old, new_data=new,
                     note=f'B7 merge queue: {note}'[:255])
    except Exception:
        logger.exception('[duplicates] audit failed')


def _locked(pk):
    from .models import MergeCandidate as MC
    try:
        return MC.objects.select_for_update().get(pk=pk)
    except MC.DoesNotExist:
        raise ReviewError('غير موجود')


def mark(pk, user):
    from .models import MergeCandidate as MC
    with transaction.atomic():
        r = _locked(pk)
        if r.status != MC.PROPOSED:
            raise ReviewError(f'لا يمكن التعليم — الحالة: {r.get_status_display()}')
        r.status, r.marked_by, r.marked_at = MC.MARKED, user, timezone.now()
        r.save()
    _audit(r, user, f'{r.old_pic} → {r.main_pic} marked', {'status': MC.PROPOSED}, {'status': MC.MARKED})
    return r


def approve(pk, user):
    from .models import MergeCandidate as MC
    with transaction.atomic():
        r = _locked(pk)
        if r.status != MC.MARKED:
            raise ReviewError('الاعتماد بعد التعليم فقط')
        if r.marked_by_id == getattr(user, 'pk', None):
            raise ReviewError('لا يمكن اعتماد ما علّمته بنفسك — يعتمده مراجع آخر')
        r.status, r.approved_by, r.approved_at = MC.APPROVED, user, timezone.now()
        r.save()
    _audit(r, user, f'{r.old_pic} → {r.main_pic} approved', {'status': MC.MARKED}, {'status': MC.APPROVED})
    return r


def reject(pk, user, reason):
    from .models import MergeCandidate as MC
    reason = (reason or '').strip()
    if not reason:
        raise ReviewError('اكتب سبب الرفض')
    with transaction.atomic():
        r = _locked(pk)
        if r.status not in MC.OPEN:
            raise ReviewError(f'لا يمكن الرفض — الحالة: {r.get_status_display()}')
        old = r.status
        r.status, r.rejected_by, r.reason = MC.REJECTED, user, reason[:255]
        r.save()
    _audit(r, user, f'{r.old_pic} → {r.main_pic} rejected: {reason}', {'status': old}, {'status': MC.REJECTED})
    return r


def swap(pk, user):
    """Make this row's old code the main of its group. Every open row of the group points to the new main
    and goes back to 'proposed' (earlier marks were for another pair); the others' strength becomes
    'review' until the next rebuild re-measures it against the new main."""
    from .models import Customer, MergeCandidate as MC
    from . import account_state as AS
    with transaction.atomic():
        r = _locked(pk)
        if r.status not in MC.OPEN:
            raise ReviewError(f'لا يمكن التبديل — الحالة: {r.get_status_display()}')
        new_main, prev_main = r.old_pic, r.main_pic
        if (r.facts.get('old') or {}).get('status') == '0':
            raise ReviewError('كود مغلق لا يصبح الكود الرئيسي')
        st = AS.state(Customer.objects.filter(softech_pic=new_main).first())
        if st['blocked'] or st['code'] == 'entity':
            raise ReviewError(f'الكود {new_main}: {st["label"]} — لا يصبح الكود الرئيسي')
        group = list(MC.objects.select_for_update().filter(main_pic=prev_main, cluster=r.cluster))
        if any(g.status not in MC.OPEN for g in group):
            raise ReviewError('في المجموعة زوج معتمد بالفعل — ارفضه أولًا')
        clash = MC.objects.select_for_update().filter(old_pic=prev_main).exclude(pk=r.pk).first()
        if clash:
            if clash.status in (MC.APPROVED, MC.MERGED):
                raise ReviewError(f'{prev_main} له قرار دمج آخر')
            clash.delete()
        new_card, prev_card = r.facts.get('old') or {}, r.facts.get('main') or {}
        for g in group:
            if g.pk == r.pk:
                continue
            g.main_pic, g.main_swapped = new_main, new_main != g.main_auto_pic
            g.status, g.marked_by, g.marked_at, g.strength = MC.PROPOSED, None, None, MC.REVIEW
            g.facts = {**g.facts, 'main': new_card, 'strength_after_swap': 'measured on the next rebuild'}
            g.save()
        r.old_pic, r.main_pic, r.main_swapped = prev_main, new_main, new_main != r.main_auto_pic
        r.status, r.marked_by, r.marked_at = MC.PROPOSED, None, None
        r.facts = {**r.facts, 'old': prev_card, 'main': new_card}
        r.save()
    _audit(r, user, f'main swapped {prev_main} → {new_main} (group {r.cluster})',
           {'main_pic': prev_main}, {'main_pic': new_main})
    return r


def bulk_mark(user, strength='strong', limit=100):
    """Mark up to `limit` proposed rows of one strength (default strong only). Another reviewer approves."""
    from .models import MergeCandidate as MC
    ids = list(MC.objects.filter(status=MC.PROPOSED, strength=strength).values_list('pk', flat=True)[:max(1, limit)])
    done = 0
    for pk in ids:
        try:
            mark(pk, user)
            done += 1
        except ReviewError:
            pass
    return done


def bulk_approve(user, strength='strong', limit=100):
    """Approve up to `limit` marked rows of one strength that someone ELSE marked."""
    from .models import MergeCandidate as MC
    ids = list(MC.objects.filter(status=MC.MARKED, strength=strength).exclude(marked_by=user)
               .values_list('pk', flat=True)[:max(1, limit)])
    done = 0
    for pk in ids:
        try:
            approve(pk, user)
            done += 1
        except ReviewError:
            pass
    return done


def summary():
    from django.db.models import Count
    from .models import MergeCandidate as MC
    out = {s: {} for s, _ in MC.STATUS_CHOICES}
    for r in MC.objects.values('status', 'strength').annotate(n=Count('id')):
        out[r['status']][r['strength']] = r['n']
    return out
