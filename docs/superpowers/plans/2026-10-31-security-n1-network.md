# Security Batch N1 — know where each request comes from (log only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every request carries a trustworthy "internal / external" label and, when internal, the site it came from. The label is shown, logged and measured, but **nothing is blocked yet** (blocking comes in N3/N4).

**Architecture:**
- nginx labels each request from the **local address the connection arrived on** (`$server_addr`): 10.50.50.77 (ZeroTier) / 10.0.0.77 (SSTP) → `internal`, anything else → `external`. This is one `map`, so there is no second server block and no bind problems when the SSTP address is down.
- Django trusts that header (Daphne listens on 127.0.0.1 only, so every request came through nginx).
- A new app `apps/access` holds the admin-editable list of trusted networks (CIDR → site/branch) and the per-request access context. Later batches (devices N2, zone policy N3, SOFTECH gate N4) build on this context.

**Tech Stack:** Django 5.2 / DRF, React 18, nginx 1.24. Tests: `python manage.py test <label> --noinput`.

**Spec:** `docs/security/2026-10-31-network-device-access-design.md` §6.1, §6.4 (points 1, 2, 7), §6.8, §8 (N1).

## Global Constraints

- Log only: no request is refused because of its network in this batch. A setting `NETWORK_POLICY_ENFORCEMENT` exists with values `off | log` only (default `log`; `off` under tests).
- The network label is trusted only from nginx. Setting `NETWORK_HEADER_TRUSTED` (default = `BEHIND_HTTPS_PROXY`). When trusted and the header is missing → `external` (fail closed). When not trusted (laptop dev, tests) → the value of `NETWORK_UNTRUSTED_ZONE` (default `'internal'`).
- Header name: `X-ElR-Network`, values exactly `internal` / `external`. Any other value → `external`.
- Client IP only via `core.client_ip.client_ip(request)`.
- No SOFTECH read/write code changes. Telemetry changes only the scope label.
- Every new screen gets help in `apps/help/content/<module>.py` (Arabic + English), `updated` 2026-10-31; `apps/tests/test_help.py` green.
- Admin-only management of trusted networks (owner decision: admin only), enforced server-side with `IsAdminRole`; every create/edit/delete writes `AuditLog`.
- Calm UI: no popups; a small badge, one admin table screen.
- Arabic user-facing text; branch names via the existing branch-label helper, never a bare branch code.

## Review Focus

1. **A client sends its own `X-ElR-Network: internal` header from the internet.** Expect: nginx overwrites it (test parses the config), and Django never reads a client value when nginx is absent and `NETWORK_HEADER_TRUSTED` is on (the label becomes `external`) → tests in Tasks 1 and 2.
2. **SSTP failover:** a request arriving on 10.0.0.77 must be `internal` exactly like 10.50.50.77 → nginx config test in Task 1.
3. **Overlapping networks** (a /16 and a /24 both listed): expect the most specific match (longest prefix) to win → test in Task 2.
4. **Internal label but an IP no listed network covers** (e.g. a new ZeroTier member): expect `internal` with `site = None` («شبكة داخلية غير مسجلة»), counted in the log, not an error → test in Task 2.
5. **IPv6 / garbage IP / IP missing:** expect no crash; `site = None` → test in Task 2.

---

### Task 1: nginx labels the network

**Files:**
- Modify: `deploy/nginx.conf`. At http level, next to the `limit_req_zone` lines:
  ```nginx
  map $server_addr $elr_network {
      10.50.50.77 internal;   # ZeroTier
      10.0.0.77   internal;   # SSTP backup
      default     external;
  }
  ```
- Modify: `deploy/nginx-proxy-headers.conf` — add `proxy_set_header X-ElR-Network $elr_network;` (overwrite, so a client value never passes).
- Modify: `deploy/LINKDATACENTER_VPS_RUNBOOK.md` — new subsection «Batch N1 on the live server»:
  - add the `map` to the live site file;
  - re-copy the proxy-headers include;
  - `nginx -t && reload`;
  - check with `curl -H 'X-ElR-Network: internal' https://elrezeikyapp.dawalvry.com/api/access/whoami/` from mobile data → `external`, and from a ZeroTier laptop browsing `https://10.50.50.77` with `Host: elrezeikyapp.dawalvry.com` → `internal`.
- Test: `apps/tests/security/test_nginx_network_label.py`.

