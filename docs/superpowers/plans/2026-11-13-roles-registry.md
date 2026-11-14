# Roles Registry (piece 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One permission-role registry (keys + Arabic/English labels + role attributes) that the backend derives every role constant from and the frontend reads through an API, so a new role is one registry line, shows with its label everywhere, and fails closed by default.

**Architecture:** `apps/users/roles.py` holds a tuple of frozen `Role` records; `ROLE_CHOICES`, `MFA_REQUIRED_ROLES`, `core.branch_scope.ALL_BRANCH_ROLES` and the RBAC "always enforced" set are derived from it. `GET /api/auth/roles/` serves it; a React hook `useRoles()` replaces the 7 frontend label tables. A ratchet guard (`apps/tests/security/role_literals.py` + two baselines) blocks new literal role lists in Python and JS.

**Tech Stack:** Django 5 / DRF, React 18 + @tanstack/react-query + vitest, PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-11-13-branch-classification-and-crews-design.md` §2 (Roles), §7 piece 3, §8, §10.

## Global Constraints

- Permission roles (`StaffProfile.role`) are NOT job titles (job titles = HR payroll list). Never mix.
- Behaviour identical for the 10 existing roles: no role × route sweep baseline line may change; `RBAC_ENFORCED_ROLES` semantics for existing roles unchanged. If a change would alter either → stop, report to the controller (owner decision).
- `ROLE_CHOICES` tuples keep their exact current `(key, English description)` values → **no migration** (`makemigrations --check` stays clean).
- Do NOT edit existing functions/sections of `apps/tests/security/static_scan.py` (piece 1 is editing it); the role guard lives in its own new module + test + baseline files.
- Tests: `TEST_DB_NAME=test_roles_<n>`, focused modules, `--keepdb`, never `--parallel`. Python = `../../../venv/Scripts/python.exe` from the worktree root. Frontend tests: `cd frontend && npx vitest run <file>` (node_modules is a junction).
- UI copy Arabic first; «سيرفر» not «خادم»; no new popups.
- Commit after each task; messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A role key in the DB that is not in the registry (stale data) → treated as enforced/fail-closed, label shown as the raw key, nothing crashes (Task 2, Task 3 tests).
2. `RBAC_ENFORCED_ROLES` env override (`'accountant, viewer'`, `()`) still behaves exactly as today for existing roles (Task 2 keeps `test_accountant_exempt_paths` green).
3. Roles API not loaded yet / failed → screens render keys, dropdowns still usable (Task 4 hook test).
4. Permission-matrix screen `roles` list must still exclude `admin` (Task 3 test).
5. Guard must not flag the registry itself nor tests/migrations (Task 6 unit tests).

---

### Task 1: Backend role registry

**Files:**
- Create: `apps/users/roles.py`
- Modify: `apps/users/models.py:5-16` (ROLE_CHOICES → import), `:111` (MFA_REQUIRED_ROLES → import), `core/branch_scope.py:17` (ALL_BRANCH_ROLES → derived)
- Test: `apps/users/tests/test_roles_registry.py` (create; check where users tests live, follow that location)

**Interfaces — Produces:**
```python
@dataclass(frozen=True)
class Role:
    key: str; label_ar: str; label_en: str; description: str   # description = current ROLE_CHOICES text
    all_branches: bool = False        # sees every branch (core.branch_scope)
    mfa_required: bool = True         # new roles default to 2FA (fail closed)
    legacy_rbac_mode: bool = False    # True = follows RBAC_ENFORCEMENT (log/enforce) as today;
                                      # False = matrix always enforced (new roles)
