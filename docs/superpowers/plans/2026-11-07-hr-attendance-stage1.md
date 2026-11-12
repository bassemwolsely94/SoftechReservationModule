# HR Attendance Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the employee list, automatic punch collection from ZK machines, the HR review screen, the monthly export and alerts, with no pay calculation and no writes to machines or SOFTECH.

**Architecture:** Models live in `apps/hr`; attendance logic lives in a new `apps/hr/attendance/` package with its own API at `/api/hr-attendance/`, gated by named grants. A standalone, dependency-free `attendance_agent/` program runs on an office PC, reads machines over the ZK protocol, keeps a disk spool and pushes to the ERP. Daily and monthly figures are calculated on request from immutable punches by a pure function.

**Tech Stack:** Django 5.2, DRF 3.18, PostgreSQL 16, openpyxl, React/Vite with TanStack Query; the agent uses the Python standard library only.

**Spec:** `docs/superpowers/specs/2026-11-07-hr-attendance-stage1-design.md`

## Global Constraints

- No pay, penalty, lateness, overtime or deduction calculation. A day with no punches reads "no punches" (`بدون بصمات`), never "absent".
- Agent's allowed device commands only: connect, disconnect, read options, read sizes, read time, read user table, read attendance log, free buffer. Fingerprint templates are never requested.
- No SOFTECH reads or writes; nothing is added to `softech_write_manifest.py`.
- The salaries workbook is never added to the repository. The import reads only columns AV, BC, AX, AY, AZ, BA, AT.
- No phone, national ID, insurance, bank, religion or pay data in any model, log or export.
- Number equality alone never links a login. Generic logins can't be linked.
- Raw punches are never edited or deleted through any API.
- `HR_ATTENDANCE_ENABLED` defaults to False; ingest refuses when off. Add it as False in `deploy/production.env.example`.
- Thresholds: work-day boundary 04:00 (per employee), duplicate display window 2 minutes, drift warning 5 minutes, bad date = more than 1 day in the future or before 2015-01-01, machine silent 24 hours, agent silent 3 hours, collection every 60 minutes.
- Wording: `سيرفر`, never `خادم`; `BL`/`useBranchLabels`, never a bare branch code; no modals for common actions; RTL.
- Tests run with a unique database name, serially for security sweeps: `$env:TEST_DB_NAME='test_elr_attendance'`.
- Before every push, re-check migration numbers against `origin/main`, because other sessions merge too.

## Decisions This Plan Makes

These refine the spec. The first two differ from its wording and are flagged to the owner at handover.

1. **API prefix gate:** the whole `hr-attendance` prefix goes in `EXEMPT_PREFIXES` with a comment naming its gate, as `pic-analytics` does. `MODULE_BY_PREFIX` would refuse named grantees whose role lacks the module.
2. **Name-conflict guard:** machine names are Latin and employee names are Arabic, so comparing them automatically would produce false alarms. Automatic conflict detection covers only different real names for one ID across machines. For machine versus employee, the Employees tab shows both side by side, and the HR head can put an ID on hold.
3. **Punch time:** stored as `punch_date` + `punch_time` (no timezone), which can't be shifted by timezone or daylight-saving conversion. Identity is the device's raw timestamp integer, so an undecodable date is still stored and never lost.
4. **Protocol code:** own minimal client derived from the working probe, not pyzk, so the allowed-command list is enforced at the one place packets are sent.

## Review Focus

1. A code in Excel arrives as `1001.0`, `" 1001"` or text; it must import as `1001` and never create a second employee.
2. A 02:00 punch on the 1st of a month belongs to the last day of the previous month; both month views and exports must agree.
3. The ERP is down or answers 500 midway through a spool; nothing is lost, and resending creates no duplicates.
4. A machine returns an impossible date (Feb 31) or a year of 2133; the punch is stored, flagged, excluded from totals and shown on the issues tab.
5. A name in the export starts with `=`; it must appear as text and never run as a formula.

---

### Task 1: Data models, switch and access gate

