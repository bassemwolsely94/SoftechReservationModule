"""
Insight rule catalog (doc 18). Each rule is a function (ctx, threshold) → [finding dicts].
Rules use efficient GROUPED queries (not per-member resolver calls) so a daily scan
over all branches/salespeople is a handful of queries. Numbers reconcile with
KpiResolver (same channel buckets / net-of-returns convention).

A finding dict: {rule_code, category, severity, scope_type, scope_key, scope_label,
                 value, baseline, threshold, message_ar, message_en}
Register a new rule by adding a function and an entry in RULES.
"""
from decimal import Decimal
from datetime import timedelta, date as _date
import calendar
import itertools

from django.db.models import Sum, Count, F, Q, DecimalField, ExpressionWrapper, Case, When, Value


def _fmt(n):
    return f'{float(n or 0):,.0f}'


def _prng(s, e):
    """Compact date-range label for comparison pairs: '2026-08-01→2026-08-08' (or a single date)."""
    return f'{s}' if s == e else f'{s}→{e}'


def _ranking(ctx, code, title_ar, title_en, ranked, is_count=False, top=5):
    """Build one 'highlight' ranking finding. `ranked` = [(label_ar, label_en, value), …]
    (any order; sorted desc here). is_count → integer format, no money unit."""
    ranked = sorted((x for x in ranked if x[2]), key=lambda x: -float(x[2]))[:top]
    if not ranked:
        return None
    f = (lambda v: f'{int(v):,}') if is_count else _fmt
    ua, ue = ('', '') if is_count else (' ج.م', ' EGP')
    ar = ' · '.join(f'{i+1}) {la} {f(v)}' for i, (la, le, v) in enumerate(ranked))
    en = ' · '.join(f'{i+1}) {le} {f(v)}' for i, (la, le, v) in enumerate(ranked))
    return dict(rule_code=code, category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='',
        value=Decimal(str(ranked[0][2])), baseline=None, threshold=None,
        message_ar=f'{title_ar} ({ctx.label()}): {ar}{ua}.',
        message_en=f'{title_en} ({ctx.pw_en()}): {en}{ue}.')


def _cash_ph(ctx, start, end, doc='115'):
    """PurchaseHistory rows for CASH channels (walk-in + delivery + عميل دائم …)."""
    from apps.customers.models import PurchaseHistory
    return PurchaseHistory.objects.filter(
        invoice_date__date__gte=start, invoice_date__date__lte=end, doc_code=doc,
        branch_id__in=ctx.branch_ids, sales_channel__in=ctx.cash_channels)


def _seg_stats(ctx, channels, *, user=None, branch_id=None, max_total=None, min_total=None,
               beauty=False, item_codes=None, s=None, e=None, value_only=False):
    """Invoice-level stats for a sales segment, NET OF RETURNS (doc 115 − doc 30) so values
    reconcile with SOFTECH تحقيق / KpiResolver. Returns dict:
    {txn (sale count), value (net), units, lines, basket (lines/sale), avg_txn (net/sale)}.
    channels=None → all real channels. s/e override the window (default = report period).
    value_only=True skips the line aggregations (used for lightweight comparison values)."""
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    D = lambda x: Decimal(str(x or 0))
    ws, we = (s or ctx.start), (e or ctx.end)

    def docqs(doc):
        q = PurchaseHistory.objects.filter(
            invoice_date__date__gte=ws, invoice_date__date__lte=we, doc_code=doc,
            branch_id__in=([branch_id] if branch_id else ctx.branch_ids),
            sales_channel__in=(channels if channels is not None else ctx.nonexclude))
        if user:
            q = q.filter(softech_user=user)
        if max_total is not None:
            q = q.filter(total_amount__lt=max_total)
        if min_total is not None:
            q = q.filter(total_amount__gte=min_total)
        return q
    inv, ret = docqs('115'), docqs('30')

    if value_only:
        if beauty or item_codes:
            def restr(qs):
                l = PurchaseHistoryLine.objects.filter(purchase__in=qs)
                if beauty and ctx.beauty_types:
                    l = l.filter(item__medicine_type__in=ctx.beauty_types)
                if item_codes:
                    l = l.filter(item__softech_id__in=list(item_codes))
                return l
            val = D(restr(inv).aggregate(v=Sum('line_total'))['v']) - D(restr(ret).aggregate(v=Sum('line_total'))['v'])
        else:
            val = D(inv.aggregate(v=Sum('total_amount'))['v']) - D(ret.aggregate(v=Sum('total_amount'))['v'])
        return {'value': val, 'txn': inv.count()}

    if beauty or item_codes:
        def restrict(qs):
            l = PurchaseHistoryLine.objects.filter(purchase__in=qs)
            if beauty and ctx.beauty_types:
                l = l.filter(item__medicine_type__in=ctx.beauty_types)
            if item_codes:
                l = l.filter(item__softech_id__in=list(item_codes))
            return l
        ls, lr = restrict(inv), restrict(ret)
        sa = ls.aggregate(val=Sum('line_total'), units=Sum('quantity'), lines=Count('id'), txn=Count('purchase', distinct=True))
        val = D(sa['val']) - D(lr.aggregate(v=Sum('line_total'))['v'])
        txn = sa['txn'] or 0
        return {'txn': txn, 'value': val, 'units': D(sa['units']), 'lines': sa['lines'] or 0,
                'basket': (D(sa['lines']) / D(txn)) if txn else Decimal('0'),
                'avg_txn': (val / D(txn)) if txn else Decimal('0')}

    ia = inv.aggregate(txn=Count('id'), val=Sum('total_amount'))
    val = D(ia['val']) - D(ret.aggregate(v=Sum('total_amount'))['v'])
    la = PurchaseHistoryLine.objects.filter(purchase__in=inv).aggregate(lines=Count('id'), units=Sum('quantity'))
    txn = ia['txn'] or 0
    return {'txn': txn, 'value': val, 'units': D(la['units']), 'lines': la['lines'] or 0,
            'basket': (D(la['lines']) / D(txn)) if txn else Decimal('0'),
            'avg_txn': (val / D(txn)) if txn else Decimal('0')}


class Ctx:
    """Shared context + cached config for one run."""
    def __init__(self, period_type, start, end):
        from apps.forecasting.kpi import KpiResolver
        from apps.forecasting.models import ChannelBucketMap as C, CallCenterConfig
        from apps.branches.models import Branch
        self.period_type = period_type
        self.start, self.end = start, end
        if period_type == 'mtd':
            # previous SIMILAR period = same day-range of the previous calendar month
            py = start.year - (1 if start.month == 1 else 0)
            pm = 12 if start.month == 1 else start.month - 1
            pdim = calendar.monthrange(py, pm)[1]
            self.prev_start = _date(py, pm, 1)
            self.prev_end = _date(py, pm, min(end.day, pdim))
        else:
            days = (end - start).days + 1
            self.prev_start = start - timedelta(days=days)
            self.prev_end = start - timedelta(days=1)
        self.resolver = KpiResolver()
        self.cash_channels = self.resolver.channels_by_bucket.get('cash', [])
        self.delivery_channels = self.resolver.cash_sub.get('delivery', [])
        self.nonexclude = self.resolver.nonexclude_channels
        # Discount-tracking channel groups. Contracts (تعاقدات/credit) are pre-fixed by
        # contract — the salesperson can't change them — so they're EXCLUDED from discount
        # leakage rules. Walk-in/delivery (discretionary) and عميل دائم (regular) are tracked
        # SEPARATELY so each gets its own threshold/finding stream.
        self.credit_channels = self.resolver.channels_by_bucket.get('credit', [])
        self.regular_channels = self.resolver.cash_sub.get('regular', [])          # عميل دائم
        _reg = set(self.regular_channels)
        self.walkin_delivery_channels = [c for c in self.cash_channels if c not in _reg]  # نقدى + توصيل + موظفين + بطاقة
        self.customer_channels = self.resolver.customer_channels
        self.beauty_types = self.resolver.beauty_types
        self.cc_agents = CallCenterConfig.get_solo().sales_agent_usercodes or []
        from apps.forecasting.kpi import analytics_branches
        self.branches = list(analytics_branches().order_by('code'))   # retail only (excl HQ)
        # softech usercode → salesperson name (ERPUser fields are swapped: username=code, user_id=name)
        from apps.users.models import ERPUser
        self.rep_names = {str(c): (n or '').strip() for c, n in
                          ERPUser.objects.exclude(user_id='').values_list('username', 'user_id')}
        # pseudo-items to keep OUT of item-level findings (loyalty coupons, etc.) — owner-editable
        from apps.config.models import SystemSetting
        kws = [k.strip() for k in str(SystemSetting.get('analytics_excluded_item_keywords', 'COUPON,كوبون') or '').split(',') if k.strip()]
        self.excluded_item_ids = set()
        if kws:
            from django.db.models import Q
            from apps.catalog.models import Item
            q = Q()
            for k in kws:
                q |= Q(name__icontains=k)
            self.excluded_item_ids = set(Item.objects.filter(q).values_list('id', flat=True))
        # Owner-tunable money floors shared by several rules:
        #  • bulk_cash_floor  — a CASH invoice at/above this counts as a "bulk cash" sale.
        #  • basket_bulk_floor — invoices at/above this are EXCLUDED from basket-size stats
        #    (a few big-ticket invoices otherwise distort items/invoice + avg basket value).
        self.bulk_cash_floor = Decimal(str(SystemSetting.get('analytics_bulk_cash_floor', '10000') or '10000'))
        self.basket_bulk_floor = Decimal(str(SystemSetting.get('analytics_basket_bulk_floor', '5000') or '5000'))
        # Minimum transactions for a rep/branch to count as "active" — scaled by period so a
        # DAILY report still lists everyone who worked that day (a rep rarely does 30/day).
        self.min_active = {'day': 5, 'week': 20}.get(period_type, 30)
        # Channel segments (for segment analytics). cash = walk-in + delivery + عميل دائم.
        _delset = set(self.delivery_channels); _regset = set(self.regular_channels)
        self.walkin_channels = [c for c in self.cash_channels if c not in _delset and c not in _regset]  # 91/11/12
        # Owner-configurable item codes to track (count + value): "code:label,code:label".
        # e.g. "2:رسوم التوصيل,QP:قياس ضغط,QS:قياس سكر". Item codes = catalog softech_id.
        self.tracked_items = []
        for pair in str(SystemSetting.get('analytics_tracked_item_codes', '') or '').split(','):
            if ':' in pair:
                code, _, label = pair.partition(':')
                if code.strip():
                    self.tracked_items.append((code.strip(), label.strip() or code.strip()))
        self.branch_by_code = {b.code or b.softech_branch_id: b for b in self.branches}
        self.branch_ids = [b.id for b in self.branches]

    def label(self):
        m = {'day': 'يوم', 'week': 'أسبوع', 'month': 'شهر', 'mtd': 'شهر حتى تاريخه'}
        return m.get(self.period_type, self.period_type)

    def pw_en(self):
        return {'day': 'day', 'week': 'week', 'month': 'month', 'mtd': 'month-to-date'}.get(
            self.period_type, self.period_type)

    def rep(self, code):
        """Salesperson display name for a softech usercode (falls back to the code)."""
        return self.rep_names.get(str(code)) or str(code)

    @staticmethod
    def bn(b, lang):
        """Branch name in the requested language."""
        return (b.name_ar or b.name) if lang == 'ar' else (b.name or b.name_ar)


def _ph(ctx, start, end):
    """Invoices for the analytics branches, restricted to REAL sale channels
    (non-exclude buckets → drops تبرعات/donations, Vip, etc.)."""
    from apps.customers.models import PurchaseHistory
    return PurchaseHistory.objects.filter(
        invoice_date__date__gte=start, invoice_date__date__lte=end,
        branch_id__in=ctx.branch_ids, sales_channel__in=ctx.nonexclude)


def _net_by_user(ctx, channels, start=None, end=None):
    """Net revenue (115 − 30) by softech_user for a channel segment — same net basis as SOFTECH."""
    from apps.customers.models import PurchaseHistory
    s = start or ctx.start; e = end or ctx.end
    base = PurchaseHistory.objects.filter(
        invoice_date__date__gte=s, invoice_date__date__lte=e,
        branch_id__in=ctx.branch_ids, sales_channel__in=channels).exclude(softech_user='')
    sale = dict(base.filter(doc_code='115').values_list('softech_user').annotate(v=Sum('total_amount')))
    ret = dict(base.filter(doc_code='30').values_list('softech_user').annotate(v=Sum('total_amount')))
    return {u: Decimal(str(sale.get(u, 0) or 0)) - Decimal(str(ret.get(u, 0) or 0)) for u in set(sale) | set(ret)}


def _net_by_branch(ctx, start, end, channels=None):
    """Net revenue (115 − 30) by branch_id for a window."""
    qs = _ph(ctx, start, end)
    if channels is not None:
        qs = qs.filter(sales_channel__in=channels)
    sale = dict(qs.filter(doc_code='115').values_list('branch_id').annotate(s=Sum('total_amount')))
    ret = dict(qs.filter(doc_code='30').values_list('branch_id').annotate(s=Sum('total_amount')))
    return {bid: Decimal(str(sale.get(bid, 0) or 0)) - Decimal(str(ret.get(bid, 0) or 0))
            for bid in set(sale) | set(ret)}


# Weekday names (Python weekday(): Mon=0 … Sun=6).
_AR_DAYS = {0: 'الإثنين', 1: 'الثلاثاء', 2: 'الأربعاء', 3: 'الخميس', 4: 'الجمعة', 5: 'السبت', 6: 'الأحد'}
_EN_DAYS = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}


def _cmp_clause(cur, base, day_name, d, lang):
    """One comparison clause with day + date + baseline sales, e.g.
    '▼12% عن الجمعة 2026-08-01 (50,000 ج.م)'  /  '▲5% vs Friday …'."""
    if base and base > 0:
        pct = (base - cur) / base * Decimal('100')
        arrow = '▼' if pct >= 0 else '▲'
        head = f'{arrow}{abs(float(pct)):.0f}%'
    else:
        head = '— (لا بيانات)' if lang == 'ar' else '— (no data)'
    return (f'{head} عن {day_name} {d} ({_fmt(base)} ج.م)' if lang == 'ar'
            else f'{head} vs {day_name} {d} ({_fmt(base)} EGP)')


# ── Rules ────────────────────────────────────────────────────────────────────

def rule_branch_vs_prev(ctx, threshold):
    """Branch net-revenue drop.
    DAILY: the trigger is the SAME-WEEKDAY-LAST-WEEK comparison (neutralises the
    weekend/Friday effect); the finding shows BOTH the last-week pair and the
    previous-day pair (each with day name, date and sales).
    WEEK/MONTH: previous equal period (no weekday effect)."""
    thr = Decimal(str(threshold if threshold is not None else 25))
    out = []

    if ctx.period_type == 'day':
        d = ctx.start
        pd, lw = d - timedelta(days=1), d - timedelta(days=7)   # previous day, same weekday last week
        cur = _net_by_branch(ctx, d, d)
        prevday = _net_by_branch(ctx, pd, pd)
        lastwk = _net_by_branch(ctx, lw, lw)
        d_ar, d_en = _AR_DAYS[d.weekday()], _EN_DAYS[d.weekday()]
        pd_ar, pd_en = _AR_DAYS[pd.weekday()], _EN_DAYS[pd.weekday()]
        lw_ar, lw_en = _AR_DAYS[lw.weekday()], _EN_DAYS[lw.weekday()]
        for b in ctx.branches:
            c = cur.get(b.id, Decimal('0'))
            base_lw = lastwk.get(b.id, Decimal('0'))
            base_pd = prevday.get(b.id, Decimal('0'))
            if base_lw <= 0:                       # no weekday-normalised baseline → can't judge, skip (avoids noise)
                continue
            drop = (base_lw - c) / base_lw * Decimal('100')
            if drop < thr:                         # weekday-normalised drop decides the flag
                continue
            nm, ne = ctx.bn(b, 'ar'), ctx.bn(b, 'en')
            out.append(dict(rule_code='branch_vs_prev', category='comparison', severity='warning',
                scope_type='branch', scope_key=b.code, scope_label=nm,
                value=c, baseline=base_lw, threshold=thr,
                message_ar=(f'📉 {nm} — مبيعات {d_ar} {d}: {_fmt(c)} ج.م. '
                            f'{_cmp_clause(c, base_lw, lw_ar, lw, "ar")}؛ '
                            f'{_cmp_clause(c, base_pd, pd_ar, pd, "ar")}.'),
                message_en=(f'📉 {ne} — {d_en} {d} sales: {_fmt(c)} EGP. '
                            f'{_cmp_clause(c, base_lw, lw_en, lw, "en")}; '
                            f'{_cmp_clause(c, base_pd, pd_en, pd, "en")}.')))
        return out

    # week / month: previous equal period
    cur = _net_by_branch(ctx, ctx.start, ctx.end)
    prev = _net_by_branch(ctx, ctx.prev_start, ctx.prev_end)
    for b in ctx.branches:
        c, p = cur.get(b.id, Decimal('0')), prev.get(b.id, Decimal('0'))
        if p <= 0:
            continue
        drop = (p - c) / p * 100
        if drop >= thr:
            nm, ne = ctx.bn(b, 'ar'), ctx.bn(b, 'en')
            cur_r, prev_r = _prng(ctx.start, ctx.end), _prng(ctx.prev_start, ctx.prev_end)
            out.append(dict(rule_code='branch_vs_prev', category='comparison', severity='warning',
                scope_type='branch', scope_key=b.code, scope_label=nm,
                value=c, baseline=p, threshold=thr,
                message_ar=f'📉 {nm}: انخفضت المبيعات {drop:.0f}% — {_fmt(c)} ج.م ({cur_r}) مقابل {_fmt(p)} ج.م ({prev_r}).',
                message_en=f'📉 {ne}: sales down {drop:.0f}% — {_fmt(c)} EGP ({cur_r}) vs {_fmt(p)} EGP ({prev_r}).'))
    return out


def rule_branch_zero_delivery(ctx, threshold):
    """Branch had zero delivery sales while it normally has delivery."""
    cur = _net_by_branch(ctx, ctx.start, ctx.end, ctx.delivery_channels)
    prev = _net_by_branch(ctx, ctx.prev_start, ctx.prev_end, ctx.delivery_channels)
    out = []
    for b in ctx.branches:
        if cur.get(b.id, Decimal('0')) <= 0 and prev.get(b.id, Decimal('0')) > 0:
            nm, ne = ctx.bn(b, 'ar'), ctx.bn(b, 'en')
            out.append(dict(rule_code='branch_zero_delivery', category='coverage', severity='critical',
                scope_type='branch', scope_key=b.code, scope_label=nm, value=Decimal('0'),
                baseline=prev.get(b.id), threshold=None,
                message_ar=f'⚠️ {nm}: لا توجد مبيعات توصيل خلال ال{ctx.label()} (المعتاد ~{_fmt(prev.get(b.id))} ج.م).',
                message_en=f'⚠️ {ne}: zero delivery sales this {ctx.pw_en()} (usually ~{_fmt(prev.get(b.id))} EGP).'))
    return out


def rule_branch_zero_callcenter(ctx, threshold):
    """Branch had zero call-center (agent) orders while normally active."""
    if not ctx.cc_agents:
        return []
    def cc_orders(start, end):
        return dict(_ph(ctx, start, end).filter(doc_code='115', softech_user__in=ctx.cc_agents)
                    .values_list('branch_id').annotate(c=Count('id')))
    cur, prev = cc_orders(ctx.start, ctx.end), cc_orders(ctx.prev_start, ctx.prev_end)
    out = []
    for b in ctx.branches:
        if cur.get(b.id, 0) == 0 and prev.get(b.id, 0) > 0:
            nm, ne = ctx.bn(b, 'ar'), ctx.bn(b, 'en')
            out.append(dict(rule_code='branch_zero_callcenter', category='coverage', severity='critical',
                scope_type='branch', scope_key=b.code, scope_label=nm, value=Decimal('0'),
                baseline=Decimal(prev.get(b.id, 0)), threshold=None,
                message_ar=f'⚠️ {nm}: لم تُسجَّل أي طلبات كول سنتر خلال ال{ctx.label()} (المعتاد ~{prev.get(b.id)} طلب).',
                message_en=f'⚠️ {ne}: no call-center orders this {ctx.pw_en()} (usually ~{prev.get(b.id)} orders).'))
    return out


def rule_branch_no_new_customer(ctx, threshold):
    """Branch registered no first-time customer (PIC not seen before the period)."""
    from apps.customers.models import PurchaseHistory
    cur = _ph(ctx, ctx.start, ctx.end).filter(doc_code='115').exclude(softech_phcode='')
    seen_by_branch = {}
    for bid, phc in cur.values_list('branch_id', 'softech_phcode').distinct():
        seen_by_branch.setdefault(bid, set()).add(phc)
    # PICs that existed before the period (chain-wide)
    prior_pics = set(PurchaseHistory.objects.filter(
        invoice_date__date__lt=ctx.start, doc_code='115').exclude(softech_phcode='')
        .values_list('softech_phcode', flat=True).distinct())
    out = []
    for b in ctx.branches:
        pics = seen_by_branch.get(b.id, set())
        new = pics - prior_pics
        if pics and not new:
            nm, ne = ctx.bn(b, 'ar'), ctx.bn(b, 'en')
            out.append(dict(rule_code='branch_no_new_customer', category='coverage', severity='warning',
                scope_type='branch', scope_key=b.code, scope_label=nm, value=Decimal('0'),
                baseline=None, threshold=None,
                message_ar=f'👥 {nm}: لم يُسجَّل أي عميل جديد (PIC) خلال ال{ctx.label()}.',
                message_en=f'👥 {ne}: no new customer (PIC) registered this {ctx.pw_en()}.'))
    return out


def rule_salesperson_no_beauty(ctx, threshold):
    """Active salesperson sold no beauty this period (only for reps with real sales)."""
    if not ctx.beauty_types:
        return []
    floor = Decimal(str(threshold if threshold is not None else 5000))  # min total sales to flag
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    total_by_user = dict(_ph(ctx, ctx.start, ctx.end).filter(doc_code='115')
                         .exclude(softech_user='').values_list('softech_user').annotate(s=Sum('total_amount')))
    beauty_users = set(PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
        purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids, purchase__sales_channel__in=ctx.nonexclude,
        item__medicine_type__in=ctx.beauty_types).exclude(purchase__softech_user='')
        .values_list('purchase__softech_user', flat=True).distinct())
    out = []
    for user, tot in total_by_user.items():
        if user in ctx.cc_agents:
            continue
        if Decimal(str(tot or 0)) >= floor and user not in beauty_users:
            out.append(dict(rule_code='salesperson_no_beauty', category='mix', severity='warning',
                scope_type='salesperson', scope_key=user, scope_label=f'مسئول البيع {ctx.rep(user)}',
                value=Decimal('0'), baseline=Decimal(str(tot)), threshold=floor,
                message_ar=f'💄 مسئول البيع {ctx.rep(user)}: لم يبع أي منتجات تجميل خلال ال{ctx.label()} (إجمالى مبيعاته {_fmt(tot)} ج.م).',
                message_en=f'💄 Salesperson {ctx.rep(user)}: sold no beauty products this {ctx.pw_en()} (total sales {_fmt(tot)} EGP).'))
    return out


def rule_salesperson_below_avg(ctx, threshold):
    """Salesperson period sales below threshold% of their trailing average (same period length)."""
    thr = Decimal(str(threshold if threshold is not None else 50)) / 100   # e.g. 0.5 = below half
    days = (ctx.end - ctx.start).days + 1
    tw_start = ctx.start - timedelta(days=days * 4)      # trailing 4 equal periods
    tw_end = ctx.start - timedelta(days=1)
    cur = dict(_ph(ctx, ctx.start, ctx.end).filter(doc_code='115').exclude(softech_user='')
               .values_list('softech_user').annotate(s=Sum('total_amount')))
    trail = dict(_ph(ctx, tw_start, tw_end).filter(doc_code='115').exclude(softech_user='')
                 .values_list('softech_user').annotate(s=Sum('total_amount')))
    out = []
    for user, tot in cur.items():
        if user in ctx.cc_agents:
            continue
        avg = Decimal(str(trail.get(user, 0) or 0)) / Decimal('4')
        c = Decimal(str(tot or 0))
        if avg >= 1000 and c < avg * thr:
            drop = (avg - c) / avg * 100
            out.append(dict(rule_code='salesperson_below_avg', category='volume', severity='warning',
                scope_type='salesperson', scope_key=user, scope_label=f'مسئول البيع {ctx.rep(user)}',
                value=c, baseline=avg, threshold=thr * 100,
                message_ar=f'🔻 مسئول البيع {ctx.rep(user)}: مبيعاته أقل {drop:.0f}% من متوسطه ({_fmt(c)} مقابل متوسط {_fmt(avg)} ج.م).',
                message_en=f'🔻 Salesperson {ctx.rep(user)}: {drop:.0f}% below his average ({_fmt(c)} vs {_fmt(avg)} EGP avg).'))
    return out


def _high_discount_core(ctx, threshold, channels, rule_code, tag_ar, tag_en):
    """Lines in `channels` discounted above threshold% (tax-inclusive list vs paid).
    Contracts are never passed in here (pre-fixed prices). Shows discount % AND value (EGP)."""
    thr = Decimal(str(threshold if threshold is not None else 30))
    if not channels:
        return []
    from apps.customers.models import PurchaseHistoryLine
    gross = ExpressionWrapper(F('list_price') * F('quantity'),
                              output_field=DecimalField(max_digits=18, decimal_places=4))
    qs = (PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
            purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
            purchase__sales_channel__in=channels, list_price__gt=0)
          .exclude(item_id__in=ctx.excluded_item_ids)
          .annotate(g=gross).filter(g__gt=0)
          .annotate(dpct=ExpressionWrapper((F('g') - F('line_total')) * Decimal('100') / F('g'),
                                           output_field=DecimalField(max_digits=8, decimal_places=2)))
          .filter(dpct__gte=thr).select_related('item', 'purchase')
          .order_by('-dpct')[:10])
    out = []
    for l in qs:
        item = getattr(l.item, 'name', '') or l.purchase.softech_invoice_id
        user = l.purchase.softech_user
        val = Decimal(str(l.g)) - Decimal(str(l.line_total))   # discount value (EGP)
        out.append(dict(rule_code=rule_code, category='discount', severity='warning',
            scope_type='product', scope_key=str(getattr(l.item, 'softech_id', '') or ''),
            scope_label=item, value=Decimal(str(round(float(l.dpct), 2))), baseline=None, threshold=thr,
            message_ar=f'🏷️ [{tag_ar}] خصم {float(l.dpct):.0f}% ({_fmt(val)} ج.م) على «{item}» (مسئول البيع {ctx.rep(user)}) — أعلى من الحد {thr:.0f}%.',
            message_en=f'🏷️ [{tag_en}] {float(l.dpct):.0f}% discount ({_fmt(val)} EGP) on “{item}” (salesperson {ctx.rep(user)}) — above the {thr:.0f}% cap.'))
    return out


def rule_high_discount(ctx, threshold):
    """Walk-in + delivery lines over the discount cap (salesperson discretion)."""
    return _high_discount_core(ctx, threshold, ctx.walkin_delivery_channels,
                               'high_discount', 'نقدى/توصيل', 'walk-in/delivery')


def rule_high_discount_regular(ctx, threshold):
    """عميل دائم (regular-customer) lines over the discount cap — tracked separately."""
    return _high_discount_core(ctx, threshold, ctx.regular_channels,
                               'high_discount_regular', 'عميل دائم', 'regular')


def rule_bulk_sale(ctx, threshold):
    """Large CASH invoices (walk-in + delivery + عميل دائم) at/above the bulk threshold.
    Shows invoice number, date and branch. Top few."""
    thr = Decimal(str(threshold if threshold is not None else 10000))
    from apps.customers.models import PurchaseHistory
    qs = (PurchaseHistory.objects.filter(
            invoice_date__date__gte=ctx.start, invoice_date__date__lte=ctx.end,
            doc_code='115', branch_id__in=ctx.branch_ids, sales_channel__in=ctx.cash_channels,
            total_amount__gte=thr)
          .select_related('branch').order_by('-total_amount')[:10])
    out = []
    for p in qs:
        nm = ctx.bn(p.branch, 'ar') if p.branch_id else '—'
        ne = ctx.bn(p.branch, 'en') if p.branch_id else '—'
        inv = p.docnumber or p.softech_invoice_id
        d = p.invoice_date.date() if p.invoice_date else ''
        out.append(dict(rule_code='bulk_sale', category='discount', severity='info',
            scope_type='branch', scope_key=(p.branch.code if p.branch_id else ''), scope_label=nm,
            value=Decimal(str(p.total_amount)), baseline=None, threshold=thr,
            message_ar=f'📦 فاتورة نقدية كبيرة {_fmt(p.total_amount)} ج.م — فاتورة {inv} بتاريخ {d} في {nm} (مسئول البيع {ctx.rep(p.softech_user)}).',
            message_en=f'📦 Large cash invoice {_fmt(p.total_amount)} EGP — invoice {inv} on {d} at {ne} (salesperson {ctx.rep(p.softech_user)}).'))
    return out


def rule_top_branch(ctx, threshold):
    """Positive highlight: best-growing branch vs previous period."""
    cur = _net_by_branch(ctx, ctx.start, ctx.end)
    prev = _net_by_branch(ctx, ctx.prev_start, ctx.prev_end)
    best, best_g = None, None
    for b in ctx.branches:
        c, p = cur.get(b.id, Decimal('0')), prev.get(b.id, Decimal('0'))
        if p > 0:
            g = (c - p) / p * 100
            if best_g is None or g > best_g:
                best, best_g = b, g
    if best and best_g and best_g > 0:
        nm, ne = ctx.bn(best, 'ar'), ctx.bn(best, 'en')
        c, p = cur.get(best.id), prev.get(best.id)
        cur_r, prev_r = _prng(ctx.start, ctx.end), _prng(ctx.prev_start, ctx.prev_end)
        return [dict(rule_code='top_branch', category='highlight', severity='info',
            scope_type='branch', scope_key=best.code, scope_label=nm,
            value=c, baseline=p, threshold=None,
            message_ar=f'🏆 الأفضل نمواً: {nm} +{best_g:.0f}% — {_fmt(c)} ج.م ({cur_r}) مقابل {_fmt(p)} ج.م ({prev_r}).',
            message_en=f'🏆 Top growth: {ne} +{best_g:.0f}% — {_fmt(c)} EGP ({cur_r}) vs {_fmt(p)} EGP ({prev_r}).')]
    return []


HQ_CODE = '100'
_PROFIT = ExpressionWrapper(F('line_total') - F('quantity') * F('cost_at_sale'),
                           output_field=DecimalField(max_digits=18, decimal_places=4))


# ── Sales leakage / performance (PurchaseHistory) ─────────────────────────────