ROLES: tuple[Role, ...]               # order = current ROLE_CHOICES order
ROLE_KEYS: tuple[str, ...]
ROLE_CHOICES: list[tuple[str, str]]   # [(key, description)] — byte-identical to today
ROLE_BY_KEY: dict[str, Role]
ALL_BRANCH_ROLES: tuple[str, ...]     # keys with all_branches, registry order
MFA_REQUIRED_ROLES: frozenset[str]
LEGACY_RBAC_ROLES: frozenset[str]
def role_label(key: str, lang: str = 'ar') -> str   # unknown key → the key itself
def is_known(key: str) -> bool
def as_api() -> list[dict]   # [{'value','label_ar','label_en','description'}] in registry order
```
Values (copy exactly): Arabic labels — admin «مدير النظام», call_center «كول سنتر», pharmacist «صيدلاني», salesperson «مندوب مبيعات», purchasing «مشتريات», delivery «توصيل», viewer «مشاهد فقط», supervisor «مشرف», quality_manager «مدير الجودة», accountant «محاسب». English — Admin, Call center, Pharmacist, Salesperson, Purchasing, Delivery, Viewer, Supervisor, Quality manager, Accountant. `all_branches` = admin, call_center, purchasing, supervisor, quality_manager, accountant (= today's `ALL_BRANCH_ROLES`, same order). `mfa_required` True only for admin, supervisor, purchasing (today's set) — every existing role sets it explicitly. `legacy_rbac_mode=True` for all 10 existing roles (accountant included: whether it is enforced keeps coming from `RBAC_ENFORCED_ROLES`).

- [ ] **Step 1: failing tests** — `test_role_choices_unchanged` (assert `ROLE_CHOICES` equals the literal current list copied from models.py:5-16), `test_all_branch_roles_unchanged` (`== ('admin','call_center','purchasing','supervisor','quality_manager','accountant')`), `test_mfa_roles_unchanged` (`== frozenset({'admin','supervisor','purchasing'})`), `test_every_role_has_labels` (non-empty ar/en), `test_unknown_role_label_is_key` (`role_label('zzz') == 'zzz'`), `test_new_role_defaults_fail_closed` (`Role('x','x','x','x')` → all_branches False, mfa_required True, legacy_rbac_mode False), `test_models_reexport` (`apps.users.models.ROLE_CHOICES is roles.ROLE_CHOICES`, `core.branch_scope.ALL_BRANCH_ROLES == roles.ALL_BRANCH_ROLES`).
- [ ] **Step 2:** run, expect ImportError.
- [ ] **Step 3:** implement `roles.py`; in `models.py` replace the literal with `from .roles import ROLE_CHOICES, MFA_REQUIRED_ROLES  # noqa: F401 — re-exported, the registry is the source` (keep names importable); in `branch_scope.py` `from apps.users.roles import ALL_BRANCH_ROLES` — check for import cycles (`apps.users.roles` must import nothing from Django models).
- [ ] **Step 4:** run tests + `python manage.py makemigrations --check --dry-run` → "No changes detected".
- [ ] **Step 5:** commit `feat(users): role registry — one source for role keys, labels and attributes`.

### Task 2: A new role fails closed in RBAC

**Files:**
- Modify: `core/middleware/module_access.py` (`enforced_roles`, `_mode_for`, `matrix_enforced_for`, line ~486), `core/permissions.py:124`, `apps/offers/permissions.py:23`
- Test: `apps/tests/security/test_rbac_new_role.py` (create)

**Interfaces:**
- Consumes: `roles.LEGACY_RBAC_ROLES`, `roles.is_known`.
- Produces: `module_access.is_enforced(role: str | None) -> bool` = `role in enforced_roles()` or role is not a legacy-mode registry role (unknown/None-but-profile roles included). `enforced_roles()` now returns configured set ∪ registry keys with `legacy_rbac_mode=False` (so `.exclude(role__in=enforced_roles())` queries in replacement/supply keep working). Every `x in enforced_roles()` membership test in the files above becomes `is_enforced(x)`. Migrations are not touched.

- [ ] **Step 1: failing tests** (patch `apps.users.roles.ROLES`/derived sets via a helper context manager that adds `Role('night_cashier', 'كاشير ليلي', 'Night cashier', 'Night cashier')`, or monkeypatch `LEGACY_RBAC_ROLES`; pick one and document it in the test):
  - `test_new_role_enforced_in_log_mode`: `RBAC_ENFORCEMENT='log'` → `_mode_for('night_cashier') == 'enforce'`; `_mode_for('pharmacist') == 'log'`.
  - `test_unknown_db_role_enforced`: `is_enforced('legacy_garbage')` True.
  - `test_new_role_unseeded_module_denied`: profile with role night_cashier, no rows for module `'catalog'` → `matrix_allows(profile,'catalog','view')` False; same with pharmacist → True (unchanged fail-open).
  - `test_new_role_rows_do_not_seed_module`: a RoleModuleAccess row for night_cashier on a module does not put it in `seeded_modules()`.
  - `test_existing_roles_unchanged`: for each existing key, `is_enforced(k) == (k in configured RBAC_ENFORCED_ROLES)` under `override_settings(RBAC_ENFORCED_ROLES='accountant')` and `=()`.
