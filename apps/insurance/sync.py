"""
apps/insurance/sync.py

Incremental sync of SOFTECHDB9.dbo.motalba and SOFTECHDB9.dbo.companiesitems
into the local PostgreSQL cache (MotalbaCache, CompaniesItemsCache).

Strategy
--------
- Initial load : last 90 days by docdate.
- Incremental  : rows whose docdate >= (max cached docdate - 2 days overlap)
                 so that any late-arriving or corrected entries are captured.
- The overlap of 2 days prevents gaps if SOFTECH back-dates corrections.
- Both tables are upserted via bulk_create(update_conflicts=True).
- invdel filter: always invdel=1 (official claim records).

Called from:
  - APScheduler (daily at 01:00 Cairo)
  - Manual API trigger: POST /api/insurance/sync-cache/
"""
import logging
import datetime as _dt

from django.db.models import Max
from django.utils import timezone

from .models import MotalbaCache, CompaniesItemsCache

logger = logging.getLogger('elrezeiky.insurance.sync')

SYNC_WINDOW_DAYS  = 90   # full window on first run
OVERLAP_DAYS      = 2    # re-sync last N days to catch late corrections
BATCH_SIZE        = 1000


# ── helpers ────────────────────────────────────────────────────────────────────

def _get_sybase():
    from config.sybase import get_sybase_connection
    return get_sybase_connection()


def _to_date(val):
    if val is None:
        return None
    if isinstance(val, _dt.datetime):
        return val.date()
    if isinstance(val, _dt.date):
        return val
    try:
        return _dt.date.fromisoformat(str(val)[:10])
    except Exception:
        return None


def _safe(val, default=''):
    if val is None:
        return default
    return str(val).strip()


def _dec(val):
    from decimal import Decimal
    if val is None:
        return Decimal('0')
    try:
        return Decimal(str(val)).quantize(Decimal('0.01'))
    except Exception:
        return Decimal('0')


# ── motalba sync ──────────────────────────────────────────────────────────────

MOTALBA_SELECT = """
    SELECT
        m.personcode,
        m.motalbano,
        m.branchcode,
        CONVERT(varchar(20), m.docnumber),
        m.docdate,
        m.motalbasdate,
        m.motalbafdate,
        m.doccode,
        m.docvalue_grandtotal,
        m.docvaluerequired,
        m.motalba_docorder,
        m.ppersoncode,
        m.patientcode,
        m.custbranchcode,
        m.usercode
    FROM SOFTECHDB9.dbo.motalba m
    WHERE m.invdel = 1
      AND m.docdate >= ?
    ORDER BY m.docdate, m.motalbano, m.motalba_docorder
"""


def sync_motalba(conn=None) -> dict:
    """
    Sync motalba (invdel=1) rows into MotalbaCache.
    Returns stats dict: {fetched, upserted, from_date}.
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_sybase()

    # Determine sync window
    latest = MotalbaCache.objects.aggregate(d=Max('docdate'))['d']
    if latest:
        from_date = latest - _dt.timedelta(days=OVERLAP_DAYS)
    else:
        from_date = _dt.date.today() - _dt.timedelta(days=SYNC_WINDOW_DAYS)

    logger.info('[motalba-sync] Fetching from %s', from_date)

    cursor = conn.cursor()
    cursor.execute(MOTALBA_SELECT, [from_date.strftime('%Y-%m-%d')])
    rows = cursor.fetchall()

    logger.info('[motalba-sync] Fetched %d rows from Sybase', len(rows))

    objs = []
    for r in rows:
        try:
            objs.append(MotalbaCache(
                personcode          = _safe(r[0]),
                motalbano           = int(r[1]) if r[1] is not None else 0,
                branchcode          = _safe(r[2]),
                docnumber           = _safe(r[3]),
                docdate             = _to_date(r[4]),
                motalbasdate        = _to_date(r[5]),
                motalbafdate        = _to_date(r[6]),
                doccode             = _safe(r[7]),
                docvalue_grandtotal = _dec(r[8]),
                docvaluerequired    = _dec(r[9]),
                motalba_docorder    = int(r[10]) if r[10] is not None else 0,
                ppersoncode         = _safe(r[11]),
                patientcode         = int(r[12]) if r[12] is not None else None,
                custbranchcode      = _safe(r[13]),
                usercode            = _safe(r[14]),
            ))
        except Exception as exc:
            logger.warning('[motalba-sync] Row build error: %s', exc)

    upserted = 0
    for i in range(0, len(objs), BATCH_SIZE):
        batch = objs[i: i + BATCH_SIZE]
        MotalbaCache.objects.bulk_create(
            batch,
            update_conflicts=True,
            unique_fields=['personcode', 'motalbano', 'branchcode', 'docnumber', 'doccode'],
            update_fields=[
                'docdate', 'motalbasdate', 'motalbafdate',
                'docvalue_grandtotal', 'docvaluerequired',
                'motalba_docorder', 'ppersoncode', 'patientcode',
                'custbranchcode', 'usercode', 'synced_at',
            ],
            batch_size=BATCH_SIZE,
        )
        upserted += len(batch)

    if close_conn:
        conn.close()

    logger.info('[motalba-sync] Done — %d rows upserted (from %s)', upserted, from_date)
    return {'fetched': len(rows), 'upserted': upserted, 'from_date': str(from_date)}


# ── companiesitems sync ───────────────────────────────────────────────────────

COMPANIESITEMS_SELECT = """
    SELECT
        ci.branchcode,
        CONVERT(varchar(20), ci.docnumber),
        ci.doccode,
        ci.docdate,
        ci.patientname,
        ci.patientno,
        ci.financialno,
        ci.fileno,
        ci.roshettano,
        ci.membershipno,
        ci.deptname,
        ci.relativedegree,
        ci.hi_typecode,
        ci.examdate
    FROM SOFTECHDB9.dbo.companiesitems ci
    WHERE ci.docdate >= ?
    ORDER BY ci.docdate, ci.branchcode
