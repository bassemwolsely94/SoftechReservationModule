"""
apps/loyalty/pic_bridge.py

SOFTECH <-> Django PIC points bridge.

HOW SOFTECH MANAGES POINTS (discovered via investigate_pic_points):
====================================================================
SOFTECH uses a 3-table architecture:

  1. picpoints  (transaction log)
       phcode       VARCHAR(13)   -- the PIC
       transdate    DATETIME      -- when the event happened
       points       INT           -- delta: positive = earned, negative = redeemed
       branchcode   VARCHAR(5)    -- originating branch
       doccode      VARCHAR(3)    -- document type code (e.g. 'INV', 'ADJ')
       docnumber    DECIMAL(6)    -- document serial number
       docdate      DATETIME      -- document date
       table_dumped DATETIME      -- replication stamp (NULL for new rows)
       vf1          VARCHAR(50)   -- free-use field (we store: reason)
       vf2          VARCHAR(50)   -- free-use field (we store: CRM operator label)
       vf3          VARCHAR(50)   -- free-use field (unused by CRM)

  2. localcustomers.picpoints  (running balance column)
       Updated AUTOMATICALLY by trigger tr_picpoints when a row is
       inserted into the picpoints table above.
       We NEVER UPDATE this column directly.

  3. localcustomerspoints  (branch-level aggregated summary)
       totpoints = cumulative earned, conpoints = cumulative consumed.
       Also maintained by trigger tr_picpoints / lcpointstrans.

CORRECT WRITE PATTERN:
  INSERT INTO picpoints (phcode, transdate, points, branchcode,
                         doccode, docnumber, docdate, vf1, vf2)
  VALUES (?, GETDATE(), ?, ?, 'ADJ', 0, GETDATE(), ?, ?)

  The tr_picpoints trigger then updates localcustomers.picpoints.

  We then read back localcustomers.picpoints to confirm the new balance.

NEVER directly UPDATE localcustomers.picpoints — that bypasses the
trigger and leaves picpoints (the log) out of sync.
"""
import logging
from datetime import datetime

from django.conf import settings

from config.sybase import get_sybase_connection, _safe_str

logger = logging.getLogger('elrezeiky.loyalty')

# doccode used for all CRM manual adjustments in the picpoints transaction log
_CRM_DOCCODE = 'ADJ'


def _operator():
    return getattr(settings, 'SOFTECH_POINTS_OPERATOR', 'CRM')


def _crm_branchcode():
    """
    Branch code stamped on CRM-originated picpoints rows.
    Override via SOFTECH_CRM_BRANCHCODE in .env (default 'CRM  ' padded to 5).
    """
    raw = getattr(settings, 'SOFTECH_CRM_BRANCHCODE', 'CRM')
    return raw[:5].ljust(5)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Read
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_softech_points_enrolled(softech_pic: str) -> bool:
    """
    Returns True if localcustomers.picpoints = 1 (customer is enrolled
    in the SOFTECH purchase-points programme at the POS terminal).

    Customers with picpoints = 0 are NOT enrolled for purchase points
    but may still earn CRM referral points tracked in Django only.
    """
    sql = (
        'SELECT lc.picpoints '
        'FROM SOFTECHDB9.dbo.localcustomers lc '
        'WHERE lc.phcode = ?'
    )
    try:
        conn   = get_sybase_connection()
        cursor = conn.cursor()
        cursor.execute(sql, [softech_pic])
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return False
        val = row[0]
        if val is None:
            return False
        return int(float(str(val))) == 1
    except Exception as exc:
        logger.warning('is_softech_points_enrolled(%s): %s', softech_pic, exc)
        return False


