# Owner go-live steps — explained (2026-11-05)

These are the steps from the [go-live readiness report](2026-11-go-live-readiness.md) that only the owner can do. A Claude session cannot SSH to the VPS, log in to the MikroTik, or sign the switch table.

For each step this page explains **what** it is, **why** it matters, **when** to do it, **exactly how**, **how to check it worked**, and **how to undo it**.

Facts were checked on 2026-11-05 against the office database and `.env`. Two items changed after that check:
- **ISR drafts #30 / #32 are already cancelled** (since 2026-10-24), so step 7 is only a re-check.
- **A/P and insurance are both ON in the office and live.** The switch table and runbook §11.6 now say so (step 3).

> **Golden rules for every step**
> - **Never paste a password, key or token into a Claude chat.** Type secrets only into the server/router or your password manager.
> - **Back up before you change.** Every step below starts with a copy of what it changes.
> - **One change at a time, check it, then the next.**

## Order

| When | Step | Time |
|---|---|---|
| Any time now (VPS still read-only) | 1. nginx compression + index.html | 15 min |
| | 2. `COUNSEL_PHONE_HASH_KEY` (VPS **and** office) | 10 min |
| | 3. Check and sign the writer switch table | 20 min |
| | 4. Backups: nightly dump, off-site copy, test restore, LDC snapshots | 2–3 h |
| | 5a. Make the 10 old worktree `.env` copies read-only | 10 min |
| | 6. Fix the Ain Shams route on the HQ MikroTik | 20 min |
| Cutover day | 5b. Make the **project** `.env` read-only (checklist W1) | 5 min |
| | 7. Re-check: no live ISR drafts (checklist W3) | 2 min |

**How to reach the VPS** (every VPS step): from the office PC, PowerShell:
```powershell
ssh bassemwolsely94@41.196.0.34
```
You use your key; `sudo` asks your password. The app lives in `/opt/elrezeiky/app` and runs as the user `elrezeiky`.

---

## 1. nginx on the VPS: compression + `index.html` never cached

**What.** Two changes to the live nginx site file `/etc/nginx/sites-available/elrezeiky`:
1. **gzip** for JavaScript, CSS and JSON. Ubuntu's default nginx compresses only HTML, so every browser downloaded the app's JavaScript uncompressed. After the code-splitting release the first page is ~0.7 MB raw; with gzip it is ~0.2 MB. Without gzip, branch PCs on slow lines wait seconds on every first visit.
2. **`index.html` with `Cache-Control: no-cache`.** After each release, the old JavaScript files are deleted. If a browser kept the old `index.html` (it was cached for 1 hour), it asks for files that no longer exist and shows «إصدار جديد متاح». With `no-cache` the browser always checks `index.html` (a tiny file), so this cannot happen.

**Why by hand.** The live file was hand-edited (certbot added the SSL lines), so copying `deploy/nginx.conf` over it would break TLS. `release.sh` never touches nginx.

**When.** Any time. It does not depend on the release, but it pays off most after the next `release.sh` (which brings the code-splitting).

**Steps.**
```bash
# 1) back up the live file (into sites-available — only sites-enabled is loaded, so the copy is inert)
sudo cp /etc/nginx/sites-available/elrezeiky /etc/nginx/sites-available/elrezeiky.bak-2026-11-05

# 2) edit
sudo nano /etc/nginx/sites-available/elrezeiky
```
Make three edits in nano (Ctrl+W searches, Ctrl+O saves, Ctrl+X exits):

**(a)** Find the block that starts `map $server_addr $elr_network {` (top of the file, outside every `server { }`). Directly **after** its closing `}`, add:
```nginx
# index.html must never be cached: after a release it points at new chunk files and the old ones are gone
map $uri $elr_spa_expires {
    /index.html -1;
    default     1h;
}
```

**(b)** Inside the `server { listen 443 ... }` block, find `client_max_body_size 50M;` and add under it:
```nginx
    gzip            on;
    gzip_vary       on;
    gzip_proxied    any;
    gzip_comp_level 5;
    gzip_min_length 1024;
    gzip_types      text/css application/javascript application/json image/svg+xml text/plain application/manifest+json;
```

