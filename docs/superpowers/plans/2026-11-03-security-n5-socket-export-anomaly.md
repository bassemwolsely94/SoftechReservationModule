# Security N5 — WebSocket re-check, export watermark, bulk-read alerts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three N5 gaps from the access design: a WebSocket outlives the zone rules, a token's expiry, a disabled account and a blocked device; an exported file carries no trace of who took it; and nobody notices one user pulling far more customer data than normal.

**Architecture:**
- **Sockets.** A socket handshake is turned into a request-shaped object, so the existing N1–N3 code (`request_network`, `devices.resolve`, `zone_for`, `policy.decide`) works out its zone unchanged.
- **Consumers.** A mixin on the three consumers runs that check at connect and every 5 minutes. It also runs at once when the server pushes a re-check, which happens on a disable, a device block or a policy change.
- **Exports.** Every export response is audited with an export id. Excel and Word files also get the id, user, time, device and zone written into their document properties by rewriting the zip. No new dependency is needed.
- **Bulk-read alerts.** A per-user hourly counter of customer rows and exports raises an admin alert. When its own switch is set to enforce, it also applies a short block.

**Tech Stack:** Django 5 / DRF, Django Channels (AsyncWebsocketConsumer, channel layer groups), openpyxl (tests only), zipfile, Postgres, React hooks (`useNotificationSocket`, `useChatterSocket`).

**Spec:** `docs/security/2026-10-31-network-device-access-design.md`:
- §3 row "WebSocket";
- §6.4 item 6;
- §6.6 bullets 1 and 3;
- §8 row N5.

## Global Constraints

- Nothing new refuses anything while the switches are at their defaults:
  - socket checks follow `NETWORK_POLICY_ENFORCEMENT` (default `log`);
  - bulk-read blocking follows a new `BULK_READ_ENFORCEMENT` = off / log / enforce, default `log`;
  - an unknown value counts as `log`.
- Two closes happen in every mode, because N2 already refuses these at connect: a disabled account and a blocked or retired device.
- The policy only narrows access and never widens it. A socket gets exactly what the same user would get over HTTP from the same zone (parity), plus one rule:
  - the PBX agent socket (live caller numbers) is internal-only, Z1/Z2.
- Close codes:
  - `4001` signed out, disabled or device revoked (existing; the client falls back to polling);
  - `4002` access token expired (new; the client reconnects normally);
  - `4403` refused by the zone policy (new; the client falls back to polling like 4001).
- Re-check interval `WS_RECHECK_SECONDS = 300`.
- Every refusal, export and alert is auditable (CLAUDE.md rule 8). New AuditLog actions:
  - `ws_zone_denied` 'اتصال مباشر — رفض حسب المنطقة';
  - `export_taken` 'تصدير ملف';
  - `bulk_read_alert` 'قراءة بيانات بكمية غير معتادة'.
  - All three go in one audit migration.
- Permissions stay server-side; the frontend only reacts to close codes.
- No SOFTECH reads or writes in this batch. No POS, pricing or checkout code is touched.
- A file the user downloads must still open exactly as before. Stamping only adds document properties: no extra sheet, no cell change, CSV and PDF bodies left untouched.
- Branch codes are never shown bare in user-facing text. Say «سيرفر», not «خادم». Help is Arabic + English, and `updated` is bumped.
- Background threads use `core.threads.start_thread` (the N4 guard test forbids bare `threading.Thread`).
- Tests use a unique `TEST_DB_NAME=test_n5 --keepdb`.

## Review Focus

1. **A socket opened before a token refresh**, when the user keeps working and the HTTP cookie keeps renewing: the socket closes with 4002 at the old token's expiry and the client reconnects silently with the new cookie. It must never fall back to polling or show an error. *(Task 2 test `test_expired_token_closes_4002_and_hook_reconnects`.)*
2. **The channel layer is down or Redis is unreachable** when a device is blocked: the block itself still succeeds, and the periodic re-check closes the socket within 5 minutes. *(Task 3 test `test_push_failure_never_breaks_block`.)*
3. **A very large or streamed export**, such as a write-only workbook or a FileResponse: it is never loaded into memory to stamp. It is audited and passed through untouched. *(Task 4 tests `test_streaming_export_audited_not_stamped` and `test_oversize_export_not_stamped`.)*
4. **A file that isn't valid OOXML** but is served with an xlsx content type: it is passed through untouched and still audited. The download never fails because of the stamp. *(Task 4 test `test_corrupt_xlsx_passes_through`.)*
5. **An admin doing legitimate bulk work**, such as a full customer export: an alert is allowed, but the admin is never blocked, because a self-lockout cannot be recovered without the server. *(Task 5 test `test_admin_alerted_never_blocked`.)*

