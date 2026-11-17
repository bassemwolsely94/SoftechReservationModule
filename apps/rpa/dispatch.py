"""Handing documents to the Windows agent: claim, lease, report, and the operator's resolve.

This is what stops the robot typing one document into SOFTECH twice:
  • a document is claimed under a row lock (select_for_update skip_locked), so two agents never
    get the same one;
  • before it is handed out SOFTECH is searched for it (RPA-<id> reference, then fingerprint);
    one already there is marked posted / sent to a person and never typed;
  • a lease that runs out goes to a person (needs_person), never back to the queue;
  • a report for a run that is already finished changes nothing (the agent retries reports).

No SQL here: SOFTECH is only read, through apps/rpa/verifier.py.
"""
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from config.writers import writer_allowed
from core import branch_scope
from core.errors import public_error
from core.permissions import matrix_allows

from .keyplan import build_keyplan
from .models import RpaDevice, RpaDocument, RpaJob, RpaRun
from .verifier import branch_lookup_problem, find_issue_document, verify_issue_document

logger = logging.getLogger(__name__)

FLAG = 'RPA_SOFTECH_ENTRY_ENABLED'
LEASE = timedelta(minutes=10)
LOST_REASON = 'انقطع الروبوت قبل الإبلاغ'
SOFTECH_DOWN = 'تعذر الاتصال بـ SOFTECH للتحقق قبل الإدخال؛ لن يُستلم أي مستند حتى يعود الاتصال'
MAX_STEPS = 5000
_OUTCOMES = {value for value, _ in RpaRun.OUTCOMES if value}


class LeaseLost(Exception):
    """The document is no longer this device's to work on (finished, expired or another's)."""


@dataclass(frozen=True)
class Claim:
    document: RpaDocument
    run: RpaRun
    mode: str
    keyplan: dict


# ── shared state changes (each audited) ──────────────────────────────────────────────────────

def _needs_person(doc, reason, *, user=None):
    old = {'status': doc.status, 'needs_person_reason': doc.needs_person_reason}
    doc.status = 'needs_person'
    doc.needs_person_reason = str(reason)[:255]
    doc.lease_until = None
    doc.save(update_fields=['status', 'needs_person_reason', 'lease_until'])
    AuditLog.log('rpa_document_needs_person', user=user, obj=doc, old_data=old,
                 new_data={'status': doc.status, 'needs_person_reason': doc.needs_person_reason},
                 note=f'{doc.reference}: {doc.needs_person_reason}')


def _verify_result(found, result):
    """JSON-safe: the found lines carry Decimals and dates, so only the verdict is kept."""
    return {'ok': bool(result.get('ok')), 'problems': list(result.get('problems') or []),
            'docnumber': found.get('docnumber'), 'matched_by': found.get('matched_by', ''),
            'checked_at': timezone.now().isoformat()}


def _record_found(doc, found, *, user=None, note=''):
    """SOFTECH holds this document: posted when its typed fields agree, else a person decides."""
    result = _verify_result(found, verify_issue_document(doc, found))
    old = {'status': doc.status, 'softech_docnumber': doc.softech_docnumber}
    doc.softech_docnumber = found['docnumber']
    doc.verify_result = result
    doc.lease_until = None
    doc.save(update_fields=['softech_docnumber', 'verify_result', 'lease_until'])
    AuditLog.log('rpa_document_verified', user=user, obj=doc, old_data=old,
                 new_data={'softech_docnumber': doc.softech_docnumber, **result},
                 note=note or f'{doc.reference}: موجود في SOFTECH برقم {doc.softech_docnumber}')
    if result['ok']:
        doc.status = 'posted'
        doc.needs_person_reason = ''
        doc.save(update_fields=['status', 'needs_person_reason'])
    else:
        _needs_person(doc, 'موجود في SOFTECH لكن لا يطابق: ' + '، '.join(result['problems']), user=user)


