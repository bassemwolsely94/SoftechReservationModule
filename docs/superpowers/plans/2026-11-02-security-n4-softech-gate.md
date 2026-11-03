# Security N4 — SOFTECH Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every SOFTECH connection opened for a web request is allowed, made read-only, or refused, according to who is asking and from which access zone. Log mode comes first; enforce comes only after the preflight check passes.

**Architecture:** One decision module, `apps/access/softech_gate.py`, reads the request's access context (N1–N3) and the `ZonePolicy.softech_read` / `softech_write` columns that N3 stored. It is called at the single choke point, `config/sybase.py::_connect_with_retry` (plus `probe_connection`).
- **Scheduler jobs (`job:*`) and commands (`cmd:*`)** keep system rights.
- **Web requests:** a request with no context fails closed.
- **Threads and pools started by views** carry the request's context through new helpers in `core/threads.py`, and a static guard keeps it that way.
- **A refusal** is its own exception, `SoftechAccessDenied`. No "branch offline" classifier ever treats it as offline, so the POS retry queue can never pick up a refused order and post it as the system.

**Tech Stack:** Django 5.2 / DRF, `contextvars`, jpype/jConnect (`config/sybase.py`), APScheduler, React 18 (whoami banner only).

**Spec:**
- `docs/security/2026-10-31-network-device-access-design.md`: §6.4 item 5 (SOFTECH gate), item 7 (audit), the "Rollout like RBAC" paragraph, and table row N4.
- The N3 plan `docs/superpowers/plans/2026-11-01-security-n3-zone-policy.md` for the interfaces N4 consumes.

**Branch:** `claude/security-n4` (worktree `.claude/worktrees/security-n4`), stacked on `claude/security-n3` (PR 35).

## Global Constraints

- CLAUDE.md rules apply in full.
  - **Rule 3:** never allow a double post to SOFTECH.
  - **Rule 8:** every SOFTECH interaction is auditable.
  - **Rule 9:** permissions are enforced server-side.
- Nothing changes in how any writer builds or sends its SQL. N4 only decides whether a connection may be opened, and whether it is read-only. The POS writer's serial allocation, `vf2` token and flush logic stay untouched.
- **New switch:** `SOFTECH_GATE_ENFORCEMENT` = `off` / `log` / `enforce`.
  - Read from `.env` via `config(...)`.
  - Default `'off' if _RUNNING_TESTS else 'log'`.
  - An unknown value counts as `log`.
  - `enforce` on an unsafe setup (`apps.access.policy_middleware.enforce_problem()` not None) runs as `log` and writes an ERROR line, the same as N3's I5.
- The gate never widens anything. The global kill switch `SOFTECH_READ_ONLY` and `config/writers.writer_allowed()` stay in force on top of it.
- **System scopes** — any scope that does not start with `web` (`job:*`, `cmd:*`) — always get FULL.
- **Refusal messages are Arabic** and must contain none of the substrings in `_UNREACHABLE_HINTS` (both writers) or `_CONNECTION_ERROR_MARKERS` (`apps/sync/tasks.py`).
  - Exact copy, deny: `SoftechAccessDenied`: `'SOFTECH غير متاح لدورك من هذا المكان'`.
  - Exact copy, write: `SoftechZoneWriteDenied`: `'الكتابة في SOFTECH غير متاحة لدورك من هذا المكان'`.
- **Log lines and audit rows** for the gate are deduplicated per `(user_id, zone, reason, mode)` for `LOG_DEDUPE_SECONDS = 600`, with `cache.add`. This copies `apps/access/middleware.py`.
- **Migrations:** `audit 0022` only (one new AuditLog action). No other schema change.
- **Tests:** use `TEST_DB_NAME=test_n4 --keepdb`. Never leave a process running. Never `git add -f` anything under `.superpowers`.
- **Help:** Arabic + English. Bump `updated` on every screen whose text changes.

## Review Focus