def rule_below_cost_sale(ctx, threshold):
    """Lines sold below cost by ≥ threshold EGP (margin leakage). Top offenders."""
    thr = Decimal(str(threshold if threshold is not None else 100))
    from apps.customers.models import PurchaseHistoryLine
    qs = (PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
            purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids, purchase__sales_channel__in=ctx.nonexclude)
          .exclude(item_id__in=ctx.excluded_item_ids)
          .annotate(loss=_PROFIT).filter(loss__lte=-thr)
          .select_related('item', 'purchase', 'purchase__branch').order_by('loss')[:10])
    out = []
    for l in qs:
        p = l.purchase
        item = getattr(l.item, 'name', '') or p.softech_invoice_id
        loss = abs(float(l.loss))
        nm = ctx.bn(p.branch, 'ar') if p.branch_id else '—'
        ne = ctx.bn(p.branch, 'en') if p.branch_id else '—'
        inv = p.docnumber or p.softech_invoice_id
        d = p.invoice_date.date() if p.invoice_date else ''
        out.append(dict(rule_code='below_cost_sale', category='discount', severity='critical',
            scope_type='product', scope_key=str(getattr(l.item, 'softech_id', '') or ''), scope_label=item,
            value=Decimal(str(round(loss, 2))), baseline=None, threshold=thr,
            message_ar=f'🩸 بيع بأقل من التكلفة: «{item}» بخسارة {_fmt(loss)} ج.م — فاتورة {inv} بتاريخ {d} في {nm} (مسئول البيع {ctx.rep(p.softech_user)}).',
            message_en=f'🩸 Sold below cost: “{item}” at {_fmt(loss)} EGP loss — invoice {inv} on {d} at {ne} (salesperson {ctx.rep(p.softech_user)}).'))
    return out


def _sales_ret_by_branch(ctx, start, end):
    q = _ph(ctx, start, end)
    sale = dict(q.filter(doc_code='115').values_list('branch_id').annotate(s=Sum('total_amount')))
    ret = dict(q.filter(doc_code='30').values_list('branch_id').annotate(s=Sum('total_amount')))
    return sale, ret


def rule_branch_high_returns(ctx, threshold):
    """Branch return value / sales exceeds threshold% (leakage / dissatisfaction)."""
    thr = Decimal(str(threshold if threshold is not None else 8))
    sale, ret = _sales_ret_by_branch(ctx, ctx.start, ctx.end)
    out = []
    for b in ctx.branches:
        s = Decimal(str(sale.get(b.id, 0) or 0)); r = Decimal(str(ret.get(b.id, 0) or 0))
        if s > 0:
            pct = r / s * 100
            if pct >= thr:
                nm, ne = ctx.bn(b, 'ar'), ctx.bn(b, 'en')
                out.append(dict(rule_code='branch_high_returns', category='volume', severity='warning',
                    scope_type='branch', scope_key=b.code, scope_label=nm, value=r, baseline=s, threshold=thr,
                    message_ar=f'↩️ {nm}: نسبة المرتجعات {pct:.0f}% من المبيعات ({_fmt(r)} ج.م) — أعلى من الحد {thr:.0f}%.',
                    message_en=f'↩️ {ne}: returns {pct:.0f}% of sales ({_fmt(r)} EGP) — above the {thr:.0f}% cap.'))
    return out


def _profit_by_branch(ctx, start, end):
    from apps.customers.models import PurchaseHistoryLine
    def g(doc):
        return dict(PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=start, purchase__invoice_date__date__lte=end,
            purchase__doc_code=doc, purchase__branch_id__in=ctx.branch_ids, purchase__sales_channel__in=ctx.nonexclude)
            .values_list('purchase__branch_id').annotate(s=Sum(_PROFIT)))
    sale, ret = g('115'), g('30')
    return {bid: Decimal(str(sale.get(bid, 0) or 0)) - Decimal(str(ret.get(bid, 0) or 0))
            for bid in set(sale) | set(ret)}


def _profit_by_user(ctx, start=None, end=None):
    """Net gross-profit (115 − 30) by softech_user."""
    from apps.customers.models import PurchaseHistoryLine
    s = start or ctx.start; e = end or ctx.end
    def g(doc):
        return dict(PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=s, purchase__invoice_date__date__lte=e,
            purchase__doc_code=doc, purchase__branch_id__in=ctx.branch_ids, purchase__sales_channel__in=ctx.nonexclude)
            .exclude(purchase__softech_user='').values_list('purchase__softech_user').annotate(s=Sum(_PROFIT)))
    sale, ret = g('115'), g('30')
    return {u: Decimal(str(sale.get(u, 0) or 0)) - Decimal(str(ret.get(u, 0) or 0)) for u in set(sale) | set(ret)}


def rule_branch_margin_drop(ctx, threshold):
    """Branch gross-margin % fell ≥ threshold points vs the previous period."""
    thr = Decimal(str(threshold if threshold is not None else 3))
    cn = _net_by_branch(ctx, ctx.start, ctx.end); cp = _profit_by_branch(ctx, ctx.start, ctx.end)
    pn = _net_by_branch(ctx, ctx.prev_start, ctx.prev_end); pp = _profit_by_branch(ctx, ctx.prev_start, ctx.prev_end)
    out = []
    for b in ctx.branches:
        cnet, pnet = cn.get(b.id, Decimal('0')), pn.get(b.id, Decimal('0'))
        if cnet > 0 and pnet > 0:
            cm = cp.get(b.id, Decimal('0')) / cnet * 100
            pm = pp.get(b.id, Decimal('0')) / pnet * 100
            if pm - cm >= thr:
                nm, ne = ctx.bn(b, 'ar'), ctx.bn(b, 'en')
                out.append(dict(rule_code='branch_margin_drop', category='comparison', severity='warning',
                    scope_type='branch', scope_key=b.code, scope_label=nm,
                    value=Decimal(str(round(float(cm), 1))), baseline=Decimal(str(round(float(pm), 1))), threshold=thr,
                    message_ar=f'📉 {nm}: هامش الربح نزل من {pm:.0f}% ({_prng(ctx.prev_start, ctx.prev_end)}) إلى {cm:.0f}% ({_prng(ctx.start, ctx.end)}).',
                    message_en=f'📉 {ne}: gross margin {pm:.0f}% ({_prng(ctx.prev_start, ctx.prev_end)}) → {cm:.0f}% ({_prng(ctx.start, ctx.end)}).'))
    return out


def _over_discount_core(ctx, threshold, channels, rule_code, tag_ar, tag_en, min_gross=20000):
    """Rep average discount % above the cap for `channels` (margin leakage). Contracts
    are never passed in (pre-fixed). Reports avg % AND total discount value (EGP).
    `min_gross` = minimum rep sales (list value) to qualify — avoids skew from tiny samples;
    smaller for عميل دائم since that channel has lower per-rep volume."""
    thr = Decimal(str(threshold if threshold is not None else 12))
    if not channels:
        return []
    from apps.customers.models import PurchaseHistoryLine
    gross = ExpressionWrapper(F('list_price') * F('quantity'),
                              output_field=DecimalField(max_digits=18, decimal_places=4))
    rows = (PurchaseHistoryLine.objects.filter(
                purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
                purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
                purchase__sales_channel__in=channels, list_price__gt=0)
            .exclude(purchase__softech_user='')
            .values('purchase__softech_user')
            .annotate(g=Sum(gross), n=Sum('line_total')))
    floor = Decimal(str(min_gross))
    out = []
    for r in rows:
        g = Decimal(str(r['g'] or 0)); n = Decimal(str(r['n'] or 0))
        if g >= floor:
            pct = (g - n) / g * 100
            if pct >= thr:
                u = r['purchase__softech_user']
                if u in ctx.cc_agents:
                    continue
                val = g - n   # total discount value (EGP)
                out.append(dict(rule_code=rule_code, category='discount', severity='warning',
                    scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
                    value=Decimal(str(round(float(pct), 1))), baseline=g, threshold=thr,
                    message_ar=f'🏷️ [{tag_ar}] مسئول البيع {ctx.rep(u)}: متوسط الخصم {pct:.0f}% بقيمة {_fmt(val)} ج.م على مبيعات {_fmt(g)} ج.م — أعلى من الحد {thr:.0f}%.',
                    message_en=f'🏷️ [{tag_en}] Salesperson {ctx.rep(u)}: avg discount {pct:.0f}% ({_fmt(val)} EGP) on {_fmt(g)} EGP of sales — above the {thr:.0f}% cap.'))
    return out


def rule_salesperson_over_discount(ctx, threshold):
    """Walk-in + delivery: rep avg discount % above cap (salesperson discretion)."""
    return _over_discount_core(ctx, threshold, ctx.walkin_delivery_channels,
                               'salesperson_over_discount', 'نقدى/توصيل', 'walk-in/delivery')


def rule_salesperson_over_discount_regular(ctx, threshold):
    """عميل دائم: rep avg discount % + value above cap — tracked separately (lower
    sales floor since the regular channel has lower per-rep volume)."""
    return _over_discount_core(ctx, threshold, ctx.regular_channels,
                               'salesperson_over_discount_regular', 'عميل دائم', 'regular', min_gross=5000)


def rule_salesperson_regular_share(ctx, threshold):
    """Hard-discounter signal: what SHARE of a salesperson's cash sales (walk-in +
    delivery + عميل دائم) sits in the discountable عميل دائم channel. A high share
    means the rep is steering business into the channel where discounts are given.
    Reports the عميل دائم value, its share of cash sales, and its discount %."""
    thr = Decimal(str(threshold if threshold is not None else 30))
    cash = ctx.walkin_delivery_channels + ctx.regular_channels
    reg = set(ctx.regular_channels)
    if not cash or not reg:
        return []
    from apps.customers.models import PurchaseHistoryLine
    DF = DecimalField(max_digits=18, decimal_places=4)
    gross = ExpressionWrapper(F('list_price') * F('quantity'), output_field=DF)
    reg_gross = Case(When(purchase__sales_channel__in=reg, then=gross), default=Value(0), output_field=DF)
    reg_paid = Case(When(purchase__sales_channel__in=reg, then=F('line_total')), default=Value(0), output_field=DF)
    rows = (PurchaseHistoryLine.objects.filter(
                purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
                purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
                purchase__sales_channel__in=cash, list_price__gt=0)
            .exclude(purchase__softech_user='')
            .values('purchase__softech_user')
            .annotate(cash_net=Sum('line_total'), reg_net=Sum(reg_paid), reg_grs=Sum(reg_gross)))
    out = []
    for r in rows:
        cash_net = Decimal(str(r['cash_net'] or 0))
        reg_net = Decimal(str(r['reg_net'] or 0))
        reg_grs = Decimal(str(r['reg_grs'] or 0))
        if cash_net < 20000 or reg_net <= 0:          # need meaningful cash volume + some عميل دائم
            continue
        share = reg_net / cash_net * 100
        if share < thr:
            continue
        u = r['purchase__softech_user']
        if u in ctx.cc_agents:
            continue
        disc = (reg_grs - reg_net) / reg_grs * 100 if reg_grs > 0 else Decimal('0')
        out.append(dict(rule_code='salesperson_regular_share', category='discount', severity='warning',
            scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
            value=Decimal(str(round(float(share), 1))), baseline=cash_net, threshold=thr,
            message_ar=(f'📊 مسئول البيع {ctx.rep(u)}: مبيعات عميل دائم {_fmt(reg_net)} ج.م = '
                        f'{share:.0f}% من مبيعاته النقدية ({_fmt(cash_net)} ج.م)، متوسط الخصم على عميل دائم {disc:.0f}%.'),
            message_en=(f'📊 Salesperson {ctx.rep(u)}: regular-customer sales {_fmt(reg_net)} EGP = '
                        f'{share:.0f}% of cash sales ({_fmt(cash_net)} EGP), avg regular discount {disc:.0f}%.')))
    return out


# ── Salesperson deep analysis ─────────────────────────────────────────────────

def rule_salesperson_basket(ctx, threshold):
    """Low items-per-invoice per rep (upsell coaching signal). Computed from CASH sales
    (walk-in + delivery + عميل دائم), EXCLUDING big-ticket invoices (≥ basket_bulk_floor)
    which would distort the basket average. Active reps only."""
    thr = Decimal(str(threshold if threshold is not None else 2))
    from apps.customers.models import PurchaseHistoryLine
    rows = (PurchaseHistoryLine.objects.filter(
                purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
                purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
                purchase__sales_channel__in=ctx.cash_channels,
                purchase__total_amount__lt=ctx.basket_bulk_floor)
            .exclude(purchase__softech_user='')
            .values('purchase__softech_user')
            .annotate(lines=Count('id'), invs=Count('purchase', distinct=True), val=Sum('line_total')))
    out = []
    for r in rows:
        invs = r['invs'] or 0
        u = r['purchase__softech_user']
        if invs < 30 or u in ctx.cc_agents:
            continue
        ipi = Decimal(r['lines']) / Decimal(invs)
        if ipi >= thr:
            continue
        atv = Decimal(str(r['val'] or 0)) / Decimal(invs)
        out.append(dict(rule_code='salesperson_basket', category='volume', severity='warning',
            scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
            value=Decimal(str(round(float(ipi), 2))), baseline=Decimal(invs), threshold=thr,
            message_ar=f'🧺 مسئول البيع {ctx.rep(u)}: متوسط {ipi:.1f} صنف/فاتورة على {invs} فاتورة (متوسط الفاتورة {_fmt(atv)} ج.م) — فرصة بيع إضافي.',
            message_en=f'🧺 Salesperson {ctx.rep(u)}: {ipi:.1f} items/invoice over {invs} invoices (avg {_fmt(atv)} EGP) — upsell opportunity.'))
    return out


def rule_salesperson_beauty_attach(ctx, threshold):
    """Low beauty attach rate per rep (% of their invoices containing a beauty item)."""
    thr = Decimal(str(threshold if threshold is not None else 20))
    if not ctx.beauty_types:
        return []
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    tot = dict(PurchaseHistory.objects.filter(
                invoice_date__date__gte=ctx.start, invoice_date__date__lte=ctx.end,
                doc_code='115', branch_id__in=ctx.branch_ids, sales_channel__in=ctx.nonexclude)
            .exclude(softech_user='').values_list('softech_user').annotate(n=Count('id')))
    bty = dict(PurchaseHistoryLine.objects.filter(
                purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
                purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
                purchase__sales_channel__in=ctx.nonexclude, item__medicine_type__in=ctx.beauty_types)
            .exclude(purchase__softech_user='')
            .values_list('purchase__softech_user').annotate(n=Count('purchase', distinct=True)))
    out = []
    for u, t in tot.items():
        if t < 30 or u in ctx.cc_agents:
            continue
        b = bty.get(u, 0)
        rate = Decimal(b) / Decimal(t) * 100
        if rate < thr:
            out.append(dict(rule_code='salesperson_beauty_attach', category='mix', severity='warning',
                scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
                value=Decimal(str(round(float(rate), 1))), baseline=Decimal(t), threshold=thr,
                message_ar=f'💄 مسئول البيع {ctx.rep(u)}: منتج تجميل في {rate:.0f}% فقط من فواتيره ({b} من {t}) — فرصة بيع متقاطع.',
                message_en=f'💄 Salesperson {ctx.rep(u)}: beauty item in only {rate:.0f}% of invoices ({b} of {t}) — cross-sell gap.'))
    return out


def rule_salesperson_return_rate(ctx, threshold):
    """A rep whose returns are a high % of their sales (quality / possible abuse)."""
    thr = Decimal(str(threshold if threshold is not None else 8))
    from apps.customers.models import PurchaseHistory
    base = (PurchaseHistory.objects.filter(
                invoice_date__date__gte=ctx.start, invoice_date__date__lte=ctx.end,
                branch_id__in=ctx.branch_ids, sales_channel__in=ctx.nonexclude)
            .exclude(softech_user=''))
    sales = dict(base.filter(doc_code='115').values_list('softech_user').annotate(v=Sum('total_amount')))
    rets = dict(base.filter(doc_code='30').values_list('softech_user').annotate(v=Sum('total_amount')))
    out = []
    for u, sv in sales.items():
        s = Decimal(str(sv or 0))
        if s < 20000 or u in ctx.cc_agents:
            continue
        rv = Decimal(str(rets.get(u, 0) or 0))
        rate = rv / s * 100 if s else Decimal('0')
        if rate >= thr:
            out.append(dict(rule_code='salesperson_return_rate', category='volume', severity='warning',
                scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
                value=Decimal(str(round(float(rate), 1))), baseline=s, threshold=thr,
                message_ar=f'↩️ مسئول البيع {ctx.rep(u)}: مرتجعاته {rate:.0f}% من مبيعاته ({_fmt(rv)} من {_fmt(s)} ج.م) — الحد {thr:.0f}%.',
                message_en=f'↩️ Salesperson {ctx.rep(u)}: returns {rate:.0f}% of sales ({_fmt(rv)} of {_fmt(s)} EGP) — cap {thr:.0f}%.'))
    return out


def rule_salesperson_customer_concentration(ctx, threshold):
    """A rep with too much of their sales concentrated on a single customer (PIC) —
    favoritism / collusion signal."""
    thr = Decimal(str(threshold if threshold is not None else 40))
    from collections import defaultdict
    from apps.customers.models import PurchaseHistory
    rows = (PurchaseHistory.objects.filter(
                invoice_date__date__gte=ctx.start, invoice_date__date__lte=ctx.end,
                doc_code='115', branch_id__in=ctx.branch_ids, sales_channel__in=ctx.nonexclude)
            .exclude(softech_user='')
            .values('softech_user', 'softech_phcode').annotate(v=Sum('total_amount')))
    tot = defaultdict(Decimal); topv = defaultdict(Decimal); toppic = {}
    for r in rows:
        u = r['softech_user']; pic = (r['softech_phcode'] or '').strip(); v = Decimal(str(r['v'] or 0))
        tot[u] += v
        if pic and v > topv[u]:
            topv[u] = v; toppic[u] = pic
    out = []
    for u, t in tot.items():
        if t < 20000 or u in ctx.cc_agents or u not in toppic:
            continue
        share = topv[u] / t * 100 if t else Decimal('0')
        if share >= thr:
            out.append(dict(rule_code='salesperson_customer_concentration', category='comparison', severity='warning',
                scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
                value=Decimal(str(round(float(share), 1))), baseline=t, threshold=thr,
                message_ar=f'🎯 مسئول البيع {ctx.rep(u)}: {share:.0f}% من مبيعاته لعميل واحد ({toppic[u]}) بقيمة {_fmt(topv[u])} من {_fmt(t)} ج.م.',
                message_en=f'🎯 Salesperson {ctx.rep(u)}: {share:.0f}% of sales to one customer ({toppic[u]}) — {_fmt(topv[u])} of {_fmt(t)} EGP.'))
    return out


def rule_salesperson_most_improved(ctx, threshold):
    """Positive highlight: the rep with the strongest sales growth vs the previous period."""
    from apps.customers.models import PurchaseHistory
    def net_by_user(s, e):
        base = (PurchaseHistory.objects.filter(
                    invoice_date__date__gte=s, invoice_date__date__lte=e,
                    branch_id__in=ctx.branch_ids, sales_channel__in=ctx.nonexclude).exclude(softech_user=''))
        sales = dict(base.filter(doc_code='115').values_list('softech_user').annotate(v=Sum('total_amount')))
        rets = dict(base.filter(doc_code='30').values_list('softech_user').annotate(v=Sum('total_amount')))
        return {u: Decimal(str(sales.get(u, 0) or 0)) - Decimal(str(rets.get(u, 0) or 0))
                for u in set(sales) | set(rets)}
    cur = net_by_user(ctx.start, ctx.end); prev = net_by_user(ctx.prev_start, ctx.prev_end)
    best = None
    for u, c in cur.items():
        p = prev.get(u, Decimal('0'))
        if p < 20000 or u in ctx.cc_agents:
            continue
        g = (c - p) / p * 100
        if best is None or g > best[1]:
            best = (u, g, c, p)
    if not best or best[1] <= 0:
        return []
    u, g, c, p = best
    cur_r, prev_r = _prng(ctx.start, ctx.end), _prng(ctx.prev_start, ctx.prev_end)
    return [dict(rule_code='salesperson_most_improved', category='highlight', severity='info',
        scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
        value=Decimal(str(round(float(g), 1))), baseline=p, threshold=None,
        message_ar=f'🌟 الأكثر تحسّناً: مسئول البيع {ctx.rep(u)} +{g:.0f}% — {_fmt(p)} ج.م ({prev_r}) ← {_fmt(c)} ج.م ({cur_r}).',
        message_en=f'🌟 Most improved: salesperson {ctx.rep(u)} +{g:.0f}% — {_fmt(p)} EGP ({prev_r}) → {_fmt(c)} EGP ({cur_r}).')]


# ── Sales boosting + abuse ────────────────────────────────────────────────────

def rule_branch_basket(ctx, threshold):
    """Branches with low items-per-invoice — basket-growth / upsell opportunity. Computed
    from CASH sales excluding big-ticket invoices (≥ basket_bulk_floor)."""
    thr = Decimal(str(threshold if threshold is not None else 2.3))
    from apps.customers.models import PurchaseHistoryLine
    rows = (PurchaseHistoryLine.objects.filter(
                purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
                purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
                purchase__sales_channel__in=ctx.cash_channels,
                purchase__total_amount__lt=ctx.basket_bulk_floor)
            .values('purchase__branch_id')
            .annotate(lines=Count('id'), invs=Count('purchase', distinct=True), val=Sum('line_total')))
    bmap = {b.id: b for b in ctx.branches}
    out = []
    for r in rows:
        invs = r['invs'] or 0
        b = bmap.get(r['purchase__branch_id'])
        if invs < 100 or not b:
            continue
        ipi = Decimal(r['lines']) / Decimal(invs)
        if ipi >= thr:
            continue
        atv = Decimal(str(r['val'] or 0)) / Decimal(invs)
        out.append(dict(rule_code='branch_basket', category='volume', severity='warning',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'),
            value=Decimal(str(round(float(ipi), 2))), baseline=Decimal(invs), threshold=thr,
            message_ar=f'🧺 {ctx.bn(b,"ar")}: متوسط {ipi:.1f} صنف/فاتورة، متوسط الفاتورة {_fmt(atv)} ج.م على {invs} فاتورة — فرصة رفع السلة.',
            message_en=f'🧺 {ctx.bn(b,"en")}: {ipi:.1f} items/invoice, avg {_fmt(atv)} EGP over {invs} invoices — basket-growth opportunity.'))
    return out


def rule_peak_hours(ctx, threshold):
    """Busiest sales hours chain-wide (staffing/coverage highlight). Uses trans_time."""
    from django.db.models.functions import ExtractHour
    from apps.customers.models import PurchaseHistory
    rows = (PurchaseHistory.objects.filter(
                invoice_date__date__gte=ctx.start, invoice_date__date__lte=ctx.end,
                doc_code='115', branch_id__in=ctx.branch_ids, sales_channel__in=ctx.nonexclude,
                trans_time__isnull=False)
            .annotate(h=ExtractHour('trans_time')).values('h').annotate(c=Count('id')))
    rows = [r for r in rows if r['h'] is not None and r['c']]
    if not rows:
        return []
    top = sorted(rows, key=lambda x: -x['c'])[:3]
    part = ' · '.join(f'{int(r["h"]):02d}:00 ({r["c"]})' for r in top)
    return [dict(rule_code='peak_hours', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(top[0]['c']), baseline=None, threshold=None,
        message_ar=f'⏰ أكثر ساعات البيع ازدحاماً ({ctx.label()}): {part} — تأكد من كفاية التغطية بها.',
        message_en=f'⏰ Busiest sales hours ({ctx.pw_en()}): {part} — make sure staffing covers them.')]


def rule_discount_to_one_customer(ctx, threshold):
    """A rep concentrating most of the discount they give onto a single customer (PIC) —
    kickback / abuse signal. Restricted to cash channels the rep actually controls."""
    thr = Decimal(str(threshold if threshold is not None else 40))
    from collections import defaultdict
    from apps.customers.models import PurchaseHistoryLine
    cash = ctx.walkin_delivery_channels + ctx.regular_channels
    if not cash:
        return []
    gross = ExpressionWrapper(F('list_price') * F('quantity'),
                              output_field=DecimalField(max_digits=18, decimal_places=4))
    rows = (PurchaseHistoryLine.objects.filter(
                purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
                purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
                purchase__sales_channel__in=cash, list_price__gt=0)
            .exclude(purchase__softech_user='')
            .values('purchase__softech_user', 'purchase__softech_phcode')
            .annotate(g=Sum(gross), n=Sum('line_total')))
    tot = defaultdict(Decimal); topd = defaultdict(Decimal); toppic = {}
    for r in rows:
        u = r['purchase__softech_user']; pic = (r['purchase__softech_phcode'] or '').strip()
        disc = Decimal(str(r['g'] or 0)) - Decimal(str(r['n'] or 0))
        if disc <= 0:
            continue
        tot[u] += disc
        if pic and disc > topd[u]:
            topd[u] = disc; toppic[u] = pic
    out = []
    for u, t in tot.items():
        if t < 5000 or u in ctx.cc_agents or u not in toppic:
            continue
        share = topd[u] / t * 100 if t else Decimal('0')
        if share >= thr:
            out.append(dict(rule_code='discount_to_one_customer', category='discount', severity='warning',
                scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
                value=Decimal(str(round(float(share), 1))), baseline=t, threshold=thr,
                message_ar=f'🎯🏷️ مسئول البيع {ctx.rep(u)}: {share:.0f}% من خصوماته لعميل واحد ({toppic[u]}) بقيمة {_fmt(topd[u])} من {_fmt(t)} ج.م.',
                message_en=f'🎯🏷️ Salesperson {ctx.rep(u)}: {share:.0f}% of discounts to one customer ({toppic[u]}) — {_fmt(topd[u])} of {_fmt(t)} EGP.'))
    return out


def rule_wash_sale(ctx, threshold):
    """Round-trip / wash sale: the same customer + item is both sold and largely returned
    within the period (inflate-then-reverse or return abuse). threshold = min returned
    share of the sold quantity (%)."""
    thr = Decimal(str(threshold if threshold is not None else 80))
    from apps.customers.models import PurchaseHistoryLine
    base = PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
        purchase__branch_id__in=ctx.branch_ids, item_id__isnull=False)

    def agg(doc):
        return (base.filter(purchase__doc_code=doc).exclude(purchase__softech_phcode='')
                .values('purchase__softech_phcode', 'item_id', 'purchase__softech_user')
                .annotate(q=Sum('quantity'), v=Sum('line_total')))
    sold = {}
    for r in agg('115'):
        sold[(r['purchase__softech_phcode'], r['item_id'])] = (
            abs(Decimal(str(r['q'] or 0))), abs(Decimal(str(r['v'] or 0))), r['purchase__softech_user'])
    hits = []
    for r in agg('30'):
        key = (r['purchase__softech_phcode'], r['item_id'])
        if key not in sold:
            continue
        sq, sv, user = sold[key]
        if sv < 2000 or sq <= 0:
            continue
        rq, rv = abs(Decimal(str(r['q'] or 0))), abs(Decimal(str(r['v'] or 0)))
        ratio = rq / sq * 100
        if ratio >= thr:
            hits.append((key, ratio, sv, rv, user))
    hits.sort(key=lambda x: -float(x[2]))
    out = []
    for (pic, iid), ratio, sv, rv, user in hits[:10]:
        nm = _item_name_by_id(iid)
        out.append(dict(rule_code='wash_sale', category='discount', severity='warning',
            scope_type='salesperson', scope_key=user or '', scope_label=f'مسئول البيع {ctx.rep(user)}',
            value=Decimal(str(round(float(ratio), 0))), baseline=sv, threshold=thr,
            message_ar=f'🔁 دورة بيع/إرجاع: «{nm}» للعميل {pic} — أُرجع {ratio:.0f}% مما بيع ({_fmt(rv)} من {_fmt(sv)} ج.م) بواسطة {ctx.rep(user)}.',
            message_en=f'🔁 Sale/return round-trip: “{nm}” for customer {pic} — {ratio:.0f}% of sold qty returned ({_fmt(rv)} of {_fmt(sv)} EGP) by {ctx.rep(user)}.'))
    return out


# ── Purchasing (procurement.PurchaseLine) ─────────────────────────────────────
_CAT_AR = {'OFFICIAL_DISTRIBUTOR': 'موزّع رسمي', 'MANUFACTURER': 'مصنع', 'SMALL_WAREHOUSE': 'مستودع صغير',
           'PATIENT_REPURCHASE': 'شراء من مريض', 'INTERNAL_TRANSFER': 'تحويل داخلي',
           'SERVICE_VENDOR': 'خدمات', 'UNKNOWN': 'غير مصنّف'}
_CAT_EN = {'OFFICIAL_DISTRIBUTOR': 'official distributor', 'MANUFACTURER': 'manufacturer',
           'SMALL_WAREHOUSE': 'small warehouse', 'PATIENT_REPURCHASE': 'patient/Rx exchange',
           'INTERNAL_TRANSFER': 'internal transfer', 'SERVICE_VENDOR': 'service', 'UNKNOWN': 'unknown'}


def _purchases(start, end):
    from apps.procurement.models import PurchaseLine
    return PurchaseLine.objects.filter(doc_date__gte=start, doc_date__lte=end)


def _item_name(code):
    """Catalog name for a softech item_code (falls back to the code). Cheap — called
    only for the handful of top offenders each purchasing rule surfaces."""
    from apps.catalog.models import Item
    return (Item.objects.filter(softech_id=str(code)).values_list('name', flat=True).first()
            or str(code))


def _item_name_by_id(iid):
    """Catalog name for a PK (falls back to the id). Only called for top offenders."""
    from apps.catalog.models import Item
    return Item.objects.filter(id=iid).values_list('name', flat=True).first() or str(iid)


def rule_hq_purchase_summary(ctx, threshold):
    """HQ purchasing headline: value + distinct item codes bought this period."""
    qs = _purchases(ctx.start, ctx.end).filter(branch_code=HQ_CODE, is_return=False)
    val = qs.aggregate(v=Sum('net_value'))['v'] or 0
    if val <= 0:
        return []
    items = qs.values('item_code').distinct().count()
    return [dict(rule_code='hq_purchase_summary', category='highlight', severity='info',
        scope_type='branch', scope_key=HQ_CODE, scope_label='المخزن الرئيسي',
        value=Decimal(str(val)), baseline=None, threshold=None,
        message_ar=f'🏭 مشتريات المخزن الرئيسي: {_fmt(val)} ج.م على {items} صنف خلال ال{ctx.label()}.',
        message_en=f'🏭 HQ purchases: {_fmt(val)} EGP across {items} distinct items this {ctx.pw_en()}.')]


def rule_purchase_category_mix(ctx, threshold):
    """Purchasing split by supplier category + flag over-reliance on small warehouses."""
    thr = Decimal(str(threshold if threshold is not None else 30))
    rows = dict(_purchases(ctx.start, ctx.end).filter(is_return=False)
                .values_list('supplier_category').annotate(v=Sum('net_value')))
    total = sum(Decimal(str(v or 0)) for v in rows.values())
    if total <= 0:
        return []
    order = sorted(rows.items(), key=lambda x: -(x[1] or 0))
    pa = [f'{_CAT_AR.get(c, c)} {Decimal(str(v or 0))/total*100:.0f}%' for c, v in order[:5] if v]
    pe = [f'{_CAT_EN.get(c, c)} {Decimal(str(v or 0))/total*100:.0f}%' for c, v in order[:5] if v]
    out = [dict(rule_code='purchase_category_mix', category='comparison', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=total, baseline=None, threshold=None,
        message_ar='🧾 توزيع المشتريات حسب المصدر: ' + ' · '.join(pa) + '.',
        message_en='🧾 Purchases by source: ' + ' · '.join(pe) + '.')]
    sw = Decimal(str(rows.get('SMALL_WAREHOUSE', 0) or 0)) / total * 100
    if sw >= thr:
        out.append(dict(rule_code='purchase_category_mix', category='discount', severity='warning',
            scope_type='chain', scope_key='', scope_label='', value=Decimal(str(round(float(sw), 1))),
            baseline=None, threshold=thr,
            message_ar=f'⚠️ اعتماد مرتفع على المستودعات الصغيرة: {sw:.0f}% من المشتريات (الحد {thr:.0f}%) — تكلفة أعلى غالباً.',
            message_en=f'⚠️ High small-warehouse reliance: {sw:.0f}% of purchases (cap {thr:.0f}%) — usually costlier.'))
    return out


