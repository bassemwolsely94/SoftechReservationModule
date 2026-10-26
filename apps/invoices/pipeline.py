"""
apps/invoices/pipeline.py

Shared OCR→match→line-build pipeline for a SINGLE SupplierInvoice.

Extracted verbatim (behaviour-preserving) from views.SupplierInvoiceViewSet so
there is exactly ONE matching implementation, reused by:
  - the single-image/PDF upload path (views._run_ocr), and
  - the multi-invoice bundle path (ingest.process_bundle), which feeds the pages
    of one detected invoice as already-rendered images.

Nothing here contacts SOFTECH; it only reads catalog/mirror data to suggest
matches. The 4-tier matching order (itemssuppliers code → learned code →
learned name → fuzzy, with the Arabic-first / English-rescue rule) is unchanged.
"""
import logging
import re

logger = logging.getLogger('elrezeiky.invoices')


# ── matcher precision helpers (barcode-exact tier + strength-conflict guard) ─────
def _looks_like_barcode(code: str) -> bool:
    """A long all-digit string is an EAN/UPC barcode, not a short supplier SKU."""
    c = (code or '').strip()
    return c.isdigit() and 8 <= len(c) <= 14


def _item_by_barcode(code: str):
    """Catalog Item whose primary (Item.barcode) or secondary (Barcode) barcode
    equals ``code`` exactly. None when nothing matches."""
    from apps.catalog.models import Item, ItemBarcode
    it = Item.objects.filter(barcode=code).first()
    if it:
        return it
    bc = ItemBarcode.objects.filter(barcode=code, is_active=True).select_related('item').first()
    return bc.item if bc else None


_STRENGTH_NU = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*(mg/5ml|mg/ml|mcg|mg|ml|iu|gm|g|%|مجم|ملجم|ملج|مج|مل)', re.IGNORECASE)

# canonicalize units so Arabic and English spellings of the same unit compare equal
# (مجم == مج == mg), otherwise a conflict between '5 مجم' and '10 mg' is missed.
_UNIT_CANON = {'مجم': 'mg', 'ملجم': 'mg', 'ملج': 'mg', 'مج': 'mg', 'مل': 'ml',
               'gm': 'g', 'mg': 'mg', 'ml': 'ml', 'mcg': 'mcg', 'iu': 'iu',
               'g': 'g', '%': '%', 'mg/ml': 'mg/ml', 'mg/5ml': 'mg/5ml'}


def _strength_num_unit(name: str):
    m = _STRENGTH_NU.search((name or '').lower())
    if not m:
        return None
    try:
        unit = _UNIT_CANON.get(m.group(2).lower(), m.group(2).lower())
        return (float(m.group(1).replace(',', '.')), unit)
    except ValueError:
        return None


def _strength_conflict(name_a: str, name_b: str) -> bool:
    """True when both names carry a strength in the SAME unit but a DIFFERENT
    magnitude (e.g. '5 مجم' vs '10 مجم') — a wrong-DOSE match that must never be
    auto-accepted (CLAUDE.md rule 4: pharmacy safety beats a convenient match).
    Different units (500mg vs 0.5g) are NOT flagged — can't be compared safely."""
    a = _strength_num_unit(name_a)
    b = _strength_num_unit(name_b)
    if not a or not b:
        return False
    return a[1] == b[1] and abs(a[0] - b[0]) > 1e-6


def learn_invoice_mappings(invoice, profile=None) -> int:
    """Learning loop: on confirm, remember every matched line as a
    VendorItemMapping (vendor + normalized raw OCR name → item, with the supplier
    code) so the next invoice from this distributor matches instantly — the free
    OCR path gets more accurate per vendor over time. Returns #mappings touched."""
    from .models import VendorItemMapping
    from .ocr import separate_code_and_batch
    from apps.shortage.matching import _normalize

    n = 0
    for line in invoice.lines.select_related('item').all():
        if not line.item_id:
            continue
        norm = _normalize(line.manual_name or line.raw_text or '')
        if not norm:
            continue
        code = (line.vendor_item_code or '').strip()
        # never learn a batch number as the supplier's item code
        if code and separate_code_and_batch(code, line.batch_number)[2]:
            code = ''
        mapping, created = VendorItemMapping.objects.get_or_create(
            vendor=invoice.vendor, raw_name_normalized=norm,
            defaults={'item': line.item, 'vendor_item_code': code,
                      'use_count': 1, 'created_by': profile})
        if not created:
            mapping.item = line.item
            mapping.use_count += 1
            if code:
                mapping.vendor_item_code = code
            mapping.save(update_fields=['item', 'vendor_item_code', 'use_count', 'updated_at'])
        n += 1
    return n


def apply_ocr_header(invoice, header):
    """Fill blank invoice header fields from the OCR'd header (never overwrite
    what a user already entered)."""
    from datetime import datetime
    if header.get('supplier_name') and not invoice.supplier_name:
        invoice.supplier_name = header['supplier_name'][:200]
    if header.get('invoice_number') and not invoice.invoice_number:
        invoice.invoice_number = header['invoice_number'][:50]
    if header.get('currency') and not invoice.currency:
        invoice.currency = header['currency'][:10]
    if header.get('invoice_date') and not invoice.invoice_date:
        try:
            invoice.invoice_date = datetime.strptime(header['invoice_date'][:10], '%Y-%m-%d').date()
        except (ValueError, TypeError):
            pass
    if header.get('declared_total'):
        invoice.declared_total = header['declared_total']


