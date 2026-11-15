# Go-live status — `origin/main` → LDC VPS (2026-11-15)

Checked on `origin/main` = `8f8a1452` (PR #137; last code PR #136 at `2e5de23a`), after the
[2026-11-14 check](2026-11-14-go-live-status.md) at `d5567155`.
Nothing was deployed. Nothing was changed on the VPS, in SOFTECH, in the tax authority, or in any `.env`.
The full how-to for every owner step is in [owner steps](2026-11-owner-go-live-steps.md), the
[2026-11-12 status](2026-11-12-go-live-status.md) (steps 1–12), the [checklist](../GO_LIVE_CHECKLIST.md) (W0–W9) and the
[tax cutover steps](2026-11-tax-cutover-steps.md). This page says what changed and gives **one list of what is left**.

| Stage | Verdict |
|---|---|
| **A** (VPS live as a reader, office stays the writer) | **GO** once owner steps A2–A6 below are done. About 1 hour. No code is waiting. |
| **B** (cutover: the VPS becomes the only writer) | **NO-GO** until B7–B10 are done and the pre-cutover checks pass. Then cutover day (B11) and the GL import (B12). |

## What merged since 2026-11-14

| Area | PRs | Go-live effect |
|---|---|---|
| ETA history mirror: phase 1, search, screens | #131, #135, #136 | `tax_invoicing` 0010–0011. 8 new keys (below), all read-only, off by default. Two new scheduler jobs (`eta_history_backfill`, `eta_history_topup`); both are guarded. |
| Crews «الأطقم» foundation | #124 | New app `crews` (0001), `users` 0057, `hr` 0012–0014. `hr` 0014 is a **data** migration: every employee with no assignment row gets one open row (idempotent, safe on an empty database). API prefix `crews` is mapped (edit = `crews edit`). |
| Roles registry | #122 | Screens and role checks only. |
| Item and channel code maps | #125 | `config` 0004, `forecasting` 0014, `audit` 0042, `chronic` 0006 (choices only). |
| Go-live and tax cutover docs, handoff | #132, #133, #134, #137 | Docs only. |

## Checked and green

| Area | Result |
|---|---|
| New settings keys | 8 keys since 2026-11-14, all `TAX_ETA_READ_*` / `TAX_ETA_HISTORY_*`: both read switches default `False`, the logins default empty, the start dates have fixed defaults. All 8 are in both templates with the switches `False`. The VPS boots without any of them. |
| Writer flags | `config/writers.py` still has **28** flags (24 SOFTECH + 4 tax). Unchanged since 2026-11-14; the SOFTECH write manifest is unchanged. The ETA history reader is not a writer flag (it reads ETA and never writes SOFTECH); W1 turns it off by hand (tax cutover page). |
| Production template | Writers off, `OMNI_CREDENTIALS_KEY=` empty, lifecycle keys, and the 8 new keys with the read switches off. |
| Migrations | `makemigrations --check`: no changes. 12 new migration files since 2026-11-14 (listed above); the test run below builds the whole chain from zero. |
| Tests (local, serial, own test DB) | `test_go_live`, `test_go_live_2026_11_12`, `test_scheduler_locks`: **35 OK** on a test database built from zero (so every migration applies cleanly, and every scheduler job, including the two ETA history jobs, is in `SCHEDULER_JOB_GUARDS`). |
| CI on `main` | Green at `2e5de23a` (#136). The run for `8f8a1452` (#137, docs only) was still going. |

## Found in this check

| # | Finding | What to do |
|---|---|---|
| F1 | **The office runtime was down** (PC restart at 04:44, nothing started on its own). | **Fixed 2026-11-15:** web, scheduler (one), AMI bridge and screens restarted. A Windows Startup entry now starts all four at logon and skips any already running. W4 on cutover day must delete it (see the [cutover day sheet](2026-11-cutover-day-sheet.md)). |
| F2 | `main-runtime` was at `cd39dc84` (#135), behind `main`. | **Fixed:** moved to `main`. `tax_invoicing` 0011 was already applied to the office database. |
| F3 | `TAX_ETA_HISTORY_RECEIPTS_START` (default `2025-01-01`) is not in the W6 key table of the tax cutover page. | Nothing to type: the default is right unless the owner wants another start. Copy the office value if it was changed. |

## Open PR

| PR | What | Needed for go-live? |
|---|---|---|
| #138 | ETA receipts reconciliation, phase 3 (read-only; adds `tax_invoicing` 0012 and the guarded daily job `eta_recon_daily`) | No. When it merges, the VPS `migrate` picks up 0012. After merge, the owner runs the one-time `eta_recon` backfill (see the PR). |

---

## What is left — one list

Owner-only unless marked. Never paste a key or password into a Claude chat.

### Stage A — VPS live as a reader

| # | Step | How | Done when |
|---|---|---|---|
| A0 | ~~Office back up (F1, F2)~~ **done 2026-11-15** | — | port 8000 answers; one scheduler |
| A2 | `OMNI_CREDENTIALS_KEY`: generate, save in the password manager, add to the office `.env`, restart | 2026-11-12 page, step 2. Nothing to re-encrypt (office has no stored channel credentials). | `manage.py omni_credentials` ends `OK` |
| A3 | `COUNSEL_PHONE_HASH_KEY`: one value for office and VPS | owner steps §2 | `check --deploy` shows no `counselling.W001` |
| A4 | VPS `.env`: the two keys above + `LIFECYCLE_HOLD_ROOT=/opt/elrezeiky/app/media_hold`; create the folder. **Before A5.** | 2026-11-12 page, step 4 | the `grep -c` prints `2` |
| A5 | `sudo /opt/elrezeiky/release.sh`, then install the new `deploy/release.sh` over it | 2026-11-12 page, step 5 | `writer_status --expect reader` → `ROLE = reader` |
| A6 | nginx by hand: gzip, `index.html` no-cache, and the `/api/finance/gl/(…)` block (600 s) **above** `location /api/`; `nginx -t && reload` | owner steps §1 + 2026-11-12 step 6 | `nginx -t` ok; `curl -I` shows `no-cache` on `/` |
| A7 | Tell testers: what they enter on the VPS is a sandbox, lost at cutover | — | — |
| A8 | **Claude:** verify the VPS with read-only commands the owner runs and pastes back (no secrets) | — | — |

### Stage B — cutover

**Before cutover day**

| # | Step | How |
|---|---|---|
| B7 | Sign the P-54 writer switch table; decide the A/P and insurance writers | owner steps §3, `docs/product-review/06_SPEC_P-54_cutover_single_writer.md` (~20 min) |
| B8 | Backups: nightly dump, off-site pull, **one tested restore**, LDC snapshot ticket; confirm VPS `.env` and TLS | owner steps §4 (2–3 h) |
| B9 | Old worktree `.env` copies read-only | owner steps §5a (~10 min) |
| B9b | Rotate the secrets that appeared in chat: SSTP secret, smoke-test admin password, ETA portal secrets of "ElRezeiky ERP Extension" | MikroTik + `/etc/ppp`; admin user; ETA portal |
| B10 | Ain Shams route on the HQ MikroTik | owner steps §6 (~20 min) |
| B10b | Uptime monitor on `/api/public/health/` every 5 min | checklist §2 item 14 |
| B10c | Pre-cutover checks on the VPS DB: `check_schema_drift`, the live `auto_repair` value, `migrate` (everything since the VPS was last released, incl. users 0052/0053, pbx 0011 and the 12 migrations above), `makemigrations --check` clean | `docs/security/round2/SUMMARY.md` "Left open" |
| B10d | ~~Printable cutover-day page~~ **done:** [cutover day sheet](2026-11-cutover-day-sheet.md) | print it before the day |

**Cutover day (B11)** — W0–W9 in the [checklist](../GO_LIVE_CHECKLIST.md), with the [tax steps](2026-11-tax-cutover-steps.md):
W1 every office `.env` a reader **and** both `TAX_ETA_READ_*_ENABLED=False` · W3 drain incl. tax `0 0 0 0` · W4 stop
everything · W5 DB copy (carries the e-receipt chain), then VPS `omni_credentials` must print `OK` · W6 kill-switch test,
tax keys, writer role with all flags off · W7 writer flags one at a time, tax last, `TAX_ETA_PRODUCTION_ALLOWED` stays
`False` · W8 `RBAC_ENFORCEMENT=enforce` · W9 external channels. Also: stop the office AMI bridge and
`systemctl enable --now elrezeiky-ami-bridge` on the VPS; move the attendance agent
([attendance doc §11](2026-11-attendance-agent-go-live.md)); restart the signing agent on 192.168.1.8 and run «اختبار الختم».

**After cutover (B12)** — on the VPS: `import_gl_coa`, `import_gl_opening`, `import_gl_parties` (unless done in the office
before the copy); keep `GL_DRAFTING_SCHEDULE_ENABLED=False` until finance confirms the parties. If #138 is merged:
the one-time `eta_recon` backfill. Then turn switches on one at a time with the owner (checklist §4).

**Not part of the cutover:** the first production tax invoice and receipt (owner's yes at that moment, per document kind).

## Still not confirmed by the owner

- **B8:** the VPS `.env`, TLS, and the rehearsal restore.
- **B9b:** the SSTP secret, the smoke-test admin password and the ETA portal secrets have not been rotated.

## Not checked

- Nothing on the VPS, the MikroTik, SOFTECH or the tax authority was contacted. The VPS migration state is unknown.
- The full backend suite and the security sweeps were left to CI (PC memory).
