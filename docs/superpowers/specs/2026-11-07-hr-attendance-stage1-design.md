# HR Attendance — Stage 1: Employee List and Fingerprint Punch Collection

Status: design, awaiting owner approval. Nothing is built.

## Why

Attendance today runs through a chain of manual steps: fingerprint machines → the ZK "Attendance Management" program at the main branch → a CSV/Excel export → premade Excel templates (hours, لائحة and labour-law rules, weekly off, leaves) → a summary → the salaries workbook.

The owner names **data extraction and entry into the Excel templates** as the step that takes longest and causes the most mistakes and disputes. The long-term goal is the whole chain inside the ERP and joined to the HR module.

This document covers only Stage 1, the part that removes extraction work and touches no money.

| Stage | Scope | Status |
|---|---|---|
| **1** | Employee list, automatic punch collection, HR review screen, monthly export | This document |
| 2 | Lateness, penalty, weekly-off and leave rules | Blocked: needs a filled attendance template and a raw ZK export |
| 3 | Salary calculation | Blocked: depends on Stage 2 and a filled monthly salary sheet |
| Later | Adding and removing users and copying fingerprints on machines | Separate design, after Stage 1 is stable |

## Goals

1. One employee list, keyed by HR number, with each person appearing once.
2. Every punch from every reachable machine saved automatically, at least daily, without manual export.
3. A screen where the HR head sees each employee's month and can spot problems: missing punches, machines that stopped reporting, unknown IDs.
4. A monthly Excel export the HR team can use with their current templates.
5. Run alongside the ZK program without disturbing it.

## Non-goals

- Any calculation of pay, penalties, lateness, overtime or deductions. Daily hours are shown as a time comparison only.
- Deciding whether a day is an absence, a weekly off or a leave. A day with no punches is shown as "no punches", never as "absent".
- Writing anything to a fingerprint machine.
- Reading, storing or copying fingerprint templates, device passwords or card numbers.
- Any read from or write to SOFTECH attendance tables. They are effectively dead (below), and Stage 1 has no need for them.
- Replacing the ZK program.
- Employee self-service or branch-manager views of attendance. HR head and admins only in this stage.

## Anti-goals (a failure even if it technically works)

- A punch is lost, or silently altered. Raw punches are the evidence in any dispute.
- A machine's logs are cleared or the machine is paused by our software.
- A person is linked to the wrong employee because two numbers happened to match.
- Salary, national ID, bank, phone or religion data is copied into the ERP "because it was in the file".
- Staff outside HR can see colleagues' attendance.

## Evidence (read-only probes, 2026-11-06 and 2026-11-07)

**HR number.** The HR head assigns the number on the machine, and it is the same number as the salary sheet's `كود الموظف` (owner). In the salaries workbook, all 12 people compared who have a real name on a machine agree with the sheet (two machine names are only a first name).

**Payroll.** The salaries workbook lists 55 employees with 55 unique codes. The owner confirmed these 55 are everyone paid.

**Machines.** Five answered the standard ZK protocol from the office network with no comm key. All show firmware Ver 6.60 and platform JZ4725_TFT.

| Name in ZK program | IP (port 4370) | Model | Serial | Users | Logs (capacity) | Reached by our probe |
|---|---|---|---|---|---|---|
| HQ | 192.168.1.15 | Unknown | A2NC173961011 | ? | ? | No. Also disconnected in the ZK program |
| Drg Store | 192.168.1.14 | K12/ID | A2ML182760598 | 16 | 2,579 (?) | No. Connected in the ZK program |
| BabAlhded | 192.168.1.13 | K12/ID | A2ML182760559 | 49 | 3,930 (?) | No. Connected in the ZK program |
| Alia | 192.168.30.15 | K12/ID | A2ML173860738 | 23 | 2,241 (100,000) | Yes |
| Ain Shams | 192.168.3.15 | K14 | OEG6090486091100521 | 64 | 3,906 (50,000) | Yes |
| Giza | 192.168.4.15 | K14 | OEG6090486091100070 | 110 | 2,804 (50,000) | Yes |
| Mohsen | 192.168.70.15 | K14 | A2NC173960786 | 105 | 2,942 (50,000) | Yes |
| 8 | 192.168.5.15 | K30/ID | A8ME185060308 | 21 | 2,351 (80,000) | Yes |

