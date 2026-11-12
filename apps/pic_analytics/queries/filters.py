"""
apps/pic_analytics/queries/filters.py — the filter bar shared by every PIC Analytics query (doc 33 §6).

`Filters.facts(access)` is the ONE place a query gets its PicDayFact rows: date range, branch scope
(a branch manager never widens), fact-level filters (salesperson / channel / category) and the
PIC-level filters (segment / customer type / frequency class). Amounts always come from here, so a
branch manager's figures can only ever be their own branches'.
"""
from dataclasses import dataclass, field
from datetime import date, datetime

from django.db.models import DecimalField, ExpressionWrapper, F, Func, Max, TextField, Value
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from apps.customers.models import Customer
from apps.pic_analytics.exclusions import excluded_pics
from apps.pic_analytics.models import PicDayFact
from apps.pic_analytics.queries.frequency import pics_in_bucket, pics_in_buckets
from core.multi_filter import filter_in, multi_values

HISTORY_START = date(2024, 8, 1)
MAX_SEARCH_LEN = 100


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


def _as_tuple(v) -> tuple:
    """A multi-select filter value as a tuple of codes: '' / None -> (), 'a' -> ('a',),
    'a,b' -> ('a', 'b'), a list/tuple/set -> its non-empty items (order kept, duplicates dropped)."""
    if v is None:
        return ()
    parts = str(v).split(',') if isinstance(v, str) else [str(x) for x in v]
    out = []
    for p in parts:
        p = p.strip()
        if p and p not in out:
            out.append(p)
    return tuple(out)


# the filter-bar fields that take several values (multi-select; none = no filter)
MULTI_FIELDS = ('salesperson', 'agent_ext', 'channel_bucket', 'category', 'segment', 'customer_type', 'frequency')


