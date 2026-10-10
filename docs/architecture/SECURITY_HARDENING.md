# Security Hardening & Safe Staging (batch 1 — 2026-10-08)

Follow-up to the deployment-readiness audit. This batch closes the leaks that
could be fixed without changing business behaviour, adds a system-wide test
sweep, and documents the risks that still need a decision.

---

## 1. What changed

| # | Area | Change | Files |
|---|------|--------|-------|
| 1 | **SOFTECH global kill-switch** | `SOFTECH_READ_ONLY=True` wraps EVERY java.sql connection (HQ, branches, `SoftechConnector`) in a proxy that refuses anything but plain reads — INSERT/UPDATE/DELETE/MERGE/TRUNCATE/DDL/EXEC/DBCC/SELECT INTO, multi-statement batches and callable statements. It sits under the per-feature `*_ENABLED` flags, so it also blocks the writes those flags never covered: price-approval `UPDATE items`, replication repair (incl. scheduled auto-repair), classification alignment, loyalty `picpoints`, personal document/cheque comments, and the diagnostic commands. It also covers writers that bypass `CursorWrapper` (`conn._conn.createStatement()` in the invoice / ISR / supplier-item writers). Default **False** (production unchanged). | `config/sybase.py`, `config/settings.py` |
| 2 | **Branch host override** | `SOFTECH_BRANCH_HOST_OVERRIDE=host[:port]` sends every branch-server connection to one (test) host instead of the production addresses stored in `Branch.db_host`. | `config/sybase.py` |
| 3 | **Hermetic test runner** | Under `manage.py test`, SOFTECH is forced unreachable and read-only regardless of `.env` (`SOFTECH_TESTS_ALLOW_LIVE=True` opts out). Before this, writer tests that drive the live path (e.g. `test_cancel_pushed_gate_on_reaches_softech_delete`) would connect to whatever `SYBASE_HOST` a developer's `.env` pointed at — production on the owner's PC. | `config/settings.py` |
| 4 | **SECRET_KEY** | No more placeholder default: a non-DEBUG process refuses to start without a real key. (JWTs, portal sessions, tracking/recording links and the default omni-credential encryption key all derive from it.) | `config/settings.py` |
| 5 | **ALLOWED_HOSTS** | Defaults to `localhost,127.0.0.1` when DEBUG is off (was `*`). | `config/settings.py` |
| 6 | **HTTPS behind a proxy** | `BEHIND_HTTPS_PROXY`, `CSRF_TRUSTED_ORIGINS`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`; secure cookies when behind TLS; nosniff / referrer policy. | `config/settings.py` |
| 7 | **Loyalty points** | `POST /api/loyalty/customers/<id>/adjust/` (writes SOFTECH `picpoints`) was open to any logged-in user incl. `viewer`. Now limited to `LOYALTY_ADJUST_ROLES` (default admin, supervisor, call_center). | `apps/loyalty/views.py` |
| 8 | **Webhooks** | WhatsApp + Meta webhooks no longer accept unsigned events when the app secret is missing (fail closed outside DEBUG); verify-token handshake requires a configured token; all secret comparisons are constant-time and byte-safe (a non-ASCII header used to raise → 500). | `apps/whatsapp/views.py`, `apps/social/views.py`, `apps/social/webhooks.py` |
| 9 | **Server-side module permissions** | New `ModuleAccessMiddleware` applies the existing `RoleModuleAccess` matrix to `/api/<module>/…` (≈50 URL prefixes → 31 modules). `RBAC_ENFORCEMENT=off\|log\|enforce`, default **log** (nothing blocked; would-be denials logged to `elrezeiky.rbac`). Enforce falls back to log if the matrix is empty. | `core/middleware/module_access.py`, `config/settings.py` |
| 10 | **Nginx** | SPA root fixed to the real build dir (`staticfiles/frontend`); security headers restored on SPA responses (a location-level `add_header` was silently dropping them); `/admin/` limited to private ranges; JWT-bearing `/ws/` URLs kept out of access logs; uploaded HTML/SVG/XML/JS under `/media/` sandboxed + forced download (stops stored-XSS stealing the localStorage JWT); `noindex` on media. | `deploy/nginx.conf` |
| 11 | **Crash bugs found by the sweep** | call-centre *add note* crashed on every request (`parser_classes=None`); voucher report (`full_name` is a property); procurement branches (annotation shadowing a field); finance sync-runs (re-ordering a sliced queryset); near-expiry stock + replication item check → 503 instead of 500 (and no driver text sent to the browser); loyalty account / referral code → 404 for unknown customers. | `apps/callcenter`, `apps/vouchers`, `apps/procurement`, `apps/finance`, `apps/incentives`, `apps/discount_approvals`, `apps/loyalty`, `apps/referral` views |
| 12 | **Comment write-back** | Personal document/cheque comments validated before opening a SOFTECH connection. | `apps/personal/writeback.py` |
| 13 | **Packaging / CI** | `python-dateutil` and `JPype1` added to both requirement files (CI had been red since `apps/cheques` started importing dateutil; `JPype1` is now imported at module load via `pos_orders.discount_authority`). `DEPLOY.md` installs a JRE, fixes the build path, documents key rotation and backups. | `requirements*.txt`, `deploy/DEPLOY.md` |
| 15 | **Signed upload links** (batch 2) | Every FileField/ImageField URL is now signed with an expiry (`core/storage.py` `SignedMediaStorage`, default 6 h, rounded to the hour); `/media/` is served by `core/media.py`, which refuses protected files without a valid signature, blocks path traversal and sends HTML/SVG/XML/JS as sandboxed downloads. Product imagery (`products/`, `image_candidates/`) and print watermarks stay public. Behind Nginx (`MEDIA_ACCEL_REDIRECT=True`) Django only checks the signature and Nginx streams the file from the internal `/protected-media/` location. No serializer or UI change was needed. Covers `media/reports/` exports too. | `core/storage.py`, `core/media.py`, `config/settings.py`, `config/urls.py`, `deploy/nginx.conf` |
| 16 | **Per-feature SOFTECH write switches** (batch 3) | `PRICING_SOFTECH_WRITE_ENABLED` (approved price/discount `UPDATE items` + classification alignment), `REPLICATION_REPAIR_ENABLED` (manual repair + scheduled auto-repair), `LOYALTY_SOFTECH_WRITE_ENABLED` (manual purchase points → `picpoints`), `PERSONAL_COMMENT_WRITE_ENABLED` (document comments / cheque notes). Default **True** — production unchanged. Checked in the view (clear 503 before anything changes: a price request stays *pending* instead of half-approved) **and** in the writer (so scheduled jobs and commands obey). | `config/settings.py`, `apps/discount_approvals/{services,alignment,replication,views}.py`, `apps/sync/tasks.py`, `apps/loyalty/{pic_bridge,views}.py`, `apps/personal/writeback.py` |
| 17 | **No internals in error responses** (batch 4) | 67 places that caught any `Exception` and echoed it to the browser (driver/database/network text: SOFTECH hosts, SQL, table names) now go through `core.errors.public_error(request, exc)`: the full error is logged (`elrezeiky.errors`) with a short reference code; admins still see the technical text, everyone else sees only the reference. Deliberate domain messages (`ValueError`, `HrError`, `RepriceError`, …) are unchanged. A static test fails CI if a new view echoes a caught `Exception` again. | `core/errors.py` + 23 view modules |
| 18 | **Login session in httpOnly cookies** (batch 5) | Access/refresh tokens are no longer stored in `localStorage`. Login and 2FA set `httpOnly`, `SameSite=Strict` cookies (Secure behind HTTPS; refresh cookie scoped to `/api/auth/`); `/api/auth/refresh/` rotates from the cookie and never returns tokens to page script; new `/api/auth/logout/` blacklists + clears. `CookieJWTAuthentication` accepts the Bearer header (scripts/tests unchanged) or the cookie; a cookie is only honoured on writes that carry `X-Requested-With` (CSRF). WebSockets (notifications, chatter, PBX) authenticate from the cookie — no token in URLs. Browsers still holding old localStorage tokens are migrated silently on next load. | `core/auth_cookies.py`, `apps/users/{views,mfa,auth_urls}.py`, `apps/notifications/middleware.py`, `core/middleware/module_access.py`, `frontend/src/api/client.js`, `frontend/src/store/authStore.js`, WS hooks, `PbxLivePage.jsx` |
| 14 | **Config templates** | `.env.example` lists the variables the code really reads (`SYBASE_HOST/PORT`, new security switches); `deploy/staging.env.example` is a complete safe UAT profile. | `.env.example`, `deploy/staging.env.example` |

## 2. New tests

| File | Covers |
|------|--------|
| `apps/tests/test_security_hardening.py` (41) | SQL read/write classifier (literals, comments, identifiers containing "update", `SELECT INTO`, batches, procs); java.sql proxy incl. raw-statement writers; guard wiring through `_connect_with_retry`; branch override; loyalty role gate (SOFTECH write never reached); webhook fail-closed + signatures + handshake; RBAC mapping/log/enforce/empty-matrix/admin; production settings guards (real settings import in a subprocess). |
| `apps/tests/test_media_security.py` (12) | Signed vs public prefixes, signature/expiry/tamper checks, serving with and without signature, traversal, sandboxed script-capable uploads, X-Accel mode, method restriction. |
| `apps/tests/test_softech_write_switches.py` (10) | Each switch defaults on; off refuses in the view and in the writer without opening a SOFTECH connection; a refused price approval stays pending; scheduled auto-repair is skipped (and logged). |
| `apps/tests/test_error_disclosure.py` (5) | Non-admins never see hosts/SQL, admins keep technical text, the reference code is in the log; a real endpoint end to end; static AST guard over every view module. |
| `apps/tests/test_auth_cookies.py` (14) | Cookie flags, cookie-only reads, CSRF header on writes, Bearer still works, rotation without body tokens + old token blacklisted, legacy body refresh migration, logout, invalid cookie → 401, public form from a logged-in browser, WebSocket cookie / legacy query token. |
| `apps/tests/test_endpoint_sweep.py` (5) | **Every** URL in the project: (1) the anonymous-access surface must equal a reviewed allow-list — a new public endpoint fails CI until reviewed; (2) every other route answers 401/403/404/405 to anonymous GET and POST; (3) every GET route, called as an admin with SOFTECH, the JVM and the internet unreachable, must not return 500. |

## 3. Running staging / UAT safely

1. Separate PostgreSQL database (restore a production dump, or migrate empty + sync).
2. `.env` from `deploy/staging.env.example`. The three SOFTECH lines that matter:
   `SOFTECH_READ_ONLY=True`, `SOFTECH_BRANCH_HOST_OVERRIDE=<test host>`, a
   **SELECT-only Sybase login** (ask the SOFTECH DBA — the only guarantee that holds
   even if code is wrong).
3. In the staging DB: `UPDATE discount_approvals_replicationpolicy SET auto_repair_enabled = false;`
   (belt and braces; the kill-switch already blocks it).
4. `RBAC_ENFORCEMENT=enforce`, one test account per role/branch you want tested.
5. Leave WhatsApp / Meta / AMI / AI keys empty so nothing reaches real customers.
6. `pg_dump` before every UAT round (DEPLOY.md §11).

## 4. Remaining risks — not fixed in this batch (need a decision)

| Risk | Why not fixed now | Recommended mitigation |
|------|-------------------|------------------------|
| Signed upload links are bearer links | Anyone holding a link can open it until it expires (≤ ~7 h) | Keep `MEDIA_URL_TTL` short; don't paste upload links into WhatsApp/email — share the record instead. |
| RBAC is in **log** mode | Enforcing blind could lock staff out of screens they use daily | Run `log` in production 1–2 weeks, fix grants (`/permissions`) until `elrezeiky.rbac` is quiet, then `enforce`. Staging can enforce now. |
| Customer portal session still in `localStorage` | Separate auth surface (magic-link), customer-scoped | Same cookie approach for `apps/portal` if the portal goes public. |
| 2FA not enforced | Business decision | Turn on `security.mfa_enforced` for admin / supervisor / purchasing. |
| No per-user "beta module" flag | Feature work | Use dedicated roles + RBAC enforce in staging. |
| `jconn3.jar` (proprietary) committed to the repo | Licensing question | Confirm the SAP/Sybase licence allows redistribution; otherwise load it via `SYBASE_JCONN_JAR`. |
| Rotating a placeholder SECRET_KEY | Signs everyone out; omni credentials need the old derived key | Follow DEPLOY.md §3 before changing the key. |
