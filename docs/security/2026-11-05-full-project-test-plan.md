# Full-project test plan, round 2

| | |
|---|---|
| Date | 2026-11-05 |
| Status | Revised after review; awaiting owner approval of §8 |
| Review reports | [`round2/review/`](round2/review/goldfish_review_report.md): five stage reports + resolution log |
| Builds on | [Round-1 suite design](../superpowers/specs/2026-10-26-full-security-test-suite-design.md) · [TEST_SUITE.md](TEST_SUITE.md) · [PERMISSION_MATRIX.md](PERMISSION_MATRIX.md) · [Network and device design](2026-10-31-network-device-access-design.md) · [`softech_write_manifest.py`](../../apps/tests/security/softech_write_manifest.py) · [`PENDING.md`](../../apps/tests/security/PENDING.md) |

## 1. The system in brief

**The ElRezeiky extension** is a Django/DRF backend plus a React/Vite frontend, built for the
ElRezeiky pharmacy chain. It has 67 apps in `INSTALLED_APPS` and runs on PostgreSQL. It sits on
top of **SOFTECH**, the chain's legacy ERP and accounting system. SOFTECH stores everything in a
Sybase ASE database, with one database at head office (HQ) and one at each branch server.

The extension **reads** SOFTECH through one guarded connection path (`config/sybase.py`). It
**writes** to SOFTECH only through registered *writers*, such as POS sales, purchase invoices,
stock-request (ISR) documents and insurance re-pricing. A wrong or doubled write there corrupts
the chain's books, which is why writes are the highest-risk area.

**Which machine writes (P-54, single writer).** Only one running copy, the **writer**, may write
to SOFTECH. It runs with `WRITER_INSTANCE=True` and `SOFTECH_READ_ONLY=False`. Every other copy is
a **reader**, which cannot write.

- **Today:** the writer is the **office laptop**. Its startup log on 2026-11-03 showed
  `WRITER_INSTANCE=True SOFTECH_READ_ONLY=False` with 16 writer flags ON.
- **At cutover:** the LDC VPS (the production server at the Link Datacenter) becomes the writer,
  and the office laptop becomes a reader.

In this plan, **production** means both the office writer and the VPS.

### Glossary

| Term | Meaning |
|---|---|
| **Write site** | A place in the code that runs INSERT, UPDATE or DELETE against SOFTECH. Each one is registered in `softech_write_manifest.py`, with its tables, its switch (flag), whether it defaults to a dry run, its idempotency guard, its audit record and its trigger. A static guard fails CI when an unregistered write site appears. |
| **Real write** | A manifest entry with `kind == 'write'`. There are 36. The other 24 kinds are rehearsals, write-then-restore steps, SQL builders and non-writes. |
| **Idempotency guard** | What stops a retry or double-click from writing twice: an advisory lock, a "done" status refusal, or a re-check of the expected current value. |
| **Sweep** | A test that walks every registered API route automatically. Two kinds matter here. **Role sweep:** every route × method × each of the 10 roles, with the expected result taken from the permission matrix, run both with the permission middleware on and in "log" mode. **Canary sweep:** a record is planted in branch A and checked so that it never shows up for a branch-B user. The phone canary does the same for phone numbers. |
| **Baseline** | A reviewed list of known exceptions a guard tolerates, in `apps/tests/security/baselines/*.txt`. A **NEW** line fails the test. A **STALE** line, an exception that no longer happens, also fails the test until it is removed. Lists can only shrink unless a reviewed reason is added (the ratchet). |
| **Pending** | A test that exposes a hole whose fix needs the owner's approval is marked `@pending('<id>')`, an expected failure, and listed in `PENDING.md`. The marker comes off when the fix lands. |
| **Stop-and-ask** | A fix in one of these areas is shown to the owner as a diff and merged only after approval: SOFTECH writes, sync schema, double-post risk, pricing or discounts, payment or checkout completion, auth, 2FA or sessions. |
| **RBAC enforcement** | Checks against the role × module × action matrix (`seed_permissions.py`). These run in two places. **Each view** checks permission itself, always, in every environment. The **middleware** is a second line, set by `RBAC_ENFORCEMENT`: `log` (record only, the production setting) or `enforce` (refuse). `RBAC_ENFORCED_ROLES=accountant` makes the middleware enforce that role even in log mode. |
| **Network policy** | `NETWORK_POLICY_ENFORCEMENT`: zone rules (inside or outside the company network × registered device × role) from the N0–N6 network batches. These run in log mode in production. |
| **W-n, P-n, Z-n** | IDs of round-1 findings. W- is Batch 6 (platform), P- is Batch 2 (SOFTECH), Z- is Batch 4 (authorization). W-4 (formula-safe exports) was merged on 2026-11-02. |
| **Motalba** | An insurance claim document in SOFTECH. Its date is changed through `apps/insurance/date_service.py`. |
| **PIC** | A customer's national identity number, used as the cross-branch customer key. |

