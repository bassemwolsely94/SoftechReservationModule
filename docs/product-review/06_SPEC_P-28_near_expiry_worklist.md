# 06 · SPEC P-28 — Near-expiry worklist: "won't sell in time", one action, and what happened

**Status:** specification (approved for spec 2026-10-30). **Build:** not yet authorised.
No SOFTECH write. It reuses P-26 (store roles, the FEFO at-risk rule) and P-29 (the return window, return records).

**Owner input** (ledger row P-28 and backlog P-28 "Revision after owner input"; these override the backlog card)
- The suggested action follows a **fixed order**:
  1. **Return.** Use it when the lot's supplier window is open or about to open (expiry month −2) and the supplier
     accepts returns. The lot goes to 105 before the window closes.
  2. **Move** to the fastest-selling branch.
  3. **Near-expiry corner / sell-first.**
  4. **Accept loss.**
- This replaces the WhatsApp broadcast with one structured list that is visible early enough. It works with P-29.
- Depends on the P-29 window rule (built: `apps/batches/return_window.py`).
- **Still needed:** the pilot branches (not yet named), and the units / FEFO check.
- Build only after the full review (owner process rule 2026-10-30).

**Owner decisions carried from P-26 / P-29** (2026-10-31)
- Store 110 is excluded from every number, screen and export.
- Supplier returns are owned by the HQ purchasing and replenishment specialists (`purchasing` role).

## 1. Problem (measured)

- About **232k EGP (1,615 lots)** of branch stock is predicted **not** to sell before expiry. It is mixed with about
  **180k** that will sell normally (backlog P-28; P-26 spec §1 gives the same ≈232k at the local rate, 180 days).
- The grids list lots **by date**, not by what will be lost. They show all near-expiry stock, including lots that will
  sell in time (backlog P-28).
- **Nobody measures what happened to an at-risk lot**: sold, moved, returned or expired. There is no realised
  write-off KPI and no sell-through tracking (`02_CURRENT_STATE_FINDINGS.md` §3.2).
- Markdown is OFF by default and **chain-wide** (`special_discp`), not branch- or batch-scoped (§3.2). It is not
  part of this card.
- No credible external benchmark exists for redistribution outcomes (`04_BENCHMARK_REGISTER.md` §3), so we set our
  own baseline.
- Branch batch data is usable: `StockExpiryBalance` batch qty equals `ItemStock` qty for 87–95% of items per branch
  (130: 3,943/4,192; 170: 3,608/4,369) (`03_DATA_OPPORTUNITY_MAP.md`, Batch 2).

**Code facts that shape the build** (read in the repo)
- **The at-risk rule already exists, twice, with the same maths.**
  - `stock_expiry.fefo_at_risk(batches, daily_rate, today, within_days)` returns **one total** per item × location.
    `at_risk_by_branch()` uses it for the P-26 KPIs, `insights.rule_near_expiry` and `forecasting._expiry_risk`.
  - `rebalance.plan()` repeats the same FEFO loop in line, then finds target branches.
  - Both use rate = `ItemDemandMetrics.qty_90d / 90` from the latest engine run (`stock_expiry._daily_rates`,
    `rebalance._load`).
  - Neither returns **per-lot** at-risk qty in a reusable form.
- **The rescue tab is move-only.** `/batches` tab `rebalance` «🔁 إنقاذ قبل الانتهاء» (`RebalanceWorklistTab` in
  `BatchesPage.jsx`) reads `GET /api/batches/stock-expiry/rebalance/` (`rebalance.worklist`).
  - It shows move lines, plus totals "no branch can absorb" and "too late to move".
  - It creates a DRAFT transfer via the existing `/transfers/` API. The permission is `CanCreateTransfer`, and open
    transfers are flagged so a line is not created twice.
  - It has no freshness bar, no keyboard grid and no branch scope. Any `BATCH_READ` user sees every branch.
  - HQ is never a move target, but HQ batches are counted as sources.
  - Settings: `EXPIRY_REBALANCE_HORIZON_DAYS` (180), `_MIN_DAYS` (30), `_TRANSIT_DAYS` (7).
