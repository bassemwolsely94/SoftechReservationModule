# Insurance claims — search by receipt number (short design)

Date: 2026-11-15 · Screen: `/insurance` (مطالبات التأمين) · Size: small change

## Why
Staff need to type a SOFTECH receipt (روشتة / فاتورة) number and see where it landed:
which of our claims (مطالبة) it sits in, whether it is active or excluded there, and how it
got there. Today the search box only filters the claims already loaded on the page, by claim
fields; it never looks inside claims.

## Goals
- One place to answer "where is receipt N?": every claim that holds it, active or excluded.
- Show how it got there: imported with the motalba, added by hand (who, why), added by a
  re-sync, excluded (reason, who, when).
- Show the SOFTECH side too: which SOFTECH motalba number it belongs to (from `MotalbaCache`,
  last 90 days only), so a receipt that is in SOFTECH but in none of our claims is still found.
- One click from a result to that claim, with the receipt highlighted.

## Non-goals / anti-goals
- No new filter on the claims grid itself; the grid stays as it is.
- No writes of any kind: read-only lookup. No SOFTECH live query (cache only).
- Never hide the branch: SOFTECH numbers receipts per branch, so the same number can exist in
  several branches. Every result shows its branch; never merge hits across branches.

## Approaches (owner picked 1)
1. **Toggle on the existing search box «مطالبة | روشتة»** — picked. Clear, one click, no new field.
2. Separate «رقم الروشتة» field — clearest, but crowds an already full filter row.
3. Guess the mode from the input (e.g. ≥6 digits) — no clicks, but motalba numbers and short
   receipt numbers look alike, so it would guess wrong sometimes.

## Design
**Frontend (`InsuranceClaimsPage.jsx`)**
- A small segmented toggle «مطالبة | روشتة» before the search input. Default «مطالبة» (today's
  behaviour, unchanged). The choice is remembered per browser (try/catch localStorage).
- In «روشتة» mode the placeholder becomes «رقم الروشتة (سوفتك)…»; Enter (or a 400 ms pause after
  ≥3 characters) calls the server. The grid's client-side search is not applied in this mode.
- Results show in a calm panel above the grid (no modal), one block per receipt
  (number · branch label · date · patient · net), with one row per claim it appears in:
  claim number, جهة/فئة, claim status, «نشطة» or «مستثناة» + reason/who/when, and how it came in
  (مستوردة مع مطالبة سوفتك N / إضافة يدوية — by, reason / مزامنة سوفتك), and «فتح ↗».
  A SOFTECH-only line shows «في سوفتك: مطالبة رقم N — لم تُستورد عندنا» when the cache has it
  but no claim of ours does. «لا نتائج» when nothing anywhere.
- «فتح ↗» navigates to `/insurance/claims/<id>?rx=<docnumber>&branch=<code>`; the detail page reads
  `rx`, scrolls to that receipt in الروشتات and briefly highlights it (and opens the excluded view
  if it is excluded).
- Branch labels via `useBranchLabels` (never a bare code).

**Backend (`apps/insurance/views.py`)**
- `GET /api/insurance/claims/find-receipt/?docnumber=…[&branch=…]` on `InsuranceClaimViewSet`
  (list-level action), same permission as the claims list (`InsuranceModuleAccess`).
- Exact match on `softech_docnumber` (trimmed) across `InsuranceClaimPrescription` and
  `InsuranceClaimManualRx`, plus `MotalbaCache.docnumber`; optional branch narrows. Capped at
  50 hits. `select_related` claim → subclient → client, exclusion → excluded_by.
- "How it came in": prescription `is_manual` + `added_by`/`manual_reason`; else the latest
  `InsuranceAuditEvent` for that claim whose `target_ref` is the receipt (manual_add / resync add);
  else «مستوردة مع المطالبة».
- Insurance is company-level (claims are per insurer, not per branch), same visibility as the
  claims list; no extra branch scoping.

**Help + tests**
- Help: `apps/help/content/insurance.py` claims screen — the toggle and the result panel (AR+EN),
  bump `updated`.
- Tests: endpoint returns active + excluded hits with reasons, branch separation (same number,
  two branches → two receipts), manual-add origin, cache-only hit, empty result, permission
  refusal for a user without the insurance module.

## Left to the builder
Exact panel styling; whether the 400 ms auto-search is kept or Enter-only feels calmer.
