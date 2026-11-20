# HR Attendance Stage 1b — Linked Gates source + work sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Linked Gates as a second, read-only punch source, group punches into work sessions, and show a daily Linked Gates vs ours comparison.

**Architecture:**
- **The agent (`attendance_agent/`):** gains a read-only SQL Server reader for `Linked_ERP_HR_v1`. The reader posts copied rows to new agent endpoints.
- **The server (`apps/hr/attendance/`):** stores them in append-only, versioned models.
- **Day figures:** come from one merged punch list (machine + Linked Gates), grouped by a pure session engine. A second pure function recomputes Linked Gates' own day rules for the comparison.
- **The page:** `HRAttendancePage.jsx` gets one new tab.

**Tech Stack:** Django/DRF, PostgreSQL, React/Vite, Python agent on Windows with `pyodbc` + ODBC Driver 18 for SQL Server.

**Spec:** `docs/superpowers/specs/2026-11-20-hr-attendance-linkedgates-sessions-design.md` (approved 2026-11-20). Stage 1 spec: `docs/superpowers/specs/2026-11-07-hr-attendance-stage1-design.md`.

## Global Constraints

- **Never write to Linked Gates or to a machine.** The agent's SQL is `SELECT` only, from a fixed allow-list of tables and columns. No procedure call, ever.
- **Never read these:** `Employee.Salary`, `Phone`, `Email`, `EmployeeImage`; the `Users` and `UserPermissions` tables; `Device.Password`.
- **Switches:**
  - `HR_ATTENDANCE_ENABLED` stays the master switch.
  - New `HR_ATTENDANCE_LINKEDGATES_ENABLED`, default `False`.
  - New `HR_ATTENDANCE_DAY_SOURCE` (`'linkedgates'` | `'sessions'`), default `'linkedgates'`.
  - New `HR_ATTENDANCE_SESSION_GAP_HOURS`, default `6`.
- **Session rules:**
  - A gap of more than 6 h starts a new session.
  - A session belongs to the date of its first punch, except that a session starting 00:00–03:59 belongs to the previous date.
  - Worked time = sum of consecutive (in, out) pairs. An odd count → `needs_review`, and the unpaired last punch adds no time.
  - Punches within 2 minutes count once (`DUPLICATE_WINDOW_SECONDS = 120`, existing).
- **Per-person cut-off:** `Employee.day_boundary` becomes nullable; null = sessions. A data migration sets every existing `04:00` to null; the office DB has all 55 rows at the default.
- **Linked Gates' rules, exactly as read from its views:**
  - **In:**
    - type 1: MIN punch in 07:00–14:00 on the calendar date
    - type 2: MIN punch in 08:00–21:00
  - **Out:**
    - type 1: MAX punch after 14:00
    - type 2: MAX punch after 21:00
    - **Any type:** a punch between 00:01 and 01:59 counts as an out of the previous date.
  - **Grouping:** per calendar date, and per DeviceID and INOutMode.
  - **NULL ShiftType:** no rows at all.
- **Comparison reason codes:**
  - `lg_night_split`
  - `lg_window_ignored`
  - `lg_out_hidden`
  - `lg_no_shifttype`
  - `lg_multi_in`
  - `missing_punch`
- **Per-punch categories:**
  - `matched`
  - `lg_manual` (Linked Gates DeviceID NULL)
  - `missing_from_pull`
  - `not_yet_in_lg` (< 24 h old)
  - `missing_in_lg`
- **Agent reading:**
  - Incremental reads use `EmployeeCheckID > last seen`, batches of 5,000.
  - Every night, re-read the last 45 days.
  - The first load starts on the 1st of last month, unless the ini says otherwise.
- **Agent timing:**
  - Machine pulls run nightly 02:00–05:00, plus collect-now.
  - If a machine refuses or times out, back off 10 minutes.