**Files:**
- Modify: `apps/hr/models.py`, `apps/users/models.py` (`MODULE_CHOICES`), `apps/users/management/commands/seed_permissions.py`, `core/middleware/module_access.py`, `apps/access/public_paths.py`, `config/settings.py`, `config/urls.py`, `deploy/production.env.example`, `apps/users/serializers.py`
- Create: `apps/hr/attendance/__init__.py`, `apps/hr/attendance/access.py`, `apps/hr/attendance/urls.py`, `apps/hr/migrations/0007_attendance_stage1.py`, `apps/users/migrations/<next>_hr_attendance_module.py`
- Test: `apps/tests/test_hr_attendance_access.py`

**Interfaces:**
- Produces models in `apps/hr/models.py`:
  - `Employee`: `hr_number` (Char 30, unique), `name_ar`, `department`, `section`, `job_title`, `work_location`, `branch` (FK null), `daily_hours` (Decimal 4,2 null), `status` (`active`/`left`), `employee_type` (`payroll`/`non_payroll`), `start_date`, `end_date` (null), `day_boundary` (Time, default 04:00), `staff` (OneToOne `users.StaffProfile`, null), `softech_usercode` (blank), `hold_resolution` (bool), `hold_reason`.
  - `GenericLogin`: `staff` (OneToOne), `marked_by`, `marked_at`. `EmployeeLinkRejection`: `employee`, `staff`, `decided_by`, `decided_at`, unique pair.
  - `AttendanceAgent`: `name`, `token_hash` (Char 64, unique), `revoked_at`, `last_seen_at`, `collect_requested_at`, `created_by`.
  - `AttendanceDevice`: `serial` (unique), `name`, `ip`, `port` (default 4370), `model_name`, `location_label`, `branch` (FK null), `agent` (FK null), `is_active`, `last_contact_at`, `last_status`, `last_drift_seconds`, `last_log_count`.
  - `DeviceUser`: `device`, `user_code`, `device_name`, `is_admin`, `first_seen_at`, `last_seen_at`; unique (`device`, `user_code`).
  - `UnknownIdDecision`: `user_code` (unique), `decision` (`ignored`), `reason`, `decided_by`, `decided_at`.
  - `AttendancePunch`: `device` (PROTECT), `user_code`, `raw_stamp` (PositiveBigInteger), `punch_date` and `punch_time` (null), `state`, `verify_mode`, `received_at` (auto), `flag` (blank / `bad_date`), `employee` (FK null, SET_NULL); UniqueConstraint (`device`, `user_code`, `raw_stamp`, `state`); index (`employee`, `punch_date`). `save()` on an existing row and `delete()` raise `PermissionError`.
  - `CollectionRun`: `agent`, `device`, `started_at`, `finished_at`, `records_read`, `new_count`, `duplicate_count`, `oldest_date`, `newest_date`, `drift_seconds`, `device_log_count`, `status` (`success`/`failed`), `error`.
  - `AttendanceAccess`: `staff`, `level` (`view`/`manage`), `granted_by`, `granted_at`, `revoked_at`.
- Produces `apps/hr/attendance/access.py`: `MODULE = 'hr_attendance'`; `class Access(user_or_request)` with booleans `can_view`, `can_export`, `can_manage`, `can_admin`, plus `as_dict()`; `can_open(user) -> bool`; `manager_recipients() -> list[StaffProfile]` (admins plus active Manage grants).

- [ ] **Step 1: Create the branch and commit the spec**

```bash
git checkout -b claude/hr-attendance-stage1
git add docs/superpowers/specs/2026-11-07-hr-attendance-stage1-design.md docs/superpowers/plans/2026-11-07-hr-attendance-stage1.md
git commit -m "docs(hr): attendance stage 1 design and plan"
```

Add only these two paths. Other sessions have untracked files in this folder.

- [ ] **Step 2: Write failing tests**

`test_admin_can_do_everything`; `test_view_grant_can_view_and_export_not_manage`; `test_manage_grant_can_manage_not_admin`; `test_revoked_grant_has_no_access`; `test_branch_manager_gets_403_on_month` (GET `/api/hr-attendance/month/`); `test_hr_self_service_module_does_not_open_attendance` (a role with `hr` view gets 403); `test_punch_save_existing_raises` and `test_punch_delete_raises` (`assertRaises(PermissionError)`); `test_punch_unique_on_device_user_stamp_state` (`IntegrityError`).

- [ ] **Step 3: Run and confirm failure**

Run: `.\venv\Scripts\python.exe manage.py test apps.tests.test_hr_attendance_access`
Expected: FAIL (import errors for the new models).

