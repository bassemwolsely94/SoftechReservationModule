# Crews (الأطقم) piece 2a — foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dated job/branch history on `hr.Employee`, a new `apps/crews` app (crew, dated rules, dated manual members, one resolver), its API and `/crews` «الأطقم» screen, and the «بائع غير محدد» per-branch share of sales with no named seller.

**Architecture:** `EmployeeAssignment` rows (append-only, dated) are written by the payroll import and a go-live seed command. `apps/crews/membership.py` is the only place membership is derived: rule matches on a person's assignment on a date, plus manual includes, minus manual excludes. Edits end-date rows, never change a row's dates retroactively. A DRF API under `/api/crews/` (RBAC module `crews`, view/edit, admin by default) serves a React page.

**Tech Stack:** Django/DRF, PostgreSQL, React/Vite + TanStack Query, Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-13-branch-classification-and-crews-design.md` (§2, §3, §4, §6.1–6.5, §6.8, §9, §10). Owner-approved; do not re-open decisions.

## Global Constraints

- Name is «طاقم / Crew» (plural «الأطقم»). Never "group" in UI text or code names.
- Crew = who, branch = where. Members are PEOPLE (`hr.Employee`), or a bare SOFTECH user code / PBX extension flagged «خارج كشف الرواتب».
- Sales credit = `PurchaseHistory.softech_user` (SOFTECH `stktransm.usercode`), never `cashiercode`.
- No SOFTECH reads or writes in this piece (only local mirrors: `PurchaseHistory`, `ERPUser`, `ErpUserGroup`).
- Do NOT edit `apps/forecasting/*`, `apps/branches/*`, `apps/purchasing/*`, `apps/catalog/*`, `apps/sync/tasks.py`, `apps/tests/security/static_scan.py` (piece 1 is changing them). Live branches = `Branch.objects.filter(kind__in=['hq', 'retail'])` (put this in ONE helper `apps/crews/branches.py::live_branches()` so piece 1's `.live()` replaces one line).
- Dates: every `valid_from` / `valid_to` is an inclusive `DateField`; `valid_to=None` = open. "Apply from D" = end the old row at `D - 1 day`, start the new one at `D`.
- Membership edits through the API may not take effect before the first day of the current month (closed months never change). Error text: «لا يمكن تطبيق تغيير قبل أول الشهر الحالي — الشهور السابقة مقفلة.»
- Every change is audited: `AuditLog.log(action, user=profile, obj=crew, old_data=..., new_data=..., extra={...})`, action strings ≤ 40 chars, prefix `crew_` (AuditLog.action choices are not enforced; no audit migration).
- Tests: always `TEST_DB_NAME=test_crews_<n>`, `--keepdb`, single focused modules, never `--parallel`, never the full suite or the security sweeps. Python: `../../../venv/Scripts/python.exe` from the worktree root.
- UI calm: no modals for common actions; sortable grids (`useSortableRows` + `components/SortTh`); `useHelpTab(tab)`; branch labels via the existing branch-label helper (never a bare code).

## Review Focus

1. An edit made today must not change `members(crew, any date before the first of this month)` — pin with a test that snapshots `members_between` for last month, edits, and compares.
2. An `Employee` who left (`end_date` set or `status='left'` with `end_date`) must drop out after `end_date` even if their open assignment still matches.
3. A manual include for a bare user code that equals an existing `Employee.softech_usercode` must resolve to that employee (one person, not two rows) — API stores the employee FK.
4. Same-day double import with different job titles must not leave two open assignments (unique open row constraint) and must not produce a `valid_to < valid_from` row.
5. «بائع غير محدد»: blank `softech_user` counts as unattributed; returns (`doc_code='30'`) are excluded; a branch with zero sales shows 0 % not a division error.

---

### Task 1: Employee assignment history + PBX extensions

**Files:**
- Modify: `apps/hr/models.py` (Employee: add `pbx_extensions`; new `EmployeeAssignment`)
- Create: `apps/hr/migrations/0012_employee_assignment_pbx_extensions.py`
- Create: `apps/hr/assignments.py`
- Modify: `apps/hr/attendance/employee_import.py` (`apply(preview, user=None, on=None)`)
- Create: `apps/hr/management/commands/seed_employee_assignments.py`
- Modify: the HR employee serializer/endpoint that edits an employee (find it under `apps/hr/attendance/views.py`; if one exists, expose `pbx_extensions` read/write with validation; if none, expose it read-only on the list)
- Test: `apps/tests/test_hr_employee_assignments.py`

**Interfaces:**
- Produces:
  - `Employee.pbx_extensions = JSONField(default=list, db_default=[] , blank=True)` — list of digit strings.
  - `EmployeeAssignment(employee FK related_name='assignments', job_title str, branch FK Branch null related_name='+', department str, section str, valid_from date, valid_to date|None, source in {'seed','import','manual'}, created_at, created_by FK StaffProfile null)`; constraints: one open row per employee (`UniqueConstraint(fields=['employee'], condition=Q(valid_to__isnull=True), name='uniq_open_employee_assignment')`), `CheckConstraint(valid_to IS NULL OR valid_to >= valid_from)`; index `(employee, valid_from)`.
  - `apps/hr/assignments.py`:
    - `SEED_EPOCH = date(2020, 1, 1)`
    - `TRACKED = ('job_title', 'branch_id', 'department', 'section')`
    - `record_assignment(employee, *, on: date, source: str, user=None) -> EmployeeAssignment | None` — no open row → create one from `employee.start_date or SEED_EPOCH`; open row equal on TRACKED → `None`; differs and open row's `valid_from == on` → update that row in place (same-day correction); differs otherwise → close open row at `on - 1 day`, create new row from `on`. Returns the created/updated row.
    - `assignment_on(employee_id: int, d: date) -> EmployeeAssignment | None`
    - `validate_extensions(values) -> list[str]` — strips, drops blanks/duplicates, each must match `^\d{2,8}$`, else `ValidationError('رقم داخلي غير صالح: <v>')`.
  - Import: after each `update_or_create`, `record_assignment(emp, on=on or timezone.localdate(), source='import', user=user)`; result dict gains `'assignments_changed': int`.
  - Command `seed_employee_assignments [--dry-run]`: for every Employee with no assignment rows, `record_assignment(..., source='seed')`; prints counts; idempotent.

Decision recorded (builder call, spec §6.2/§6.8): department/section changes also open a new row, because crew rules may match on them; without it a section-based crew would use a stale section.

- [ ] **Step 1: Write failing tests** in `apps/tests/test_hr_employee_assignments.py` (TestCase; build Employees directly and via `employee_import.apply` with an `ImportPreview` built in code):
  - `test_first_import_opens_row_from_start_date_or_epoch` — employee with `start_date=2023-05-01` → row valid_from 2023-05-01, valid_to None; one without → `SEED_EPOCH`.
  - `test_reimport_unchanged_writes_nothing` — apply twice same preview → 1 row; result `assignments_changed == 0` on 2nd.
  - `test_job_change_closes_previous_day_and_opens_new` — apply with `on=2026-11-13` job A, then `on=2026-12-01` job B → rows (A, …, 2026-11-30), (B, 2026-12-01, None).
  - `test_branch_change_and_section_change_each_open_row`.
  - `test_same_day_change_corrects_in_place` — two applies `on` same date with different job → 1 row, job = second, no `valid_to < valid_from`.
  - `test_assignment_on_picks_row_covering_date`.
  - `test_seed_command_idempotent` — `call_command('seed_employee_assignments')` twice → one row per employee.
  - `test_validate_extensions` — `[' 201', '201', '', '33']` → `['201','33']`; `'12a'` raises.
  - `test_import_audit_extra_has_assignments_changed`.
- [ ] **Step 2: Run** `TEST_DB_NAME=test_crews_1 ../../../venv/Scripts/python.exe manage.py test apps.tests.test_hr_employee_assignments --keepdb` → FAIL (import errors).
- [ ] **Step 3: Implement** models, migration (`makemigrations hr`, rename to the file above), `assignments.py`, import change, command, serializer field.
- [ ] **Step 4: Run** the new module plus `apps.tests.test_hr_attendance_import` (regression) → PASS.
- [ ] **Step 5: Commit** `feat(hr): dated employee assignment history + PBX extensions`.

---

### Task 2: `apps/crews` models + resolver

**Files:**
- Create: `apps/crews/__init__.py`, `apps.py` (`CrewsConfig`, verbose «الأطقم»), `models.py`, `membership.py`, `branches.py`, `admin.py` (read-only registration), `migrations/0001_initial.py`
- Modify: `config/settings.py` INSTALLED_APPS (`'apps.crews',  # الأطقم — dated cross-branch people groupings (spec 2026-11-13 §6)`)
- Test: `apps/tests/test_crews_membership.py`

**Interfaces:**
- Consumes: `EmployeeAssignment`, `assignment_on`, `Employee.pbx_extensions` (Task 1).
- Produces (`apps/crews/models.py`):
  - `Crew(name ≤120, type in TYPE_CHOICES=[('call_center','كول سنتر'),('job','وظيفي'),('custom','مخصص')], description text blank, is_archived bool, created_by/updated_by FK StaffProfile null, created_at, updated_at)`; `UniqueConstraint(Lower('name'), condition=Q(is_archived=False), name='uniq_live_crew_name')`. Method `has_history() -> bool` = any rule or manual row (not voided) with `valid_from < today` (2b adds rollup references here).
  - Shared abstract `DatedRow`: `valid_from date`, `valid_to date|None`, `created_by/at`, `ended_by FK null`, `ended_at null`, `voided_at null`, `voided_by FK null`; `CheckConstraint(valid_to IS NULL OR valid_to >= valid_from)`.
  - `CrewRule(DatedRow)`: `crew FK related_name='rules'`, `job_titles JSON list`, `branches M2M Branch related_name='+' blank`, `departments JSON list`, `sections JSON list`, `note`.
  - `CrewManualMember(DatedRow)`: `crew FK related_name='manual_members'`, `mode in [('include','إضافة'),('exclude','استبعاد')]`, `employee FK null`, `softech_usercode ≤20 blank`, `pbx_extension ≤10 blank`, `label ≤120 blank` (name for off-payroll), `reason ≤255 required`; `CheckConstraint(employee IS NOT NULL OR softech_usercode <> '' OR pbx_extension <> '')`.
  - `apps/crews/branches.py::live_branches() -> QuerySet[Branch]` = `Branch.objects.filter(kind__in=['hq','retail'])` with a comment "piece 1 swaps this for Branch.objects.live()".
- Produces (`apps/crews/membership.py`):
  - `@dataclass(frozen=True) Member(key: tuple, employee_id: int|None, name: str, hr_number: str, job_title: str, branch_id: int|None, softech_usercodes: tuple[str,...], extensions: tuple[str,...], staff_id: int|None, off_payroll: bool, source: str)` — `key = ('emp', id)` or `('code', usercode)` / `('ext', extension)`; `source` in `'rule' | 'manual'`.
  - `members(crew, d: date) -> list[Member]` sorted by name.
  - `members_between(crew, start: date, end: date) -> dict[tuple, list[tuple[date, date]]]` — inclusive spans clipped to [start, end], adjacent spans merged.
  - `identities(crew, start, end) -> list[Identity]`; `@dataclass(frozen=True) Identity(kind: 'softech_user'|'extension'|'staff', value: str, valid_from: date, valid_to: date, member_key: tuple)`.
  - `preview(rules: list[dict], d: date, crew=None) -> list[Member]` — unsaved rule dicts (`job_titles, branch_ids, departments, sections`) + the crew's active manual rows on `d` when `crew` is given.
  - Rule semantics: a rule is active on D when `valid_from <= D <= (valid_to or ∞)` and not voided; a person matches when their assignment on D matches every NON-EMPTY set (empty set = any); an all-empty rule matches nobody (guard against "everyone" by accident). Person must be employed on D: `start_date is None or start_date <= D`, and `end_date is None or D <= end_date`. Membership = (rule matches ∪ includes) − excludes. An exclude row matches an employee by FK, or a bare include by the same usercode/extension, or an employee whose `softech_usercode` equals it.
  - `members_between` algorithm: collect change points (each row's `valid_from` and `valid_to + 1`, each assignment's, each employee's `start_date` and `end_date + 1`) inside (start, end]; evaluate membership at `start` and every change point using data loaded ONCE (no per-day queries); build spans. Query count must not grow with the number of days.

- [ ] **Step 1: Write failing tests** `apps/tests/test_crews_membership.py` (TestCase; helper makes Employees with assignments via `record_assignment` and Branches with `kind='retail'`):
  - `test_rule_matches_job_and_branch` — pharmacist@130 in, pharmacist@140 out when rule branches={130}, cashier@130 out.
  - `test_empty_sets_are_wildcards_but_all_empty_rule_matches_nobody`.
  - `test_rule_with_several_job_titles`.
  - `test_department_and_section_sets`.
  - `test_assignment_change_splits_span` — job changes on 2026-10-15 → `members_between(Oct)` gives `[(10-01, 10-14)]`.
  - `test_left_employee_drops_after_end_date`.
  - `test_manual_include_off_payroll_usercode` — `Member.off_payroll is True`, key `('code','777')`, `softech_usercodes == ('777',)`.
  - `test_manual_exclude_only_inside_its_dates`.
  - `test_exclude_by_usercode_removes_matching_employee`.
  - `test_ended_rule_stops_at_valid_to_and_voided_row_ignored`.
  - `test_replacing_rule_from_d_keeps_earlier_membership` (Review Focus 1) — snapshot `members_between(crew, Oct)`, end rule at Nov-30 and add new rule from Dec-01 → October unchanged.
  - `test_identities_carry_codes_extensions_staff_with_spans`.
  - `test_members_between_query_count_independent_of_range` — `assertNumQueries` equal for a 31-day and a 365-day range.
  - `test_preview_uses_unsaved_rules_and_crew_manual_rows`.
  - `test_crew_name_unique_among_live_only` — archived duplicate allowed.
- [ ] **Step 2: Run** `TEST_DB_NAME=test_crews_2 ../../../venv/Scripts/python.exe manage.py test apps.tests.test_crews_membership --keepdb` → FAIL.
- [ ] **Step 3: Implement** app, models, migration (`makemigrations crews`), resolver.
- [ ] **Step 4: Run** → PASS. Also `manage.py makemigrations --check --dry-run` shows no pending changes.
- [ ] **Step 5: Commit** `feat(crews): crew, dated rules and manual members, membership resolver`.

---

### Task 3: RBAC module `crews`, API, audit, «بائع غير محدد»

**Files:**
- Modify: `apps/users/models.py` (MODULE_CHOICES += `('crews', 'الأطقم')`)
- Create: `apps/users/migrations/0057_crews_module.py` (AlterField choices + explicit rows for every role × action; GRANTS = admin all, nobody else — copy the 0055 pattern)
- Modify: `apps/users/management/commands/seed_permissions.py` (ALL_MODULES += `'crews',  # الأطقم: 'view' = list/members/history/unattributed sales, 'edit' = create/change/end rows/archive; admin only by default`)
- Modify: `apps/tests/security/permission_matrix.py` (BRANCH_SCOPE `'crews': 'all — company-level by design (spec 2026-11-13 §10): crews group people across branches; admin only by default'`), regenerate `docs/security/PERMISSION_MATRIX.md` with the command in that file's docstring
- Modify: `apps/tests/security/test_rbac_accountant.py` (add `'crews'` to the "added since 0051" set, with a comment)
- Modify: `core/middleware/module_access.py` (`MODULE_BY_PREFIX['crews'] = 'crews'`)
- Modify: `config/urls.py` (`path('api/crews/', include('apps.crews.urls'))`)
- Create: `apps/crews/serializers.py`, `apps/crews/services.py`, `apps/crews/unattributed.py`, `apps/crews/views.py`, `apps/crews/urls.py`
- Test: `apps/tests/test_crews_api.py`

**Interfaces:**
- Consumes: Task 2 models + `members`, `members_between`, `preview`, `live_branches`.
- `apps/crews/services.py` (all writes go here, each in `transaction.atomic`, each audited):
  - `check_effective(d: date)` → raises `ValidationError(<Global Constraints text>)` when `d < first day of current month`.
  - `create_crew(data, user) -> Crew` (`crew_created`), `update_crew(crew, data, user)` (`crew_updated`, name/type/description only), `remove_crew(crew, user) -> str` → `'deleted'` when `not crew.has_history()` (`crew_deleted`, rows deleted) else `'archived'` (`crew_archived`); `unarchive_crew` (`crew_unarchived`, refuses when a live crew has the same name).
  - `add_rule(crew, data, user) -> CrewRule` (`crew_rule_added`), `end_rule(rule, on: date, user)` (`crew_rule_ended`; sets `valid_to = on - 1`; if `rule.valid_from >= on` the row never applied → set `voided_at/by` instead, `crew_rule_voided`), `replace_rule(rule, data, on, user) -> CrewRule` (end + add in one transaction, `crew_rule_replaced`).
  - `add_manual(crew, data, user) -> CrewManualMember` (`crew_member_added`) — when only `softech_usercode` is given and an Employee has that `softech_usercode`, store the employee FK (Review Focus 3); `end_manual(row, on, user)` (same end/void rule, `crew_member_ended`).
  - Every audit call: `obj=crew`, `extra={'crew_id', 'row': 'rule'|'manual'|None, 'row_id'}`, `old_data`/`new_data` dicts of the changed row.
- Endpoints (`apps/crews/views.py`; permission `[IsAuthenticated, matrix_permission('crews', post=('edit',), delete=('edit',))]` — the module has only view/edit):
  - `GET /api/crews/?archived=1` → `[{id, name, type, type_label, description, is_archived, member_count, last_change}]` (`member_count` = `len(members(crew, today))`).
  - `POST /api/crews/` create · `GET/PATCH/DELETE /api/crews/<id>/` (DELETE → `{'result': 'deleted'|'archived'}`) · `POST /api/crews/<id>/unarchive/`.
  - `GET /api/crews/<id>/` detail adds `rules` (all rows, newest first, with `branch_ids`, `branch_labels`, `status` in active/ended/future/voided) and `manual` (same + `off_payroll`).
  - `GET /api/crews/<id>/members/?date=YYYY-MM-DD` → Member rows (+ `branch_label`).
  - `GET /api/crews/<id>/history/?start&end` (default: last 12 months) → `{'spans': [{key, name, off_payroll, from, to}], 'changes': [AuditLog rows for obj=crew: at, user_name, action, action_label, old_data, new_data, note]}`.
  - `POST /api/crews/<id>/rules/` · `POST /api/crews/<id>/rules/<rid>/end/ {on}` · `POST /api/crews/<id>/rules/<rid>/replace/ {..., on}`.
  - `POST /api/crews/<id>/manual/` · `POST /api/crews/<id>/manual/<mid>/end/ {on}`.
  - `POST /api/crews/preview/ {rules: [...], date?, crew_id?}` (edit) → Member rows.
  - `GET /api/crews/options/` → `{job_titles, departments, sections}` (distinct non-blank values from open `EmployeeAssignment` rows ∪ `Employee` current fields, sorted), `branches: [{id, code, label}]` from `live_branches()`, `employees: [{id, hr_number, name, job_title, branch_id, softech_usercode, pbx_extensions, status}]`.
  - `GET /api/crews/unattributed-sales/?start&end` (default: first of current month → today) and `GET/PUT /api/crews/unattributed-sales/config/` (PUT = edit, audited `crew_generic_sellers_set`).
- `apps/crews/unattributed.py`:
  - `SETTING_KEY = 'crews.generic_sellers'`; `DEFAULT_RULE = {'groups': ['17'], 'usercodes': []}` (SOFTECH user group 17 = cashier stations, spec §6.8). Stored as a `SystemSetting` json row (create on first PUT).
  - `generic_rule() -> dict`, `set_generic_rule(groups, usercodes, user)`.
  - `is_generic(code: str, rule: dict, group_of: dict[str, str]) -> bool` — blank code → True; code in `usercodes` → True; `group_of.get(code)` in `groups` → True. `group_of` from `ERPUser.username → user_group`.
  - `unattributed_by_branch(start: date, end: date) -> dict` → `{'rule', 'branches': [{branch_id, label, invoices, amount, unattributed_invoices, unattributed_amount, share}], 'sellers': [{code, name, group, group_name, invoices, amount, generic}]}` over `PurchaseHistory` with `doc_code='115'`, `invoice_date` date in [start, end], branches = `live_branches()` (plus any branch that has rows in range, so nothing silently drops); `share` = unattributed_amount / amount, 0 when amount is 0. `sellers` = top 50 codes by amount across the range, so the owner can mark a code as generic.
- Branch scope: none — company-level, documented in BRANCH_SCOPE. Errors through `core/errors.public_error` where the code catches exceptions.

- [ ] **Step 1: Write failing tests** `apps/tests/test_crews_api.py`:
  - `test_admin_full_flow` — create crew, add rule, preview, members, history contains `crew_created` and `crew_rule_added`.
  - `test_pharmacist_and_supervisor_refused_view_and_edit` (403) and `test_anonymous_401`.
  - `test_role_granted_view_only_cannot_edit` — grant `RoleModuleAccess(role='supervisor', module='crews', action='view')` → GET 200, POST 403.
  - `test_effective_date_before_month_start_refused` (400 with the Arabic text).
  - `test_end_rule_sets_previous_day_and_future_row_voided`.
  - `test_delete_unused_crew_deletes_used_crew_archives` (row with valid_from yesterday → archived; name reusable for a new live crew).
  - `test_manual_usercode_matching_employee_stores_fk`.
  - `test_options_lists_new_job_title_and_live_branches_only` — a new job title appears without code change; a `kind='closed'` branch is absent.
  - `test_unattributed_sales_share` — blank seller + group-17 seller + named seller at one branch; return `doc_code='30'` ignored; branch with no sales has share 0.
  - `test_generic_config_put_audited_and_used`.
  - `test_module_mapped_and_matrix_migration_agree` — `MODULE_BY_PREFIX['crews'] == 'crews'`; `'crews' in ALL_MODULES`; migration 0057 GRANTS admin-only equals `{r for r in PERMISSIONS if PERMISSIONS[r].get('crews')} == set()` plus admin.
- [ ] **Step 2: Run** `TEST_DB_NAME=test_crews_3 ../../../venv/Scripts/python.exe manage.py test apps.tests.test_crews_api --keepdb` → FAIL.
- [ ] **Step 3: Implement** the files above; regenerate PERMISSION_MATRIX.md.
- [ ] **Step 4: Run** `apps.tests.test_crews_api apps.tests.test_crews_membership apps.tests.security.test_permission_matrix apps.tests.security.test_rbac_accountant` (one command, serial) → PASS.
- [ ] **Step 5: Commit** `feat(crews): API, RBAC module crews, audit, unattributed-seller share`.

---

### Task 4: `/crews` screen «الأطقم» + in-app help

**Files:**
- Create: `frontend/src/pages/CrewsPage.jsx`, `frontend/src/pages/crews/CrewList.jsx`, `CrewEditor.jsx` (name/type/description + rules + manual rows + live preview), `CrewMembers.jsx`, `CrewHistory.jsx`, `UnattributedSales.jsx`
- Modify: `frontend/src/api/client.js` (`crewsApi`), `frontend/src/App.jsx` (lazy route `crews`), `frontend/src/components/navGroups.js` (entry under the admin/HR group: `{ to: '/crews', icon: '👥', label: 'الأطقم', roles: ['admin'], module: 'crews' }` — follow how existing module-gated entries combine roles+module so a later matrix grant opens it)
- Create: `apps/help/content/crews.py`; Modify: `apps/help/content/__init__.py` (MODULE_FILES, next to `'hr'`), `apps/help/content/hr.py` (one line: the import keeps a dated job/branch history; bump `updated`)
- Test: `apps/tests/test_help.py` (existing — must pass), `npm run build`

**Interfaces:**
- Consumes: Task 3 endpoints exactly as listed.
- Page tabs (keys used by `useHelpTab` and the help file): `crews` «الأطقم» (list + editor of the selected crew below/beside it), `members` «الأعضاء» (date picker, defaults today), `history` «السجل», `unattributed` «بائع غير محدد».
- Behaviour: no modals. Rule pickers are multi-select chips filled from `/options/`; every picker change calls `/preview/` (debounced 400 ms) and shows the matching people count and list. Effective-date input defaults to today with `min` = first of current month (server still decides). Manual add: search employees by name/HR number/user code, or switch to «خارج كشف الرواتب» and type a user code and/or extension plus a label; reason required. Ended/voided rows stay visible, greyed, with their dates. Delete button says «حذف / أرشفة» and shows the server's answer. Off-payroll members carry a «خارج كشف الرواتب» badge. Unattributed tab: per-branch grid (invoices, amount, unattributed amount, share %) and a sellers grid with a «حساب عام» checkbox per code (edit permission only; PUT config then refetch). All grids sortable; review-grid keyboard (`useGridKeyboard`) on the members and sellers grids. Edit controls hidden without `crews` edit (server enforces anyway). `data-help-target` attributes on: `crews-list`, `crews-editor-rules`, `crews-editor-preview`, `crews-editor-manual`, `crews-members-grid`, `crews-history`, `crews-unattributed-branches`, `crews-unattributed-sellers`.
- Help file `crews.py`: key `crews`, group as the HR/admin group used by `hr.py`, title «الأطقم» / "Crews", summary explaining crew = who / branch = where, dated membership, edits apply from a date and never change closed months, off-payroll badge, «بائع غير محدد» meaning (sales whose seller is a cashier-station / generic account; fixing it is an operations matter); one `screens` entry `crews.main` route `/crews` with the four tabs; one flow; `updated: '2026-11-13'`. Mirror the structure of `apps/help/content/data_health.py` exactly and satisfy every check in `apps/tests/test_help.py`.

- [ ] **Step 1:** Create `frontend/node_modules` junction to the main checkout's `frontend/node_modules` (`cmd /c mklink /J`), confirm `npm run build` runs on the untouched tree.
- [ ] **Step 2:** Write the help file + MODULE_FILES entry; run `TEST_DB_NAME=test_crews_4 ../../../venv/Scripts/python.exe manage.py test apps.tests.test_help --keepdb` → FAIL until the route exists (route-without-help / help-without-route checks).
- [ ] **Step 3:** Implement the page, components, client, route, nav entry.
- [ ] **Step 4:** `npm run build` (in `frontend/`) → succeeds; `apps.tests.test_help` → PASS; `npm run lint` on the new files if the project has lint configured.
- [ ] **Step 5:** Commit `feat(crews): /crews screen «الأطقم» + in-app help`.

---

### Task 5: Verification + PR

- [ ] Run serially, one command: `TEST_DB_NAME=test_crews_5 ../../../venv/Scripts/python.exe manage.py test apps.tests.test_hr_employee_assignments apps.tests.test_hr_attendance_import apps.tests.test_crews_membership apps.tests.test_crews_api apps.tests.test_help apps.tests.security.test_permission_matrix apps.tests.security.test_rbac_accountant --keepdb` → all PASS.
- [ ] `manage.py makemigrations --check --dry-run` → "No changes detected".
- [ ] `manage.py check` → no issues.
- [ ] Check the canary planter can build the crews models: `manage.py shell -c "from apps.tests.security import canary; ..."` (see its `plant`/`skipped` API) — `CrewRule`/`CrewManualMember` not in skipped (they have no direct Branch FK; confirm whether they are even branch-linked and note it).
- [ ] Push branch, open PR to `main` (do not merge). PR body: what/why, migrations (`hr 0012`, `crews 0001`, `users 0057` — main session renumbers if piece 1 lands a users migration first), decisions made (dept/section trigger rows; month-start edit floor; void-instead-of-end for not-yet-started rows; generic seller rule default group 17), what's out of scope (2b), go-live step `manage.py seed_employee_assignments`.