- **The return side is built (P-29).**
  - `return_window.window_for(expiry, today, open_offset, close_offset)` gives `opens`, `closes` and `state`.
  - `return_calendar.attribute()` names the supplier with a confidence chip.
  - `return_calendar.request_returns()` creates idempotent `ExpiryDisposalRecord(decision='return_supplier',
    source='return_window')`. The record qty is the **whole** mirror qty of the lot.
  - `lead_days()` comes from SystemSetting `return_window_branch_lead_days` (14).
  - `branch_send_lines()` already adds "send to HQ for return by <date>" lines to the weekly worklist.
- **Weekly worklist.** `send_expiry_worklists` (scheduler job `expiry_worklists`, Sunday 08:00) calls
  `expiry_audit.generate_branch_worklists`. Its rows come from the **purchase-expiry audit** (`audit_candidates`,
  ranked by expected loss), not from the live mirror. There is one notification per branch per ISO week
  (`dedup_key expiry_worklist_<branch>_<yyyy>W<ww>`), sent to that branch's pharmacist and supervisor.
- **Stock snapshot.** `StockExpiryBalance` is a replace-snapshot (`sync_stock_expiry`, daily 05:30, all 6 nodes) and
  keeps **no history**. P-29 had to add `ReturnWindowMonthly` for the same reason.
- **Ledger for "what happened".** `stock_audit.StockLedgerLine` mirrors `stktrans` from HQ, which holds **every
  branch's lines** (`branchcode` 100/130/140/150/160/170; `03_DATA_OPPORTUNITY_MAP.md` Batch 3). This corrects the
  card's "HQ mirror only".
  - The window is `STOCK_AUDIT_WINDOW_DAYS` (365). It is refreshed every 2 hours (`stock_ledger_sync`) with a 03:15
    catch-up. The freshness domain is `stock_audit`.
  - Fields used: `branchcode`, `doccode`, `docnumber`, `docdate`, `storecode`, `itemcode`, `itemexpirydate`,
    `transqty`, `newqty`.
  - Doc labels in the repo (`stock_audit/rules.py` `_DOC_AR`, `stockcount.DOCCODE_LABELS`): 115 sale, 80 reservation
    sale, 30 sale return, 125 transfer out, 25 transfer in, 120 return to supplier, 160 write-off (هالك), 150 count
    deficit, 50 count surplus.
- **Safety inputs that exist.**
  - `catalog.safety.item_safety_flags`: block = inactive / archived / sale stopped; warn = return only, dispensing
    restricted, market shortage; info = fridge.
  - `Item.requires_fridge`.
  - `Item.strategic_hold`: kept on purpose for a contract or oncology patient. 0 items are flagged today (data map,
    Batch 2).
- **Branch scope.** `core/branch_scope.py` is on this branch (`branch_ids`, `allows`, `scope`). All-branch roles are
  admin, call_center, purchasing, supervisor and quality_manager. P-29's `_return_scope` predates it.

## 2. Scope

### 2.1 One per-lot at-risk function (extend P-26, no second rule)

1. In `apps/batches/stock_expiry.py`, add `fefo_at_risk_lots(batches, daily_rate, today, within_days)`.
   - It takes the same input as `fefo_at_risk`, plus the batch id in each tuple.
   - It returns per lot: `days_left`, `sells_qty`, `at_risk_qty`.
2. `fefo_at_risk` becomes `sum(at_risk_qty)` of that function. The P-26 numbers stay identical (a test proves it).
3. `rebalance.plan` calls the same function for its at-risk step instead of its own loop. Target-finding is
   unchanged.
