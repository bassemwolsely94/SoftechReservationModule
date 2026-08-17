"""
apps/insurance/importer.py

Pulls prescriptions from Softech and freezes them into the PostgreSQL snapshot.

Two import paths (confirmed from schema inspection 2026-06-02):

  PATH A — by motalbano (preferred):
    1. Query motalbas WHERE motalbano=? → header (personcode, dates, totals)
    2. Query motalba  WHERE motalbano=? → all prescription docnumbers
    3. For each docnumber: fetch stktrans lines with item classification
    4. Classify local/imported/tarsia, apply contract discounts
    5. Freeze snapshot into InsuranceClaimPrescription + InsuranceClaimLine
    6. Update InsuranceClaim totals

  PATH B — by personcode + date range (fallback when motalbano unknown):
    Same as A but queries motalba by personcode+date range.

Patient name resolution:
  motalba.ppersoncode → localcustomers.phcode → branchcustname
  Fallback: personsdata.personcode → personname
"""
import logging
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    InsuranceClaim, InsuranceClaimPrescription, InsuranceClaimLine,
    InsuranceClaimAdjustment, InsuranceClaimExclusion,
    ITEM_CATEGORY_LOCAL,
)
from .classifier import (
    classify_item, aggregate_prescription_totals, calculate_line_discount,
    load_classification_overrides,
)
from .sybase_queries import (
    QUERY_MOTALBA_HEADER_FROM_DETAIL,
    QUERY_MOTALBA_LINES_BY_NO,
    QUERY_MOTALBA_LINES_BY_PERSONCODE_DATERANGE,
    QUERY_PRESCRIPTION_LINES_CLASSIFIED,
    QUERY_ALL_MOTALBA_LINES_CLASSIFIED,
    QUERY_PATIENT_NAME_BY_PHCODE,
    QUERY_PATIENT_NAME_FROM_PERSONSDATA,
    QUERY_PRESCRIPTION_HEADER_BY_DOCNO,
    QUERY_PRESCRIPTION_HEADER_BY_DOCNO_BRANCH,
    QUERY_CHECK_DOC_IN_MOTALBA_BRANCH,
    QUERY_CHECK_DOC_IN_MOTALBA,
    QUERY_CUSTDISCOUNTS_BY_PERSONCODE,
)

logger = logging.getLogger('elrezeiky.insurance')


class InsuranceImportError(Exception):
    pass


def _get_connection():
    from config.sybase import get_sybase_connection
    return get_sybase_connection()


def _safe(val, default=''):
    if val is None:
        return default
    if isinstance(val, str):
        return val.strip()
    return val


def _to_decimal(val, default=Decimal('0')) -> Decimal:
    if val is None:
        return default
    try:
        return Decimal(str(val)).quantize(Decimal('0.01'))
    except Exception:
        return default


def _to_qty(val, default=Decimal('1')) -> Decimal:
    """
    Quantity at FULL precision — never round before multiplying by the price.

    SOFTECH stores fractional pack quantities like 0.66667 (40 of a 60-tab pack);
    rounding to 2dp (0.67) and then ×price inflates the line total (e.g. JUSPRIN
    81 × 0.67 = 54.27 instead of 81 × 0.66667 = 54.00), which is exactly the
    drift away from the finance team's Power-Query figures.
    """
    if val is None:
        return default
    try:
        return Decimal(str(val))
    except Exception:
        return default


def _to_date(val) -> date | None:
    if val is None:
        return None
    # Check callable .date() FIRST — datetime is a subclass of date, so the
    # plain isinstance(val, date) branch would return a datetime unchanged,
    # which DRF DateField refuses to serialise.
    if hasattr(val, 'date') and callable(val.date):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val)[:10])
    except Exception:
        return None


def _to_int(val, default=0) -> int:
    if val is None:
        return default
    try:
        return int(str(val).split('.')[0])
    except Exception:
        return default


# ── Discount-rate reader from custdiscounts ───────────────────────────────────

# custdiscpcode → category sets — single source of truth in classifier.py
from .classifier import (
    DEFAULT_LOCAL_CODES as _LOCAL_CODES,
    DEFAULT_IMPORTED_CODES as _IMPORTED_CODES,
    DEFAULT_TARSIA_CLASSIF_CODES as _TARSIA_CODES,
)


def read_discount_rates(conn, personcode: str) -> tuple[Decimal, Decimal, Decimal]:
    """
    Read per-category contract discount rates from custdiscounts for a personcode.
    Returns (local_pct, imported_pct, tarsia_pct) as Decimals.

    Strategy:
    - Collect all custdiscp values for LOCAL, IMPORTED, TARSIA codes.
    - Take the MAX non-zero rate per category (handles clients that have
      multiple codes for the same category with the same rate).
    - Tarsia is always 0% in practice (confirmed from all clients inspected).
    """
    local_rates    = []
    imported_rates = []
    tarsia_rates   = []

    try:
        cursor = conn.cursor()
        cursor.execute(QUERY_CUSTDISCOUNTS_BY_PERSONCODE, [personcode])
        for row in cursor.fetchall():
            code  = str(row[0] or '').strip()
            rate  = _to_decimal(row[1])
            allow = row[6]   # allow_sell flag
            if allow != 1:
                continue
            if code in _LOCAL_CODES:
                local_rates.append(rate)
            elif code in _IMPORTED_CODES:
                imported_rates.append(rate)
            elif code in _TARSIA_CODES:
                tarsia_rates.append(rate)
    except Exception as exc:
        logger.warning('read_discount_rates failed for personcode=%s: %s', personcode, exc)

    local_pct    = max(local_rates,    default=Decimal('0'))
    imported_pct = max(imported_rates, default=Decimal('0'))
    tarsia_pct   = max(tarsia_rates,   default=Decimal('0'))

    logger.info(
        'Discount rates for personcode=%s: local=%.1f%% imported=%.1f%% tarsia=%.1f%%',
        personcode, local_pct, imported_pct, tarsia_pct,
    )
    return local_pct, imported_pct, tarsia_pct


def _signed_dgt(dgt: Decimal | None, dvr: Decimal | None, doccode: str) -> tuple[Decimal, Decimal]:
    """
    Apply sign correction for motalba returns.

    SOFTECH stores docvalue_grandtotal (gross) and docvaluerequired (net) as
    POSITIVE values for both sales (doccode=115) and returns (doccode=30).
    SOFTECH's printed claim shows returns as NEGATIVE amounts.

    Returns (gross, net) with the correct sign.
    """
    gross = _to_decimal(dgt)
    net   = _to_decimal(dvr)
    if str(doccode).strip() == '30':   # return prescription
        gross = -gross
        net   = -net
    return gross, net


# ── Patient name cache ─────────────────────────────────────────────────────────

_patient_name_cache: dict[str, str] = {}


