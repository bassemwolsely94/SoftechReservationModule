# Stage 9: Implementation readiness test

- **Target:** `docs/security/2026-11-05-full-project-test-plan.md`, DetailedRange lines 84–212.
- **Reviewers:** `egm-implementation-readiness` and `egm-codebase-details` (both against the
  implementation-readiness standard), plus `egm-style`. All three completed.
- **Verdict:** NOT READY. Both reviewers who checked the code say so.
- **After de-duplication:** 4 Blockers, 14 Majors and 17 Nits.

## Verified by the author (Elephant) before writing this report

- **IB2 is confirmed.** `apps/insurance/date_service.py::_set_motalba_docdate` runs only inside
  `_apply_locked`, which holds:
  - `LOCK_DATE_EDIT = 7_301_008`;
  - the open `SoftechDateEditRun.STATUS_APPLIED` refusal;
  - the `expected_old` re-check.

  `DateEditTests` covers it. The plan, and the manifest's `idempotency=None`, are wrong for this
  site.
- **Contested: the claim that the office laptop is not a writer.** The reviewer read
  `config/writers.py` and the docstrings in `config/settings.py`, which describe the target setup.
  But the owner's runserver log on 2026-11-03 printed `WRITER_INSTANCE=True SOFTECH_READ_ONLY=False`
  with 16 writer flags ON. That matches the P-54 rule that the office is the writer until cutover.
  The plan's statement stays, with the log as its source.

## 🔴 Blockers