Counts for Drg Store and BabAlhded come from the ZK program screenshot.

**Rosters.** The five reachable machines hold 323 entries for 240 distinct IDs (905–1712). The name field repeats the ID on 217 entries, is blank on 38, and holds a Latin name with no spaces on 68. Of the 55 payroll codes, 44 are on these machines; 11 are not (6 stores, 4 management, 1 call center) and may be on the unreachable machines. 196 machine IDs are not on payroll, cause unconfirmed.

**Machine numbers are not unique.** HQ, Drg Store and BabAlhded all show MachineNo 1. Identify machines by serial number.

**Clocks.** The five machines agree with each other within about 5 seconds, and were about 3 minutes behind the laptop that probed them. Which clock is right is unknown.

**Logs.** Low counts against capacity suggest something may clear them. The owner isn't sure. An attempt to read log date ranges failed because the laptop lost its office VPN. **Assume logs can be cleared at any time.**

**SOFTECH.** `empdailyattendance` holds only 2018 data and invalid dates, and the other attendance tables are empty at HQ. `users.usercode` is a login, not an employee number: of 96 machine IDs that equal a usercode, the 9 with a real machine name gave 2 same people, 6 different and 1 generic login. **Never link on a matching SOFTECH number alone.**

**ERP.** `StaffProfile.hr_code` is blank for all 92 staff, while HR requests expect it. There are 92 logins for 55 paid people, including generic logins. HR request tables are nearly empty (2 leave requests). `AttendanceRecord` (GPS check-in) has 0 rows. There is no HR role, and `/api/hr/` is deliberately open to all staff for self-service.

## What gets built

### 1. Employee list (`apps/hr`)

A new `Employee` record per paid person, keyed by HR number.

- **Fields:** HR number (unique), Arabic name, department, job title, work location, optional branch, daily hours, status (active / left), start and end date of employment if known.
- **Optional links:** ERP `StaffProfile` (one-to-one) and SOFTECH usercode. Both may be empty, because staff such as office boys have no login.
- **Relationship to `StaffProfile`:** an `Employee` holds no login data and doesn't replace `StaffProfile`. Confirming a link writes the HR number to `StaffProfile.hr_code`, so existing HR requests connect to the right person. Linked requests stay as they are.
- **Link review:** the system suggests ERP-login matches from names. The HR head confirms or rejects each. Number equality alone never creates a link, and generic logins (cashier accounts) stay unlinked.
- **SOFTECH `personcode`:** left out of Stage 1. 22 machine IDs equal a `personsdata2.personcode`, which needs checking first and isn't needed yet.

**One-time import from the salaries workbook.** A management command with a dry-run preview. It reads only: `كود الموظف` (AV), `اسم الموظف` (BC), `الادارة` (AX), `القسم` (AY), `الفرع` (AZ), `الوظيفة` (BA), `عدد الساعات الاساسية` (AT).

- It takes the file path as an argument. The workbook is never added to the repository.
- It must not read pay, ID number, insurance, bank, phone or religion columns.
- `الفرع` values such as «الادارة», «المخازن» and «كول سنتر» aren't branches. Keep the value as work location, and set the branch only where it maps cleanly.
- Seven employees have no daily hours. Leave these empty and show "not set".

### 2. Machines

An `AttendanceDevice` record per machine: serial (the identity), name, IP, port, model, optional branch or location label, assigned agent, active flag, last contact, last collection outcome, last clock drift. Managed on a screen by admins. Seeded from the table above.

The physical location of "Alia" and "8", and the branch of each machine, must be confirmed by the owner when seeding. Don't guess.

### 3. Collection agent