def rule_supplier_return_spike(ctx, threshold):
    """Large return-to-supplier value in the period (top suppliers)."""
    thr = Decimal(str(threshold if threshold is not None else 20000))
    rows = (_purchases(ctx.start, ctx.end).filter(is_return=True)
            .values('supplier_code', 'supplier_category')
            .annotate(v=Sum('raw_value')).order_by('-v')[:5])
    out = []
    for r in rows:
        v = abs(float(r['v'] or 0))
        if Decimal(str(v)) >= thr:
            cat_ar = _CAT_AR.get(r['supplier_category'], ''); cat_en = _CAT_EN.get(r['supplier_category'], '')
            out.append(dict(rule_code='supplier_return_spike', category='discount', severity='warning',
                scope_type='product', scope_key=r['supplier_code'], scope_label=r['supplier_code'],
                value=Decimal(str(round(v, 2))), baseline=None, threshold=thr,
                message_ar=f'📦↩️ مرتجعات لمورد ({cat_ar}) بقيمة {_fmt(v)} ج.م خلال ال{ctx.label()}.',
                message_en=f'📦↩️ Returns to a supplier ({cat_en}) worth {_fmt(v)} EGP this {ctx.pw_en()}.'))
    return out


def rule_hq_purchase_trend(ctx, threshold):
    """HQ purchasing value + distinct items vs the previous equal period (trend)."""
    thr = Decimal(str(threshold if threshold is not None else 20))
    def snap(s, e):
        qs = _purchases(s, e).filter(branch_code=HQ_CODE, is_return=False)
        return (Decimal(str(qs.aggregate(v=Sum('net_value'))['v'] or 0)),
                qs.values('item_code').distinct().count())
    cv, ci = snap(ctx.start, ctx.end)
    pv, pi = snap(ctx.prev_start, ctx.prev_end)
    if cv <= 0 or pv <= 0:
        return []
    d = (cv - pv) / pv * 100
    arrow = '▲' if d >= 0 else '▼'
    return [dict(rule_code='hq_purchase_trend', category='comparison', severity='info',
        scope_type='branch', scope_key=HQ_CODE, scope_label='المخزن الرئيسي',
        value=cv, baseline=pv, threshold=thr,
        message_ar=f'🏭 مشتريات المخزن الرئيسي: {_fmt(cv)} ج.م على {ci} صنف ({arrow}{abs(float(d)):.0f}% عن السابق: {_fmt(pv)} ج.م / {pi} صنف).',
        message_en=f'🏭 HQ purchases: {_fmt(cv)} EGP over {ci} items ({arrow}{abs(float(d)):.0f}% vs prev: {_fmt(pv)} EGP / {pi} items).')]


def rule_purchase_price_creep(ctx, threshold):
    """Items whose HQ effective unit cost rose ≥ threshold% vs the previous period
    (supplier price creep). FOC lines excluded so free goods don't distort cost."""
    thr = Decimal(str(threshold if threshold is not None else 10))
    def unit_cost(s, e):
        rows = (_purchases(s, e).filter(branch_code=HQ_CODE, is_return=False, is_foc=False)
                .values('item_code').annotate(v=Sum('net_value'), q=Sum('net_qty')))
        return {r['item_code']: (Decimal(str(r['v'] or 0)), Decimal(str(r['q'] or 0)))
                for r in rows if (r['q'] or 0) > 0 and (r['v'] or 0) > 0}
    cur, prev = unit_cost(ctx.start, ctx.end), unit_cost(ctx.prev_start, ctx.prev_end)
    hits = []
    for code, (cv, cq) in cur.items():
        if code not in prev:
            continue
        pv, pq = prev[code]
        cu, pu = cv / cq, pv / pq
        if pu <= 0 or cv < 5000:                 # need prior price + meaningful current spend
            continue
        rise = (cu - pu) / pu * 100
        if rise >= thr:
            hits.append((code, rise, cu, pu, cv))
    hits.sort(key=lambda x: -x[1])
    out = []
    for code, rise, cu, pu, cv in hits[:8]:
        nm = _item_name(code)
        out.append(dict(rule_code='purchase_price_creep', category='discount', severity='warning',
            scope_type='product', scope_key=str(code), scope_label=nm,
            value=Decimal(str(round(float(rise), 1))), baseline=Decimal(str(round(float(pu), 2))), threshold=thr,
            message_ar=f'📈 ارتفاع سعر شراء «{nm}» بنسبة {rise:.0f}% ({_fmt(pu)}→{_fmt(cu)} ج.م/وحدة) على مشتريات {_fmt(cv)} ج.م.',
            message_en=f'📈 Purchase price of “{nm}” up {rise:.0f}% ({_fmt(pu)}→{_fmt(cu)} EGP/unit) on {_fmt(cv)} EGP bought.'))
    return out


def rule_purchase_thin_margin(ctx, threshold):
    """HQ-bought items whose value-weighted margin (public vs cost) is below the floor —
    they'll sell at a thin/negative margin. Highest-spend offenders first."""
    thr = Decimal(str(threshold if threshold is not None else 8))
    wm = ExpressionWrapper(F('margin_pct') * F('net_value'),
                           output_field=DecimalField(max_digits=22, decimal_places=4))
    rows = (_purchases(ctx.start, ctx.end)
            .filter(branch_code=HQ_CODE, is_return=False, is_foc=False, margin_pct__isnull=False, net_value__gt=0)
            .values('item_code').annotate(v=Sum('net_value'), mw=Sum(wm)))
    hits = []
    for r in rows:
        v = Decimal(str(r['v'] or 0))
        if v < 5000:
            continue
        m = Decimal(str(r['mw'] or 0)) / v if v else Decimal('0')
        if m < thr:
            hits.append((r['item_code'], m, v))
    hits.sort(key=lambda x: -x[2])
    out = []
    for code, m, v in hits[:8]:
        nm = _item_name(code)
        out.append(dict(rule_code='purchase_thin_margin', category='discount', severity='warning',
            scope_type='product', scope_key=str(code), scope_label=nm,
            value=Decimal(str(round(float(m), 1))), baseline=None, threshold=thr,
            message_ar=f'📉 هامش شراء ضعيف على «{nm}»: {m:.0f}% (الحد {thr:.0f}%) على مشتريات {_fmt(v)} ج.م.',
            message_en=f'📉 Thin buying margin on “{nm}”: {m:.0f}% (floor {thr:.0f}%) on {_fmt(v)} EGP bought.'))
    return out


def rule_buyer_small_warehouse(ctx, threshold):
    """A buyer (مسئول شراء) sourcing too much from small warehouses (usually costlier)."""
    thr = Decimal(str(threshold if threshold is not None else 30))
    sw_val = Case(When(supplier_category='SMALL_WAREHOUSE', then=F('net_value')),
                  default=Value(0), output_field=DecimalField(max_digits=18, decimal_places=4))
    rows = (_purchases(ctx.start, ctx.end).filter(branch_code=HQ_CODE, is_return=False)
            .exclude(buyer_code='').values('buyer_code')
            .annotate(tot=Sum('net_value'), sw=Sum(sw_val)))
    out = []
    for r in rows:
        tot = Decimal(str(r['tot'] or 0)); sw = Decimal(str(r['sw'] or 0))
        if tot < 20000 or sw <= 0:
            continue
        share = sw / tot * 100
        if share >= thr:
            b = ctx.rep(r['buyer_code'])
            out.append(dict(rule_code='buyer_small_warehouse', category='comparison', severity='warning',
                scope_type='salesperson', scope_key=r['buyer_code'], scope_label=f'مشتريات {b}',
                value=Decimal(str(round(float(share), 1))), baseline=tot, threshold=thr,
                message_ar=f'🏬 مسئول الشراء {b}: {share:.0f}% من مشترياته من مستودعات صغيرة ({_fmt(sw)} من {_fmt(tot)} ج.م) — الحد {thr:.0f}%.',
                message_en=f'🏬 Buyer {b}: {share:.0f}% of purchases from small warehouses ({_fmt(sw)} of {_fmt(tot)} EGP) — cap {thr:.0f}%.'))
    return out


def rule_supplier_concentration(ctx, threshold):
    """One supplier taking ≥ threshold% of HQ spend (dependency / negotiation risk)."""
    thr = Decimal(str(threshold if threshold is not None else 35))
    rows = dict(_purchases(ctx.start, ctx.end).filter(branch_code=HQ_CODE, is_return=False)
                .exclude(supplier_code='').values_list('supplier_code').annotate(v=Sum('net_value')))
    total = sum(Decimal(str(v or 0)) for v in rows.values())
    if total <= 0:
        return []
    top, tv = max(rows.items(), key=lambda x: (x[1] or 0))
    share = Decimal(str(tv or 0)) / total * 100
    if share < thr:
        return []
    return [dict(rule_code='supplier_concentration', category='comparison', severity='warning',
        scope_type='product', scope_key=top, scope_label=top,
        value=Decimal(str(round(float(share), 1))), baseline=total, threshold=thr,
        message_ar=f'🔗 تركّز الموردين: مورد واحد ({top}) يمثل {share:.0f}% من مشتريات المخزن الرئيسي ({_fmt(tv)} من {_fmt(total)} ج.م).',
        message_en=f'🔗 Supplier concentration: one supplier ({top}) = {share:.0f}% of HQ purchases ({_fmt(tv)} of {_fmt(total)} EGP).')]


def rule_foc_captured(ctx, threshold):
    """Positive: value of free-of-charge / bonus goods negotiated into HQ purchases."""
    cost = ExpressionWrapper(F('cost_price') * F('raw_qty'),
                             output_field=DecimalField(max_digits=20, decimal_places=4))
    qs = _purchases(ctx.start, ctx.end).filter(branch_code=HQ_CODE, is_foc=True)
    agg = qs.aggregate(n=Count('id'), q=Sum('raw_qty'), val=Sum(cost))
    val = Decimal(str(agg['val'] or 0))
    if (agg['n'] or 0) == 0 or val <= 0:
        return []
    units = float(agg['q'] or 0)
    return [dict(rule_code='foc_captured', category='highlight', severity='info',
        scope_type='branch', scope_key=HQ_CODE, scope_label='المخزن الرئيسي',
        value=val, baseline=None, threshold=None,
        message_ar=f'🎁 بضائع مجانية/بونص مُحصّلة: ~{units:,.0f} وحدة بقيمة ~{_fmt(val)} ج.م (تكلفة) خلال ال{ctx.label()}.',
        message_en=f'🎁 Free/bonus goods captured: ~{units:,.0f} units worth ~{_fmt(val)} EGP (cost) this {ctx.pw_en()}.')]


# ── Purchasing at the BRANCHES (local buying, not via HQ) ──────────────────────

def rule_branch_local_purchase(ctx, threshold):
    """Branches buying locally (not through HQ) — value + distinct items. Local buying
    is usually costlier than central distribution, so it's worth watching."""
    thr = Decimal(str(threshold if threshold is not None else 10000))
    rows = (_purchases(ctx.start, ctx.end).filter(is_return=False)
            .exclude(branch_code=HQ_CODE).exclude(branch_code='')
            .values('branch_code').annotate(v=Sum('net_value'), items=Count('item_code', distinct=True))
            .order_by('-v'))
    out = []
    for r in rows:
        v = Decimal(str(r['v'] or 0))
        if v < thr:
            continue
        b = ctx.branch_by_code.get(str(r['branch_code']))
        nm = (b.name_ar or b.name) if b else str(r['branch_code'])
        ne = (b.name or b.name_ar) if b else str(r['branch_code'])
        out.append(dict(rule_code='branch_local_purchase', category='comparison', severity='info',
            scope_type='branch', scope_key=str(r['branch_code']), scope_label=nm,
            value=v, baseline=None, threshold=thr,
            message_ar=f'🛒 {nm}: مشتريات محلية {_fmt(v)} ج.م على {r["items"]} صنف خلال ال{ctx.label()}.',
            message_en=f'🛒 {ne}: local purchases {_fmt(v)} EGP over {r["items"]} items this {ctx.pw_en()}.'))
    return out


def rule_branch_small_warehouse(ctx, threshold):
    """A branch sourcing too much of its local buying from small warehouses (costlier)."""
    thr = Decimal(str(threshold if threshold is not None else 40))
    sw_val = Case(When(supplier_category='SMALL_WAREHOUSE', then=F('net_value')),
                  default=Value(0), output_field=DecimalField(max_digits=18, decimal_places=4))
    rows = (_purchases(ctx.start, ctx.end).filter(is_return=False)
            .exclude(branch_code=HQ_CODE).exclude(branch_code='')
            .values('branch_code').annotate(tot=Sum('net_value'), sw=Sum(sw_val)))
    out = []
    for r in rows:
        tot = Decimal(str(r['tot'] or 0)); sw = Decimal(str(r['sw'] or 0))
        if tot < 5000 or sw <= 0:
            continue
        share = sw / tot * 100
        if share >= thr:
            b = ctx.branch_by_code.get(str(r['branch_code']))
            nm = (b.name_ar or b.name) if b else str(r['branch_code'])
            ne = (b.name or b.name_ar) if b else str(r['branch_code'])
            out.append(dict(rule_code='branch_small_warehouse', category='comparison', severity='warning',
                scope_type='branch', scope_key=str(r['branch_code']), scope_label=nm,
                value=Decimal(str(round(float(share), 1))), baseline=tot, threshold=thr,
                message_ar=f'🏬 {nm}: {share:.0f}% من مشترياته المحلية من مستودعات صغيرة ({_fmt(sw)} من {_fmt(tot)} ج.م).',
                message_en=f'🏬 {ne}: {share:.0f}% of local buying from small warehouses ({_fmt(sw)} of {_fmt(tot)} EGP).'))
    return out


def rule_patient_repurchase_volume(ctx, threshold):
    """شراء من مريض / Rx-exchange volume per branch (governance — buying stock back from patients)."""
    thr = Decimal(str(threshold if threshold is not None else 5000))
    rows = (_purchases(ctx.start, ctx.end)
            .filter(is_return=False, supplier_category='PATIENT_REPURCHASE')
            .values('branch_code').annotate(v=Sum('net_value'), n=Count('id')).order_by('-v'))
    out = []
    for r in rows:
        v = Decimal(str(r['v'] or 0))
        if v < thr:
            continue
        code = str(r['branch_code'])
        b = ctx.branch_by_code.get(code)
        nm = (b.name_ar or b.name) if b else (code or 'المخزن الرئيسي' if code == HQ_CODE else code)
        ne = (b.name or b.name_ar) if b else code
        out.append(dict(rule_code='patient_repurchase_volume', category='comparison', severity='info',
            scope_type='branch', scope_key=code, scope_label=nm,
            value=v, baseline=None, threshold=thr,
            message_ar=f'👥 {nm}: شراء من مرضى/تبادل روشتات بقيمة {_fmt(v)} ج.م ({r["n"]} عملية) خلال ال{ctx.label()}.',
            message_en=f'👥 {ne}: patient/Rx-exchange buying {_fmt(v)} EGP ({r["n"]} ops) this {ctx.pw_en()}.'))
    return out


def rule_buy_vs_sell_imbalance(ctx, threshold):
    """Items bought into HQ in significant value but barely sold chain-wide in the same
    period — overstock / tied-up capital. threshold = max sell-through (% of buy value)."""
    thr = Decimal(str(threshold if threshold is not None else 10))
    bought = dict(_purchases(ctx.start, ctx.end)
                  .filter(branch_code=HQ_CODE, is_return=False, net_value__gt=0)
                  .values_list('item_code').annotate(v=Sum('net_value')))
    bought = {c: Decimal(str(v or 0)) for c, v in bought.items() if Decimal(str(v or 0)) >= 20000}
    if not bought:
        return []
    from apps.catalog.models import Item
    from apps.customers.models import PurchaseHistoryLine
    id_by_code = dict(Item.objects.filter(softech_id__in=list(bought)).values_list('softech_id', 'id'))
    sold_by_id = dict(PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
        purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
        item_id__in=list(id_by_code.values()))
        .values_list('item_id').annotate(v=Sum('line_total')))
    hits = []
    for code, bv in bought.items():
        sv = Decimal(str(sold_by_id.get(id_by_code.get(code), 0) or 0))
        if sv < bv * thr / 100:
            hits.append((code, bv, sv))
    hits.sort(key=lambda x: -x[1])
    out = []
    for code, bv, sv in hits[:8]:
        nm = _item_name(code)
        st = (sv / bv * 100) if bv else Decimal('0')
        out.append(dict(rule_code='buy_vs_sell_imbalance', category='volume', severity='warning',
            scope_type='product', scope_key=str(code), scope_label=nm,
            value=bv, baseline=sv, threshold=thr,
            message_ar=f'📦⚖️ «{nm}»: مشتريات {_fmt(bv)} ج.م مقابل مبيعات {_fmt(sv)} فقط ({st:.0f}%) خلال ال{ctx.label()} — مخزون زائد.',
            message_en=f'📦⚖️ “{nm}”: bought {_fmt(bv)} EGP vs only {_fmt(sv)} sold ({st:.0f}%) this {ctx.pw_en()} — overstock.'))
    return out


# ── Purchasing STUDY: descriptive analytics (values, distributions, rankings) ─
# General item-category (medicine_type) labels — the DB *_ar field holds English.
_GENCAT_AR = {'50': 'مستحضرات تجميل', '10': 'أدوية', '20': 'أخرى', '30': 'مكملات غذائية',
              '40': 'بيطري', '60': 'هدايا عملاء', '70': 'خدمات', '00': 'غير مصنّف', '': 'غير مصنّف'}
_GENCAT_EN = {'50': 'Cosmetics', '10': 'Medicine', '20': 'Others', '30': 'Body Building',
              '40': 'Veterinary', '60': 'Client gifts', '70': 'Services', '00': 'Unclassified', '': 'Unclassified'}


def _supplier_names(codes):
    from apps.procurement.models import SupplierProfile
    return {c: (n or c) for c, n in
            SupplierProfile.objects.filter(supplier_code__in=list(codes))
            .values_list('supplier_code', 'supplier_name')}


def rule_purchase_overview(ctx, threshold):
    """Chain-wide purchasing headline: net purchase value (HQ + branches split), distinct
    items, distinct suppliers, returns value + rate, free/bonus value, and trend vs prev."""
    from django.db.models import Count as _C
    cost_foc = ExpressionWrapper(F('cost_price') * F('raw_qty'),
                                 output_field=DecimalField(max_digits=20, decimal_places=4))

    def net(s, e, branch=None):
        q = _purchases(s, e).filter(is_return=False)
        if branch == 'hq':
            q = q.filter(branch_code=HQ_CODE)
        elif branch == 'branches':
            q = q.exclude(branch_code=HQ_CODE)
        return Decimal(str(q.aggregate(v=Sum('net_value'))['v'] or 0))
    cur = net(ctx.start, ctx.end)
    if cur <= 0:
        return []
    hq = net(ctx.start, ctx.end, 'hq'); br = net(ctx.start, ctx.end, 'branches')
    prev = net(ctx.prev_start, ctx.prev_end)
    d = ((cur - prev) / prev * 100) if prev else Decimal('0')
    arrow = '▲' if d >= 0 else '▼'
    buy = _purchases(ctx.start, ctx.end).filter(is_return=False)
    items = buy.values('item_code').distinct().count()
    suppliers = buy.exclude(supplier_code='').values('supplier_code').distinct().count()
    ret_val = abs(Decimal(str(_purchases(ctx.start, ctx.end).filter(is_return=True)
                             .aggregate(v=Sum('raw_value'))['v'] or 0)))
    rate = ret_val / (cur + ret_val) * 100 if (cur + ret_val) else Decimal('0')
    foc = Decimal(str(buy.filter(is_foc=True).aggregate(v=Sum(cost_foc))['v'] or 0))
    return [dict(rule_code='purchase_overview', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=cur, baseline=prev, threshold=None,
        message_ar=(f'🧮 إجمالى المشتريات ({ctx.label()}): صافي {_fmt(cur)} ج.م '
                    f'(مركزي {_fmt(hq)} + فروع {_fmt(br)}) على {items} صنف من {suppliers} مورد '
                    f'({arrow}{abs(float(d)):.0f}% عن السابق) — مرتجعات {_fmt(ret_val)} ({rate:.0f}%)، بضائع مجانية ~{_fmt(foc)} ج.م.'),
        message_en=(f'🧮 Total purchases ({ctx.pw_en()}): net {_fmt(cur)} EGP '
                    f'(HQ {_fmt(hq)} + branches {_fmt(br)}) over {items} items from {suppliers} suppliers '
                    f'({arrow}{abs(float(d)):.0f}% vs prev) — returns {_fmt(ret_val)} ({rate:.0f}%), free goods ~{_fmt(foc)} EGP.'))]


def rule_purchase_general_category(ctx, threshold):
    """Purchase value split by general item category (medicine / cosmetics / others …)."""
    rows = (_purchases(ctx.start, ctx.end).filter(is_return=False, net_value__gt=0)
            .values('item__medicine_type').annotate(v=Sum('net_value')))
    agg = {}
    for r in rows:
        code = r['item__medicine_type'] or ''
        agg[code] = agg.get(code, Decimal('0')) + Decimal(str(r['v'] or 0))
    if not agg:
        return []
    order = sorted(agg.items(), key=lambda x: -x[1])
    total = sum(agg.values())
    pa = ' · '.join(f'{_GENCAT_AR.get(c, c)} {_fmt(v)} ({v/total*100:.0f}%)' for c, v in order[:6] if v)
    pe = ' · '.join(f'{_GENCAT_EN.get(c, c)} {_fmt(v)} ({v/total*100:.0f}%)' for c, v in order[:6] if v)
    return [dict(rule_code='purchase_general_category', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=total, baseline=None, threshold=None,
        message_ar=f'🧴 توزيع المشتريات حسب فئة الصنف ({ctx.label()}): {pa}.',
        message_en=f'🧴 Purchases by item category ({ctx.pw_en()}): {pe}.')]


def rule_rank_suppliers(ctx, threshold):
    """Top suppliers by net purchase value (with supplier category)."""
    rows = (_purchases(ctx.start, ctx.end).filter(is_return=False, net_value__gt=0)
            .exclude(supplier_code='')
            .values('supplier_code', 'supplier_category').annotate(v=Sum('net_value')).order_by('-v')[:5])
    rows = [r for r in rows if r['v']]
    if not rows:
        return []
    names = _supplier_names([r['supplier_code'] for r in rows])
    def lbl(r):
        cat = _CAT_AR.get(r['supplier_category'], '')
        nm = names.get(r['supplier_code'], r['supplier_code'])
        return f'{nm}{f" ({cat})" if cat else ""}'
    ar = ' · '.join(f'{i+1}) {lbl(r)} {_fmt(r["v"])}' for i, r in enumerate(rows))
    en = ' · '.join(f'{i+1}) {names.get(r["supplier_code"], r["supplier_code"])} {_fmt(r["v"])}' for i, r in enumerate(rows))
    return [dict(rule_code='rank_suppliers', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(str(rows[0]['v'])), baseline=None, threshold=None,
        message_ar=f'🏭 أكبر الموردين قيمةً ({ctx.label()}): {ar} ج.م.',
        message_en=f'🏭 Top suppliers by value ({ctx.pw_en()}): {en} EGP.')]


def rule_rank_purchased_items(ctx, threshold):
    """Top items by net purchase value."""
    rows = (_purchases(ctx.start, ctx.end).filter(is_return=False, net_value__gt=0)
            .values('item_code').annotate(v=Sum('net_value')).order_by('-v')[:5])
    rows = [r for r in rows if r['v']]
    if not rows:
        return []
    ar = ' · '.join(f'{i+1}) «{_item_name(r["item_code"])}» {_fmt(r["v"])}' for i, r in enumerate(rows))
    en = ' · '.join(f'{i+1}) “{_item_name(r["item_code"])}” {_fmt(r["v"])}' for i, r in enumerate(rows))
    return [dict(rule_code='rank_purchased_items', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(str(rows[0]['v'])), baseline=None, threshold=None,
        message_ar=f'📦 أكثر الأصناف شراءً قيمةً ({ctx.label()}): {ar} ج.م.',
        message_en=f'📦 Top purchased items by value ({ctx.pw_en()}): {en} EGP.')]


def rule_branch_purchase_profile(ctx, threshold):
    """PER-BRANCH purchasing section (for the فرع scope): each branch's purchase value,
    distinct items, category mix and its top suppliers. HQ (المخزن الرئيسي) included."""
    from collections import defaultdict
    from apps.branches.models import Branch
    thr = Decimal(str(threshold if threshold is not None else 5000))
    buy = _purchases(ctx.start, ctx.end).filter(is_return=False, net_value__gt=0).exclude(branch_code='')
    val_rows = buy.values('branch_code').annotate(v=Sum('net_value'), items=Count('item_code', distinct=True))
    cat = defaultdict(lambda: defaultdict(Decimal))
    for r in buy.values('branch_code', 'item__medicine_type').annotate(v=Sum('net_value')):
        cat[r['branch_code']][r['item__medicine_type'] or ''] += Decimal(str(r['v'] or 0))
    sup = defaultdict(list)
    for r in buy.exclude(supplier_code='').values('branch_code', 'supplier_code').annotate(v=Sum('net_value')):
        sup[r['branch_code']].append((r['supplier_code'], Decimal(str(r['v'] or 0))))
    names = _supplier_names({c for lst in sup.values() for c, _ in lst})
    bmap = {b.code or b.softech_branch_id: b for b in Branch.objects.all()}
    HQ = 'المخزن الرئيسي'
    out = []
    for r in val_rows:
        code = str(r['branch_code']); v = Decimal(str(r['v'] or 0))
        if v < thr:
            continue
        b = bmap.get(code)
        nm = (b.name_ar or b.name) if b else (HQ if code == HQ_CODE else code)
        ne = (b.name or b.name_ar) if b else (HQ if code == HQ_CODE else code)
        tot = sum(cat[code].values()) or Decimal('1')
        cs = sorted(cat[code].items(), key=lambda x: -x[1])[:4]
        pa = ' · '.join(f'{_GENCAT_AR.get(c, c)} {x/tot*100:.0f}%' for c, x in cs)
        pe = ' · '.join(f'{_GENCAT_EN.get(c, c)} {x/tot*100:.0f}%' for c, x in cs)
        out.append(dict(rule_code='branch_purchase_profile', category='comparison', severity='info',
            scope_type='branch', scope_key=code, scope_label=nm, value=v, baseline=None, threshold=None,
            message_ar=f'🧮 مشتريات {nm} ({ctx.label()}): صافي {_fmt(v)} ج.م على {r["items"]} صنف — {pa}.',
            message_en=f'🧮 {ne} purchases ({ctx.pw_en()}): net {_fmt(v)} EGP over {r["items"]} items — {pe}.'))
        tops = sorted(sup[code], key=lambda x: -x[1])[:3]
        if tops:
            sa = ' · '.join(f'{names.get(sc, sc)} {_fmt(sv)}' for sc, sv in tops)
            out.append(dict(rule_code='branch_purchase_profile', category='comparison', severity='info',
                scope_type='branch', scope_key=code, scope_label=nm, value=tops[0][1], baseline=None, threshold=None,
                message_ar=f'🏭 أكبر موردي {nm}: {sa} ج.م.',
                message_en=f'🏭 {ne} top suppliers: {sa} EGP.'))
    return out


def rule_supplier_scorecard(ctx, threshold):
    """Supplier SCORECARD from SupplierProfile intelligence: best suppliers by overall score
    (with return% / bonus% / margin% / service%), plus a watch-list of high-return suppliers.
    threshold = return% that puts a supplier on the watch-list."""
    thr = Decimal(str(threshold if threshold is not None else 10))
    from apps.procurement.models import SupplierProfile
    qs = list(SupplierProfile.objects.filter(net_purchase_value__gte=20000))
    if not qs:
        return []
    fp = lambda x: float(x or 0)
    out = []
    best = sorted(qs, key=lambda s: -fp(s.total_score))[:5]
    ar = ' · '.join(
        f'{i+1}) {s.supplier_name or s.supplier_code} ({fp(s.total_score):.0f}: مرتجع {fp(s.return_pct):.0f}% · بونص {fp(s.foc_rate_pct):.0f}% · هامش {fp(s.avg_margin_pct):.0f}% · خدمة {fp(s.service_level_pct):.0f}%)'
        for i, s in enumerate(best))
    en = ' · '.join(
        f'{i+1}) {s.supplier_name or s.supplier_code} ({fp(s.total_score):.0f}: ret {fp(s.return_pct):.0f}% · bonus {fp(s.foc_rate_pct):.0f}% · margin {fp(s.avg_margin_pct):.0f}% · service {fp(s.service_level_pct):.0f}%)'
        for i, s in enumerate(best))
    out.append(dict(rule_code='supplier_scorecard', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(str(round(fp(best[0].total_score), 1))),
        baseline=None, threshold=None,
        message_ar=f'🏅 تقييم الموردين (الأعلى أداءً): {ar}.',
        message_en=f'🏅 Supplier scorecard (top performers): {en}.'))
    watch = sorted([s for s in qs if fp(s.return_pct) >= float(thr)], key=lambda s: -fp(s.return_pct))[:5]
    for s in watch:
        out.append(dict(rule_code='supplier_scorecard', category='discount', severity='warning',
            scope_type='product', scope_key=s.supplier_code, scope_label=s.supplier_name or s.supplier_code,
            value=Decimal(str(round(fp(s.return_pct), 1))), baseline=Decimal(str(s.net_purchase_value or 0)), threshold=thr,
            message_ar=f'⚠️ مورد للمتابعة: {s.supplier_name or s.supplier_code} — نسبة مرتجعات {fp(s.return_pct):.0f}% · خدمة {fp(s.service_level_pct):.0f}% على مشتريات {_fmt(s.net_purchase_value)} ج.م.',
            message_en=f'⚠️ Supplier to watch: {s.supplier_name or s.supplier_code} — returns {fp(s.return_pct):.0f}% · service {fp(s.service_level_pct):.0f}% on {_fmt(s.net_purchase_value)} EGP.'))
    return out


# ── Optimization & diagnosis (purchasing & replenishment domain) ──────────────

