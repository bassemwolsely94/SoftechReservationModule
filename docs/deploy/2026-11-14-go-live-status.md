# Go-live status — `origin/main` → LDC VPS (2026-11-14)

Checked on `origin/main` = `d5567155` (PR #127), 92 commits after the [2026-11-12 check](2026-11-12-go-live-status.md) at `063da6fe`.
Nothing was deployed. Nothing was changed on the VPS, in SOFTECH, or in any `.env`. The office `.env` was read for key **names** and on/off switches only.
The full how-to for every owner step is in [owner steps](2026-11-owner-go-live-steps.md) and the [2026-11-12 status](2026-11-12-go-live-status.md); this page only says what changed.

| Stage | Verdict |
|---|---|
| **A** (VPS live as a reader, office stays the writer) | **GO** once owner steps 2–6 of the 2026-11-12 page are done (step 1 is done). About 1 hour. |
| **B** (cutover: the VPS becomes the only writer) | **NO-GO** until owner steps 7–12 are done. On cutover day, follow the tax steps too (T below, added by #133). |

## What merged since 2026-11-12

| Area | PRs | Go-live effect |
|---|---|---|
| Go-live fixes G1–G4 (channel key, counselling warning, `release.sh` order, lifecycle keys) | #117 | Done. The new `release.sh` must be installed on the VPS after the first release (step 5). |
| Tax invoicing (ETA e-invoice and e-receipt), signing agent, code check, GS1, receipt start date | #99, #120, #121, #123, #126, #128–#130 | Adds `tax_invoicing` migrations and 4 writer flags. All default off and the production template keeps them off. See **T** below. |
| Multi-select filters | #115, #116, #118, #119 | Screens only. |
| SOFTECH probes, branch classification | #110, #127 | `branches` migrations; no new SOFTECH write site. |

## Checked and green

| Area | Result |
|---|---|
| New settings keys | Every key added to `config/settings.py` since 2026-11-12 has a safe default: the tax keys are empty or off, the signer is `NotConfiguredSigner`, and `TAX_ALLOW_MOCK_SIGNER=False`. The VPS boots without any of them. |
| Writer flags | `config/writers.py` now lists 28 flags (24 SOFTECH + 4 tax). The tax gates (`submission.py`, `receipts.py`, `coding.py`, `environment.py`) read them through `writer_allowed()`, so a reader instance can never send to the tax authority. W1 (office → reader) therefore also stops tax sending in the office. |
| Production template | Has the 4 tax flags set to `False`, `OMNI_CREDENTIALS_KEY=` empty, and the lifecycle keys. |
| `release.sh` | Builds the frontend and runs `check --deploy` before the migration prompt, and restarts the AMI bridge if it runs. |
| Tax signing agent | Its `config.example.ini` already points at `https://elrezeikyapp.dawalvry.com`, so it is aimed at the VPS. |

## Office state (read 2026-11-14, names only)

| Item | State | Effect on the owner steps |
|---|---|---|
| `OMNI_CREDENTIALS_KEY` | not set | `omni_credentials` shows **no stored channel credentials** (4 empty rows, 0 derived, 0 unreadable). Step 2 shrinks to: generate the key, save it in the password manager, put it in the office `.env` and the VPS `.env`. There is nothing to re-encrypt. |
| `COUNSEL_PHONE_HASH_KEY` | not set | Step 3 is still to do. The office and the VPS need the same value. |
| Role | `WRITER_INSTANCE=True`, `SOFTECH_READ_ONLY=False` | Expected until W1. |
| Tax | `TAX_ETA_ENVIRONMENT=preprod`, `TAX_ERECEIPT_SUBMIT_ENABLED=True`, `TAX_ETA_CODING_ENABLED=True` | The office sends e-receipts to the tax authority's **pre-production** system. See T. |

## T — tax cutover steps (done: PR #133)

The tax steps are now in [`2026-11-tax-cutover-steps.md`](2026-11-tax-cutover-steps.md), linked from the checklist and the P-54 switch spec:
W1 (the office stops sending), W3 tax drain, W5 (the database copy carries the tax state and the e-receipt chain), W6 tax keys for the VPS `.env` (names only), W7 tax flags after the SOFTECH writers, the signing agent on 192.168.1.8, and rollback.
Stage B now waits only on owner steps 7–12, with these tax steps followed on cutover day.

## Open PRs (none needed for Stage A)

| PR | What | State |
|---|---|---|
| #122 | Roles registry | Merged 2026-11-14 |
| #124 | Crews «الأطقم» foundation | CI running; its session merges when green |
| #125 | Item and channel code maps | Merged 2026-11-14 |
| #131 | ETA history mirror, phase 1 (read-only; switches off) | Merged 2026-11-14 |

## Developing after go-live

The plan is unchanged and is in runbook §13:

- **Office laptop** (after W1): stays a read-only development copy. It never writes to SOFTECH again, and every new worktree `.env` is copied from the main `.env` after W1.
- **VPS workbench** `/home/bassemwolsely94/work/app`: VS Code Remote-SSH, and Claude Code with the project memory copied over (§13.3). It reads live data through `elrezeiky_work` (read-only), runs no scheduler and no website, and previews screens with Vite through an SSH tunnel (§13.4).
- **Releasing:** only Git → PR → CI green → `main` → `sudo /opt/elrezeiky/release.sh` (§13.5). Never edit `/opt/elrezeiky/app` by hand.
- **On the 8 GB VPS**, run focused tests only and leave the full suite and security sweeps to CI. Parallel test runs exhausted the office PC's memory on 2026-11-12. On the VPS they would compete with the live site.

## Still not confirmed by the owner

- **B8:** where the VPS stands (`.env`, TLS, rehearsal restore).
- **B9:** the SSTP secret and the smoke-test admin password, which appeared in chat, have not been rotated.

## Not checked

- Nothing on the VPS, the MikroTik, SOFTECH or the tax authority was contacted.
- No local test run (PC memory). CI on `main` for #127 was still running at the time of this check; #130 and earlier were green.
