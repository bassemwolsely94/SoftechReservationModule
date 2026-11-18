# Role-by-role UAT before go-live â€” design

Date: 2026-11-16 آ· Branch: `claude/role-uat` آ· Status: approved by owner 2026-11-16

## 1. Intent

Before the new system goes live, prove through the **real screens** (not just the API) that the
foundation holds for every role / user group:

- every screen is visible or refused exactly as the approved permission table says;
- every button is visible or hidden exactly as that table says;
- every role's daily workflows actually work end to end;
- customer phone numbers stay masked for users who must not see them;
- one branch's data never shows to another branch's users;
- all of this on production-sized data, and with several users working at once.

Success = a findings report the owner can act on (each gap: role, screen, what was wrong, severity),
plus an automated suite that can be re-run at any time (after fixes, before cutover, after cutover).

## 2. Goals / non-goals / anti-goals

Goals
- All 10 roles in `apps/users/roles.py` (admin, call_center, pharmacist, salesperson, purchasing,
  delivery, viewer, supervisor, quality_manager, accountant), desktop **and** mobile `/m/*` screens.
- Users with special branch shapes: home branch only, extra `allowed_branches`, `restricted_branches`,
  `can_see_customer_phone` on/off.
- A handful of **real users** (on the copy only) so their real grants/caps are exercised.
- Light concurrency on the copy (5â€“10 simulated users) to find slow screens on real volumes.

Non-goals
- The full 20â€“40-user load test (stays on the VPS, Stage A, using the existing `deploy/loadtest/locustfile.py`).
- Penetration testing.
- Fixing every finding inside this project â€” fixes are separate batches the owner approves.

Anti-goals (a failure even if the tests "pass")
- **Any write reaching SOFTECH, the tax authority, WhatsApp/SMS, or the PBX from a test.**
- Testing on the office writer instance or its database `elrezeiky_db`.
- Silently "fixing" permissions to make tests green. A mismatch is reported; the owner decides.
- Duplicating the existing API sweeps (`apps/tests/security/`) â€” the UI suite complements them.

## 3. Constraints (found in recon)

- The repo `.env` / office runtime is the **live SOFTECH writer** (24 write switches on). Never used here.
- Existing pieces to reuse, not rebuild:
  - Playwright set-up: `frontend/playwright.config.js`, `frontend/e2e/` (`login.setup.js` per-role
    storage state, `menu-api.spec.js`, `navApi.js`, `knownGaps.js`, `flows.spec.js`, `finance-gl.spec.js`).
  - `config/settings_e2e.py` (reader, all writers forced off, blank messaging keys, own DB, refuses `elrezeiky_db`).
  - `seed_e2e_users` (guarded test-user seeding), `seed_permissions` `PERMISSIONS` = the source of truth.
  - Frontend gating: `navGroups.js` + `navItemVisible`, `usePermission`, `CanDo`, `RouteGuards`.
  - Backend truth for branches/phones: `core/branch_scope.py`, `apps/customers/access.py` `mask()`.
  - `deploy/loadtest/locustfile.py` (on main, never run).
- This PC: 31 GB RAM, ~70 GB free on C:, PostgreSQL 16 service. Parallel heavy test runs have crashed
  Postgres twice â†’ **only one heavy run (restore, sweep, load) at a time**, across all sessions.
- The office DB is ~12 GB and holds real customer data; the copy stays on this PC (same as today).

## 4. Approaches considered

| | Approach | Trade-off |
|---|---|---|
| A | Automated browser suite only | Repeatable, but only finds what we told it to look for |
| B | Hands-on browser pass only | Finds the unexpected, but 10 roles أ— ~210 screens can't be covered by hand and can't be repeated |
| **C** | **Automated sweep + scripted workflows + hands-on pass of high-risk screens** | **Chosen by the owner.** Coverage and repeatability from the automation, judgment where it matters |

