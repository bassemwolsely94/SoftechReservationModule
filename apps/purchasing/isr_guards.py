"""
apps/purchasing/isr_guards.py — guards on ISR drafts (IsrPush) so nothing is posted to
SOFTECH twice (doc 30 phase A, owner 2026-10-24).

Found 2026-10-24: drafts #30 and #32 were identical copies of #29 (HQ → 160, 5,174 lines),
which was already PUSHED — approving either would have sent the same ISR again; «توليد» in
«التوزيعة» pressed twice made every draft twice; the transfer pairing made an HQ → HQ leg.

  • route rules — self: source = destination; HQ → branch: source 100, destination a
    branch; branch → HQ: destination 100, source a branch. Anything else is refused.
  • one LIVE general draft per route (kind, source, destination) — "general" = not tied
    to a branch request (origin_isr) or a WhatsApp request (origin_request); those have
    their own per-request rules. A new draft SUPERSEDES an older PROPOSED one (cancelled,
    linked, audited); an APPROVED one blocks — a person signed it off, so it must be pushed
    or cancelled first. A partial unique constraint backs this up in the database.
  • push guard — a draft whose lines are identical to an ISR pushed on the same route in
    the last DUP_PUSH_DAYS days is refused unless a reason is given (then recorded).
  • overlap guard (P-32 §2.4) — a draft that shares SOME items with an ISR pushed to the same destination
    (same kind) in the last DUP_PUSH_DAYS days and not yet dispensed (owner 2026-11-01; dispensed = the source
    issued the item to that destination after the push, stock-ledger doc 125) is refused unless a reason is
    given (then recorded). Off until
    the owner confirms the rule: SystemSetting `isr_overlap_guard` = on. `report_isr_overlaps` measures it.
  • leg order — the HQ → branch leg of a transfer is pushed only after its branch → HQ
    leg (the goods must be on their way to HQ before HQ sends them on).
  • cancel — any unpushed draft, with a reason, audited.
"""
import hashlib
import logging
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.utils import timezone

logger = logging.getLogger('elrezeiky.purchasing')

HQ = '100'
DUP_PUSH_DAYS = 7
LIVE = ('proposed', 'approved')
MIN_REASON = 5


class GuardError(ValueError):
    """A draft or push the guards refuse. `code` lets the screen react (e.g. offer a reason)."""

    def __init__(self, message, *, code='refused', other=None):
        super().__init__(message)
        self.code = code
        self.other = other


def validate_route(kind, source, dest):
    from apps.purchasing.models import IsrPush as P
    source, dest = str(source or '').strip(), str(dest or '').strip()
    if kind == P.KIND_SELF:
        ok = bool(source) and dest in ('', source)
    elif kind == P.KIND_HQ_TO_BRANCH:
        ok = source == HQ and bool(dest) and dest != HQ
    elif kind == P.KIND_BRANCH_TO_HQ:
        ok = dest == HQ and bool(source) and source != HQ
    else:
        ok = False
    if not ok:
        raise GuardError(f'مسار غير صالح لطلب التوريد: {source or "؟"} ← {dest or "؟"} ({kind}).', code='bad_route')


def _general(qs):
    return qs.filter(origin_isr__isnull=True, origin_request__isnull=True, origin_shortage_list__isnull=True)


def live_on_route(kind, source, dest, *, exclude=None):
    from apps.purchasing.models import IsrPush as P
    qs = _general(P.objects.filter(kind=kind, branchcode=str(source), dest_branchcode=str(dest or ''),
                                   status__in=LIVE))
    return qs.exclude(pk=exclude) if exclude else qs


PLANNER_AR = {'replenishment': 'طلبات التوريد', 'distribution': 'التوزيعة', 'transfer': 'تحويلات المحرك'}


