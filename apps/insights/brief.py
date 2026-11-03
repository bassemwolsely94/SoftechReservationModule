"""
09:00 branch morning brief over WhatsApp.

``compose`` builds the text for one branch from the existing engines only (``KpiResolver`` for
yesterday, ``kpi_board.branch_mtd`` for the month, the stored ``InsightRun`` findings for the
worst three, live reservation / transfer rows for today's follow-ups): no number is computed
here. ``send_all`` sends the ``morning_brief`` template to each branch's brief recipients and its
shared alert mobile through the phone-alerts sender (dry-run rules and the
``MORNING_BRIEF_SEND_ENABLED`` switch live there); tapping «التفاصيل» returns the full text
(``inbound.handle_brief_tap``).
"""
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

logger = logging.getLogger('elrezeiky.phone_alerts')

MAX_FOLLOWUPS = 5
STUCK_AFTER_DAYS = 2
ACTIVE_RESERVATION = ('pending', 'available', 'contacted', 'confirmed')
STUCK_TRANSFER = ('pending', 'approved', 'needs_revision')

H_YESTERDAY = 'أمس'
H_MTD = 'الشهر حتى الآن'
H_DROPS = 'أهم 3 تراجعات'
H_FOLLOWUP = 'متابعة اليوم'


@dataclass
class BriefContent:
    headline_vars: list     # the 3 single-line template variables: branch, yesterday net sales, MTD %
    text: str               # the full brief, sent as free text when «التفاصيل» is tapped


def _n(value, places=0):
    return f'{Decimal(value):,.{places}f}'


def _pct(value):
    return '—' if value is None else f'{Decimal(value):.0f}%'


def _signed_pct(now, before):
    if not before:
        return '—'
    delta = (Decimal(now) - Decimal(before)) / Decimal(before) * 100
    return f'{delta:+.0f}%'


def _yesterday_section(branch, yesterday):
    from apps.forecasting.kpi import KpiResolver
    from apps.forecasting.kpi_board import SALES_METRIC
    from apps.forecasting.models import KpiActualRollup as K
    r = KpiResolver()
    kw = dict(branch_ids=[branch.pk])
    sales = r.resolve(SALES_METRIC, start=yesterday, end=yesterday, **kw)
    orders = r.resolve(K.M_ORDERS, start=yesterday, end=yesterday, **kw)
    week = yesterday - timedelta(days=7)
    sales_before = r.resolve(SALES_METRIC, start=week, end=week, **kw)
    basket = (sales / orders) if orders else None
    lines = [f'*{H_YESTERDAY}*',
             f'• صافي المبيعات: {_n(sales)} ج.م',
             f'• عدد الفواتير: {_n(orders)}',
             f'• متوسط الفاتورة: {_n(basket) + " ج.م" if basket is not None else "—"}',
             f'• عن نفس اليوم الأسبوع الماضي: {_signed_pct(sales, sales_before)}']
    return lines, sales


def _mtd_section(branch, yesterday):
    from apps.forecasting import kpi_board
    mtd = kpi_board.branch_mtd([branch.pk], yesterday.year, yesterday.month)[branch.pk]
    lines = [f'*{H_MTD}*', f'• المحقق: {_n(mtd["actual"])} ج.م']
    if mtd['target'] is not None:
        lines.append(f'• المستهدف: {_n(mtd["target"])} ج.م — النسبة {_pct(mtd["pct"])}')
        if mtd['daily_needed'] is not None:
            lines.append(f'• المطلوب يومياً للوصول للهدف: {_n(mtd["daily_needed"])} ج.م')
    else:
        lines.append('• لا يوجد مستهدف لهذا الشهر')
    return lines, mtd


def _drops_section(branch, yesterday):
    from apps.insights.engine import InsightEngine
    from apps.insights.models import InsightRun
    run = (InsightRun.objects.filter(domain='sales', period_type='day', period_end=yesterday)
           .order_by('-created_at').first())
    msgs = InsightEngine.top_negative_for_branch(run, branch, 'ar', 3) if run else []
    if not msgs:
        return []
    return [f'*{H_DROPS}*'] + [f'• {m}' for m in msgs]


def _capped(qs, line_of):
    """First MAX_FOLLOWUPS rows of ``qs`` as lines, plus «+N أخرى» for the rest (one COUNT, one slice)."""
    total = qs.count()
    lines = [line_of(r) for r in qs[:MAX_FOLLOWUPS]]
    if total > MAX_FOLLOWUPS:
        lines.append(f'  +{total - MAX_FOLLOWUPS} أخرى')
    return lines


