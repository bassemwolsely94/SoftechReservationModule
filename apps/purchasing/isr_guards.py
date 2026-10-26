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
  • leg order — the HQ → branch leg of a transfer is pushed only after its branch → HQ
    leg (the goods must be on their way to HQ before HQ sends them on).
  • cancel — any unpushed draft, with a reason, audited.
"""
import hashlib
import logging
from datetime import timedelta

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
    return qs.filter(origin_isr__isnull=True, origin_request__isnull=True)


def live_on_route(kind, source, dest, *, exclude=None):
    from apps.purchasing.models import IsrPush as P
    qs = _general(P.objects.filter(kind=kind, branchcode=str(source), dest_branchcode=str(dest or ''),
                                   status__in=LIVE))
    return qs.exclude(pk=exclude) if exclude else qs


def check_route_free(kind, source, dest):
    """Before a new general draft: refuse when an APPROVED one waits on the route; return
    the PROPOSED ones the new draft will supersede."""
    live = list(live_on_route(kind, source, dest).select_for_update())
    approved = [p for p in live if p.status == 'approved']
    if approved:
        raise GuardError(f'يوجد طلب توريد معتمد #{approved[0].pk} لنفس المسار ({source} ← {dest or source}) '
                         f'لم يُرحَّل بعد — رحّله أو ألغه أولاً.', code='approved_exists', other=approved[0].pk)
    return [p for p in live if p.status == 'proposed']


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
