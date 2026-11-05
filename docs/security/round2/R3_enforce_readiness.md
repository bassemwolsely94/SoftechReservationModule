# R3 — enforce readiness (round 2, authorization)

Batch R3 of [the round-2 plan](../2026-11-05-full-project-test-plan.md) §7. Measured on a reader copy
(`WRITER_INSTANCE=False`, `SOFTECH_READ_ONLY=True`, worktree without `.env`), `manage.py test`, own
`TEST_DB_NAME`. Branch `claude/round2-r3r4-access-803ed1`.

## 1. Verdict

**Enforce-ready.** Switching `RBAC_ENFORCEMENT` to `enforce` changes the answer for exactly two
role × route pairs (below), neither called by any screen. Every other request the matrix denies is
already refused by the view itself in today's `log` mode (`role_leaks_log`), and `enforce` adds no leak
(`role_leaks_enforce` empty). Per owner decision **D8 the switch is not part of round 2**: the owner
decides after go-live, from this page.

## 2. Would-deny summary (what `enforce` changes)

| Role × route | Today (log) | Under enforce | Impact |
|---|---|---|---|
| pharmacist `POST /api/config/settings/by_key/` | answered (holds settings view) | 403 from the middleware (POST counted as a write) | none — no frontend caller (`configApi.byKey` is unused) |
| purchasing `POST /api/config/settings/by_key/` | same | same | same |

These are the only two lines of `role_leaks_log`, each with its reason (Z-4). If a screen ever
starts calling `by_key`, map it to `settings view` in `module_access.required()` first (an auth change:
stop-and-ask).

**Before flipping in production**, look at a few days of real would-deny lines (the sweep sees every
route, not what staff actually click):

```bash
grep "would-deny" logs/platform.log | awk '{print $NF}' | sort | uniq -c | sort -rn | head -50
```

Any line there for a role and screen that should work is a matrix gap to fix before `enforce`.

## 3. What R3 changed in the sweep

- **Real records behind detail routes (R3.1).** `sweep.seed_detail_paths()` plants one row per detail
  route that admin cannot reach with the dummy id (the canary `Planter`), picking the model by the
  view's queryset, then the app's models closest in name to the path, and keeping the first one admin
  actually reaches. About 565 detail routes now get a real record; `role_unproven` fell from 460
  lines to 93, each with a reason (nested replacement chains, and routes that need a record in a specific state).
- **Route catalogue fix.** DRF's `<drf_format_suffix:format>` api-root pattern rendered as
  `/api/<prefix>/x`, a path that does not resolve; it accounted for the `/api/config/x`, `/api/hr/x`,
  `/api/qa/x`, `/api/enrichment/x` unproven lines. `routes._render` now skips it.
- **Feature flags on (R4.3, used by R3 too).** The sweeps run with `sweep.FEATURE_FLAGS_ON`
  (daily counts, usage print, missed sales, missed-call call-backs, counselling content), so those
  screens are really checked instead of answering 503. Send and SOFTECH-write switches stay off.
- **Every view gated (R3.3).** `test_static_guards.EveryViewGatedTests`: a viewer with every matrix
  row off, in log mode, calls every protected route and method. Whatever still answers is open to all
  staff and is listed, with a reason, in `baselines/open_to_all_staff.txt`.
- **New-module cases (R3.4).** `test_named_grants.py`: PIC analytics + stock audit named grants
  (granted / ungranted / revoked / other branch, every route and method); counselling, tasks and
  missed sales (whole role sweep restricted to those prefixes, must be clean); usage print (own gate,
  flag on and off).
- **Break-in delta (R3.5).** `test_breakin_delta.py`.
- **D6 — views that checked only "logged in" (owner decision, default Fix).** 131 views under a module
  prefix had nothing but IsAuthenticated, so in log mode every signed-in staff member reached them.
  107 now carry `core.permissions.RouteModulePermission`: the middleware's own rule
  (`module_access.required()` + the matrix) at view level, so a view refuses exactly what `enforce`
  would refuse — no new lockout by construction (the role sweep's overblock and log-leak baselines
  confirm it). Not changed: daily counts (own gate, the middleware skips them), the router root, the
  caller's own PBX extension (open read), and the stop-and-ask areas — users, counselling cards and
  cheque plans already check inside (tests pass), loyalty redeem / approve is pending **D-64**.