def check_route_free(kind, source, dest, *, planner=None):
    """Before a new general draft: refuse when an APPROVED one waits on the route, or (P-32 §2.3) when a PROPOSED
    one from ANOTHER planner waits there — it is no longer silently cancelled. Return the PROPOSED drafts the new
    draft will supersede (same planner, or drafts made before planners were recorded)."""
    live = list(live_on_route(kind, source, dest).select_for_update())
    approved = [p for p in live if p.status == 'approved']
    if approved:
        raise GuardError(f'يوجد طلب توريد معتمد #{approved[0].pk} لنفس المسار ({source} ← {dest or source}) '
                         f'لم يُرحَّل بعد — رحّله أو ألغه أولاً.', code='approved_exists', other=approved[0].pk)
    proposed = [p for p in live if p.status == 'proposed']
    if planner:
        other = next((p for p in proposed if (p.params or {}).get('planner') not in (None, '', planner)), None)
        if other is not None:
            who = PLANNER_AR.get(other.params['planner'], other.params['planner'])
            raise GuardError(f'يوجد طلب مقترح #{other.pk} من «{who}» لنفس المسار ({source} ← {dest or source}) — '
                             f'لن يُلغى تلقائياً. راجعه أو ألغه أولاً.', code='other_planner', other=other.pk)
    return proposed


def _audit(action, obj, *, user=None, note='', changes=None, extra=None):
    try:
        from apps.audit.models import AuditLog
        staff = getattr(user, 'staff_profile', None) if user is not None else None
        AuditLog.log(action, user=staff, obj=obj, changes=changes, note=(note or '')[:255], extra=extra)
    except Exception:
        logger.warning('isr guard audit failed for %s', getattr(obj, 'pk', None))


def retire(old_drafts, *, user=None):
    """Cancel the older PROPOSED drafts on a route BEFORE the new one is saved (the database
    allows only one live draft per route at any moment). Same transaction as the create."""
    for p in old_drafts:
        _cancel(p, user=user, reason='استُبدل بطلب أحدث لنفس المسار')


def link_superseded(old_drafts, new):
    """After the new draft exists: point each retired draft at it."""
    for p in old_drafts:
        params = dict(p.params or {})
        params.setdefault('cancelled', {})['superseded_by'] = new.pk
        p.params = params
        p.notes = (p.notes or '').replace('استُبدل بطلب أحدث لنفس المسار', f'استُبدل بالطلب #{new.pk} (نفس المسار)')
        p.save(update_fields=['params', 'notes'])


def _cancel(p, *, user=None, reason='', superseded_by=None):
    before = p.status
    p.status = p.STATUS_CANCELLED
    params = dict(p.params or {})
    params['cancelled'] = {'at': timezone.now().isoformat(), 'by': getattr(user, 'username', None),
                           'reason': reason, **({'superseded_by': superseded_by} if superseded_by else {})}
    p.params = params
    p.notes = (f'{p.notes}\n' if p.notes else '') + f'ملغى: {reason}'
    p.save(update_fields=['status', 'params', 'notes'])
    _audit('isr_draft_cancelled', p, user=user, note=reason, changes={'status': [before, p.status]},
           extra={'superseded_by': superseded_by})


def cancel(p, *, user, reason):
    """A person cancels an unpushed draft (reason required)."""
    reason = (reason or '').strip()
    if len(reason) < MIN_REASON:
        raise GuardError('اكتب سبب الإلغاء.', code='reason_required')
    if p.status not in ('proposed', 'approved', 'failed'):
        raise GuardError(f'لا يمكن إلغاء طلب حالته {p.get_status_display()}.', code='bad_status')
    _cancel(p, user=user, reason=reason)
    return p


def fingerprint(lines) -> str:
    """Same items and whole-pack quantities = the same ISR, whatever the line order."""
    key = '|'.join(sorted(f"{str(l.get('itemcode') or '').strip()}:{int(round(float(l.get('itemqty') or 0)))}"
                          for l in (lines or [])))
    return hashlib.sha1(key.encode('utf-8')).hexdigest()


