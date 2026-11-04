"""
Counselling sheet workflow — the only code that changes a sheet. Every change is audited.

draft ──submit──▶ pending_review ──approve──▶ approved ──edit──▶ draft (the approved snapshot keeps
serving until the next approval) · any ──retire──▶ retired (nothing reaches customers any more).
An AI draft is created here like any other draft; only a human's approve() makes text customer-facing.
"""
import datetime as dt

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.catalog.models import Item

from .models import CONTENT_FIELDS, CounsellingContent, CounsellingContentItem, CounsellingContentVersion

MAX_FIELD_LEN = 2000


def _clean(data: dict) -> dict:
    out = {}
    for f in CONTENT_FIELDS:
        if f in data:
            v = data[f]
            out[f] = '' if v is None else str(v).strip()[:MAX_FIELD_LEN]
    if 'title' in data:
        out['title'] = str(data['title'] or '').strip()[:200]
    if out.get('with_food', '') not in ('', 'before', 'after', 'any'):
        raise ValidationError({'with_food': 'قيمة غير صحيحة'})
    return out


def _check_free(item_ids, content=None):
    taken = CounsellingContentItem.objects.filter(item_id__in=item_ids)
    if content is not None:
        taken = taken.exclude(content=content)
    if taken.exists():
        raise ValidationError({'items': 'الصنف مرتبط بإرشاد آخر'})


@transaction.atomic
def create_sheet(actor, data: dict, item_ids: list, source: str = 'manual', ai_model: str = ''):
    ids = sorted({int(i) for i in item_ids or []})
    if not ids:
        raise ValidationError({'items': 'اختر صنفاً واحداً على الأقل'})
    items = list(Item.objects.filter(pk__in=ids))
    if len(items) != len(ids):
        raise ValidationError({'items': 'صنف غير موجود'})
    _check_free(ids)
    fields = _clean(data)
    if not fields.get('title'):
        fields['title'] = items[0].name
    c = CounsellingContent.objects.create(source=source, ai_model=ai_model[:80], created_by=actor,
                                          updated_by=actor, **fields)
    for it in items:
        CounsellingContentItem.objects.create(content=c, item=it, linked_by=actor)
    AuditLog.log('counselling_drafted', user=actor, obj=c, new_data=c.snapshot(),
                 extra={'items': ids, 'source': source, 'ai_model': ai_model})
    return c


@transaction.atomic
def edit_sheet(actor, content, data: dict):
    content = CounsellingContent.objects.select_for_update().get(pk=content.pk)
    if content.status == 'retired':
        raise ValidationError({'detail': 'الإرشاد مسحوب — لا يمكن تعديله'})
    before = content.snapshot()
    for k, v in _clean(data).items():
        setattr(content, k, v)
    if content.status in ('approved', 'pending_review'):
        content.status = 'draft'          # the approved snapshot keeps serving until re-approved
    content.updated_by = actor
    content.save()
    changes = {k: [before[k], v] for k, v in content.snapshot().items() if before[k] != v}
    AuditLog.log('counselling_edited', user=actor, obj=content, old_data=before, changes=changes)
    return content


@transaction.atomic
def submit(actor, content):
    content = CounsellingContent.objects.select_for_update().get(pk=content.pk)
    if content.status != 'draft':
        raise ValidationError({'detail': 'يمكن إرسال المسودات فقط للاعتماد'})
    content.status, content.updated_by = 'pending_review', actor
    content.save(update_fields=['status', 'updated_by', 'updated_at'])
    AuditLog.log('counselling_submitted', user=actor, obj=content)
    return content


@transaction.atomic
def approve(actor, content):
    content = CounsellingContent.objects.select_for_update().get(pk=content.pk)
    if content.status not in ('draft', 'pending_review'):
        raise ValidationError({'detail': 'لا توجد تعديلات بانتظار الاعتماد'})
    if not (content.how_to_use_ar.strip() or content.dose_ar.strip()):
        raise ValidationError({'detail': 'أدخل طريقة الاستخدام أو الجرعة'})
    version = CounsellingContentVersion.objects.create(
        content=content, version=content.version + 1, data=content.snapshot(), approved_by=actor)
    content.version, content.approved_version = version.version, version
    content.status, content.approved_by, content.approved_at = 'approved', actor, timezone.now()
    content.save()
    AuditLog.log('counselling_approved', user=actor, obj=content, new_data=version.data,
                 extra={'version': version.version, 'source': content.source})
    return version


@transaction.atomic
def retire(actor, content, reason: str):
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError({'reason': 'اذكر سبب السحب'})
    content = CounsellingContent.objects.select_for_update().get(pk=content.pk)
    content.status, content.retired_reason, content.updated_by = 'retired', reason[:255], actor
    content.save(update_fields=['status', 'retired_reason', 'updated_by', 'updated_at'])
    AuditLog.log('counselling_retired', user=actor, obj=content, note=reason[:255])
    return content


@transaction.atomic
def link_items(actor, content, item_ids):
    ids = sorted({int(i) for i in item_ids or []})
    items = list(Item.objects.filter(pk__in=ids))
    if len(items) != len(ids):
        raise ValidationError({'items': 'صنف غير موجود'})
    _check_free(ids, content)
    added = []
    for it in items:
        _, created = CounsellingContentItem.objects.get_or_create(item=it, defaults={'content': content,
                                                                                     'linked_by': actor})
        if created:
            added.append(it.pk)
    if added:
        AuditLog.log('counselling_item_linked', user=actor, obj=content, extra={'items': added})
    return added


@transaction.atomic
def unlink_item(actor, content, item_id):
    deleted, _ = CounsellingContentItem.objects.filter(content=content, item_id=int(item_id)).delete()
    if deleted:
        AuditLog.log('counselling_item_unlinked', user=actor, obj=content, extra={'item': int(item_id)})
    return bool(deleted)


def suggest_items(content, limit: int = 20) -> list:
    """Items that probably share this sheet (other pack sizes / codes) — suggestions only, never linked."""
    from django.contrib.postgres.search import TrigramSimilarity
    first = content.links.select_related('item').order_by('linked_at').first()
    if first is None:
        return []
    base = first.item
    qs = (Item.objects.filter(is_active=True, counselling_link__isnull=True)
          .exclude(pk=base.pk)
          .annotate(sim=TrigramSimilarity('name', base.name))
          .filter(sim__gte=0.35))
    if base.shape_name:
        qs = qs.filter(shape_name=base.shape_name)
    return [{'item_id': i.pk, 'softech_id': i.softech_id, 'name': i.name, 'similarity': round(i.sim, 2)}
            for i in qs.order_by('-sim', 'name')[:limit]]


def needs_content_queue(days: int = 30, limit: int = 200) -> list:
    """Active items sold recently with no sheet yet, most sold first — where curation pays off most."""
    from apps.customers.models import PurchaseHistoryLine
    since = timezone.now() - dt.timedelta(days=days)
    rows = (PurchaseHistoryLine.objects
            .filter(purchase__invoice_date__gte=since, item__is_active=True,
                    item__counselling_link__isnull=True, quantity__gt=0)
            .values('item_id', 'item__name', 'item__softech_id')
            .annotate(sold=Sum('quantity'))
            .order_by('-sold', 'item_id')[:limit])
    return [{'item_id': r['item_id'], 'name': r['item__name'], 'softech_id': r['item__softech_id'],
             'sold': float(r['sold'] or 0)} for r in rows]
