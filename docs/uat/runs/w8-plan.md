# W8 — mobile, rider and 2FA worked through (plan, 2026-11-20)

Owner-approved round: the role UAT (`docs/uat/2026-11-role-uat-report.md`, "Not covered") only
visited the phone (`/m`) and rider (`/rider`) screens and skipped 2FA. W8 works them through per role on
the UAT copy (`config.settings_uat`: reader copy, no SOFTECH, no sends, RBAC enforce). Method, severities
(P0–P3) and the findings format: `docs/superpowers/specs/2026-11-16-role-uat-design.md`.

**Status: built, not run.** The run needs the merge coordinator's go and a migrated copy (below).

## Files

| file | what |
|---|---|
| `frontend/uat/workflows/_w8.js` | shared: live expectations, session guard, refusal / allow checks |
| `frontend/uat/workflows/mfa/mfa.spec.js` | 8 tests, serial, one test user |
| `frontend/uat/workflows/mobile/mobile.spec.js` | 51 tests (12 tabs, 12 creates, 9 cancel, 16 phones, 2 shell) |
| `frontend/uat/workflows/rider/rider.spec.js` | 13 tests (10 gate, 2 shell, 1 journey) |
| `frontend/uat/lib/totp.js` + `totp.test.mjs` | RFC 6238 TOTP with `node:crypto` (no new npm package); `node --test` passes the RFC 4226 / 6238 vectors |

72 tests plus the 19 sign-ins of `login.setup.js`. Playwright runs the files in name order: mfa, mobile, rider.

## Where the expected outcome comes from

From the server, read at run time, never from role lists in the spec:

- **Role matrix.** `GET /api/users/my-permissions/` (`permissions` + `seeded`) for each user.
  The Nov-17 `.uat-expected.json` predates the role review (PR 283). It is used only for branch ids and
  reference customers.
- **Branch rule.** `/api/auth/me/` `can_pick_any_branch` (`core.branch_scope`).
- **Phone rule.** `can_see_customer_phone` + branch scope = `apps/customers/access.py` `phones_visible`.
- **Registry flags.** `qa_inspections` and `mfa_required`, parsed from `apps/users/roles.py`. The QA rule is
  `apps/qa/views.py`: a registry QA role and an hr write grant.
- **No matrix rows.** A module without matrix rows on the copy is not judged. Every spec stops at
  `beforeAll` when `rider` / `dispatch` have no rows, which means the copy is not migrated.

## What each spec checks

### mobile.spec.js (phone-sized Chromium, Pixel 7)
Users: the 10 home roles (branch A 160) + the 4 branch-B twins (150). The delivery role goes to the
shell check instead. The phone check adds `multi`, `restricted`, `phoneHidden` and `phoneVisible`.

| check | per user | expected | finding |
|---|---|---|---|
| tabs | bottom bar + «المزيد» sheet | each `MOBILE_TABS` entry shown iff its grant: pos / reservations / transfers / demand / shortage / delivery / approvals / customers / vouchers / tasks / stockcount `view`; `/m/qa` = QA rule; `daily-count` = `features.daily_count`; the rest always | P2 `screen` on any difference |
| creates | reservation, demand, transfer request (catalogue PANADOL, «حفظ وتقديم»), shortage list + one line, QA round (start → answer one line → submit) | the create grant (QA rule for QA): done through the phone form, saved for the user's branch | P1 `workflow` if a step fails; P1 `branch` if saved for the wrong branch |
| no grant | the same five | `POST` refused 403/404; the `/new` screen does not crash | P1 if allowed; P1 `crash`; P3 `button` if the create control is offered anyway |
| branch picker | each create form | picker shown iff `admin` or `can_pick_any_branch`; a picker's create for the other branch is allowed; a non-picker's is refused (403/400) | P2 `branch` (picker), P1 (server) |
| cancel | 9 home roles with reservations view; admin creates a pending reservation | «إلغاء» offered and the server allows it iff `reservations:edit` (role review decision 6); an edit holder cancels with a reason on the phone | P2/P3 `button`; P2 if the server lets a non-edit role cancel |
| phones | a full-phone search on `/m/customers` for a branch-A and a branch-B reference customer | full number iff `can_see_customer_phone` and (all-branch or the customer's branch is the user's); else masked in the API answer and on screen | P1 `phone` leak, P2 over-mask, P3 search gap — last 3 digits only |
| shell | delivery, delivery@B | `/m`, `/m/reservations/new`, `/m/customers` → `/rider` | P1 |

