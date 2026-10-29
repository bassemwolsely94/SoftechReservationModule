# Security Suite — Batch 4 (authorization) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** a role can do on the server exactly what the code matrix (`seed_permissions.PERMISSIONS`)
gives it — no more — whether `RBAC_ENFORCEMENT` is `log` or `enforce`, and switching production
to `enforce` breaks no screen.

**Flow:** same as Batches 2–3 — failing test `@pending('Z-<n>')` + `PENDING.md` line →
`scratch/batch4/Z-<n>.patch` → owner OK → apply, run, next. Payments, POS and pricing views
always stop for the OK (design §Stop-and-ask).

**Spec:** [design](../specs/2026-10-26-full-security-test-suite-design.md) Batch 4 row ·
[TEST_SUITE.md](../../security/TEST_SUITE.md) role-sweep classification.

## Verified (2026-10-27)

Production runs `RBAC_ENFORCEMENT=log` (settings default, DEPLOY.md, VPS runbook): the middleware
only logs, so every view that checks `IsAuthenticated` alone is open to every role.

| Baseline | Lines | Meaning |
|---|---|---|
| `role_leaks_log` | 1391 | matrix denies, the view let it through (1012 GET, 379 POST; every non-admin role) |
| `role_leaks_enforce` | 0 | with `enforce` the middleware blocks all of them |
| `role_softech_reach` | 6 | denied role still opened a SOFTECH connection |
| `role_outside_reach` | 18 | denied role still started a job / thread (background triggers) |
| `unclassified_api_prefixes` | 3 | `tasks`, `recommendations`, `stock-audit` — middleware never checks them |
| `role_overblocks` | 683 | matrix grants, view answers 403 (owner review — not a leak) |
| `role_unproven` | 1228 | admin got 404 too (id 1 missing) — the check was never reached |

Largest leak groups: purchasing 200, procurement 162, finance 116, forecasting 99, pos-orders 84,
callcenter 50, followups 49, batches 48, chronic 43, sync 40, users 35, pricing-approvals 35.

**Enforce would break shared reads.** `logs/platform.log` (this PC, 2026-10-26/27 only) shows
`would-deny` for reads every screen makes: `/api/users/my-permissions/` (permission store, every
role), `/api/sync/freshness/` + `/api/sync/status/` (DataFreshnessBar on most modules). A role
without `users`/`sync` view would lose its menu and freshness bars the moment `enforce` is on.

**Other gaps:** POST maps to any of create/edit/approve/assign/finalize/export in the middleware,
so `create` on a module also passes its approve/finalize endpoints; the sweep sends only GET and
POST `{}` (no PUT/PATCH/DELETE); 14 `fields = '__all__'` serializers (mass-assignment candidates,
e.g. `apps/payments`, `apps/insurance`).

## Items (order: risk first)

| Z | What | Ask? |
|---|---|---|
| Z-1 | Middleware gaps: map `tasks` / `recommendations` / `stock-audit`; own-data reads (`users/my-permissions`) exempt, `sync/freshness` + `sync/status` GET read-open; sweep adds PUT/PATCH/DELETE | yes (all roles) |
| Z-2 | Background triggers any role can fire (the 24 reach lines): enrichment batches/recompute, finance trigger-discover/sync, purchasing trigger/sync-items/seasonality/catchup, forecasting kpi-board refresh, pricing replication item, ISR fulfilment recent | pricing part: yes |
| Z-3 | finance + payments + cheques (145) — `MatrixPermission` / `deny_unless`, per-action (`approve`, `export`) | yes |
| Z-4 | users + audit + sync + config (≈110) | — |
| Z-5 | pos-orders + offers + commerce (128), incl. DELETE | yes |
| Z-6 | pricing-approvals + approvals (≈40) | yes |
| Z-7 | purchasing + procurement + forecasting + supply + transits + invoices (≈510) | — |
| Z-8 | customer data: callcenter, omni, pbx, whatsapp, campaigns, chronic, composition, followups, reservations, demand, transfers (≈280) | — |
| Z-9 | catalog (batches, images, enrichment, items), incentives, hr, analytics, insights, insurance, vouchers, shortage, stockcount (rest) | vouchers: yes |
| Z-10 | mass-assignment: `__all__` / writable status, branch, approver, amount fields | payments: yes |

Each Z: `role_leaks_log` lines for its prefixes go STALE → deleted; the module's own tests stay green.

### Progress (2026-10-28)

