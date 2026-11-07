"""
apps/data_lifecycle/register.py

Every lifecycle rule, in code. Admins can change a rule's mode and lengthen its period through
policy.set_policy; they cannot add a rule or go below its minimum (design §4, §6 Stage 3).

Company-level by nature, no branch scoping; see models.py for who may see it. No SOFTECH reads or writes.

Limits are in days and counts. "Count" means rows for a row rule and files for a file rule.
"""
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from django.apps import apps
from django.db import models

from apps.sync.maintenance import (
    AUDIT_NOISE_DAYS, NOTIF_UNREAD_DAYS, PBX_EVENT_DAYS, SLOW_REQUEST_DAYS,
)

KIND_ROW = 'row'
KIND_FILE = 'file'
KIND_P56 = 'p56'

# No rule may select rows of these apps: money, permissions, approvals, finance, insurance (§8).
PROTECTED_APPS = frozenset({'finance', 'payments', 'insurance', 'users', 'audit', 'access'})

# The only way a rule may touch a protected app: clear this file field and keep the row.
PROTECTED_FILE_TARGETS = frozenset({
    'payments.ExternalPayment.screenshot',
    'payments.BankStatementImport.raw_file',
})

# images.ImageCandidate.status (apps/images/models.py CANDIDATE_STATUS). Only the rejected and unreviewed
# groups are selected by age. `auto_approved` counts as approved. `new` and `error` have no rule: default
# is keep. Approved images on an obsolete item are the images_obsolete rule's, whatever the status.
IMAGE_REJECTED_STATUSES = ('rejected',)
IMAGE_UNREVIEWED_STATUSES = ('scored', 'pending_review')
IMAGE_APPROVED_STATUSES = ('approved', 'auto_approved')


@dataclass(frozen=True)
class Rule:
    """One lifecycle rule.

    kind          `row`, `file`, or `p56` (an existing step of apps/sync/maintenance.py, listed only so
                  the owner sees one complete list; always on and not changeable here).
    floor_days    The written floor, or None if the design sets none. The period can never go below the
                  floor, or below default_days when there is no floor (policy.minimum_days).
    default_days  The period, or None when the rule does not keep by a number of days (rate_runs,
                  p56_engine). Such a rule refuses a period change.
    margin        Circuit breaker: the count a run may remove with no recent preview, its normal volume.
    ceiling       Circuit breaker: the count a run may never exceed. margin and ceiling are None for p56.
    candidates    Called with no arguments. A `row` rule returns a list of querysets, a `file` rule a list
                  of file candidates. None for p56. The runner never calls it for a p56 rule.
    targets       What the rule may touch. `row`: 'app.Model'. `file`: 'app.Model.field', and these count
                  as classified. Empty for a file rule with no field (bundle_pages, unreferenced) and
                  for p56.
    age_field     {'app.Model': date field} for a rule that ages by a date on the record, one entry per
                  target model because the names differ. None for a rule that ages some other way.
    apply         When set, the runner calls it for a real run instead of deleting the candidates. The
                  rate rule needs this: prune_engine_runs stays the only code that deletes those rows.
    """
    key: str
    label_ar: str
    label_en: str
    kind: str
    floor_days: Optional[int]
    default_days: Optional[int]
    reason: str
    margin: Optional[int]
    ceiling: Optional[int]
    candidates: Optional[Callable]
    targets: tuple
    age_field: Optional[Mapping[str, str]] = None
    apply: Optional[Callable] = None


def _no_candidates_yet():
    """Stub until the rule's task fills it (Tasks 5, 6 and 9 of the Stage 3 plan). Selects nothing."""
    return []