- [ ] **Step 1: Write the failing tests:**
  - `test_map_labels_tunnel_addresses_internal`: parse the `map $server_addr $elr_network` block; `10.50.50.77` → `internal`, `10.0.0.77` → `internal`, `default` → `external`.
  - `test_proxy_headers_overwrite_network_header`: `deploy/nginx-proxy-headers.conf` contains `proxy_set_header X-ElR-Network $elr_network;`.
  - `test_every_proxied_location_gets_label`: every `location` with `proxy_pass` includes the proxy-headers file (reuse the block parser from `test_client_ip.py` — import it, don't copy it).
- [ ] **Step 2:** Run `python manage.py test apps.tests.security.test_nginx_network_label --noinput` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the test plus `apps.tests.security.test_client_ip apps.tests.security.test_admin_exposure` → PASS.
- [ ] **Step 5:** Commit `feat(security): nginx labels each request internal/external by arrival address (N1)`.

---

### Task 2: `apps/access` — trusted networks and request network

**Files:**
- Create the app `apps/access/` (`__init__.py`, `apps.py` with `verbose_name='الوصول والشبكات'`, `models.py`, `network.py`, `admin.py` empty, `migrations/0001_initial.py`). Register it in `INSTALLED_APPS`.
- Modify: `config/settings.py` — `NETWORK_HEADER_TRUSTED = config('NETWORK_HEADER_TRUSTED', default=BEHIND_HTTPS_PROXY, cast=bool)`; `NETWORK_UNTRUSTED_ZONE = config('NETWORK_UNTRUSTED_ZONE', default='internal')`; `NETWORK_POLICY_ENFORCEMENT = config('NETWORK_POLICY_ENFORCEMENT', default='off' if _RUNNING_TESTS else 'log')`.
- Test: `apps/tests/security/test_access_network.py`.

**Interfaces — produces:**
- Model `TrustedNetwork`:
  - `name` (CharField 120)
  - `cidr` (CharField 43; `clean()` validates with `ipaddress.ip_network(strict=False)` and stores the normalised form)
  - `kind` (choices `branch_lan` «شبكة فرع», `staff_vpn` «VPN الموظفين», `server` «سيرفر»)
  - `branch` (FK `branches.Branch`, null, `on_delete=PROTECT`)
  - `is_active` (default True), `notes` (Text, blank)
  - `created_at` / `updated_at`; `updated_by` (FK StaffProfile, null)
  - `verbose_name` Arabic.
- `apps/access/network.py`:
  - `INTERNAL = 'internal'`, `EXTERNAL = 'external'`.
  - `@dataclass(frozen=True) class NetworkInfo: zone: str; ip: str | None; site: TrustedNetwork | None`; property `label_ar` returns «داخل الشبكة — <site name>» / «شبكة داخلية غير مسجلة» / «خارج الشبكة».
  - `zone_from_request(request) -> str`, applying the Global Constraints rules for `X-ElR-Network` (`request.META['HTTP_X_ELR_NETWORK']`).
  - `match_site(ip: str | None) -> TrustedNetwork | None`: active rows only; longest prefix wins; IPv4 and IPv6; bad or None IP → None. Cache the active list for 60 s (`cache` key `access:trusted-networks`), invalidated on save/delete via signals; tests override the TTL to 0.
  - `request_network(request) -> NetworkInfo`: `site` only when zone is `internal`.

- [ ] **Step 1: Write the failing tests:**
  - `test_trusted_header_internal` / `test_trusted_header_missing_is_external` / `test_trusted_header_garbage_is_external` (with `NETWORK_HEADER_TRUSTED=True`).
  - `test_untrusted_ignores_client_header` (`NETWORK_HEADER_TRUSTED=False`, client sends `external` → zone = `NETWORK_UNTRUSTED_ZONE`).
  - `test_longest_prefix_wins` (10.0.0.0/8 "wide" and 10.50.50.0/24 "zt" → 10.50.50.9 matches "zt").
  - `test_internal_unlisted_ip_has_no_site`.
  - `test_external_never_gets_site` (IP inside a listed network, header external → site None).
  - `test_inactive_network_ignored`.
  - `test_bad_ip_and_ipv6`: `'abc'`, `None` → None; an IPv6 /64 match works.
  - `test_cidr_normalised_and_validated`: `'192.168.3.7/24'` saves as `'192.168.3.0/24'`; `'300.1.1.1/24'` raises `ValidationError`.
- [ ] **Step 2:** Run `python manage.py test apps.tests.security.test_access_network --noinput` → FAIL.
- [ ] **Step 3:** Implement the app, model, migration, settings and `network.py`.
- [ ] **Step 4:** Run the test plus `makemigrations --check --dry-run` → PASS / no changes.
- [ ] **Step 5:** Commit `feat(security): apps/access — trusted networks and request network label (N1)`.

---

### Task 3: Access context per request, login logging, telemetry by zone

**Files:**
- Create: `apps/access/context.py`.
- Create: `apps/access/middleware.py` — `AccessContextMiddleware`.
- Modify: `config/settings.py` — insert `'apps.access.middleware.AccessContextMiddleware'` after `CurrentUserMiddleware` and before `ModuleAccessMiddleware` (L883-889).
- Modify: `apps/users/models.py` `UserActivityLog` — `network = models.CharField(max_length=10, blank=True)`, `network_site = models.CharField(max_length=120, blank=True)`, `user_agent = models.CharField(max_length=300, blank=True)`. Migration `apps/users/migrations/0035_activitylog_network.py`.
- Modify: `apps/users/views.py` `_log_auth` and `apps/users/mfa.py` `_log` — take `request` and fill the three fields (`network`, the site name or `''`, the `HTTP_USER_AGENT` truncated to 300). Every existing caller passes the request it already has.
- Modify: `apps/users/serializers.py` — the activity-log serializer exposes the three fields read-only.
- Modify: `frontend/src/pages/UserManagementPage.jsx` — activity-log rows show «داخل الشبكة — <site>» / «خارج الشبكة» next to the IP. Keep it to a short text chip, no new column if the row has no room.
- Test: `apps/tests/security/test_access_context.py`.

**Interfaces:**
- Consumes: `apps.access.network.request_network(request) -> NetworkInfo` (Task 2), `core.auth_cookies.user_from_request(request)`.
- Produces, in `apps/access/context.py`:
  - `@dataclass(frozen=True) class AccessContext: network: NetworkInfo; user_id: int | None; role: str | None` (later batches add `device`).
  - `current() -> AccessContext | None` (contextvar `access_context`).
  - `for_request(request) -> AccessContext`.
- Middleware behaviour:
  - Computes the context once.
  - Sets `request.access` and the contextvar.
  - Wraps the response in `apps.sync.softech_load.scope(f'web:{zone}:{role or "anon"}')`, so live SOFTECH load is broken down by network and role on the existing load screen.
  - Resets both in `finally`.
  - Never raises (any error → `external` / `anon`, logged at WARNING on logger `elrezeiky.access`).
  - With `NETWORK_POLICY_ENFORCEMENT == 'log'`, writes one INFO line per external request that reaches `/api/` with user, role, IP, path, method on logger `elrezeiky.access` (no DB writes per request).

- [ ] **Step 1: Write the failing tests:**
  - `test_request_access_attached` (internal header + listed IP → `request.access.network.site.name`).
  - `test_contextvar_reset_after_response`.
  - `test_softech_scope_label` (inside a view, `softech_load.current_scope() == 'web:external:pharmacist'`; use a tiny test view via `override_settings(ROOT_URLCONF=...)` or patch).
  - `test_middleware_never_raises` (patch `request_network` to raise → 200, zone `external`).
  - `test_login_rows_record_network_and_agent` (failed + successful login with `HTTP_USER_AGENT` and internal header → row fields filled).
  - `test_mfa_rows_record_network`.
  - `test_external_api_request_logged_in_log_mode` (`assertLogs('elrezeiky.access', 'INFO')`).
- [ ] **Step 2:** Run `python manage.py test apps.tests.security.test_access_context --noinput` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the test plus `apps.tests.security.test_auth_lockout apps.tests.security.test_auth_mfa apps.tests.security.test_auth_mfa_attempts apps.tests.security.test_client_ip apps.tests.test_help` and `makemigrations --check --dry-run` → PASS.
- [ ] **Step 5:** Commit `feat(security): per-request access context; login log + SOFTECH load by network (N1)`.

---

### Task 4: «من أين أتصل؟» badge and the trusted-networks screen

**Files:**
- Create: `apps/access/serializers.py`, `apps/access/views.py`, `apps/access/urls.py`; mount `path('api/access/', include('apps.access.urls'))` in `config/urls.py`.
- Modify: `core/middleware/module_access.py` — `MODULE_BY_PREFIX['access'] = 'settings'`, and `'/api/access/whoami/'` in `OPEN_READ_EXACT`. The static "unclassified API prefix" test must stay green.
- Create: `apps/access/management/commands/seed_trusted_networks.py`.
- Create: `frontend/src/pages/TrustedNetworksPage.jsx`, route `/access/networks` (admin `RequireRole`), menu entry under the admin/settings group in `Layout.jsx`. Add api calls in `frontend/src/api/client.js`.
- Create: `frontend/src/components/NetworkBadge.jsx`, rendered in the desktop header (`Layout.jsx`) and the mobile header (`MobileLayout.jsx`).
- Help: new screen entry for `/access/networks` + a tip about the badge in the general module (Arabic + English), `updated` 2026-10-31.
- Test: `apps/tests/security/test_access_api.py`.

**Endpoints:**
- `GET /api/access/whoami/` (`AllowAny`, throttled with a new scope `access_whoami` at `'60/min'`): `{zone, ip, label, site: {name, kind, branch_label} | null}`. Anonymous callers get the same shape. `site` is null whenever the zone is external.
- `GET/POST /api/access/networks/` and `GET/PATCH/DELETE /api/access/networks/<id>/`: `IsAuthenticated` + `IsAdminRole`; each write → `AuditLog` action `trusted_network_changed` (add the choice + an audit migration) with before/after and actor.
- `seed_trusted_networks` (idempotent, dry-run unless `--apply`):
  - For every branch with `db_host` in 192.168.x.y, a `branch_lan` row `<x.y.z>.0/24` named after the branch.
  - Plus `10.50.50.0/24` staff_vpn «ZeroTier».
  - Never overwrites an existing row with the same cidr.

**Frontend behaviour:**
- `NetworkBadge`: one call to `whoami` on load and on window focus; a small pill «🏢 داخل الشبكة — فرع …» (internal + site), «🏢 شبكة داخلية غير مسجلة», «🌐 خارج الشبكة». No popup.
- `TrustedNetworksPage`: table (name, cidr, kind, branch, active, notes) with inline add/edit rows, `useGridKeyboard`, a delete confirm via the existing inline pattern (no modal), and the caller's own `whoami` result shown at the top.

- [ ] **Step 1: Write the failing tests:**
  - `test_whoami_anonymous_internal_listed` (site name returned).
  - `test_whoami_external_hides_site`.
  - `test_whoami_ignores_client_header_when_untrusted`.
  - `test_networks_admin_only` (pharmacist → 403 on GET and POST).
  - `test_network_crud_audited` (POST/PATCH/DELETE → three AuditLog rows with actor).
  - `test_invalid_cidr_rejected` (400 with an Arabic message).
  - `test_seed_from_branch_db_hosts` (two branches with db_host 192.168.3.10 and 192.168.30.12 → two /24 rows + the ZT row; second run creates nothing).
- [ ] **Step 2:** Run `python manage.py test apps.tests.security.test_access_api --noinput` → FAIL.
- [ ] **Step 3:** Implement the backend, frontend and help.
- [ ] **Step 4:** Run the test plus `apps.tests.security.test_rbac_middleware_gaps apps.tests.security.test_permission_matrix apps.tests.test_help`, `makemigrations --check --dry-run` and `cd frontend && npm run build` → PASS.
- [ ] **Step 5:** Commit `feat(security): network badge + admin trusted-networks screen (N1)`.

---

### Task 5: IT runbook for tunnel + split DNS, docs, full verification

**Files:**
- Modify: `deploy/LINKDATACENTER_VPS_RUNBOOK.md` — new section «Company network through the tunnel (split DNS)» turning design §6.8 T1–T7 into concrete steps:
  - the T1 inventory table template (site, router, LAN, guest Wi-Fi, link to HQ, VPN pools);
  - HQ MikroTik forward + no-NAT rule commands (address-list `elrezeiky-internal-clients`, tcp 80/443 to 10.50.50.77 and 10.0.0.77, `accept` placed above masquerade);
  - branch router static DNS + route commands and the DNS-bypass block;
  - the ZeroTier Central DNS push;
  - the VPS tunnel-watcher return routes (where in `/usr/local/sbin/elrezeiky-tunnel-watch` the list lives);
  - the T7 test list, using `/api/access/whoami/`;
  - finish with "add each site in /access/networks".
  - Mark clearly which steps are IT-only. Copy-paste RouterOS commands use placeholders `<BRANCH_LAN>`, never invented addresses.
- Modify: `docs/security/2026-10-31-network-device-access-design.md` — §8 N1 row marked built (commit ids); a note that blocking starts in N3.
- Modify: `docs/architecture/11_ERP_INDEX.md` — module row for `apps/access`, API row `/api/access/`, screen row `/access/networks`.

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2:** `python manage.py makemigrations --check --dry-run` → no changes.
- [ ] **Step 3:** `python manage.py test --noinput` (full suite) → all PASS.
- [ ] **Step 4:** `cd frontend && npm run build` → success.
- [ ] **Step 5:** Commit `docs(security): N1 — tunnel/split-DNS runbook, index, design status`.
