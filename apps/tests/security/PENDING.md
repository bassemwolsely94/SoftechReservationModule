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

## Round 2, R3 — owner decision D6 (2026-11-05): views that checked only "logged in"

D6 (decision pack, default Fix) gave 107 such views `core.permissions.RouteModulePermission` — the
middleware's own rule at view level, so nothing is refused that `enforce` would not refuse. These
are in stop-and-ask areas. Users, counselling cards and cheque plans already check inside the view
(tests in `test_d6_route_gate.py` pass); this one waits for the owner to OK the one-line diff
(`permission_classes = [IsAuthenticated, RouteModulePermission]`):
- D-64: loyalty redeem / approve redemption — reachable without the `customers` grant in log mode (customer money)