---

### Task 1: Socket access context and verdict

**Files:**
- Create: `apps/access/ws.py`
- Test: `apps/tests/security/test_access_ws_verdict.py`

**Interfaces:**
- Consumes:
  - `context.AccessContext`;
  - `network.request_network(request)`;
  - `devices.resolve(request)`, `devices.is_revoked(public_id)`;
  - `zones.zone_for`;
  - `policy.policy_for`, `policy.decide`;
  - `policy_middleware._mode()`;
  - `session_policy.subject(user)`;
  - `users.sessions.account_active(user)`.
- Produces:
  - `class ScopeRequest` — built from a Channels `scope`. It exposes:
    - `META`: `REMOTE_ADDR` from `scope['client'][0]`, and each header as `HTTP_<UPPER_SNAKE>`;
    - `COOKIES` (dict);
    - `path` and `path_info` (`scope['path']`);
    - `method = 'GET'`;
    - `GET = {}`.
  - `context_for_scope(scope, user) -> AccessContext`. It never raises; on error it returns `context.fallback(ScopeRequest(scope))` with `user_id`/`role` filled.
  - `SOCKET_KINDS = {'notifications': ('/api/notifications/', None), 'chatter': ('/api/notifications/chatter/', None), 'pbx': ('/ws/pbx/agent/', 'callcenter')}` — kind → (path given to `policy.decide`, module).
  - `@dataclass(frozen=True) class WsVerdict: allowed: bool; close_code: int | None; reason: str | None; zone: str | None; enforced: bool`.
  - `verdict(scope, user, kind, token_exp=None, now=None) -> WsVerdict`.
  - Constants `CLOSE_AUTH = 4001`, `CLOSE_EXPIRED = 4002`, `CLOSE_ZONE = 4403`, `WS_RECHECK_SECONDS = 300`.

`verdict` order, first match wins:
1. Not `account_active(user)` → `(False, 4001, 'inactive', …, enforced=True)`.
2. The device cookie's `public_id` is revoked → `(False, 4001, 'device_revoked', …, enforced=True)`.
3. `token_exp` is set and `now >= token_exp` → `(False, 4002, 'expired', …, enforced=True)`.
4. Mode `off` → allowed.
5. Zone rules, using `subject(user)` as the profile and the context zone (a `failed` context on an internal network is allowed, F3 parity):
   - kind `pbx` in Z3/Z4 → reason `'module'`;
   - otherwise `policy.decide(profile, zone, path, 'GET', module=module)` for the kind's path/module.
   - Refused → `(False, 4403, reason, zone, enforced=(mode == 'enforce'))`; the caller closes only when `enforced`.

- [ ] **Step 1: Write the failing tests** (pytest-style names under `class WsVerdictTests(TestCase)`, using `make_user` from the existing security test helpers):
  - `test_scope_request_maps_headers_cookies_client`: given a scope with `x-elr-network: internal`, `cookie: erp_device=abc` and client `('10.0.0.5', 1234)`:
    - `META['HTTP_X_ELR_NETWORK'] == 'internal'`;
    - `COOKIES['erp_device'] == 'abc'`;
    - `META['REMOTE_ADDR'] == '10.0.0.5'`.
  - `test_inactive_user_closes_4001_in_every_mode`: patch the mode to `off` and expect `close_code == 4001`, `enforced is True`.
  - `test_revoked_device_closes_4001`.
  - `test_expired_token_closes_4002`: `token_exp = now - 1`.
  - `test_pbx_outside_refused_4403_in_enforce`: zone patched to Z3, role `call_center`, mode `enforce` → `(False, 4403, 'module')`.
  - `test_pbx_outside_log_mode_not_enforced`: same, mode `log` → `allowed is False`, `enforced is False`.
  - `test_notifications_allowed_for_rider_outside`: role `delivery`, Z4.
  - `test_blocked_role_outside_notifications_parity`: role `pharmacist`, Z3. The `/api/notifications/` path is always open over HTTP too, so parity means the result is `allowed is True`. This test pins that parity on purpose (sign-in and refresh already refuse that role outside).
  - `test_context_failure_internal_allowed_external_refused`.