def resolve_patient_name(cursor, ppersoncode: str) -> str:
    """
    Resolve patient name from motalba.ppersoncode.
    Tries localcustomers.phcode first, then personsdata.
    """
    if not ppersoncode:
        return ''
    code = ppersoncode.strip()
    if code in _patient_name_cache:
        return _patient_name_cache[code]

    name = ''
    # Path 1: localcustomers (retail patients)
    try:
        cursor.execute(QUERY_PATIENT_NAME_BY_PHCODE, [code])
        row = cursor.fetchone()
        if row and row[0]:
            name = _safe(row[0])
    except Exception as e:
        logger.debug('localcustomers lookup failed for ppersoncode=%s: %s', code, e)

    # Path 2: personsdata (institutional patients)
    if not name:
        try:
            cursor.execute(QUERY_PATIENT_NAME_FROM_PERSONSDATA, [code])
            row = cursor.fetchone()
            if row and row[0]:
                name = _safe(row[0])
        except Exception as e:
            logger.debug('personsdata lookup failed for ppersoncode=%s: %s', code, e)

    _patient_name_cache[code] = name
    return name


# ── Fast batch line-fetch (50 docnumbers per query, no stktransm join) ─────────

BATCH_SIZE = 50  # docnumbers per Sybase query


def _zero_totals_dict() -> dict:
    z = Decimal('0')
    return {
        'local_before': z, 'imported_before': z, 'tarsia_before': z,
        'gross_before': z, 'local_discount': z, 'imported_discount': z,
        'tarsia_discount': z, 'total_discount': z, 'net_after': z,
    }


def _fetch_lines_batch(
    conn,
    prescriptions: list[tuple[str, str, Decimal]],  # [(docnumber, branchcode_raw, dgt), ...]
    local_disc: Decimal,
    imported_disc: Decimal,
    tarsia_disc: Decimal,
    tarsia_classif_codes: set | None,
) -> dict[str, tuple[list[dict], dict, str]]:
    """
    Fetch item lines for up to BATCH_SIZE prescriptions in one Sybase query.
    stktrans + stktransm (for sm.branchcustname) + items + itemsorigin + custdiscpclassif.
    No localcustomers — patient name comes from stktransm.branchcustname directly.
    Branchcode NOT in WHERE (prevents index use) — filtered in Python instead.
    Retries with a fresh connection if the passed one is dead.
    """
    from collections import defaultdict
    from .sybase_queries import QUERY_ITEM_LINES_DOCNOS_TEMPLATE

    if not prescriptions:
        return {}

    docno_filter = ' OR '.join(
        'st.docnumber = CONVERT(numeric(6), ?)'
        for _ in prescriptions
    )
    sql    = QUERY_ITEM_LINES_DOCNOS_TEMPLATE.format(docno_filter=docno_filter)
    params = [docno for docno, _, _dgt in prescriptions]
    branch_map = {docno: branch.strip() for docno, branch, _dgt in prescriptions}
    dgt_map    = {docno: dgt           for docno, _branch, dgt in prescriptions}

    result: dict[str, tuple[list[dict], dict, str]] = {}

    # Attempt with passed connection, then retry with fresh one if it's dead
    rows = None
    for attempt, use_conn in enumerate([conn, None]):
        try:
            if use_conn is None:
                use_conn = _get_connection()
            cursor = use_conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            break
        except Exception as e:
            if attempt == 0:
                logger.warning('Batch attempt 1 failed, retrying with fresh connection: %s', e)
            else:
                logger.warning('Batch line fetch failed after retry (%d prescriptions): %s',
                               len(prescriptions), e)
                for docno, _, _dgt in prescriptions:
                    result[docno] = ([], _zero_totals_dict(), '')
                return result

    grouped: dict[str, list] = defaultdict(list)
    for row in rows or []:
        doc_key    = str(_to_int(row[0])) if row[0] else ''
        row_branch = _safe(row[1])
        expected   = branch_map.get(doc_key, '')
        if doc_key and (not expected or row_branch == expected):
            grouped[doc_key].append(row)

    overrides = load_classification_overrides()
    for docno, _, dgt in prescriptions:
        result[docno] = _classify_lean_rows(
            grouped.get(docno, []),
            local_disc, imported_disc, tarsia_disc, tarsia_classif_codes,
            docvalue_grandtotal=dgt,
            overrides=overrides,
        )
    return result


def _classify_lean_rows(
    rows: list,
    local_disc: Decimal,
    imported_disc: Decimal,
    tarsia_disc: Decimal,
    tarsia_classif_codes: set | None,
    docvalue_grandtotal: Decimal | None = None,
    overrides: dict | None = None,
) -> tuple[list[dict], dict, str]:
    """
    Classify rows from QUERY_ITEM_LINES_DOCNOS_TEMPLATE.
    Columns: [0]=docnumber, [1]=branchcode, [2]=itemcode, [3]=itemname,
             [4]=transqty, [5]=transprice (insurance unit), [6]=transprice_total (insurance),
             [7]=importedorigin, [8]=itemstoreclassif, [9]=itemorigincode,
             [10]=custdiscpdescr, [11]=itemsaleprice (PUBLIC unit price),
             [12]=lc.branchcustname (patient name — present for ~66% of prescriptions)

    line_total = itemsaleprice × transqty = PUBLIC price (سعر الجمهور before discount).
    Patient name: from localcustomers.branchcustname via stktransm.phcode.
    """
    if overrides is None:
        overrides = load_classification_overrides()
    patient_name = ''
    classified_lines = []
    for lr in rows:
        imported_origin  = _safe(lr[7])
        store_classif    = _safe(lr[8])
        transqty         = _to_qty(lr[4])
        itemsaleprice    = _to_decimal(lr[11])
        line_total_public = (itemsaleprice * transqty).quantize(Decimal('0.01'))

        # Patient name from localcustomers.branchcustname (first non-empty)
        if not patient_name and len(lr) > 12 and lr[12]:
            patient_name = _safe(lr[12])

        category = classify_item(
            imported_origin=imported_origin,
            store_classif=store_classif,
            tarsia_codes=tarsia_classif_codes,
            item_code=_safe(lr[2]),
            overrides=overrides,
        )
        classified_lines.append({
            'itemcode':      _safe(lr[2]),
            'item_name':     _safe(lr[3]),
            'quantity':      transqty,
            'unit_price':    itemsaleprice,
            'line_total':    line_total_public,
            'category':      category,
            'origin_code':   _safe(lr[9]),
            'imported_flag': imported_origin == '1',
            'store_classif': store_classif,
        })

    totals = aggregate_prescription_totals(
        classified_lines, local_disc, imported_disc, tarsia_disc,
        docvalue_grandtotal=docvalue_grandtotal,
    )
    return classified_lines, totals, patient_name


# ── Core line-fetch + classify ─────────────────────────────────────────────────

