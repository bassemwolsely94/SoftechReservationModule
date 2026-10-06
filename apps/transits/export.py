"""
apps/transits/export.py

Picking-sheet (ورقة التجميع) Excel export for SOFTECH replenishment orders
(doccode 125 — already-issued transactions cached in InTransitTransfer).

Replaces the Supply Chain team's manual pipeline of:
    SOFTECH print → save as HTML → Power Query in
    "Replenishment Order Printing File.xlsm" → classified picking sheet.

Workbook layout (one export = one workbook):
  Sheet 1   "التجميع الموحد" — consolidated pick matrix: one row per item across
            all selected orders, one qty column per order/branch, total qty,
            sorted by pick zone then item name (the warehouse pick path).
  Sheet 2+  "مراجعة <doc>"   — one revision sheet per order in the same zone
            order, with expiry/batch/prices, a revision check column and a
            signature block. Printed twice: one copy stays with the packer,
            one travels with the shipment to the destination branch.

Pick-zone classification rules live in SystemSetting 'replenishment_pick_zones'
(JSON, seeded by seed_config from PICK_ZONE_RULES_DEFAULT below — a 1:1 port of
the team's Power Query M logic). Rules evaluate top-to-bottom; the first
keyword hit wins; the price threshold (and the catalog fridge flag) outrank
all keyword rules. Zones sort as plain strings — the numeric prefixes in the
category labels ARE the pick-path order, exactly as in the team's Excel.
"""
import datetime
import io
import logging
from decimal import Decimal

logger = logging.getLogger('elrezeiky.transits')

try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    _HAS_OPENPYXL = True
except ImportError:                                       # pragma: no cover
    _HAS_OPENPYXL = False
    logger.warning('openpyxl not installed — picking-sheet export unavailable')


# ── Default pick zones + rules (bootstrap seed for the DB tables) ─────────────
# Sort keys preserve the team's historical pick path (their Excel sorted the
# old "1./20./21./3./…" prefixes as STRINGS — these numeric keys reproduce
# that exact walking order). Fully editable afterwards from /pick-zones.
PRICE_THRESHOLD_DEFAULT = 500      # سعر جمهور >= → منطقة الغوالي
FRIDGE_KEYWORD = 'FRIDGE'          # + catalog requires_fridge flag

# Rule match_field → (catalog Item CODE column, label-column candidates).
# 'name' is special-cased (keyword contains-search); these are exact-value
# matches against the item-master classification columns, whose values come
# from the SOFTECH lookup sub-tables (itemshape / itemstree / itemsfamily / …).
MATCH_FIELDS = {
    'shape':         ('shape_code',    ('shape_name_ar', 'shape_name')),
    'medicine_type': ('medicine_type', ('medicine_type_name_ar', 'medicine_type_name')),
    'family':        ('family_code',   ('family_name_ar', 'family_name')),
    'producer':      ('producer_code', ('producer_name',)),
    'origin':        ('origin_code',   ('origin_name_ar', 'origin_name')),
    'unit':          ('unit_code',     ('unit_name',)),
}
ATTR_COLUMNS = [code for code, _labels in MATCH_FIELDS.values()]

# (sort_key, name, is_price_zone, is_fridge_zone, is_fallback)
DEFAULT_ZONES = [
    (10,  'غوالى-ثلاجه',  True,  True,  False),
    (20,  'أقراص',        False, False, False),
    (30,  'كريم-مرهم-جل', False, False, False),
    (40,  'بخاخات-سبراى', False, False, False),
    (50,  'حقن',          False, False, False),
    (60,  'لبوس',         False, False, False),
    (70,  'قطرات-نقط',    False, False, False),
    (80,  'فوارات',       False, False, False),
    (90,  'شامبو',        False, False, False),
    (100, 'مضمضه',        False, False, False),
    (110, 'ألبان',        False, False, False),
    (120, 'شراب',         False, False, False),
    (130, 'لوسيون-سيرم',  False, False, False),
    (140, 'محلول',        False, False, False),
    (999, 'غير مصنف',     False, False, True),
]

# (priority, zone_name, keywords) — evaluation order = Power Query if-chain
DEFAULT_RULES = [
    (10,  'أقراص',        ['TAB', 'CAP', 'LOZENG']),
    (20,  'كريم-مرهم-جل', ['CREAM', 'OINT', 'GEL']),
    (30,  'قطرات-نقط',    ['DROP']),
    (40,  'حقن',          ['AMP', 'VIAL', 'INJECT']),
    (50,  'لبوس',         ['SUPP']),
    (60,  'شراب',         ['SUSP', 'SUSPENSION', 'SYRUP', 'SYP', 'SYR', 'ORAL SOL']),
    (70,  'بخاخات-سبراى', ['INHAL', 'HALER', 'DISKUS']),
    (80,  'غوالى-ثلاجه',  ['PEN ', 'FLEXPEN', 'CARTRIDGE', 'CARTIDGE', 'PENFILL']),
    (90,  'فوارات',       ['GRAN', 'SACH', 'SAC ', ' EFF', 'EFF ']),
    (100, 'ألبان',        ['MILK']),
    (110, 'بخاخات-سبراى', ['SPRAY']),
    (120, 'محلول',        ['SOLUTION']),
    (130, 'لوسيون-سيرم',  ['LOTION', 'SERUM']),
    (140, 'شامبو',        [' SH ']),
    (150, 'مضمضه',        ['MOUTHWASH']),
]


