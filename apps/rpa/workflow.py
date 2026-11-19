"""RPA job workflow: create, four-eyes approval of jobs and recipes, cancel, draft-recipe edits."""
import re

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from core import branch_scope
from core.permissions import matrix_allows
from core.upload_safety import sha256_of

from .models import RpaDocument, RpaJob, RpaRecipe, RpaScreen
from .sheet import build_lines, parse_issue_sheet
from .verifier import branch_lookup_problem

CLOSED_BRANCH_CODE = '110'
LINE_FIELDS = ('itemcode', 'qty', 'expiry')         # what a recipe line may type (keyplan.format_field)
EDITABLE_RECIPE_FIELDS = ('cancel_keys', 'popups', 'header_checklist', 'ref_cells')
_DATALOAD_KEY = re.compile(r'\\\{[^{}]*\}')
_POPUP_KEYS = {'title_contains', 'text_contains', 'answer_keys'}


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
    # the double-post guard searches the source branch's SOFTECH server by its code, and compares
    # the receiving branch's code: without them it would find nothing and the robot would type blind
    for field, b, needs_server in (('branch', branch, True), ('target_branch', target_branch, False)):
        problem = branch_lookup_problem(b, needs_server=needs_server)
        if problem:
            raise ValidationError({field: f'{problem}؛ لا يمكن التحقق من SOFTECH قبل الإدخال.'})
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
        # a finished dry run or a document SOFTECH already holds keeps its record; the rest cancel
        kept = [d.pk for d in documents if d.status == 'dry_run_ok' or d.softech_docnumber is not None]
        cancelled = [d.pk for d in documents if d.status != 'cancelled' and d.pk not in kept]
        RpaDocument.objects.filter(pk__in=cancelled).update(status='cancelled')
        AuditLog.log('rpa_job_cancelled', user=profile, obj=job,
                     old_data={'status': old_status},
                     new_data={'status': 'cancelled', 'reason': reason, 'documents_cancelled': cancelled,
                               'documents_kept': kept},
                     note=reason)
    return job


# ── recipe content checks (draft edit and approval) ───────────────────────────────────────────

def _keys_problem(text, where):
    r"""Key cells are DataLoad form: a special key is `\{ESC}`. A bare `{ESC}` would be typed as the
    literal text "{ESC}" (keyplan.to_send_keys), and the save-key guard could not see it."""
    if not isinstance(text, str) or not text.strip():
        return f'{where}: المفاتيح فارغة'
    if '{' in _DATALOAD_KEY.sub('', text) or '}' in _DATALOAD_KEY.sub('', text):
        return f'{where}: المفتاح الخاص يُكتب بصيغة DataLoad مثل \\{{ESC}}'
    return ''


def _cells_problems(cells, where, *, fields=(), required=False):
    if not isinstance(cells, list):
        return [f'{where}: يجب أن تكون قائمة']
    if required and not cells:
        return [f'{where}: لا يمكن أن تكون فارغة']
    problems = []
    for n, cell in enumerate(cells, start=1):
        if not isinstance(cell, dict) or cell.get('kind') not in ('keys', 'field'):
            problems.append(f'{where} {n}: خلية غير صالحة')
        elif cell['kind'] == 'field':
            if cell.get('value') not in fields:
                problems.append(f'{where} {n}: حقل غير معروف {cell.get("value")!r}')
        else:
            problem = _keys_problem(cell.get('value'), f'{where} {n}')
            if problem:
                problems.append(problem)
    return problems


def _popups_problems(popups):
    if not isinstance(popups, list):
        return ['النوافذ المنبثقة: يجب أن تكون قائمة']
    problems = []
    for n, rule in enumerate(popups, start=1):
        where = f'النافذة المنبثقة {n}'
        if not isinstance(rule, dict) or set(rule) - _POPUP_KEYS:
            problems.append(f'{where}: قاعدة غير صالحة')
            continue
        title, text = rule.get('title_contains', ''), rule.get('text_contains', '')
        if not isinstance(title, str) or not isinstance(text, str):
            problems.append(f'{where}: العنوان والنص يجب أن يكونا نصاً')
        elif not (title.strip() or text.strip()):   # an empty rule would match (and answer) every popup
            problems.append(f'{where}: اكتب جزءاً من العنوان أو النص')
        problem = _keys_problem(rule.get('answer_keys'), f'{where} — مفاتيح الرد')
        if problem:
            problems.append(problem)
    return problems


def _checklist_problems(items):
    if not isinstance(items, list) or not all(isinstance(t, str) and t.strip() and len(t) <= 200 for t in items):
        return ['قائمة المراجعة: أسطر نصية غير فارغة (200 حرف بحد أقصى)']
    return []


def _field_problems(name, value):
    if name == 'cancel_keys':
        return _cells_problems(value, 'مفاتيح الإلغاء', required=True)
    if name == 'save_keys':
        return _cells_problems(value, 'مفاتيح الحفظ')
    if name == 'ref_cells':
        problems = _cells_problems(value, 'خلايا المرجع', fields=('reference',))
        if not problems and value and not any(c['kind'] == 'field' for c in value):
            problems.append('خلايا المرجع: يجب أن تحتوي حقل المرجع')
        return problems
    if name == 'line_cells':
        problems = _cells_problems(value, 'خلايا السطر', fields=LINE_FIELDS, required=True)
        if not problems and not any(c['kind'] == 'field' for c in value):
            problems.append('خلايا السطر: لا يوجد حقل بيانات')
        return problems
    if name == 'popups':
        return _popups_problems(value)
    if name == 'header_checklist':
        return _checklist_problems(value)
    raise ValueError(name)