def rule_transfer_matcher(ctx, threshold):
    """Overstock↔stockout: an item DEAD at one branch but STOCKED-OUT (fast-mover) at another
    → suggest an inter-branch transfer that frees capital and saves lost sales."""
    from collections import defaultdict
    from apps.catalog.models import ItemStock
    thr = float(threshold if threshold is not None else 5)   # monthly velocity at the stocked-out branch
    dead = defaultdict(list)
    # source = has stock but barely moving there (spare); target = stocked-out & selling fast
    for r in ItemStock.objects.filter(branch_id__in=ctx.branch_ids, quantity_on_hand__gt=0, monthly_qty__lte=2).values(
            'item_id', 'branch_id', 'quantity_on_hand', 'item__cost_price'):
        dead[r['item_id']].append((r['branch_id'], float(r['quantity_on_hand'] or 0),
                                   Decimal(str((r['quantity_on_hand'] or 0) * (r['item__cost_price'] or 0)))))
    if not dead:
        return []
    short = defaultdict(list)
    for r in ItemStock.objects.filter(branch_id__in=ctx.branch_ids, quantity_on_hand__lte=0, monthly_qty__gte=thr).values('item_id', 'branch_id'):
        short[r['item_id']].append(r['branch_id'])
    opps = [(iid, dl, short[iid], sum(v for _, _, v in dl)) for iid, dl in dead.items() if iid in short]
    opps.sort(key=lambda x: -x[3])
    bmap = _branch_map(ctx)
    bn = lambda bid: ctx.bn(bmap[bid], 'ar') if bid in bmap else str(bid)
    bne = lambda bid: ctx.bn(bmap[bid], 'en') if bid in bmap else str(bid)
    out = []
    for iid, dl, shorts, val in opps[:8]:
        nm = _item_name_by_id(iid); db = max(dl, key=lambda x: x[2])
        out.append(dict(rule_code='transfer_matcher', category='volume', severity='warning',
            scope_type='product', scope_key=str(iid), scope_label=nm, value=val, baseline=None, threshold=None,
            message_ar=f'🔄 نقل مقترح: «{nm}» راكد في {bn(db[0])} ({db[1]:.0f} وحدة ~{_fmt(val)} ج.م) ونافد في {bn(shorts[0])} — انقله لتفادي مبيعات ضائعة.',
            message_en=f'🔄 Transfer idea: “{nm}” dead at {bne(db[0])} ({db[1]:.0f} units ~{_fmt(val)} EGP) but stocked-out at {bne(shorts[0])} — move it to avoid lost sales.'))
    return out


def rule_margin_leakage(ctx, threshold):
    """Per-branch margin-leakage waterfall: profit lost to discounts + below-cost sales +
    returns. threshold = min total leakage (EGP) to report a branch."""
    thr = Decimal(str(threshold if threshold is not None else 20000))
    from apps.customers.models import PurchaseHistoryLine
    gross = ExpressionWrapper(F('list_price') * F('quantity'), output_field=DecimalField(max_digits=18, decimal_places=4))
    disc = {}
    for r in (PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
            purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
            purchase__sales_channel__in=(ctx.walkin_channels + ctx.regular_channels), list_price__gt=0)
            .values('purchase__branch_id').annotate(g=Sum(gross), n=Sum('line_total'))):
        disc[r['purchase__branch_id']] = max(Decimal('0'), Decimal(str(r['g'] or 0)) - Decimal(str(r['n'] or 0)))
    loss = {}
    for r in (PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
            purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids, purchase__sales_channel__in=ctx.nonexclude)
            .annotate(p=_PROFIT).filter(p__lt=0).values('purchase__branch_id').annotate(l=Sum('p'))):
        loss[r['purchase__branch_id']] = abs(Decimal(str(r['l'] or 0)))
    _, ret = _sales_ret_by_branch(ctx, ctx.start, ctx.end)
    bmap = _branch_map(ctx)
    out = []
    for b in ctx.branches:
        d = disc.get(b.id, Decimal('0')); lo = loss.get(b.id, Decimal('0')); rt = Decimal(str(ret.get(b.id, 0) or 0))
        total = d + lo + rt
        if total >= thr:
            out.append(dict(rule_code='margin_leakage', category='discount', severity='warning',
                scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'), value=total, baseline=None, threshold=thr,
                message_ar=f'💸 تسرب الهامش في {ctx.bn(b,"ar")} ({ctx.label()}): خصومات {_fmt(d)} · بيع تحت التكلفة {_fmt(lo)} · مرتجعات {_fmt(rt)} = إجمالى {_fmt(total)} ج.م.',
                message_en=f'💸 Margin leakage at {ctx.bn(b,"en")} ({ctx.pw_en()}): discounts {_fmt(d)} · below-cost {_fmt(lo)} · returns {_fmt(rt)} = {_fmt(total)} EGP total.'))
    return out


def rule_price_inconsistency(ctx, threshold):
    """Same item sold at very different unit prices across branches (uncontrolled discounting
    / pricing errors). threshold = min spread % (max vs min) to flag."""
    thr = Decimal(str(threshold if threshold is not None else 25))
    from collections import defaultdict
    from apps.customers.models import PurchaseHistoryLine
    by_item = defaultdict(list)
    for r in (PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
            purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids, purchase__sales_channel__in=ctx.nonexclude,
            quantity__gt=0, line_total__gt=0, item_id__isnull=False)
            .exclude(item_id__in=ctx.excluded_item_ids)
            .values('item_id', 'purchase__branch_id').annotate(q=Sum('quantity'), v=Sum('line_total'))):
        if r['q']:
            by_item[r['item_id']].append((float(r['v']) / float(r['q']), float(r['v'])))
    hits = []
    for iid, lst in by_item.items():
        if len(lst) < 3:
            continue
        prices = [p for p, _ in lst]; val = sum(v for _, v in lst)
        mn, mx = min(prices), max(prices)
        if mn > 0 and val >= 20000:
            spread = (mx - mn) / mn * 100
            if spread >= float(thr):
                hits.append((iid, spread, mn, mx, val))
    hits.sort(key=lambda x: -x[4])
    out = []
    for iid, spread, mn, mx, val in hits[:8]:
        nm = _item_name_by_id(iid)
        out.append(dict(rule_code='price_inconsistency', category='discount', severity='warning',
            scope_type='product', scope_key=str(iid), scope_label=nm, value=Decimal(str(round(spread, 1))), baseline=None, threshold=thr,
            message_ar=f'🏷️⚠️ تفاوت سعر «{nm}» بين الفروع {spread:.0f}% ({_fmt(mn)}→{_fmt(mx)} ج.م/وحدة) على مبيعات {_fmt(val)} ج.م — انضباط تسعير.',
            message_en=f'🏷️⚠️ “{nm}” unit price varies {spread:.0f}% across branches ({_fmt(mn)}→{_fmt(mx)} EGP) on {_fmt(val)} EGP — pricing discipline.'))
    return out


def rule_inventory_turnover(ctx, threshold):
    """Branch inventory efficiency: net sales ÷ inventory value at cost. Low = idle capital.
    Ranking + a flag for branches below threshold turns."""
    thr = Decimal(str(threshold if threshold is not None else 0))
    from apps.catalog.models import ItemStock
    inv = dict(ItemStock.objects.filter(branch_id__in=ctx.branch_ids, quantity_on_hand__gt=0)
               .values_list('branch_id').annotate(v=Sum(ExpressionWrapper(
                   F('quantity_on_hand') * F('item__cost_price'), output_field=DecimalField(max_digits=20, decimal_places=2)))))
    sales = _net_by_branch(ctx, ctx.start, ctx.end)
    bmap = _branch_map(ctx)
    data = []
    for bid, iv in inv.items():
        iv = Decimal(str(iv or 0))
        if bid in bmap and iv > 0:
            data.append((ctx.bn(bmap[bid], 'ar'), ctx.bn(bmap[bid], 'en'), sales.get(bid, Decimal('0')) / iv))
    r = _pct_rank_finding  # reuse? no — turnover is a ratio not %. build inline
    ranked = sorted((x for x in data if x[2]), key=lambda x: -float(x[2]))[:5]
    out = []
    if ranked:
        ar = ' · '.join(f'{i+1}) {la} {float(v):.2f}×' for i, (la, le, v) in enumerate(ranked))
        en = ' · '.join(f'{i+1}) {le} {float(v):.2f}×' for i, (la, le, v) in enumerate(ranked))
        out.append(dict(rule_code='inventory_turnover', category='highlight', severity='info',
            scope_type='chain', scope_key='', scope_label='', value=Decimal(str(round(float(ranked[0][2]), 2))), baseline=None, threshold=None,
            message_ar=f'♻️ كفاءة المخزون (مبيعات÷مخزون) ({ctx.label()}): {ar} — الأعلى أكفأ.',
            message_en=f'♻️ Inventory turnover (sales÷stock) ({ctx.pw_en()}): {en} — higher is leaner.'))
    return out


def rule_structural_loss_skus(ctx, threshold):
    """Items whose SELLING price is below COST (structurally sold at a loss) — a pricing-config
    problem. Counts active items sold in the period + top examples."""
    from apps.catalog.models import Item
    from apps.customers.models import PurchaseHistoryLine
    sold_ids = set(PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
        purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids, item_id__isnull=False)
        .values_list('item_id', flat=True).distinct())
    if not sold_ids:
        return []
    # pack_price vs cost_price — both per-PACK (unit_price is per-unit → basis mismatch)
    qs = Item.objects.filter(id__in=sold_ids, is_active=True, cost_price__gt=0, pack_price__gt=0, pack_price__lt=F('cost_price'))
    n = qs.count()
    if n == 0:
        return []
    top = list(qs.annotate(gap=F('cost_price') - F('pack_price')).order_by('-gap')[:5])
    lst = ' · '.join(f'«{i.name}» (بيع {_fmt(i.pack_price)}/تكلفة {_fmt(i.cost_price)})' for i in top)
    return [dict(rule_code='structural_loss_skus', category='discount', severity='warning',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(n), baseline=None, threshold=None,
        message_ar=f'🩹 {n} صنف يُباع بأقل من التكلفة هيكلياً (سعر البيع < التكلفة) — مراجعة تسعير. أبرزها: {lst}.',
        message_en=f'🩹 {n} items priced below cost (sale < cost) — pricing review needed. Top: {lst}.')]


def rule_data_hygiene(ctx, threshold):
    """Data-quality flags that undermine analytics: invoices with no salesperson / no customer
    (PIC), and lines with missing cost. threshold = min % to flag."""
    thr = Decimal(str(threshold if threshold is not None else 5))
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    base = PurchaseHistory.objects.filter(invoice_date__date__gte=ctx.start, invoice_date__date__lte=ctx.end,
                                          doc_code='115', branch_id__in=ctx.branch_ids)
    total = base.count()
    if total == 0:
        return []
    norep = base.filter(softech_user='').count()
    nopic = base.filter(softech_phcode='').count()
    lbase = PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
        purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids)
    ltot = lbase.count()
    nocost = lbase.filter(Q(cost_at_sale__isnull=True) | Q(cost_at_sale=0)).count() if ltot else 0
    out = []
    for label_ar, label_en, num, den in [
        ('فواتير بلا مسئول بيع', 'invoices with no salesperson', norep, total),
        ('فواتير بلا عميل (PIC)', 'invoices with no customer PIC', nopic, total),
        ('بنود بلا تكلفة', 'lines with missing cost', nocost, ltot),
    ]:
        if den and (Decimal(num) / Decimal(den) * 100) >= thr:
            pct = Decimal(num) / Decimal(den) * 100
            out.append(dict(rule_code='data_hygiene', category='coverage', severity='warning',
                scope_type='chain', scope_key='', scope_label='', value=Decimal(str(round(float(pct), 1))), baseline=None, threshold=thr,
                message_ar=f'🧹 جودة البيانات: {num} {label_ar} ({pct:.0f}%) — يُضعف دقة التحليلات.',
                message_en=f'🧹 Data quality: {num} {label_en} ({pct:.0f}%) — weakens analytics accuracy.'))
    return out


def _latest_demand_run():
    from apps.purchasing.models import ItemDemandMetrics
    return ItemDemandMetrics.objects.order_by('-run_id').values_list('run_id', flat=True).first()


def rule_predictive_reorder(ctx, threshold):
    """PREDICTIVE stockout: items already below their safety stock (from the demand engine's
    ItemDemandMetrics) → reorder before they hit zero. Per branch: count + top by lost revenue."""
    from collections import defaultdict
    from apps.purchasing.models import ItemDemandMetrics
    thr = Decimal(str(threshold if threshold is not None else 10))   # min monthly velocity
    run = _latest_demand_run()
    if not run:
        return []
    qs = (ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches,
              current_stock__lt=F('safety_stock'), monthly_avg__gte=thr)
          .select_related('item', 'branch'))
    by_branch = defaultdict(list)
    for m in qs:
        by_branch[m.branch_id].append(m)
    out = []
    for bid, ms in by_branch.items():
        b = next((x for x in ctx.branches if x.id == bid), None)
        if not b:
            continue
        ms.sort(key=lambda m: -(float(m.lost_revenue_30d or 0)))
        top = ' · '.join(f'«{(x.item.name if x.item_id else x.item_id)}» ({float(x.coverage_days or 0):.0f} يوم)' for x in ms[:3])
        lost = sum(Decimal(str(x.lost_revenue_30d or 0)) for x in ms)
        out.append(dict(rule_code='predictive_reorder', category='coverage', severity='warning',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'), value=Decimal(len(ms)),
            baseline=lost, threshold=thr,
            message_ar=f'🔴 {ctx.bn(b,"ar")}: {len(ms)} صنف تحت حد الأمان (إعادة طلب قريبة) — أبرزها: {top}. مبيعات ضائعة متوقعة ~{_fmt(lost)} ج.م.',
            message_en=f'🔴 {ctx.bn(b,"en")}: {len(ms)} items below safety stock (reorder soon) — top: {top}. Expected lost revenue ~{_fmt(lost)} EGP.'))
    return out


def rule_near_expiry(ctx, threshold):
    """Near-expiry markdown candidates: items carrying expected expiry-risk value (from the
    demand engine) → push/discount before they're written off. Per branch: total + top items."""
    from collections import defaultdict
    from apps.purchasing.models import ItemDemandMetrics
    thr = Decimal(str(threshold if threshold is not None else 1000))
    run = _latest_demand_run()
    if not run:
        return []
    qs = (ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches, expected_expiry_risk_value__gte=thr)
          .select_related('item', 'branch'))
    by_branch = defaultdict(list)
    for m in qs:
        by_branch[m.branch_id].append(m)
    out = []
    for bid, ms in by_branch.items():
        b = next((x for x in ctx.branches if x.id == bid), None)
        if not b:
            continue
        ms.sort(key=lambda m: -(float(m.expected_expiry_risk_value or 0)))
        total = sum(Decimal(str(x.expected_expiry_risk_value or 0)) for x in ms)
        top = ' · '.join(f'«{(x.item.name if x.item_id else x.item_id)}» {_fmt(x.expected_expiry_risk_value)}' for x in ms[:3])
        out.append(dict(rule_code='near_expiry', category='volume', severity='warning',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'), value=total, baseline=None, threshold=thr,
            message_ar=f'⏳ {ctx.bn(b,"ar")}: مخاطر انتهاء صلاحية ~{_fmt(total)} ج.م على {len(ms)} صنف — تصريف/عرض قبل الخسارة. أبرزها: {top}.',
            message_en=f'⏳ {ctx.bn(b,"en")}: ~{_fmt(total)} EGP expiry risk across {len(ms)} items — mark down before loss. Top: {top}.'))
    return out


def rule_lost_sales_value(ctx, threshold):
    """Quantified lost sales: sum of lost_revenue_30d (demand engine) per branch — the real EGP
    walked out due to stockouts. Chain total + per-branch."""
    from apps.purchasing.models import ItemDemandMetrics
    thr = Decimal(str(threshold if threshold is not None else 5000))
    run = _latest_demand_run()
    if not run:
        return []
    rows = dict(ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches)
                .values_list('branch_id').annotate(v=Sum('lost_revenue_30d')))
    bmap = _branch_map(ctx)
    total = sum(Decimal(str(v or 0)) for v in rows.values())
    if total < thr:
        return []
    out = [dict(rule_code='lost_sales_value', category='coverage', severity='warning',
        scope_type='chain', scope_key='', scope_label='', value=total, baseline=None, threshold=thr,
        message_ar=f'💥 مبيعات ضائعة (آخر 30 يوماً): ~{_fmt(total)} ج.م بسبب نفاد المخزون — عبر الشبكة.',
        message_en=f'💥 Lost sales (last 30d): ~{_fmt(total)} EGP from stockouts — chain-wide.')]
    for bid, v in sorted(rows.items(), key=lambda x: -(x[1] or 0)):
        v = Decimal(str(v or 0))
        if bid in bmap and v >= thr:
            out.append(dict(rule_code='lost_sales_value', category='coverage', severity='info',
                scope_type='branch', scope_key=bmap[bid].code, scope_label=ctx.bn(bmap[bid], 'ar'),
                value=v, baseline=None, threshold=thr,
                message_ar=f'💥 {ctx.bn(bmap[bid],"ar")}: مبيعات ضائعة ~{_fmt(v)} ج.م (آخر 30 يوماً) من نفاد المخزون.',
                message_en=f'💥 {ctx.bn(bmap[bid],"en")}: ~{_fmt(v)} EGP lost sales (30d) from stockouts.'))
    return out


def rule_demand_surge_unmet(ctx, threshold):
    """A/B-class items whose 30-day forecast far exceeds current stock → an incoming stockout on
    important items. Per branch: top items by forecast gap."""
    from collections import defaultdict
    from apps.purchasing.models import ItemDemandMetrics
    thr = float(threshold if threshold is not None else 2)   # forecast ≥ thr× current stock
    run = _latest_demand_run()
    if not run:
        return []
    qs = (ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches, abc_class__in=['A', 'B'],
              forecast_next_30d__gt=0, monthly_avg__gte=10)
          .select_related('item', 'branch'))
    by_branch = defaultdict(list)
    for m in qs:
        cs = float(m.current_stock or 0); fc = float(m.forecast_next_30d or 0)
        if fc >= thr * max(cs, 1) and fc - cs >= 10:
            by_branch[m.branch_id].append((m, fc - cs))
    out = []
    for bid, items in by_branch.items():
        b = next((x for x in ctx.branches if x.id == bid), None)
        if not b:
            continue
        items.sort(key=lambda x: -x[1])
        top = ' · '.join(f'«{(m.item.name if m.item_id else m.item_id)}» (طلب {float(m.forecast_next_30d or 0):.0f}/مخزون {float(m.current_stock or 0):.0f})' for m, _ in items[:3])
        out.append(dict(rule_code='demand_surge_unmet', category='coverage', severity='warning',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'), value=Decimal(len(items)),
            baseline=None, threshold=None,
            message_ar=f'📈⚠️ {ctx.bn(b,"ar")}: {len(items)} صنف مهم طلبه المتوقع يفوق المخزون — نفاد وشيك. أبرزها: {top}.',
            message_en=f'📈⚠️ {ctx.bn(b,"en")}: {len(items)} key items with forecast above stock — imminent stockout. Top: {top}.'))
    return out


def rule_chronic_low_availability(ctx, threshold):
    """Fast-movers with chronically low availability_rate_30d (persistently out of stock) — a
    structural replenishment failure, not a one-off. Per branch: count + worst items."""
    from collections import defaultdict
    from apps.purchasing.models import ItemDemandMetrics
    thr = Decimal(str(threshold if threshold is not None else 70))
    run = _latest_demand_run()
    if not run:
        return []
    qs = (ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches,
              availability_rate_30d__lt=thr, monthly_avg__gte=10).select_related('item', 'branch'))
    by_branch = defaultdict(list)
    for m in qs:
        by_branch[m.branch_id].append(m)
    out = []
    for bid, ms in by_branch.items():
        b = next((x for x in ctx.branches if x.id == bid), None)
        if not b or len(ms) < 3:
            continue
        ms.sort(key=lambda m: float(m.availability_rate_30d or 0))
        top = ' · '.join(f'«{(m.item.name if m.item_id else m.item_id)}» ({float(m.availability_rate_30d or 0):.0f}%)' for m in ms[:3])
        out.append(dict(rule_code='chronic_low_availability', category='coverage', severity='warning',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'), value=Decimal(len(ms)),
            baseline=None, threshold=thr,
            message_ar=f'🚫 {ctx.bn(b,"ar")}: {len(ms)} صنف سريع الحركة إتاحته منخفضة مزمناً (<{thr:.0f}%) — نفاد متكرر. أبرزها: {top}.',
            message_en=f'🚫 {ctx.bn(b,"en")}: {len(ms)} fast-movers chronically low availability (<{thr:.0f}%) — repeat stockouts. Worst: {top}.'))
    return out


def rule_dead_stock_growth(ctx, threshold):
    """Idle capital (dead stock) GROWING vs a ~30-day-earlier demand run — tied-up capital trend."""
    from django.db.models import Max as _Max
    from apps.purchasing.models import ItemDemandMetrics
    thr = Decimal(str(threshold if threshold is not None else 10))
    dates = list(ItemDemandMetrics.objects.values('run_id').annotate(d=_Max('calc_date')).order_by('-d')[:30])
    if len(dates) < 2:
        return []
    latest = dates[0]
    older = next((x for x in dates[1:] if (latest['d'] - x['d']).days >= 20), None)
    if not older:
        return []
    idle = ExpressionWrapper(F('current_stock') * F('pack_price'), output_field=DecimalField(max_digits=22, decimal_places=2))

    def idle_val(rid):
        return Decimal(str(ItemDemandMetrics.objects.filter(run_id=rid, branch__in=ctx.branches,
                       monthly_avg__lte=0, current_stock__gt=0).aggregate(v=Sum(idle))['v'] or 0))
    now, prev = idle_val(latest['run_id']), idle_val(older['run_id'])
    if prev <= 0 or now <= prev:
        return []
    growth = (now - prev) / prev * 100
    if growth < thr:
        return []
    return [dict(rule_code='dead_stock_growth', category='volume', severity='warning',
        scope_type='chain', scope_key='', scope_label='', value=now, baseline=prev, threshold=thr,
        message_ar=f'🧊📈 المخزون الراكد يتزايد: {_fmt(now)} ج.م (▲{growth:.0f}% عن {older["d"]}) — رأس مال مُجمّد ينمو.',
        message_en=f'🧊📈 Dead stock growing: {_fmt(now)} EGP (▲{growth:.0f}% vs {older["d"]}) — tied-up capital rising.')]


def rule_overstock_coverage(ctx, threshold):
    """Over-ordering: items still moving but carrying ≥ threshold months of coverage — capital
    tied up + expiry exposure. Per branch: idle value + worst items. (Uses ItemDemandMetrics.)"""
    from collections import defaultdict
    from apps.purchasing.models import ItemDemandMetrics
    thr = Decimal(str(threshold if threshold is not None else 12))
    run = _latest_demand_run()
    if not run:
        return []
    qs = (ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches,
              coverage_months__gte=thr, current_stock__gt=0, monthly_avg__gte=1).select_related('item', 'branch'))
    by_branch = defaultdict(list)
    for m in qs:
        by_branch[m.branch_id].append(m)
    out = []
    for bid, ms in by_branch.items():
        b = next((x for x in ctx.branches if x.id == bid), None)
        if not b:
            continue
        val = sum(Decimal(str((m.current_stock or 0))) * Decimal(str((m.pack_price or 0))) for m in ms)
        if val < 20000:
            continue
        ms.sort(key=lambda m: -(float(m.current_stock or 0) * float(m.pack_price or 0)))
        top = ' · '.join(f'«{(m.item.name if m.item_id else m.item_id)}» ({float(m.coverage_months or 0):.0f} شهر)' for m in ms[:3])
        out.append(dict(rule_code='overstock_coverage', category='volume', severity='warning',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'), value=val, baseline=None, threshold=thr,
            message_ar=f'📦🐌 {ctx.bn(b,"ar")}: {len(ms)} صنف تغطيته ≥{thr:.0f} شهر (~{_fmt(val)} ج.م رأس مال) — تقليل الطلب. أبرزها: {top}.',
            message_en=f'📦🐌 {ctx.bn(b,"en")}: {len(ms)} items with ≥{thr:.0f} months coverage (~{_fmt(val)} EGP capital) — cut ordering. Top: {top}.'))
    return out


def rule_stockout_root_cause(ctx, threshold):
    """Decompose lost sales by ROOT CAUSE (purchasing vs transfer vs internal vs unknown) so the
    fix is targeted at the real bottleneck. Chain-level. (Uses ItemDemandMetrics.)"""
    from apps.purchasing.models import ItemDemandMetrics
    run = _latest_demand_run()
    if not run:
        return []
    rows = (ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches, lost_revenue_30d__gt=0)
            .values('root_cause').annotate(v=Sum('lost_revenue_30d')).order_by('-v'))
    rows = [r for r in rows if r['v']]
    if not rows:
        return []
    RC_AR = {'purchasing': 'مشتريات', 'transfer': 'تحويلات', 'internal': 'داخلي', 'supplier': 'مورد',
             'demand': 'طلب', 'unknown': 'غير معروف'}
    RC_EN = {'purchasing': 'purchasing', 'transfer': 'transfers', 'internal': 'internal', 'supplier': 'supplier',
             'demand': 'demand', 'unknown': 'unknown'}
    pa = ' · '.join(f'{RC_AR.get(r["root_cause"], r["root_cause"])} {_fmt(r["v"])}' for r in rows)
    pe = ' · '.join(f'{RC_EN.get(r["root_cause"], r["root_cause"])} {_fmt(r["v"])}' for r in rows)
    return [dict(rule_code='stockout_root_cause', category='coverage', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(str(rows[0]['v'] or 0)), baseline=None, threshold=None,
        message_ar=f'🔎 أسباب المبيعات الضائعة (آخر 30 يوماً): {pa} ج.م — عالِج الأكبر أولاً.',
        message_en=f'🔎 Lost-sales root causes (last 30d): {pe} EGP — fix the biggest first.')]


def rule_critical_coverage(ctx, threshold):
    """Days-to-stockout: important (A/B) fast-movers with ≤ threshold days of stock left →
    order NOW. Sharper urgency signal than 'below safety stock'. Per branch: count + soonest."""
    from collections import defaultdict
    from apps.purchasing.models import ItemDemandMetrics
    thr = float(threshold if threshold is not None else 5)
    run = _latest_demand_run()
    if not run:
        return []
    qs = (ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches,
              coverage_days__lte=thr, monthly_avg__gte=5, abc_class__in=['A', 'B']).select_related('item', 'branch'))
    by_branch = defaultdict(list)
    for m in qs:
        by_branch[m.branch_id].append(m)
    out = []
    for bid, ms in by_branch.items():
        b = next((x for x in ctx.branches if x.id == bid), None)
        if not b or len(ms) < 3:
            continue
        ms.sort(key=lambda m: float(m.coverage_days or 0))
        top = ' · '.join(f'«{(m.item.name if m.item_id else m.item_id)}» ({float(m.coverage_days or 0):.0f} يوم)' for m in ms[:3])
        out.append(dict(rule_code='critical_coverage', category='coverage', severity='critical',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'), value=Decimal(len(ms)),
            baseline=None, threshold=Decimal(str(thr)),
            message_ar=f'⛔ {ctx.bn(b,"ar")}: {len(ms)} صنف مهم يكفي مخزونه ≤{thr:.0f} يوم — اطلب فوراً. أقربها: {top}.',
            message_en=f'⛔ {ctx.bn(b,"en")}: {len(ms)} key items with ≤{thr:.0f} days of stock — order now. Soonest: {top}.'))
    return out


def rule_supply_bottlenecks(ctx, threshold):
    """Items that were a supply BOTTLENECK for many of the last 30 days (persistent supply
    friction) — chain top items by bottleneck days. (ItemDemandMetrics.bottleneck_days_30d.)"""
    from apps.purchasing.models import ItemDemandMetrics
    thr = int(threshold if threshold is not None else 4)
    run = _latest_demand_run()
    if not run:
        return []
    qs = (ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches, bottleneck_days_30d__gte=thr)
          .select_related('item').order_by('-bottleneck_days_30d', '-lost_revenue_30d')[:8])
    ms = list(qs)
    if not ms:
        return []
    top = ' · '.join(f'«{(m.item.name if m.item_id else m.item_id)}» ({m.bottleneck_days_30d} يوم)' for m in ms)
    return [dict(rule_code='supply_bottlenecks', category='coverage', severity='warning',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(len(ms)), baseline=None, threshold=Decimal(thr),
        message_ar=f'🚧 اختناقات التوريد ({ctx.label()}): أصناف كانت نافدة ≥{thr} يوماً من آخر 30 — {top} — راجع التوريد.',
        message_en=f'🚧 Supply bottlenecks ({ctx.pw_en()}): items unavailable ≥{thr} of last 30 days — {top} — review sourcing.')]


def rule_abc_distribution(ctx, threshold):
    """ABC inventory mix (from the demand engine): items, stock value and sales per A/B/C class
    + a flag if too much capital sits in low-value C items."""
    from apps.purchasing.models import ItemDemandMetrics
    thr = Decimal(str(threshold if threshold is not None else 40))
    run = _latest_demand_run()
    if not run:
        return []
    idle = ExpressionWrapper(F('current_stock') * F('pack_price'), output_field=DecimalField(max_digits=22, decimal_places=2))
    rows = {r['abc_class']: r for r in ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches)
            .values('abc_class').annotate(n=Count('id'), inv=Sum(idle), sales=Sum('net_sales_revenue'))}
    if not rows:
        return []
    LA = {'A': 'أ (عالية)', 'B': 'ب', 'C': 'ج (منخفضة)', 'X': 'غير مصنّف'}
    LE = {'A': 'A (high)', 'B': 'B', 'C': 'C (low)', 'X': 'unclassified'}
    tot_inv = sum(Decimal(str(r['inv'] or 0)) for r in rows.values())

    def turns(r):   # annual sales ÷ current stock value = inventory turns/yr
        inv = float(r['inv'] or 0)
        return (float(r['sales'] or 0) / inv) if inv > 0 else 0
    pa = ' · '.join(f'{LA.get(c, c)}: {rows[c]["n"]} صنف · مخزون {_fmt(rows[c]["inv"])} · مبيعات سنوية {_fmt(rows[c]["sales"])} · دوران {turns(rows[c]):.1f}×/سنة'
                    for c in ['A', 'B', 'C'] if c in rows)
    pe = ' · '.join(f'{LE.get(c, c)}: {rows[c]["n"]} items · stock {_fmt(rows[c]["inv"])} · annual sales {_fmt(rows[c]["sales"])} · turns {turns(rows[c]):.1f}×/yr'
                    for c in ['A', 'B', 'C'] if c in rows)
    out = [dict(rule_code='abc_distribution', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=tot_inv, baseline=None, threshold=None,
        message_ar=f'🅰️ توزيع المخزون ABC (لقطة حالية · مبيعات 365 يوم): {pa} ج.م.',
        message_en=f'🅰️ ABC inventory mix (current stock · 365-day sales): {pe} EGP.')]
    c_inv = Decimal(str(rows.get('C', {}).get('inv', 0) or 0))
    if tot_inv > 0 and c_inv / tot_inv * 100 >= thr:
        out.append(dict(rule_code='abc_distribution', category='volume', severity='warning',
            scope_type='chain', scope_key='', scope_label='', value=c_inv, baseline=tot_inv, threshold=thr,
            message_ar=f'⚠️ {c_inv/tot_inv*100:.0f}% من رأس مال المخزون في أصناف C منخفضة القيمة ({_fmt(c_inv)} ج.م) — راجع سياسة الشراء.',
            message_en=f'⚠️ {c_inv/tot_inv*100:.0f}% of inventory capital sits in low-value C items ({_fmt(c_inv)} EGP) — review buying policy.'))
    return out


def rule_low_forecast_confidence(ctx, threshold):
    """Important (A/B) items whose demand forecast is LOW-confidence (volatile demand) → hold a
    larger safety buffer. Chain top by value. (ItemDemandMetrics.forecast_confidence 0–1.)"""
    from apps.purchasing.models import ItemDemandMetrics
    thr = Decimal(str(threshold if threshold is not None else 0.6))
    run = _latest_demand_run()
    if not run:
        return []
    qs = (ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches, forecast_confidence__lt=thr,
              abc_class__in=['A', 'B'], monthly_value__gte=5000).select_related('item').order_by('forecast_confidence')[:8])
    ms = list(qs)
    if len(ms) < 3:
        return []
    top = ' · '.join(f'«{(m.item.name if m.item_id else m.item_id)}» ({float(m.forecast_confidence or 0)*100:.0f}%)' for m in ms[:4])
    return [dict(rule_code='low_forecast_confidence', category='coverage', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(len(ms)), baseline=None, threshold=thr,
        message_ar=f'🔮 تنبؤ غير موثوق: {len(ms)}+ صنف مهم طلبه متقلّب (ثقة <{float(thr)*100:.0f}%) — احتفظ بمخزون أمان أكبر. أبرزها: {top}.',
        message_en=f'🔮 Low-confidence forecast: {len(ms)}+ key items with volatile demand (<{float(thr)*100:.0f}%) — hold more safety stock. Top: {top}.')]


