"""
apps/config/code_maps.py  (piece 4 — item & channel codes, Task 5)
===================================================================
The owner's editing API behind the /code-maps screen:

  GET   /api/config/code-maps/channels/          customer channels (ChannelBucketMap, pt '10')
  PATCH /api/config/code-maps/channels/<pk>/     group · is_contract_sale · followup_rank
  GET   /api/config/code-maps/item-types/        item categories (MedicineTypeMap)
  PATCH /api/config/code-maps/item-types/<pk>/   group · is_medicine · excluded_from_planning

GET needs settings/view, PATCH settings/edit (server-side matrix). Only the meaning
fields are writable here — the KPI bucket / subtype / counts / profit flags stay in the
Django admin + KPI config, so KPI figures never move from this screen; any other key in
the body is ignored. Every real change writes one `code_map_changed` AuditLog row with
the before/after values; a PATCH that changes nothing writes none. The readers'
caches drop on save (post_save signals on both models).
"""
from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.config import item_types
from apps.config.models import MedicineTypeMap
from apps.forecasting import channels
from apps.forecasting.models import ChannelBucketMap
from core.permissions import matrix_permission

SETTINGS = matrix_permission('settings')     # GET → view · PATCH → edit
SALES_WINDOW_DAYS = 90

_GROUP_ERR = {'invalid_choice': 'مجموعة غير معروفة.', 'null': 'المجموعة مطلوبة.',
              'blank': 'المجموعة مطلوبة.'}
_BOOL_ERR = {'invalid': 'قيمة غير صحيحة (نعم / لا).', 'null': 'قيمة غير صحيحة (نعم / لا).'}
_RANK_ERR = {'invalid': 'أولوية المتابعة رقم من 1 إلى 4 أو فارغة.',
             'min_value': 'أولوية المتابعة رقم من 1 إلى 4 أو فارغة.',
             'max_value': 'أولوية المتابعة رقم من 1 إلى 4 أو فارغة.',
             'max_string_length': 'أولوية المتابعة رقم من 1 إلى 4 أو فارغة.'}
_EMPTY_MEDICINE = ('لا يمكن إلغاء آخر تصنيف دواء: يجب أن يبقى تصنيف واحد على الأقل «دواء»، '
                   'وإلا تتوقف متابعات إعادة الصرف والأمراض المزمنة.')


class ChannelPatchSerializer(serializers.Serializer):
    group = serializers.ChoiceField(choices=ChannelBucketMap.GROUP_CHOICES, required=False,
                                    error_messages=_GROUP_ERR)
    is_contract_sale = serializers.BooleanField(required=False, error_messages=_BOOL_ERR)
    followup_rank = serializers.IntegerField(required=False, allow_null=True, min_value=1,
                                             max_value=4, error_messages=_RANK_ERR)


class ItemTypePatchSerializer(serializers.Serializer):
    group = serializers.ChoiceField(choices=MedicineTypeMap.GROUP_CHOICES, required=False,
                                    error_messages=_GROUP_ERR)
    is_medicine = serializers.BooleanField(required=False, error_messages=_BOOL_ERR)
    excluded_from_planning = serializers.BooleanField(required=False, error_messages=_BOOL_ERR)


def _first_error(errors) -> str:
    """One Arabic sentence out of a serializer's errors (our own messages only)."""
    for msgs in errors.values():
        if isinstance(msgs, (list, tuple)) and msgs:
            return str(msgs[0])
    return 'بيانات غير صحيحة.'


def _bad(text: str) -> Response:
    return Response({'detail': text}, status=status.HTTP_400_BAD_REQUEST)


def _apply(row, data: dict, request) -> bool:
    """Write the changed fields of `data` onto `row` and audit them. True when anything changed."""
    from apps.audit.models import AuditLog
    old, new = {}, {}
    for field, value in data.items():
        if getattr(row, field) != value:
            old[field], new[field] = getattr(row, field), value
            setattr(row, field, value)
    if not new:
        return False
    fields = list(new)
    if any(f.name == 'updated_at' for f in row._meta.concrete_fields):
        fields.append('updated_at')
    row.save(update_fields=fields)
    AuditLog.log('code_map_changed', user=getattr(request.user, 'staff_profile', None), obj=row,
                 old_data=old, new_data=new, request=request)
    return True


