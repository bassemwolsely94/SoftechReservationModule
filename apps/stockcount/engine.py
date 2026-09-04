"""
apps/stockcount/engine.py

SOFTECH data-access layer for the Stock Count system.

Public API
----------
preview_items(params)         → list[dict]  (no DB write)
generate_snapshot(session)    → int  (number of snapshots created)
process_upload(session, rows) → dict  (variance summary)

Supported doccodes
------------------
10  → Purchases from suppliers
25  → Transfer received
30  → Sales returns
50  → Stock surplus (adjustment)
80  → Reservation sales
115 → Direct sales
125 → Transfer sent out
150 → Stock deficit (adjustment)
"""
import logging
import random
from decimal import Decimal, InvalidOperation

from decouple import config
from django.utils import timezone

logger = logging.getLogger('elrezeiky.stockcount')

# ── Mock mode (set SOFTECH_MOCK=True in .env when server is unreachable) ──────

_MOCK_MODE = config('SOFTECH_MOCK', default=False, cast=bool)

_MOCK_ITEMS = [
    {'item_code': '1001', 'item_name': 'أموكسيسيلين 500مج كبسول',       'item_medicine': 'أ', 'category_name': 'مضادات حيوية'},
    {'item_code': '1002', 'item_name': 'باراسيتامول 500مج قرص',          'item_medicine': 'ب', 'category_name': 'مسكنات الألم'},
    {'item_code': '1003', 'item_name': 'أومبيبرازول 20مج كبسول',         'item_medicine': 'أ', 'category_name': 'الجهاز الهضمي'},
    {'item_code': '1004', 'item_name': 'ميتفورمين 500مج قرص',            'item_medicine': 'أ', 'category_name': 'السكري'},
    {'item_code': '1005', 'item_name': 'أتورفاستاتين 20مج قرص',          'item_medicine': 'أ', 'category_name': 'الكوليسترول'},
    {'item_code': '1006', 'item_name': 'أملوديبين 5مج قرص',              'item_medicine': 'أ', 'category_name': 'ضغط الدم'},
    {'item_code': '1007', 'item_name': 'سيتريزين 10مج قرص',              'item_medicine': 'ب', 'category_name': 'الحساسية'},
    {'item_code': '1008', 'item_name': 'إيبوبروفين 400مج قرص',           'item_medicine': 'ب', 'category_name': 'مسكنات الألم'},
    {'item_code': '1009', 'item_name': 'ليفوثيروكسين 50مكغ قرص',         'item_medicine': 'أ', 'category_name': 'الغدة الدرقية'},
    {'item_code': '1010', 'item_name': 'ميترونيدازول 250مج قرص',         'item_medicine': 'أ', 'category_name': 'مضادات حيوية'},
    {'item_code': '1011', 'item_name': 'فيتامين ج 1000مج فوار',          'item_medicine': '',  'category_name': 'فيتامينات'},
    {'item_code': '1012', 'item_name': 'زنك 20مج أقراص',                 'item_medicine': '',  'category_name': 'فيتامينات'},
    {'item_code': '1013', 'item_name': 'أوميغا 3 كبسول 1000مج',          'item_medicine': '',  'category_name': 'مكملات غذائية'},
    {'item_code': '1014', 'item_name': 'كلاريثروميسين 500مج قرص',        'item_medicine': 'أ', 'category_name': 'مضادات حيوية'},
    {'item_code': '1015', 'item_name': 'رانيتيدين 150مج قرص',            'item_medicine': 'أ', 'category_name': 'الجهاز الهضمي'},
    {'item_code': '1016', 'item_name': 'ديكلوفيناك 50مج قرص',            'item_medicine': 'ب', 'category_name': 'مسكنات الألم'},
    {'item_code': '1017', 'item_name': 'فلوكونازول 150مج كبسول',          'item_medicine': 'أ', 'category_name': 'مضادات الفطريات'},
    {'item_code': '1018', 'item_name': 'سيبروفلوكساسين 500مج قرص',       'item_medicine': 'أ', 'category_name': 'مضادات حيوية'},
    {'item_code': '1019', 'item_name': 'هيدروكسيزين 25مج قرص',           'item_medicine': 'أ', 'category_name': 'مهدئات'},
    {'item_code': '1020', 'item_name': 'ملح الإماهة الفموي ساشيه',        'item_medicine': '',  'category_name': 'ترطيب'},
]