4. **Rate basis.** There is one SystemSetting, `expiry_at_risk_rate_basis`:
   - `q90` (default, today's rule): `qty_90d / 90`.
   - `min_90_365`: the lower of `qty_90d / 90` and `qty_365d / 365`. The card proposes this so seasonal items do not
     look safe.
   - `_daily_rates` reads the setting. The P-26 KPIs, the insights rule, rebalance and this worklist all move
     together, so there is still **one** at-risk number. Changing the default is an owner decision (open question 3).
5. Horizon: 180 days (`EXPIRY_REBALANCE_HORIZON_DAYS`), the same as the card and P-26.

### 2.2 Which lots are listed

- `StockExpiryBalance`, `store_role='live'`, `qty > 0`, `today ≤ expiry ≤ today + 180`.
- **Branch nodes only.** HQ nodes (`Branch.kind == 'hq'`) are left out: HQ has no sales rate, so every HQ lot would
  look at risk. HQ stock stays in P-29 (105 and HQ live) and P-27 (open question 6).
- **Pilot gate.** SystemSetting `near_expiry_worklist_branches` (CSV of SOFTECH branch codes). The default is empty,
  which means nothing is listed and no job runs. The card's smallest version names 130 and 160. The owner names the
  pilot (open question 1).
- A lot is listed only when `at_risk_qty ≥ 1` (whole packs; the same threshold as rebalance).
- Value = at-risk qty × `Item.cost_price` (`_item_attr_map` `unit_cost`), the same basis as P-26 and P-29.
- Ranked by at-risk value, highest first. Ties go to the earliest expiry.

### 2.3 One suggested action per lot (fixed order, deterministic)

The at-risk qty of each lot goes down the owner's order. Each step takes what it can, and the rest moves to the next
step. The **suggested action** is the first step that takes at least 1 pack. The split is shown too, for example
"return 6 · corner 2".

| # | Action | Arabic label | Takes qty when | Reuses |
|---|---|---|---|---|
| 1 | `return` | «مرتجع للمورد» | `attribute()` gives a supplier with an active `SupplierReturnPolicy` (`accepts_expiry_returns=True`), and `window_for` state is `opens_next_month`, `open` or `closes_this_month`, and `closes − lead_days ≥ today` (the branch can still send it to HQ in time) | `return_window`, `return_calendar.attribute`, `lead_days` |
| 2 | `move` | «نقل لفرع يبيعه» | `rebalance.plan` finds a target branch with headroom for this batch (30 ≤ days left ≤ 180, transit 7 days) | `rebalance.plan` |
| 3 | `sell_first` | «ركن قرب الانتهاء / بيع أولاً» | the item can be sold: no `block` safety flag and no `return_only` flag; `days_left ≥` SystemSetting `near_expiry_sell_first_min_days` (proposed 30, open question 5) | `catalog.safety.item_safety_flags` |
| 4 | `accept_loss` | «قبول الخسارة» | whatever is left | — |

Rules:
- **Return takes the whole at-risk qty** of the lot. Whether a supplier also takes the part that would sell is open
  question 7. With an `ambiguous` supplier, the line shows the candidates, and a person picks one (as in P-29).
- A rejected answer in the P-29 history (`answer_history`, «رُفض آخر مرة») is shown as a hint. It does **not** skip
  the return step, the same as P-29 ("no rule hides a line"). Open question 8.
- **Move** skips items with `requires_fridge` during the pilot (P-27 risk note) and items with `strategic_hold`.
- **Sell-first never overrides safety** (CLAUDE.md rule 4). The line shows the counselling rule: do not give a
  short-dated lot to a patient whose course will outlast the expiry (chronic or long courses). It is a shelf and
  counter flag only. **No price change.**
- The engine only suggests. A person chooses the action, and only the chosen action is acted on.

### 2.4 Weekly snapshot and outcome check

**New model** `batches.AtRiskLot`: one row per lot per pilot branch while it is tracked.
- Identity: `branch_code`, `store_code`, `item_code`, `batch_no`, `expiry_date`. It is unique while `status='open'`.
- T0, set the first week the lot is listed:
  - `first_week` (the Sunday date);
  - `t0_qty`, `t0_at_risk_qty`, `t0_unit_cost`, `t0_value`;
  - `t0_daily_rate`, `rate_basis`.
- Latest week: `last_week`, `qty`, `at_risk_qty`, `value`.
- Suggestion: `suggested_action`, `split` (JSON qty per action), `suggest_detail` (JSON: supplier, confidence,
  window closes, send-by date, target branch + qty).
- Choice: `chosen_action`, `chosen_by`, `chosen_at`, `note`.
  - `disposal_record` FK (nullable, the P-29 return record).
  - `transfer_request` FK (nullable, `transfers.TransferRequest`).
- Outcome:
  - `outcome` (`''` | `saved_sold` | `saved_moved` | `saved_returned` | `written_off` | `expired` | `mixed` |
    `unexplained`);
  - `outcome_qty` (JSON per class), `saved_value`, `lost_value`;
  - `outcome_at`, `ledger_refs` (JSON line keys used).
- `status` (`open` | `closed`).

**New model** `batches.AtRiskRun`: started, finished, status, `week`, lines, value, `stock_expiry_run` (FK, the
snapshot it read), detail. It is the run log for freshness and for "once per week".

**Migration `batches/0008_near_expiry_worklist`:** the two new tables only. Existing tables are not changed.

**Job** `near_expiry_weekly` (new scheduler entry, Sunday 07:30). It runs after the 05:30 `stock_expiry_sync` and
before the 08:00 `expiry_worklists`.
1. It refuses to run on a stale snapshot. If the last `StockExpirySyncRun` is not `success` / `partial` today, or the
   pilot branch's node failed in that run, it waits. A catch-up runs when due (the per-module refresh rule).
2. For each pilot branch, it computes 2.1–2.3, opens new `AtRiskLot` rows and updates the open ones.
3. **Re-running in the same week is idempotent.** It updates the same rows, opens no duplicates and leaves T0
   values alone.

**Outcome check** (same job, for every open lot):
- Qty drop = previous `qty` − current mirror qty for the same lot. A lot missing from the mirror counts as qty 0.
- Attribution reads `StockLedgerLine` at that `branchcode` + `itemcode`, from `first_week` to today:

  | Class | Doc codes | Counted as |
  |---|---|---|
  | sold | 115, 80, minus 30 | saved |
  | moved | 125 (to a branch) | saved |
  | sent for return | 125 to HQ, then a closed P-29 record (doc 120 at HQ) | saved |
  | written off | 160, 150 | lost |
  | unexplained | qty drop not covered by the above | shown, never counted as saved |

- **Lot match.** If `itemexpirydate` is filled on branch sale lines, lines are matched to the lot by expiry date.
  If not, sales of the item are applied FEFO: the earliest expiry first, the same assumption as the at-risk rule.
  This is open question 2 (a read-only check). The help states which method is used.
- Each ledger line is used once (`ledger_refs`). A re-run consumes nothing twice.
- **Close:**
  - qty reaches 0 → outcome from the classes (one class ≥ 90% of the drop, otherwise `mixed`);
  - expiry date passed with qty > 0 → `expired`, with `lost_value` = remaining qty × `t0_unit_cost`.
- Saved value = saved qty × `t0_unit_cost`, capped at `t0_at_risk_qty`. Sales the lot would have made anyway are not
  "saved". Only the at-risk part counts.
- **Known limit:** a lot moved to another branch is "saved" at the source. If it becomes at risk at the target, it
  appears there as a new lot.

### 2.5 Actions (existing flows only)

| Action | Who (server-side) | What happens | Reuse |
|---|---|---|---|
| Choose action (any of 4) | `BATCH_DISPOSAL` + `branch_scope.allows` for the lot's branch | `chosen_action` set; `AuditLog.log` with before/after | — |
| «طلب مرتجع» | `BATCH_DISPOSAL` | Calls `return_calendar.request_returns` for the lot. It is idempotent: an open record for the same lot is linked, not duplicated | P-29 |
| «مسودة تحويل» | `CanCreateTransfer` (enforced by `/transfers/`) | The screen creates the draft through the existing API, as the rescue tab does now. Then `POST …/link-transfer/` stores the FK after the server checks that item, source and target match | transfers |
| «بيع أولاً» | `BATCH_DISPOSAL` | Flag only. Shown on the branch's weekly list | — |
| «قبول الخسارة» | `BATCH_DISPOSAL`, reason required | Flag only. Destroy or write-off stays native in SOFTECH. The P-26 store 102 flow is unchanged | — |

- Bulk choose on ticked rows (no modal).
- Every choice and link writes `AuditLog.log` (who, what, when, why, before/after).
- Whether branch pharmacists may mark «بيع أولاً» without `BATCH_DISPOSAL` is open question 9.

### 2.6 API (`apps/batches/urls.py`, new views in `views.py`)

| Endpoint | Method | Permission |
|---|---|---|
| `/api/batches/at-risk/?branch=&action=&status=&week=` | GET | `BATCH_READ`; rows filtered by `core/branch_scope.py` |
| `/api/batches/at-risk/choose/` | POST (bulk: ids + action + note) | `BATCH_DISPOSAL` + branch scope per row |
| `/api/batches/at-risk/request-return/` | POST (ids) | `BATCH_DISPOSAL` + scope; delegates to `request_returns` |
| `/api/batches/at-risk/<id>/link-transfer/` | POST | `CanCreateTransfer` + scope |
| `/api/batches/at-risk/outcomes/?branch=&from=&to=` | GET | `BATCH_READ` + scope |
| `/api/batches/at-risk/export/` | GET (xlsx) | `BATCH_READ` + scope |
| `/api/batches/at-risk/recompute/` | POST (background, one at a time) | `CanRefreshExpiry` |

`GET /api/batches/stock-expiry/rebalance/` stays as it is. It gains branch scope through the same helper (it has none
today).

### 2.7 Screen: extend `/batches` tab `rebalance` «🔁 إنقاذ قبل الانتهاء»

There is **no new tab**. The move-only table is replaced by the at-risk worklist. Move lines become the `move` filter.
The tab count stays «ثمانية».

1. **New component** `frontend/src/components/NearExpiryWorklistTab.jsx`, the same pattern as `ReturnWindowTab.jsx`.
   The inline `RebalanceWorklistTab` is removed from `BatchesPage.jsx`.
2. **Freshness:** `DataFreshnessBar domains={['expiry','stock_audit','near_expiry']}`.
   - New domain `near_expiry` in `apps/sync/freshness.py` reads `AtRiskRun` (cadence 10080, weekly).
   - The existing stock-expiry sync button (`CanRefreshExpiry`) and a «إعادة الحساب» button both show a
     `ProgressBar`.
3. **Header:** branch picker (pilot branches only, labels via `useBranchLabels`, never a bare code), and action chips
   with value and count: «مرتجع» · «نقل» · «بيع أولاً» · «خسارة».
4. **Grid** (`useGridKeyboard`: ↑↓, Space tick, Ctrl+A, Enter = accept the suggestion). Columns:
   - item, batch, expiry + days left;
   - qty, rate/month, at-risk qty, at-risk value;
   - suggested action chip + split;
   - detail (supplier + confidence + "send to HQ by", or target branch + its rate);
   - safety chips (fridge, restricted, chronic-course caution);
   - chosen action, link (return record / transfer number).
   Row actions are inline buttons. There is no modal.
5. **Sub-view «ماذا حدث؟»** (a toggle in the tab, not a modal): closed lots per week with outcome chips, saved vs lost
   value, unexplained qty, and the method used (expiry match or FEFO).
6. **Exports:** «⬇️ تصدير Excel» of both views, with branch names via `BL`.
7. The tab already gets help through `useHelpTab(tab)` in `BatchesPage`.

### 2.8 Weekly notification (extend, not a second message)

- `generate_branch_worklists` adds a section for **pilot branches only**: the top at-risk lots with their suggested
  action, for example «نقل 8 إلى <branch name>» or «أرسل للرئيسي للمرتجع قبل <date>».
- The existing P-29 send lines are folded into this section for pilot branches, so a lot is not listed twice.
- It stays one message per branch per ISO week (same `dedup_key` and recipients).
- Non-pilot branches keep today's message unchanged.
- No new notification type.

### 2.9 Help

`apps/help/content/batches.py`, screen `batches.main`, Arabic + English:
- rewrite the `rebalance` tab entry: the at-risk rule (FEFO, rate basis, 180 days), the fixed action order and why,
  sell-first safety, the «ماذا حدث؟» outcome classes and their limits (lot match method, unexplained qty, moved =
  saved at the source), pilot branches;
- update the `batches-main-rescue-transfer` tour step if its target moves;
- bump `updated`.

### 2.10 Tests (new file `apps/tests/test_near_expiry_worklist.py`)

| Test | Proves |
|---|---|
| per-lot = total | `sum(fefo_at_risk_lots)` == `fefo_at_risk` on fixtures; P-26 KPI values unchanged |
| rebalance unchanged | `rebalance.plan` gives the same lines as before on the existing fixtures |
| rate basis | `min_90_365` picks the lower rate; the default `q90` keeps today's numbers |
| lot filter | HQ, store 110, quarantine roles, expired and >180 days are never listed; only pilot branches |
| action order | return before move before sell-first before loss; split sums to the at-risk qty |
| return gate | no policy / window `later` / `missed` / send-by passed → no return step |
| move exclusions | fridge (pilot) and `strategic_hold` items get no move |
| sell-first safety | blocked or return-only items never get sell-first; below the min days → loss |
| weekly idempotent | a second run in the same week opens 0 rows and keeps T0 |
| stale snapshot | the job waits when the stock-expiry run failed for that node |
| outcome sold / moved / expired | ledger fixtures with 115, 125 and expiry passed → the right class and values |
| ledger once | a re-run consumes no ledger line twice; unexplained qty is never saved |
| saved cap | saved qty never exceeds `t0_at_risk_qty` |
| return link | «طلب مرتجع» creates or links one P-29 record; a second click creates 0 |
| transfer link | a mismatched item or branch → 400 |
| permissions | viewer cannot choose (403); a branch user sees only own-branch lots; audit row per choice |
| worklist message | a pilot branch gets the action section once per week; a non-pilot message is unchanged |
| freshness | `near_expiry` domain stale logic (`test_sync_freshness.py`) |
| scheduler | `near_expiry_weekly` registered (`test_scheduler_jobs.py`) |

Keep green: `test_expiry_buckets.py`, `test_expiry_rebalance.py`, `test_return_window.py`,
`test_purchase_expiry_audit.py`, `test_help.py`. The frontend build must pass.

## 3. Acceptance criteria

- One FEFO at-risk rule feeds the P-26 KPIs, the insights rule, rebalance and this worklist. Changing the rate basis
  changes all of them together (tests).
- For each pilot branch, the tab lists only lots that will not sell in time, ranked by at-risk value, each with one
  suggested action in the owner's order.
- The total is checked read-only against the backlog baseline (≈232k chain-wide, for the pilot branches' share)
  after deploy. Differences are explained, not hidden.
- Return and move use the existing P-29 records and draft transfers. No new return or transfer logic.
- Each Sunday the list re-computes, and every closed lot carries an outcome class and saved/lost value from the
  ledger. Unexplained qty is shown separately.
- Sell-first is never suggested for a blocked or return-only item, and never changes a price.
- No SOFTECH write anywhere in this card (code review: no writer import, no `writer_allowed` call).
- Help updated; `test_help.py` passes.

## 4. Measurement

- **Primary KPI:** of the at-risk value at T0, the % saved (sold + moved + returned) vs % expired or written off,
  per pilot branch, per 8-week cohort.
- Unexplained share of the qty drop. A high share means the attribution is not trustworthy yet.
- Monthly realised branch write-off: expired `AtRiskLot` value plus ledger 160 / 150 at the pilot branches.
- Use: % of listed lots with a chosen action within 7 days.
- **Baseline:** the first 8 weeks of the pilot (backlog card). The upper bound is ≈232k at risk in the current
  180-day window; the realised saving is measured, not assumed.

## Out of scope

- **Any SOFTECH write:** transfer, return (doc 120), write-off, adjustment. These stay native or go through the
  existing gated flows.
- **Any markdown or price change**, including branch- or batch-scoped markdown (P-16) and the existing chain-wide
  `near_expiry_markdown_enabled` request. Pricing is stop-and-ask.
- The near-expiry staff incentive (exists, inactive; not recommended for safety).
- Dead stock that is not near expiry (P-27) and HQ live stock.
- Following moved stock to its sale at the target branch, beyond it re-appearing as a new lot there.
- Patient-level checks at the counter (which patient gets which lot). Sell-first only shows the counselling rule.

## Open questions / owner inputs

1. **Pilot branches.** The card proposes 130 and 160. The ledger says "still to be named".
2. **Units / FEFO check** (ledger "evidence still needed"). To verify read-only on 20 lots per pilot branch:
   - Are `stkbalexpiry.itemqty` and `ItemDemandMetrics.qty_90d` both in packs? The POS writer notes say `transqty` is
     in packs, with fractions for strips.
   - Do branches really sell earliest expiry first?
   - Is `StockLedgerLine.itemexpirydate` filled on branch 115 sale lines (decides the lot-match method)?
3. **Rate basis:** switch everyone to the lower of the 90-day and 365-day rates (card's seasonal-risk fix), or keep
   `qty_90d / 90`? It also changes the P-26 KPIs.
4. **"Fastest-selling branch":** the existing rule picks the target with the most headroom in the time left, not the
   highest rate. Is that acceptable? Proposed: yes, because it is the branch that can actually absorb the qty.
5. **Sell-first minimum days:** below how many days left is a corner pointless (proposed 30)? Who owns the corner in
   a branch?
6. **HQ live stock** near expiry: in this list, in P-27, or only in P-29?
7. **Return qty:** should the return cover only the at-risk part, or the whole lot? `request_returns` records the
   whole lot today.
8. Should a supplier's earlier rejection for the same item skip the return step? It is a hint only today, as in P-29.
9. **Who chooses actions:** branch pharmacists for sell-first and loss, HQ purchasing for return and move? Do branch
   pharmacists hold `catalog` edit (`BATCH_DISPOSAL`)? To check in the permission matrix.
10. **Branch → HQ return route:** which doc code does a branch use to send stock to HQ 105 for return (125, or
    another)? The outcome class "sent for return" depends on it. To verify read-only.
11. Accept-loss approval: is the branch's choice enough, or must a supervisor or quality manager confirm it?

## Stop-and-ask

- Any SOFTECH write (transfer posting, doc 120, write-off, adjustment).
- Any markdown, discount or price change for near-expiry stock (CLAUDE.md: pricing is stop-and-ask).
- Changing the default rate basis, because it changes the P-26 numbers already live.
- Turning on WhatsApp delivery of the worklist (`expiry_worklist_whatsapp_enabled`). It is outbound messaging, so
  it is a separate decision.