def seed_default_pick_zones(stdout=None):
    """
    Idempotent bootstrap: create the default zones + rules when the PickZone
    table is empty, and ensure the price-threshold setting exists (500 EGP).
    Existing zones/rules are never touched. Returns (zones_created, rules_created).
    """
    from apps.config.models import SystemSetting
    from .models import PickZone, PickZoneRule

    zones_created = rules_created = 0
    if not PickZone.objects.exists():
        by_name = {}
        for sort_key, name, is_price, is_fridge, is_fallback in DEFAULT_ZONES:
            by_name[name] = PickZone.objects.create(
                name=name, sort_key=sort_key,
                is_price_zone=is_price, is_fridge_zone=is_fridge,
                is_fallback=is_fallback,
            )
            zones_created += 1
        for priority, zone_name, keywords in DEFAULT_RULES:
            PickZoneRule.objects.create(
                zone=by_name[zone_name], priority=priority, keywords=keywords,
            )
            rules_created += 1

    SystemSetting.objects.get_or_create(
        key='replenishment_price_threshold',
        defaults={
            'label': 'حد سعر الغوالي (ج.م)',
            'description': 'الصنف الذي يبلغ سعر جمهوره هذا الحد أو أكثر يذهب لمنطقة الغوالي في ورقة التجميع',
            'value': str(PRICE_THRESHOLD_DEFAULT),
            'value_type': 'integer',
            'category': 'transfers',
        },
    )
    # legacy JSON rules setting superseded by the PickZone tables
    SystemSetting.objects.filter(key='replenishment_pick_zones').delete()

    if stdout:
        stdout.write(f'pick zones: {zones_created} zones, {rules_created} rules created')
    return zones_created, rules_created


class _PseudoZone:
    """In-memory stand-in when the PickZone table is empty (no DB writes)."""
    def __init__(self, sort_key, name, location=''):
        self.id = None
        self.sort_key = sort_key
        self.name = name
        self.location = location

    @property
    def sheet_label(self):
        return f'{self.name} — {self.location}' if self.location else self.name


def _rule_hit(match_field, values, name_u, attrs):
    """Return the matching keyword/value, or None."""
    if match_field == 'name':
        for kw in values:
            if kw and kw.upper() in name_u:
                return kw
        return None
    col = MATCH_FIELDS.get(match_field, (None,))[0]
    if not col:
        return None
    item_val = str((attrs or {}).get(col) or '').strip()
    if not item_val:
        return None
    for v in values:
        if str(v).strip() == item_val:
            return v
    return None


class Ruleset:
    """
    Snapshot of the full classification config, loaded once per export/request
    for ONE supplying location (branch config, falling back to the default).

    classify() precedence:
      item override (branch-specific beats default) → fridge (flag OR 'FRIDGE'
      in name) → price threshold → rules by priority (name keywords OR exact
      item-master column values) → fallback zone
    """

    def __init__(self, threshold, price_zone, fridge_zone, fallback_zone,
                 rules, overrides=None):
        self.threshold = threshold
        self.price_zone = price_zone
        self.fridge_zone = fridge_zone
        self.fallback_zone = fallback_zone
        self.rules = rules                      # [(zone, match_field, [values…]), …]
        self.overrides = overrides or {}        # itemcode → (zone, tag)

    def classify(self, name, price=None, requires_fridge=False, itemcode=None,
                 attrs=None):
        """Returns (zone, tag) — tag is non-empty only for overrides."""
        if itemcode and itemcode in self.overrides:
            return self.overrides[itemcode]

        name_u = (name or '').upper()

        if self.fridge_zone and (requires_fridge or FRIDGE_KEYWORD in name_u):
            return self.fridge_zone, ''

        if self.price_zone and self.threshold and price is not None:
            try:
                if float(price) >= float(self.threshold):
                    return self.price_zone, ''
            except (TypeError, ValueError):
                pass

        for zone, match_field, values in self.rules:
            if _rule_hit(match_field, values, name_u, attrs) is not None:
                return zone, ''

        return self.fallback_zone, ''

    def explain(self, name, price=None, requires_fridge=False, itemcode=None,
                attrs=None):
        """Like classify() but also says WHY: (zone, tag, reason_ar)."""
        if itemcode and itemcode in self.overrides:
            zone, tag = self.overrides[itemcode]
            return zone, tag, 'تخصيص يدوي للصنف'

        name_u = (name or '').upper()

        if self.fridge_zone and (requires_fridge or FRIDGE_KEYWORD in name_u):
            why = ('علامة ثلاجة بالكتالوج' if requires_fridge
                   else f'كلمة {FRIDGE_KEYWORD} بالاسم')
            return self.fridge_zone, '', f'ثلاجة ({why})'

        if self.price_zone and self.threshold and price is not None:
            try:
                if float(price) >= float(self.threshold):
                    return (self.price_zone, '',
                            f'السعر {price} ≥ حد الغوالي {_num(self.threshold)}')
            except (TypeError, ValueError):
                pass

        field_labels = dict(
            [('name', 'كلمة')] +
            [(k, label) for k, label in [
                ('shape', 'شكل الصنف'), ('medicine_type', 'نوع الدواء'),
                ('family', 'عائلة الصنف'), ('producer', 'الشركة المنتجة'),
                ('origin', 'بلد المنشأ'), ('unit', 'وحدة العبوة'),
            ]]
        )
        for zone, match_field, values in self.rules:
            hit = _rule_hit(match_field, values, name_u, attrs)
            if hit is not None:
                label = field_labels.get(match_field, match_field)
                return zone, '', f'قاعدة {label} "{hit}"'

        return self.fallback_zone, '', 'لا يطابق أي قاعدة — غير مصنف'