- **Machines:**
  - Rename 192.168.4.15 to «Balegh» and 192.168.5.15 to «Zahar».
  - Add BabElhadid 192.168.1.13 and Wearhouse 192.168.1.14.
  - Closed (`is_active=False`, label «مغلق»): Head Office, Marian, Michael, Rashidi, Shady, Shoubra, Amany, Ehab, Aliaa.
- **Never touch the office DB** without the owner's word. Commands default to a dry run.
- **Repo rules** (CLAUDE.md): help text in Arabic and English for the new tab, with its `updated` date bumped; permission tests; a performance budget row; exports through the shared safe-export path; no new `# nosec` or `# noqa`.
- **Coordinator rules:**
  - Local test runs need clearance from the coordinator session.
  - Merges go through the coordinator.
  - Migrations take the next free number on `main` at the time of writing (hr is at 0014 today).

## Review Focus

1. **A Linked Gates row edited after we copied it:** the new version wins in day figures, and the old one stays visible. (Task 4 test `test_edited_row_supersedes`.)
2. **Punches that are both on the machine and in Linked Gates:** they count once in the session figures, not twice. (Task 5 test `test_same_punch_both_sources_counts_once`.)
3. **A session that crosses the month boundary** (in on the 31st at 23:00, out on the 1st at 08:00): it belongs to the 31st, and the 1st doesn't show a lone punch. (Task 2 test `test_month_edge_night_session`.)
4. **The SQL reader fails mid-batch** (SQL Server restarted): the agent resumes from the last stored ID with no gap and no duplicate. (Task 3 test `test_resume_after_failed_batch`.)
5. **A closed machine starts sending punches again:** the punches are stored and an alert appears, rather than being refused. (Task 8 test `test_closed_device_punch_alerts`.)

---

### Task 1: Settings, nullable cut-off and the Linked Gates models

**Files:**
- Modify: `config/settings.py` (next to `HR_ATTENDANCE_ENABLED`, line ~661)
- Modify: `apps/hr/models.py` (`Employee.day_boundary` line 541; new models after `AttendancePunch`)
- Create: `apps/hr/migrations/00NN_attendance_linkedgates.py`, a schema migration plus a RunPython step that sets `04:00` to null
- Modify: `apps/hr/attendance/resolve.py` (`_eligible`): use `effective_boundary(employee)`
- Test: `apps/tests/test_hr_attendance_linkedgates_models.py`

**Interfaces:**
- **Produces, settings** (via `decouple.config`):
  - `HR_ATTENDANCE_LINKEDGATES_ENABLED: bool`
  - `HR_ATTENDANCE_DAY_SOURCE: str`
  - `HR_ATTENDANCE_SESSION_GAP_HOURS: int`
- **Produces, function:** `apps.hr.attendance.days.effective_boundary(employee) -> datetime.time`. Returns `employee.day_boundary or datetime.time(4, 0)`. Used only for employment-date eligibility.
- **Produces, models** (all with `db_default` on NOT NULL fields, per the migration rules):
  - **`LinkedGatesDevice`:**
    - `lg_device_id` (int, unique)
    - `name`, `ip`, `lg_status: bool`
    - `device` (FK `AttendanceDevice`, null)
    - `refreshed_at`
  - **`LinkedGatesEmployee`:**
    - `lg_employee_id` (int, unique)
    - `enroll_no: int`, `hr_code: str`, `first_name`, `last_name`, `department_name`
    - `shift_type: int|None`, `is_manager: bool`, `lg_status: bool`
    - `refreshed_at`
  - **`LinkedGatesPunch`**, append-only (copy the `save`/`delete` guards from `AttendancePunch`, but allow updates that touch only `superseded_at` and `lg_removed`):
    - `lg_check_id: int`, `version: int` (default 1)
    - `enroll_no: int`, `check_time: datetime` (naive Cairo, stored as aware Cairo), `in_out_mode: int`
    - `lg_device_id: int|None`, `created_by_lg: int|None`, `edit_by_lg: int|None`, `edit_on_lg: datetime|None`
    - `employee` (FK `Employee`, null)
    - `received_at`, `superseded_at` (null), `lg_removed: bool`
    - `flag` (same as `AttendancePunch.flag`)
    - **Constraint:** unique (`lg_check_id`, `version`). Index on (`employee`, `check_time`).
  - **`LinkedGatesCursor`:** a singleton with `last_check_id: int`, `last_full_reread_at`.

