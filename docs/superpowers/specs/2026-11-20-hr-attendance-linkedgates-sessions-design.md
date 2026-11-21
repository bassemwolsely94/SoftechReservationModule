# HR Attendance: Linked Gates source and work sessions (Stage 1b)

**Date:** 2026-11-20
**Status:** approved by the owner 2026-11-20
**Builds on:** Stage 1 (`docs/superpowers/specs/2026-11-07-hr-attendance-stage1-design.md`, PR 91 on main).
**Not in scope:** lateness, penalties and salaries (Stages 2 and 3).

## 1. Why

Today HR builds attendance by hand, every month:
1. The Linked Gates HR portal (192.168.5.43) pulls the punches from the fingerprint machines.
2. HR exports "Calculate Logs" (first in and last out per day).
3. HR reformats the export and fixes it using the "Employee Check" screen. Evening and night shifts and managers with several in/outs come out wrong.
4. HR pastes the result into the Excel template that calculates salaries.

The owner wants the whole chain automated. This stage covers the data part:
- getting every punch reliably, both from the machines and from Linked Gates
- grouping the punches into correct working days

Stages 2 and 3 then produce the salary file from those days.

## 2. What we learned about Linked Gates (2026-11-20, read-only)

- **Where it runs:** Hyper-V virtual machine "PC HR" on host HQ-HV01. It runs IIS with an ASP.NET MVC app, on SQL Server 2019 Express (`HR\SQLEXPRESS`).
- **Database access:** the database isn't reachable over the network; port 1433 is closed.
- **Live database:** `Linked_ERP_HR_v1`. `Linked_ERP_HR_v2`, `hrdemo` and `Test2025` aren't used.
- **Tables we use:**
  - `EmployeeCheck`: punches, about 764K rows since 2015-08.
  - `Device`: 17 rows.
  - `Employee`: 686 rows.
  - `Department`: 16 rows.
- **Tables we ignore:**
  - `EmployeeTimeCard` (1.85M rows, all with an empty status)
  - `Sheet`, `Sheet2`, `Query1` (old imports)
- **Private data we never read:**
  - `Employee.Salary`, `Phone`, `Email`, `EmployeeImage`
  - the `Users` and `UserPermissions` tables
  - `Device.Password`
- **How punches arrive:** `Insert_into_employeeCheck` maps a machine by its IP address.
  - Two IPs appear twice in `Device`: 192.168.30.15 (Alia 4023 and the old Aliaa 4021) and 192.168.20.15 (two Amany rows).
  - A punch from an unknown IP is stored with `DeviceID` NULL. There are 3,430 such punches; 3,429 were created by user 1 between 2021 and today.
- **The Calculate Logs screen writes data.** `sp_CalulateLogs`:
  - fills the missing `EmployeeID` values in `EmployeeCheck`
  - runs `sp_FillTimeCardGapes`
  - runs `SP_Removeduplicaterows`, which deletes exact duplicates of (EnrollNo, CheckTime, DeviceID)

  Our login must never be able to run any procedure.
- **Linked Gates' day rules** (views `CheckIn` and `CheckOut`, joined in `CalculatedLogs` and `View_All_Checks`):
  - **ShiftType 1:** in = the earliest punch between 07:00 and 14:00 on the calendar date. Out = the latest punch after 14:00.
  - **ShiftType 2:** in = the earliest punch between 08:00 and 21:00. Out = the latest punch after 21:00.
  - **Any type:** a punch between 00:01 and 01:59 counts as the previous day's out.
  - **Known losses:**
    - People with no ShiftType (9 people) get no days at all.
    - Punches between 02:00 and 07:00 are ignored.
    - A night shift from 23:00 to 08:00 is split across two days.
    - A same-date afternoon punch hides an after-midnight out.
    - Grouping by device or by in/out mode can give one person several "in" rows on the same day.
- **Punch hours (last 60 days):** almost none between 02:00 and 05:00.
  - Type 1 people punch around 08:00, 16:00–17:00 and 00:00–01:00. That's a mix of morning and evening staff.
  - Type 2 people punch around 00:00, 15:00–16:00, 23:00 and 08:00. That's evening and night staff.
  - ShiftType therefore isn't a reliable shift label.