- [ ] **Step 2:** run, expect failures.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** run new test + `test_accountant_exempt_paths test_rbac_accountant test_rbac_matrix_seeding test_rbac_middleware_gaps test_rbac_offers` → all pass.
- [ ] **Step 5:** commit `feat(rbac): a role outside the registry's legacy set is always matrix-enforced`.

### Task 3: Roles API + permission-matrix roles from the registry

**Files:**
- Modify: `apps/users/views.py` (add `roles_view`; matrix `list` at ~line 740 builds `roles` from the registry), `apps/users/auth_urls.py` (`path('roles/', roles_view)`), `apps/tests/security/baselines/open_to_all_staff.txt` (add `GET /api/auth/roles/  [-]` under the existing auth reason line, extend that reason with "role names and labels")
- Test: `apps/users/tests/test_roles_api.py`

**Interfaces — Produces:** `GET /api/auth/roles/` (IsAuthenticated) → `{"roles": [{"value","label_ar","label_en","description"}, …]}` in registry order. Matrix list response: `roles` = `[{'value': k, 'label': label_ar, 'label_en': ...} for registry roles except admin]` — keep key `label` (frontend reads it), now Arabic.

- [ ] **Step 1: failing tests** — anonymous → 401; any staff role (e.g. viewer) → 200 with 10 roles incl. `{'value':'supervisor','label_ar':'مشرف',...}`; matrix list (admin) `roles` excludes admin and includes quality_manager with Arabic label.
- [ ] **Step 2–4:** fail → implement → pass. Check the permission-matrix frontend page still reads `roles[].label` (grep `PermissionMatrix`/`permissionsApi`).
- [ ] **Step 5:** commit `feat(users): /api/auth/roles/ serves the role registry`.

### Task 4: Frontend `useRoles` hook + replace the 7 label tables

**Files:**
- Create: `frontend/src/hooks/useRoles.js`, `frontend/src/hooks/useRoles.test.jsx`
- Modify: `frontend/src/api/client.js` (`authApi.roles: () => api.get('/auth/roles/')`), `pages/UserManagementPage.jsx` (ROLES/ROLE_OPTIONS/RoleBadge from hook; keep ROLE_COLORS, add supervisor/quality_manager/accountant colours), `pages/gamification/labels.js` + `GamificationPage.jsx` + `gamification/ChampionsTab.jsx` (roleLabel from hook; filter options = all registry roles with «كل الأدوار» first), `pages/HelpManualPage.jsx:18-25`, `help/TrainingEditor.jsx:16` (option text = label, accountant now included), `pages/AnnouncementsPage.jsx:10`, `pages/FollowUpsPage.jsx:964` (keep its assignable subset of keys only if the backend restricts assignment; otherwise all roles — check `apps/followups/views.py` assign), `pages/SyncPage.jsx:149-157`
- Delete: `frontend/src/utils/roleLabels.js`, move `roleLabels.test.js` intent into `useRoles.test.jsx`

**Interfaces — Produces:**
```js
// useRoles() → { roles: [{value,label_ar,label_en,description}], roleLabel(key, lang='ar') → string, isLoading }
// react-query key ['roles'], staleTime: Infinity; roleLabel falls back to the key while loading / unknown.
```
- [ ] **Step 1: failing test** `useRoles.test.jsx`: mock `authApi.roles` → roles incl. supervisor & quality_manager; `roleLabel('supervisor') === 'مشرف'`, `roleLabel('supervisor','en') === 'Supervisor'`, `roleLabel('zzz') === 'zzz'`; before resolve `roleLabel('admin') === 'admin'`. Plus a UserManagement dropdown test if the page renders in jsdom with mocked APIs (render `UserDrawer` or the page; assert `<option value="quality_manager">`); if the page is too heavy to render, export a tiny pure `roleOptions(roles)` helper and test it.
- [ ] **Step 2–4:** fail → implement → `npx vitest run src/hooks src/utils src/components` pass; `grep -rn "ROLE_LABELS\|ROLE_NAMES\|EXTRA_ROLE_LABELS" frontend/src` → nothing.
- [ ] **Step 5:** help: if any help content (`apps/help/content/*.py`) lists the role options of the users screen, add supervisor/QM and bump `updated`; run `apps/tests/test_help.py`.
- [ ] **Step 6:** `cd frontend && npm run build` green; commit `feat(frontend): role labels come from the registry API (7 tables removed)`.

