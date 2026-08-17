"""
apps/insurance/classifier.py

Item classification engine for insurance claims.

Classification priority (highest wins):
  1. Manual override stored in InsuranceContract.tarsia_classif_codes
  2. custdiscpclassif codes that indicate Tarsia (configurable)
  3. itemsorigin.importedorigin flag: '1'=imported, '0'=local

Default Tarsia custdiscpcode values (from live Softech data):
  Code '25' → typically Tarsia/special contract items
  Can be extended via contract configuration.
"""
from decimal import Decimal
from .models import ITEM_CATEGORY_LOCAL, ITEM_CATEGORY_IMPORTED, ITEM_CATEGORY_TARSIA

# ── custdiscpclassif (تصنيف خصم التعاقدات) code → category sets ─────────────────
# SOFTECH splits the printed motalba's محلى / مستورد columns by the contract
# discount classification (items.itemstoreclassif → custdiscpclassif code), NOT
# by itemsorigin.  Matching this is what makes our محلى/مستورد equal the finance
# team's Power-Query split exactly.  Confirmed from custdiscounts across clients:
#   local    10,11,12,19,25         (Med: Local / under-license / 25% / shortage)
#   imported 13,14,15,26,27,28,50,90 (Egydrug/Agent/Imported + shortage + insulin + المستلزمات المستوردة)
#   tarsia   22,23                  (اصناف ترسية / اصناف اورام — zero discount)
DEFAULT_LOCAL_CODES          = {'10', '11', '12', '19', '25'}
DEFAULT_IMPORTED_CODES       = {'13', '14', '15', '26', '27', '28', '50', '90'}
DEFAULT_TARSIA_CLASSIF_CODES = {'22', '23'}


def load_classification_overrides() -> dict:
    """
    Return {item_code: forced_category} for every ACTIVE, FORCE-mode override.
    Cheap single query; call once per import/apply batch and pass the result to
    classify_item so mis-defined items get their corrected category.

    REVIEW-mode entries (dual-origin items decided per motalba) are deliberately
    excluded — they must NOT be force-classified globally.
    """
    from .models import InsuranceItemClassificationOverride
    return {
        str(o.item_code).strip(): o.forced_category
        for o in InsuranceItemClassificationOverride.objects
        .filter(is_active=True, mode=InsuranceItemClassificationOverride.MODE_FORCE)
        .only('item_code', 'forced_category')
    }


def load_review_item_codes() -> dict:
    """
    Return {item_code: suggested_category} for ACTIVE, REVIEW-mode entries —
    dual-origin items that must be decided per motalba in the فحص الفروقات tab.
    """
    from .models import InsuranceItemClassificationOverride
    return {
        str(o.item_code).strip(): o.forced_category
        for o in InsuranceItemClassificationOverride.objects
        .filter(is_active=True, mode=InsuranceItemClassificationOverride.MODE_REVIEW)
        .only('item_code', 'forced_category')
    }


def classify_item(
    imported_origin: str | None,       # itemsorigin.importedorigin ('1'/'0'/None)
    store_classif: str | None,         # items.itemstoreclassif (custdiscpcode)
    tarsia_codes: set | None = None,   # override set of tarsia custdiscpcodes
    local_codes: set | None = None,    # accepted for API compat (unused)
    imported_codes: set | None = None, # accepted for API compat (unused)
    item_code: str | None = None,      # itemcode — used to look up a manual override
    overrides: dict | None = None,     # {item_code: category} from load_classification_overrides()
) -> str:
    """
    Return one of: ITEM_CATEGORY_LOCAL, ITEM_CATEGORY_IMPORTED, ITEM_CATEGORY_TARSIA.

    SOFTECH builds the محلى/مستورد split on the printed motalba from
    itemsorigin.importedorigin (confirmed: origin-based reproduces the Power-Query
    split to within a few EGP; custdiscpclassif-based does NOT).  Tarsia is the one
    exception — it is flagged by the contract discount classification code.

    A manual InsuranceItemClassificationOverride (passed in via `overrides`) wins
    over everything: it corrects items wrongly defined as مستورد/محلى in the master.
    """
    # Priority 0: manual per-item correction (highest — a mis-defined master item)
    if overrides and item_code is not None:
        forced = overrides.get(str(item_code).strip())
        if forced:
            return forced

    _tarsia = tarsia_codes if tarsia_codes is not None else DEFAULT_TARSIA_CLASSIF_CODES

    # Priority 1: Tarsia (contract discount classification)
    if store_classif and str(store_classif).strip() in _tarsia:
        return ITEM_CATEGORY_TARSIA

    # Priority 2: imported by origin flag
    if imported_origin is not None and str(imported_origin).strip() == '1':
        return ITEM_CATEGORY_IMPORTED

    # Default: local
    return ITEM_CATEGORY_LOCAL