## 2. Problem, goals and non-goals

### Problem

Round 1 ran from 2026-10-26 to 2026-11-03. It completed suite batches 0–6 and network batches
N0–N6, and all of it is merged to `main`. It left three kinds of work:

1. **Measured debt.** Round 1 recorded holes it did not close as baseline lines and manifest gaps
   (§4). For example, 460 permission checks on edit and delete are *unproven*: the sweep's request
   hit a missing record (404) before reaching the check.
2. **Modules built after their area's batch closed** (§4.4). New routes are swept automatically.
   Per-module items are not: branch scoping of new models, new write paths, money logic and test
   depth.
3. **Suite batches 7 and 8 never started.** Batch 7 is per-app tests. Batch 8 is the frontend:
   lint, unit tests and per-role browser tests.

Round 2 is therefore **debt + delta + batches 7 and 8**. It is not a re-check of everything.

### Goals

These are the owner's aims, unchanged from round 1. Each goal names the measure that shows it is
met.

1. **No data leaks.** Measure: `branch_canary_leaks` and `phone_canary_leaks` hold only reasoned
   lines. No secret or phone number appears in logs or error responses.
2. **No break-ins.** Measure: the authentication suite (Batch 3) and network batches stay green.
   Every new login-adjacent route, token or WebSocket group added since round 1 is covered.
3. **No access to functions, modules or branches a role should not have.** Measure:
   - `role_unproven` is down to routes that have no record to seed, each with a reason.
   - `role_leaks_log` holds only reasoned lines, so the middleware can be switched to `enforce`.
4. **SOFTECH is reached only through the guarded read path and the registered writers.** Measure:
   - every real write site matches its row in the §6 R1 table;
   - every idempotency gap is closed or owner-accepted.
5. **Money, stock and writes are deterministic.** Totals rebuild from their lines, writes are
   idempotent, and every sensitive action records who, what, when, before and after. Measure: the
   R2 assertions and the audit-gap list in §4.2.

**A hole a test exposes is closed in the same batch.** If the fix is stop-and-ask, the test is
marked pending until the owner decides (§3).

### Non-goals

- **No penetration test** of the VPS, network or nginx host. Config files are checked statically
  only. This carries over from round 1.
- **No rewrites** of working features. Each fix is the smallest change that closes the hole.
- **No pytest.** Tests run under the Django test runner only, because the SOFTECH isolation
  depends on it.
- **No switch to `enforce` in this round.** Switching `RBAC_ENFORCEMENT` or
  `NETWORK_POLICY_ENFORCEMENT` to `enforce` is the owner's cutover decision. This round only makes
  it ready: R3 and R4 exit criteria.
- **No new product features**, except as owner-approved items in the decision pack (for example a
  duplicate-scheduler alert).

## 3. Rules

**1. Isolation**
- Tests run only through `manage.py test`, which turns on the SOFTECH isolation in
  `config/settings.py`.
- Each run uses a unique `TEST_DB_NAME`, synthetic data and test credentials.
- No test connects to SOFTECH, HQ or a branch server, sends a message, or triggers a payment.

**2. Never on the writer**
- All round-2 development, test runs, `runserver`, `shell` and management commands run on a
  **reader** copy: `WRITER_INSTANCE=False`, `SOFTECH_READ_ONLY=True`. A git worktree with its own
  `.env` counts as one.
- Nothing in this round runs on the office laptop's writer copy or on the VPS.
- Live probes stay manual commands that the owner runs.

**3. No weakening to go green**
- No authentication, authorization, validation or test is relaxed so that a check passes.
- Every suppression needs a reviewed reason next to it:
  - a baseline line;
  - an inline `# nosec` or `# noqa`;
  - an allow-list `# reason:`;
  - a `@pending` marker.
- A STALE baseline line is always removed.
- R0 adds a guard that counts `# nosec` / `# noqa` (§6).

**4. Stop-and-ask fixes**
- Tests for these are marked `@pending` and listed in `PENDING.md`, so the batch can end green.
- The fix lands only after the owner approves its diff.
- If the owner declines, the item is recorded as accepted risk in `PENDING.md`, with the owner's
  reason.

**5. No guessed rules.** Expected access comes from three places:
1. the role matrix, `seed_permissions.py`, rendered as `PERMISSION_MATRIX.md`;
2. named per-user grants: the staff caps `can_pic_analytics` and `can_stock_audit`;
3. owner decisions recorded in `TEST_SUITE.md` § "Owner decisions closed" and in round-1 design
   §"Owner decisions".

