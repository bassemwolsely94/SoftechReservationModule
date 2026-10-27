"""
apps/stock_audit/rules.py

Doc 32 Phase 2 — the checks. Each check is a PURE function:

    fn(lines, params, ctx) -> [candidate dict, ...]

`lines`  — StockLedgerLine objects for ONE branch inside the rule's window (any doccode the
           rule asked for), `params` — effective thresholds (defaults ⊕ chain ⊕ branch),
`ctx`    — RuleContext (exclusion sets, sales channel per invoice, names, window).

Deterministic: no AI, no fuzzy logic; every threshold comes from `params`.
Candidate keys: dedup_key, severity, itemcode, doccode, docnumber, docdate, occurred_at,
softech_user, personcode, value_egp, metric, threshold, evidence, message_ar, message_en.
"""
import datetime as _dt
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal('0')
HUNDRED = Decimal('100')
_EPOCH = _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)   # sort key for a missing trans_time


def _q2(v):
    return Decimal(v).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _fmt(v):
    return f'{Decimal(v):,.2f}'


def _num(v):
    return Decimal(str(v))


def _line_ref(l):
    """Evidence entry for one ledger line (ledger ids change on day replace — never store them)."""
    return {
        'doccode': l.doccode, 'docnumber': l.docnumber, 'docdate': l.docdate.isoformat(),
        'trans_time': l.trans_time.isoformat() if l.trans_time else None,
        'itemcode': l.itemcode, 'qty': str(l.transqty), 'price': str(l.transprice),
        'cost': str(l.newcostprice), 'newqty': str(l.newqty), 'usercode': l.usercode,
        'personcode': l.personcode,
        'expiry': l.itemexpirydate.isoformat() if l.itemexpirydate else None,
    }


def _base(l, ctx):
    return dict(itemcode=l.itemcode, doccode=l.doccode, docnumber=l.docnumber, docdate=l.docdate,
                occurred_at=l.trans_time, softech_user=l.usercode, personcode=l.personcode)


class RuleContext:
    """Everything a rule needs besides lines/params. Built once per engine run."""

    def __init__(self, date_from, date_to, item_names=None, branch_names=None,
                 excluded_item_codes=None, channel_of_invoice=None, channel_bucket=None,
                 returned_invoices=None, report_from=None, medicine_items=None, monthly_qty=None,
                 on_hand=None, sales=None, returns_total=None, ledger_from=None, counts=None,
                 branch_hours=None):
        self.date_from = date_from                               # earliest line loaded (lookbacks)
        self.date_to = date_to                                   # exclusive
        self.report_from = report_from or date_from              # findings only for events from here
        self.medicine_items = set(medicine_items or ())          # itemcodes with medicine_type '10'
        self.monthly_qty = monthly_qty or {}                     # (branch, item) -> stkbal monthly rate
        self.on_hand = on_hand or {}                             # (branch, item) -> current stock
        self.sales = sales or {}                                 # (branch, docnumber, docdate, item) -> sold qty (115)
        self.returns_total = returns_total or {}                 # (branch, r_docnumber, r_docdate, item) -> returned qty, all dates
        self.ledger_from = ledger_from                           # oldest docdate held in the mirror
        self.counts = counts or {}                               # (branch, item) -> [counted stock-count rows]
        self.branch_hours = branch_hours or {}                   # branch -> {'is_24h', 'windows'} (BranchSettings)
        self.item_names = item_names or {}                       # itemcode → name
        self.branch_names = branch_names or {}                   # branchcode → (ar, en)
        self.excluded_item_codes = set(excluded_item_codes or ())
        self.channel_of_invoice = channel_of_invoice or {}       # (branch, docnumber, docdate) → channel
        self.channel_bucket = channel_bucket or {}               # channel → bucket
        self.returned_invoices = set(returned_invoices or ())    # (branch, docnumber, docdate) of returned 115s

    def item(self, code):
        return self.item_names.get(code) or code

    def branch(self, code, lang='ar'):
        ar, en = self.branch_names.get(code, (code, code))
        return ar if lang == 'ar' else en


# ── 1. Sales below cost ───────────────────────────────────────────────────────

def net_unit_price(l):
    """Sale price net of VAT. Phase 0: on 115 lines transprice INCLUDES VAT, additionaldiscp is the
    VAT rate (14) and itemsalestax the VAT amount; newcostprice is pre-VAT net cost."""
    price = l.transprice
    if l.itemsalestax and l.itemsalestax > 0:
        if l.additionaldiscp and l.additionaldiscp > 0:
            return price / (1 + l.additionaldiscp / HUNDRED)
        if l.itemsaleprice and l.itemsaleprice > 0 and l.itemsaleprice_tax:
            return price * l.itemsaleprice_tax / l.itemsaleprice
    return price