- [ ] **Step 1:** Write the failing tests:
  - `test_day_boundary_nullable_and_migrated`: an employee created with `day_boundary=None` saves. The migration function `null_default_boundaries(apps, schema_editor)` turns `04:00` into null and leaves `06:00` alone.
  - `test_lg_punch_append_only`: a second `save()` that changes `check_time` raises `PermissionError`. Changing only `superseded_at` is allowed. `delete()` raises.
  - `test_lg_punch_unique_version`: a duplicate (`lg_check_id`, `version`) raises `IntegrityError`.
  - `test_eligible_with_null_boundary`: `resolve._eligible` treats null like `04:00`.
- [ ] **Step 2:** Run `venv/Scripts/python.exe manage.py test apps.tests.test_hr_attendance_linkedgates_models --keepdb`. **Expected:** FAIL (no models). *Coordinator clearance required before any local run.*
- [ ] **Step 3:** Add the settings, change `day_boundary` to `null=True, blank=True, default=None`, add the models, then run `makemigrations hr` and add the RunPython step. Update `resolve._eligible` and `views.py:399` (`_RESOLVE_FIELDS`) so they accept null.
- [ ] **Step 4:** Run the same tests, plus `makemigrations --check --dry-run` and `apps.tests.test_migration_rules`. **Expected:** PASS.
- [ ] **Step 5:** Commit: `feat(hr): Linked Gates models, nullable day cut-off`.

### Task 2: Work-session engine

**Files:**
- Create: `apps/hr/attendance/sessions.py` (pure functions, no ORM)
- Modify: `apps/hr/attendance/days.py` (`build_days`): when `boundary is None`, use sessions; otherwise keep the current path
- Test: `apps/tests/test_hr_attendance_sessions.py`

**Interfaces:**
- **Consumes:** `HR_ATTENDANCE_SESSION_GAP_HOURS`; `DUPLICATE_WINDOW_SECONDS` from `days.py`.
- **Produces:**
  - `Stamp = NamedTuple(at: datetime.datetime, machine: str, sources: frozenset[str])`, where the sources are `'machine'` or `'lg'`.
  - `Session = dataclass(work_date: date, stamps: list[Stamp], first_in: datetime, last_out: datetime|None, worked_minutes: int, needs_review: bool)`.
  - `merge_stamps(stamps: list[Stamp]) -> list[Stamp]`: sorts, and folds stamps within 120 s into one, uniting `sources` and keeping the earliest `at`.
  - `build_sessions(stamps: list[Stamp], gap_hours: int = 6) -> list[Session]`.
  - `DayRow` gets a new field, `sessions: list[Session]` (default empty).
  - `build_days(...)` accepts `boundary=None`, and then fills `first_in`, `last_out`, `worked_minutes` and `needs_review` from that date's sessions. Worked minutes are summed across sessions; `needs_review` is true if any session needs review.

- [ ] **Step 1:** Write the failing tests:

| Test | Punches | Expected |
|---|---|---|
| `test_morning` | 08:00, 16:00 | 1 session on D, 480 min |
| `test_evening_past_midnight` | 16:00 D, 00:30 D+1 | 1 session on D, 510 min |
| `test_night_shift` | 23:00 D, 08:00 D+1 | 1 session on D, 540 min |
| `test_lone_after_midnight` | 00:40 D+1 only | session on D, `needs_review` |
| `test_manager_pairs` | 09:00, 12:00, 13:00, 18:00 | 480 min (3 h + 5 h) |
| `test_odd_punches` | 09:00, 12:00, 13:00 | 180 min, `needs_review` |
| `test_split_shift_gap` | 08:00, 12:00, 19:00, 23:00 | 2 sessions, both on D, total 480 |
| `test_duplicate_window` | 08:00:00, 08:01:30 | one stamp |
| `test_two_machines` | 08:00 on A, 16:00 on B | one session; machines are A and B |
| `test_month_edge_night_session` | 23:00 on the 31st, 08:00 on the 1st, `build_days` for both months | the earlier month has the 31st at 540 min; the later month has no punches on the 1st |
| `test_fixed_boundary_still_works` | `boundary=time(6, 0)` | current behaviour unchanged |