Where the code and these sources disagree, it goes to the owner as a question. It is not decided
silently.

**6. CLAUDE.md batch rules** apply to every batch:
- in-app help for changed screens;
- migrations;
- tests, then build;
- a regression check;
- a summary;
- the proposal for the next batch.

**7. Features merged during round 2** are covered by whichever batch is open at the time.

## 4. Where things stand (measured 2026-11-05 on `main`)

- **Backend tests.** 6,046 run. All tests pass in CI. The last red run (eabddef7) failed only the
  bandit scan step.
- **The bandit failure.** It was B608, string-built SQL, in `apps/finance/queries/sybase_gl.py`.
  1929463d **suppressed** it with four `# nosec B608` comments. The reason given is that only
  `date.isoformat()` values and module constants are interpolated. That reason gets reviewed in
  R1.
- **CI on 1929463d.** Pending at the time of writing. R0 records the result.
- **CI time.** Backend runs observed on 2026-11-02 to 11-04 took 33–47 minutes. The timeout is
  75 minutes. R0 measures it properly.

### 4.1 Baselines (known exceptions) and their round-2 targets

| Baseline | Lines | What a line means | Target after round 2 | Batch |
|---|---:|---|---|---|
| `role_unproven` | 460 | The edit or delete check was never reached | Only routes with no seedable record, each with a reason | R3 |
| `role_overblocks` | 463 | The matrix allows it, but the view refuses (388 after Batch 4) | Each line classified: fix the view or fix the matrix, by owner decision | R3 |
| `role_crashes` | 6 | 500 errors for some role | 0 | R7 |
| `role_leaks_log` | 2 | Reachable while the middleware is in log mode | Reasoned lines only | R3 |
| `branch_canary_leaks` | 22 | Shown to another branch on purpose | Reasoned lines only (already reasoned; re-check new routes) | R4 |
| `phone_canary_leaks` | 4 | Number shown on purpose | Reasoned lines only | R4 |
| `sql_from_text` | 222 | SQL built from text (reviewed safe) | Does not grow; each line's reason re-checked for SOFTECH paths | R5 |
| `unsafe_exports` | 8 | An export without formula neutralising | 0 | R5 |
| `write_flags_default_true` | 6 | A write flag defaulting to ON | Each one owner-confirmed, or set to OFF | R1 |
| `tracked_secrets` | 1 | A secret-looking tracked file | Reasoned, or removed | R5 |
| `bandit-baseline.json` | 576 | Accepted bandit results | Does not grow; new findings go here with a reason, not to `# nosec` | R0 rule |
| Canary planter `skipped` | not yet counted | A model the canary could not build | Becomes a baseline with reasons | R4 |

### 4.2 SOFTECH write sites (36 real writes)

| Gap | Sites |
|---|---|
| **No idempotency guard (2)** | `discount_approvals/alignment.py::apply_classification_changes` (`PRICING_SOFTECH_WRITE_ENABLED`); `discount_approvals/replication.py::force_replication` (`REPLICATION_REPAIR_ENABLED`) |
| **Manifest wrong** | `insurance/date_service.py::_set_motalba_docdate` is listed with `idempotency=None`, but it runs only inside `_apply_locked`. That function holds lock `LOCK_DATE_EDIT = 7_301_008`, refuses an already-applied run, and re-checks `expected_old`. `DateEditTests` covers it. Its real gap is audit: the old motalba date is not kept, so a revert cannot restore it. |
| **Write without a dry-run default (13)** | `alignment.apply_classification_changes`, `alignment.create_new_tier`, `replication.force_replication`, `services.execute_price_change`, `recon_writer._reverse_steps`, `recon_writer.complete_half_reversal`, `recon_writer.complete_half_write`, `reprice_service._revert_locked`, `pic_bridge.adjust_softech_points`, `writeback._write_and_verify`, `pos_orders.writer._delete_pending_from_softech`, `isr_writer.approve_isr`, `shortage_writer._write_softech` (plus `test_replication_cycle`, `None`) |
| **Weak or missing audit (6 real writes)** | `force_replication` (logger unless run from the repair view); `recon_writer._live_write._write_steps` (no actor when run from a command); `complete_half_reversal` (failure not audited); `_set_motalba_docdate` (old value not kept); `backfill_bonusqty` (no user); 2 probes (stdout only) |
| **Command-only triggers (11)** | No HTTP route to refuse a role: `copy_one`, `merge_one`, `remove_one`, `backfill_bonusqty`, the coverage writers, `approve_isr`, the two `complete_half_*` (no production caller), and the 2 probes |
| **Probes that bypass `config/writers.py`** | Sites gated by `SOFTECH_PROBES_ENABLED` (`core/softech_switches.py`) do not check `WRITER_INSTANCE`, so a reader copy with that switch ON could reach them |
| **Weak guards** | `create_new_tier` (MAX+1 code race), `execute_price_change` (no row lock), the rate push (no lock), `approve_isr` (re-stamps user and time on every call) |