def _transfer_line(t):
    items = sorted(t.items.all(), key=lambda i: i.pk)           # prefetched: no per-transfer query
    return f'• {t.request_number or "#" + str(t.pk)} — {items[0].item.name if items else "—"}'


def _followups_section(branch, day):
    from django.db.models import Q
    from apps.reservations.models import Reservation
    from apps.transfers.models import TransferRequest
    cutoff = day - timedelta(days=STUCK_AFTER_DAYS)
    res = (Reservation.objects.filter(branch=branch, status__in=ACTIVE_RESERVATION)
           .filter(Q(follow_up_date__lt=day) | Q(expected_arrival_date__lt=day)
                   | Q(status__in=('pending', 'available'), updated_at__date__lt=cutoff))
           .select_related('item').order_by('pk'))
    trs = (TransferRequest.objects.filter(status__in=STUCK_TRANSFER, updated_at__date__lt=cutoff)
           .filter(Q(requesting_branch=branch) | Q(supplying_branch=branch))
           .prefetch_related('items__item').order_by('pk'))
    lines = _capped(res, lambda r: f'• #{r.pk} — {r.item_label}')
    lines += _capped(trs, _transfer_line)
    if not lines:
        return []
    return [f'*{H_FOLLOWUP}*'] + lines


def compose(branch, day):
    """The brief for ``branch`` on ``day`` (reports on the day before)."""
    yesterday = day - timedelta(days=1)
    name = branch.name_ar or branch.name
    y_lines, sales = _yesterday_section(branch, yesterday)
    m_lines, mtd = _mtd_section(branch, yesterday)
    sections = [y_lines, m_lines, _drops_section(branch, yesterday), _followups_section(branch, day)]
    text = '\n\n'.join('\n'.join(s) for s in [[f'☀️ صباح الخير — {name}']] + [s for s in sections if s])
    return BriefContent(
        headline_vars=[' '.join(name.split()), f'{_n(sales)} ج.م', _pct(mtd['pct'])],
        text=text)


def _phones(branch):
    """Distinct plausible international phones: the branch's brief recipients, then its shared mobile."""
    from apps.branches.models import BranchSettings
    from apps.insights.models import InsightRecipient
    from apps.notifications.phone_alerts.recipients import is_plausible_phone
    from core.sms import sms_number
    raw = list(InsightRecipient.objects.filter(branch=branch, morning_brief=True, active=True)
               .order_by('pk').values_list('wa_number', flat=True))
    row = BranchSettings.objects.filter(branch=branch).first()
    if row and (row.alert_mobile or '').strip():
        raw.append(row.alert_mobile)
    seen, out = set(), []
    for number in raw:
        phone = sms_number(number)
        if is_plausible_phone(phone) and phone not in seen:
            seen.add(phone)
            out.append(phone)
    return out


def send_all(day=None) -> int:
    """Send today's brief to every branch that has recipients. Returns the number of alerts sent.

    A phone that already got this branch's brief on that Cairo calendar day is skipped (safe to re-run);
    one branch failing never stops the others."""
    from apps.branches.models import Branch
    from apps.insights.models import InsightRecipient
    from apps.notifications.phone_alerts import sender
    from apps.notifications.phone_alerts.models import PhoneAlert
    day = day or timezone.localdate()
    start = timezone.make_aware(datetime.combine(day, time.min))        # the brief's Cairo calendar day
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))
    ct =ContentType.objects.get_for_model(Branch)
    branch_ids = set(InsightRecipient.objects.filter(morning_brief=True, active=True, branch__isnull=False)
                     .values_list('branch_id', flat=True))
    count = 0
    for branch in Branch.objects.filter(pk__in=branch_ids).order_by('pk'):
        try:
            recent = set(PhoneAlert.objects.filter(
                kind='brief', source_ct=ct, source_id=branch.pk,
                created_at__gte=start, created_at__lt=end).values_list('phone', flat=True))
            phones = [p for p in _phones(branch) if p not in recent]
            if not phones:
                continue
            content = compose(branch, day)
            variables = [{'type': 'text', 'text': sender._one_line(v) or '—'} for v in content.headline_vars]
            for phone in phones:
                alert = PhoneAlert.objects.create(event='morning_brief', kind='brief', phone=phone,
                                                  source_ct=ct, source_id=branch.pk)
                sender.deliver(alert, template='morning_brief', variables=variables,
                               payloads=[f'brief:{alert.token}'])
                count += 1
        except Exception:
            logger.exception('morning brief: branch %s failed', branch.pk)
    return count