## 4. Baselines

| Baseline | Before R3/R4 (`main`) | After | Every line reasoned | Notes |
|---|---:|---:|---|---|
| `role_unproven` | 460 | 93 | yes | real records behind detail routes; route-catalogue fix removed the fake `/x` paths |
| `role_overblocks` | 463 | 525 | yes | −8 counselling (opened, Q-2); +70 seen only with real records (task owner rule, rider / role rules on delivery actions, replacement managers, SOFTECH ERP-match role lists — Q-8) |
| `role_leaks_log` | 2 | 184 | yes — 2 settled, 182 **OPEN owner questions Q-5 / Q-7** | real records exercised delete / edit for the first time; enforce closes every one (`role_leaks_enforce` stays 0) |
| `role_leaks_enforce` | 0 | 0 | — | |
| `role_crashes` | 6 | 99 | yes (93 handed to R7) | 500s only visible on real records; admin crashes too, so no permission question |
| `open_to_all_staff` (new) | — | 92 | yes | own-data / help / pickers / open reads / matrix-consistent (all roles but the middleware-enforced accountant hold the module) |
| `branch_canary_leaks` | 22 | 49 | yes | +27 `GET-DETAIL` lines (B-2 customer reads, shared config, HQ modules incl. insurance, vouchers, stock-audit management); 1 fixed (forecast results) |
| `canary_skipped_models` (new) | — | 2 | yes | |
| `phone_canary_leaks` | 4 | 4 | yes | missed-sales number now masked (fixed) |
| `privacy_log_leaks` / `privacy_answer_leaks` (new) | — | 0 | — | 3 disclosure fixes |


## 5. `role_overblocks` by module and reason source (R3.2)

463 lines on `main` before R3, in 45 reasoned groups. None is unreviewed. Sources:

Every line sits under a `# reason:` header; R3 classified each group by **where its reason comes from**
(lines on `main` before R3 → module(s) → refused roles):

| Source | Groups | Lines | Modules |
|---|---:|---:|---|
| **A. Owner decision recorded** — B-1 company-level finance (A/P reconciliation, cash view, receivables, supplier terms, branch-contribution / inventory-investment boards), owner decision 4 (purchasing branch requests / ISR), §7.2 device registry, owner 2026-11-01 (disposal status) | 6 | 50 | finance 34, analytics 4, purchasing 4, settings 4, catalog 4 |
| **B. Batch-4 overblock review, "Keep — stricter on purpose"** (Z-11c, owner-approved review 2026-10-28): pricing approvals, coupons, voucher cancel, driver app, delivery assign, pick zones, follow-up batch jobs, PBX / omni supervision, purchasing / supply dashboards, OCR stats, customer merges & point adjustments, system jobs, replacement grants, admin screens, abuse summary, offers channel apply, insights backfill | 20 | 315 | approvals 68, vouchers 44, delivery 35, transfers 29, callcenter 25, finance 21, followups 19, demand 17, dashboard 15, catalog 14, customers 9, users 5, replacement 4, purchasing 4, analytics 2, audit 2, offers 2 |
| **C. View asks a finer action than the middleware** (matrix-consistent; the sweep sends a generic request): Z-1, Z-3, Z-5a, Z-7b, Z-8b, Z-9a, Z-9b, Z-11a, Z-12, shortage export / vendors-linkable (merge with the consolidation line) | 16 | 80 | analytics 17, shortage 9, catalog 9, callcenter 8, hr 8, finance 6, purchasing 6, transfers 6, offers 4, customers 3, approvals 2, replacement 2 |
| **D. Security batches N1 / N3** — trusted networks and the zone-policy grid admin-only "like the rest of the access settings" | 2 | 10 | settings 10 |
| **E. No owner decision, module author's choice** — Project 4 counselling curation (needs queue, suggest-items) | 1 | 8 | counselling 8 |

**Changed in R3:** group E — no owner decision covered it, so the §8 Q5 default applied (the matrix
wins): the «يحتاج محتوى» list (the counselling screen's FIRST tab, so view-only roles opened the screen
onto a 403) and similar-item suggestions now follow `counselling → view`; writing and linking still need
`edit`. Help updated. Its 8 lines go STALE.

