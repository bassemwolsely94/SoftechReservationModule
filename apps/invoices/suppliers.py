"""
Supplier resolution — map an OCR'd supplier name to a SOFTECH personcode
(personsdata.ptcode='20') and get/create the matching VendorProfile.

Without a resolved ``VendorProfile.softech_personcode`` the writeback is blocked
(validations E7 ``supplier_unlinked``), because that code becomes
``stktransm.cust_branch_code`` on the pushed purchase/return document.

Resolution order (first confident hit wins):
  1. an existing VendorProfile whose name / aliases match (learned links)
  2. the curated TOP_SUPPLIERS map — the ~10 top Egyptian distributors whose
     invoices are OCR'd most often; hand-verified codes + name variants
  3. (optional) a live fuzzy match against SOFTECH personsdata ptcode='20'

Only 1 & 2 run offline; 3 needs a SOFTECH connection and is opt-in.
"""
from __future__ import annotations

import difflib
import logging
import re

logger = logging.getLogger(__name__)

# ── Curated top-10 distributors (personcode verified against personsdata) ───────
# personcode → (canonical_name, [alias fragments — normalized-substring matched]).
# Alias fragments are matched with _norm() applied to BOTH sides, longest-first,
# so a more specific alias ("egy drug sherif") beats a generic one ("egy drug").
TOP_SUPPLIERS: dict[str, tuple[str, list[str]]] = {
    '565':  ('PHARMA OVER SEAS', [
        'pharma over seas', 'pharmaoverseas', 'pharma overseas', 'over seas',
        'overseas', '565 pharma', 'فارما اوفر سيز', 'اوفر سيز', 'اوفرسيز', 'بي او اس']),
    '260':  ('IBN SINA', [
        'ibn sina', 'ibnsina', 'ibn-sina', 'ابن سينا', 'ابن سيناء']),
    '4327': ('EGY DRUG - ZAYTOUN', [
        'egy drug zaytoun', 'egy drug zeitoun', 'egy drug zaitoun', 'egydrug zaytoun',
        'ايجي دروج الزيتون', 'ايجي دراج الزيتون', 'ايجى دروج الزيتون', 'ايجي درج الزيتون',
        'ايجي دروج زيتون']),
    '786':  ('EGY DRUG - SHERIF', [
        'egy drug sherif', 'egy drug -sherif', 'egydrug sherif', 'egy drug shrif',
        'ايجي دروج شريف', 'ايجى دروج شريف', 'ايجي دروج الشريف']),
    '30':   ('RAMCO PHARM', [
        'ramco pharm', 'ramco', 'رامكو فارم', 'رامكو']),
    '746':  ('SOFICO', [
        'sofico', 'سوفيكو']),
    '124':  ('AKHNATON EVA', [
        'ikhnatoun', 'akhnatoun', 'akhnaton', 'ikhnaton', 'akhnaton eva',
        'اخناتون ايفا', 'اخناتون']),
    '156':  ('MEC - Middle East Chemicals', [
        'middle east chemicals', 'mec', 'الشرق الاوسط للكيماويات', 'الشرق الاوسط']),
    '13':   ('CHEMIPHARM', [
        'chemipharm', 'كيميفارم', 'كيمي فارم']),
    '16':   ('EIPICO', [
        'eipico', 'ايبيكو', 'ايبيك']),
}

# Generic tokens that must NOT alone drive a curated match (too many suppliers
# share them). A single-token alias equal to one of these is ignored.
_GENERIC = {'pharma', 'egy', 'drug', 'egy drug', 'فارما', 'ايجي دروج', 'ادوية'}

_AR_DIAC = re.compile(r'[ً-ْـ]')          # tashkeel + tatweel
_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def _norm(s: str) -> str:
    """Lower/strip, drop Arabic diacritics, unify alef/ya/ta-marbuta, collapse
    punctuation & whitespace so OCR spelling noise doesn't defeat matching."""
    if not s:
        return ''
    s = str(s).translate(_AR_DIGITS)
    s = _AR_DIAC.sub('', s)
    s = (s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
           .replace('ى', 'ي').replace('ة', 'ه'))
    s = re.sub(r'[^0-9a-z؀-ۿ]+', ' ', s.lower())
    return re.sub(r'\s+', ' ', s).strip()


def _alias_hits(alias: str, n: str) -> bool:
    """True when a (normalized) alias matches name ``n`` — exact, or as a whole
    word/phrase (word-boundary), so a short alias like 'mec' does NOT match
    inside another word ('pharmec')."""
    if not alias:
        return False
    if alias == n:
        return True
    return re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', n) is not None


# Pre-normalize the curated aliases once (longest-first for specificity).
_CURATED: list[tuple[str, str]] = sorted(
    ((_norm(a), code) for code, (_, aliases) in TOP_SUPPLIERS.items() for a in aliases),
    key=lambda t: len(t[0]), reverse=True,
)