# ── Channels ───────────────────────────────────────────────────────────────────

def _sales_90d(codes) -> dict:
    since = timezone.now() - dt.timedelta(days=SALES_WINDOW_DAYS)
    from apps.customers.models import PurchaseHistory
    return dict(PurchaseHistory.objects
                .filter(doc_code='115', invoice_date__gte=since, sales_channel__in=list(codes))
                .values('sales_channel').annotate(n=Count('id'))
                .values_list('sales_channel', 'n'))


def _channel_dict(row, sales: dict) -> dict:
    return {
        'id': row.pk, 'code': row.channel, 'label': row.label or '',
        'group': row.group, 'group_label': channels.GROUP_LABELS.get(row.group, row.group),
        'bucket': row.bucket, 'bucket_label': row.get_bucket_display(),
        'is_contract_sale': bool(row.is_contract_sale), 'followup_rank': row.followup_rank,
        'sales_90d': sales.get(row.channel, 0),
    }


def _channel_sort_key(row):
    big = 10 ** 6
    return (row.group != 'unclassified',
            row.followup_rank if row.followup_rank is not None else big, row.channel)


@api_view(['GET'])
@permission_classes([IsAuthenticated, SETTINGS])
def channel_list(request):
    channels.ensure_defaults()
    rows = sorted(ChannelBucketMap.objects.filter(person_type=channels.CUSTOMER_PT),
                  key=_channel_sort_key)
    sales = _sales_90d(r.channel for r in rows)
    return Response([_channel_dict(r, sales) for r in rows])


@api_view(['PATCH'])
@permission_classes([IsAuthenticated, SETTINGS])
def channel_detail(request, pk: int):
    ser = ChannelPatchSerializer(data=request.data)
    if not ser.is_valid():
        return _bad(_first_error(ser.errors))
    with transaction.atomic():
        row = get_object_or_404(ChannelBucketMap.objects.select_for_update(),
                                pk=pk, person_type=channels.CUSTOMER_PT)
        _apply(row, ser.validated_data, request)
    return Response(_channel_dict(row, _sales_90d([row.channel])))


# ── Item categories ──────────────────────────────────────────────────────────────

def _item_counts(codes) -> dict:
    from apps.catalog.models import Item
    return dict(Item.objects.filter(is_active=True, medicine_type__in=list(codes))
                .values('medicine_type').annotate(n=Count('id'))
                .values_list('medicine_type', 'n'))


def _item_type_dict(row, counts: dict) -> dict:
    return {
        'id': row.pk, 'code': row.code, 'label': row.label or '',
        'group': row.group, 'group_label': row.get_group_display(),
        'is_medicine': bool(row.is_medicine),
        'excluded_from_planning': bool(row.excluded_from_planning),
        'item_count': counts.get(row.code, 0),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated, SETTINGS])
def item_type_list(request):
    rows = sorted(item_types.all_types(), key=lambda r: (r.group != 'unclassified', r.code))
    counts = _item_counts(r.code for r in rows)
    return Response([_item_type_dict(r, counts) for r in rows])


@api_view(['PATCH'])
@permission_classes([IsAuthenticated, SETTINGS])
def item_type_detail(request, pk: int):
    ser = ItemTypePatchSerializer(data=request.data)
    if not ser.is_valid():
        return _bad(_first_error(ser.errors))
    data = ser.validated_data
    with transaction.atomic():
        row = get_object_or_404(MedicineTypeMap.objects.select_for_update(), pk=pk)
        # An empty medicine set would make refill / chronic inference switch every
        # inferred profile off — refuse the change that would leave none. The medicine
        # rows are locked so two owners un-ticking the last two at once cannot both pass.
        if row.is_medicine and data.get('is_medicine') is False:
            others = [r.pk for r in MedicineTypeMap.objects.select_for_update()
                      .filter(is_medicine=True).exclude(pk=row.pk)]
            if not others:
                return _bad(_EMPTY_MEDICINE)
        _apply(row, data, request)
    return Response(_item_type_dict(row, _item_counts([row.code])))