Groups A–C are settled (owner decision, owner-approved review, or matrix-consistent). Group D is listed
as question Q-1 below because its reason cites the design, not an owner line.


## 6. Matrix-vs-view questions for the owner

Default if unanswered: the matrix wins (§8 Q5). None of these blocks go-live, but **Q-7a** (any role
can delete a customer while production runs in log mode) is worth answering first: it is a one-line
change per view once the owner confirms.

| # | Where | Matrix says | View does | Default / proposal |
|---|---|---|---|---|
| Q-1 | Trusted networks (`/api/access/networks/`) and zone-policy grid (`/api/access/zone-policies/`) | pharmacist and purchasing hold `settings` view | admin only (IsAdminRole) | **Keep admin only** and record it as an owner decision: the device registry beside them is already owner-decided admin-only (§7.2); opening who-counts-as-inside to branch staff has no use. A "yes" turns the reason into an owner line. |
| Q-2 | Counselling curation lists (R3 applied the default) | counselling `view` | was `edit` only | **Applied: matrix wins.** Say no if the needs queue should stay a pharmacists-only screen; then the tab must be hidden for view-only roles instead. |
| Q-3 | Loyalty redeem / approve redemption (PENDING **D-64**, the one D6 view left in a stop-and-ask area that does not check inside) | `customers` grant | only "logged in" (in log mode any signed-in staff member) | **Add RouteModulePermission** — `permission_classes = [IsAuthenticated, RouteModulePermission]` on `RedeemRewardView` and `ApproveRedemptionView` (`apps/loyalty/views.py`); the owner OKs the diff. |
| Q-5 | Missed sales (`/api/pos-orders/missed-sales/`, Project 3) | the middleware maps the prefix to `pos` | the view checks `reservations` (suggestions are confirmed into reservations) — quality manager and viewer hold reservations view, not pos view, so they read the list in log mode | **Owner picks the module.** Default (matrix wins) = `pos`; that would refuse quality manager / viewer, who may use it today, so per D6's no-lockout rule it is listed, not changed. Under enforce today the middleware already refuses them. |
| Q-7 | **Write actions the view lets through though the matrix says no** (182 lines of `role_leaks_log`, found once the sweep used real records; `enforce` refuses every one today). **a — customers (top priority):** every role, viewer included, can DELETE a customer; view-only roles (delivery, salesperson, purchasing, quality manager, viewer) can edit a customer / health profile / conditions, add notes and approve a loyalty redemption. **b — QA inspections:** editable by every hr holder. **c — forecasting / sales targets:** written by the analyst roles per Z-7b / Z-9a, while the matrix gives them no analytics edit / delete (paper mismatch only). **d — insight rules:** editable by every analytics view holder, viewer included. **e — deleting a record or a document line** by roles with create / edit but not delete (reservation lines / images, shortage items, demand lines, chronic tags, catalog bundles, call-center calls, transit config, cheque plans, invoice lines, product images …). | the role's matrix action (edit / delete) | module grant (or branch) only | **a, b, d: add RouteModulePermission** (matrix wins, Q5) — lockout-free for every role the matrix grants; owner confirms no counter role edits customers today without `customers edit`. **c: grant analytics edit / delete to supervisor / purchasing** so matrix and decision agree. **e: per module — grant `delete` where the role really removes lines, else RouteModulePermission.** Not changed in R3 (D6's no-lockout rule). |
| Q-8 | SOFTECH ERP match (`check-erp-match`) on reservations and transfers | reservations / transfers create holders | hard-coded role lists (reservations: admin / pharmacist / purchasing; transfers: admin / purchasing) | **Keep** (it reads SOFTECH); a "yes" records it as an owner line. |
| Q-4 | Forecast scenario results (R4 detail canary) | analytics view (pharmacist holds it) | listed every branch's result rows | **Fixed** to the caller's branches + the chain total (owner decisions 3 / B-1); say so if branch pharmacists should see other branches' targets. |


## 7. Break-in delta since 2026-11-03