def rule_stockout_calendar(ctx, threshold):
    """Forward-looking STOCKOUT CALENDAR from the demand engine's expected_stockout_date: how
    many important items run out in the next 7 / 8-14 / 15-30 days, the monthly value at risk,
    the soonest items, and a per-branch imminent (≤7d) count."""
    from collections import defaultdict
    from datetime import timedelta as _td
    from django.db.models import Max as _Max
    from apps.purchasing.models import ItemDemandMetrics
    horizon = int(threshold if threshold is not None else 30)
    run = _latest_demand_run()
    if not run:
        return []
    base = ItemDemandMetrics.objects.filter(run_id=run, branch__in=ctx.branches,
               expected_stockout_date__isnull=False, monthly_avg__gte=5)
    calc = base.aggregate(c=_Max('calc_date'))['c']
    if not calc:
        return []
    up = base.filter(expected_stockout_date__gt=calc, expected_stockout_date__lte=calc + _td(days=horizon))
    if not up.exists():
        return []
    def cnt(lo, hi):
        return up.filter(expected_stockout_date__gt=calc + _td(days=lo), expected_stockout_date__lte=calc + _td(days=hi)).count()
    b7 = up.filter(expected_stockout_date__lte=calc + _td(days=7)).count()
    b14, b30 = cnt(7, 14), cnt(14, 30)
    val = Decimal(str(up.aggregate(v=Sum('monthly_value'))['v'] or 0))
    soon = list(up.select_related('item').order_by('expected_stockout_date')[:5])
    lst = ' · '.join(f'«{(m.item.name if m.item_id else m.item_id)}» ({m.expected_stockout_date})' for m in soon)
    out = [dict(rule_code='stockout_calendar', category='coverage', severity='warning',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(b7 + b14 + b30), baseline=val, threshold=Decimal(horizon),
        message_ar=f'📅 تقويم النفاد (اعتباراً من {calc}): خلال 7 أيام {b7} صنف · 8-14 يوم {b14} · 15-30 يوم {b30} — بقيمة مبيعات شهرية ~{_fmt(val)} ج.م معرّضة.',
        message_en=f'📅 Stockout calendar (from {calc}): next 7 days {b7} items · 8-14 days {b14} · 15-30 days {b30} — ~{_fmt(val)} EGP monthly sales at risk.')]
    if soon:
        out.append(dict(rule_code='stockout_calendar', category='coverage', severity='info',
            scope_type='chain', scope_key='', scope_label='', value=Decimal(len(soon)), baseline=None, threshold=None,
            message_ar=f'🔜 الأقرب نفاداً: {lst} — رتّب الطلب حسب التاريخ.',
            message_en=f'🔜 Soonest to run out: {lst} — sequence orders by date.'))
    per_branch = defaultdict(int)
    for bid in up.filter(expected_stockout_date__lte=calc + _td(days=7)).values_list('branch_id', flat=True):
        per_branch[bid] += 1
    bmap = _branch_map(ctx)
    for bid, n in per_branch.items():
        if bid in bmap and n >= 5:
            out.append(dict(rule_code='stockout_calendar', category='coverage', severity='warning',
                scope_type='branch', scope_key=bmap[bid].code, scope_label=ctx.bn(bmap[bid], 'ar'),
                value=Decimal(n), baseline=None, threshold=None,
                message_ar=f'📅 {ctx.bn(bmap[bid],"ar")}: {n} صنف مهم سينفد خلال 7 أيام — اطلب الآن.',
                message_en=f'📅 {ctx.bn(bmap[bid],"en")}: {n} key items will run out within 7 days — order now.'))
    return out


# ── Stock counts (stockcount.StockCountSession) ───────────────────────────────

def rule_stock_variance(ctx, threshold):
    """A stock count with high deficit/surplus item counts (shrinkage / error signal)."""
    thr = int(threshold if threshold is not None else 15)
    from apps.stockcount.models import StockCountSession
    sessions = StockCountSession.objects.filter(
        variance_at__date__gte=ctx.start, variance_at__date__lte=ctx.end,
        status__in=['variance_ready', 'closed'])
    out = []
    for s in sessions:
        if s.deficit_count >= thr or s.surplus_count >= thr:
            b = ctx.branch_by_code.get(str(s.branch_code))
            nm = (b.name_ar or b.name) if b else s.branch_code
            ne = (b.name or b.name_ar) if b else s.branch_code
            out.append(dict(rule_code='stock_variance', category='coverage', severity='warning',
                scope_type='branch', scope_key=str(s.branch_code), scope_label=nm,
                value=Decimal(s.deficit_count), baseline=Decimal(s.surplus_count), threshold=Decimal(thr),
                message_ar=f'📦 جرد {nm}: {s.deficit_count} صنف عجز و{s.surplus_count} صنف زيادة.',
                message_en=f'📦 {ne} stock count: {s.deficit_count} items short, {s.surplus_count} over.'))
    return out


# ── Inter-branch cooperation (transfers.TransferRequest) ──────────────────────

def _peer_transfers(ctx):
    """Actual SOFTECH inter-branch transfers (doccode 125) issued in the period BETWEEN retail
    branches — excludes HQ→branch warehouse distribution (supplying branch must be a retail branch)."""
    from apps.transits.models import InTransitTransfer
    return InTransitTransfer.objects.filter(
        issue_date__gte=ctx.start, issue_date__lte=ctx.end,
        supplying_branch_id__in=ctx.branch_ids)


def rule_branch_cooperation(ctx, threshold):
    """Highlight peer help from SOFTECH transfers (125): total + top supplying (helper) branch."""
    qs = _peer_transfers(ctx)
    total = qs.count()
    if total == 0:
        return []
    top = (qs.values('supplying_branch__name', 'supplying_branch__name_ar')
           .annotate(c=Count('id')).order_by('-c').first())
    out = [dict(rule_code='branch_cooperation', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(total), baseline=None, threshold=None,
        message_ar=f'🤝 تعاون الفروع: {total} تحويل بيني (من فرع لفرع) خلال ال{ctx.label()}.',
        message_en=f'🤝 Branch cooperation: {total} peer branch-to-branch transfers this {ctx.pw_en()}.')]
    if top and top['c']:
        nm = top['supplying_branch__name_ar'] or top['supplying_branch__name'] or '—'
        ne = top['supplying_branch__name'] or top['supplying_branch__name_ar'] or '—'
        out.append(dict(rule_code='branch_cooperation', category='highlight', severity='info',
            scope_type='branch', scope_key='', scope_label=nm, value=Decimal(top['c']), baseline=None, threshold=None,
            message_ar=f'🏅 الأكثر مساعدة: {nm} زوّد الفروع الأخرى بـ {top["c"]} تحويل.',
            message_en=f'🏅 Most helpful: {ne} supplied {top["c"]} transfers to other branches.'))
    return out


def rule_branch_isolation(ctx, threshold):
    """Retail branch that took no part in peer transfers (neither supplied nor received)."""
    qs = _peer_transfers(ctx)
    if not qs.exists():
        return []
    active = set(qs.values_list('supplying_branch_id', flat=True)) | set(qs.values_list('receiving_branch_id', flat=True))
    out = []
    for b in ctx.branches:
        if b.id not in active:
            nm, ne = ctx.bn(b, 'ar'), ctx.bn(b, 'en')
            out.append(dict(rule_code='branch_isolation', category='volume', severity='info',
                scope_type='branch', scope_key=b.code, scope_label=nm, value=Decimal('0'), baseline=None, threshold=None,
                message_ar=f'🔌 {nm}: لم يشارك في أي تحويل بيني (من/إلى فرع) خلال ال{ctx.label()}.',
                message_en=f'🔌 {ne}: no peer branch-to-branch transfer activity this {ctx.pw_en()}.'))
    return out


# ── Don't-lose-sales: inventory (catalog.ItemStock; monthly_qty = velocity) ────

def rule_stockout_fastmovers(ctx, threshold):
    """Fast-moving items out of stock at a branch = lost sales. Count + top items."""
    from apps.catalog.models import ItemStock
    thr = Decimal(str(threshold if threshold is not None else 30))   # min monthly units to be a 'fast mover'
    qs = (ItemStock.objects.filter(branch_id__in=ctx.branch_ids,
              quantity_on_hand__lte=0, monthly_qty__gte=thr)
          .select_related('item').order_by('-monthly_qty'))
    by_branch = {}
    for s in qs:
        by_branch.setdefault(s.branch_id, []).append(s)
    out = []
    for b in ctx.branches:
        items = by_branch.get(b.id, [])
        if items:
            top = '، '.join((getattr(s.item, 'name', '') or '')[:22] for s in items[:3])
            out.append(dict(rule_code='stockout_fastmovers', category='coverage', severity='critical',
                scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'),
                value=Decimal(len(items)), baseline=None, threshold=thr,
                message_ar=f'🚨 {ctx.bn(b,"ar")}: {len(items)} صنف سريع الحركة نافد من المخزون (مبيعات ضائعة) — أبرزها: {top}.',
                message_en=f'🚨 {ctx.bn(b,"en")}: {len(items)} fast-moving items out of stock (lost sales) — e.g. {top}.'))
    return out


def rule_dead_stock(ctx, threshold):
    """Capital tied in non-moving stock (qty on hand, no monthly movement), EGP per branch,
    BROKEN DOWN by general category (medicine / cosmetics / others …), plus a chain ranking
    of branches by total dead-stock value."""
    from collections import defaultdict
    from apps.catalog.models import ItemStock
    thr = Decimal(str(threshold if threshold is not None else 150000))   # EGP at cost
    val = ExpressionWrapper(F('quantity_on_hand') * F('item__cost_price'),
                            output_field=DecimalField(max_digits=18, decimal_places=2))
    # medicine_type code → clean bilingual category label (the DB *_ar field holds English)
    MED_AR = {'50': 'مستحضرات تجميل', '10': 'أدوية', '20': 'أخرى', '30': 'مكملات غذائية',
              '40': 'بيطري', '60': 'هدايا عملاء', '70': 'خدمات', '00': 'غير مصنّف', '': 'غير مصنّف'}
    MED_EN = {'50': 'Cosmetics', '10': 'Medicine', '20': 'Others', '30': 'Body Building',
              '40': 'Veterinary', '60': 'Client gifts', '70': 'Services', '00': 'Unclassified', '': 'Unclassified'}
    rows = (ItemStock.objects.filter(branch_id__in=ctx.branch_ids,
                    quantity_on_hand__gt=0, monthly_qty__lte=0)
            .values('branch_id', 'item__medicine_type')
            .annotate(v=Sum(val)))
    per_branch = defaultdict(lambda: defaultdict(Decimal))   # bid → {(cat_ar,cat_en): value}
    totals = defaultdict(Decimal)
    for r in rows:
        bid = r['branch_id']; v = Decimal(str(r['v'] or 0))
        code = r['item__medicine_type'] or ''
        cat_ar = MED_AR.get(code, code or 'غير مصنّف')
        cat_en = MED_EN.get(code, code or 'Unclassified')
        per_branch[bid][(cat_ar, cat_en)] += v
        totals[bid] += v
    out = []
    for b in ctx.branches:
        v = totals.get(b.id, Decimal('0'))
        if v >= thr:
            cats = sorted(per_branch[b.id].items(), key=lambda x: -x[1])[:4]
            split_ar = ' · '.join(f'{ca} {_fmt(cv)}' for (ca, ce), cv in cats)
            split_en = ' · '.join(f'{ce} {_fmt(cv)}' for (ca, ce), cv in cats)
            out.append(dict(rule_code='dead_stock', category='volume', severity='warning',
                scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'),
                value=v, baseline=None, threshold=thr,
                message_ar=f'🧊 {ctx.bn(b,"ar")}: مخزون راكد {_fmt(v)} ج.م (رأس مال مُجمّد) — {split_ar}.',
                message_en=f'🧊 {ctx.bn(b,"en")}: {_fmt(v)} EGP dead stock (tied-up capital) — {split_en}.'))
    # chain ranking of branches by total dead stock
    ranked = sorted(((b, totals.get(b.id, Decimal('0'))) for b in ctx.branches), key=lambda x: -x[1])
    r = _ranking(ctx, 'dead_stock', '🧊 ترتيب الفروع في المخزون الراكد',
                 'Dead-stock ranking', [(ctx.bn(b, 'ar'), ctx.bn(b, 'en'), val) for b, val in ranked])
    if r:
        out.append(r)
    return out


# ── Sales SEGMENT analytics (values, averages, basket, counts per channel/band) ─

def _segline(s, ar=True):
    """Compact stat line for a segment dict from _seg_stats."""
    if ar:
        return f'{_fmt(s["value"])} ج.م · {s["txn"]} عملية · سلة {float(s["basket"]):.1f} · متوسط الفاتورة {_fmt(s["avg_txn"])} ج.م'
    return f'{_fmt(s["value"])} EGP · {s["txn"]} txns · basket {float(s["basket"]):.1f} · avg {_fmt(s["avg_txn"])} EGP'


def _delta(cur, alt):
    cur, alt = float(cur or 0), float(alt or 0)
    if alt <= 0:
        return '—'
    d = (cur - alt) / alt * 100
    return f'{"▲" if d >= 0 else "▼"}{abs(d):.0f}%'


def _last_year(ctx):
    """Same calendar window one year earlier (for YoY same-period comparison)."""
    def y1(d):
        try:
            return d.replace(year=d.year - 1)
        except ValueError:      # 29 Feb
            return d.replace(year=d.year - 1, day=28)
    return y1(ctx.start), y1(ctx.end)


def _cmp(cur_val, pv, lv, ar):
    """' (الفترة السابقة ▲X% · العام السابق ▼Y%)' comparison suffix on the segment VALUE."""
    if ar:
        return f' (الفترة السابقة {_delta(cur_val, pv)} · نفس الفترة العام السابق {_delta(cur_val, lv)})'
    return f' (prev period {_delta(cur_val, pv)} · same period last yr {_delta(cur_val, lv)})'


def rule_sales_segments(ctx, threshold):
    """Comprehensive CHAIN segment analytics with two comparisons per segment VALUE — vs the
    previous same-length period (for MTD = same days last month) and vs the same period last
    year. Segments: total / cash / non-bulk / bulk / walk-in / delivery / beauty."""
    fl = ctx.basket_bulk_floor
    lys, lye = _last_year(ctx)

    def seg3(channels, **kw):
        cur = _seg_stats(ctx, channels, **kw)
        pv = _seg_stats(ctx, channels, s=ctx.prev_start, e=ctx.prev_end, value_only=True, **kw)['value']
        lv = _seg_stats(ctx, channels, s=lys, e=lye, value_only=True, **kw)['value']
        return cur, pv, lv
    total, tpv, tlv = seg3(None)
    if total['txn'] == 0:
        return []
    cash, cpv, clv = seg3(ctx.cash_channels)
    cash_nb, npv, nlv = seg3(ctx.cash_channels, max_total=fl)
    cash_bulk, bpv, blv = seg3(ctx.cash_channels, min_total=fl)
    walkin, wpv, wlv = seg3(ctx.walkin_channels)
    deliv, dpv, dlv = seg3(ctx.delivery_channels)
    beauty, ypv, ylv = seg3(ctx.cash_channels, beauty=True)
    walkin_nb = _seg_stats(ctx, ctx.walkin_channels, max_total=fl)
    deliv_nb = _seg_stats(ctx, ctx.delivery_channels, max_total=fl)
    L = ctx.label(); Le = ctx.pw_en()
    mk = lambda ar, en: dict(rule_code='sales_segments', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=Decimal('0'), baseline=None, threshold=None,
        message_ar=ar, message_en=en)
    return [
        mk(f'📊 صافي المبيعات ({L}): {_segline(total)}{_cmp(total["value"],tpv,tlv,True)}.',
           f'📊 Net sales ({Le}): {_segline(total, False)}{_cmp(total["value"],tpv,tlv,False)}.'),
        mk(f'💵 المبيعات النقدية ({L}): {_segline(cash)}{_cmp(cash["value"],cpv,clv,True)}.',
           f'💵 Cash sales ({Le}): {_segline(cash, False)}{_cmp(cash["value"],cpv,clv,False)}.'),
        mk(f'💵 نقدى بدون الجملة (<{_fmt(fl)}): {_segline(cash_nb)}{_cmp(cash_nb["value"],npv,nlv,True)}.',
           f'💵 Cash ex-bulk (<{_fmt(fl)}): {_segline(cash_nb, False)}{_cmp(cash_nb["value"],npv,nlv,False)}.'),
        mk(f'📦 نقدى الجملة (≥{_fmt(fl)}): {_fmt(cash_bulk["value"])} ج.م · {cash_bulk["txn"]} عملية · متوسط {_fmt(cash_bulk["avg_txn"])}{_cmp(cash_bulk["value"],bpv,blv,True)}.',
           f'📦 Bulk cash (≥{_fmt(fl)}): {_fmt(cash_bulk["value"])} EGP · {cash_bulk["txn"]} txns · avg {_fmt(cash_bulk["avg_txn"])}{_cmp(cash_bulk["value"],bpv,blv,False)}.'),
        mk(f'🚶 استلام مباشر ({L}): {_segline(walkin)}{_cmp(walkin["value"],wpv,wlv,True)} — بدون الجملة: سلة {float(walkin_nb["basket"]):.1f} · متوسط {_fmt(walkin_nb["avg_txn"])}.',
           f'🚶 Walk-in ({Le}): {_segline(walkin, False)}{_cmp(walkin["value"],wpv,wlv,False)} — ex-bulk: basket {float(walkin_nb["basket"]):.1f} · avg {_fmt(walkin_nb["avg_txn"])}.'),
        mk(f'🚚 التوصيل ({L}): {_segline(deliv)}{_cmp(deliv["value"],dpv,dlv,True)} — بدون الجملة: سلة {float(deliv_nb["basket"]):.1f} · متوسط {_fmt(deliv_nb["avg_txn"])}.',
           f'🚚 Delivery ({Le}): {_segline(deliv, False)}{_cmp(deliv["value"],dpv,dlv,False)} — ex-bulk: basket {float(deliv_nb["basket"]):.1f} · avg {_fmt(deliv_nb["avg_txn"])}.'),
        mk(f'💄 التجميل نقدى ({L}): {_fmt(beauty["value"])} ج.م · {beauty["txn"]} عملية · سلة {float(beauty["basket"]):.1f}{_cmp(beauty["value"],ypv,ylv,True)}.',
           f'💄 Beauty cash ({Le}): {_fmt(beauty["value"])} EGP · {beauty["txn"]} txns · basket {float(beauty["basket"]):.1f}{_cmp(beauty["value"],ypv,ylv,False)}.'),
    ]


def rule_tracked_items(ctx, threshold):
    """Count + value of owner-configured item codes (delivery fees, BP/glucose measurement, …)
    — chain-wide, plus a per-branch line. Configure via SystemSetting analytics_tracked_item_codes."""
    if not ctx.tracked_items:
        return []
    out = []
    for code, label in ctx.tracked_items:
        s = _seg_stats(ctx, None, item_codes=[code])
        if s['txn'] == 0 and s['value'] == 0:
            continue
        out.append(dict(rule_code='tracked_items', category='highlight', severity='info',
            scope_type='product', scope_key=code, scope_label=label, value=s['value'], baseline=None, threshold=None,
            message_ar=f'🩺 {label} ({ctx.label()}): {_fmt(s["units"])} مرة بقيمة {_fmt(s["value"])} ج.م في {s["txn"]} فاتورة.',
            message_en=f'🩺 {label} ({ctx.pw_en()}): {_fmt(s["units"])} times worth {_fmt(s["value"])} EGP in {s["txn"]} invoices.'))
    return out


def rule_branch_segments(ctx, threshold):
    """Per-branch segment snapshot (for the فرع report): total / cash / delivery / beauty."""
    out = []
    for b in ctx.branches:
        total = _seg_stats(ctx, None, branch_id=b.id)
        if total['txn'] == 0:
            continue
        cash = _seg_stats(ctx, ctx.cash_channels, branch_id=b.id)
        deliv = _seg_stats(ctx, ctx.delivery_channels, branch_id=b.id)
        beauty = _seg_stats(ctx, ctx.cash_channels, branch_id=b.id, beauty=True)
        out.append(dict(rule_code='branch_segments', category='volume', severity='info',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'),
            value=total['value'], baseline=None, threshold=None,
            message_ar=(f'📊 قطاعات {ctx.bn(b,"ar")} ({ctx.label()}): إجمالى {_segline(total)} — نقدى {_fmt(cash["value"])} · '
                        f'توصيل {_fmt(deliv["value"])} ({deliv["txn"]} عملية) · تجميل {_fmt(beauty["value"])} ({beauty["txn"]}).'),
            message_en=(f'📊 {ctx.bn(b,"en")} segments ({ctx.pw_en()}): total {_segline(total, False)} — cash {_fmt(cash["value"])} · '
                        f'delivery {_fmt(deliv["value"])} ({deliv["txn"]} txns) · beauty {_fmt(beauty["value"])} ({beauty["txn"]}).')))
    return out


def _basket_rank_finding(ctx, code, title_ar, title_en, data):
    """Ranking finding for a basket-size metric (1-decimal, 'items' unit). data=[(la,le,val)]."""
    ranked = sorted((x for x in data if x[2]), key=lambda x: -float(x[2]))[:5]
    if not ranked:
        return None
    ar = ' · '.join(f'{i+1}) {la} {float(v):.1f}' for i, (la, le, v) in enumerate(ranked))
    en = ' · '.join(f'{i+1}) {le} {float(v):.1f}' for i, (la, le, v) in enumerate(ranked))
    return dict(rule_code=code, category='highlight', severity='info', scope_type='chain', scope_key='', scope_label='',
        value=Decimal(str(round(float(ranked[0][2]), 2))), baseline=None, threshold=None,
        message_ar=f'{title_ar} ({ctx.label()}): {ar} صنف.', message_en=f'{title_en} ({ctx.pw_en()}): {en} items.')


def rule_segment_rankings(ctx, threshold):
    """Walk-in and delivery leaderboards — branches AND salespeople ranked by segment VALUE
    and by BASKET size (items/invoice)."""
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    bmap = _branch_map(ctx)
    out = []

    def group(channels):
        vb = _net_by_branch(ctx, ctx.start, ctx.end, channels=channels)   # net of returns
        vu = _net_by_user(ctx, channels)
        lb = PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
            purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids, purchase__sales_channel__in=channels)
        bk_b = {r['purchase__branch_id']: (Decimal(r['l']) / Decimal(r['i']))
                for r in lb.values('purchase__branch_id').annotate(l=Count('id'), i=Count('purchase', distinct=True)) if r['i']}
        bk_u = {r['purchase__softech_user']: (Decimal(r['l']) / Decimal(r['i']))
                for r in lb.exclude(purchase__softech_user='').values('purchase__softech_user')
                .annotate(l=Count('id'), i=Count('purchase', distinct=True)) if (r['i'] or 0) >= ctx.min_active}
        return vb, vu, bk_b, bk_u

    for seg_ar, seg_en, channels in [('استلام مباشر', 'walk-in', ctx.walkin_channels),
                                     ('التوصيل', 'delivery', ctx.delivery_channels)]:
        vb, vu, bk_b, bk_u = group(channels)
        r = _ranking(ctx, 'segment_rankings', f'💰 ترتيب الفروع في قيمة {seg_ar}', f'Branch {seg_en}-value ranking',
                     [(ctx.bn(bmap[b], 'ar'), ctx.bn(bmap[b], 'en'), v) for b, v in vb.items() if b in bmap])
        if r: out.append(r)
        r = _ranking(ctx, 'segment_rankings', f'💰 ترتيب مسئولي البيع في قيمة {seg_ar}', f'Salesperson {seg_en}-value ranking',
                     [(ctx.rep(u), ctx.rep(u), v) for u, v in vu.items() if u not in ctx.cc_agents])
        if r: out.append(r)
        r = _basket_rank_finding(ctx, 'segment_rankings', f'🧺 ترتيب الفروع في متوسط سلة {seg_ar}', f'Branch {seg_en} basket-size',
                     [(ctx.bn(bmap[b], 'ar'), ctx.bn(bmap[b], 'en'), v) for b, v in bk_b.items() if b in bmap])
        if r: out.append(r)
        r = _basket_rank_finding(ctx, 'segment_rankings', f'🧺 ترتيب مسئولي البيع في متوسط سلة {seg_ar}', f'Salesperson {seg_en} basket-size',
                     [(ctx.rep(u), ctx.rep(u), v) for u, v in bk_u.items() if u not in ctx.cc_agents])
        if r: out.append(r)
    return out


# ── Comparative rankings (deliberate, category-specific — NOT raw total sales) ─

def _branch_map(ctx):
    return {b.id: b for b in ctx.branches}


def rule_rank_cosmetics(ctx, threshold):
    """Leaderboard: branches by cosmetics sales (a deliberate push metric)."""
    if not ctx.beauty_types:
        return []
    from apps.customers.models import PurchaseHistoryLine
    bmap = _branch_map(ctx)

    def bty(doc):
        return dict(PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
            purchase__doc_code=doc, purchase__branch_id__in=ctx.branch_ids, purchase__sales_channel__in=ctx.nonexclude,
            item__medicine_type__in=ctx.beauty_types)
            .values_list('purchase__branch_id').annotate(v=Sum('line_total')))
    sale, ret = bty('115'), bty('30')   # net of returns
    net = {bid: Decimal(str(sale.get(bid, 0) or 0)) - Decimal(str(ret.get(bid, 0) or 0)) for bid in set(sale) | set(ret)}
    ranked = sorted(((bmap[bid], v) for bid, v in net.items() if bid in bmap and v), key=lambda x: -x[1])
    if not ranked:
        return []
    ar = ' · '.join(f'{i+1}) {ctx.bn(b,"ar")} {_fmt(v)}' for i, (b, v) in enumerate(ranked[:5]))
    en = ' · '.join(f'{i+1}) {ctx.bn(b,"en")} {_fmt(v)}' for i, (b, v) in enumerate(ranked[:5]))
    return [dict(rule_code='rank_cosmetics', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=ranked[0][1], baseline=None, threshold=None,
        message_ar=f'🧴 ترتيب الفروع في التجميل ({ctx.label()}): {ar} ج.م.',
        message_en=f'🧴 Cosmetics ranking ({ctx.pw_en()}): {en} EGP.')]


def rule_rank_delivery(ctx, threshold):
    """Leaderboard: branches by delivery TRANSACTION COUNT (count is size-fair-er than value)."""
    from apps.customers.models import PurchaseHistory
    bmap = _branch_map(ctx)
    rows = (PurchaseHistory.objects.filter(
                invoice_date__date__gte=ctx.start, invoice_date__date__lte=ctx.end,
                doc_code='115', sales_channel__in=ctx.delivery_channels, branch_id__in=ctx.branch_ids)
            .values_list('branch_id').annotate(c=Count('id')).order_by('-c'))
    ranked = [(bmap[bid], c) for bid, c in rows if bid in bmap and c]
    if not ranked:
        return []
    ar = ' · '.join(f'{i+1}) {ctx.bn(b,"ar")} ({c})' for i, (b, c) in enumerate(ranked[:5]))
    en = ' · '.join(f'{i+1}) {ctx.bn(b,"en")} ({c})' for i, (b, c) in enumerate(ranked[:5]))
    return [dict(rule_code='rank_delivery', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(ranked[0][1]), baseline=None, threshold=None,
        message_ar=f'🚚 ترتيب الفروع في عدد طلبات التوصيل ({ctx.label()}): {ar}.',
        message_en=f'🚚 Delivery orders ranking ({ctx.pw_en()}): {en}.')]


def rule_rank_salespeople(ctx, threshold):
    """Leaderboard: top salespeople by net sales (motivational; excludes CC agents)."""
    from apps.customers.models import PurchaseHistory
    rows = (PurchaseHistory.objects.filter(
                invoice_date__date__gte=ctx.start, invoice_date__date__lte=ctx.end,
                doc_code='115', branch_id__in=ctx.branch_ids)
            .exclude(softech_user='').values_list('softech_user').annotate(s=Sum('total_amount')).order_by('-s'))
    ranked = [(u, Decimal(str(s))) for u, s in rows if u not in ctx.cc_agents and s][:5]
    if not ranked:
        return []
    ar = ' · '.join(f'{i+1}) {ctx.rep(u)} {_fmt(v)}' for i, (u, v) in enumerate(ranked))
    en = ' · '.join(f'{i+1}) {ctx.rep(u)} {_fmt(v)}' for i, (u, v) in enumerate(ranked))
    return [dict(rule_code='rank_salespeople', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=ranked[0][1], baseline=None, threshold=None,
        message_ar=f'🏅 أفضل مسئولي البيع ({ctx.label()}): {ar} ج.م.',
        message_en=f'🏅 Top salespeople ({ctx.pw_en()}): {en} EGP.')]


def rule_branch_rankings(ctx, threshold):
    """Comparative BRANCH leaderboards (value + count): total net sales, cash sales value,
    delivery value, all transaction count, cash transaction count."""
    from apps.customers.models import PurchaseHistory
    bmap = _branch_map(ctx)
    out = []

    def emit(code_title, netmap=None, cnt_qs=None, is_count=False):
        title_ar, title_en = code_title
        if netmap is not None:
            data = [(ctx.bn(bmap[bid], 'ar'), ctx.bn(bmap[bid], 'en'), v)
                    for bid, v in netmap.items() if bid in bmap]
        else:
            data = [(ctx.bn(bmap[bid], 'ar'), ctx.bn(bmap[bid], 'en'), c)
                    for bid, c in cnt_qs if bid in bmap]
        r = _ranking(ctx, 'branch_rankings', title_ar, title_en, data, is_count=is_count)
        if r:
            out.append(r)

    emit(('💰 ترتيب الفروع في إجمالى المبيعات', 'Branch total-sales ranking'),
         netmap=_net_by_branch(ctx, ctx.start, ctx.end))
    emit(('💵 ترتيب الفروع في قيمة البيع النقدى', 'Branch cash-sales ranking'),
         netmap=_net_by_branch(ctx, ctx.start, ctx.end, channels=ctx.cash_channels))
    emit(('🚚 ترتيب الفروع في قيمة التوصيل', 'Branch delivery-value ranking'),
         netmap=_net_by_branch(ctx, ctx.start, ctx.end, channels=ctx.delivery_channels))
    emit(('🧾 ترتيب الفروع في عدد عمليات البيع', 'Branch transaction-count ranking'),
         cnt_qs=_ph(ctx, ctx.start, ctx.end).filter(doc_code='115').values_list('branch_id').annotate(c=Count('id')),
         is_count=True)
    emit(('💵 ترتيب الفروع في عدد عمليات البيع النقدى', 'Branch cash-transaction-count ranking'),
         cnt_qs=_cash_ph(ctx, ctx.start, ctx.end).values_list('branch_id').annotate(c=Count('id')),
         is_count=True)
    return out


