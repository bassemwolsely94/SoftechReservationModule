# Round 2 — summary (closed 2026-11-12)

[Plan](../2026-11-05-full-project-test-plan.md) · [R0 sizing](R0_findings.md) ·
[R1 write sites](R1_write_sites.md) · [Decision pack](decision_pack.md) ·
[R3/R4 enforce readiness](R3_enforce_readiness.md) · [R5/R6](R5_R6.md) ·
[R8 frontend](../2026-11-05-r8-frontend-report.md)

All work ran on reader copies (`WRITER_INSTANCE=False`, `SOFTECH_READ_ONLY=True`) with isolated test
databases and synthetic data. Nothing touched production SOFTECH, sent a real message or charged
anyone. This is not a claim that the application is bug-free or fully tested: it is what the
sweeps and the targeted tests below cover.

## Merged

R0–R8 are on `main`: PRs 68 (plan), 70 (R2), 72 + 82 (R8), 73 (R5/R6), 74 (R7), 75 (R3/R4),
76–79 (R1, D1–D3, drift check), 80 (R2 follow-up), and the close-out PR (this page).

## Found and fixed

| Area | What was wrong | Fix |
|---|---|---|
| SOFTECH writes (R1) | Pricing classification and forced replication had no idempotency guard; motalba date edits lost the old date; three writers had weak audit | Advisory locks + re-check before write; old dates kept and restored on revert; actor on every command; failure audit (D1–D3) |
| Money (R2) | Offers discounted safety-blocked items (M-1); stacked offers reached 170% / negative totals (M-2); insurance net override never reached the claim or export (M-3) | Safety block wins; discount capped at line gross; override used |
| Access (R3/R4) | 107 views checked only "logged in"; any role could delete a customer in log mode (Q-7a); missed sales, QA, insight rules, loyalty redeem disagreed with the matrix | `RouteModulePermission` on every module view; owner answers Q-1…Q-8 applied; users 0052/0053 grants |
| Privacy (R4) | A SOFTECH error returned the connection string and password; five loggers wrote passwords/tokens; missed-sales showed full numbers | `public_error` + `core/log_redact.py`; `record_phone()` |
| Abuse / reliability (R5/R6) | Formula injection in 8 exports; SQL built from a typed supplier code; campaign drain double send; no per-recipient send limit; two schedulers could double-write | Export neutralising; bound params; atomic claims; 10-minute send limit; single-scheduler lock; S-1…S-3 |
| Crashes (R7 + close-out) | Voucher mark-used always 500 on PostgreSQL; insurance payment always 400; 93 crash lines found once the sweep used real records — demand actions from the wrong status, deleting an insurance client still in use, replication check with SOFTECH down, a reservation image row without a file, a non-numeric transit doc number | Each answers a clear 400 / 409 / 503 or works; `test_round2_crash_fixes.py` |
| Transit actions (close-out) | Once the transit list stopped crashing, the sweep showed an export-only role (quality manager) could add notes to and mark in-transit transfers received | Refused server-side (`RouteModulePermission`); owner decision 2026-11-12: "No, block them". Force-close stays admin / purchasing (Z-7c) |
| Frontend (R8) | 125 menu entries whose API refused the role, or answered a role the menu hid | Owner decisions applied (PR 82); Playwright 23/23 in CI |
| Database | Two NOT NULL columns on the office DB broke inserts; `CREATE TABLE IF NOT EXISTS` skipped a column | `check_schema_drift`; customers 0032, users 0043; migration rules test |

## Accepted (owner decisions, with reasons in the files)

- M-4: claim net differs by a few piasters from the printed rows (finance's formula kept).
- D5: 13 SOFTECH write actions without a dry-run default — all explicit, audited actions.
- R5 grid sort: an unknown sort key is ignored rather than refused.
- Every remaining baseline line sits under a `# reason:` (owner decision, owner-approved review,
  or matrix-consistent).

## Left open

| Item | Owner of the decision |
|---|---|
| W-1 (voucher OTP hands the plain code to staff) — held until WhatsApp is chosen | Owner |
| `RBAC_ENFORCEMENT` / `NETWORK_POLICY_ENFORCEMENT` → `enforce` (D8). Before flipping, give supervisor and purchasing `hr edit` (shift templates) | Owner, after go-live, from `R3_enforce_readiness.md` |
| 77 `role_unproven` lines: routes that need a record in a specific state; a state-aware builder would close them | Next test round |
| `/loyalty`, `/products`, `/referral`: 11 menu-hidden pairs still answer (roles hold customers / catalog view) | Owner may revisit |
| Backend CI now takes 55–70 minutes of its 75-minute limit (see R0 §1) | Owner: split CI or raise the limit |
| Local PC: PostgreSQL ran out of memory twice on 2026-11-12 (891 stuck `rg.exe` searches, ~15 GB); 136 leftover test databases (7.5 GB) slow its crash recovery past the service start timeout | Owner: prune old test databases |
| Before cutover: run `check_schema_drift` on the VPS DB; check the live `auto_repair` value; rotate the smoke admin password; run `migrate` (users 0052/0053, pbx 0011) | Owner |
