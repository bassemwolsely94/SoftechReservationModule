# Security Suite — Batch 0 (Harness) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared harness every later batch plugs into: a ratchet for known holes, a
shared route catalogue with a SOFTECH/side-effect tripwire, per-role JWT clients on the code
role matrix, the role × route sweep, the static guards, and CI scanners.

**Architecture:** New package `apps/tests/security/`. Generic sweeps and AST guards report what
they find; anything found today goes into a tracked *baseline* file, so the suite is green on day
one but fails on any **new** hole and on any **fixed-but-still-listed** hole. Later batches shrink
the baselines to empty. Runs only under `manage.py test` (the SOFTECH isolation in
`config/settings.py` depends on it).

**Tech Stack:** Django 4.2 test runner, DRF `APIClient` + simplejwt `AccessToken`, Python `ast`,
coverage.py, bandit, pip-audit, npm audit, GitHub Actions.

**Spec:** [docs/superpowers/specs/2026-10-26-full-security-test-suite-design.md](../specs/2026-10-26-full-security-test-suite-design.md)
(inventory: [docs/security/2026-10-26-security-inventory.md](../../security/2026-10-26-security-inventory.md))

**Later batches** each get their own plan file, written at the start of the batch, because what
they fix depends on what this harness reports (the spec's "every view stronger than
IsAuthenticated" static guard and the cross-branch record fixtures are built in Batches 4 and 5,
on top of this harness): 1 SQL injection · 2 SOFTECH safety · 3 Auth ·
4 Authorization · 5 Branch scoping · 6 Platform & abuse · 7 Per-app coverage · 8 Frontend.

## Global Constraints

- Test runner: `venv/Scripts/python.exe manage.py test …` locally, `python manage.py test` in CI. No pytest.
- Locally always export `TEST_DB_NAME=test_elrezeiky_security` first — other sessions use the default test database (seen 2026-10-26: "being accessed by other users").
- No test may open a SOFTECH/HQ/branch connection, make outbound HTTP, or start a background thread.
- Role truth = `PERMISSIONS` in `apps/users/management/commands/seed_permissions.py` (owner decision 1).
- The role sweep runs in **both** `RBAC_ENFORCEMENT='enforce'` and `'log'` (owner decision 2: views must be safe on their own).
- Middleware only sees real credentials: sweep clients authenticate with `Bearer <AccessToken>`, never `force_authenticate`.
- Baseline entries are posix paths relative to the repo root, one per line, `#` comments allowed, sorted.
- Baselines may only shrink without a human edit: the update switch removes stale entries, never adds.
- Batch 0 changes no product code. Every hole found goes into a baseline for its owning batch.
- No commits unless the owner asks (spec, "My calls").
- Don't touch the unrelated uncommitted work in the tree.

## Review Focus

1. **A client the middleware can't see.** `force_authenticate` bypasses `ModuleAccessMiddleware`, so the sweep would report "safe" for everything → Task 3 pins that a sweep viewer gets 403 from the middleware in enforce mode.
2. **The sweep causing real side effects.** POSTing `{}` to ~600 routes can hit triggers, flushes, thread launchers → Task 2 tripwire test: a view that starts a thread and calls `get_sybase_connection` records both and runs neither.
3. **A baseline that quietly grows.** Someone sets the update switch to silence a new leak → Task 1 test: update mode drops stale entries and still fails on new ones.
4. **SQL built in one statement and executed in the next** (`sql = f"…"; cur.execute(sql)`), or with `%` / `+` / `.format` → Task 5 synthetic-snippet tests for all four shapes plus the safe parameterised shape.
5. **Windows paths in baselines.** Entries written on Windows with `\` wouldn't match in CI → Task 1 test that entries are normalised to `/`.

---

### Task 1: Ratchet baselines and the pending-decision list

**Files:**
- Create: `apps/tests/security/__init__.py` (empty)
- Create: `apps/tests/security/baseline.py`
- Create: `apps/tests/security/baselines/.gitkeep`
- Create: `apps/tests/security/PENDING.md`
- Test: `apps/tests/security/test_harness.py`

**Interfaces:**
- Produces:
  - `REPO_ROOT: pathlib.Path`
  - `norm(path: str | Path) -> str`: repo-relative posix path.
  - `load_baseline(name: str) -> set[str]`: reads `baselines/<name>.txt`, ignores blanks and `#` lines.
  - `assert_matches_baseline(testcase, name: str, found: Iterable[str]) -> None`
    - Fails with two labelled lists: `NEW (fix it or, if reviewed, add it to baselines/<name>.txt)` and `STALE (fixed — delete from baselines/<name>.txt)`.
    - When env `SECURITY_BASELINE_PRUNE=1`, it rewrites the file without the stale entries, keeping comments. It still fails on new entries.
  - `pending_ids() -> set[str]`: ids from `PENDING.md` lines shaped `- P-<n>: …`.
  - `pending(decision_id: str)`: decorator = `unittest.expectedFailure` plus `__pending__ = decision_id` on the test.

