"""Staff REST API of the screen robot (/api/rpa/): jobs, documents, recipes, devices, status.

Backend owns the rules (workflow.py / dld.py / dispatch.py); these views only authenticate, scope to the
user's branches, parse uploads and shape responses. Nothing here writes to SOFTECH.
"""
import json
import re
from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from core import branch_scope
from core.errors import public_error
from core.permissions import matrix_permission
from core.sort_ordering import NullsLastOrderingFilter, explicit_order_by
from core.upload_safety import max_upload_bytes

from . import workflow
from .dld import decode_dld, parse_dld, recipe_from_dld
from .models import RpaDevice, RpaDocument, RpaJob, RpaRecipe, RpaScreen
from .serializers import (DeviceSerializer, DocumentDetailSerializer, JobDetailSerializer, JobListSerializer,
                          RecipeSerializer, ScreenSerializer)

STAGE1_SCREENS = ('issue_125',)
_ARABIC = re.compile(r'[؀-ۿ]')
_REF = re.compile(r'مرجع:\s*(\w+)')

# Keys the /rpa screen sends as ?ordering= (optionally '-' prefixed) -> model field; branches sort by name.
JOB_SORT_KEYS = {'id': 'id', 'created_at': 'created_at', 'screen': 'screen__title_ar', 'branch': 'branch__name',
                 'target_branch': 'target_branch__name', 'filename': 'filename', 'status': 'status'}

RPA = matrix_permission('rpa')
RPA_APPROVE = matrix_permission('rpa', post=('approve',))
RPA_EDIT = matrix_permission('rpa', post=('edit',))


class RpaAdminOnly(BasePermission):
    """Recipes are company-level: importing and approving one is the admin's job (profile.is_admin)."""
    message = 'هذا الإجراء للمدير فقط.'

    def has_permission(self, request, view):
        profile = getattr(request.user, 'staff_profile', None)
        return bool(profile is not None and profile.is_active and profile.is_admin)


def _profile(request):
    return request.user.staff_profile


def _bad_input(request, exc, fallback):
    """A 400 for a file we could not read. Our own Arabic messages pass; anything else (openpyxl, codec,
    zip internals) is logged through public_error and the caller only sees `fallback` and the log ref."""
    if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) and _ARABIC.search(str(exc)):
        return ValidationError({'detail': str(exc)})
    shown = public_error(request, exc)
    ref = _REF.search(shown)
    suffix = f' (مرجع: {ref.group(1)})' if ref else ''
    return ValidationError({'detail': fallback + suffix})


def _check_upload(upload, *, extensions=None):
    if upload is None:
        raise ValidationError({'file': 'يجب إرفاق ملف.'})
    if upload.size > max_upload_bytes():
        raise ValidationError({'file': 'الملف أكبر من الحد المسموح.'})
    if extensions and not (upload.name or '').lower().endswith(extensions):
        raise ValidationError({'file': 'نوع الملف غير مدعوم.'})


def _branch(value, field):
    try:
        return Branch.objects.get(pk=int(value))
    except (TypeError, ValueError, Branch.DoesNotExist):
        raise ValidationError({field: 'فرع غير صالح.'})


# ── Jobs ─────────────────────────────────────────────────────────────────────

def _scoped_jobs(profile):
    qs = RpaJob.objects.select_related('screen', 'branch', 'target_branch', 'created_by__user', 'approved_by__user',
                                       'recipe').annotate(
        documents_count=Count('documents', distinct=True), lines_count=Count('documents__lines', distinct=True))
    return branch_scope.scope(qs, profile, 'branch')


