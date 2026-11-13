# Branch classification, crews (الأطقم) and "new value" robustness — design

Date: 2026-11-13 · Status: design, awaiting owner approval · Owner decisions quoted as "owner".

## 1. Why

Before go-live the system must treat every master list as open-ended. Today a new branch,
role, job title, item code or customer channel is silently dropped, mislabelled or — in one
case — crashes an export. The call center is modelled seven different ways, one of them a fake
branch (`CC`), and the owner wants more cross-branch people groupings than just the call center
("the pharmacists across all branches", "the pharmacists of certain branches") as targets for
data, insights and reports.

Success: adding a branch, a person, a job title, a role, an item value, a PIC or a new module
needs no code change to show up correctly in every list, report and export — and CI catches the
code that would break that.

## 2. Findings this design rests on (sweep of 2026-11-13)

Branches (6 live = HQ 100 + 130/140/150/160/170; 7 closed = 110/120/180/190/200/210/220; `CC`;
test branch `B01`, closed by owner on 2026-11-13 on the office-laptop DB only):

- `Branch.kind` (hq / retail / call_center / closed, `apps/branches/models.py`) is the curated
  truth, but only ~10 call sites use it. 24 use `is_active`, 12 use `is_operational`, to decide
  "is this branch live". `is_active` is True for every synced row, closed ones included.
- `/api/branches/` (`apps/branches/views.py:33`) filters on `is_active` only, so `CC` and closed
  branches appear in every frontend branch picker (49 `branchesApi.list` callers). The frontend
  never reads `kind`; `SettingsPage.jsx` labels "مغلق" from `is_active`.
- Branch sync (`apps/sync/tasks.py:460`) creates a new SOFTECH branch with model defaults →
  kind=retail, is_operational=True. That is how `B01` became a live branch.
- Fixed branch lists: `apps/forecasting/kpi_export.py:54-57` (5 slots — a 6th live branch raises
  IndexError), `:495`; `apps/purchasing/views.py:1142` (v2 pivot, new branch silently missing);
  `apps/pbx/management/commands/classify_pbx_extensions.py:17-35`; finance GL
  `apps/finance/gl/seed.py:18-32` (fails loudly as an exception — acceptable), `manual_import.py:88`,
  `softech_stock.py:22`.
- HQ `'100'` is a local constant in 13 modules. Quarantine/closed stores 102/103/105/110 have two
  central homes (`catalog.models.EXCLUDED_STORE_CODES`, `apps/batches/store_roles.py`) plus 13
  literal copies; store 110 is not in `EXCLUDED_STORE_CODES`.

Call center — seven representations: role `call_center`; fake Branch `CC` created by
`get_cc_branch()` (`build_call_center_rollups.py:25`, which does not set `kind`, so on a fresh DB
it is kind=retail); `Branch.KIND_CALL_CENTER` (unused); SOFTECH `crmbranchcode='100'`;
`CallCenterConfig.sales_agent_usercodes` / `call_agent_extensions`; fixed PBX `AGENT_EXTS`;
source enums on delivery/demand/followups. `KpiActualRollup` rows for the call center hang off
the `CC` branch row.

People: the permission role is not the job (office DB: 83 of 88 active staff are `salesperson`, no
pharmacists). `hr.Employee` (Attendance Stage 1) already holds job title, branch, SOFTECH user
code, start/end dates and the login link, imported from the payroll workbook
(`apps/hr/attendance/employee_import.py`). Owner: "the payroll workbook job title is reliable, use
it". Nothing keeps history of a person's job or branch.

Roles: ~180 inline role checks backend, ~185 frontend, 7 frontend role-label tables;
`utils/roleLabels.js` lacks `supervisor` and `quality_manager`, so the user-management dropdown
cannot assign them (live bug). Item codes: medicine_type `'10'` (medicine) and `'60'` (gifts)
fixed in several modules. Customer channels: `ptclassifcode` meanings conflict between
`followups/models.py:401`, `pos_orders/models.py:23` and `replacement/config.py:55`; an unknown
code silently becomes "home delivery".

## 3. Goals, non-goals, anti-goals

Goals
- One authority for "what is this branch" (`kind`), used everywhere.
- A new SOFTECH branch never goes live by itself.
- A first-class, dated, cross-branch people grouping — **crew (طاقم)** — with its own screen.
- The call center becomes the first crew; the `CC` fake branch retires.
- Every export/report iterates the live data, not fixed lists.
- CI tests that prove a new value flows through, and a static guard that blocks new fixed lists.

Non-goals
- Changing SOFTECH. All of this is read-only toward SOFTECH; no new write.
- Using crews for permissions. Crews say whom a report is about, never who may open a screen.
- Rewriting the permission system (piece 3 only centralises role names and labels).

