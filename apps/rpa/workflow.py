"""RPA job workflow: create, four-eyes approval of jobs and recipes, cancel."""
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from core import branch_scope
from core.permissions import matrix_allows
from core.upload_safety import sha256_of

from .models import RpaDocument, RpaJob, RpaRecipe, RpaScreen
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
            detail = {'detail': 'تم رفع هذا الملف من قبل.'}
            if branch_scope.allows(profile, existing.branch_id):   # never leak another branch's job id
                detail['job_id'] = existing.id
            raise ValidationError(detail)
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


def approve_job(job, profile) -> RpaJob:
    """Four-eyes: someone other than the uploader approves; freezes the latest approved recipe."""
    if not matrix_allows(profile, 'rpa', 'approve'):
        raise PermissionDenied('ليس لديك صلاحية اعتماد مهام الروبوت.')
    if profile.id == job.created_by_id:
        raise PermissionDenied('لا يمكنك اعتماد مهمة قمت برفعها أنت.')
    with transaction.atomic():
        job = RpaJob.objects.select_for_update().get(pk=job.pk)
        if job.status != 'uploaded':
            raise ValidationError({'detail': 'لا يمكن اعتماد هذه المهمة في حالتها الحالية.'})
        if RpaDocument.objects.filter(job=job, lines__status__in=['unmatched', 'error']).exists():
            raise ValidationError({'detail': 'توجد أصناف غير مطابقة أو بها خطأ؛ صحّحها قبل الاعتماد.'})
        # The screen row is the lock recipe approvals take too: the recipe cannot be retired
        # between reading it here and freezing it onto the job.
        RpaScreen.objects.select_for_update().get(pk=job.screen_id)
        recipe = (RpaRecipe.objects.filter(screen_id=job.screen_id, status='approved')
                  .order_by('-version').first())
        if recipe is None:
            raise ValidationError({'detail': 'لا توجد وصفة معتمدة لهذه الشاشة.'})
        job.recipe = recipe
        job.status = 'approved'
        job.approved_by = profile
        job.approved_at = timezone.now()
        job.save(update_fields=['recipe', 'status', 'approved_by', 'approved_at'])
        job.documents.filter(status='pending').update(status='approved')
        AuditLog.log('rpa_job_approved', user=profile, obj=job,
                     old_data={'status': 'uploaded'},
                     new_data={'status': 'approved', 'recipe_id': recipe.id, 'recipe_version': recipe.version},
                     note=f'اعتماد مهمة {job.screen.title_ar}')
    return job


def cancel_job(job, profile, reason: str) -> RpaJob:
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError({'reason': 'يجب ذكر سبب الإلغاء.'})
    with transaction.atomic():
        job = RpaJob.objects.select_for_update().get(pk=job.pk)
        if job.status in ('cancelled', 'done'):
            raise ValidationError({'detail': 'لا يمكن إلغاء هذه المهمة في حالتها الحالية.'})
        documents = list(job.documents.select_for_update())   # a claim cannot slip in between
        if any(d.status in ('in_progress', 'posted') for d in documents):
            raise ValidationError({'detail': 'لا يمكن الإلغاء: يوجد مستند قيد التنفيذ أو مُرحَّل.'})
        old_status = job.status
        job.status = 'cancelled'
        job.save(update_fields=['status'])
        job.documents.exclude(status='cancelled').update(status='cancelled')
        AuditLog.log('rpa_job_cancelled', user=profile, obj=job,
                     old_data={'status': old_status}, new_data={'status': 'cancelled', 'reason': reason},
                     note=reason)
    return job


def approve_recipe(recipe, profile) -> RpaRecipe:
    """Four-eyes on a recipe: an admin other than its importer; the previous approved one retires."""
    if not profile.is_admin:
        raise PermissionDenied('اعتماد الوصفة للمدير فقط.')
    if profile.id == recipe.created_by_id:
        raise PermissionDenied('لا يمكنك اعتماد وصفة قمت باستيرادها أنت.')
    with transaction.atomic():
        RpaScreen.objects.select_for_update().get(pk=recipe.screen_id)   # one approval per screen at a time
        recipe = RpaRecipe.objects.select_for_update().get(pk=recipe.pk)
        if recipe.status != 'draft':
            raise ValidationError({'detail': 'يمكن اعتماد الوصفة وهي مسودة فقط.'})
        previous = (RpaRecipe.objects.select_for_update()
                    .filter(screen_id=recipe.screen_id, status='approved').first())
        if previous is not None:
            previous.status = 'retired'
            previous.save()          # through the guard; approved -> retired is the allowed move
        recipe.status = 'approved'
        recipe.approved_by = profile
        recipe.approved_at = timezone.now()
        recipe.save()
        AuditLog.log('rpa_recipe_approved', user=profile, obj=recipe,
                     old_data={'previous_recipe_id': previous.id if previous else None},
                     new_data={'recipe_id': recipe.id, 'version': recipe.version},
                     note=f'اعتماد وصفة {recipe.screen.title_ar} v{recipe.version}')
    return recipe