- [ ] **Step 2:** Run `... test apps.tests.test_hr_attendance_sessions --keepdb`. **Expected:** FAIL.
- [ ] **Step 3:** Implement `sessions.py` and the `build_days` branch. `punches_for_month` must widen its window to the month's last day + 1, as it already does.
- [ ] **Step 4:** Run it together with `apps.tests.test_hr_attendance_days`. **Expected:** PASS, with the existing day tests unchanged.
- [ ] **Step 5:** Commit: `feat(hr): work-session day grouping`.

### Task 3: Agent — read-only Linked Gates reader

**Files:**
- Create: `attendance_agent/lg_reader.py`
- Modify:
  - `attendance_agent/collector.py`: `load_config` reads an optional `[linkedgates]` section; `AgentLoop.tick` calls the reader when it's configured and the server's config says `linkedgates: true`
  - `attendance_agent/uploader.py`: no change beyond the new `kind` values
  - `attendance_agent/agent.ini.example`: add a `[linkedgates]` example (`server = .\SQLEXPRESS`, `database = Linked_ERP_HR_v1`, `trusted = yes`, optional `user`/`password`, `first_load_from = 2026-10-01`)
  - `attendance_agent/README.md`: install ODBC Driver 18 and `pyodbc`
- Test: `apps/tests/test_attendance_agent_lg_reader.py` (a fake connection object; pyodbc is not needed in CI)

**Interfaces:**
- **Produces:**
  - `ALLOWED_QUERIES: dict[str, str]`, a fixed set of four SELECTs:
    - `punches_after`: columns `EmployeeCheckID, EnrollNo, INOutMode, CheckTime, DeviceID, CreatedBy, EditBy, EditOn`, filtered by `WHERE EmployeeCheckID > ?`, ordered by ID, `TOP 5000`
    - `punches_since`: the same columns, `WHERE CheckTime >= ?`
    - `devices`: `DeviceID, DeviceName, IPAddress, Status`
    - `employees`: `EmployeeID, EnrollNo, HRCode, EmployeeFirstName, EmployeeLastName, DepartmentID, ShiftType, IsManager, Status`, plus `Department` (`DepartmentID, DepartmentName`)
  - `class LinkedGatesReader(connect: Callable[[], Connection])` with:
    - `read_new(after_id: int) -> list[dict]`
    - `read_since(since: datetime) -> list[dict]`
    - `read_reference() -> dict`
  - `_run(name, *params)` is the only place SQL executes. It looks up `ALLOWED_QUERIES[name]`, so no caller-supplied SQL ever runs.
  - Agent state file `lg_cursor.json` holds `{"last_check_id": int, "last_full_reread": iso}`. The agent advances it only after the server accepts the batch.
  - **Upload kinds:**
    - `lg_punches`, payload `{"rows": [...], "reread": bool}`
    - `lg_reference`, payload `{"devices": [...], "employees": [...], "departments": [...]}`

- [ ] **Step 1:** Write the failing tests:
  - `test_only_allowed_sql`: parse every string in `ALLOWED_QUERIES`. Each starts with `SELECT`, and contains none of `INSERT`, `UPDATE`, `DELETE`, `EXEC`, `MERGE`, `DROP`, `ALTER`, `CREATE`, `;`, `Salary`, `Phone`, `Email`, `EmployeeImage`, `Password`, `Users`, `UserPermissions`.
  - `test_no_other_execute`: grep the source of `lg_reader.py`. `.execute(` appears exactly once, inside `_run`.
  - `test_incremental_batches`: the fake returns 5,000, then 1,200, then 0 rows. The reader reads three times, and the cursor ends at the maximum ID.
  - `test_resume_after_failed_batch`: the upload raises on the second batch. The cursor stays at the end of the first batch, and the next tick re-reads from there.
  - `test_nightly_reread_once_per_day`: `read_since(today - 45 days)` runs once per calendar day, sent with `reread: true`.
  - `test_logs_have_no_codes`: captured log records contain only counts.