@dataclass
class Filters:
    """The multi-select fields hold a tuple of codes (() = all). A plain string is accepted too
    ('u1' or 'u1,u2') and normalised, so callers and tests that pass one value keep working."""
    start: date
    end: date
    branch_ids: set | None = None
    salesperson: tuple = ()
    agent_ext: tuple = ()        # stored only — used by the call queries (Task 9)
    channel_bucket: tuple = ()
    category: tuple = ()
    segment: tuple = ()
    customer_type: tuple = ()
    frequency: tuple = ()
    q: str = ''                  # PIC list search (name / PIC code / phone); read by pics.pic_rows only
    data_from: date = HISTORY_START
    data_to: date = field(default_factory=timezone.localdate)
    clamped: bool = False
    # per-request memo for results several tabs share (the export asks for them 5+ times); never compared/shown
    memo: dict = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self):
        for name in MULTI_FIELDS:
            setattr(self, name, _as_tuple(getattr(self, name)))

    @classmethod
    def from_request(cls, request, access, live=False):
        """live=True for the call tabs: calls are mirrored every 10 min, so they run to today instead
        of stopping at the latest nightly-built fact day (sales facts are built through yesterday)."""
        params = request.query_params if hasattr(request, 'query_params') else request.GET
        start = _date(params, 'from', 'من')
        end = _date(params, 'to', 'إلى')
        if start > end:
            raise FilterError('تاريخ البداية بعد تاريخ النهاية')
        # facts exist only through the latest built day: never promise more than that
        latest = timezone.localdate() if live else (PicDayFact.objects.aggregate(m=Max('day'))['m']
                                                    or timezone.localdate())
        data_from, data_to = HISTORY_START, min(end, latest, timezone.localdate())
        clamped = start < data_from or end > data_to
        start, end = max(start, data_from), data_to
        if start > end:
            raise FilterError('الفترة خارج نطاق البيانات المتاحة')
        # branch: ?branch=3,7 or ?branch=3&branch=7. A requested set only narrows (Access.allowed_branch_ids
        # intersects it with the user's branches); a non-number is refused as before, never ignored.
        branch_ids = None
        raw_branches = multi_values(params, 'branch')
        if raw_branches:
            try:
                branch_ids = {int(x) for x in raw_branches}
            except ValueError:
                raise FilterError('رقم الفرع غير صالح')
        g = lambda k: (params.get(k) or '').strip()      # noqa: E731

        def m(k):   # multi-select: ?k=a,b or ?k=a&k=b
            return tuple(multi_values(params, k))
        if len(g('q')) > MAX_SEARCH_LEN:
            raise FilterError('نص البحث طويل جدًا')
        return cls(start=start, end=end, branch_ids=branch_ids, salesperson=m('salesperson'),
                   agent_ext=m('agent'), channel_bucket=m('channel'), category=m('category'),
                   segment=m('segment'), customer_type=m('customer_type'), frequency=m('frequency'), q=g('q'),
                   data_from=data_from, data_to=data_to, clamped=clamped)

    # ── the fact rows every query reads ──────────────────────────────────────────────────────
    @property
    def has_pic_filters(self):
        return bool(self.segment or self.customer_type or self.frequency)

    def net_expr(self):
        """Net of a fact row: the whole net, or — with a category filter — the net of the ticked
        categories (one category: exactly as before; several: their sum, a missing key counting 0)."""
        def cat_net(code):
            # jsonb_extract_path_text, not KeyTextTransform: Django reads a numeric key ('50') as an array index
            text = Func(F('net_by_category'), Value(code), function='jsonb_extract_path_text',
                        output_field=TextField())
            return Cast(text, DecimalField(max_digits=14, decimal_places=2))
        if len(self.category) == 1:
            return cat_net(self.category[0])
        if self.category:
            zero = Value(0, output_field=DecimalField(max_digits=14, decimal_places=2))
            total = Coalesce(cat_net(self.category[0]), zero)
            for code in self.category[1:]:
                total = total + Coalesce(cat_net(code), zero)
            return ExpressionWrapper(total, output_field=DecimalField(max_digits=14, decimal_places=2))
        return F('net')

    def excluded(self) -> frozenset:
        """The active excluded PICs (exclusions.py), read once per request."""
        return excluded_pics(self.memo)

    def facts(self, access, *, start=None, end=None, pic_filters=True, only_excluded=False):
        """PicDayFact rows in range, annotated `enet` (the net to sum). Scoped to the branches the
        user may see; `pic_filters=False` skips segment/type/frequency (used for the no-PIC line).
        Excluded PICs (doc 33 §15) are left out of every result; `only_excluded=True` returns just
        their rows — the one «عملاء مستبعدون» line."""
        qs = PicDayFact.objects.filter(day__gte=start or self.start, day__lte=end or self.end)
        ex = self.excluded()
        if only_excluded:
            qs = qs.filter(pic__in=ex)
        elif ex:
            qs = qs.exclude(pic__in=ex)
        ids = access.allowed_branch_ids(self.branch_ids)
        if ids is not None:
            qs = qs.filter(branch__in=ids)
        # multi-select filters: several values = their union, one = as before, none = no filter
        qs = filter_in(qs, 'salesperson', list(self.salesperson))
        qs = filter_in(qs, 'channel_bucket', list(self.channel_bucket))
        if pic_filters:
            cust = Customer.objects.all()
            cust = filter_in(cust, 'segment', list(self.segment))
            cust = filter_in(cust, 'softech_ptclassifcode', list(self.customer_type))
            if self.segment or self.customer_type:
                qs = qs.filter(pic__in=cust.values('softech_pic'))
            if len(self.frequency) == 1:
                qs = qs.filter(pic__in=pics_in_bucket(self.frequency[0], self.end))
            elif self.frequency:
                qs = qs.filter(pic__in=pics_in_buckets(self.frequency, self.end))
        qs = qs.annotate(enet=self.net_expr())
        # a category filter counts a fact only where the ticked categories' net is positive
        return qs.filter(enet__gt=0) if self.category else qs