def rule_salesperson_rankings(ctx, threshold):
    """Comparative SALESPERSON leaderboards on cash sales: cash-sales value, cash
    transaction count. (Excludes call-center agents.)"""
    out = []
    base = _cash_ph(ctx, ctx.start, ctx.end).filter(doc_code='115').exclude(softech_user='')
    val = [(ctx.rep(u), ctx.rep(u), v) for u, v in _net_by_user(ctx, ctx.cash_channels).items()
           if u not in ctx.cc_agents and v]   # net of returns
    r = _ranking(ctx, 'salesperson_rankings', '🏅 أفضل مسئولي البيع في البيع النقدى',
                 'Top salespeople — cash sales', val)
    if r:
        out.append(r)
    cnt = [(ctx.rep(u), ctx.rep(u), c)
           for u, c in base.values_list('softech_user').annotate(c=Count('id'))
           if u not in ctx.cc_agents and c]
    r = _ranking(ctx, 'salesperson_rankings', '🧾 ترتيب مسئولي البيع في عدد عمليات البيع النقدى',
                 'Salesperson cash-transaction-count ranking', cnt, is_count=True)
    if r:
        out.append(r)
    return out


def rule_bulk_cash_ranking(ctx, threshold):
    """Leaderboards by COUNT of bulk cash invoices (≥ threshold EGP) — branches and reps."""
    thr = Decimal(str(threshold if threshold is not None else ctx.bulk_cash_floor))
    bmap = _branch_map(ctx)
    qs = _cash_ph(ctx, ctx.start, ctx.end).filter(total_amount__gte=thr)
    out = []
    bdata = [(ctx.bn(bmap[bid], 'ar'), ctx.bn(bmap[bid], 'en'), c)
             for bid, c in qs.values_list('branch_id').annotate(c=Count('id')) if bid in bmap]
    r = _ranking(ctx, 'bulk_cash_ranking',
                 f'📦 ترتيب الفروع في عدد الفواتير النقدية الكبيرة (≥{_fmt(thr)})',
                 f'Branch bulk-cash-invoice count (≥{_fmt(thr)})', bdata, is_count=True)
    if r:
        out.append(r)
    sdata = [(ctx.rep(u), ctx.rep(u), c)
             for u, c in qs.exclude(softech_user='').values_list('softech_user').annotate(c=Count('id'))
             if u not in ctx.cc_agents and c]
    r = _ranking(ctx, 'bulk_cash_ranking',
                 '📦 ترتيب مسئولي البيع في عدد الفواتير النقدية الكبيرة',
                 'Salesperson bulk-cash-invoice count', sdata, is_count=True)
    if r:
        out.append(r)
    return out


def rule_basket_ranking(ctx, threshold):
    """Leaderboards by basket size (items/invoice) and average basket value, computed from
    CASH sales EXCLUDING big-ticket invoices (≥ basket_bulk_floor). Branches + reps."""
    from apps.customers.models import PurchaseHistoryLine
    floor = ctx.basket_bulk_floor
    base = PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
        purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
        purchase__sales_channel__in=ctx.cash_channels, purchase__total_amount__lt=floor)
    bmap = _branch_map(ctx)
    out = []

    def build(group_field, label_fn, min_invs, exclude_cc=False):
        rows = base.values(group_field).annotate(
            lines=Count('id'), invs=Count('purchase', distinct=True), val=Sum('line_total'))
        size, avgval = [], []
        for r in rows:
            key = r[group_field]; invs = r['invs'] or 0
            if invs < min_invs:
                continue
            if exclude_cc and key in ctx.cc_agents:
                continue
            lab = label_fn(key)
            if not lab:
                continue
            ipi = Decimal(r['lines']) / Decimal(invs)
            atv = Decimal(str(r['val'] or 0)) / Decimal(invs)
            size.append((lab[0], lab[1], ipi))
            avgval.append((lab[0], lab[1], atv))
        return size, avgval

    b_size, b_val = build('purchase__branch_id',
                          lambda k: (ctx.bn(bmap[k], 'ar'), ctx.bn(bmap[k], 'en')) if k in bmap else None, 100)
    s_size, s_val = build('purchase__softech_user',
                          lambda k: (ctx.rep(k), ctx.rep(k)) if k else None, 30, exclude_cc=True)
    for code, ta, te, data, cnt in [
        ('basket_ranking', '🧺 ترتيب الفروع في متوسط أصناف الفاتورة', 'Branch basket-size (items/invoice)', b_size, True),
        ('basket_ranking', '🧺 ترتيب الفروع في متوسط قيمة الفاتورة', 'Branch avg basket value', b_val, False),
        ('basket_ranking', '🧺 ترتيب مسئولي البيع في متوسط أصناف الفاتورة', 'Salesperson basket-size (items/invoice)', s_size, True),
        ('basket_ranking', '🧺 ترتيب مسئولي البيع في متوسط قيمة الفاتورة', 'Salesperson avg basket value', s_val, False),
    ]:
        if cnt:   # items/invoice: show 1-decimal, no money unit
            ranked = sorted((x for x in data if x[2]), key=lambda x: -float(x[2]))[:5]
            if not ranked:
                continue
            ar = ' · '.join(f'{i+1}) {la} {float(v):.1f}' for i, (la, le, v) in enumerate(ranked))
            en = ' · '.join(f'{i+1}) {le} {float(v):.1f}' for i, (la, le, v) in enumerate(ranked))
            out.append(dict(rule_code=code, category='highlight', severity='info',
                scope_type='chain', scope_key='', scope_label='', value=Decimal(str(round(float(ranked[0][2]), 2))),
                baseline=None, threshold=None,
                message_ar=f'{ta} ({ctx.label()}): {ar} صنف.',
                message_en=f'{te} ({ctx.pw_en()}): {en} items.'))
        else:
            r = _ranking(ctx, code, ta, te, data)
            if r:
                out.append(r)
    return out


# ── Customer analytics: new vs returning ─────────────────────────────────────

def rule_customer_mix(ctx, threshold):
    """New vs returning customers (PIC) per branch and per salesperson — rankings + a
    per-branch mix line (for branch reports). New = PIC whose first-ever purchase is in
    the period (not seen chain-wide before ctx.start)."""
    from collections import defaultdict
    from apps.customers.models import PurchaseHistory
    triples = (_ph(ctx, ctx.start, ctx.end).filter(doc_code='115').exclude(softech_phcode='')
               .values_list('branch_id', 'softech_user', 'softech_phcode').distinct())
    br_pics = defaultdict(set); us_pics = defaultdict(set); all_pics = set()
    for bid, u, pic in triples:
        br_pics[bid].add(pic)
        if u:
            us_pics[u].add(pic)
        all_pics.add(pic)
    if not all_pics:
        return []
    prior = set(PurchaseHistory.objects.filter(
        invoice_date__date__lt=ctx.start, doc_code='115').exclude(softech_phcode='')
        .values_list('softech_phcode', flat=True).distinct())
    bmap = _branch_map(ctx)
    out = []
    b_new, b_ret, per_branch = [], [], {}
    for bid, pics in br_pics.items():
        if bid not in bmap:
            continue
        new = len(pics - prior); ret = len(pics & prior)
        b = bmap[bid]
        b_new.append((ctx.bn(b, 'ar'), ctx.bn(b, 'en'), new))
        b_ret.append((ctx.bn(b, 'ar'), ctx.bn(b, 'en'), ret))
        per_branch[bid] = (new, ret)
    s_new, s_ret = [], []
    for u, pics in us_pics.items():
        if u in ctx.cc_agents:
            continue
        s_new.append((ctx.rep(u), ctx.rep(u), len(pics - prior)))
        s_ret.append((ctx.rep(u), ctx.rep(u), len(pics & prior)))
    for args in [
        ('🆕 ترتيب الفروع في العملاء الجدد', 'Branch new-customers ranking', b_new),
        ('🔁 ترتيب الفروع في العملاء العائدين', 'Branch returning-customers ranking', b_ret),
        ('🆕 ترتيب مسئولي البيع في العملاء الجدد', 'Salesperson new-customers ranking', s_new),
        ('🔁 ترتيب مسئولي البيع في العملاء العائدين', 'Salesperson returning-customers ranking', s_ret),
    ]:
        r = _ranking(ctx, 'customer_mix', *args, is_count=True)
        if r:
            out.append(r)
    for bid, (new, ret) in per_branch.items():
        tot = new + ret
        if tot < 1:
            continue
        b = bmap[bid]; mix = Decimal(new) / Decimal(tot) * 100
        out.append(dict(rule_code='customer_mix', category='comparison', severity='info',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'),
            value=Decimal(new), baseline=Decimal(ret), threshold=None,
            message_ar=f'👥 {ctx.bn(b,"ar")}: عملاء جدد {new} · عائدون {ret} · نسبة الجدد {mix:.0f}% خلال ال{ctx.label()}.',
            message_en=f'👥 {ctx.bn(b,"en")}: {new} new · {ret} returning · {mix:.0f}% new-mix this {ctx.pw_en()}.'))
    return out


def rule_cross_sell_pairs(ctx, threshold):
    """BRANCH-SPECIFIC companion suggestions: the item-pairs most often bought together at
    EACH branch (cash sales) — so a branch pushes the pairs that actually move for it — plus
    a compact chain summary (top pairs with attach% and the cross-sell miss)."""
    from collections import Counter, defaultdict
    from apps.customers.models import PurchaseHistoryLine
    from apps.catalog.models import Item
    rows = (PurchaseHistoryLine.objects.filter(
                purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
                purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
                purchase__sales_channel__in=ctx.cash_channels, item_id__isnull=False)
            .exclude(item_id__in=ctx.excluded_item_ids)
            .values_list('purchase_id', 'purchase__branch_id', 'item_id'))
    inv_items = defaultdict(set); inv_branch = {}
    for pid, bid, iid in rows.iterator():
        inv_items[pid].add(iid); inv_branch[pid] = bid
    bpair = defaultdict(Counter); chain_pair = Counter(); chain_item = Counter()
    for pid, items in inv_items.items():
        bid = inv_branch[pid]
        for iid in items:
            chain_item[iid] += 1
        for a, b in itertools.combinations(sorted(items), 2):
            bpair[bid][(a, b)] += 1; chain_pair[(a, b)] += 1
    if not chain_pair:
        return []
    bmap = _branch_map(ctx)
    chain_top = chain_pair.most_common(5)
    branch_top = {bid: pc.most_common(3) for bid, pc in bpair.items() if bid in bmap}
    need = {i for (a, b), _ in chain_top for i in (a, b)}
    for tp in branch_top.values():
        need.update(i for (a, b), _ in tp for i in (a, b))
    names = dict(Item.objects.filter(id__in=need).values_list('id', 'name'))
    nm = lambda i: names.get(i, str(i))
    out = []
    # compact chain summary (top pairs) — highlight for the board
    ar = ' · '.join(f'«{nm(a)}»+«{nm(b)}» ({c})' for (a, b), c in chain_top)
    en = ' · '.join(f'“{nm(a)}”+“{nm(b)}” ({c})' for (a, b), c in chain_top)
    out.append(dict(rule_code='cross_sell_pairs', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(chain_top[0][1]), baseline=None, threshold=None,
        message_ar=f'🔗 أزواج البيع المتقاطع الأكثر تكراراً ({ctx.label()}): {ar}.',
        message_en=f'🔗 Most frequent cross-sell pairs ({ctx.pw_en()}): {en}.'))
    # per-branch companion suggestions (surfaced in each branch report)
    for bid, tp in branch_top.items():
        b = bmap[bid]
        pa = ' · '.join(f'«{nm(a)}»+«{nm(b)}» ({c})' for (a, b), c in tp)
        pe = ' · '.join(f'“{nm(a)}”+“{nm(b)}” ({c})' for (a, b), c in tp)
        out.append(dict(rule_code='cross_sell_pairs', category='mix', severity='info',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'),
            value=Decimal(tp[0][1]), baseline=None, threshold=None,
            message_ar=f'🔗 {ctx.bn(b,"ar")}: أزواج مقترحة للبيع المتقاطع — {pa}.',
            message_en=f'🔗 {ctx.bn(b,"en")}: suggested cross-sell pairs — {pe}.'))
    return out


def rule_branch_standings(ctx, threshold):
    """Per-branch standing: where each branch ranks across the key metrics. One finding per
    branch (scope_key=branch) → surfaced in that branch's own report."""
    bmap = _branch_map(ctx)
    txn = dict(_ph(ctx, ctx.start, ctx.end).filter(doc_code='115').values_list('branch_id').annotate(c=Count('id')))
    metrics = [
        ('إجمالى المبيعات', 'total sales', _net_by_branch(ctx, ctx.start, ctx.end)),
        ('البيع النقدى', 'cash', _net_by_branch(ctx, ctx.start, ctx.end, channels=ctx.cash_channels)),
        ('التوصيل', 'delivery', _net_by_branch(ctx, ctx.start, ctx.end, channels=ctx.delivery_channels)),
        ('عدد العمليات', 'transactions', txn),
    ]
    ranks = {}
    for la, le, mp in metrics:
        ordered = sorted(((bid, v) for bid, v in mp.items() if bid in bmap), key=lambda x: -float(x[1]))
        n = len(ordered)
        for i, (bid, v) in enumerate(ordered, 1):
            ranks.setdefault(bid, []).append((la, le, i, n))
    out = []
    for bid, items in ranks.items():
        b = bmap[bid]
        ar = ' · '.join(f'{la} #{i}/{n}' for la, le, i, n in items)
        en = ' · '.join(f'{le} #{i}/{n}' for la, le, i, n in items)
        out.append(dict(rule_code='branch_standings', category='comparison', severity='info',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'),
            value=Decimal(items[0][2]), baseline=None, threshold=None,
            message_ar=f'📊 ترتيب فرعك بين الفروع ({ctx.label()}): {ar}.',
            message_en=f'📊 Your branch rank among branches ({ctx.pw_en()}): {en}.'))
    return out


def rule_salesperson_standings(ctx, threshold):
    """Per-salesperson standing across cash value, transaction count and basket size — one
    finding per ACTIVE rep (scope_key=usercode) for rep-level (WhatsApp) reports."""
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    base = _cash_ph(ctx, ctx.start, ctx.end).filter(doc_code='115').exclude(softech_user='')
    cashval = dict(base.values_list('softech_user').annotate(v=Sum('total_amount')))
    txn = dict(base.values_list('softech_user').annotate(c=Count('id')))
    brows = (PurchaseHistoryLine.objects.filter(
                purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
                purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
                purchase__sales_channel__in=ctx.cash_channels, purchase__total_amount__lt=ctx.basket_bulk_floor)
            .exclude(purchase__softech_user='')
            .values('purchase__softech_user').annotate(lines=Count('id'), invs=Count('purchase', distinct=True)))
    basket = {r['purchase__softech_user']: (Decimal(r['lines']) / Decimal(r['invs']))
              for r in brows if (r['invs'] or 0) >= 1}
    active = [u for u, c in txn.items() if c >= 30 and u not in ctx.cc_agents]
    if not active:
        return []
    metrics = [('البيع النقدى', 'cash sales', {u: Decimal(str(cashval.get(u, 0) or 0)) for u in active}),
               ('عدد العمليات', 'transactions', {u: Decimal(txn.get(u, 0)) for u in active}),
               ('متوسط السلة', 'basket size', {u: basket.get(u, Decimal('0')) for u in active})]
    ranks = {}
    for la, le, mp in metrics:
        ordered = sorted(mp.items(), key=lambda x: -float(x[1]))
        n = len(ordered)
        for i, (u, v) in enumerate(ordered, 1):
            ranks.setdefault(u, []).append((la, le, i, n))
    out = []
    for u, items in ranks.items():
        ar = ' · '.join(f'{la} #{i}/{n}' for la, le, i, n in items)
        en = ' · '.join(f'{le} #{i}/{n}' for la, le, i, n in items)
        out.append(dict(rule_code='salesperson_standings', category='comparison', severity='info',
            scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
            value=Decimal(items[0][2]), baseline=None, threshold=None,
            message_ar=f'📊 ترتيبك بين مسئولي البيع ({ctx.label()}): {ar}.',
            message_en=f'📊 Your rank among salespeople ({ctx.pw_en()}): {en}.'))
    return out


def rule_salesperson_profile(ctx, threshold):
    """COMPREHENSIVE personalized salesperson stats (for the per-rep report): sales value +
    cash + transactions + units, basket + avg invoice, customers (served/new/returning),
    quality (beauty%/returns%/discount%/عميل-دائم%), growth vs prev, and rankings BACKED BY
    values (rep value · peer average · leader value) + target achievement."""
    from collections import defaultdict
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    D = lambda x: Decimal(str(x or 0))
    ph = _ph(ctx, ctx.start, ctx.end)
    sales = dict(ph.filter(doc_code='115').exclude(softech_user='').values_list('softech_user').annotate(v=Sum('total_amount')))
    rets = dict(ph.filter(doc_code='30').exclude(softech_user='').values_list('softech_user').annotate(v=Sum('total_amount')))
    txn = dict(ph.filter(doc_code='115').exclude(softech_user='').values_list('softech_user').annotate(c=Count('id')))
    net = {u: D(sales.get(u, 0)) - D(rets.get(u, 0)) for u in set(sales) | set(rets)}
    prevph = _ph(ctx, ctx.prev_start, ctx.prev_end)
    ps = dict(prevph.filter(doc_code='115').exclude(softech_user='').values_list('softech_user').annotate(v=Sum('total_amount')))
    pr = dict(prevph.filter(doc_code='30').exclude(softech_user='').values_list('softech_user').annotate(v=Sum('total_amount')))
    prev_net = {u: D(ps.get(u, 0)) - D(pr.get(u, 0)) for u in set(ps) | set(pr)}
    cashph = _cash_ph(ctx, ctx.start, ctx.end).filter(doc_code='115').exclude(softech_user='')
    cashval = _net_by_user(ctx, ctx.cash_channels)          # net of returns
    cashtxn = dict(cashph.values_list('softech_user').annotate(c=Count('id')))
    regval = _net_by_user(ctx, ctx.regular_channels)
    walkval = _net_by_user(ctx, ctx.walkin_channels)
    delval = _net_by_user(ctx, ctx.delivery_channels)
    deltxn = dict(cashph.filter(sales_channel__in=ctx.delivery_channels).values_list('softech_user').annotate(c=Count('id')))
    btyval = btytxn = {}
    if ctx.beauty_types:
        def _bty(doc):
            return dict(PurchaseHistoryLine.objects.filter(
                purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
                purchase__doc_code=doc, purchase__branch_id__in=ctx.branch_ids,
                purchase__sales_channel__in=ctx.cash_channels, item__medicine_type__in=ctx.beauty_types)
                .exclude(purchase__softech_user='').values_list('purchase__softech_user').annotate(v=Sum('line_total')))
        bs, br = _bty('115'), _bty('30')
        btyval = {u: D(bs.get(u, 0)) - D(br.get(u, 0)) for u in set(bs) | set(br)}
        btytxn = dict(PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
            purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
            purchase__sales_channel__in=ctx.cash_channels, item__medicine_type__in=ctx.beauty_types)
            .exclude(purchase__softech_user='').values_list('purchase__softech_user').annotate(t=Count('purchase', distinct=True)))
    units = dict(PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
        purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids, purchase__sales_channel__in=ctx.nonexclude)
        .exclude(purchase__softech_user='').values_list('purchase__softech_user').annotate(q=Sum('quantity')))
    # basket (cash excl bulk)
    brows = (PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
        purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
        purchase__sales_channel__in=ctx.cash_channels, purchase__total_amount__lt=ctx.basket_bulk_floor)
        .exclude(purchase__softech_user='').values('purchase__softech_user')
        .annotate(lines=Count('id'), invs=Count('purchase', distinct=True), val=Sum('line_total')))
    ipi = {}; atv = {}
    for r in brows:
        u = r['purchase__softech_user']; iv = r['invs'] or 0
        if iv:
            ipi[u] = D(r['lines']) / D(iv); atv[u] = D(r['val']) / D(iv)
    # discount (cash+regular gross vs paid)
    gross = ExpressionWrapper(F('list_price') * F('quantity'), output_field=DecimalField(max_digits=18, decimal_places=4))
    drows = (PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
        purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
        purchase__sales_channel__in=ctx.cash_channels, list_price__gt=0)
        .exclude(purchase__softech_user='').values('purchase__softech_user').annotate(g=Sum(gross), n=Sum('line_total')))
    drows = list(drows)
    disc = {r['purchase__softech_user']: ((D(r['g']) - D(r['n'])) / D(r['g']) * 100) for r in drows if D(r['g']) > 0}
    discval = {r['purchase__softech_user']: (D(r['g']) - D(r['n'])) for r in drows}
    # customers served / new / returning
    us_pics = defaultdict(set)
    for u, pic in ph.filter(doc_code='115').exclude(softech_phcode='').values_list('softech_user', 'softech_phcode').distinct():
        if u:
            us_pics[u].add(pic)
    prior = set(PurchaseHistory.objects.filter(invoice_date__date__lt=ctx.start, doc_code='115')
                .exclude(softech_phcode='').values_list('softech_phcode', flat=True).distinct())
    # beauty attach
    tot_inv = dict(ph.filter(doc_code='115').exclude(softech_user='').values_list('softech_user').annotate(n=Count('id')))
    bty = {}
    if ctx.beauty_types:
        bty = dict(PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
            purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids, purchase__sales_channel__in=ctx.nonexclude,
            item__medicine_type__in=ctx.beauty_types).exclude(purchase__softech_user='')
            .values_list('purchase__softech_user').annotate(n=Count('purchase', distinct=True)))
    # profit + productivity
    pu = _profit_by_user(ctx)
    from django.db.models.functions import ExtractHour
    hrs = {}
    for r in (ph.filter(doc_code='115', trans_time__isnull=False).exclude(softech_user='')
              .annotate(h=ExtractHour('trans_time')).values('softech_user', 'h').distinct()):
        hrs[r['softech_user']] = hrs.get(r['softech_user'], 0) + 1
    # active reps (period-aware minimum so daily lists everyone who worked that day)
    active = [u for u, c in txn.items() if (c or 0) >= ctx.min_active and u not in ctx.cc_agents]
    if not active:
        return []

    def rank(dmap):
        ordered = sorted(((u, float(dmap.get(u, 0) or 0)) for u in active), key=lambda x: -x[1])
        n = len(ordered)
        avg = sum(v for _, v in ordered) / n if n else 0
        pos = {u: i + 1 for i, (u, _) in enumerate(ordered)}
        return pos, n, avg, (ordered[0][1] if ordered else 0)
    rnet, N, net_avg, net_lead = rank(net)
    rcash, _, cash_avg, cash_lead = rank(cashval)
    rtxn, _, txn_avg, _ = rank(txn)
    rbask, _, bask_avg, _ = rank(ipi)
    rprof, _, prof_avg, prof_lead = rank(pu)
    net_sorted = sorted(active, key=lambda u: -float(net.get(u, 0) or 0))
    above = {net_sorted[i]: net_sorted[i - 1] for i in range(1, len(net_sorted))}   # rep just ahead of you
    # target achievement (committed salesperson scenario)
    tgt = {}
    scen = _committed_scenario(ctx, 'salesperson')
    if scen:
        from apps.forecasting.models import ForecastResult
        ty, tm, ms, me, factor = _target_month_slice(ctx)
        for x in ForecastResult.objects.filter(scenario=scen, metric='cash_delivery'):
            if x.target_value:
                tgt[x.scope_key] = D(x.target_value) * factor

    out = []
    for u in active:
        rep = ctx.rep(u)
        served = len(us_pics.get(u, set())); new = len(us_pics.get(u, set()) - prior); ret = served - new
        ti = tot_inv.get(u, 0); ba = (D(bty.get(u, 0)) / D(ti) * 100) if ti else Decimal('0')
        rr = (D(rets.get(u, 0)) / D(sales.get(u, 0)) * 100) if sales.get(u) else Decimal('0')
        regsh = (D(regval.get(u, 0)) / D(cashval.get(u, 0)) * 100) if cashval.get(u) else Decimal('0')
        p = prev_net.get(u, Decimal('0'))
        grow = ((net.get(u, Decimal('0')) - p) / p * 100) if p > 0 else None
        base = dict(scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {rep}',
                    value=net.get(u, Decimal('0')), baseline=None, threshold=None)
        out.append(dict(base, rule_code='salesperson_profile', category='volume', severity='info',
            message_ar=f'💰 أرقامك ({ctx.label()}): صافي المبيعات {_fmt(net.get(u,0))} ج.م (نقدى {_fmt(cashval.get(u,0))}) · {txn.get(u,0)} عملية · {_fmt(units.get(u,0))} وحدة مباعة.',
            message_en=f'💰 Your numbers ({ctx.pw_en()}): net sales {_fmt(net.get(u,0))} EGP (cash {_fmt(cashval.get(u,0))}) · {txn.get(u,0)} txns · {_fmt(units.get(u,0))} units.'))
        out.append(dict(base, rule_code='salesperson_profile', category='volume', severity='info',
            message_ar=f'🧺 سلتك: {float(ipi.get(u,0)):.1f} صنف/فاتورة · متوسط الفاتورة {_fmt(atv.get(u,0))} ج.م (نقدى بدون الجملة).',
            message_en=f'🧺 Basket: {float(ipi.get(u,0)):.1f} items/invoice · avg invoice {_fmt(atv.get(u,0))} EGP (cash, ex-bulk).'))
        out.append(dict(base, rule_code='salesperson_profile', category='mix', severity='info',
            message_ar=f'👥 عملاؤك: {served} عميل ({new} جديد · {ret} عائد) · نسبة التجميل {float(ba):.0f}% · مرتجعات {float(rr):.0f}% · الخصم النقدى {float(disc.get(u,0)):.0f}% بقيمة {_fmt(discval.get(u,0))} ج.م · عميل دائم {float(regsh):.0f}%.',
            message_en=f'👥 Customers: {served} ({new} new · {ret} returning) · beauty {float(ba):.0f}% · returns {float(rr):.0f}% · cash discount {float(disc.get(u,0)):.0f}% ({_fmt(discval.get(u,0))} EGP) · regular-share {float(regsh):.0f}%.'))
        out.append(dict(base, rule_code='salesperson_profile', category='volume', severity='info',
            message_ar=f'🧩 قنواتك: استلام مباشر {_fmt(walkval.get(u,0))} ج.م · توصيل {_fmt(delval.get(u,0))} ({deltxn.get(u,0)} عملية) · تجميل نقدى {_fmt(btyval.get(u,0))} ({btytxn.get(u,0)} فاتورة).',
            message_en=f'🧩 Channels: walk-in {_fmt(walkval.get(u,0))} EGP · delivery {_fmt(delval.get(u,0))} ({deltxn.get(u,0)} txns) · beauty cash {_fmt(btyval.get(u,0))} ({btytxn.get(u,0)} invoices).'))
        prof = pu.get(u, Decimal('0')); marg = (prof / net.get(u, Decimal('0')) * 100) if net.get(u, 0) > 0 else Decimal('0')
        wh = hrs.get(u, 0); sph = (net.get(u, Decimal('0')) / Decimal(wh)) if wh else Decimal('0')
        out.append(dict(base, rule_code='salesperson_profile', category='volume', severity='info',
            message_ar=f'💎 ربحيتك: ربح {_fmt(prof)} ج.م · هامش {float(marg):.0f}% · مبيعات/ساعة {_fmt(sph)} ج.م ({wh} ساعة عمل).',
            message_en=f'💎 Profitability: profit {_fmt(prof)} EGP · margin {float(marg):.0f}% · sales/hour {_fmt(sph)} EGP ({wh} active hrs).'))
        gtxt_ar = f' · النمو {"+" if (grow or 0)>=0 else ""}{float(grow):.0f}% عن الفترة السابقة' if grow is not None else ''
        gtxt_en = f' · growth {"+" if (grow or 0)>=0 else ""}{float(grow):.0f}% vs prev' if grow is not None else ''
        atxt_ar = atxt_en = ''
        if u in tgt and tgt[u] > 0:
            ach = float(D(cashval.get(u, 0)) / tgt[u] * 100)
            atxt_ar = f' · تحقيق الهدف {ach:.0f}%'; atxt_en = f' · target {ach:.0f}%'
        if u in above:
            gap = net.get(above[u], Decimal('0')) - net.get(u, Decimal('0'))
            atxt_ar += f' · 🎯 تحتاج {_fmt(gap)} ج.م لتتخطى {ctx.rep(above[u])} (#{rnet[u]-1})'
            atxt_en += f' · 🎯 need {_fmt(gap)} EGP to pass {ctx.rep(above[u])} (#{rnet[u]-1})'
        out.append(dict(base, rule_code='salesperson_profile', category='comparison', severity='info',
            message_ar=(f'🏅 ترتيبك: المبيعات #{rnet[u]}/{N} ({_fmt(net.get(u,0))} · متوسط الزملاء {_fmt(net_avg)} · الأول {_fmt(net_lead)}) · '
                        f'الربح #{rprof[u]}/{N} ({_fmt(pu.get(u,0))} · المتوسط {_fmt(prof_avg)}) · '
                        f'النقدى #{rcash[u]}/{N} · العمليات #{rtxn[u]}/{N} · السلة #{rbask[u]}/{N}{gtxt_ar}{atxt_ar}.'),
            message_en=(f'🏅 Your rank: sales #{rnet[u]}/{N} ({_fmt(net.get(u,0))} · peer avg {_fmt(net_avg)} · leader {_fmt(net_lead)}) · '
                        f'profit #{rprof[u]}/{N} ({_fmt(pu.get(u,0))} · avg {_fmt(prof_avg)}) · '
                        f'cash #{rcash[u]}/{N} · txns #{rtxn[u]}/{N} · basket #{rbask[u]}/{N}{gtxt_en}{atxt_en}.')))
    return out


def _pct_rank_finding(ctx, code, title_ar, title_en, data):
    """Ranking finding for a percentage metric. data=[(label_ar, label_en, pct)]."""
    ranked = sorted((x for x in data if x[2] is not None), key=lambda x: -float(x[2]))[:5]
    if not ranked:
        return None
    ar = ' · '.join(f'{i+1}) {la} {float(v):.0f}%' for i, (la, le, v) in enumerate(ranked))
    en = ' · '.join(f'{i+1}) {le} {float(v):.0f}%' for i, (la, le, v) in enumerate(ranked))
    return dict(rule_code=code, category='highlight', severity='info', scope_type='chain', scope_key='', scope_label='',
        value=Decimal(str(round(float(ranked[0][2]), 1))), baseline=None, threshold=None,
        message_ar=f'{title_ar} ({ctx.label()}): {ar}.', message_en=f'{title_en} ({ctx.pw_en()}): {en}.')


def rule_profit_rankings(ctx, threshold):
    """Leaderboards by GROSS PROFIT (not revenue) and by MARGIN % — branches and reps.
    Profit rewards selling high-margin items, not just high revenue."""
    bmap = _branch_map(ctx)
    out = []
    pb = _profit_by_branch(ctx, ctx.start, ctx.end); nb = _net_by_branch(ctx, ctx.start, ctx.end)
    r = _ranking(ctx, 'profit_rankings', '💎 ترتيب الفروع في الربح', 'Branch gross-profit ranking',
                 [(ctx.bn(bmap[b], 'ar'), ctx.bn(bmap[b], 'en'), v) for b, v in pb.items() if b in bmap])
    if r: out.append(r)
    r = _pct_rank_finding(ctx, 'profit_rankings', '📐 ترتيب الفروع في هامش الربح', 'Branch margin% ranking',
                 [(ctx.bn(bmap[b], 'ar'), ctx.bn(bmap[b], 'en'), pb.get(b, 0) / nb[b] * 100) for b in nb if b in bmap and nb[b] > 0])
    if r: out.append(r)
    pu = _profit_by_user(ctx); nu = _net_by_user(ctx, ctx.nonexclude)
    r = _ranking(ctx, 'profit_rankings', '💎 أفضل مسئولي البيع في الربح', 'Top salespeople by profit',
                 [(ctx.rep(u), ctx.rep(u), v) for u, v in pu.items() if u not in ctx.cc_agents])
    if r: out.append(r)
    r = _pct_rank_finding(ctx, 'profit_rankings', '📐 ترتيب مسئولي البيع في هامش الربح', 'Salesperson margin% ranking',
                 [(ctx.rep(u), ctx.rep(u), pu[u] / nu[u] * 100) for u in pu if u not in ctx.cc_agents and nu.get(u, 0) > 20000])
    if r: out.append(r)
    return out


