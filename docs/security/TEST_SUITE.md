# Security test suite — how it works

Design: [docs/superpowers/specs/2026-10-26-full-security-test-suite-design.md](../superpowers/specs/2026-10-26-full-security-test-suite-design.md) ·
inventory: [2026-10-26-security-inventory.md](2026-10-26-security-inventory.md) ·
code: `apps/tests/security/`

## Run it

```bash
# use your own test database name — other sessions share the default one
TEST_DB_NAME=test_elrezeiky_security venv/Scripts/python.exe manage.py test apps.tests.security --keepdb
```

Always through `manage.py test` (never pytest): the SOFTECH isolation in `config/settings.py`
only switches on under `manage.py test`. Creating the test database takes ~6 minutes; `--keepdb`
reuses it (drop it after migrations change).

| Part | File | Wall time (2026-10-26, Windows dev box) |
|---|---|---|
| Harness self-tests (baseline, pending, tripwire, role fixtures) | `test_harness.py` | ~20 s |
| Static guards (no DB) | `test_static_guards.py` | ~25–50 s |
| Role × route sweep, both modes | `test_role_sweep.py` | ~7–9 min |
| Authentication (Batch 3) | `test_auth_*.py`, `test_client_ip.py` | ~2 min |

## Baselines — the ratchet

Counts move as other work lands: on 2026-10-26 a parallel change put `MatrixPermission` on the
incentives views and 60 log-mode leaks went STALE the same day — the ratchet doing its job.


Every sweep and guard reports what it finds. What existed when the suite was written is listed
in `apps/tests/security/baselines/<name>.txt`, so the suite is green on day one. A test fails on:

- **NEW** — found but not listed: a fresh hole. Fix it. Only a reviewed, deliberate exception
  may be added by hand, with a `# reason:` line above it.
- **STALE** — listed but no longer found: the hole was fixed. Delete the line (or run once with
  `SECURITY_BASELINE_PRUNE=1`, which only ever deletes stale lines — it never adds).

A batch is done when its baselines are empty (or only hold reviewed `# reason:` lines).