def _fetch_and_classify_lines(
    cursor,
    docnumber: str,
    branchcode: str,
    local_disc: Decimal,
    imported_disc: Decimal,
    tarsia_disc: Decimal,
    tarsia_classif_codes: set | None,
    docvalue_grandtotal: Decimal | None = None,
    docvalue_required: Decimal | None = None,
    overrides: dict | None = None,
) -> tuple[list[dict], dict, str]:
    """
    Fetch item lines for one prescription, classify them, and extract patient name.

    Returns (classified_lines, totals_dict, patient_name).

    Column layout from QUERY_PRESCRIPTION_LINES_CLASSIFIED:
      [0] itemcode, [1] itemname, [2] qty, [3] price, [4] total,
      [5] importedorigin, [6] itemstoreclassif, [7] itemorigincode,
      [8] custdiscpdescr, [9] phcode, [10] branchcustname (patient name)
    """
    if overrides is None:
        overrides = load_classification_overrides()
    try:
        cursor.execute(QUERY_PRESCRIPTION_LINES_CLASSIFIED, [docnumber, branchcode])
        line_rows = cursor.fetchall()
    except Exception as e:
        # A dead/closed connection must PROPAGATE so the caller can reconnect and
        # retry — swallowing it here silently corrupts the prescription (empty
        # lines → fallback totals).  Only genuine per-row errors are tolerated.
        msg = str(e)
        if ('Connection is already closed' in msg or 'ConnectionDead' in msg
                or 'JZ0C0' in msg or 'JZ006' in msg or 'closed' in msg.lower()):
            raise
        logger.warning('Could not fetch lines for docnumber=%s branch=%s: %s', docnumber, branchcode, e)
        line_rows = []

    # QUERY_PRESCRIPTION_LINES_CLASSIFIED column layout:
    # [0]=itemcode, [1]=itemname, [2]=transqty, [3]=transprice (insurance unit),
    # [4]=transprice_total (insurance total — not used for calc),
    # [5]=importedorigin, [6]=itemstoreclassif, [7]=itemorigincode,
    # [8]=custdiscpdescr, [9]=phcode, [10]=itemsaleprice (PUBLIC unit price),
    # [11]=lc.branchcustname (patient name — NULL when phcode not in localcustomers)
    patient_name = ''
    classified_lines = []
    for lr in line_rows:
        imported_origin = _safe(lr[5])
        store_classif   = _safe(lr[6])
        transqty        = _to_qty(lr[2])
        itemsaleprice   = _to_decimal(lr[10])
        line_total      = (itemsaleprice * transqty).quantize(Decimal('0.01'))

        if not patient_name and len(lr) > 11 and lr[11]:
            patient_name = _safe(lr[11])

        category = classify_item(
            imported_origin=imported_origin,
            store_classif=store_classif,
            tarsia_codes=tarsia_classif_codes,
            item_code=_safe(lr[0]),
            overrides=overrides,
        )
        classified_lines.append({
            'itemcode':      _safe(lr[0]),
            'item_name':     _safe(lr[1]),
            'quantity':      transqty,
            'unit_price':    itemsaleprice,
            'line_total':    line_total,
            'category':      category,
            'origin_code':   _safe(lr[7]),
            'imported_flag': imported_origin == '1',
            'store_classif': store_classif,
        })

    totals = aggregate_prescription_totals(
        classified_lines, local_disc, imported_disc, tarsia_disc,
        docvalue_grandtotal=docvalue_grandtotal,
        docvalue_required=docvalue_required,
    )
    return classified_lines, totals, patient_name


def _classify_prefetched_lines(
    line_rows: list,
    local_disc: Decimal,
    imported_disc: Decimal,
    tarsia_disc: Decimal,
    tarsia_classif_codes: set | None,
    overrides: dict | None = None,
) -> tuple[list[dict], dict, str]:
    """
    Classify a list of pre-fetched item rows (from QUERY_ALL_MOTALBA_LINES_CLASSIFIED).
    Same output contract as _fetch_and_classify_lines but uses rows already in memory.

    Column layout (columns 1-11 of the batch query, i.e. row[1]..row[11]):
      [1] itemcode, [2] itemname, [3] qty, [4] price, [5] total,
      [6] importedorigin, [7] itemstoreclassif, [8] itemorigincode,
      [9] custdiscpdescr, [10] phcode, [11] branchcustname (patient name)
    """
    if overrides is None:
        overrides = load_classification_overrides()
    patient_name = ''
    classified_lines = []
    for lr in line_rows:
        imported_origin = _safe(lr[6])
        store_classif   = _safe(lr[7])
        line_total      = _to_decimal(lr[5])

        if not patient_name and lr[11]:
            patient_name = _safe(lr[11])

        category = classify_item(
            imported_origin=imported_origin,
            store_classif=store_classif,
            tarsia_codes=tarsia_classif_codes,
            item_code=_safe(lr[1]),
            overrides=overrides,
        )
        classified_lines.append({
            'itemcode':      _safe(lr[1]),
            'item_name':     _safe(lr[2]),
            'quantity':      _to_decimal(lr[3], Decimal('1')),
            'unit_price':    _to_decimal(lr[4]),
            'line_total':    line_total,
            'category':      category,
            'origin_code':   _safe(lr[8]),
            'imported_flag': imported_origin == '1',
            'store_classif': store_classif,
        })

    totals = aggregate_prescription_totals(classified_lines, local_disc, imported_disc, tarsia_disc)
    return classified_lines, totals, patient_name


def _write_prescription_snapshot(
    claim: InsuranceClaim,
    seq: int,
    docnumber: str,
    docdate: date,
    branchcode: str,
    personcode: str,
    patient_name: str,
    classified_lines: list[dict],
    totals: dict,
    local_disc: Decimal,
    imported_disc: Decimal,
    tarsia_disc: Decimal,
) -> InsuranceClaimPrescription:
    """Create one frozen InsuranceClaimPrescription + its InsuranceClaimLine records."""
    rx = InsuranceClaimPrescription.objects.create(
        claim              = claim,
        softech_docnumber  = docnumber,
        softech_docdate    = docdate,
        softech_branchcode = branchcode,
        softech_personcode = personcode,
        patient_name       = patient_name,
        sequence           = seq,
        local_before       = totals['local_before'],
        imported_before    = totals['imported_before'],
        tarsia_before      = totals['tarsia_before'],
        gross_before       = totals['gross_before'],
        local_discount     = totals['local_discount'],
        imported_discount  = totals['imported_discount'],
        tarsia_discount    = totals['tarsia_discount'],
        total_discount     = totals['total_discount'],
        net_after          = totals['net_after'],
        softech_net        = totals.get('softech_net'),
    )

    line_objs = []
    for cl in classified_lines:
        disc_pct = (
            local_disc    if cl['category'] == ITEM_CATEGORY_LOCAL
            else imported_disc if cl['category'] == 'imported'
            else tarsia_disc
        )
        disc_amt, net_amt = calculate_line_discount(
            cl['category'], cl['line_total'], local_disc, imported_disc, tarsia_disc,
        )
        line_objs.append(InsuranceClaimLine(
            prescription          = rx,
            softech_itemcode      = cl['itemcode'],
            item_name             = cl['item_name'],
            item_category         = cl['category'],
            softech_origin_code   = cl['origin_code'],
            softech_imported_flag = cl['imported_flag'],
            softech_store_classif = cl['store_classif'],
            quantity              = cl['quantity'],
            unit_price            = cl['unit_price'],
            line_total            = cl['line_total'],
            discount_pct          = disc_pct,
            discount_amt          = disc_amt,
            net_amount            = net_amt,
        ))
    if line_objs:
        InsuranceClaimLine.objects.bulk_create(line_objs)

    return rx