"""


def sync_companiesitems(conn=None) -> dict:
    """
    Sync companiesitems rows into CompaniesItemsCache.
    Returns stats dict.
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_sybase()

    latest = CompaniesItemsCache.objects.aggregate(d=Max('docdate'))['d']
    if latest:
        from_date = latest - _dt.timedelta(days=OVERLAP_DAYS)
    else:
        from_date = _dt.date.today() - _dt.timedelta(days=SYNC_WINDOW_DAYS)

    logger.info('[ci-sync] Fetching companiesitems from %s', from_date)

    cursor = conn.cursor()
    cursor.execute(COMPANIESITEMS_SELECT, [from_date.strftime('%Y-%m-%d')])
    rows = cursor.fetchall()

    logger.info('[ci-sync] Fetched %d rows', len(rows))

    objs = []
    for r in rows:
        try:
            objs.append(CompaniesItemsCache(
                branchcode     = _safe(r[0]),
                docnumber      = _safe(r[1]),
                doccode        = _safe(r[2]),
                docdate        = _to_date(r[3]),
                patientname    = _safe(r[4]),
                patientno      = _safe(r[5]),
                financialno    = _safe(r[6]),
                fileno         = _safe(r[7]),
                roshettano     = _safe(r[8]),
                membershipno   = _safe(r[9]),
                deptname       = _safe(r[10]),
                relativedegree = _safe(r[11]),
                hi_typecode    = _safe(r[12]),
                examdate       = _to_date(r[13]),
            ))
        except Exception as exc:
            logger.warning('[ci-sync] Row build error: %s', exc)

    upserted = 0
    for i in range(0, len(objs), BATCH_SIZE):
        batch = objs[i: i + BATCH_SIZE]
        CompaniesItemsCache.objects.bulk_create(
            batch,
            update_conflicts=True,
            unique_fields=['branchcode', 'docnumber', 'doccode'],
            update_fields=[
                'docdate', 'patientname', 'patientno', 'financialno',
                'fileno', 'roshettano', 'membershipno', 'deptname',
                'relativedegree', 'hi_typecode', 'examdate', 'synced_at',
            ],
            batch_size=BATCH_SIZE,
        )
        upserted += len(batch)

    if close_conn:
        conn.close()

    logger.info('[ci-sync] Done — %d rows upserted (from %s)', upserted, from_date)
    return {'fetched': len(rows), 'upserted': upserted, 'from_date': str(from_date)}


# ── combined entry point ──────────────────────────────────────────────────────

def sync_insurance_cache() -> dict:
    """
    Sync both motalba and companiesitems caches in one Sybase connection.
    Called by APScheduler and the manual sync API endpoint.
    """
    try:
        conn = _get_sybase()
        motalba_stats = sync_motalba(conn)
        ci_stats      = sync_companiesitems(conn)
        conn.close()
        return {
            'status':       'ok',
            'motalba':      motalba_stats,
            'companiesitems': ci_stats,
            'synced_at':    timezone.now().isoformat(),
        }
    except Exception as exc:
        logger.error('[insurance-cache-sync] Failed: %s', exc, exc_info=True)
        return {'status': 'error', 'error': str(exc)}