### 4.3 Already covered (reuse, do not rebuild)

| Area | Existing test or code |
|---|---|
| Writer and reader start-up | `apps/tests/test_writer_instance.py`: `StartupGuardTests`, `WriterAllowedTests.test_no_gate_reads_a_writer_flag_directly`, `SchedulerTests.test_non_writer_registers_no_writer_job` |
| Write-site registry | The `test_static_guards.py` manifest check |
| Per-site switch-off, locks and idempotency | `test_softech_writes_*.py`, `test_softech_writes_unswitched.py`, `test_softech_writes_locks.py` (includes `DateEditTests`) |
| Read-only SQL checker | `config/sybase.py::is_read_only_sql`; `test_softech_read_only_guard.py::ReadOnlySqlCheckTests`; `test_gl_sources.py::test_open_fetch_refuses_non_select` |
| Route classification | `test_static_guards.py::test_every_api_prefix_is_classified`, against `core/middleware/module_access.py` (`MODULE_BY_PREFIX`, `READ_OPEN_PREFIXES`, `EXEMPT_PREFIXES`) |
| Accountant role | `test_rbac_accountant.py`, plus the role sweep (all `ROLE_CHOICES`) |
| Canary planting | `canary.py::branch_linked_models()` walks every model with a branch FK or a branch code field, so new models are included automatically |
| Exports | `test_static_guards.py::test_exports_neutralise_formulas` plus `baselines/unsafe_exports.txt`; behaviour tests in `test_platform_export_formulas.py` |
| Uploads | `test_platform_upload_limits.py`, `core/upload_safety.py` |
| Scheduler | `test_scheduler_jobs.py::test_no_job_function_registered_twice_on_the_same_cadence`; heartbeat `SCHEDULER_HEARTBEAT_KEY` and `/api/sync/scheduler-status/` |
| Schema defaults | `test_purchasehistory_db_defaults.py` (an `information_schema` pattern) |
| Nav map parsing | `test_help.py::_anchors`, which reads `NAV_GROUPS` from `Layout.jsx` |

### 4.4 Built after its area's batch closed

| Item | Missed batch | Where |
|---|---|---|
| Finance GL + `accountant` role | 4 (authz), 5 (scoping) | `apps/finance/gl`, `apps/finance/queries/sybase_gl.py` (SOFTECH reads); architecture doc 35 |
| Counselling, staff drug assistant (Project 4) | 4, 6 (sends) | `apps/counselling`; doc 34 |
| Missed sales + missed-call call-backs (Project 3) | 4, 5, 6 | `apps/pos_orders` (`missed-sales/`, module `pos`); `apps/pic_analytics` call-backs |
| Usage-instructions slip (Project 5) | 4, 7 | `apps/usage_print` |
| Daily counts + camera scanning (Project 2) | 5, 7 | `apps/stockcount/daily` (feature flag `DAILY_COUNT_ENABLED`); scanning is client-side only |
| Phone alerts + morning brief (Project 1) | 6 (sends) | WhatsApp staff alerts |
| PIC analytics | 4, 5 | `apps/pic_analytics`; doc 33; named grant `can_pic_analytics` |
| Stock audit | 5 | `apps/stock_audit`; doc 32; named grant `can_stock_audit` |
| Sortable grids | 1 (injection) | `core/sort_ordering.py` (ORM `F()`, 400 on an unknown key) |
| Forecasting horizons | 7 | `apps/forecasting` |
| `trace` app | 4, 7 | `apps/trace` |

"Doc nn" means `docs/architecture/nn_*.md`.

## 5. Approach and alternatives considered

**Approach.**
1. Reuse the sweeps, which already discover new routes and models.
2. Close their blind spots by seeding records, ratcheting the planter's skip list and adding
   detail routes.
3. Pay down the measured baselines in §4.1.
4. Add targeted tests only where a sweep cannot reach: money logic, writer safety, privacy in logs
   and sends.
5. Finish batches 7 and 8.

R0 sizes all of this and produces **one owner decision pack**, so R1–R6 do not stall waiting for
approvals.