_PCT_FIELDS = ('discount_pct', 'extra_discount_pct', 'special_discount_pct', 'vat_pct')
_NUM_FIELDS = ('quantity', 'bonus_qty', 'public_price', 'unit_price', 'distributor_margin_amt',
               'pharmacist_margin_amt') + _PCT_FIELDS


def _fit_numbers(cand) -> tuple:
    """OCR can put a barcode / a total into a number column (a real Pharma Overseas page read
    1,000+ into «VAT %»). A value that can't be right — a percentage outside 0–100, or a number
    too large for its column — is dropped (0) and named, instead of crashing the whole line
    (and, in a bundle, losing the invoice). Returns ({field: value}, [dropped 'field=value'])."""
    from decimal import Decimal, InvalidOperation
    from .models import InvoiceLine
    out, dropped = {}, []
    for name in _NUM_FIELDS:
        if name not in cand:
            continue
        raw = cand.get(name)
        try:
            v = Decimal(str(raw if raw not in (None, '') else 0))
        except (InvalidOperation, ValueError):
            out[name] = 0
            dropped.append(f'{name}={raw}')
            continue
        f = InvoiceLine._meta.get_field(name)
        limit = Decimal(10) ** (f.max_digits - f.decimal_places)
        bad = abs(v) >= limit or (name in _PCT_FIELDS and not (0 <= v <= 100))
        if bad:
            dropped.append(f'{name}={raw}')
            v = Decimal(0)          # a 0 quantity is blocked by validations → a person fixes it
        out[name] = v
    return out, dropped


def match_candidates(candidates, vendor):
    """Match each OCR candidate to a catalog Item with the 4-tier logic, WITHOUT
    writing any InvoiceLine rows. Returns one dict per candidate, aligned with the
    input order:  {item, score, match_review, tier}  where ``tier`` is one of
    'itemssuppliers' | 'vendor_code' | 'vendor_name' | 'fuzzy' | '' (no match).

    This is the single source of truth for invoice→catalog matching: ``build_lines``
    delegates to it, and the accuracy benchmark calls it directly, so the two can
    never drift. ``vendor`` is the resolved VendorProfile (or None — then the
    vendor-scoped tiers degrade to global lookups and Tier-0 is skipped)."""
    from .models import VendorItemMapping
    from apps.shortage.matching import find_best_matches, _normalize
    from apps.catalog.models import Item

    # ── Tier 0 (batch): SOFTECH itemssuppliers recall (authoritative code→item) ──
    supplier_code_map = {}
    if vendor and vendor.softech_personcode and vendor.is_main:
        codes = [(c.get('vendor_item_code') or '').strip() for c in candidates]
        codes = [c for c in codes if c]
        if codes:
            from apps.catalog.supplier_links import resolve_codes as mirror_codes
            supplier_code_map = mirror_codes(vendor.softech_personcode, codes)
            missing = [c for c in codes if c not in supplier_code_map]
            if missing:
                try:
                    from . import supplier_items
                    conn = supplier_items.open_conn()
                    try:
                        supplier_code_map.update(supplier_items.resolve_codes(
                            conn, vendor.softech_personcode, missing))
                    finally:
                        conn.close()
                except Exception as e:
                    logger.warning('itemssuppliers recall failed: %s', e)

    results = []
    for cand in candidates:
        name_raw = (cand.get('manual_name') or cand.get('raw_text') or '')
        code     = (cand.get('vendor_item_code') or '').strip()
        item_obj = None
        score    = None
        tier     = ''
        match_review = False

        # ── 0. SOFTECH itemssuppliers: supplier code → catalog item ──
        if code and code in supplier_code_map:
            item_obj = Item.objects.filter(softech_id=supplier_code_map[code]).first()
            if item_obj:
                score, tier = 1.0, 'itemssuppliers'

        # ── 1. Learned supplier item code (our PG mirror) ──
        if item_obj is None and code:
            code_qs = VendorItemMapping.objects.filter(vendor_item_code=code)
            if vendor:
                code_qs = code_qs.filter(vendor=vendor)
            m = code_qs.select_related('item').order_by('-use_count').first()
            if m:
                item_obj, score, tier = m.item, 1.0, 'vendor_code'

        # ── 2. Learned name mapping ──
        if item_obj is None and name_raw:
            norm = _normalize(name_raw)
            name_qs = VendorItemMapping.objects.filter(raw_name_normalized=norm)
            if vendor:
                name_qs = name_qs.filter(vendor=vendor)
            m = name_qs.select_related('item').order_by('-use_count').first()
            if m:
                item_obj, score, tier = m.item, 1.0, 'vendor_name'

        # ── 2.5 barcode-exact: a scanned EAN/UPC in the code field → catalog item.
        # Authoritative and helps the FIRST sighting (no itemssuppliers/learning). ──
        if item_obj is None and _looks_like_barcode(code):
            it = _item_by_barcode(code)
            if it:
                item_obj, score, tier = it, 1.0, 'barcode'

        # ── 3. Learned corpus + fuzzy fallback (Arabic-first, English rescues),
        # STRENGTH-AWARE: from the top candidates prefer one whose strength doesn't
        # conflict with the OCR name, so '5mg' doesn't get matched to the '10mg'
        # sibling just because the names are similar. ──
        if item_obj is None and name_raw:
            vcode  = (vendor.softech_personcode or '') if vendor else ''

            def _pick(cands):
                """(chosen candidate, all_conflicted?) — best non-strength-conflicting
                candidate, else the top one with a flag that every option conflicts."""
                if not cands:
                    return None, False
                ok = [c for c in cands if not _strength_conflict(name_raw, c.get('name', ''))]
                return (ok[0] if ok else cands[0]), (not ok)

            ar, ar_conf = _pick(find_best_matches(name_raw, top_n=5, min_score=0.5, vendor_code=vcode))
            best = ar
            gen_en = (cand.get('generic_name_en') or '').strip()
            en = None
            if gen_en:
                en, _ = _pick(find_best_matches(gen_en, top_n=5, min_score=0.5, vendor_code=vcode))
                if (best is None or best['score'] < 0.60) and en and \
                   (best is None or en['score'] > best['score']):
                    best = en
            if ar and en and ar['item_id'] != en['item_id']:
                match_review = True
            if best:
                # strength still conflicts even after trying alternatives → wrong-dose
                # risk: keep the suggestion but force review, never silent-accept.
                if _strength_conflict(name_raw, best.get('name', '')):
                    match_review = True
                try:
                    item_obj = Item.objects.get(pk=best['item_id'])
                    score, tier = best['score'], 'fuzzy'
                except Item.DoesNotExist:
                    pass

        results.append({'item': item_obj, 'score': score,
                        'match_review': match_review, 'tier': tier})
    return results


