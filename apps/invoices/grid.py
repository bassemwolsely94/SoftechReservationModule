"""
apps/invoices/grid.py

Bridge between the stored InvoiceLine / catalog Item and the pure SofTech column
engine (softech_columns). The backend owns every number (CLAUDE.md rule #7): the
grid UI sends edited cells, the server recomputes via softech_columns and returns
the consistent row — the frontend never does the money math.

The discount BASE (itemsaleprice_tax) and the tax rate come from the catalog mirror
(Item.pack_price / pack_price_tax / sale_tax_pct), so a keystroke recompute needs
no SofTech round-trip.
"""
from __future__ import annotations

from . import softech_columns as sc


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def item_price_base(item):
    """(public P, pre-tax base Pb, rate%) for a catalog Item. Rate is derived from
    the P/Pb ratio (authoritative — sale_tax_pct is 0 on some taxed items), falling
    back to sale_tax_pct, then 0."""
    if item is None:
        return 0.0, 0.0, 0.0
    P  = _f(getattr(item, 'pack_price', 0))
    Pb = _f(getattr(item, 'pack_price_tax', 0))
    if P > 0 and Pb > 0:
        rate = round((P / Pb - 1) * 100, 4)
    else:
        rate = _f(getattr(item, 'sale_tax_pct', 0))
    return P, Pb, rate


def effective_tax(line):
    """(public, pre-tax base Pb, rate%, conflict) for a line, with the INVOICE's own
    VAT rate taking priority over the catalog-derived rate.

    Why: the catalog rate comes from the item master's pack_price / pack_price_tax
    ratio, which is DIRTY on some items — an item that is actually taxed can have
    pack_price_tax == pack_price in the master (→ derived 0%). The physical invoice
    (what the distributor billed, read by OCR into line.vat_pct) is authoritative for
    THIS purchase, so when the OCR'd rate is present and disagrees with the catalog we
    use it and recompute Pb = public / (1 + rate) to stay consistent. The disagreement
    is flagged (`conflict`) so a human verifies it — never silently trusted, per the
    deterministic/auditable rule. (Reconciliation proof: an item written exempt off a
    dirty catalog under-charged VAT and made the whole invoice miss the paper total.)"""
    if not line.item_id:
        return _f(line.public_price), 0.0, _f(getattr(line, 'vat_pct', 0)), False
    P_cat, Pb_cat, rate_cat = item_price_base(line.item)
    public = _f(line.public_price) or P_cat
    if not Pb_cat and not rate_cat:
        # No pre-tax base in the catalog and no VAT: the base IS the public price (what
        # pricing.compute_line did for every 0 % line) — never post a base of 0.
        Pb_cat = public
    ocr_rate = _f(getattr(line, 'vat_pct', 0))
    if ocr_rate > 0 and abs(ocr_rate - rate_cat) > 0.5:
        base = (public / (1 + ocr_rate / 100.0)) if ocr_rate else public
        return public, round(base, 4), ocr_rate, True
    return public, Pb_cat, rate_cat, False