- [ ] **Step 1: Write the failing tests** in `test_harness.py`, class `BaselineTests(SimpleTestCase)`. Use a temp dir patched over the baselines directory.
  - `test_new_entry_fails`: baseline `{a}`, found `{a, b}` → `AssertionError` whose message contains `NEW` and `b`.
  - `test_stale_entry_fails`: baseline `{a, b}`, found `{a}` → message contains `STALE` and `b`.
  - `test_prune_removes_stale_but_still_fails_on_new`: with `SECURITY_BASELINE_PRUNE=1`, baseline `{a, s}`, found `{a, n}` → raises (because of `n`), and the file now holds `a` but not `s`.
  - `test_comments_and_blanks_ignored`.
  - `test_norm_uses_forward_slashes`: `norm(REPO_ROOT / 'apps' / 'x.py') == 'apps/x.py'`.

  Class `PendingTests(SimpleTestCase)`:
  - `test_markers_match_pending_md`: walk every test method in `apps.tests` that has `__pending__`. The set of ids must equal `pending_ids()`. Both are empty today, so this passes once written.

- [ ] **Step 2: Run, expect failures (ImportError)**
  Run: `venv/Scripts/python.exe manage.py test apps.tests.security.test_harness -v 2`

- [ ] **Step 3: Implement `baseline.py`.** Create `PENDING.md` with a heading, one sentence on how it's used, and an empty list.

- [ ] **Step 4: Run, expect PASS** (same command).

---

### Task 2: Shared route catalogue and side-effect tripwire

**Files:**
- Create: `apps/tests/security/routes.py`
- Modify: `apps/tests/test_endpoint_sweep.py`. Delete its `_CONVERTERS`, `_render`, `_walk`, `_view_id`, `_is_public`, `_api_routes`, `_known` and `_Offline`, and import them from `routes.py`. `KNOWN_PUBLIC_VIEWS` moves to `routes.py` unchanged. Keep the test classes.
- Test: `apps/tests/security/test_harness.py` (add `TripwireTests`)

**Interfaces:**
- Produces, in `routes.py`:
  - `KNOWN_PUBLIC_VIEWS: set[str]`
  - `api_routes() -> Iterator[tuple[str, Callable]]`
  - `view_id(cb) -> tuple[str, type | None]`
  - `is_public(cls) -> bool`
  - `known_public(view_id: str) -> bool`
  - `class Tripwire` (context manager):
    - While active, `config.sybase.get_sybase_connection`, `config.sybase.get_branch_connection`, `config.sybase.SoftechConnector.connect` and `config.sybase._ensure_jvm` raise `ConnectionError('offline in tests')`. Each call is appended to `self.softech_calls: list[str]` (qualified name).
    - `requests.sessions.Session.request` raises the same error and is recorded in `self.http_calls`.
    - `threading.Thread.start` becomes a no-op that records the target's qualified name in `self.threads`.
    - `Offline` stays as an alias of `Tripwire` for the existing sweep.

- [ ] **Step 1: Write the failing tests** in `TripwireTests(SimpleTestCase)`:
  - `test_softech_call_is_blocked_and_recorded`: inside `Tripwire() as t`, calling `config.sybase.get_sybase_connection()` raises `ConnectionError`, and `t.softech_calls == ['config.sybase.get_sybase_connection']`.
  - `test_thread_start_is_recorded_not_run`: a `threading.Thread(target=f)` whose `f` sets a flag. Inside the tripwire, `.start()` leaves the flag unset and `t.threads` has one entry.
  - `test_http_is_blocked`: `requests.get('http://example.invalid')` raises, and `len(t.http_calls) == 1`.
  - `test_patches_removed_on_exit`: after the block, `threading.Thread.start` is the original.

