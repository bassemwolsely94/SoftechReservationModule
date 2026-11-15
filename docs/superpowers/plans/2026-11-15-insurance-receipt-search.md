# Insurance receipt search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find a SOFTECH receipt number across every insurance claim (and the motalba cache) from the claims list, and open the claim on it.

**Architecture:** A read-only list action `find-receipt` on `InsuranceClaimViewSet` built by a pure function in a new `apps/insurance/receipt_search.py`; the claims page gets a «مطالبة | روشتة» toggle and a results panel; the detail page reads `?rx=` into its existing receipt filter.

**Tech Stack:** Django/DRF, React (Vite), Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-15-insurance-receipt-search-design.md`

## Global Constraints
- Read-only: no writes, no live SOFTECH query (MotalbaCache only).
- Exact `softech_docnumber` match (trimmed); optional `branch`; max 50 receipts.
- Permission = `InsuranceModuleAccess` (same as the claims list).
- Every hit carries its branch code; UI shows it via `useBranchLabels`.
- Help AR+EN on `/insurance`, bump `updated`; tour text ≤160, label ≤40, more ≤600, no raw newlines.

## Review Focus
- Same number in two branches → two separate receipt groups, never merged (test in Task 1).
- Receipt active in one claim, excluded in another → both listed with status (test in Task 1).
- Number with surrounding spaces → trimmed, still found (test in Task 1).
- Empty `docnumber` → 400 with Arabic message, no query (test in Task 1).
- Receipt only in MotalbaCache → returned as SOFTECH-only with its motalbano (test in Task 1).

---

### Task 1: Backend lookup + endpoint

**Files:**
- Create: `apps/insurance/receipt_search.py`
- Modify: `apps/insurance/views.py` (new `@action(detail=False, methods=['get'], url_path='find-receipt')` on `InsuranceClaimViewSet`)
- Test: `apps/tests/test_insurance_receipt_search.py`

**Interfaces:**
- Produces: `find_receipt(docnumber: str, branch: str | None = None) -> list[dict]`, one dict per (docnumber, branch):
  `{docnumber, branch, docdate, patient_name, net, appearances: [...], softech: [{motalbano, personcode, docdate}]}`;
  appearance = `{claim_id, claim_number, client_name, subclient_name, claim_status, claim_status_label, kind: 'rx'|'manual', active: bool, excluded_reason, excluded_by, excluded_at, origin: 'import'|'manual'|'resync', origin_by, origin_reason, softech_motalba_no}`.
- Endpoint: `GET /api/insurance/claims/find-receipt/?docnumber=&branch=` → `{"results": [...]}`; 400 `{'error': 'أدخل رقم الروشتة'}` when empty.

- [ ] Step 1: tests — `test_active_and_excluded_listed`, `test_same_number_two_branches_kept_apart`, `test_manual_rx_origin_and_exclusion`, `test_resync_origin_from_audit`, `test_cache_only_hit`, `test_trimmed_and_branch_filter`, `test_empty_docnumber_400`, `test_refused_without_insurance_module`.
- [ ] Step 2: run, expect failures (404 / import error).
- [ ] Step 3: implement. Origin: rx.is_manual → 'manual' (added_by, manual_reason); else an `InsuranceAuditEvent(claim, action='resync_add', target_ref=docnumber)` → 'resync'; else 'import'. ManualRx → 'manual' (added_by, reason), active = not is_excluded.
- [ ] Step 4: tests pass; `test_insurance_portfolio`, `test_help` still pass.
- [ ] Step 5: commit.

### Task 2: Claims page toggle + results panel, detail deep link, help

**Files:**
- Modify: `frontend/src/api/client.js` (`insuranceApi.findReceipt(docnumber, branch)`)
- Create: `frontend/src/components/insurance/ReceiptSearchResults.jsx`
- Modify: `frontend/src/pages/InsuranceClaimsPage.jsx` (toggle, mode-aware placeholder, Enter / 400 ms after ≥3 chars, panel above grid; client-side search ignored in receipt mode)
- Modify: `frontend/src/pages/InsuranceClaimDetailPage.jsx` (`?rx=` → `rxFilter`, tab `prescriptions`)
- Modify: `apps/help/content/insurance.py` (claims screen: toggle + panel, AR/EN, `updated`)

- [ ] Step 1: implement; toggle remembered in localStorage key `ins.claims.searchMode` (try/catch).
- [ ] Step 2: `npx eslint` on changed files (no new warnings), `npx vite build` OK, `test_help` passes.
- [ ] Step 3: browser check on the e2e DB: toggle, active+excluded hits, «فتح ↗» filters the detail grid.
- [ ] Step 4: commit, PR.