# ═══════════════════════════════════════════════════════════════════════════════
# PATH A — Import by Motalba Number (PREFERRED)
# ═══════════════════════════════════════════════════════════════════════════════

def import_claim_by_motalbano(
    claim: InsuranceClaim,
    motalbano: int,
    tarsia_classif_codes: set | None = None,
    user=None,
) -> dict:
    """Import all prescriptions from the Softech motalba with the given motalbano."""
    return import_claim_by_motalbano_batch(claim, motalbano, tarsia_classif_codes, user)


def import_claim_by_motalbano_batch(
    claim: InsuranceClaim,
    motalbano: int,
    tarsia_classif_codes: set | None = None,
    user=None,
) -> dict:
    """
    Import a Softech motalba into a frozen InsuranceClaim snapshot.

    Strategy (two Sybase round-trips per prescription):
      1. QUERY_MOTALBA_HEADER_FROM_DETAIL  → period dates, rx count
      2. QUERY_MOTALBA_LINES_BY_NO         → list of (docnumber, branchcode, date …)
      3. For each prescription:
           QUERY_PRESCRIPTION_LINES_CLASSIFIED → item lines, patient name
           (uses docnumber+branchcode index → fast per-Rx query)

    This avoids the massive 5-table JOIN in QUERY_ALL_MOTALBA_LINES_CLASSIFIED
    which causes full table scans on stktrans (~millions of rows) and hangs.
    """
    _patient_name_cache.clear()

    try:
        conn = _get_connection()
    except Exception as e:
        raise InsuranceImportError(f'فشل الاتصال بسوفتك: {e}') from e

    cursor = conn.cursor()

    # Step 1: Resolve personcode — motalbano is NOT unique across personcodes
    personcodes = claim.subclient.get_all_personcodes()
    if not personcodes:
        raise InsuranceImportError('لا يوجد كود عميل في سوفتك لهذه الفئة')

    softech_personcode = None
    header = None
    for pc in personcodes:
        try:
            cursor.execute(QUERY_MOTALBA_HEADER_FROM_DETAIL, [pc, motalbano])
            row = cursor.fetchone()
            if row and row[2] is not None:
                softech_personcode = pc
                header = row
                break
        except Exception as e:
            logger.warning('Header query failed for personcode=%s motalbano=%d: %s', pc, motalbano, e)
            cursor = conn.cursor()

    if not header or not softech_personcode:
        raise InsuranceImportError(
            f'لم يتم العثور على مطالبة رقم {motalbano} في سوفتك '
            f'لأي من الأكواد {personcodes}.'
        )

    period_from = _to_date(header[2]) or claim.period_from
    period_to   = _to_date(header[3]) or claim.period_to

    # Step 2: Fetch prescription headers
    cursor = conn.cursor()
    try:
        cursor.execute(QUERY_MOTALBA_LINES_BY_NO, [softech_personcode, motalbano])
        prescription_rows = cursor.fetchall()
    except Exception as e:
        raise InsuranceImportError(f'فشل استرجاع بنود المطالبة {motalbano}: {e}') from e

    if not prescription_rows:
        raise InsuranceImportError(
            f'المطالبة رقم {motalbano} ليس بها روشتات نشطة (invdel=0).'
        )

    logger.info('Insurance import: motalbano=%d personcode=%s — %d prescriptions',
                motalbano, softech_personcode, len(prescription_rows))

    # ── Auto-read discount rates from custdiscounts (overrides manual entry) ────
    auto_local, auto_imported, auto_tarsia = read_discount_rates(conn, softech_personcode)
    local_disc    = auto_local    if auto_local    > 0 else Decimal(str(claim.applied_local_disc_pct    or 0))
    imported_disc = auto_imported if auto_imported > 0 else Decimal(str(claim.applied_imported_disc_pct or 0))
    tarsia_disc   = auto_tarsia   if auto_tarsia   > 0 else Decimal(str(claim.applied_tarsia_disc_pct   or 0))

    with transaction.atomic():
        InsuranceClaimPrescription.objects.filter(claim=claim).delete()

        if period_from and period_from != claim.period_from:
            claim.period_from = period_from
        if period_to and period_to != claim.period_to:
            claim.period_to = period_to
        claim.softech_motalba_no         = str(motalbano)
        claim.imported_personcodes       = softech_personcode
        # Persist the auto-read rates onto the claim
        claim.applied_local_disc_pct     = local_disc
        claim.applied_imported_disc_pct  = imported_disc
        claim.applied_tarsia_disc_pct    = tarsia_disc

        claim_local = claim_imported = claim_tarsia = Decimal('0')
        claim_gross = claim_discount = claim_net   = Decimal('0')
        rx_count    = 0
        seen_docnumbers: set[str] = set()
        # Track the actual receipt-date range (motalba.docdate = dispense date)
        # so the claim period mirrors SOFTECH instead of the manually-entered
        # motalbasdate/motalbafdate boundaries.
        receipt_min = receipt_max = None

        for _i, prx_row in enumerate(prescription_rows):
            # Proactively refresh the Sybase connection every 100 prescriptions —
            # a single connection processing thousands of line queries gets dropped
            # by the server mid-run (SybConnectionDeadException) on large motalbas.
            if _i and _i % 100 == 0:
                try:
                    conn = _get_connection()
                except Exception as _re:
                    logger.warning('Periodic reconnect failed at #%d: %s', _i, _re)

            branchcode_raw = prx_row[2] if prx_row[2] is not None else ''
            branchcode     = branchcode_raw.strip() if isinstance(branchcode_raw, str) else str(branchcode_raw)
            docnumber      = str(_to_int(prx_row[3])) if prx_row[3] else ''
            docdate        = _to_date(prx_row[4]) or period_from
            doccode        = str(prx_row[5] or '').strip()

            if docdate:
                receipt_min = docdate if receipt_min is None else min(receipt_min, docdate)
                receipt_max = docdate if receipt_max is None else max(receipt_max, docdate)

            if not docnumber or docnumber in seen_docnumbers:
                continue
            seen_docnumbers.add(docnumber)

            # Apply sign: docvalue_grandtotal (gross) and docvaluerequired (net)
            # are stored as POSITIVE in SOFTECH for both sales and returns.
            # Returns (doccode=30) must be negated to correctly reduce the total.
            # prx_row[7]  = docvalue_grandtotal (gross at public price)
            # prx_row[11] = docvaluerequired    (net after contract discount)
            dgt, dvr = _signed_dgt(prx_row[7], prx_row[11], doccode)

            try:
                line_cursor = conn.cursor()
                classified_lines, totals, patient_name = _fetch_and_classify_lines(
                    line_cursor, docnumber, branchcode_raw,
                    local_disc, imported_disc, tarsia_disc, tarsia_classif_codes,
                    docvalue_grandtotal=dgt,
                    docvalue_required=dvr,
                )
            except Exception as e:
                logger.warning('Line fetch failed docnumber=%s, retrying with fresh conn: %s',
                               docnumber, e)
                try:
                    conn = _get_connection()
                    line_cursor = conn.cursor()
                    classified_lines, totals, patient_name = _fetch_and_classify_lines(
                        line_cursor, docnumber, branchcode_raw,
                        local_disc, imported_disc, tarsia_disc, tarsia_classif_codes,
                        docvalue_grandtotal=dgt,
                        docvalue_required=dvr,
                    )
                except Exception as e2:
                    # If the connection is STILL dead after a reconnect+retry, fail
                    # the whole claim rather than silently corrupting it with empty
                    # lines (the reimport command marks it failed, not FIXED).
                    msg2 = str(e2)
                    if ('Connection is already closed' in msg2 or 'ConnectionDead' in msg2
                            or 'JZ0C0' in msg2 or 'JZ006' in msg2):
                        raise InsuranceImportError(
                            f'انقطع الاتصال بسوفتك أثناء استيراد الفاتورة {docnumber} — '
                            f'أعد المحاولة: {e2}'
                        ) from e2
                    logger.warning('Line fetch failed after retry docnumber=%s: %s', docnumber, e2)
                    classified_lines, totals, patient_name = [], _zero_totals_dict(), ''

            rx_count += 1
            _write_prescription_snapshot(
                claim=claim, seq=rx_count,
                docnumber=docnumber, docdate=docdate,
                branchcode=branchcode,
                personcode=softech_personcode,
                patient_name=patient_name,
                classified_lines=classified_lines, totals=totals,
                local_disc=local_disc, imported_disc=imported_disc, tarsia_disc=tarsia_disc,
            )

            claim_local    += totals['local_before']
            claim_imported += totals['imported_before']
            claim_tarsia   += totals['tarsia_before']
            claim_gross    += totals['gross_before']
            claim_discount += totals['total_discount']
            claim_net      += totals['net_after']

        # Override the claim period with the actual receipt-date range
        # (SOFTECH groups its motalba daily report by docdate, not by the
        # manually-entered motalbasdate/motalbafdate header fields).
        if receipt_min:
            claim.period_from = receipt_min
        if receipt_max:
            claim.period_to = receipt_max

        _save_claim_totals(claim, rx_count, claim_local, claim_imported, claim_tarsia,
                           claim_gross, claim_discount, claim_net, user)

        # Enrich with companiesitems metadata from the local cache (non-fatal)
        try:
            enrich_prescriptions_from_cache(claim)
        except Exception as enrich_err:
            logger.warning('Enrichment failed (non-fatal): %s', enrich_err)

    logger.info('Import complete: motalbano=%d rx=%d net=%.2f', motalbano, rx_count, float(claim_net))
    return _summary(rx_count, claim_local, claim_imported, claim_tarsia, claim_gross, claim_net)