| Choice | Picked | Rejected, and why |
|---|---|---|
| Scope | Debt + delta + batches 7 and 8 | A full re-check of every app: repeats round 1 at about 45 minutes of CI per batch, and finds nothing the sweeps don't already cover. |
| Order | R0 first; R1–R6 in aim order; **R7 and R8 run alongside**, because they need no owner approvals | Strictly serial: R1 is mostly stop-and-ask, and serial order would idle the independent work. |
| Ranking thin apps | By line coverage from R0's coverage run | Counting test files that mention an app: says nothing about how much code is exercised. |
| Money tests | Hand-written table tests (input → expected), no new dependency | Hypothesis property tests: adds a dependency, and the expected values come from SOFTECH's documented formulas, not from properties. |
| Writer checks | A per-site expectation table taken from the manifest (§6 R1) | The same five checks for every site: most sites legitimately fail one of them (commands have no HTTP route; absolute SET writes are idempotent in their end state). |
| "Hidden means forbidden" | Playwright in R8 (real browser, real API) | A Django test parsing JSX: breaks when the layout is refactored, and nav items carry screen paths, not API routes. |

## 6. Risks and limits

| Risk | Likelihood | Mitigation |
|---|---|---|
| Work touches writer code while the office laptop writes live | Medium | Rule 2 (reader copy only). Writer fixes are stop-and-ask, deployed by the owner. |
| CI time grows past 75 minutes | Medium | R0 measures it. Owner question Q3 (split fast and full runs). |
| Stop-and-ask items stall batches | High | The decision pack in R0 plus `@pending` (Rule 4). |
| Shared test databases collide | Low | A unique `TEST_DB_NAME` per run. |
| Playwright flakiness blocks merges | Medium | Retries ≤ 2. The e2e job is non-blocking for its first week (Q4). |
| The first run of a new guard finds many items | High | R0 runs every new guard in report-only mode. The owner decides, per guard, to baseline with reasons or fix in its batch. |
| New modules keep landing during the round | High | Rule 7, plus the new-module definition of done (R0). |

**Limits.** This round shows that the listed checks pass and the listed gaps are closed. It cannot
show that unlisted bugs don't exist. Live SOFTECH behaviour stays verified only by the owner's
manual probes.

## 7. Batches

Each batch ends with the full backend suite and the frontend build green. Stop-and-ask items may
be `@pending` (Rule 4). Each batch's PR description lists every new baseline line or suppression,
with its reason.

### R0: Sizing, guards in report-only mode, and the decision pack (no product changes)

1. **Run:** the full suite, both sweep modes, bandit, pip-audit, npm audit, and
   `coverage report` by app. Record the CI wall time.
2. **Size the new guards in report-only mode** (they print and never fail):
   - views with no permission stronger than `IsAuthenticated`, against the prefix classification;
   - the canary planter `skipped` list;
   - the `# nosec` / `# noqa` count.
3. **Schema drift check:** a read-only management command, `check_schema_drift`. It compares every
   managed model's columns, types and nullability with `information_schema` on the database it
   runs against. The owner runs it on the office and VPS databases. A test DB cannot show drift.
4. **New-module definition of done:** a checklist added to the CLAUDE.md batch rules. Every new
   module needs:
   - a matrix module or a reasoned open listing;
   - branch scoping through `core/branch_scope`, or a reason why it doesn't need it;
   - any SOFTECH write registered in the manifest;
   - view and permission tests;
   - help text.
5. **Output:** `docs/security/round2/R0_findings.md`, with sizes per batch, CI time, and the
   coverage table. Plus `docs/security/round2/decision_pack.md`, with every stop-and-ask item each
   batch will meet, each with a recommended default.

**Files:**
- Create `apps/sync/management/commands/check_schema_drift.py`.
- Create `apps/tests/test_check_schema_drift.py`.
- Create `apps/tests/security/test_suppression_count.py` (report-only).
- Create `docs/security/round2/R0_findings.md` and `docs/security/round2/decision_pack.md`.
- Modify `CLAUDE.md` (the definition-of-done checklist).

### R1: SOFTECH write safety (aim 4); every fix is stop-and-ask

1. **Per-site expectation table.** Create `docs/security/round2/R1_write_sites.md`: one row per
   real write site, taken from the manifest. Each column says whether the check applies:
   - **Switch off means no connection:** applies to all sites.
   - **Dry run by default:** applies, or "No: <reason>" for the 13 sites in §4.2.
   - **Twice gives one write:** for absolute-SET writers, this means "the second call changes no
     value". It must not re-stamp `itemlastupdate`.
   - **Audit row:** who, what, when, before and after.
   - **HTTP role refusal:** applies, or "command only".

   A mismatch is either a hole (fix it, stop-and-ask, `@pending` meanwhile) or an
   **owner-accepted exception**, recorded in the table with the owner's reason.
2. **Tests:** only for rows that are new or changed since 2026-10-26, rows whose callers changed,
   and every hole. They extend `test_softech_writes_*.py`, using `RecordingSybase`, the test
   double that records SQL instead of sending it.