def line_cells(line, fold_margin: bool = False) -> dict:
    """Engine cells from a stored line — the SofTech column set: catalog public +
    pre-tax base, the THREE discounts, qty, bonus, the VAT rate and tax-base flag.

    The VAT rate / base come from effective_tax(): the invoice's own OCR'd rate wins
    over a dirty catalog rate (and is flagged for review when they disagree).

    ``fold_margin`` (PharmaOverseas-style vendors): the distributor fixed margin
    (هامش ثابت للموزع) is FOLDED INTO the unit cost that posts to SOFTECH, because the
    human bakes it in (cost = net + margin) and the invoice's grand total includes it.
    The engine's unit_cost then = net + margin, so the back-solved discount matches the
    human's SofTech line. VAT and margin never coexist on one line (مانعان متبادلان —
    a line is either taxed OR margin-eligible), so folding never touches VAT. For
    RAMCO-style vendors the margin is display-only and fold_margin is False."""
    public, Pb, rate, _conflict = effective_tax(line)
    net    = _f(line.unit_price)                                   # OCR سعر صيدلي (pre-margin)
    margin = _f(getattr(line, 'distributor_margin_amt', 0)) if fold_margin else 0.0
    if margin > 0:
        # A margin-eligible (Egyptian-made) medicine is never VAT-taxed — VAT and the
        # fixed margin are mutually exclusive — so ignore any phantom rate a dirty
        # catalog ratio would imply and treat the line as exempt (Pb = public).
        rate, Pb = 0.0, public
    return {
        'public_price':     public,
        'base_price':       Pb,                       # السعر الأساسى (pre-VAT base)
        'vat_pct':          rate,
        'quantity':         _f(line.quantity),
        'disc_pct':         _f(line.discount_pct),
        'extra_disc_pct':   _f(line.extra_discount_pct),
        'special_disc_pct': _f(getattr(line, 'special_discount_pct', 0)),
        'tax_from_cost':    bool(getattr(line, 'tax_from_cost', True)),
        'unit_cost':        net + margin,             # = التكلفة للترحيل (what SofTech stores)
        'margin_in_cost':   margin,                   # lets the engine split net ⟷ cost to post
        'bonus_qty':        _f(line.bonus_qty),
        '_net_cost':        net,                      # تكلفة الوحدة (OCR net, pre-margin)
        '_distributor_margin': margin,                # هامش الموزع folded in (0 if not folding)
    }


def invoice_folds_margin(invoice, lines=None) -> bool:
    """Whether this invoice's distributor fixed margin folds INTO the posted unit cost
    (PharmaOverseas-style) or is display-only (RAMCO-style).

    Priority: (1) explicit per-vendor flag ocr_profile['fold_distributor_margin'];
    (2) else AUTO-DETECT from the printed grand total — fold when it matches
    Σ(net×qty)+Σ(tax×qty)+Σ(margin×qty) better than the no-margin total (and the
    margin is non-zero). Auto-detect lets a new supplier's behaviour be learned from
    its own invoice before anyone sets a flag."""
    vendor = getattr(invoice, 'vendor', None)
    prof = (getattr(vendor, 'ocr_profile', None) or {})
    if 'fold_distributor_margin' in prof:
        return bool(prof['fold_distributor_margin'])
    declared = _f(getattr(invoice, 'declared_total', 0))
    if declared <= 0:
        return False
    if lines is None:
        lines = list(invoice.lines.all())
    net_t = tax_t = margin_t = 0.0
    for ln in lines:
        cells = line_cells(ln, fold_margin=False)
        row = sc.recompute(cells, changed='unit_cost' if _f(ln.unit_price) > 0 else None)
        qty = _f(cells.get('quantity'))
        net_t += _f(row.get('cost_total'))
        tax_t += _f(row.get('vat_amount')) * qty
        margin_t += _f(getattr(ln, 'distributor_margin_amt', 0)) * qty
    if margin_t <= 0:
        return False
    with_m, without = net_t + tax_t + margin_t, net_t + tax_t
    return (abs(declared - with_m) < abs(declared - without)
            and abs(declared - with_m) <= max(1.0, 0.01 * declared))


# public price vs catalog beyond this fraction → likely another row's numbers
# (real price rises are smaller and show as the «سعر جديد؟» chip instead)
ROW_SHIFT_PRICE_GAP = 0.35


