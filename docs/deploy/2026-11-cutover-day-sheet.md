# Cutover day sheet — office → LDC VPS

Print this page and tick each box with initials and the time. It holds **no secrets**: keys and passwords are typed by
the owner from the password manager, never written here and never pasted into a Claude chat.
The full commands are in [`GO_LIVE_CHECKLIST.md`](../GO_LIVE_CHECKLIST.md) §3 (W0–W9), the
[runbook §11](../../deploy/LINKDATACENTER_VPS_RUNBOOK.md) and the [tax cutover steps](2026-11-tax-cutover-steps.md).
If this sheet and those pages ever disagree, **stop and ask**.

Date: ____________ Window start: ______ End: ______ Owner: ______________ Second person: ______________

> **The one rule:** never two SOFTECH writers. From W1 until W6 **nobody** writes to SOFTECH. Never turn the office
> back into a writer while the VPS has any writer flag on.

VPS shell: `ssh bassemwolsely94@41.196.0.34` · app `/opt/elrezeiky/app` · run Django commands as
`cd /opt/elrezeiky/app && sudo -u elrezeiky /opt/elrezeiky/venv/bin/python manage.py <command>`.
Office: the project folder, `venv\Scripts\python manage.py <command>`.

---

## Before the day (all must be ✔ or don't start)

| ✔ | Item | Where |
|---|---|---|
| ☐ | Stage A done: VPS runs as a reader, `writer_status --expect reader` passes | 2026-11-12 status, steps 2–6 |
| ☐ | P-54 switch table signed (A/P and insurance writers decided) | owner steps §3 |
| ☐ | Nightly dump, off-site pull, **one tested restore**, LDC snapshot ticket | owner steps §4 |
| ☐ | Old worktree `.env` copies read-only | owner steps §5a |
| ☐ | Secrets that appeared in chat rotated (SSTP, smoke-test admin, ETA portal) | — |
| ☐ | Ain Shams route on the HQ MikroTik | owner steps §6 |
| ☐ | VPS DB checks: `check_schema_drift` clean, `makemigrations --check` clean, live `auto_repair` value noted: ____ | round-2 SUMMARY "Left open" |
| ☐ | Branches told: system down in the window, new address `https://elrezeikyapp.dawalvry.com` | — |
| ☐ | Today's office writer flags written down (expect 16 ON; boot log line `writer flags ON: …`) | office web window |

---

## Cutover

| ✔ | Step | Where | Do | Pass when | Time / initials |
|---|---|---|---|---|---|
| ☐ | **W0** | VPS | `writer_status --expect reader` | `ROLE = reader`, exit 0 | |
| ☐ | **W1** | office | Run the W1 PowerShell block (checklist §3) on **every** office `.env`. In each, also set `TAX_ETA_READ_PREPROD_ENABLED=False` and `TAX_ETA_READ_PRODUCTION_ENABLED=False`. Restart office web + scheduler | every file prints `READER` | |
| ☐ | **W2** | office | `writer_status --expect reader` | `ROLE = reader`, exit 0; scheduler log says `not the writer instance` | |
| ☐ | **W3** | office | Drain. `/api/pos-orders/queue-status/` queued and push_failed = 0. No ISR / invoice / A/P / insurance item "pushing". No ISR draft proposed or approved. **Tax drain** command (tax steps §W3) | all 0; tax prints `0 0 0 0`. **Anything left → stop and ask** | |
| ☐ | | office | Note the last good time of each sync domain on the freshness bar | written down | |
| ☐ | **W4** | office | Stop everything: close the 4 windows (web, scheduler, AMI bridge, screens), any `runserver` / `run_scheduler` / `daphne`, NSSM `ElRezeikyPlatform` if installed. **Delete `ElRezeiky office start.cmd` from the Windows Startup folder** (it would start web, scheduler and AMI bridge at the next logon). **Disable the 3 Task Scheduler tasks** `ElRezeiky_Daily_Followup`, `ElRezeiky_Transfer_Flag_Check`, `ElRezeiky_Weekly_Summary` (they send reminders and summaries from the office database) | Task Manager: no `python.exe` with `runserver` / `run_scheduler` / `run_ami_bridge` / `daphne`; the 3 tasks show `Disabled` | |
| ☐ | **W5** | both | Final `pg_dump` on the office → copy → restore on the VPS → `migrate` → media rsync → `vacuumdb --analyze-in-stages` (runbook §11.4). Start VPS web + **scheduler**, still a reader (§11.5) | one full sync cycle green; `writer_status --expect reader` still passes | |
| ☐ | | VPS | `omni_credentials` | ends `OK` | |
| ☐ | **W6** | VPS | Kill-switch test: with `SOFTECH_READ_ONLY=True` a writer dry-run is refused. Tax keys into `.env` (names in tax steps §W6; every tax flag `False`). Then `SOFTECH_READ_ONLY=False` + `WRITER_INSTANCE=True`, **all writer flags still False**. Restart web + scheduler | `writer_status --expect writer`: `ROLE = writer`, every flag `effective=False` | |
| ☐ | **W7** | VPS | Writer flags **one at a time**, up to the signed table, never more than the office had (order below). After each: restart, one real operation, read it back in SOFTECH | each read-back matches | |
| ☐ | | VPS | `/sync` → «🔐 مفاتيح الكتابة» | matches the signed table | |
| ☐ | **W8** | VPS | `RBAC_ENFORCEMENT=enforce`, restart | normal users still reach their screens | |
| ☐ | **W9** | VPS | External channels (runbook §11.7): WhatsApp / Meta webhooks, VAPID, `FRONTEND_BASE_URL` | webhook verified; bell WebSocket 101 | |
| ☐ | | VPS | AMI bridge: office copy already stopped (W4) → `sudo systemctl enable --now elrezeiky-ami-bridge` | `/pbx/live` → «🩺 فحص الاتصال» all green, «السنترال: متصل» | |
| ☐ | | office | Attendance agent: `url` under `[erp]` in `agent.ini` → the VPS (`https`), restart the agent. `HR_ATTENDANCE_ENABLED` off on the office (attendance doc §11) | agent reaches the VPS | |
| ☐ | | 192.168.1.8 | Restart the signing agent; on the VPS Settings → electronic signature → «اختبار الختم» | company certificate + thumbprint shown | |
| ☐ | | branches | Users open the new address; remove old office bookmarks (runbook §11.8) | — | |