def _mock_preview_items(branch_code: str, seed_extra: int = 0) -> list:
    """Return deterministic mock items with random-ish stock quantities."""
    rng = random.Random(hash(branch_code) + seed_extra)
    result = []
    for item in _MOCK_ITEMS:
        qty = Decimal(str(rng.randint(0, 250)))
        result.append({**item, 'qty': qty})
    return result

# ── Excluded store codes (quarantine / expired stock at HQ) ──────────────────
_EXCLUDED_STORES = "('102','103','105')"

# ── SQL: distinct items touched by specific transactions ─────────────────────
# Sybase ASE 12.5 has no DATE type and only supports CONVERT styles 0-14/100-114.
# Use direct DATETIME range comparison: docdate >= 'YYYY-MM-DD 00:00:00'
# and docdate < next-day to cover the full end date (avoids style-number issues).
# When user_filter is set, stktransm (sm) is joined to reach sm.usercode.
_SQL_TRANSACTION_ITEMS = """\
SELECT DISTINCT
    st.itemcode,
    i.itemname,
    ISNULL(i.itemmedicine, '') AS itemmedicine,
    ISNULL(ic.classifnamearabic, ISNULL(ic.itemsclassifname, '')) AS category_name
FROM SOFTECHDB9.dbo.stktrans st
JOIN SOFTECHDB9.dbo.items i
    ON i.itemcode = st.itemcode
LEFT JOIN SOFTECHDB9.dbo.itemsclassif ic
    ON ic.itemsclassifcode = i.itemclassifcode
{user_join}
WHERE st.doccode IN ({doccodes})
  AND st.branchcode = '{branch}'
  AND st.docdate >= '{date_from} 00:00:00'
  AND st.docdate <  DATEADD(day, 1, CONVERT(DATETIME, '{date_to}'))
  {user_filter}
  AND st.storecode NOT IN {excluded}
ORDER BY i.itemname"""

# ── SQL: stock balance for a set of items ────────────────────────────────────
_SQL_STOCK_BALANCE = """\
SELECT
    sb.itemcode,
    SUM(CONVERT(DECIMAL(14,3), ISNULL(sb.nowqty, 0))) AS total_qty
FROM SOFTECHDB9.dbo.stkbal sb
WHERE sb.branchcode = '{branch}'
  AND sb.storecode NOT IN {excluded}
  AND sb.itemcode IN ({item_codes})
GROUP BY sb.itemcode"""

# ── SQL: full branch stock (all items with any balance, optional category) ───
_SQL_FULL_STOCK = """\
SELECT
    sb.itemcode,
    i.itemname,
    ISNULL(i.itemmedicine, '') AS itemmedicine,
    ISNULL(ic.classifnamearabic, ISNULL(ic.itemsclassifname, '')) AS category_name,
    SUM(CONVERT(DECIMAL(14,3), ISNULL(sb.nowqty, 0))) AS total_qty
FROM SOFTECHDB9.dbo.stkbal sb
JOIN SOFTECHDB9.dbo.items i
    ON i.itemcode = sb.itemcode
LEFT JOIN SOFTECHDB9.dbo.itemsclassif ic
    ON ic.itemsclassifcode = i.itemclassifcode
WHERE sb.branchcode = '{branch}'
  AND sb.storecode NOT IN {excluded}
  {category_filter}
GROUP BY sb.itemcode, i.itemname, i.itemmedicine,
         ic.classifnamearabic, ic.itemsclassifname
HAVING SUM(CONVERT(DECIMAL(14,3), ISNULL(sb.nowqty, 0))) > 0
ORDER BY i.itemname"""