A small program on a separate always-on office PC (owner's choice), not on a SOFTECH server. It connects out to the ERP, so nothing needs to reach into the office network from the ERP server.

**Where punches go.** The office ERP is still the live one (owner), so the agent sends there first. Three things follow:
- **The ERP address is configuration,** so the VPS switch-over changes one setting. HTTPS is required once on the VPS.
- **The office ERP's address must be reachable and steady from the agent PC.** If the ERP runs on a laptop that can leave the office network or lose its VPN (this happened during the probes), punches wait in the agent's spool until it returns. Collection continues, but the screens fall behind. Because the office instance may not have HTTPS, its connection stays on the office network or VPN and never crosses the public internet.
- **At the switch-over,** punches move with the database. Only one ERP receives punches at a time, like the existing writer rule. After the switch, the agent resends what the machines still hold, and uniqueness makes that safe, which covers any gap.

- **Machine list:** the agent gets its machines from the ERP. Each machine is assigned to one agent, so a second agent can be added if no single PC reaches all eight. The design shouldn't assume there will be more than one, and collect-now is routed through this assignment.
- **Comm key:** if a machine turns out to need one (the 192.168.1.x machines are unprobed), it's kept in the agent's local configuration, never in the ERP. The non-goal about device passwords is about passwords of users on the machine.
- **Each run, per machine:** connect, read the clock, read the user list (ID, name, privilege only) and the attendance log, disconnect, then send to the ERP.
- **Schedule:** every 60 minutes. Reading the full log each time is acceptable at these sizes.
- **Local spool:** data is written to disk before sending and removed only after the ERP acknowledges it, so internet outages lose nothing.
- **Failures are isolated:** one unreachable machine doesn't stop the others, and every outcome is reported.
- **"Collect now":** the agent polls the ERP for a request, which gives the screen a refresh button without any inbound connection.

**Allowed device commands, enforced in code and by a test:** connect, disconnect, read options, read sizes, read time, read user table, read attendance log, free buffer. The agent has no code path for clearing logs, disabling the device, changing the clock, restarting, or writing or deleting users, and never requests fingerprint templates. If a third-party library such as pyzk is used, it is wrapped so that only these commands can be reached.

**Coexistence:** before the first scheduled run, test on one machine that the ZK program and the agent can both connect, and confirm the agent doesn't interrupt punching.

### 4. Ingest API

Endpoints under a new prefix with their own authentication, used only by agents: get assigned machines, submit punches, submit rosters, report outcomes, poll for collect-now.

- **Authentication:** a per-agent secret in a header, stored hashed, compared in constant time, and revocable from the screen. Agent requests carry no staff login and don't use the JWT flow. Access is limited to these endpoints.
- **Idempotent:** a punch is unique on (device serial, user ID, device timestamp, state). Resending is safe and is expected.
- **Add-only:** agents can't change or delete a stored punch.
- **Payload limits:** a maximum batch size and basic validation, returning per-batch accepted and duplicate counts.

### 5. Stored data

- **`AttendancePunch`:** device, machine user ID as sent, the device's timestamp exactly as sent, state, verify mode, received time, resolved employee (nullable). Immutable: no edit or delete through the API or the screen. A later correction is a separate record (Stage 2).
- **`DeviceUser`:** the latest roster per machine, with first-seen and last-seen, to show who is enrolled where and flag IDs not on payroll. Entries are never removed from a machine by this stage.
- **`CollectionRun`:** agent, device, start and end, records read, new and duplicate counts, oldest and newest punch, clock drift, outcome, error text. Error text follows `core/errors.public_error` and contains no secrets.

**Time handling.** Store the device's local time as given, treated as Africa/Cairo, alongside received time. Never shift a stored punch. Record drift each run, and warn when a machine differs from the server by more than 5 minutes. Don't correct clocks (that's a write).

**Bad dates.** Past records show dates from 1900 to 2133. A punch with a timestamp more than 1 day in the future, or before 2015, is stored but flagged and left out of totals.

**Resolving a punch to an employee.** The HR number is the machine number (owner), so a punch resolves automatically when its ID equals an employee's HR number, with two guards. If the machine holds a real name that conflicts with the employee's name, or the same ID has different real names on different machines, that ID goes to the HR head's review and its punches stay unresolved until decided. If an employee has start or end dates, punches outside them stay unresolved, which protects against a reused number. The anti-goal about matching numbers applies to logins and SOFTECH codes, not to this ID.

**Unknown IDs.** Punches from IDs not on the employee list are always stored and left unresolved. If the ID is added later, they resolve then. The issues tab groups them per ID (last punch, machines, count), so they don't swamp it, and the HR head can either create an employee from one, or mark it as ignored with a reason. An `Employee` has a type (payroll / non-payroll), so a person working but not paid through the sheet can get a row. The first collection will show how many of the 196 non-payroll IDs are still punching; any screen detail that depends on this number can be adjusted then.

### 6. Attendance screen

A new `الحضور والبصمة` page, under the HR area, with these tabs:

- **الشهر (month):** one row per employee, with a click-through to days.
- **يوم بيوم (day by day):** per employee, with first and last punch, all raw punches on expand, and flags.
- **تنبيهات (issues):** missing punches, unknown IDs, flagged dates, drift.
- **الموظفون (employees):** the list and the link review queue.
- **الأجهزة (machines):** state of each machine and agent, last contact, and "collect now".

**Daily view rules, display only:**
- Punches are grouped into work days per employee, using a work-day boundary (default 04:00, so a punch at 02:00 belongs to the previous day). The sheet has a `بدل سهر` allowance, so overnight work is real. Boundary configurable per employee.
- First punch = in, last punch = out. Machine in/out state is stored but not trusted for this.
- A single punch on a day is flagged "needs review" and contributes no hours.
- Punches within 2 minutes of each other are treated as one for display. Raw punches are all kept.
- Approved `LeaveRequest` and `Permit` records show on matching days, for information only.
- Multiple machines are combined; each punch shows its machine.

**Monthly totals per employee:** days with punches, worked hours, daily hours × days with punches (expected time for comparison), days needing review, days with no punches. No money and no verdicts.

**House rules:** calm UI with no modals for common actions; sortable grids (`useSortableRows` / `SortTh`, `core sort_ordering`); `useGridKeyboard` on the link review grid; `BL` / `useBranchLabels`, never a bare branch code; «سيرفر» wording; a `ProgressBar` for collection; freshness and refresh through the FreshnessBar domains pattern with a new attendance domain.

### 7. Monthly export

Excel through `core/export_safety.py`, for a chosen month. Sheet 1 has monthly totals per employee. Sheet 2 has one row per employee per day. A third sheet lists unresolved and flagged items, so that nothing is hidden.

**Known limit:** this can't match the current templates until a filled one is seen, so staff may need to copy into them at first. Matching the layout is a follow-up once the file arrives.

### 8. Alerts

Through existing notifications to attendance managers: a machine with no successful collection for 24 hours, an agent silent for 3 hours, drift over 5 minutes, and a log count that falls between runs. **That last one is evidence of clearing**, and it answers the open question over time.

## Access and security

- **New RBAC module `hr_attendance`,** added to `MODULE_CHOICES` and `seed_permissions.py`, with `PERMISSION_MATRIX.md` regenerated. Default: admin only. Don't widen the existing self-service `hr` module.
- **Access levels:** there is no HR role, and `can_do` works by role only, so use a named grants table following the `apps/pic_analytics/access.py` pattern. Don't add a new role in this stage. Three levels, and "attendance managers" in this document means the first two:
  - **View:** see all tabs, export.
  - **Manage (the HR head):** the above, plus confirm links, edit employees, decide unknown IDs. Confirming a link writes `StaffProfile.hr_code`, so this level is separate from View.
  - **Admin role only:** machines, agents and agent secrets.
- **API prefixes:** map them in `core/middleware/module_access.py` (`MODULE_BY_PREFIX`), and give the agent prefix an `EXEMPT_PREFIXES` entry with a comment naming its gate. Check that the network and device zoning in `apps/access` allows the agent route.
- **Branch scoping:** company-level by decision: only HR head and admins see this data. Say so in the code as `core/branch_scope` expects, and keep the canary planter able to build the new models.
- **SOFTECH:** no reads and no writes in Stage 1. Nothing is added to the write manifest.
- **Privacy:** no phone or ID columns are imported. No names or punch data in logs. Exports through `core/export_safety.py`. Fingerprint templates are never read.
- **Audit (`AuditLog`):** link confirm and reject, employee edit, status change, device edit, agent secret issue and revoke, collect-now, export.
- **Staff notice:** attendance is already recorded, so this is not new surveillance, but a line in the HR policy about the ERP holding it should go with the PDPL employee-data check already noted for P-57.
- **Retention:** keep raw punches indefinitely for now, because of dispute and legal use. To be revisited with the PDPL check.
- **Switch:** `HR_ATTENDANCE_ENABLED`, default off, in the existing settings pattern. Ingest refuses when off.

## Definition of done

Each of these is required, and items 1–6 are checkable by test or by reading the output.

1. Every item in the project's "Security definition of done".
2. A test proves the agent can't send a command outside the allowed list.
3. Sending the same punches twice creates no duplicates; a punch can't be edited or deleted through any API.
4. Import dry-run on the real workbook shows 55 employees and reads none of the excluded columns (test with a fixture that has those columns populated).
5. No link is created without a confirmation; a generic login can't be linked.
6. Non-granted users get 403 on attendance screens and APIs, including branch managers. A View grant can't confirm links, and only the admin role can manage machines and agent secrets.
7. In-app help for every new tab, Arabic and English, with `apps/tests/test_help.py` passing.
8. Tests, lint and frontend build pass; `docs/architecture` updated (02, 03, 11).

**Rollout:** collection can start on the machines the agent reaches. Stage 1 isn't done until every machine that is working in the ZK program is collected. A machine that's also down there (HQ today) is a logged exception.

**Parallel run (owner-visible success):** for one full month, the HR team's manual extract and the ERP are compared per machine and per employee. Stage 1 is successful when every punch in the manual extract is in the ERP, and the HR team can produce the month's attendance without using the ZK export. No comparison tool is built in Stage 1: the export's raw day sheet and the per-machine counts support a manual check. Once a raw ZK export is available, a one-off script does the full comparison, and its format is checked then.

## Decisions

### Owner's
- All of it should end up in the ERP, joined to HR.
- HR number = the machine number = the salary sheet code, assigned by the HR head.
- The 55 on the sheet are everyone paid.
- Extraction and entry is the first pain to remove.
- Punches start on the office ERP, which is still live.
- The agent runs on a separate office PC, not a SOFTECH server.
- The HR head and named HR team members get access.

### Claude's calls, open to correction
- Start with Stage 1 and no money.
- An outbound agent rather than a router rule.
- Moving punches at the switch-over with the database, plus a safe resend.
- 60-minute collection.
- `Employee` as a new record, linked to rather than replacing `StaffProfile`.
- Work-day boundary at 04:00, 2-minute duplicate window, 5-minute drift warning, and the date cut-offs for flagged punches.
- Named-grant access with three levels, and no new role.
- Automatic punch-to-employee resolution with the name-conflict and date guards.
- A non-payroll employee type and per-ID review of unknown IDs.
- Per-machine agent assignment, and a comm key held only on the agent.
- A manual parallel-run check, with no comparison tool built in Stage 1.
- Keep raw punches indefinitely.
- Leave `AttendanceRecord` (GPS) and mobile check-in untouched; they are unused and out of scope.

### Left to the builder
- Library versus own protocol code (a working standard-library read was used for the probes; it isn't production code).
- Agent packaging as a Windows service or scheduled task.
- Exact model and endpoint names, and batch sizes.

## Open items for the owner

None of these change what gets built, but each is needed before go-live.

1. **Which office PC runs the agent.** It must stay on and reach all 8 machines and the ERP.
2. **Access names.** ERP usernames of the HR head (Manage) and the HR team members (View), or a note that someone needs a login created.
3. **Machine locations.** The real location of "Alia" and "8", and which branch each machine belongs to.
4. **The HQ machine.** It's disconnected in the ZK program too. It needs a physical or network check.
5. **The network path to the 192.168.1.x machines** from the chosen PC. They timed out from the laptop used for the probes.
6. **How the agent reaches the office ERP** (see "Where punches go").

## Risks

- **Clearing before collection:** if something clears logs often, punches from before the first run may be gone. Mitigated by hourly collection and the log-count alert. History on the machines at first contact is all we can recover from them.
- **ZK program conflict:** concurrent sessions are untested. Tested on one machine first, and easy to back out.
- **Old firmware:** 2015–2018 firmware may behave oddly on long reads. Reads of user tables worked on five machines; log reads are untested.
- **Egypt's daylight-saving changes:** machine clocks may not follow them. Drift warnings will show this; Stage 2 must decide how it affects hours.
- **Doubling punches across machines:** someone may punch on two machines on the same day. They're combined by employee, so first and last are still right.