**IB1. No file boundary** (readiness #1, codebase M9; all batches)

No batch lists the files it creates, modifies or deletes. No write allowlist can be derived. For
example, `config/settings_e2e.py` does not exist and is not marked Create.

**Fix:** give each batch a Files list.

**IB2. The motalba "missing guard" is wrong** (codebase B1; lines 109–110, Q1 line 196)

It is already guarded (see above). The real recorded gap is that the before-value is not kept and
the write is not reverted.

**Fix:** R1 corrects the manifest entry. Q1 becomes "keep the motalba before-value?". Re-count the
idempotency gaps: 2 sites, not 3.

**IB3. The R1 checks contradict the manifest for many sites** (codebase B2, readiness #3, design M4)

| Check | Sites that cannot pass it |
|---|---|
| Dry-run default | 13 sites have `dry_run_default=False` |
| Audit | about 7 sites record no actor, write to stdout or a logger, or keep no before-value |
| HTTP trigger | about 9 sites are commands only |

Two "writes" are also probes: `probe_ap_writeback` (rolled back) and `test_replication_cycle`.
And "exactly one write" is undefined for absolute-SET writers, which re-stamp `itemlastupdate`.

**Fix:** a per-site table of expected results taken from the manifest, saying which checks apply
to which `kind` and trigger. Plus an exception policy that says whether each mismatch is a hole
(stop-and-ask), an accepted exception (recorded where), or out of scope. State the selection rule:
`kind == 'write'`.

**IB4. The guard design is left to the builder** (readiness #2; lines 109–110)

For `apply_classification_changes` and `force_replication`, choose the mechanism (advisory lock
from the 7301xxx range, done-skip, guarded UPDATE or read-back), the lock ID, where it goes, and
the test that proves it.

## 🟡 Majors

| # | Source | Lines | Finding and fix |
|---|---|---|---|
| IM1 | readiness #4, design M2 | 25, 86, 41–47, 196 | No holding mechanism for owner-pending fixes, and no default if the owner says no. **Fix:** adopt `@pending` plus `apps/tests/security/PENDING.md` and give each question a fallback. |
| IM2 | readiness #5, codebase M4, zoom-out M2 | 92–95 | A migrated test DB can't detect the cited drift. **Fix:** compare against an owner-supplied schema dump or `information_schema` (pattern: `test_purchasehistory_db_defaults.py`), or use a static migration rule. Give the R0 findings table a path. |
| IM3 | codebase M1, M2 | 114–119 | Probe sites gated by `SOFTECH_PROBES_ENABLED` bypass `config/writers.py`; `run_startup_checks` refuses only 2 conditions. **Fix:** name the combinations to refuse, decide on probes, and extend `apps/tests/test_writer_instance.py`. |
| IM4 | codebase M3 | 116–117 | **Fix:** name `config/sybase.py::is_read_only_sql` and the existing `ReadOnlySqlCheckTests` and `test_gl_sources.py::test_open_fetch_refuses_non_select`. The `open_fetch` gate in `sybase_gl.py` (lines 108–119) is a weaker regex that misses newline-separated batches and comment-hidden writes. Fuzz it. |
| IM5 | readiness #6, style #4 | 123–134 | **Fix:** choose between Hypothesis and table tests. Link the SOFTECH formula, points, strip/pack and status-machine sources, and give rounding a mode and precision. |
| IM6 | style #3 | 129, 131 | Table cells are noun phrases. **Fix:** rewrite them as assertions (points equal the formula; a locked period rejects recalculation). |
| IM7 | readiness #7, codebase M5, M6 | 142–146 | **Fix:** extend `test_static_guards.py::test_every_api_prefix_is_classified` and the prefix maps, and give the open-to-staff list a home. For "hidden means forbidden", the visibility rule is `(roles ∪ cap) ∧ module`, nav items hold SPA paths with no API mapping, and a parser already exists in `test_help.py::_anchors`. Pick one mechanism; it overlaps with R8. |
| IM8 | codebase M6 | 138–141 | **Fix:** the branch-manager grants are the staff caps `can_pic_analytics` and `can_stock_audit`. Missed sales sits under the `pos` module and call-backs under `pic_analytics`. `accountant` is already covered by `test_rbac_accountant.py`. |
| IM9 | codebase M7, zoom-out S8 M4 | 150–152 | The canary already finds new models. **Fix:** clear the planter's `skipped` list, and open feature-flagged routes such as daily counts (404 while `DAILY_COUNT_ENABLED` is off). |
| IM10 | readiness #8 | 153–155 | **Fix:** define "secret", how logs are captured, and the masked-phone format, and list the WhatsApp payload paths. |
| IM11 | codebase M8 | 163 | Camera scanning is client-side and daily counts have no uploads. **Fix:** retarget to the session `upload-results` action and reuse `test_platform_upload_limits.py`. |
| IM12 | readiness #9, style #5 | 164–165 | **Fix:** give the throttle numbers, and name the setting or model that holds the allowed numbers. |
| IM13 | readiness #10, codebase N3 | 169–175 | The duplicate-scheduler alert doesn't exist and `run_scheduler` takes no lock, so building it is new work. **Fix:** define the migration cutoff, "column repair", and which sync jobs must resume after a partial failure. |
| IM14 | readiness #11, #12, codebase N5 | 179–192 | **R7:** order the apps, set a minimum per app, and set `--fail-under` in ci.yml line 68. **R8:** create `config/settings_e2e.py`, pick tool versions, config files and scripts, seed the test users, lay out the CI job, and reconcile `npm audit --audit-level=high` with `npm_audit_check.cjs`. |

## 🟢 Nits

| # | Lines | Finding |
|---|---|---|
| IN1 | 99 | "Real" write is undefined; it means `kind == 'write'`. |
| IN2 | 103 | "Recorded `RecordingSybase`" should be "asserted with `RecordingSybase`". |
| IN3 | 110, 197 | Use one term for "the office" / "the office laptop". |
| IN4 | 114–115 | "Supposed to be read-only" should be "must be read-only". |
| IN5 | 97, 121 | Define "stop-and-ask" once. |
| IN6 | 154 | Name the classes of secret. |
| IN7 | 159–160 | `ordering` is ORM `F()` with a 400 fallback, so the risk is a sort oracle, not SQL injection. Wildcard means LIKE escaping; extend `test_wildcard_search.py`. |
| IN8 | 161 | Name `baselines/unsafe_exports.txt` and `test_platform_export_formulas.py`. Define the W-4 date and list the exports. |
| IN9 | 163, 175 | Give the expected behaviour for uploads and sync. |
| IN10 | 175 | There is no "fetch budget". Name `SYBASE_QUERY_TIMEOUT`, `SYBASE_FETCH_TIMEOUT` and `SYBASE_LOGIN_TIMEOUT`. |
| IN11 | 92–94, 172–173 | Use one incident-reference style, with ISO dates. |
| IN12 | 177, 183, 181 | Explain the two numbering schemes; "ratcheted" is jargon. |
| IN13 | 191 | "Never pushed" means "never submitted to SOFTECH". |
| IN14 | 199, 201 | Give the source of the time estimates; "OK?" should be "Is this acceptable?". |
| IN15 | 151 vs 74–82 | One canonical late-module list and cutoff date. |
| IN16 | 205–209 | Give PENDING.md's full path, the TEST_SUITE sections, and where the summary goes. |
| IN17 | 211–212 | Drop the defensive caveat; "listed holes" should be "the gaps listed in R1–R8". |