| Baseline | Entries 2026-10-26 | Owner batch | What a line means |
|---|---|---|---|
| `role_leaks_enforce` | 0 | 4 | matrix-denied request that got through with `RBAC_ENFORCEMENT=enforce` — must stay empty |
| `role_leaks_log` | 1391 | 4 | matrix-denied request the **view** let through (`log` mode = today's production) |
| `role_overblocks` | 683 | 4 (owner review) | matrix grants the role, the request answered 403 |
| `role_softech_reach` | 6 | 4 | matrix-denied request that still reached a SOFTECH connection attempt |
| `role_crashes` | 29 | 7 | 500 / exception for some role (admin included) with SOFTECH and the internet offline |
| `role_outside_reach` | 18 | 4 | matrix-denied request that still started a thread / pool job / HTTP / socket / subprocess |
| `role_unproven` | 1220 | 4/5 | denied role and admin both got 404 — the check behind the route was never reached |
| `unclassified_api_prefixes` | 3 | 4 | `/api/<prefix>/` the RBAC middleware never checks (`tasks`, `recommendations`, `stock-audit`) |
| `sql_from_text` | 218 | 1 → 2 | SQL built from text reaching an execute-style call. Batch 1 fixed every user-reachable read; what is left is explained in blocks: 26 SOFTECH write paths reviewed in Batch 2 (the 2 HIGH ones — user value unescaped — fixed by P-1 via `_dt_literal`; the rest bind or escape their values), 73 internal-only (with reasons), 119 management commands. A new line needs a `# reason:` or `# Owner: Batch 2` header (guarded) |
| `raw_softech_connect` | 0 | 2 ✅ | SOFTECH connection bypassing the read-only kill-switch — must stay empty (`diag_appname` deleted, P-3) |
| `write_flags_default_true` | 6 | 2 ✅ | write-pattern switch defaulting ON — only reviewed ones left: no SOFTECH write (P-5 turned those off); `AP_RECONCILE_AUTO_APPROVE` stays on (owner confirmed 2026-10-26) |
| `tracked_secrets` | 2 | 6 | credential-looking literal in a tracked file (1 real: `scripts/smoke_api_live.py`) |

Also ratcheted outside the baselines folder:

- `softech_write_manifest.py` — **every** SOFTECH INSERT/UPDATE/DELETE site (59), with tables,
  switch, dry-run, idempotency, audit, trigger — each field verified against the code (P-10).
  A new write site without an entry fails.
- `bandit-baseline.json` — 568 bandit findings (553 are B608 SQL strings; also B613 trojan-source
  ×2, B507 SSH host-key ×1, B324 weak hash ×2, B310 urlopen ×5 — Batch 6). CI fails on new ones.
  2026-10-27: +10 reviewed B608 (placeholders only, constant WHERE with bound values, regex-checked
  identifiers, read-only probe lists). Bandit runs with forward-slash paths in CI, so on Windows
  compare by (file, test, text, severity, confidence) instead of passing `-b` directly.
- `pip-audit-ignore.txt` / `npm-audit-allow.txt` — known dependency advisories (below).

## Testing SQL: `RecordingSybase`

`apps/tests/security/sql_recorder.py` stands in for SOFTECH (`get_sybase_connection`,
`get_branch_connection`, `SoftechConnector.connect`) and records every `(sql, params)`.
Push a payload through the real endpoint and prove it arrived bound:

```python
with RecordingSybase(rows=[...]) as rec:
    client.get('/api/…', {'code': "1' OR '1'='1"})
assert_payload_bound(self, rec.calls, "1' OR '1'='1")
```

Every execute also checks `sql.count('?') == len(params)`. IN-lists are chunked at **400**
bound parameters per statement (proven live). Fixed in Batch 1: stock count, near-expiry +
incentive readers, shortage supplier export, purchase-expiry audit, procurement category
backfill (now ORM), invoice OCR code recall — `apps/tests/security/test_sqli_*.py`.

## Role sweep classification

Every non-admin role × every protected `/api/` route × `GET` and `POST {}`, once with the RBAC
middleware enforcing and once logging only. Expectations come from the **code** role matrix
(`seed_permissions.PERMISSIONS`, owner decision 1) through `module_access.required()`.

- Matrix **denies**: 401/403/404/405 ok · 2xx/400/409/422 **leak** (400 means validation ran, so
  permission passed) · 500/exception **crash**.
- Matrix **grants**: 403 **overblock** · 500/exception **crash**.
- 301/503 ok either way.
- Admin sends every request too, as the reference. A denied role's **404** counts as a refusal
  only when admin got further; when admin also got 404 the route was never reached (id 1
  doesn't exist) and the request is listed as **unproven** — Batches 4/5 add real records so
  these become real checks.
- A denied role whose request still tried SOFTECH (`role_softech_reach`) or started a thread,
  HTTP call, socket or subprocess (`role_outside_reach`) is listed — permission came too late.
- **Known gap:** only GET and POST `{}` are swept. PUT / PATCH / DELETE (the matrix's
  `edit` / `delete`) are added in Batch 4.
- Clients log in with a real Bearer JWT — `force_authenticate()` would hide the user from the
  middleware.
- Each request runs in a rolled-back savepoint inside the **Tripwire**: SOFTECH connections,
  `requests`, any Python socket (urllib, httpx/SDKs, AMI, SFTP, Redis, SMTP), subprocesses,
  threads and thread-pool jobs are blocked and recorded, never run. PostgreSQL is unaffected
  (libpq, not Python sockets).

## Batch 2 — SOFTECH write safety (done 2026-10-26)

[Plan](../superpowers/plans/2026-10-26-security-suite-batch-2-softech-writes.md). Each item: a
failing test first, then a diff the owner approved. Tests: `test_softech_*.py`.

- **P-1** POS `claim.examdate` and every `__dt__` value pasted unescaped into SOFTECH INSERTs → real dates only (`_dt_literal`) + serializer date check.
- **P-2** shortage flag / unflag / dismiss / retrieve wrote SOFTECH `items` for any logged-in user → permission checked in each view.
- **P-3** `diag_appname` opened its own connection past the kill-switch and INSERTed on HQ → deleted.
- **P-4** loyalty points adjust: retry wrote double points, no cap → row lock + 2-minute duplicate window, 1,000-point cap, role list.
- **P-5** four SOFTECH write switches defaulted ON (pricing, replication repair, loyalty, personal comments) → default off.
- **P-6** writes reachable over HTTP with no switch (tier create, invoice probe, coupon batch probe) → gated.
- **P-7** rehearsal / diagnostic writes (`probe_*`, `investigate_*`, `diag_*`, command modes) → `SOFTECH_PROBES_ENABLED` (default off).
- **P-8** read-only guard holes (`--` inside a string literal, `stmt.getConnection()`, connector ignoring the branch-host override) → closed.
- **P-9** writers that relied on their caller for the switch → check it themselves.
- **P-10** write manifest: every field verified against the code, plus a switch-off test per site.
- **P-11** POS double post: flush job registered twice + non-atomic claim → one job, atomic claim.
- **P-12** `SoftechConnector` begin / commit / rollback were no-ops (a "rehearsal" committed `cheques`) → real transactions.
- **P-13** rate / coverage / ISR-approve rehearsals restore in `finally`.
- **P-14** sync investigations restore every row they touch, `usercode` included (`core/softech_probe_restore.py`); replication-cycle plant gets a guarded `--mode restore`.
- **P-15** locks / idempotency: ISR push (per-draft lock, status re-read; `push_isr --commit` retired), insurance rebalance / revert and date edit, points removal, offers channel B.
- **P-16** an AuditLog row for every SOFTECH write (`core/softech_audit.py`): item / catalog writes (a) and who pushed (b). The `softech_*` action labels still need one state-only migration in the audit app.

## Batch 3 — authentication (done 2026-10-27)

[Plan](../superpowers/plans/2026-10-27-security-suite-batch-3-auth.md). Same flow as Batch 2.
Tests: `test_auth_*.py`, `test_client_ip.py`.

- **A-1** 2FA bypass with the password only: the login pre-auth token could set up and enable a new secret over the enrolled one → setup / enable take an enrol token only and refuse an enrolled account.
- **A-2** second factor guessable / replayable → 5 wrong codes end the login; a login token opens one session; an accepted code can't be used again.
- **A-3** disabling an account or resetting its password left the session alive → access and refresh refused for an inactive account, all refresh tokens blacklisted on change / reset / disable (`apps/users/sessions.py`); the remembered-device token is tied to the password and 2FA secret.
- **A-4** WebSocket took refresh tokens, disabled accounts and any Origin → access token of an active account only, `AllowedHostsOriginValidator`.
- **A-5** passwords: 6 characters only → `AUTH_PASSWORD_VALIDATORS` (10 characters, common, numeric, similar to username) on change, admin reset and create (`apps/users/passwords.py`); create-user no longer answers 500 after saving.
- **A-6** forged client address: DRF throttles keyed on the whole `X-Forwarded-For`, audit IP its client-written first entry → `NUM_PROXIES` (1 on the VPS; default 1 behind the HTTPS proxy) feeds DRF and `core/client_ip.py`.

## Pending owner decisions

A test exposing a hole whose fix needs the owner's OK (SOFTECH writes, auth, pricing, checkout)
is marked `@pending('<X>-<n>')` (an expected failure: `P-` Batch 2, `A-` Batch 3) and listed in
`apps/tests/security/PENDING.md`. A guard keeps the markers and the list in step; the marker
comes off when the fix lands.

## CI

`.github/workflows/ci.yml`: `coverage run manage.py test` + coverage report (no floor yet —
Batch 7 sets it), `bandit -b bandit-baseline.json`, `pip_audit_check.py`, and in the frontend job
`npm_audit_check.cjs` before the build (it fails when the audit itself can't run).

## Known dependency advisories (2026-10-26)

- **Python** (`pip-audit-ignore.txt`, owner Batch 6): direct pins — Django 4.2.13 (81; the 4.2
  line is past end of support and several fixes ship only in 5.2+), djangorestframework 3.15.1 (7),
  djangorestframework-simplejwt 5.3.1 (2), twisted 26.4.0 (6); installed transitive packages —
  147 advisories in 21 packages, notably Pillow (62), **PyJWT (19 — login tokens)**, aiohttp (14),
  cryptography (7), sqlparse (9), daphne (4). The CI check audits the installed environment
  (exactly what requirements-ci.txt installs); run it inside the production venv to cover
  production-only packages.
- **npm (production deps) — 35 advisories** (`npm-audit-allow.txt`): axios (most, several high),
  follow-redirects, form-data, react-router / react-router-dom. Owner: Batch 6.