3. **The two idempotency guards.** These are proposed designs, and each needs owner approval:
   - **`apply_classification_changes`:** take advisory lock `7_301_011` and skip any item whose
     SOFTECH class already equals the target, so it neither re-stamps `itemlastupdate` nor
     triggers re-replication. A test shows the second call writes zero rows.
   - **`force_replication`:** take advisory lock `7_301_012` and refuse a second repair of the same
     item within 10 minutes, recorded in `ReplicationGap`. A test shows a concurrent and a repeated
     call each write once.
4. **Correct the manifest:** `_set_motalba_docdate` idempotency becomes
   "LOCK_DATE_EDIT + applied-run refusal + expected_old".
5. **Audit gaps.** For each, propose a fix or ask the owner to accept it: the old motalba date
   (decision pack Q1); the command actor for `_write_steps`; failure audit for
   `complete_half_reversal`; `force_replication` outside the repair view.
6. **Probes.** Make `require_probes` also refuse when `WRITER_INSTANCE=False` and
   `SOFTECH_READ_ONLY=False`. Extend `test_writer_instance.py` to cover this.
7. **Read-only checks.**
   - **`open_fetch` regex** (`apps/finance/queries/sybase_gl.py`): fuzz it with newline-separated
     second statements and writes hidden in comments or string literals. If any gets through,
     replace the regex with `config/sybase.py::is_read_only_sql`.
   - **Its `# nosec`:** re-check the reason against the interpolated values.
8. **Write flags that default to ON:** the 6 `write_flags_default_true` lines are each confirmed by
   the owner, or switched to OFF.

**Files:**
- Modify `apps/tests/security/softech_write_manifest.py`.
- Modify `apps/discount_approvals/alignment.py` and `apps/discount_approvals/replication.py`.
- Modify `core/softech_switches.py` and `apps/finance/queries/sybase_gl.py`.
- Modify `apps/tests/test_writer_instance.py`, `apps/tests/test_gl_sources.py` and
  `apps/tests/security/test_softech_read_only_guard.py`.
- Create `apps/tests/security/test_softech_writes_round2.py`.
- Create `docs/security/round2/R1_write_sites.md`.
- Audit fixes touch only the four files named in step 5, after owner approval.

### R2: Money and stock correctness (aim 5); pricing or checkout fixes are stop-and-ask

These are table tests on synthetic data. Every expected value cites its source, and money uses
`Decimal` throughout.

| Area | Assertions |
|---|---|
| Finance GL | Every posted journal entry has debits equal to credits. The trial balance totals 0.00. A reversal entry plus its original totals 0.00 on every account. Editing an approved entry returns 409. Two drafting runs over the same period produce no duplicate draft. |
| POS orders | Line net = gross × (1 − d1) × (1 − d2), rounded half-up to 0.01. Order total = Σ line nets. VAT per line = net × rate. Points = Σ floor(line net × customer discount %). Strip quantity = round(strips ÷ pack quantity, 5), half-up. Source: `docs/architecture` POS writer docs and the SOFTECH points mechanism. |
| Offers | An item with a safety flag never receives an offer discount. One offer never applies twice to the same line. |
| Incentives | Calculating the same period twice gives identical rows. Finalizing locks the period, and later recalculation returns 409 unless forced. A forced recalculation sets the period back to un-finalized. |
| Insurance | After applying a plan, each receipt's SOFTECH price equals the plan's new price. Claim final totals equal Σ line finals after recalculation. One receipt is active in exactly one claim. |
| Replacement payouts and reversals | Amount > 0, rejected by the database otherwise (`ck_replacement_payout_positive`, `ck_replacement_reversal_positive`). A reversal plus its payout nets to 0.00. |
| Stock count, transfers, transits | Received + in-transit + cancelled = sent. Status only moves along the defined transitions; a skipped step returns 400 or 409. |

**Files:**
- Create `apps/tests/test_money_gl.py`, `apps/tests/test_money_pos.py`,
  `apps/tests/test_money_offers_incentives.py`, `apps/tests/test_money_insurance_replacement.py`
  and `apps/tests/test_stock_conservation.py`.

### R3: Authorization (aim 3); ends enforce-ready

1. **Seed records so `role_unproven` drops.** The sweep's PUT, PATCH and DELETE go to a real record
   per route through the canary Planter, instead of id 987654321. The STALE lines are then pruned.
2. **Classify `role_overblocks` (463).** Group the lines by module. For each group, either fix the
   view or the matrix gets changed, through the decision pack.
3. **"Every view gated" guard.** This extends `test_every_api_prefix_is_classified` down to view
   level. A view must carry a module permission, or appear in
   `apps/tests/security/baselines/open_to_all_staff.txt` with a reason. The first findings follow
   R0's sizing decision.