Anti-goals (a failure even if it "works")
- A crew that rewrites history: editing membership must never change a past month's figures.
- Closed branches vanishing from history: their past sales stay attributed and filterable.
- Another parallel call-center definition left behind after the move.

## 4. Approaches considered

For the cross-branch grouping (owner picked the first):
1. **A new crew concept with dated members** — people, not logins; rule + manual membership;
   reports filter by crew beside branch. Picked: fits "pharmacists of certain branches", keeps
   branches meaning places where stock and sales happen.
2. More `Branch.kind` values (call center, pharmacists …) — rejected: a pharmacist group is not a
   place; stock, transfers and exports would keep tripping over it.
3. Django auth groups — rejected: they are permission groups (the confusion the owner wants to
   avoid) and have no rule-based or dated membership.

Membership history (owner picked dated): a March report counts who was in the crew in March.

Name (owner): «طاقم / Crew» — unused anywhere in the code; «فريق» (gamification teams), «شريحة»
(customer segments) and «فئة» (insurance billing groups) are taken.

For branch classification there was one sensible way: make `kind` the authority (it already
exists and is curated); the alternatives (fix each `is_active` filter in place, or add more
booleans) leave three competing truths.

## 5. Piece 1 — branch classification (full)

5.1 `kind` gains **`pending` («جديد — بانتظار التصنيف»)**. Branch sync creates any new SOFTECH
branch as `pending`, `is_operational=False`, `pos_enabled=False`, and sends an admin notification
(existing notifications app, a new type). Pending branches are excluded from live lists and
exports and from analytics until an admin classifies them. Existing rows are not touched by sync
(kind stays curated, as today).

5.2 Meanings, written once in the model docstring and help:
- `kind` — what the branch is (the only "is it live" test).
- `is_operational` — temporarily paused (stock count, maintenance) for a live branch; never used
  to decide live vs closed.
- `is_active` — kept for history attribution only; no new code filters on it.

5.3 One helper set on `BranchQuerySet`: `live()` (hq + retail), `retail()`, `hq()` (single row,
raises if not exactly one), `closed()`, `pending()`, plus a module-level `hq_code()` cached
helper. Every "is this branch live" filter in the sweep (24 `is_active`, 12 `is_operational`,
the 4 listing `Branch.objects.all()` calls) moves to these. Label maps over `all()` stay.

5.4 `/api/branches/` gets `?scope=live` (default — pickers), `live_hq`, `all` (history filters;
closed rows carry `kind` so the UI marks them «مغلق»), `pending` (admin). The serializer exposes
`kind` and `kind_label`. The frontend `BranchSelect` passes a scope; history/report filters get a
«إظهار الفروع المغلقة» toggle. `SettingsPage` shows `kind`, not `is_active`.

5.5 **Branch display order**: new `Branch.display_order` (integer, editable on the branches
settings screen; initial values reproduce the owner's legacy order 160, 170, 140, 150, 130, then
code). Replaces `LEGACY_BRANCH_ORDER` and `BRANCH_ORDER`. A shared `branch_column_order()` (the
ISR exports already have one in `apps/purchasing` — reuse/move it to `apps/branches`) is used by
every per-branch export.

5.6 Exports fixed: KPI export (`kpi_export.py`) lays out branch blocks dynamically — owner
2026-11-13: nobody reads it at fixed cells, "the layout simply grows: branches, then totals, then
call center" (then any other crew with targets); row geometry and every formula reference are
computed from the number of retail branches; purchasing v2 pivot iterates `live()`; PBX extension
classification reads extensions from crews (piece 2) and branch phones from data, not a list.
Finance GL per-branch account maps stay in the finance rules (they already fail loudly into the
exceptions queue); the doc adds a help note that a new branch needs its cash account mapped.

5.7 HQ `'100'` literals → `hq_code()`. Store exclusions: `apps/batches/store_roles.py` becomes the
single registry (with its SystemSetting override); `EXCLUDED_STORE_CODES` is derived from it; the
13 literal copies import it. Owner 2026-11-13: **store 110 and every store of the test branch
`B01` are excluded from catalog and POS stock too** — generally, every store of a branch whose
kind is `closed` (or `pending`) is excluded everywhere, which covers both. Stock figures on those
screens drop by what is booked there; the plan states the before/after totals.

5.8 Data migration: `B01` → closed (if the row exists — production gets the change the office
laptop got by hand); `CC` row → see §6.6.

## 6. Piece 2 — crews (الأطقم) (full)

