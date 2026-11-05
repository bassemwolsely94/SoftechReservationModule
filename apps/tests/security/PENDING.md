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

## Round 2 / R2 money — awaiting the owner (2026-11-05)

Stop-and-ask (offer discounts, insurance billing totals). Tests in `apps/tests/test_money_offers_incentives.py`
and `apps/tests/test_money_insurance_replacement.py`; proposed diffs in the R2 PR description.
- M-1: the offers engine discounts an item whose safety flag blocks the sale (sale stopped / archived / inactive) — `offers/engine._qualifies` never calls `catalog.safety.blocks_sale`
- M-2: stacked offers can push a POS line past 100% — `offers/attach.build_attach_plan` sums the per-offer amounts without the engine's per-line gross cap (10% + 60% + fixed → cust_discp 170%, negative line total)
- M-3: a prescription's net_override never reaches the claim total — `insurance/importer.recalculate_claim_final_totals` (and the invoice export) rebuild the net from the summed splits
- M-4: the claim net can differ by cents from the sum of the printed row nets (rows rounded each, claim rounded once) — keep Power-Query parity or sum the rows?

## Round 2, R3 — owner decision D6 (2026-11-05): views that checked only "logged in"

D6 (decision pack, default Fix) gave 107 such views `core.permissions.RouteModulePermission` — the
middleware's own rule at view level, so nothing is refused that `enforce` would not refuse. These
are in stop-and-ask areas. Users, counselling cards and cheque plans already check inside the view
(tests in `test_d6_route_gate.py` pass); this one waits for the owner to OK the one-line diff
(`permission_classes = [IsAuthenticated, RouteModulePermission]`):
- D-64: loyalty redeem / approve redemption — reachable without the `customers` grant in log mode (customer money)
