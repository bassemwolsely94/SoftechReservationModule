# Security Batch N0 — fix the audit holes (H1–H9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the holes found in the 2026-10-31 access audit before any network/device gating is built.

**Architecture:** Small, independent fixes in existing code. No new subsystem. Every fix has its own test in `apps/tests/security/`. Two migrations: `users.0034`, `delivery.0010`. nginx changes live in `deploy/` and are applied by the owner on the VPS.

**Tech Stack:** Django 5.2 / DRF, React 18, nginx 1.24, Daphne 4.2. Tests: `python manage.py test <label> --noinput` (hermetic runner; SOFTECH disabled under tests).

**Spec:** `docs/security/2026-10-31-network-device-access-design.md` §5 (H-list) and §8 (batch N0).

## Global Constraints

- No SOFTECH write path, pricing, discount, payment or checkout code is touched.
- Backend owns the rule. Frontend buttons are convenience only; every check is server-side.
- Every new screen element / status gets in-app help in `apps/help/content/<module>.py` (Arabic + English) with the screen's `updated` bumped; `apps/tests/test_help.py` must stay green.
- Every security-relevant event is written to `UserActivityLog` (users) or `AuditLog` (others) with actor + IP.
- Client IP is always read with `core.client_ip.client_ip(request)` (or `apps.users.middleware.get_current_ip()`), never `request.META['REMOTE_ADDR']`.
- Arabic user-facing messages; no raw exception text returned to the client (use the existing `public_error(request, e)`).
- Out of scope, deliberately: H4 (rider confined to the rider surface → batch N3 zone policy) and H10 (HR geofence never blocks → owner decision later).

## Review Focus