- [ ] **Step 2:** Run `... test apps.tests.test_attendance_agent_lg_reader --keepdb`. **Expected:** FAIL.
- [ ] **Step 3:** Implement. `connect` is built in `collector` from the ini: `pyodbc.connect('DRIVER={ODBC Driver 18 for SQL Server};SERVER=…;DATABASE=…;Trusted_Connection=yes;Encrypt=no', readonly=True)`. Import `pyodbc` lazily, so an agent without `[linkedgates]` never needs it.
- [ ] **Step 4:** Run the tests, plus `apps.tests.test_attendance_agent_loop`. **Expected:** PASS.
- [ ] **Step 5:** Commit: `feat(agent): read-only Linked Gates reader`.

### Task 4: Server — store Linked Gates rows (versioned)

**Files:**
- Create: `apps/hr/attendance/lg_ingest.py`
- Modify:
  - `apps/hr/attendance/agent_views.py`: add `AgentLgPunchesView` and `AgentLgReferenceView`. Both return 503 (`SwitchedOff`) unless both switches are on. `AgentConfigView` adds `'linkedgates': settings.HR_ATTENDANCE_LINKEDGATES_ENABLED`.
  - `apps/hr/attendance/urls.py`: add `agent/lg/punches/` and `agent/lg/reference/`
- Test: `apps/tests/test_hr_attendance_lg_ingest.py`

**Interfaces:**
- **Consumes:** the models from Task 1; `ingest.is_bad_date`; `resolve._employee_for`.
- **Produces:**
  - `store_lg_punches(rows: list[dict], reread: bool, today=None) -> dict`, returning `{'new': int, 'versioned': int, 'unchanged': int, 'removed': int}`.
    - **New `lg_check_id`:** insert version 1.
    - **Known ID whose `check_time`, `enroll_no` or `lg_device_id` changed:** set `superseded_at` on the current version and insert version n+1.
    - **On `reread=True`:** any current row whose ID falls inside the batch's ID range and check-time window but is missing from the batch gets `lg_removed=True`.
    - **Bad dates** (future, or before 2015-01-01) are stored with `flag='bad_date'`.
    - The employee is resolved by `enroll_no` = `Employee.hr_number`.
  - `store_lg_reference(body: dict) -> dict`: upserts devices and employees. It auto-maps a `LinkedGatesDevice` to the `AttendanceDevice` with the same IP **only** when exactly one Linked Gates device has that IP.
  - `MAX_LG_ROWS_PER_REQUEST = 5000`.

- [ ] **Step 1:** Write the failing tests:
  - `test_new_rows_inserted`
  - `test_resend_is_idempotent`: the same batch twice gives `unchanged == n`
  - `test_edited_row_supersedes`: two versions; the current one has the new time
  - `test_reread_marks_removed`
  - `test_bad_date_flagged`: year 2116
  - `test_duplicate_ip_not_automapped`: 192.168.30.15 twice gives `device=None` for both
  - `test_switch_off_returns_503`
  - `test_wrong_agent_secret_401`
  - `test_over_limit_413`
- [ ] **Step 2:** Run `... test apps.tests.test_hr_attendance_lg_ingest --keepdb`. **Expected:** FAIL.
- [ ] **Step 3:** Implement `lg_ingest.py` and the views. Each batch runs in `transaction.atomic()`.
- [ ] **Step 4:** Run the tests, plus `apps.tests.test_hr_attendance_ingest`. **Expected:** PASS.
- [ ] **Step 5:** Commit: `feat(hr): store Linked Gates punches, versioned`.

