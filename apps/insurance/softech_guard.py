"""
Deterministic plausibility guard for SOFTECH receipt re-prices.

Pure functions over plain data (no DB, no SOFTECH) so every rule is unit-testable.
Two levels:
  block — never written, whatever the user types (a receipt number typed as a price,
          a price far from both SOFTECH and our own references, an absurd total);
  warn  — written only with a typed reason (≥ REASON_MIN_CHARS), recorded on the run.

Real incident that motivated this (2026-11-01): receipt number 931120 typed into the
price box → item 111062 written at 931,120 instead of 240 (+772,692.65 on one receipt).
"""
from decimal import Decimal, InvalidOperation

# ── thresholds (owner asked for strict) ──────────────────────────────────────
HARD_RATIO          = Decimal('3')      # beyond ×3 / ÷3 of the SOFTECH price → block, always
RATIO               = Decimal('2')      # beyond ×2 / ÷2 → block unless it equals our reference
REF_TOLERANCE       = Decimal('0.01')   # "equals" claim / catalog price within 1 %
RECEIPT_DELTA_BLOCK = Decimal('3000')   # one receipt's net change
RECEIPT_DELTA_WARN  = Decimal('500')
PLAN_DELTA_WARN     = Decimal('2000')   # the whole batch's net change
REASON_MIN_CHARS    = 10
PREVIEW_TTL_SECONDS = 600               # a preview older than this cannot be applied


def _dec(v):
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


def _near(a, b):
    return a is not None and b is not None and b > 0 and abs(a - b) <= b * REF_TOLERANCE


def _issue(level, code, msg, itemcode=None):
    return {'level': level, 'code': code, 'message': msg, 'itemcode': itemcode}


def check_receipt(*, docno, new_prices, softech_prices, claim_prices, catalog_prices,
                  net_delta, known_numbers=()):
    """Issues for one receipt.

    new_prices      {itemcode: typed price}
    softech_prices  {itemcode: current SOFTECH itemsaleprice}   (items on the receipt)
    claim_prices    {itemcode: our claim's unit price}
    catalog_prices  {itemcode: catalog pack price}
    known_numbers   receipt numbers / item codes a price must never equal
    """
    issues = []
    ids = {str(x).strip() for x in known_numbers if str(x).strip()} | {str(docno).strip()}
    ids |= {str(c).strip() for c in new_prices}
    for code, raw in new_prices.items():
        code = str(code).strip()
        p = _dec(raw)
        if p is None or p <= 0:
            issues.append(_issue('block', 'not_positive', f'السعر «{raw}» للصنف {code} غير صالح.', code))
            continue
        if p != p.quantize(Decimal('0.01')):
            issues.append(_issue('block', 'decimals', f'السعر {raw} للصنف {code} بأكثر من رقمين عشريين.', code))
        if str(raw).strip().split('.')[0] in ids and p == p.to_integral_value():
            issues.append(_issue('block', 'looks_like_id',
                                 f'السعر {raw} للصنف {code} يطابق رقم إيصال أو كود صنف — غالباً أُدخل فى الخانة الخطأ.', code))
        old = _dec(softech_prices.get(code))
        if old is None:
            issues.append(_issue('block', 'not_on_receipt', f'الصنف {code} غير موجود على الإيصال #{docno}.', code))
            continue
        ref_claim, ref_cat = _dec(claim_prices.get(code)), _dec(catalog_prices.get(code))
        matches_ref = _near(p, ref_claim) or _near(p, ref_cat)
        if old > 0:
            ratio = p / old
            if ratio > HARD_RATIO or ratio < 1 / HARD_RATIO:
                issues.append(_issue('block', 'hard_ratio',
                                     f'السعر {p} للصنف {code} بعيد جداً عن سعر سوفتك {old} (أكثر من ×{HARD_RATIO}).', code))
            elif ratio > RATIO or ratio < 1 / RATIO:
                if matches_ref:
                    issues.append(_issue('warn', 'big_ratio',
                                         f'السعر {p} للصنف {code} أكثر من ضعف/نصف سعر سوفتك {old} (يطابق سعر المطالبة/الكتالوج).', code))
                else:
                    issues.append(_issue('block', 'ratio',
                                         f'السعر {p} للصنف {code} أكثر من ضعف/نصف سعر سوفتك {old} ولا يطابق سعر المطالبة ولا الكتالوج.', code))
        elif not matches_ref:
            issues.append(_issue('block', 'no_reference',
                                 f'سعر سوفتك للصنف {code} صفر والسعر {p} لا يطابق سعر المطالبة ولا الكتالوج.', code))
        if not matches_ref:
            refs = ' / '.join(x for x in (f'المطالبة {ref_claim}' if ref_claim else '',
                                          f'الكتالوج {ref_cat}' if ref_cat else '') if x) or 'لا يوجد مرجع'
            issues.append(_issue('warn', 'off_reference',
                                 f'السعر {p} للصنف {code} لا يطابق ({refs}).', code))
        if old > 0 and p < old:
            issues.append(_issue('warn', 'decrease', f'تخفيض سعر الصنف {code} من {old} إلى {p}.', code))

    d = _dec(net_delta) or Decimal('0')
    if abs(d) > RECEIPT_DELTA_BLOCK:
        issues.append(_issue('block', 'receipt_delta',
                             f'فرق صافى الإيصال #{docno} = {d} يتجاوز الحد ({RECEIPT_DELTA_BLOCK}).'))
    elif abs(d) > RECEIPT_DELTA_WARN:
        issues.append(_issue('warn', 'receipt_delta', f'فرق صافى الإيصال #{docno} = {d} (أكبر من {RECEIPT_DELTA_WARN}).'))
    return issues