def _needs_review(line, cells) -> tuple[bool, list]:
    """Which lines the operator must actually check — so a near-perfect extraction
    needs only a QUICK review of the few uncertain lines, not the whole invoice.
    Returns (needs_review, [arabic reasons])."""
    reasons = []
    if not line.item_id:
        reasons.append('صنف غير مطابق')
    elif getattr(line, 'needs_pick', False):
        reasons.append('اختر الصنف')
    if getattr(line, 'match_review', False):
        reasons.append('مطابقة غير مؤكدة')
    if line.item_id and (getattr(line, 'match_score', None) or 1) < 0.75:
        reasons.append('نسبة تطابق منخفضة')
    notes = getattr(line, 'notes', '') or ''
    if 'مُصحّحة' in notes:
        reasons.append('الكمية مُصحّحة آلياً')
    from .reconcile import COLUMN_SHIFT_NOTE, MARGIN_MISMATCH_NOTE
    if COLUMN_SHIFT_NOTE in notes:
        reasons.append('أعمدة الأرقام كانت مُزاحة — راجع الخصم والتكلفة')
    if MARGIN_MISMATCH_NOTE in notes:
        reasons.append('الصافي لا يطابق الهوامش والخصم')
    # A public price far from the catalog's usually means OCR attached ANOTHER row's
    # numbers to this item (seen on invoice 224: «جولدن فير» got 192 instead of 34).
    cat_public = _f(line.item.pack_price) if line.item_id else 0.0
    ocr_public = _f(line.public_price)
    if cat_public > 0 and ocr_public > 0 and abs(ocr_public / cat_public - 1) > ROW_SHIFT_PRICE_GAP:
        reasons.append('سعر الجمهور بعيد عن الكتالوج — قد تكون أرقام سطر آخر')
    if (getattr(line, 'ocr_confidence', None) or 1) < 0.5:
        reasons.append('ثقة قراءة منخفضة')
    if _f(cells.get('unit_cost')) <= 0 and _f(cells.get('public_price')) <= 0:
        reasons.append('سعر مفقود')
    if _f(cells.get('quantity')) <= 0:
        reasons.append('كمية مفقودة')
    # VAT rate from the invoice disagrees with the catalog → the invoice rate was used
    # (catalog tax data can be dirty); surface it so the operator confirms the tax.
    if effective_tax(line)[3]:
        reasons.append('ضريبة الصنف من الفاتورة تخالف الكتالوج — راجعها')
    # VAT and a distributor margin are mutually exclusive (a line is either taxed OR
    # margin-eligible, never both) — their coexistence means an OCR misread.
    if _f(getattr(line, 'vat_pct', 0)) > 0 and _f(getattr(line, 'distributor_margin_amt', 0)) > 0:
        reasons.append('صنف خاضع للضريبة وله هامش معاً — غير ممكن، راجع')
    return bool(reasons), reasons


def _current_stock(item, stock_map):
    """Live warehouse stock for an item: stock_map (SOFTECH stkbal) when present,
    else the catalog mirror's nowqty, else None (no matched item)."""
    if item is None:
        return None
    sid = str(getattr(item, 'softech_id', '') or '')
    if stock_map and sid in stock_map:
        return _f(stock_map[sid])
    return _f(getattr(item, 'nowqty', 0))