class JobListCreateView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, RPA]
    serializer_class = JobListSerializer
    filter_backends = []          # ordering is explicit (whitelist below); unknown keys -> 400
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = _scoped_jobs(_profile(self.request))
        wanted = self.request.query_params.get('status')
        if wanted:
            qs = qs.filter(status=wanted)
        return qs.order_by(*explicit_order_by(self.request.query_params.get('ordering'), JOB_SORT_KEYS,
                                              ('-created_at', '-id')))

    def post(self, request):
        profile = _profile(request)
        data = request.data
        screen_key = (data.get('screen') or '').strip()
        if screen_key not in STAGE1_SCREENS:
            raise ValidationError({'screen': 'هذه الشاشة غير متاحة في المرحلة الأولى.'})
        if 'dry_run' in data and str(data.get('dry_run')).strip().lower() not in ('1', 'true', 'yes', 'on'):
            raise ValidationError({'dry_run': 'المرحلة الأولى تجريبية فقط (بدون إدخال فعلي).'})
        branch = _branch(data.get('branch'), 'branch')
        target = _branch(data.get('target_branch'), 'target_branch')
        upload = request.FILES.get('file')
        _check_upload(upload)
        try:
            job = workflow.create_job(profile=profile, screen_key=screen_key, branch=branch, target_branch=target,
                                      store_code=data.get('store_code') or '', upload=upload)
        except RpaScreen.DoesNotExist:
            raise ValidationError({'screen': 'الشاشة غير موجودة.'})
        except APIException:
            raise
        except Exception as exc:   # noqa: BLE001 - ValueError/UnicodeDecodeError/openpyxl/BadZipFile: 400, never raw text
            raise _bad_input(request, exc, 'تعذّرت قراءة الملف؛ تأكد أنه ملف Excel أو CSV سليم بعمودي الكود والكمية.')
        job = _scoped_jobs(profile).get(pk=job.pk)
        return Response(JobDetailSerializer(job, context={'request': request}).data, status=status.HTTP_201_CREATED)


def _job_or_404(request, pk):
    return branch_scope.get_or_404(_scoped_jobs(_profile(request)), _profile(request), pk=pk)


@api_view(['GET'])
@permission_classes([IsAuthenticated, RPA])
def job_detail(request, pk):
    job = _job_or_404(request, pk)
    return Response(JobDetailSerializer(job, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, RPA_APPROVE])
def job_approve(request, pk):
    job = _job_or_404(request, pk)
    workflow.approve_job(job, _profile(request))
    return Response(JobDetailSerializer(_job_or_404(request, pk), context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, RPA_APPROVE])
def job_cancel(request, pk):
    job = _job_or_404(request, pk)
    workflow.cancel_job(job, _profile(request), request.data.get('reason', ''))
    return Response(JobDetailSerializer(_job_or_404(request, pk), context={'request': request}).data)


# ── Documents ────────────────────────────────────────────────────────────────

def _document_or_404(request, pk):
    qs = RpaDocument.objects.select_related('job__screen', 'job__branch', 'job__target_branch', 'claimed_by')
    return branch_scope.get_or_404(qs, _profile(request), field='job__branch', pk=pk)


def _document_response(request, pk):
    doc = _document_or_404(request, pk)
    return Response(DocumentDetailSerializer(doc, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated, RPA])
def document_detail(request, pk):
    return _document_response(request, pk)


@api_view(['POST'])
@permission_classes([IsAuthenticated, RPA_EDIT])
def document_resolve(request, pk):
    document = _document_or_404(request, pk)
    from apps.rpa.dispatch import resolve_document   # Task 8 module; imported late so the API loads without it
    resolve_document(document, _profile(request), request.data.get('decision', ''), request.data.get('reason', ''))
    return _document_response(request, pk)


# ── Recipes ──────────────────────────────────────────────────────────────────