def duplicate_pushed(p):
    """An ISR already PUSHED on the same route in the last DUP_PUSH_DAYS days with the same lines."""
    from apps.purchasing.models import IsrPush as P
    since = timezone.now() - timedelta(days=DUP_PUSH_DAYS)
    fp = fingerprint(p.lines_snapshot)
    for o in (P.objects.filter(kind=p.kind, branchcode=p.branchcode, dest_branchcode=p.dest_branchcode,
                               status=P.STATUS_PUSHED, pushed_at__gte=since).exclude(pk=p.pk)
              .only('id', 'lines_snapshot', 'isrdocnumber', 'pushed_at')):
        if fingerprint(o.lines_snapshot) == fp:
            return o
    return None


def overlap_guard_on():
    from apps.config.models import SystemSetting
    return str(SystemSetting.get('isr_overlap_guard', 'off') or 'off').strip().lower() == 'on'


def _qty(line):
    return int(round(float(line.get('itemqty') or 0)))


ISSUE_DOCCODE = '125'   # صرف لفرع — the source issues to the destination (counterpart store = destination)


def _dispensed(rows, before):
    """{(push_id, itemcode)} of `rows` the earlier ISR's source has already issued to the destination after that
    push and before `before` (owner 2026-11-01: a repeat counts only while the earlier ISR is NOT dispensed).
    From the stock ledger mirror (doc 125). SOFTECH does not put the ISR number on the issue line, so this is
    item × route × time; the ledger refreshes every 2 hours, so a very recent issue still asks for a reason."""
    from apps.stock_audit.models import StockLedgerLine
    if not rows:
        return set()
    first = min(r['pushed_at'] for r in rows)
    issues = defaultdict(list)
    for src, dest, item, t, d in (StockLedgerLine.objects.filter(
            doccode=ISSUE_DOCCODE, branchcode__in={r['source'] for r in rows},
            storecode2__in={r['dest'] for r in rows}, itemcode__in={r['itemcode'] for r in rows},
            docdate__gte=timezone.localdate(first))
            .values_list('branchcode', 'storecode2', 'itemcode', 'trans_time', 'docdate')):
        issues[(src, dest, item)].append(t or timezone.make_aware(datetime.combine(d, time.max)))
    return {(r['push_id'], r['itemcode']) for r in rows
            if any(r['pushed_at'] <= t < before for t in issues.get((r['source'], r['dest'], r['itemcode']), ()))}


def overlapping_pushed(p, *, since=None, pushed=None, before=None):
    """Lines of draft `p` whose item is also in an ISR PUSHED to the same destination (same kind) in the last
    DUP_PUSH_DAYS days and NOT yet dispensed (see _dispensed). An identical ISR is the duplicate guard's case and is
    not listed here. Returns [{itemcode, qty, earlier_qty, push_id, isrdocnumber, pushed_at}], one row per item."""
    from apps.purchasing.models import IsrPush as P
    if pushed is None:
        since = since or timezone.now() - timedelta(days=DUP_PUSH_DAYS)
        pushed = (P.objects.filter(kind=p.kind, dest_branchcode=p.dest_branchcode, status=P.STATUS_PUSHED,
                                   pushed_at__gte=since).exclude(pk=p.pk)
                  .only('id', 'lines_snapshot', 'isrdocnumber', 'pushed_at').order_by('pushed_at'))
    mine = {str(l.get('itemcode') or '').strip(): _qty(l) for l in (p.lines_snapshot or [])}
    fp = fingerprint(p.lines_snapshot)
    cand = []
    for o in pushed:
        if fingerprint(o.lines_snapshot) == fp:
            continue
        for l in o.lines_snapshot or []:
            code = str(l.get('itemcode') or '').strip()
            if code in mine:
                cand.append({'itemcode': code, 'qty': mine[code], 'earlier_qty': _qty(l), 'push_id': o.pk,
                             'isrdocnumber': o.isrdocnumber, 'pushed_at': o.pushed_at,
                             'source': str(o.branchcode), 'dest': str(o.dest_branchcode or o.branchcode)})
    done = _dispensed(cand, before or timezone.now())
    out, seen = [], set()
    for r in cand:
        if (r['push_id'], r['itemcode']) in done or r['itemcode'] in seen:
            continue
        seen.add(r['itemcode'])
        out.append(r)
    return sorted(out, key=lambda r: r['itemcode'])