**(c)** Find `location / {` (the React app block, with `root /opt/elrezeiky/app/staticfiles/frontend;`). In it, **replace** these two lines:
```nginx
        expires 1h;
        add_header Cache-Control "public";
```
with this one line:
```nginx
        expires $elr_spa_expires;
```
Leave every other `add_header` line in that block (X-Frame-Options, CSP, …) **unchanged**. They are the security headers.

```bash
# 3) test the syntax — must say "syntax is ok" and "test is successful"
sudo nginx -t
# 4) apply without dropping connections
sudo systemctl reload nginx
```

**Check it worked.**
```bash
curl -sI https://elrezeikyapp.dawalvry.com/ | grep -i cache-control
#   → Cache-Control: no-cache
JS=$(curl -s https://elrezeikyapp.dawalvry.com/ | grep -o '/assets/index-[^"]*\.js' | head -1)
curl -sI -H 'Accept-Encoding: gzip' "https://elrezeikyapp.dawalvry.com$JS" | grep -i -E 'content-encoding|cache-control'
#   → Content-Encoding: gzip   and   Cache-Control: max-age=3600
```
Then open the site in a browser and check that login and one screen still work.

**Undo.**
```bash
sudo cp /etc/nginx/sites-available/elrezeiky.bak-2026-11-05 /etc/nginx/sites-available/elrezeiky
sudo nginx -t && sudo systemctl reload nginx
```
**If `nginx -t` fails:** read the line number it names, fix that line, or undo. Never `reload` after a failed `-t`.

---

## 2. `COUNSEL_PHONE_HASH_KEY`

**What.** The counselling card (Project 4) stores **opt-outs** ("don't send me cards again") as a keyed hash of the phone number, not the number itself. The key is this setting.
- If it is not set, the code uses a fixed default (`elrezeiky-counsel-phone-v1`) that is in the public repo. Anyone with the database could then test phone numbers against the hashes.
- **If the key ever changes, every stored opt-out silently stops matching.** People who opted out would get cards again.

**When.** **Now, before the first card is sent.** Checked 2026-11-05: all counselling tables are empty (0 cards, 0 opt-outs), so setting it now loses nothing.

**Same key on the VPS and in the office.** At cutover the office database is copied to the VPS. If the office sends cards before cutover with a different key, those opt-outs break on the VPS. So generate **one** key and put it in **both** `.env` files.