class RecipeListCreateView(generics.ListAPIView):
    serializer_class = RecipeSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [NullsLastOrderingFilter]
    ordering_fields = ['id', 'version', 'status', 'created_at', 'approved_at']
    ordering = ['-version', '-id']

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [IsAuthenticated(), RPA()]
        return [IsAuthenticated(), RpaAdminOnly()]

    def get_queryset(self):
        return RpaRecipe.objects.select_related('screen', 'created_by__user', 'approved_by__user')

    def post(self, request):
        profile = _profile(request)
        screen_key = (request.data.get('screen') or '').strip()
        if screen_key not in STAGE1_SCREENS:
            raise ValidationError({'screen': 'هذه الشاشة غير متاحة في المرحلة الأولى.'})
        screen = RpaScreen.objects.filter(key=screen_key).first()
        if screen is None:
            raise ValidationError({'screen': 'الشاشة غير موجودة.'})
        upload = request.FILES.get('file')
        _check_upload(upload, extensions=('.dld',))
        raw_map = request.data.get('field_map')
        try:
            field_map = json.loads(raw_map) if isinstance(raw_map, str) else raw_map
        except ValueError:
            field_map = None
        if (not isinstance(field_map, list) or not field_map
                or not all(isinstance(n, str) and n.strip() for n in field_map)):
            raise ValidationError({'field_map': 'field_map يجب أن تكون قائمة بأسماء الحقول بترتيب أعمدة البيانات.'})
        try:
            template = parse_dld(decode_dld(upload.read()))
            recipe = recipe_from_dld(template, screen=screen, field_map=[n.strip() for n in field_map],
                                     created_by=profile, source_filename=(upload.name or '')[:255])
        except Exception as exc:   # noqa: BLE001 - parser / codec errors: 400 with a log reference, never raw text
            raise _bad_input(request, exc, 'تعذّر استيراد القالب؛ تأكد أنه ملف .dld سليم وأن أسماء الحقول بعدد أعمدة البيانات.')
        recipe = self.get_queryset().get(pk=recipe.pk)
        return Response(RecipeSerializer(recipe).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated, RpaAdminOnly])
def recipe_approve(request, pk):
    recipe = generics.get_object_or_404(RpaRecipe.objects.select_related('screen'), pk=pk)
    workflow.approve_recipe(recipe, _profile(request))
    recipe = RpaRecipe.objects.select_related('screen', 'created_by__user', 'approved_by__user').get(pk=pk)
    return Response(RecipeSerializer(recipe).data)


# ── Devices ──────────────────────────────────────────────────────────────────

def _devices_for(profile):
    qs = RpaDevice.objects.select_related('staff__user')
    return qs if profile.is_admin else qs.filter(staff=profile)


class DeviceListCreateView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, RPA]
    serializer_class = DeviceSerializer
    filter_backends = [NullsLastOrderingFilter]
    ordering_fields = ['id', 'label', 'created_at', 'last_seen_at', 'revoked_at']
    ordering = ['-created_at', '-id']

    def get_queryset(self):
        return _devices_for(_profile(self.request))

    def post(self, request):
        profile = _profile(request)
        label = (request.data.get('label') or '').strip()
        if not label:
            raise ValidationError({'label': 'اكتب اسم الجهاز.'})
        from apps.rpa.auth import issue_device   # Task 8 module
        device, token = issue_device(staff=profile, label=label[:120], created_by=profile)
        # The token is returned here and nowhere else; only its hash is stored.
        return Response({'device': DeviceSerializer(device).data, 'token': token}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated, RPA])
def device_revoke(request, pk):
    profile = _profile(request)
    device = generics.get_object_or_404(_devices_for(profile), pk=pk)
    if device.revoked_at is None:
        device.revoked_at = timezone.now()
        device.save(update_fields=['revoked_at'])
        AuditLog.log('rpa_device_revoked', user=profile, obj=device,
                     new_data={'label': device.label, 'owner_id': device.staff_id}, note=f'إيقاف جهاز {device.label}')
    return Response(DeviceSerializer(device).data)


# ── Status ───────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated, RPA])
def rpa_status(request):
    profile = _profile(request)
    mine = RpaDevice.objects.filter(staff=profile, revoked_at__isnull=True,
                                    last_seen_at__gte=timezone.now() - timedelta(minutes=2))
    return Response({
        'switch_on': bool(getattr(settings, 'RPA_SOFTECH_ENTRY_ENABLED', False)),
        'screens': ScreenSerializer(RpaScreen.objects.order_by('id'), many=True).data,
        'my_devices_online': DeviceSerializer(mine.select_related('staff__user'), many=True).data,
    })