def check_sale_below_cost(lines, p, ctx):
    excluded_people = {str(c).strip() for c in p['excluded_personcodes']}
    excluded_buckets = set(p['excluded_channel_buckets'])
    min_pct, min_egp = _num(p['min_loss_pct']), _num(p['min_loss_egp'])
    crit_pct, crit_egp = _num(p['critical_loss_pct']), _num(p['critical_loss_egp'])
    out = []
    for l in lines:
        if l.doccode != '115' or l.transqty <= 0 or l.newcostprice <= 0:
            continue
        if l.personcode in excluded_people or l.itemcode in ctx.excluded_item_codes:
            continue
        channel = ctx.channel_of_invoice.get((l.branchcode, l.docnumber, l.docdate))
        if channel is not None and ctx.channel_bucket.get(channel) in excluded_buckets:
            continue
        net = net_unit_price(l)
        cost = l.newcostprice
        if net >= cost:
            continue
        loss_pct = (cost - net) / cost * HUNDRED
        loss_egp = (cost - net) * l.transqty
        if loss_pct < min_pct or loss_egp < min_egp:
            continue
        sev = 'critical' if (loss_pct >= crit_pct or loss_egp >= crit_egp) else 'warning'
        name = ctx.item(l.itemcode)
        out.append(dict(
            _base(l, ctx), severity=sev,
            dedup_key=f'{l.branchcode}|{l.docnumber}|{l.docdate}|{l.itemcode}|'
                      f'{l.trans_time.isoformat() if l.trans_time else ""}|{l.transprice}',
            value_egp=_q2(loss_egp), metric=loss_pct.quantize(Decimal('0.0001')), threshold=min_pct,
            evidence={'line': _line_ref(l), 'net_price': str(_q2(net)), 'cost': str(cost),
                      'loss_pct': str(_q2(loss_pct)), 'channel': channel},
            message_ar=f'بيع بأقل من التكلفة: «{name}» بسعر {_fmt(net)} (بدون الضريبة) والتكلفة {_fmt(cost)} — '
                       f'خسارة {_fmt(loss_egp)} ج.م ({_fmt(loss_pct)}%) — فاتورة {l.docnumber} في {ctx.branch(l.branchcode)}.',
            message_en=f'Sold below cost: “{name}” at {_fmt(net)} (ex-VAT) vs cost {_fmt(cost)} — '
                       f'loss {_fmt(loss_egp)} EGP ({_fmt(loss_pct)}%) — invoice {l.docnumber} at {ctx.branch(l.branchcode, "en")}.',
        ))
    return out


# ── 2. Duplicate lines / documents ────────────────────────────────────────────

def _line_sig(l):
    return (l.itemcode, l.transqty, l.transprice, l.itemexpirydate)


def check_duplicate_line(lines, p, ctx):
    """(a) the same line (item, qty, price, expiry) twice inside one document — OFF by default
        (`include_same_document`): live data showed these are SOFTECH saving an item scanned once per
        unit (same second, stock falling one unit per line), not a double posting;
    (b) two documents of the same type, branch and customer with IDENTICAL line sets,
        entered within `window_min` — unless one of them was returned (a correction).
    Different expiries = different batches, never a duplicate."""
    doccodes = set(p['doccodes'] or [])
    window = _dt.timedelta(minutes=int(p['window_min']))
    min_lines = int(p['cross_doc_min_lines'])
    docs = defaultdict(list)
    for l in lines:
        if doccodes and l.doccode not in doccodes:
            continue
        docs[(l.doccode, l.docnumber, l.docdate)].append(l)
    out = []

    # (a) within one document
    for (dc, dn, dd), ls in (docs.items() if p['include_same_document'] else ()):
        groups = defaultdict(list)
        for l in ls:
            groups[_line_sig(l)].append(l)
        for sig, g in groups.items():
            if len(g) < 2:
                continue
            first = min(g, key=lambda x: x.trans_time or _dt.datetime.max.replace(tzinfo=_dt.timezone.utc))
            extra = sum(x.transqty * x.newcostprice for x in g[1:])
            name = ctx.item(first.itemcode)
            out.append(dict(
                _base(first, ctx), severity='warning',
                dedup_key=f'in|{first.branchcode}|{dc}|{dn}|{dd}|{first.itemcode}|{first.transqty}|{first.transprice}|{first.itemexpirydate}',
                value_egp=_q2(extra), metric=Decimal(len(g)), threshold=Decimal(2),
                evidence={'kind': 'same_document', 'lines': [_line_ref(x) for x in g]},
                message_ar=f'سطر مكرر داخل نفس المستند: «{name}» × {first.transqty} مكرر {len(g)} مرات — '
                           f'مستند {dn} ({dc}) في {ctx.branch(first.branchcode)}.',
                message_en=f'Line repeated inside one document: “{name}” × {first.transqty}, {len(g)} times — '
                           f'document {dn} ({dc}) at {ctx.branch(first.branchcode, "en")}.',
            ))

    # (b) identical documents close in time
    by_sig = defaultdict(list)
    for (dc, dn, dd), ls in docs.items():
        if len(ls) < min_lines:
            continue
        t = min((x.trans_time for x in ls if x.trans_time), default=None)
        if t is None:
            continue
        sig = (dc, ls[0].personcode, tuple(sorted((str(a), str(b), str(c), str(d)) for a, b, c, d in map(_line_sig, ls))))
        by_sig[sig].append((t, dn, dd, ls))
    for (dc, person, _), docs_ in by_sig.items():
        docs_.sort(key=lambda x: x[0])
        i = 0
        while i < len(docs_):
            cluster = [docs_[i]]
            j = i + 1
            while j < len(docs_) and docs_[j][0] - cluster[0][0] <= window:
                cluster.append(docs_[j])
                j += 1
            i = j
            if len(cluster) < 2:
                continue
            if dc == '115' and any((c[3][0].branchcode, c[1], c[2]) in ctx.returned_invoices for c in cluster):
                continue                                         # one copy was returned → corrected
            first_t, first_dn, first_dd, first_ls = cluster[0]
            doc_value = sum(x.transqty * x.newcostprice for x in first_ls)
            l0 = first_ls[0]
            numbers = [c[1] for c in cluster]
            out.append(dict(
                _base(l0, ctx), severity='warning', occurred_at=first_t,
                dedup_key=f'docs|{l0.branchcode}|{dc}|{first_dn}|{first_dd}',
                value_egp=_q2(doc_value * (len(cluster) - 1)), metric=Decimal(len(cluster)), threshold=Decimal(2),
                evidence={'kind': 'identical_documents', 'documents': numbers,
                          'lines': [_line_ref(x) for c in cluster for x in c[3]]},
                message_ar=f'مستندات متطابقة خلال {p["window_min"]} دقيقة: {len(cluster)} مستندات ({dc}) بنفس الأصناف '
                           f'والكميات والأسعار — {", ".join(map(str, numbers))} في {ctx.branch(l0.branchcode)}.',
                message_en=f'Identical documents within {p["window_min"]} min: {len(cluster)} documents ({dc}) with the same '
                           f'items, quantities and prices — {", ".join(map(str, numbers))} at {ctx.branch(l0.branchcode, "en")}.',
            ))
    return out


