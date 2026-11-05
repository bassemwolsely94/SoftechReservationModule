# Round 2: owner decision pack

These are all the stop-and-ask items round 2 will meet, collected in one place so the batches
don't stall. The owner approved the plan's §8 defaults on 2026-11-05.

**Rules for each item:**
- **Default:** the default applies unless the owner answers otherwise before the batch reaches it.
- **Pending:** until it is decided, the test that exposes the item stays `@pending` and is listed in
  `apps/tests/security/PENDING.md`.
- **Declined:** a declined item is recorded there as accepted risk, with the owner's reason.

Plan: [2026-11-05-full-project-test-plan.md](../2026-11-05-full-project-test-plan.md) · Findings:
[R0_findings.md](R0_findings.md)

## Already decided (plan §8, approved with defaults)

| # | Item | Decision | Batch |
|---|---|---|---|
| Q1 | Should a motalba date change keep the old date, so a revert can restore it? | **Yes**, stored in `SoftechDateEditRun` | R1 |
| Q2 | Build the two idempotency guards (`apply_classification_changes` lock 7_301_011 + skip-unchanged; `force_replication` lock 7_301_012 + 10-minute repeat refusal) | **Yes**, both behind their existing flags | R1 |
| Q3 | Split CI into fast and full runs | **No**, unless R0 measures more than 60 minutes | R0 |
| Q4 | Playwright in CI | **Yes**, non-blocking for the first week | R8 |
| Q5 | When a view and the role matrix disagree, which wins? | **The matrix**, unless a recorded owner decision says otherwise | R3 |
| Q6 | Automatic-message rate limit | **At most 1** per recipient, per 10 minutes, per message type | R5 |

## New from R0, needing a yes or no

| # | Item | Default | Batch |
|---|---|---|---|
| D1 | **Probe switch on a reader copy.** Sites gated only by `SOFTECH_PROBES_ENABLED` don't check `WRITER_INSTANCE`. Make `require_probes` refuse on any copy that isn't the writer, unless `SOFTECH_READ_ONLY=True`, which keeps rehearsals read-only. | **Yes** | R1 |
| D2 | **Command actor in A/P audit.** `recon_writer._live_write._write_steps` records `performed_by=None` when run from a command. Require `--actor <username>` on those commands and store it. | **Yes** | R1 |
| D3 | **Failed reversals audited.** `complete_half_reversal` audits success only. Also write a `ReconAuditEvent` on failure. | **Yes** | R1 |
| D4 | **`force_replication` outside the repair view.** It only writes to the log there. Always write an audit row (who, item, branches). | **Yes** | R1 |
| D5 | **13 write sites with no dry-run default.** Most are the explicit "apply" step after a preview. Each one is listed in `R1_write_sites.md` with its reason, as an owner-accepted exception. A site with no preview step is proposed as a fix instead. | **Accept** where a preview exists; **fix** otherwise | R1 |
| D6 | **130 views under a module prefix that check only "logged in".** In production the middleware only logs, so these rely on their own code. Add the prefix's module permission to each view. A view where the role sweep shows that this would lock out a role that uses it today goes back to the owner instead (anti-goal: no lockouts). | **Fix** | R3 |
| D7 | **Duplicate-scheduler alert.** Only a heartbeat exists today, and nothing detects a second scheduler. | **Not now.** Product work after go-live | R6 |
| D8 | **Switching `RBAC_ENFORCEMENT` and `NETWORK_POLICY_ENFORCEMENT` to `enforce`.** | **Not in round 2.** The owner decides after go-live, using `R3_enforce_readiness.md` | after R3 |

## Owner answers (2026-11-05, in chat)

| # | Answer | Status |
|---|---|---|
| D1 | **Restrict probes:** refuse on a non-writer copy unless it is read-only | R1 |
| D2 + D3 | **Both:** `--actor <username>` is required on the A/P writer commands, and failed reversals are audited | R1 |
| D4 | Delivered with the Q2 guard: every `force_replication` writes an `AuditLog` `softech_replication_forced` row (in our own database only) | Done in R1 |
| D5 | **Accept all 13** as recorded exceptions (see [R1_write_sites.md](R1_write_sites.md)) | Done; no code change |
| Q1 follow-up | **A revert also restores the old motalba dates** (this changes the earlier "the motalba keeps the corrected date" rule) | R1 |
| M-1, M-2, M-3 | **Fix** (safety block beats offers; cap stacked discount at gross; claim total uses `net_override`) | R2 follow-up PR |
| M-4 | **Keep the current rounding**; accepted risk | Recorded |
| R7-V1 | **Fix** voucher mark-used (lock the document row only) | R7 PR |
| D6, D7, D8 | Defaults stand: D6 fix, D7 not now, D8 not in round 2 | R3 / after go-live |

## Already settled (no action)

- **The 6 `write_flags_default_true` lines** each carry a reviewed reason. `AP_RECONCILE_AUTO_APPROVE` was owner-confirmed on 2026-10-26: it approves matches in our own copy of the data, and the SOFTECH write stays behind `AP_RECONCILE_WRITER_ENABLED`, which defaults to False. The other five are read-only feature switches, not SOFTECH writes.
- **The 8 `# nosec` comments** each name a bandit rule and give a reason. From now on, `test_suppression_count.py` keeps it that way.