def build_ruleset(item_codes=None, branch=None, purpose='picking') -> Ruleset:
    """
    Load the active classification config for ONE location + purpose.

    `branch`  — Branch instance or id of the location.
    `purpose` — 'picking'  (تجميع: supplying-warehouse walk order) or
                'stocking' (ترصيص: destination-branch shelf order; also used
                by stock-count sheets).

    Zone resolution chain (first non-empty wins):
      picking : (branch, picking) → (default, picking) → built-in defaults
      stocking: (branch, stocking) → (default, stocking)
                → (branch, picking) → (default, picking) → built-in defaults
    Overrides resolve per item WITHIN the same purpose: branch-specific
    beats default. `item_codes` limits the override lookup.
    """
    from apps.config.models import SystemSetting
    from .models import ItemPickOverride, PickZone

    branch_id = getattr(branch, 'id', branch) or None
    purpose   = purpose if purpose in ('picking', 'stocking') else 'picking'

    try:
        threshold = float(SystemSetting.get('replenishment_price_threshold',
                                            PRICE_THRESHOLD_DEFAULT))
    except (TypeError, ValueError):
        threshold = PRICE_THRESHOLD_DEFAULT

    chain = [(branch_id, purpose)] if branch_id else [(None, purpose)]
    if branch_id:
        chain.append((None, purpose))
    if purpose == 'stocking':
        if branch_id:
            chain.append((branch_id, 'picking'))
        chain.append((None, 'picking'))

    zones = []
    for b_id, p in chain:
        qs = PickZone.objects.filter(is_active=True, purpose=p)
        qs = qs.filter(branch_id=b_id) if b_id else qs.filter(branch__isnull=True)
        zones = list(qs.prefetch_related('rules'))
        if zones:
            break

    if not zones:
        # Bootstrap-free fallback — mirror DEFAULT_ZONES/DEFAULT_RULES in memory
        pseudo = {name: _PseudoZone(sk, name)
                  for sk, name, _p, _f, _fb in DEFAULT_ZONES}
        price_zone = fridge_zone = pseudo['غوالى-ثلاجه']
        fallback   = pseudo['غير مصنف']
        rules = [(pseudo[zname], 'name', kws) for _prio, zname, kws in DEFAULT_RULES]
        return Ruleset(threshold, price_zone, fridge_zone, fallback, rules)

    price_zone    = next((z for z in zones if z.is_price_zone), None)
    fridge_zone   = next((z for z in zones if z.is_fridge_zone), None)
    fallback_zone = next((z for z in zones if z.is_fallback), None) or (
        zones[-1] if zones else None)

    rules = []
    for z in zones:
        for r in z.rules.all():
            if r.is_active and r.keywords:
                rules.append((r.priority, r.id, z, r.match_field, r.keywords))
    rules.sort(key=lambda t: (t[0], t[1]))
    rules = [(z, mf, kws) for _p, _id, z, mf, kws in rules]

    # Overrides: same purpose only; default (branch NULL) first,
    # then branch-specific wins per item
    overrides = {}
    ov_qs = (ItemPickOverride.objects.select_related('zone', 'item')
             .filter(purpose=purpose)
             .filter(db_q_branch(branch_id)))
    if item_codes is not None:
        ov_qs = ov_qs.filter(item__softech_id__in=list(item_codes))
    for ov in ov_qs.order_by('branch_id'):     # NULLs first on PG ASC? enforce below
        if not ov.zone.is_active:
            continue
        code = ov.item.softech_id
        if ov.branch_id:                        # branch-specific always wins
            overrides[code] = (ov.zone, ov.tag or '')
        elif code not in overrides:             # default fills the gaps
            overrides[code] = (ov.zone, ov.tag or '')

    return Ruleset(threshold, price_zone, fridge_zone, fallback_zone,
                   rules, overrides)


def classify_for_stocking(item_codes, branch=None):
    """
    Cross-module helper (used by apps/stockcount count sheets): classify item
    codes with the branch's STOCKING config (ترصيص — shelf order, with the
    stocking→picking fallback chain) and return {itemcode: zone}.

    Codes missing from the catalog land in the fallback zone so every row
    still gets a deterministic position in the counting walk.
    """
    from apps.catalog.models import Item

    codes = [str(c).strip() for c in (item_codes or []) if str(c).strip()]
    ruleset = build_ruleset(item_codes=codes, branch=branch, purpose='stocking')

    zone_map = {}
    if codes:
        for it in Item.objects.filter(softech_id__in=codes).only(
            'softech_id', 'name', 'pack_price', 'requires_fridge', *ATTR_COLUMNS,
        ):
            zone, _tag = ruleset.classify(
                it.name, it.pack_price, it.requires_fridge,
                itemcode=it.softech_id,
                attrs={col: getattr(it, col, '') for col in ATTR_COLUMNS},
            )
            zone_map[it.softech_id] = zone
    for c in codes:
        zone_map.setdefault(c, ruleset.fallback_zone)
    return zone_map


def db_q_branch(branch_id):
    """Q filter: default overrides + (optionally) the branch's own."""
    from django.db.models import Q
    q = Q(branch__isnull=True)
    if branch_id:
        q |= Q(branch_id=branch_id)
    return q


# ── Styling (palette matches apps/stockcount/excel_io.py) ─────────────────────
_HEADER_BG   = 'FF1F3864'   # dark navy
_HEADER_FG   = 'FFFFFFFF'
_TITLE_BG    = 'FF2E75B6'   # blue
_ZONE_BG     = 'FFD9E2F3'   # light blue — zone change stripe
_CHECK_BG    = 'FFFFFFCC'   # pale yellow — handwritten columns
_EXPIRY_BG   = 'FFFCE4D6'   # light red — near-expiry warning
_TOTAL_BG    = 'FFE2EFDA'   # light green
_PARTIAL_BG  = 'FFFFE9C7'   # amber — partial (part-pack) quantity

