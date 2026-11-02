# Security N2 — Device Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every browser that completes a staff sign-in becomes a registered device (pending until an admin approves it). Admins approve, block or retire devices from a fast «الأجهزة» queue. Blocking a device ends its sessions at once. "Remember this device" for 2FA moves onto approved devices.

**Architecture:** A random device secret lives in an httpOnly cookie `erp_device`, and the server stores only its SHA-256. `apps/access/devices.py` owns create / resolve / approve / block / retire. Login stamps the device's public id into the JWT as claim `dev`. Refresh and `CookieJWTAuthentication` refuse a token whose `dev` is blocked or retired. `AccessContext` gains `device`. Zones and refusals by device *status* stay out of scope: that is N3. N2 only refuses **blocked/retired** devices, which is an explicit admin action.

**Tech Stack:** Django 5.2 / DRF / simplejwt (token_blacklist installed; rotation copies custom claims but does **not** create an OutstandingToken for the rotated token) · React 18 / Vite / TanStack Query.

**Spec:** `docs/security/2026-10-31-network-device-access-design.md` — §3 (current state), §6.2 (device registry), §6.4 points 2/4/7, §7.2 (admin-only approval + fast queue + bulk + admin notification), §8 row N2.

## Global Constraints

- Builds on N1 (`apps/access`, `AccessContext`, `NETWORK_POLICY_ENFORCEMENT`). Branch `claude/security-n2` stacked on `claude/security-n1`.
- Device approval is **admin only**: server-side `IsAdminRole` on every device write. Branch managers do not approve (§7.2).
- Device cookie: name `erp_device`; `httponly=True`, `secure=settings.AUTH_COOKIE_SECURE`, `samesite='Strict'`, `path='/'`, `max_age=400 days`. Value = `secrets.token_urlsafe(32)`. Store only `hashlib.sha256(value).hexdigest()`.
- Device statuses: `pending`, `approved`, `blocked`, `retired`. Kinds: `branch_pc`, `personal_laptop`, `phone`, `rider_phone`, `kiosk` (labels: «جهاز فرع», «لابتوب شخصي», «موبايل», «موبايل طيار», «كشك»).
- JWT claim name: `dev` = `Device.public_id` (a UUID string). Never put the secret or its hash in a token.
- Nothing in N2 refuses a request because a device is **pending** or **unknown**. Only `blocked` / `retired` refuse, and only for tokens carrying that device's `dev`.
- Every device change is audited with `AuditLog.log('device_changed', …)` using before/after snapshots, the same pattern as `trusted_network_changed` in `apps/access/views.py`.
- The legacy MFA `device_token` (localStorage) keeps working in N2. Removing it is N3. A new remember path is added on approved devices.
- Arabic UI copy. Calm UI: no modals for approve/block; one keystroke per action (`useGridKeyboard`: ↑↓ Space Enter M Ctrl+A).
- Every changed screen gets help in `apps/help/content/` (AR + EN), with `updated` = 2026-11-01. `apps/tests/test_help.py` must pass.
- Use `SimpleRouter`, never `DefaultRouter`: a DRF API root trips the role sweep.
- Tests: `TEST_DB_NAME=test_n2_<task>` with `venv/Scripts/python.exe manage.py test …`. Never run two suites at once.

## Review Focus

1. **Shared branch PC:** several staff sign in on one browser. It must stay ONE device with several `DeviceUser` rows; a second user must not create a second device or reset approval. *(Task 2 test `test_second_user_same_browser_reuses_device`.)*
2. **Stale or forged cookie:** an `erp_device` value matching no row, or a cookie of a retired device, must create a fresh pending device at the next sign-in, never 500 and never revive the old row. *(Task 2 test `test_unknown_cookie_gets_new_device`, `test_retired_cookie_gets_new_device`.)*
3. **Blocking during a live session:** after an admin blocks a device, the very next API call with its access token answers 401, and `/api/auth/refresh/` refuses and clears cookies. A token with no `dev` claim (scripts, old sessions) keeps working. *(Task 3 tests.)*
4. **Per-request cost:** resolving the device must not add an uncached DB query to every request, and `last_seen` writes at most once per 10 min per device. *(Task 3 test `test_device_resolve_is_cached`.)*
5. **Remember-device after forget/block:** "forget saved devices" (N0 epoch) or blocking the device must cancel the approved-device 2FA skip. *(Task 4 tests.)*