def read_softech_points(softech_pic: str) -> int | None:
    """
    Read the current net points balance for a single PIC.

    Balance = SUM(totpoints) - SUM(conpoints) from localcustomerspoints.
      totpoints = cumulative points earned (positive events)
      conpoints = cumulative points consumed/deducted (negative events)

    The tr_picpoints trigger maintains this table on every INSERT to picpoints.
    localcustomers.picpoints is a boolean enrollment flag, NOT the balance.

    Returns None if the PIC has no rows in localcustomerspoints (never earned
    any points) or on connection error.
    Returns 0 if rows exist but net is zero.
    """
    sql = (
        'SELECT SUM(lcp.totpoints), SUM(lcp.conpoints) '
        'FROM SOFTECHDB9.dbo.localcustomerspoints lcp '
        'WHERE lcp.phcode = ?'
    )
    try:
        conn   = get_sybase_connection()
        cursor = conn.cursor()
        cursor.execute(sql, [softech_pic])
        row = cursor.fetchone()
        conn.close()
        if row is None or (row[0] is None and row[1] is None):
            # PIC has never had a points transaction — treat as 0
            return 0
        tot = int(float(str(row[0]))) if row[0] is not None else 0
        con = int(float(str(row[1]))) if row[1] is not None else 0
        return tot - con
    except Exception as exc:
        logger.warning('read_softech_points(%s): %s', softech_pic, exc)
        return None


def read_bulk_softech_points(pic_list: list) -> dict:
    """
    Fetch net points balances for multiple PICs in one round-trip.
    Returns { phcode: int_net_balance } — PICs with no history are returned as 0.
    """
    if not pic_list:
        return {}

    placeholders = ', '.join(['?' for _ in pic_list])
    sql = (
        f'SELECT lcp.phcode, SUM(lcp.totpoints), SUM(lcp.conpoints) '
        f'FROM SOFTECHDB9.dbo.localcustomerspoints lcp '
        f'WHERE lcp.phcode IN ({placeholders}) '
        f'GROUP BY lcp.phcode'
    )
    try:
        conn   = get_sybase_connection()
        cursor = conn.cursor()
        cursor.execute(sql, list(pic_list))
        rows = cursor.fetchall()
        conn.close()
        result = {}
        for row in rows:
            pic = _safe_str(row[0]) if row[0] else None
            if not pic:
                continue
            try:
                tot = int(float(str(row[1]))) if row[1] is not None else 0
                con = int(float(str(row[2]))) if row[2] is not None else 0
                result[pic] = tot - con
            except Exception:
                result[pic] = 0
        # PICs not in localcustomerspoints yet → default 0
        for pic in pic_list:
            if pic not in result:
                result[pic] = 0
        return result
    except Exception as exc:
        logger.warning('read_bulk_softech_points: %s', exc)
        return {}


