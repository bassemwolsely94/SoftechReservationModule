# W8 triage: mobile /m, rider /rider, 2FA (run 2, 2026-11-20)

Run: `%TEMP%\w8-run2.log`: 72 passed, 14 failed, 2 skipped (cancel: purchasing, accountant have no
reservations view, as designed), 3 did not run (mfa serial tail: lockout, admin reset, 2FA off).
Findings: `frontend/uat-findings/w8-run2.jsonl` (35 rows). `w8-run1-partial.jsonl` (same code) shows the
same failures for the same roles. Severity scale: docs/superpowers/specs/2026-11-16-role-uat-design.md.
Access rules: docs/superpowers/specs/2026-11-20-role-review-design.md. Read-only triage: no test runs and
no app changes. Server evidence comes from `%TEMP%\uat-server-8200.log` (the UAT runserver).

**Verdicts for the 14 failures:** REAL 3 · HARNESS 11 · DESIGN 0. Two of the HARNESS failures also
turned up a separate REAL P3 (see the REAL list).

## 1. Failures

### 1a. 2FA

| test | verdict | sev | evidence | proposed fix (one line) |
|---|---|---|---|---|
| mfa.spec.js:330 «تذكّر هذا الجهاز» … the admin cancels it | **REAL** | **P1** | `POST /api/users/140/forget-devices/` → 500 `DataError: value too long for type character varying(20)` (uat-server-8200.log:680–805, again at 3503–3626). The insert is the audit row in `apps/users/mfa.py:118-121`, `action='mfa_devices_forgotten'` (21 chars). The model and every migration say `max_length=30`, but `users/0008…useractivitylog.py:364` used `CREATE TABLE IF NOT EXISTS`, so a database that already had the older table kept `action varchar(20)`. This is the same drift class as users 0043 (`ip_address` column missing). There is no `ATOMIC_REQUESTS`, so the epoch bump at mfa.py:116 commits, the audit row is lost, and the admin sees a 500. The self-service `/api/auth/2fa/forget-devices/` (mfa.py:470-477) fails the same way. | New users migration: idempotent `ALTER TABLE users_useractivitylog ALTER COLUMN action TYPE varchar(30)` (0043 pattern). Extend the model-vs-`information_schema` sweep to compare `character_maximum_length`. Check the live/office DB with `\d users_useractivitylog`. |

### 1b. Mobile creates (7 roles, same failure)

| test | verdict | sev | evidence | proposed fix (one line) |
|---|---|---|---|---|
| mobile.spec.js:231 creates: admin | HARNESS | n/a (side P3 below) | The submit is found and enabled, but each click retry is caught by `[data-tour="general-help-center-offer"]` (the «جديد هنا؟» TourOffer chip, `fixed bottom-24 … z-[94]`, `frontend/src/help/Hints.jsx:193-194`) or by the bottom tab bar (`MobileLayout.jsx:193`, `fixed bottom-0 z-30`). Run log lines 155-300 show this. The form is the last thing on the page and `main` has only `pb-20` (MobileLayout.jsx:185), so the button's centre stays inside the chip's band. `clickFor` (`uat/workflows/ops/_ops.js:90-91`) then times out after 60 s. Screenshot `test-results-uat/…-49a4b-…/test-failed-1.png` shows the chip over the bottom of the form. | Hide or dismiss the TourOffer chip in `asUser` (init script: CSS `[data-tour="general-help-center-offer"]{display:none}`), or click its ✕ in `clickFor` when visible. |
| creates: call_center | HARNESS | n/a | Same click-intercept log (lines 301-410), at the reservation submit | same |
| creates: pharmacist | HARNESS | n/a | Same (411-520) | same |
| creates: salesperson | HARNESS | n/a | Same (521-630) | same |
| creates: supervisor | HARNESS | n/a | Same (631-872) | same |
| creates: pharmacist@B | HARNESS | n/a | Same chip intercept, here at `[data-tour="demand-mobile-new-submit"]` (mobile.spec.js:138; log 873+). The reservation step passed in run 2 because the chip comes 1.5 s after arriving and once per screen version (`Hints.jsx:183-186`). The "offered" state persists in localStorage `elrezeiky-help` (`help/helpStore.js:69-77`), and `asUser.close()` writes that back into `uat/.auth/<key>.json`. Whether it shows depends on earlier runs and timing. | same, so the run does not depend on what is in the state file |
| creates: salesperson@B | HARNESS | n/a | Same (1130+) | same |