- [ ] **Step 4: Implement**

Add the models and migrations. Add `('hr_attendance', 'الحضور والبصمة')` to `MODULE_CHOICES` and `seed_permissions.py` with no role but admin. Add `'hr-attendance'` to `EXEMPT_PREFIXES` with the comment `# own gate apps/hr/attendance/access.py: RBAC hr_attendance + named grants`. Add `'/api/hr-attendance/agent/'` to `PUBLIC_PREFIXES` with the comment `# apps.hr.attendance.agent_views (no staff user; per-agent secret, hashed, constant-time)`. Add `HR_ATTENDANCE_ENABLED = config(..., default=False, cast=bool)`. Register `path('api/hr-attendance/', include('apps.hr.attendance.urls'))`. Add `can_hr_attendance` to the `/api/auth/me/` serializer, as `can_pic_analytics` does. Add a code comment in `access.py` that attendance is company-level by decision, seen only by named grantees and admins.

- [ ] **Step 5: Run tests and the security sweeps**

Run: `.\venv\Scripts\python.exe manage.py test apps.tests.test_hr_attendance_access`, then `.\venv\Scripts\python.exe manage.py test apps.tests.security`
Expected: PASS. If `test_skipped_models_are_baselined` reports a new model, add a builder to `apps/tests/security/canary.py`, not a baseline line. Regenerate `PERMISSION_MATRIX.md` as `apps/tests/security/permission_matrix.py` directs.

- [ ] **Step 6: Commit**: `feat(hr): attendance models, switch and access gate`.

### Task 2: One-time employee import

**Files:**
- Create: `apps/hr/attendance/employee_import.py`, `apps/hr/management/commands/import_attendance_employees.py`
- Test: `apps/tests/test_hr_attendance_import.py` (builds its workbook with openpyxl at test time, with fake data)

**Interfaces:**
- Produces: `IMPORT_COLUMNS = {'AV': 'hr_number', 'BC': 'name_ar', 'AX': 'department', 'AY': 'section', 'AZ': 'work_location', 'BA': 'job_title', 'AT': 'daily_hours'}`; `normalise_code(value) -> str`; `read_workbook(path) -> ImportPreview` (`rows`, `errors`); `apply(preview, user) -> dict`. Command: `import_attendance_employees <path> [--apply]`, dry-run by default.

- [ ] **Step 1: Write failing tests**

`test_normalise_code_handles_float_space_text`: `1001.0`, `' 1001'`, `'1001'` all give `'1001'`. `test_reads_only_allowed_columns`: fixture has `CE`, `Z`, `AE`, `AU`, `Y` populated with `SECRET`; `'SECRET'` appears nowhere in the preview. `test_skips_total_row`: a row named `الاجمالى` is excluded. `test_55_rows_dry_run_writes_nothing`: 55 rows give `len(preview.rows) == 55` and `Employee.objects.count() == 0`. `test_duplicate_code_is_an_error`. `test_missing_hours_stays_null`. `test_branch_set_only_on_clean_map`: `المخازن` gives `work_location='المخازن', branch=None`. `test_apply_is_idempotent`: applying twice leaves one row per code and updates fields. `test_apply_audited`.

- [ ] **Step 2: Run and confirm failure**: `.\venv\Scripts\python.exe manage.py test apps.tests.test_hr_attendance_import` fails on import.

- [ ] **Step 3: Implement**

Header row is 2; data starts at row 3. Load with `data_only=True, read_only=True`, and read cells only by `IMPORT_COLUMNS`. Error messages name a row and code, never a value from another column. Match `branch` by exact `Branch` name only. Dry-run prints counts and errors, not names. `AuditLog.log('hr_employee_import', ...)`.

- [ ] **Step 4: Run tests**: PASS.

- [ ] **Step 5: Commit**: `feat(hr): one-time employee import with dry-run`.

### Task 3: Agent ingest API

**Files:**
- Create: `apps/hr/attendance/ingest.py`, `apps/hr/attendance/resolve.py`, `apps/hr/attendance/agent_auth.py`, `apps/hr/attendance/agent_views.py`, `apps/hr/management/commands/issue_attendance_agent.py`
- Modify: `apps/hr/attendance/urls.py`
- Test: `apps/tests/test_hr_attendance_ingest.py`