def grid_row(line, stock_map: dict | None = None, fold_margin: bool = False) -> dict:
    """The full SofTech-column view for one stored line: recomputed cells (respecting
    an OCR-supplied net cost), the two-line FOC preview, and the new/old price check.
    ``stock_map`` {softech_id: nowqty} supplies the live warehouse stock (رصيد حالي);
    falls back to the catalog mirror when absent. ``fold_margin`` folds the distributor
    margin into the posted cost for PharmaOverseas-style vendors."""
    cells = line_cells(line, fold_margin=fold_margin)
    # If OCR supplied a net cost, honour it and back-solve the discount (what the
    # invoice actually says); otherwise derive the cost from the discounts.
    changed = 'unit_cost' if _f(line.unit_price) > 0 else None
    row = sc.recompute(cells, changed=changed)
    cat_public = _f(line.item.pack_price) if line.item_id else 0.0
    item = line.item if line.item_id else None
    return {
        'line_id':    line.id,
        'item_id':    line.item_id,
        'item_name':  (item.name if item else line.manual_name),
        'softech_id': (item.softech_id if item else None),
        'raw_name':   line.manual_name or line.raw_text,
        'vendor_item_code': line.vendor_item_code,      # كود (item code OR barcode)
        'batch_number': line.batch_number,               # رقم القطعة أو الباتش
        'expiry_date': line.expiry_date,                 # تاريخ الصلاحية
        'bonus_qty':  _f(line.bonus_qty),
        # ── SofTech display-only columns ──
        'dbitemflag':    getattr(line, 'order', 0),      # (empty-title) line order / flag
        'ro_serial':     getattr(line, 'ro_serial', None),   # رقم مسلسل إذن الاستلام
        'print_barcode': bool(getattr(item, 'barcode', '')) if item else False,  # طباعة باركود
        'current_stock': _current_stock(item, stock_map),                         # رصيد حالى (warehouse)
        'expense_item':  getattr(line, 'expense_item', '') or '',                # بند المصروف
        # ── fixed-margin columns (هامش ثابت للصيدلى / للموزع) — editable. The
        # pharmacist margin is always display-only. The distributor margin is FOLDED
        # into the posted cost when fold_margin (PharmaOverseas-style); otherwise it is
        # display-only (RAMCO-style). See invoice_folds_margin(). ──
        'pharmacist_margin_amt':   _f(getattr(line, 'pharmacist_margin_amt', 0)),   # هامش ثابت للصيدلى
        'distributor_margin_amt':  _f(getattr(line, 'distributor_margin_amt', 0)),  # هامش ثابت للموزع
        'fold_margin':  fold_margin,
        'net_cost':     _f(row.get('net_cost')),       # تكلفة الوحدة (net, pre-margin)
        'cost_to_post': _f(row.get('unit_cost')),      # التكلفة للترحيل = net + margin → SofTech
        # ── review / match flags ──
        'match_score': line.match_score,
        'match_review': line.match_review,
        'needs_pick': line.needs_pick,
        'is_confirmed': line.is_confirmed,
        'price_action': line.price_action,
        'cells':      row,
        'foc':        sc.expand_foc(cells),
        'price':      sc.price_comparison(_f(line.public_price), cat_public) if line.item_id else None,
        **dict(zip(('needs_review', 'review_reasons'), _needs_review(line, row))),
    }


def margin_summary(lines) -> dict:
    """Invoice-level roll-up of the fixed margins. Each line's cost/line-total is the
    NET discounted base (unchanged — SOFTECH stores net), so summing line totals does
    NOT include the margins; the margins add on top at the INVOICE level. This returns
    both figures so the UI can show the difference and it can be probed against the
    printed invoice total:
        lines_net_total           = Σ line totals (what summing the rows gives)
        distributor_margin_total  = Σ (هامش موزع × qty)
        pharmacist_margin_total   = Σ (هامش صيدلى × qty)
        invoice_total_with_margin = lines_net_total + distributor_margin_total
    (Margins are fixed per-unit amounts, so they scale by quantity.)"""
    lines_net = dist = pharm = 0.0
    for ln in lines:
        qty = _f(getattr(ln, 'quantity', 0)) or 0.0
        cells = line_cells(ln)
        changed = 'unit_cost' if _f(ln.unit_price) > 0 else None
        row = sc.recompute(cells, changed=changed)
        lines_net += _f(row.get('cost_total_incl_tax') or row.get('cost_total') or 0)
        dist += _f(getattr(ln, 'distributor_margin_amt', 0)) * qty
        pharm += _f(getattr(ln, 'pharmacist_margin_amt', 0)) * qty
    return {
        'lines_net_total':           round(lines_net, 2),
        'distributor_margin_total':  round(dist, 2),
        'pharmacist_margin_total':   round(pharm, 2),
        'invoice_total_with_margin': round(lines_net + dist, 2),
    }