# ── claim ────────────────────────────────────────────────────────────────────────────────────

def sweep_expired_leases():
    """Every in_progress document whose lease ran out goes to a person; its open run is closed."""
    now = timezone.now()
    with transaction.atomic():
        expired = list(RpaDocument.objects.select_for_update(skip_locked=True)
                       .filter(status='in_progress', lease_until__lt=now))
        for doc in expired:
            RpaRun.objects.filter(document=doc, finished_at__isnull=True).update(
                outcome='timeout', finished_at=now)
            _needs_person(doc, LOST_REASON)
    return len(expired)


def _candidates(device):
    return (RpaDocument.objects
            .select_for_update(skip_locked=True, of=('self',))
            .select_related('job__screen', 'job__recipe', 'job__branch', 'job__target_branch',
                            'job__created_by')
            .filter(status='approved', job__status='approved', job__screen__enabled=True,
                    job__created_by_id=device.staff_id)
            .order_by('job_id', 'seq', 'pk'))


def _still_claimable(doc):
    """Re-read after the lock: the lock covers the document row only (of=self), and PostgreSQL
    re-checks a WHERE only on the rows it locks, so a job cancelled after the candidate query's
    snapshot would otherwise pass. Asked again right before the claim is written."""
    return (RpaDocument.objects.filter(pk=doc.pk, status='approved').exists()
            and RpaJob.objects.filter(pk=doc.job_id, status='approved').exists())


_UNREACHABLE = object()      # _claim_loop's answer when SOFTECH could not be searched


def _set_claim_error(device, text):
    """Why the last claim handed nothing out although work may be waiting ('' = no problem).
    Shown on /api/rpa/status/ next to the device, so the operator is not left guessing."""
    if (device.last_claim_error or '') == text:
        return
    device.last_claim_error = text
    device.last_claim_error_at = timezone.now() if text else None
    RpaDevice.objects.filter(pk=device.pk).update(last_claim_error=text,
                                                  last_claim_error_at=device.last_claim_error_at)


def claim_next(device):
    """The next document for this device's operator, claimed under a 10-minute lease, or None.

    Oldest first. One already in SOFTECH is recorded (posted, or needs_person when its fields
    differ) and the loop moves on; one whose keyplan cannot be built goes to a person. Each
    candidate is decided in its own transaction, under its row lock."""
    sweep_expired_leases()
    if not writer_allowed(FLAG):
        return None
    claim = _claim_loop(device)
    if claim is _UNREACHABLE:
        _set_claim_error(device, SOFTECH_DOWN)
        return None
    _set_claim_error(device, '')
    return claim


