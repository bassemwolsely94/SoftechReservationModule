"""
apps/replacement/config.py — every tunable of the reconstruction in ONE place (doc 25 §16).

Nothing here is a hard-coded business rule: each value can be overridden in settings via
REPLACEMENT_<NAME>. Owner decisions 2026-09-28 are the defaults. Bump RULES_VERSION whenever
a default that changes reconstruction output changes, so every case records which rules
built it.
"""
from decimal import Decimal

from django.conf import settings

RULES_VERSION = 'p0-v5'   # v2: legacy −1-day purchase lines, return settlement, receipt-named patient
                          # v3: capacity-aware duplicates, proportional coverage, clock tie-break
                          # v4: owner auto-confirm of a unique anonymous receipt; cross-branch severity by origin
                          # v5: entry-first (owner 2026-10-26) — anon auto-confirm OFF, unclaimed purchases,
                          #     live cases fund vouchers from their DECLARED receipts only

# ── virtual / buy-back supplier accounts (personsdata ptcode 20) ─────────────────────────
# tier = the % in the supplier NAME (an indicator only — D2); the posted line discount may
# differ and is recorded separately as applied_deduction_pct.
#   A  = our insurance Rx          B1 = insurance meds not dispensed by us
#   B2 = non-insurance client selling medicines
SUPPLIERS = {
    '4472': {'tier': Decimal('25'), 'label': 'مورد شركات 25%', 'family': 'contract',
             'expects_sale': True,  'default_mode': 'products'},   # A — shortage / cannot supply
    '4471': {'tier': Decimal('30'), 'label': 'مورد شركات 30%', 'family': 'contract',
             'expects_sale': True,  'default_mode': 'products'},   # A — products
    '4470': {'tier': Decimal('40'), 'label': 'مورد شركات 40%', 'family': 'contract',
             'expects_sale': None,  'default_mode': 'either'},     # A cash  OR  B1 products
    '4469': {'tier': Decimal('50'), 'label': 'مورد شركات 50%', 'family': 'contract',
             'expects_sale': False, 'default_mode': 'cash'},       # B1 cash
    '3068': {'tier': None,          'label': 'مورد عام',       'family': 'general',
             'expects_sale': False, 'default_mode': 'either'},     # B2 (also used for ordinary buys!)
    '4069': {'tier': Decimal('50'), 'label': 'مورد عام 50%',   'family': 'general',
             'expects_sale': False, 'default_mode': 'either'},     # B2
}
# 5014 «مورد عام مستورد» is deliberately NOT here (owner D8: not a buy-back account).


def _s(name, default):
    return getattr(settings, f'REPLACEMENT_{name}', default)


def supplier_codes():
    return list(_s('SUPPLIERS', SUPPLIERS).keys())


def supplier_cfg(code):
    return _s('SUPPLIERS', SUPPLIERS).get(str(code).strip(), {})


# Contract-sale channels (stktransm.ptclassifcode on the sale): 10 contract, 11 employee,
# 15 insurance (unused today), 17 compensation.
CONTRACT_CHANNELS = ('10', '11', '15', '17')

# D1 — purchase before sale preferred; sale before purchase allowed inside a window.
SALE_BEFORE_PURCHASE_DAYS = 45     # sale may precede the purchase by up to N days
SALE_AFTER_PURCHASE_DAYS  = 15     # purchase may precede the sale by up to N days
RETURN_PAIR_DAYS          = 3      # a contract return pairs with a sale within N days

# Voucher → product-receipt funding window (calibrated on the Samra case: patient receipts
# 9–42 min BEFORE the voucher; anonymous receipt 5 min before).
FUND_PATIENT_BEFORE_MIN = 180
FUND_PATIENT_AFTER_MIN  = 60
FUND_ANON_BEFORE_MIN    = 30
FUND_ANON_AFTER_MIN     = 10
FUND_MAX_SUBSET         = 12       # brute-force subset search cap (patient receipts only)
# Owner rule 2026-10-02: auto-confirm an ANONYMOUS receipt when it is the ONLY anonymous receipt
# in [voucher − 10 min, voucher + 2 min] whose amount is 80 %–100 % of the voucher (+ absorb tol).
# Owner 2026-10-26 (Q5): switched OFF — an anonymous receipt is always a *proposed* link for review.
ANON_AUTO_CONFIRM     = False
ANON_AUTO_BEFORE_MIN  = 10
ANON_AUTO_AFTER_MIN   = 2
ANON_AUTO_MIN_RATIO   = Decimal('0.80')

# Differences (D4): receipts > voucher by ≤ this → absorbed rounding; more → customer top-up.
ABSORB_ABS = Decimal('5.00')
ABSORB_PCT = Decimal('0.01')
# Rule C (§16.2): cash remainder paid 1:1 from a product-rate entitlement.
CASH_REMAINDER_ABS = Decimal('200.00')
CASH_REMAINDER_PCT = Decimal('0.15')

