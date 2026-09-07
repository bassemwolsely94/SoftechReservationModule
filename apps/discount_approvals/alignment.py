"""
apps/discount_approvals/alignment.py

Discount-alignment audit. Compares each item's ACTUAL basic discount
(pharmacy_discp / خصم أساسى) against two expected sources:

  1. Tier label — the % embedded in the item's own classification labels
     (origin_name / store_classif_name, e.g. "Med: Imported Imported 18 %").
  2. Master policy — SupplierDiscountPolicy for the item's supplier/origin
     (the "big supplier's current discount").

Any divergence beyond a tolerance is flagged, so old/new mis-set items surface
and can be fixed (and pushed back to SOFTECH via the existing writeback service).

Pure/read-only — no DB writes, no SOFTECH access. Safe to unit-test.
"""
import re
from decimal import Decimal

TOLERANCE = Decimal('0.01')          # discounts equal within 0.01% are "aligned"

# Matches "18 %", "18%", "25 %", "12.5%" — the discount tier embedded in a label.
_PCT_RE = re.compile(r'(\d+(?:\.\d+)?)\s*%')


def parse_tier_pct(label: str):
    """Extract the discount % embedded in a classification label, or None."""
    if not label:
        return None
    m = _PCT_RE.search(str(label))
    if not m:
        return None
    try:
        return Decimal(m.group(1))
    except Exception:
        return None


def _d(v):
    try:
        return Decimal(str(v))
    except Exception:
        return None


# Classification "family" — the local/imported/… nature encoded in a label. Used
# so a fix suggestion matches BOTH the target % AND the right family (e.g. a 20%
# item that became LOCAL should map to "Local 20%", not "Under-license 20%" of a
# different family). Order matters: check the most specific keywords first.
FAMILY_KEYWORDS = [
    ('imported',  ['مستورد', 'imported', 'egydrug', 'وكيل', 'agent', 'المصرية']),
    ('local',     ['محلى', 'local', 'مصنع', 'under license', 'license', 'استثمارى', 'investment']),
    ('cosmetics', ['cosmetics', 'برفان', 'عطور', 'مزيل']),
    ('supplies',  ['مستلزمات', 'أغذية', 'رضع', 'أطفال', 'ورقيات', 'اجهزه', 'تعويض', 'supplies', 'baby']),
    ('vet',       ['بيطر', 'vetrin', 'veterin']),
    ('services',  ['خدمات', 'services']),
    ('herbal',    ['أعشاب', 'herbal']),
    ('bodybuild', ['كمال اجسام', 'body build', 'bodybuild']),
]


def family_of(label):
    """Classify a tier/origin label into a family bucket, or None."""
    if not label:
        return None
    low = str(label).lower()
    for fam, kws in FAMILY_KEYWORDS:
        if any(k.lower() in low for k in kws):
            return fam
    return None


def infer_item_family(item, basic):
    """
    The item's TRUE family. When one label conflicts with the real discount
    (its % ≠ basic) it is stale → its family is ignored; the non-conflicting
    label's family wins. Falls back to any detected family.
    """
    cands = []   # (family, conflicts?)
    # Each dimension: family may live in the AR name, but the % usually lives in
    # the EN name (e.g. "Med: Imported 18 %" / "مستورد خاص"). Read both.
    for ar, en in ((item.origin_name_ar, item.origin_name),
                   (item.store_classif_name, item.store_classif_name)):
        fam = family_of(ar) or family_of(en)
        if not fam:
            continue
        pct = parse_tier_pct(en) or parse_tier_pct(ar)
        conflicts = pct is not None and abs(pct - basic) > TOLERANCE
        cands.append((fam, conflicts))
    non_conflicting = [f for f, c in cands if not c]
    if non_conflicting:
        return non_conflicting[0]
    return cands[0][0] if cands else None