# ── 3. Price variance inside one invoice ──────────────────────────────────────

def check_price_variance_invoice(lines, p, ctx):
    ratio, warn_ratio, floor = _num(p['ratio']), _num(p['warning_ratio']), _num(p['min_price_egp'])
    groups = defaultdict(list)
    for l in lines:
        if l.doccode == '115' and l.transprice >= floor and l.transqty > 0:
            groups[(l.docnumber, l.docdate, l.itemcode)].append(l)
    out = []
    for (dn, dd, ic), g in groups.items():
        if len(g) < 2:
            continue
        lo = min(x.transprice for x in g)
        hi = max(x.transprice for x in g)
        r = hi / lo
        if r <= ratio:
            continue
        low_qty = sum(x.transqty for x in g if x.transprice == lo)
        first = g[0]
        name = ctx.item(ic)
        out.append(dict(
            _base(first, ctx), severity='warning' if r > warn_ratio else 'info',
            dedup_key=f'{first.branchcode}|{dn}|{dd}|{ic}',
            value_egp=_q2((hi - lo) * low_qty), metric=r.quantize(Decimal('0.0001')), threshold=ratio,
            evidence={'low': str(lo), 'high': str(hi), 'lines': [_line_ref(x) for x in g]},
            message_ar=f'سعران مختلفان لنفس الصنف في فاتورة واحدة: «{name}» من {_fmt(lo)} إلى {_fmt(hi)} '
                       f'(× {r:.2f}) — فاتورة {dn} في {ctx.branch(first.branchcode)}.',
            message_en=f'Two prices for the same item on one invoice: “{name}” {_fmt(lo)} to {_fmt(hi)} '
                       f'(× {r:.2f}) — invoice {dn} at {ctx.branch(first.branchcode, "en")}.',
        ))
    return out


# ── 5. Stock adjustments ──────────────────────────────────────────────────────

_ADJ_LABEL_AR = {'50': 'فائض جرد', '150': 'عجز جرد', '160': 'صرف هالك'}
_ADJ_LABEL_EN = {'50': 'count surplus', '150': 'count deficit', '160': 'write-off'}


def _adj_value(l):
    return abs(l.transqty) * l.newcostprice