4. **New-module cases:**
   - named grants: `can_pic_analytics` and `can_stock_audit`, for granted, ungranted and
     wrong-branch users;
   - missed sales (`pos` module);
   - call-backs (`pic_analytics`);
   - `counselling`;
   - `usage_print`;
   - `tasks`.
5. **Break-in delta (aim 2).** List every route, token, OTP or WebSocket group added since
   2026-11-03 that takes part in login, sessions or one-time codes. Examples: counselling cards,
   alert links, call-back links. Each gets an anonymous-refusal test, an expired-or-reused-token
   test, and a WebSocket group-membership test, reusing the Batch 3 and W-3 test patterns.
6. **Exit criterion:** `role_leaks_log` holds only reasoned lines, and a would-deny log summary is
   in `docs/security/round2/R3_enforce_readiness.md`. The owner can then decide on switching to
   `enforce`.

**Files:**
- Modify `apps/tests/security/test_role_sweep.py`, `apps/tests/security/canary.py` and
  `apps/tests/security/test_static_guards.py`.
- Create `apps/tests/security/baselines/open_to_all_staff.txt` and
  `apps/tests/security/test_named_grants.py`.
- Create `docs/security/round2/R3_enforce_readiness.md`.
- Views are fixed in the files the sweep names; each fix is listed in the PR.

### R4: Branch separation and privacy (aims 1, 3)

1. **Skipped models.** Ratchet the planter's `skipped` list into
   `baselines/canary_skipped_models.txt`. Each skipped model gets a builder fix or a reason.
2. **Detail routes.** The canary sweep also requests the detail route of the planted record. Today
   it requests list routes only.
3. **Feature-flagged routes.** The sweep turns on their flags during the test, so they are checked
   rather than counted unproven. Example: daily counts, `DAILY_COUNT_ENABLED`.
4. **Company-level modules** (Finance GL, which has no branch field): an explicit test that
   branch-scoped roles get 403.
5. **Logs and errors.** Capture logs with `assertLogs` on the root logger during the sweeps, and
   check every `public_error` response. Neither may contain:
   - an unmasked phone (any 11-digit national or `+20` number without the mask `***`);
   - a PIC;
   - a password, token, OTP or the SOFTECH connection string.
6. **WhatsApp payloads staff can see** (alerts, counselling cards, call-backs): the customer number
   is masked unless the viewer passes `apps/customers/access.py::record_phone`.

**Files:**
- Modify `apps/tests/security/canary.py` and `apps/tests/security/test_branch_canary_sweep.py`.
- Create `apps/tests/security/baselines/canary_skipped_models.txt`,
  `apps/tests/security/test_privacy_logs.py` and `apps/tests/security/test_gl_company_scope.py`.

### R5: Injection and abuse (aims 1, 2)

1. **Sortable grids.** `core/sort_ordering.py` builds ORM expressions, so the risk is sorting by a
   field the screen doesn't show (a sort oracle), not SQL. Test that unknown and hidden keys
   return 400.