def build_lines(invoice, candidates):
    """
    Resolve the supplier, match every candidate to a catalog Item (via the shared
    ``match_candidates`` 4-tier matcher), and create InvoiceLine rows. Idempotent
    only in the sense that the caller clears existing lines first when re-running.
    """
    from .models import InvoiceLine
    from .ocr import normalize_expiry

    # Resolve the supplier → SOFTECH personcode and link a VendorProfile BEFORE
    # item matching, so vendor-scoped mappings apply. Offline; never fatal.
    if not (invoice.vendor_id and invoice.vendor and invoice.vendor.softech_personcode):
        try:
            from . import suppliers
            res = suppliers.link_invoice_vendor(invoice)
            if res:
                logger.info('invoice %s supplier %r → personcode %s (%s)',
                            invoice.pk, invoice.supplier_name, res['personcode'], res['source'])
        except Exception as e:
            logger.warning('supplier resolution failed for invoice %s: %s', invoice.pk, e)

    vendor = invoice.vendor
    matches = match_candidates(candidates, vendor)

    for idx, cand in enumerate(candidates):
        name_raw     = cand['manual_name'] or cand['raw_text']
        code         = (cand.get('vendor_item_code') or '').strip()
        mr           = matches[idx]
        item_obj     = mr['item']
        score        = mr['score']
        match_review = mr['match_review']

        nums, dropped = _fit_numbers(cand)
        if dropped:
            cand = {**cand, 'notes': (cand.get('notes', '') + ' — قيم غير منطقية من القراءة أُهملت: ' +
                                      '، '.join(dropped)).strip(' —')}
        cand = {**cand, **nums}
        InvoiceLine.objects.create(
            invoice                = invoice,
            raw_text               = cand['raw_text'],
            manual_name            = name_raw,
            manufacturer           = cand.get('manufacturer', ''),
            vendor_item_code       = code,
            batch_number           = cand.get('batch_number', ''),
            notes                  = (cand.get('notes', '') + (
                f" — قُرئ: كود «{cand['read_as']['vendor_item_code']}» تشغيلة «{cand['read_as']['batch_number']}»"
                if cand.get('read_as') else ''))[:300],
            expiry_date            = normalize_expiry(cand.get('expiry_date', '')) or cand.get('expiry_date', ''),
            quantity               = cand['quantity'],
            bonus_qty              = cand.get('bonus_qty', 0) or 0,
            public_price           = cand.get('public_price', 0),
            discount_pct           = cand.get('discount_pct', 0),
            extra_discount_pct     = cand.get('extra_discount_pct', 0),
            special_discount_pct   = cand.get('special_discount_pct', 0) or 0,
            unit_price             = cand.get('unit_price', 0),
            vat_pct                = cand.get('vat_pct', 0),
            distributor_margin_amt = cand.get('distributor_margin_amt', 0),
            pharmacist_margin_amt  = cand.get('pharmacist_margin_amt', 0),
            item                   = item_obj,
            match_score            = score,
            match_review           = match_review,
            ocr_confidence         = cand.get('ocr_confidence'),
            order                  = idx,
        )