### W7 order — tick each flag as it goes on

SOFTECH first, one at a time (runbook §11.6), only those signed ON:
☐ POS writer (only if signed) · ☐ POS cancel log (only if signed) · ☐ discount / pricing (offers ×3) · ☐ ISR ·
☐ sales rate · ☐ coverage ×3 · ☐ demand engine schedule · ☐ invoices ×2 · ☐ A/P · ☐ insurance · ☐ shortage ·
☐ customer branch copy · ☐ points removal

Tax **last**, after every SOFTECH writer is read back (tax steps §W7):
☐ `TAX_ETA_READ_PREPROD_ENABLED` (a history round shows) · ☐ `TAX_ETA_CODING_ENABLED` (status refresh answers) ·
☐ `TAX_ERECEIPT_SUBMIT_ENABLED` (only if receipts were being tested; one test receipt read back) ·
☐ `TAX_ETA_SUBMIT_ENABLED` (only after «اختبار الختم» passes) ·
`TAX_ETA_PRODUCTION_ALLOWED` stays **False** — production sending is a separate owner yes, not part of cutover.

---

## Rollback (only if the VPS can't carry the day)

| ✔ | Step |
|---|---|
| ☐ | 1. VPS: `WRITER_INSTANCE=False` + `SOFTECH_READ_ONLY=True`, restart, `writer_status --expect reader`. Stop the VPS scheduler and AMI bridge |
| ☐ | 2. Only then, office **project `.env` only**: `WRITER_INSTANCE=True` + `SOFTECH_READ_ONLY=False`; start web + scheduler + AMI bridge (put the Startup file back and re-enable the 3 tasks if wanted) |
| ☐ | 3. List what was entered on the VPS since W5 from its audit log (and `TaxAuditEvent`); the office DB does not have it |

Tax sending was drained at W3, so switching back loses no receipt.

---

## After cutover

| ✔ | Item |
|---|---|
| ☐ | Finance GL on the VPS: `import_gl_coa`, `import_gl_opening`, `import_gl_parties` (unless done in the office before W5). Keep `GL_DRAFTING_SCHEDULE_ENABLED=False` until finance confirms the parties |
| ☐ | If the receipts reconciliation (PR #138) is merged: one-time `eta_recon` backfill (see the PR) |
| ☐ | `backfill_upload_hashes --apply` (data lifecycle) |
| ☐ | Uptime monitor on `https://elrezeikyapp.dawalvry.com/api/public/health/` every 5 min |
| ☐ | 📸 LDC snapshot `04-live` |
| ☐ | Office copy kept as a cold fallback for 2 weeks: data intact, reader, nothing auto-starting |
| ☐ | First 7 mornings: «المشتريات والوارد» freshness green through yesterday; `journalctl -u elrezeiky-web -u elrezeiky-scheduler --since yesterday -p err`; RAM / swap in Cockpit |
| ☐ | Then turn the other switches on one per calm day, with the owner (checklist §4) |