_ROW_AND_FILE_RULES = (
    # ── Rows ─────────────────────────────────────────────────────────────────
    Rule(
        key='rate_runs', label_ar='تفاصيل تشغيلات حساب المعدلات', label_en='Rate run details',
        kind=KIND_ROW, floor_days=None, default_days=None,
        reason='آخر 3 تشغيلات مكتملة + آخر تشغيل من كل شهر لمدة 24 شهرًا + أي تشغيل ما زال مستخدمًا. '
               'رؤوس التشغيلات تبقى، وتوصيات التحويل المراجَعة لا تُحذف.',
        margin=150_000, ceiling=1_500_000, candidates=_no_candidates_yet,
        targets=('purchasing.ItemDemandMetrics', 'purchasing.ItemDemandAggregated',
                 'purchasing.TransferRecommendation'),
    ),
    Rule(
        key='transit_alert_notes', label_ar='ملاحظات تنبيهات التحويلات المتأخرة', label_en='Transit alert notes',
        kind=KIND_ROW, floor_days=None, default_days=90,
        reason='التنبيهات التلقائية فقط، بعد 90 يومًا من إغلاق التحويل. تنبيهات عدم التطابق مع ERP '
               'والملاحظات اليدوية تبقى دائمًا.',
        margin=2_000, ceiling=200_000, candidates=_no_candidates_yet,
        targets=('transits.InTransitNote',),
    ),
    Rule(
        key='transit_audit_events', label_ar='أحداث مزامنة وتنبيه التحويلات', label_en='Transit sync and alert events',
        kind=KIND_ROW, floor_days=None, default_days=90,
        reason='حدث alert_sent التلقائي وحدث synced فقط، بعد 90 يومًا من إغلاق التحويل. '
               'باقي أحداث المراجعة تبقى دائمًا.',
        margin=5_000, ceiling=300_000, candidates=_no_candidates_yet,
        targets=('transits.InTransitAuditEvent',),
    ),

    # ── Files: the row stays, the file goes ──────────────────────────────────
    Rule(
        key='prescriptions', label_ar='صور الروشتات', label_en='Prescription images',
        kind=KIND_FILE, floor_days=1095, default_days=1095,
        reason='قرار المالك: 3 سنوات كحد أدنى، وتتبقى المراجعة القانونية. يُحذف الملف ويبقى السجل.',
        margin=200, ceiling=5_000, candidates=_no_candidates_yet,
        targets=('pos_orders.SoftechSalesOrder.prescription_image', 'usage_print.UsageSheet.prescription_image',
                 'callcenter.CallLog.prescription_image', 'reservations.Reservation.image',
                 'reservations.ReservationImage.image'),
        age_field={'pos_orders.SoftechSalesOrder': 'created_at', 'usage_print.UsageSheet': 'created_at',
                   'callcenter.CallLog': 'called_at', 'reservations.Reservation': 'created_at',
                   'reservations.ReservationImage': 'uploaded_at'},
    ),
    Rule(
        key='ocr_pos_rx', label_ar='صور الروشتات في مخزن القراءة الآلية', label_en='Prescription scans in the OCR store',
        kind=KIND_FILE, floor_days=1095, default_days=1095,
        reason='قرار المالك: 3 سنوات كحد أدنى. وحدة pos_rx فقط؛ تُحذف الصورة وتبقى القراءات النصية للتعلم. '
               'باقي الوحدات تبقى دائمًا.',
        margin=200, ceiling=5_000, candidates=_no_candidates_yet,
        targets=('vision.OcrSample.image',),
        age_field={'vision.OcrSample': 'created_at'},
    ),
    Rule(
        key='conversations', label_ar='مرفقات محادثات العملاء', label_en='Customer conversation files',
        kind=KIND_FILE, floor_days=None, default_days=1095,
        reason='قد تحتوي على روشتات، فتأخذ مدة الروشتات. يُحذف الملف ويبقى السجل.',
        margin=200, ceiling=5_000, candidates=_no_candidates_yet,
        targets=('whatsapp.WAMediaFile.local_file', 'callcenter.CallLogAttachment.file',
                 'callcenter.CaseEvent.attachment'),
        age_field={'whatsapp.WAMediaFile': 'created_at', 'callcenter.CallLogAttachment': 'uploaded_at',
                   'callcenter.CaseEvent': 'created_at'},
    ),
    Rule(
        key='financial_docs', label_ar='المستندات المالية', label_en='Financial documents',
        kind=KIND_FILE, floor_days=1825, default_days=1825,
        reason='5 سنوات كحد أدنى، في انتظار تأكيد المحاسب. يُحذف الملف ويبقى السجل المالي كما هو.',
        margin=100, ceiling=2_000, candidates=_no_candidates_yet,
        targets=('invoices.SupplierInvoice.source_image', 'invoices.InvoiceBatch.source_file',
                 'payments.ExternalPayment.screenshot', 'payments.BankStatementImport.raw_file',
                 'hr.ExpenseClaim.receipt'),
        age_field={'invoices.SupplierInvoice': 'created_at', 'invoices.InvoiceBatch': 'created_at',
                   'payments.ExternalPayment': 'created_at', 'payments.BankStatementImport': 'imported_at',
                   'hr.ExpenseClaim': 'created_at'},
    ),
    Rule(
        key='bundle_pages', label_ar='صور صفحات حزم الفواتير', label_en='Invoice bundle page images',
        kind=KIND_FILE, floor_days=None, default_days=30,
        reason='المجلد invoice_bundles/pages/batch_<id>/ بعد 30 يومًا من آخر فاتورة في الحزمة صارت معتمدة أو '
               'مرفوضة، أو من فشل الحزمة. ملف PDF الأصلي يبقى.',
        margin=500, ceiling=5_000, candidates=_no_candidates_yet,
        targets=(),
    ),
    Rule(
        key='images_rejected', label_ar='صور الأصناف المرفوضة', label_en='Rejected item images',
        kind=KIND_FILE, floor_days=None, default_days=30,
        reason='يُحذف الملف ويبقى السجل حتى لا تُنزَّل الصورة مرة أخرى.',
        margin=100, ceiling=3_000, candidates=_no_candidates_yet,
        targets=('images.ImageCandidate.local_file',),
        age_field={'images.ImageCandidate': 'created_at'},
    ),
    Rule(
        key='images_unreviewed', label_ar='صور الأصناف غير المراجَعة', label_en='Unreviewed item images',
        kind=KIND_FILE, floor_days=None, default_days=180,
        reason='يُحذف الملف ويبقى السجل حتى لا تُنزَّل الصورة مرة أخرى.',
        margin=100, ceiling=3_000, candidates=_no_candidates_yet,
        targets=('images.ImageCandidate.local_file',),
        age_field={'images.ImageCandidate': 'created_at'},
    ),
    Rule(
        key='images_obsolete', label_ar='صور الأصناف المتوقفة', label_en='Images of obsolete items',
        kind=KIND_FILE, floor_days=None, default_days=90,
        reason='بعد 90 يومًا من أول مرة رأينا الصنف متوقفًا. يتوقف العد إذا عاد الصنف للاستخدام.',
        margin=100, ceiling=1_000, candidates=_no_candidates_yet,
        targets=('images.ImageCandidate.local_file', 'product_experience.ProductMedia.file',
                 'product_experience.ProductMedia.thumbnail'),
    ),
    Rule(
        key='delivery_proof', label_ar='صور إثبات التوصيل', label_en='Delivery proof',
        kind=KIND_FILE, floor_days=None, default_days=365,
        reason='يُحذف الملف ويبقى طلب التوصيل.',
        margin=200, ceiling=5_000, candidates=_no_candidates_yet,
        targets=('delivery.DeliveryOrder.pod_photo',),
        age_field={'delivery.DeliveryOrder': 'created_at'},
    ),
    Rule(
        key='staff_messages', label_ar='مرفقات رسائل الموظفين', label_en='Staff messages and attachments',
        kind=KIND_FILE, floor_days=None, default_days=365,
        reason='يُحذف الملف ويبقى السجل.',
        margin=500, ceiling=5_000, candidates=_no_candidates_yet,
        targets=('notifications.ChatterMessage.attachment', 'notifications.ChatterMessage.voice_note',
                 'reservations.ReservationActivity.attachment', 'reservations.ReservationActivity.voice_note',
                 'transfers.TransferRequestMessage.attachment', 'transfers.TransferRequestMessage.voice_note',
                 'tasks.TaskAttachment.file', 'supply.AvailabilityBatch.source_image',
                 'shortage.ShortageList.source_image'),
        age_field={'notifications.ChatterMessage': 'created_at', 'reservations.ReservationActivity': 'created_at',
                   'transfers.TransferRequestMessage': 'created_at', 'tasks.TaskAttachment': 'uploaded_at',
                   'supply.AvailabilityBatch': 'created_at', 'shortage.ShortageList': 'created_at'},
    ),
    Rule(
        key='unreferenced', label_ar='ملفات لا يستخدمها أي سجل', label_en='Files no record uses',
        kind=KIND_FILE, floor_days=None, default_days=30,
        reason='ملف تحت media/ بلا أي سجل يشير إليه، ظهر في فحصين بينهما 30 يومًا.',
        margin=100, ceiling=1_000, candidates=_no_candidates_yet,
        targets=(),
    ),
)