Environment: **local copy first** (owner's choice), VPS for the real load test later.

## 5. Design

### 5.1 UAT environment (workstream W1 â€” blocks the runs of everything else)
- `pg_dump -Fc elrezeiky_db` â†’ `pg_restore` into a new DB **`elrezeiky_uat`**, then `migrate` with
  the branch code. Re-runnable by one command/script (`scripts/uat/refresh_uat_db.ps1`), with a
  RAM/disk check first.
- New settings module **`config/settings_uat.py`** modelled on `settings_e2e.py`: never reads `.env`,
  `WRITER_INSTANCE=False`, `SOFTECH_READ_ONLY=True`, no SOFTECH host, every writer flag and every
  `*_SEND_ENABLED` forced off, all WhatsApp/SMS/AMI/AI/ETA keys blank, `SCHEDULER_AUTOSTART=False`,
  `RBAC_ENFORCEMENT=enforce` (what cutover uses), refuses any DB name other than `elrezeiky_uat*`.
  A guard test proves each of these.
- Runs on its own ports (backend 8200, Vite 5200) so it never collides with the office server on 8000.
- `manage.py seed_uat_users` (guarded like `seed_e2e_users`, only under `settings_uat`):
  - `uat_<role>` for all 10 roles in a real branch A; same-role twins in branch B for isolation checks;
  - shape users: multi-branch (`allowed_branches`), restricted branch, phone-visible vs phone-hidden;
  - `--real <username>â€¦` resets the password of chosen real users **on the copy only** (no revert
    needed â€” the copy is thrown away). 2FA is turned off for UAT users on the copy.
  - Writes the credentials to a git-ignored `frontend/e2e/.uat-users.json`; never printed.
- The real-data reference set: the seeder records which real records belong to branch A vs B
  (customers with phones, reservations, transfers, POS ordersâ€¦) so tests know what must / must not show.

### 5.2 Visibility sweep (W2) â€” every screen أ— every role
Generated, not hand-written: routes from `App.jsx` + `navGroups.js`, expected result from
`seed_permissions` (via a small JSON export command, so the frontend tests read the same truth the
backend uses) + `knownGaps.js` owner decisions. For each role أ— route:
- menu item shown / hidden as expected;
- direct URL: screen renders, or is refused cleanly (no blank page, no crash, no endless spinner);
- console errors and failed API calls (5xx) recorded;
- page load time recorded (feeds the slow-screen list).

### 5.3 Button visibility (W3)
Action buttons gated by `CanDo` / `usePermission` get a stable `data-perm="<module>:<action>"`
attribute (one small change in `CanDo` + the hook users). The sweep then checks, per role and screen,
that every rendered `data-perm` button is allowed and that allowed primary actions exist. Buttons
gated by hard-coded `user.role` checks (82 spots) are listed and checked against the table; mismatches
are findings.

### 5.4 Data exposure (W4) â€” phones and branches, on screen
- **Phones:** on every screen that shows customers, the rendered page text and the API responses are
  scanned for the full number of known reference customers. A phone-hidden user, or a user from
  another branch, must only ever see the masked form.
- **Branches:** branch-B users visit list/detail screens; the page text and responses must contain no
  branch-A reference record (number, customer, invoice). Multi-branch and restricted users are checked
  for exactly their allowed set.
- Includes mobile `/m/*`, exports (Excel downloads are opened and scanned), and search boxes (Ctrl+K,
  item/customer search).

### 5.5 Workflows per role (W5)
Scripted Playwright journeys, one file per area, each run as the roles that do that work, plus a
"must be refused" check for roles that must not. Areas (first cut): reservations, demand + follow-ups,
transfers, POS up to cashier-ready (push asserts dry-run), shortage, stock count / daily count, approvals
(operational + pricing), insurance claim review, supply / ISR review, delivery dispatch, call center
case, GL entry, HR attendance/leave, vouchers. Every created record is tagged `UAT-` in a note field
where possible.

### 5.6 Hands-on pass (W6)
After the automated runs, I drive the browser as each role over the high-risk screens (customer 360,
POS, approvals, finance, insurance, exports, user management) looking for what scripts miss:
confusing states, wrong wording, broken RTL layout, actions that look possible but fail.

### 5.7 Light load on the copy (W7)
Run the existing locustfile (extended with the UAT users' role mix) at 5 â†’ 10 users for 10 minutes
against `settings_uat`, with the scheduler off. Output: slowest endpoints and screens on real volume.
The 20â€“40-user test stays on the VPS.

### 5.8 Report (W8)
`docs/uat/2026-11-role-uat-report.md`: summary per role, findings table (id, role, screen, expected,
actual, severity P0â€“P3, evidence screenshot path), slow-screen list, and the list of owner decisions
needed. Each finding â†’ owner decides fix / accept / defer.

## 6. Parallel execution

- W1 is built first (small); it is the only thing the runs depend on.
- W2, W3, W4, W5 (and W7's script) can be **built** in parallel in separate sessions/worktrees
  against the tiny e2e fixtures, each touching its own files (`frontend/e2e/<area>/â€¦`). Shared
  helpers (UAT user loader, reference-data loader) are written in W1 so they don't collide.
- **Runs** against the 12 GB copy are serialized â€” one at a time â€” because of the PC's memory history.
- W6 and W8 come last.

## 7. Calls I made (owner can overturn)

- `RBAC_ENFORCEMENT=enforce` on the copy, since cutover uses it. Findings that only appear in enforce
  mode are still real for go-live.
- Dedicated `uat_*` users + a few real users with reset passwords on the copy â€” no reverting needed.
- 2FA disabled for test users on the copy only; 2FA itself is already covered by backend tests.
- Test transactions stay inside the copy; SOFTECH, tax, WhatsApp, SMS and PBX are unreachable by settings.
- `data-perm` attributes on buttons are the one product-code change; everything else is test code.

### 7.1 Rules settled after the builder check

- **Truth = the live permission rows as restored**, because that is what go-live gets. The UAT seeder
  must **never run `seed_permissions`** on the copy. A separate check compares the live
  `RoleModuleAccess` rows with the code `PERMISSIONS` and reports every difference as a finding
  ("drift"). Expected results for sampled real users come from the backend's own resolvers
  (`core/branch_scope`, `apps/customers/access.py`, per-user grants/caps) exported to JSON by one
  management command, not re-derived in JavaScript.
- **Branch isolation follows the decisions already made**, not a stricter guess: B-1 finance
  all-branch roles, B-2 another branch's customer may open by full-phone lookup but phones show masked,
  B-3 supervisor/QM all-branch; all-branch roles in `roles.py`; the reasoned lines in
  `baselines/branch_canary_leaks.txt` and `phone_canary_leaks.txt`. Each screen/domain gets one rule:
  *must be absent* / *may appear masked* / *may appear in full*. A case none of these covers is
  reported as "decision needed", not as a P0.
- **Hidden-but-served pairs in `knownGaps.js` are owner-accepted**: a direct URL rendering is a pass.
- **Role-hard-coded buttons (W3):** the automated check covers `CanDo` / `usePermission` buttons. The
  hard-coded `user.role` buttons are catalogued with an inferred module:action, marked
  "inferred â€” needs confirmation"; a role check stricter than the table is a P3 finding, looser is P1.

- **Owner decision (2026-11-16): on the copy only, scripts may push POS orders and approve pricing /
  discount requests end to end.** This is safe only because `settings_uat` makes SOFTECH unreachable
  and every writer flag off; each such test first asserts `writer_status` = reader and that the push
  result is a dry run. This approval does not extend to any other environment.

## 8. Left to the builder

Exact file layout under `frontend/e2e/`, the JSON export format for expected permissions, which
real users to sample (proposed: one branch manager per role that exists in real data), screenshot
naming, and severity rubric details.