Why 7 roles fail and 5 pass: the passing roles (purchasing, viewer, QM, accountant, viewer@B) hold no
create grant for the first area, so they never click a submit. Their branch is mustRefuse + "button
offered" (mobile.spec.js:264-284). Every role that clicks hits the chip. The step throws
(`_w8.js:161-169`), so demand, transfer, shortage and QA were **not exercised** for those 7 roles. Rerun.

### 1c. Mobile reservation cancel

| test | verdict | sev | evidence | proposed fix (one line) |
|---|---|---|---|---|
| mobile.spec.js:292 cancel: viewer | **REAL** | **P3** | The seed grants viewer `reservations: RO` (seed_permissions.py:218), so `edit=false`. `MobileReservationDetailPage.jsx:65` reads `canCancel = usePermission('reservations','edit')`, but `canCancel` can only **add** «إلغاء» (lines 106-108). `TRANSITIONS` (lines 24-28) already holds `'cancelled'` for pending/available/contacted/confirmed, so the button shows for everyone. The other status buttons («المخزون متاح», «منتهي») are not gated either. The server refuses (mustRefuse at mobile.spec.js:320 passed, no P2 row), so only the screen is wrong (role review decision 6). | Line 106: drop `'cancelled'` from `allowed` when `!canCancel`, and hide the whole status block without `reservations:edit`. |
| cancel: quality_manager | **REAL** | **P3** | QM `reservations: RE` (seed_permissions.py:284). Same code path. | same |

### 1d. Mobile phones

| test | verdict | sev | evidence | proposed fix (one line) |
|---|---|---|---|---|
| mobile.spec.js:336 phones: restricted | HARNESS | n/a | `ensureSignedIn` failed: "login 401, me 401" (`_w8.js:58-62`). Server log 5085-5097: me 401 → refresh 401 → login 401. `restricted` is the 2FA user. The enrolment test opens a context from the shared `stateFile('restricted')` (mfa.spec.js:240-241) and adds that browser's device to `S.devices` (:276). `restoreAll` then **retires** it (mfa.spec.js:154-160; log 3647-3651, devices 1786/1790/1791). The saved session in `uat/.auth/restricted.json` belongs to a retired device: `core/auth_cookies.py:89-90` refuses it, and the re-login could not recover. The mfa test's restore itself succeeded (no restore finding; cleanup file gone). | In mfa.spec use a fresh context for enrolment (not `stateFile(KEY)`), or delete/re-create `restricted.json` after `restoreAll`. In `ensureSignedIn`, clear the context cookies before the password login. |

Side note, not a finding yet: if a stale access cookie of a retired device does reach `login_view`
(AllowAny, but DRF still runs `CookieJWTAuthentication`), that would answer 401 to a correct password.
The real frontend refreshes first (refresh clears cookies on a revoked device, users/views.py:345-347),
so users are unlikely to hit it. Worth one unit test: login with a revoked-device cookie, then answer 200.

### 1e. Rider gate

| test | verdict | sev | evidence | proposed fix (one line) |
|---|---|---|---|---|
| rider.spec.js:36 gate: admin | HARNESS | n/a | /rider **opened**. error-context.md shows the RiderLayout header, «🚚 مهامي اليوم», «لا توجد مهام حالياً», and the URL stayed /rider. The access path is correct. `App.jsx:266-273` RiderHome redirects only `role==='delivery'` and never sends other roles away. `/rider` is `RequireRole module="rider"` (App.jsx:327), and the seed gives `rider` to admin, delivery, supervisor, call_center (seed_permissions.py:370; role review). The misclassification: `/api/delivery/app/my-orders/` answers 403 «ليس لديك ملف سائق مرتبط.» for a user with no driver profile (apps/delivery/views.py:1383-1385). `classify()` counts any API 403 on a screen under 200 chars as `refused` (`uat/lib/page.js:23-26`). | In the gate test, judge by URL plus the RequireRole refusal text, or by `[data-tour="delivery-driver-header"]` being visible. Ignore the driver-profile 403. |
| gate: call_center | HARNESS | n/a | Same (call_center gained rider in the role review) | same |
| gate: supervisor | HARNESS | n/a | Same | same |

## 2. Findings file (35 rows): verdicts