- [ ] **Step 2: Run, expect ImportError**
  Run: `venv/Scripts/python.exe manage.py test apps.tests.security.test_harness.TripwireTests -v 2`

- [ ] **Step 3: Implement `routes.py`.** Move the helpers verbatim, add `Tripwire`, then rewire `test_endpoint_sweep.py`.

- [ ] **Step 4: Run both, expect PASS. The existing sweep must be unchanged in result.**
  Run: `venv/Scripts/python.exe manage.py test apps.tests.security apps.tests.test_endpoint_sweep -v 1`

---

### Task 3: Role fixtures on the code matrix

**Files:**
- Create: `apps/tests/security/fixtures.py`
- Test: `apps/tests/security/test_harness.py` (add `RoleFixtureTests`)

**Interfaces:**
- Consumes: `apps.tests.factories.make_branch`, `make_branch2`, `make_user`; `apps.users.models.ROLE_CHOICES`, `RoleModuleAccess`; `core.middleware.module_access.clear_cache`; `seed_permissions.PERMISSIONS`, `ALL_MODULES`, `ALL_ACTIONS`.
- Produces:
  - `ROLES: list[str]`: every role in `ROLE_CHOICES`.
  - `NON_ADMIN_ROLES: list[str]`
  - `seed_code_matrix() -> None`: replaces all `RoleModuleAccess` rows with one row per (role, module, action) from `PERMISSIONS` (allowed and denied), then `clear_cache()`.
  - `granted(role: str, module: str, actions: tuple[str, ...]) -> bool`: answers from `PERMISSIONS` directly. Admin is always True.
  - `bearer_client(user) -> APIClient`: credentials `HTTP_AUTHORIZATION='Bearer ' + str(AccessToken.for_user(user))`.
  - `role_clients(branch=None) -> dict[str, APIClient]`: one user per role named `sec_<role>`, in `branch` (default `make_branch()`). Admin gets `access_all=True`.

- [ ] **Step 1: Write the failing tests** in `RoleFixtureTests(TestCase)`:
  - `test_matrix_matches_code`: after `seed_code_matrix()`, `RoleModuleAccess.objects.filter(role='viewer', module='finance', action='view', is_allowed=True).exists() == granted('viewer', 'finance', ('view',))`. Repeat for `('call_center', 'pos', ('create',))`.
  - `test_row_count_is_complete`: count == `len(ROLES) * len(ALL_MODULES) * len(ALL_ACTIONS)`.
  - `test_middleware_sees_bearer_client`: under `override_settings(RBAC_ENFORCEMENT='enforce')`, `role_clients()['viewer'].get('/api/sync/logs/')` returns 403 with `json()['module'] == 'sync'`. This pins Review Focus 1.
  - `test_admin_not_blocked`: admin client GET `/api/sync/status/` != 403.

- [ ] **Step 2: Run, expect ImportError**
  Run: `venv/Scripts/python.exe manage.py test apps.tests.security.test_harness.RoleFixtureTests -v 2`

- [ ] **Step 3: Implement `fixtures.py`.** Use `bulk_create` after `RoleModuleAccess.objects.all().delete()`.

- [ ] **Step 4: Run, expect PASS.** If `test_row_count_is_complete` fails because the model has a unique constraint or other fields, adapt to the model. Don't change the matrix.

---

### Task 4: Role × route sweep

**Files:**
- Create: `apps/tests/security/test_role_sweep.py`
- Create (generated on first run, then reviewed): `apps/tests/security/baselines/role_leaks_enforce.txt`, `role_leaks_log.txt`, `role_overblocks.txt`, `role_crashes.txt`

**Interfaces:**
- Consumes: `routes.api_routes`, `view_id`, `is_public`, `known_public`, `Tripwire`; `fixtures.seed_code_matrix`, `role_clients`, `granted`, `NON_ADMIN_ROLES`; `module_access.required(path, method) -> (module, actions) | None`; `baseline.assert_matches_baseline`.
- Produces, used by Batches 4/5:
  - `sweep(mode: str, roles: list[str]) -> SweepResult`
  - `SweepResult(leaks: set[str], overblocks: set[str], crashes: set[str], softech_calls: list[str], threads: list[str])`
  - Entry format: `<role> <METHOD> <path>`. No status code, so entries stay stable.