def check_stock_adjustment(lines, p, ctx):
    """(a) any single adjustment worth ≥ single_egp at cost; (b) ≥ count adjustments on one item
    in the last `days` days (one finding per item per month of its latest adjustment)."""
    codes = set(p['doccodes'])
    single, crit = _num(p['single_egp']), _num(p['critical_egp'])
    since = ctx.date_to - _dt.timedelta(days=int(p['days']))
    adj = [l for l in lines if l.doccode in codes]
    out = []
    for l in adj:
        v = _adj_value(l)
        if v < single:
            continue
        name = ctx.item(l.itemcode)
        out.append(dict(
            _base(l, ctx), severity='critical' if v >= crit else 'warning',
            dedup_key=f'one|{l.branchcode}|{l.doccode}|{l.docnumber}|{l.docdate}|{l.itemcode}|'
                      f'{l.trans_time.isoformat() if l.trans_time else ""}',
            value_egp=_q2(v), metric=_q2(v), threshold=single,
            evidence={'kind': 'single', 'line': _line_ref(l)},
            message_ar=f'{_ADJ_LABEL_AR.get(l.doccode, l.doccode)} بقيمة {_fmt(v)} ج.م بالتكلفة: «{name}» × {abs(l.transqty)} — '
                       f'مستند {l.docnumber} في {ctx.branch(l.branchcode)}.',
            message_en=f'{_ADJ_LABEL_EN.get(l.doccode, l.doccode).capitalize()} worth {_fmt(v)} EGP at cost: “{name}” × {abs(l.transqty)} — '
                       f'document {l.docnumber} at {ctx.branch(l.branchcode, "en")}.',
        ))
    per_item = defaultdict(list)
    for l in adj:
        if l.docdate >= since:
            per_item[l.itemcode].append(l)
    for ic, g in per_item.items():
        if len(g) < int(p['count']):
            continue
        g.sort(key=lambda x: (x.docdate, x.trans_time or _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)))
        last = g[-1]
        gross = sum(_adj_value(x) for x in g)
        net_qty = sum(x.transqty if x.doccode == '50' else -x.transqty for x in g)
        users = sorted({x.usercode for x in g if x.usercode})
        name = ctx.item(ic)
        out.append(dict(
            _base(last, ctx), severity='critical' if gross >= crit else 'warning',
            dedup_key=f'count|{last.branchcode}|{ic}|{last.docdate:%Y-%m}',
            value_egp=_q2(gross), metric=Decimal(len(g)), threshold=Decimal(int(p['count'])),
            evidence={'kind': 'repeated', 'days': int(p['days']), 'net_qty': str(net_qty), 'users': users,
                      'lines': [_line_ref(x) for x in g]},
            message_ar=f'تسويات متكررة: «{name}» {len(g)} تسويات خلال {p["days"]} يوم بقيمة {_fmt(gross)} ج.م '
                       f'(صافي الكمية {net_qty:+}) في {ctx.branch(last.branchcode)}.',
            message_en=f'Repeated adjustments: “{name}” {len(g)} adjustments in {p["days"]} days worth {_fmt(gross)} EGP '
                       f'(net qty {net_qty:+}) at {ctx.branch(last.branchcode, "en")}.',
        ))
    return out



# ── 4. Purchase cost fluctuation ──────────────────────────────────────────────

def check_cost_fluctuation(lines, p, ctx):
    """A purchase (10) unit cost that differs from the PREVIOUS purchase of the same item at the
    same branch — from the SAME supplier by default (`same_supplier_only`; comparing suppliers is the
    supplier price comparison screen's job) — in an earlier document within `lookback_days`, by more
    than `change_pct`, either way. `excluded_suppliers` (default the بدل الروشتة virtual suppliers
    4469–4472, which are buy-backs, not supply) are ignored.
    Free-goods lines are never compared: SOFTECH writes them as a separate line with pharmacydiscp = 100
    and a small non-zero price (the VAT on the free goods), so a price test alone does not catch them.
    Lines of the same document are never compared with each other."""
    change, warn = _num(p['change_pct']), _num(p['warning_pct'])
    lookback = _dt.timedelta(days=int(p['lookback_days']))
    skip = {str(c).strip() for c in p['excluded_suppliers']}
    by_item = defaultdict(list)
    for l in lines:
        sup = l.personcode or l.suppliercode
        if (l.doccode == '10' and l.transprice > 0 and l.transqty > 0 and l.pharmacydiscp < HUNDRED
                and sup not in skip):
            by_item[(l.itemcode, sup) if p['same_supplier_only'] else (l.itemcode, '')].append(l)
    out = []
    for (ic, _sup), g in by_item.items():
        g.sort(key=lambda x: (x.docdate, x.trans_time or _EPOCH))
        for i, l in enumerate(g):
            if l.docdate < ctx.report_from:
                continue
            prev = next((x for x in reversed(g[:i]) if (x.docnumber, x.docdate) != (l.docnumber, l.docdate)), None)
            if prev is None or l.docdate - prev.docdate > lookback:
                continue
            pct = (l.transprice - prev.transprice) / prev.transprice * HUNDRED
            if abs(pct) <= change:
                continue
            name = ctx.item(ic)
            word_ar, word_en = ('ارتفاع', 'up') if pct > 0 else ('انخفاض', 'down')
            out.append(dict(
                _base(l, ctx), severity='warning' if abs(pct) > warn else 'info',
                dedup_key=f'{l.branchcode}|{l.docnumber}|{l.docdate}|{ic}',
                value_egp=_q2(abs(l.transprice - prev.transprice) * l.transqty),
                metric=pct.quantize(Decimal('0.0001')), threshold=change,
                evidence={'line': _line_ref(l), 'previous': _line_ref(prev), 'change_pct': str(_q2(pct))},
                message_ar=f'{word_ar} تكلفة الشراء {_fmt(abs(pct))}%: «{name}» من {_fmt(prev.transprice)} '
                           f'(مستند {prev.docnumber} بتاريخ {prev.docdate}، مورد {prev.personcode or prev.suppliercode}) إلى '
                           f'{_fmt(l.transprice)} (مورد {l.personcode or l.suppliercode}) — مستند {l.docnumber} في {ctx.branch(l.branchcode)}.',
                message_en=f'Purchase cost {word_en} {_fmt(abs(pct))}%: “{name}” from {_fmt(prev.transprice)} '
                           f'(document {prev.docnumber} on {prev.docdate}, supplier {prev.personcode or prev.suppliercode}) to '
                           f'{_fmt(l.transprice)} (supplier {l.personcode or l.suppliercode}) — document {l.docnumber} at {ctx.branch(l.branchcode, "en")}.',
            ))
    return out