**Interfaces:**
- Header: `X-ElR-Attendance-Agent: <secret>`.
- `GET agent/config/` returns `{agent, collect_now: bool, devices: [{serial, name, ip, port}]}`, only active devices assigned to this agent.
- `POST agent/punches/` takes `{device_serial, punches: [{user_code, raw_stamp, date|null, time|null, state, verify_mode}]}` and returns `{accepted, duplicate}`. Max 2,000 per request; more gets 413.
- `POST agent/roster/` takes `{device_serial, users: [{user_code, name, is_admin}]}`.
- `POST agent/runs/` takes `{device_serial, started_at, finished_at, records_read, oldest_date, newest_date, drift_seconds, device_log_count, status, error}`, and clears `collect_requested_at` only when the request sends `collect_done: true`.
- Produces `ingest.store_punches(device, rows, today=None) -> (accepted, duplicate)`; `ingest.is_bad_date(d, today) -> bool`; `resolve.resolve_user_code(code) -> None`; `resolve.conflicting_user_codes() -> set[str]`; `resolve.is_real_name(name, user_code) -> bool`.

- [ ] **Step 1: Write failing tests**

- `test_no_or_wrong_or_revoked_secret_is_401`, and `test_switch_off_is_503` (`override_settings(HR_ATTENDANCE_ENABLED=False)`).
- `test_agent_secret_opens_only_agent_endpoints`: the same header on `/api/hr-attendance/month/` gets 401/403.
- `test_device_not_assigned_is_403`.
- `test_resend_creates_no_duplicates`: same batch twice gives `accepted=2, duplicate=0`, then `accepted=0, duplicate=2`.
- `test_more_than_2000_is_413`.
- `test_bad_year_stored_flagged`: date `2133-05-06` is stored with `flag='bad_date'`; so is `2014-12-31`; and `today + 2 days`.
- `test_undecodable_date_stored`: `date=None, raw_stamp=123` stores with `flag='bad_date'`.
- `test_punch_resolves_to_employee`; `test_unknown_id_stays_unresolved_then_resolves_when_added`.
- `test_punch_outside_employment_dates_unresolved`; `test_hold_resolution_keeps_punches_unresolved`.
- `test_two_real_names_on_two_machines_is_conflict`: names `SamerSami` and `AhmedAli` on one ID appear in `conflicting_user_codes()`; a name equal to the ID or blank is not a real name; `'Samer Sami'` and `'SamerSami'` count as the same.
- `test_conflict_blocks_resolution`.
- `test_error_text_uses_public_error`.

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

Store the SHA-256 of the secret and compare with `hmac.compare_digest`, using the bytes approach in `apps/access/network.py:40-46`. Use `bulk_create(ignore_conflicts=True)` and count from a pre-query of existing `raw_stamp`s for that device. Resolve with `queryset.update(employee=...)`, which doesn't call the blocked `save()`. `issue_attendance_agent <name>` prints the secret once and stores only the hash. Update `last_seen_at` and device `last_contact_at`, `last_status`, `last_drift_seconds`, `last_log_count`.

- [ ] **Step 4: Run tests**: PASS.

- [ ] **Step 5: Commit**: `feat(hr): attendance agent ingest API`.

### Task 4: Agent ZK read client

**Files:**
- Create: `attendance_agent/__init__.py`, `attendance_agent/zk_client.py`, `attendance_agent/README.md` (Arabic and English install steps; first run note)
- Test: `apps/tests/test_attendance_agent_zk.py`

**Interfaces:**
- Produces `ALLOWED_COMMANDS: frozenset[int]` = `{1000, 1001, 11, 50, 201, 1503, 1504, 1502}`; `class ZkClient(ip, port=4370, timeout=30, comm_key=None)` as a context manager with `read_time() -> datetime`, `read_sizes() -> Sizes`, `read_users() -> list[DeviceUserRow]`, `read_logs() -> list[LogRow]`; `decode_stamp(raw: int) -> tuple[date | None, time | None]`; `parse_users(table, count)`; `parse_logs(table, count)`. `DeviceUserRow` has `user_code, name, is_admin` only, with no password or card field. `LogRow` has `user_code, raw_stamp, date, time, state, verify_mode`.

- [ ] **Step 1: Write failing tests**