- **The in/out button can't be trusted:** in the last 30 days there were 1,296 "in" punches against 1,081 "out".
- **Matching people:** `Employee.EnrollNo` = `HRCode` for 684 of 686 employees. The two exceptions (1360/905 and 1580/15801) aren't on payroll.
  - `Status` = 1 for all 686, so Linked Gates can't tell who still works here.
- **Machines:** 7 sent punches in the last 30 days: BabElhadid, Ain Shams, Mohsen, Balegh, Wearhouse, Alia and Zahar.
  - Head Office, Marian, Michael, Rashidi, Shady, Shoubra and Amany are closed, per the owner. Ehab and Aliaa are already inactive in Linked Gates.
  - Mohsen holds a punch dated 2116 (wrong clock).
- **Several machines per person:** in the last 30 days, 11 people used 2 machines and 1 person used 3.

## 3. Goals, non-goals, anti-goals

**Goals**
1. **Two sources, compared every day:** our own machine collection (Stage 1 agent) and a read-only copy of Linked Gates' punches.
2. **Correct working days for every shift pattern:** morning, evening, night, double shifts and managers' several in/outs, with no setup per employee.
3. **During the trial, show Linked Gates' own numbers next to ours,** with the reason for every difference, so HR can trust ours before relying on it.
4. **Fix the machine names in our system** to match Linked Gates (Balegh, not Giza; Zahar, not "8"). Add the two 192.168.1.x machines and mark the closed ones.

**Non-goals (this stage)**
- lateness, overtime, penalties, salaries and the Excel salary template (Stages 2 and 3)
- replacing Linked Gates. It stays the place where fingerprints are added to the machines.

**Anti-goals**
- **Never write to Linked Gates or to a machine:** no procedure calls, no clearing logs, no clock changes.
- **Never read salaries, phone numbers or passwords from Linked Gates.**
- **Never decide money here.** These are display figures only, as in Stage 1.
- **Never silently prefer one source.** Every difference is shown.

## 4. Approaches considered (owner picked A on 2026-11-20)

- **A. Work sessions, plus a comparison with Linked Gates (chosen).** Punches are grouped by the time gap between them. There are no fixed windows and no per-employee setup. Linked Gates' numbers are reproduced alongside ours for comparison.
- **B. Copy Linked Gates' rules.** HR knows them, but we would inherit all the losses in section 2. Rejected.
- **C. A fixed shift schedule per employee.** The most exact option, but it needs everyone set up first and breaks on shift swaps. It's deferred to Stage 2, and used only for measuring lateness, never for deciding which day a punch belongs to.

## 5. Design

### 5.1 Where things run
- **Our agent runs on PC HR (192.168.5.43)**, the PC the owner named. From there it reaches all 7 live machines, including the two 192.168.1.x machines this laptop can't reach. It does two jobs:
  1. **Machine pull (existing Stage 1 code):** short, read-only reads. Timing is set apart from the Linked Gates pull. If a machine is busy, the agent backs off and tries later instead of forcing a connection.
  2. **Linked Gates read (new):** reads `Linked_ERP_HR_v1` on the same PC through a read-only login. It uses the IT note: `db_datareader`; DENY INSERT/UPDATE/DELETE/EXECUTE/ALTER; and column DENYs on the private fields.
- **Connecting to SQL Server:** through ODBC on the same PC. No network exposure is needed.
- **Login type:** a Windows login is preferred (no password). If a SQL login is used, its password lives only in `agent.ini` on PC HR.

### 5.2 What we copy from Linked Gates
- **New model `LinkedGatesPunch`:** append-only, unique on `lg_check_id` (= `EmployeeCheckID`). Fields:
  - `enroll_no`
  - `check_time`
  - `lg_device_id` (nullable)
  - `in_out_mode`
  - `created_by_lg` (the CreatedBy number, kept as is)
  - `received_at`
  - `employee` (FK, resolved by `enroll_no` = `hr_number`, the same resolver as machine punches)
- **What gets read, and how:**
  - `EmployeeCheck` is read incrementally: `EmployeeCheckID > last seen`, in batches of 5,000.
  - The first load starts at a date HR picks (default: 1st of last month).
