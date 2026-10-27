# Security & test inventory — 2026-10-26

Read-only sweep of the whole repo before designing the full test suite. Nothing was changed.
Items marked ✔ were re-checked by hand against the code; the rest come from the sweep and
still need confirming when their test is written.

## 1. Existing tests

- 2,668 backend tests in 197 files (`apps/tests/`, plus `apps/portal/tests.py`,
  `apps/users/tests_mfa.py`). Django test runner on PostgreSQL; CI = `.github/workflows/ci.yml`
  (`makemigrations --check` + `manage.py test`, frontend `npm run build` only).
- Test isolation from SOFTECH lives in `config/settings.py` (~L52–71, L409–414): under
  `manage.py test` the host is blanked, branches point at `softech-disabled-in-tests.invalid`,
  `SOFTECH_READ_ONLY=True`, and every `*_ENABLED`/`*_WRITE*` flag ignores `.env`.
  Only works under `manage.py test` (not pytest).
- `RBAC_ENFORCEMENT` is `off` in tests → the role matrix is never exercised end-to-end.
- `test_endpoint_sweep.py`: anonymous callers rejected on every route; public views are a
  reviewed allow-list; admin GET of every route doesn't 500. **No per-role sweep, no write
  sweep, no object/branch-level checks** (detail routes are hit with id=1 → 404).
- Apps with no tests at all: campaigns, cheques, enrichment, erp, images, payments,
  product_experience, qa, referral. Thin: dashboard, chronic, stockcount, tasks, lineage,
  delivery, portal, social, insurance, hr, followups.
- Frontend: **zero tests**, no eslint, no test runner.
- No static security tools: no bandit/ruff/pip-audit/npm audit/coverage.

## 2. Confirmed critical findings

| # | Finding | Where |
|---|---|---|
| C1 ✔ | **2FA bypass with password only.** Login pre-auth token is accepted by `setup_2fa_view` → attacker installs their own secret → `enable_2fa_view` returns JWTs. Also: setup overwrites the secret of an already-enrolled user; `verify_2fa_view` unthrottled. | `apps/users/mfa.py:157,204,224` |
| C2 ✔ | **SQL injection into SOFTECH (stock count).** `branch_code`, `user_code_filter`, `category_filter`, `doccodes`, `item_codes_filter` formatted into SQL; any logged-in user. | `apps/stockcount/engine.py:183,213,…`; views `:65` |
| C3 ✔ | **SQL injection into SOFTECH (near-expiry report).** `store_codes`/`item_codes` query params. Any logged-in user. | `apps/incentives/engine.py:657-669`; views `:1580` |
| C4 ✔ | **Any logged-in user can write SOFTECH `items`** via shortage flag/unflag/dismiss/retrieve; local `.env` has `SHORTAGE_SOFTECH_WRITE_ENABLED=True`. | `apps/purchasing/shortage_views.py:208-315` |
| C5 ✔ | **Role matrix never blocks** — `RBAC_ENFORCEMENT` defaults to `log`. Combined with many views being `IsAuthenticated` only, any role (incl. viewer/delivery) reaches finance, cheques, payments, incentives adjustments, campaigns, analytics, procurement, customers DELETE, POS order DELETE. | `config/settings.py:854` |
| C6 ✔ | **Branch restrictions on users are never applied** — `allowed_branches`/`restricted_branches` are saved but nothing filters by them. Many lists/details aren't branch-scoped at all (pos_orders, payments, cheques, invoices, stockcount, customers, finance, analytics…). | `apps/users/models.py:156-162` |
| C7 ✔ | **Kill-switch bypass** — `diag_appname` connects with `SybDriver().connect` directly and INSERTs on HQ (rolled back), ignoring `SOFTECH_READ_ONLY`. | `apps/invoices/management/commands/diag_appname.py:13-33` |
| C8 ✔ | **Four SOFTECH write switches default ON** (pricing, replication repair, loyalty points, personal comments). Loyalty INSERT has **no idempotency** (retry = double points; call_center can trigger; no size cap). | `config/settings.py:420-423`; `apps/loyalty/pic_bridge.py:264` |
| C9 ✔ | **Local `.env` runs DEBUG=True** (duplicate line, last wins) → webhooks accept unsigned payloads when secrets are empty, debug pages on. | `.env:6,15` |
| C10 | **Hardcoded admin credentials** in a tracked script. Rotate if real. | `scripts/smoke_api_live.py:7-9` |
| C11 | **Deactivating a user doesn't end their session** (only `StaffProfile.is_active` flips; JWT keeps working, refresh extends it). | `apps/users/views.py:368` |

## 3. High / medium (from the sweeps, to confirm)

- POS `OrderDetailView` DELETE open to any user, lock check covers update only (`pos_orders/views.py:152`) ✔.
- Incentive `AdjustmentEntryViewSet` — docstring says admin-only, enforces nothing ✔ (`incentives/views.py:1199`).
- Incentive programs create/calculate/finalize open; campaigns self-approve + bulk WhatsApp send; loyalty redemption self-approve; payments PATCH amount of a confirmed payment / DELETE; cheque instalment → `cleared` by anyone.
- `CanPushPosOrders` = grant **or** role list, so the matrix can't revoke it.
- Middleware: POST passes with any one of create/edit/approve/assign/finalize/export; `tasks` and `recommendations` prefixes unmapped; `search` (incl. customers) exempt.
- Writes with no enable flag over HTTP: `alignment/tier-create` (INSERT lookup tables), invoice `probe` and coupon `batch-probe` (real INSERT + rollback on production).
- Live-writing management commands without flags (`investigate_britems*`, `probe_itemlastupdate`, `probe_replication_source`, `probe_repl_queue`, `test_replication_cycle --mode plant`, `test_pic_points` default live, `capture_save_sql --enable-monitoring` runs `sp_configure`).
- Read-only guard: `'--'` inside a string literal hides trailing SQL; `stmt.getConnection()` returns the raw connection; `SoftechConnector` ignores the branch-host override.
- WebSocket: chatter subscribe/post for any record with no allow-list; PBX group exposes all calls to every user; refresh/blacklisted tokens accepted; no Origin validator.
- SSRF via staff-set `recording_url` fetched by transcription (`omni/transcription.py:55`).
- Throttles keyed on spoofable `X-Forwarded-For` (`NUM_PROXIES` unset).
- No CSV/XLSX formula-injection guard in ~25 exports.
- Voucher OTP returned to the employee as a QR (can redeem without customer).
- Portal magic link reusable for 15 min; reorder quantity unbounded, unthrottled.
- Uploads: no type/size checks (mitigated by signed sandboxed media URLs).
- No `AUTH_PASSWORD_VALIDATORS` (6-char minimum only); HSTS 0 by default.
- `.gitignore` missing newline merged `.env` with a docs path; two tracked investigation exports may contain patient/financial data.
- Scheduler job `pos_orders_flush` defined twice (`apps/sync/tasks.py:2685,2853`).

## 4. Fine as found

Webhook HMAC (fail-closed outside DEBUG), portal customer scoping, wildcard search
(parameterised), media signing + traversal guard, OTP storage (hashed + salted), staff JWT in
httpOnly SameSite=Strict cookies, no eval/pickle/shell sinks, LLM outputs advisory only.