- `test_forbidden_command_raises`: `client._send(2004)` (CMD_CLEAR_ATTLOG) raises `ForbiddenCommand` before any socket write. Also for `1002` (disable), `1003` (enable), `1004` (restart), `8` (write user), `18` (delete user), `202` (set time), `88` (read template).
- `test_source_has_no_public_write_methods`: `dir(ZkClient)` has no name containing `clear`, `delete`, `set_`, `write`, `disable`, `restart`, `template`.
- `test_parse_users_72_and_28_byte_records_keep_no_password`: fixture records with a password `b'SECRET'`; `'SECRET'` isn't in `repr(rows)`.
- `test_parse_logs_40_16_8_byte_records`.
- `test_decode_stamp`: known value gives the expected date and time; a value decoding to Feb 31 gives `(None, None)`.
- `test_read_users_over_fake_socket_chunked`: a fake socket serves `1500 + 1501 + 2000` frames in pieces.

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

Port the checksum, framing and buffer reads from the probes described in the spec, with `_send` as the single gate on `ALLOWED_COMMANDS`. The comm key, if configured, uses the standard CMD_AUTH (`1102`), which is added to the allowed list only when `comm_key` is set. If the device answers `2005` and no key is set, raise `CommKeyRequired`.

- [ ] **Step 4: Run tests**: PASS. Must import nothing from Django.

- [ ] **Step 5: Commit**: `feat(hr): read-only ZK client with command allow-list`.

### Task 5: Agent collection loop and spool

**Files:**
- Create: `attendance_agent/spool.py`, `attendance_agent/uploader.py`, `attendance_agent/collector.py`, `attendance_agent/__main__.py`, `attendance_agent/agent.ini.example`
- Test: `apps/tests/test_attendance_agent_loop.py`

**Interfaces:**
- Consumes: `ZkClient`; agent endpoints from Task 3.
- Produces `Spool(path)`: `put(kind, payload) -> Path`, `pending() -> list[Path]` (oldest first), `ack(path)`. `Uploader(base_url, secret)`: `get_config() -> dict`, `send(kind, payload)`. `collect_device(device, client_factory, spool, now) -> None`. `run_forever(config)`.

- [ ] **Step 1: Write failing tests**

- `test_spool_written_before_send`: a fake uploader sees the spool file already on disk.
- `test_erp_500_keeps_file_and_resends_in_order`: 500 keeps all files; success removes only acked ones, oldest first.
- `test_crash_mid_write_ignored`: a `.tmp` file isn't listed as pending (atomic rename).
- `test_one_bad_machine_does_not_stop_others`: the first device raises `TimeoutError`; the second is still collected; a failed run is reported for the first.
- `test_batches_at_2000`: 4,500 logs make 3 punch files.
- `test_drift_reported`: device clock 180 s behind gives `drift_seconds=-180`.
- `test_collect_now_triggers_run` and `test_hourly_schedule`.
- `test_secret_never_logged`: captured logs don't contain the secret.

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

Poll config every 60 seconds; collect each device hourly or on `collect_now`. Order per device: time, sizes, users, logs, disconnect, spool, send. Write with `.tmp` + `os.replace`. HTTP through `urllib.request` with a 60-second timeout. Configuration comes from `agent.ini`, whose path is an argument, and which holds the ERP URL, secret and optional per-serial comm keys. Log to a rotating file with counts only: no names. Windows Task Scheduler instructions in the README.

- [ ] **Step 4: Run tests**: PASS.

- [ ] **Step 5: Commit**: `feat(hr): attendance agent spool and collection loop`.

### Task 6: Daily and monthly engine

**Files:**
- Create: `apps/hr/attendance/days.py`
- Test: `apps/tests/test_hr_attendance_days.py`

**Interfaces:**
- Produces `work_date_for(punch_date, punch_time, boundary) -> date`; `build_days(punches, boundary, daily_hours, year, month, info_by_date=None) -> list[DayRow]`; `month_totals(days) -> MonthTotals`; `punches_for_month(employee_ids, year, month) -> dict`; `leave_info(employees, year, month) -> dict`.
- `DayRow`: `work_date, first_in, last_out, worked_minutes, needs_review, no_punches, punch_count, machines, raw, info`.
- `MonthTotals`: `days_with_punches, worked_hours, expected_hours, days_needing_review, days_no_punches`.

- [ ] **Step 1: Write failing tests**