### rider.spec.js
| check | who | expected |
|---|---|---|
| gate | 10 home roles | `/rider` opens iff `rider:view`. After 0062 that is admin, delivery, supervisor and call_center. Without it the screen is redirected or refused and `my-orders` is not 200. A rider-module holder without a driver profile gets 403 «ليس لديك ملف سائق», and the screen must say so (P3 if blank). |
| shell | delivery, delivery@B | `/`, `/dashboard`, `/m`, `/reservations` → `/rider`; `/security` → `/rider/security`; the security page shows its status card |
| journey | supervisor → call_center → delivery | Supervisor registers or reuses the UAT rider's driver profile. Call center creates a cash order of 49.75 for branch A (API) and assigns it. Rider: `my-orders` contains the order, `my-route` answers, then «قبول الطلب» and «انطلقت» on `/rider`. Ten junk `collected_amount` values (`abc`, `-5`, `NaN`, `Infinity`, `1e999`, `12.345`, `1,000`, `٥٠..٥`, 11 digits, `true`) must each answer **400, never 500**, and leave the order out for delivery. Then «تم التسليم ✅» with 49.75 through the proof-of-delivery sheet: delivered, `collected_amount` = 49.75. |

### mfa.spec.js (one test user, serial)
| test | expected |
|---|---|
| B-01 | `security.mfa_enforced` = `false`, `False`, `0`, `off`, `''` (string) and `false` (boolean) → `2fa/status` `enforcement_on=false`, and a required-role user signs in without a code. P1 if any of them enforces. |
| enrolment | Default: from «أمان الحساب» (`/security`). With `UAT_MFA_ENFORCE=1`: the row is set to `true` and the user's sign-in shows «تأمين الحساب» (forced set-up), then the row is restored at once. Both: type the shown key's code, see 10 backup codes, status `enabled`, 10 codes left. |
| TOTP sign-in | Real login screen: a wrong code shows «رمز التحقق غير صحيح» (401), the right code signs in |
| backup codes | An unused code signs in (9 left); the same code again is refused (P0 if it works) |
| remember device | «تذكّر» on a new (pending) device is not honoured (P1 if it skips the code). The admin approves the device; «تذكّر» then skips the code (P2 if not). The admin's «إلغاء الأجهزة المحفوظة» brings the code back (P1 if not). |
| lockout | 5 wrong codes kill the login token (P0 if the right code still works afterwards). The next password sign-in gets 429 (P1 if not). The admin's unlock opens it again. |
| admin reset | A `PATCH mfa_enabled=false` must not switch 2FA off (P1 if it does). Recorded as a P2 decision: there is no admin 2FA reset; only forget-devices and unlock exist. |
| off again | A wrong password is refused (400); password + code switches 2FA off |

TOTP codes are computed in the test. The server takes each 30-second step once (A-2), so the helper waits
for a fresh step when it must. Neither the secret nor any code is logged. Screenshots are off in this spec,
because the set-up screen shows the key.

## What W8 switches on, and how it is restored

- **2FA for one test user.** The user is `UAT_MFA_KEY`, default `restricted`: a supervisor, and supervisor
  has `mfa_required`. 2FA is switched on through the app's own `/security` → `2fa/setup` → `2fa/enable`.
  `afterAll` switches it off with password + code, retires the browser devices this spec created, lifts any
  lock and restores the setting row. The secret, device ids and original row are kept in the git-ignored
  `frontend/uat/.auth/w8-mfa-cleanup.json`, so if a run crashes, the next run's `beforeAll` cleans up first.
  If the restore fails, the spec writes a P1 finding saying so, and `seed_uat_users` also resets it.