def check_plan_total(net_delta):
    d = _dec(net_delta) or Decimal('0')
    if abs(d) > PLAN_DELTA_WARN:
        return [_issue('warn', 'plan_delta', f'إجمالى فرق الصافى للدفعة {d} (أكبر من {PLAN_DELTA_WARN}).')]
    return []


def summarize(issues):
    return {'blocked': any(i['level'] == 'block' for i in issues),
            'needs_reason': any(i['level'] == 'warn' for i in issues)}


def reason_ok(reason):
    return len((reason or '').strip()) >= REASON_MIN_CHARS


# ── receipt-date edit (📅 temporary printed date) ─────────────────────────────
DATE_MAX_SHIFT_DAYS  = 60   # beyond this the "temporary reprint date" story does not hold → block
DATE_WARN_SHIFT_DAYS = 14   # a normal re-entry gap is days, not weeks → reason


def check_date(*, old, new, today, period_from=None, period_to=None):
    """Issues for moving a receipt's printed date from `old` to `new` (dates)."""
    if new is None:
        return [_issue('block', 'date_invalid', 'اختر التاريخ الجديد.')]
    if old is None:
        return [_issue('block', 'date_missing', 'تعذّرت قراءة تاريخ الإيصال الحالى.')]
    issues = []
    shift = (new - old).days
    if new > today:
        issues.append(_issue('block', 'date_future', f'التاريخ {new} فى المستقبل.'))
    if shift == 0:
        issues.append(_issue('block', 'date_same', 'التاريخ الجديد يساوى التاريخ الحالى — لا يوجد تغيير.'))
    if abs(shift) > DATE_MAX_SHIFT_DAYS:
        issues.append(_issue('block', 'date_far',
                             f'فرق {abs(shift)} يوم يتجاوز الحد ({DATE_MAX_SHIFT_DAYS} يوماً) لتعديل مؤقت للطباعة.'))
    elif abs(shift) > DATE_WARN_SHIFT_DAYS:
        issues.append(_issue('warn', 'date_shift', f'فرق {abs(shift)} يوم (أكثر من {DATE_WARN_SHIFT_DAYS}).'))
    if shift > 0:
        issues.append(_issue('warn', 'date_later',
                             f'التاريخ الجديد بعد الحالى ({old} → {new}) — المعتاد تقديم التاريخ للخلف.'))
    if period_from and period_to and not (period_from <= new <= period_to):
        issues.append(_issue('warn', 'date_outside_period',
                             f'التاريخ {new} خارج فترة المطالبة ({period_from} → {period_to}).'))
    return issues
