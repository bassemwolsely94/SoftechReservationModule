# Go-live readiness re-check — `origin/main` → LDC VPS (2026-11-07)

Read-only review. Nothing was deployed, and nothing was changed on the VPS, in SOFTECH or in the office `.env`. This file is the only change.
- Reviewed commit: `origin/main` = `d1905793` (PR #83), 266 commits after the last review at `60fb01ad`.
- Previous report: [2026-11-go-live-readiness.md](2026-11-go-live-readiness.md). Blocker numbers B2–B9 keep their meaning; C1 and C2 are new.
- Owner commands, checks and undo: [2026-11-owner-go-live-steps.md](2026-11-owner-go-live-steps.md). Order and cutover steps W0–W9: [`docs/GO_LIVE_CHECKLIST.md`](../GO_LIVE_CHECKLIST.md).

## Verdict

| Stage | Verdict | Why |
|---|---|---|
| **A. VPS live as a reader** (testers on real data; the office stays the SOFTECH writer) | **GO after 2 small code items (C1, C2) and owner items B8, B9** | Tests, migrations and build show no product regression. But `main` is red in CI because of one test with an expired date (C2), and a `.env` copied from the template as committed crashes the app at boot (C1). |
| **B. Cutover** (VPS becomes the only SOFTECH writer) | **NO-GO until B2–B6** | No change from 2026-11-04 except a lower `.env` count: the switch table is unsigned, there is no proven backup, 11 office `.env` copies can write, and the Ain Shams route was not reported fixed. |

**The earlier report's "boots as a reader" does not hold for the template as committed.** The cause of C1 was already there at `60fb01ad`, with 22 lines affected then and 36 now.

> **Still to decide before stage A (owner):** the runbook throws the rehearsal database away at cutover (§10.2 → §11.4).
> Anything testers enter during stage A is lost. Tell them it is a sandbox, or keep stage A short.

## Remaining blockers

Size: XS < 1 h, S ≈ half a day. Sizes for owner items are the working time from the owner steps page.

### Code

| # | Blocks | Blocker | Size | Fix |
|---|---|---|---|---|
| **C1** | A (fresh or template-based `.env`) | **The app will not start from `deploy/production.env.example` as committed.** python-decouple 3.8 (the pinned version) does not strip inline comments, so `DJANGO_ADMIN_ENABLED=False  # no 2FA…` raises `ValueError: Invalid truth value` at boot. 36 lines have an inline comment. The env block in runbook §8.2 has them too, and so do 16 lines of `deploy/staging.env.example`. `apps/tests/test_go_live.py` cannot see this: its own regex drops the comment before checking. | XS | Move the comments onto their own lines in both templates and the §8.2 block. Make `test_go_live` read templates with the real decouple parser. |
| **C2** | A (CI signal), and every open PR | **`main` is red.** The last two runs (42301036344, 42315550927) fail on the same single test: `test_cash_view…test_view_drill_inputs_audit_export` (`2000.0 != 5000`). The test uses today's date against a fixture with fixed dates, so it stopped passing on 2026-11-07, Cairo time. Same fixture, same API call, only the date changed: `as_of` 11-05 and 11-06 → 5000; 11-07 and 11-13 → 2000; 11-14 → 0. It is not a money bug. | XS | **Already written:** commit `e4ecd229` on PR #84 pins the date. Merge #84, or cherry-pick that one commit. |

If C1 is not fixed first, the owner can clean a VPS `.env` with this. It was tested on a copy of the template: 36 lines cleaned, 105 keys kept, and the cleaned file boots as a reader and passes `check --deploy`.
```bash
sudo -u elrezeiky cp /opt/elrezeiky/app/.env /opt/elrezeiky/app/.env.bak-comments
sudo -u elrezeiky sed -i -E 's/^([A-Z][A-Z0-9_]*=[^#]*[^#[:space:]])[[:space:]]+#.*$/\1/; s/^([A-Z][A-Z0-9_]*=)[[:space:]]+#.*$/\1/' /opt/elrezeiky/app/.env
grep -cE '^[A-Z][A-Z0-9_]*=.*[[:space:]]#' /opt/elrezeiky/app/.env     # must print 0; prints no values
```
Clean **every** line, not only the True/False ones. Leaving comments on the text values gives `access.E002` and the app refuses to start, because `NETWORK_POLICY_ENFORCEMENT` becomes `'log   # off | log | enforce (N3)'`.

A VPS that already runs has a `.env` that works, so C1 only matters if the file gets rebuilt from the template. B8 settles which case applies.

### Owner

| # | Blocks | Blocker | Today | Size |
|---|---|---|---|---|
| **B8** | A | Report where the VPS stands for runbook §8.2–§10 (`.env`, OCR, units, nginx, TLS, DNS, rehearsal restore). | Unknown to any session | XS |
| **B9** | A | Rotate the secrets that appeared in chat: the SSTP secret and the smoke-test admin password. | Not confirmed | XS |
| **B2** | B | Confirm the corrected switch table values, and decide the A/P writer, the waiting A/P allocations (23 when counted on 2026-11-05) and the insurance writer. | Text corrected on `main`, owner decision open | XS (20 min, with B3) |
| **B3** | B | Sign the P-54 switch table. | **0 of 15 rows signed** | XS |
| **B4** | B | Nightly dump, off-site copy, one tested restore, LDC snapshot ticket. | Nothing in the repo shows it done; owner to confirm | S (2–3 h) |
| **B5** | B | Make the office `.env` copies read-only. | **11 can write:** the project `.env` (correct until cutover) + 10 worktrees. See below. | XS (10 min now, 5 min on the day) |
| **B6** | B | Fix the Ain Shams route on the HQ MikroTik. | Not confirmed | XS (20 min) |

B7 (ISR drafts #30/#32) stays resolved; re-check at W3 only.

## What was checked

### 1. CI and open PRs
| Run | Commit | Result |
|---|---|---|
| 42315550927 | `d1905793` (head) | Backend **failed**: `Ran 6699 tests … FAILED (failures=1, skipped=14, expected failures=2)`. Frontend lint + unit, build and Playwright passed. |
| 42301036344 | `e9940035` | Backend **failed** on the same test. |
| 42287945249 | `1228157c` | Green (ran before midnight Cairo). |

| PR | Must it merge first? | State |
|---|---|---|
| **#84** finance GL Q3 | **Only for its test fix (C2).** Its features are not needed for go-live: SOFTECH access is SELECT only and the drafting schedule stays off by default. | Mergeable, all checks green. Its PR text says the final merge is covered by CI only. Adds `finance 0024`. |
| **#80** insurance print cover | **No.** It corrects a printed cover row (category rows ignored a net override). Worth merging soon, because a printed total that does not add up is confusing, but it does not block either stage. | Mergeable, checks green but from 2026-11-05, so they predate many merges. Re-run CI after C2. |

There are no other open PRs.

### 2. Migrations
`manage.py makemigrations --check --dry-run` → `No changes detected` (exit 0).

31 new migrations since `60fb01ad`: access 0007, approvals 0005, audit 0037–0039, branches 0012, counselling 0003, customers 0032, finance 0020–0023, insights 0004, insurance 0036, notifications 0038–0043, omni 0004, reservations 0023, tasks 0003, transfers 0011, users 0045, 0048–0053.

- **None touches the SOFTECH schema or a SOFTECH connection.** They run on Postgres through Django; a text search of all 31 found no call to the SOFTECH driver.
- **One touches a table the sync fills:** `customers 0032` drops NOT NULL on our own `customers_purchasehistory.invoice_date` (and `users_useractivitylog.target_user_id`). It only loosens a rule on the Postgres side, so existing sync writes still work. It is a no-op where the column is already nullable.
- **Three change who can reach what:** `users 0051–0053` are role-permission data migrations (accountant denials, round-2 owner grants, R8 menu decisions). Testers may see access differ from what they know.

### 3. Frontend
```
npm ci            exit 0
npm run build     exit 0  — 1628 modules, built in 40.84s, largest chunk 699 KB (was 5.07 MB)
```
`npm audit` shows 3 findings (2 critical) in `vitest`/`tinypool`, test tooling only. `npm audit --omit=dev` → `found 0 vulnerabilities`. They do not ship, so this is a non-blocker.

### 4. Writer flags and scheduler jobs
- **No new writer flag.** `config/writers.py` is unchanged: 24 flags, all `False` in the template. `POS_OFFERS_POSDISCP_WRITE` and `POS_OFFERS_PROMO_WRITE` appear in the P-54 table in short form (`_POSDISCP_WRITE / _PROMO_WRITE`), so they are covered.
- **Runbook §11.6 is correct on A/P** after the 2026-11-05 fix. It lists writers by plain name, not by flag name, which is how it was before.
- **One new SOFTECH write site, under an existing flag:** `apps/insurance/date_service.py::_revert_locked`, gated by `INSURANCE_SOFTECH_WRITE_ENABLED`, with a lock and audit. Two pricing and replication write sites were renamed and now have locks. All are in `softech_write_manifest.py`.
- **Four new scheduler jobs (66 → 70). All four are in the `test_scheduler_locks.py` guard table.** None writes to SOFTECH, so they correctly have no row in the P-54 table or §11.6:

| Job | Schedule | Its switch (off by default) | Touches SOFTECH? |
|---|---|---|---|
| `phone_alerts_tick` | every minute | `PHONE_ALERTS_SEND_ENABLED` gates the sending | No driver use in its module |
| `morning_brief` | 09:00 | `MORNING_BRIEF_SEND_ENABLED` gates the sending | No driver use in its module |
| `gl_drafting` | 08:30 | `GL_DRAFTING_SCHEDULE_ENABLED` | SELECT only |
| `payment_exception_checks` | 05:10 | DB setting `payments.exception_checks_enabled` | No driver use in its command |

- **Tests.** Serial, unique `TEST_DB_NAME`, no `--parallel`:
  - `apps.tests.test_go_live` + `apps.tests.test_writer_instance`: `Ran 30 tests … OK`.
  - These pass despite C1, because of the regex noted there.
- The single-scheduler lock added in PR 78 is per database. It does not stop an office scheduler and a VPS scheduler running side by side, so W4 (stop the office) still matters.

### 5. New env keys and office `.env` copies
**New keys since `60fb01ad`: 5. The VPS needs to set none of them** to run; all have safe defaults.

| Key | Default | In template? |
|---|---|---|
| `GL_DRAFTING_SCHEDULE_ENABLED` | False | Yes |
| `PHONE_ALERTS_SEND_ENABLED` | False | Yes |
| `MORNING_BRIEF_SEND_ENABLED` | False | Yes |
| `RBAC_ENFORCED_ROLES` | `accountant` | Yes |
| `SEND_MIN_INTERVAL_SECONDS` | 600 | **No** (harmless; code default is the owner's 10-minute rule) |

`COUNSEL_PHONE_HASH_KEY` is not new, but still has to be set once before the first counselling card is sent (owner steps §2).

**B5 count today:**

| `.env` state | Copies |
|---|---|
| Project `.env`: writer (correct until cutover) | 1 |
| Worktree `.env`: writer (`WRITER_INSTANCE=True` + `SOFTECH_READ_ONLY=False`) | **10** |
| Worktree `.env`: reader | 9 |
| **Total** (61 worktree folders, 19 with a `.env`) | 20 |

Only 1 worktree has a `.bak-golive` backup, so owner step 5a does not appear to have been run. 1 of the 10 writer copies was created or changed in the last 3 days, so **writer copies are still being made or changed**. A new worktree can copy the project `.env`, which stays a writer until W1. Counted before this session made its own reader copy, which has since been deleted.

## Non-blockers worth doing

| # | Item | Owner | Size |
|---|---|---|---|
| N9 | An unedited `SECRET_KEY=CHANGE` boots and passes `check --deploy`, the check `release.sh` runs, with only a warning. `config/settings.py` refuses only the prefix `change-me`. Make it refuse the template's placeholder too. | code | XS |
| N10 | `check --deploy` shows 3 warnings on a clean template: `W005`, `W021` (HSTS subdomains, preload) and `W008` (SSL redirect). They do not fail the release. Confirm nginx does the HTTPS redirect, since Django does not. | code/owner | XS |
| N11 | Add `SEND_MIN_INTERVAL_SECONDS` to the template, so it is visible with the other keys. | code | XS |
| N12 | Upgrade `vitest` to 5.x to clear the dev-only audit findings. It is a major version, so run the frontend tests. | code | XS–S |
| N13 | Open items from the last report: nginx compression + `index.html` step and `COUNSEL_PHONE_HASH_KEY` (owner steps §1, §2). External channels can follow by a day. | owner | XS |

## Not checked

- **VPS, MikroTik and SOFTECH: nothing was contacted.** B4, B6, B8 and B9 are stated as "not confirmed", not as "not done".
- **No live office data was read.** The A/P count of 23 and the "0 live ISR drafts" result are from 2026-11-05, so re-check them at W3.
- **Full backend suite:** taken from CI on `d1905793`, not run locally.
- **Boot tests** used dummy values on Windows, not systemd. The VPS units load the same file through `EnvironmentFile`; that path was not tested.
- **Only the failures visible in one day were found.** Other tests with fixed dates could expire later; this run shows only one has so far.

## Next owner steps

**To open stage A**
1. Tell a Claude session where the VPS stands today: is the site up, and were `.env`, nginx, TLS and the rehearsal restore done? (B8)
2. Change the two passwords that appeared in chat, the SSTP secret and the smoke-test admin password. Don't paste them into chat. (B9)
3. Approve the two small code fixes: merge PR #84 or just its test fix (C2), and have a session fix the template (C1).
4. On the VPS, run `release.sh`, then `writer_status --expect reader`. It must say `ROLE = reader`.
5. Do the nginx step and set `COUNSEL_PHONE_HASH_KEY` (owner steps §1, §2).
6. Tell testers that whatever they enter is a sandbox and will be lost at cutover.

**While testers work, to clear stage B**
7. Decide the A/P and insurance writers, and sign the switch table (B2, B3; 20 min).
8. Set up the nightly backup, the off-site copy and one test restore, and open the LDC snapshot ticket (B4; 2–3 h).
9. Make the 10 old worktree `.env` copies read-only (B5, owner steps §5a; 10 min).
10. Fix the Ain Shams route on the HQ router (B6; 20 min).

**Cutover day**
11. Follow W0–W9 in the checklist. W1 flips the project `.env` and every worktree copy. Re-run its check right before W4, since new worktrees keep appearing.