2. **Wildcard search.** Test that `%`, `_` and `\` in input are matched as literal text. Extend
   `apps/tests/test_wildcard_search.py`.
3. **Finance GL filters.** Run the SQL-injection payload set from Batch 1 against them.
4. **Exports.** Get `unsafe_exports` to 0 by neutralising the 8 listed exports. Every export added
   since 2026-11-02 (W-4) is found by the static guard.
5. **Uploads.** The only stock-count upload is the session `upload-results` action. Reuse
   `test_platform_upload_limits.py` for type, 25 MB size, 50,000-row cap and path names. Camera
   scanning makes no upload.
6. **Sends.** These are morning brief, alerts, counselling, and call-backs.
   - **Rate limit:** the per-recipient limit from owner question 6.
   - **Recipients:** only numbers held in the configured staff-alert setting or on the customer's
     own record.
   - The exact setting names go in the R0 findings.
7. **Re-check `sql_from_text`** lines on SOFTECH paths, and the one `tracked_secrets` line.

**Files:**
- Create `apps/tests/test_sort_ordering_security.py` and `apps/tests/security/test_send_limits.py`.
- Modify `apps/tests/test_wildcard_search.py` and
  `apps/tests/security/baselines/unsafe_exports.txt`.
- Modify the 8 export views it lists.

### R6: Reliability (aim 5)

1. **Scheduler.**
   - Test that every job runs under its documented lock or idempotency key.
   - A duplicate-scheduler alert does not exist today (only the heartbeat does). It goes in the
     decision pack as optional feature work.
2. **Migration rules.** A static test over migrations newer than the first migration dated
   2026-11-05 fails on two things:
   - an `AddField` of a NOT NULL column without a server default;
   - a `CREATE TABLE IF NOT EXISTS` that has no matching `ADD COLUMN IF NOT EXISTS` for each
     column.

   These are the 2026-08-16 and 2026-10-28 NOT NULL incidents, and the 2026-11-03 users 0008 drift.
3. **Sync.** Test that `SYBASE_LOGIN_TIMEOUT`, `SYBASE_QUERY_TIMEOUT` and `SYBASE_FETCH_TIMEOUT`
   (600 s) are applied on every connection. Test that the fast and slow sales syncs resume from
   their last saved point after a mid-run failure.

**Files:**
- Create `apps/tests/test_migration_rules.py` and `apps/tests/test_scheduler_locks.py`.
- Modify `apps/tests/test_sybase_deadline.py`.

### R7: Per-app tests (suite batch 7); runs alongside R1–R6

- **Which apps.** Apps below 60% line coverage in R0, ordered money and stock first, then by
  coverage.
- **Minimum per app:** one view test per route group, one permission test, and one business-rule
  test.
- **`role_crashes`** goes to 0.
- **Coverage floor.** Add `--fail-under` to `coverage report` in `.github/workflows/ci.yml` (line
  68). Set it to R0's total rounded down to the whole percent. It never goes down.

**Files:**
- Create `apps/tests/test_<app>_*.py` per app, listed in the R0 findings.
- Modify `.github/workflows/ci.yml`.

### R8: Frontend (suite batch 8); runs alongside R1–R6

1. **Lint.** ESLint 9 (flat config) with `eslint-plugin-react` (`react/no-danger`) and
   `eslint-plugin-react-hooks`. Add the script `npm run lint`.
2. **Unit tests.** Vitest 3 with jsdom. Cover the API client, `authStore`, `permissionStore`, route
   guards (`RequireRole`), money and number formatting, and the shared grid hooks
   (`useSortableRows`, `useGridKeyboard`). Add the script `npm test`.
3. **Browser tests.** Playwright 1.5x, Chromium only.
   - Create `config/settings_e2e.py`. It imports the settings and forces `SOFTECH_READ_ONLY=True`,
     `WRITER_INSTANCE=False`, its own database, and no outbound sends.
   - The management command `seed_e2e_users` creates one user per role with test passwords, read
     from the e2e settings.
   - Flows: login per role; for each menu item hidden from a role, the matching API call returns
     403; reservation create; transfer request; POS order to "ready". The order is never submitted
     to SOFTECH.
4. **CI.** A `frontend-quality` job that runs lint and Vitest, blocking. An `e2e` job running
   Playwright, non-blocking for its first week (Q4). Keep `npm_audit_check.cjs` as the audit gate:
   it already fails on any advisory not on the allow-list, which is stricter than
   `--audit-level=high`.

**Files:**
- Create `frontend/eslint.config.js`, `frontend/vitest.config.js`, `frontend/src/**/*.test.js(x)`,
  `frontend/e2e/*.spec.js` and `frontend/playwright.config.js`.
- Create `config/settings_e2e.py` and `apps/users/management/commands/seed_e2e_users.py`.
- Modify `frontend/package.json` and `.github/workflows/ci.yml`.

## 8. Owner questions (the default applies if there's no answer before the batch)

1. **Old motalba date.** Should a date change keep the old motalba date, so a revert can restore
   it? Default: yes, stored in `SoftechDateEditRun`.
2. **Idempotency guards.** May the two guards in R1 step 3 be built as designed? Default: yes, both
   behind their existing flags.
3. **CI split.** Split CI into a fast per-PR run (static guards, changed apps, about 10 minutes) and
   the full sweeps on `main` plus nightly? Default: no split until R0 shows more than 60 minutes.
4. **Playwright in CI.** Add Playwright to CI? It costs about 5 more minutes (estimated, not
   measured). Default: yes, non-blocking for its first week.
5. **Matrix vs view mismatches.** For `role_overblocks` groups where the view and the matrix
   disagree, which wins? Default: the matrix, except where a recorded owner decision says
   otherwise.
6. **Message rate limit.** How many automatic messages may one recipient get from each sender (morning
   brief, alerts, counselling, call-backs)? Default: at most 1 per recipient per 10 minutes per
   message type. The test is written against this limit.

## 9. Done means

Every item below must hold:

- **Batches:** R0–R8 are each merged to `main` with CI green.
- **Baselines:** every baseline in §4.1 meets its target, and each remaining line has a reason.
- **Suppressions:** no new `# nosec` / `# noqa` without a reason.
- **`apps/tests/security/PENDING.md`:** holds only items the owner has held or accepted, each with
  their reason.
- **`docs/security/TEST_SUITE.md`:** gains a "Round 2" section (batch results and new guards), and
  its baseline numbers are updated.
- **Summary:** `docs/security/round2/SUMMARY.md` is one page: what was found, fixed, accepted, and
  left open.