def recipe_problems(recipe) -> list:
    """Why this recipe cannot run a safe dry run (empty = it can). Checked at approval."""
    problems = [] if (recipe.window_title or '').strip() else ['عنوان النافذة فارغ']
    for name in ('line_cells', 'cancel_keys', 'save_keys', 'ref_cells', 'popups', 'header_checklist'):
        problems += _field_problems(name, getattr(recipe, name))
    return problems


def edit_recipe(recipe, profile, changes: dict) -> RpaRecipe:
    """An admin sets a DRAFT recipe's cancel keys, popup rules, checklist and reference cells.

    Approved and retired recipes stay frozen (the model guard backs this up). The edit is stamped
    on the recipe (edited_by / edited_at, the last editor) and logged; no admin who ever edited it
    can then approve it (approve_recipe), so four eyes still see the final content."""
    if not profile.is_admin:
        raise PermissionDenied('تعديل الوصفة للمدير فقط.')
    if not isinstance(changes, dict) or not changes:
        raise ValidationError({'detail': 'لا توجد تعديلات.'})
    unknown = set(changes) - set(EDITABLE_RECIPE_FIELDS)
    if unknown:
        raise ValidationError({'detail': 'حقول لا يمكن تعديلها: ' + '، '.join(sorted(unknown))})
    errors = {name: problems for name in changes if (problems := _field_problems(name, changes[name]))}
    if errors:
        raise ValidationError(errors)
    with transaction.atomic():
        recipe = RpaRecipe.objects.select_for_update().select_related('screen').get(pk=recipe.pk)
        if recipe.status != 'draft':
            raise ValidationError({'detail': 'الوصفة المعتمدة لا تتغير؛ استورد مسودة جديدة.'})
        old = {name: getattr(recipe, name) for name in changes}
        old['edited_by_id'] = recipe.edited_by_id
        for name, value in changes.items():
            setattr(recipe, name, value)
        recipe.edited_by = profile
        recipe.edited_at = timezone.now()
        recipe.save(update_fields=[*changes, 'edited_by', 'edited_at'])
        AuditLog.log('rpa_recipe_edited', user=profile, obj=recipe, old_data=old,
                     new_data={**changes, 'edited_by_id': profile.id},
                     note=f'تعديل مسودة وصفة {recipe.screen.title_ar} v{recipe.version}')
    return recipe


def set_screen_enabled(screen, profile, enabled: bool) -> RpaScreen:
    """Admin switch: whether the robot takes this screen's documents. `live` is not settable here
    (Stage 1 is dry run only)."""
    if not profile.is_admin:
        raise PermissionDenied('تفعيل الشاشات للمدير فقط.')
    with transaction.atomic():
        screen = RpaScreen.objects.select_for_update().get(pk=screen.pk)
        old = screen.enabled
        if old != enabled:
            screen.enabled = enabled
            screen.save(update_fields=['enabled'])
            AuditLog.log('rpa_screen_changed', user=profile, obj=screen,
                         old_data={'enabled': old}, new_data={'enabled': enabled},
                         note=f'{"تفعيل" if enabled else "إيقاف"} شاشة {screen.title_ar}')
    return screen


def _ever_edited_by(recipe, profile) -> bool:
    """Any past edit of this recipe by this admin, from the audit trail (edit_recipe logs each one)."""
    return AuditLog.objects.filter(action='rpa_recipe_edited', model_name='RpaRecipe',
                                   object_id=str(recipe.pk), user=profile).exists()


def approve_recipe(recipe, profile) -> RpaRecipe:
    """Four-eyes on a recipe: an admin who neither imported it nor ever edited it. Checked under the
    recipe row lock against the row (created_by, last editor edited_by) and the audit trail (every
    earlier editor; if retention ever prunes it, edited_by still holds the last one). The content
    must allow a safe dry run; the previous approved one retires."""
    if not profile.is_admin:
        raise PermissionDenied('اعتماد الوصفة للمدير فقط.')
    with transaction.atomic():
        RpaScreen.objects.select_for_update().get(pk=recipe.screen_id)   # one approval per screen at a time
        recipe = RpaRecipe.objects.select_for_update().get(pk=recipe.pk)
        if profile.id == recipe.created_by_id:
            raise PermissionDenied('لا يمكنك اعتماد وصفة قمت باستيرادها أنت.')
        if profile.id == recipe.edited_by_id or _ever_edited_by(recipe, profile):
            raise PermissionDenied('لا يمكنك اعتماد وصفة عدّلتها أنت.')
        if recipe.status != 'draft':
            raise ValidationError({'detail': 'يمكن اعتماد الوصفة وهي مسودة فقط.'})
        problems = recipe_problems(recipe)
        if problems:
            raise ValidationError({'detail': 'الوصفة غير مكتملة: ' + '؛ '.join(problems)})
        previous = (RpaRecipe.objects.select_for_update()
                    .filter(screen_id=recipe.screen_id, status='approved').first())
        if previous is not None and recipe.version < previous.version:
            raise ValidationError({'detail': f'الإصدار v{recipe.version} أقدم من المعتمد الحالي v{previous.version}.'})
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