_thin  = Side(style='thin', color='FF9CA3AF') if _HAS_OPENPYXL else None
_BOX   = Border(left=_thin, right=_thin, top=_thin, bottom=_thin) if _HAS_OPENPYXL else None

_NEAR_EXPIRY_DAYS = 45


def _fill(color):
    return PatternFill(start_color=color, end_color=color, fill_type='solid')


def _is_near_expiry(expiry_iso) -> bool:
    if not expiry_iso:
        return False
    try:
        exp = datetime.date.fromisoformat(str(expiry_iso)[:10])
    except (ValueError, TypeError):
        return False
    return exp <= datetime.date.today() + datetime.timedelta(days=_NEAR_EXPIRY_DAYS)


# ── Export modes ──────────────────────────────────────────────────────────────
# picking  (ورقة التجميع)  — classified by the SUPPLYING branch's picking config
# stocking (ورقة الترصيص) — classified by the RECEIVING branch's stocking config
EXPORT_MODES = {
    'picking': {
        'purpose':        'picking',
        'branch_of':      lambda t: t.supplying_branch_id,
        'consol_sheet':   'التجميع الموحد',
        'consol_title':   'ورقة التجميع الموحدة (مسار مخزن المصدر)',
        'order_sheet':    'مراجعة {doc}',
        'order_title':    'إذن صرف بضاعة إلى فرع — ورقة المراجعة',
        'check_col':      'تجميع ✓',
        'order_check':    'مراجعة ✓',
        'signatures':     ['أمين المخزن:', 'جمعه:', 'راجعه:', 'مستلم الفرع:'],
        'filename':       'picking',
    },
    'stocking': {
        'purpose':        'stocking',
        'branch_of':      lambda t: t.receiving_branch_id,
        'consol_sheet':   'الترصيص الموحد',
        'consol_title':   'ورقة الترصيص الموحدة (ترتيب أرفف الفرع المستلم)',
        'order_sheet':    'ترصيص {doc}',
        'order_title':    'إذن صرف بضاعة إلى فرع — ورقة الترصيص (أرفف الفرع)',
        'check_col':      'ترصيص ✓',
        'order_check':    'ترصيص ✓',
        'signatures':     ['مستلم الفرع:', 'رصّصه:', 'راجعه:', 'مدير الفرع:'],
        'filename':       'stocking',
    },
}


# ── Data assembly ─────────────────────────────────────────────────────────────

def _catalog_maps(item_codes, supplying_branch_ids):
    """
    Bulk-resolve catalog + HQ-balance data.

    Returns (item_map, balance_map):
      item_map    : itemcode → {producer, price, fridge, name}
      balance_map : (itemcode, branch_id) → Decimal quantity on hand
                    (summed across stores, quarantine stores excluded)
    """
    from django.db.models import Sum
    from apps.catalog.models import EXCLUDED_STORE_CODES, Item, ItemStock

    item_map = {}
    for it in Item.objects.filter(softech_id__in=item_codes).only(
        'softech_id', 'name', 'producer_name', 'pack_price', 'requires_fridge',
        'pack_qty', *ATTR_COLUMNS,
    ):
        item_map[it.softech_id] = {
            'name':     it.name,
            'producer': it.producer_name or '',
            'price':    it.pack_price,
            'fridge':   it.requires_fridge,
            'pack_qty': it.pack_qty or 1,
            'attrs':    {col: getattr(it, col, '') for col in ATTR_COLUMNS},
        }

    balance_map = {}
    if supplying_branch_ids:
        rows = (
            ItemStock.objects
            .filter(item__softech_id__in=item_codes,
                    branch_id__in=supplying_branch_ids)
            .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
            .values('item__softech_id', 'branch_id')
            .annotate(qty=Sum('quantity_on_hand'))
        )
        for r in rows:
            balance_map[(r['item__softech_id'], r['branch_id'])] = r['qty'] or Decimal('0')

    return item_map, balance_map


