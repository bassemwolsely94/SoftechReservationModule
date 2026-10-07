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
| 14 | **Config templates** | `.env.example` lists the variables the code really reads (`SYBASE_HOST/PORT`, new security switches); `deploy/staging.env.example` is a complete safe UAT profile. | `.env.example`, `deploy/staging.env.example` |

## 2. New tests

| File | Covers |
|------|--------|
| `apps/tests/test_security_hardening.py` (41) | SQL read/write classifier (literals, comments, identifiers containing "update", `SELECT INTO`, batches, procs); java.sql proxy incl. raw-statement writers; guard wiring through `_connect_with_retry`; branch override; loyalty role gate (SOFTECH write never reached); webhook fail-closed + signatures + handshake; RBAC mapping/log/enforce/empty-matrix/admin; production settings guards (real settings import in a subprocess). |
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
| `/media/` uploads (prescriptions, insurance docs, payment proofs) served without login | Needs signed URLs in ~29 serializers + every `<img>`/link in the UI | Never expose the server publicly without an identity-aware access layer (VPN / Zero-Trust tunnel). Next batch: short-lived signed media URLs + `X-Accel-Redirect`. |
| RBAC is in **log** mode | Enforcing blind could lock staff out of screens they use daily | Run `log` in production 1–2 weeks, fix grants (`/permissions`) until `elrezeiky.rbac` is quiet, then `enforce`. Staging can enforce now. |
| JWT stored in `localStorage`; WebSocket token in query string | Moving to httpOnly cookies changes login, refresh and WS auth end-to-end | Media sandboxing (done) removes the main XSS vector; plan cookie auth as its own batch. |
| 148 API responses return raw exception text (`str(exc)`) | Many are deliberate user-facing validation messages | Review per module; a DRF exception handler + `logger.exception` for unexpected errors only. |
| Price approvals / replication repair / loyalty / comments have no per-feature env flag | Changing them touches pricing and loyalty workflows (CLAUDE.md: ask first) | Covered by `SOFTECH_READ_ONLY` in staging; add explicit flags if you want them switchable individually in production. |
| 2FA not enforced | Business decision | Turn on `security.mfa_enforced` for admin / supervisor / purchasing. |
| No per-user "beta module" flag | Feature work | Use dedicated roles + RBAC enforce in staging. |
| `jconn3.jar` (proprietary) committed to the repo | Licensing question | Confirm the SAP/Sybase licence allows redistribution; otherwise load it via `SYBASE_JCONN_JAR`. |
| Rotating a placeholder SECRET_KEY | Signs everyone out; omni credentials need the old derived key | Follow DEPLOY.md §3 before changing the key. |