# ── Sales-boost opportunity sizing (quantified upside, not just flags) ─────────

def _median(vals):
    v = sorted(float(x) for x in vals)
    n = len(v)
    if not n:
        return 0.0
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def rule_basket_uplift(ctx, threshold):
    """Quantifies the EGP upside if below-median-basket salespeople reached the chain median
    basket (cash, ex-bulk): uplift = (median − basket) × invoices × avg item value."""
    from apps.customers.models import PurchaseHistoryLine
    rows = (PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
        purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
        purchase__sales_channel__in=ctx.cash_channels, purchase__total_amount__lt=ctx.basket_bulk_floor)
        .exclude(purchase__softech_user='').values('purchase__softech_user')
        .annotate(lines=Count('id'), invs=Count('purchase', distinct=True), val=Sum('line_total')))
    reps = {r['purchase__softech_user']: r for r in rows
            if (r['invs'] or 0) >= ctx.min_active and r['purchase__softech_user'] not in ctx.cc_agents}
    if not reps:
        return []
    baskets = {u: (r['lines'] / r['invs']) for u, r in reps.items()}
    med = _median(baskets.values())
    if med <= 0:
        return []
    upl = {}
    for u, r in reps.items():
        gap = med - baskets[u]
        if gap > 0:
            avg_item = (float(r['val']) / r['lines']) if r['lines'] else 0
            upl[u] = Decimal(str(gap * r['invs'] * avg_item))
    total = sum(upl.values(), Decimal('0'))
    if total <= 0:
        return []
    top = sorted(upl.items(), key=lambda x: -x[1])[:5]
    lst = ' · '.join(f'{ctx.rep(u)} {_fmt(v)}' for u, v in top)
    return [dict(rule_code='basket_uplift', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=total, baseline=None, threshold=None,
        message_ar=f'🎯 فرصة رفع السلة ({ctx.label()}): +{_fmt(total)} ج.م لو وصل مسئولو البيع تحت المتوسط لمتوسط السلة ({med:.1f} صنف/فاتورة) — أكبر الفرص: {lst}.',
        message_en=f'🎯 Basket-uplift opportunity ({ctx.pw_en()}): +{_fmt(total)} EGP if below-median reps reached the median basket ({med:.1f} items/inv) — biggest: {lst}.')]


def rule_lapsed_customers(ctx, threshold):
    """Win-back: regular customers (PIC) who bought repeatedly in the prior quarter but have
    NOT purchased in the last ~60 days — chain total + per-branch counts (for branch reports)."""
    from collections import defaultdict
    from apps.customers.models import PurchaseHistory
    from datetime import timedelta as _td
    recent_from = ctx.end - _td(days=60)
    before_from = ctx.end - _td(days=240)
    before = (PurchaseHistory.objects.filter(
        invoice_date__date__gte=before_from, invoice_date__date__lt=recent_from,
        doc_code='115', branch_id__in=ctx.branch_ids).exclude(softech_phcode=''))
    cnt = defaultdict(int); pic_branch = {}
    for pic, bid in before.values_list('softech_phcode', 'branch_id'):
        cnt[pic] += 1
        pic_branch.setdefault(pic, defaultdict(int))
        pic_branch[pic][bid] += 1
    regulars = {p for p, c in cnt.items() if c >= 3}          # bought ≥3× in the prior window
    if not regulars:
        return []
    recent = set(PurchaseHistory.objects.filter(
        invoice_date__date__gte=recent_from, invoice_date__date__lte=ctx.end,
        doc_code='115').exclude(softech_phcode='').values_list('softech_phcode', flat=True).distinct())
    lapsed = regulars - recent
    if not lapsed:
        return []
    bmap = _branch_map(ctx)
    by_branch = defaultdict(int)
    for pic in lapsed:
        home = max(pic_branch[pic].items(), key=lambda x: x[1])[0]
        by_branch[home] += 1
    out = [dict(rule_code='lapsed_customers', category='comparison', severity='warning',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(len(lapsed)), baseline=None, threshold=None,
        message_ar=f'🔚 عملاء متوقفون: {len(lapsed)} عميل كان منتظماً ولم يشترِ منذ 60 يوماً — فرصة استرجاع.',
        message_en=f'🔚 Lapsed customers: {len(lapsed)} once-regular PICs with no purchase in 60 days — win-back opportunity.')]
    for bid, n in by_branch.items():
        if bid not in bmap or n < 5:
            continue
        b = bmap[bid]
        out.append(dict(rule_code='lapsed_customers', category='comparison', severity='info',
            scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'),
            value=Decimal(n), baseline=None, threshold=None,
            message_ar=f'🔚 {ctx.bn(b,"ar")}: {n} عميل منتظم توقّف عن الشراء (60 يوماً) — قائمة استرجاع.',
            message_en=f'🔚 {ctx.bn(b,"en")}: {n} regulars lapsed (60 days) — win-back list.'))
    return out


def rule_category_penetration(ctx, threshold):
    """Beauty penetration gap: branches whose beauty share is below the chain average by
    ≥ threshold points → push opportunity, sized in EGP."""
    thr = Decimal(str(threshold if threshold is not None else 3))
    if not ctx.beauty_types:
        return []
    from apps.customers.models import PurchaseHistoryLine
    tot = _net_by_branch(ctx, ctx.start, ctx.end)
    bty = dict(PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=ctx.start, purchase__invoice_date__date__lte=ctx.end,
        purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids, purchase__sales_channel__in=ctx.nonexclude,
        item__medicine_type__in=ctx.beauty_types).values_list('purchase__branch_id').annotate(v=Sum('line_total')))
    ct = sum(tot.values(), Decimal('0')); cb = sum(Decimal(str(v or 0)) for v in bty.values())
    if ct <= 0:
        return []
    chain_share = cb / ct * 100
    bmap = _branch_map(ctx)
    out = []
    for bid, t in tot.items():
        if bid not in bmap or t <= 0:
            continue
        share = Decimal(str(bty.get(bid, 0) or 0)) / t * 100
        gap = chain_share - share
        if gap >= thr:
            egp = gap / 100 * t
            out.append(dict(rule_code='category_penetration', category='mix', severity='warning',
                scope_type='branch', scope_key=bmap[bid].code, scope_label=ctx.bn(bmap[bid], 'ar'),
                value=Decimal(str(round(float(share), 1))), baseline=Decimal(str(round(float(chain_share), 1))), threshold=thr,
                message_ar=f'💄 فجوة التجميل: {ctx.bn(bmap[bid],"ar")} نسبته {share:.0f}% مقابل متوسط الشبكة {chain_share:.0f}% — فرصة ~{_fmt(egp)} ج.م.',
                message_en=f'💄 Beauty gap: {ctx.bn(bmap[bid],"en")} at {share:.0f}% vs chain {chain_share:.0f}% — ~{_fmt(egp)} EGP upside.'))
    return out


# ── Competitiveness / gamification ────────────────────────────────────────────

def rule_rank_movement(ctx, threshold):
    """Rank movement vs the previous period (climbed/dropped places) — the most motivating
    competitive signal. Chain highlight of top climbers + per-branch/per-rep movement lines."""
    bmap = _branch_map(ctx)
    out = []

    def positions(dmap):
        return {k: i + 1 for i, (k, _) in enumerate(sorted(dmap.items(), key=lambda x: -float(x[1])))}

    # branches
    bp_now = positions(_net_by_branch(ctx, ctx.start, ctx.end))
    bp_prev = positions(_net_by_branch(ctx, ctx.prev_start, ctx.prev_end))
    bmv = {k: (bp_now[k], bp_prev[k], bp_prev[k] - bp_now[k]) for k in bp_now if k in bp_prev}
    # reps (meaningful only)
    nu = _net_by_user(ctx, ctx.nonexclude); pu = _net_by_user(ctx, ctx.nonexclude, ctx.prev_start, ctx.prev_end)
    nu = {u: v for u, v in nu.items() if v >= 20000 and u not in ctx.cc_agents}
    up_now = positions(nu); up_prev = positions({u: v for u, v in pu.items() if u not in ctx.cc_agents})
    umv = {u: (up_now[u], up_prev[u], up_prev[u] - up_now[u]) for u in up_now if u in up_prev}

    # chain highlight — biggest climbers
    bc = sorted([(k, m) for k, m in bmv.items() if m[2] > 0 and k in bmap], key=lambda x: -x[1][2])[:3]
    uc = sorted([(u, m) for u, m in umv.items() if m[2] > 0], key=lambda x: -x[1][2])[:3]
    if bc or uc:
        pb = ' · '.join(f'{ctx.bn(bmap[k],"ar")} ⬆️{m[2]} (#{m[0]})' for k, m in bc)
        pu2 = ' · '.join(f'{ctx.rep(u)} ⬆️{m[2]} (#{m[0]})' for u, m in uc)
        parts = [x for x in [pb, pu2] if x]
        out.append(dict(rule_code='rank_movement', category='highlight', severity='info',
            scope_type='chain', scope_key='', scope_label='', value=Decimal('0'), baseline=None, threshold=None,
            message_ar='📈 الأكثر تقدماً في الترتيب ({}): {}.'.format(ctx.label(), ' — '.join(parts)),
            message_en='📈 Biggest rank climbers ({}): {}.'.format(ctx.pw_en(), ' — '.join(parts))))
    # per-branch movement
    for bid, (now, prev, delta) in bmv.items():
        if bid not in bmap:
            continue
        arrow = '⬆️' if delta > 0 else ('⬇️' if delta < 0 else '➡️')
        txt_ar = f'صعد {delta} مركز' if delta > 0 else (f'نزل {-delta} مركز' if delta < 0 else 'ثابت')
        txt_en = f'up {delta}' if delta > 0 else (f'down {-delta}' if delta < 0 else 'unchanged')
        out.append(dict(rule_code='rank_movement', category='comparison', severity='info',
            scope_type='branch', scope_key=bmap[bid].code, scope_label=ctx.bn(bmap[bid], 'ar'),
            value=Decimal(now), baseline=Decimal(prev), threshold=None,
            message_ar=f'{arrow} ترتيب {ctx.bn(bmap[bid],"ar")} في المبيعات: #{now} ({txt_ar} — كان #{prev}).',
            message_en=f'{arrow} {ctx.bn(bmap[bid],"en")} sales rank: #{now} ({txt_en} — was #{prev}).'))
    # per-rep movement
    for u, (now, prev, delta) in umv.items():
        arrow = '⬆️' if delta > 0 else ('⬇️' if delta < 0 else '➡️')
        txt_ar = f'صعدت {delta} مركز' if delta > 0 else (f'نزلت {-delta} مركز' if delta < 0 else 'ثابت')
        txt_en = f'up {delta}' if delta > 0 else (f'down {-delta}' if delta < 0 else 'unchanged')
        out.append(dict(rule_code='rank_movement', category='comparison', severity='info',
            scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
            value=Decimal(now), baseline=Decimal(prev), threshold=None,
            message_ar=f'{arrow} ترتيبك في المبيعات: #{now} من {len(up_now)} ({txt_ar} — كنت #{prev}).',
            message_en=f'{arrow} Your sales rank: #{now} of {len(up_now)} ({txt_en} — was #{prev}).'))
    return out


def rule_rfm_segments(ctx, threshold):
    """RFM customer segmentation over a trailing 180-day window: Champions / Loyal / At-risk /
    Lost / New — chain distribution (count + value) to steer retention and win-back."""
    from collections import defaultdict
    from datetime import timedelta as _td
    from django.db.models import Max as _Max, Count as _C
    from apps.customers.models import PurchaseHistory
    win_from = ctx.end - _td(days=180)
    rows = (PurchaseHistory.objects.filter(invoice_date__date__gte=win_from, invoice_date__date__lte=ctx.end,
                doc_code='115', branch_id__in=ctx.branch_ids).exclude(softech_phcode='')
            .values('softech_phcode').annotate(last=_Max('invoice_date'), freq=_C('id'), mon=Sum('total_amount')))
    seg_c = defaultdict(int); seg_v = defaultdict(Decimal); tot = 0
    for r in rows:
        rec = (ctx.end - r['last'].date()).days if r['last'] else 999
        f = r['freq'] or 0; mon = Decimal(str(r['mon'] or 0)); tot += 1
        if f >= 6 and rec <= 30: seg = 'champions'
        elif f >= 6 and rec <= 90: seg = 'loyal'
        elif f >= 3 and 30 < rec <= 90: seg = 'atrisk'
        elif rec > 90: seg = 'lost'
        elif f <= 2 and rec <= 30: seg = 'new'
        else: seg = 'others'
        seg_c[seg] += 1; seg_v[seg] += mon
    if not tot:
        return []
    LA = {'champions': 'أبطال', 'loyal': 'أوفياء', 'atrisk': 'معرضون للفقد', 'lost': 'مفقودون', 'new': 'جدد'}
    LE = {'champions': 'Champions', 'loyal': 'Loyal', 'atrisk': 'At-risk', 'lost': 'Lost', 'new': 'New'}
    order = ['champions', 'loyal', 'atrisk', 'lost', 'new']
    pa = ' · '.join(f'{LA[s]} {seg_c[s]} ({_fmt(seg_v[s])})' for s in order if seg_c[s])
    pe = ' · '.join(f'{LE[s]} {seg_c[s]} ({_fmt(seg_v[s])})' for s in order if seg_c[s])
    out = [dict(rule_code='rfm_segments', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=Decimal(tot), baseline=None, threshold=None,
        message_ar=f'🧬 تقسيم العملاء RFM (آخر 180 يوماً، {tot} عميل): {pa} ج.م.',
        message_en=f'🧬 RFM customer segments (last 180d, {tot} customers): {pe} EGP.')]
    risk = seg_c['atrisk'] + seg_c['lost']
    if tot and risk / tot * 100 >= 40:
        out.append(dict(rule_code='rfm_segments', category='comparison', severity='warning',
            scope_type='chain', scope_key='', scope_label='', value=Decimal(risk), baseline=Decimal(tot), threshold=None,
            message_ar=f'⚠️ {risk} من {tot} عميل ({risk/tot*100:.0f}%) معرضون للفقد أو مفقودون — خطر تآكل قاعدة العملاء.',
            message_en=f'⚠️ {risk} of {tot} customers ({risk/tot*100:.0f}%) at-risk or lost — customer-base erosion risk.'))
    return out


def rule_momentum(ctx, threshold):
    """Trailing-6-month momentum (month reports): personal-best periods + growth streaks
    (motivation) and DECLINE STREAKS (risk / performance-decline early warning) — branches & reps."""
    from collections import defaultdict
    from datetime import date as _d
    import calendar as _cal
    months = []
    y, m = ctx.end.year, ctx.end.month
    for _ in range(6):
        months.append((y, m)); m -= 1
        if m == 0: m = 12; y -= 1
    months.reverse()
    mb, mu = [], []
    for (yy, mm) in months:
        s, e = _d(yy, mm, 1), _d(yy, mm, _cal.monthrange(yy, mm)[1])
        mb.append(_net_by_branch(ctx, s, e)); mu.append(_net_by_user(ctx, ctx.nonexclude, s, e))
    ser = lambda dicts, k: [float(d.get(k, 0) or 0) for d in dicts]
    def strk(s, up):
        k = 0
        for i in range(len(s) - 1, 0, -1):
            if (s[i] > s[i - 1] * 1.001) if up else (s[i] < s[i - 1] * 0.999):
                k += 1
            else:
                break
        return k

    def emit(key, label, scope_type, scope_key):
        pass
    out = []

    def analyse(entities):
        for scope_type, scope_key, label, s in entities:
            if s[-1] <= 0:
                continue
            up, dn = strk(s, True), strk(s, False)
            best = s[-1] >= max(s)
            base = dict(scope_type=scope_type, scope_key=scope_key, scope_label=label,
                        value=Decimal(str(round(s[-1], 0))), baseline=None, threshold=None)
            if best and up >= 1:
                out.append(dict(base, rule_code='momentum', category='highlight', severity='info',
                    message_ar=f'🏆 أعلى أداء: {label} سجّل أفضل شهر خلال 6 أشهر ({_fmt(s[-1])} ج.م، صعود {up} أشهر متتالية).',
                    message_en=f'🏆 Personal best: {label} hit a 6-month high ({_fmt(s[-1])} EGP, {up}-month rising streak).'))
            elif up >= 3:
                out.append(dict(base, rule_code='momentum', category='highlight', severity='info',
                    message_ar=f'📈 زخم صاعد: {label} في صعود {up} أشهر متتالية.',
                    message_en=f'📈 Rising momentum: {label} up {up} consecutive months.'))
            elif dn >= 3:
                out.append(dict(base, rule_code='momentum', category='comparison', severity='warning',
                    message_ar=f'📉 تراجع مستمر: {label} في هبوط {dn} أشهر متتالية ({_fmt(s[-1])} ج.م) — إنذار مبكر.',
                    message_en=f'📉 Sustained decline: {label} down {dn} consecutive months ({_fmt(s[-1])} EGP) — early warning.'))
    analyse([('branch', b.code, ctx.bn(b, 'ar'), ser(mb, b.id)) for b in ctx.branches])
    users = set().union(*[set(d) for d in mu]) if mu else set()
    analyse([('salesperson', u, f'مسئول البيع {ctx.rep(u)}', ser(mu, u))
             for u in users if u not in ctx.cc_agents and float(mu[-1].get(u, 0) or 0) >= 20000])
    return out


# ── Trend engine (reusable N-period streak detector) ──────────────────────────

def _trailing_periods(ctx, n):
    """n trailing periods of the report's shape, oldest→newest (last = current)."""
    import calendar as _cal
    from datetime import date as _d
    if ctx.period_type in ('month', 'mtd'):
        out = []; y, m = ctx.end.year, ctx.end.month
        for _ in range(n):
            out.append((_d(y, m, 1), _d(y, m, _cal.monthrange(y, m)[1]))); m -= 1
            if m == 0: m = 12; y -= 1
        return list(reversed(out))
    days = (ctx.end - ctx.start).days + 1
    out = []; e = ctx.end
    for _ in range(n):
        s = e - timedelta(days=days - 1); out.append((s, e)); e = s - timedelta(days=1)
    return list(reversed(out))


def _streak(seq, direction='down'):
    """Length of the trailing consecutive run in `direction` ('down'/'up') ending at the last."""
    k = 0
    for i in range(len(seq) - 1, 0, -1):
        ok = (seq[i] < seq[i - 1] * 0.999) if direction == 'down' else (seq[i] > seq[i - 1] * 1.001)
        if ok:
            k += 1
        else:
            break
    return k


def _trend_engine(ctx, metric_fn, rule_code, name_ar, name_en, *, n=4, direction='down',
                  min_streak=3, unit='%', decimals=0):
    """Generic per-branch & per-rep trend detector. metric_fn(start, end) → (branch_dict, user_dict)
    of the metric. Emits a warning wherever the metric streaks `direction` for ≥ min_streak of the
    last n periods. Adding a new trend rule = write metric_fn + one call to this."""
    periods = _trailing_periods(ctx, n)
    bmaps, umaps = [], []
    for (s, e) in periods:
        bd, ud = metric_fn(s, e)
        bmaps.append(bd); umaps.append(ud)
    bmap = _branch_map(ctx)
    arrow = '📉' if direction == 'down' else '📈'
    out = []

    def scan(maps, is_branch):
        keys = set().union(*[set(d) for d in maps]) if maps else set()
        for k in keys:
            seq = [float(d.get(k, 0) or 0) for d in maps]
            if _streak(seq, direction) < min_streak:
                continue
            st = _streak(seq, direction)
            if is_branch:
                if k not in bmap:
                    continue
                stype, sk, la, le = 'branch', bmap[k].code, ctx.bn(bmap[k], 'ar'), ctx.bn(bmap[k], 'en')
            else:
                if k in ctx.cc_agents:
                    continue
                stype, sk, la, le = 'salesperson', k, f'مسئول البيع {ctx.rep(k)}', f'Salesperson {ctx.rep(k)}'
            trail = '→'.join(f'{v:.{decimals}f}{unit}' for v in seq[-(min_streak + 1):])
            out.append(dict(rule_code=rule_code, category='comparison', severity='warning',
                scope_type=stype, scope_key=sk, scope_label=la, value=Decimal(str(round(seq[-1], 2))),
                baseline=None, threshold=None,
                message_ar=f'{arrow} {name_ar}: {la} — {st} فترات متتالية ({trail}) — إنذار مبكر.',
                message_en=f'{arrow} {name_en}: {le} — {st} periods in a row ({trail}) — early warning.'))
    scan(bmaps, True); scan(umaps, False)
    return out


def rule_margin_trend(ctx, threshold):
    """Margin-erosion: gross-margin % falling for ≥3 consecutive periods (branch/rep)."""
    def metric(s, e):
        nb = _net_by_branch(ctx, s, e); pb = _profit_by_branch(ctx, s, e)
        nu = _net_by_user(ctx, ctx.nonexclude, s, e); pu = _profit_by_user(ctx, s, e)
        bd = {b: float(pb.get(b, 0) or 0) / float(nb[b]) * 100 for b in nb if nb[b] > 0}
        ud = {u: float(pu.get(u, 0) or 0) / float(nu[u]) * 100 for u in nu if nu[u] >= 20000}
        return bd, ud
    return _trend_engine(ctx, metric, 'margin_trend', 'تآكل هامش الربح', 'Margin erosion', unit='%', decimals=0)


def rule_basket_trend(ctx, threshold):
    """Basket-shrinkage: items/invoice (cash, ex-bulk) falling ≥3 consecutive periods."""
    from apps.customers.models import PurchaseHistoryLine

    def metric(s, e):
        base = PurchaseHistoryLine.objects.filter(
            purchase__invoice_date__date__gte=s, purchase__invoice_date__date__lte=e,
            purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
            purchase__sales_channel__in=ctx.cash_channels, purchase__total_amount__lt=ctx.basket_bulk_floor)
        bd = {r['purchase__branch_id']: (r['l'] / r['i']) for r in base.values('purchase__branch_id')
              .annotate(l=Count('id'), i=Count('purchase', distinct=True)) if r['i']}
        ud = {r['purchase__softech_user']: (r['l'] / r['i']) for r in base.exclude(purchase__softech_user='')
              .values('purchase__softech_user').annotate(l=Count('id'), i=Count('purchase', distinct=True))
              if (r['i'] or 0) >= 30}
        return bd, ud
    return _trend_engine(ctx, metric, 'basket_trend', 'تقلّص متوسط السلة', 'Basket shrinkage', unit=' صنف', decimals=1)


def rule_top_rep_collapse(ctx, threshold):
    """A previously strong rep whose sales dropped ≥ threshold% below their trailing 3-period
    average — disengagement / attrition early warning."""
    from collections import defaultdict
    thr = Decimal(str(threshold if threshold is not None else 40))
    hist = _trailing_periods(ctx, 4)[:-1]
    acc = defaultdict(list)
    for (s, e) in hist:
        for u, v in _net_by_user(ctx, ctx.nonexclude, s, e).items():
            acc[u].append(float(v))
    cur = _net_by_user(ctx, ctx.nonexclude)
    out = []
    for u, c in cur.items():
        if u in ctx.cc_agents or len(acc.get(u, [])) < 3:
            continue
        avg = sum(acc[u]) / len(acc[u])
        if avg >= 30000 and float(c) < avg * (1 - float(thr) / 100):
            drop = (avg - float(c)) / avg * 100
            out.append(dict(rule_code='top_rep_collapse', category='comparison', severity='critical',
                scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
                value=Decimal(str(round(drop, 1))), baseline=Decimal(str(round(avg, 0))), threshold=thr,
                message_ar=f'🚨 انهيار أداء: مسئول البيع {ctx.rep(u)} مبيعاته {_fmt(c)} ج.م — أقل {drop:.0f}% من متوسطه ({_fmt(avg)}) — متابعة عاجلة.',
                message_en=f'🚨 Performance collapse: {ctx.rep(u)} at {_fmt(c)} EGP — {drop:.0f}% below their avg ({_fmt(avg)}) — urgent follow-up.'))
    return out


def rule_revenue_concentration(ctx, threshold):
    """Branch whose top-10 customers make up ≥ threshold% of its sales — a fragile revenue base
    (loss of a few accounts hurts). PIC-based."""
    from collections import defaultdict
    thr = Decimal(str(threshold if threshold is not None else 30))
    ph = _ph(ctx, ctx.start, ctx.end).filter(doc_code='115').exclude(softech_phcode='')
    by_branch = defaultdict(lambda: defaultdict(Decimal))
    for r in ph.values('branch_id', 'softech_phcode').annotate(v=Sum('total_amount')):
        by_branch[r['branch_id']][r['softech_phcode']] += Decimal(str(r['v'] or 0))
    bmap = _branch_map(ctx)
    out = []
    for bid, cust in by_branch.items():
        if bid not in bmap:
            continue
        total = sum(cust.values(), Decimal('0'))
        if total <= 0:
            continue
        top10 = sum(sorted(cust.values(), reverse=True)[:10])
        share = top10 / total * 100
        if share >= thr:
            out.append(dict(rule_code='revenue_concentration', category='comparison', severity='warning',
                scope_type='branch', scope_key=bmap[bid].code, scope_label=ctx.bn(bmap[bid], 'ar'),
                value=Decimal(str(round(float(share), 1))), baseline=total, threshold=thr,
                message_ar=f'🎯 تركّز الإيرادات: {ctx.bn(bmap[bid],"ar")} أعلى 10 عملاء = {share:.0f}% من مبيعاته ({_fmt(top10)} من {_fmt(total)}) — قاعدة هشّة.',
                message_en=f'🎯 Revenue concentration: {ctx.bn(bmap[bid],"en")} top-10 customers = {share:.0f}% of sales — fragile base.'))
    return out


# ── Heavy cash discounters (spot / rank / track values) ───────────────────────

def _cash_discount(ctx, s, e):
    """Discount aggregates over CASH channels (walk-in + delivery + عميل دائم), list_price>0:
    returns (by_branch, by_user) each {key: (gross_list, paid)}."""
    from apps.customers.models import PurchaseHistoryLine
    gross = ExpressionWrapper(F('list_price') * F('quantity'), output_field=DecimalField(max_digits=18, decimal_places=4))
    base = PurchaseHistoryLine.objects.filter(
        purchase__invoice_date__date__gte=s, purchase__invoice_date__date__lte=e,
        purchase__doc_code='115', purchase__branch_id__in=ctx.branch_ids,
        purchase__sales_channel__in=ctx.cash_channels, list_price__gt=0)
    D = lambda x: Decimal(str(x or 0))
    bd = {r['purchase__branch_id']: (D(r['g']), D(r['n']))
          for r in base.values('purchase__branch_id').annotate(g=Sum(gross), n=Sum('line_total'))}
    ud = {r['purchase__softech_user']: (D(r['g']), D(r['n']))
          for r in base.exclude(purchase__softech_user='').values('purchase__softech_user').annotate(g=Sum(gross), n=Sum('line_total'))}
    return bd, ud


def rule_heavy_discounters(ctx, threshold):
    """Heavy CASH discounters: rank salespeople by total discount VALUE given in cash channels
    (walk-in + delivery + عميل دائم), track the EGP, and flag reps whose avg discount ≥ cap."""
    thr = Decimal(str(threshold if threshold is not None else 12))
    _, ud = _cash_discount(ctx, ctx.start, ctx.end)
    rows = []
    for u, (g, n) in ud.items():
        if u in ctx.cc_agents or g <= 0:
            continue
        val = g - n
        if val > 0:
            rows.append((u, val, val / g * 100, g))
    if not rows:
        return []
    rows.sort(key=lambda x: -x[1])
    out = []
    top = rows[:6]
    ar = ' · '.join(f'{i+1}) {ctx.rep(u)} {_fmt(val)} ({pct:.0f}%)' for i, (u, val, pct, g) in enumerate(top))
    en = ' · '.join(f'{i+1}) {ctx.rep(u)} {_fmt(val)} ({pct:.0f}%)' for i, (u, val, pct, g) in enumerate(top))
    out.append(dict(rule_code='heavy_discounters', category='highlight', severity='info',
        scope_type='chain', scope_key='', scope_label='', value=top[0][1], baseline=None, threshold=None,
        message_ar=f'🏷️ أكثر مسئولي البيع خصماً نقدياً بالقيمة ({ctx.label()}): {ar} ج.م.',
        message_en=f'🏷️ Heaviest cash discounters by value ({ctx.pw_en()}): {en} EGP.'))
    for u, val, pct, g in rows:
        if g >= 20000 and pct >= float(thr):
            out.append(dict(rule_code='heavy_discounters', category='discount', severity='warning',
                scope_type='salesperson', scope_key=u, scope_label=f'مسئول البيع {ctx.rep(u)}',
                value=Decimal(str(round(float(pct), 1))), baseline=val, threshold=thr,
                message_ar=f'🏷️ خصّام كبير: مسئول البيع {ctx.rep(u)} منح خصماً نقدياً {_fmt(val)} ج.م ({pct:.0f}%) على مبيعات {_fmt(g)} ج.م — أعلى من الحد {thr:.0f}%.',
                message_en=f'🏷️ Heavy discounter: {ctx.rep(u)} gave {_fmt(val)} EGP cash discount ({pct:.0f}%) on {_fmt(g)} EGP — above {thr:.0f}% cap.'))
    return out


def rule_discount_creep(ctx, threshold):
    """Discount-creep: a branch/rep's avg cash discount % RISING for ≥3 consecutive periods."""
    def metric(s, e):
        bd, ud = _cash_discount(ctx, s, e)
        b = {k: float(g - n) / float(g) * 100 for k, (g, n) in bd.items() if g > 0}
        u = {k: float(g - n) / float(g) * 100 for k, (g, n) in ud.items() if g >= 20000}
        return b, u
    return _trend_engine(ctx, metric, 'discount_creep', 'تصاعد الخصومات', 'Discount creep', unit='%', direction='up', decimals=0)


def rule_return_climb(ctx, threshold):
    """Rising returns: returns %-of-sales climbing for ≥3 consecutive periods (branch/rep)."""
    from apps.customers.models import PurchaseHistory

    def metric(s, e):
        base = PurchaseHistory.objects.filter(invoice_date__date__gte=s, invoice_date__date__lte=e,
                                              branch_id__in=ctx.branch_ids, sales_channel__in=ctx.nonexclude)
        bs = dict(base.filter(doc_code='115').values_list('branch_id').annotate(v=Sum('total_amount')))
        br = dict(base.filter(doc_code='30').values_list('branch_id').annotate(v=Sum('total_amount')))
        b = {k: float(br.get(k, 0) or 0) / float(bs[k]) * 100 for k in bs if bs[k]}
        us = dict(base.filter(doc_code='115').exclude(softech_user='').values_list('softech_user').annotate(v=Sum('total_amount')))
        ur = dict(base.filter(doc_code='30').exclude(softech_user='').values_list('softech_user').annotate(v=Sum('total_amount')))
        u = {k: float(ur.get(k, 0) or 0) / float(us[k]) * 100 for k in us if (us[k] or 0) >= 20000}
        return b, u
    return _trend_engine(ctx, metric, 'return_climb', 'تصاعد المرتجعات', 'Rising returns', unit='%', direction='up', decimals=0)