---

### Task 1: Device model, secret helpers, audit + log fields

**Files:**
- Create: `apps/access/devices.py`
- Modify: `apps/access/models.py`, `apps/audit/models.py` (action `device_changed` «جهاز — اعتماد / حظر / تعديل»), `apps/users/models.py` (`UserActivityLog.device` FK → `access.Device`, null, `SET_NULL`, related_name `activity`)
- Migrations: `apps/access/migrations/0003_device.py`, `apps/users/migrations/0036_activitylog_device.py`, audit choices migration (next free number in `apps/audit/migrations/`)
- Test: `apps/tests/security/test_access_devices.py`

**Interfaces:**
- Produces, in `apps/access/models.py`:
  - `Device`: `public_id` (UUIDField, default uuid4, unique), `secret_hash` (CharField 64, unique), `name` (120), `kind` (choices above, default `personal_laptop`), `status` (choices above, default `pending`), `branch` FK `branches.Branch` null PROTECT, `owner` FK `users.StaffProfile` null SET_NULL, `allowed_roles` JSONField default list (stored only; enforced in N3), `first_ip` / `last_ip` (GenericIPAddressField null), `first_network` / `last_network` (CharField 10), `last_site` (CharField 120), `user_agent` (300), `first_seen` (auto_now_add), `last_seen` (DateTime null), `approved_by` FK StaffProfile null SET_NULL, `approved_at`, `status_note` (CharField 200), `updated_by`. Meta ordering `['status', '-first_seen']`.
  - `DeviceUser`: `device` FK CASCADE, `user` FK StaffProfile CASCADE, `first_seen` auto, `last_seen`, `mfa_remembered_at` (DateTime null), `mfa_remembered_epoch` (PositiveIntegerField null). `unique_together (device, user)`.
- Produces, in `apps/access/devices.py`:
  - `COOKIE = 'erp_device'`, `COOKIE_MAX_AGE = 400 * 24 * 3600`
  - `new_secret() -> str`, `hash_secret(secret: str) -> str`
  - `from_secret(secret: str | None) -> Device | None`: the matching row, or None for a missing, unknown or retired cookie
  - `guess_kind(user_agent: str, network) -> str`: mobile UA → `phone`; internal site with a branch → `branch_pc`; else `personal_laptop`
  - `snapshot(device) -> dict`: the audited fields

- [ ] **Step 1: Write failing tests**: `test_hash_is_sha256_and_secret_never_stored`, `test_from_secret_none_unknown_retired` (missing → None, unknown → None, retired → None, pending → row), `test_guess_kind` (iPhone UA → `phone`; internal site with branch → `branch_pc`; desktop external → `personal_laptop`), `test_device_user_unique`.
- [ ] **Step 2: Run them**: `manage.py test apps.tests.security.test_access_devices` → FAIL (no module).
- [ ] **Step 3: Implement** the models, migrations and helpers above. `makemigrations --check` must report clean afterwards.
- [ ] **Step 4: Run them** → PASS. Also run `apps.tests.security.test_access_api` (N1 still green).
- [ ] **Step 5: Commit** `feat(security): device registry model + secret helpers (N2)`.

### Task 2: Enrollment at sign-in + `dev` claim + alerts

**Files:**
- Modify: `apps/users/views.py` (`login_view` no-2FA success path; `_log_auth` gains `device=None`), `apps/users/mfa.py` (`build_login_response(user, request=None)`; `session_response(payload, status_code=200, device_secret=None)`; callers `verify_2fa_view`, `enable_2fa_view` pass `request`), `apps/access/devices.py`, `core/auth_cookies.py` (`set_device_cookie(response, secret)`)
- Test: `apps/tests/security/test_access_devices.py`, `apps/users/tests_mfa.py` (existing tests must stay green)