| Added | Login / session / one-time code? | Test |
|---|---|---|
| `/api/public/counsel/<token>/` + opt-out (Project 4) | signed token, salt `counsel-card`, 90-day max age | existing `test_counselling_public` (tampered, expired, other salt, opt-out idempotent) + new cross-purpose replay (delivery-track / portal salts) |
| phone-alert «استلمت» tap `alert:<token>:ack` (Project 1) | random token in a WhatsApp quick reply | existing `test_phone_alerts` (other phone ignored, unknown token, duplicate tap no-op) |
| `/api/public/challenge/`, `/api/public/health/` (N6, go-live) | proof-of-work challenge (signed) | existing `test_access_public_gate`, `test_public_guard` |
| WebSocket groups | none new (only a `personal_group` robustness fix in `pbx/consumers.py`) | existing `test_access_ws_consumers` |
| every new staff route (counselling, finance/gl, usage-print, stockcount/daily, phone-alerts, missed-sales, pic-analytics, forecasting) | session (JWT) | new: anonymous caller refused on **every** protected route and method, public gate `off` and `enforce` |

## 8. R4 — branch separation and privacy (same branch)

| Step | What changed | Result |
|---|---|---|
| R4.1 skipped models | `baselines/canary_skipped_models.txt` (ratchet + every line explained) | 2 models, both reasoned: `access.TrustedNetwork` (needs a valid CIDR; admin-only network list) and `users.StaffProfile` (one per user; covered by the role sweep and branch-isolation tests) — matches R0's count |
| R4.2 detail routes | canary sweep also opens the detail route of each planted record (lines `GET-DETAIL …`) | 28 cross-branch detail reads; 27 reasoned (B-2 customer reads, shared configuration, vouchers chain-wide, HQ-only modules incl. insurance, stock-audit management); **1 fixed**: forecast scenario results now follow the caller's branches (+ chain total), help updated |
| R4.3 feature flags | `sweep.FEATURE_FLAGS_ON` in every sweep (daily counts, usage print, missed sales, call-backs, counselling content) | those screens are checked instead of answering 503 |
| R4.4 Finance GL | `test_gl_company_scope.py`: every branch role holding EVERY ledger action is refused on every GL route and method, log and enforce; the same user lifted to all branches passes (proves it is the branch rule) | green |
| R4.5 logs and errors | `test_privacy_logs.py`: a SOFTECH failure carrying a connection string, password and token; a planted customer phone + PIC; every route × GET / POST {} by admin, another branch and a no-phone user, with every log record captured | **3 fixes**: (1) `POST /api/insurance/sync-cache/` returned the raw driver error (connection string, password) to everyone → `public_error`; (2) `public_error` showed admins the raw text → `core.errors.redact()` masks credentials (hosts stay for IT); (3) five loggers wrote passwords / tokens from exception text (`isr_views`, `discount_approvals`, `incentives`, `insurance.sync`, `django.request`) → `core/log_redact.py` redacts every record process-wide before any handler |
| R4.6 WhatsApp payloads | phone canary runs with the flags on and checks the records behind call-backs (CDR calls), counselling cards, WhatsApp conversations and phone alerts are planted | **1 fix**: the missed-sales list showed the customer's full number to own-branch staff with `can_see_customer_phone = False` → `record_phone()` (D2/D3), help updated |

No log line carried the planted phone number (11-digit or +20 form) or PIC — the test keeps checking
both. The log redaction itself masks credentials only, not phones: masking is a display rule and IT
traces sends by number. Owner question **Q-6**: should phones also be masked inside
`logs/platform.log`? Default: no.

## 9. Handed over

- **R7 (per-app tests):** 93 new `role_crashes` lines — 500s that appear only on real records
  (transits list / detail / exports, reservation detail and images, demand actions, insurance client
  deletes, forecasting generate …). List in `baselines/role_crashes.txt` under the
  round-2 reason.
- **Test-runner note:** `manage.py test --parallel` closes the database connection under the sweeps
  (every later request fails "connection already closed"); run the security sweeps serially. Serial
  timings on this machine: canary sweep ≈2.5 min, role sweep ≈25 min, whole security suite ≈2.5 h
  while three sibling sessions shared the machine.