Applied (uncommitted): Z-1 … Z-6, Z-5c (per-module seeding + no grants cache under tests), Z-7a
(purchasing / procurement / invoices / ISR / rates), Z-7b (Market Shortage / Phantom / Cash
Optimization / Forecasting), Z-7c (transits / pick zones). Z-7 closed 497 leak and 233 unproven
lines. Baselines now: `role_leaks_log` 449 (from 1391), `role_unproven` 754 (from 1228),
`role_crashes` 25, `role_softech_reach` / `role_outside_reach` / `unclassified_api_prefixes` 0.
Z-8 splits into Z-8a (chronic / composition / follow-ups / reservations), Z-8b (call center /
omni / pbx / WhatsApp / campaigns), Z-8c (demand / transfers).

Z-8 (2026-10-28, applied, uncommitted): Z-8a / Z-8b / Z-8c closed 259 leak and 450 unproven lines.
Baselines now: `role_leaks_log` 190, `role_unproven` 304, `role_overblocks` 742 (of which 99 are
reviewed quality_manager writes: it holds view + export on chronic / followups / reservations /
callcenter / demand / transfers and the middleware counts export as a write grant — an
overblock-review item: make the middleware's write tuple exclude export, or keep the reasons).
`core.permissions.matrix_permission` gained `edit=` / `delete=` / `actions=`. Open from another
session: `apps/customers/management/commands/relink_purchase_customers.py` trips
`test_no_sql_built_from_text` (dates only — not injectable — but needs bound parameters or a
reviewed baseline line).

Z-9 (2026-10-28, applied, uncommitted): Z-9a (analytics / insights / incentives / HR shifts),
Z-9b (batches / expiry / images / catalog / enrichment), Z-9c (stock count / shortage lists / QA /
customers / delivery locations), Z-9d (vouchers — owner sign-off). Baselines now: `role_leaks_log`
2 (the two config `settings/by_key` POSTs reviewed in Z-4), `role_unproven` 87, `role_overblocks`
772, `role_crashes` 21 (Batch 7), `role_softech_reach` / `role_outside_reach` /
`unclassified_api_prefixes` 0.

Z-10 (2026-10-28, applied, uncommitted) — mass assignment, three diffs, 31 attack tests in
`test_mass_assignment_{money,workflow,who}.py`, each failing first:
- **Z-10a (SOFTECH / money, owner sign-off):** supplier-invoice generic PUT/PATCH closed (a PATCH
  could re-open a finalized invoice and clear its docnumber → a second SOFTECH push); payments
  editable only pending / disputed, deletable only pending; payment exceptions read-only apart
  from resolve / dismiss / assign; POS `softech_branchcode` always the order's branch, cashier not
  client-set, branch / store / seller / channel / kind fixed after create; insurance claim generic
  PUT/PATCH closed (create already safe), supplements stay on their claim; cheques change only on
  an active plan and cleared / cancelled are final; delivery value closed from out-for-delivery;
  vouchers: customer only through assign, value fixed once used or assigned.
- **Z-10b (workflow / points):** stock-count, follow-up, shortage-list and invoice-bundle generic
  PUT/PATCH closed (status there was free gamification points); tasks changed / cancelled only by
  creator, assignees, supervisor or admin; call-log `quality_score` / `handled_by` / AI fields
  read-only; availability status / operator / fingerprint read-only; incentive adjustments refused
  on a finalized settlement (old or new period) and for yourself.
- **Z-10c ("who" / posted records):** HR requester cannot nominate themselves (or the subject) as
  approver; procurement alerts resolved in the caller's name; statement `imported_by` and mapping
  `mapped_by` server-set; supplier invoices frozen (header / lines) once queued / pushing /
  finalized; every payment edit logged before → after.
Left open for the owner: edits to a *confirmed* invoice (no reopen action; push failures need
fixes), self-approval in the shared approvals engine (touches discount / price approvals), free
branch choice on transfers / reservations / demand and task visibility (Batch 5 scoping).

Z-11 (2026-10-28 → 29, applied, uncommitted) — the overblock review
(`2026-10-28-batch-4-overblock-review.md`, all proposals accepted):
- **Z-11a** `export` is no write grant: the middleware's POST tuple drops it; analytics POSTs, the
  transit picking / stocking sheets and QA filing keep taking it; call scoring, transcript
  correction, a count's item preview, an incentive dry run and cancelling one's own HR request map
  to view; the replacement gate needs a write grant before body validation. Quality manager /
  purchasing lose the writes their views let through on export (customer notes / receipts,
  loyalty, referral, transit notes) — real grants if wanted.
- **Z-11b** the sweep skips a method the view does not implement (`routes.handles`) — 161 noise
  lines gone, sweep ~2× faster. **Z-11c** 317 kept overblocks under 21 `# reason:` blocks.
- **Z-11d** payment confirm = finance approve (purchasing too). **Z-11e** the six lost-demand
  analytics pages = analytics view. **Z-11f** the omni wallboard opens to call center (owner;
  listen / whisper stay admin / supervisor, buttons hidden for others). **Z-11g** purchasing runs
  catch-up / items sync (engine-run rule); the expiry syncs = catalog edit with a 6-hour
  no-double-run guard. **Z-11h** discrepancy report for supervisors; flag summary / staff audit
  trail for the quality manager.
- **Z-11i** (owner): supervisors run stock counts, supervisors + call center classify chronic items
  — code matrix + data migration `users.0032` (turns only those rows on); mobile Reservations /
  Transfers tabs follow the matrix (`pages/mobile/mobileAccess.js`); expiry spawn-count = catalog
  edit (its "or stockcount create" only ever matched pharmacists).
- **Z-11j** (owner sign-off) the approvals engine refuses a requester's own approval (HR,
  quarantine, markdowns, POS offers, rewards, replacement). **Z-11k** (owner sign-off) an edit to a
  confirmed / push-failed invoice sends it back to review, audited.