# ═══════════════════════════════════════════════════════════════════════════════
# PATH B — Import by personcode + date range (fallback)
# ═══════════════════════════════════════════════════════════════════════════════

def import_claim_from_softech(
    claim: InsuranceClaim,
    personcodes: list[str],
    period_from: date,
    period_to: date,
    branchcodes: list[str] | None = None,
    tarsia_classif_codes: set | None = None,
    user=None,
) -> dict:
    """
    Import by personcode + date range using the motalba table.
    Fetches all motalba lines for the given personcodes within the date range.
    Does NOT require knowing the motalbano.
    """
    _patient_name_cache.clear()

    try:
        conn = _get_connection()
    except Exception as e:
        raise InsuranceImportError(f'فشل الاتصال بسوفتك: {e}') from e

    cursor = conn.cursor()

    local_disc    = Decimal(str(claim.applied_local_disc_pct    or 0))
    imported_disc = Decimal(str(claim.applied_imported_disc_pct or 0))
    tarsia_disc   = Decimal(str(claim.applied_tarsia_disc_pct   or 0))

    period_from_str = period_from.strftime('%Y-%m-%d')
    period_to_str   = period_to.strftime('%Y-%m-%d')

    # Collect all motalba lines for all personcodes
    all_lines: list[tuple] = []
    seen_docnumbers: set[str] = set()

    for personcode in personcodes:
        try:
            cursor.execute(
                QUERY_MOTALBA_LINES_BY_PERSONCODE_DATERANGE,
                [personcode, period_from_str, period_to_str]
            )
            rows = cursor.fetchall()
            for row in rows:
                docnumber = str(_to_int(row[3])) if row[3] else ''
                if docnumber and docnumber not in seen_docnumbers:
                    seen_docnumbers.add(docnumber)
                    all_lines.append(row)
        except Exception as e:
            logger.warning('Failed motalba query for personcode=%s: %s', personcode, e)

    if not all_lines:
        raise InsuranceImportError(
            'لم يتم العثور على روشتات في جداول المطالبات. '
            'تحقق من كود العميل والفترة الزمنية.'
        )

    # Sort by motalba_docorder, docdate
    all_lines.sort(key=lambda r: (_to_int(r[6]), str(r[4] or ''), str(r[3] or '')))

    logger.info('Insurance import by personcode: found %d prescriptions', len(all_lines))

    with transaction.atomic():
        InsuranceClaimPrescription.objects.filter(claim=claim).delete()

        claim.imported_personcodes = ','.join(personcodes)

        claim_local = claim_imported = claim_tarsia = Decimal('0')
        claim_gross = claim_discount = claim_net   = Decimal('0')
        rx_count    = 0

        for line_row in all_lines:
            branchcode  = _safe(line_row[2])
            docnumber   = str(_to_int(line_row[3])) if line_row[3] else ''
            docdate     = _to_date(line_row[4]) or period_from
            personcode  = _safe(line_row[0])
            doccode     = str(line_row[5] or '').strip()
            ppersoncode = _safe(line_row[9])
            # line_row[7]=docvalue_grandtotal, line_row[11]=docvaluerequired
            dgt, dvr = _signed_dgt(line_row[7], line_row[11] if len(line_row) > 11 else None, doccode)

            if branchcodes and branchcode not in branchcodes:
                continue

            classified_lines, totals, patient_name = _fetch_and_classify_lines(
                cursor, docnumber, branchcode,
                local_disc, imported_disc, tarsia_disc, tarsia_classif_codes,
                docvalue_grandtotal=dgt,
                docvalue_required=dvr,
            )
            if not patient_name and ppersoncode:
                patient_name = resolve_patient_name(cursor, ppersoncode)

            rx_count += 1
            _write_prescription_snapshot(
                claim=claim, seq=rx_count,
                docnumber=docnumber, docdate=docdate,
                branchcode=branchcode, personcode=personcode,
                patient_name=patient_name,
                classified_lines=classified_lines, totals=totals,
                local_disc=local_disc, imported_disc=imported_disc, tarsia_disc=tarsia_disc,
            )

            claim_local    += totals['local_before']
            claim_imported += totals['imported_before']
            claim_tarsia   += totals['tarsia_before']
            claim_gross    += totals['gross_before']
            claim_discount += totals['total_discount']
            claim_net      += totals['net_after']

        _save_claim_totals(claim, rx_count, claim_local, claim_imported, claim_tarsia,
                           claim_gross, claim_discount, claim_net, user)

        # Enrich with companiesitems metadata from the local cache (non-fatal)
        try:
            enrich_prescriptions_from_cache(claim)
        except Exception as enrich_err:
            logger.warning('Enrichment failed (non-fatal): %s', enrich_err)

    return _summary(rx_count, claim_local, claim_imported, claim_tarsia, claim_gross, claim_net)


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLE RX LOOKUP (for manual add)
# ═══════════════════════════════════════════════════════════════════════════════

