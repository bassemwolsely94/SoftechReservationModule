"""
apps/catalog/item_columns.py — the «بيانات الصنف» block every Excel export carries (owner 2026-10-26).

One definition of each item column (label, how it is read, width, number format), so the purchasing
pivot and every /supply export show the same thing the same way. Always read from the items table
at export time (load_items) — never from a snapshot — so an update to an item shows in the next
export of every file. The items table itself follows SOFTECH through the item sync.

    from apps.catalog.item_columns import ITEM_HEADS, ITEM_WIDTHS, item_cells, load_items
    items = load_items(codes=[...])            # {softech_id: Item}
    row = [code, name, *item_cells(items.get(code)), ...]

Internal data (cost, public price, classifications) — never add it to a sheet sent to a supplier.
"""


def _f(v):
    return float(v) if v is not None else None


def medicine_type(it):
    return it.medicine_type_name_ar or it.medicine_type_name or ''


def dosage_form(it):
    c = it.category
    return (c.name_ar or c.name) if c else ''


def shape(it):
    return it.shape_name_ar or it.shape_name or ''


def family(it):
    return it.family_name_ar or it.family_name or ''


# (label, reader, width, number format or None) — after the item's code + name, in this order.
ITEM_COLUMNS = [
    ('التصنيف العام',     medicine_type,                                  14, None),
    ('الشكل الصيدلي',     dosage_form,                                    12, None),
    ('الشكل والوحدة',     shape,                                          14, None),
    ('تصنيف الخصم',       lambda it: it.store_classif_name or '',         12, None),
    ('موقوف التوريد',     lambda it: 'موقوف' if it.no_more_use else '',   9,  None),
    ('كود المورد',        lambda it: it.supplier_code or '',              8,  None),
    ('المورد الرئيسي',    lambda it: it.supplier_name or '',              20, None),
    ('كود الشركة المنتجة', lambda it: it.producer_code or '',             9,  None),
    ('الشركة المنتجة',    lambda it: it.producer_name or '',              20, None),
    ('العائلة',           family,                                         14, None),
    ('سعر الجمهور',       lambda it: _f(it.pack_price),                   10, '#,##0.00'),
    ('سعر التكلفة',       lambda it: _f(it.cost_price),                   10, '#,##0.00'),
]
ITEM_HEADS = [c[0] for c in ITEM_COLUMNS]
ITEM_NOTE = ('• «بيانات الصنف» (التصنيف، المورد الرئيسي، الشركة المنتجة، سعر الجمهور، سعر التكلفة…) من جدول '
             'الأصناف لحظة التصدير — أي تحديث للصنف يظهر في التصدير التالي.')
ITEM_WIDTHS = [c[2] for c in ITEM_COLUMNS]
ITEM_FORMATS = [c[3] for c in ITEM_COLUMNS]
N = len(ITEM_COLUMNS)


PRICE_HEADS = ('سعر الجمهور', 'سعر التكلفة')


def columns(prices=True):
    """The block's column specs. prices=False drops سعر الجمهور / سعر التكلفة — for a sheet that
    already carries its own (e.g. a saved plan whose formulas use the price it was built with)."""
    return [c for c in ITEM_COLUMNS if prices or c[0] not in PRICE_HEADS]


def item_cells(item, prices=True):
    """The block's values for one item (blanks when the item is unknown)."""
    cols = columns(prices)
    if item is None:
        return [None] * len(cols)
    return [read(item) for _l, read, _w, _fmt in cols]


def load_items(*, codes=None, ids=None):
    """Live Item rows for an export, keyed by softech_id (codes=) or by id (ids=)."""
    from apps.catalog.models import Item
    qs = Item.objects.select_related('category')
    if codes is not None:
        codes = {str(c) for c in codes if c not in (None, '')}
        return {it.softech_id: it for it in qs.filter(softech_id__in=codes)}
    ids = {i for i in (ids or ()) if i}
    return {it.id: it for it in qs.filter(id__in=ids)}


def style_columns(ws, first_col, header_row=1):
    """Number formats for the block when it starts at 1-based column first_col (openpyxl ws)."""
    for k, fmt in enumerate(ITEM_FORMATS):
        if not fmt:
            continue
        for (cell,) in ws.iter_rows(min_row=header_row + 1, min_col=first_col + k, max_col=first_col + k):
            cell.number_format = fmt