Baselines after Z-11: `role_overblocks` 352 (all reasoned; was 772 with 615 unreviewed),
`role_unproven` 124, `role_leaks_log` 2 (the reviewed config lines), `role_crashes` 21 (Batch 7),
`role_softech_reach` / `role_outside_reach` / `unclassified_api_prefixes` 0.

### Status against "Done when" (2026-10-29)

- `role_leaks_log` empty — **no**: 2 reviewed lines (pharmacist / purchasing POST
  `/api/config/settings/by_key/`, Z-4) remain.
- `role_softech_reach`, `role_outside_reach`, `unclassified_api_prefixes` empty — **yes**.
- The sweep covers PUT / PATCH / DELETE — **no**: it still sends GET and POST only (listed under
  Z-1, never built). Mass assignment (Z-10) was covered by attack tests instead.
- Overblocks reviewed by the owner — **yes** (Z-11).

Fresh-database run (2026-10-29, `manage.py test apps`, all migrations from scratch): 3,436 tests,
11 failures — 10 from `users.0032` marking the chronic / stock-count matrix "seeded" with two
roles' rows on a fresh install (fixed: it now touches only an already-seeded module; the 10 plus
the matrix / decision suites pass on a new fresh database, 76/76) and the relink command below.
Insurance `RbacTests` passes on a fresh database — the earlier failure was the kept test DB.

Open from Batch 4: the two config leak lines, the PUT / PATCH / DELETE sweep, `confirmed_by` /
an audit entry on invoice confirm, and another session's `relink_purchase_customers.py` that
trips `test_no_sql_built_from_text`.

## Owner decisions (2026-10-27)

1. **Enforce:** production switches to `RBAC_ENFORCEMENT=enforce` after Z-1, at the VPS cutover —
   the middleware closes the 1391 leaks at once while Z-2…Z-10 fix the views underneath.
2. **Approval:** every Z item is a diff the owner approves (not only payments / POS / pricing).
3. **Overblocks:** reviewed per module at the end of Batch 4; not changed before.
4. **Purchasing (Z-2):** the code matrix + SOFTECH supply groups (supply-group members get the
   purchasing role's grants on the purchasing screens).
5. **Offers (Z-5a):** a matrix module of its own, `offers`, under المخزون and not under POS —
   managed by admin / supervisor / purchasing; the checkout's evaluate / apply-to-order stay POS.
   Z-5 splits into Z-5a (offers) and Z-5b (POS orders + commerce).
6. **Purchasing family (Z-7, 2026-10-28):** map by screen — each endpoint follows the module of the
   people who use its screen. Market Shortage → `shortage`; Forecasting, KPI board, scenarios,
   Phantom and Cash Optimization reads → `analytics` (forecast / phantom writes keep their
   admin / supervisor / purchasing checks); procurement, the purchasing engine, ISR / rates and
   invoices → `purchasing` / `invoices` + supply groups; transits → `transfers`. Z-7 splits into
   Z-7a (purchasing / procurement / invoices), Z-7b (shortage / phantom / spike / forecasting),
   Z-7c (transits).

## Done when

`role_leaks_log`, `role_softech_reach`, `role_outside_reach`, `unclassified_api_prefixes` empty;
the sweep covers PUT/PATCH/DELETE; overblocks reviewed by the owner.