def evaluate_item(item, policies: dict, origin_idx: dict = None, store_idx: dict = None) -> dict:
    """
    Build the alignment row for one catalog.Item.

    policies: {('supplier', code): SupplierDiscountPolicy, ('origin', code): ...}
    origin_idx / store_idx: {(family, pct_float): tier_dict} — when provided, a
      family-aware fix SUGGESTION (target origin / store tier) is computed.

    Returns a dict with every discount field + parsed expectations + flags.
    """
    basic = _d(item.pharmacy_discp) or Decimal('0')     # خصم أساسى
    pos   = _d(item.pos_discp)                            # حد أقصى خصم مبيعات

    origin_pct = parse_tier_pct(item.origin_name)
    store_pct  = parse_tier_pct(item.store_classif_name)

    supp_pol = policies.get(('supplier', str(item.supplier_code or '')))
    orig_pol = policies.get(('origin',   str(item.origin_code or '')))
    master_pol = supp_pol or orig_pol
    master_pct = _d(master_pol.expected_discount) if master_pol else None

    flags = []
    # Internal consistency: label tier % vs actual basic discount
    if origin_pct is not None and abs(origin_pct - basic) > TOLERANCE:
        flags.append('origin_vs_discount')
    if store_pct is not None and abs(store_pct - basic) > TOLERANCE:
        flags.append('store_vs_discount')
    # Origin tier vs contract tier disagree with each other
    if origin_pct is not None and store_pct is not None and abs(origin_pct - store_pct) > TOLERANCE:
        flags.append('origin_vs_store')
    # Master policy vs actual basic discount
    if master_pct is not None and abs(master_pct - basic) > TOLERANCE:
        flags.append('master_vs_discount')

    # Target % the LABELS should reflect (master-policy direction): the real
    # discount is the truth (or the master policy where configured).
    target_pct = master_pct if master_pct is not None else basic

    # Family-aware fix suggestion: the origin/store tier matching (family, target%).
    family = infer_item_family(item, basic)
    sugg_origin = sugg_store = None
    if family is not None and target_pct is not None:
        key = (family, float(target_pct))
        if origin_idx:
            sugg_origin = origin_idx.get(key)
        if store_idx:
            sugg_store = store_idx.get(key)

    return {
        'item_id':          item.id,
        'softech_id':       item.softech_id,
        'name':             item.name,
        'supplier_code':    item.supplier_code,
        'supplier_name':    item.supplier_name,
        'origin_code':      item.origin_code,
        'origin_name':      item.origin_name_ar or item.origin_name,
        'store_classif':    item.store_classif,
        'store_classif_name': item.store_classif_name,
        'pack_price':       str(_d(item.pack_price) or 0),
        'cost_price':       str(_d(item.cost_price) or 0),
        'pharmacy_discp':   str(basic),                 # خصم أساسى
        'additional_discp': str(_d(item.additional_discp) or 0),
        'special_discp':    str(_d(item.special_discp) or 0),
        'pos_discp':        str(pos) if pos is not None else None,   # حد أقصى خصم مبيعات
        'origin_pct':       str(origin_pct) if origin_pct is not None else None,
        'store_pct':        str(store_pct) if store_pct is not None else None,
        'master_pct':       str(master_pct) if master_pct is not None else None,
        'target_pct':       str(target_pct) if target_pct is not None else None,
        'target_family':    family,
        # Family-aware suggested target tiers (code + name) — pre-fills the fix pickers
        'suggested_origin_code':  sugg_origin['code'] if sugg_origin else None,
        'suggested_origin_name':  sugg_origin['name'] if sugg_origin else None,
        'suggested_store_code':   sugg_store['code'] if sugg_store else None,
        'suggested_store_name':   sugg_store['name'] if sugg_store else None,
        'flags':            flags,
        'misaligned':       bool(flags),
        'is_active':        item.is_active,
        'no_more_use':      item.no_more_use,
    }


def load_policies() -> dict:
    """Load active SupplierDiscountPolicy rows into a lookup dict."""
    from .models import SupplierDiscountPolicy
    return {
        (p.scope, str(p.code)): p
        for p in SupplierDiscountPolicy.objects.filter(is_active=True)
    }


def list_tiers():
    """
    Distinct classification tiers available in the catalog, for the fix-target
    pickers. Returns {'origins': [...], 'store_classifs': [...]} where each entry
    is {code, name, pct}. Sorted by pct then name.
    """
    from apps.catalog.models import Item

    def _tiers(code_field, name_field, name_ar_field=None):
        fields = [code_field, name_field] + ([name_ar_field] if name_ar_field else [])
        seen = {}
        for r in Item.objects.exclude(**{code_field: ''}).values(*fields).distinct():
            code = r.get(code_field)
            if not code:
                continue
            nm = (r.get(name_ar_field) if name_ar_field else None) or r.get(name_field) or code
            if code not in seen:
                pct = parse_tier_pct(r.get(name_field)) or parse_tier_pct(nm)
                seen[code] = {'code': code, 'name': nm,
                              'pct': str(pct) if pct is not None else None,
                              'family': family_of(nm) or family_of(r.get(name_field))}
        return sorted(seen.values(), key=lambda x: (float(x['pct']) if x['pct'] else 999, x['name']))

    return {
        'origins':        _tiers('origin_code',   'origin_name', 'origin_name_ar'),
        'store_classifs': _tiers('store_classif', 'store_classif_name'),
    }


