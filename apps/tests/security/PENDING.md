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