def _build_lines(transfers, mode='picking'):
    """
    Flatten + enrich + classify every snapshot line of every transfer.

    Returns (per_order, consolidated):
      per_order    : [{transfer, lines: [line, …]}, …]  — sorted zone→name
      consolidated : [{zone, itemcode, itemname, expiry(earliest), balance,
                       qty_by_transfer: {transfer_id: qty}, total_qty,
                       near_expiry}, …]                 — sorted zone→name

    Each line/row carries the zone as an object (PickZone or _PseudoZone) —
    sheets sort by (zone.sort_key, zone.name) = the configured pick path.
    """
    all_codes  = set()
    branch_ids = set()
    for t in transfers:
        all_codes.update(
            str(e.get('itemcode') or '').strip()
            for e in (t.items_snapshot or [])
        )
        if t.supplying_branch_id:
            branch_ids.add(t.supplying_branch_id)
    all_codes.discard('')

    # One ruleset per location — each order classifies with the config of the
    # mode's relevant branch (picking: supplying / stocking: receiving),
    # falling back per the resolution chain. The consolidated sheet uses each
    # item's zone from its first-seen order; mixed-location bulk exports are
    # rare (one warehouse/branch per physical pass).
    mode_cfg  = EXPORT_MODES[mode]
    _rulesets = {}

    def _ruleset_for(branch_id):
        if branch_id not in _rulesets:
            _rulesets[branch_id] = build_ruleset(item_codes=all_codes,
                                                 branch=branch_id,
                                                 purpose=mode_cfg['purpose'])
        return _rulesets[branch_id]

    item_map, balance_map = _catalog_maps(list(all_codes), list(branch_ids))

    def _zone_sort(z):
        return (z.sort_key, z.name) if z else (9999, '')

    per_order = []
    consolidated_idx = {}

    for t in transfers:
        ruleset = _ruleset_for(mode_cfg['branch_of'](t))
        lines = []
        for entry in (t.items_snapshot or []):
            code = str(entry.get('itemcode') or '').strip()
            if not code:
                continue
            cat  = item_map.get(code, {})
            name = cat.get('name') or entry.get('itemname') or code
            price = cat.get('price')
            zone, tag = ruleset.classify(
                name, price, cat.get('fridge', False), itemcode=code,
                attrs=cat.get('attrs'),
            )

            qty    = float(entry.get('qty') or 0)
            expiry = entry.get('expiry') or None
            balance = balance_map.get((code, t.supplying_branch_id))
            pack_qty = cat.get('pack_qty', 1)
            qty_text, is_partial = _qty_parts(qty, pack_qty, name)

            line = {
                'zone':        zone,
                'tag':         tag,
                'itemcode':    code,
                'itemname':    name,
                'producer':    cat.get('producer', ''),
                'qty':         qty,
                'pack_qty':    pack_qty,
                'qty_text':    qty_text,
                'is_partial':  is_partial,
                'expiry':      expiry,
                'batch':       entry.get('batch') or '',
                'price':       price,
                'extended':    (float(price) * qty) if price is not None else None,
                'cost':        float(entry.get('extended_cost') or 0),
                'balance':     balance,
                'near_expiry': _is_near_expiry(expiry),
            }
            lines.append(line)

            crow = consolidated_idx.setdefault(code, {
                'zone': zone, 'tag': tag, 'itemcode': code, 'itemname': name,
                'expiry': expiry, 'balance': balance, 'pack_qty': pack_qty,
                'qty_by_transfer': {}, 'total_qty': 0.0,
                'near_expiry': False,
            })
            crow['qty_by_transfer'][t.id] = crow['qty_by_transfer'].get(t.id, 0.0) + qty
            crow['total_qty'] += qty
            if expiry and (not crow['expiry'] or expiry < crow['expiry']):
                crow['expiry'] = expiry
            crow['near_expiry'] = crow['near_expiry'] or _is_near_expiry(crow['expiry'])

        lines.sort(key=lambda l: (_zone_sort(l['zone']), l['itemname']))
        per_order.append({'transfer': t, 'lines': lines})

    consolidated = sorted(
        consolidated_idx.values(),
        key=lambda r: (_zone_sort(r['zone']), r['itemname']),
    )
    # spell out partial totals once every order's qty has been accumulated
    for rec in consolidated:
        rec['qty_text'], rec['is_partial'] = _qty_parts(
            rec['total_qty'], rec.get('pack_qty', 1), rec['itemname'])
    return per_order, consolidated


# ── A4 print fitting ──────────────────────────────────────────────────────────
# Everything must land inside ONE A4 page width, fully readable on paper.
#
# Excel column "width units" ≈ characters of the default font; a column of
# width w renders as (7·w + 5) pixels at 96 DPI. So the printable budget is
#     sum(w) = (usable_inches · 96 − 5·ncols) / 7
# A4 landscape = 11.69in wide; with the near-zero side margins below that
# leaves ~11.49in ≈ 1103px. Portrait = 8.27in → ~8.07in ≈ 775px.
_PAGE_MARGIN_IN = 0.10          # side margins (the user accepts none)
_A4_LANDSCAPE_IN = 11.69
_A4_PORTRAIT_IN  = 8.27


def _width_budget(ncols: int, landscape: bool = True) -> float:
    """Total column-width units that fit one A4 page across."""
    page_in = _A4_LANDSCAPE_IN if landscape else _A4_PORTRAIT_IN
    usable_px = (page_in - 2 * _PAGE_MARGIN_IN) * 96
    return max((usable_px - 5 * ncols) / 7.0, 10)


def _apply_widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = round(w, 2)


def _fit_widths(plan, flex_index, ncols, landscape=True,
                flex_min=26, flex_max=52, spill_index=-1):
    """
    Turn a column plan into printable widths + the number of A4 pages needed
    across. Returns (widths, pages_wide).

    • `flex_index` — the item-name column. It absorbs the page's spare width,
      clamped to [flex_min, flex_max]: never so narrow that wrapping turns a
      name into a tower of single letters, never wastefully wide.
    • leftover width beyond flex_max goes to `spill_index` (the notes column),
      giving staff a bigger handwriting box instead of dead margin.
    • When the columns genuinely cannot fit one page (a consolidated matrix
      with many branch columns), we DON'T crush them to unreadable slivers —
      we report pages_wide > 1 so the caller sets fitToWidth accordingly and
      repeats the identity columns on each page.
    """
    import math

    budget = _width_budget(ncols, landscape)
    widths = list(plan)
    others = sum(w for i, w in enumerate(widths) if i != flex_index)

    widths[flex_index] = max(flex_min, min(budget - others, flex_max))

    leftover = budget - sum(widths)
    if leftover > 1 and spill_index is not None:
        widths[spill_index] += leftover

    pages_wide = max(1, math.ceil(sum(widths) / budget - 0.02))
    return widths, pages_wide


# ── Worksheet writers ─────────────────────────────────────────────────────────

def _setup_sheet(ws, *, landscape=True):
    ws.sheet_view.rightToLeft = True
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = 'landscape' if landscape else 'portrait'
    ws.page_setup.fitToWidth = 1     # safety net; the width plan already fits
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    # No side margins — the user wants maximum usable width.
    ws.page_margins.left = ws.page_margins.right = _PAGE_MARGIN_IN
    ws.page_margins.top = ws.page_margins.bottom = 0.3
    ws.page_margins.header = ws.page_margins.footer = 0