def apply_classification_changes(plan, usercode):
    """
    Write classification codes (origin / contract-discount tier) to SOFTECH items
    — the "fix the stale label" path. Each plan entry may target a DIFFERENT tier
    (per-row suggestions) or the same one (uniform bulk). Mirrors the ERP Save:
    usercode + itemlastupdate = GETDATE() so SSB9 replicates to all branches.
    Read-back verified per item.

    plan: [ {item_id, origin_code?, store_classif?}, ... ]
    Returns (error_or_None, [ {softech_id, ok, error?}, ... ]).
    ADMIN-only + a valid SOFTECH usercode must be enforced by the caller.
    """
    from config.sybase import get_sybase_connection
    from apps.catalog.models import Item

    if not plan:
        return 'لا توجد تغييرات', []
    items = {i.id: i for i in Item.objects.filter(id__in=[p.get('item_id') for p in plan])}

    results = []
    conn = get_sybase_connection()
    cur = conn.cursor()
    try:
        for p in plan:
            it = items.get(p.get('item_id'))
            if it is None:
                results.append({'item_id': p.get('item_id'), 'ok': False, 'error': 'not found'})
                continue
            set_cols = []
            if p.get('origin_code') not in (None, ''):
                set_cols.append(('itemorigincode', 'origin_code', str(p['origin_code'])))
            if p.get('store_classif') not in (None, ''):
                set_cols.append(('itemstoreclassif', 'store_classif', str(p['store_classif'])))
            if not set_cols:
                results.append({'softech_id': it.softech_id, 'ok': False, 'error': 'لا هدف'})
                continue
            set_clause = ', '.join(f'{col} = ?' for col, _, _ in set_cols)
            sql = (f'UPDATE SOFTECHDB9.dbo.items SET {set_clause}, '
                   f'usercode = ?, itemlastupdate = GETDATE() WHERE itemcode = ?')
            params = [v for _, _, v in set_cols] + [str(usercode), it.softech_id]
            try:
                cur.execute(sql, params)
                verify = ', '.join(col for col, _, _ in set_cols)
                cur.execute(f'SELECT {verify} FROM SOFTECHDB9.dbo.items WHERE itemcode = ?',
                            [it.softech_id])
                row = cur.fetchone()
                ok = bool(row) and all(
                    str(row[i] or '').strip() == set_cols[i][2] for i in range(len(set_cols))
                )
                if ok:
                    for _, django_field, v in set_cols:
                        setattr(it, django_field, v)
                    it.save(update_fields=[df for _, df, _ in set_cols])
                    results.append({'softech_id': it.softech_id, 'ok': True})
                else:
                    results.append({'softech_id': it.softech_id, 'ok': False, 'error': 'read-back mismatch'})
            except Exception as exc:
                results.append({'softech_id': it.softech_id, 'ok': False, 'error': str(exc)[:150]})
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return None, results


# ── Phase 3: create NEW classification tiers in SOFTECH lookup tables ─────────
# Whitelisted tables only. New rows are created by COPYING an existing row as a
# template (so every NOT-NULL column gets a valid value) then overriding just the
# code + description columns — the safest generic way to add a lookup value.
LOOKUP_TABLES = {
    'origin': {'table': 'itemsorigin',      'code_col': 'itemorigincode'},   # المنشأ
    'store':  {'table': 'custdiscpclassif', 'code_col': 'custdiscpcode'},     # تصنيف خصم التعاقدات
}


def _tier_schema(cur, spec):
    # NOTE: this Sybase ASE does NOT support `SELECT TOP n` (syntax error). The
    # lookup tables are tiny (~21 rows), so plain SELECT + fetchone() is fine.
    cur.execute(f"SELECT * FROM SOFTECHDB9.dbo.{spec['table']}")
    cols = [d[0] for d in cur.description]
    template = cur.fetchone()
    code_col = spec['code_col'] if spec['code_col'] in cols else cols[0]
    desc_cols = [c for c in cols
                 if c != code_col and ('desc' in c.lower() or 'name' in c.lower())]
    return cols, template, code_col, desc_cols


def _next_code(cur, table, code_col):
    cur.execute(f"SELECT MAX(CONVERT(INT, {code_col})) FROM SOFTECHDB9.dbo.{table} "
                f"WHERE {code_col} NOT LIKE '%[^0-9]%'")
    mx = cur.fetchone()[0] or 0
    return str(int(mx) + 1)