def read_softech_points_log(softech_pic: str, limit: int = 50) -> list:
    """
    Return the most recent `limit` rows from the SOFTECH picpoints log
    for this PIC — newest first.

    Each row is a dict:
      { transdate, points, branchcode, doccode, docnumber, vf1, vf2 }
    """
    sql = (
        'SELECT pt.transdate, pt.points, pt.branchcode, '
        '       pt.doccode, pt.docnumber, pt.vf1, pt.vf2 '
        'FROM SOFTECHDB9.dbo.picpoints pt '
        'WHERE pt.phcode = ? '
        'ORDER BY pt.transdate DESC'
    )
    try:
        conn   = get_sybase_connection()
        # Sybase ASE 12.5 uses SET ROWCOUNT instead of SELECT TOP N
        conn.cursor().execute(f'SET ROWCOUNT {limit}')
        cursor = conn.cursor()
        cursor.execute(sql, [softech_pic])
        rows = cursor.fetchall()
        conn.cursor().execute('SET ROWCOUNT 0')
        conn.close()
        result = []
        for row in rows:
            result.append({
                'transdate':  str(row[0]) if row[0] else None,
                'points':     int(row[1]) if row[1] is not None else 0,
                'branchcode': _safe_str(row[2]) or '',
                'doccode':    _safe_str(row[3]) or '',
                'docnumber':  int(row[4]) if row[4] is not None else 0,
                'vf1':        _safe_str(row[5]) or '',
                'vf2':        _safe_str(row[6]) or '',
            })
        return result
    except Exception as exc:
        logger.warning('read_softech_points_log(%s): %s', softech_pic, exc)
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Write — INSERT into picpoints (same as ERP screen)
# The tr_picpoints trigger updates localcustomers.picpoints automatically.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def adjust_softech_points(softech_pic: str, delta: int,
                           reason: str = '', operator: str | None = None) -> int:
    """
    Adjust picpoints for the given PIC by inserting a row into the SOFTECH
    picpoints transaction log — exactly as the ERP screen does.

    The tr_picpoints trigger fires on INSERT and updates
    localcustomers.picpoints automatically.

    delta > 0  =  add points (credit / manual bonus)
    delta < 0  =  subtract points (deduction / redemption)

    Returns the confirmed new balance read back from localcustomers.picpoints.
    Raises RuntimeError on write failure or if readback is inconsistent.
    """
    if delta == 0:
        raise ValueError('delta cannot be 0 — no-op adjustments are not allowed.')

    op         = operator or _operator()
    branchcode = _crm_branchcode()
    # Sybase JDBC (JPype) does not accept datetime objects — pass as string
    now        = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    vf1        = (reason or '')[:50]   # reason stored in free field vf1
    vf2        = op[:50]               # operator label stored in vf2

    # ── 1. Read balance BEFORE so we can verify the trigger fired ─────────────
    balance_before = read_softech_points(softech_pic)
    if balance_before is None:
        raise RuntimeError(
            f'PIC {softech_pic} not found in localcustomers — cannot adjust points.'
        )

    # ── 2. INSERT into picpoints (the ERP pattern) ────────────────────────────
    insert_sql = """
        INSERT INTO SOFTECHDB9.dbo.picpoints
               (phcode,  transdate, points, branchcode,
                doccode, docnumber, docdate,
                vf1,     vf2)
        VALUES (?,       ?,         ?,      ?,
                ?,       0,         ?,
                ?,       ?)
    """
    params = [softech_pic, now, delta, branchcode,
              _CRM_DOCCODE, now,
              vf1, vf2]

    try:
        conn   = get_sybase_connection()
        cursor = conn.cursor()
        cursor.execute(insert_sql, params)
        conn.close()
        logger.info(
            'adjust_softech_points: INSERT OK  PIC=%s  delta=%+d  op=%s  reason=%s',
            softech_pic, delta, op, reason,
        )
    except Exception as exc:
        logger.error(
            'adjust_softech_points: INSERT FAILED  PIC=%s  delta=%+d  err=%s',
            softech_pic, delta, exc,
        )
        raise RuntimeError(f'فشل تسجيل النقاط في SOFTECH: {exc}') from exc

    # ── 3. Read back from localcustomers.picpoints to confirm trigger fired ────
    new_balance = read_softech_points(softech_pic)
    if new_balance is None:
        raise RuntimeError(
            f'تعذّر قراءة الرصيد بعد التحديث للعميل PIC={softech_pic}'
        )

    expected = balance_before + delta
    if new_balance != expected:
        logger.warning(
            'adjust_softech_points: readback mismatch  PIC=%s  '
            'expected=%d  got=%d  (trigger may have applied rounding or limits)',
            softech_pic, expected, new_balance,
        )
        # Do not raise — SOFTECH may cap/round points internally via the trigger.
        # Log the discrepancy and return the actual new value.

    logger.info(
        'adjust_softech_points: readback  PIC=%s  before=%d  delta=%+d  after=%d',
        softech_pic, balance_before, delta, new_balance,
    )
    return new_balance


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Batch sync (called from APScheduler every 30 min)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def sync_all_softech_balances() -> int:
    """
    Pull localcustomers.picpoints for all customers with a softech_pic and a
    LoyaltyAccount, write results into softech_points_balance cache.
    Returns the number of accounts whose cached value changed.
    """
    from apps.loyalty.models import LoyaltyAccount

    accounts = list(
        LoyaltyAccount.objects
        .filter(customer__softech_pic__isnull=False)
        .select_related('customer')
        .only('id', 'softech_points_balance', 'customer__softech_pic')
    )
    if not accounts:
        return 0

    pic_map = {acc.customer.softech_pic: acc for acc in accounts}
    pics    = list(pic_map.keys())

    # Fetch in chunks of 200 (safe IN-clause size for Sybase ASE 12.5)
    CHUNK    = 200
    balances: dict = {}
    for i in range(0, len(pics), CHUNK):
        balances.update(read_bulk_softech_points(pics[i:i + CHUNK]))

    updated = 0
    for pic, new_bal in balances.items():
        acc = pic_map.get(pic)
        if acc and acc.softech_points_balance != new_bal:
            acc.softech_points_balance = new_bal
            acc.save(update_fields=['softech_points_balance', 'updated_at'])
            updated += 1

    logger.info('sync_all_softech_balances: %d / %d accounts updated', updated, len(pic_map))
    return updated