# ── 6. Frequent stock-outs ────────────────────────────────────────────────────

def check_frequent_stockout(lines, p, ctx):
    """A medicine whose stock hit 0 (newqty = 0 after a sale, transfer out, deficit or reservation
    delivery) at least `count` times in the last `days` days, for items selling at least
    `min_monthly_qty` a month. One finding per item per month of its latest stock-out."""
    codes = set(p['doccodes'])
    since = ctx.date_to - _dt.timedelta(days=int(p['days']))
    min_rate = _num(p['min_monthly_qty'])
    per_item = defaultdict(list)
    for l in lines:
        if l.doccode in codes and l.newqty == 0 and l.docdate >= since and l.itemcode in ctx.medicine_items:
            per_item[l.itemcode].append(l)
    out = []
    for ic, g in per_item.items():
        if len(g) < int(p['count']):
            continue
        bc = g[0].branchcode
        rate = ctx.monthly_qty.get((bc, ic), ZERO)
        if rate < min_rate:
            continue
        g.sort(key=lambda x: (x.docdate, x.trans_time or _EPOCH))
        last = g[-1]
        if last.docdate < ctx.report_from:
            continue
        now = ctx.on_hand.get((bc, ic))
        now_ar = '' if now is None else f' — الرصيد الآن {_fmt(now)}'
        now_en = '' if now is None else f' — stock now {_fmt(now)}'
        name = ctx.item(ic)
        out.append(dict(
            _base(last, ctx), severity='info',
            dedup_key=f'{bc}|{ic}|{last.docdate:%Y-%m}',
            value_egp=ZERO, metric=Decimal(len(g)), threshold=Decimal(int(p['count'])),
            evidence={'days': int(p['days']), 'monthly_qty': str(rate),
                      'on_hand_now': None if now is None else str(now), 'lines': [_line_ref(x) for x in g]},
            message_ar=f'نفاد متكرر: «{name}» وصل رصيده صفر {len(g)} مرات خلال {p["days"]} يوم، ومعدل بيعه '
                       f'{_fmt(rate)} شهرياً{now_ar} في {ctx.branch(bc)}.',
            message_en=f'Frequent stock-out: “{name}” hit zero {len(g)} times in {p["days"]} days, selling '
                       f'{_fmt(rate)} a month{now_en} at {ctx.branch(bc, "en")}.',
        ))
    return out


# ── 10. Returns without an invoice / more than sold ───────────────────────────