def calculate_line_discount(
    category: str,
    line_total: Decimal,          # PUBLIC price from st.itemsaleprice × st.transqty
    local_disc_pct: Decimal,
    imported_disc_pct: Decimal,
    tarsia_disc_pct: Decimal,
) -> tuple[Decimal, Decimal]:
    """
    Calculate (discount_amount, net_amount) for one item line.
    line_total is the PUBLIC price (st.itemsaleprice × st.transqty).
    Returns (discount_amount, net_amount).
    """
    line_total = Decimal(str(line_total or 0))
    if category == ITEM_CATEGORY_LOCAL:
        pct = Decimal(str(local_disc_pct or 0))
    elif category == ITEM_CATEGORY_IMPORTED:
        pct = Decimal(str(imported_disc_pct or 0))
    else:
        pct = Decimal(str(tarsia_disc_pct or 0))

    discount = (line_total * pct / Decimal('100')).quantize(Decimal('0.01'))
    net = line_total - discount
    return discount, net


def balance_local_before(
    net_after: Decimal,
    imported_before: Decimal,
    tarsia_before: Decimal,
    local_disc_pct: Decimal,
    imported_disc_pct: Decimal,
    tarsia_disc_pct: Decimal,
) -> Decimal:
    """
    Return the LOCAL before-discount figure that makes the contract algebra
    reconcile against the authoritative net:

        net = local·(1−l%) + imported·(1−i%) + tarsia·(1−t%)
      ⇒ local = [net − imported·(1−i%) − tarsia·(1−t%)] / (1−l%)

    SOFTECH's frozen net (motalba.docvaluerequired) is authoritative and
    matches the printed motalba to the piastre; imported/tarsia come from the
    flagged-item public prices; local is whatever balances the equation.
    """
    Q = Decimal('0.01')
    lpct = Decimal(str(local_disc_pct))    / 100
    ipct = Decimal(str(imported_disc_pct)) / 100
    tpct = Decimal(str(tarsia_disc_pct))   / 100
    denom = Decimal('1') - lpct
    if denom == 0:
        return Decimal('0.00')
    imported_net = imported_before * (Decimal('1') - ipct)
    tarsia_net   = tarsia_before   * (Decimal('1') - tpct)
    return ((net_after - imported_net - tarsia_net) / denom).quantize(Q)