- **Deleted rows:** Linked Gates deletes exact duplicates. A copied row whose source later disappears is kept on our side (append-only) and marked `lg_removed` by a weekly check of ID ranges.
- **Reference copies (refreshed daily, no history):**
  - `LinkedGatesDevice`: id, name, IP, status
  - `LinkedGatesEmployee`: EmployeeID, EnrollNo, HRCode, first and last name, DepartmentID, ShiftType, IsManager, Status
  - `Department` names
- **Device mapping:** each `LinkedGatesDevice` maps to one `AttendanceDevice` (a manage-only screen). Default: match by IP. The duplicate-IP rows are mapped by hand once.

### 5.3 Work sessions (replaces the fixed 04:00 boundary for day grouping)
- **Which punches count:** all of a person's usable punches from both sources, merged and de-duplicated. The same moment within 2 minutes counts once, as in Stage 1. Each kept punch remembers its source(s).
- **Sorted by time.** A new session starts when the gap from the previous punch is **more than 6 hours** (`SESSION_GAP_HOURS`, a setting).
- **A session belongs to the date of its first punch.**
  - **Corner case:** a session starting between 00:00 and 03:59 belongs to the previous date. This catches an evening worker whose only punch that night falls after midnight.
- **First punch = in, last punch = out.**
  - **Worked time** = sum of (out − in) over consecutive pairs, in time order (in, out, in, out, …).
  - **Odd number of punches:** the last one is unpaired. The session is flagged `needs_review` and its time counts only up to the last full pair.
- **Display:** a day can hold more than one session, for example a split shift with a gap over 6 hours. The day shows each session plus the day total.
- **Per-employee override:** HR may set a fixed day cut-off for one person (the existing `day_boundary`). If set, it replaces session grouping for that person.
- **Punches never used:**
  - future-dated punches, or punches before 2015 (flag `bad_date`)
  - punches from people not on payroll. These go to the existing "not on payroll" list.

### 5.4 The daily comparison
For each machine and each day:
- **Matched:** the same (person, time within 2 minutes) appears in both sources.
- **Only in Linked Gates:**
  - **"manual / no machine"** if `lg_device_id` is NULL. Otherwise **"missing from our pull"**, which means a collection problem.
- **Only in our pull:**
  - **"not yet in Linked Gates"** if it's less than 24 hours old. Otherwise **"missing in Linked Gates"**.
- **Day-level comparison:** for every employee-day, our session figures sit next to **Linked Gates' figures**, recomputed by us from the copied punches using the rules in section 2. The difference gets a reason code:
  - `lg_night_split`
  - `lg_window_ignored` (a punch outside the windows)
  - `lg_out_hidden`
  - `lg_no_shifttype`
  - `lg_multi_in`
  - `missing_punch`
- **Where it shows:** a new **«مقارنة لينكد جيتس»** tab on `/hr/attendance` (view grant). It lists counts per machine and day, then the employee-days that differ, with the reason. It's sortable and exportable through the shared export path.
- **During the trial, Linked Gates counts for salaries.** After one full month in which every difference is explained, the owner switches the source to ours (a setting). Linked Gates then remains a cross-check.

### 5.5 Machines in our system
- **Rename** "Giza" (192.168.4.15) to **Balegh** and "8" (192.168.5.15) to **Zahar**.
- **Add** BabElhadid (192.168.1.13) and Wearhouse (192.168.1.14).
- **Machine kinds:**
  - `is_active = False`, with a "closed" label: the 7 closed machines (Head Office, Marian, Michael, Rashidi, Shady, Shoubra, Amany), and also Ehab and Aliaa, which Linked Gates already lists as inactive.
  - Live: the 7 machines that still send punches.
- **Alert:** if a closed machine sends punches, raise an alert instead of failing silently.
- **How the change is made:** a data migration or management command with a dry-run default. It never touches the office DB without the owner's word.

### 5.6 Safety and access
- **Read-only, by construction and by test:**
  - The agent's SQL module allows only `SELECT` against a fixed list of tables and columns, the same way the ZK client allows only listed commands.
  - A test fails if any other statement or column appears.
- **The login is locked down:** EXECUTE on every procedure is denied, so `sp_CalulateLogs` can never be triggered from our side.
- **Switches:**
  - `HR_ATTENDANCE_ENABLED` stays the master switch.
  - New `HR_ATTENDANCE_LINKEDGATES_ENABLED`, default OFF.