- [ ] **Step 2:** Run `TEST_DB_NAME=test_n5 python manage.py test apps.tests.security.test_access_ws_verdict --keepdb`. Expected: FAIL (ImportError).
- [ ] **Step 3:** Implement `apps/access/ws.py` per the Interfaces above. `context_for_scope` reuses `context.for_request` on a `ScopeRequest`, but resolves the user from the argument instead of `user_from_request`: build the AccessContext with that user's pk and role.
- [ ] **Step 4:** Run the same command. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(security): socket access context and verdict (N5)`.

### Task 2: Consumers check at connect, every 5 minutes and on push; clients react

**Files:**
- Modify:
  - `apps/access/ws.py` (add the mixin);
  - `apps/notifications/middleware.py` (keep the token's `exp` and `dev` in the scope);
  - `apps/notifications/consumers.py` (NotificationConsumer, ChatterConsumer);
  - `apps/pbx/consumers.py` (AgentCallConsumer);
  - `apps/audit/models.py` and a new migration `apps/audit/migrations/0023_n5_actions.py` (all three N5 actions);
  - `frontend/src/hooks/useNotificationSocket.js`, `frontend/src/hooks/useChatterSocket.js`, and the PBX agent socket hook if one exists (find it with `grep -rn "ws/pbx" frontend/src`).
- Test: `apps/tests/security/test_access_ws_consumers.py` (WebsocketCommunicator, same style as `test_auth_websocket.py`)

**Interfaces:**
- Consumes: `verdict`, `WsVerdict` and the constants from Task 1.
- Produces:
  - `class ZoneGuardMixin` with `socket_kind: str` (class attribute), plus:
    - `async def zone_admit(self) -> bool` — call it in `connect()` after the existing user check and before `accept()`;
    - `async def zone_start(self)` — call it after `accept()`; it joins group `f'access_user_{user.pk}'` and `'access_all'` and starts the re-check loop;
    - `async def zone_stop(self)` — call it in `disconnect()`;
    - handler `async def access_recheck(self, event)` — the channel-layer message type `'access.recheck'`.
  - The middleware sets `scope['token_exp']` (int epoch) and `scope['token_dev']` (str or None) when a token was read.

Behaviour:
- `zone_admit`:
  - refused and `enforced` → close with the verdict's code and return False;
  - refused and not enforced → one deduplicated warning log line (`'ws would-deny user=… kind=… zone=… reason=…'`, cache key per user/kind/zone/reason, 600 s) and admit.
  - A zone refusal (4403) writes AuditLog `ws_zone_denied`, deduplicated the same way. A 4001/4002 refusal writes no audit row.
- The re-check loop is an `asyncio` task: `asyncio.sleep(WS_RECHECK_SECONDS)`, then the same verdict; a refused and enforced verdict closes. The task is cancelled in `zone_stop`.
- `access_recheck` runs the verdict once immediately.
- Frontend:
  - 4403 → the same branch as 4001 (polling);
  - 4002 → the normal back-off reconnect, with the delay reset to the minimum.

- [ ] **Step 1: Write the failing tests:**
  - `test_connect_refused_4403_in_enforce`: PBX socket, zone patched to Z3, mode `enforce` → `connected is False`, close code 4403; one `ws_zone_denied` AuditLog row.
  - `test_connect_admitted_in_log_mode_with_warning`.
  - `test_recheck_push_closes_disabled_user`: connect, set `is_active=False`, `group_send('access_user_<pk>', {'type': 'access.recheck'})` → output close 4001.
  - `test_expired_token_closes_4002_and_hook_reconnects`: patch `WS_RECHECK_SECONDS` to 0.05 and `token_exp` to now+0.01 → close 4002. The frontend half is checked by reading the hook diff: 4002 goes to reconnect, not polling.
  - `test_chatter_still_checks_record_access_after_zone_admit`: an existing W-3 refusal (4003) still happens.
  - `test_disconnect_cancels_recheck_task`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement the mixin, the middleware scope fields, the three consumers, the audit actions with their migration (`makemigrations audit -n n5_actions`), and the two or three frontend hooks.
- [ ] **Step 4:** Run:
  - `test_access_ws_consumers`, `test_auth_websocket` and `test_platform_chatter_socket`;
  - `python manage.py makemigrations --check --dry-run`;
  - `cd frontend && npm run build`.
  Expected: all PASS / no changes / build OK.
- [ ] **Step 5:** Commit: `feat(security): sockets re-check zone, expiry and revocation (N5)`.

### Task 3: Server pushes a re-check on disable, device change and policy change

**Files:**
- Modify:
  - `apps/access/ws.py` (push helpers);
  - `apps/users/sessions.py` (`end_sessions`);
  - `apps/access/devices.py` (`set_status`);
  - `apps/access/apps.py` (signal wiring for ZonePolicy and TrustedNetwork save/delete).
- Test: `apps/tests/security/test_access_ws_push.py`

**Interfaces:**
- Produces:
  - `push_recheck(user_ids=None) -> None`:
    - with ids → `group_send(f'access_user_{id}', {'type': 'access.recheck'})` for each id;
    - with None → `group_send('access_all', …)`.
    - It runs after commit (`transaction.on_commit`). It never raises: an exception is logged at WARNING with the error, and no traceback reaches the caller.
- Call sites:
  - `end_sessions(user)` → `push_recheck([user.pk])`;
  - `set_status(device, status, …)`, on any status change → `push_recheck(<user ids linked to the device through DeviceUser>)`;
  - ZonePolicy or TrustedNetwork post_save/post_delete → `push_recheck(None)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_end_sessions_pushes_user_group` (mock `group_send`, `captureOnCommitCallbacks(execute=True)`);
  - `test_block_device_pushes_its_users`;
  - `test_zone_policy_save_pushes_all`;
  - `test_push_failure_never_breaks_block`: `group_send` raises → `set_status` still returns, and the device is blocked in the DB.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run this test file plus `apps.tests.security` device/session tests (`test_access_devices*`, `test_users_sessions*` — whatever exists). Expected: PASS.
- [ ] **Step 5:** Commit: `feat(security): push socket re-check on disable, device and policy changes (N5)`.

### Task 4: Every export audited; Excel and Word files stamped

**Files:**
- Create:
  - `core/export_stamp.py`;
  - `apps/access/export_middleware.py`.
- Modify: `config/settings.py` (MIDDLEWARE: put `apps.access.export_middleware.ExportAuditMiddleware` right after `ZonePolicyMiddleware`; add `EXPORT_STAMP_MAX_BYTES = 50 * 1024 * 1024`).
- Test: `apps/tests/security/test_access_export_stamp.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) ExportMark: export_id: str; username: str; at: str (ISO, Africa/Cairo); device: str; zone: str; ip: str`.
  - `stamp_ooxml(content: bytes, mark: ExportMark) -> bytes`. It rewrites `docProps/core.xml`:
    - `dc:creator` / `cp:lastModifiedBy` = username;
    - `dc:description` = the one-line Arabic + English text `'تصدير {export_id} — {username} — {at} — {device} — {zone}'`;
    - `cp:keywords` = `export_id`.
    It also adds or replaces `docProps/custom.xml` with properties `ElR-ExportId`, `ElR-User`, `ElR-At`, `ElR-Device`, `ElR-Zone`, `ElR-IP`, and adds the custom-properties relationship and content-type override when they are missing.
    All other zip members are copied byte for byte. A non-zip or malformed package raises `ValueError`.
  - `ExportAuditMiddleware`: a response counts as an export when either is true:
    - `policy.is_export(path, method, query)` and status 200;
    - `Content-Disposition` contains `attachment`.
    For each export it:
    - writes one `AuditLog` `export_taken` (user, path, zone, device public_id, ip, export_id, content type, byte size or null when streaming);
    - sets the response header `X-ElR-Export-Id`;
    - stamps the body only when all of these hold: not streaming, content type is xlsx (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`) or docx, and size ≤ `EXPORT_STAMP_MAX_BYTES`. On a `ValueError` it leaves the body untouched and logs a deduplicated warning. It sets `Content-Length` again after stamping.
    - It never raises out of the middleware.
  - Anonymous responses are skipped.