RATE_DEVIATION_PP  = Decimal('5.0')   # |applied − supplier tier| above this → exception
AGED_OUTSTANDING_DAYS = 90

# ── live workflow (Phase 1) ─────────────────────────────────────────────────────────────────
# Master switch for SOFTECH postings from a case. OFF ⇒ every leg returns the writer's dry-run
# plan only (the invoices / POS writers additionally keep their own gates).
POSTING_ENABLED = False
# B1 pilot: a live post also needs the case's branch in this list (empty = no branch) — the
# rollout is per branch (doc 25 §21, pilot 130). Both switches stay OFF until the owner says go.
POSTING_BRANCHES = ()
# B3 cash payouts: an instruction not executed by the cashier within N days, or a paid one whose
# handover nobody confirmed within N days, becomes an exception.
PAYOUT_EXECUTE_DAYS = 2
PAYOUT_CONFIRM_DAYS = 1
# Pre-write guard: the writer's own computed purchase total must equal the approved balance.
PURCHASE_PRECHECK_TOLERANCE = Decimal('0.05')

# How far a role may LOWER a rule's deduction (patient-favourable), in percentage points, when
# the employee has no personal ReplacementGrant. Raising the deduction is always allowed.
ROLE_MAX_OVERRIDE_PP = {'admin': 100, 'supervisor': 5}

# Approval routing (owner 2026-10-03 + 2026-10-26). Amounts are compared to the patient's ROLLING
# total over AGGREGATION_DAYS (anti-splitting, control H).
APPROVAL_AGGREGATION_DAYS = 7
APPROVAL_AUTO_MAX      = Decimal('500')    # ≤ → no approval needed (products, no override)
APPROVAL_MANAGER_ABOVE = Decimal('500')    # > → manager workflow (branch supervisor, then manager)
APPROVAL_CASH_ALWAYS   = True              # any cash / mixed settlement needs (at least) a supervisor
APPROVAL_CASH_MANAGER_ABOVE = Decimal('1500')   # cash part above this → manager
APPROVAL_OVERRIDE_ALWAYS = True            # any patient-favourable rate override needs (at least) a supervisor
APPROVAL_OVERRIDE_MANAGER_PP = Decimal('5')     # lowered by more than N points → manager
# Backdate (control E): a case whose purchase is dated before the case was entered.
# same day → auto · ≤ N days and same month → supervisor · older or crossing month-end → manager
APPROVAL_BACKDATE_SUPERVISOR_DAYS = 3

# ── entry-first (owner 2026-10-26) ──────────────────────────────────────────────────────────
# Branch → first purchase date from which every virtual-supplier purchase must come from a case
# entered in the module first. A purchase on/after that date with no live case becomes an
# UNCLAIMED record «شراء بدون حالة» (money still tracked, HIGH exception, claimable).
# Before the date (or for a branch not listed) reconstruction keeps building historical cases.
ENTRY_FIRST_FROM = {'130': '2026-11-01'}
WORKFLOW_SUPERVISOR = 'replacement_supervisor'
WORKFLOW_MANAGER    = 'replacement_manager'

# Redemption: patient may take products worth more than the remaining entitlement and pay the
# difference (customer top-up, D-22). Cap the top-up so a case is not a disguised ordinary sale.
MAX_TOPUP_PCT = Decimal('0.50')            # top-up ≤ 50 % of the remaining entitlement

# Token stamped as the purchase's supplier-invoice number (docnumber2) — internal field only
# (owner D14). 9 + 7-digit case id: never a valid ddmmyyyy date (day 90) → no clash with typed dates.
PURCHASE_TOKEN_PREFIX = 9

CONF_HIGH   = Decimal('80')
CONF_MEDIUM = Decimal('55')

# Sales channel codes that are NOT product-redemption receipts.
NON_REDEMPTION_CHANNELS = CONTRACT_CHANNELS


def get(name):
    """Settings override → module default."""
    return _s(name, globals()[name])


def entry_first_from(branchcode):
    """Cut-over date for the branch, or None while it is still matcher-first."""
    from datetime import date
    raw = get('ENTRY_FIRST_FROM').get(str(branchcode or '').strip())
    if not raw:
        return None
    return raw if isinstance(raw, date) else date.fromisoformat(str(raw))


def is_entry_first(branchcode, day) -> bool:
    start = entry_first_from(branchcode)
    return bool(start and day and day >= start)


def conf_class(score) -> str:
    score = Decimal(str(score))
    if score >= get('CONF_HIGH'):
        return 'high'
    if score >= get('CONF_MEDIUM'):
        return 'medium'
    return 'low'
