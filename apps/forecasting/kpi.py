"""
KpiResolver  (doc 16, Phase 1–2)
================================
Computes branch KPI actuals from customers.PurchaseHistory(+Line), driven entirely
by ChannelBucketMap + BeautyClassRule (nothing hard-coded).

All money metrics are NET of returns (doc_code '30' subtracted from '115').

Validated 2026-07-29 against تحقيق مايو 2026 — cash/delivery/regular/credit reproduce
exactly; customers ±≤8; gross-profit within ~1–5% (residual discount factor, TBD).

Works over ANY date range and ANY branch set (Phase 2 attainment / chain scope):
  • branch_ids = None  → all branches (chain)
  • branch_ids = [id]  → single branch
  • softech_user       → optional salesperson filter

Metric keys are the KpiActualRollup.M_* constants.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum, F, DecimalField, ExpressionWrapper

_PROFIT_EXPR = ExpressionWrapper(
    F('line_total') - F('quantity') * F('cost_at_sale'),
    output_field=DecimalField(max_digits=18, decimal_places=4),
)


def analytics_excluded_branch_codes():
    """Branch codes that are NOT retail sales branches — excluded from sales analytics.
    HQ (100) is the administrative branch + distributing warehouse; its 'sales' are internal,
    not retail. Owner-editable via SystemSetting 'analytics_excluded_branches' (comma-sep)."""
    from apps.config.models import SystemSetting
    raw = SystemSetting.get('analytics_excluded_branches', '100')
    return {c.strip() for c in str(raw or '100').split(',') if c.strip()}


def analytics_branches():
    """Operational RETAIL branches for analytics/targets/board (excludes HQ/admin)."""
    from apps.branches.models import Branch
    excl = analytics_excluded_branch_codes()
    return (Branch.objects.filter(is_operational=True)
            .exclude(code__in=excl).exclude(softech_branch_id__in=excl))


class KpiResolver:
    """Resolve KPI actuals for a branch set × date range."""

    def __init__(self):
        self._load_config()

    # ── config ───────────────────────────────────────────────────────────────
    def _load_config(self):
        from apps.forecasting.models import ChannelBucketMap, BeautyClassRule
        rows = list(ChannelBucketMap.objects.filter(active=True))
        self.channels_by_bucket = {}          # bucket -> [channel codes]
        self.cash_sub = {'': [], 'delivery': [], 'regular': []}
        self.customer_channels = []
        self.profit_channels = []
        self.nonexclude_channels = []
        for r in rows:
            self.channels_by_bucket.setdefault(r.bucket, []).append(r.channel)
            if r.bucket == ChannelBucketMap.BUCKET_CASH:
                self.cash_sub.setdefault(r.subtype or '', []).append(r.channel)
            if r.bucket != ChannelBucketMap.BUCKET_EXCLUDE:
                self.nonexclude_channels.append(r.channel)
            if r.counts_customer:
                self.customer_channels.append(r.channel)
            if r.include_in_profit:
                self.profit_channels.append(r.channel)
        self.beauty_types = list(
            BeautyClassRule.objects.filter(active=True).values_list('medicine_type', flat=True)
        )
        from apps.forecasting.models import UnitCountExclusion
        self.unit_excluded_items = set(
            UnitCountExclusion.objects.filter(active=True).values_list('item_id', flat=True)
        )

    @staticmethod
    def month_bounds(year: int, month: int):
        last = monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last)

    @staticmethod
    def _as_list(branch_ids):
        if branch_ids is None:
            return None
        return list(branch_ids) if isinstance(branch_ids, (list, tuple, set)) else [branch_ids]

    # ── low-level nets ───────────────────────────────────────────────────────
    @staticmethod
    def _user_filter(qs, field, softech_user):
        """softech_user may be a single code (exact) or a list/set (IN)."""
        if not softech_user:
            return qs
        if isinstance(softech_user, (list, tuple, set)):
            return qs.filter(**{f'{field}__in': list(softech_user)})
        return qs.filter(**{field: softech_user})

    def _ph_qs(self, branch_ids, start, end, softech_user=None, category_id=None):
        from apps.customers.models import PurchaseHistory
        qs = PurchaseHistory.objects.filter(
            invoice_date__date__gte=start, invoice_date__date__lte=end,
        )
        bl = self._as_list(branch_ids)
        if bl is not None:
            qs = qs.filter(branch_id__in=bl)
        qs = self._user_filter(qs, 'softech_user', softech_user)
        if category_id:
            # header-level: keep invoices that contain ≥1 line of the category
            qs = qs.filter(lines__item__category_id=category_id).distinct()
        return qs

    def _line_qs(self, branch_ids, start, end, softech_user=None, category_id=None):
        from apps.customers.models import PurchaseHistoryLine
        qs = PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=start, purchase__invoice_date__date__lte=end,
        )
        bl = self._as_list(branch_ids)
        if bl is not None:
            qs = qs.filter(purchase__branch_id__in=bl)
        qs = self._user_filter(qs, 'purchase__softech_user', softech_user)
        if category_id:
            qs = qs.filter(item__category_id=category_id)
        return qs

    def _net_amount(self, branch_ids, start, end, channels, softech_user=None):
        if not channels:
            return Decimal('0')
        base = self._ph_qs(branch_ids, start, end, softech_user).filter(sales_channel__in=channels)
        sale = base.filter(doc_code='115').aggregate(s=Sum('total_amount'))['s'] or 0
        ret  = base.filter(doc_code='30').aggregate(s=Sum('total_amount'))['s'] or 0
        return Decimal(str(sale)) - Decimal(str(ret))

    def _net_profit(self, branch_ids, start, end, channels, softech_user=None):
        if not channels:
            return Decimal('0')
        base = self._line_qs(branch_ids, start, end, softech_user).filter(purchase__sales_channel__in=channels)
        sale = base.filter(purchase__doc_code='115').aggregate(s=Sum(_PROFIT_EXPR))['s'] or 0
        ret  = base.filter(purchase__doc_code='30').aggregate(s=Sum(_PROFIT_EXPR))['s'] or 0
        return Decimal(str(sale)) - Decimal(str(ret))

    def _net_beauty(self, branch_ids, start, end, softech_user=None):
        if not self.beauty_types or not self.nonexclude_channels:
            return Decimal('0')
        base = self._line_qs(branch_ids, start, end, softech_user).filter(
            purchase__sales_channel__in=self.nonexclude_channels,
            item__medicine_type__in=self.beauty_types,
        )
        sale = base.filter(purchase__doc_code='115').aggregate(s=Sum('line_total'))['s'] or 0
        ret  = base.filter(purchase__doc_code='30').aggregate(s=Sum('line_total'))['s'] or 0
        return Decimal(str(sale)) - Decimal(str(ret))

    def _distinct_customers(self, branch_ids, start, end, softech_user=None):
        if not self.customer_channels:
            return Decimal('0')
        n = (self._ph_qs(branch_ids, start, end, softech_user)
             .filter(doc_code='115', sales_channel__in=self.customer_channels)
             .exclude(softech_phcode='')
             .values('softech_phcode').distinct().count())
        return Decimal(n)

    def _order_count(self, branch_ids, start, end, softech_user=None):
        if not self.nonexclude_channels:
            return Decimal('0')
        n = (self._ph_qs(branch_ids, start, end, softech_user)
             .filter(doc_code='115', sales_channel__in=self.nonexclude_channels)
             .count())
        return Decimal(n)

    # ── public: single metric over a range ─────────────────────────────────────
    def resolve(self, metric, *, branch_ids=None, start, end, softech_user=None,
                category_id=None) -> Decimal:
        """Compute one metric key over a branch set + date range.
        category_id → line-based (a category's own sales), else header-based
        (branch/salesperson use the whole invoice total)."""
        from apps.forecasting.models import ChannelBucketMap as C, KpiActualRollup as K
        # Derivable Phase-2 metrics (mirror-only; all scopes).
        if metric in (K.M_UNITS_SOLD, K.M_GROSS_MARGIN_PCT, K.M_REVENUE_PER_CUST,
                      K.M_CROSS_CATEGORY_RATE, K.M_NEW_CUSTOMERS):
            return self._derived_metric(metric, branch_ids, start, end, softech_user, category_id)
        # Discounting family (line-based; works for all scopes incl. category).
        if metric in K.DISCOUNT_METRICS:
            return self._discount_metric(metric, branch_ids, start, end, softech_user, category_id)
        # Extended volume/mix metrics (header scopes only for now).
        if metric in K.EXTENDED_HEADER_METRICS:
            if category_id:
                return Decimal('0')   # category variants TBD
            return self._extended_metric(metric, branch_ids, start, end, softech_user)
        if category_id:
            return self._resolve_category(metric, branch_ids, start, end, category_id, softech_user)
        cash_all  = self.channels_by_bucket.get(C.BUCKET_CASH, [])
        credit    = self.channels_by_bucket.get(C.BUCKET_CREDIT, [])
        insurance = self.channels_by_bucket.get(C.BUCKET_INSURANCE, [])
        amt = lambda ch: self._net_amount(branch_ids, start, end, ch, softech_user)
        table = {
            K.M_CASH_DELIVERY: lambda: amt(cash_all),
            K.M_CASH:          lambda: amt(self.cash_sub.get('', [])),
            K.M_DELIVERY:      lambda: amt(self.cash_sub.get('delivery', [])),
            K.M_REGULAR:       lambda: amt(self.cash_sub.get('regular', [])),
            K.M_CREDIT:        lambda: amt(credit),
            K.M_INSURANCE:     lambda: amt(insurance),
            K.M_NET_REVENUE:   lambda: amt(self.nonexclude_channels),
            K.M_GROSS_PROFIT:  lambda: self._net_profit(branch_ids, start, end, self.profit_channels, softech_user),
            K.M_CUSTOMERS:     lambda: self._distinct_customers(branch_ids, start, end, softech_user),
            K.M_ORDERS:        lambda: self._order_count(branch_ids, start, end, softech_user),
            K.M_BEAUTY:        lambda: self._net_beauty(branch_ids, start, end, softech_user),
        }
        fn = table.get(metric)
        return fn() if fn else Decimal('0')

    # ── derivable Phase-2 metrics (mirror-only) ─────────────────────────────────
    def _derived_metric(self, metric, branch_ids, start, end, softech_user, category_id) -> Decimal:
        from django.db.models import Sum, Count
        from apps.forecasting.models import KpiActualRollup as K
        if not self.nonexclude_channels:
            return Decimal('0')

        if metric == K.M_UNITS_SOLD:
            lines = self._line_qs(branch_ids, start, end, softech_user, category_id).filter(
                purchase__doc_code='115', purchase__sales_channel__in=self.nonexclude_channels)
            if self.unit_excluded_items:
                lines = lines.exclude(item_id__in=self.unit_excluded_items)   # syringes, delivery fees…
            sale = lines.aggregate(s=Sum('quantity'))['s'] or 0
            ret_lines = self._line_qs(branch_ids, start, end, softech_user, category_id).filter(
                purchase__doc_code='30', purchase__sales_channel__in=self.nonexclude_channels)
            if self.unit_excluded_items:
                ret_lines = ret_lines.exclude(item_id__in=self.unit_excluded_items)
            ret = ret_lines.aggregate(s=Sum('quantity'))['s'] or 0
            return Decimal(str(sale)) - Decimal(str(ret))

        if metric == K.M_GROSS_MARGIN_PCT:
            rev = self.resolve(K.M_NET_REVENUE, branch_ids=branch_ids, start=start, end=end,
                               softech_user=softech_user, category_id=category_id)
            prof = self.resolve(K.M_GROSS_PROFIT, branch_ids=branch_ids, start=start, end=end,
                                softech_user=softech_user, category_id=category_id)
            return (prof / rev * 100).quantize(Decimal('0.01'), ROUND_HALF_UP) if rev else Decimal('0')

        if metric == K.M_REVENUE_PER_CUST:
            rev = self.resolve(K.M_NET_REVENUE, branch_ids=branch_ids, start=start, end=end,
                               softech_user=softech_user, category_id=category_id)
            pics = self._distinct_pic_all(branch_ids, start, end, softech_user, category_id)
            return (rev / pics).quantize(Decimal('0.01'), ROUND_HALF_UP) if pics else Decimal('0')

        if metric == K.M_CROSS_CATEGORY_RATE:
            base = self._ph_qs(branch_ids, start, end, softech_user).filter(
                doc_code='115', sales_channel__in=self.nonexclude_channels)
            total = base.count()
            if not total:
                return Decimal('0')
            multi = (base.annotate(ncat=Count('lines__item__category', distinct=True))
                     .filter(ncat__gt=1).count())
            return (Decimal(multi) / Decimal(total) * 100).quantize(Decimal('0.01'), ROUND_HALF_UP)

        if metric == K.M_NEW_CUSTOMERS:
            from apps.customers.models import PurchaseHistory
            period = (self._ph_qs(branch_ids, start, end, softech_user)
                      .filter(doc_code='115').exclude(softech_phcode='')
                      .values_list('softech_phcode', flat=True).distinct())
            period = set(period)
            if not period:
                return Decimal('0')
            prior = set(PurchaseHistory.objects.filter(
                invoice_date__date__lt=start, doc_code='115', softech_phcode__in=period)
                .values_list('softech_phcode', flat=True).distinct())
            return Decimal(len(period - prior))
        return Decimal('0')

    def _distinct_pic_all(self, branch_ids, start, end, softech_user=None, category_id=None):
        n = (self._ph_qs(branch_ids, start, end, softech_user, category_id)
             .filter(doc_code='115', sales_channel__in=self.nonexclude_channels)
             .exclude(softech_phcode='').values('softech_phcode').distinct().count())
        return Decimal(n)

    # ── discounting metrics (doc 16 metric-catalog) — line-based, all scopes ────
    def _discount_metric(self, metric, branch_ids, start, end, softech_user, category_id) -> Decimal:
        from django.db.models import Sum, F, Q, DecimalField, ExpressionWrapper
        from apps.forecasting.models import KpiActualRollup as K
        if not self.nonexclude_channels:
            return Decimal('0')
        base = self._line_qs(branch_ids, start, end, softech_user, category_id).filter(
            purchase__doc_code='115', purchase__sales_channel__in=self.nonexclude_channels)

        # Discount is the ACTUAL reduction: tax-INCLUSIVE list (list_price=itemsaleprice)
        # minus what the customer paid (line_total). This inherently discounts on the full
        # tax-inclusive price (owner rule), and ignores pharmacy/additional discp which are
        # NOT customer discounts (they don't reduce the paid price).
        gross_expr = ExpressionWrapper(F('list_price') * F('quantity'),
                                       output_field=DecimalField(max_digits=18, decimal_places=4))

        if metric == K.M_DISCOUNT_FREQ:
            total = base.count()
            if not total:
                return Decimal('0')
            # a line is "discounted" when list·qty exceeds what was paid (>0.5 EGP tolerance)
            disc = base.annotate(g=gross_expr).filter(g__gt=F('line_total') + Decimal('0.5')).count()
            return (Decimal(disc) / Decimal(total) * 100).quantize(Decimal('0.01'), ROUND_HALF_UP)

        gross = Decimal(str(base.aggregate(s=Sum(gross_expr))['s'] or 0))
        net   = Decimal(str(base.aggregate(s=Sum('line_total'))['s'] or 0))
        disc_val = max(gross - net, Decimal('0'))   # effective customer discount (tax-inclusive)

        if metric == K.M_GROSS_SALES:
            return gross.quantize(Decimal('0.01'), ROUND_HALF_UP)
        if metric == K.M_DISCOUNT_VALUE:
            return disc_val.quantize(Decimal('0.01'), ROUND_HALF_UP)
        if metric == K.M_DISCOUNT_PCT:
            return (disc_val / gross * 100).quantize(Decimal('0.01'), ROUND_HALF_UP) if gross else Decimal('0')
        if metric == K.M_DISC_TO_MARGIN:
            profit = Decimal(str(base.aggregate(s=Sum(_PROFIT_EXPR))['s'] or 0))
            return (disc_val / profit * 100).quantize(Decimal('0.01'), ROUND_HALF_UP) if profit > 0 else Decimal('0')
        return Decimal('0')

    # ── extended volume/mix metrics (doc 16 extension) — header scopes ──────────
    def _extended_metric(self, metric, branch_ids, start, end, softech_user) -> Decimal:
        from django.db.models import Count, Sum
        from apps.forecasting.models import KpiActualRollup as K
        chans = self.nonexclude_channels
        if not chans:
            return Decimal('0')
        sales = self._ph_qs(branch_ids, start, end, softech_user).filter(
            doc_code='115', sales_channel__in=chans)

        if metric == K.M_PIC_COUNT:
            return Decimal(sales.exclude(softech_phcode='').values('softech_phcode').distinct().count())
        if metric == K.M_BULK_TXN:
            from apps.config.models import SystemSetting
            thr = Decimal(str(SystemSetting.get('kpi_bulk_sale_threshold', 5000) or 5000))
            return Decimal(sales.filter(total_amount__gte=thr).count())
        if metric == K.M_MULTI_ITEM_TXN:
            return Decimal(sales.annotate(nl=Count('lines')).filter(nl__gt=1).count())
        if metric in (K.M_BASKET_VALUE, K.M_BASKET_UNITS):
            orders = sales.count()
            if not orders:
                return Decimal('0')
            if metric == K.M_BASKET_VALUE:
                net = self._net_amount(branch_ids, start, end, chans, softech_user)
                return (net / Decimal(orders)).quantize(Decimal('0.01'), ROUND_HALF_UP)
            units = (self._line_qs(branch_ids, start, end, softech_user)
                     .filter(purchase__doc_code='115', purchase__sales_channel__in=chans)
                     .aggregate(s=Sum('quantity'))['s'] or 0)
            return (Decimal(str(units)) / Decimal(orders)).quantize(Decimal('0.01'), ROUND_HALF_UP)
        return Decimal('0')

    # ── category scope (doc 16, Phase 6) — line-based, a category's own sales ────
    def _resolve_category(self, metric, branch_ids, start, end, category_id, softech_user) -> Decimal:
        from apps.forecasting.models import ChannelBucketMap as C, KpiActualRollup as K
        cash_all = self.channels_by_bucket.get(C.BUCKET_CASH, [])
        credit   = self.channels_by_bucket.get(C.BUCKET_CREDIT, [])

        def line_net(channels=None, profit=False):
            base = self._line_qs(branch_ids, start, end, softech_user, category_id)
            if channels is not None:
                base = base.filter(purchase__sales_channel__in=channels)
            else:
                base = base.filter(purchase__sales_channel__in=self.nonexclude_channels)
            expr = _PROFIT_EXPR if profit else 'line_total'
            agg = (lambda qs: qs.aggregate(s=Sum(expr))['s'] or 0)
            sale = agg(base.filter(purchase__doc_code='115'))
            ret  = agg(base.filter(purchase__doc_code='30'))
            return Decimal(str(sale)) - Decimal(str(ret))

        if metric == K.M_GROSS_PROFIT:
            return line_net(profit=True)
        if metric == K.M_CASH_DELIVERY:
            return line_net(cash_all)
        if metric == K.M_CREDIT:
            return line_net(credit)
        if metric in (K.M_NET_REVENUE, K.M_BEAUTY):
            return line_net()
        if metric == K.M_ORDERS:
            n = (self._ph_qs(branch_ids, start, end, softech_user, category_id)
                 .filter(doc_code='115').values('softech_invoice_id').distinct().count())
            return Decimal(n)
        if metric == K.M_CUSTOMERS:
            n = (self._ph_qs(branch_ids, start, end, softech_user, category_id)
                 .filter(doc_code='115', sales_channel__in=self.customer_channels)
                 .exclude(softech_phcode='').values('softech_phcode').distinct().count())
            return Decimal(n)
        return line_net()

    # ── call center (doc 16, Phase 5) — cross-branch overlay by sales agents ─────
    def compute_call_center_month(self, year, month, agent_usercodes=None) -> dict:
        """
        CC KPIs for a month from invoices placed by CC sales agents (all branches,
        all channels — matches the owner's 'doccode All / personcode All' pivot):
          sales   = net total_amount              profit = net gross profit
          beauty  = net beauty line_total         orders = distinct invoices (عدد العملاء)
        Call-count is added separately (from CDR). Returns metric keys reused by rollups.
        """
        from apps.forecasting.models import KpiActualRollup as K, CallCenterConfig
        agents = agent_usercodes or CallCenterConfig.get_solo().sales_agent_usercodes
        if not agents:
            return {}
        start, end = self.month_bounds(year, month)

        def net_amount():
            base = self._ph_qs(None, start, end, softech_user=agents)
            sale = base.filter(doc_code='115').aggregate(s=Sum('total_amount'))['s'] or 0
            ret  = base.filter(doc_code='30').aggregate(s=Sum('total_amount'))['s'] or 0
            return Decimal(str(sale)) - Decimal(str(ret))

        def net_profit():
            base = self._line_qs(None, start, end, softech_user=agents)
            sale = base.filter(purchase__doc_code='115').aggregate(s=Sum(_PROFIT_EXPR))['s'] or 0
            ret  = base.filter(purchase__doc_code='30').aggregate(s=Sum(_PROFIT_EXPR))['s'] or 0
            return Decimal(str(sale)) - Decimal(str(ret))

        def net_beauty():
            if not self.beauty_types:
                return Decimal('0')
            base = self._line_qs(None, start, end, softech_user=agents).filter(
                item__medicine_type__in=self.beauty_types)
            sale = base.filter(purchase__doc_code='115').aggregate(s=Sum('line_total'))['s'] or 0
            ret  = base.filter(purchase__doc_code='30').aggregate(s=Sum('line_total'))['s'] or 0
            return Decimal(str(sale)) - Decimal(str(ret))

        def distinct_orders():
            n = (self._ph_qs(None, start, end, softech_user=agents)
                 .filter(doc_code__in=['115', '30'])
                 .values('softech_invoice_id').distinct().count())
            return Decimal(n)

        return {
            K.M_CASH_DELIVERY: net_amount(),     # CC net sales (المبيعات)
            K.M_GROSS_PROFIT:  net_profit(),     # الربحية
            K.M_BEAUTY:        net_beauty(),     # التجميل
            K.M_CUSTOMERS:     distinct_orders(),# عدد العملاء (= distinct invoices, per owner)
        }

    # ── public: full month for one branch (rollup builder) ─────────────────────
    def compute_branch_month(self, branch_id, year, month) -> dict:
        """Return {metric_key: Decimal} for one branch × month (used by build_kpi_rollups)."""
        from apps.forecasting.models import KpiActualRollup as K
        start, end = self.month_bounds(year, month)
        keys = [
            K.M_CASH_DELIVERY, K.M_CASH, K.M_DELIVERY, K.M_REGULAR, K.M_CREDIT,
            K.M_INSURANCE, K.M_NET_REVENUE, K.M_GROSS_PROFIT, K.M_CUSTOMERS,
            K.M_ORDERS, K.M_BEAUTY,
        ]
        return {k: self.resolve(k, branch_ids=[branch_id], start=start, end=end) for k in keys}