6.1 Person. Crew members are **people**, identified by `hr.Employee` (payroll workbook master).
One person carries their system login (`staff`), SOFTECH user code and — new — PBX extension(s),
so a crew report catches sales, calls and in-system work together. A crew may also hold a person
with no `Employee` row only via a manual SOFTECH user code / extension entry (call-center agents
missing from payroll) — see §9.

6.2 Dated job and branch history. New append-only `EmployeeAssignment` (employee, job_title,
branch, valid_from, valid_to). The payroll import writes a new row only when job title or branch
changes (closing the previous one at the import date). Go-live seeds one row per employee from
the current workbook, valid_from = the employee's start date (or 2020-01-01 when blank): before
go-live we assume today's job and branch.

6.3 Crew model.
- `Crew`: name (unique among non-archived), type (`call_center`, `job`, `custom`), description,
  is_archived, created/updated by/at.
- `CrewRule` (zero or more, versioned by valid_from/valid_to): job titles (set), branches (set),
  departments/sections (set; optional). A person matches a rule on a date when their assignment
  on that date matches every non-empty set. Several job titles in one rule are allowed (owner:
  "groups carrying different people with different job titles").
- `CrewManualMember`: person, include or exclude, valid_from, valid_to, reason.
- Membership on date D = (matches an active rule on D ∪ manual includes active on D) − manual
  excludes active on D.

6.4 Resolver (deterministic, one place, `apps/crews/membership.py`):
`members(crew, date)`, `members_between(crew, start, end)` → per-person date spans,
`identities(crew, start, end)` → SOFTECH user codes / extensions / staff ids with their spans,
for report joins. Every report that filters by crew uses this; no module re-derives membership.
Edits apply from a chosen date and never rewrite earlier spans (rule and manual rows are
end-dated, not edited in place).

6.5 Screen «الأطقم» `/crews` (desktop; RBAC module `crews`, actions view/edit; admin by default):
list (name, type, current member count, last change); create/edit with rule pickers filled from
live data (distinct job titles from `EmployeeAssignment`, live branches) so new values appear by
themselves; manual add/exclude with dates and reason; live preview of who matches before save;
history tab (who entered/left when, and every crew change). Delete: a crew never used by a report
or rollup is deleted; otherwise archived (hidden from pickers, name kept in past reports). Every
change is audited (AuditLog, before/after). In-app help `apps/help/content/crews.py` (AR + EN).
Sortable grids, keyboard per the review-grid convention.

6.6 Call center move.
- A seeded crew «الكول سنتر» (type `call_center`) built from today's
  `CallCenterConfig.sales_agent_usercodes` + `call_agent_extensions` + PBX `AGENT_EXTS`, as manual
  members dated from the earliest month with call-center rollups.
- `build_call_center_rollups` reads agents from the crew (`identities`), not `CallCenterConfig`
  lists; those two fields become read-only and are then removed after one release.
- `KpiActualRollup` gains nullable `crew` FK (branch becomes nullable; check constraint: exactly
  one of branch/crew). Existing `CC` rows move to the crew. KPI board / KPI export / forecasting
  references show the crew as its own block, not as a branch.
- The `CC` Branch row is kept (kind `call_center`) only until nothing references it, then kind →
  closed; `get_cc_branch()` is removed. The `'CC'` literals listed in §2 go.
- SOFTECH `crmbranchcode='100'` (delivery/sync) stays as the SOFTECH fact it is; the doc only
  labels it "call-center order recorded on HQ".
- Role `call_center` stays a permission role.

6.7 Reports gaining a crew filter in this piece: KPI board and export, call-center KPIs,
PIC analytics per salesperson, gamification rankings. Others adopt it later through the same
resolver.

6.8 What a crew's figures mean (builder-check calls, owner may override):
- A crew's figures are the work **stamped with its members' identities** in the span they were
  members — sales by their SOFTECH user codes, calls by their extensions, system actions by their
  logins — exactly as the call center works today. Not the sales of the branches they sit in
  ("crew = who, branch = where"; a branch filter narrows it to work done at that branch).
- Sales credit = SOFTECH `stktransm.usercode` (the seller), never `cashiercode`. Verified on HQ
  `stktransm`, doccode 115, Oct 2026 (read-only, 2026-11-13): every branch invoice carries both;
  `usercode` ≠ `cashiercode` on ~99% of them; `usercode` is a named seller (10–16 per branch),
  `cashiercode` is one of 2–3 shared cashier-station accounts per branch (SOFTECH user group 17,
  «cashir 2 130» …). This is what `PurchaseHistory.softech_user` already mirrors.
