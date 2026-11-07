# Attendance agent go-live (الحضور والبصمة, Stage 1)

For the owner. Plain language, in order. Do not skip a step. Nothing here runs by itself.

What this does: a small program (the "agent") on one office PC reads the fingerprint punches from the
8 ZK machines and sends them to the ERP. The ERP shows them at `/hr/attendance`. The agent only
reads. It never clears a machine, changes a clock or writes to a machine. Stage 1 shows punches only:
no lateness, no penalties, no salaries.

The feature switch `HR_ATTENDANCE_ENABLED` is OFF by default and stays off until step 8.

Facts to keep in mind from the build:

- Reading the punch log has **never been tested on a real machine**. Only user lists were tried.
  Step 8 is that test. Do not enable all machines before it passes.
- The machines on 192.168.1.x were **unreachable from the development laptop**, and the HQ machine
  also shows as down in the ZK program. Check reachability from the office PC first.
- Two machines have an unconfirmed location: `Alia` and `8`. Their location label is empty on purpose.

## 1. Back up and update the office ERP (owner-approved, never automatic)

1. Take a database backup first, the same way the project has done before (a `pg_dump -Fc` of
   `elrezeiky_db` to a folder outside the code folder). Check that the file is not empty.
2. Update the office ERP code to the branch that holds the attendance work, once the owner has
   approved the PR.
3. Run the migrations: `hr` 0007 to 0010, `users` 0054 and `notifications` 0044. Look at the list
   with `python manage.py migrate --plan` first; it should show only those. Then run `migrate`.
4. Restart the ERP web process **and** the scheduler process (both read the settings).
5. Check that `/hr/attendance` is not shown to anyone yet (the switch is still off and nobody has
   access).

## 2. Choose the office PC and test its path to all 8 machines

1. Pick one PC that is always on, with sleep and hibernation turned off. Python 3.12 or newer
   installed. Use a PC whose Windows account only the IT team uses.
2. From that PC, test that each machine answers on its IP and port 4370 (for example
   `Test-NetConnection 192.168.1.15 -Port 4370` in PowerShell). The list is in
   `apps/hr/management/commands/seed_attendance_devices.py`.
3. Write down which machines answer. Any that do not answer need a network fix (route or VPN)
   before they can be enabled. Do not move on for those machines.

## 3. Confirm how the agent reaches the office ERP

1. The agent needs the ERP address that works **from that PC**: the office network or the VPN
   only. Plain `http` is acceptable on the office network or VPN; it must never be a public address.
2. Open that address in a browser on the PC and make sure the ERP login page loads.
3. Note the address; it goes into `agent.ini` in step 6.

## 4. Import the employees (dry run first)

1. Keep the payroll workbook on a private IT folder. **The salaries workbook never goes in the
   repo** and is never committed or emailed.
2. Dry run: `python manage.py import_attendance_employees <path to workbook>`. It writes nothing.
   Read the counts and any skipped rows.
3. If the numbers look right: `python manage.py import_attendance_employees <path to workbook> --apply`.
4. The import only creates the employee list. Linking fingerprint IDs to employees is done later
   on the screen.

## 5. Seed the machines and confirm locations

1. `python manage.py seed_attendance_devices`. It is safe to repeat and never overwrites an edit.
2. In the ERP, as admin, open `/hr/attendance`, tab "الأجهزة" (Machines). Turn each machine's
   **active** switch off for now.
3. Confirm each machine's branch and location label. Set the branch and location for `Alia` and
   `8` once the owner confirms where they stand.

## 6. Issue the agent secret and install the agent

1. On the ERP server: `python manage.py issue_attendance_agent <agent name>`. The secret is shown
   **once**. Copy it straight into `agent.ini`. Do not send it by email or WhatsApp.
2. In the "الأجهزة" tab, assign the reachable machines to this agent.
3. On the office PC, follow `attendance_agent/README.md`: copy the `attendance_agent` folder, copy
   `agent.ini.example` to `agent.ini` **outside the program folder**, fill in the ERP address and the
   secret.
