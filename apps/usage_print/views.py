"""
apps/usage_print/views.py — /api/usage-print/ (Project 5). Flag OFF → every endpoint 404.

  GET  sheet/?branch=<code>&number=<int>&date=YYYY-MM-DD   open (or re-check) the invoice's sheet
  POST lines/<id>/            {action: confirm|exclude|reset, text}
  POST sheets/<id>/print/     {layout: single|per_item} → slip payload (409 while a line is pending)
  POST sheets/<id>/prescription/   multipart prescription photo
  GET|PUT settings/           presets + slip settings (PUT = RBAC edit)
"""
import datetime as _dt

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from core import branch_scope

from . import services
from .access import Access
from .lookup import LiveUnavailable, find_invoice
from .models import UsagePreset, UsageSheet, UsageSheetLine
from .slip import SLIP_SETTINGS, build_slip, save_slip_settings, slip_settings

MAX_DAYS_BACK = 7


def _access(request, need='view'):
    a = Access(request)
    if not a.can_view:
        raise Http404   # flag off or no module access: the screen does not exist
    if need == 'create' and not a.can_create or need == 'edit' and not a.can_edit:
        return a, Response({'detail': 'ليس لديك صلاحية لهذا الإجراء.'}, status=status.HTTP_403_FORBIDDEN)
    return a, None


def _presets():
    out = {k: [] for k, _ in UsagePreset.KIND_CHOICES}
    for p in UsagePreset.objects.filter(is_active=True):
        out[p.kind].append(p.text)
    return out


def _line_json(ln):
    return {'id': ln.id, 'itemcode': ln.itemcode, 'item_name': ln.item_name, 'quantity': str(ln.quantity),
            'suggested_text': ln.suggested_text, 'suggestion_source': ln.suggestion_source,
            'suggestion_label': ln.get_suggestion_source_display(), 'text': ln.text, 'status': ln.status,
            'confirmed_by': ln.confirmed_by.full_name if ln.confirmed_by_id else '',
            'confirmed_at': ln.confirmed_at}


def _image_url(sheet):
    if sheet.prescription_image:
        return sheet.prescription_image.url, 'sheet'
    order = sheet.pos_order
    if order is not None and order.prescription_image:
        return order.prescription_image.url, 'pos'
    return None, ''


def _sheet_json(sheet, access):
    url, origin = _image_url(sheet)
    lines = list(sheet.lines.select_related('confirmed_by'))
    return {
        'id': sheet.id, 'invoice_id': sheet.softech_invoice_id, 'docnumber': sheet.docnumber,
        'docdate': sheet.docdate, 'source': sheet.source,
        'branch': {'code': sheet.branch.softech_branch_id, 'name': str(sheet.branch.name_ar or sheet.branch.name)},
        'patient_name': sheet.patient_name, 'invoice_changed': sheet.invoice_changed,
        'pos_order_id': sheet.pos_order_id, 'prescription_image': url, 'prescription_origin': origin,
        'print_count': sheet.print_count, 'last_printed_at': sheet.last_printed_at,
        'lines': [_line_json(ln) for ln in lines],
        'ready': bool(lines) and all(ln.status != UsageSheetLine.STATUS_PENDING for ln in lines)
                 and any(ln.status == UsageSheetLine.STATUS_CONFIRMED for ln in lines),
        'presets': _presets(), 'perms': access.as_dict(),
    }