def _claim_parent_ppersoncodes(claim: InsuranceClaim) -> set[str]:
    """
    Determine the parent personcode(s) (ppersoncode / عميل أب) that a claim
    belongs to.  A manual Rx may only be added if its motalba ppersoncode is in
    this set — this stops one client's receipts being billed onto another's.

    Sources (union):
      1. Configured parent: claim.subclient.client.parent.softech_personcode
      2. Derived from data: MotalbaCache.ppersoncode for the claim's own
         personcodes (the parent group those children actually roll up to)

    Returns an empty set when the parent cannot be determined (caller then
    degrades to a soft warning rather than a hard block).
    """
    codes: set[str] = set()

    # 1) Configured parent client (عميل أب)
    try:
        parent = getattr(claim.subclient.client, 'parent', None)
        if parent and parent.softech_personcode:
            codes.add(str(parent.softech_personcode).strip())
    except Exception:
        pass

    # 2) The claim's own personcodes (a shared code may appear as a personcode on
    #    one motalba row and as a ppersoncode on another — both identify the same
    #    عميل أب group).
    try:
        for c in (claim.subclient.get_all_personcodes() or []):
            if c:
                codes.add(str(c).strip())
    except Exception:
        pass

    # 3) Derived from data: BOTH the personcode and ppersoncode columns of the
    #    claim's motalba rows (the group code can live in either column).
    try:
        from .models import MotalbaCache
        child_codes = [str(c) for c in (claim.subclient.get_all_personcodes() or [])]
        if child_codes:
            rows = (MotalbaCache.objects
                    .filter(personcode__in=child_codes)
                    .values_list('personcode', 'ppersoncode'))
            for pc, pp in rows:
                if pc: codes.add(str(pc).strip())
                if pp: codes.add(str(pp).strip())
            # Also: rows where the claim's code appears as the PARENT (ppersoncode)
            rows2 = (MotalbaCache.objects
                     .filter(ppersoncode__in=child_codes)
                     .values_list('personcode', 'ppersoncode'))
            for pc, pp in rows2:
                if pc: codes.add(str(pc).strip())
                if pp: codes.add(str(pp).strip())
    except Exception:
        pass

    return {c for c in codes if c}


def _resolve_docnumber_branch(docnumber: str) -> str | None:
    """
    A docnumber is NOT unique across branches.  Resolve the correct branch for
    an insurance receipt from the local caches (fast, no Sybase round-trip):
      1. CompaniesItemsCache — insurance prescriptions are recorded here
      2. MotalbaCache        — any motalba line
    Returns the branchcode string, or None if unknown (caller falls back).
    """
    try:
        from .models import CompaniesItemsCache, MotalbaCache
        ci = (CompaniesItemsCache.objects
              .filter(docnumber=str(docnumber))
              .values_list('branchcode', flat=True).first())
        if ci:
            return str(ci).strip()
        mc = (MotalbaCache.objects
              .filter(docnumber=str(docnumber))
              .values_list('branchcode', flat=True).first())
        if mc:
            return str(mc).strip()
    except Exception:
        pass
    return None