def _title_row(ws, row, text, ncols):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    c = ws.cell(row=row, column=1, value=text)
    c.font = Font(bold=True, size=12, color=_HEADER_FG)
    c.fill = _fill(_TITLE_BG)
    # Wrap + a height that grows with the text so long title lines (bulk
    # exports list every document number) stay fully visible in print.
    c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    ws.row_dimensions[row].height = 24 if len(text) <= 110 else 38


def _header_row(ws, row, headers):
    """Header cells wrap; the row is tall enough for two-line branch labels."""
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=col, value=h)
        c.font = Font(bold=True, size=9, color=_HEADER_FG)
        c.fill = _fill(_HEADER_BG)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        c.border = _BOX
    tallest = max((str(h).count('\n') + 1) for h in headers) if headers else 1
    ws.row_dimensions[row].height = max(30, 15 * tallest + 8)


def _branch_label(transfer):
    b = transfer.receiving_branch
    name = (b.name if b else '') or transfer.erp_receiving_branch_code or '؟'
    return f'{name}\n({transfer.erp_doc_number})'


def _write_consolidated_sheet(wb, per_order, consolidated, mode='picking'):
    """Sheet 1 — the consolidated matrix (pick walk or shelf walk per mode)."""
    mode_cfg = EXPORT_MODES[mode]
    ws = wb.active
    ws.title = mode_cfg['consol_sheet']
    _setup_sheet(ws)

    transfers = [po['transfer'] for po in per_order]
    fixed_head = ['م', 'المنطقة', 'الكود', 'إســم الصنـف', 'ت الصلاحية', 'رصيد المصدر']
    qty_heads  = [_branch_label(t) for t in transfers]
    tail_head  = ['إجمالي الكمية', 'تفصيل الكمية', mode_cfg['check_col'], 'ملاحظات']
    headers    = fixed_head + qty_heads + tail_head
    ncols      = len(headers)

    today = datetime.date.today().strftime('%Y/%m/%d')
    docs  = '، '.join(t.erp_doc_number for t in transfers)
    _title_row(ws, 1, f"{mode_cfg['consol_title']} — أذونات: {docs} — {today}", ncols)
    _header_row(ws, 2, headers)
    ws.freeze_panes = 'A3'
    ws.print_title_rows = '1:2'

    row = 3
    prev_zone = object()
    serial = 0
    for rec in consolidated:
        zone_name  = rec['zone'].name if rec['zone'] else 'غير مصنف'
        zone_label = rec['zone'].sheet_label if rec['zone'] else 'غير مصنف'
        if zone_name != prev_zone:
            # zone stripe row (pick-path section break, with warehouse location)
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
            c = ws.cell(row=row, column=1, value=zone_label)
            c.font = Font(bold=True, size=11)
            c.fill = _fill(_ZONE_BG)
            c.alignment = Alignment(horizontal='right', vertical='center')
            row += 1
            prev_zone = zone_name

        serial += 1
        values = [
            serial, zone_name, rec['itemcode'], rec['itemname'],
            rec['expiry'] or '', _num(rec['balance']),
        ]
        values += [_num(rec['qty_by_transfer'].get(t.id)) or '' for t in transfers]
        values += [_num(rec['total_qty']), rec.get('qty_text') or '',
                   '', rec.get('tag') or '']

        qty_first = len(fixed_head) + 1                    # first branch qty col
        total_col = len(fixed_head) + len(qty_heads) + 1   # إجمالي الكمية
        detail_col = total_col + 1                         # تفصيل الكمية

        for col, v in enumerate(values, start=1):
            c = ws.cell(row=row, column=col, value=v)
            c.border = _BOX
            # Item name + qty breakdown wrap so nothing is clipped on paper.
            c.alignment = Alignment(
                horizontal='right' if col in (4, detail_col) else 'center',
                vertical='center',
                wrap_text=(col in (4, detail_col)),
            )
            if col in (4, detail_col):
                c.font = Font(size=9)
            if col == 5 and rec['near_expiry']:
                c.fill = _fill(_EXPIRY_BG)
            # quantities: exact decimals, whole numbers without a trailing dot
            if col == 6 or qty_first <= col <= total_col:
                c.number_format = _num_format(v)
            if col == total_col:
                c.font = Font(bold=True)
                c.fill = _fill(_TOTAL_BG)
            elif col == detail_col:
                if rec.get('is_partial'):
                    c.fill = _fill(_PARTIAL_BG)       # flag part-pack picking
                    c.font = Font(size=9, bold=True, color='FF9A3412')
            elif col > total_col:
                c.fill = _fill(_CHECK_BG)
        row += 1

    # Column plan: fixed columns + one qty column per order; the item-name
    # column (index 3) absorbs whatever the A4 budget leaves over.
    plan = ([4, 12, 8, 40, 10, 9] + [9] * len(qty_heads) + [9, 14, 7, 10])
    widths, pages_wide = _fit_widths(plan, flex_index=3, ncols=ncols)
    _apply_widths(ws, widths)
    # Many branch columns can't fit one page across — print over N pages and
    # repeat the identity columns (م/المنطقة/الكود/الصنف) on each of them.
    ws.page_setup.fitToWidth = pages_wide
    if pages_wide > 1:
        ws.print_title_cols = 'A:D'
    return ws


