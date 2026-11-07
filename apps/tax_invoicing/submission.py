"""
apps/tax_invoicing/submission.py — the gated outward channel to ETA. Doc 36.

Gates, in order: dry run is the default · flag TAX_ETA_SUBMIT_ENABLED (OFF by default, read through
writer_allowed so only the writer instance can send) · typed confirmation of the document number ·
permission in the view · atomic approved → submitting so two clicks cannot both send.

A retry reuses the same document and internal id. After an uncertain result nothing is sent again
until `reconcile` has asked ETA what it holds.
"""
import datetime as dt

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from config.writers import writer_allowed

from . import eta_client, fiscal
from .models import TaxDocument, TaxSubmissionAttempt
from .services import TaxRuleError, audit, set_status
from .signing import SigningUnavailable, assert_ready_for_live, get_signer

FLAG = 'TAX_ETA_SUBMIT_ENABLED'
_STATUS_MAP = {'valid': TaxDocument.VALID, 'invalid': TaxDocument.INVALID, 'submitted': TaxDocument.SUBMITTED}


def _wait_minutes():
    return int(getattr(settings, 'TAX_RECONCILE_WAIT_MINUTES', 15))


def preview(doc):
    """What would go out. Sends nothing, signs nothing, changes nothing."""
    if doc.status != TaxDocument.APPROVED:
        raise TaxRuleError('المعاينة للمستند المعتمد فقط')
    return {'dry_run': True, 'internal_id': doc.internal_id, 'payload_text': doc.payload_text,
            'payload_hash': doc.payload_hash, 'canonical_hash': fiscal.sha256_hex(fiscal.canonical(doc.payload_text)),
            'submit_enabled': writer_allowed(FLAG)}


def _finish(attempt, state, *, http_status=None, response=None, error=''):
    attempt.state, attempt.http_status = state, http_status
    attempt.response, attempt.error = response or {}, error
    attempt.finished_at = timezone.now()
    attempt.save()


def _fail_not_sent(doc, attempt, actor, message, http_status=None, response=None):
    with transaction.atomic():
        _finish(attempt, TaxSubmissionAttempt.FAILED, http_status=http_status, response=response, error=message)
        set_status(doc, TaxDocument.APPROVED, actor, reason=f'لم يصل للمصلحة: {message}')


def submit(doc_id, actor, confirm):
    if not writer_allowed(FLAG):
        raise TaxRuleError('الإرسال للمصلحة مغلق (TAX_ETA_SUBMIT_ENABLED)')
    signer = get_signer()
    try:
        assert_ready_for_live(signer)
    except SigningUnavailable as exc:
        raise TaxRuleError(str(exc)) from exc
    with transaction.atomic():
        doc = TaxDocument.objects.select_for_update().get(pk=doc_id)
        if confirm != doc.internal_id:
            raise TaxRuleError('اكتب رقم المستند للتأكيد')
        if doc.status == TaxDocument.UNCERTAIN:
            raise TaxRuleError('نتيجة الإرسال السابق غير مؤكدة؛ استعلم من المصلحة أولاً')
        if doc.status != TaxDocument.APPROVED:
            raise TaxRuleError('يُرسل المستند المعتمد فقط')
        if fiscal.sha256_hex(doc.payload_text) != doc.payload_hash:
            raise TaxRuleError('محتوى المستند تغير بعد الاعتماد؛ لن يُرسل')
        set_status(doc, TaxDocument.SUBMITTING, actor, reason='بدء الإرسال')
        attempt = TaxSubmissionAttempt.objects.create(document=doc, payload_hash=doc.payload_hash, started_by=actor)

    # Outside the transaction: this row must stay "submitting" if the process dies mid-call.
    try:
        if not doc.signed_payload_text:
            signature = signer.sign(fiscal.canonical(doc.payload_text))
            doc.signed_payload_text = fiscal.with_signature(doc.payload_text, signature)
            doc.save()
        http_status, body = eta_client.submit_documents(doc.signed_payload_text)
    except (SigningUnavailable, eta_client.EtaNotConfigured) as exc:
        _fail_not_sent(doc, attempt, actor, str(exc))
        raise TaxRuleError(str(exc)) from exc
    except eta_client.EtaRefused as exc:
        _fail_not_sent(doc, attempt, actor, str(exc), exc.http_status, exc.body)
        raise TaxRuleError(str(exc)) from exc
    except eta_client.EtaUncertain as exc:
        with transaction.atomic():
            _finish(attempt, TaxSubmissionAttempt.TIMEOUT, http_status=exc.http_status, response=exc.body, error=str(exc))
            set_status(doc, TaxDocument.UNCERTAIN, actor, reason=str(exc))
        return doc

    with transaction.atomic():
        doc.eta_submission_uuid = body.get('submissionUUID') or body.get('submissionId') or ''
        accepted = next((d for d in body.get('acceptedDocuments') or []
                         if str(d.get('internalId') or d.get('internalID')) == doc.internal_id), None)
        rejected = next((d for d in body.get('rejectedDocuments') or []
                         if str(d.get('internalId') or d.get('internalID')) == doc.internal_id), None)
        if accepted:
            doc.eta_uuid, doc.eta_long_id = accepted.get('uuid', ''), accepted.get('longId', '')
            _finish(attempt, TaxSubmissionAttempt.ACCEPTED, http_status=http_status, response=body)
            set_status(doc, TaxDocument.SUBMITTED, actor, reason='استلمتها المصلحة')
        elif rejected:
            doc.eta_status_reason = str(rejected.get('error') or '')[:2000]
            _finish(attempt, TaxSubmissionAttempt.REJECTED, http_status=http_status, response=body)
            set_status(doc, TaxDocument.REJECTED, actor, reason=doc.eta_status_reason)
        else:
            # An answer that names neither list says nothing about this document.
            _finish(attempt, TaxSubmissionAttempt.TIMEOUT, http_status=http_status, response=body,
                    error='رد لا يذكر المستند')
            set_status(doc, TaxDocument.UNCERTAIN, actor, reason='رد المصلحة لا يذكر المستند')
    return doc


