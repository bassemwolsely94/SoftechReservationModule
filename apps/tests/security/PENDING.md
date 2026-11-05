# Pending owner decisions

Tests that expose a hole whose fix needs the owner's OK (SOFTECH writes, auth, pricing,
checkout) are marked `@pending('P-<n>')` and listed here as `- P-<n>: <one line>`. The marker
comes off the day the fix lands; `PendingTests.test_markers_match_pending_md` keeps this list
and the markers in step.

## Batch 5 — decided 2026-10-30 (owner)

B-1 finance: company-wide hub for admin, quality manager and the HQ roles; a branch user sees their
own branch only; supplier A/P reconciliation is company-only. B-2 customers: anyone finds any
customer by full phone; browse / name search / edit / churn list own branch; other branches' numbers
masked; call center and all-branch roles edit anyone (`apps/customers/access.py`). B-3: supervisor
and quality manager are all-branch roles (`core/branch_scope.ALL_BRANCH_ROLES`).
- W-1: voucher generate-otp hands the plain code to the staff member (wa.me text + QR)

## Round 2 / R2 money — decided 2026-11-05 (owner)

M-1 fixed: offers skip any item that `catalog.safety.blocks_sale` refuses (`offers/engine._qualifies`).
M-2 fixed: a line's combined offer discount is capped at its gross in `offers/attach.build_attach_plan`,
the same cap `evaluate_offers` uses, so the line total never goes below zero. M-3 fixed: the claim total
(`insurance/importer.recalculate_claim_final_totals`) and the invoice export (`invoice_builder`) use a
prescription's `net_override` where it has one. M-4 owner-accepted, no code change: the claim net stays
the Power-Query formula over the summed splits (rounded once), matching finance's workbook, and the
few-piaster difference from the sum of the printed row nets is accepted.
`apps/tests/test_money_insurance_replacement.py` tests the accepted behaviour.
