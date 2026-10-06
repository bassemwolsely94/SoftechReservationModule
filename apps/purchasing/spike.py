"""
apps/purchasing/spike.py — Demand-spike over-purchase detector (📈).

The "doctor-target" behavior: a doctor prescribes a drug hard until he hits a
manufacturer target, then shifts. We chase the burst with a big purchase; the burst
fades → dead stock (validated: Awadist 130001 spike 80×, Jutoxib 130892 spike 41×).
The SOFTECH referral-doctor field is empty, so we detect the demand SHAPE, not the
doctor — from the demand metrics the engine already computes.

Signal (per item, from the run's metrics):
    recent = qty_90d / 3            # last-quarter monthly rate
    prior  = (qty_365d − qty_90d)/9 # the 9 months BEFORE the recent quarter
  STRONG  = recent≥5 AND (prior<0.15  →  new burst, no history
                          OR recent/prior ≥ 10×)      → cap-eligible
  WATCH   = recent≥5 AND 6× ≤ recent/prior < 10×      → monitor only, never capped

The order CAP is REVIEW-GATED (spike_confirmed) + opt-in: a STRONG spike is flagged
automatically, but المطلوب is cut only after a human confirms "unsustained burst" AND
the cap is activated for the run — so genuine new-product ramps aren't starved. When
active + confirmed: order only ~CAP_MONTHS of coverage at the recent rate. Pure +
unit-testable; no DB/SOFTECH access in the scoring functions.
"""
from django.conf import settings

MIN_RECENT    = float(getattr(settings, 'CASH_SPIKE_MIN_RECENT', 5.0))    # min recent monthly rate
STRONG_RATIO  = float(getattr(settings, 'CASH_SPIKE_STRONG_RATIO', 10.0)) # recent/prior for STRONG
WATCH_RATIO   = float(getattr(settings, 'CASH_SPIKE_WATCH_RATIO', 6.0))   # recent/prior for WATCH
NEW_BURST_PRIOR = float(getattr(settings, 'CASH_SPIKE_NEW_BURST_PRIOR', 0.15))  # prior below → new burst
CAP_MONTHS    = float(getattr(settings, 'CASH_SPIKE_CAP_MONTHS', 1.0))    # coverage to order when capping


def classify_spike(qty_30d, qty_90d, qty_365d):
    """Pure spike classification from the three demand windows.

    Returns dict(recent, prior, ratio, tier). tier ∈ '' | 'watch' | 'strong'.
    ratio is 999.0 for a new burst (no prior baseline)."""
    recent = float(qty_90d) / 3.0
    prior  = max(0.0, float(qty_365d) - float(qty_90d)) / 9.0
    if recent < MIN_RECENT:
        return {'recent': round(recent, 3), 'prior': round(prior, 3), 'ratio': 0.0, 'tier': ''}
    if prior < NEW_BURST_PRIOR:
        ratio = 999.0                      # new burst — no history to justify it
    else:
        ratio = recent / prior
    if ratio >= STRONG_RATIO:
        tier = 'strong'
    elif ratio >= WATCH_RATIO:
        tier = 'watch'
    else:
        tier = ''
    return {'recent': round(recent, 3), 'prior': round(prior, 3),
            'ratio': round(ratio, 2), 'tier': tier}


def capped_gap(gap, branch_recent_monthly, *, apply, cap_months=None):
    """Review-gated order cap for a confirmed STRONG spike item, per branch.

    apply=False (default) → gap unchanged. apply=True → order no more than
    cap_months of the branch's own recent monthly rate ("buy a month, watch it").
    Only ever reduces; never increases. Pure + unit-testable."""
    if not apply or gap <= 0:
        return gap
    months = CAP_MONTHS if cap_months is None else float(cap_months)
    return min(gap, max(0.0, float(branch_recent_monthly) * months))