def tax_summary(lines, fold_margin: bool = False) -> dict:
    """The invoice-level totals SofTech shows at the bottom of «مشتريات من الموردين»,
    the HOUSE-STANDARD way (Method 1 — VAT tracked OUTSIDE the unit cost):
        total_net        = Σ (net × qty)                 (الإجمالى بدون ضريبة بدون هامش)
        margin_total     = Σ (distributor margin × qty)  (قيمة الهامش الثابت للموزع)
        tax_outside_cost = Σ (itemsalestax × qty)        (خارج التكلفة)
        total_final      = total_net + margin_total + tax_outside_cost  (الإجمالى النهائى)
    The distributor margin is counted ONLY when ``fold_margin`` (PharmaOverseas-style);
    for RAMCO-style vendors it is 0. Verified: doc 65966 → 3309.71 / 0 / 68.53 / 3378.24;
    PharmaOverseas doc 65688 → 3655.46 / 101 / 0 / 3756.46."""
    net_t = tax_t = margin_t = 0.0
    for ln in lines:
        cells = line_cells(ln, fold_margin=False)     # net subtotal uses NET (no margin)
        changed = 'unit_cost' if _f(ln.unit_price) > 0 else None
        row = sc.recompute(cells, changed=changed)
        qty = _f(cells.get('quantity'))
        net_t += _f(row.get('cost_total'))
        tax_t += _f(row.get('vat_amount')) * qty
        if fold_margin:
            margin_t += _f(getattr(ln, 'distributor_margin_amt', 0)) * qty
    return {
        'total_net':        round(net_t, 2),
        'margin_total':     round(margin_t, 2),
        'tax_outside_cost': round(tax_t, 2),
        'total_final':      round(net_t + margin_t + tax_t, 2),
    }


def computed_entries(line, fold_margin: bool = False) -> list[dict]:
    """The stktrans money entries a line produces at push time, via the CORRECTED
    engine (pre-tax discount base), honouring an OCR-supplied net cost. ``fold_margin``
    folds the distributor margin into the posted unit cost (PharmaOverseas-style).

    A line with a bonus becomes TWO entries — the paid line, then a FREE line
    (qty = bonus_qty, cost 0). Each entry carries its own ``qty`` (the writer uses
    it for transqty + the running newqty balance). The final native DML column set
    is still built by writer._line_row from these money fields."""
    cells   = line_cells(line, fold_margin=fold_margin)
    # The line's own cost is authoritative when the OCR gave one — or when the item is
    # one we legitimately buy at cost 0 (the coupon SERVED item 118639: sale −50, cost 0;
    # validations.zero_cost_items). Otherwise a 0 cost would be re-derived from the
    # price × discounts and post −50 a unit (reference doc 63945 holds 0).
    from .validations import zero_cost_items
    fixed_cost = _f(line.unit_price) > 0 or (
        line.item_id and str(line.item.softech_id) in zero_cost_items())
    changed = 'unit_cost' if fixed_cost else None
    row     = sc.recompute(cells, changed=changed)
    paid    = {**sc.row_to_write(row), 'qty': _f(line.quantity)}
    out     = [paid]
    bonus   = _f(line.bonus_qty)
    if bonus > 0:
        free_row = sc.recompute({**cells, 'unit_cost': 0.0, 'disc_pct': 100.0,
                                 'extra_disc_pct': 0.0, 'quantity': bonus},
                                changed='unit_cost')
        # native free line: bonusqty = value of the free goods = paid unit cost × free qty
        # (doc 100/10/66173: 1 free × 56.2 → bonusqty 56.2; header docvalue1 = Σ bonusqty)
        out.append({**sc.row_to_write(free_row), 'qty': bonus, 'is_bonus': True,
                    'bonus_value': round(_f(paid['transprice']) * bonus, 4)})
    return out


def recompute_cells(payload: dict) -> dict:
    """Stateless recompute for a single edited row (the keystroke endpoint).
    payload = { cells:{...}, changed:"unit_cost", tax_rate?:14 }.
    When tax_rate is absent it stays whatever the cells carry (the grid seeds it
    from the item at load)."""
    cells   = dict(payload.get('cells') or {})
    changed = payload.get('changed')
    if payload.get('tax_rate') is not None:
        cells['tax_rate'] = _f(payload['tax_rate'])
    if payload.get('vat_pct') is not None:
        cells['vat_pct'] = _f(payload['vat_pct'])
    row = sc.recompute(cells, changed=changed)
    return {'cells': row, 'foc': sc.expand_foc(row), 'softech': sc.to_write_fields(row)}