def check_return_without_invoice(lines, p, ctx):
    """Customer returns (30): (a) no original invoice number; (b) the item is not on the referenced
    sale although that sale's date is inside the mirror; (c) more returned — over ALL returns against
    that invoice — than was sold on it. A reference older than the mirror is skipped (cannot be checked)."""
    tol = _num(p['qty_tolerance'])
    out = []
    seen = set()
    for l in lines:
        if l.doccode != '30' or l.docdate < ctx.report_from:
            continue
        name = ctx.item(l.itemcode)
        refund = abs(l.transqty) * l.transprice
        if not l.r_docnumber:
            out.append(dict(
                _base(l, ctx), severity='warning',
                dedup_key=f'noref|{l.branchcode}|{l.docnumber}|{l.docdate}|{l.itemcode}',
                value_egp=_q2(refund), metric=None, threshold=None,
                evidence={'kind': 'no_invoice', 'line': _line_ref(l)},
                message_ar=f'مرتجع بدون رقم فاتورة بيع: «{name}» × {abs(l.transqty)} بقيمة {_fmt(refund)} ج.م — '
                           f'مرتجع {l.docnumber} في {ctx.branch(l.branchcode)}.',
                message_en=f'Return with no sale invoice: “{name}” × {abs(l.transqty)} worth {_fmt(refund)} EGP — '
                           f'return {l.docnumber} at {ctx.branch(l.branchcode, "en")}.',
            ))
            continue
        if l.r_docdate is None or (ctx.ledger_from and l.r_docdate < ctx.ledger_from):
            continue                                             # original outside the mirror
        ref = (l.branchcode, l.r_docnumber, l.r_docdate, l.itemcode)
        if ref in seen:
            continue
        seen.add(ref)
        sold = ctx.sales.get(ref)
        returned = ctx.returns_total.get(ref, abs(l.transqty))
        reference = {'docnumber': l.r_docnumber, 'docdate': l.r_docdate.isoformat()}
        if sold is None:
            out.append(dict(
                _base(l, ctx), severity='warning',
                dedup_key=f'notfound|{l.branchcode}|{l.r_docnumber}|{l.r_docdate}|{l.itemcode}',
                value_egp=_q2(refund), metric=None, threshold=None,
                evidence={'kind': 'invoice_not_found', 'line': _line_ref(l), 'reference': reference},
                message_ar=f'مرتجع لصنف غير موجود في فاتورة البيع المذكورة: «{name}» — الفاتورة {l.r_docnumber} '
                           f'بتاريخ {l.r_docdate} — مرتجع {l.docnumber} في {ctx.branch(l.branchcode)}.',
                message_en=f'Return of an item not on the stated sale invoice: “{name}” — invoice {l.r_docnumber} '
                           f'of {l.r_docdate} — return {l.docnumber} at {ctx.branch(l.branchcode, "en")}.',
            ))
            continue
        if returned - sold > tol:
            extra = returned - sold
            out.append(dict(
                _base(l, ctx), severity='critical',
                dedup_key=f'over|{l.branchcode}|{l.r_docnumber}|{l.r_docdate}|{l.itemcode}',
                value_egp=_q2(extra * l.transprice), metric=_q2(returned), threshold=_q2(sold),
                evidence={'kind': 'over_returned', 'sold': str(sold), 'returned': str(returned),
                          'line': _line_ref(l), 'reference': reference},
                message_ar=f'مرتجع أكثر من المباع: «{name}» بيع منه {_fmt(sold)} في الفاتورة {l.r_docnumber} '
                           f'وارتُجع {_fmt(returned)} — في {ctx.branch(l.branchcode)}.',
                message_en=f'Returned more than sold: “{name}” sold {_fmt(sold)} on invoice {l.r_docnumber}, '
                           f'returned {_fmt(returned)} — at {ctx.branch(l.branchcode, "en")}.',
            ))
    return out


# ── 11. Adjustment after a count that does not match it ───────────────────────

def check_adjustment_after_count(lines, p, ctx):
    """Surplus/deficit (50/150) entered within `hours` after a stock-count snapshot that covered the
    item, where the net adjustment differs from the counted difference by more than `qty_tolerance`
    (incl. an adjustment on an item that counted as matching). Posting exactly the counted result is
    the normal close of a count and is not flagged."""
    window = _dt.timedelta(hours=int(p['hours']))
    tol = _num(p['qty_tolerance'])
    adj = defaultdict(list)
    for l in lines:
        if l.doccode in ('50', '150') and l.trans_time:
            adj[l.itemcode].append(l)
    out = []
    for ic, ls in adj.items():
        bc = ls[0].branchcode
        for c in ctx.counts.get((bc, ic), []):
            start, end = c['snapshot_at'], c['snapshot_at'] + window
            hit = sorted((l for l in ls if start <= l.trans_time <= end), key=lambda x: x.trans_time)
            if not hit or hit[-1].docdate < ctx.report_from:
                continue
            net = sum(l.transqty if l.doccode == '50' else -l.transqty for l in hit)
            diff = c['difference']
            if abs(net - diff) <= tol:
                continue
            name = ctx.item(ic)
            out.append(dict(
                _base(hit[-1], ctx), severity='warning',
                dedup_key=f'{bc}|{c["session_id"]}|{ic}',
                value_egp=_q2(abs(net - diff) * hit[-1].newcostprice), metric=_q2(net), threshold=_q2(diff),
                evidence={'session_id': c['session_id'], 'snapshot_at': c['snapshot_at'].isoformat(),
                          'expected': str(c['expected']), 'counted': str(c['counted']), 'difference': str(diff),
                          'net_adjustment': str(net), 'lines': [_line_ref(x) for x in hit]},
                message_ar=f'تسوية لا تطابق الجرد: «{name}» — فرق الجرد {diff:+} وصافي التسوية {net:+} خلال '
                           f'{p["hours"]} ساعة من جلسة الجرد #{c["session_id"]} في {ctx.branch(bc)}.',
                message_en=f'Adjustment does not match the count: “{name}” — counted difference {diff:+}, net '
                           f'adjustment {net:+} within {p["hours"]} h of count session #{c["session_id"]} at {ctx.branch(bc, "en")}.',
            ))
    return out