1. **Streaming exports that read SOFTECH while the response streams.** The middleware has already reset the context by then. Expected: the iterator runs inside the request's context. The test is in Task 1.
2. **A cashier on an unapproved branch PC (Z2) presses «ترحيل» in enforce.** Expected: the order becomes `push_failed` with the Arabic refusal. It is never `queued`, because the scheduler would post a queued order with system rights. A later push from an approved PC posts it exactly once. The test is in Task 4.
3. **The global `SOFTECH_READ_ONLY` is on and the zone grant is READ.** Expected: the connection is wrapped once, the stricter global message wins, and nothing raises `cannot be switched off`. The test is in Task 3.
4. **A health sweep started from the /sync screen by a role the gate refuses.** Expected: no node is recorded "offline". Refused probes are skipped, not stored. The test is in Task 3.
5. **An admin in Z3 with the per-user `external_softech_write` flag.** Expected: FULL. The same admin without the flag gets READ. The test is in Task 2.

---

### Task 1: Request context follows threads, pools and streamed responses

**Files:**
- Create: `core/threads.py`
- Modify:
  - every `threading.Thread(` / `Thread(target=` site under `apps/` (27 today — list them with `grep -rn "Thread(target\|threading.Thread(" --include=*.py apps core | grep -v /tests/`);
  - `apps/sync/network_health.py:92`;
  - `apps/images/views.py:782`;
  - `apps/access/middleware.py`.
- Test: `apps/tests/security/test_access_thread_context.py`

**Interfaces:**
- Produces:
  - `start_thread(target, *, args=(), kwargs=None, name=None, daemon=True) -> threading.Thread`: already started, runs `target` inside `contextvars.copy_context()` taken at call time.
  - `class ContextThreadPoolExecutor(concurrent.futures.ThreadPoolExecutor)`: `submit(fn, *a, **kw)` runs each task in its own `copy_context()` taken at submit time.
  - Both live in `core/threads.py`.

- [ ] **Step 1: Write the failing tests**