- `test_0200_belongs_to_previous_day`; `test_0200_on_first_counts_in_previous_month`: a 02:00 punch on Dec 1 counts in the November days and not December.
- `test_overnight_shift_is_one_day`: 22:00 and 03:30 next day give 330 minutes on the first date.
- `test_custom_boundary`: boundary 06:00 moves a 05:00 punch to the previous day.
- `test_punches_within_two_minutes_count_once`: 09:00 and 09:01:59 are a single punch for display, so that day `needs_review`; `raw` keeps both.
- `test_single_punch_needs_review_no_hours`.
- `test_day_with_no_punches_is_no_punches_not_absent`: `no_punches=True`, and no field or value contains `absent` or `غياب`.
- `test_machine_in_out_state_ignored`: first is in and last is out, whatever `state` says.
- `test_two_machines_combined`.
- `test_flagged_and_unresolved_excluded`.
- `test_expected_hours`: daily 8.5 × 4 days with punches = 34; `daily_hours=None` gives `expected_hours=None`.
- `test_approved_leave_and_permit_shown_as_info_only`: matched by `staff` or `employee_hr_code`; a pending request isn't shown; totals don't change.

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement** as pure functions, except the two query helpers, with `Decimal` for hours. Don't list dates after today as `no_punches`.

- [ ] **Step 4: Run tests**: PASS.

- [ ] **Step 5: Commit**: `feat(hr): attendance day and month engine (display only)`.

### Task 7: Staff API and link review

**Files:**
- Create: `apps/hr/attendance/views.py`, `apps/hr/attendance/links.py`, `apps/hr/attendance/issues.py`, `apps/hr/management/commands/seed_attendance_devices.py`
- Modify: `apps/hr/attendance/urls.py`
- Test: `apps/tests/test_hr_attendance_views.py`

**Interfaces:**
- Consumes: `Access`, `build_days`, `month_totals`, `resolve.*`.
- Produces `links.suggest(employee) -> list[{staff_id, name, reason}]`; `links.is_generic_login(staff) -> bool` (a `GenericLogin` row, or username/name matching `cash|كاشير|test|branch|فرع`, case-insensitive); `links.confirm(employee, staff, user)`; `links.reject(employee, staff, user)`; `links.mark_generic(staff, user)`; `links.unlink(employee, user)`; `issues.list_issues() -> list[dict]`.
- Endpoints under `/api/hr-attendance/`:
  - View: `me/`, `month/?month=YYYY-MM`, `employees/<id>/days/?month=`, `issues/`, `employees/`, `unknown-ids/`, `devices/`, `freshness`.
  - Manage: `employees/<id>/` PATCH, `employees/<id>/link/`, `reject-link/`, `unlink/`, `hold/`, `generic-login/`, `unknown-ids/<code>/create-employee/`, `unknown-ids/<code>/ignore/`, `collect-now/`.
  - Admin only: `devices/<id>/` PATCH, `agents/`, `agents/issue/`, `agents/<id>/revoke/`, `grants/`, `grants/<id>/revoke/`.

- [ ] **Step 1: Write failing tests**

- `test_every_endpoint_403_for_non_granted`: table-driven over all routes; covers GET and POST.
- `test_view_grant_cannot_confirm_link`, and `test_manage_grant_cannot_edit_device_or_issue_agent`.
- `test_same_number_alone_is_not_linked`: an employee's HR number equal to `softech_user_id` leaves `staff=None` after import, ingest and suggestions.
- `test_confirm_link_writes_hr_code_and_audits`; `test_generic_login_cannot_be_linked` (400); `test_reject_is_not_suggested_again`; `test_one_staff_one_employee` (400).
- `test_unlink_clears_hr_code`: `StaffProfile.hr_code` becomes blank, and existing HR requests keep their stored code.
- `test_month_has_no_money_keys`: response JSON has no key containing `salary`, `amount`, `deduct`, `penalty`, `net`.
- `test_issues_groups_unknown_ids_per_id` (last punch, machines, count), and `test_ignored_id_leaves_issues` (a reason is required).
- `test_create_employee_from_unknown_id_resolves_old_punches`, with `employee_type='non_payroll'`.
- `test_issues_lists_bad_dates_drift_and_conflicts`.
- `test_sorting_whitelist`: an unknown `ordering` value is ignored.
- `test_collect_now_sets_flag_and_audits`; `test_all_changes_audited`: link, reject, edit, status, device, agent issue and revoke.
- `test_seed_devices_is_idempotent`: 8 devices from the spec table; `Alia` and `8` get an empty `location_label`, and no branch is guessed.

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement** using `core/sort_ordering.py` (`NullsLastOrderingFilter` / `explicit_order_by`) and `AuditLog.log(...)` as in `apps/pic_analytics/views.py:84`.