**Classification rules** (the single source of truth for later batches). For each non-public route, each non-admin role, and methods GET and POST (`{}` JSON):
- `need = required(path, method)`. If `None` (unmapped/exempt prefix) → skip. Prefix coverage is Task 5's guard.
- Each request runs inside `transaction.atomic()` with a forced rollback, wrapped in `Tripwire`.
- Expected denied (`not granted(role, *need)`):
  - status in {401, 403, 404, 405} → ok
  - 2xx, 400, 409 or 422 → **leak** (400 means validation ran, so permission passed)
  - 500 or raised → **crash**
- Expected allowed:
  - 403 → **overblock** (owner review, not failure semantics)
  - 500 or raised → **crash**
- 301 or 503 → ok in both cases.

- [ ] **Step 1: Write the tests** in `RoleSweepTests(TestCase)`. `setUpTestData`: `seed_code_matrix()`, `role_clients()`.
  - `test_enforce_mode_leaks` (`override_settings(RBAC_ENFORCEMENT='enforce')`): `assert_matches_baseline(self, 'role_leaks_enforce', result.leaks)`.
  - `test_log_mode_leaks` (`'log'`): the same against `role_leaks_log`.
  - `test_overblocks` (enforce): against `role_overblocks`.
  - `test_crashes`: the union from both modes, against `role_crashes`.
  - `test_sweep_touches_nothing_outside`: `result.softech_calls == []` for both modes. Threads recorded are allowed but never run (the assertion is that the tripwire caught them, so `threads` is reported in the failure message only).
  - `test_sweep_is_not_empty`: enforce mode classified more than 2,000 (role, method, route) triples. This guards against a broken route walk silently checking nothing.

- [ ] **Step 2: First run. It fails with the full NEW lists. That run *is* the inventory.**
  Run: `venv/Scripts/python.exe manage.py test apps.tests.security.test_role_sweep -v 2 > scratch/role_sweep_first_run.txt 2>&1`

- [ ] **Step 3: Write the four baseline files from the NEW lists.** Head each with: `# Owner: Batch 4 (authorization). Every line is a hole; the batch is done when this file is empty.` For overblocks use `# Owner review: role is granted in the matrix but the view refuses.` For crashes use `# Owner: Batch 7.`
  - If `test_sweep_touches_nothing_outside` fails, stop. That is a view reaching SOFTECH through a path the tripwire doesn't cover: extend `Tripwire` (Task 2) and rerun. Never baseline it.

- [ ] **Step 4: Run, expect PASS.** Record the wall time in the Task 6 doc. If the file takes more than 15 min, split each test per role with `subTest` (keep one baseline per mode).

---

### Task 5: Static guards

**Files:**
- Create: `apps/tests/security/static_scan.py`
- Create: `apps/tests/security/softech_write_manifest.py`
- Create: `apps/tests/security/test_static_guards.py`
- Create (from first run, then reviewed): `baselines/sql_from_text.txt`, `raw_softech_connect.txt`, `write_flags_default_true.txt`, `tracked_secrets.txt`, `unclassified_api_prefixes.txt`

**Interfaces:**
- Produces:
  - `static_scan.python_files(roots=('apps', 'core', 'config', 'scripts')) -> Iterator[Path]`: excludes `apps/tests/`, `migrations/` and `__pycache__`.
  - `static_scan.sql_from_text_sites(tree, path) -> set[str]`: entries `path::Qualname.func`. A site is a call to `execute`, `executeQuery`, `executeUpdate`, `executeLargeUpdate`, `prepareStatement`, `addBatch`, `raw`, `extra` or `_run` whose first argument is any of:
    - an f-string with an interpolation
    - `%` on a string
    - `.format(...)`
    - `+` with a non-constant operand
    - a `Name` assigned one of the above earlier in the same function
  - `static_scan.raw_connect_sites(tree, path) -> set[str]`: any reference to `SybDriver`, `DriverManager.getConnection`, `jaydebeapi.connect` or `pyodbc.connect`. In `config/sybase.py`, the functions `get_sybase_connection`, `get_branch_connection`, `probe_connection` and `SoftechConnector.connect` are allowed.
  - `static_scan.softech_write_sites(tree, path) -> set[str]`: entries `path::Qualname.func` for every string constant (including f-string literal parts) matching `(?is)\b(insert\s+into|update\s+[\w.]+\s+set|delete\s+from)\b`, in a module that references `config.sybase`, `get_sybase_connection`, `get_branch_connection`, `SoftechConnector` or `createStatement`.
  - `softech_write_manifest.WRITE_SITES: dict[str, WriteSite]`
  - `WriteSite(tables: tuple[str, ...], flag: str | None, dry_run_default: bool, idempotency: str | None, audit: str | None, trigger: str, owner_batch: int)`