- Gap found: at least ~3,300 of ~22,400 October invoices (~15%) carry a generic or management
  account as seller (Admin 10, a cashier-station account, and a few management-group users) —
  those sales cannot be credited to a person. The crew screen shows them as «بائع غير محدد» per
  branch so the share is visible; fixing the habit at the till is an operations matter.
- A crew shows as **its own block/row**, not as a filter over branch blocks.
- **Rollups are written only for `call_center` crews** (as today). Other crews are computed live
  from the mirror through the resolver. Because membership spans are end-dated, never edited, a
  live recompute of a past month gives the same answer.
- Seeding the call-center crew: today's `CallCenterConfig` user codes and extensions and PBX
  `AGENT_EXTS` become manual members, matched to an `Employee` by `softech_usercode` where one
  exists, else kept as a bare user code / extension (flagged «خارج كشف الرواتب»), dated from the
  earliest month with call-center rollups. That is exactly what the current rollups assumed, so the
  acceptance check is: rebuilt call-center rollups equal the existing `CC` rows for every month.
  `hr.Employee` gains department/section on `EmployeeAssignment` and a PBX extension list.

6.8b Targets and forecasts (owner 2026-11-13: "all crews"): **every crew can carry targets,
forecasts and incentives**, not only the call center. `incentives.SalesTarget` and the forecasting
scope (`ForecastScenario` / `ForecastResult`, `ForecastEngine._members`) gain a crew scope
alongside branch (exactly one of the two). Crew actuals come from §6.8 (rollup for call-center
crews, live resolver for the rest — the target engine reads both through one function).
Historical `CC` forecasts, targets and rollups are migrated to the call-center crew **value for
value**; acceptance test: every past month's achieved, target and achieved-vs-target result, and
every incentive figure derived from them, is identical before and after. Only then does the `CC`
row go to kind closed. Because this touches incentive money, the plan for this step stops for
owner sign-off on the before/after comparison before it is merged.

6.9 Analytics branch set (call): analytics, forecasting and the KPI board keep using **retail**
branches (HQ stays out, as today). A temporarily paused (`is_operational=False`) retail branch
still counts in analytics — a pause is days, its month is real. The owner-editable
`analytics_excluded_branches` setting stays as an extra exclusion on top of `kind`.

## 7. Pieces 3 and 4 — outline (own design pass each)

Piece 3 — roles: one role registry (`ROLE_CHOICES` + Arabic/English labels) served by the API;
the 7 frontend label tables replaced by it (fixes the supervisor / quality-manager dropdown bug
first, as a small fix); inline role lists replaced by permission checks where a matrix entry
exists; a new role fails closed by default.

Piece 4 — item and channel codes: medicine-type meanings (`10` medicine, `60` gifts) and the
customer channel (`ptclassifcode`) meanings move into one editable mapping (reusing
`ChannelBucketMap` / SystemSetting style already present), the three conflicting tables reconciled
against SOFTECH; an unknown code shows as «غير مصنف» instead of a guessed bucket.

## 8. Guards that keep it true (grow with each piece)

- **New-value test** (`apps/tests/test_new_values.py`): plants a 7th live branch, a pending
  branch, a new job title, a crew, (piece 3) a new role, (piece 4) a new medicine type and
  channel; runs every registered per-branch export and report; asserts nothing crashes, the new
  live branch appears, pending/closed/CC do not appear where live-only is meant. A registry of
  exports/reports lives next to the test so a new module adds itself (CLAUDE.md "definition of
  done" gains this line).
- **Static guard** (alongside `apps/tests/security/static_scan.py`): fails on new code that
  filters branches by `is_active`/`is_operational` for liveness, writes literal lists of branch
  codes or `'100'` as HQ, or literal role lists, outside a reasoned allow-list baseline (ratchet:
  existing hits listed, the list only shrinks).

## 9. Left to the builder / small calls made (owner may override)

- People not on the payroll workbook (e.g. a call-center agent paid elsewhere): allowed as a
  manual member by SOFTECH user code/extension only; flagged «خارج كشف الرواتب» on the screen.
- Initial `display_order` = legacy order, then by code.
- Notification recipients for a pending branch: admins.
- Order of delivery: piece 1 → piece 2 → (supervisor/QM dropdown fix can ship any time) → 3 → 4,
  each its own plan and PR, each passing the new-value test and the static guard.

## 10. Safety and project rules

No SOFTECH writes. Branch scoping (`core/branch_scope`) unchanged; crew data is company-level and
visible to holders of the `crews` module permission. New module: `MODULE_BY_PREFIX` entry,
`MODULE_CHOICES` + `seed_permissions` row, PERMISSION_MATRIX regenerated, view + permission tests,
canary planter can build the models. Everything audited. Help updated for `/crews`, branches
settings, and every screen whose branch picker changes behaviour.