### Task 5: One merged punch list for day figures

**Files:**
- Modify: `apps/hr/attendance/days.py`. `punches_for_month` returns `{employee_id: [Stamp]}`, built from `AttendancePunch` plus the current `LinkedGatesPunch` rows (where `superseded_at` is null, `lg_removed` is false and `flag` is empty), then passed through `sessions.merge_stamps`.
- Modify: `apps/hr/attendance/views.py`, `employee_days` (line ~263), to use the same helper.
- Test: extend `apps/tests/test_hr_attendance_days.py`.

**Interfaces:**
- **Consumes:** `sessions.Stamp`, `sessions.merge_stamps`.
- **Produces:**
  - `punches_for_month(employee_ids, year, month, sources=('machine', 'lg')) -> dict[int, list[Stamp]]`.
  - The machine name of a Linked Gates stamp comes from `LinkedGatesDevice.device.name`, else `LinkedGatesDevice.name`, else «يدوي» when `lg_device_id` is null.
  - `build_days` takes stamps; the fixed-boundary path converts them the same way.

- [ ] **Step 1:** Write the failing tests:
  - `test_same_punch_both_sources_counts_once`: 08:00:10 on the machine and 08:00:40 in Linked Gates give one stamp, with sources `{'machine', 'lg'}`.
  - `test_lg_manual_punch_used`: a null-device Linked Gates punch completes a day.
  - `test_superseded_and_removed_ignored`.
  - `test_query_count_flat`: `assert_budget` with 1 and 30 employees.
- [ ] **Step 2:** Run the day tests. **Expected:** FAIL.
- [ ] **Step 3:** Implement with two queries (machine and Linked Gates), each with `select_related`.
- [ ] **Step 4:** Run `apps.tests.test_hr_attendance_days apps.tests.test_hr_attendance_export apps.tests.test_hr_attendance_views`. **Expected:** PASS.
- [ ] **Step 5:** Commit: `feat(hr): days from merged machine + Linked Gates punches`.

### Task 6: Linked Gates rules recompute and the comparison engine

**Files:**
- Create: `apps/hr/attendance/lg_rules.py` (pure)
- Create: `apps/hr/attendance/compare.py`
- Test: `apps/tests/test_hr_attendance_lg_rules.py`, `apps/tests/test_hr_attendance_compare.py`

**Interfaces:**
- **Produces:**
  - `LgDay = dataclass(work_date, in_times: list[datetime], out_time: datetime|None)`. There can be several entries in `in_times` because of the device and mode grouping.
  - `lg_days(punches: list[LinkedGatesPunch-like], shift_type: int|None) -> dict[date, LgDay]`, applying the Global Constraints rules exactly.
  - `reason_codes(our: DayRow, lg: LgDay|None, punches: list[Stamp], shift_type) -> list[str]`, using the six codes in Global Constraints.
  - `punch_categories(device_id: int|None, day: date, now) -> list[dict]`. Each item is `{'at', 'enroll_no', 'machine', 'category'}`, with the five categories in Global Constraints.
  - `compare_month(employees, year, month) -> list[dict]`, one row per employee-day that differs: `{'employee_id', 'date', 'ours': {'in','out','minutes'}, 'lg': {'in','out','minutes'}, 'reasons': [...]}`.
  - `machine_day_counts(year, month) -> list[dict]`, one row per machine per day: `{'device', 'date', 'matched', 'lg_manual', 'missing_from_pull', 'not_yet_in_lg', 'missing_in_lg'}`.

- [ ] **Step 1:** Write the failing `lg_rules` tests, each one Linked Gates loss from the spec:

| Test | Shift type | Punches | Expected |
|---|---|---|---|
| `test_type1_window` | 1 | 06:30, 08:00, 16:00 | in 08:00, out 16:00; 06:30 ignored |
| `test_type2_window` | 2 | 09:00, 22:00 | in 09:00, out 22:00 |
| `test_after_midnight_out_moves_back` | 1 | 16:00 D, 00:30 D+1 | out on D = 00:30 |
| `test_out_hidden` | 1 | 16:00 D, 00:30 D+1, and on D+1 16:00 and 23:00 | D has no out |
| `test_no_shifttype` | None | | `{}` |
| `test_multi_in_device_mode` | | 08:00 on A mode 0, 08:05 on B mode 0 | 2 `in_times` |
| `test_night_split` | 2 | 23:00 D, 08:00 D+1 | D: out 23:00, no in; D+1: in 08:00 |

- [ ] **Step 2:** Write the failing `compare` tests:
  - `test_reason_night_split`
  - `test_reason_window_ignored`
  - `test_identical_day_not_listed`
  - `test_categories`: manual / missing_from_pull / not_yet_in_lg at 23 h, and missing_in_lg at 25 h
  - `test_compare_query_budget`
- [ ] **Step 3:** Run both test modules. **Expected:** FAIL.
- [ ] **Step 4:** Implement. Matching a punch across sources: same `enroll_no`/`user_code` and |Δt| ≤ 120 s. For a mapped device, the device must also match.
- [ ] **Step 5:** Run them. **Expected:** PASS.
- [ ] **Step 6:** Commit: `feat(hr): Linked Gates rules recompute + comparison`.

### Task 7: Comparison API, month columns, the «مقارنة لينكد جيتس» tab, help

**Files:**
- Modify: `apps/hr/attendance/views.py`. Add:
  - `lg_compare` (view level): GET `?year&month`, returning `{'machines': machine_day_counts, 'days': compare_month, 'day_source': settings.HR_ATTENDANCE_DAY_SOURCE}`
  - `lg_compare_export` (view level), through `core/export_safety.py`
  - `lg_device_map` (manage level): POST `{lg_device_id, device_id|null}`, audited
- Modify: `apps/hr/attendance/urls.py`: `linkedgates/compare/`, `linkedgates/compare/export/`, `linkedgates/devices/`, `linkedgates/devices/<int:lg_device_id>/map/`.
- Modify: `apps/hr/attendance/export.py` and the month payload in `views.month`. Each employee-month carries `ours` and `lg` totals plus `official: 'lg'|'ours'` from `HR_ATTENDANCE_DAY_SOURCE`. The Excel export puts the «المعتمد» column first.
- Modify: `frontend/src/pages/HRAttendancePage.jsx`. Add:
  - the tab «مقارنة لينكد جيتس», with a machine × day counts grid and a differences grid
  - sortable columns (`useSortableRows`)
  - `useGridKeyboard`
  - `useHelpTab('lg-compare')`
  - an export button
  - a device-mapping section (manage only)
  - the month grid shows both totals, and «المعتمد» marks the official one
- Modify: `apps/help/content/hr.py`: Arabic + English for the new tab, the both-columns month view, and the reason codes in plain words. Bump `updated`.
- Modify: `apps/tests/perf/budgets.py`: rows for `hr-attendance-lg-compare` and `hr-attendance-lg-devices`.
- Modify: `apps/tests/new_value_registry.py`: register the comparison export.
- Test: `apps/tests/test_hr_attendance_lg_views.py`

**Interfaces:**
- **Consumes:** `compare.compare_month`, `compare.machine_day_counts`; `access.py` grants.

- [ ] **Step 1:** Write the failing tests:
  - `test_compare_requires_view_grant`: 403 without a grant, 200 with view.
  - `test_device_map_requires_manage`.
  - `test_device_map_audited`: the audit row records before and after.
  - `test_export_safe`: the formula neutraliser is applied.
  - `test_month_has_both_totals_and_official`.
  - `test_switch_off_hides_lg`: with `HR_ATTENDANCE_LINKEDGATES_ENABLED=False`, the compare endpoint returns `{'enabled': False}`, and month figures fall back to machine punches only.
  - `test_compare_budget`: `assert_budget`.