- [ ] **Step 1: Write the snippet tests** in `StaticScanUnitTests(SimpleTestCase)`. Each one parses an inline source string:
  - `test_fstring_execute_flagged`: `def f(x): cur.execute(f"select {x}")` → one site `t.py::f`.
  - `test_variable_then_execute_flagged`: `def f(x):\n sql = "a %s" % x\n cur.execute(sql)` → flagged.
  - `test_format_and_concat_flagged`: two functions, both flagged.
  - `test_parameterised_not_flagged`: `cur.execute("select ?", [x])` → no site.
  - `test_raw_connect_flagged_outside_sybase`: `SybDriver().connect(u, p)` in `apps/x.py` is flagged; the same in `config/sybase.py::get_sybase_connection` is not.
  - `test_write_literal_detected`: a module with `from config.sybase import get_sybase_connection` and `"INSERT INTO SOFTECHDB9.dbo.picpoints (a) VALUES (?)"` in `def push()` → `{'m.py::push'}`.

- [ ] **Step 2: Write the guard tests** in `StaticGuardTests(SimpleTestCase)`:
  - `test_no_sql_built_from_text` → baseline `sql_from_text` (Owner: Batch 1; reviewed internal-constant sites stay with a `# reason:` comment above them).
  - `test_no_raw_softech_connections` → baseline `raw_softech_connect` (Owner: Batch 2).
  - `test_every_softech_write_site_is_registered`: `set(WRITE_SITES) == found`, failing with the unregistered and the stale keys. Plus `test_manifest_flags_exist`: every non-None `flag` is a real attribute of `django.conf.settings`.
  - `test_softech_write_flags_default_false`: parse `config/settings.py` with `ast`. Find `config('<KEY>', default=True, …)` where KEY matches the settings file's own regex `(_ENABLED|_WRITE|_WRITER|_AUTO_APPROVE|_AUTO_TOPUP|_UPDATE_PATIENTDATA|_NOTIFY)$`. Report against baseline `write_flags_default_true` (Owner: Batch 2 — needs owner OK).
  - `test_no_hardcoded_secrets_in_tracked_files`: `git ls-files` (skip with a clear message if git is missing). Scan text files under 1 MB for:
    - `(?i)(pass(word)?|secret|token|api[_-]?key)\s*[:=]\s*['"][^'"\s]{6,}['"]`
    - `-----BEGIN [A-Z ]*PRIVATE KEY-----`
    - `AIza[0-9A-Za-z_\-]{35}`
    - `eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.`

    Entries are `path:pattern-name`. Excluded: `apps/tests/`, `*.example`, `docs/`, `package-lock.json`. Baseline `tracked_secrets` (Owner: Batch 6).
  - `test_every_api_prefix_is_classified`: every `parts[2]` of `api_routes()` must be in `MODULE_BY_PREFIX`, `READ_OPEN_PREFIXES` or `EXEMPT_PREFIXES`. Baseline `unclassified_api_prefixes` (Owner: Batch 4).

- [ ] **Step 3: Run, expect ImportError, then implement `static_scan.py`.** Use `ast.NodeVisitor` tracking the enclosing class/function qualname, and per-function `Name → tainted` assignments.
  Run: `venv/Scripts/python.exe manage.py test apps.tests.security.test_static_guards -v 2`

- [ ] **Step 4: Populate `WRITE_SITES` from the first run's unregistered list.**
  - Fill every field from the code at that site, using the inventory's write-path table as a cross-check.
  - Fields you can't establish from the code are `None` with a comment `# unknown — Batch 2`.
  - Never guess a flag.

