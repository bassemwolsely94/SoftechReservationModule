"""
apps/data_lifecycle/problems.py

The data problems table of /data-health (design §6 Stage 5). Every count reads local mirrors only, never SOFTECH,
and returns a number: customer data is counts only, so no name or phone leaves this module. Company-level
by nature (no branch scoping); admin, supervisor and quality manager may see it.
"""
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Optional

from django.db.models import Count, Exists, OuterRef
from django.utils import timezone

logger = logging.getLogger('elrezeiky.sync')

STALE_DAYS = 90
PHONE_FORMAT = r'^01[0125][0-9]{8}$'


@dataclass(frozen=True)
class Problem:
    key: str
    label_ar: str
    label_en: str
    owner_role_ar: str
    link: Optional[str]
    note_ar: str
    count: Callable[[], int]


def _cutoff():
    return timezone.now() - timedelta(days=STALE_DAYS)


def _shared_phone():
    from apps.customers.models import Customer
    shared = (Customer.objects.exclude(phone='').values('phone')
              .annotate(n=Count('pk')).filter(n__gt=1).values('phone'))
    return Customer.objects.exclude(phone='').filter(phone__in=shared).count()


def _bad_phone():
    from apps.customers.models import Customer
    return Customer.objects.exclude(phone='').exclude(phone__regex=PHONE_FORMAT).count()


def _no_sales():
    from apps.customers.models import Customer, PurchaseHistory
    return Customer.objects.filter(~Exists(PurchaseHistory.objects.filter(customer=OuterRef('pk')))).count()


def _ingredients_pending():
    from apps.composition.models import IngredientParseCandidate as Candidate
    return Candidate.objects.filter(status__in=[Candidate.STATUS_PENDING, Candidate.STATUS_NEEDS_REVIEW]).count()


def _undefined_scientific():
    from apps.catalog.models import Item
    return Item.objects.filter(name_scientific__iregex=r'^(undefined|undefined item)$').count()


def _followups_missed():
    from apps.followups.models import FollowUpTask
    return FollowUpTask.objects.filter(status='missed', due_date__lt=_cutoff().date()).count()


def _deliveries_stuck():
    from apps.delivery.models import DeliveryOrder
    return (DeliveryOrder.objects.exclude(status__in=DeliveryOrder.TERMINAL_STATUSES)
            .filter(created_at__lt=_cutoff()).count())


def _supply_open():
    from apps.supply.models import SupplyCase
    return SupplyCase.objects.filter(status__in=SupplyCase.OPEN_STATUSES, first_detected_at__lt=_cutoff()).count()


def _stockcount_open():
    # Daily sessions are kept on purpose: an unclosed one is the same kind of leftover.
    from apps.stockcount.models import StockCountSession
    return StockCountSession.objects.exclude(status='closed').filter(created_at__lt=_cutoff()).count()


def _pos_ready():
    from apps.pos_orders.models import SoftechSalesOrder
    return SoftechSalesOrder.objects.filter(status=SoftechSalesOrder.STATUS_READY, created_at__lt=_cutoff()).count()


PROBLEMS = (
    Problem('customers_shared_phone', 'عملاء يشتركون في رقم هاتف', 'Customers sharing a phone number',
            'خدمة العملاء', '/customers/merge', '', _shared_phone),
    Problem('phones_bad_format', 'أرقام هاتف بصيغة غير صحيحة', 'Phone numbers in a wrong format',
            'خدمة العملاء', None, 'بعضها أرقام أرضية', _bad_phone),
    Problem('customers_no_sales', 'عملاء بلا أي مبيعات', 'Customers with no sales',
            'الإدارة', None, 'ليس دليلاً على أنه سجل مهمل', _no_sales),
    Problem('ingredients_pending', 'مكونات بانتظار المراجعة', 'Ingredients waiting for review',
            'الجودة', '/composition', '', _ingredients_pending),
    Problem('items_undefined_scientific', 'أصناف اسمها العلمي undefined', 'Items with an undefined scientific name',
            'الجودة', '/composition', '', _undefined_scientific),
    Problem('followups_missed_90d', 'متابعات فائتة منذ أكثر من 90 يوماً', 'Follow-ups missed over 90 days ago',
            'المتابعات', '/followups', '', _followups_missed),
    Problem('deliveries_stuck_90d', 'طلبات توصيل عالقة أكثر من 90 يوماً', 'Deliveries stuck over 90 days',
            'التوصيل', '/delivery', '', _deliveries_stuck),
    Problem('supply_open_90d', 'حالات توريد مفتوحة أكثر من 90 يوماً', 'Supply cases open over 90 days',
            'المشتريات', '/supply', '', _supply_open),
    Problem('stockcount_open_90d', 'جلسات جرد مفتوحة أكثر من 90 يوماً', 'Stock counts open over 90 days',
            'المخزون', '/stock-count', '', _stockcount_open),
    Problem('pos_ready_90d', 'طلبات نقاط البيع جاهزة منذ أكثر من 90 يوماً', 'POS orders ready for over 90 days',
            'نقاط البيع', '/pos', 'لا تُغلق تلقائياً', _pos_ready),
)


def count_all():
    """{key: int | None}. Each count in its own try: a failure logs the key and the exception class only
    (never the message, which could carry a value) and gives None, so one bad table never blocks the rest."""
    out = {}
    for problem in PROBLEMS:
        try:
            out[problem.key] = int(problem.count())
        except Exception as exc:
            logger.error('[data-health] problem count %s failed: %s', problem.key, type(exc).__name__)
            out[problem.key] = None
    return out