# ── 9. Entries outside branch working hours ───────────────────────────────────

_DOC_AR = {'115': 'بيع', '30': 'مرتجع', '10': 'شراء', '120': 'مرتجع لمورد', '50': 'فائض جرد', '150': 'عجز جرد',
           '160': 'هالك', '125': 'صرف لفرع', '25': 'استلام من فرع', '110': 'صرف للفرع', '15': 'استلام من الرئيسي',
           '80': 'حجز', '180': 'تسليم حجز', '181': 'إلغاء حجز', '170': 'صرف مصروفات'}


def check_after_hours_entry(lines, p, ctx):
    """A document entered outside its branch's working hours (BranchSettings, local time) by more than
    `grace_min`. Branches open 24 hours, and branches with no hours set, are never flagged. A window
    may apply to some document types only (e.g. the HQ call center until midnight). One finding per
    document; warning when more than `warning_after_min` outside."""
    if not lines:
        return []
    bc = lines[0].branchcode
    hours = ctx.branch_hours.get(bc)
    if not hours or hours.get('is_24h') or not hours.get('windows'):
        return []
    from apps.branches.hours import describe, minutes_outside
    from django.utils import timezone as _tz
    codes = set(p['doccodes'] or [])
    skip_users = {str(u).strip() for u in p['excluded_users']}
    grace, warn = int(p['grace_min']), int(p['warning_after_min'])
    docs = defaultdict(list)
    for l in lines:
        if l.trans_time and l.docdate >= ctx.report_from and (not codes or l.doccode in codes) \
                and l.usercode not in skip_users:
            docs[(l.doccode, l.docnumber, l.docdate)].append(l)
    out = []
    for (dc, dn, dd), ls in docs.items():
        first = min(ls, key=lambda x: x.trans_time)
        local = _tz.localtime(first.trans_time)
        gap = minutes_outside(hours['windows'], local.hour * 60 + local.minute, dc, grace)
        if not gap:                                          # inside (0), or no window covers this document type
            continue
        value = sum(abs(x.transqty) * x.newcostprice for x in ls)
        label = _DOC_AR.get(dc, dc)
        when = local.strftime('%H:%M')
        span = describe(hours['windows'])
        out.append(dict(
            _base(first, ctx), severity='warning' if gap > warn else 'info',
            dedup_key=f'{bc}|{dc}|{dn}|{dd}',
            value_egp=_q2(value), metric=Decimal(gap), threshold=Decimal(grace),
            evidence={'local_time': local.isoformat(), 'minutes_outside': gap, 'hours': hours['windows'],
                      'lines': [_line_ref(x) for x in ls[:50]], 'line_count': len(ls)},
            message_ar=f'إدخال خارج مواعيد العمل: {label} {dn} أُدخل الساعة {when} (مواعيد الفرع {span}) — '
                       f'{len(ls)} سطر بقيمة {_fmt(value)} ج.م بالتكلفة — في {ctx.branch(bc)}.',
            message_en=f'Entry outside working hours: {dc} {dn} entered at {when} (branch hours {span}) — '
                       f'{len(ls)} lines worth {_fmt(value)} EGP at cost — at {ctx.branch(bc, "en")}.',
        ))
    return out


def adjustments_by_user(lines, doccodes=('50', '150', '160')):
    """Check 5 ranking (always shown, no threshold): per SOFTECH user → count, gross value, by doccode."""
    out = defaultdict(lambda: {'count': 0, 'value_egp': ZERO, 'by_doccode': defaultdict(int)})
    for l in lines:
        if l.doccode not in doccodes:
            continue
        r = out[(l.branchcode, l.usercode)]
        r['count'] += 1
        r['value_egp'] += _adj_value(l)
        r['by_doccode'][l.doccode] += 1
    return sorted(({'branchcode': b, 'usercode': u, 'count': r['count'], 'value_egp': _q2(r['value_egp']),
                    'by_doccode': dict(r['by_doccode'])} for (b, u), r in out.items()),
                  key=lambda x: -x['value_egp'])


# ── Registry ──────────────────────────────────────────────────────────────────
# schema: param → ('number', min, max) | ('codes',) | ('bool',) — validated in params.validate_params.
# `doccodes` = what the engine loads; `lookback` = days of lines the rule needs (≥ the engine window).