**Interfaces:**
- Consumes: Task 1.
- Produces, in `apps/access/devices.py`:
  - `enroll(request, profile) -> tuple[Device, str | None, bool]`: (device, new_secret_or_None, created).
    - The request's `erp_device` cookie resolves through `from_secret` → reuse that device and return secret None.
    - Otherwise create a `pending` Device: kind from `guess_kind`; name `f'{ua_short} — {profile.full_name or username}'`, where `ua_short` is the browser + OS words from the UA, max 120; owner = profile; branch = site branch when internal, else `profile.branch`. Return the new secret.
    - Always: upsert `DeviceUser`; set last_ip / last_network / last_site / last_seen / user_agent.
    - Never raises. On error it logs a warning and returns `(None, None, False)`, and the sign-in still succeeds.
  - `notify_new_device(device, profile)`: `Notification.send_to_user(..., 'system', ...)` to the profile and to every active admin, with `dedup_key=f'device_new_{device.pk}'`.
    - Title «💻 جهاز جديد بانتظار الاعتماد».
    - Body names the user, the device name and the network label (`NetworkInfo.label_ar`).
    - Never raises. Called only when `created`.
- Sign-in completion (all three paths: password-only, 2FA verify, 2FA enable at login):
  1. Call `enroll`.
  2. Add claim `refresh['dev'] = str(device.public_id)` before minting the access token, so the access token copies it.
  3. Set the device cookie when a new secret was made.
  4. Write `login_success` / `mfa_verified` with `device=device`.

- [ ] **Step 1: Write failing tests**:
  - `test_first_login_creates_pending_device_and_cookie`: cookie `erp_device` is httpOnly and SameSite=Strict; the DB stores no raw secret; `status='pending'`.
  - `test_access_token_carries_dev_claim`: decode the `erp_access` cookie; `dev == str(public_id)`.
  - `test_second_login_same_cookie_reuses_device`.
  - `test_second_user_same_browser_reuses_device`: two `DeviceUser` rows, one Device, status unchanged.
  - `test_unknown_cookie_gets_new_device`.
  - `test_retired_cookie_gets_new_device`.
  - `test_new_device_notifies_user_and_admins`: one Notification for the user and one per admin; none on the second login.
  - `test_enroll_failure_does_not_break_login`: patch `enroll` internals to raise → 200 and the tokens are still issued.
  - `test_2fa_verify_path_enrolls`.
  - `test_failed_password_creates_no_device`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**, following the Interfaces block.
- [ ] **Step 4: Run** the new tests, then `apps.users.tests_mfa`, `apps.tests.security.test_auth_lockout`, `apps.tests.security.test_auth_mfa`, `apps.tests.security.test_auth_sessions` → all PASS.
- [ ] **Step 5: Commit** `feat(security): enroll a device at sign-in, dev claim, new-device alert (N2)`.

### Task 3: Device in the access context; blocked device ends sessions

**Files:**
- Modify:
  - `apps/access/context.py`: `AccessContext.device: DeviceInfo | None`
  - `apps/access/devices.py`
  - `apps/access/middleware.py`: no change in shape; the device comes through `for_request`
  - `core/auth_cookies.py`: `CookieJWTAuthentication.get_user` and `user_from_request`
  - `apps/users/views.py`: `refresh_view`
  - `apps/access/views.py`: `whoami` adds `device`
- Test: `apps/tests/security/test_access_devices.py`, `apps/tests/security/test_access_context.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces, in `apps/access/devices.py`:
  - `@dataclass(frozen=True) DeviceInfo(public_id: str, status: str, name: str, kind: str)`
  - `resolve(request) -> DeviceInfo | None`: from the cookie hash.
    - Cached under `access:dev:<hash>` for `DEVICE_CACHE_SECONDS = 60`.
    - Touches last_seen/last_ip at most once per `TOUCH_SECONDS = 600` per device, via `cache.add(f'access:devtouch:{pk}', 1, 600)` + `QuerySet.update`.
    - Never raises.
  - `is_revoked(public_id: str | None) -> bool`: True when that device is `blocked` or `retired`; False for None or unknown.
    - Cached under `access:devrev:<public_id>` for 60 s.
  - `invalidate(device)`: clears both cache keys. Call it from a `post_save` signal on Device.
- `whoami` response gains `device: null | {status, status_label, name}`. It is `null` for anonymous callers, so an anonymous call reveals nothing about devices.
- Revocation rule:
  - If the validated token's `dev` claim `is_revoked` → `AuthenticationFailed('هذا الجهاز موقوف — تواصل مع المدير', code='device_blocked')`.
  - `refresh_view` returns 401 with the same message and clears the auth cookies.
  - A token without `dev` is unaffected.

- [ ] **Step 1: Write failing tests**:
  - `test_blocked_device_access_token_refused` (401 on `/api/auth/me/`).
  - `test_blocked_device_refresh_refused_and_cookies_cleared`.
  - `test_token_without_dev_claim_unaffected`.
  - `test_retired_device_refused`.
  - `test_unblock_restores` (approve again → 200 after cache invalidation).
  - `test_device_resolve_is_cached`: `assertNumQueries` shows the second resolve makes 0 queries.
  - `test_last_seen_touched_once_per_window`.
  - `test_context_has_device`.
  - `test_whoami_device_null_when_anonymous`.
  - `test_whoami_device_when_signed_in`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests plus `apps.tests.security.test_access_context`, `test_access_api`, `test_auth_sessions`, `test_auth_websocket` → PASS.
- [ ] **Step 5: Commit** `feat(security): device in access context; blocked device ends its sessions (N2)`.

### Task 4: "Remember this device" on approved devices

**Files:**
- Modify: `apps/users/mfa.py` (`verify_2fa_view`, `forget_devices`), `apps/users/views.py` (`login_view` 2FA gate), `apps/access/devices.py`
- Test: `apps/tests/security/test_access_devices.py`, `apps/users/tests_mfa.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces, in `apps/access/devices.py`:
  - `remember_mfa(device, profile)`: sets `DeviceUser.mfa_remembered_at=now`, `mfa_remembered_epoch=profile.mfa_device_epoch`.
  - `mfa_remembered(request, profile) -> bool`: True only when **all** of these hold:
    - the cookie's device is `approved`;
    - its DeviceUser for the profile has `mfa_remembered_at` within 30 days;
    - `mfa_remembered_epoch == profile.mfa_device_epoch`.