### Task 5: Inline copies of registry groups → registry names

**Files:** backend sites whose literal list equals a registry-derived group (`ALL_BRANCH_ROLES`, `MFA_REQUIRED_ROLES`) *with the same meaning* — find with the scan from Task 6 or grep; `apps/batches/return_calendar.py:40` is a different set and stays.
- [ ] Replace each with the registry name, no behaviour change; add `apps/users/tests/test_roles_registry.py::test_no_inline_copy_of_all_branch_roles` only if cheap. Run the tests of each touched app. Commit `refactor: role groups read from the registry`.
- Inline lists that would need a *matrix* check instead: do NOT convert (none found whose list equals the seeded grant set of the same module/action — sweep 2026-11-13: 87 of 120 multi-role lists match some grant set by coincidence only, e.g. `transfers` "admin+purchasing" ≠ `transfers.approve`). Record them in the PR as an owner decision.

### Task 6: Static guard against new literal role lists

**Files:**
- Create: `apps/tests/security/role_literals.py`, `apps/tests/security/test_role_literal_guard.py`, `apps/tests/security/baselines/role_literals_py.txt`, `apps/tests/security/baselines/role_literals_js.txt`
- Modify: `CLAUDE.md` security DoD (one line: "a new role = one line in `apps/users/roles.py`; no literal role lists (role_literals guard)")

**Interfaces — Produces:**
```python
ROLE_KEYS from apps.users.roles
def py_role_literal_sites(tree, path) -> set[str]   # entries "path::Qualname::k1,k2" (sorted keys)
def js_role_literal_sites(text, path) -> set[str]   # entries "path::k1,k2"
def repo_py_sites() -> set[str]; def repo_js_sites() -> set[str]   # skip apps/tests/, migrations, apps/users/roles.py, *.test.*
```
Flag (Python, AST via `static_scan.python_files/parse_file/_Scoped` — import, don't modify): (a) a tuple/list/set/frozenset literal of ≥2 strings all in ROLE_KEYS, anywhere; (b) a `Compare` or keyword (`role=`, `role__in=`, any kwarg containing `role`) pairing a role-ish expression (unparsed text contains "role") with a single role key other than `'admin'`. (JS, regex on `frontend/src/**/*.{js,jsx}`): array literals with ≥2 quoted role keys; `role ===/!== '<key>'` with key ≠ admin.
- [ ] **Step 1:** unit tests on snippets: `role in ('admin','supervisor')` flagged as `t.py::f::admin,supervisor`; `role == 'admin'` not flagged; `role == 'viewer'` flagged `t.py::f::viewer`; `ROLES = ['a','b']` (non-role strings) not flagged; JS `roles: ['admin','pharmacist']` flagged; `x === 'admin'` not.
- [ ] **Step 2:** implement; write baselines from the current tree (header comment: ratchet, the list only shrinks; a new role belongs in apps/users/roles.py).
- [ ] **Step 3:** repo tests `test_python_role_literals_match_baseline`, `test_js_role_literals_match_baseline` via `assert_matches_baseline`. Run `apps.tests.security.test_role_literal_guard` + `apps.tests.security.test_static_guards` (suppression counts etc.) pass.
- [ ] **Step 4:** commit `test(security): ratchet guard against new literal role lists`.

### Task 7: New-role end-to-end test

**Files:** Create `apps/tests/test_new_role.py` (not `test_new_values.py` — piece 1 owns that file).
- [ ] Plant `night_cashier` in the registry (same helper as Task 2): `/api/auth/roles/` lists it with its label; a staff user with that role, branch-scoped (`branch_ids` = own branch only), `MFA_REQUIRED` semantics (`mfa_required` True), middleware in `log` mode refuses an unseeded-for-it module route with 403. Commit `test: a new role shows up with its label and fails closed`.

### Task 8: Verification + PR (controller)

- [ ] Focused backend tests of every touched app; `npx vitest run`; `npm run build`.
- [ ] Role × route sweep once, serially, after checking free RAM and confirming no other session is running one: `apps.tests.security.test_role_sweep` → baselines unchanged.
- [ ] PR to main (not merged) with the owner-decision list from Task 5.