- [ ] **Step 2:** Run `... test apps.tests.test_hr_attendance_lg_views apps.tests.test_help --keepdb`. **Expected:** FAIL.
- [ ] **Step 3:** Implement the backend. Then implement the tab, following the existing tab components in `HRAttendancePage.jsx` and adding no new modal.
- [ ] **Step 4:** Run the tests, `cd frontend && npm run lint && npm run build`, and the `apps.tests.security` sweeps serially, with clearance. **Expected:** PASS, build OK.
- [ ] **Step 5:** Commit: `feat(hr): Linked Gates comparison tab and both-columns month`.

### Task 8: Machine list fix, closed machines, agent timing

**Files:**
- Create: `apps/hr/management/commands/sync_attendance_devices.py`. Dry run by default; `--apply` writes; `--agent <name>` assigns every live machine to that agent. The command replaces the `MACHINES` list in `seed_attendance_devices.py` with the corrected 16-row list, which both commands import. It is idempotent and audited.
- Modify: `apps/hr/attendance/ingest.py` (`store_punches`). Punches for an `is_active=False` device are stored, and a one-per-day notification «جهاز مغلق أرسل بصمات» is raised through the existing `attendance_alert` notification type.
- Modify: `apps/hr/attendance/ingest.py` (`_update_device`). If `device_log_count` drops below the last known count, raise the alert «سجل الجهاز اتمسح».
- Modify: `attendance_agent/collector.py`:
  - `COLLECT_WINDOW = (time(2, 0), time(5, 0))`: scheduled reads happen only inside it; collect-now ignores it.
  - `BUSY_BACKOFF_SECONDS = 600`: used after a connect refusal or timeout, instead of `MIN_READ_GAP_SECONDS`.
- Test: `apps/tests/test_hr_attendance_devices_sync.py`; extend `test_attendance_agent_loop.py` and `test_hr_attendance_ingest.py`.

**Interfaces:**
- **Consumes:** the existing `AttendanceDevice` and `CollectionRun`; the notifications `attendance_alert` type.

- [ ] **Step 1:** Write the failing tests:
  - `test_sync_dry_run_writes_nothing`
  - `test_sync_renames_giza_to_balegh`
  - `test_sync_marks_closed`
  - `test_sync_idempotent`
  - `test_closed_device_punch_alerts`
  - `test_log_count_drop_alerts`
  - `test_scheduled_read_only_in_window`
  - `test_collect_now_ignores_window`
  - `test_busy_backoff_600`
- [ ] **Step 2:** Run the three modules. **Expected:** FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the attendance test modules. **Expected:** PASS.
- [ ] **Step 5:** Commit: `feat(hr): corrected machine list, closed-machine and log-cleared alerts, night collection window`.

### Task 9: Go-live doc and IT note

**Files:**
- Modify: `docs/deploy/2026-11-attendance-agent-go-live.md`. Add:
  - PC HR as the agent host
  - the ODBC Driver 18 install
  - the `[linkedgates]` ini section
  - the read-only login steps (from the IT note, with `Linked_ERP_HR_v1` and the column DENYs)
  - the order of switching on: `HR_ATTENDANCE_ENABLED`, then `HR_ATTENDANCE_LINKEDGATES_ENABLED`, with `HR_ATTENDANCE_DAY_SOURCE` left at `linkedgates`
  - `sync_attendance_devices` as a dry run, then `--apply`, with the owner's word
  - **"Never press F5 on Linked Gates procedures."**
- Modify: `docs/superpowers/specs/2026-11-07-hr-attendance-stage1-design.md`: one line pointing to the Stage 1b spec.

- [ ] **Step 1:** Write the doc changes.
- [ ] **Step 2:** Run `... test apps.tests.test_help` and the full `apps.hr`/attendance test modules once, with clearance. **Expected:** PASS.
- [ ] **Step 3:** Commit: `docs(hr): Stage 1b go-live`. Open a PR, report readiness to the coordinator, and don't merge.
