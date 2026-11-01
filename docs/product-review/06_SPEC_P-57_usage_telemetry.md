# 06 · SPEC P-57 — Usage telemetry from day 1

**Status:** specification (approved for spec 2026-10-30). **Build:** not yet authorised.
**Owner decision:** used for product decisions **and** individual staff evaluation, with the safeguards below.

## 1. Scope

1. **Model.** `ScreenView` in `apps/audit`, which already owns activity data:

   | Field | Type |
   |---|---|
   | staff | FK StaffProfile |
   | role | char |
   | branch | FK, nullable |
   | route | the route **pattern**, e.g. `/transits/:id`, never the raw URL with ids or query strings |
   | tab | char, nullable; the `useHelpTab` value where the page has tabs |
   | at | datetime, indexed |

   No page content, search text or customer identifiers.
2. **Capture.**
   - `Layout.jsx` already has `useLocation()` (line 250). On route change, post `{route_pattern, tab}` to
     `POST /api/audit/screen-view/`.
   - Debounce: the same route within 30 s is not re-sent.
   - Failures are silent and never block the UI.
   - Mobile layout: the same.
3. **Reports** (`/audit` → new tab «استخدام الشاشات»):
   - per module and screen: weekly active users, visits;
   - by branch and by role;
   - **zero-use screens in 60 days**;
   - per staff member: **admin and HR roles only**.
   - Branch managers see their own branch's aggregate only.
4. **Retention:** 12 months, then deleted (P-56 retention job).
5. **Staff notice:**
   - a one-time in-app notice (announcement with read receipt — existing module) plus a line in the HR policy:
     "screen usage is recorded and may be used in performance evaluation together with outcome measures";
   - help text (Arabic + English).

## 2. Rules

- **Never evaluate on usage alone.** The individual view shows usage next to outcome KPIs where they exist:
  identified-sale rate (P-37), refill outcomes (P-46), fridge log on time (P-53), QA / mystery-shopper score (P-51).
- PDPL (employee personal data): confirm with legal. Already listed as an evidence gap.

## 3. Acceptance criteria

- Visiting `/transits/123?x=1` stores route `/transits/:id`; the id and query are never stored (test).
- A non-admin, non-HR user gets 403 on the per-staff report. A branch manager sees only their branch (RBAC tests).
- Rows older than 12 months are removed by retention (test).
- Help entry present; `test_help.py` passes.

## 4. Measurement

- Weekly active users per module from go-live. This is the adoption baseline for all 30 approved proposals.