RULES = {
    'sale_below_cost': {
        'number': 1, 'name_ar': 'بيع بأقل من التكلفة', 'name_en': 'Sales below cost',
        'fn': check_sale_below_cost, 'doccodes': ['115'],
        'defaults': {'min_loss_pct': 5, 'min_loss_egp': 20, 'critical_loss_pct': 30, 'critical_loss_egp': 500,
                     'excluded_personcodes': ['4785', '4283'], 'excluded_channel_buckets': ['credit']},
        'schema': {'min_loss_pct': ('number', 0, 100), 'min_loss_egp': ('number', 0, 1_000_000),
                   'critical_loss_pct': ('number', 0, 100), 'critical_loss_egp': ('number', 0, 10_000_000),
                   'excluded_personcodes': ('codes',), 'excluded_channel_buckets': ('codes',)},
    },
    'duplicate_line': {
        'number': 2, 'name_ar': 'سطور ومستندات مكررة', 'name_en': 'Duplicate lines and documents',
        'fn': check_duplicate_line, 'doccodes': None,
        'defaults': {'window_min': 20, 'cross_doc_min_lines': 2, 'doccodes': [], 'include_same_document': False},
        'schema': {'window_min': ('number', 1, 1440), 'cross_doc_min_lines': ('number', 1, 100),
                   'doccodes': ('codes',), 'include_same_document': ('bool',)},
    },
    'price_variance_invoice': {
        'number': 3, 'name_ar': 'اختلاف السعر داخل الفاتورة', 'name_en': 'Price variance within an invoice',
        'fn': check_price_variance_invoice, 'doccodes': ['115'],
        'defaults': {'ratio': 1.10, 'warning_ratio': 1.5, 'min_price_egp': 1},
        'schema': {'ratio': ('number', 1, 100), 'warning_ratio': ('number', 1, 100),
                   'min_price_egp': ('number', 0, 100_000)},
    },
    'cost_fluctuation': {
        'number': 4, 'name_ar': 'تذبذب تكلفة الشراء', 'name_en': 'Purchase cost fluctuation',
        'fn': check_cost_fluctuation, 'doccodes': ['10'], 'lookback_param': 'lookback_days',
        'lookback_from': 'report_from',
        'defaults': {'change_pct': 20, 'warning_pct': 50, 'lookback_days': 90, 'same_supplier_only': True,
                     'excluded_suppliers': ['4469', '4470', '4471', '4472']},
        'schema': {'change_pct': ('number', 1, 1000), 'warning_pct': ('number', 1, 1000),
                   'lookback_days': ('number', 7, 365), 'same_supplier_only': ('bool',),
                   'excluded_suppliers': ('codes',)},
    },
    'stock_adjustment': {
        'number': 5, 'name_ar': 'تسويات المخزون', 'name_en': 'Stock adjustments',
        'fn': check_stock_adjustment, 'doccodes': ['50', '150', '160'], 'lookback_param': 'days',
        'defaults': {'doccodes': ['50', '150', '160'], 'count': 3, 'days': 30,
                     'single_egp': 500, 'critical_egp': 2000},
        'schema': {'doccodes': ('codes',), 'count': ('number', 2, 1000), 'days': ('number', 1, 365),
                   'single_egp': ('number', 0, 10_000_000), 'critical_egp': ('number', 0, 10_000_000)},
    },
    'frequent_stockout': {
        'number': 6, 'name_ar': 'نفاد متكرر للرصيد', 'name_en': 'Frequent stock-outs',
        'fn': check_frequent_stockout, 'doccodes': ['115', '125', '150', '180'], 'lookback_param': 'days',
        'defaults': {'doccodes': ['115', '125', '150', '180'], 'count': 3, 'days': 30, 'min_monthly_qty': 1},
        'schema': {'doccodes': ('codes',), 'count': ('number', 2, 1000), 'days': ('number', 1, 365),
                   'min_monthly_qty': ('number', 0, 100_000)},
    },
    'after_hours_entry': {
        'number': 9, 'name_ar': 'إدخال خارج مواعيد العمل', 'name_en': 'Entries outside working hours',
        'fn': check_after_hours_entry, 'doccodes': None,
        'defaults': {'grace_min': 30, 'warning_after_min': 120, 'doccodes': [], 'excluded_users': []},
        'schema': {'grace_min': ('number', 0, 240), 'warning_after_min': ('number', 0, 1440),
                   'doccodes': ('codes',), 'excluded_users': ('codes',)},
    },
    'return_without_invoice': {
        'number': 10, 'name_ar': 'مرتجعات بدون فاتورة أو أكثر من المباع', 'name_en': 'Returns without invoice or over sold',
        'fn': check_return_without_invoice, 'doccodes': ['30'],
        'defaults': {'qty_tolerance': 0},
        'schema': {'qty_tolerance': ('number', 0, 1000)},
    },
    'adjustment_after_count': {
        'number': 11, 'name_ar': 'تسوية لا تطابق الجرد', 'name_en': 'Adjustment not matching the count',
        'fn': check_adjustment_after_count, 'doccodes': ['50', '150'],
        'defaults': {'hours': 48, 'qty_tolerance': 0},
        'schema': {'hours': ('number', 1, 720), 'qty_tolerance': ('number', 0, 1000)},
    },
}