# ── SQL: specific item list (filtered mode) ───────────────────────────────────
_SQL_FILTERED_STOCK = """\
SELECT
    sb.itemcode,
    i.itemname,
    ISNULL(i.itemmedicine, '') AS itemmedicine,
    ISNULL(ic.classifnamearabic, ISNULL(ic.itemsclassifname, '')) AS category_name,
    SUM(CONVERT(DECIMAL(14,3), ISNULL(sb.nowqty, 0))) AS total_qty
FROM SOFTECHDB9.dbo.stkbal sb
JOIN SOFTECHDB9.dbo.items i
    ON i.itemcode = sb.itemcode
LEFT JOIN SOFTECHDB9.dbo.itemsclassif ic
    ON ic.itemsclassifcode = i.itemclassifcode
WHERE sb.branchcode = '{branch}'
  AND sb.storecode NOT IN {excluded}
  AND sb.itemcode IN ({item_codes})
GROUP BY sb.itemcode, i.itemname, i.itemmedicine,
         ic.classifnamearabic, ic.itemsclassifname
ORDER BY i.itemname"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sybase():
    from config.sybase import get_sybase_connection
    return get_sybase_connection()


def _run(sql: str) -> list:
    """Execute SQL on Sybase and return all rows as plain Python lists."""
    conn = _sybase()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchall()
    finally:
        conn.close()


def _to_dec(val, default=Decimal('0')) -> Decimal:
    if val is None:
        return default
    try:
        return Decimal(str(val)).quantize(Decimal('0.001'))
    except (InvalidOperation, ValueError):
        return default


def _to_str(val, default='') -> str:
    if val is None:
        return default
    return str(val).strip()


def _quoted_list(values) -> str:
    """Format a Python list as SQL IN clause content: 'A','B','C' """
    return ', '.join(f"'{v}'" for v in values)


# ── Item extraction — transaction mode ───────────────────────────────────────

def fetch_transaction_items(
    branch_code: str,
    doccodes: list,
    date_from: str,   # 'YYYY-MM-DD'
    date_to: str,
    user_code: str = '',
) -> list:
    """
    Query SOFTECH for distinct items that appeared in the given transactions.
    Returns list of dicts: {item_code, item_name, item_medicine, category_name}
    """
    if not doccodes:
        return []

    # Only JOIN stktransm when filtering by user (avoids unnecessary join cost)
    if user_code:
        user_join   = (
            "JOIN SOFTECHDB9.dbo.stktransm sm\n"
            "    ON  sm.branchcode = st.branchcode\n"
            "    AND sm.doccode    = st.doccode\n"
            "    AND sm.docnumber  = st.docnumber\n"
            "    AND sm.docdate    = st.docdate"
        )
        user_filter = f"AND sm.usercode = '{user_code}'"
    else:
        user_join   = ''
        user_filter = ''

    sql = _SQL_TRANSACTION_ITEMS.format(
        doccodes    = _quoted_list(doccodes),
        branch      = branch_code,
        date_from   = date_from,
        date_to     = date_to,
        user_join   = user_join,
        user_filter = user_filter,
        excluded    = _EXCLUDED_STORES,
    )

    rows = _run(sql)
    return [
        {
            'item_code':     _to_str(r[0]),
            'item_name':     _to_str(r[1]),
            'item_medicine': _to_str(r[2]),
            'category_name': _to_str(r[3]),
        }
        for r in rows
        if r[0]
    ]


# ── Stock balance lookup ──────────────────────────────────────────────────────

def fetch_stock_balance(branch_code: str, item_codes: list) -> dict:
    """
    Return {item_code: Decimal(qty)} for the given items at this branch.
    Items with no stkbal row return 0.
    """
    if not item_codes:
        return {}

    # Sybase may have limits on IN clause; chunk into batches of 500
    result = {}
    batch_size = 500
    for i in range(0, len(item_codes), batch_size):
        batch = item_codes[i: i + batch_size]
        sql = _SQL_STOCK_BALANCE.format(
            branch      = branch_code,
            item_codes  = _quoted_list(batch),
            excluded    = _EXCLUDED_STORES,
        )
        for row in _run(sql):
            code = _to_str(row[0])
            qty  = _to_dec(row[1])
            result[code] = result.get(code, Decimal('0')) + qty

    return result


def fetch_full_stock(branch_code: str, category_filter: str = '') -> list:
    """
    Return all items with positive balance at this branch.
    Returns list of dicts: {item_code, item_name, item_medicine, category_name, qty}
    """
    cat_clause = ''
    if category_filter:
        cat_clause = f"AND i.itemclassifcode = '{category_filter}'"

    sql = _SQL_FULL_STOCK.format(
        branch          = branch_code,
        excluded        = _EXCLUDED_STORES,
        category_filter = cat_clause,
    )

    rows = _run(sql)
    return [
        {
            'item_code':     _to_str(r[0]),
            'item_name':     _to_str(r[1]),
            'item_medicine': _to_str(r[2]),
            'category_name': _to_str(r[3]),
            'qty':           _to_dec(r[4]),
        }
        for r in rows
        if r[0]
    ]


def fetch_filtered_stock(branch_code: str, item_codes: list) -> list:
    """
    Return stock for a specific list of item_codes.
    Returns list of dicts: {item_code, item_name, item_medicine, category_name, qty}
    """
    if not item_codes:
        return []

    sql = _SQL_FILTERED_STOCK.format(
        branch     = branch_code,
        item_codes = _quoted_list(item_codes),
        excluded   = _EXCLUDED_STORES,
    )

    rows = _run(sql)
    return [
        {
            'item_code':     _to_str(r[0]),
            'item_name':     _to_str(r[1]),
            'item_medicine': _to_str(r[2]),
            'category_name': _to_str(r[3]),
            'qty':           _to_dec(r[4]),
        }
        for r in rows
        if r[0]
    ]


# ── Public: preview items (no DB write) ──────────────────────────────────────

def preview_items(
    mode: str,
    branch_code: str,
    doccodes: list = None,
    date_from: str = None,
    date_to: str = None,
    user_code: str = '',
    category_filter: str = '',
    item_codes_filter: list = None,
) -> list:
    """
    Dry-run: return the items that would be included in this count session.
    Does NOT write anything to the database.

    Returns list of dicts: {item_code, item_name, item_medicine, category_name, qty}
    """
    if _MOCK_MODE:
        logger.warning('SOFTECH_MOCK=True — returning sample data for branch %s', branch_code)
        items = _mock_preview_items(branch_code)
        if mode == 'filtered' and item_codes_filter:
            items = [i for i in items if i['item_code'] in item_codes_filter]
        if category_filter:
            items = [i for i in items if category_filter.lower() in i['category_name'].lower()]
        return items

    if mode == 'transaction':
        item_metas = fetch_transaction_items(
            branch_code, doccodes or [],
            date_from or '', date_to or '',
            user_code,
        )
        if not item_metas:
            return []
        codes = [m['item_code'] for m in item_metas]
        balances = fetch_stock_balance(branch_code, codes)
        return [
            {**m, 'qty': balances.get(m['item_code'], Decimal('0'))}
            for m in item_metas
        ]

    if mode == 'full':
        return fetch_full_stock(branch_code, category_filter)

    # 'expiry_audit' reuses filtered-stock capture: the item set is supplied by
    # the batches purchase-expiry engine (via item_codes_filter) when the session
    # is spawned; the expiry-context/physical-expiry live on the snapshot rows.
    if mode in ('filtered', 'expiry_audit'):
        if item_codes_filter:
            return fetch_filtered_stock(branch_code, item_codes_filter)
        if category_filter:
            return fetch_full_stock(branch_code, category_filter)
        return []

    return []


# ── Public: generate snapshot ────────────────────────────────────────────────

def generate_snapshot(session) -> int:
    """
    Capture the current stock state for all items in the session's scope.
    Creates StockCountSnapshot records (one per item, IMMUTABLE after creation).
    Updates session.status → 'snapshot_taken' and session.item_count.

    Returns the number of snapshot rows created.
    """
    from .models import StockCountSnapshot

    now   = timezone.now()
    items = preview_items(
        mode              = session.mode,
        branch_code       = session.branch_code,
        doccodes          = session.doccodes,
        date_from         = session.date_from.strftime('%Y-%m-%d') if session.date_from else None,
        date_to           = session.date_to.strftime('%Y-%m-%d')   if session.date_to   else None,
        user_code         = session.user_code_filter or '',
        category_filter   = session.category_filter or '',
        item_codes_filter = session.item_codes_filter or [],
    )

    if not items:
        raise ValueError('لم يتم العثور على أصناف تطابق المعايير المحددة')

    # Delete any previous snapshots (re-snapshot scenario)
    StockCountSnapshot.objects.filter(session=session).delete()

    # Bulk-create snapshots
    snapshots = [
        StockCountSnapshot(
            session       = session,
            item_code     = it['item_code'],
            item_name     = it['item_name'],
            item_medicine = it.get('item_medicine', ''),
            category_name = it.get('category_name', ''),
            branch_code   = session.branch_code,
            expected_qty  = it.get('qty', Decimal('0')),
        )
        for it in items
    ]
    StockCountSnapshot.objects.bulk_create(snapshots, ignore_conflicts=False)

    # Update session
    session.status      = 'snapshot_taken'
    session.snapshot_at = now
    session.item_count  = len(snapshots)
    session.save(update_fields=['status', 'snapshot_at', 'item_count', 'updated_at'])

    logger.info(
        'Stock count snapshot generated: session=%s branch=%s items=%d',
        session.pk, session.branch_code, len(snapshots),
    )
    return len(snapshots)


# ── Variance helpers (shared by upload + live count entry) ───────────────────

def _variance_type(diff: Decimal) -> str:
    if abs(diff) < Decimal('0.001'):
        return 'ok'
    return 'surplus' if diff > 0 else 'deficit'


def refresh_session_counts(session, by=None):
    """Recompute a session's surplus/deficit/ok counters and advance its status
    while counting is in progress. Shared by the live count-entry endpoint."""
    from django.db.models import Count, Q
    from .models import StockCountSnapshot
    agg = StockCountSnapshot.objects.filter(session=session).aggregate(
        surplus=Count('id', filter=Q(variance_type='surplus')),
        deficit=Count('id', filter=Q(variance_type='deficit')),
        ok=Count('id', filter=Q(variance_type='ok')),
    )
    now = timezone.now()
    session.surplus_count = agg['surplus']
    session.deficit_count = agg['deficit']
    session.ok_count      = agg['ok']
    session.variance_at   = now
    if session.status in ('snapshot_taken', 'exported'):
        session.status      = 'uploaded'
        session.uploaded_at = now
        if by:
            session.uploaded_by = by
    session.save(update_fields=[
        'surplus_count', 'deficit_count', 'ok_count', 'variance_at',
        'status', 'uploaded_at', 'uploaded_by', 'updated_at',
    ])


def apply_single_count(session, item_code, counted_qty, by=None, physical_expiry=None):
    """Record one counted item (live aisle entry). Returns the updated snapshot,
    or None if the item is not in this session's scope. expected_qty is never
    touched; difference + variance_type are recomputed exactly like the upload path.

    physical_expiry (date | 'YYYY-MM-DD' | None): the real shelf expiry the
    counter reads off the pack — captured for expiry_audit sessions. None leaves
    the stored value unchanged."""
    from datetime import date, datetime
    from .models import StockCountSnapshot
    code = str(item_code).strip()
    snap = StockCountSnapshot.objects.filter(session=session, item_code=code).first()
    if snap is None:
        return None
    counted = Decimal(str(counted_qty)).quantize(Decimal('0.001'))
    snap.counted_qty   = counted
    snap.difference    = counted - snap.expected_qty
    snap.variance_type = _variance_type(snap.difference)
    update_fields = ['counted_qty', 'difference', 'variance_type']

    if physical_expiry is not None:
        parsed = physical_expiry
        if isinstance(parsed, datetime):
            parsed = parsed.date()
        elif isinstance(parsed, str) and parsed.strip():
            try:
                parsed = datetime.strptime(parsed.strip()[:10], '%Y-%m-%d').date()
            except ValueError:
                parsed = None
        elif not isinstance(parsed, date):
            parsed = None
        if parsed is not None:
            snap.physical_expiry = parsed
            update_fields.append('physical_expiry')

    snap.save(update_fields=update_fields)
    refresh_session_counts(session, by=by)
    return snap


# ── Public: process upload results ───────────────────────────────────────────

def process_upload(session, rows: list, uploaded_by=None) -> dict:
    """
    Apply counted quantities from an uploaded file to the session's snapshots.

    rows: list of dicts with keys 'item_code' and 'counted_qty'

    Rules:
      - Only item_codes present in the snapshot are accepted.
      - Unknown item_codes are collected in 'rejected' list.
      - expected_qty is NEVER modified.
      - difference = counted_qty − expected_qty
      - variance_type: 'ok' | 'surplus' | 'deficit'

    Returns a summary dict.
    """
    from .models import StockCountSnapshot

    snapshots = {
        s.item_code: s
        for s in StockCountSnapshot.objects.filter(session=session)
    }

    accepted  = 0
    rejected  = []
    unmatched = []      # items in snapshot that were not in the upload

    for row in rows:
        code     = str(row.get('item_code', '')).strip()
        raw_qty  = row.get('counted_qty')

        if not code:
            continue

        snap = snapshots.get(code)
        if snap is None:
            rejected.append(code)
            continue

        try:
            counted = Decimal(str(raw_qty)).quantize(Decimal('0.001'))
        except (InvalidOperation, TypeError, ValueError):
            rejected.append(code)
            continue

        diff = counted - snap.expected_qty

        if abs(diff) < Decimal('0.001'):
            vtype = 'ok'
        elif diff > 0:
            vtype = 'surplus'
        else:
            vtype = 'deficit'

        snap.counted_qty   = counted
        snap.difference    = diff
        snap.variance_type = vtype
        accepted += 1

    # Bulk-update only the snapshots that were touched
    touched = [s for s in snapshots.values() if s.counted_qty is not None]
    if touched:
        StockCountSnapshot.objects.bulk_update(
            touched, ['counted_qty', 'difference', 'variance_type']
        )

    # Items in snapshot not present in upload
    upload_codes = {str(r.get('item_code', '')).strip() for r in rows}
    unmatched    = [code for code in snapshots if code not in upload_codes]

    # Aggregate counters
    now = timezone.now()
    surplus_count = sum(1 for s in snapshots.values() if s.variance_type == 'surplus')
    deficit_count = sum(1 for s in snapshots.values() if s.variance_type == 'deficit')
    ok_count      = sum(1 for s in snapshots.values() if s.variance_type == 'ok')

    # Update session
    session.status        = 'variance_ready'
    session.uploaded_at   = now
    session.variance_at   = now
    session.uploaded_by   = uploaded_by
    session.surplus_count = surplus_count
    session.deficit_count = deficit_count
    session.ok_count      = ok_count
    session.save(update_fields=[
        'status', 'uploaded_at', 'variance_at', 'uploaded_by',
        'surplus_count', 'deficit_count', 'ok_count', 'updated_at',
    ])

    logger.info(
        'Stock count upload processed: session=%s accepted=%d rejected=%d unmatched=%d',
        session.pk, accepted, len(rejected), len(unmatched),
    )

    return {
        'accepted':     accepted,
        'rejected':     rejected,
        'unmatched':    unmatched,
        'surplus_count': surplus_count,
        'deficit_count': deficit_count,
        'ok_count':      ok_count,
        'total_items':   len(snapshots),
    }