def _scoped_sheet(request, pk):
    sheet = UsageSheet.objects.select_related('branch', 'pos_order').filter(pk=pk).first()
    if sheet is None or not branch_scope.allows(request.user, sheet.branch_id):
        raise Http404
    return sheet


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sheet_lookup(request):
    access, denied = _access(request)
    if denied:
        return denied
    p = request.query_params
    try:
        number = int(str(p.get('number', '')).strip())
        if number <= 0:
            raise ValueError
    except ValueError:
        return Response({'detail': 'اكتب رقم الفاتورة (أرقام فقط).'}, status=status.HTTP_400_BAD_REQUEST)
    today = timezone.localdate()
    try:
        docdate = _dt.date.fromisoformat(p['date']) if p.get('date') else today
    except ValueError:
        return Response({'detail': 'تاريخ غير صحيح.'}, status=status.HTTP_400_BAD_REQUEST)
    if docdate > today or (today - docdate).days > MAX_DAYS_BACK:
        return Response({'detail': f'التاريخ يجب أن يكون خلال آخر {MAX_DAYS_BACK} أيام.'},
                        status=status.HTTP_400_BAD_REQUEST)
    profile = access.profile
    code = (p.get('branch') or '').strip() or (profile.branch.softech_branch_id if profile.branch_id else '')
    branch = Branch.objects.filter(softech_branch_id=code).first() if code else None
    if branch is None:
        return Response({'detail': 'اختار الفرع.'}, status=status.HTTP_400_BAD_REQUEST)
    if not branch_scope.allows(request.user, branch.id):
        return Response({'detail': 'هذا الفرع خارج صلاحياتك.'}, status=status.HTTP_403_FORBIDDEN)
    try:
        inv = find_invoice(branch, number, docdate)
    except LiveUnavailable:
        return Response({'detail': 'تعذر الوصول للفاتورة الآن — حاول بعد دقائق.'},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if inv is None:
        return Response({'detail': 'الفاتورة غير موجودة لهذا الفرع في هذا اليوم.'}, status=status.HTTP_404_NOT_FOUND)
    sheet = services.open_sheet(inv, profile)
    return Response(_sheet_json(sheet, access))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def line_action(request, pk):
    access, denied = _access(request, 'create')
    if denied:
        return denied
    line = UsageSheetLine.objects.select_related('sheet', 'confirmed_by').filter(pk=pk).first()
    if line is None or not branch_scope.allows(request.user, line.sheet.branch_id):
        raise Http404
    try:
        services.set_line(line, request.data.get('action'), request.data.get('text'), access.profile, request)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    sheet = _scoped_sheet(request, line.sheet_id)
    return Response(_sheet_json(sheet, access))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def sheet_print(request, pk):
    access, denied = _access(request, 'create')
    if denied:
        return denied
    sheet = _scoped_sheet(request, pk)
    layout = request.data.get('layout') or UsageSheet.LAYOUT_SINGLE
    if layout not in dict(UsageSheet.LAYOUT_CHOICES):
        return Response({'detail': 'شكل طباعة غير معروف.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        sheet = services.mark_printed(sheet, layout, access.profile, request)
    except services.NotReady as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response({'slip': build_slip(sheet, layout), 'sheet': _sheet_json(sheet, access)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def sheet_prescription(request, pk):
    from apps.pos_orders.views import prescription_image_error
    access, denied = _access(request, 'create')
    if denied:
        return denied
    sheet = _scoped_sheet(request, pk)
    f = request.FILES.get('prescription_image') or request.FILES.get('file')
    error = prescription_image_error(f)
    if error:
        return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
    sheet.prescription_image = f
    sheet.save(update_fields=['prescription_image', 'updated_at'])
    AuditLog.log('usage_rx_attached', user=access.profile, obj=sheet, request=request,
                 extra={'invoice': sheet.softech_invoice_id})
    return Response(_sheet_json(sheet, access))


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def settings_view(request):
    access, denied = _access(request, 'edit' if request.method == 'PUT' else 'view')
    if denied:
        return denied
    if request.method == 'PUT':
        changes = {}
        presets = request.data.get('presets')
        with transaction.atomic():
            if isinstance(presets, dict):
                before = _presets()
                kinds = dict(UsagePreset.KIND_CHOICES)
                for kind, texts in presets.items():
                    if kind not in kinds or not isinstance(texts, list):
                        continue
                    clean = [str(t).strip()[:200] for t in texts if str(t).strip()][:60]
                    if clean == before.get(kind):
                        continue
                    UsagePreset.objects.filter(kind=kind).delete()
                    UsagePreset.objects.bulk_create(
                        [UsagePreset(kind=kind, text=t, sort_order=i) for i, t in enumerate(clean)])
                    changes[f'presets.{kind}'] = [before.get(kind), clean]
            if isinstance(request.data.get('slip'), dict):
                changes.update(save_slip_settings(request.data['slip']))
        if changes:
            AuditLog.log('usage_settings_changed', user=access.profile, request=request, changes=changes)
    return Response({
        'presets': _presets(),
        'slip': slip_settings(),
        'slip_labels': {k: label for k, (label, _d) in SLIP_SETTINGS.items()},
        'perms': access.as_dict(),
    })
