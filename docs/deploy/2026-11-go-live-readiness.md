# Go-live readiness — `origin/main` → LDC VPS (2026-11-04)

Read-only review. Nothing was deployed, pushed to the server or changed on it.
- Reviewed commit: `origin/main` = `60fb01ad` (PR #59, counselling). The review started on `625e2ba0`; `main` moved during it, and every result below is restated for `60fb01ad`.
- `main` keeps moving (a forecasting docs commit landed after `60fb01ad`). Re-check `release.sh`'s `migrate --plan` output on the day.
- Companion docs: [`docs/GO_LIVE_CHECKLIST.md`](../GO_LIVE_CHECKLIST.md) (order and owner steps W0–W9) and [`deploy/LINKDATACENTER_VPS_RUNBOOK.md`](../../deploy/LINKDATACENTER_VPS_RUNBOOK.md) (commands).
- This page does **not** repeat those. It lists what still stands between `main` and live users, and what changed since the checklist was written (`6de9fedb` → `60fb01ad`).

## Verdict

| Stage | Verdict | Why |
|---|---|---|
| **A. VPS live as a reader** (users test on real data; office stays the SOFTECH writer — checklist "Day −1") | **GO** (owner items B8, B9 first) | No code blocker. `main` is green in CI at `60fb01ad` (5406 tests OK) and the frontend builds. The deploy kit, kill-switches and flags are in order. B1, the red CI found earlier in this review, was fixed on `main` during the review. |
| **B. Cutover** (VPS becomes the only SOFTECH writer — checklist "Day 0", runbook §11) | **NO-GO until B2–B7** | All owner items: the switch table has two conflicting rows and is unsigned, there is no off-site backup or tested restore, 12 office `.env` copies can still write, Ain Shams is unreachable, ISR #30/#32 are still open. |

> **Decide before stage A (owner):** the runbook throws the rehearsal database away at cutover (§10.2 → §11.4 restores a fresh office dump).
> Anything testers enter on the VPS during stage A (reservations, demand, notes, claims) is **lost** at cutover.
> Either tell testers it is a sandbox, or keep stage A short and cut over soon after.

## Blockers

Owner = who has to act. **code** = a change in the repo. **owner** = a decision, credential or server/router action.
Fix size: XS < 1 h, S ≈ half a day, M ≈ 1–2 days.

| # | Blocks | Blocker | Owner | Size |
|---|---|---|---|---|
| ~~**B1**~~ ✅ | A, B | **RESOLVED on `main` during this review** (PRs #55, #56, #59, plus `6188955e`, `cfc098de`, `11993212`; CI run 41757408306 on `60fb01ad` is green). It is kept here for the record. <br>**`main` failed CI.** Run 41728342697 (`2db7b6ab`) ended `Ran 5285 tests … FAILED (failures=3)`. The local run on `625e2ba0` had 7 failures: the 3 below, plus 4 from the `usage_print` merge (permission-matrix doc stale, no branch-scope row, `/api/usage-print/` prefix unclassified, SQL built from text in `apps/usage_print/lookup.py::_read_live`). The 3: <br>1. `test_role_sweep.test_unproven` — 51 new `/api/stockcount/daily/*` routes answer 404 for every role, because `DAILY_COUNT_ENABLED` is off. They need entries in `baselines/role_unproven.txt` (reviewed), or the sweep must turn the flag on. <br>2. `test_endpoint_sweep.test_public_views_are_exactly_the_reviewed_set` — `apps.access.public_views.health` (`/api/public/health/`, which `release.sh` and the uptime monitor depend on) is not in `KNOWN_PUBLIC_VIEWS`. <br>3. `test_static_guards.test_exports_neutralise_formulas` — `apps/stockcount/daily/views.py::_report_xlsx` saves a workbook without `core.export_safety.neutralise_formulas`. Staff and branch names go into the cells, so this is a real (small) formula-injection gap, not only a baseline. | code | XS |
| **B2** | B | **The switch table contradicts itself on two writers.** <br>- `AP_RECONCILE_WRITER_ENABLED`: the P-54 appendix says "ON" and the checklist says the office has it ON. Runbook §11.6 says "A/P (still OFF — it was gated OFF in the office)". <br>- `INSURANCE_SOFTECH_WRITE_ENABLED`: the checklist says the office has it ON (re-price writeback is live). The P-54 appendix says "currently OFF everywhere". <br>- `AP_RECONCILE_UPDATE_PATIENTDATA` is in the `.env` template but has no row in the table. <br>W7 says "never more than the office had", so the table must say what the office really has. | owner | decision |
| **B3** | B | **The P-54 switch table is unsigned** (`06_SPEC_P-54` appendix: every "Initials / date" cell is empty). W7 uses it as the pass condition. | owner | XS |
| **B4** | B | **No proven backup.** The nightly `pg_dump` cron (§12.1) is runbook text only. There is no off-site copy, LDC snapshots are 0 on this plan (checklist item 13), and no restore has been tested. `release.sh` takes a pre-release dump, but on the same disk. Before the VPS is the system of record: cron + `.pgpass`, an off-site pull to HQ, one test restore (`createdb elrezeiky_restore_test` → `pg_restore` → row counts → `dropdb`), and the LDC snapshot ticket. | owner | S |
| **B5** | B | **13 office `.env` files can write to SOFTECH**: the project `.env` plus 12 worktrees with `WRITER_INSTANCE=True` + `SOFTECH_READ_ONLY=False`. The checklist counted 9. New since then: `finance-gl`, `finance-gl-plan2-28e4b9`, `finance-gl-plan3-d34b10` — the GL sessions running right now. Any server, scheduler or command started there can write. The W1 PowerShell block already flips every `.claude\worktrees\*\.env`. The point is to run it, then re-run its check right before W4, because sessions keep creating worktrees. | owner | XS |
| **B6** | B | **Ain Shams node** (192.168.3.10:5000) times out over the tunnel (checklist §0). Until it is routed, that branch's syncs fail on the VPS. With the office stopped at W4, that branch's data goes stale. | owner (router) | S |
| **B7** | B | **Duplicate ISR drafts #30 / #32** of the already-pushed #29 must be cancelled on the office before the final dump (W3). Otherwise they can be pushed again from the VPS (double post). | owner | XS |
| **B8** | A | **VPS state is unconfirmed** for runbook §8.2–§10: `.env` secrets, OCR sidecar + `ocr_tessdata/`, units, nginx, TLS, DNS, rehearsal restore (checklist §0, "owner confirms"). The N0–N6 runbook text says "the live server", so the web may already run. Owner to report where it stands. | owner | XS (to report) |
| **B9** | A | **Rotate the secrets that appeared in chat** (SSTP secret `elrezeiky-vps`, smoke-test admin password) before real users log in. | owner | XS |

## Test and build results

**Backend — CI on `60fb01ad` (the reviewed head)**, run 41757408306, Ubuntu + Postgres 15:
```
Ran 5406 tests in 2398.586s
OK (skipped=12, expected failures=2)
```
Frontend job: success.

**Backend — local runs** (Windows, PostgreSQL, unique `TEST_DB_NAME` each):
- Full suite on `625e2ba0` (serial): the 7 failures it found are listed under B1, all since fixed.
  ```
  Ran 5304 tests in 9546.898s
  FAILED (failures=7, skipped=12, expected failures=2)
  ```
  (A `--parallel 4` attempt crashed in the Windows test runner with a `PicklingError` while reporting results. That is a harness problem, not a test result; CI runs serially.)
- Go-live, security-guard and changed-app suites on `60fb01ad`: `test_go_live`, `test_writer_instance`, `test_endpoint_sweep`, `security.test_static_guards`, `security.test_permission_matrix`, `security.test_role_sweep`, `test_help`, `counselling`, `usage_print`, `stockcount`.
  ```
  Ran 202 tests in 1704.390s
  OK
  ```

**Backend — CI history on `main`:**
- 41709846218 (N6 docs) green.
- 41722950177 (go-live kit) and 41728342697 red, with `failures=3`.
- 41757408306 (`60fb01ad`) green.

**Migrations:** `manage.py makemigrations --check --dry-run` on `60fb01ad` → `No changes detected` (exit 0).
- New since the checklist (`6de9fedb`):
  - `audit 0031–0036`, including the merge `0035_merge_20261104_0307`;
  - `branches 0011`;
  - `stockcount 0004`;
  - `usage_print 0001–0002`;
  - `counselling 0001–0002` (new app);
  - `callcenter 0010`, `pos_orders 0017`, `reservations 0022` (missed sales and calls);
  - `users 0045–0047`, including the merge `0046_merge_20261104_0307`.
- Two parallel branches each added an `audit 0031` and a `users 0045`; the merge migrations reconcile them, and the check is clean.
- All of them are Postgres-side tables, columns and choices. **None** touches the SOFTECH schema or sync.
- `release.sh` prints the plan and asks before it applies.

**Frontend — `npm ci && npm run build`** on `60fb01ad`:
```
CI EXIT 0
✓ 1610 modules transformed.
../staticfiles/frontend/assets/index-DThkzViU.js   5,071.91 kB │ gzip: 1,228.56 kB
(!) Some chunks are larger than 500 kB after minification.
✓ built in 43.02s
BUILD EXIT 0
```
Passes. The size warning is a non-blocker; see N4.

## What was checked and is in order

- **Deploy kit vs code.** `release.sh` gives one ordered run: pre-release `pg_dump` → `pull --ff-only` → pip (CPU torch first) → OCR sidecar deps only when changed → `migrate --plan` + y/N confirm → migrate → `npm ci && build` → `collectstatic` → `check --deploy` → `writer_status` → restart **all** processes (P-56) → 60 s health wait with rollback hint.
  - The units and nginx in `deploy/` use `/opt/elrezeiky/…`, and runbook §9.1/§9.2 `sed` them to `/opt/elrezeiky/app/…`. That is consistent with `release.sh` (`APP=/opt/elrezeiky/app`) and with `STATIC_ROOT`/`MEDIA_ROOT = BASE_DIR/…`.
  - The OCR unit already uses `/opt/elrezeiky/app/ocr_sidecar`, with `MemoryMax=2G` and `CPUQuota=200%` for the 8 GB budget.
- **Env template vs settings.** `deploy/production.env.example` boots as a reader (`WRITER_INSTANCE=False`, `SOFTECH_READ_ONLY=True`) and lists all 24 `config/writers.py WRITER_FLAGS` as `False`. `apps/tests/test_go_live.py` keeps this true.
  - 252 keys are read through `config()`; 86 are in the template.
  - The unlisted ones fall back to code defaults. None of them can write to SOFTECH: every write needs `WRITER_INSTANCE` **and** its flag (`config/writers.py`), **and** passes the driver-level kill-switch in `config/sybase.py`.
- **SOFTECH write channels.** There are two independent locks.
  - `writer_allowed(flag)` = `WRITER_INSTANCE and <flag>`.
  - `SOFTECH_READ_ONLY` refuses every non-read statement at the JDBC proxy.
  - The writer jobs (`pos_orders_flush`, `pos_cancel_write`, `coverage_topup`, `demand_engine_scheduled`) are not even scheduled on a non-writer instance.
  - `writer_status --expect reader|writer` is the scripted check, and it fails on a duplicated `.env` key.
  - The new features since the checklist ship dark and are read-only toward SOFTECH: `DAILY_COUNT_ENABLED` (hourly job, gated inside the job, plus a per-branch pilot switch), `CAMERA_SCAN_ENABLED`, `USAGE_PRINT_ENABLED` and the counselling app (`COUNSELLING_CONTENT_ENABLED`, `COUNSEL_CARD_SEND_ENABLED`, default off; it has no SOFTECH connection).
- **Recommended values at go-live:**
  - Stage A: everything as in the template (reader).
  - Stage B: the signed table, after B2. Leave these OFF: `POS_WRITER_ENABLED` (P-39 parity), `ISR_AUTO_APPROVE_ENABLED`, `REPLACEMENT_POSTING_ENABLED` (B4 returns not built), `CUSTOMER_MERGE_WRITE_ENABLED`, `PRICING_SOFTECH_WRITE_ENABLED`, `REPLICATION_REPAIR_ENABLED` and `LOYALTY_SOFTECH_WRITE_ENABLED`. Keep `SOFTECH_PROBES_ENABLED=False`, and keep `PHANTOM_APPLY_REDUCTION` at its default `False`.
- **Security switches (N0–N6).** In both the template and the defaults, these are `log`: `RBAC_ENFORCEMENT`, `NETWORK_POLICY_ENFORCEMENT` (N3), `SOFTECH_GATE_ENFORCEMENT` (N4), `BULK_READ_ENFORCEMENT` (N5) and `PUBLIC_API_ENFORCEMENT` (N6).
  - N0 (nginx headers, admin allow-list, `DJANGO_ADMIN_ENABLED=False`), N1 (zone label) and N2 (device registry, refuses only blocked devices) are on by design.
  - That is the right state for go-live: nothing is refused that would surprise testers, and the logs fill up for the enforce decisions.
  - Flip order after go-live: `RBAC_ENFORCEMENT=enforce` at W8, then N3 → N6, one per quiet week (checklist §4).
  - Precondition before any `enforce`: `NETWORK_HEADER_TRUSTED=True` only with nginx + `elrezeiky-proxy-headers.conf` as the sole entry (the gate refuses enforce otherwise — `access.E004`, seen in the test log).
- **Cutover §11 / W0–W9.** The order makes two writers impossible (W1 reader everywhere → W2 verify → W3 drain → W4 stop → W5 restore as reader + scheduler → W6 writer role with all flags off → W7 one flag at a time with SOFTECH read-back). The rollback path is written down. No code change is needed; the open items are B2–B7.
- **`docs/architecture/09_TECHNICAL_DEBT_REPORT.md`** (last edited 2026-08-18) is largely stale, and **nothing in it blocks go-live**:
  - C001 (role guards): RBAC exists, in log mode.
  - C002 (manual ERP writes): replaced by the writer flags.
  - H003 (pagination): DRF default `PageNumberPagination`, `PAGE_SIZE=50`.
  - H005 (error boundaries): `ErrorBoundary` in `Layout`, `MobileLayout` and `PortalLayout`, with stale-chunk detection.
  - H007 (`hmac.new`): that is the correct stdlib call.
  - M007 (demand number race): `DEM-{pk}` comes from the primary key.
  - M001 (finance scaffold): true. The GL work is in progress on its own branches, so don't point testers at `/finance` yet.

## Non-blockers worth doing in the first week

| # | Item | Owner | Size |
|---|---|---|---|
| N1 | Add `DAILY_COUNT_ENABLED=False`, `CAMERA_SCAN_ENABLED=False`, `COUNSELLING_CONTENT_ENABLED=False` and `COUNSEL_CARD_SEND_ENABLED=False` to `production.env.example`, so every dark feature is visible in one place. | code | XS |
| N1b | `COUNSEL_PHONE_HASH_KEY` defaults to a constant that is in the repo (`elrezeiky-counsel-phone-v1`). Give production its own secret value in the `.env` **before** the first counselling opt-out is stored: changing it later breaks the existing opt-out hashes. | owner (+ template line) | XS |
| N2 | `SOFTECH_READ_ONLY` defaults to `False` when the key is missing. `WRITER_INSTANCE` (default `False`) still closes every writer gate, but the driver-level lock is then open. Option: default `SOFTECH_READ_ONLY` to `not WRITER_INSTANCE`. | code | XS |
| N3 | `release.sh` does not redeploy changed `deploy/*.service` or `nginx.conf` (they are copied by hand once). Have it print a warning when `git diff OLD..NEW -- deploy/` is non-empty. | code | XS |
| N4 | One 5 MB JS chunk (1.2 MB gzipped). The Ubuntu nginx default compresses only `text/html`, so branches download ~5 MB per device on first load. Add `gzip_types application/javascript text/css application/json;` to the site file. Code-split later. | owner (nginx) + code | XS / M |
| N5 | `index.html` is served with `expires 1h`. After a release, browsers may ask for deleted hashed chunks for up to an hour; `ErrorBoundary` recovers, but `Cache-Control: no-cache` on `index.html` avoids it. | code | XS |
| N6 | `deploy/DEPLOY.md` (older generic guide) overlaps with the runbook. Mark it as superseded, so nobody follows two guides. | code | XS |
| N7 | Settings that default ON without being listed: `AP_RECONCILE_AUTO_APPROVE`, `CUSTOMER_MERGE_QUEUE_ENABLED`, `REPLACEMENT_DAILY_CHECK_ENABLED`, `STOCK_AUDIT_ENABLED`, `GAMIFICATION_ENABLED`, `POS_ENFORCE_STOCK`, `CUSTOMER_STATUS_DRIFT_CHECK_ENABLED`, `PHANTOM_SCAN_IN_ENGINE_RUN`. They are internal to Postgres (no SOFTECH write). List them in the template so the owner sees them. | code | XS |
| N8 | External channels (W9): the WhatsApp/Meta webhooks, AMI and VAPID can follow by a day. SMS stays off until the provider is chosen (W-1). | owner | — |

## Suggested order from here

1. **code (XS, optional before stage A):** one small PR for N1/N1b/N3/N5/N6/N7. B1 is already fixed on `main`.
2. **owner:** B8 (report VPS state), B9 (rotate secrets), then `release.sh` → stage A (the VPS as a reader, testers in, sandbox caveat announced).
3. **owner, while testers work:** B2 + B3 (resolve and sign the table), B4 (backup + test restore), B6 (Ain Shams route).
4. **cutover day:** B7 + B5 at W1/W3, then W0–W9 unchanged.