def _p56(key, label_ar, label_en, default_days, reason):
    return Rule(key=key, label_ar=label_ar, label_en=label_en, kind=KIND_P56, floor_days=None,
                default_days=default_days, reason=reason, margin=None, ceiling=None, candidates=None, targets=())


_P56_RULES = (
    _p56('p56_engine', 'تفاصيل تشغيلات المحرك', 'Engine run details', None,
         'آخر 10 تشغيلات + آخر تشغيل من كل شهر. قاعدة rate_runs تحل محلها عند تشغيلها.'),
    _p56('p56_notifications', 'الإشعارات', 'Notifications', NOTIF_UNREAD_DAYS,
         'المقروءة بعد 30 يومًا وغير المقروءة بعد 90 يومًا. الإعلانات لا تُحذف.'),
    _p56('p56_pbx', 'أحداث السنترال', 'PBX events', PBX_EVENT_DAYS, 'الأحداث الخام بعد 90 يومًا.'),
    _p56('p56_audit', 'سجل المراجعة: أحداث الدخول والمزامنة', 'Audit log noise', AUDIT_NOISE_DAYS,
         'أحداث الدخول والمزامنة فقط بعد سنة. باقي السجل لا يُحذف أبدًا.'),
    _p56('p56_slow', 'الطلبات البطيئة', 'Slow requests', SLOW_REQUEST_DAYS, 'بعد 30 يومًا.'),
    _p56('p56_screen_views', 'استخدام الشاشات', 'Screen views', 365, 'بعد 12 شهرًا.'),
)

RULES = {rule.key: rule for rule in (*_ROW_AND_FILE_RULES, *_P56_RULES)}

# Files kept with no rule, each with its reason. Every FileField is in a rule's targets or here.
KEEP_FOREVER = {
    'product_experience.ProductSEO.og_image': 'Live content: the sharing image of a product page.',
    'insurance.InsuranceExportProfile.watermark_image': 'Live configuration of insurance exports; a protected app.',
    'vision.OcrSample.audio': 'The design names only the image for pos_rx, so default is keep.',
}


def classified_file_fields():
    """Every 'app.Model.field' that has a decision."""
    out = set(KEEP_FOREVER)
    for rule in RULES.values():
        if rule.kind == KIND_FILE:
            out.update(rule.targets)
    return out


def unclassified_file_fields():
    """Local FileFields (ImageField included) with no rule and no keep-forever reason, as 'app.Model.field'."""
    classified = classified_file_fields()
    return sorted(
        f'{model._meta.label}.{field.name}'
        for model in apps.get_models()
        for field in model._meta.local_fields
        if isinstance(field, models.FileField) and f'{model._meta.label}.{field.name}' not in classified
    )