def aggregate_prescription_totals(
    lines: list[dict],
    local_disc_pct: Decimal,
    imported_disc_pct: Decimal,
    tarsia_disc_pct: Decimal,
    docvalue_grandtotal: Decimal | None = None,
    docvalue_required: Decimal | None = None,
) -> dict:
    """
    Compute per-prescription invoice totals the POWER-QUERY way (the finance
    team's recalculated معيار), NOT SOFTECH's stored net.

    Inputs (public prices, سعر الجمهور):
      • local_before / imported_before / tarsia_before =
        Σ (st.itemsaleprice × st.transqty) per category, rounded 2dp/line.
      • gross_before = local + imported + tarsia  (matches SOFTECH's سعر الجمهور).

    NET — the Power-Query formula (uniform contract rates, NOT SOFTECH's
    per-line discount):
        net = local·(1−l%) + imported·(1−i%) + tarsia·(1−t%)
      e.g. motalba 119:  499043.05·0.83 + 387712.42·0.94 = 778,655.41
      (SOFTECH's own net for the same motalba is 778,750.68 — we deliberately do
       NOT use it; that 95.27 gap is item-level discount nuance we discard.)
      total_discount = gross − net.

    docvalue_required (SOFTECH's stored net, محلولdvr) is kept ONLY as a
    reference (`softech_net`) so the UI/templates can FLAG prescriptions whose
    Power-Query net differs from SOFTECH — those are the ones to review.

    Returns: local_before, imported_before, tarsia_before, gross_before,
             local_discount, imported_discount, tarsia_discount,
             total_discount, net_after, softech_net.

    Sign: returns (doccode=30) arrive with a negative docvalue_grandtotal, so
    the whole prescription flips negative.  Fallback when there are no item
    lines (manual rows): put the authoritative gross in local.
    """
    Q = Decimal('0.01')

    raw_local    = Decimal('0')
    raw_imported = Decimal('0')
    raw_tarsia   = Decimal('0')

    for line in lines:
        total = Decimal(str(line.get('line_total') or 0))
        cat   = line.get('category', ITEM_CATEGORY_LOCAL)
        if cat == ITEM_CATEGORY_LOCAL:
            raw_local += total
        elif cat == ITEM_CATEGORY_IMPORTED:
            raw_imported += total
        else:
            raw_tarsia += total

    dgt = Decimal(str(docvalue_grandtotal or 0))
    dvr = Decimal(str(docvalue_required or 0))
    sign = Decimal('-1') if (dgt < 0 or dvr < 0) else Decimal('1')

    lb = (sign * raw_local).quantize(Q)
    ib = (sign * raw_imported).quantize(Q)
    tb = (sign * raw_tarsia).quantize(Q)

    # Fallback: no stktrans lines to classify → put the authoritative gross in local
    if lb == 0 and ib == 0 and tb == 0 and dgt != 0:
        lb = dgt.quantize(Q)

    return powerquery_totals_from_splits(
        lb, ib, tb, local_disc_pct, imported_disc_pct, tarsia_disc_pct,
        softech_net=(dvr.quantize(Q) if dvr != 0 else None),
    )


def powerquery_totals_from_splits(
    local_before: Decimal,
    imported_before: Decimal,
    tarsia_before: Decimal,
    local_disc_pct: Decimal,
    imported_disc_pct: Decimal,
    tarsia_disc_pct: Decimal,
    softech_net: Decimal | None = None,
) -> dict:
    """
    Build the full per-row / per-total figures from the public-price splits
    using the Power-Query net formula.  Shared by per-prescription aggregation,
    daily subtotals and the claim/cover total so every level reconciles.
    """
    Q = Decimal('0.01')
    lb = Decimal(str(local_before or 0))
    ib = Decimal(str(imported_before or 0))
    tb = Decimal(str(tarsia_before or 0))

    lrate = Decimal(str(local_disc_pct    or 0)) / 100
    irate = Decimal(str(imported_disc_pct or 0)) / 100
    trate = Decimal(str(tarsia_disc_pct   or 0)) / 100

    gross_before  = lb + ib + tb
    local_disc    = (lb * lrate).quantize(Q)
    imported_disc = (ib * irate).quantize(Q)
    tarsia_disc   = (tb * trate).quantize(Q)

    # Power-Query NET: net = Σ split·(1−rate); discount is the gross−net residual.
    net_after  = (lb * (Decimal('1') - lrate)
                  + ib * (Decimal('1') - irate)
                  + tb * (Decimal('1') - trate)).quantize(Q)
    total_disc = gross_before - net_after

    return {
        'local_before':      lb,
        'imported_before':   ib,
        'tarsia_before':     tb,
        'gross_before':      gross_before,
        'local_discount':    local_disc,
        'imported_discount': imported_disc,
        'tarsia_discount':   tarsia_disc,
        'total_discount':    total_disc,
        'net_after':         net_after,
        'softech_net':       softech_net,
    }