- **Access:** screens follow the existing `AttendanceAccess` grants. HR head and HR specialists get view or manage access by name.
- **Audit:** mapping changes, the trial-source switch and HR cut-off overrides are recorded (who, when, before and after).

### 5.7 Tests (minimum)
- **Session building:**
  - morning, evening, night (23:00→08:00), double shift, manager with 4 punches, odd punches, split shift with a gap over 6 h
  - a lone after-midnight punch
  - a person on two machines
- **The Linked Gates recompute** reproduces each loss in section 2 on fixtures.
- **Comparison categories,** including NULL-device punches and duplicate IPs.
- **Incremental read:** resumes after the last ID. Reading the same batch twice adds nothing.
- **Guards:**
  - the read-only SQL allow-list guard
  - the private-column guard
- **Help, permissions and performance:**
  - help page updated (Arabic and English) for the new tab
  - permission tests
  - a performance budget row for the comparison list

## 5.8 Decisions settled during review (designer's calls, owner to check)
- **What "ours" and "Linked Gates'" figures are:**
  - **Ours:** session rules applied to the merged punch set, meaning machine punches plus every Linked Gates punch, including the NULL-device "manual" ones.
  - **Linked Gates':** Linked Gates' own rules applied to the Linked Gates punches only.
  - **Display:** the month screen and the Excel export show both columns during the trial.
  - **What the switch does:** in this stage `HR_ATTENDANCE_DAY_SOURCE` (`linkedgates` | `sessions`, default `linkedgates`) only decides which column is marked «المعتمد» and comes first. Stage 3 reads the same setting for salaries.
- **Linked Gates edits rows** (`EmployeeCheck` has `EditBy`/`EditOn`). Besides the incremental read, the agent re-reads the last 45 days every night. A row whose time, person or machine changed is stored as a new version: `LinkedGatesPunch` gets `version` plus `superseded_at`, and older versions stay. Days use the latest version. The comparison screen shows "edited in Linked Gates" with who and when (the `EditBy` number).
- **Machine logs:** neither side clears them. Linked Gates re-reads the full log and de-duplicates, and our agent never clears.
  - On first contact, the agent records each machine's log count.
  - If a count ever drops, raise a "log cleared" alert. "Missing from our pull" stays a real fault.
- **Per-person cut-off:**
  - `Employee.day_boundary` becomes nullable: null = session grouping.
  - A data migration sets the existing 04:00 values to null. The office DB was checked on 2026-11-20: all 55 rows are at the 04:00 default and none was customised.
  - Only a non-null value overrides sessions.
- **Agents:** no Stage 1 agent has ever run. The office DB has 0 agents and 0 punches. The PC HR agent is the only agent, and every live machine is assigned to it in the section 5.5 migration, so no two agents compete for a machine.

- **The Linked Gates collector, "Puma Service":** a Linked Gates program on PC HR built on BiometrixCore and the ZK SDK. Its buttons are Run Now, Set Schedule and Tools.
  - **It runs on request only.** HR presses Run Now when they need the data, and the schedule is not used (owner, 2026-11-20). So there's no fixed Puma time to avoid.
  - **How our agent avoids clashing:** it pulls at night, between 02:00 and 05:00, plus whenever a manager asks. If a machine refuses or times out, it backs off for 10 minutes, assuming Puma is busy, rather than retrying immediately.
  - **Its Tools → Device Panel** offers Download/Upload/Delete Users Data, Get Device Time, Restart and Power Off, with no clear-logs action. Uploads and deletes stay Linked Gates' job; our agent's allow-list keeps excluding all of them.
- **Approval:** the owner approved this design on 2026-11-20 with no changes.

## 6. Open items for the builder (minor, builder's call)
- the batch size and the polling interval for Linked Gates (default every 15 minutes)
- the exact Arabic labels for the reason codes
- whether `SESSION_GAP_HOURS` is global only, or per branch later

## 7. Needed from the owner or IT before go-live
1. **IT on PC HR:**
   - Create the read-only login, following the IT note (`linkedgates_readonly_login_for_IT.md`).
   - Install the agent there, with ODBC Driver 18 for SQL Server.
2. **The ERP usernames of the HR head and the HR specialists,** and whether each gets view or manage access.
3. **A date for the first live run:** switches on, reading only, with someone from HR watching.
4. **For Stages 2 and 3:** one filled salary template, plus the shift start times per branch, for lateness.