def rule_delivery_share_trend(ctx, threshold):
    """Delivery-share slide: a branch's delivery % of net sales falling ≥3 consecutive periods
    (delivery is a strategic growth channel — a slide is an early warning)."""
    def metric(s, e):
        tot = _net_by_branch(ctx, s, e); dl = _net_by_branch(ctx, s, e, channels=ctx.delivery_channels)
        b = {k: float(dl.get(k, 0) or 0) / float(tot[k]) * 100 for k in tot if tot[k] > 0}
        return b, {}   # delivery is branch-level; skip rep dimension
    return _trend_engine(ctx, metric, 'delivery_share_trend', 'تراجع حصة التوصيل', 'Delivery-share slide', unit='%', direction='down', decimals=0)


def rule_new_customer_trend(ctx, threshold):
    """New-customer acquisition declining: per-branch new-customer count falling ≥3 consecutive
    periods (funnel drying up). Uses an incremental prior-PIC set across the trailing windows."""
    from collections import defaultdict
    from apps.customers.models import PurchaseHistory
    periods = _trailing_periods(ctx, 4)
    prior = set(PurchaseHistory.objects.filter(invoice_date__date__lt=periods[0][0], doc_code='115')
                .exclude(softech_phcode='').values_list('softech_phcode', flat=True).distinct())
    series = defaultdict(list)
    for (s, e) in periods:
        seen = defaultdict(set)
        for bid, pic in (PurchaseHistory.objects.filter(invoice_date__date__gte=s, invoice_date__date__lte=e,
                         doc_code='115', branch_id__in=ctx.branch_ids).exclude(softech_phcode='')
                         .values_list('branch_id', 'softech_phcode').distinct()):
            seen[bid].add(pic)
        wpics = set()
        for b in ctx.branches:
            pics = seen.get(b.id, set())
            series[b.id].append(len(pics - prior)); wpics |= pics
        prior |= wpics
    out = []
    for b in ctx.branches:
        seq = series.get(b.id, [])
        if len(seq) < 4 or sum(seq) == 0:
            continue
        st = _streak([float(x) for x in seq], 'down')
        if st >= 3:
            trail = '→'.join(str(int(v)) for v in seq[-4:])
            out.append(dict(rule_code='new_customer_trend', category='comparison', severity='warning',
                scope_type='branch', scope_key=b.code, scope_label=ctx.bn(b, 'ar'), value=Decimal(seq[-1]),
                baseline=None, threshold=None,
                message_ar=f'📉 تراجع اكتساب العملاء الجدد: {ctx.bn(b,"ar")} — {st} فترات متتالية ({trail}) — تباطؤ نمو القاعدة.',
                message_en=f'📉 New-customer acquisition falling: {ctx.bn(b,"en")} — {st} periods in a row ({trail}) — funnel drying up.'))
    return out


# ── Target achievement (forecasting integration, doc 16 ↔ doc 18) ─────────────
# When a ForecastScenario is COMMITTED for the report's month, these rules narrate
# actual-vs-target achievement (%), rank branches / salespeople, and flag whoever is
# behind pace. Silent when no committed target exists for the period.
_METRIC_AR = {'cash_delivery': 'المبيعات النقدية', 'credit': 'الآجل/التعاقدات', 'beauty': 'التجميل',
              'gross_profit': 'الربح', 'customer_count': 'عدد العملاء', 'net_revenue': 'إجمالى المبيعات'}
_METRIC_EN = {'cash_delivery': 'cash+delivery', 'credit': 'credit', 'beauty': 'beauty',
              'gross_profit': 'profit', 'customer_count': 'customers', 'net_revenue': 'net sales'}


def _committed_scenario(ctx, scope_type):
    """Latest committed forecast scenario whose target month == the report's month."""
    from apps.forecasting.models import ForecastScenario
    return (ForecastScenario.objects.filter(
                status='committed', scope_type=scope_type, year=ctx.end.year, month=ctx.end.month)
            .order_by('-committed_at', '-id').first())


def _target_month_slice(ctx):
    """The slice of the report period that falls inside the target month, plus the
    pro-rate factor (elapsed days ÷ days-in-month) so partial periods compare fairly."""
    import calendar
    from datetime import date as _date
    ty, tm = ctx.end.year, ctx.end.month
    ms = max(ctx.start, _date(ty, tm, 1))
    me = ctx.end
    dim = calendar.monthrange(ty, tm)[1]
    factor = Decimal((me - ms).days + 1) / Decimal(dim)
    return ty, tm, ms, me, factor


def rule_branch_target_achievement(ctx, threshold):
    """Actual-vs-target achievement for a committed BRANCH scenario: a chain summary
    across metrics, a branch ranking on the primary sales metric, and a behind-pace flag
    per branch. threshold = behind-pace cutoff (% of pro-rated target)."""
    thr = Decimal(str(threshold if threshold is not None else 85))
    scen = _committed_scenario(ctx, 'branch')
    if not scen:
        return []
    from apps.forecasting.models import ForecastResult
    ty, tm, ms, me, factor = _target_month_slice(ctx)
    r = ctx.resolver
    results = [x for x in ForecastResult.objects.filter(scenario=scen).select_related('branch')
               if x.branch_id]
    if not results:
        return []
    metrics = sorted({x.metric for x in results})
    out = []
    # ① chain summary across metrics
    parts_ar, parts_en = [], []
    for m in metrics:
        tgt = sum((x.target_value for x in results if x.metric == m), Decimal('0')) * factor
        if tgt <= 0:
            continue
        pct = Decimal(str(r.resolve(m, branch_ids=ctx.branch_ids, start=ms, end=me))) / tgt * 100
        parts_ar.append(f'{_METRIC_AR.get(m, m)} {pct:.0f}%')
        parts_en.append(f'{_METRIC_EN.get(m, m)} {pct:.0f}%')
    if parts_ar:
        out.append(dict(rule_code='branch_target_achievement', category='highlight', severity='info',
            scope_type='chain', scope_key='', scope_label='', value=Decimal('0'), baseline=None, threshold=None,
            message_ar=f'🎯 إنجاز الشبكة مقابل الهدف ({ty}-{tm:02d}): ' + ' · '.join(parts_ar) + '.',
            message_en=f'🎯 Chain achievement vs target ({ty}-{tm:02d}): ' + ' · '.join(parts_en) + '.'))
    # ② per-branch ranking + behind-pace flags on the primary sales metric
    primary = 'cash_delivery' if 'cash_delivery' in metrics else metrics[0]
    rows = []
    for x in results:
        if x.metric != primary:
            continue
        tgt = x.target_value * factor
        if tgt <= 0:
            continue
        act = Decimal(str(r.resolve(primary, branch_ids=[x.branch_id], start=ms, end=me)))
        rows.append((x, act, tgt, act / tgt * 100))
    rows.sort(key=lambda z: -z[3])
    if rows:
        rk_ar = ' · '.join(f'{ctx.bn(x.branch,"ar")} {p:.0f}%' for x, _, _, p in rows[:5])
        rk_en = ' · '.join(f'{ctx.bn(x.branch,"en")} {p:.0f}%' for x, _, _, p in rows[:5])
        out.append(dict(rule_code='branch_target_achievement', category='highlight', severity='info',
            scope_type='chain', scope_key='', scope_label='', value=Decimal('0'), baseline=None, threshold=None,
            message_ar=f'🏆 ترتيب الفروع في تحقيق هدف {_METRIC_AR.get(primary, primary)} ({ty}-{tm:02d}): {rk_ar}.',
            message_en=f'🏆 Branch achievement ranking — {_METRIC_EN.get(primary, primary)} ({ty}-{tm:02d}): {rk_en}.'))
        for x, act, tgt, pct in rows:
            if pct < thr:
                out.append(dict(rule_code='branch_target_achievement', category='comparison', severity='warning',
                    scope_type='branch', scope_key=x.branch.code, scope_label=ctx.bn(x.branch, 'ar'),
                    value=Decimal(str(round(float(pct), 1))), baseline=tgt, threshold=thr,
                    message_ar=f'📉 {ctx.bn(x.branch,"ar")}: حقّق {pct:.0f}% من هدف {_METRIC_AR.get(primary, primary)} ({_fmt(act)} من {_fmt(tgt)} ج.م) — خلف المستهدف.',
                    message_en=f'📉 {ctx.bn(x.branch,"en")}: {pct:.0f}% of {_METRIC_EN.get(primary, primary)} target ({_fmt(act)} of {_fmt(tgt)} EGP) — behind pace.'))
    return out


def rule_salesperson_target_achievement(ctx, threshold):
    """Actual-vs-target achievement for a committed SALESPERSON scenario: ranking on the
    primary metric + behind-pace flag per rep. threshold = behind-pace cutoff %."""
    thr = Decimal(str(threshold if threshold is not None else 85))
    scen = _committed_scenario(ctx, 'salesperson')
    if not scen:
        return []
    from apps.forecasting.models import ForecastResult
    ty, tm, ms, me, factor = _target_month_slice(ctx)
    r = ctx.resolver
    results = list(ForecastResult.objects.filter(scenario=scen))
    metrics = sorted({x.metric for x in results})
    if not metrics:
        return []
    primary = 'cash_delivery' if 'cash_delivery' in metrics else metrics[0]
    rows = []
    for x in results:
        if x.metric != primary or x.scope_key in ctx.cc_agents:
            continue
        tgt = x.target_value * factor
        if tgt <= 0:
            continue
        act = Decimal(str(r.resolve(primary, softech_user=x.scope_key, start=ms, end=me)))
        rows.append((x, act, tgt, act / tgt * 100))
    rows.sort(key=lambda z: -z[3])
    out = []
    if rows:
        rk = ' · '.join(f'{ctx.rep(x.scope_key)} {p:.0f}%' for x, _, _, p in rows[:5])
        out.append(dict(rule_code='salesperson_target_achievement', category='highlight', severity='info',
            scope_type='chain', scope_key='', scope_label='', value=Decimal('0'), baseline=None, threshold=None,
            message_ar=f'🏅 ترتيب مسئولي البيع في تحقيق الهدف ({ty}-{tm:02d}): {rk}.',
            message_en=f'🏅 Salesperson achievement ranking ({ty}-{tm:02d}): {rk}.'))
        for x, act, tgt, pct in rows:
            if pct < thr:
                out.append(dict(rule_code='salesperson_target_achievement', category='comparison', severity='warning',
                    scope_type='salesperson', scope_key=x.scope_key, scope_label=f'مسئول البيع {ctx.rep(x.scope_key)}',
                    value=Decimal(str(round(float(pct), 1))), baseline=tgt, threshold=thr,
                    message_ar=f'📉 مسئول البيع {ctx.rep(x.scope_key)}: حقّق {pct:.0f}% من هدفه ({_fmt(act)} من {_fmt(tgt)} ج.م) — خلف المستهدف.',
                    message_en=f'📉 Salesperson {ctx.rep(x.scope_key)}: {pct:.0f}% of target ({_fmt(act)} of {_fmt(tgt)} EGP) — behind pace.'))
    return out


# code → (evaluator, default name_ar, name_en, category, severity, default_threshold, periods)
RULES = {
    'branch_vs_prev':         (rule_branch_vs_prev, 'انخفاض مبيعات فرع', 'Branch sales drop', 'comparison', 'warning', 25, 'day,week,month'),
    'branch_zero_delivery':   (rule_branch_zero_delivery, 'صفر توصيل', 'Zero delivery', 'coverage', 'critical', None, 'day,week,month'),
    'branch_zero_callcenter': (rule_branch_zero_callcenter, 'صفر كول سنتر', 'Zero call-center', 'coverage', 'critical', None, 'day,week,month'),
    'branch_no_new_customer': (rule_branch_no_new_customer, 'لا عملاء جدد', 'No new customers', 'coverage', 'warning', None, 'day,week,month'),
    'salesperson_no_beauty':  (rule_salesperson_no_beauty, 'مسئول بيع بلا تجميل', 'Salesperson no beauty', 'mix', 'warning', 5000, 'day,week'),
    'salesperson_below_avg':  (rule_salesperson_below_avg, 'مسئول بيع تحت متوسطه', 'Salesperson below average', 'volume', 'warning', 50, 'day,week'),
    'high_discount':          (rule_high_discount, 'خصم مرتفع (نقدى/توصيل)', 'High discount (walk-in/delivery)', 'discount', 'warning', 30, 'day,week,month'),
    'high_discount_regular':  (rule_high_discount_regular, 'خصم مرتفع (عميل دائم)', 'High discount (regular customer)', 'discount', 'warning', 30, 'day,week,month'),
    'bulk_sale':              (rule_bulk_sale, 'فاتورة نقدية كبيرة', 'Large cash invoice', 'discount', 'info', 10000, 'day,week,month'),
    'top_branch':             (rule_top_branch, 'أفضل فرع', 'Top branch', 'highlight', 'info', None, 'day,week,month'),
    # ── leakage / performance ──
    'below_cost_sale':        (rule_below_cost_sale, 'بيع تحت التكلفة', 'Below-cost sale', 'discount', 'critical', 100, 'day,week,month'),
    'branch_high_returns':    (rule_branch_high_returns, 'مرتجعات مرتفعة', 'High returns', 'volume', 'warning', 8, 'week,month'),
    'branch_margin_drop':     (rule_branch_margin_drop, 'تراجع الهامش', 'Margin drop', 'comparison', 'warning', 3, 'week,month'),
    'salesperson_over_discount': (rule_salesperson_over_discount, 'مسئول بيع كثير الخصم (نقدى/توصيل)', 'Salesperson over-discounts (walk-in/delivery)', 'discount', 'warning', 12, 'week,month'),
    'salesperson_over_discount_regular': (rule_salesperson_over_discount_regular, 'مسئول بيع كثير الخصم (عميل دائم)', 'Salesperson over-discounts (regular)', 'discount', 'warning', 12, 'week,month'),
    'salesperson_regular_share': (rule_salesperson_regular_share, 'تركيز مبيعات عميل دائم', 'Regular-channel concentration', 'discount', 'warning', 30, 'week,month'),
    'salesperson_basket':     (rule_salesperson_basket, 'حجم فاتورة المسئول صغير', 'Salesperson small basket', 'volume', 'warning', 2, 'week,month'),
    'salesperson_beauty_attach': (rule_salesperson_beauty_attach, 'ضعف إرفاق التجميل', 'Low beauty attach', 'mix', 'warning', 20, 'week,month'),
    'salesperson_return_rate': (rule_salesperson_return_rate, 'مرتجعات المسئول مرتفعة', 'Salesperson high returns', 'volume', 'warning', 8, 'week,month'),
    'salesperson_customer_concentration': (rule_salesperson_customer_concentration, 'تركّز عملاء المسئول', 'Salesperson customer concentration', 'comparison', 'warning', 40, 'week,month'),
    'salesperson_most_improved': (rule_salesperson_most_improved, 'الأكثر تحسّناً', 'Most-improved salesperson', 'highlight', 'info', None, 'month'),
    # ── sales boosting + abuse ──
    'branch_basket':          (rule_branch_basket, 'حجم فاتورة الفرع صغير', 'Branch small basket', 'volume', 'warning', 2.3, 'week,month'),
    'peak_hours':             (rule_peak_hours, 'ساعات الذروة', 'Peak sales hours', 'highlight', 'info', None, 'day,week,month'),
    'discount_to_one_customer': (rule_discount_to_one_customer, 'خصم مُركّز على عميل', 'Discount to one customer', 'discount', 'warning', 40, 'week,month'),
    'wash_sale':              (rule_wash_sale, 'دورة بيع/إرجاع', 'Sale/return round-trip', 'discount', 'warning', 80, 'week,month'),
    # ── purchasing STUDY (descriptive analytics) ──
    'purchase_overview':      (rule_purchase_overview, 'إجمالى المشتريات', 'Purchasing overview', 'highlight', 'info', None, 'day,week,month'),
    'purchase_general_category': (rule_purchase_general_category, 'توزيع المشتريات حسب فئة الصنف', 'Purchases by item category', 'highlight', 'info', None, 'day,week,month'),
    'rank_suppliers':         (rule_rank_suppliers, 'أكبر الموردين', 'Top suppliers', 'highlight', 'info', None, 'day,week,month'),
    'rank_purchased_items':   (rule_rank_purchased_items, 'أكثر الأصناف شراءً', 'Top purchased items', 'highlight', 'info', None, 'day,week,month'),
    'branch_purchase_profile': (rule_branch_purchase_profile, 'مشتريات الفرع (تفصيلي)', 'Per-branch purchasing', 'comparison', 'info', 5000, 'day,week,month'),
    'supplier_scorecard':     (rule_supplier_scorecard, 'تقييم الموردين', 'Supplier scorecard', 'highlight', 'info', 10, 'week,month'),
    # ── purchasing (HQ cost control) ──
    'hq_purchase_summary':    (rule_hq_purchase_summary, 'ملخص مشتريات HQ', 'HQ purchases', 'highlight', 'info', None, 'day,week,month'),
    'hq_purchase_trend':      (rule_hq_purchase_trend, 'اتجاه مشتريات HQ', 'HQ purchase trend', 'comparison', 'info', 20, 'week,month'),
    'purchase_category_mix':  (rule_purchase_category_mix, 'توزيع المشتريات', 'Purchase mix', 'comparison', 'info', 30, 'week,month'),
    'purchase_price_creep':   (rule_purchase_price_creep, 'ارتفاع أسعار الشراء', 'Purchase price creep', 'discount', 'warning', 10, 'week,month'),
    'purchase_thin_margin':   (rule_purchase_thin_margin, 'هامش شراء ضعيف', 'Thin buying margin', 'discount', 'warning', 8, 'week,month'),
    'buyer_small_warehouse':  (rule_buyer_small_warehouse, 'مشترى كثير المستودعات الصغيرة', 'Buyer small-warehouse reliance', 'comparison', 'warning', 30, 'week,month'),
    'supplier_concentration': (rule_supplier_concentration, 'تركّز الموردين', 'Supplier concentration', 'comparison', 'warning', 35, 'week,month'),
    'foc_captured':           (rule_foc_captured, 'بضائع مجانية/بونص', 'Free/bonus goods', 'highlight', 'info', None, 'week,month'),
    'supplier_return_spike':  (rule_supplier_return_spike, 'مرتجعات موردين', 'Supplier returns', 'discount', 'warning', 20000, 'week,month'),
    # ── purchasing (branches) ──
    'branch_local_purchase':  (rule_branch_local_purchase, 'مشتريات محلية للفرع', 'Branch local purchases', 'comparison', 'info', 10000, 'week,month'),
    'branch_small_warehouse': (rule_branch_small_warehouse, 'فرع كثير المستودعات الصغيرة', 'Branch small-warehouse reliance', 'comparison', 'warning', 40, 'week,month'),
    'patient_repurchase_volume': (rule_patient_repurchase_volume, 'شراء من مرضى', 'Patient/Rx repurchase', 'comparison', 'info', 5000, 'week,month'),
    'buy_vs_sell_imbalance':  (rule_buy_vs_sell_imbalance, 'شراء دون بيع (مخزون زائد)', 'Buy-vs-sell imbalance', 'volume', 'warning', 10, 'week,month'),
    # ── optimization & diagnosis (purchasing & replenishment) ──
    'transfer_matcher':       (rule_transfer_matcher, 'مطابقة نقل (راكد↔نافد)', 'Overstock↔stockout transfer matcher', 'volume', 'warning', 5, 'day,week,month'),
    'margin_leakage':         (rule_margin_leakage, 'تسرب الهامش (تفصيلي)', 'Margin-leakage waterfall', 'discount', 'warning', 20000, 'week,month'),
    'price_inconsistency':    (rule_price_inconsistency, 'تفاوت الأسعار بين الفروع', 'Cross-branch price inconsistency', 'discount', 'warning', 25, 'week,month'),
    'inventory_turnover':     (rule_inventory_turnover, 'كفاءة المخزون', 'Inventory turnover', 'highlight', 'info', None, 'week,month'),
    'structural_loss_skus':   (rule_structural_loss_skus, 'أصناف بيعها تحت التكلفة هيكلياً', 'Structural-loss SKUs', 'discount', 'warning', None, 'week,month'),
    'data_hygiene':           (rule_data_hygiene, 'جودة البيانات', 'Data hygiene', 'coverage', 'warning', 5, 'week,month'),
    # ── stock ──
    'stock_variance':         (rule_stock_variance, 'فروق الجرد', 'Stock variance', 'coverage', 'warning', 15, 'day,week,month'),
    # ── inter-branch cooperation ──
    'branch_cooperation':     (rule_branch_cooperation, 'تعاون الفروع', 'Branch cooperation', 'highlight', 'info', None, 'week,month'),
    'branch_isolation':       (rule_branch_isolation, 'فرع منعزل', 'Branch isolation', 'volume', 'info', None, 'week,month'),
    # ── don't-lose-sales: inventory ──
    'stockout_fastmovers':    (rule_stockout_fastmovers, 'أصناف نافدة سريعة الحركة', 'Fast-mover stockouts', 'coverage', 'critical', 30, 'day,week,month'),
    'dead_stock':             (rule_dead_stock, 'مخزون راكد', 'Dead stock', 'volume', 'warning', 150000, 'week,month'),
    # ── comparative rankings ──
    'rank_cosmetics':         (rule_rank_cosmetics, 'ترتيب التجميل', 'Cosmetics ranking', 'highlight', 'info', None, 'day,week,month'),
    'rank_delivery':          (rule_rank_delivery, 'ترتيب التوصيل', 'Delivery ranking', 'highlight', 'info', None, 'day,week,month'),
    'rank_salespeople':       (rule_rank_salespeople, 'ترتيب مسئولي البيع', 'Salespeople ranking', 'highlight', 'info', None, 'day,week,month'),
    # ── segment analytics ──
    'sales_segments':         (rule_sales_segments, 'تحليل قطاعات المبيعات', 'Sales segment analytics', 'highlight', 'info', None, 'day,week,month'),
    'tracked_items':          (rule_tracked_items, 'أصناف متابَعة (أكواد)', 'Tracked item codes', 'highlight', 'info', None, 'day,week,month'),
    'branch_segments':        (rule_branch_segments, 'قطاعات مبيعات الفرع', 'Per-branch segments', 'comparison', 'info', None, 'day,week,month'),
    'segment_rankings':       (rule_segment_rankings, 'ترتيب قنوات البيع (استلام/توصيل)', 'Segment leaderboards (walk-in/delivery)', 'highlight', 'info', None, 'day,week,month'),
    'profit_rankings':        (rule_profit_rankings, 'ترتيب الربح والهامش', 'Profit & margin rankings', 'highlight', 'info', None, 'day,week,month'),
    # ── sales-boost opportunity sizing ──
    'basket_uplift':          (rule_basket_uplift, 'فرصة رفع السلة (ج.م)', 'Basket-uplift opportunity', 'highlight', 'info', None, 'day,week,month'),
    'lapsed_customers':       (rule_lapsed_customers, 'عملاء متوقفون (استرجاع)', 'Lapsed customers (win-back)', 'comparison', 'warning', None, 'week,month'),
    'category_penetration':   (rule_category_penetration, 'فجوة التجميل', 'Beauty penetration gap', 'mix', 'warning', 3, 'week,month'),
    # ── competitiveness / gamification ──
    'rank_movement':          (rule_rank_movement, 'حركة الترتيب (صعود/هبوط)', 'Rank movement', 'comparison', 'info', None, 'day,week,month'),
    'momentum':               (rule_momentum, 'الزخم (سلاسل صعود/هبوط)', 'Momentum (streaks / decline)', 'comparison', 'info', None, 'month'),
    'rfm_segments':           (rule_rfm_segments, 'تقسيم العملاء RFM', 'RFM customer segments', 'highlight', 'info', None, 'week,month'),
    # ── decline / risk detectors ──
    'margin_trend':           (rule_margin_trend, 'تآكل هامش الربح (اتجاه)', 'Margin-erosion trend', 'comparison', 'warning', None, 'week,month'),
    'basket_trend':           (rule_basket_trend, 'تقلّص السلة (اتجاه)', 'Basket-shrinkage trend', 'comparison', 'warning', None, 'week,month'),
    'top_rep_collapse':       (rule_top_rep_collapse, 'انهيار أداء مسئول بيع', 'Top-rep collapse', 'comparison', 'critical', 40, 'month'),
    'revenue_concentration':  (rule_revenue_concentration, 'تركّز الإيرادات على عملاء', 'Revenue concentration', 'comparison', 'warning', 30, 'week,month'),
    'heavy_discounters':      (rule_heavy_discounters, 'أكثر مسئولي البيع خصماً (نقدى)', 'Heavy cash discounters', 'discount', 'warning', 12, 'day,week,month'),
    'discount_creep':         (rule_discount_creep, 'تصاعد الخصومات (اتجاه)', 'Discount-creep trend', 'comparison', 'warning', None, 'week,month'),
    'return_climb':           (rule_return_climb, 'تصاعد المرتجعات (اتجاه)', 'Rising-returns trend', 'comparison', 'warning', None, 'week,month'),
    'delivery_share_trend':   (rule_delivery_share_trend, 'تراجع حصة التوصيل (اتجاه)', 'Delivery-share slide', 'comparison', 'warning', None, 'week,month'),
    'new_customer_trend':     (rule_new_customer_trend, 'تراجع العملاء الجدد (اتجاه)', 'New-customer decline', 'comparison', 'warning', None, 'month'),
    # ── predictive replenishment (purchasing domain) ──
    'predictive_reorder':     (rule_predictive_reorder, 'إعادة الطلب التنبؤية', 'Predictive reorder', 'coverage', 'warning', 10, 'day,week,month'),
    'near_expiry':            (rule_near_expiry, 'قرب انتهاء الصلاحية', 'Near-expiry markdown', 'volume', 'warning', 1000, 'week,month'),
    'lost_sales_value':       (rule_lost_sales_value, 'قيمة المبيعات الضائعة', 'Quantified lost sales', 'coverage', 'warning', 5000, 'day,week,month'),
    'demand_surge_unmet':     (rule_demand_surge_unmet, 'طلب متزايد غير مغطّى', 'Unmet demand surge', 'coverage', 'warning', 2, 'week,month'),
    'chronic_low_availability': (rule_chronic_low_availability, 'إتاحة منخفضة مزمنة', 'Chronic low availability', 'coverage', 'warning', 70, 'week,month'),
    'dead_stock_growth':      (rule_dead_stock_growth, 'تزايد المخزون الراكد', 'Dead-stock growth', 'volume', 'warning', 10, 'week,month'),
    'overstock_coverage':     (rule_overstock_coverage, 'إفراط شراء (تغطية عالية)', 'Overstock (high coverage)', 'volume', 'warning', 12, 'week,month'),
    'stockout_root_cause':    (rule_stockout_root_cause, 'أسباب المبيعات الضائعة', 'Lost-sales root causes', 'coverage', 'info', None, 'week,month'),
    'critical_coverage':      (rule_critical_coverage, 'مخزون على وشك النفاد (أيام)', 'Days-to-stockout (critical)', 'coverage', 'critical', 5, 'day,week,month'),
    'supply_bottlenecks':     (rule_supply_bottlenecks, 'اختناقات التوريد', 'Supply bottlenecks', 'coverage', 'warning', 4, 'week,month'),
    'abc_distribution':       (rule_abc_distribution, 'توزيع المخزون ABC', 'ABC inventory mix', 'highlight', 'info', 40, 'week,month'),
    'low_forecast_confidence': (rule_low_forecast_confidence, 'تنبؤ غير موثوق', 'Low forecast confidence', 'coverage', 'info', 0.6, 'week,month'),
    'stockout_calendar':      (rule_stockout_calendar, 'تقويم النفاد المتوقع', 'Stockout calendar', 'coverage', 'warning', 30, 'day,week,month'),
    'branch_rankings':        (rule_branch_rankings, 'ترتيب الفروع (مبيعات/نقدى/توصيل/عدد)', 'Branch rankings suite', 'highlight', 'info', None, 'day,week,month'),
    'salesperson_rankings':   (rule_salesperson_rankings, 'ترتيب مسئولي البيع (نقدى/عدد)', 'Salesperson rankings suite', 'highlight', 'info', None, 'day,week,month'),
    'bulk_cash_ranking':      (rule_bulk_cash_ranking, 'ترتيب الفواتير النقدية الكبيرة', 'Bulk-cash-invoice rankings', 'highlight', 'info', 10000, 'day,week,month'),
    'basket_ranking':         (rule_basket_ranking, 'ترتيب حجم/قيمة السلة', 'Basket-size & value rankings', 'highlight', 'info', None, 'week,month'),
    'branch_standings':       (rule_branch_standings, 'ترتيب الفرع بين الفروع', 'Per-branch standing', 'comparison', 'info', None, 'day,week,month'),
    'salesperson_profile':    (rule_salesperson_profile, 'ملف مسئول البيع الشامل', 'Salesperson full profile', 'comparison', 'info', None, 'day,week,month'),
    'customer_mix':           (rule_customer_mix, 'مزيج العملاء (جدد/عائدون)', 'New vs returning customers', 'comparison', 'info', None, 'week,month'),
    'cross_sell_pairs':       (rule_cross_sell_pairs, 'أزواج البيع المتقاطع', 'Cross-sell pairs', 'mix', 'info', None, 'week,month'),
    # ── target achievement (forecasting integration) ──
    'branch_target_achievement': (rule_branch_target_achievement, 'إنجاز أهداف الفروع', 'Branch target achievement', 'comparison', 'warning', 85, 'week,month'),
    'salesperson_target_achievement': (rule_salesperson_target_achievement, 'إنجاز أهداف مسئولي البيع', 'Salesperson target achievement', 'comparison', 'warning', 85, 'week,month'),
}


# Report domain per rule. 'purchasing' = purchasing + replenishment/stock; everything
# else is 'sales'. Drives the two separate reports (المبيعات / المشتريات والتموين).
_PURCHASING_CODES = {
    'purchase_overview', 'purchase_general_category', 'rank_suppliers', 'rank_purchased_items',
    'branch_purchase_profile', 'supplier_scorecard',
    'hq_purchase_summary', 'hq_purchase_trend', 'purchase_category_mix', 'purchase_price_creep',
    'purchase_thin_margin', 'buyer_small_warehouse', 'supplier_concentration', 'foc_captured',
    'supplier_return_spike', 'branch_local_purchase', 'branch_small_warehouse',
    'patient_repurchase_volume', 'buy_vs_sell_imbalance',
    # replenishment / stock
    'stockout_fastmovers', 'dead_stock', 'stock_variance',
    # optimization & diagnosis
    'transfer_matcher', 'margin_leakage', 'price_inconsistency', 'inventory_turnover',
    'structural_loss_skus', 'data_hygiene',
    # predictive replenishment
    'predictive_reorder', 'near_expiry', 'lost_sales_value', 'demand_surge_unmet',
    'chronic_low_availability', 'dead_stock_growth', 'critical_coverage', 'supply_bottlenecks',
    'abc_distribution', 'low_forecast_confidence', 'overstock_coverage', 'stockout_root_cause',
    'stockout_calendar',
}


def rule_domain(code):
    """'purchasing' for purchasing+replenishment rules, else 'sales'."""
    return 'purchasing' if code in _PURCHASING_CODES else 'sales'