4. `agent.ini` holds the secret and **must stay on that PC**. Never commit it. Restrict it and the
   state folder to the account that runs the agent (the `icacls` line in the README).
5. Do not schedule the agent yet.

## 7. Grant the HR head and the HR team

1. As admin, open `/hr/attendance`, tab "الوصول" (Access). Find the HR head and the team members and
   give each a level: view, manage or export. The HR head gets manage and export; others only what
   they need.
2. Access can only be given here. No access means the screen shows a lock message.

## 8. First-contact test on ONE reachable machine

This is the test that has never been done. Do it with the ZK program open and a staff member
present.

1. Pick one machine from step 2 that answered. Turn on `HR_ATTENDANCE_ENABLED`:
   - Add `HR_ATTENDANCE_ENABLED=True` to the office ERP `.env`.
   - Restart the ERP web process **and** the scheduler process. Without the restart the agent
     endpoints answer 404.
2. Make only that machine active and assigned to the agent.
3. With the **ZK program connected to the same machine at the same time**, run on the office PC from
   the folder that holds `attendance_agent`:
   `python -m attendance_agent C:\ElRezeiky\agent\agent.ini --once --serial <machine serial>`
4. While the read is running, ask a staff member to **punch**. Confirm the machine accepts the punch
   and the ZK program keeps working.
5. Compare the number of punches the agent read with the count the machine shows.
6. Check on the screen (tab "الأيام") that user codes are real ID numbers. A code like `uid-5` means
   the log holds an internal slot instead of the ID. Stop and report it; it needs a decision.
7. If anything is wrong (error, count mismatch, ZK program disturbed, punch refused): stop, turn
   `HR_ATTENDANCE_ENABLED` off again, keep the agent log, and report. Do not go on to step 9.

## 9. Enable all machines

1. Only after step 8 passed. In the "الأجهزة" tab, make the remaining reachable machines active and
   assigned.
2. Schedule the agent with Windows Task Scheduler as written in `attendance_agent/README.md`
   (at startup, restart on failure, one instance).
3. After an hour, check each machine's last contact. A machine silent for hours means the agent or
   the machine is down; the HR head also gets a notification.
4. Handle the "المشاكل" (Issues) tab: link unknown IDs to employees, resolve name conflicts.
5. If the ERP is down, the agent keeps punches in its spool on the PC and sends them when the ERP
   returns. During a long outage this is about **60 MB a day** and there is **no enforced limit**, so
   watch the PC's free disk space. Do not delete spool files by hand.

## 10. One-month parallel check

1. For one full month, keep the manual extraction from the ZK program as it is today.
2. At month end, compare the ERP month export with the ZK result for a sample of employees and days,
   including each branch. There is no comparison tool built in Stage 1; this is done by hand.
3. Only when the owner is satisfied, **consider** stopping manual extraction. This is a decision for
   the owner, not part of the build.

## 11. VPS switch-over

When the ERP moves to the VPS:

1. On the office PC, change **one setting**: the `url` under `[erp]` in `agent.ini` (use `https` for
   the VPS). Restart the agent.
2. Punches the agent holds, and any gap, are covered by its resend. The ERP ignores repeats.
3. Only **one** ERP may receive punches at a time. Turn `HR_ATTENDANCE_ENABLED` off on the office
   ERP when the VPS takes over, and issue the agent again on the VPS if the secrets are not carried
   over.

## Not in this stage

- **Stage 2** (lateness, penalties) and **Stage 3** (salaries) still need a **filled attendance
  template** and a **raw ZK export**. Without them they cannot be built.
- The agent does not change machines in any way.

## If something goes wrong

- Turn `HR_ATTENDANCE_ENABLED` off and restart web and scheduler. Collection stops; nothing is lost
  on the machines or in the agent's spool.
- Agent log: `agent.log` in the state folder (counts and serials only, no names or secrets).
- Log files that could not be read are kept in `spool\quarantine\`. Keep them and report.
