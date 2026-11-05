# Go-live checklist — office → LDC VPS (2026-11-03)

The goal is to get the system live on `https://elrezeikyapp.dawalvry.com` now, let users test it hard, and keep developing there.
- Full commands are in [`deploy/LINKDATACENTER_VPS_RUNBOOK.md`](../deploy/LINKDATACENTER_VPS_RUNBOOK.md) (§ numbers below).
- This page sets the **order**, says **who** does each step, and gives the **writer switch-over**, which must never have two writers.
- Tick each box with initials and date.

Legend: **[owner]** = only the owner can do it (credentials, server, DNS, router, Meta). **[code]** = in the repo.

---

## 0. Where we stand

| Area | State | Source |
|---|---|---|
| VPS (Ubuntu 24.04, 4 vCPU / 8 GB / 300 GB, 41.196.0.34) | ✅ created and hardened (§4) | runbook memory, 2026-10-27 |
| Tunnel to HQ (ZeroTier primary + SSTP backup, watchdog) | ✅ built, failover tested; ⚠ Ain Shams 192.168.3.10:5000 timed out | §5.0 |
| Stack (PG16, Redis, nginx, Java, Tesseract, Node) + PG roles | ✅ §6, §7 | 2026-10-27 |
| App user, clone, venv (§8.1) | handed over 2026-10-29; **owner confirms** | — |
| `.env`, OCR sidecar, units, nginx, TLS, frontend (§8.2–9.4) | **owner confirms**. The runbook N0–N6 steps talk about "the live server", so the web may already run read-only | — |
| Rehearsal restore (§10) | **owner confirms** | — |
| Office copy | **The office is still the SOFTECH writer today**: `WRITER_INSTANCE=True`, `SOFTECH_READ_ONLY=False`, 17 writer flags ON. It runs `runserver 0.0.0.0:8000` + `run_scheduler` | office `.env`, 2026-11-03 |
| Code on `main` | 2026-11-04: go-live batch plus Projects 2–5 merged (PRs #55–#59): camera scan, daily counts, missed sales / call-backs, drug assistant + counselling card, and the usage slip. Each ships behind its own switch, OFF in `deploy/production.env.example`. Still open: PR #53 (N6 follow-ups, green) and PR #54 (N3–N5 "before enforce", backend tests failing). Phone alerts + the 09:00 morning brief merged as `14af2b45` (switches OFF; jobs `phone_alerts_tick` every minute, `morning_brief` 09:00). Deploy migrations include audit 0037, branches 0012, users 0050, reservations 0023 and notifications 0039–0041 | git |

> ⚠ **Found 2026-11-03: there is more than one office `.env`.** Besides the project `.env`, 14 Claude worktrees under
> `.claude\worktrees\*\.env` have their own copy.
> - 9 of them say `WRITER_INSTANCE=True` + `SOFTECH_READ_ONLY=False`: integrate-1102, pbx-cdr-pic-link, phone-alerts,
>   pic-analytics, pic-excl-sort, roster-batch2, security-batch6-platform, security-n0, security-n1.
> - Any server, scheduler or command started from one of those folders can write to SOFTECH.
>
> Step W1 below flips **every** copy, not only the main one.

---

## 1. Code-side (branch `claude/amazing-mcnulty-1fc8b9`) — done, waiting for merge

- [x] Fresh-database check: `makemigrations --check` shows no changes, and the full migration chain builds an empty test database.
- [x] `deploy/production.env.example`: the VPS template.
  - It boots as a **reader**: `WRITER_INSTANCE=False`, `SOFTECH_READ_ONLY=True`, and all 24 writer flags of `config/writers.py` listed and `False`.
  - It also has the N1–N6 switches and the local OCR settings, with no Windows paths.
  - §8.2 now copies this file, not the staging one. The staging template was missing `WRITER_INSTANCE` and 5 writer flags; they are added there too.
- [x] `apps/tests/test_go_live.py` keeps both templates honest:
  - every writer flag is present and off;
  - no key is duplicated;
  - no key is misspelled (each key must be one the code reads).
- [x] `manage.py writer_status [--expect reader|writer]`.
  - It prints the instance role and every flag, value and effective state.
  - It exits 1 on a mismatch or on a duplicated `.env` key.
  - It needs no server and makes no SOFTECH connection. This is the switch-over check.
- [x] `GET /api/public/health/`:
  - `{"status":"ok"}` 200 when Daphne reaches PostgreSQL, 503 otherwise;
  - anonymous, 300 requests/hour per IP, `no-store`, and it shows nothing else;
  - for the uptime monitor (§12.2) and `release.sh`.
- [x] `deploy/release.sh` is now a repo file (it used to be text inside the runbook). It runs `writer_status`, then waits for the health check before it says "live".
- [x] `deploy/elrezeiky-ocr.service` is now a repo file. The web and scheduler units now start after Redis and the tunnel (`zerotier-one`, `elrezeiky-tunnel-watch`).
- [ ] **[owner]** Approve the merge of this branch to `main`. The VPS then runs `release.sh`, or `git pull` before §10.

## 2. Owner actions — nothing below can be done from a Claude session

Claude sessions on the PC are not allowed to SSH to the VPS. Do these in order.

1. [ ] **Tell this session where the VPS stands** for §8.2–§10 (see table 0), so the remaining steps can be trimmed.
2. [ ] **DNS** (§3) at LinkDatacenter: A records `elrezeikyapp` and `elrezeikyerp` → `41.196.0.34`. Check with `nslookup elrezeikyapp.dawalvry.com 8.8.8.8`. This is needed for TLS.
3. [ ] **Secrets into the VPS `.env`** (from `deploy/production.env.example`):
   - `SECRET_KEY` (new);
   - `PG_PASSWORD`;
   - `SYBASE_USER` / `SYBASE_PASSWORD` / `SOFTECH_PROFILE`, from the office;
   - `OMNI_CREDENTIALS_KEY` (**the same as the office**, or stored channel credentials can't be decrypted);
   - `NETWORK_PROXY_KEY`;
   - optionally `GEMINI_API_KEY`.
4. [ ] **Rotate the passwords that appeared in chat:**
   - the SSTP secret `elrezeiky-vps` (MikroTik + `/etc/ppp`);
   - the smoke-test admin password.
5. [ ] **`ocr_tessdata/` copied** to the VPS (§8.4 a). It is git-ignored.
6. [ ] **TLS**: `certbot` for `elrezeikyapp.dawalvry.com` (§9.3).
7. [ ] **Ain Shams node** (192.168.3.10:5000) reachable over the tunnel. This is a branch-side route. Until it is fixed, that branch's syncs fail on the VPS.
8. [x] **Before cutover (§11.2):** cancel the duplicate ISR drafts #30 / #32 of the already-pushed #29. Done: cancelled 2026-10-25 with the ISR guards (`apps/purchasing/isr_guards.py`); checked 2026-11-05 that #29 is pushed and no draft is proposed or approved.
9. [ ] **WhatsApp / Meta (§11.7, can follow go-live by a day):**
   - the WhatsApp token, phone number id, app secret and verify token;
   - the Meta webhook URL → `https://elrezeikyapp.dawalvry.com/api/whatsapp/webhook/` (and `/api/social/webhook/meta/`);
   - approved Meta templates for refill reminders, phone alerts and the morning brief;
   - the VAPID pair (the office one, so users keep their push subscriptions).
10. [ ] **SMS (W-1)**: choose the SMS company. Until then `SMS_PROVIDER` stays empty, and that does not block go-live.
11. [ ] **AMI / Issabel** credentials, and Issabel allowing the HQ router IP (§11.7). The call-center live view needs them; nothing else waits on them.
12. [ ] **Signed switch table**: fill in value, initials and date for each flag in the `06_SPEC_P-54` appendix.
   - Today's office values: ISR, SALES_RATE, COVERAGE ×3, DEMAND_ENGINE_SCHEDULE, INVOICE ×2, SHORTAGE, AP_RECONCILE, POS_OFFERS ×3, CUSTOMER_BRANCH_COPY, POINTS_REMOVAL and INSURANCE are **ON**.
   - POS_WRITER, POS_CANCEL, PRICING, REPLICATION, LOYALTY, PERSONAL_COMMENT, REPLACEMENT and CUSTOMER_MERGE are **OFF**.
   - ISR_AUTO_APPROVE is **OFF**.
13. [ ] **LDC ticket**: enable snapshots (the plan has 0). Until then, the nightly `pg_dump` plus an off-site copy (§12.1) is the only backup.
14. [ ] **Uptime monitor** (UptimeRobot / Better Stack) on `https://elrezeikyapp.dawalvry.com/api/public/health/` every 5 minutes.

## 3. Go-live sequence

### Day −1: rehearsal (VPS stays a reader; the office stays the writer)
- [ ] Merge this branch. On the VPS run `release.sh` (or §8–§9 if first time).
- [ ] On the VPS, `manage.py writer_status --expect reader` ends with `ROLE = reader`.
- [ ] Do §10.1 restore and §10.2 verify. Testers may click around. Nothing can write to SOFTECH: two locks, plus no scheduler.

### Day 0: cutover, in a quiet window after closing (1–2 h)

**The writer switch-over has no window where two instances can write.** Between W1 and W6 **nobody** writes to SOFTECH; that gap is the safety margin.

| Step | Where | Exactly what | Pass condition |
|---|---|---|---|
| **W0** | VPS | `writer_status --expect reader` | `ROLE = reader`, exit 0 |
| **W1** | office | Make **every** office `.env` a reader with the PowerShell block below, then restart the office web + scheduler | The block prints `READER` for every file |
| **W2** | office | In the project folder: `venv\Scripts\python manage.py writer_status --expect reader` | `ROLE = reader`, exit 0. The scheduler boot log says `not the writer instance` |
| **W3** | office | Drain (§11.2). `/api/pos-orders/queue-status/` must show queued and push_failed = 0. No ISR / invoice / A/P / insurance item may be "pushing". No ISR draft may be proposed or approved (#30/#32 were cancelled 2026-10-25) | All zero. **If something is still queued: stop and ask.** Never flip the office back to writer while the VPS has any writer flag on |
| **W4** | office | Stop everything (§11.3): every `runserver`, every `run_scheduler`, `daphne` and the NSSM service `ElRezeikyPlatform` if installed, plus Task Scheduler / Startup entries | Task Manager: no `python.exe` with `runserver` / `run_scheduler` / `daphne` |
| **W5** | both | Final `pg_dump` (office) → restore + `migrate` on the VPS (§11.4). Start the VPS web + **scheduler**, still a reader (§11.5) | One full sync cycle is green on the freshness bar. `writer_status --expect reader` still passes |
| **W6** | VPS | Kill-switch test (§11.6). Then in `/opt/elrezeiky/app/.env` set `SOFTECH_READ_ONLY=False` + `WRITER_INSTANCE=True`, with **all writer flags still False**. Restart web + scheduler. Run `writer_status --expect writer` | `ROLE = writer`, every flag `effective=False` |
| **W7** | VPS | Turn on one writer flag at a time, in the §11.6 order, up to the signed table and **never more than the office had**. Restart, do one real operation, read it back in SOFTECH, then do the next | Each read-back matches. `/sync` → «🔐 مفاتيح الكتابة» matches the signed table |
| **W8** | VPS | `RBAC_ENFORCEMENT=enforce` (P-54 §3.4), restart | Normal users still reach their screens |
| **W9** | VPS | External channels (§11.7), users get the new URL (§11.8) | WhatsApp webhook verified. Bell WS 101 |

**W1: flip every office `.env` to reader** (PowerShell, in the project folder; it only touches these two keys):
```powershell
$files = @(Get-Item .env) + @(Get-ChildItem .claude\worktrees\*\.env)
$utf8 = New-Object System.Text.UTF8Encoding($false)   # read and write UTF-8 without a BOM (decouple would misread a BOM)
foreach ($f in $files) {
  Copy-Item $f.FullName "$($f.FullName).bak-golive"
  $t = [IO.File]::ReadAllLines($f.FullName, $utf8) | Where-Object { $_ -notmatch '^\s*(WRITER_INSTANCE|SOFTECH_READ_ONLY)\s*=' }
  $t = @($t) + 'WRITER_INSTANCE=False' + 'SOFTECH_READ_ONLY=True'
  [IO.File]::WriteAllLines($f.FullName, [string[]]$t, $utf8)
}
foreach ($f in $files) {
  $ok = (Select-String -Path $f.FullName -Pattern '^WRITER_INSTANCE=False$') -and (Select-String -Path $f.FullName -Pattern '^SOFTECH_READ_ONLY=True$')
  "{0}  {1}" -f ($(if ($ok) {'READER'} else {'!! NOT READER'})), $f.FullName
}
```
From then on the office copy is the read-only development copy (P-54). It must stay a reader forever, and so must every new worktree `.env`: copy it from the main `.env` *after* W1.

### Rollback (only if the VPS can't carry the day)
1. VPS: `WRITER_INSTANCE=False` + `SOFTECH_READ_ONLY=True`, restart, `writer_status --expect reader`. Then stop the scheduler.
2. Only then, on the office **project `.env` only**: set `WRITER_INSTANCE=True` + `SOFTECH_READ_ONLY=False`, and start web + scheduler.
3. The office DB lacks whatever was entered on the VPS since W5. List it from the VPS audit log before switching back.

## 4. First week after go-live
- [ ] Turn the new features on one at a time, after a calm day:
  - `CAMERA_SCAN_ENABLED`;
  - `DAILY_COUNT_ENABLED` (plus the pilot branch switch);
  - `MISSED_SALES_ENABLED` / `MISSED_CALL_CALLBACKS_ENABLED`;
  - `DRUG_ASSISTANT_ENABLED` / `COUNSELLING_CONTENT_ENABLED`;
  - `USAGE_PRINT_ENABLED`.
- [ ] `PHONE_ALERTS_SEND_ENABLED` / `MORNING_BRIEF_SEND_ENABLED` go on only after all of these:
  - the staff-alerts WhatsApp number is connected and marked `is_staff_alerts`;
  - Meta has approved their templates;
  - one test alert reaches a phone.
- [ ] `COUNSEL_CARD_SEND_ENABLED` only after both of these:
  - Meta has approved the `counsel_card` template;
  - `COUNSEL_PHONE_HASH_KEY` is set (once, and never changed after that).
- [ ] Each morning, check freshness: «المشتريات والوارد» is green through yesterday (§11.8b).
- [ ] Each morning, run `journalctl -u elrezeiky-web -u elrezeiky-scheduler --since yesterday -p err`.
- [ ] Each morning, check RAM and swap in Cockpit (8 GB budget).
- [ ] Nightly backups run, and the first off-site copy has been pulled (§12.1). Do one test restore.
- [ ] The N3–N6 switches go `log → enforce`, one per quiet week, on the owner's call (runbook N-batches).
- [ ] New features ship only through PR → `main` → `release.sh`, each behind its own flag that defaults OFF.