- [ ] **Step 1: Write the failing tests:**
  - `test_stamp_roundtrip_opens_and_keeps_cells`: build an openpyxl workbook with 3 cells, stamp it, reload it with openpyxl → the cells are the same, `wb.properties.creator == username`, and `export_id in wb.properties.keywords`; `custom_doc_props['ElR-ExportId'].value == export_id` (openpyxl ≥ 3.1).
  - `test_stamp_keeps_other_members_identical`: every zip member except docProps/rels/content types has the same bytes.
  - `test_corrupt_xlsx_passes_through`: the view returns `b'not a zip'` with the xlsx content type → same body, one audit row.
  - `test_streaming_export_audited_not_stamped`.
  - `test_oversize_export_not_stamped`: `EXPORT_STAMP_MAX_BYTES=10`.
  - `test_csv_export_audited_body_unchanged`.
  - `test_non_export_response_not_audited`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Use `xml.etree.ElementTree` with the OOXML namespaces registered, so prefixes survive the round trip.
- [ ] **Step 4:** Run this file, then `apps.tests.security` and 3 existing export tests (e.g. `grep -rl "spreadsheetml" apps/tests | head -3`). Expected: PASS.
- [ ] **Step 5:** Commit: `feat(security): audit every export and stamp Excel/Word files (N5)`.