def _write_revision_sheet(wb, po, mode='picking'):
    """One sheet per order — revision (picking) or shelf-order (stocking)."""
    mode_cfg = EXPORT_MODES[mode]
    t     = po['transfer']
    lines = po['lines']

    title = mode_cfg['order_sheet'].format(doc=t.erp_doc_number)[:31]
    ws = wb.create_sheet(title=title)
    _setup_sheet(ws)

    headers = ['م', 'المنطقة', 'الكود', 'إســم الصنـف', 'الشركة المنتجة',
               'الكمية', 'تفصيل الكمية', 'ت الصلاحية', 'التشغيلة', 'سعر الجمهور',
               'الإجمالي', mode_cfg['order_check'], 'ملاحظات']
    ncols = len(headers)

    _title_row(ws, 1, mode_cfg['order_title'], ncols)

    # header info block
    from_name = (t.supplying_branch.name if t.supplying_branch
                 else t.erp_supplying_branch_code)
    to_name   = (t.receiving_branch.name if t.receiving_branch
                 else t.erp_receiving_branch_code or '؟')
    # Three different money bases exist — label them so they're never confused:
    #   ERP document value   (stktransm.docvalue)
    #   ERP line-cost total  (Σ stktrans.transprice_total)
    #   retail total         (Σ سعر الجمهور × الكمية) — the totals row below
    cost_total = sum(l.get('cost') or 0.0 for l in lines)
    info = [
        ('رقم إذن الصرف', t.erp_doc_number,
         'من فرع', from_name, False),
        ('تاريخ الإذن', _fmt_date(t.issue_date),
         'إلى فرع', to_name, False),
        ('عدد الأصناف', len(lines),
         'قيمة المستند (ERP)', _num(t.doc_value), True),
        ('إجمالي الكمية (عبوات)', _num(sum(l['qty'] for l in lines)),
         'إجمالي تكلفة البنود (ERP)', _num(cost_total), True),
    ]
    r = 2
    for k1, v1, k2, v2, is_money in info:
        for col, val, bold in ((1, k1, True), (3, v1, False),
                               (6, k2, True), (8, v2, False)):
            c = ws.cell(row=r, column=col, value=val)
            c.font = Font(bold=bold, size=10)
            c.alignment = Alignment(horizontal='right')
            if is_money and col == 8:
                c.number_format = _num_format(v2, money=True)
            if col == 3 and k1.startswith('إجمالي الكمية'):
                c.number_format = _num_format(v1)
        r += 1

    head_row = r
    _header_row(ws, head_row, headers)
    ws.freeze_panes = f'A{head_row + 1}'
    ws.print_title_rows = f'{head_row}:{head_row}'

    row = head_row + 1
    prev_zone = object()
    serial = 0
    total_qty = 0.0
    total_val = 0.0
    for line in lines:
        zone_name  = line['zone'].name if line['zone'] else 'غير مصنف'
        zone_label = line['zone'].sheet_label if line['zone'] else 'غير مصنف'
        if zone_name != prev_zone:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
            c = ws.cell(row=row, column=1, value=zone_label)
            c.font = Font(bold=True, size=11)
            c.fill = _fill(_ZONE_BG)
            c.alignment = Alignment(horizontal='right', vertical='center')
            row += 1
            prev_zone = zone_name

        serial += 1
        total_qty += line['qty']
        total_val += line['extended'] or 0.0
        values = [
            serial, zone_name, line['itemcode'], line['itemname'],
            line['producer'], _num(line['qty']), line.get('qty_text') or '',
            line['expiry'] or '', line['batch'],
            _num(line['price']), _num(line['extended']),
            '', line.get('tag') or '',
        ]
        for col, v in enumerate(values, start=1):
            c = ws.cell(row=row, column=col, value=v)
            c.border = _BOX
            # Item name / producer / qty breakdown wrap — nothing gets clipped.
            c.alignment = Alignment(
                horizontal='right' if col in (4, 5, 7) else 'center',
                vertical='center',
                wrap_text=(col in (4, 5, 7)),
            )
            if col in (4, 5, 7):
                c.font = Font(size=9)
            if col == 6:                                  # الكمية
                c.number_format = _num_format(v)
            elif col == 7 and line.get('is_partial'):     # تفصيل الكمية
                c.fill = _fill(_PARTIAL_BG)
                c.font = Font(size=9, bold=True, color='FF9A3412')
            elif col == 8 and line['near_expiry']:        # ت الصلاحية
                c.fill = _fill(_EXPIRY_BG)
            elif col in (10, 11):                         # السعر / الإجمالي
                c.number_format = _num_format(v, money=True)
            elif col in (12, 13):                         # مراجعة ✓ / ملاحظات
                c.fill = _fill(_CHECK_BG)
        row += 1

    # totals row — labelled so it is never mistaken for the ERP document value
    lbl = ws.cell(row=row, column=4, value='الإجمالي (سعر الجمهور)')
    lbl.font = Font(bold=True)
    lbl.alignment = Alignment(horizontal='right')
    for col, v, is_money in ((6, _num(total_qty), False),
                             (11, _num(total_val), True)):
        c = ws.cell(row=row, column=col, value=v)
        c.font = Font(bold=True)
        c.fill = _fill(_TOTAL_BG)
        c.border = _BOX
        c.number_format = _num_format(v, money=is_money)
    row += 2

    # signature block
    for col, label in zip((1, 4, 7, 10), mode_cfg['signatures']):
        c = ws.cell(row=row, column=col, value=f'{label} ........................')
        c.font = Font(bold=True, size=10)

    # م، المنطقة، الكود، [الصنف — مرن]، الشركة، الكمية، تفصيل الكمية،
    # الصلاحية، التشغيلة، السعر، الإجمالي، مراجعة، ملاحظات
    plan = [4, 12, 8, 40, 13, 7, 14, 10, 10, 9, 10, 7, 10]
    widths, pages_wide = _fit_widths(plan, flex_index=3, ncols=ncols)
    _apply_widths(ws, widths)
    ws.page_setup.fitToWidth = pages_wide
    return ws


