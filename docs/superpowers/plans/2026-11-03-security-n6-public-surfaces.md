# Security N6 — Public-Surface Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the customer-facing pages (`/notify`, the `/portal` sign-in, `/track/:token`) safe to leave open to the internet:
- anonymous requests reach only an explicit allow-list;
- a bot cannot fill the forms in bulk;
- a visitor cannot learn whether a phone number is known;
- nothing a stranger types ever reaches SOFTECH or a customer record without staff seeing it first.

**Architecture:** Four layers:
- **Gate.** One allow-list module names every path an anonymous request may reach. A middleware refuses the rest, following its own off/log/enforce switch.
- **Form guard.** A small self-hosted form-guard module in `core/` combines a signed, single-use proof-of-work challenge, a honeypot field, a minimum fill time and a per-phone limit. Its browser half uses Web Crypto, so no third-party service and no new dependency is involved.
- **Routes.** The public routes get one canonical prefix, `/api/public/`. The old paths stay as aliases, because tracking links already sit in customers' WhatsApp chats.
- **No SOFTECH from the form.** Self-service demand records are no longer matched to SOFTECH or to a customer when they are created. Staff do that from the demand screen.

**Tech Stack:** Django 5 / DRF (throttles, `django.core.signing`, cache), React + Vite (`crypto.subtle`), Postgres.

**Spec:** `docs/security/2026-10-31-network-device-access-design.md`:
- §6.7 (public surfaces);
- §7 decision 4 (self-hosted bot check);
- §8 row N6.

§7 decision 5 ("which customer data-entry form") is still open with the owner. This plan hardens the forms that exist (`/notify` and the portal sign-in) and builds the guard so any future form reuses it.

## Global Constraints

- Self-hosted only:
  - no third-party CAPTCHA, script or service;
  - no visitor data leaves our server;
  - no new npm or pip dependency (spec §7.4).
- The anonymous allow-list follows `PUBLIC_API_ENFORCEMENT` = off / log / enforce, default `log`. An unknown value is `log`, plus system check `access.W005`.
- Everything else in N6 is on from release. It changes only anonymous public endpoints and never touches a signed-in staff request.
- Write-only public forms:
  - a field allow-list, server-side validation and length limits;
  - the SAME response whether or not the phone or record already exists (no enumeration);
  - no stored data read back.
- Rate limits per IP AND per phone (spec §6.7). Per phone, `PUBLIC_PHONE_DAILY_MAX = 3` submissions per form per phone per Cairo day.
- Proof of work:
  - signed (`django.core.signing`, salt `'public-pow'`), single-use (cache key per challenge id), expiring (`PUBLIC_POW_TTL_SECONDS = 600`);
  - `PUBLIC_POW_DIFFICULTY = 16` leading zero bits of `sha256(challenge + ':' + nonce)`;
  - minimum fill time `PUBLIC_MIN_FILL_SECONDS = 3`, measured from the challenge's signed issue time;
  - honeypot field name `website`.
- No SOFTECH access from a public path, ever (spec §6.7, last bullet). This holds in every mode of the N4 gate.
- Public input never writes or links a `Customer` directly. Self-service demand records stay unlinked until staff act on them.
- Never break a link already sent: `/api/delivery/track/<token>/` and `/api/demand/public/*` stay as aliases of the new `/api/public/*` routes.
- Arabic user-facing text on public pages, plus Arabic + English in-app help for the staff screens that change. Say «سيرفر», not «خادم».
- Background threads use `core.threads.start_thread`. No POS, pricing, checkout or SOFTECH-write code is touched.
- Tests: fresh `TEST_DB_NAME` per run (the socket tests flush seeded rows from a kept DB).

## Review Focus

