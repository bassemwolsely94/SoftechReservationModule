# Go-live status — `origin/main` → LDC VPS (2026-11-12)

Checked on `origin/main` = `063da6fe` (PR #113), 237 commits after the 2026-11-07 check at `d1905793`.
Nothing was deployed. Nothing was changed on the VPS, in SOFTECH, or in an office `.env`.
Earlier reports: [2026-11-07](2026-11-07-go-live-readiness.md), [2026-11-05 owner steps](2026-11-owner-go-live-steps.md) (full how-to, checks and undo for every owner step below).

**Stage A** means the VPS is live as a reader: testers work there, and the office stays the SOFTECH writer.
**Stage B** is the cutover: the VPS becomes the only writer.

| Stage | Verdict |
|---|---|
| **A** | **GO** once the code PR is merged and owner steps 1–6 are done (about 1 hour). |
| **B** | **NO-GO** until owner steps 7–12 are done. They are the same blockers as on 2026-11-07, plus the GL and attendance items. |

## Green (nothing to do)

| Area | Result |
|---|---|
| CI on `main` | Green at `b4e67e69` (#96). Runs for #114 and #113 were still going at the time of this check. |
| 2026-11-07 code items | **C1** fixed: the templates have no inline comments, and `test_go_live` reads them with the real parser. **C2** fixed (#84 merged). **N9** fixed: any `SECRET_KEY` that starts with `change…` refuses to boot. **N11** fixed: `SEND_MIN_INTERVAL_SECONDS` is in the template. |
| SOFTECH writers | Still 24 flags in `config/writers.py`. Every one defaults to `False` in `config/settings.py`, and both templates keep them off. The write manifest is unchanged since 2026-11-07, and no new write site was added. Open PR #99 adds tax-authority sending flags, which also default to off. |
| Migrations | `makemigrations --check` reports no changes (after this PR's `audit 0040`). A throwaway test database built from zero applied every migration cleanly. |
| Scheduler jobs | Every job is in `SCHEDULER_JOB_GUARDS`, including the new `attendance_health`. `test_scheduler_locks` enforces that in CI. |
| New env keys | All have safe defaults, so the VPS can run without any of them. New switches since 2026-11-07, all off: `HR_ATTENDANCE_ENABLED`, `LIFECYCLE_FILE_RULES_ENABLED`. Also new: `WHISPER_LAUNCH_RUNNER=False` and `PBX_WEBRTC_*` (empty = off). |
| Attendance agent | It runs on an office PC, not on the VPS: no unit and no nginx change are needed. The switch-over is in [its doc §11](2026-11-attendance-agent-go-live.md). |

## Needs code — this PR

| # | Problem | Fix |
|---|---|---|
| G1 | **Channel credentials would be lost on the VPS.** The template had `OMNI_CREDENTIALS_KEY=CHANGE`. That is not a valid key, so saving a channel account fails, and every stored credential reads back empty, with no error. The office has no key at all, so its credentials are encrypted with a key derived from the office `SECRET_KEY`. The VPS has a different `SECRET_KEY` and cannot read them. | The env key now takes over without a gap: rows under the old derived key still open after the new key is set. New command `manage.py omni_credentials`: with no options it shows the state; `--rekey --apply` re-encrypts the stored credentials under the env key. It never prints a credential or a key, and it writes an audit row (`audit 0040`). New `check --deploy` rules: `omni.E001` (an invalid key stops the release) and `omni.W001` (the key is empty). Both templates now say `OMNI_CREDENTIALS_KEY=` with instructions. |
| G2 | `COUNSEL_PHONE_HASH_KEY` left at its public default gives no warning. | New `counselling.W001` warning in `check --deploy`. |
| G3 | `release.sh` ran the frontend build and `check --deploy` **after** `migrate`. A failure there stopped the script with the new schema applied and the old processes still running (the P-56 failure). It also never restarted the AMI bridge. | The build and `check --deploy` now run before the migration prompt. The AMI bridge is restarted when it is running. |
| G4 | `LIFECYCLE_HOLD_ROOT` and `LIFECYCLE_FILE_RULES_ENABLED` were missing from the production template. | Added, with the VPS path, and the rules stay off. |

Tests: `apps/tests/test_go_live_2026_11_12.py`.

## Open PRs

| PR | Needed for go-live? |
|---|---|
| **This PR** | **Yes**: G1–G3. |
| #99 Tax invoicing | No. Sending stays off. It adds `tax_invoicing 0001–0003`, `users 0056` and two template keys at the end of the file. There is no conflict with this PR. |
| #115, #116 Multi-select filters | No. They are screen-only. |

## Owner-only steps, in order

The VPS is reached with `ssh bassemwolsely94@41.196.0.34`, and the app is at `/opt/elrezeiky/app`.
Never paste a key or password into a Claude chat.

**Stage A — VPS live as a reader**

1. **Merge this PR.** Then update the office to `main`: the project folder and `main-runtime`. Restart the office web and scheduler.
2. **Office: one channel key.**
   1. Generate the key and save it in the password manager:
      ```powershell
      venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
      ```
   2. Add it once to the project `.env` as `OMNI_CREDENTIALS_KEY=<key>`, then restart the office web and scheduler.
   3. Re-encrypt the stored credentials:
      ```powershell
      venv\Scripts\python manage.py omni_credentials --rekey
      ```
   4. If it lists accounts and no `unreadable` rows, run it again with `--apply`.
   5. Then `venv\Scripts\python manage.py omni_credentials` must end with `OK`.
3. **Office: `COUNSEL_PHONE_HASH_KEY`.** Follow [owner steps §2](2026-11-owner-go-live-steps.md#2-counsel_phone_hash_key). The office and the VPS need the same value.
4. **VPS `.env`.** Run `sudo -u elrezeiky nano /opt/elrezeiky/app/.env` and set:
   - `OMNI_CREDENTIALS_KEY=` the key from step 2;
   - `COUNSEL_PHONE_HASH_KEY=` the key from step 3;
   - `LIFECYCLE_HOLD_ROOT=/opt/elrezeiky/app/media_hold`.

   Then:
   ```bash
   sudo -u elrezeiky mkdir -p /opt/elrezeiky/app/media_hold
   grep -cE '^(OMNI_CREDENTIALS_KEY|COUNSEL_PHONE_HASH_KEY)=.+' /opt/elrezeiky/app/.env
   ```
   The `grep` must print `2`.

   **Do this before step 5.** The release script now on the VPS still runs `check --deploy` after `migrate`. A leftover `OMNI_CREDENTIALS_KEY=CHANGE` would stop it half-way.
5. **Release.**
   ```bash
   sudo /opt/elrezeiky/release.sh
   ```
   Then install the new script:
   ```bash
   sudo install -o root -g root -m 700 /opt/elrezeiky/app/deploy/release.sh /opt/elrezeiky/release.sh
   ```
   Then check the role and the channel key:
   ```bash
   cd /opt/elrezeiky/app && sudo -u elrezeiky /opt/elrezeiky/venv/bin/python manage.py writer_status --expect reader
   cd /opt/elrezeiky/app && sudo -u elrezeiky /opt/elrezeiky/venv/bin/python manage.py omni_credentials
   ```
   `writer_status` must show `ROLE = reader`. `omni_credentials` shows `OK` once the office database has been copied over; before that it has nothing to check.
6. **nginx, by hand.** Make the three edits in [owner steps §1](2026-11-owner-go-live-steps.md#1-nginx-on-the-vps-compression--indexhtml-never-cached) (gzip and `index.html` no-cache). Then copy the new `location ~ ^/api/finance/gl/(…)` block from `deploy/nginx.conf` (the block with `proxy_read_timeout 600s`) and put it **above** `location /api/`. Then:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```
   Tell testers that what they enter is a sandbox and will be lost at cutover.

**Stage B — cutover (unchanged since 2026-11-07, plus 11 and 12)**

7. **Switch table.** Decide the A/P and insurance writers and sign the P-54 table. See [owner steps §3](2026-11-owner-go-live-steps.md#3-the-writer-switch-table-check-and-sign). It takes about 20 minutes.
8. **Backups.** Set up the nightly dump, the off-site pull and one tested restore, and open the LDC snapshot ticket. See [owner steps §4](2026-11-owner-go-live-steps.md#4-backups-nightly-dump-off-site-copy-a-tested-restore-snapshots). It takes 2–3 hours.
9. **Worktree `.env` files.** Make the old worktree `.env` copies read-only. See [owner steps §5a](2026-11-owner-go-live-steps.md#5a-now-the-worktree-copies-only). It takes about 10 minutes.
10. **Ain Shams route** on the HQ MikroTik. See [owner steps §6](2026-11-owner-go-live-steps.md#6-ain-shams-route-on-the-hq-mikrotik). It takes about 20 minutes.
11. **Cutover day.** Follow W0–W9 in [`docs/GO_LIVE_CHECKLIST.md`](../GO_LIVE_CHECKLIST.md). After the database copy, the VPS must print `OK` for `manage.py omni_credentials`. Then:
    - stop the office AMI bridge;
    - run `sudo systemctl enable --now elrezeiky-ami-bridge` (runbook §11);
    - move the attendance agent to the VPS ([attendance doc §11](2026-11-attendance-agent-go-live.md)).
12. **After cutover.** Finance GL needs the chart of accounts, the opening balance and the party import on the VPS. Use `import_gl_coa`, `import_gl_opening` and `import_gl_parties`, unless they were already done in the office database before the copy. Keep `GL_DRAFTING_SCHEDULE_ENABLED=False` until finance confirms the parties.

Still not confirmed by the owner from 2026-11-07:
- **B8**: where the VPS stands (`.env`, TLS, rehearsal restore).
- **B9**: the SSTP secret and the smoke-test admin password, which appeared in chat, have not been rotated.

## Not checked

- Nothing on the VPS, the MikroTik or SOFTECH was contacted. The VPS's current migration state is unknown, so `migrate --plan` was checked from an empty database, not from the VPS state.
- The full backend suite and the security sweeps were left to CI. Only focused tests were run locally (PC memory).
- `check --deploy` was run on Windows with dummy production-like values, not under systemd.
