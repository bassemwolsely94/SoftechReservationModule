"""
apps/invoices/anomalies.py

Anomaly detection for supplier invoices.
Checks each InvoiceLine and returns a list of flagged issues.

Anomaly types:
  unmatched       — no ERP item matched
  price_zero      — unit_price = 0 with qty > 0
  qty_zero        — quantity = 0
  high_discount   — discount_pct > 50 %
  price_deviation — invoice price differs > 30 % from ERP catalog price
  duplicate_item  — same ERP item appears more than once on the invoice
  total_mismatch  — Σ line totals differs > 2 % from the OCR'd invoice grand-total
"""
from __future__ import annotations

# Severity levels: 'error' > 'warning' > 'info'
_PRICE_DEV_THRESHOLD     = 0.30   # 30 % price deviation
_HIGH_DISCOUNT_THRESH    = 50.0   # > 50 % line discount is unusual
_TOTAL_MISMATCH_THRESHOLD = 0.02  # Σ lines vs OCR'd invoice total: flag > 2 %


def check_invoice_anomalies(invoice) -> list[dict]:
    """
    Scan all lines on *invoice* and return a list of anomaly dicts:
      { line_id, raw_name, type, message, severity }

    Callers should prefetch  invoice.lines.select_related('item').all()
    before calling to avoid N+1 queries.
    """
    anomalies: list[dict] = []
    seen_items: dict[int, int] = {}   # item_id → first line_id

    for line in invoice.lines.select_related('item').all():
        raw_name = line.manual_name or line.raw_text or '—'
        qty      = float(line.quantity or 0)
        price    = float(line.unit_price or 0)
        disc_pct = float(line.discount_pct or 0)

        def _flag(typ, msg, sev='warning'):
            anomalies.append({
                'line_id':  line.id,
                'raw_name': raw_name,
                'type':     typ,
                'message':  msg,
                'severity': sev,
            })

        # ── Unmatched ──────────────────────────────────────────────────────
        if not line.item_id:
            _flag('unmatched',
                  f'"{raw_name}" — لم يتم العثور على صنف مطابق في ERP',
                  'warning')
            continue   # rest of checks require an item

        # ── Zero price ─────────────────────────────────────────────────────
        if qty > 0 and price == 0:
            _flag('price_zero',
                  f'السعر = 0 للصنف: {line.item.name}',
                  'error')

        # ── Zero quantity ──────────────────────────────────────────────────
        if qty == 0:
            _flag('qty_zero',
                  f'الكمية = 0 للصنف: {line.item.name}',
                  'warning')

        # ── High discount ──────────────────────────────────────────────────
        if disc_pct > _HIGH_DISCOUNT_THRESH:
            _flag('high_discount',
                  f'خصم مرتفع ({disc_pct:.0f}%) للصنف: {line.item.name}',
                  'warning')

        # ── Price deviation vs ERP ─────────────────────────────────────────
        if price > 0:
            erp_price = float(line.item.pack_price or 0)
            if erp_price > 0:
                deviation = abs(price - erp_price) / erp_price
                if deviation > _PRICE_DEV_THRESHOLD:
                    direction = 'أعلى' if price > erp_price else 'أقل'
                    _flag('price_deviation',
                          (f'سعر الفاتورة ({price:.2f} ج.م) {direction} من سعر ERP '
                           f'({erp_price:.2f} ج.م) بنسبة {deviation:.0%} — {line.item.name}'),
                          'info')

        # ── Duplicate item ─────────────────────────────────────────────────
        if line.item_id in seen_items:
            _flag('duplicate_item',
                  f'الصنف مكرر في الفاتورة: {line.item.name} (سطر {seen_items[line.item_id]} و {line.id})',
                  'warning')
        else:
            seen_items[line.item_id] = line.id

    # ── Header total reconciliation (OCR declared_total vs Σ lines) ─────────
    declared = float(invoice.declared_total or 0)
    if declared > 0:
        computed = float(invoice.total_after_discount or 0)
        if computed > 0:
            dev = abs(computed - declared) / declared
            if dev > _TOTAL_MISMATCH_THRESHOLD:
                anomalies.append({
                    'line_id':  None,
                    'raw_name': '—',
                    'type':     'total_mismatch',
                    'message':  (f'إجمالي السطور ({computed:.2f} ج.م) يختلف عن إجمالي الفاتورة '
                                 f'المقروء ({declared:.2f} ج.م) بنسبة {dev:.0%} — راجع الأسطر'),
                    'severity': 'error' if dev > 0.10 else 'warning',
                })

    return anomalies