def reconcile(doc_id, actor):
    """Ask ETA what it holds. Only ETA's clear answer moves the document; "not found" frees a retry
    only after the wait, in case ETA has not finished indexing it."""
    doc = TaxDocument.objects.get(pk=doc_id)
    if doc.status not in (TaxDocument.UNCERTAIN, TaxDocument.SUBMITTING, TaxDocument.SUBMITTED):
        raise TaxRuleError('لا يوجد ما يُستعلم عنه لهذا المستند')
    last = doc.attempts.first()
    if doc.status == TaxDocument.SUBMITTING and last and timezone.now() - last.started_at < dt.timedelta(minutes=_wait_minutes()):
        raise TaxRuleError('الإرسال ما زال جارياً')

    issued = doc.date_time_issued or timezone.now()
    try:
        row = eta_client.find_by_internal_id(doc.internal_id, issued - dt.timedelta(days=1),
                                             min(issued + dt.timedelta(days=7), timezone.now()))
    except eta_client.EtaNotConfigured as exc:
        raise TaxRuleError(str(exc)) from exc
    except (eta_client.EtaRefused, eta_client.EtaUncertain) as exc:
        raise TaxRuleError(f'تعذر الاستعلام من المصلحة؛ لم يتغير شيء: {exc}') from exc

    with transaction.atomic():
        doc = TaxDocument.objects.select_for_update().get(pk=doc_id)
        doc.eta_checked_at = timezone.now()
        if doc.status == TaxDocument.SUBMITTING:
            set_status(doc, TaxDocument.UNCERTAIN, actor, reason='توقف الإرسال دون نتيجة')
        if row is None:
            waited = last and timezone.now() - last.started_at >= dt.timedelta(minutes=_wait_minutes())
            if doc.status == TaxDocument.UNCERTAIN and waited:
                set_status(doc, TaxDocument.APPROVED, actor, reason='لا يوجد لدى المصلحة بعد فترة الانتظار؛ يمكن إعادة الإرسال بنفس الرقم')
            else:
                doc.save()
                audit('reconcile_not_found', document=doc, actor=actor)
            return doc
        doc.eta_uuid = row.get('uuid') or doc.eta_uuid
        doc.eta_long_id = row.get('longId') or doc.eta_long_id
        doc.eta_submission_uuid = row.get('submissionUUID') or doc.eta_submission_uuid
        doc.eta_status_reason = str(row.get('documentStatusReason') or '')[:2000]
        target = _STATUS_MAP.get(str(row.get('status') or '').lower())
        if target and target != doc.status and target in TaxDocument.TRANSITIONS.get(doc.status, []):
            set_status(doc, target, actor, reason=f'حالة المصلحة: {row.get("status")}')
        else:
            doc.save()
            audit('reconcile_checked', document=doc, actor=actor, after={'eta_status': row.get('status')})
    return doc