### Task 5: Bulk-read anomaly alert and temporary block

**Files:**
- Create: `apps/access/bulk_read.py`.
- Modify:
  - `apps/access/export_middleware.py` (count after the response, so one middleware sees both);
  - `apps/access/checks.py` (W004 for an unknown `BULK_READ_ENFORCEMENT`);
  - `config/settings.py`;
  - `apps/access/preflight.py` (an informational item `bulk_read_mode`).
- Test: `apps/tests/security/test_access_bulk_read.py`

**Interfaces:**
- Settings (env-overridable, same pattern as the other switches):
  - `BULK_READ_ENFORCEMENT='log'`;
  - `BULK_READ_ROWS_PER_HOUR=3000`;
  - `BULK_EXPORTS_PER_HOUR=30`;
  - `BULK_READ_BLOCK_MINUTES=30`;
  - `BULK_READ_PATHS=('/api/customers/',)`.
- Produces:
  - `rows_in(response) -> int`: `len(data['results'])` for a paginated DRF body, `len(data)` for a list body, else 0.
  - `record(user, *, rows=0, export=False) -> str | None`. It adds to cache counters keyed `access:bulk:{user.pk}:{YYYYMMDDHH}` (TTL 2 h). When a limit is first crossed in that hour it returns `'rows'` or `'exports'`, and None otherwise.
  - `alert(user, kind, request)`:
    - one AuditLog `bulk_read_alert` with the counts;
    - `devices.admin_digest(...)` with title `'قراءة بيانات بكمية غير معتادة'`, body (Arabic + English) user, role, count, limit, and network label;
    - when the mode is `enforce` and the role is not admin → `cache.set(f'access:bulkblock:{user.pk}', 1, BULK_READ_BLOCK_MINUTES*60)`.
  - `blocked(user) -> bool`.
- Middleware flow:
  - before the view, a blocked user's request to a `BULK_READ_PATHS` path or an export path → 403 `{'detail': 'تم إيقاف قراءة بيانات العملاء مؤقتاً بسبب كمية غير معتادة — تواصل مع الإدارة', 'reason': 'bulk_read'}`, in enforce only;
  - after the view, `record(...)`, then `alert` on a crossing.
- `manage.py clear_bulk_block <username>` deletes the block key and writes an AuditLog row.

- [ ] **Step 1: Write the failing tests:**
  - `test_rows_counted_from_paginated_and_list_bodies`;
  - `test_crossing_alerts_once_per_hour`;
  - `test_log_mode_alerts_never_blocks`;
  - `test_enforce_blocks_customer_reads_for_minutes`;
  - `test_admin_alerted_never_blocked`;
  - `test_exports_counted_toward_export_limit`;
  - `test_clear_bulk_block_command`;
  - `test_unknown_mode_is_log_and_w004`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run this file plus `apps.tests.security`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(security): bulk-read alert and temporary block (N5)`.

### Task 6: Help, runbook, design doc

**Files:**
- Modify:
  - `apps/help/content/` — the page for `/access/zone-policy` (find it with `grep -rln "zone-policy" apps/help/content`): two tips, Arabic + English, and bump `updated`:
    - live connections follow the zone and close when access changes;
    - every export has an id in its file properties, and unusual bulk reading alerts the admin;
  - `docs/security/2026-10-31-network-device-access-design.md`: §3 WebSocket row Gap → "Re-checked every 5 min + on change (N5)"; mark §8 N5 Built with the commit list;
  - `deploy/LINKDATACENTER_VPS_RUNBOOK.md`: section «Batch N5 on the live server»:
    1. `release.sh`, which runs migrate (audit 0023);
    2. `grep 'ws would-deny' platform.log` during the log week;
    3. read the `export_taken` and `bulk_read_alert` audit rows;
    4. tune `BULK_READ_ROWS_PER_HOUR` from a week of data before `BULK_READ_ENFORCEMENT=enforce`;
    5. `manage.py clear_bulk_block`.
- [ ] **Step 1:** Write the help, runbook and doc text.
- [ ] **Step 2:** Run `apps.tests.test_help` and `apps.tests.security`. Expected: PASS.
- [ ] **Step 3:** Run the full suite (`TEST_DB_NAME=test_n5_full`), `npm run build`, and `makemigrations --check`. Expected: all green.
- [ ] **Step 4:** Commit: `docs(security): N5 help, runbook and design status`.
