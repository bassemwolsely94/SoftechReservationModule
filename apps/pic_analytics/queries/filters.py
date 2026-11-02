"""
apps/pic_analytics/queries/filters.py — the filter bar shared by every PIC Analytics query (doc 33 §6).

`Filters.facts(access)` is the ONE place a query gets its PicDayFact rows: date range, branch scope
(a branch manager never widens), fact-level filters (salesperson / channel / category) and the
PIC-level filters (segment / customer type / frequency class). Amounts always come from here, so a
branch manager's figures can only ever be their own branches'.
"""
from dataclasses import dataclass, field
from datetime import date, datetime

from django.db.models import DecimalField, F, Func, TextField, Value
from django.db.models.functions import Cast
from django.utils import timezone

from apps.customers.models import Customer
from apps.pic_analytics.models import PicDayFact
from apps.pic_analytics.queries.frequency import pics_in_bucket

HISTORY_START = date(2024, 8, 1)


class FilterError(ValueError):
    """A bad filter bar value — the message is Arabic and safe to show."""


def _date(params, key, label):
    raw = (params.get(key) or '').strip()
    if not raw:
        raise FilterError(f'التاريخ «{label}» مطلوب')
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        raise FilterError(f'التاريخ «{label}» غير صالح — الصيغة YYYY-MM-DD')


@dataclass
class Filters:
    start: date
    end: date
    branch_ids: set | None = None
    salesperson: str = ''
    agent_ext: str = ''          # stored only — used by the call queries (Task 9)
    channel_bucket: str = ''
    category: str = ''
    segment: str = ''
    customer_type: str = ''
    frequency: str = ''
    data_from: date = HISTORY_START
    data_to: date = field(default_factory=timezone.localdate)
    clamped: bool = False

    @classmethod
    def from_request(cls, request, access):
        params = request.query_params if hasattr(request, 'query_params') else request.GET
        start = _date(params, 'from', 'من')
        end = _date(params, 'to', 'إلى')
        if start > end:
            raise FilterError('تاريخ البداية بعد تاريخ النهاية')
        data_from, data_to = HISTORY_START, timezone.localdate()
        clamped = start < data_from or end > data_to
        start, end = max(start, data_from), min(end, data_to)
        if start > end:
            raise FilterError('الفترة خارج نطاق البيانات المتاحة')
        branch_ids = None
        raw = (params.get('branch') or '').strip()
        if raw:
            try:
                branch_ids = {int(x) for x in raw.split(',') if x.strip()}
            except ValueError:
                raise FilterError('رقم الفرع غير صالح')
        g = lambda k: (params.get(k) or '').strip()      # noqa: E731
        return cls(start=start, end=end, branch_ids=branch_ids, salesperson=g('salesperson'),
                   agent_ext=g('agent'), channel_bucket=g('channel'), category=g('category'),
                   segment=g('segment'), customer_type=g('customer_type'), frequency=g('frequency'),
                   data_from=data_from, data_to=data_to, clamped=clamped)

    # ── the fact rows every query reads ──────────────────────────────────────────────────────
    @property
    def has_pic_filters(self):
        return bool(self.segment or self.customer_type or self.frequency)

    def net_expr(self):
        """Net of a fact row: the whole net, or — with a category filter — that category's net."""
        if self.category:
            # jsonb_extract_path_text, not KeyTextTransform: Django reads a numeric key ('50') as an array index
            text = Func(F('net_by_category'), Value(self.category), function='jsonb_extract_path_text',
                        output_field=TextField())
            return Cast(text, DecimalField(max_digits=14, decimal_places=2))
        return F('net')

    def facts(self, access, *, start=None, end=None, pic_filters=True):
        """PicDayFact rows in range, annotated `enet` (the net to sum). Scoped to the branches the
        user may see; `pic_filters=False` skips segment/type/frequency (used for the no-PIC line)."""
        qs = PicDayFact.objects.filter(day__gte=start or self.start, day__lte=end or self.end)
        ids = access.allowed_branch_ids(self.branch_ids)
        if ids is not None:
            qs = qs.filter(branch__in=ids)
        if self.salesperson:
            qs = qs.filter(salesperson=self.salesperson)
        if self.channel_bucket:
            qs = qs.filter(channel_bucket=self.channel_bucket)
        if pic_filters:
            cust = Customer.objects.all()
            if self.segment:
                cust = cust.filter(segment=self.segment)
            if self.customer_type:
                cust = cust.filter(softech_ptclassifcode=self.customer_type)
            if self.segment or self.customer_type:
                qs = qs.filter(pic__in=cust.values('softech_pic'))
            if self.frequency:
                qs = qs.filter(pic__in=pics_in_bucket(self.frequency, self.end))
        qs = qs.annotate(enet=self.net_expr())
        # a category filter counts a fact only where that category's net is positive
        return qs.filter(enet__gt=0) if self.category else qs
