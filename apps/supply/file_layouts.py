"""
apps/supply/file_layouts.py — remember each supplier's Excel / CSV column layout
(owner 2026-10-05: "their files import perfectly from the second time on").

  detect_header(rows)        → index of the header row (or None: no header, plain lines)
  suggest(headers)           → {column index: role} from the header words (deterministic)
  find_layout(batch, sig)    → the confirmed layout for this supplier + header row, if any
  remember(batch, …)         → save / refresh the confirmed layout (SupplierFileLayout)
  import_rows(batch, rows, header_row, mapping) → AvailabilityLines, one per data row

Roles: name · code (the supplier's own item code) · barcode · qty · price (offered price to
us) · foc · discount · expiry · ignore. A remembered layout is keyed by supplier + the exact
header row, so a supplier who changes their file format is simply asked once more.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .availability import _fold_digits, _norm_expiry, build_line, ParsedAvailability

ROLES = ['name', 'code', 'barcode', 'qty', 'price', 'foc', 'discount', 'expiry', 'ignore']
ROLE_LABELS = {'name': 'اسم الصنف', 'code': 'كود المورد', 'barcode': 'باركود', 'qty': 'الكمية',
               'price': 'السعر', 'foc': 'البونص', 'discount': 'الخصم %', 'expiry': 'الصلاحية',
               'ignore': 'تجاهل'}

# Header words → role, most specific first. "سعر الجمهور / public" is the consumer price,
# NOT what the supplier charges us → ignored by default (a person can still map it).
_RULES = [
    ('barcode', r'bar\s*code|barcode|ean|gtin|باركود|الباركود'),
    ('ignore',  r'جمهور|public|retail|consumer|المستهلك'),
    ('discount', r'disc|خصم|discount'),
    ('foc',     r'bonus|foc|free|بونص|بونس|هدية|هديه'),
    ('expiry',  r'exp|صلاحي|انتهاء|تاريخ\s*الصلاحية'),
    ('price',   r'price|cost|net|سعر|صافي|صيدلي|التكلفة'),
    ('qty',     r'qty|quant|avail|stock|balance|الكمية|كمية|كميه|متاح|المتاح|الرصيد|رصيد|عدد'),
    ('code',    r'code|item\s*no|كود|الكود|رقم\s*الصنف|item\s*#'),
    ('name',    r'name|item|product|desc|الصنف|اسم|الاسم|البيان|المنتج|الدواء|صنف'),
]


def _norm_header(v) -> str:
    return re.sub(r'\s+', ' ', _fold_digits(str(v or ''))).strip().lower()


def _role_of(header: str):
    h = _norm_header(header)
    if not h:
        return None
    for role, pat in _RULES:
        if re.search(pat, h, re.I):
            return role
    return None


def detect_header(rows, *, scan: int = 15):
    """The first row (among the first `scan`) where ≥2 cells are recognisable column
    titles and one of them is the product name. None = no header (plain list)."""
    for i, row in enumerate(rows[:scan]):
        roles = [_role_of(c) for c in row]
        if sum(1 for r in roles if r) >= 2 and 'name' in roles:
            return i
    return None


def suggest(headers) -> dict:
    """{str(col): role} — each role used once (the left-most column wins), except ignore."""
    out, used = {}, set()
    for i, h in enumerate(headers):
        role = _role_of(h)
        if role and (role == 'ignore' or role not in used):
            out[str(i)] = role
            used.add(role)
    return out


def signature(headers) -> str:
    return '|'.join(_norm_header(h) for h in headers)[:500]


def supplier_key(batch) -> str:
    if batch.supplier_id and batch.supplier and batch.supplier.softech_personcode:
        return f'pc:{batch.supplier.softech_personcode}'
    name = re.sub(r'\s+', ' ', (batch.supplier_name or '').strip().lower())
    return f'name:{name}'[:120] if name else ''


def find_layout(batch, sig: str):
    from .models import SupplierFileLayout
    key = supplier_key(batch)
    if not key or not sig:
        return None
    return SupplierFileLayout.objects.filter(supplier_key=key, signature=sig).first()


def suggested_from_others(sig: str):
    """Another supplier sent a file with the very same header row → its confirmed mapping
    is the best first guess (still shown for a person to confirm)."""
    from .models import SupplierFileLayout
    other = SupplierFileLayout.objects.filter(signature=sig).order_by('-use_count').first()
    return other.mapping if other else None


def clean_mapping(mapping, ncols: int) -> dict:
    """Validate a mapping from the client: known roles, real columns, each role once (ignore
    may repeat), and a name column."""
    out, used = {}, set()
    for k, role in (mapping or {}).items():
        if not str(k).isdigit() or int(k) >= ncols or role not in ROLES:
            raise ValueError('ترتيب أعمدة غير صالح.')
        if role != 'ignore' and role in used:
            raise ValueError(f'العمود «{ROLE_LABELS[role]}» محدد أكثر من مرة.')
        used.add(role)
        out[str(int(k))] = role
    if 'name' not in used:
        raise ValueError('حدد عمود اسم الصنف.')
    return out


def remember(batch, *, sig: str, headers, header_row: int, mapping: dict, staff=None):
    from .models import SupplierFileLayout
    key = supplier_key(batch)
    if not key:
        return None
    lay, created = SupplierFileLayout.objects.get_or_create(
        supplier_key=key, signature=sig,
        defaults={'vendor': batch.supplier if batch.supplier_id else None, 'headers': list(headers),
                  'header_row': header_row, 'mapping': mapping, 'updated_by': staff})
    if not created:
        lay.use_count += 1
        lay.mapping, lay.header_row, lay.headers, lay.updated_by = mapping, header_row, list(headers), staff
        lay.save(update_fields=['use_count', 'mapping', 'header_row', 'headers', 'updated_by', 'updated_at'])
    return lay


# ── cell parsing ───────────────────────────────────────────────────────────────
def _txt(v) -> str:
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r'\s+', ' ', _fold_digits(str(v))).strip()


def _number(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    m = re.search(r'\d+(?:[.,]\d+)?', _txt(v))
    return float(m.group(0).replace(',', '.')) if m else None


def _expiry(v) -> str:
    if isinstance(v, (datetime, date)):
        return f'{v.month:02d}/{v.year}'
    t = _txt(v)
    m = re.search(r'(\d{1,4})[/.\-](\d{1,4})(?:[/.\-](\d{2,4}))?', t)
    if not m:
        return t[:20]
    if m.group(3):                         # d/m/y or y/m/d → month / year
        a, b, c = m.group(1), m.group(2), m.group(3)
        return _norm_expiry(b, c) if len(a) <= 2 else _norm_expiry(a, b)
    return _norm_expiry(m.group(1), m.group(2))


_TOTAL_RE = re.compile(r'^\s*(?:ال)?(?:إجمالي|اجمالي|إجمالى|اجمالى|مجموع|جملة)|^\s*(?:grand\s+)?(?:total|sum)\b', re.I)


def import_rows(batch, rows, *, header_row, mapping: dict, vendor_code: str = '') -> list:
    """One AvailabilityLine per data row, the economics read from their own columns (never
    guessed from free text). Rows without a name are skipped."""
    by_role = {role: int(col) for col, role in mapping.items() if role != 'ignore'}
    start = (header_row + 1) if header_row is not None else 0
    created = []

    def cell(row, role):
        i = by_role.get(role)
        return row[i] if i is not None and i < len(row) else None

    for row in rows[start:]:
        name = _txt(cell(row, 'name'))
        if not name or not re.search(r'[A-Za-z؀-ۿ]{2,}', name) or _TOTAL_RE.match(name):
            continue                      # empty / a totals row («الإجمالي», "Total") is not a product
        code = _txt(cell(row, 'code'))[:40]
        barcode = re.sub(r'\D', '', _txt(cell(row, 'barcode')))
        parsed = ParsedAvailability(
            name_part=name[:250], supplier_qty=_number(cell(row, 'qty')), price=_number(cell(row, 'price')),
            foc_qty=_number(cell(row, 'foc')), discount_pct=_number(cell(row, 'discount')),
            expiry=_expiry(cell(row, 'expiry')) if cell(row, 'expiry') not in (None, '') else '',
            supplier_item_code=code, extracted={'layout': True})
        raw = ' · '.join(x for x in [name, code and f'كود {code}', barcode,
                                     _txt(cell(row, 'qty')) and f"كمية {_txt(cell(row, 'qty'))}",
                                     _txt(cell(row, 'price')) and f"سعر {_txt(cell(row, 'price'))}"] if x)
        line = build_line(batch, raw[:300], source='file', vendor_code=vendor_code,
                          parsed=parsed, barcode=barcode)
        if line is not None:
            created.append(line)
    return created