- `verify_2fa_view`: when `remember_device` is set, also call `remember_mfa` on the enrolled device. The legacy `device_token` stays in the response.
- `login_view` skips the 2FA challenge when `valid_device_token(...)` **or** `mfa_remembered(request, profile)`.
- `forget_devices` already bumps the epoch, which cancels both paths. Add an assertion test only.

- [ ] **Step 1: Write failing tests**:
  - `test_remembered_on_approved_device_skips_2fa`.
  - `test_remembered_on_pending_device_still_challenged`.
  - `test_forget_devices_cancels_device_remember`.
  - `test_blocked_device_cancels_remember`.
  - `test_remember_expires_after_30_days`.
  - `test_legacy_device_token_still_works`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests plus `apps.users.tests_mfa`, `apps.tests.security.test_auth_mfa`, `test_auth_mfa_attempts` → PASS.
- [ ] **Step 5: Commit** `feat(security): remember 2FA on approved devices (N2)`.

### Task 5: Admin device API (approve / block / retire / bulk), audited

**Files:**
- Modify: `apps/access/views.py`, `apps/access/serializers.py`, `apps/access/urls.py`, `apps/access/devices.py`
- Modify: `apps/tests/security/baselines/role_overblocks.txt`. Add rows only if the sweep reports pharmacist/purchasing GET overblocks on `/api/access/devices/…`, under one `# reason:` block: «admin only — §7.2 owner decision».
- Test: `apps/tests/security/test_access_devices_api.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `DeviceViewSet` at `/api/access/devices/` (SimpleRouter, basename `device`), `IsAdminRole`.
    - Methods: list / retrieve / partial_update. No create; no delete — retire instead.
    - Filters: `?status=`, `?branch=`, `?kind=`, `?q=` (name / user / IP, using `apps/catalog/wildcard.py` like other searches).
    - Default list order: `pending` first, then `-first_seen`.
    - Each row includes: `users` [{id, name, role, last_seen, mfa_remembered}], `branch_label`, `status_label`, `kind_label`, `last_network_label`.
  - Actions, each taking an optional `note`:
    - `POST {id}/approve/` → status `approved`, approved_by / approved_at.
    - `POST {id}/block/` → `blocked`, note **required** (400 «اكتب سبب الحظر»).
    - `POST {id}/retire/` → `retired`.
    - `POST bulk-approve/` with `{ids: [...]}` → approves pending ones only and returns `{approved: n, skipped: m}`.
  - `devices.set_status(device, status, by, note='') -> Device`:
    - updates the row;
    - calls `invalidate`;
    - writes `AuditLog.log('device_changed', ..., changes={'before': .., 'after': ..})`;
    - writes a `UserActivityLog` row `action='device_status'`, with `target_user=device.owner` and the device. Add this action to the users action choices plus a migration if the choices are enforced.
  - partial_update fields: `name`, `kind`, `branch`, `owner`, `allowed_roles`. These are audited too.
  - `MODULE_BY_PREFIX` already maps `access` → `settings`; no change.

- [ ] **Step 1: Write failing tests**:
  - `test_devices_admin_only` (pharmacist / supervisor / delivery → 403 on list and every action).
  - `test_pending_listed_first`.
  - `test_approve_audited_before_after`.
  - `test_block_requires_note`.
  - `test_block_then_token_refused` (end-to-end with Task 3).
  - `test_bulk_approve_only_pending`.
  - `test_patch_kind_branch_audited`.
  - `test_no_delete_no_create` (405).
  - `test_filter_status_and_search`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests, then the sweeps `apps.tests.security.test_role_sweep apps.tests.test_endpoint_sweep apps.tests.security.test_static_guards` → PASS. Add baseline rows only as described above.
- [ ] **Step 5: Commit** `feat(security): admin device API — approve/block/retire/bulk, audited (N2)`.

### Task 6: «الأجهزة» screen, badge, help, docs

**Files:**
- Create: `frontend/src/pages/DevicesPage.jsx`
- Modify:
  - `frontend/src/App.jsx`: route `/access/devices`, `RequireRole` admin
  - the nav entry next to «الشبكات الموثوقة»
  - `frontend/src/api/client.js`: `accessApi.devices*`
  - `frontend/src/components/NetworkBadge.jsx`: append the device status word when `whoami.device` is present — «جهاز معتمد» / «جهاز بانتظار الاعتماد» / no text when null
  - `frontend/src/pages/UserManagementPage.jsx`: activity log row shows the device name when present
  - `apps/users/serializers.py` (or wherever the activity-log serializer lives): `device_name`
  - `apps/help/content/admin.py`: new `admin.devices` entry plus bumps of `admin.users` and `general.main` (the badge)
  - Docs:
    - `docs/architecture/11_ERP_INDEX.md` (module / API / screen rows)
    - `docs/architecture/04_API_REGISTRY.md` (ACCESS section rows)
    - design doc §8 N2 row → «Built 2026-11-01 …»
    - runbook: a short «Batch N2 on the live server» section. No nginx change; `migrate`. Rollout: open «الأجهزة», bulk-approve each branch's PCs after staff sign in once.
- Test: `apps/tests/test_help.py` (must pass)

**Interfaces:**
- Consumes: the Task 5 API and the Task 3 `whoami.device`.
- Screen behaviour:
  - Tabs «بانتظار الاعتماد» (default) / «المعتمدة» / «المحظورة والمتقاعدة» call `useHelpTab(tab)`.
  - Grid columns: الجهاز، النوع، الفرع، المستخدمون، الشبكة / IP، أول ظهور، آخر ظهور.
  - Keyboard via `useGridKeyboard`: ↑↓ move, Space select, Enter = approve the focused row, M = mark, Ctrl+A select all.
  - Buttons: «اعتماد المحدد», «حظر» (inline note field, no modal), «تقاعد».
  - Inline edit of name / kind / branch.
  - The page must not unmount its grid on reload (see the review-grid keyboard memory: keep rows mounted, show refetch state in place).
  - A refresh button invalidates the query.

- [ ] **Step 1:** Add the help entries and run `manage.py test apps.tests.test_help` → it FAILS on the new route until the route and help exist, then PASSES.
- [ ] **Step 2:** Build the screen, the badge text and the activity-log device name.
- [ ] **Step 3:** In `frontend/`, run `npm run build` → success.
- [ ] **Step 4:** Update the docs and runbook listed above.
- [ ] **Step 5:** Run `manage.py test apps.tests.test_help apps.tests.security.test_access_devices apps.tests.security.test_access_devices_api` → PASS.
- [ ] **Step 6: Commit** `feat(security): «الأجهزة» approval queue, badge device status, help + docs (N2)`.

---

## Out of scope (later batches)

- Refusing or limiting **pending / unknown** devices, using `allowed_roles`, external profiles, session caps → N3.
- Removing the legacy localStorage `device_token` → N3, once devices are approved.
- WebAuthn passkeys for admin / finance, and WebSocket re-check on block → N5.
- Branch-manager read-only view of their branch's devices: deferred. Admin is the only viewer in N2; adding a read-only filtered view later is cheap.