| rows | verdict | note |
|---|---|---|
| 1 × P1 workflow admin /users forget-devices 500 | REAL P1 | 1a |
| 7 × P1 workflow `<role> /m/{reservations,demand}/new` "locator.click: Test ended" | HARNESS | 1b (chip/tab-bar intercept) |
| 22 × P3 button "`<submit>` offered on /m/…/new" and "/m/qa `hr-qa-new`" (purchasing 3, viewer 5, QM 4, accountant 5, viewer@B 5) | REAL P3 (one finding) | No mobile create screen checks the create grant. `MobileNewReservationPage.jsx:310-313`, `MobileNewDemandPage`, `MobileNewTransferPage`, `MobileNewShortagePage` have no `usePermission`. `MobileQAPage.jsx:125-128` shows the «+» FAB to anyone who reaches /m/qa (its tab is role-limited, App.jsx:257, but the route at :363 is open). The server refused every one (mustRefuse passed), so this is screen polish (CLAUDE.md rule 9 holds). |
| 2 × P3 button «إلغاء» offered (viewer, QM) | REAL P3 | 1c |
| 3 × P1 screen /rider "refused, landed on /rider" | HARNESS | 1e |

## 3. REAL findings, by severity

1. **P1, `forget-devices` answers 500 (admin «إلغاء الأجهزة المحفوظة» and self-service), audit row lost.**
   The DB column `users_useractivitylog.action` is `varchar(20)` on the copy, while the model says 30 (drift from
   users 0008's `CREATE TABLE IF NOT EXISTS`). The 21-char `mfa_devices_forgotten` cannot be stored. The epoch
   bump still commits, so the forget takes effect, but the screen shows an error and CLAUDE.md rule 8
   (audit) is broken. Fix: repair migration (ALTER … TYPE varchar(30), idempotent) plus a column-length
   drift sweep. Check the live/office DB too, since the copy is taken from it.
2. **P3, mobile reservation detail offers «إلغاء» (and the other status moves) without `reservations:edit`.**
   `MobileReservationDetailPage.jsx:24-28,65,106-108`. The server refuses. Role review decision 6 is only
   half done on the phone.
3. **P3, mobile create screens offer the submit without the create grant.** /m/reservations/new,
   /m/demand/new, /m/transfers/new, /m/shortage/new, and the /m/qa «+». The server refuses. Gate each page
   on `usePermission(module,'create')` (QA: the QA_INSPECTION rule) with a calm "no permission" line.
4. **P3, the «جديد هنا؟» TourOffer chip covers the bottom of mobile forms.** On a phone it sits at
   `bottom-24` (Hints.jsx:194). It overlaps the last control of /m/*/new forms, whose content ends `pb-20`
   (5rem) above the tab bar. A user can still tap the uncovered part or ✕ the chip once. Fix: put the chip
   above `bottom-28` on `/m`, or give MobileLayout `main` more bottom padding while it shows.
5. **P3, /rider for a rider-module holder without a driver profile says «لا توجد مهام حالياً».** That
   is misleading. The server's 403 «ليس لديك ملف سائق مرتبط» is dropped (DriverDeliveryApp.jsx:37-41
   ignores the error, :88 shows "no tasks"). Supervisor and call_center now reach /rider by design, so
   they should see "no driver profile linked".

Observation only (not graded): React dev warning "Cannot update a component while rendering a different
component" (QueryErrorStrip ↔ MobileShortageDetailPage) in the supervisor and pharmacist@B browser logs.
Worth a look when someone is in that page.

## 4. Harness fixes before a clean rerun

1. **TourOffer chip**: in `asUser` (`_w8.js:73-77`), add an init script that hides
   `[data-tour="general-help-center-offer"]`, or seed `elrezeiky-help` so nothing is offered. Record the
   overlap once as its own P3 check so hiding it does not erase finding 4. This unblocks the 7 create tests.
2. **Rider gate**: stop treating the driver-profile 403 as a refusal. Decide by final URL, the RequireRole
   refusal text, and the visible `delivery-driver-header` (rider.spec.js:42-47).
3. **mfa ↔ shared state file**: the enrolment test must not use `stateFile('restricted')`, or `restoreAll`
   must re-create `restricted.json` after retiring the devices. Before the rerun, delete
   `frontend/uat/.auth/restricted.json` so `login.setup` signs `restricted` in afresh.
4. **mfa serial tail**: wrap the forget-devices call in `flag` (soft), not a throwing `step`, so the lockout,
   admin reset and «2FA off again» tests still run (3 did not run this time). Alternatively land fix P1
   first.
5. **`ensureSignedIn`** (`_w8.js:58-62`): clear the context cookies before the password login, so a dead
   session never blocks the re-login.
6. After fix 1, the create tests run demand, transfer, shortage line and QA round for the 7 creating roles
   for the first time. Expect new findings there.