def _claim_loop(device):
    while True:
        with transaction.atomic():
            doc = _candidates(device).first()
            if doc is None:
                return None
            job = doc.job
            if not _still_claimable(doc):
                continue
            problem = (branch_lookup_problem(job.branch)
                       or branch_lookup_problem(job.target_branch, needs_server=False))
            if problem:                              # SOFTECH cannot be searched: never type blind
                _needs_person(doc, f'لا يمكن التحقق من SOFTECH: {problem}', user=job.created_by)
                continue
            try:
                found = find_issue_document(doc)
            except Exception as exc:                 # noqa: BLE001 - SOFTECH unreachable: claim nothing
                logger.warning('rpa claim: SOFTECH lookup failed for document %s (%s)',
                               doc.pk, type(exc).__name__)
                return _UNREACHABLE
            if found is not None:
                _record_found(doc, found, user=job.created_by,
                              note=f'{doc.reference}: موجود في SOFTECH قبل الإدخال — لن يُكتب')
                continue
            recipe = job.recipe
            if recipe is None or recipe.status != 'approved' or recipe.screen_id != job.screen_id:
                _needs_person(doc, 'لا توجد وصفة معتمدة لهذه المهمة', user=job.created_by)
                continue
            mode = 'dry_run' if job.dry_run else 'live'
            try:
                with transaction.atomic():           # savepoint: a DB error here must not poison the claim
                    keyplan = build_keyplan(doc, mode=mode)
            except PermissionError:
                _needs_person(doc, 'الإدخال الفعلي غير مفعل لهذه الشاشة', user=job.created_by)
                continue
            except ValueError as exc:
                _needs_person(doc, f'تعذر بناء خطة الإدخال: {exc}', user=job.created_by)
                continue
            except Exception as exc:                 # noqa: BLE001 - one bad document must not block the queue
                _needs_person(doc, f'تعذر بناء خطة الإدخال — {public_error(None, exc)}', user=job.created_by)
                continue
            if not _still_claimable(doc):            # cancelled while SOFTECH was being searched
                continue
            now = timezone.now()
            doc.status = 'in_progress'
            doc.claimed_by = device
            doc.claimed_at = now
            doc.lease_until = now + LEASE
            doc.needs_person_reason = ''
            doc.save(update_fields=['status', 'claimed_by', 'claimed_at', 'lease_until', 'needs_person_reason'])
            run = RpaRun.objects.create(document=doc, device=device, recipe=recipe, mode=mode, started_at=now)
            AuditLog.log('rpa_document_claimed', user=device.staff, obj=doc,
                         old_data={'status': 'approved'},
                         new_data={'status': doc.status, 'device_id': device.pk, 'run_id': run.pk,
                                   'mode': mode, 'lease_until': doc.lease_until.isoformat()},
                         note=f'{doc.reference}: استلمه جهاز {device.label}')
            return Claim(document=doc, run=run, mode=mode, keyplan=keyplan)


def extend_lease(document, device):
    """Another 10 minutes, only while the document is in progress under this device's live lease."""
    now = timezone.now()
    with transaction.atomic():
        doc = RpaDocument.objects.select_for_update().get(pk=document.pk)
        if (doc.status != 'in_progress' or doc.claimed_by_id != device.pk
                or doc.lease_until is None or doc.lease_until < now):
            raise LeaseLost()
        doc.lease_until = now + LEASE
        doc.save(update_fields=['lease_until'])
    return doc.lease_until


# ── report ───────────────────────────────────────────────────────────────────────────────────

def _clean_steps(steps):
    if not isinstance(steps, list):
        return []
    out = []
    for s in steps[:MAX_STEPS]:
        if not isinstance(s, dict):
            continue
        out.append({'i': s.get('i') if isinstance(s.get('i'), int) else None,
                    'label': str(s.get('label', ''))[:120], 'at': str(s.get('at', ''))[:40],
                    'ok': bool(s.get('ok')), 'note': str(s.get('note', ''))[:300]})
    return out


def _run_id(payload):
    raw = payload.get('run_id')
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError({'run_id': 'رقم تشغيل غير صالح'})


