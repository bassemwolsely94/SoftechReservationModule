# 14 — Decision register (needs the owner)

Full audit, 2026-11-15. Each row is a change Claude did **not** make because CLAUDE.md requires approval
(SOFTECH posting, pricing/discount, checkout, permissions policy, schema on large tables, deployment, live
configuration) or because it changes a business outcome. Finding IDs link to reports 03–07.

Decisions available per row: **approve** · **approve with changes** · **defer** · **reject** · **need more evidence**.

## Do now (security)

| # | Decision | Finding | Why it needs you | Recommended option | Effort |
|---|---|---|---|---|---|
| D-01 ✅ done 2026-11-15 | **Replace the office `SECRET_KEY`** (it equals the public placeholder in `.env.example`; office runs `DEBUG=True`) | SEC-1 (P0) | Live office config. A new key logs every user out and makes channel credentials encrypted with a key derived from the old one unreadable | 1) set `OMNI_CREDENTIALS_KEY` and re-encrypt stored channel credentials with it (memory: "office signing key cutover gap"); 2) set a new random `SECRET_KEY` (and `COUNSEL_PHONE_HASH_KEY`); 3) restart web + scheduler; 4) everyone logs in again. Then approve the code guard below | 30–60 min owner + Claude |
| D-02 ✅ done (`eec5a978`) | Make the settings guard refuse a placeholder key in DEBUG too | SEC-1 | Shipping it before D-01 would give the office a new random key **on every restart** (logouts, unreadable credentials) | Ship right after D-01 | 1 h |
| D-03 ✅ replaced by a code fix (`eec5a978`): DEBUG no longer opens webhooks or `/admin`; DEBUG itself stays on for the dev server | Turn `DEBUG` off on the office server | SEC-4 (P2) | DEBUG disables webhook signature checks and mounts `/admin/` without 2FA; turning it off changes error pages and static serving for the office dev workflow | Off, with `BEHIND_HTTPS_PROXY`/static settings as in `deploy/production.env.example` | 1 h |
| D-04 ◐ PR (owner 2026-11-19: review reports, then enforce; owner approves before merge) — `deploy/nginx-csp.conf` enforce + one-word rollback, `csp_report_summary`, CI CSP browser check; VPS apply = runbook §9.2 «D-04» | Move CSP from report-only to enforce | SEC-5 (P2) | Can break screens that load an unlisted source | Enforce after one week of report data from `/api/csp-report/` | 2 h |

## SOFTECH posting (stop-and-ask items)

| # | Decision | Finding | Risk today | Recommended fix | Effort |
|---|---|---|---|---|---|
| D-05 ✅ done PR 153 (a person confirms after an unknown outcome — a settled sale keeps no `vf2`) | POS crash recovery must also look in the settled tables for the `vf2` tag before a retry | S-1 (P1), BE-2/3 (P1/P2) | Second sale in SOFTECH after a lost commit reply + cashier settlement + retry | Search `stktransm` (final) as well as `stktransm5`; lock `prepare_order` and make it atomic; reconcile `push_failed` orders too | 1–2 days + golden-template verify |
| D-06 ✅ lock done PR 150; in-transaction `HOLDLOCK` read still open (rollback probe first) | A/P allocation writer: lock and re-read inside the SOFTECH transaction | S-2 (P1) | Lost update / doubled `chequestrans` link under two simultaneous writes on one invoice | Advisory lock per invoice + read inside the txn + relative update of `docvaluepay` | 1 day |
| D-07 ◐ PR 151: outcome unknown + 2 % adoption check; `INV<pk>` tag still open (rollback probe first) | Purchase-invoice idempotency key | S-3 (P1), S-4 | Duplicate purchase on retry when the supplier number has no digits; wrong adoption when digits collide | Write the `INV<pk>` tag the code already expects and look it up first; treat any post-commit error as "outcome unknown" | 1 day |
| D-08 ✅ done PR 152 (POS cancel part in PR 153) | ISR push and POS cancel after a lost commit reply | S-5, S-6, S-14 (P2/P3) | Second approved ISR; a cancelled order left pending in SOFTECH; duplicate `pos_cancel` rows | Record "outcome unknown" and re-read by tag before any retry | 1 day |
| D-09 | Price-change writer derives prices from the mirror and overwrites blindly | S-11 (P2), BE-14 | Wrong price if pack size / VAT changed in SOFTECH since the last sync | Read live pack/VAT inside the write, compare-and-set on the old value | 0.5–1 day |
| D-10 | Bare docnumber lookups in the reservation / transfer matchers | S-8 (P2) | A reservation confirmed against another branch's sale | Always key on (branch, doccode, docnumber) | 0.5 day |