- [ ] **Step 4: Run tests and sweeps**: `apps.tests.test_hr_attendance_views`, then `apps.tests.security`: PASS.

- [ ] **Step 5: Commit**: `feat(hr): attendance staff API and link review`.

### Task 8: Monthly Excel export

**Files:**
- Create: `apps/hr/attendance/export.py`
- Modify: `apps/hr/attendance/views.py`, `apps/hr/attendance/urls.py`
- Test: `apps/tests/test_hr_attendance_export.py`

**Interfaces:**
- Consumes: `build_days`, `month_totals`, `issues.list_issues`.
- Produces `build_workbook(year, month) -> Workbook`; endpoint `GET month/export/?month=YYYY-MM`, needing `can_export`.
- Sheets: `الملخص الشهري`, `يوم بيوم`, `بنود للمراجعة`.

- [ ] **Step 1: Write failing tests**

`test_three_sheets`; `test_summary_matches_month_api` (same totals for a fixed fixture); `test_formula_name_is_neutralised`: `name_ar='=1+1'` isn't stored as a formula; `test_no_bare_branch_code` (branch label is used); `test_unresolved_and_flagged_are_listed`; `test_no_money_columns`; `test_month_boundary_matches_screen`; `test_export_is_audited`; `test_view_without_export_403`.

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement** with `core.export_safety.safe_sheet` and `neutralise_formulas`. Right-to-left sheets. Label the "no punches" column `بدون بصمات`.

- [ ] **Step 4: Run tests**: PASS.

- [ ] **Step 5: Commit**: `feat(hr): monthly attendance Excel export`.

### Task 9: Alerts, scheduler and freshness

**Files:**
- Create: `apps/hr/attendance/health.py`, `apps/notifications/migrations/<next>_attendance_alert.py`
- Modify: `apps/notifications/models.py` (new `notification_type` `attendance_alert` and `TYPE_CATEGORY`), `apps/sync/tasks.py`, `apps/tests/test_scheduler_locks.py` (`SCHEDULER_JOB_GUARDS`), `apps/sync/freshness.py`
- Test: `apps/tests/test_hr_attendance_health.py`

**Interfaces:**
- Consumes: `manager_recipients()`, `Notification.send_to_user(staff, notification_type, title, body, dedup_key=..., bypass_role_gate=True)`.
- Produces `health.check_attendance_health(now=None) -> dict`; freshness domain `attendance` (`cadence_min: 60`, `kind: 'snapshot'`, source from `CollectionRun`, as `_source_stock_audit` does).

- [ ] **Step 1: Write failing tests**

- `test_machine_silent_24h_alerts`, and not at 23h.
- `test_agent_silent_3h_alerts`, and not at 2h59.
- `test_drift_over_5_min_alerts`, and not at 300 s exactly.
- `test_log_count_fall_alerts`: previous 3,906 and current 120 alerts; a rise doesn't.
- `test_failed_run_does_not_count_as_fall`.
- `test_alert_deduped_per_day`, and `test_only_managers_receive`: a view-only grantee gets nothing.
- `test_alert_text_has_no_employee_names`.
- `test_switch_off_no_alerts`.
- `test_inactive_device_no_alert`.

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

Run every 30 minutes, with `max_instances=1`, not in `WRITER_JOBS` (no SOFTECH writes). The dedup key includes kind, device or agent id, and date, with `dedup_once=True`. Add the job to `SCHEDULER_JOB_GUARDS`.

- [ ] **Step 4: Run tests**: `apps.tests.test_hr_attendance_health apps.tests.test_scheduler_locks`: PASS.

- [ ] **Step 5: Commit**: `feat(hr): attendance health alerts and freshness`.

### Task 10: Attendance screen