- [ ] **Step 5: Write the five baseline files from the NEW lists.** Use the owner headers listed above.

- [ ] **Step 6: Run, expect PASS.** Then sanity-check against the inventory:
  - `raw_softech_connect` must contain `apps/invoices/management/commands/diag_appname.py::_connect`.
  - `write_flags_default_true` must contain the four inventory flags (`PRICING_SOFTECH_WRITE_ENABLED`, `REPLICATION_REPAIR_ENABLED`, `LOYALTY_SOFTECH_WRITE_ENABLED`, `PERSONAL_COMMENT_WRITE_ENABLED`).
  - `sql_from_text` must contain `apps/stockcount/engine.py::fetch_transaction_items` and `apps/incentives/engine.py` near-expiry.
  - `tracked_secrets` must contain `scripts/smoke_api_live.py`.

  If any is missing, the scanner is wrong: fix it, don't edit the baseline.

---

### Task 6: CI scanners, coverage, and the suite guide

**Files:**
- Modify: `requirements-ci.txt` (add `coverage>=7.4`, `bandit>=1.7.8`, `pip-audit>=2.7`)
- Create: `.coveragerc` (`source = apps, core, config`; omit `*/migrations/*`, `apps/tests/*`, `*/management/commands/*`)
- Create: `apps/tests/security/bandit-baseline.json` (generated)
- Modify: `.github/workflows/ci.yml`
- Create: `docs/security/TEST_SUITE.md`
- Modify: `docs/architecture/11_ERP_INDEX.md` (one row in DESIGN DOCS pointing at the spec and the guide)

- [ ] **Step 1: Generate the bandit baseline locally.**
  Run: `venv/Scripts/python.exe -m pip install bandit pip-audit coverage`, then `venv/Scripts/python.exe -m bandit -r apps core config -x apps/tests,*/migrations -f json -o apps/tests/security/bandit-baseline.json -ll`
  Expected: a JSON file. Skim it: it should list the stockcount/incentives SQL (B608). Confirm that, don't fix it.

- [ ] **Step 2: Run pip-audit and npm audit locally. Record the findings in `TEST_SUITE.md` under "Known dependency advisories".**
  Run: `venv/Scripts/python.exe -m pip_audit -r requirements.txt` and `cd frontend && npm audit --omit=dev --audit-level=high`
  - CI fails on advisories not listed with `--ignore-vuln <ID>`.
  - Each ignored ID gets a one-line reason in the guide.
  - Upgrading a dependency is not part of Batch 0. Note it for Batch 6.

- [ ] **Step 3: Edit `ci.yml`.**
  - In `backend-tests`, replace the test step with `coverage run manage.py test --noinput --verbosity 2` followed by `coverage report --skip-covered | tail -40`. No floor yet; the first green run sets it in Batch 7.
  - Add `bandit -r apps core config -x apps/tests,*/migrations -ll -b apps/tests/security/bandit-baseline.json` and `pip-audit -r requirements.txt <ignore flags>`.
  - In `frontend-build`, add `npm audit --omit=dev --audit-level=high` after `npm ci`.

- [ ] **Step 4: Write `docs/security/TEST_SUITE.md`.** Cover:
  - how to run the suite and the security package
  - what a baseline is, and the rule that only owner-reviewed edits add lines
  - `SECURITY_BASELINE_PRUNE=1`
  - `PENDING.md` and `@pending`
  - the classification rules from Task 4
  - the role sweep's wall time
  - the table of baselines → owning batch → current entry count

- [ ] **Step 5: Run the whole backend suite. Expect the same pass/fail as before Batch 0, plus the new security tests passing.**
  Run: `venv/Scripts/python.exe manage.py test --noinput -v 1 > scratch/full_suite_batch0.txt 2>&1`
  - Compare its failures with a run of the untouched suite (Step 0 of execution: run once before starting Task 1 and save the result as `scratch/full_suite_before.txt`).
  - Any failure that isn't in both runs is a regression from this batch: fix it.

- [ ] **Step 6: Batch summary to owner.** Cover:
  - per-baseline entry counts (the real hole inventory)
  - any surprises versus the inventory doc
  - wall times
  - the proposed Batch 1 plan headline

  No commit unless asked.