def check_push(p, *, user=None, force_reason=''):
    """Before writing a draft to SOFTECH: no identical recent ISR on the route (unless a
    reason is given), and a forwarding leg never goes before the leg that feeds it."""
    from apps.purchasing.models import IsrPush as P
    validate_route(p.kind, p.branchcode, p.dest_branchcode)
    if p.kind == P.KIND_HQ_TO_BRANCH and p.linked_push_id:
        feeder = p.linked_push
        if feeder.kind == P.KIND_BRANCH_TO_HQ and feeder.status != P.STATUS_PUSHED:
            raise GuardError(f'هذا الطلب يصرف بضاعة تصل للرئيسي من فرع {feeder.branchcode} بالطلب #{feeder.pk} — '
                             f'رحّل #{feeder.pk} أولاً.', code='feeder_first', other=feeder.pk)
    dup = duplicate_pushed(p)
    if dup is not None:
        reason = (force_reason or '').strip()
        if len(reason) < MIN_REASON:
            raise GuardError(f'نفس الطلب (نفس الأصناف والكميات) رُحِّل بالفعل لنفس المسار بالطلب #{dup.pk} '
                             f'(SOFTECH ISR {dup.isrdocnumber}) خلال آخر {DUP_PUSH_DAYS} أيام. '
                             f'لن يُرحَّل مرة ثانية إلا بسبب مكتوب.', code='duplicate_push', other=dup.pk)
        params = dict(p.params or {})
        params['forced_push'] = {'reason': reason, 'duplicate_of': dup.pk, 'by': getattr(user, 'username', None),
                                 'at': timezone.now().isoformat()}
        p.params = params
        p.save(update_fields=['params'])
        _audit('isr_duplicate_push_forced', p, user=user, note=reason, extra={'duplicate_of': dup.pk})
    if overlap_guard_on():
        rows = overlapping_pushed(p)
        if rows:
            reason = (force_reason or '').strip()
            shown = '، '.join(f"{r['itemcode']} (#{r['push_id']})" for r in rows[:10])
            more = f' و{len(rows) - 10} صنف آخر' if len(rows) > 10 else ''
            if len(reason) < MIN_REASON:
                raise GuardError(f'{len(rows)} صنف في هذا الطلب رُحِّل بالفعل لنفس الفرع خلال آخر {DUP_PUSH_DAYS} أيام: '
                                 f'{shown}{more}. لن يُرحَّل إلا بسبب مكتوب.', code='overlap_push',
                                 other=rows[0]['push_id'])
            earlier = sorted({r['push_id'] for r in rows})
            params = dict(p.params or {})
            params['forced_overlap'] = {'reason': reason, 'items': [r['itemcode'] for r in rows], 'earlier': earlier,
                                        'by': getattr(user, 'username', None), 'at': timezone.now().isoformat()}
            p.params = params
            p.save(update_fields=['params'])
            _audit('isr_overlap_push_forced', p, user=user, note=reason,
                   extra={'earlier': earlier, 'items': len(rows)})


def expiry_days():
    """SystemSetting `isr_draft_expiry_days` (0 / missing = off)."""
    from apps.config.models import SystemSetting
    try:
        return max(0, int(SystemSetting.get('isr_draft_expiry_days', 0) or 0))
    except (TypeError, ValueError):
        return 0


def expire_drafts(*, now=None):
    """P-32 §2.4 / doc 30 §2.6: cancel, with audit, every PROPOSED general draft older than `expiry_days()` (PG only,
    never SOFTECH). Approved drafts (a person signed them off) and drafts tied to a branch / WhatsApp / shortage-list
    request keep their own rules. Returns the cancelled ids. Idempotent."""
    from apps.purchasing.models import IsrPush as P
    days = expiry_days()
    if not days:
        return []
    cutoff = (now or timezone.now()) - timedelta(days=days)
    done = []
    for p in _general(P.objects.filter(status=P.STATUS_PROPOSED, created_at__lt=cutoff)).order_by('pk'):
        _cancel(p, reason=f'انتهت صلاحية المقترح: أقدم من {days} أيام دون اعتماد')
        done.append(p.pk)
    return done
