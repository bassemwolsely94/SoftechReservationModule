"""RPA job workflow: create (Task 4); approve/cancel are added in Task 5."""
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from core import branch_scope
from core.upload_safety import sha256_of

from .models import RpaDocument, RpaJob, RpaScreen
from .sheet import build_lines, parse_issue_sheet

CLOSED_BRANCH_CODE = '110'


def _is_closed_branch(branch):
    return CLOSED_BRANCH_CODE in (str(branch.code or ''), str(branch.softech_branch_id or ''))


def create_job(*, profile, screen_key, branch, target_branch, store_code, upload) -> RpaJob:
    if not branch_scope.allows(profile, branch.id):
        raise PermissionDenied('لا يمكنك الرفع على فرع خارج فروعك.')
    if target_branch is None:
        raise ValidationError({'target_branch': 'يجب تحديد الفرع المستلم.'})
    if target_branch.id == branch.id:
        raise ValidationError({'target_branch': 'الفرع المستلم هو نفسه الفرع المصدر.'})
    if _is_closed_branch(target_branch):
        raise ValidationError({'target_branch': f'الفرع {target_branch.name} مغلق ولا يمكن الصرف إليه.'})
    if _is_closed_branch(branch):
        raise ValidationError({'branch': 'هذا الفرع مغلق ولا يمكن الصرف منه.'})
    digest = sha256_of(upload)
    filename = getattr(upload, 'name', '') or ''
    rows = parse_issue_sheet(upload.read(), filename)
    with transaction.atomic():
        # Serialise concurrent uploads for this screen: the sha check below has no DB constraint.
        screen = RpaScreen.objects.select_for_update().get(key=screen_key)
        existing = RpaJob.objects.filter(upload_sha256=digest).exclude(status='cancelled').first()
        if existing:
            raise ValidationError({'detail': 'تم رفع هذا الملف من قبل.', 'job_id': existing.id})
        job = RpaJob.objects.create(
            screen=screen, branch=branch, target_branch=target_branch, created_by=profile,
            store_code=str(store_code or ''), source_kind='excel', filename=filename[:255],
            upload_sha256=digest)
        # Stage 1: one document per sheet; the splitting rule is set in Stage 2 with the owner.
        document = RpaDocument.objects.create(job=job, seq=1)
        build_lines(document, rows)
        AuditLog.log('rpa_job_uploaded', user=profile, obj=job,
                     new_data={'filename': job.filename, 'sha256': digest, 'rows': len(rows),
                               'branch': branch.name,
                               'target_branch': target_branch.name if target_branch else ''},
                     note=f'رفع مهمة {screen.title_ar}')
    return job
