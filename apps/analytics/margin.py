"""
apps/analytics/margin.py — C19 / P-35: ONE margin basis for reports (VAT-aligned). REPORTING ONLY.

docs/full-project-audit/08 §C19: a sale line's line_total INCLUDES VAT (stktrans itemsaleprice is tax-inclusive, see
customers.PurchaseHistoryLine) while cost_at_sale EXCLUDES it, so «line_total − cost» overstates profit and margin on
taxed (14 %) items. The aligned basis compares like with like:

    revenue_ex_vat = line_total × 100 ÷ (100 + VAT %)
    profit_ex_vat  = revenue_ex_vat − cost_at_sale × quantity
    margin %       = profit_ex_vat ÷ revenue_ex_vat × 100

VAT % = the item's SOFTECH rate (catalog.Item.sale_tax_pct, itemsalestaxp). SOFTECH does not keep the rate per sale
line, so the item's CURRENT rate is used (owner question: confirm the basis / a rate history). A line with no item or no
rate is untaxed (rate 0) — its two bases are equal.

This never changes a price, a discount, a total or anything sent to SOFTECH: it is how a report divides numbers that
already exist. Returns (doc 30) are subtracted by the callers exactly as the existing reports do.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Value
from django.db.models.functions import Coalesce

BASIS = 'ex_vat'
BASIS_LABEL_AR = 'بدون ضريبة القيمة المضافة (الإيراد ÷ (1 + نسبة الضريبة) − التكلفة)'
HUNDRED = Decimal('100')
CENT = Decimal('0.01')

_DEC = DecimalField(max_digits=20, decimal_places=6)


def revenue_ex_vat(line_total, vat_pct) -> Decimal:
    """One line's revenue without VAT (Decimal)."""
    total = Decimal(str(line_total or 0))
    rate = Decimal(str(vat_pct or 0))
    if rate <= 0:
        return total
    return total * HUNDRED / (HUNDRED + rate)


def profit_ex_vat(line_total, vat_pct, cost, qty) -> Decimal:
    return revenue_ex_vat(line_total, vat_pct) - Decimal(str(cost or 0)) * Decimal(str(qty or 0))


def margin_pct(profit, revenue) -> float:
    """profit ÷ revenue × 100, 2 decimals; 0 when there is no revenue."""
    revenue = Decimal(str(revenue or 0))
    if revenue == 0:
        return 0.0
    return float((Decimal(str(profit or 0)) * HUNDRED / revenue).quantize(CENT, ROUND_HALF_UP))


def money(v) -> float:
    return float(Decimal(str(v or 0)).quantize(CENT, ROUND_HALF_UP))


def line_expressions(prefix: str = ''):
    """ORM expressions over customers.PurchaseHistoryLine (prefix for a related path):
    (revenue_incl_vat, revenue_ex_vat, cogs, profit_ex_vat). The same arithmetic as the Python helpers above."""
    p = prefix
    rate = Coalesce(F(f'{p}item__sale_tax_pct'), Value(Decimal('0')), output_field=_DEC)
    rev = ExpressionWrapper(F(f'{p}line_total') * Value(Decimal('1')), output_field=_DEC)
    rev_ex = ExpressionWrapper(F(f'{p}line_total') * Value(HUNDRED) / (Value(HUNDRED) + rate), output_field=_DEC)
    cogs = ExpressionWrapper(F(f'{p}cost_at_sale') * F(f'{p}quantity'), output_field=_DEC)
    profit_ex = ExpressionWrapper(rev_ex - cogs, output_field=_DEC)
    return rev, rev_ex, cogs, profit_ex