1. **A slow or old phone solving the challenge.** At 16 bits, about 65,000 hashes are needed. The page must show «جارٍ التحقق…» and finish. A solve that is too slow or impossible (no `crypto.subtle` on plain http) shows an Arabic message instead of hanging. *(Task 2 test `test_challenge_is_solvable_at_configured_difficulty`, plus the frontend helper's timeout in Task 3.)*
2. **The same customer submits twice in a minute**, a real double-tap: both get the same friendly success, and only one demand record exists. *(Task 3 test `test_double_submit_same_response_one_record`.)*
3. **A replayed solved challenge** is refused, and a challenge solved for the portal is refused on `/notify`. *(Task 2 tests `test_solution_is_single_use` and `test_challenge_bound_to_form`.)*
4. **A tracking link sent before N6** (`/api/delivery/track/<token>/`) still works after release. *(Task 4 test `test_old_track_path_still_works`.)*
5. **A signed-in staff member on a staff screen** is never touched by the anonymous gate, including portal session requests, which are "anonymous" to Django. *(Task 1 tests `test_signed_in_staff_never_gated` and `test_portal_session_paths_allowed`.)*

---

### Task 1: Anonymous allow-list gate

**Files:**
- Create:
  - `apps/access/public_paths.py`;
  - `apps/access/public_middleware.py`.
- Modify:
  - `config/settings.py` (MIDDLEWARE: right after `AccessContextMiddleware`; `PUBLIC_API_ENFORCEMENT = config('PUBLIC_API_ENFORCEMENT', default='log')`);
  - `apps/access/checks.py` (W005);
  - `apps/access/preflight.py` (an informational `public_api_mode` item, alongside `bulk_read_mode`).
- Test: `apps/tests/security/test_access_public_gate.py`

**Interfaces:**
- Produces:
  - `PUBLIC_PREFIXES: tuple[str, ...]` — every path an anonymous request may reach. Start from the list below, then grep `AllowAny` and `authentication_classes([])` to confirm nothing is missed. Each entry carries a one-line comment naming its view.
    - `/api/auth/` (login, refresh, MFA);
    - `/api/users/` entries only for the three AllowAny views in `apps/users/views.py` (add exact paths, not the prefix);
    - `/api/access/whoami/`;
    - `/api/config/theme/` (GET only);
    - `/api/csp-report/`;
    - `/api/portal/` (portal session auth is not a Django user);
    - `/api/demand/public/`;
    - `/api/delivery/track/`;
    - `/api/public/`.
  - `PUBLIC_GET_ONLY: tuple[str, ...]` — prefixes allowed for GET/HEAD/OPTIONS only (`/api/config/theme/`).
  - `is_public(path: str, method: str) -> bool`.
  - `PublicApiMiddleware` — for a path under `/api/` with no signed-in user (`request.access.user_id is None`) and not `is_public`:
    - `log` → one WARNING line per path and IP per 600 s (`'public gate would-deny %s %s ip=%s'`), then pass through;
    - `enforce` → 401 `{'detail': 'يلزم تسجيل الدخول'}`;
    - `off` → nothing.
    - It never raises. On an internal error it passes in log/off mode and refuses in enforce.

- [ ] **Step 1: Write the failing tests:**
  - `test_anonymous_unlisted_api_refused_in_enforce` (`/api/customers/` → 401);
  - `test_anonymous_unlisted_logged_in_log_mode`;
  - `test_listed_public_paths_reach_their_views` (notify item lookup, track, request-link, theme GET, csp-report, whoami → not 401 from the gate);
  - `test_theme_put_anonymous_refused`;
  - `test_signed_in_staff_never_gated`;
  - `test_portal_session_paths_allowed`;
  - `test_every_allowany_view_is_listed`: a static scan of `apps/**/views.py` and `core/*.py` for `AllowAny` and `authentication_classes([])`. Every such view's URL must resolve to `is_public` True (use `django.urls` reverse-walking or the urlconf resolver).
  - `test_unknown_mode_is_log_and_w005`.
- [ ] **Step 2:** Run on a fresh DB: `TEST_DB_NAME=test_n6 ../../../venv/Scripts/python.exe manage.py test apps.tests.security.test_access_public_gate --noinput`. Expected: FAIL (ImportError).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same, plus `apps.tests.security.test_access_preflight*` and `test_access_checks*`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(security): anonymous allow-list gate for /api (N6)`.

### Task 2: Self-hosted form guard (proof of work, honeypot, fill time, per-phone limit)

**Files:**
- Create:
  - `core/public_guard.py`;
  - `apps/access/public_views.py` (the challenge endpoint);
  - `frontend/src/utils/publicGuard.js`.
- Modify:
  - `config/urls.py` (`path('api/public/', include('apps.access.public_urls'))` with a new `apps/access/public_urls.py`);
  - `config/settings.py` (the guard settings from Global Constraints, env-overridable).
- Test: `apps/tests/security/test_public_guard.py`

**Interfaces:**
- Produces (Python, `core/public_guard.py`):
  - `issue_challenge(form: str) -> dict` returns `{'challenge': <signed str>, 'difficulty': int}`. The signed payload is `{'id': uuid4 hex, 'form': form, 'iat': epoch seconds}`, signed with salt `'public-pow'`.
  - `class GuardError(Exception)` with `.code` in `'bot' | 'expired' | 'replayed' | 'too_fast' | 'bad_solution' | 'wrong_form' | 'phone_limit'`.
  - `check_submission(data: dict, form: str, phone: str | None = None) -> None`. Order:
    1. honeypot `data.get('website')` non-empty → `'bot'`;
    2. unsign the challenge, older than TTL → `'expired'`;
    3. payload form differs from `form` → `'wrong_form'`;
    4. `now - iat < PUBLIC_MIN_FILL_SECONDS` → `'too_fast'`;
    5. `sha256(f'{challenge}:{nonce}')` lacks `difficulty` leading zero bits → `'bad_solution'`;
    6. `cache.add(f'public:pow:{id}', 1, TTL)` fails → `'replayed'`;
    7. `phone` given and the per-phone daily counter `public:phone:{form}:{phone}:{YYYYMMDD Cairo}` is already ≥ `PUBLIC_PHONE_DAILY_MAX` → `'phone_limit'`. Otherwise increment it.
  - `GUARD_MESSAGES = {code: Arabic text}`. `'bot'` and `'phone_limit'` map to the SAME generic success-looking text as a normal submit. Callers return the normal success response for those two codes (no signal to a bot), and log one INFO line.
- Endpoint: `GET /api/public/challenge/?form=<notify|portal_link>`, AllowAny, throttled 60/hour per IP. An unknown form → 400.
- Frontend (`publicGuard.js`):
  - `async function solveChallenge(form, {timeoutMs = 20000} = {}) -> {challenge, nonce}`. It fetches the challenge, then loops `nonce` with `crypto.subtle.digest('SHA-256', …)`, in batches that yield to the UI.
  - It throws `Error('unsupported')` when `crypto.subtle` is missing and `Error('timeout')` past the timeout.

- [ ] **Step 1: Write the failing tests:**
  - `test_valid_submission_passes` (a test helper solves the challenge in Python);
  - `test_honeypot_flags_bot`;
  - `test_expired_challenge`;
  - `test_too_fast` (patch time);
  - `test_bad_solution`;
  - `test_solution_is_single_use`;
  - `test_challenge_bound_to_form`;
  - `test_phone_daily_limit` (the 4th of one phone the same day → `'phone_limit'`; a different phone → passes);
  - `test_challenge_is_solvable_at_configured_difficulty` (the Python solver finds a nonce within 2^20 tries at difficulty 16);
  - `test_challenge_endpoint_unknown_form_400`.
- [ ] **Step 2:** Run on a fresh DB. Expected: FAIL.
- [ ] **Step 3:** Implement. The Python solver used by tests lives in the test file, not in `core/`.
- [ ] **Step 4:** Run the tests, plus `cd frontend && npm run build`. Expected: PASS / build OK.
- [ ] **Step 5:** Commit: `feat(security): self-hosted form guard — proof of work, honeypot, fill time, per-phone limit (N6)`.

### Task 3: The /notify form — guarded, write-only, no SOFTECH

**Files:**
- Modify:
  - `apps/demand/views.py` (`public_item_lookup`, `public_branches`, `public_demand_interest`);
  - `apps/demand/service.py` (`create_demand`);
  - `apps/access/public_urls.py` (canonical routes);
  - `frontend/src/pages/NotifyPage.jsx`;
  - the demand screen help in `apps/help/content/` (find the page for the demand list with `grep -rln "'/demand" apps/help/content`).
- Test: `apps/tests/security/test_public_notify.py`

**Interfaces:**
- Consumes: `issue_challenge`, `check_submission`, `GuardError` and `GUARD_MESSAGES` (Task 2); `is_public` (Task 1) already covers `/api/public/`.
- Canonical routes: `/api/public/notify/item/`, `/api/public/notify/branches/`, `/api/public/notify/interest/`. These point to the same three views. The `/api/demand/public/*` routes stay.
- `public_item_lookup`: the response drops `softech_id` (`{'found', 'id', 'name'}` only), and NotifyPage stops showing it.
- `public_demand_interest`:
  - calls `check_submission(request.data, 'notify', phone=phone)` after phone validation;
  - name ≤ 80 characters (longer → 400);
  - only the fields `phone`, `name`, `item`, `branch`, `challenge`, `nonce` and `website` are read.
  - Response, always for success, duplicate, `'bot'` and `'phone_limit'`: `{'ok': True}` with status 200. There is no `already` and no `demand_number`.
  - Guard codes other than `bot` / `phone_limit` → 400 with `GUARD_MESSAGES[code]`.
- `service.create_demand(..., source=...)`: when `source == 'self_service'`, skip `enrich_demand_from_erp` and `try_link_customer`. The staff "enrich" action (`views.py` ~l.542) already links on demand.
- NotifyPage:
  - solves the challenge on submit (shows «جارٍ التحقق…»);
  - sends `challenge`, `nonce` and an empty hidden `website` input (`autocomplete="off"`, `tabIndex=-1`, visually hidden and not `display:none`);
  - shows the same success screen for every `{ok: true}`;
  - for `unsupported` / `timeout` shows «تعذر التحقق من الجهاز — جرّب متصفحاً آخر أو اتصل بالفرع».
  - It calls the canonical `/api/public/notify/*` routes.
- Help (staff demand screen, Arabic + English, `updated` bumped): self-service requests arrive unmatched. Open the request and use «ربط بالعميل / تحديث من سوفتك» to match it.

- [ ] **Step 1: Write the failing tests:**
  - `test_double_submit_same_response_one_record`;
  - `test_existing_phone_item_same_response_as_new` (identical JSON body and status);
  - `test_no_softech_on_public_create`: patch `config.sybase.get_sybase_connection` to raise if called, submit, and expect success with the connection never called;
  - `test_self_service_demand_not_linked_to_customer` (a Customer with the same phone exists, so `demand.customer` stays null);
  - `test_item_lookup_has_no_softech_id`;
  - `test_long_name_rejected`;
  - `test_bot_gets_success_but_no_record`;
  - `test_canonical_and_old_routes_both_work`.
- [ ] **Step 2:** Run on a fresh DB. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests, plus the existing demand tests (`grep -rl "public_demand\|demand/public" apps/tests`), plus `npm run build`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(security): /notify form guarded, write-only, no SOFTECH from the public page (N6)`.

### Task 4: Portal sign-in link and delivery tracking

**Files:**
- Modify:
  - `apps/portal/views.py` (`request_link`) and `apps/portal/serializers.py` (accept `challenge` / `nonce` / `website`);
  - `apps/delivery/views.py` (`delivery_public_track`: add a throttle);
  - `apps/access/public_urls.py` (`/api/public/track/<str:token>/` → the same view);
  - `frontend/src/pages/portal/*` (the sign-in page that posts request-link; find it with `grep -rn "request-link" frontend/src`);
  - `frontend/src/pages/DeliveryTrackPage.jsx` (calls `/api/public/track/<token>/`).
- Test: `apps/tests/security/test_public_portal_track.py`

**Interfaces:**
- Consumes: Task 2 guard (form `'portal_link'`).
- `request_link`:
  - runs `check_submission(request.data, 'portal_link', phone=<normalised phone>)` before the customer lookup;
  - `'bot'` / `'phone_limit'` → the existing generic 200 `_GENERIC_LINK_MSG`, sending nothing;
  - other guard codes → 400 with `GUARD_MESSAGES[code]`;
  - the response stays identical whether or not the customer exists (already true; keep the test).
- `delivery_public_track`: a throttle class `PublicTrackThrottle(AnonRateThrottle)` with rate `'120/hour'`. The response fields are unchanged.
- Portal sign-in page: solves the challenge before posting, with the same Arabic messages as NotifyPage (import from `publicGuard.js`).

- [ ] **Step 1: Write the failing tests:**
  - `test_request_link_requires_challenge`;
  - `test_request_link_bot_gets_generic_200_and_no_message` (patch `send_magic_link`, assert it is not called);
  - `test_request_link_same_response_known_and_unknown_phone`;
  - `test_track_throttled` (121st request in an hour → 429);
  - `test_new_track_path_works`;
  - `test_old_track_path_still_works`.
- [ ] **Step 2:** Run on a fresh DB. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests, plus the existing portal and delivery tests (`grep -rl "portal\|delivery_public_track\|delivery/track" apps/tests`), plus `npm run build`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(security): portal sign-in link guarded, tracking throttled, /api/public routes (N6)`.

### Task 5: Help, runbook, design doc, full check

**Files:**
- Modify:
  - `deploy/LINKDATACENTER_VPS_RUNBOOK.md`: a section «Batch N6 on the live server» after N5:
    - release;
    - in the log week, grep `'public gate would-deny'`;
    - open `/notify` and the portal sign-in from a phone and submit once each;
    - set `PUBLIC_API_ENFORCEMENT=enforce` after a clean week;
    - way back.
  - `docs/security/2026-10-31-network-device-access-design.md`:
    - §8 N6 row → Built with commits;
    - §7 decision 5 stays open (note that the guard is ready for any new form);
    - §6.7 "optional signed, expiring link per invitation" → "not built (not needed for /notify; revisit with decision 5)".
  - The plan's help items already landed in Task 3. Here, confirm `apps.tests.test_help` passes.
- [ ] **Step 1:** Write the runbook and design-doc text.
- [ ] **Step 2:** Run the full suite on a fresh DB (`TEST_DB_NAME=test_n6_full ... manage.py test --noinput --parallel 1`), plus `makemigrations --check --dry-run` (expected: no changes, since N6 adds no models) and `npm run build`. Expected: all green.
- [ ] **Step 3:** Commit: `docs(security): N6 runbook and design status`.
