# R0: Sizing and findings (2026-11-05)

[Plan](../2026-11-05-full-project-test-plan.md) §7 R0 · [Decision pack](decision_pack.md) ·
[R1 write sites](R1_write_sites.md)

R0 measured the project and changed no product behaviour.

## 1. Test suite

| | Result |
|---|---|
| Full backend suite, locally on a reader copy, with coverage | **6,068 tests, all pass** (12 skipped, 2 expected failures for W-1, which is held). Commit e5beab09. |
| Local wall time | 293 minutes, with coverage, on a machine shared with five other sessions. **Not** a CI figure. |
| Backend CI wall time | **1h02m** (PR 70, 2026-11-05). Earlier runs on 2026-11-02 to 11-04 took 33–47 minutes. The CI timeout is 75 minutes. |
| `makemigrations --check` | Clean |
| Bandit / pip-audit / npm audit | Green in CI on `main` 1929463d |

**Decision Q3 is triggered.** Its default was "no split until R0 shows more than 60 minutes", and
backend CI now takes 62 minutes. The R7 and R8 tests will add more, and the job is within about 13
minutes of the 75-minute timeout. So CI is split into two runs:

- **Per PR (fast):** static guards, plus the test modules for the apps the PR changes.
- **On `main` + nightly (full):** the full suite, plus both sweep modes.

This is done after the R7 and R8 PRs merge, because both of them edit `ci.yml`.

## 2. Line coverage by app

Total coverage for `apps/`, excluding migrations and tests, is **73.7%** (87,175 of 118,289
statements). R7 sets `--fail-under=73`.

| Coverage band | Apps |
|---|---|
| **Under 60% (R7 targets)** | images 37.6 · insurance 48.1 · sync 49.0 · enrichment 51.2 · personal 51.8 · incentives 51.9 · discount_approvals 52.5 · reservations 55.2 · recommendations 55.3 |
| 60–70% | demand 62.1 · invoices 62.8 · chronic 63.4 · campaigns 63.5 · referral 63.5 · followups 63.9 · procurement 64.0 · purchasing 66.2 · transfers 66.6 · callcenter 68.4 · pos_orders 68.4 · shortage 69.1 |
| 70% or more | every other app (finance 80.0, catalog 80.8, forecasting 81.3, …) |

In the R7 targets, money and stock apps go first: insurance, incentives and discount_approvals.

## 3. New guards, sized in report-only mode

### Views checking only "logged in"

**315 of 1,738 API routes** have views whose `permission_classes` hold only `IsAuthenticated`
or `AllowAny`.

| How the prefix is classified | Views | Notes |
|---|---:|---|
| `EXEMPT_PREFIXES` | 164 | Mostly correct: help, notifications, personal, auth, gamification, portal. pic-analytics (29) and stock-audit (16) have their own gates in `access.py`, which R3 confirms. |
| A module prefix (`MODULE_BY_PREFIX`) | 130 | Production runs the middleware in log mode, so these rely only on checks inside each view. Largest groups: delivery 32, products 17, stockcount 10, hr 9, loyalty 9, referral 8. **Decision D6** (default: fix). |
| `READ_OPEN_PREFIXES` | 21 | Reads open by design (items, recommendations, branches, config). |

### Canary planter

It builds **116 branch-linked models** and skips **2**:

- `access.TrustedNetwork` is configuration, not branch data.
- `users.StaffProfile` is planted separately, as the test users.

R4 turns this into a ratcheted baseline.

### Inline suppressions

There were **8 `# nosec`** at R0 (10 after two reviewed Finance GL query builders landed the same day), all naming their bandit rule and giving a reason, and **126 `# noqa`**.
These counts are now enforced by `apps/tests/security/test_suppression_count.py`: every `# nosec`
must give a rule and a reason, and neither count may grow.

## 4. Baselines at the start of round 2

| Baseline | Lines | Batch |
|---|---:|---|
| role_unproven | 460 | R3 |
| role_overblocks | 463 | R3 |
| role_crashes | 6 | R7 (5 lines were the voucher mark-used crash; the owner approved that fix) |
| role_leaks_log | 2 | R3 |
| branch_canary_leaks | 22 | R4 |
| phone_canary_leaks | 4 | R4 |
| sql_from_text | 222 | R5 |
| unsafe_exports | 8 | R5 |
| write_flags_default_true | 6 | Already settled: all have a reason or the owner's OK |
| tracked_secrets | 1 | R5 |
| bandit-baseline.json | 576 | Ratchet |

## 5. SOFTECH writes

There are 36 real write sites. The full table is in [R1_write_sites.md](R1_write_sites.md).

- **Idempotency gaps (2).** Both are closed by this batch: `apply_classification_changes` and
  `force_replication` (approved as Q2).
- **The motalba manifest entry was wrong.** The write was already guarded. The registry entry is
  corrected, and the old dates are now stored (approved as Q1).
- **No dry-run default (13).** All 13 are explicit actions or commands. They are accepted under
  the D5 default, which is still pending the owner.
- **Two automatic writers checked.**
  - `sync_shortage_softech` is not scheduled.
  - The replication `auto_repair` setting defaults to OFF. **The owner should check its live value
    before go-live.**

## 6. Other R0 outputs

- **`check_schema_drift`:** a read-only command. **The owner runs it on the office database and
  on the VPS** before cutover. Exit code 0 means no drift. Tests are in
  `apps/tests/test_check_schema_drift.py`.
- **New-module security definition of done:** added to `CLAUDE.md`.

## 7. Found by the parallel batches so far

These were all decided by the owner on 2026-11-05.

| ID | Finding | Owner decision |
|---|---|---|
| R7-V1 | POS voucher mark-used always failed with a 500 error on PostgreSQL (`select_for_update` together with a nullable join), so the discount was never finalized and no audit row was written. | Fix it, by locking the document row only. |
| M-1 | The offers engine discounted items whose safety flag blocks the sale. | Fix it: a safety block always wins. |
| M-2 | Offers stacked on one POS line could reach a 170% discount and a negative total. | Fix it: cap the discount at the line's gross. |
| M-3 | An insurance net override never reached the claim total or the export. | Fix it: use the override. |
| M-4 | The claim net differs by a few piasters from the sum of the rounded rows. | Keep the current method; accepted. |
| I-1 | Recording an insurance payment (`POST …/claims/<id>/payments/`) always answered 400 "claim: required". | Fix it, in R7: `claim` is filled by the server. |

## 8. Go-live notes for the VPS

- **`python-docx`** was missing from `requirements.txt`. On a fresh VPS install, the insurance cover
  letter and submission package would have answered with a 500 error. PR 74 (R7) adds it.
- **Run `check_schema_drift`** on the VPS database after `migrate`, and before cutover.
- **Check the live `auto_repair` value** on the pricing replication screen. It should stay OFF
  unless it is wanted.
- **Backend CI now takes about 60 minutes.** Split CI (Q3) before more tests land.
