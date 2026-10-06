"""
catalog/safety.py — deterministic product safety / dispensing flags for the POS
product card.

These are DERIVED, on the fly, from signals SOFTECH already gives us on `Item`
(sale permission, dispensing restriction, fridge, archive/discontinued, market
shortage). Nothing is stored (no drift) and nothing is invented: the item master
has NO reliable narcotics/controlled-schedule column yet (see Item.item_level
help_text), so we deliberately emit no controlled-substance flag — pharmacy safety
must never rest on a guess (rules 4/5/10).

Severity contract:
  'block' — this item cannot be sold as-is (the POS/writer already enforces this;
            the flag only makes the reason visible so it can't be silently upsold).
  'warn'  — sale allowed but a restriction/handling caveat applies.
  'info'  — neutral handling note (e.g. fridge).
"""

# customer_trans (SOFTECH items.itemtrans3): 0=sell+return, 1=sell only,
# 2=return only, 3=full stop.
_CUSTOMER_TRANS = {
    '2': ('return_only', 'warn', 'ارتجاع فقط — لا يُباع', 'Return only — not sellable'),
    '3': ('sale_stopped', 'block', 'موقوف عن البيع', 'Sale stopped'),
}

# nosale_classif (items.itemnosaleclassif): 10/empty = normal, else a dispensing
# restriction tier. We surface it as a caveat, not a hard block (contract logic
# decides the actual gate).
_NORMAL_NOSALE = {'', '10'}


def item_safety_flags(item):
    """Return an ordered list of flag dicts (most severe first) for one Item."""
    flags = []

    if not getattr(item, 'is_active', True):
        flags.append(_flag('inactive', 'block', 'غير نشط', 'Inactive'))
    if getattr(item, 'item_archive', False):
        flags.append(_flag('archived', 'block', 'مؤرشف', 'Archived'))
    if getattr(item, 'no_more_use', False):
        flags.append(_flag('discontinued', 'warn', 'موقوف/غير مستخدم', 'Discontinued'))

    ct = (getattr(item, 'customer_trans', '') or '').strip()
    if ct in _CUSTOMER_TRANS:
        code, sev, ar, en = _CUSTOMER_TRANS[ct]
        flags.append(_flag(code, sev, ar, en))

    nosale = (getattr(item, 'nosale_classif', '') or '').strip()
    if nosale not in _NORMAL_NOSALE:
        flags.append(_flag('dispense_restricted', 'warn',
                           f'تقييد صرف (تصنيف {nosale})', f'Dispensing restricted (class {nosale})'))

    if getattr(item, 'in_shortage', False):
        flags.append(_flag('market_shortage', 'warn', 'نقص بالسوق', 'Market shortage'))
    if getattr(item, 'requires_fridge', False):
        flags.append(_flag('fridge', 'info', 'يُحفظ بالثلاجة', 'Keep refrigerated'))

    order = {'block': 0, 'warn': 1, 'info': 2}
    flags.sort(key=lambda f: order.get(f['severity'], 9))
    return flags


def blocks_sale(item) -> bool:
    """True if any derived flag is a hard 'block'. Deterministic, safety-first."""
    return any(f['severity'] == 'block' for f in item_safety_flags(item))


def _flag(code, severity, label_ar, label_en):
    return {'code': code, 'severity': severity, 'label_ar': label_ar, 'label_en': label_en}