def report_run(document, device, payload) -> RpaRun:
    """Close the run the agent was given at claim time and move the document on.

    A run that is already finished is returned untouched: the agent retries reports, and a late
    report after the lease ran out must not undo what a person now owns."""
    if not isinstance(payload, dict):
        raise ValidationError({'detail': 'طلب غير صالح'})
    run_id = _run_id(payload)
    with transaction.atomic():
        doc = RpaDocument.objects.select_for_update().select_related('job').get(pk=document.pk)
        runs = RpaRun.objects.select_for_update().filter(document=doc, device=device)
        run = (runs.filter(pk=run_id) if run_id is not None
               else runs.filter(finished_at__isnull=True).order_by('-started_at')).first()
        if run is None:
            raise RpaRun.DoesNotExist()
        if run.finished_at is not None:
            return run
        outcome = payload.get('outcome')
        # the agent stopped itself because the heartbeat said the lease is gone
        lease_lost = outcome == 'lease_lost'
        outcome = 'timeout' if lease_lost else outcome if outcome in _OUTCOMES else 'error'
        run.outcome = outcome
        run.steps = _clean_steps(payload.get('steps'))
        run.finished_at = timezone.now()
        run.save(update_fields=['outcome', 'steps', 'finished_at'])

        old = doc.status
        user = device.staff
        softech_check = None
        if doc.status == 'in_progress' and doc.claimed_by_id == device.pk:
            if outcome == 'dry_run_ok' and run.mode == 'dry_run':
                doc.status = 'dry_run_ok'
                doc.lease_until = None
                doc.save(update_fields=['status', 'lease_until'])
                softech_check = _after_dry_run(doc, run, user)
            elif outcome == 'saved' and run.mode == 'live':
                _after_save(doc, user)
            elif outcome == 'saved':
                _needs_person(doc, 'أبلغ الروبوت بالحفظ في تشغيل تجريبي', user=user)
            elif outcome == 'dry_run_ok':
                _needs_person(doc, 'نتيجة تجريبية في تشغيل فعلي', user=user)
            else:
                _needs_person(doc, LOST_REASON if lease_lost else outcome, user=user)
        new = {'status': doc.status, 'run_id': run.pk, 'mode': run.mode, 'outcome': outcome,
               'steps': len(run.steps)}
        if softech_check is not None:
            new['softech_check'] = softech_check
        AuditLog.log('rpa_run_reported', user=user, obj=doc, old_data={'status': old}, new_data=new,
                     note=f'{doc.reference}: {outcome}')
    return run


SAVED_IN_DRY_RUN = ('وُجد المستند محفوظاً في SOFTECH برقم {n} بعد تشغيل تجريبي — '
                    'كان يجب ألا يُحفظ؛ راجع الوصفة قبل أي تشغيل آخر')
NOT_CHECKED_NOTE = 'لم يتم التحقق من SOFTECH بعد التجربة (تعذر الاتصال)'


def _after_dry_run(doc, run, user):
    """A dry run must leave nothing in SOFTECH: look, and send a hit to a person.

    Returns what the check found, for the run's audit: 'clear', 'found', or 'not_checked'
    (SOFTECH unreachable: the result stays dry_run_ok and the run carries a note saying so)."""
    try:
        found = find_issue_document(doc)
    except Exception as exc:                         # noqa: BLE001 - the operator sees the note on the run
        logger.warning('rpa report: SOFTECH check after dry run failed for document %s (%s)',
                       doc.pk, type(exc).__name__)
        run.steps = run.steps + [{'i': None, 'label': 'تحقق SOFTECH', 'at': timezone.now().isoformat(),
                                  'ok': False, 'note': NOT_CHECKED_NOTE}]
        run.save(update_fields=['steps'])
        return 'not_checked'
    if found is None:
        return 'clear'
    old = {'softech_docnumber': doc.softech_docnumber}
    doc.softech_docnumber = found['docnumber']
    doc.save(update_fields=['softech_docnumber'])
    AuditLog.log('rpa_document_verified', user=user, obj=doc, old_data=old,
                 new_data={'softech_docnumber': doc.softech_docnumber, 'matched_by': found.get('matched_by', ''),
                           'run_id': run.pk, 'saved_in_dry_run': True},
                 note=f'{doc.reference}: محفوظ في SOFTECH بعد تشغيل تجريبي')
    _needs_person(doc, SAVED_IN_DRY_RUN.format(n=found['docnumber']), user=user)
    return 'found'


def _after_save(doc, user):
    try:
        found = find_issue_document(doc)
    except Exception as exc:                         # noqa: BLE001 - a person checks SOFTECH by hand
        logger.warning('rpa report: SOFTECH lookup failed for document %s (%s)', doc.pk, type(exc).__name__)
        _needs_person(doc, 'تعذر التحقق من SOFTECH بعد الحفظ', user=user)
        return
    if found is None:
        _needs_person(doc, 'أبلغ الروبوت بالحفظ ولم يُعثر على المستند في SOFTECH', user=user)
        return
    _record_found(doc, found, user=user)