## Money and business rules

| # | Decision | Finding | Note |
|---|---|---|---|
| D-11 | Discount-authority check and points rate **fail open** when the branch read fails | BE-12, BE-13, S-12 | Today: the sale proceeds without the check / with 0 points. Options: fail closed (sale blocked offline) or allow + flag for review |
| D-12 | Orders posted from the queue don't consume offer uses | BE-4 | Offers flag is OFF; must be fixed before the first promotion (P-38 gate) |
| D-13 | Loyalty balance updates are read-modify-write (all point methods) | BE-7 | The approval path is fixed (BE-6); converting every method to `F()`/row locks touches earn/expire jobs — approve as one batch |
| D-14 | Referral-point deduction lane | BE-8 | Fixed to *refuse* negative referral adjustments. Decide whether call-centre staff should be able to deduct referral points at all |
| D-15 | Insurance cover-page category discounts rounded as floats | BE-16 | Can differ by piasters from the Decimal totals; finance must pick the formula (M-4 precedent) |
| D-16 | Incentive recalculation: delete + insert without a transaction; forced recalculation un-finalizes | BE-10, BE-21 | Wrap in a transaction (safe) — but the "forced re-calc reopens finalized settlements" behaviour needs a rule |
| D-17 | Voucher / incentive audit rows deleted with their parent (`CASCADE`) | BE-11 | Change to `PROTECT` = a migration; vouchers with redemptions could no longer be deleted |
| D-18 | POS checkout runs as 4 browser requests and the browser computes tenders | FE-3 | Checkout path — one server endpoint that prices and pushes atomically |

## Performance and platform

| # | Decision | Finding | Note |
|---|---|---|---|
| D-19 ◐ PR 154: monitoring alerts kept 14 days; bell default still open | Notification flood: 726k rows, none read; bell polled every 30 s | PERF-1 | Purge/archive old notifications (data deletion) + default the bell to action items. Pairs with C26 |
| D-20 ✅ done PR 154, office 315 → 4.1 ms | Index on `customers_purchasehistory (invoice_date, doc_code)` + sargable date filters | PERF-2 | Migration on a large table: `CREATE INDEX CONCURRENTLY` at a quiet time |
| D-21 ◐ PR 154 opt-in unit + runbook §13.6 — owner installs | More than one web process on the VPS | PERF-3 | Deployment change (e.g. 3 uvicorn workers behind nginx + Redis channel layer); move 70–165 s exports/OCR off the web process |
| D-22 ⏳ Locust plan + runbook §13.7 — owner runs on the VPS | Load test with 20 simultaneous users | §12.10 | Not run: the only full database is the office DB that the live office runtime uses. Run on the VPS **before** Stage B, or approve a 10-minute run against the office at a quiet hour |
| D-23 | Drop the 3.65 GB of indexes with zero scans | PERF-7 | Stats were reset by the 2026-11-12 crashes — re-measure on production first |
| D-24 ✅ done PR 154 | Offline queue: bind writes to the user who made them and honour `X-Idempotency-Key` on the server | FE-1 | Changes the mobile offline contract |
| D-25 | Replace ~200 native `confirm/alert/prompt` dialogs and modal create flows | FE-9, FE-27 | UI redesign scale (CLAUDE.md rule 11); do screen by screen with the busiest first |
| D-26 | `RBAC_ENFORCEMENT` / `NETWORK_POLICY_ENFORCEMENT` → `enforce` | SEC-12, round 2 D8 | Unchanged from round 2: after go-live, per `docs/security/round2/R3_enforce_readiness.md` |

## Build picks

| # | Decision | Where |
|---|---|---|
| D-27 | Which of the Top 10 to build first (recommended order in the report; ~168 h total) | [09](09_TOP_30_QUICK_WINS.md) §4 |
| D-28 | The owner questions each candidate card lists ("Owner decision needed: yes") | [08](08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md) §8 |