```python
class ThreadContextTests(SimpleTestCase):
    def test_start_thread_sees_access_context_and_scope(self):
        # set access_context + softech_load.scope('web:internal:admin'), start_thread(fn), join;
        # fn records context.current() and softech_load.current_scope()
        assert seen_ctx is ctx and seen_scope == 'web:internal:admin'

    def test_pool_submit_sees_context_per_task(self):
        # two submits under two different contexts → each task sees its own

    def test_streaming_response_iterates_inside_request_context(self):
        # a view returning StreamingHttpResponse(gen()) where gen() reads context.current();
        # client GET through the middleware stack → the chunk text names the request's role

class NoBareThreadsGuard(SimpleTestCase):
    def test_no_bare_threads_outside_core_threads(self):
        # AST scan of apps/ and core/ (excluding tests, migrations and core/threads.py):
        # any Call to threading.Thread / Thread / ThreadPoolExecutor fails, unless the file:line is in
        # ALLOWED = {'apps/sync/tasks.py': 'APScheduler executor (jobs are scoped job:*)',
        #            'apps/sync/apps.py': 'atexit workaround, no SOFTECH'}
        assert offenders == []
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `TEST_DB_NAME=test_n4 python manage.py test apps.tests.security.test_access_thread_context --keepdb`
Expected: FAIL, because `core.threads` does not exist.

- [ ] **Step 3: Implement `core/threads.py`, and convert every flagged site to `start_thread(...)` / `ContextThreadPoolExecutor(...)`**
  - Keep each site's `name=` and `daemon=`.
  - A site that kept the `Thread` object (`t = threading.Thread(...); t.start()`) uses the returned thread.
  - Then wrap streamed content in `AccessContextMiddleware.__call__`: if `response.streaming`, capture `ctx = contextvars.copy_context()` before the `finally` resets, and replace `response.streaming_content` with a generator that pulls each chunk with `ctx.run(next, it)`.

- [ ] **Step 4: Run them and confirm they pass,** then run `apps.tests.security.test_access_context apps.tests.security.test_access_policy_middleware`.
Expected: PASS.

- [ ] **Step 5: Commit**: `feat(security): request context follows threads, pools and streamed responses (N4)`.

---

### Task 2: The gate decision

**Files:**
- Create: `apps/access/softech_gate.py`
- Modify:
  - `config/settings.py` (next to `NETWORK_POLICY_ENFORCEMENT`, line 111);
  - `apps/audit/models.py` (action choice);
  - `apps/audit/migrations/0022_softech_gate_action.py`.
- Test: `apps/tests/security/test_access_softech_gate.py`

**Interfaces:**
- Consumes:
  - `apps.access.context.current()`, which returns `AccessContext(network, user_id, role, device, zone, failed)`;
  - `apps.access.session_policy.subject(user)`;
  - `apps.access.policy.policy_for(role, zone)`;
  - `apps.access.policy.softech_write_allowed(profile, zone)`;
  - `apps.access.policy_middleware.enforce_problem()`;
  - `apps.sync.softech_load.current_scope()`.
- Produces (in `apps/access/softech_gate.py`):
  - `FULL = 'full'`, `READ = 'read'`, `NONE = 'none'`.
  - `@dataclass(frozen=True) class GateDecision: grant: str; reason: str | None; scope: str; zone: str | None`
  - Reasons:
    - `'no_context'`: a web scope without an AccessContext;
    - `'anonymous'`;
    - `'context_failed'`;
    - `'zone_no_read'`;
    - `'zone_no_write'`.
  - `mode() -> str`: off / log / enforce, with unsafe enforce becoming log plus an ERROR line.
  - `decide(scope: str, ctx, profile) -> GateDecision`: pure apart from `policy_for`.
  - `check(label: str = '') -> GateDecision`: the **effective** decision for the current scope and context, after the mode.
    - **off:** always FULL.
    - **log:** returns FULL. A NONE is logged and audited as would-deny. A READ is returned as `GateDecision(READ, 'zone_no_write', …)` with `grant=READ` so that Task 3 installs the *observing* proxy.
    - **enforce:** returns the decision.
  - `note(decision, label, *, enforced: bool)`: deduplicated log line plus AuditLog row, action `'softech_gate_denied'`.
    - Label: `'SOFTECH — رفض حسب المنطقة'`.
    - `extra`: `{scope, zone, reason, label, mode, ip, device_id, enforced}`.

- [ ] **Step 1: Write the failing table test** for `decide` with `ctx` / `profile` doubles. Each row is (scope, ctx, profile) and the expected (grant, reason):

```python
CASES = [
    ('job:sync_stock',        None,                         None,            FULL, None),
    ('cmd:shell',             None,                         None,            FULL, None),
    ('web',                   None,                         None,            NONE, 'no_context'),
    ('web:external:anon',     ctx(zone=None, user=None),    None,            NONE, 'anonymous'),
    ('web:internal:anon',     ctx(failed=True, net='internal'), None,        FULL, 'context_failed'),  # F3 parity, ERROR logged
    ('web:external:anon',     ctx(failed=True, net='external'), None,        NONE, 'context_failed'),
    ('web:internal:salesperson', ctx(zone='Z1'),            prof('salesperson'), FULL, None),
    ('web:internal:salesperson', ctx(zone='Z2'),            prof('salesperson'), READ, 'zone_no_write'),
    ('web:external:salesperson', ctx(zone='Z3'),            prof('salesperson'), NONE, 'zone_no_read'),
    ('web:external:supervisor',  ctx(zone='Z3'),            prof('supervisor'),  READ, 'zone_no_write'),
    ('web:external:admin',       ctx(zone='Z3'),            prof('admin'),       READ, 'zone_no_write'),
    ('web:external:admin',       ctx(zone='Z3'),            prof('admin', external_softech_write=True), FULL, None),
    ('web:external:delivery',    ctx(zone='Z4'),            prof('delivery'),    NONE, 'zone_no_read'),
]
```

  These run against the seeded 0006 rows. Add these tests too:
  - `test_role_without_rows_inside_full_outside_none`, matching `policy.softech_write_allowed`'s no-row rule;
  - `test_check_log_mode_returns_full_and_audits_once`: two calls give one AuditLog row;
  - `test_check_enforce_unsafe_runs_as_log`: with `NETWORK_ENFORCE_GUARD=True` and `NETWORK_HEADER_TRUSTED=False`;
  - `test_check_off_never_audits`.

- [ ] **Step 2: Run it and confirm it fails** (`ImportError`).

- [ ] **Step 3: Implement**
  - The profile for `check()` is `subject(User.objects.select_related('staff_profile').get(pk=ctx.user_id))`, memoised for the request on a module `contextvars.ContextVar('softech_gate_subject')`, keyed by `user_id`.
  - Ordering in `decide`: system scope → no ctx → `ctx.failed` → anonymous → policy row.
  - Add `SOFTECH_GATE_ENFORCEMENT` to settings, and the audit choice plus its migration (`makemigrations audit`).

- [ ] **Step 4: Run it and confirm it passes.**

- [ ] **Step 5: Commit**: `feat(security): SOFTECH gate decision — role × zone × scope, log first (N4)`.

---

### Task 3: Wire the gate into the connection choke point

**Files:**
- Modify:
  - `config/sybase.py:221-341` (exceptions, proxies, `_guard`), `:362` (`_connect_with_retry`) and `:458` (`probe_connection`);
  - `apps/sync/network_health.py:58-110`.
- Test: `apps/tests/security/test_access_softech_connect.py`

**Interfaces:**
- Consumes: `softech_gate.check(label)` and `softech_gate.note(...)` from Task 2.
- Produces (in `config/sybase.py`):
  - `class SoftechAccessDenied(RuntimeError)`, with the exact copy from Global Constraints and attribute `.reason`.
  - `class SoftechZoneWriteDenied(SoftechReadOnlyError)`, with the exact copy.
  - `_guard(java_conn, zone_grant: str = 'full', observe_only: bool = False)`.
  - `probe_connection(...)` returns `{'ok': False, 'elapsed_ms': 0.0, 'error': <copy>, 'denied': True}` when refused, without connecting.

- [ ] **Step 1: Write the failing tests**, using a `Mock()` driver whose `connect` returns a `Mock()` java connection:
  - `test_denied_raises_before_driver_connect`: the gate returns NONE in enforce. Expect `SoftechAccessDenied`, `driver.connect.assert_not_called()`, no retry sleep, and no `record_connect(..., False)`.
  - `test_read_grant_refuses_write_sql`: READ in enforce. `conn.prepareStatement('UPDATE items SET x=1')` raises `SoftechZoneWriteDenied`; `prepareStatement('SELECT 1')` passes.
  - `test_read_grant_log_mode_observes_but_allows_write`: READ in log. The UPDATE is allowed, and one `softech_gate_denied` AuditLog row is written with `enforced=False`.
  - `test_global_read_only_wins_and_wraps_once`: `SOFTECH_READ_ONLY=True` plus READ. The UPDATE raises the global `SoftechReadOnlyError` text (not the zone one), and `setReadOnly(True)` was called once.
  - `test_full_grant_returns_raw_connection`: unchanged behaviour.
  - `test_probe_denied_does_not_connect` and `test_health_sweep_skips_denied_results`: `probe_all_nodes(record=True)` under a refused context stores no `NodeHealth` row for the refused nodes and returns them as `denied`.

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement**
  - `_connect_with_retry` calls `softech_gate.check(label)` once, before the retry loop:
    - NONE → raise `SoftechAccessDenied`;
    - otherwise → `_guard(driver.connect(...), zone_grant=d.grant, observe_only=(mode is log))`.
  - `_guard` order:
    1. global `SOFTECH_READ_ONLY` → existing `_ReadOnlyJavaConnection` only;
    2. zone READ → the same proxy classes with a pluggable `check` callable.
  - Give `_ReadOnlyStatement` and `_ReadOnlyJavaConnection` a `check=` parameter (default `_refuse_if_write`).
    - The zone enforce check raises `SoftechZoneWriteDenied`.
    - The zone observe check calls `softech_gate.note(..., enforced=False)` and returns.
    - The `setReadOnly(True)` hint only when enforcing.
  - The gate import is lazy, like `_load()`.
  - In `network_health`, skip storing results with `denied`.

- [ ] **Step 4: Run them and confirm they pass,** plus `apps.tests.security.test_softech_read_only_guard`.

- [ ] **Step 5: Commit**: `feat(security): SOFTECH connections follow the gate — refuse, read-only or full (N4)`.

---

### Task 4: A refusal is never "offline"; POS and the other writers stay single-post

**Files:**
- Modify:
  - `apps/pos_orders/writer.py:110`;
  - `apps/invoices/writer.py:64`;
  - `apps/sync/tasks.py:56`;
  - `core/errors.py:25`;
  - `core/exceptions.py` (create if missing) plus `REST_FRAMEWORK['EXCEPTION_HANDLER']` in `config/settings.py`.
- Test: `apps/tests/security/test_access_softech_refusal.py`

**Interfaces:**
- Consumes: the exceptions from Task 3.
- Produces:
  - `core.exceptions.api_exception_handler(exc, context)`: `SoftechAccessDenied` / `SoftechZoneWriteDenied` → `Response({'detail': str(exc), 'code': 'softech_zone'}, status=403)`; anything else → DRF's default.

- [ ] **Step 1: Write the failing tests**
  - `test_refusals_are_not_unreachable`: for both exceptions, `pos_orders.writer._is_unreachable`, `invoices.writer._is_unreachable` and `sync.tasks._is_connection_error` all return False. Also assert that neither message contains any marker from the three tuples.
  - `test_pos_push_refused_is_push_failed_not_queued`:
    - create a `SoftechSalesOrder` ready to push;
    - with the gate patched to NONE in enforce, call `writer.push_order(order, dry_run=False)`;
    - expect `SoftechAccessDenied`;
    - `order.status == STATUS_PUSH_FAILED`, `'SOFTECH غير متاح' in order.erp_error`, status never `STATUS_QUEUED`, and no serial-allocation call (patch the allocator and `assert_not_called`).
  - `test_pos_push_after_refusal_posts_once`: the same order, then the gate set to FULL with the fake writer connection used in `apps/tests/test_pos_resilience.py` / `apps/tests/security/test_softech_writes_pos_flush.py`. One insert is recorded, and a second push is refused by the existing idempotency (`vf2` token).
  - `test_public_error_shows_refusal_text`: `public_error(request, SoftechAccessDenied())` returns the Arabic copy, not `خطأ داخلي`, for a non-admin.
  - `test_uncaught_refusal_is_403`: a DRF view raising `SoftechAccessDenied` answers 403 with `code: softech_zone`.

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement**
  - Each classifier starts with `if isinstance(exc, (SoftechAccessDenied, SoftechReadOnlyError)): return False`.
  - `public_error` returns `str(exc)` for these two types, after logging.
  - Add the exception handler.

- [ ] **Step 4: Run them and confirm they pass,** plus `apps.tests.test_pos_resilience apps.tests.security.test_softech_writes_pos_flush apps.tests.security.test_softech_audit_pushes apps.tests.security.test_rbac_pos`.

- [ ] **Step 5: Commit**: `fix(security): a SOFTECH refusal is never "branch offline" — refused POS orders fail, never queue (N4)`.

---

### Task 5: SOFTECH write audit carries where it came from

**Files:**
- Modify: `core/softech_audit.py:37`.
- Test: `apps/tests/security/test_access_softech_audit.py`

**Interfaces:**
- Consumes: `apps.access.context.current()` and `apps.sync.softech_load.current_scope()`.
- Produces: every `audit_softech_write(...)` row's `extra` gains `ip`, `device_id`, `zone`, `network` and `scope`. These are `setdefault`, so a caller's own values win. If there is no context, only `scope` is added.

- [ ] **Step 1: Write the failing tests**: `test_write_audit_has_ip_device_zone` (with a context set) and `test_write_audit_without_context_has_scope_only`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.** Wrap the additions in try/except; auditing must never fail a write.
- [ ] **Step 4: Run them and confirm they pass,** plus `apps.tests.security.test_softech_audit_pushes`.
- [ ] **Step 5: Commit**: `feat(security): SOFTECH write audit records ip, device, zone and scope (N4)`.

---

### Task 6: Preflight, whoami and the screens

**Files:**
- Modify:
  - `apps/access/preflight.py` (new `check_softech(now)` added to `run`);
  - `apps/access/views.py` (whoami);
  - `frontend/src/components/ZoneBanner.jsx`;
  - `frontend/src/pages/ZonePolicyPage.jsx` (column hints);
  - `apps/access/models.py:157-158` (drop the "enforced in N4" comments);
  - `apps/help/content/admin.py` (the «سياسة الشبكات» and banner entries, Arabic + English, bump `updated`).
- Test: `apps/tests/security/test_access_preflight.py` (extend), `apps/tests/security/test_access_api.py` (extend).

**Interfaces:**
- Consumes: the AuditLog rows `softech_gate_denied` from Task 2.
- Produces:
  - whoami gains `softech_access: 'full' | 'read' | 'none'`, the effective grant for that request, and `softech_gate_mode`.
  - Preflight items:
    - `softech_no_context`: BLOCK when any row in the last `RECENT_DAYS` has reason `no_context`. That means a screen opens SOFTECH from a thread or path with no context, which would break in enforce. The item lists the scopes and labels.
    - `softech_would_deny`: WARN, listing role × zone × reason counts.
    - `softech_mode`: OK or WARN, showing the current mode.

- [ ] **Step 1: Write the failing tests**:
  - `test_preflight_blocks_on_no_context_rows`;
  - `test_preflight_warns_with_counts`;
  - `test_whoami_softech_access_read_in_z2`;
  - `test_whoami_softech_access_full_in_z1`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
  - ZoneBanner: when `softech_access === 'read'` and the mode is `enforce`, show the line «SOFTECH للعرض فقط من هذا المكان»; when it is `'none'`, show «SOFTECH غير متاح من هذا المكان». No new modal.
  - ZonePolicyPage: the hints under the «قراءة SOFTECH» / «كتابة SOFTECH» columns say they are enforced when `SOFTECH_GATE_ENFORCEMENT=enforce`.
- [ ] **Step 4: Run them and confirm they pass,** plus `apps.tests.test_help` and `npm run build`.
- [ ] **Step 5: Commit**: `feat(security): SOFTECH gate in preflight, whoami and the zone screens (N4)`.

---

### Task 7: Runbook and docs

**Files:**
- Modify:
  - `deploy/LINKDATACENTER_VPS_RUNBOOK.md` (new section «Batch N4 on the live server», after the N3 section);
  - `docs/security/2026-10-31-network-device-access-design.md` (row N4 → Built, with commits);
  - `docs/architecture/04_API_REGISTRY.md` (whoami fields).

- [ ] **Step 1: Write the runbook section**, in order:
  1. `release.sh` (migrates audit 0022).
  2. Confirm `SOFTECH_GATE_ENFORCEMENT` is absent or `log` in `/opt/elrezeiky/app/.env`.
  3. Run a log week, and check `journalctl -u elrezeiky-web | grep softech_gate`.
  4. `manage.py access_preflight` until there are no `softech_no_context` blockers.
  5. Switch with `sudo -u elrezeiky env SOFTECH_GATE_ENFORCEMENT=enforce $PY $APP/manage.py check && sed … .env && systemctl restart elrezeiky-web` (check before editing `.env`, as N3 Step 9).
  6. The way back: set it to `log` and restart.

  Also cover:
  - a staff note that a refused cashier sees «SOFTECH غير متاح…» and retries from an approved PC, where the order posts once;
  - the order of switches: N3 enforce first, then N4.
- [ ] **Step 2: Commit**: `docs(security): N4 runbook — log week, preflight, switch to enforce (N4)`.