def preview_new_tier(kind, label, code=None):
    """READ-ONLY. Returns the discovered schema + the exact row that would be
    inserted, so it can be reviewed before any write. kind ∈ {'origin','store'}."""
    if kind not in LOOKUP_TABLES:
        return {'error': 'نوع غير صالح'}
    from config.sybase import get_sybase_connection
    spec = LOOKUP_TABLES[kind]
    conn = get_sybase_connection(); cur = conn.cursor()
    try:
        cols, template, code_col, desc_cols = _tier_schema(cur, spec)
        new_code = str(code) if code else _next_code(cur, spec['table'], code_col)
        cur.execute(f"SELECT 1 FROM SOFTECHDB9.dbo.{spec['table']} WHERE {code_col} = ?", [new_code])
        exists = cur.fetchone() is not None
        proposed = dict(zip(cols, template))
        proposed[code_col] = new_code
        for dc in desc_cols:
            proposed[dc] = label
    finally:
        try: conn.close()
        except Exception: pass
    return {
        'table': spec['table'], 'code_col': code_col, 'desc_cols': desc_cols,
        'new_code': new_code, 'code_exists': exists, 'columns': cols,
        'template_row': {c: (str(v) if v is not None else None) for c, v in zip(cols, template)},
        'proposed_row': {c: (str(v) if v is not None else None) for c, v in proposed.items()},
    }


def create_new_tier(kind, label, usercode, code=None):
    """
    Create a new lookup tier (COPY template → override code + description).
    Read-back verified. Returns (error_or_None, {code, ok}).
    ADMIN-only must be enforced by the caller.
    """
    if kind not in LOOKUP_TABLES:
        return 'نوع غير صالح', None
    if not label or not str(label).strip():
        return 'الاسم مطلوب', None
    from config.sybase import get_sybase_connection
    spec = LOOKUP_TABLES[kind]
    conn = get_sybase_connection(); cur = conn.cursor()
    try:
        cols, template, code_col, desc_cols = _tier_schema(cur, spec)
        new_code = str(code) if code else _next_code(cur, spec['table'], code_col)
        cur.execute(f"SELECT 1 FROM SOFTECHDB9.dbo.{spec['table']} WHERE {code_col} = ?", [new_code])
        if cur.fetchone():
            return f'الكود {new_code} مستخدم بالفعل', None

        vals = dict(zip(cols, template))
        vals[code_col] = new_code
        for dc in desc_cols:
            vals[dc] = label
        # Sensible overrides for known lookup columns (not blind template copies):
        low_label = str(label).lower()
        is_imported = any(k in low_label for k in ('import', 'مستورد', 'egydrug', 'وكيل'))
        for c in cols:
            cl = c.lower()
            if cl == 'usercode':
                vals[c] = str(usercode)
            elif cl == 'importedorigin':     # itemsorigin flag: 1=imported, 0=local
                vals[c] = '1' if is_imported else '0'

        # Columns written as literal SQL (not parameters): fresh timestamps.
        literal = {c: 'GETDATE()' for c in cols if 'lastupdate' in c.lower() or 'modif' in c.lower()}
        col_sql, param_cols = [], []
        for c in cols:
            if c in literal:
                col_sql.append(literal[c])
            else:
                col_sql.append('?')
                param_cols.append(c)
        sql = (f"INSERT INTO SOFTECHDB9.dbo.{spec['table']} ({', '.join(cols)}) "
               f"VALUES ({', '.join(col_sql)})")
        cur.execute(sql, [vals[c] for c in param_cols])

        # read-back verify
        verify = desc_cols[0] if desc_cols else code_col
        cur.execute(f"SELECT {verify} FROM SOFTECHDB9.dbo.{spec['table']} WHERE {code_col} = ?", [new_code])
        row = cur.fetchone()
        ok = row is not None
    finally:
        try: conn.close()
        except Exception: pass
    if not ok:
        return 'لم يُؤكَّد الإدراج (read-back)', None
    return None, {'code': new_code, 'table': spec['table'], 'ok': True}


def scan_alignment(item_qs, only_misaligned: bool = True, limit: int = 2000):
    """
    Evaluate a catalog Item queryset. Returns (rows, stats).
    only_misaligned → keep only flagged rows (default).
    """
    policies = load_policies()
    # Build family-aware tier indices once so each row gets a fix suggestion.
    tiers = list_tiers()
    origin_idx = {(t['family'], float(t['pct'])): t
                  for t in tiers['origins'] if t['family'] and t['pct'] is not None}
    store_idx  = {(t['family'], float(t['pct'])): t
                  for t in tiers['store_classifs'] if t['family'] and t['pct'] is not None}

    rows, checked, flagged = [], 0, 0
    for item in item_qs.iterator():
        checked += 1
        row = evaluate_item(item, policies, origin_idx, store_idx)
        if row['misaligned']:
            flagged += 1
        if row['misaligned'] or not only_misaligned:
            rows.append(row)
            if len(rows) >= limit:
                break
    stats = {'checked': checked, 'flagged': flagged, 'returned': len(rows)}
    return rows, stats
