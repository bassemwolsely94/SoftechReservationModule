"""
apps/tax_invoicing/signing.py — the seal behind one interface.

  Signer.sign(canonical_text) -> base64 signature, or raises SigningUnavailable.

  NotConfiguredSigner  the default: refuses, so nothing can leave.
  MockSigner           local and staging tests. Marked is_mock; never usable against production ETA.
  AgentSigner          the real path. The USB token stays on the signing workstation, whose agent
                       (deploy/tax_signing_agent) pulls jobs from here over the VPN. The PIN and key
                       never reach this server.

Live sending also needs `assert_ready_for_live`: a passed smoke test against the real token.
"""
import base64
import hashlib
import re
import secrets
import time
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.module_loading import import_string

from . import fiscal
from .models import TaxSigningCertification, TaxSigningJob

PRODUCTION_HOST = 'api.invoicing.eta.gov.eg'
STALE_DOCUMENT_GRACE_SECONDS = 60   # past AgentSigner's own wait, which normally expires the job first
STALE_SMOKE_MINUTES = 15            # long enough for someone to walk over and start the agent


class SigningUnavailable(Exception):
    pass


class NotConfiguredSigner:
    is_mock = False
    needs_certification = True

    def sign(self, canonical_text: str) -> str:
        raise SigningUnavailable('الختم الإلكتروني غير موصول بعد بالنظام')


class MockSigner:
    """Not a signature. Clearly labelled, so it can never pass for one."""
    is_mock = True
    needs_certification = False

    def sign(self, canonical_text: str) -> str:
        return base64.b64encode(b'MOCK-SIGNATURE:' + fiscal.sha256_hex(canonical_text).encode()).decode()


class AgentSigner:
    is_mock = False
    needs_certification = True

    def sign(self, canonical_text: str) -> str:
        job = TaxSigningJob.objects.create(kind=TaxSigningJob.KIND_DOCUMENT, canonical_text=canonical_text,
                                           canonical_sha256=fiscal.sha256_hex(canonical_text))
        wait = int(getattr(settings, 'TAX_SIGNING_WAIT_SECONDS', 60))
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            job.refresh_from_db()
            if job.status == TaxSigningJob.SIGNED:
                return _checked_document_signature(job)
            if job.status == TaxSigningJob.FAILED:
                raise SigningUnavailable(f'فشل التوقيع على جهاز الختم: {job.error}')
            time.sleep(1)
        TaxSigningJob.objects.filter(pk=job.pk, status__in=[TaxSigningJob.PENDING, TaxSigningJob.CLAIMED]).update(
            status=TaxSigningJob.EXPIRED, finished_at=timezone.now())
        raise SigningUnavailable('جهاز الختم لم يرد في الوقت المحدد؛ تأكد أنه يعمل وأن الفلاشة موصلة')


def _expected_thumbprint():
    """Hex digits only: Windows' certificate dialog adds spaces and an invisible mark when copied."""
    return re.sub(r'[^0-9A-F]', '', str(getattr(settings, 'TAX_SIGNING_CERT_THUMBPRINT', '') or '').upper())


def _checked_document_signature(job):
    """A wrong or foreign signature stops here, on the server, rather than going to ETA."""
    from . import cades
    try:
        details = cades.inspect_signature(base64.b64decode(job.signature), job.canonical_text.encode('utf-8'))
    except (cades.SignatureInvalid, ValueError) as exc:
        raise SigningUnavailable(f'توقيع جهاز الختم غير صالح: {str(exc)[:200]}') from exc
    expected = _expected_thumbprint()
    if expected and details['thumbprint'] != expected:
        raise SigningUnavailable('المستند موقّع بشهادة غير المسجلة في TAX_SIGNING_CERT_THUMBPRINT')
    return job.signature


def get_signer():
    return import_string(getattr(settings, 'TAX_SIGNER_CLASS', 'apps.tax_invoicing.signing.NotConfiguredSigner'))()


def latest_certification():
    return TaxSigningCertification.objects.order_by('-created_at', '-id').first()


def assert_ready_for_live(signer=None):
    """Raises SigningUnavailable unless this signer may sign something that really goes out."""
    signer = signer or get_signer()
    if signer.is_mock:
        if not getattr(settings, 'TAX_ALLOW_MOCK_SIGNER', False):
            raise SigningUnavailable('التوقيع التجريبي مسموح فقط في بيئة الاختبار')
        if PRODUCTION_HOST in str(getattr(settings, 'TAX_ETA_API_BASE_URL', '')):
            raise SigningUnavailable('لا يمكن استخدام التوقيع التجريبي مع منظومة المصلحة الفعلية')
        return
    if not signer.needs_certification:
        return
    cert = latest_certification()
    if cert is None or not cert.passed:
        raise SigningUnavailable('لم ينجح اختبار الختم الفعلي بعد؛ الإرسال موقوف')
    expected = _expected_thumbprint()
    if not expected or cert.thumbprint != expected:
        raise SigningUnavailable('بصمة شهادة الختم لا تطابق الإعداد TAX_SIGNING_CERT_THUMBPRINT')
    if cert.not_after and cert.not_after <= timezone.now():
        raise SigningUnavailable('شهادة الختم منتهية')


def expire_stale_jobs():
    """Close jobs left open when the agent or a web process died: the screen stops waiting for them, and
    the agent never seals a document nobody is waiting for. An unanswered smoke test records no
    certification, because silence from the agent says nothing about the token."""
    now = timezone.now()
    document_limit = int(getattr(settings, 'TAX_SIGNING_WAIT_SECONDS', 60)) + STALE_DOCUMENT_GRACE_SECONDS
    return TaxSigningJob.objects.filter(status__in=[TaxSigningJob.PENDING, TaxSigningJob.CLAIMED]).filter(
        Q(kind=TaxSigningJob.KIND_DOCUMENT, created_at__lt=now - timedelta(seconds=document_limit))
        | Q(kind=TaxSigningJob.KIND_SMOKE, created_at__lt=now - timedelta(minutes=STALE_SMOKE_MINUTES)),
    ).update(status=TaxSigningJob.EXPIRED, finished_at=now)


def start_smoke_test(actor):
    """A harmless text for the real token to sign. It proves the path, and it is never sent to ETA."""
    text = f'"SMOKETEST""{secrets.token_hex(16)}"'
    return TaxSigningJob.objects.create(kind=TaxSigningJob.KIND_SMOKE, canonical_text=text,
                                        canonical_sha256=fiscal.sha256_hex(text), requested_by=actor)


def record_smoke_result(job):
    """Verify what the agent returned, here on the server, and record the outcome."""
    from . import cades
    row = TaxSigningCertification(job=job, requested_by=job.requested_by)
    if job.status != TaxSigningJob.SIGNED:
        row.passed, row.detail = False, job.error or job.status
    else:
        try:
            details = cades.inspect_signature(base64.b64decode(job.signature), job.canonical_text.encode('utf-8'))
            row.passed = True
            row.subject, row.issuer, row.thumbprint = details['subject'], details['issuer'], details['thumbprint']
            row.not_after = details['not_after']
        except (cades.SignatureInvalid, ValueError) as exc:
            row.passed, row.detail = False, str(exc)[:500]
    row.save()
    return row


def agent_token_ok(presented):
    expected = str(getattr(settings, 'TAX_SIGNING_AGENT_TOKEN', '') or '')
    if len(expected) < 32 or not presented:
        return False
    return secrets.compare_digest(hashlib.sha256(presented.encode()).digest(), hashlib.sha256(expected.encode()).digest())