def resolve_supplier(name: str, *, conn=None, min_fuzzy: float = 0.86) -> dict | None:
    """Resolve a raw supplier name to {personcode, name, score, source} or None.

    ``conn`` (an open SOFTECH connection) enables the live personsdata fuzzy
    fallback; omit it to stay fully offline (curated + learned only)."""
    from .models import VendorProfile

    n = _norm(name)
    if not n:
        return None

    # 1. Learned VendorProfile (exact name, or an alias fragment) ───────────────
    for vp in VendorProfile.objects.exclude(softech_personcode='').exclude(softech_personcode__isnull=True):
        if _norm(vp.name) == n:
            return {'personcode': vp.softech_personcode, 'name': vp.name,
                    'score': 1.0, 'source': 'vendor'}
        for al in (vp.aliases or '').split(','):
            al = _norm(al)
            if al and al in _GENERIC:
                continue
            if _alias_hits(al, n):
                return {'personcode': vp.softech_personcode, 'name': vp.name,
                        'score': 0.97, 'source': 'vendor_alias'}

    # 2. Curated top-10 alias map (longest alias wins) ─────────────────────────
    for alias, code in _CURATED:
        if not alias or alias in _GENERIC:
            continue
        if _alias_hits(alias, n) or (len(n) >= 4 and n in alias):
            return {'personcode': code, 'name': TOP_SUPPLIERS[code][0],
                    'score': 0.95, 'source': 'curated'}

    # 3. Live fuzzy against SOFTECH suppliers (opt-in) ─────────────────────────
    if conn is not None:
        best = None
        try:
            cur = conn.cursor()
            cur.execute("SELECT personcode, personname FROM personsdata WHERE ptcode='20'")
            for code, pname in cur.fetchall():
                r = difflib.SequenceMatcher(None, n, _norm(pname)).ratio()
                if best is None or r > best[0]:
                    best = (r, str(code).strip(), str(pname or '').strip())
        except Exception as e:  # pragma: no cover - network dependent
            logger.warning('supplier fuzzy lookup failed: %s', e)
            best = None
        if best and best[0] >= min_fuzzy:
            return {'personcode': best[1], 'name': best[2],
                    'score': round(best[0], 4), 'source': 'softech_fuzzy'}

    return None


def main_personcodes() -> set:
    """The SOFTECH personcodes of the vendors flagged is_main — the ONLY suppliers
    we process (sourcing, injection, recall, exports). Empty set = none flagged."""
    from .models import VendorProfile
    return {c for c in VendorProfile.objects.filter(is_main=True)
            .exclude(softech_personcode='').values_list('softech_personcode', flat=True) if c}


def main_suppliers() -> list:
    """[(personcode, name)] for the is_main vendors, stable by name — used for the
    supplier-matrix columns and the single-supplier PO picker."""
    from .models import VendorProfile
    return [(v.softech_personcode, v.name) for v in
            VendorProfile.objects.filter(is_main=True).exclude(softech_personcode='').order_by('name')]


def is_main_personcode(personcode: str) -> bool:
    from .models import VendorProfile
    pc = str(personcode or '').strip()
    return bool(pc) and VendorProfile.objects.filter(softech_personcode=pc, is_main=True).exists()


def get_or_create_vendor(personcode: str, name: str, *, alias: str = ''):
    """Get/create a VendorProfile for a SOFTECH personcode, learning the alias."""
    from .models import VendorProfile

    vp = VendorProfile.objects.filter(softech_personcode=personcode).first()
    if vp is None:
        # Avoid a unique-name clash if a placeholder profile already exists.
        base = name or f'SUPPLIER {personcode}'
        vname, i = base, 1
        while VendorProfile.objects.filter(name=vname).exists():
            i += 1
            vname = f'{base} ({i})'
        vp = VendorProfile.objects.create(name=vname, softech_personcode=personcode)
    # Learn the raw OCR alias so next time it resolves via the 'vendor' path.
    a = (alias or '').strip()
    if a and _norm(a) not in {_norm(x) for x in (vp.aliases or '').split(',')} and _norm(a) not in _GENERIC:
        vp.aliases = (vp.aliases + ',' + a).strip(',') if vp.aliases else a
        vp.save(update_fields=['aliases'])
    return vp


def link_invoice_vendor(invoice, *, conn=None) -> dict | None:
    """Resolve invoice.supplier_name → VendorProfile and attach it (if not already
    linked). Returns the resolution dict, or None when unresolved."""
    if invoice.vendor_id and invoice.vendor and invoice.vendor.softech_personcode:
        return {'personcode': invoice.vendor.softech_personcode,
                'name': invoice.vendor.name, 'score': 1.0, 'source': 'already_linked'}
    res = resolve_supplier(invoice.supplier_name or '', conn=conn)
    if not res:
        return None
    vp = get_or_create_vendor(res['personcode'], res['name'], alias=invoice.supplier_name or '')
    invoice.vendor = vp
    invoice.save(update_fields=['vendor'])
    return res