**Files:**
- Create: `frontend/src/pages/HRAttendancePage.jsx`, `frontend/src/pages/hr-attendance/MonthTab.jsx`, `DaysTab.jsx`, `IssuesTab.jsx`, `EmployeesTab.jsx`, `DevicesTab.jsx`
- Modify: `frontend/src/App.jsx` (route `hr/attendance`), `frontend/src/api/client.js` (`hrAttendanceApi`), the sidebar next to wherever `can_pic_analytics` is used (`grep can_pic_analytics frontend/src`)

**Interfaces:**
- Consumes: Task 7 and 8 endpoints; `me/` returns the access dict.
- Tabs are `month`, `days`, `issues`, `employees`, `devices`; they call `useHelpTab(tab)`.

- [ ] **Step 1: Build the tabs**

- All grids use `useSortableRows`/`useServerSort` + `SortTh`; `useGridKeyboard` on the link review grid.
- Hide Manage and Admin controls using `me/`; the server still decides.
- **Month:** totals per employee; a row click opens Days in place, with no modal.
- **Days:** first, last, hours, flags; expand for raw punches and machine; `بدون بصمات` as neutral text.
- **Issues:** unknown IDs grouped per ID with "add as employee" and "ignore" (reason required), inline.
- **Employees:** machine name next to `name_ar`, link suggestions, confirm/reject, "generic login", hold with reason.
- **Devices:** machines and agents, clock drift, last contact, and "collect now" with `ProgressBar` (machines finished out of assigned).
- `DataFreshnessBar` in domains mode with `attendance`. Use `BL`/`useBranchLabels` and «سيرفر». Keep Arabic text consistent with `apps/help/content/hr.py`.

- [ ] **Step 2: Build and lint**

Run: `cd frontend; npm run lint; npm run build`
Expected: both pass.

- [ ] **Step 3: Verify in the preview**

Start through `preview_start`, sign in with the project's test values, and seed fake employees and punches in the dev database. Check all 5 tabs for console errors, RTL and a phone-width layout; take a screenshot; confirm a non-granted user can't open the page or its API.

- [ ] **Step 4: Commit**: `feat(hr): attendance screen`.

### Task 11: Help, documentation and final sweep

**Files:**
- Modify: `apps/help/content/hr.py`, `docs/architecture/02_MODULE_REGISTRY.md`, `docs/architecture/03_DATABASE_DICTIONARY.md`, `docs/architecture/11_ERP_INDEX.md`, `docs/security/PERMISSION_MATRIX.md`
- Create: `docs/deploy/2026-11-attendance-agent-go-live.md`
- Test: `apps/tests/test_help.py` (existing)

- [ ] **Step 1: Add help**

Add Arabic and English help for route `/hr/attendance` and each tab, with the `updated` date, and tours per `docs/architecture/28_IN_APP_HELP.md`.

- [ ] **Step 2: Write the go-live runbook**

Cover in this order:
1. Choose the office PC and test its path to all 8 machines.
2. Confirm how the agent reaches the office ERP, over the office network or VPN only.
3. Run the import as a dry run, then `--apply`.
4. Seed machines and confirm locations.
5. Issue the agent secret.
6. **First-contact test on one reachable machine:** log read works (it was never tested on a real machine), with the ZK program connected at the same time, and a staff member can punch during the read.
7. Enable all machines.
8. Grant the HR head and team.
9. Start the one-month parallel check.
10. Note the VPS switch-over step: change one agent setting, and let the resend cover any gap.

- [ ] **Step 3: Run everything**

Run: `.\venv\Scripts\python.exe manage.py makemigrations --check`, `.\venv\Scripts\python.exe manage.py test apps.tests.test_help`, then all `apps.tests.test_hr*`, `apps.tests.test_attendance*`, `apps.tests.test_scheduler_locks` and `apps.tests.security` serially, `bandit` as CI runs it, and `cd frontend; npm run build`.
Expected: all pass; no new `# nosec`, `# noqa` or baseline line without a written reason.

- [ ] **Step 4: Check each Definition of Done item**

Go through the spec's list and CLAUDE.md's security list, and name the test or file that proves each.

- [ ] **Step 5: Commit**: `docs(hr): attendance help, architecture docs and go-live runbook`. Then re-check migration numbers against `origin/main` and open a PR for owner review. Don't enable `HR_ATTENDANCE_ENABLED` anywhere.