# ── resolve (a person decides on a needs_person document) ───────────────────────────────────

DECISIONS = ('retry', 'posted', 'cancelled')


def resolve_document(document, profile, decision: str, reason: str):
    if not matrix_allows(profile, 'rpa', 'edit'):
        raise PermissionDenied('ليس لديك صلاحية تعديل مستندات الروبوت.')
    if not branch_scope.allows(profile, document.job.branch_id):
        raise PermissionDenied('لا يمكنك التعامل مع مستند فرع خارج فروعك.')
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError({'reason': 'يجب كتابة السبب.'})
    if decision not in DECISIONS:
        raise ValidationError({'decision': 'قرار غير معروف.'})
    with transaction.atomic():
        doc = RpaDocument.objects.select_for_update().select_related('job').get(pk=document.pk)
        if doc.status != 'needs_person':
            raise ValidationError({'detail': 'المستند لا ينتظر قرار موظف.'})
        old = {'status': doc.status, 'needs_person_reason': doc.needs_person_reason,
               'softech_docnumber': doc.softech_docnumber}
        problem = '' if decision == 'cancelled' else branch_lookup_problem(doc.job.branch)
        if problem:                                  # retry / posted both need SOFTECH searched first
            raise ValidationError({'detail': f'لا يمكن التحقق من SOFTECH: {problem}'})
        if decision == 'retry':
            try:
                found = find_issue_document(doc)
            except Exception as exc:                 # noqa: BLE001 - shown as a calm message, not the error
                logger.warning('rpa resolve: SOFTECH lookup failed for document %s (%s)',
                               doc.pk, type(exc).__name__)
                raise ValidationError({'detail': 'تعذر الاتصال بـ SOFTECH للتأكد أن المستند غير محفوظ، حاول لاحقاً.'})
            if found is not None:                    # typing it again would post it twice
                raise ValidationError({'detail': f'المستند موجود في SOFTECH برقم {found["docnumber"]}؛ '
                                                 'لا يمكن إعادة المحاولة — اختر «تم الحفظ في SOFTECH».'})
            doc.status = 'approved'
            doc.claimed_by = None
            doc.claimed_at = None
            doc.lease_until = None
            doc.needs_person_reason = ''
            doc.save(update_fields=['status', 'claimed_by', 'claimed_at', 'lease_until', 'needs_person_reason'])
        elif decision == 'posted':
            try:
                found = find_issue_document(doc)
            except Exception as exc:                 # noqa: BLE001 - shown as a calm message, not the error
                logger.warning('rpa resolve: SOFTECH lookup failed for document %s (%s)',
                               doc.pk, type(exc).__name__)
                raise ValidationError({'detail': 'تعذر الاتصال بـ SOFTECH للتحقق، حاول لاحقاً.'})
            if found is None:
                raise ValidationError({'detail': 'لم يتم العثور على المستند في SOFTECH.'})
            result = _verify_result(found, verify_issue_document(doc, found))
            doc.status = 'posted'
            doc.softech_docnumber = found['docnumber']
            doc.verify_result = result
            doc.needs_person_reason = ''
            doc.save(update_fields=['status', 'softech_docnumber', 'verify_result', 'needs_person_reason'])
        else:
            doc.status = 'cancelled'
            doc.lease_until = None
            doc.save(update_fields=['status', 'lease_until'])
        new = {'status': doc.status, 'decision': decision, 'reason': reason,
               'softech_docnumber': doc.softech_docnumber}
        if decision == 'posted':                     # a person may post over a failed check: keep it on record
            new.update(verify_ok=doc.verify_result['ok'], verify_problems=doc.verify_result['problems'])
        AuditLog.log('rpa_document_resolved', user=profile, obj=doc, old_data=old, new_data=new,
                     note=f'{doc.reference}: {decision} — {reason}')
    return doc