def fetch_single_rx_from_softech(docnumber: str, claim: InsuranceClaim,
                                 branchcode: str | None = None) -> dict:
    """
    Fetch a single prescription from Softech by docnumber.
    Returns a dict with all fields needed for InsuranceClaimManualRx.
    Does NOT write to the database.

    branchcode: optional explicit branch.  When omitted, the correct branch is
    resolved from the local caches (docnumber is not unique across branches).
    """
    try:
        conn = _get_connection()
    except Exception as e:
        raise InsuranceImportError(f'فشل الاتصال بسوفتك: {e}') from e

    cursor = conn.cursor()

    # Resolve the branch up front so we read the RIGHT prescription, not just
    # the first branch that happens to share this docnumber.
    target_branch = (branchcode or '').strip() or _resolve_docnumber_branch(docnumber)

    # Branch-scoped header query when the branch is known (cache-resolved) —
    # avoids a full-table scan of stktransm (docnumber alone isn't index-leading).
    if target_branch:
        cursor.execute(QUERY_PRESCRIPTION_HEADER_BY_DOCNO_BRANCH, [docnumber, target_branch])
        header_rows = cursor.fetchall() or []
        if not header_rows:
            # Branch guess missed — fall back to the (slower) unscoped lookup.
            cursor.execute(QUERY_PRESCRIPTION_HEADER_BY_DOCNO, [docnumber])
            header_rows = cursor.fetchall() or []
    else:
        cursor.execute(QUERY_PRESCRIPTION_HEADER_BY_DOCNO, [docnumber])
        header_rows = cursor.fetchall() or []
    if not header_rows:
        raise InsuranceImportError(f'لم يتم العثور على الفاتورة رقم {docnumber} في سوفتك')

    # Pick the row matching the resolved branch; else fall back to the first.
    header = None
    if target_branch:
        for hr in header_rows:
            if _safe(hr[0]) == target_branch:
                header = hr
                break
    header = header or header_rows[0]

    branchcode = _safe(header[0])
    docdate    = _to_date(header[3]) or claim.period_from
    phcode     = _safe(header[5])

    local_disc    = Decimal(str(claim.applied_local_disc_pct    or 0))
    imported_disc = Decimal(str(claim.applied_imported_disc_pct or 0))
    tarsia_disc   = Decimal(str(claim.applied_tarsia_disc_pct   or 0))

    classified_lines, totals, patient_name = _fetch_and_classify_lines(
        cursor, docnumber, branchcode,
        local_disc, imported_disc, tarsia_disc, None,
    )
    # Fallback to phcode-based lookup if not found in lines
    if not patient_name and phcode:
        patient_name = resolve_patient_name(cursor, phcode)

    # ── PARENT-CODE GUARDRAIL (عميل أب / ppersoncode) ─────────────────────────
    # A manual Rx may only be added to a claim if the receipt's motalba parent
    # code (ppersoncode) matches the claim's parent group.  This stops one
    # client's receipts being billed onto another client's claim.
    #
    #   same parent, different child personcode → ALLOW (intended cross-subclient
    #     aggregation under one عميل أب) — surfaced as an informational note.
    #   different parent                         → BLOCK (hard error).
    #   parent indeterminable (receipt not in any motalba, or no cache/parent
    #     configured)                            → ALLOW with a soft warning.
    warning = ''
    tx_personcode = tx_ppersoncode = ''
    motalbano = None
    # Prefer the fast local MotalbaCache (indexed) over a live full-table scan of
    # SOFTECHDB9.dbo.motalba (273k rows, docnumber may be unindexed → very slow).
    try:
        from .models import MotalbaCache
        mc = (MotalbaCache.objects
              .filter(docnumber=str(docnumber))
              .order_by('-docdate')
              .values('motalbano', 'personcode', 'ppersoncode', 'branchcode')
              .first())
        if mc:
            motalbano      = str(mc['motalbano'])
            tx_personcode  = (mc['personcode'] or '').strip()
            tx_ppersoncode = (mc['ppersoncode'] or '').strip()
    except Exception:
        pass
    # Fall back to a live (timeout-bounded) lookup only if the cache misses
    if not tx_personcode:
        try:
            cursor.execute(QUERY_CHECK_DOC_IN_MOTALBA, [docnumber])
            motalba_row = cursor.fetchone()
            if motalba_row:
                motalbano       = _safe(motalba_row[0])
                tx_personcode   = _safe(motalba_row[1])
                tx_ppersoncode  = _safe(motalba_row[2]) if len(motalba_row) > 2 else ''
        except Exception:
            pass

    allowed_codes = _claim_parent_ppersoncodes(claim)   # set of all codes tied to the claim
    claim_codes   = claim.subclient.get_all_personcodes()

    def _receipt_codes():
        return {c for c in (tx_personcode, tx_ppersoncode) if c}

    if allowed_codes and _receipt_codes():
        # The shared عميل أب code may sit in EITHER column (personcode or
        # ppersoncode) — they identify the same group.  Allow when ANY of the
        # receipt's codes matches the claim's related code set.
        if not (_receipt_codes() & allowed_codes):
            # No shared code per cache — but cache may be STALE (codes were just
            # corrected in SOFTECH).  Re-verify LIVE before blocking.
            try:
                live_branch = branchcode or target_branch
                if live_branch:
                    cursor.execute(QUERY_CHECK_DOC_IN_MOTALBA_BRANCH, [docnumber, live_branch])
                else:
                    cursor.execute(QUERY_CHECK_DOC_IN_MOTALBA, [docnumber])
                live_row = cursor.fetchone()
                if live_row:
                    tx_personcode  = _safe(live_row[1]) or tx_personcode
                    tx_ppersoncode = (_safe(live_row[2]) if len(live_row) > 2 else '') or tx_ppersoncode
                    motalbano      = _safe(live_row[0]) or motalbano
            except Exception:
                pass

        if not (_receipt_codes() & allowed_codes):
            # Confirmed (live) unrelated client → block.
            raise InsuranceImportError(
                f'لا يمكن إضافة هذه الفاتورة لهذه المطالبة. '
                f'الفاتورة تخص عميلاً مختلفاً (كود: {tx_personcode or "?"} / أب: {tx_ppersoncode or "?"})، '
                f'لا ينتمي للعميل الأب لهذه المطالبة '
                f'({"، ".join(sorted(allowed_codes))}). '
                f'يُسمح فقط بإضافة فواتير تنتمي لنفس العميل الأب.'
            )
        # Related — allow; note if it is a different sub-client (child code)
        if tx_personcode and tx_personcode not in claim_codes:
            warning = (
                f'هذه الفاتورة تخص فئة أخرى (كود: {tx_personcode}) ضمن نفس '
                f'العميل الأب — سيتم إضافتها لهذه المطالبة.'
            )
    elif tx_personcode and tx_personcode not in claim_codes:
        # Couldn't determine the claim's code set — fall back to a soft warning.
        warning = (
            f'هذه الفاتورة تخص مطالبة رقم {motalbano} (كود عميل: {tx_personcode}). '
            f'تعذّر التحقق من العميل الأب — تأكد قبل الإضافة.'
        )

    return {
        'softech_docnumber':         docnumber,
        'softech_docdate':           docdate,
        'softech_branchcode':        branchcode,
        'softech_personcode':        tx_personcode,
        'softech_ppersoncode':       tx_ppersoncode,
        'patient_name':              patient_name,
        'original_client_warning':   warning,
        **totals,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RECALCULATE FINAL TOTALS (after adjustments/exclusions/supplements)
# ═══════════════════════════════════════════════════════════════════════════════

def recalculate_claim_final_totals(claim: InsuranceClaim) -> None:
    from .models import (
        InsuranceClaimAdjustment, InsuranceClaimExclusion,
        InsuranceClaimSupplement, InsuranceClaimManualRx,
    )

    # Drop any prefetched relations (the DRF viewset prefetches prescriptions/
    # supplements/manual_rx) so we re-read the CURRENT rows from the DB.  Without
    # this, an apply that just mutated prescriptions would re-aggregate the stale
    # prefetched objects and leave the claim totals unchanged.
    claim._prefetched_objects_cache = {}

    excluded_ids = set(
        InsuranceClaimExclusion.objects.filter(prescription__claim=claim)
        .values_list('prescription_id', flat=True)
    )

    local_disc    = Decimal(str(claim.applied_local_disc_pct    or 0))
    imported_disc = Decimal(str(claim.applied_imported_disc_pct or 0))
    tarsia_disc   = Decimal(str(claim.applied_tarsia_disc_pct   or 0))

    local = imported = tarsia = gross = discount = net = Decimal('0')
    rx_count = 0

    for rx in claim.prescriptions.all():
        if rx.id in excluded_ids:
            continue
        rx_count += 1

        try:
            adj = rx.adjustment
            lb = adj.local_before    if adj.local_before    is not None else rx.local_before
            ib = adj.imported_before if adj.imported_before is not None else rx.imported_before
            tb = adj.tarsia_before   if adj.tarsia_before   is not None else rx.tarsia_before
            gb = lb + ib + tb

            if adj.net_override is not None:
                rx_net  = adj.net_override
                rx_disc = gb - rx_net
            else:
                ld  = (lb * local_disc    / 100).quantize(Decimal('0.01'))
                id_ = (ib * imported_disc / 100).quantize(Decimal('0.01'))
                td  = (tb * tarsia_disc   / 100).quantize(Decimal('0.01'))
                rx_disc = ld + id_ + td
                rx_net  = gb - rx_disc
        except InsuranceClaimAdjustment.DoesNotExist:
            lb, ib, tb = rx.local_before, rx.imported_before, rx.tarsia_before
            gb      = rx.gross_before
            rx_disc = rx.total_discount
            rx_net  = rx.net_after

        local    += lb; imported += ib; tarsia += tb
        gross    += gb; discount += rx_disc; net += rx_net

    # Standalone supplements (ملحق مستقل) are SEPARATE printouts with their own
    # number — they are excluded from this claim's grand total, matching
    # invoice_builder.build_invoice_dataset().
    for sup in claim.supplements.filter(is_excluded=False).exclude(
        supplement_type=InsuranceClaimSupplement.SUPPLEMENT_STANDALONE
    ):
        local += sup.local_before; imported += sup.imported_before
        tarsia += sup.tarsia_before; gross += sup.gross_before
        discount += sup.total_discount; net += sup.net_after
        rx_count += sup.rx_count

    for mrx in claim.manual_rx.filter(is_excluded=False):
        local += mrx.local_before; imported += mrx.imported_before
        tarsia += mrx.tarsia_before; gross += mrx.gross_before
        discount += mrx.total_discount; net += mrx.net_after
        rx_count += 1

    # ── Claim totals via the Power-Query net formula on the summed splits ─────
    from .classifier import powerquery_totals_from_splits
    t = powerquery_totals_from_splits(local, imported, tarsia,
                                      local_disc, imported_disc, tarsia_disc)
    local, imported, tarsia = t['local_before'], t['imported_before'], t['tarsia_before']
    gross, discount, net    = t['gross_before'], t['total_discount'], t['net_after']

    claim.final_rx_count        = rx_count
    claim.final_local_before    = local
    claim.final_imported_before = imported
    claim.final_tarsia_before   = tarsia
    claim.final_gross_before    = gross
    claim.final_total_discount  = discount
    claim.final_net_after       = net
    claim.save(update_fields=[
        'final_rx_count', 'final_local_before', 'final_imported_before',
        'final_tarsia_before', 'final_gross_before', 'final_total_discount',
        'final_net_after',
    ])


# ── Helpers ────────────────────────────────────────────────────────────────────

def enrich_prescriptions_from_cache(claim) -> int:
    """
    Populate companiesitems metadata (roshetta_no, patient_no, dept_name, etc.)
    on the claim's prescriptions from the local CompaniesItemsCache.

    Matches on (docnumber, branchcode).  Falls back to docnumber-only match if
    the branch differs (some prescriptions span branch corrections).
    Returns count of enriched prescriptions.

    This uses the fast local cache — no live Sybase round-trips.  Run the cache
    sync first (sync_insurance_cache) so recent prescriptions are covered.
    """
    from .models import CompaniesItemsCache, InsuranceClaimPrescription

    rxs = list(claim.prescriptions.all())
    if not rxs:
        return 0

    docnos = {rx.softech_docnumber for rx in rxs if rx.softech_docnumber}
    if not docnos:
        return 0

    # Build lookup: (docnumber, branchcode) -> cache row, and docnumber -> row
    cache_rows = CompaniesItemsCache.objects.filter(docnumber__in=docnos)
    by_doc_branch: dict = {}
    by_doc: dict = {}
    for c in cache_rows:
        by_doc_branch[(c.docnumber, c.branchcode)] = c
        by_doc.setdefault(c.docnumber, c)

    enriched = 0
    to_update = []
    for rx in rxs:
        c = (by_doc_branch.get((rx.softech_docnumber, rx.softech_branchcode))
             or by_doc.get(rx.softech_docnumber))
        if not c:
            continue
        rx.roshetta_no     = c.roshettano or ''
        rx.patient_no      = c.patientno or ''
        rx.financial_no    = c.financialno or ''
        rx.file_no         = c.fileno or ''
        rx.membership_no   = c.membershipno or ''
        rx.dept_name       = c.deptname or ''
        rx.relative_degree = c.relativedegree or ''
        rx.hi_type_code    = c.hi_typecode or ''
        rx.exam_date       = c.examdate
        # Prefer cache patient name if prescription has none
        if not rx.patient_name and c.patientname:
            rx.patient_name = c.patientname
        to_update.append(rx)
        enriched += 1

    if to_update:
        InsuranceClaimPrescription.objects.bulk_update(
            to_update,
            ['roshetta_no', 'patient_no', 'financial_no', 'file_no',
             'membership_no', 'dept_name', 'relative_degree', 'hi_type_code',
             'exam_date', 'patient_name'],
            batch_size=500,
        )
    logger.info('[enrich] %d/%d prescriptions enriched from CompaniesItemsCache',
                enriched, len(rxs))
    return enriched


def _save_claim_totals(claim, rx_count, local, imported, tarsia, gross, discount, net, user):
    # ── Claim totals via the Power-Query net formula on the summed splits ──────
    # net = local·(1−l) + imported·(1−i) + tarsia·(1−t); since net is linear in
    # the splits, computing it on the summed splits == summing per-row nets, so
    # the cover reconciles to the finance team's Power-Query output exactly.
    from .classifier import powerquery_totals_from_splits
    t = powerquery_totals_from_splits(
        local, imported, tarsia,
        claim.applied_local_disc_pct, claim.applied_imported_disc_pct,
        claim.applied_tarsia_disc_pct,
    )
    local, imported, tarsia = t['local_before'], t['imported_before'], t['tarsia_before']
    gross, discount, net    = t['gross_before'], t['total_discount'], t['net_after']

    claim.snapshot_rx_count        = rx_count
    claim.snapshot_local_before    = local
    claim.snapshot_imported_before = imported
    claim.snapshot_tarsia_before   = tarsia
    claim.snapshot_gross_before    = gross
    claim.snapshot_total_discount  = discount
    claim.snapshot_net_after       = net
    claim.final_rx_count        = rx_count
    claim.final_local_before    = local
    claim.final_imported_before = imported
    claim.final_tarsia_before   = tarsia
    claim.final_gross_before    = gross
    claim.final_total_discount  = discount
    claim.final_net_after       = net
    claim.imported_at           = timezone.now()
    if user:
        claim.imported_by = user
    claim.save()


def _summary(rx_count, local, imported, tarsia, gross, net) -> dict:
    return {
        'rx_count':      rx_count,
        'local_before':  float(local),
        'imported_before': float(imported),
        'tarsia_before': float(tarsia),
        'gross_before':  float(gross),
        'net_after':     float(net),
    }
