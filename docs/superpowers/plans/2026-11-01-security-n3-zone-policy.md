# Security N3 — Zone Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every request gets an access zone (Z1–Z4) from its network and device, and the owner's per-role rules for each zone are applied on the server: what a role may open, read-only or not, exports, 2FA, and how long a session may last. This runs in `log` mode first and is switched to `enforce` by the owner.

**Architecture:**
- nginx proves to Django that a request really came through it, with a secret header. Without that proof, nothing counts as internal.
- `apps/access/zones.py` computes the zone. A `ZonePolicy` table, seeded from the owner's §7.3 table and editable and audited, holds the rules.
- A `ZonePolicyMiddleware` runs right after the role matrix. Sign-in and refresh apply the same rules, cap the session and require 2FA where the zone does.
- One switch decides behaviour: `NETWORK_POLICY_ENFORCEMENT` = off | log | enforce. Nothing is refused until it is `enforce`.

**Tech Stack:** Django 5.2 / DRF / simplejwt (rotation keeps custom claims) · React 18 / Vite / TanStack Query · nginx.

**Spec:** `docs/security/2026-10-31-network-device-access-design.md`, the parts it uses:
- §6.3 zones;
- §6.4 points 3–4 (middleware, login/refresh);
- §6.5 (2FA outside Z1, session cap);
- §6.6 (exports off outside Z1, phones masked);
- §7.3 (owner's external profile table);
- §8 row N3 (proxy secret before enforce);
- §5 H4 (rider confinement).

## Global Constraints

- Builds on N2 (branch `claude/security-n3` on `claude/security-n2`). Reuse `apps/access` (`network.py`, `context.py`, `devices.py`, `AccessContextMiddleware`) and `core/middleware/module_access.py`. Never duplicate the role matrix: the zone policy only **narrows** what the role already has.
- Zones:

  | Zone | Network | Device |
  |---|---|---|
  | `Z1` trusted | internal | approved |
  | `Z2` internal-unknown | internal | pending, unknown or none |
  | `Z3` external-trusted | external | approved |
  | `Z4` external-unknown | external | pending, unknown or none |

  Anonymous requests get no zone (`None`); the public surfaces are N6.
- Owner table §7.3, verbatim intent. The data migration seeds exactly this:

  | Role | Z1 | Z2 | Z3 | Z4 |
  |---|---|---|---|---|
  | admin | full | read-only | all modules; export only with per-user flag `external_export`; SOFTECH write only with per-user flag `external_softech_write` | blocked |
  | supervisor, purchasing, quality_manager | full | read-only | their modules **view-only**; no export | blocked |
  | call_center | full | read-only | modules intake/demand, reservations, customers (view + their normal writes there); no export | blocked |
  | delivery | full | read-only | rider surface only | rider surface only, 2FA, 12 h |
  | pharmacist, salesperson, viewer | full | read-only | blocked | blocked |

  - All of Z3/Z4: 2FA required, session cap 8 h (delivery 12 h), no 7-day refresh, phones masked, login alert to the user and the admins.
  - Z2 everywhere: login allowed, read-only, no export, banner «جهاز غير معتمد — للعرض فقط».
- Always reachable in every zone for a signed-in user (`ALWAYS_OPEN`):
  - `/api/auth/` (incl. me, 2FA, refresh, logout, change password)
  - `/api/users/my-permissions/`
  - `/api/notifications/`
  - `/api/help/`
  - `/api/access/whoami/`
  - `/api/audit/screen-view/`
- Rider surface (`RIDER_PATHS`, regexes on `request.path_info`):
  - `^/api/delivery/app/`
  - `^/api/delivery/\d+/$` (GET only)
  - `^/api/delivery/\d+/(accept|dispatch|complete|partial|unavailable|fail|collect-cash|items)/$`

  The Task 6 implementer checks this list against every call in `frontend/src/pages/DriverDeliveryApp.jsx` (and the components it uses), and adds any missing one with a ledger note.
- Proxy secret:
  - nginx sends `X-ElR-Proxy-Key: <secret>` from `/etc/nginx/elrezeiky-proxy-key.conf`, a one-line `proxy_set_header`, readable by root only. It is included from `deploy/nginx-proxy-headers.conf`.
  - Django setting `NETWORK_PROXY_KEY` (env). `X-ElR-Network` is trusted only when `NETWORK_HEADER_TRUSTED` is on **and** the key matches (`hmac.compare_digest`).
  - When a key is set and does not match, the request is `external`.
- Sessions:
  - Every token gets the claims `zone` (Z1–Z4) and `auth_at` (epoch seconds of the sign-in).
  - The refresh rotation keeps `auth_at` and re-evaluates the zone.
  - A refresh refuses when the current zone's cap has passed since `auth_at`, or when the role is blocked in the current zone.
- Legacy MFA `device_token` (localStorage) is **removed**: server, client and tests. Only the approved-device remember (N2) skips 2FA.
- 403 body for a zone refusal: `{'detail': <Arabic>, 'zone': 'Z3', 'reason': <code>}`. Messages:
  - `blocked`: «الدخول من خارج شبكة الشركة غير متاح لدورك»
  - `read_only`: «هذا الجهاز غير معتمد — للعرض فقط»
  - `module`: «هذه الشاشة غير متاحة من خارج شبكة الشركة»
  - `export`: «التصدير متاح من داخل شبكة الشركة فقط»
- Every policy edit is audited with `AuditLog.log('zone_policy_changed', …)` before/after.
- The owner flips enforcement: `NETWORK_POLICY_ENFORCEMENT` stays `log` by default.
  - `manage.py check` errors (`access.E003`) when it is `enforce`, `NETWORK_HEADER_TRUSTED` is on and `NETWORK_PROXY_KEY` is empty.
- Help AR+EN for every new or changed screen (CLAUDE.md 5b). `SimpleRouter` only. Tests: `TEST_DB_NAME=test_n3 … --keepdb`; never two suites at once.

## Review Focus

1. **The owner locked out:** an admin on an approved laptop over ZeroTier is Z1, so full access. An admin abroad on an unknown device is Z4, so blocked. The runbook must say how to get in (ZeroTier, or approve the device from inside). In `log` mode nobody is refused. *(Task 4 test `test_log_mode_never_refuses`; runbook step.)*
2. **Old sessions:** tokens minted before N3 have no `zone` or `auth_at`. They must be treated as "sign-in time = token `iat`", never as unlimited, and never 500. *(Task 5 test `test_token_without_auth_at_uses_iat`.)*
3. **Spoofing:** a VPS-local process calling `127.0.0.1:8000` with `X-ElR-Network: internal` and no key, or a wrong key, is external. A missing key setting with the header trusted is refused by `manage.py check` before enforce. *(Task 1 tests.)*
4. **Rider in Z4:** the delivery role on an unknown phone reaches only `RIDER_PATHS` + `ALWAYS_OPEN`. Customers list, POS and SOFTECH screens → 403 `module`. *(Task 6 test `test_rider_z4_only_rider_paths`.)*
5. **Read-only Z2** still lets a user sign in, sign out, change their own password, run 2FA and send notifications reads. `ALWAYS_OPEN` writes are not blocked. *(Task 4 test `test_z2_always_open_writes_allowed`.)*

---

### Task 1: Proxy secret — only nginx can say "internal"

**Files:**
- Modify: `apps/access/network.py` (`zone_from_request`), `apps/access/checks.py` (`access.E003`), `config/settings.py` (`NETWORK_PROXY_KEY = env('NETWORK_PROXY_KEY', default='')`), `deploy/nginx-proxy-headers.conf` (add `include /etc/nginx/elrezeiky-proxy-key.conf;`)
- Create: `deploy/nginx-proxy-key.conf.example` (`proxy_set_header X-ElR-Proxy-Key "CHANGE-ME";`)
- Modify: `.env.example`, `deploy/staging.env.example`, `deploy/DEPLOY.md`, `deploy/LINKDATACENTER_VPS_RUNBOOK.md` (new «Batch N3 on the live server», step 1: generate the key with `openssl rand -hex 32`, write the nginx file with mode 600, set the env, `nginx -t`, reload, restart)
- Test: `apps/tests/security/test_access_network.py`, `apps/tests/security/test_access_checks.py`, `apps/tests/security/test_nginx_network_label.py`

**Interfaces:**
- Produces: `network.proxy_key_ok(request) -> bool`. True when no key is configured (backward compatible in log mode); otherwise a constant-time match of the `HTTP_X_ELR_PROXY_KEY` header.

- [ ] **Step 1: Failing tests.**
  - `test_key_set_and_missing_header_is_external`
  - `test_key_set_and_wrong_key_is_external`
  - `test_key_matches_internal_trusted`
  - `test_no_key_configured_keeps_n1_behaviour`
  - `test_check_e003_enforce_without_key` (Error with id `access.E003`)
  - `test_nginx_include_has_proxy_key` (the headers include references the key file)
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS. Also run all of `test_access_network`, `test_access_context` and `test_access_checks`.
- [ ] **Step 5: Commit** `feat(security): nginx proxy key — only nginx can label a request internal (N3)`.

### Task 2: Zone computation in the access context

**Files:**
- Create: `apps/access/zones.py`
- Modify: `apps/access/context.py` (`AccessContext.zone: str | None = None`; `for_request` computes it), `apps/access/views.py` (`whoami` adds `zone` and `zone_label`)
- Test: `apps/tests/security/test_access_zones.py`

**Interfaces:**
- Produces in `zones.py`:
  - `Z1, Z2, Z3, Z4 = 'Z1', 'Z2', 'Z3', 'Z4'`
  - `ZONE_LABELS`:
    - Z1: «داخل الشبكة — جهاز معتمد»
    - Z2: «داخل الشبكة — جهاز غير معتمد»
    - Z3: «خارج الشبكة — جهاز معتمد»
    - Z4: «خارج الشبكة — جهاز غير معتمد»
  - `zone_for(network_zone: str, device_status: str | None) -> str`
  - `current_zone() -> str | None` (from the contextvar; `None` for anonymous).

- [ ] **Step 1: Failing tests.**
  - `test_zone_matrix`: all four combinations, including device `None` and `blocked`. A blocked device never gets a zone better than Z2/Z4.
  - `test_anonymous_has_no_zone`
  - `test_whoami_zone_signed_in`
- [ ] **Steps 2–4: Run → FAIL → implement → PASS.** Also run `test_access_context` and `test_access_api`.
- [ ] **Step 5: Commit** `feat(security): access zone Z1–Z4 from network and device (N3)`.

### Task 3: Zone policy table, seeded from the owner's decisions; per-user flags

**Files:**
- Modify: `apps/access/models.py` (`ZonePolicy`), `apps/users/models.py` (`StaffProfile.external_export`, `StaffProfile.external_softech_write`, BooleanFields default False, Arabic labels), `apps/audit/models.py` (`zone_policy_changed`)
- Migrations:
  - `apps/access` schema migration plus a data migration seeding the table above;
  - `apps/users` (two flags);
  - `apps/audit` (choice, the next number after `0020`).
- Create: `apps/access/policy.py`
- Test: `apps/tests/security/test_access_policy.py`

**Interfaces:**
- `ZonePolicy` fields:
  - `role` (StaffProfile role choices), `zone` (Z1–Z4); unique (role, zone);
  - `access`: choices `full`, `read_only`, `listed`, `rider`, `none`;
  - `modules`: JSON list of module keys from `MODULE_BY_PREFIX` values, used when `listed`;
  - `view_only`: bool; with `listed`, unsafe methods are refused;
  - `export`: bool;
  - `softech_read`, `softech_write`: bool, stored for N4;
  - `require_mfa`: bool;
  - `max_session_hours`: PositiveSmallInteger, null = no cap;
  - `updated_by`, `updated_at`.
- `policy.py`:
  - `@dataclass(frozen=True) Decision(allowed: bool, reason: str | None, zone: str | None)` — `reason` ∈ `blocked`, `read_only`, `module`, `export`.
  - `policy_for(role, zone) -> ZonePolicy | None`, cached 60 s, invalidated on save.
  - `decide(profile, zone, path, method, module: str | None, is_export: bool) -> Decision`:
    - always allowed when the zone is None, the path is `ALWAYS_OPEN`, or there is no policy row;
    - the admin per-user flags widen `export` (and, for N4, `softech_write`) in Z3 only.
  - `ALWAYS_OPEN`, `RIDER_PATHS` as in Global Constraints.
  - `is_export(path, method) -> bool`: a path segment `export` or ending in `-export`/`/export/`. The implementer runs `grep -rn "export" apps/*/urls.py`, lists every export route in the test, and asserts that each one is detected.
- Seeding the call_center `listed` modules: use the module keys that `MODULE_BY_PREFIX` gives for `/api/callcenter/`, `/api/demand/`, `/api/reservations/` and `/api/customers/`. The implementer resolves the exact keys and records them in the report.

- [ ] **Step 1: Failing tests.**
  - `test_seed_matches_owner_table`: every role × zone row.
  - `test_decide_matrix`, at least:
    - pharmacist Z3 → blocked
    - purchasing Z3 POST → read_only
    - call_center Z3 POST on customers → allowed
    - call_center Z3 GET pos → module
    - admin Z3 export → export, but allowed with the flag
    - delivery Z4 rider path → allowed; other path → module
    - anyone Z2 POST → read_only
    - Z1 → allowed
  - `test_always_open_allowed_everywhere`
  - `test_export_routes_detected`: the full inventory.
- [ ] **Steps 2–4.** Also run `makemigrations --check`.
- [ ] **Step 5: Commit** `feat(security): zone policy table seeded from the owner's external profile (N3)`.

### Task 4: Zone policy middleware (off / log / enforce)

**Files:**
- Create: `apps/access/policy_middleware.py` (`ZonePolicyMiddleware`)
- Modify: `config/settings.py`. Add it to MIDDLEWARE immediately **after** `core.middleware.module_access.ModuleAccessMiddleware`.
- Test: `apps/tests/security/test_access_policy_middleware.py`

**Interfaces:**
- Consumes: `request.access` (zone), `module_access.required(path, method)` for the module, `policy.decide`, `policy.is_export`.
- Behaviour:
  - `off` → nothing.
  - `log` → a would-deny line on logger `elrezeiky.access`, deduplicated per (user, zone, reason, path) for 10 min the same way as N1.
  - `enforce` → 403 with the Global Constraints body. Never raises: on an internal error it logs a warning and lets the request through in log mode, and refuses in enforce mode.
  - Only `/api/` paths. Anonymous → untouched (the views answer 401).

- [ ] **Step 1: Failing tests.**
  - `test_log_mode_never_refuses` (Review Focus 1)
  - `test_enforce_refuses_with_arabic_reason` (each reason)
  - `test_z2_always_open_writes_allowed` (Review Focus 5: change own password and logout in Z2)
  - `test_admin_z3_full_but_no_export`
  - `test_middleware_never_raises`
  - `test_log_line_deduplicated`
- [ ] **Steps 2–4.** Also run `apps.tests.security.test_role_sweep` (background + wait). The sweep runs with enforcement `off` in tests: the default test setting stays off, so baselines are unaffected.
- [ ] **Step 5: Commit** `feat(security): zone policy middleware — log first, enforce on switch (N3)`.

### Task 5: Sign-in, refresh and 2FA follow the zone; session caps; legacy remember token removed

**Files:**
- Modify:
  - `apps/users/views.py` (`login_view`, `refresh_view`)
  - `apps/users/mfa.py` (`build_login_response`, `verify_2fa_view`, `enable_2fa_view`; delete `make_device_token`, `valid_device_token` and the `device_token` response field)
  - `frontend/src/store/authStore.js`, `frontend/src/api/client.js` (stop storing and sending `mfa_device_token`; clean up the old localStorage key once)
  - `apps/users/tests_mfa.py` and the N2 tests that used the legacy token
- Create: `apps/access/session_policy.py`
- Test: `apps/tests/security/test_access_session_policy.py`

**Interfaces:**
- Produces in `session_policy.py`:
  - `stamp(refresh: RefreshToken, zone: str | None, auth_at: int | None = None)`: sets the `zone` and `auth_at` claims. Default `auth_at` is now.
  - `cap_hours(profile, zone) -> int | None`
  - `refresh_allowed(profile, token, zone) -> tuple[bool, str | None]`:
    - `auth_at` falls back to `iat`;
    - refuses with `expired` when past the cap, and with `blocked` when the role is blocked in the zone.
  - `mfa_required_in_zone(profile, zone) -> bool`
- Sign-in:
  1. Compute the zone from the request (network + the device cookie's status).
  2. If the policy blocks the role, the answer depends on the mode:
     - enforce → 403 `blocked`, logged as `login_refused_zone` (a new UserActivityLog action and users migration; not `login_failed`, so it never feeds the lockout);
     - log → a log line, and the sign-in continues.
  3. If `mfa_required_in_zone` and the user is not enrolled → the existing `mfa_setup_required` flow. If enrolled → challenge, unless the approved-device remember applies.
  4. Stamp the tokens.
  5. If the zone is Z3/Z4 → login alert to the user, and the admin hourly digest (reuse the N2 digest helper with a new title «دخول من خارج الشبكة»).
- Refresh:
  1. Re-evaluate the zone.
  2. Call `refresh_allowed`. Refusals happen only in enforce mode → 401 plus cleared cookies; log mode only logs.
  3. Restamp `zone`, keep `auth_at`.
- `refresh` cookie max_age for Z3/Z4: the cap instead of 7 days.

- [ ] **Step 1: Failing tests.**
  - `test_token_without_auth_at_uses_iat` (Review Focus 2)
  - `test_external_session_capped_8h` (freeze time)
  - `test_rider_capped_12h`
  - `test_internal_token_used_outside_reevaluated` (pharmacist Z1 token refreshed from Z3 → refused in enforce)
  - `test_blocked_role_login_refused_enforce_only`
  - `test_external_requires_2fa`
  - `test_legacy_device_token_ignored`
  - `test_login_alert_external`
- [ ] **Steps 2–4.** Also run `apps.users.tests_mfa`, `apps.tests.security.test_auth_mfa`, `test_auth_lockout`, `test_auth_sessions`, `test_access_devices`, `test_access_devices_final`. Then `npm run build`.
- [ ] **Step 5: Commit** `feat(security): sign-in and refresh follow the zone — 2FA, session caps; legacy remember removed (N3)`.

### Task 6: Leakage controls — rider confinement (H4), phones masked outside

**Files:**
- Modify: `apps/customers/access.py` (`phones_visible`, `record_phones_visible`), `frontend/src/App.jsx` (`/rider` behind `RequireRole` delivery/admin/supervisor; the delivery role is redirected to `/rider` from any other route), `frontend/src/pages/DriverDeliveryApp.jsx` only if a call is missing from `RIDER_PATHS`
- Test: `apps/tests/security/test_access_leakage.py`

**Interfaces:**
- `phones_visible(user, customer)` → False when `zones.current_zone()` is Z3/Z4.
- `record_phones_visible(user)` → in Z3/Z4, True only for roles `delivery` and `call_center`. Their records are already scoped: a rider sees only their own orders, and the call centre the active customer. Everyone else gets masked numbers.

- [ ] **Step 1: Failing tests.**
  - `test_rider_z4_only_rider_paths` (Review Focus 4; enforce)
  - `test_customer_phone_masked_external`
  - `test_rider_sees_own_order_phone_external`
  - `test_internal_unchanged`
- [ ] **Steps 2–4.** Also run `apps.tests.security.test_phone_rules apps.tests.security.test_phone_canary_sweep apps.tests.security.test_delivery_rider_powers`. Then `npm run build`.
- [ ] **Step 5: Commit** `feat(security): rider confined to the rider screen; phones masked outside the network (N3)`.

### Task 7: «سياسة الشبكات» admin screen, Z2 banner, help, docs

**Files:**
- Modify: `apps/access/views.py`, `serializers.py`, `urls.py`:
  - `ZonePolicyViewSet` at `/api/access/zone-policies/`: list + partial_update, IsAdminRole, audited.
  - `/api/users/<pk>/` admin edit gains the two per-user flags. Use the existing user-edit serializer; audit as that screen already does.
- Create: `frontend/src/pages/ZonePolicyPage.jsx` (`/access/zone-policy`, admin). A role × zone grid; each cell edits access / modules / view_only / export / require_mfa / max_session_hours inline.
- Modify:
  - `frontend/src/components/Layout.jsx` (or wherever the shell banner lives): a calm top strip «جهاز غير معتمد — للعرض فقط» when `whoami.zone === 'Z2'`, and «خارج الشبكة» info when Z3/Z4;
  - `NetworkBadge.jsx` shows the zone label;
  - `UserManagementPage.jsx`: the two per-user flags on the user form, admin only.
- Help:
  - `apps/help/content/admin.py`: new `admin.zone_policy`, plus bumps of `admin.users` and `admin.devices`;
  - `apps/help/content/general.py`: banner + badge, bump.
- Docs:
  - `docs/architecture/11_ERP_INDEX.md`
  - `04_API_REGISTRY.md`
  - design doc §8 N3 row → Built
  - runbook «Batch N3 on the live server»:
    1. proxy key;
    2. migrate;
    3. stay in `log` for at least a week and read the would-deny lines (`journalctl -u elrezeiky-web | grep 'zone would-deny'`);
    4. approve devices;
    5. then set `NETWORK_POLICY_ENFORCEMENT=enforce` and restart;
    6. the way back in if locked out: ZeroTier → Z1/Z2, or flip back to `log`.
- Test: `apps/tests/test_help.py`, `apps/tests/security/test_access_policy_api.py`:
  - admin only
  - audited before/after
  - modules validated against known module keys
  - `max_session_hours` 1..72 or null

- [ ] **Steps 1–5:** tests → implement → `test_help` + the new API tests + `npm run build` → commit `feat(security): «سياسة الشبكات» screen, Z2 banner, per-user external flags, help + docs (N3)`.

---

## Out of scope

- The SOFTECH gate in `config/sybase.py` that reads `softech_read` / `softech_write`: N4, stop-and-ask, because it touches the POS push path.
- WebSocket periodic re-check, export watermark and anomaly alerts: N5.
- Public surfaces: N6.
- Switching to `enforce` is the owner's action after the log period, not part of this batch.