**Steps.**
```bash
# on the VPS — generate (prints 64 hex characters); copy it into your password manager right away
openssl rand -hex 32

# add it ONCE to the VPS .env (the processes refuse to start on a duplicated key)
sudo -u elrezeiky nano /opt/elrezeiky/app/.env
#   if the template line "# COUNSEL_PHONE_HASH_KEY=..." is there: delete the "# " and put the value after =
#   otherwise add a new line at the end:   COUNSEL_PHONE_HASH_KEY=<the 64 characters>
grep -c '^COUNSEL_PHONE_HASH_KEY=' /opt/elrezeiky/app/.env      # → 1   (exactly one)
sudo systemctl restart elrezeiky-web elrezeiky-scheduler
```
Office: open the project `.env` (in `...\Reservation Module\.env`) in Notepad and add the **same** line once. Save it as UTF-8 without BOM (Notepad's default "UTF-8"). Restart the office web and scheduler.

**Check it worked** (prints only True/False, never the key):
```bash
cd /opt/elrezeiky/app && sudo -u elrezeiky /opt/elrezeiky/venv/bin/python manage.py shell -c \
 "from django.conf import settings as s; print(len(s.COUNSEL_PHONE_HASH_KEY)==64 and s.COUNSEL_PHONE_HASH_KEY!='elrezeiky-counsel-phone-v1')"
#   → True
```
Office: `venv\Scripts\python manage.py shell -c "<same line>"` → `True`.

**Rules from now on.** Never change this key and never rotate it. Keep it in the password manager. A future server gets the **same** value.

---

## 3. The writer switch table: check and sign

**What.** `docs/product-review/06_SPEC_P-54_cutover_single_writer.md`, appendix «production switch table». It lists every flag that lets the app write into SOFTECH, with the value the VPS will have after cutover.
- At cutover step W7 you turn the flags on one by one and stop at this table.
- The rule is "**never more than the office had**", so a double post or a surprise write cannot happen.

**What was wrong and is now corrected** (checked 2026-11-05 against the office `.env` and database):

| Flag | Was in the docs | Truth in the office | Table now says |
|---|---|---|---|
| `AP_RECONCILE_WRITER_ENABLED` | P-54: ON; runbook §11.6: "still OFF" | **ON**, and **53,811 allocations already written** to SOFTECH. A person triggers it (button/command); it is not scheduled. 23 approved allocations are waiting to be written. | ON (runbook fixed) |
| `INSURANCE_SOFTECH_WRITE_ENABLED` | "currently OFF everywhere" | **ON**; the re-price writeback is live (through the guarded plan only) | ON |
| `AP_RECONCILE_UPDATE_PATIENTDATA` | not in the table | not set → **OFF** | OFF (row added) |

**What you decide.**
1. **A/P writer ON on the VPS?** It is ON today. Recommended: **ON**, turned on near the end of W7 (the order is in §11.6), with one real allocation read back in SOFTECH.
2. **The 23 approved, not-yet-written A/P allocations.** Choose one:
   - write them from the office **before** W1;
   - or let the VPS write them after W7. That is safe: the writer checks SOFTECH (`chequestrans`) first and skips anything already written, so nothing doubles.
3. **Insurance writer ON?** Recommended: **ON** (live today).
4. **Every other row:** confirm the values as written. These stay OFF: POS writer (until P-39 parity), pricing, replication, loyalty, personal comment, POS cancel, replacement posting, customer merge, ISR auto-approve.

**How to see the office values yourself** (project folder, PowerShell):
```powershell
venv\Scripts\python manage.py writer_status
```
It prints the role and every flag with its value and effective state; it changes nothing. In the app: `/sync` → «🔐 مفاتيح الكتابة في SOFTECH».

**How to sign.** Open the appendix and fill the last column of each row: your initials and the date (e.g. `BW 2026-11-06`). Sign in Git, or print it and sign on paper.
- To sign in Git, send the initials to a Claude session and say which rows. It fills the column and commits; that is not a secret.
- On cutover day (W7) this signed table is the pass condition: `/sync` → «🔐 مفاتيح الكتابة» must match it, row by row.

---

## 4. Backups: nightly dump, off-site copy, a tested restore, snapshots

**Why this blocks cutover.** After cutover the VPS database is the **only** copy of everything that isn't in SOFTECH: reservations, demand, transfers, approvals, insurance claims, A/P reconciliation, the audit trail, the finance GL.
- Today nothing backs it up except the dump `release.sh` takes before a release, on the **same disk**.
- LDC snapshots are 0 on this plan.
- If the VPS disk dies, all of that is gone.

Database size today (office): **11 GB**. A compressed dump is roughly 2–3 GB; check the real size after the first one.

### 4a. Nightly dump on the VPS

```bash
# folder for backups (outside the code folder)
sudo -u elrezeiky mkdir -p /opt/elrezeiky/backups

# password file so cron's pg_dump can log in without a prompt
sudo -u elrezeiky nano /opt/elrezeiky/.pgpass
#   one line:   localhost:5432:elrezeiky_db:elrezeiky:<PG_PASSWORD from /opt/elrezeiky/app/.env>
sudo chmod 600 /opt/elrezeiky/.pgpass        # pg_dump ignores the file if it is readable by others

# test by hand — must NOT ask for a password, and must produce a file of a few GB
sudo -u elrezeiky pg_dump -h localhost -U elrezeiky -Fc -Z 6 elrezeiky_db -f /opt/elrezeiky/backups/db_test.dump
ls -lh /opt/elrezeiky/backups/
sudo -u elrezeiky rm /opt/elrezeiky/backups/db_test.dump
```
Schedule it (`sudo -u elrezeiky crontab -e`, choose nano, paste at the end, save):
```cron
# 02:30 nightly DB dump, keep 14 days (log in backup.log)
30 2 * * * pg_dump -h localhost -U elrezeiky -Fc -Z 6 elrezeiky_db -f /opt/elrezeiky/backups/db_$(date +\%F).dump >> /opt/elrezeiky/backups/backup.log 2>&1 && find /opt/elrezeiky/backups -name 'db_*.dump' -mtime +14 -delete
# 03:15 every Friday: media (uploads), keep 4
15 3 * * 5 tar czf /opt/elrezeiky/backups/media_$(date +\%F).tgz -C /opt/elrezeiky/app media media_hold >> /opt/elrezeiky/backups/backup.log 2>&1 && find /opt/elrezeiky/backups -name 'media_*.tgz' -mtime +28 -delete
```
The `\%` is required in crontab. Without the backslash, cron cuts the line at the `%`.

**Data lifecycle: the holding folder.** Files the lifecycle file rules remove wait 30 days in `media_hold`, outside `media/`. The Friday media `tar` must include it (the command above does). Create the folder once now with `sudo -u elrezeiky mkdir -p /opt/elrezeiky/app/media_hold`: the app only creates it on the first move, and until it exists the `tar` fails and the old-backup cleanup after it is skipped. In the VPS `.env`, set `LIFECYCLE_HOLD_ROOT=/opt/elrezeiky/app/media_hold` (the same disk as `media/`, so a move is one rename). Set `LIFECYCLE_FILE_RULES_ENABLED=True` only after the media copy is verified; until then every file rule stays in preview. Rules are switched on one by one, after reading their preview (`docs/architecture/36_DATA_LIFECYCLE.md`).

**Data lifecycle, Stage 4.** (1) After the media copy is verified, run `python manage.py backfill_upload_hashes` (dry run), then `--apply`, so the duplicate-invoice notice also knows the files uploaded before. (2) After the first VPS preview of the `bundle_pages` rule, read it and switch it on: the pages folder is only used while a bundle is processed, so it is safe (file rules stay in preview until `LIFECYCLE_FILE_RULES_ENABLED=True` and a fresh preview exist). (3) `media_hold` now also receives files staff delete or replace (kept 30 days, then purged by the daily retention step), so it will not stay empty, and the Friday backup `tar` already includes it. An admin can retrieve a copy of such a file, not restore it into the record.

**Check the next morning:** `ls -lh /opt/elrezeiky/backups/` shows `db_<today>.dump`, and `backup.log` is empty or has no errors. Disk: 14 dumps × ~3 GB ≈ 40 GB of the 300 GB. Check with `df -h /`.

### 4b. Off-site copy to an HQ PC

A backup on the same VPS dies with the VPS, so a second copy must live somewhere else. The plan: an HQ PC pulls last night's dump every morning. It uses a **dedicated, read-only** login that can only download from the backup folder: no shell, no write, nothing else.

**On the VPS (once):**
```bash
# group that may read the backup folder; new files there inherit the group (setgid)
sudo groupadd backupread
sudo chgrp backupread /opt/elrezeiky/backups
sudo chmod 2750 /opt/elrezeiky/backups
# the pull user must be able to pass through /opt/elrezeiky (Ubuntu makes home folders 750)
sudo apt install -y acl
sudo setfacl -m g:backupread:x /opt/elrezeiky
# the pull user: key login only, read-only SFTP, nothing else
sudo useradd -m -s /bin/sh -G backupread backuppull
sudo passwd -l backuppull
sudo -u backuppull mkdir -p /home/backuppull/.ssh
sudo -u backuppull chmod 700 /home/backuppull/.ssh
```
**On the HQ PC that will hold the copies.** Pick a PC that is on most mornings and has a disk with room (≥ 100 GB). In PowerShell:
```powershell
ssh-keygen -t ed25519 -C "erp-backup-pull" -f $env:USERPROFILE\.ssh\erp_backup_pull
#   press Enter twice for NO passphrase (the task must run unattended; the key can only download backups)
Get-Content $env:USERPROFILE\.ssh\erp_backup_pull.pub        # copy this one line
```
**Back on the VPS:**
```bash
sudo -u backuppull nano /home/backuppull/.ssh/authorized_keys
#   ONE line: the forced read-only SFTP, then the public key you copied:
#   restrict,command="/usr/lib/openssh/sftp-server -R" ssh-ed25519 AAAA....  erp-backup-pull
sudo chmod 600 /home/backuppull/.ssh/authorized_keys
```
If `/etc/ssh/sshd_config` (or a file in `sshd_config.d/`) has an `AllowUsers` line, add `backuppull` to it, then `sudo systemctl reload ssh`.

**HQ PC, the pull script:** create `C:\ErpBackup\pull.ps1`:
```powershell
$dst = 'D:\Backups\erp'                                   # change to your disk
$key = "$env:USERPROFILE\.ssh\erp_backup_pull"
$day = (Get-Date).ToString('yyyy-MM-dd')
New-Item -ItemType Directory -Force $dst | Out-Null
$lines = @("get /opt/elrezeiky/backups/db_$day.dump $($dst -replace '\\','/')/db_$day.dump")
if ((Get-Date).DayOfWeek -eq 'Friday') { $lines += "get /opt/elrezeiky/backups/media_$day.tgz $($dst -replace '\\','/')/media_$day.tgz" }
$batch = Join-Path $env:TEMP 'erp_pull.txt'
$lines | Set-Content -Encoding ascii $batch
sftp -i $key -b $batch -o BatchMode=yes backuppull@41.196.0.34
if ($LASTEXITCODE -ne 0) { "$(Get-Date -f s) FAILED" | Add-Content "$dst\pull.log"; exit 1 }
"$(Get-Date -f s) OK db_$day.dump $([math]::Round((Get-Item "$dst\db_$day.dump").Length/1GB,2)) GB" | Add-Content "$dst\pull.log"
Get-ChildItem $dst -Include 'db_*.dump','media_*.tgz' -Recurse | Where-Object LastWriteTime -lt (Get-Date).AddDays(-30) | Remove-Item
```
**First run by hand.** It asks once to trust the server's key: answer `yes`. It must end without errors and `pull.log` must say `OK`:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\ErpBackup\pull.ps1
```
**Schedule it** (Task Scheduler → Create Task):
- Name «ERP backup pull».
- «Run whether user is logged on or not».
- Trigger daily at **04:30**, after the 02:30 dump.
- Action `powershell` with arguments `-NoProfile -ExecutionPolicy Bypass -File C:\ErpBackup\pull.ps1`.
- Settings: «Run task as soon as possible after a scheduled start is missed».

**Protect the copies.** The dumps contain customer names and phones. Limit the folder to admins (right-click → Properties → Security), and turn on BitLocker on that disk if available.

**If the office line is slow:** 2–3 GB a day may be heavy. Then pull only on Fridays: wrap the `db_` line in the same `if` as the media line. That still gives a weekly off-site copy, plus the 14 daily dumps on the VPS.

### 4c. Test a restore (once now, then monthly)

A backup is only proven when it has been restored. On the VPS, restore last night's dump into a **separate** test database. Never touch `elrezeiky_db`.
```bash
D=/opt/elrezeiky/backups/db_$(date +%F).dump        # or yesterday's file
sudo -u postgres createdb -O elrezeiky elrezeiky_restore_test
sudo -u postgres pg_restore --no-owner --role=elrezeiky -d elrezeiky_restore_test -j 2 "$D"
# compare a few tables: the numbers must match (or be slightly lower in the test copy, for rows added since 02:30)
for DB in elrezeiky_db elrezeiky_restore_test; do
  sudo -u postgres psql -d $DB -Atc "select '$DB', (select count(*) from reservations_reservation), (select count(*) from audit_auditlog), (select count(*) from purchasing_isrpush)"
done
sudo -u postgres dropdb elrezeiky_restore_test
```
Write the date and the three numbers in the go-live checklist §4. Once, also restore one off-site copy on the HQ PC's PostgreSQL the same way. That proves the copy that survives a VPS loss is usable.

### 4d. LDC snapshots

Open a ticket with LinkDatacenter. Suggested text:
> Please enable VPS snapshots for server 41.196.0.34 (elrezeikyerp). We need at least one automatic snapshot per day (or week), kept for 7 days, plus the ability to take manual snapshots before maintenance. Please tell us the price and the retention.

Snapshots let you roll the whole server back (system + app + DB) after a bad change. They do **not** replace 4a/4b: they live at the same provider.

---

## 5. Making office `.env` files read-only

**What.** Every copy of the project on the office PC has its own `.env`: the project folder plus each Claude worktree under `.claude\worktrees\*`. Any server, scheduler or `manage.py` command started in a folder whose `.env` says `WRITER_INSTANCE=True` + `SOFTECH_READ_ONLY=False` **can write to SOFTECH**.
- After cutover, the VPS must be the **only** writer.
- A second writer is how a double post happens: the same ISR, invoice or payment posted twice.

Checked 2026-11-05: **10 worktree `.env` files are writers.** They are `finance-gl-plan3-d34b10`, `integrate-1102`, `pbx-cdr-pic-link`, `phone-alerts`, `pic-analytics`, `pic-excl-sort`, `roster-batch2`, `security-batch6-platform`, `security-n0` and `security-n1`. The project `.env` is a writer too (correct until cutover).

The scheduler folder `main-runtime` has no `.env` of its own; it uses the project `.env`.

### 5a. Now: the worktree copies only

They are leftovers from finished work and should never have been writers. Flipping them now changes nothing in daily operation, because the real office server and scheduler use the **project** `.env`, which this block does not touch.

First, Task Manager → Details: make sure no `python.exe` is running from one of those worktree folders. If unsure, close the Claude sessions that use them.

Then, PowerShell, in the project folder:
```powershell
cd "C:\Users\basse\OneDrive\ElRezeiky Depts\IT Software Development\Claude Development\Reservation Module"
$files = @(Get-ChildItem .claude\worktrees\*\.env)             # worktrees ONLY — not the project .env
$utf8 = New-Object System.Text.UTF8Encoding($false)            # UTF-8 without BOM (a BOM breaks the first key)
foreach ($f in $files) {
  Copy-Item $f.FullName "$($f.FullName).bak-golive"            # backup next to it
  $t = [IO.File]::ReadAllLines($f.FullName, $utf8) | Where-Object { $_ -notmatch '^\s*(WRITER_INSTANCE|SOFTECH_READ_ONLY)\s*=' }
  $t = @($t) + 'WRITER_INSTANCE=False' + 'SOFTECH_READ_ONLY=True'
  [IO.File]::WriteAllLines($f.FullName, [string[]]$t, $utf8)
}
foreach ($f in $files) {
  $ok = (Select-String -Path $f.FullName -Pattern '^WRITER_INSTANCE=False$') -and (Select-String -Path $f.FullName -Pattern '^SOFTECH_READ_ONLY=True$')
  "{0}  {1}" -f ($(if ($ok) {'READER'} else {'!! NOT READER'})), $f.FullName
}
```
What it does, line by line:
1. Lists every worktree `.env`.
2. Saves a `.bak-golive` copy of each.
3. Removes any existing `WRITER_INSTANCE` / `SOFTECH_READ_ONLY` lines (there may be duplicates).
4. Appends exactly `WRITER_INSTANCE=False` and `SOFTECH_READ_ONLY=True`.
5. Writes the file back as UTF-8 without BOM.
6. Prints `READER` per file.

Every line must say `READER`.

**Undo** (only if something needed one of them as a writer, which it shouldn't): `Copy-Item <file>.bak-golive <file>`.

### 5b. Cutover day: the project `.env` (checklist step W1)

**Not before cutover day.** Until then the office is the real writer: the ISR pushes, invoices, A/P and insurance that run today all come from it.

On cutover day, run the **full** W1 block from `docs/GO_LIVE_CHECKLIST.md` §3. It is the same as above, but its first line also includes the project `.env`:
```powershell
$files = @(Get-Item .env) + @(Get-ChildItem .claude\worktrees\*\.env)
```
Then restart the office web and scheduler, and run W2:
```powershell
venv\Scripts\python manage.py writer_status --expect reader       # must end with ROLE = reader, exit 0
```
**Run the check part again right before W4 (stop the office).** New worktrees appear whenever a Claude session starts, and they copy the project `.env`.
- After W1 the copies are readers too, which is safe.
- A worktree created between your W1 and W4 is caught by that re-check.

Since 2026-11-04 the code also defaults to read-only when a `.env` has **no** `SOFTECH_READ_ONLY` line and is not the writer instance.

---

## 6. Ain Shams route on the HQ MikroTik

**What is broken.** The VPS reaches SOFTECH branch servers through the tunnel to the HQ MikroTik, which forwards to each branch. For Ain Shams (`192.168.3.0/24`, SOFTECH server `192.168.3.10:5000`) the HQ router has **two** routes:
- the old WireGuard `wg0` route, distance **1**. It is dead: the WireGuard link to that branch no longer carries traffic.
- the live SSTP route via `10.0.0.4`, distance **5**.

RouterOS uses the route with the **lowest distance** that it considers active. A WireGuard interface counts as "up" even when its peer is gone, so the dead route keeps winning and traffic to Ain Shams vanishes. Result: on the VPS, Ain Shams syncs time out, and that branch's stock/sales data goes stale.

**When.** Any time; best in a quiet hour. The change affects only traffic to Ain Shams. If the office PC also syncs Ain Shams through this router, it starts working there too. Check `/sync`: if Ain Shams is stale in the office as well, this is the same cause.

**Steps** (WinBox → New Terminal on the HQ router «Bab El Haded HQ»):
```routeros
/system backup save name=before-ainshams-route
/ip route print detail where dst-address=192.168.3.0/24
```
Look at the output. You should see two routes: one with `gateway=wg0` (or `…%wg0`), `distance=1`, and one with `gateway=10.0.0.4`, `distance=5`. Note the **number** in the first column of the `wg0` one (e.g. `3`). Then:
```routeros
/ip route set 3 disabled=yes comment="old WG to Ain Shams - dead; SSTP 10.0.0.4 carries it (2026-11)"
/ip route print where dst-address=192.168.3.0/24
```
Now the `10.0.0.4` route must show the **A** (active) flag, and the `wg0` route **X** (disabled).
```routeros
/ping 192.168.3.10 src-address=192.168.1.201 count=5
```
Replies mean the HQ side works.
> Safe Mode trap (runbook §5.2): if you switched Safe Mode on, leave it with **Ctrl+X** right after. A dropped WinBox session in Safe Mode undoes the change.

Save the result: `/system backup save name=after-ainshams-route`.

**Check from the VPS:**
```bash
nc -vz -w 5 192.168.3.10 5000          # → "succeeded"
```
Then in the app: `/sync` → run one manual sync for the Ain Shams branch. It must finish, and the freshness bar for Ain Shams turns green after the next cycle.

**Undo:** `/ip route set [find where comment~"old WG to Ain Shams"] disabled=no`. Or restore the backup: `/system backup load name=before-ainshams-route` (this reboots the router).

**If the ping still fails** after the SSTP route is active: the Ain Shams branch's SSTP link is down (check `/interface sstp-server print` / `/ppp active print` for its user), or its router has no route back to `192.168.1.0/24`. The office PC uses the same path, so if the office can reach Ain Shams, the VPS can too after this fix.

---

## 7. ISR drafts #30 / #32: already cancelled, re-check at W3

**What it was.** On 2026-10-24, drafts #30 and #32 turned out to be identical copies of ISR #29 (HQ → branch 160, 5,174 lines), which had **already been pushed** to SOFTECH. Approving either would have posted the same ISR twice.

**Status (checked 2026-11-05 in the office database):**
- #29 is `pushed`.
- #30 and #32 have been `cancelled` since 2026-10-24 21:02, with the reason «نسخة مطابقة للطلب #29 المُرحَّل (ISR 26100661) — منع ترحيل مزدوج».
- There are **0** live drafts (proposed / approved / failed) today.
- Since then the code also refuses this by itself:
  - one live draft per route;
  - a push identical to one pushed in the last 7 days is refused unless a reason is given.

**So nothing to do now.** On cutover day, at **W3 (drain)**, check that nothing is half-way:
- in the app: `/supply` → ISR tab → status filter «مقترح» / «معتمد»; push or cancel (with a reason) anything you find;
- or in PowerShell, in the project folder:
```powershell
venv\Scripts\python manage.py shell -c "from apps.purchasing.models import IsrPush as P; print(P.objects.filter(status__in=['proposed','approved','failed']).count())"
```
→ `0` is clean. Any other number: open those drafts and push or cancel them on the office **before W1**. A draft pushed from the office after W1 is impossible, which is the point of W1.