def _fmt_date(d):
    """date/datetime/ISO-string → 'YYYY/MM/DD' (or '' when unset)."""
    if not d:
        return ''
    if isinstance(d, (datetime.date, datetime.datetime)):
        return d.strftime('%Y/%m/%d')
    return str(d)[:10].replace('-', '/')


# Legacy fixed formats (kept for any external import). Prefer _num_format().
_FMT_MONEY = '#,##0.00'
_FMT_QTY   = '0.###'


def _num_format(value, money=False):
    """
    Excel number format chosen per value: whole numbers get NO trailing dot,
    fractions show their decimals, everything is thousands-grouped.

        quantities (money=False) — exact decimals, never rounded:
            5    → '#,##0'      → "5"
            2.5  → '#,##0.0'    → "2.5"
            0.25 → '#,##0.00'   → "0.25"
        money (money=True) — capped at 2 dp (conventional; tiny rounding on
        4-dp internal cost figures is accepted):
            5400     → '#,##0'    → "5,400"
            49949.99 → '#,##0.00' → "49,949.99"
            16649.99 → '#,##0.00' → "16,650.00"

    A fixed format like '0.###' can't do this: Excel renders its literal
    decimal point even for integers ("5."), which is the readability problem
    this replaces.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 'General'
    # decimals actually present — strip float noise, then trailing zeros
    txt = f'{abs(f):.6f}'.rstrip('0').rstrip('.')
    dp = len(txt.split('.', 1)[1]) if '.' in txt else 0
    if dp == 0:
        return '#,##0'                       # whole number → no decimal point
    return '#,##0.00' if money else f'#,##0.{"0" * dp}'


def _num(v):
    """Decimal/float → numeric cell value (precision kept; format handles display)."""
    if v is None or v == '':
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return round(f, 5)


# Sub-unit wording for partial packs. `unit_name` in the catalog is the PACK
# noun ('علبة') for virtually every row, so the sub-unit is inferred from the
# item name instead — with a neutral fallback.
_SUBUNIT_KEYWORDS = [
    ('STRIP',   'شريط'),
    ('FLEXPEN', 'قلم'),
    ('PENFILL', 'قلم'),
    ('CARTRID', 'خرطوشة'),
    ('VIAL',    'فيال'),
    ('AMP',     'أمبول'),
    ('SACH',    'كيس'),
    ('SUPP',    'لبوسة'),
]


def _subunit_label(name: str) -> str:
    name_u = (name or '').upper()
    for kw, label in _SUBUNIT_KEYWORDS:
        if kw in name_u:
            return label
    return 'وحدة'


def _qty_parts(qty, pack_qty, name=''):
    """
    Spell out a partial quantity: (text, is_partial).

    SOFTECH stores quantities in PACKS, so a fraction is a part-pack —
    e.g. qty 2.333 of a 3-strip pack = '2 علبة + 1 شريط'. Whole quantities
    return '' (the numeric column already states them plainly).
    """
    try:
        q = float(qty or 0)
    except (TypeError, ValueError):
        return '', False

    packs = int(q)
    frac  = q - packs
    if frac <= 1e-9:
        return '', False

    try:
        pk = max(int(pack_qty or 1), 1)
    except (TypeError, ValueError):
        pk = 1

    units   = frac * pk
    rounded = round(units)
    label   = _subunit_label(name)

    if pk > 1 and rounded >= 1 and abs(units - rounded) < 0.02:
        tail = f'{rounded} {label}'
    else:
        # not a clean sub-unit split (odd ERP fraction) — state it as-is
        tail = f'{frac:g} علبة'

    return (f'{packs} علبة + {tail}' if packs else tail), True


# ── Public entry point ────────────────────────────────────────────────────────

def generate_picking_workbook(transfers, mode='picking') -> tuple:
    """
    Build the workbook for one or more InTransitTransfer records.

    mode='picking'  → ورقة التجميع: consolidated pick matrix + revision sheets,
                      classified by each order's SUPPLYING branch picking config.
    mode='stocking' → ورقة الترصيص: same structure but classified by each
                      order's RECEIVING branch stocking config (shelf order),
                      so branch staff shelve goods in one walk.

    Returns (bytes, filename, content_type). Raises RuntimeError when openpyxl
    is unavailable (unlike stock count there is no meaningful CSV fallback —
    the multi-sheet layout is the whole point).
    """
    if mode not in EXPORT_MODES:
        raise ValueError(f'وضع تصدير غير معروف: {mode}')
    if not _HAS_OPENPYXL:
        raise RuntimeError('openpyxl غير مثبت — لا يمكن توليد الورقة')

    transfers = list(transfers)
    if not transfers:
        raise ValueError('لا توجد أذونات للتصدير')

    per_order, consolidated = _build_lines(transfers, mode=mode)

    wb = openpyxl.Workbook()
    _write_consolidated_sheet(wb, per_order, consolidated, mode=mode)
    for po in per_order:
        _write_revision_sheet(wb, po, mode=mode)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    prefix = EXPORT_MODES[mode]['filename']
    if len(transfers) == 1:
        filename = f'{prefix}_{transfers[0].erp_doc_number}.xlsx'
    else:
        today = datetime.date.today().isoformat()
        filename = f'{prefix}_{len(transfers)}_orders_{today}.xlsx'

    return (
        buf.getvalue(),
        filename,
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