1. **Deliberate lock-out of a real user** (attacker types wrong passwords for a manager's username). Expect: the lock lasts 15 min only, admins are notified once per lock, an admin can unlock at once, and the message never says whether the account exists → test in Task 2.
2. **Unknown usernames vs real usernames** must get identical responses (same text, same status, also once "locked") so the lock does not reveal which accounts exist → test in Task 2.
3. **Existing remembered devices on deploy:** adding the epoch to the fingerprint invalidates every current "remember this device" token. Expect one extra 2FA prompt per user, nothing worse → test in Task 3.
4. **Rider sends junk coordinates** (strings, out-of-range, missing) to the location endpoint. Expect 400 and no change to the order's drop-off point → test in Task 5.
5. **A forged `X-Forwarded-For` sent by the client** must not change the IP written to logs, throttles or lockout → test in Task 1.

---

### Task 1: One trusted client IP (H6)

Daphne `--proxy-headers` takes the **leftmost** `X-Forwarded-For` entry (`venv/Lib/site-packages/daphne/utils.py:67-68`). The Ubuntu `proxy_params` *appends* to the header, so the leftmost entry is client-controlled. Eight code paths fall back to `REMOTE_ADDR`.

**Files:**
- Create: `deploy/nginx-proxy-headers.conf` — sets `Host $host`, `X-Real-IP $remote_addr`, `X-Forwarded-For $remote_addr` (**overwrite, not append**), `X-Forwarded-Proto $scheme`.
- Modify: `deploy/nginx.conf` — replace every `include /etc/nginx/proxy_params;` (L63, 73, 102, 109) with `include /etc/nginx/elrezeiky-proxy-headers.conf;`, and add the same include to `/ws/` (L113-122), keeping its Upgrade/Connection lines.
- Modify: `deploy/LINKDATACENTER_VPS_RUNBOOK.md` §9.2 — copy step for the new file.
- Modify: `apps/users/views.py:131,298,360,386,406,565`, `apps/users/mfa.py:227`, plus the remaining `REMOTE_ADDR` reads outside `core/client_ip.py` (8 total; find with `grep -rn "REMOTE_ADDR" apps core config --include=*.py`) → `client_ip(request)`.
- Test: `apps/tests/security/test_client_ip.py` (extend).

**Interfaces:**
- Consumes: `core.client_ip.client_ip(request) -> str | None` (existing).
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**
  - `test_no_remote_addr_reads_outside_helper`: walk `apps/`, `core/`, `config/` `*.py` (skip `tests`, `migrations`); assert no file other than `core/client_ip.py` contains `REMOTE_ADDR`.
  - `test_nginx_overwrites_forwarded_for`: read `deploy/nginx-proxy-headers.conf`; assert it contains `proxy_set_header X-Forwarded-For $remote_addr;` and not `$proxy_add_x_forwarded_for`.
  - `test_every_proxy_location_uses_trusted_headers`: parse `deploy/nginx.conf`; every `location` block with `proxy_pass` contains `include /etc/nginx/elrezeiky-proxy-headers.conf;` (this includes `/ws/`); no `proxy_params` remains.
  - `test_login_failure_logs_proxy_ip_not_forged`: with `NUM_PROXIES=1`, POST a bad login with `HTTP_X_FORWARDED_FOR='6.6.6.6, 41.32.31.187'` and `REMOTE_ADDR='6.6.6.6'`; the `login_failed` row has `ip_address == '41.32.31.187'`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.security.test_client_ip --noinput` → the new tests FAIL.
- [ ] **Step 3: Implement** the nginx file, the nginx.conf edits, the runbook step and the `client_ip(request)` replacements.
- [ ] **Step 4: Run** the same command → PASS.
- [ ] **Step 5: Commit** `fix(security): one trusted client IP — nginx overwrites X-Forwarded-For, no REMOTE_ADDR reads (N0/H6)`.

---

### Task 2: Per-account login lockout (H8)

**Files:**
- Create: `apps/users/lockout.py`.
- Modify: `apps/users/models.py:75-90` — add actions `('login_locked', 'إيقاف الدخول مؤقتاً')`, `('login_unlocked', 'رفع إيقاف الدخول')`, `('mfa_challenge', 'طلب رمز التحقق')`.
- Modify: `apps/users/views.py` `login_view` (L125-187): lock check before `authenticate`; log `mfa_challenge` instead of `login_success` at L165 and L170.
- Modify: `apps/users/mfa.py` `verify_2fa_view` (L233): lock check first; a failed code also counts (already logged as `mfa_failed`).
- Modify: `apps/users/urls.py` + `apps/users/views.py` — `POST /api/users/<id>/unlock-login/` (admin only, `IsAdminRole`).
- Modify: `frontend/src/pages/UsersPage.jsx` (or the user-detail drawer it uses) — «رفع الإيقاف» button shown when the user payload has `login_locked_until`; `apps/users/serializers.py` adds read-only `login_locked_until`.
- Modify: `apps/help/content/users.py` (Arabic + English: what the lock is, how to unlock), bump `updated`.
- Migration: `apps/users/migrations/0034_security_n0.py` (choices; Task 3 adds a field to the same migration — create it in this task, extend in Task 3).
- Test: `apps/tests/security/test_auth_lockout.py`.

**Interfaces:**
- Produces, in `apps/users/lockout.py`:
  - `FAIL_LIMIT = 5`, `WINDOW = timedelta(minutes=15)`, `LOCK_FOR = timedelta(minutes=15)`.
  - `locked_until(profile) -> datetime | None`: counts `login_failed` + `mfa_failed` rows for `profile` created after `max(now - WINDOW, last login_success / login_unlocked)`. It returns `last_failure + LOCK_FOR` when the count is ≥ `FAIL_LIMIT` and that time is in the future, else `None`. DB-backed (not the cache) so it survives restarts and works across processes.
  - `register_lock(profile, ip)`: writes `login_locked` once per lock and notifies admins through the existing notifications service (one notification per lock, `dedup_key=f'login-lock:{profile.id}'`).
  - `unlock(profile, by_profile, ip)`: writes `login_unlocked`.
  - `unknown_identifier_locked(identifier: str) -> bool` + `note_unknown_failure(identifier)`: cache counter for identifiers that match no account (same limits), so their responses match locked real accounts.
- Response when locked (real or unknown account): HTTP 429, `{'error': 'تم إيقاف الدخول مؤقتاً بسبب محاولات خاطئة متكررة. حاول بعد 15 دقيقة أو تواصل مع المدير'}`.

- [ ] **Step 1: Write the failing tests** in `test_auth_lockout.py`:
  - `test_fifth_wrong_password_locks`: 5 bad POSTs to `/api/auth/login/` → the 6th, **with the correct password**, returns 429 with the exact message; one `login_locked` row.
  - `test_lock_expires_after_15_minutes` (freeze time / move `created_at`): after 15 min the correct password → 200.
  - `test_success_resets_counter`: 4 bad, 1 good, 4 bad → still 401, not 429.
  - `test_wrong_2fa_codes_count`: user with 2FA; correct password + 5 wrong codes over fresh login tokens → next login 429.
  - `test_unknown_identifier_same_response`: 6 bad POSTs for `no-such-user` → the 6th returns 429 with the same body as a real locked account; the first 5 return the same 401 body as a real account.
  - `test_admin_unlock`: admin POST `/api/users/<id>/unlock-login/` → 200 and `login_unlocked` row; the user can log in; a non-admin gets 403.
  - `test_mfa_challenge_not_logged_as_success`: password OK + 2FA on → row action `mfa_challenge`, no `login_success`.
  - `test_admins_notified_once_per_lock`: 8 bad attempts → exactly one admin notification.
- [ ] **Step 2: Run** `python manage.py test apps.tests.security.test_auth_lockout --noinput` → FAIL.
- [ ] **Step 3: Implement** `lockout.py`, the view changes, the unlock endpoint, the serializer field, the migration, the Users-page button and the help text.
- [ ] **Step 4: Run** the lockout tests, plus `apps.tests.security.test_auth_mfa apps.tests.security.test_auth_mfa_attempts apps.tests.security.test_auth_sessions apps.tests.test_help` → PASS.
- [ ] **Step 5: Commit** `feat(security): per-account login lockout + admin unlock (N0/H8)`.

---

### Task 3: Revocable "remember this device" (H7, interim until N2)

**Files:**
- Modify: `apps/users/models.py` `StaffProfile` — `mfa_device_epoch = models.PositiveIntegerField(default=0)`; add action `('mfa_devices_forgotten', 'إلغاء الأجهزة المحفوظة')`.
- Modify: `apps/users/migrations/0034_security_n0.py` (from Task 2) — add the field.
- Modify: `apps/users/mfa.py:95-102` `_device_fingerprint` — material becomes `f'{user.password}|{mfa_secret}|{profile.mfa_device_epoch}'`.
- Modify: `apps/users/auth_urls.py` + `mfa.py` — `POST /api/auth/2fa/forget-devices/` (self, authenticated): increments the epoch.
- Modify: `apps/users/urls.py` + `views.py` — `POST /api/users/<id>/forget-devices/` (admin): same, on another user.
- Modify: `frontend/src/pages/SecurityPage.jsx` — «إلغاء كل الأجهزة المحفوظة» button; `UsersPage.jsx` — the same action for admins.
- Modify: `apps/help/content/users.py` (security screen + users screen), bump `updated`.
- Test: `apps/tests/security/test_auth_mfa.py` (extend).

**Interfaces:**
- Consumes: `lockout` nothing; `mfa.make_device_token(user)`, `mfa.valid_device_token(token, user)` (existing).
- Produces: `mfa.forget_devices(profile, by_profile, ip) -> int` (returns the new epoch; logs `mfa_devices_forgotten`).

- [ ] **Step 1: Write the failing tests:**
  - `test_forget_devices_invalidates_token`: get a device token → `valid_device_token` True → POST self forget → False.
  - `test_admin_forget_devices_other_user`: admin → 200 + log row; non-admin on another user → 403.
  - `test_other_users_tokens_unaffected`: forgetting user A leaves user B's token valid.
- [ ] **Step 2: Run** `python manage.py test apps.tests.security.test_auth_mfa --noinput` → FAIL.
- [ ] **Step 3: Implement** the field, the fingerprint change, both endpoints, the two buttons and the help text.
- [ ] **Step 4: Run** `apps.tests.security.test_auth_mfa apps.tests.security.test_auth_mfa_attempts apps.tests.test_help` → PASS.
- [ ] **Step 5: Commit** `feat(security): revocable remembered devices (N0/H7)`.

---

### Task 4: Personal person-search leak (H1)

`GET /api/personal/persons/search/` (`apps/personal/views.py:126-140`) runs a live HQ `personsdata` LIKE for any logged-in user (25 names + codes per call; 2-char minimum). It also returns raw SOFTECH error text. `/api/personal/` is RBAC-exempt. The widget-data path is already gated by approved claims and stays as is.

**Files:**
- Modify: `apps/personal/views.py` `persons_search`.
- Create: `PersonSearchThrottle(UserRateThrottle)` with `scope = 'personal_person_search'` in `apps/personal/views.py`; rate `'30/hour'` in `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']` (`config/settings.py:303-309`).
- Test: `apps/tests/security/test_personal_person_search.py`.

**Behaviour:**
- `q` stripped length < 3 → `{'results': []}` (no SOFTECH call).
- `profile.role == 'delivery'` or no active profile → 403 `{'detail': 'غير مصرّح'}`.
- Error → 502 `{'detail': 'تعذّر البحث في SOFTECH'}` plus `public_error(...)` only (no raw text).
- Each search writes `AuditLog` action `personal_person_search` with `q`, `kind`, result count and IP.

- [ ] **Step 1: Write the failing tests** (patch `apps.personal.queries.search_persons`):
  - `test_short_query_does_not_hit_softech` (`q='ab'` → mock not called).
  - `test_delivery_role_refused` (403, mock not called).
  - `test_throttled_after_30_per_hour` (31st → 429).
  - `test_error_text_not_leaked` (mock returns `[{'_error': 'JZ0T3 secret host 192.168.1.8'}]` → body has no `192.168.1.8`).
  - `test_search_is_audited`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.security.test_personal_person_search --noinput` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the test plus `apps.personal` → PASS.
- [ ] **Step 5: Commit** `fix(security): limit and audit the live person search (N0/H1)`.

---

### Task 5: Rider location and rider powers (H2, H3)

- **H2:** `driver_app_update_location` (`apps/delivery/views.py:1318-1338`) overwrites `order.delivery_lat/lng`, which is the drop-off geofence target (`:479`) and the customer tracking pin (`:1393`).
- **H3:** the `delivery` role holds `approve` + `finalize` (`seed_permissions.py:178`), so a rider can cancel (`:640`) and close (`:691`) their own order. Collect-cash (`:718`) uses `rider_ok=True` and keeps working without those grants.

**Files:**
- Modify: `apps/delivery/models.py` `DeliveryOrder` (near L436) — `rider_lat`, `rider_lng` (same DecimalField spec as `delivery_lat`), `rider_location_at = DateTimeField(null=True, blank=True)`.
- Migration: `apps/delivery/migrations/0010_rider_location.py`.
- Modify: `apps/delivery/views.py:1330-1338` — validate floats (`-90..90`, `-180..180`, else 400 `'الإحداثيات غير صحيحة.'`); write `rider_*` + `rider_location_at=now`; never touch `delivery_*`.
- Modify: `apps/delivery/views.py:1393-1394` (public tracking) — use `rider_lat/lng` when `rider_location_at` is within the last 30 min, else no rider pin.
- Modify: `apps/delivery/serializers.py` — expose `rider_lat`, `rider_lng`, `rider_location_at` read-only where `delivery_lat` is exposed (L141, L233); dispatch map uses them if it shows rider position (check `serializers.py:284` and `views.py:1244`; leave drop-off pins on `delivery_*`).
- Modify: `apps/users/management/commands/seed_permissions.py:178` → `'delivery': {'view', 'edit'}`, plus the comment.
- Migration: `apps/users/migrations/0034_security_n0.py` — `RunPython` sets `RoleModuleAccess(role='delivery', module='delivery', action__in=['approve','finalize']).is_allowed=False` (reverse sets True).
- Regenerate: `docs/security/PERMISSION_MATRIX.md` (drift-tested generator, see `apps/tests/security/permission_matrix.py`).
- Modify: `apps/help/content/delivery.py` — rider cannot cancel/close; the dispatcher does. Bump `updated`.
- Test: `apps/tests/security/test_delivery_rider_powers.py`.

**Interfaces:**
- Produces: `DeliveryOrder.rider_lat/rider_lng/rider_location_at` (later batches read them; N3 rider zone).

- [ ] **Step 1: Write the failing tests:**
  - `test_location_update_keeps_dropoff_target`: order with `delivery_lat=30.0`; rider posts `31.5` → `delivery_lat` still `30.0`, `rider_lat == 31.5`.
  - `test_location_rejects_junk` (`'abc'`, `91`, missing) → 400, order unchanged.
  - `test_dropoff_geofence_uses_original_target`: after a location update far away, completing at the real address passes and completing at the reported spot fails.
  - `test_rider_cannot_cancel_or_close_own_order` (403 each).
  - `test_rider_can_still_collect_cash_and_complete`.
  - `test_dispatcher_can_cancel_and_close` (supervisor/admin).
  - `test_tracking_shows_recent_rider_location_only`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.security.test_delivery_rider_powers --noinput` → FAIL.
- [ ] **Step 3: Implement** models, migrations, views, serializers, seed, the matrix doc and help.
- [ ] **Step 4: Run** the test plus `apps.delivery apps.tests.security.test_permission_matrix apps.tests.security.test_rbac_matrix_seeding apps.tests.test_help` → PASS.
- [ ] **Step 5: Commit** `fix(security): rider location no longer moves the drop-off target; riders cannot cancel/close (N0/H2,H3)`.

---

### Task 6: Open SOFTECH network probe (H5)

`GET /api/sync/branch-health/?probe=1` (`apps/sync/views.py:158-180`) lets any logged-in user start a live login to all 6 SOFTECH nodes.

**Files:**
- Modify: `apps/sync/views.py` `branch_health`.
- Test: `apps/tests/security/test_sync_probe_gate.py`.

**Behaviour:**
- `probe=1` runs `probe_all_nodes` only for `IsAdminRole`, and at most once per 60 s across all users (`cache.add('sync:branch-health:probe', 1, 60)`).
- Otherwise it returns the stored snapshot with `'probe': 'refused'` (non-admin) or `'probe': 'cooldown'`.
- HTTP 200 either way, so the panel still renders.

- [ ] **Step 1: Write the failing tests** (patch `apps.sync.network_health.probe_all_nodes`):
  - `test_non_admin_probe_refused` (mock not called, `probe == 'refused'`).
  - `test_admin_probe_runs_once_per_minute` (2 calls → mock called once, second `probe == 'cooldown'`).
  - `test_snapshot_still_returned`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.security.test_sync_probe_gate --noinput` → FAIL.
- [ ] **Step 3: Implement**; `SyncPage.jsx` shows «الفحص المباشر للمدير فقط» / «انتظر دقيقة» from the `probe` field; help in `apps/help/content/sync.py` (bump `updated`).
- [ ] **Step 4: Run** the test plus `apps.tests.test_help` → PASS.
- [ ] **Step 5: Commit** `fix(security): live SOFTECH network probe admin-only with cooldown (N0/H5)`.

---

### Task 7: Django admin exposure (H9)

nginx `/admin/` allows all of 10/8 (every ZeroTier member) and Django admin has no 2FA.

**Files:**
- Modify: `config/settings.py` — `DJANGO_ADMIN_ENABLED = config('DJANGO_ADMIN_ENABLED', default=DEBUG, cast=bool)`.
- Modify: `config/urls.py:7` — mount `admin/` only when enabled (otherwise 404).
- Create: `deploy/nginx-admin-allow.conf.example` — `allow 127.0.0.1;` + commented `# allow <owner ZeroTier IP>;` lines + `deny all;`.
- Modify: `deploy/nginx.conf:55-64` — replace the private-range allows with `include /etc/nginx/elrezeiky-admin-allow.conf;`.
- Modify: `deploy/staging.env.example` + runbook §8.2/§9.2 — `DJANGO_ADMIN_ENABLED=False` in production; turn on only for a maintenance window.
- Test: `apps/tests/security/test_admin_exposure.py`.

- [ ] **Step 1: Write the failing tests:**
  - `test_admin_404_when_disabled` (`override_settings` + `clear_url_caches`/reload urlconf).
  - `test_admin_mounted_when_enabled`.
  - `test_nginx_admin_has_no_private_range_allow` (no `allow 10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` in `deploy/nginx.conf`; include present).
- [ ] **Step 2: Run** `python manage.py test apps.tests.security.test_admin_exposure --noinput` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `fix(security): Django admin off in production; nginx admin allow-list per IP (N0/H9)`.

---

### Task 8: Whole-batch verification and docs

- [ ] **Step 1:** `python manage.py makemigrations --check --dry-run` → "No changes detected".
- [ ] **Step 2:** `python manage.py check --deploy` with production-like env → no new warnings versus main.
- [ ] **Step 3:** `python manage.py test --noinput` (full suite) → all PASS; compare the security baselines (`apps/tests/security/baselines/`) and bandit (normalize `/` vs `\` paths on Windows).
- [ ] **Step 4:** `cd frontend && npm run build` → success.
- [ ] **Step 5:** Update `docs/security/2026-10-31-network-device-access-design.md` §5 (mark H1–H3, H5–H9 fixed with commit ids; H4 → N3, H10 → owner) and `docs/security/TEST_SUITE.md` (N0 line). Commit `docs(security): N0 done`.
- [ ] **Step 6:** Owner applies on the VPS after merge: copy `elrezeiky-proxy-headers.conf` and `elrezeiky-admin-allow.conf` to `/etc/nginx/`, then `nginx -t && systemctl reload nginx`; set `DJANGO_ADMIN_ENABLED=False`; run migrations through `release.sh`.