- **`security.mfa_enforced`.** Written only to false-like values, which change nothing for anyone. It is
  restored to its original state: deleted when absent (`seed_uat_users` deletes it), else its value and type
  are put back. It is set to `true` only with `UAT_MFA_ENFORCE=1`, for the few seconds until the set-up
  screen shows, and restored in a `finally`.
- **Rows created.** Reservations, demand, transfers, shortage lists, QA inspections, one delivery order and
  one driver profile, all tagged `UAT-W8-…` and all on the copy only. Only the cancel test's reservations are
  cancelled again. The copy is thrown away at the next refresh.

**Effect on other sessions** (see "Concerns"):

- While mfa.spec runs (~5–8 min), a `login.setup` of `restricted` from another session gets a code step.
- With `UAT_MFA_ENFORCE=1`, for those seconds every unenrolled admin, purchasing or supervisor sign-in on
  the copy goes to set-up. That includes `real:bassemwolsely94`, a real account whose password was reset on
  the copy.

## Run command (PowerShell, from the worktree root)

```powershell
. scripts/uat/uat-env.ps1
cd frontend
$env:UAT_WEB_PORT = 5208
$env:UAT_RUN_ID = 'w8-run1'
# optional: $env:UAT_MFA_ENFORCE = '1'   # forced-enrolment check; only when no other UAT run is signing in
..\scripts\uat\heavy.ps1 -Name "W8 mobile rider 2FA" -Command { npx playwright test -c playwright.uat.config.js uat/workflows/mfa uat/workflows/mobile uat/workflows/rider }
Copy-Item uat-findings\w8-run1.jsonl ..\docs\uat\runs\w8-findings.jsonl   # findings live outside test-results-uat
```

`assertUatCopy` runs first, so a server that is down or not the copy stops the run. The spec-level guard
`requireRoleReviewCopy` also stops it when the copy lacks the role-review matrix.

**Expected duration: ~1.5 h** (sign-ins ~5 min, mfa ~8, tabs ~10, creates ~35, cancel ~6, phones ~12,
rider ~12; Vite compiles each phone screen on first visit). That is over an hour, so every `asUser` checks
the session first and refreshes or signs in again.

## Environment check (2026-11-20, read-only)

- **UAT server 127.0.0.1:8200: down.** `curl …/api/auth/me/` → connection refused (000). Not started, since
  it is shared. Start it detached with `scripts/uat/serve.ps1` before the run. A Playwright-started server
  dies with the run.
- **The copy is not migrated to main.** These are missing:
  - `users` 0058–0062. This includes **0061_staffprofile_bell_view**, a new column: main's code will fail on
    StaffProfile queries against this DB. It also includes **0062_role_review_modules**, the rider and
    dispatch matrix rows.
  - `access` 0008_zone_policy_role_review_modules.
  - About 55 more across 25 apps: rpa 0001–0006, marketplace 0001, export_jobs 0001, tax_invoicing
    0015–0024, catalog 0044–0048, qa 0003–0004, customers 0036–0037, pos_orders 0018–0020 and others.

  **Migrate or refresh the copy (heavy, takes the lock) before W8**, then rerun
  `seed_uat_users --real-auto` and `export_uat_expectations` (the role review changed the matrix).
- **Seeded users.** `.uat-users.json` (Nov 17) has 19 users: 10 home roles in 160, 4 twins in 150, multi,
  restricted, phoneHidden, phoneVisible and one real admin. `delivery` has the delivery role. No driver
  profile is linked to it on a fresh copy, so the journey has the supervisor register one, as W5a did.
  `restricted` is a supervisor, so it qualifies as the 2FA user.

## Concerns

1. **Needs your go:** the forced-enrolment check (`UAT_MFA_ENFORCE=1`) briefly enforces 2FA for every
   admin, purchasing and supervisor sign-in on the shared copy, including the real admin account. It is off
   by default; without it, enrolment is tested from «أمان الحساب» only.
2. The 2FA test user (`restricted`) is shared. Schedule W8 when no other session runs `login.setup`.
3. The copy must be migrated first (above). Today main's code would not even sign in against it
   (0061 column).
