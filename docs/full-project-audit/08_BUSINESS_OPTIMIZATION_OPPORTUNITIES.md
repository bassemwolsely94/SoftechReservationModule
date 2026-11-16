# 08 — Business opportunities: quick wins and best return on development time

Date: 2026-11-15. Read-only review of the repo `.claude/worktrees/full-audit` (branch `claude/full-project-audit`), the product-review ledger and the 2026-11-15 handoff. No database, SOFTECH or server was touched. Money figures are quoted only from measured numbers already in `docs/product-review/05_PROPOSAL_BACKLOG.md` / `00_INDEX_AND_DECISION_LEDGER.md` (office PG read-only snapshots, 2026-10-28/31) — none are invented; where no figure exists the score says so.

## 1. Headline

- 33 candidates scored. **23 finish / switch on / connect / expose existing code; 10 are new** (and those 10 are small builds on data already mirrored).
- The biggest measured money is in **stock and expiry**, and most of the tooling is already built: return window (≈64k in window, ≈113k already missed, 2 suppliers only), near-expiry (≈232k won't sell in time), dead stock (1.43M sells elsewhere, ≈713k fits another branch's gap). The gap is the **last step**: action, assignment and outcome.
- The second theme is **sales capture without POS go-live**: network stock, demand capture, reservation and verified alternatives are already built for the POS drawer, but the POS is not live (writer OFF). The call centre — where "most calls are about orders and availability" — sees one branch only. Exposing what exists there is the cheapest sales lever.
- Several ledger items are now stale: **P-05 consent is built** (commit 937883e6, 2026-11-15), **P-27 part A** (dead-stock list) and **P-37 identified-sale gamification** (`apps/gamification/pic.py`) exist. Owner-deferred/rejected items are not re-proposed (P-01, P-02–P-04, P-44, P-45 insurance collection, P-01(a)/(c), order-list split, P-31 "unordered" flagging as first built, P-33(b)). P-16 near-expiry markdown and any minimum-delivery-order rule are pricing → stop-and-ask, listed only as decisions.

## 2. Scoring method

- Ten scores 1–5 per candidate (reasons in §5). Effort and risk are inverted (5 = least effort / least risk).
- **Value** = mean(revenue, profit, time saved, waste reduction, loss prevention, UX). **Feasibility** = mean(effort, risk, data readiness, confidence).
- **Quick-win score** = Value × Feasibility (max 25). **Return on development time (RoDT)** = Quick-win score ÷ hours × 10.
- Hours = one developer, including in-app help (AR+EN) and tests as CLAUDE.md requires; excludes owner time, data entry and pilot weeks.
- Measurability: **direct** (a count/EGP from our mirror), **expected** (logic-based, measurable later), **speculative**.

## 3. TOP 30 quick wins (ranked by quick-win score)

| # | ID | Candidate | Area | Kind | Hours | Value | Feas. | Score | RoDT | Owner decision |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | C03 | Return-window coverage: more suppliers + weekly branch "send by" list | Inventory & expiry | existing | 6 | 3.33 | 4.50 | 15.0 | 25.0 | yes |
| 2 | C05 | Dead-stock "move" lane → one-click internal transfer draft (P-27 part B) | Inventory & expiry | existing | 16 | 3.50 | 4.00 | 14.0 | 8.8 | yes |
| 3 | C04 | Near-expiry action worklist with outcome check (P-28) | Inventory & expiry | existing | 24 | 3.33 | 4.00 | 13.3 | 5.6 | yes |
| 4 | C32 | Weekly HQ exception digest: money at stake + who acts | Management | new | 20 | 3.50 | 3.75 | 13.1 | 6.6 | no |
| 5 | C01 | Network stock + capture inside the call centre and omni inbox | Sales growth | existing | 10 | 3.00 | 4.25 | 12.8 | 12.8 | no |
| 6 | C02 | Morning brief that says what to do (action lines per branch) | Management | existing | 12 | 3.33 | 3.75 | 12.5 | 10.4 | yes |
| 7 | C15 | AP exception review queue: bulk review + weekly finance digest | Finance | existing | 10 | 2.83 | 4.00 | 11.3 | 11.3 | no |
| 8 | C13 | Stock-audit finding → task + targeted count (P-07) | Loss prevention | existing | 14 | 2.67 | 4.00 | 10.7 | 7.6 | yes |
| 9 | C08 | Refill-due list from buying behaviour, into existing call lists (P-46) | Sales growth | existing | 20 | 2.67 | 3.75 | 10.0 | 5.0 | yes |
| 10 | C25 | Tiered-cover report under a cash budget (P-34, read-only) | Procurement | new | 24 | 2.67 | 3.75 | 10.0 | 4.2 | yes |
| 11 | C24 | Bulk actions on the remaining worklists | Staff productivity | existing | 12 | 2.33 | 4.25 | 9.9 | 8.3 | no |
| 12 | C23 | Saved filters / default views per user on worklist screens | Staff productivity | new | 16 | 2.17 | 4.50 | 9.8 | 6.1 | no |
| 13 | C16 | Show months-of-cover and the "buying despite cover" warning on the order export | Procurement | existing | 8 | 2.33 | 4.00 | 9.3 | 11.7 | no |
| 14 | C26 | Make the bell useful: verify mark-read + "action items only" default | Management | existing | 6 | 2.00 | 4.50 | 9.0 | 15.0 | yes |
| 15 | C06 | "Out here, in stock there" daily list from current stock (P-30 list without waiting for newqty) | Sales growth | new | 20 | 2.67 | 3.25 | 8.7 | 4.3 | yes |
| 16 | C30 | Phantom-substitution monthly review list | Loss prevention | existing | 4 | 2.00 | 4.25 | 8.5 | 21.2 | yes |
| 17 | C07 | Discount policy-breach report (P-36) as a stock-audit rule | Finance / loss prevention | new | 20 | 2.50 | 3.25 | 8.1 | 4.1 | no for the rule |
| 18 | C10 | Switch on WhatsApp refill reminders for consented customers | Sales growth | existing | 4 | 2.50 | 3.25 | 8.1 | 20.3 | yes |
| 19 | C17 | "Bought dearer while cheaper was available" monthly report | Procurement | new | 10 | 2.00 | 4.00 | 8.0 | 8.0 | no |
| 20 | C27 | POS search/discount-suggest debounce + cached reference reads (P-06) | Sales growth | existing | 8 | 2.00 | 4.00 | 8.0 | 10.0 | no |
| 21 | C19 | One margin basis + channel × branch board (P-35) | Finance | existing | 24 | 2.33 | 3.25 | 7.6 | 3.2 | yes |
| 22 | C14 | Count variance valued at cost + movement netting (P-08) | Loss prevention | existing | 14 | 2.17 | 3.50 | 7.6 | 5.4 | yes |
| 23 | C11 | Identified-sale rate on the brief and /me (P-37 surfacing) | Sales growth | existing | 6 | 1.67 | 4.50 | 7.5 | 12.5 | no |
| 24 | C31 | Fridge log + EDA visit checklist in QA (P-53) | Loss prevention / compliance | new | 16 | 2.00 | 3.75 | 7.5 | 4.7 | yes |
| 25 | C33 | Reservation stock check on every line (not header item only) | Sales growth | existing | 6 | 1.67 | 4.50 | 7.5 | 12.5 | no |
| 26 | C09 | Schedule follow-up generation + auto-close, retire the May backlog | Staff productivity | existing | 6 | 1.83 | 4.00 | 7.3 | 12.2 | yes |
| 27 | C12 | One-tap call reason + outcome (P-49) | Staff productivity | existing | 6 | 1.50 | 4.75 | 7.1 | 11.9 | no |
| 28 | C28 | Missed-sale suggestions from call-centre items not ordered | Sales growth | existing | 12 | 2.00 | 3.50 | 7.0 | 5.8 | yes |
| 29 | C21 | Delivery stuck-order auto-close (P-48 part) | Staff productivity | existing | 8 | 1.67 | 4.00 | 6.7 | 8.3 | no |
| 30 | C18 | Missing-bonus check at invoice receipt | Procurement | new | 16 | 2.00 | 3.25 | 6.5 | 4.1 | yes |

Below the cut: C29 Verified alternatives in the call centre when out of stock (6.5); C20 Delivery small-order and fee-less invoice report (6.0); C22 Ride-level rider payout ledger (P-48) (6.0).

## 4. TOP 10 best return on development time

Full RoDT order first; the selection rule and the TOP 10 follow below it.

| RoDT rank | ID | Candidate | Hours | RoDT |
|---|---|---|---|---|
| 1 | C03 | Return-window coverage: more suppliers + weekly branch "send by" list | 6 | 25.0 |
| 2 | C30 | Phantom-substitution monthly review list | 4 | 21.2 |
| 3 | C10 | Switch on WhatsApp refill reminders for consented customers | 4 | 20.3 |
| 4 | C26 | Make the bell useful: verify mark-read + "action items only" default | 6 | 15.0 |
| 5 | C01 | Network stock + capture inside the call centre and omni inbox | 10 | 12.8 |
| 6 | C11 | Identified-sale rate on the brief and /me (P-37 surfacing) | 6 | 12.5 |
| 7 | C33 | Reservation stock check on every line (not header item only) | 6 | 12.5 |
| 8 | C09 | Schedule follow-up generation + auto-close, retire the May backlog | 6 | 12.2 |
| 9 | C12 | One-tap call reason + outcome (P-49) | 6 | 11.9 |
| 10 | C16 | Show months-of-cover and the "buying despite cover" warning on the order export | 8 | 11.7 |
| 11 | C15 | AP exception review queue: bulk review + weekly finance digest | 10 | 11.3 |
| 12 | C29 | Verified alternatives in the call centre when out of stock | 6 | 10.8 |
| 13 | C02 | Morning brief that says what to do (action lines per branch) | 12 | 10.4 |
| 14 | C27 | POS search/discount-suggest debounce + cached reference reads (P-06) | 8 | 10.0 |
| 15 | C05 | Dead-stock "move" lane → one-click internal transfer draft (P-27 part B) | 16 | 8.8 |
| 16 | C21 | Delivery stuck-order auto-close (P-48 part) | 8 | 8.3 |
| 17 | C24 | Bulk actions on the remaining worklists | 12 | 8.3 |
| 18 | C17 | "Bought dearer while cheaper was available" monthly report | 10 | 8.0 |
| 19 | C13 | Stock-audit finding → task + targeted count (P-07) | 14 | 7.6 |
| 20 | C20 | Delivery small-order and fee-less invoice report | 8 | 7.5 |
| 21 | C32 | Weekly HQ exception digest: money at stake + who acts | 20 | 6.6 |
| 22 | C23 | Saved filters / default views per user on worklist screens | 16 | 6.1 |
| 23 | C28 | Missed-sale suggestions from call-centre items not ordered | 12 | 5.8 |
| 24 | C04 | Near-expiry action worklist with outcome check (P-28) | 24 | 5.6 |
| 25 | C14 | Count variance valued at cost + movement netting (P-08) | 14 | 5.4 |
| 26 | C08 | Refill-due list from buying behaviour, into existing call lists (P-46) | 20 | 5.0 |
| 27 | C31 | Fridge log + EDA visit checklist in QA (P-53) | 16 | 4.7 |
| 28 | C06 | "Out here, in stock there" daily list from current stock (P-30 list without waiting for newqty) | 20 | 4.3 |
| 29 | C25 | Tiered-cover report under a cash budget (P-34, read-only) | 24 | 4.2 |
| 30 | C07 | Discount policy-breach report (P-36) as a stock-audit rule | 20 | 4.1 |
| 31 | C18 | Missing-bonus check at invoice receipt | 16 | 4.1 |
| 32 | C19 | One margin basis + channel × branch board (P-35) | 24 | 3.2 |
| 33 | C22 | Ride-level rider payout ledger (P-48) | 20 | 3.0 |

### Selection rule

Pure RoDT favours tiny items with little value (C30 digest, C10 switch-on, C26 bell, C11 tile, C33 — all under 6 h but Value ≤ 2.5, or blocked on owner inputs). The TOP 10 is therefore **the highest RoDT among candidates with Value ≥ 2.5 and quick-win score ≥ 9**, then put in dependency order. Cheap enablers that a TOP-10 item needs (C09, C12) are bundled with it.

### The TOP 10, in build order

| Order | ID | Candidate | Module | Hours | Why |
|---|---|---|---|---|---|
| 1 | C03 | Return-window coverage + weekly "send by" list | batches / `procurement.SupplierReturnPolicy` | 6 | Highest RoDT (25.0). Most time-critical measured cash: ≈64k in window, ≈113k already past it, for 2 suppliers only. Config + schedule; owner supplies windows. |
| 2 | C01 (+C12 enabler, +6 h) | Network stock + capture in call centre / omni | `StockLookupDrawer.jsx` reuse; callcenter | 10 (+6) | Sales lever that does not wait for POS go-live; APIs exist; C12 call reasons measure it (636/647 calls "general"). |
| 3 | C15 | AP exception bulk review + finance digest | finance recon (`scan_ap_anomalies`) | 10 | 59 mis-links + 2,631 held matches waiting; duplicate-payment control with no writer change. |
| 4 | C02 | Morning brief with action lines (+ /me) | `apps/insights/brief.py` | 12 | Turns built engines into a daily to-do; in-app works while WhatsApp send stays off. Uses C03's list. |
| 5 | C05 | Dead-stock move lane → transfer drafts | `purchasing/dead_stock.py` + transfers | 16 | 1.43M sells elsewhere, ≈713k fits a gap; only the move step is missing. Internal drafts; ISR push stays stop-and-ask. |
| 6 | C13 | Stock-audit finding → task + targeted count | stock_audit + tasks + stockcount | 14 | 915 open findings with no owner; loss prevention by connecting 3 built apps. |
| 7 | C04 | Near-expiry action worklist + outcome (P-28) | batches rescue tab | 24 | ≈232k (1,615 lots) won't sell in time; spec written; needs C03's window rule. |
| 8 | C08 (+C09 enabler, +6 h) | Behaviour-based refill-due call list | followups call lists + consent | 20 (+6) | 665 lapsed regular cash buyers (233k/month spend) + 249 delivery (90k); consent now built; C09 schedules generation/auto-close first. |
| 9 | C32 | Weekly HQ exception digest (EGP + who acts) | insights + notifications routing | 20 | One ranked list over C03/C05/C13/C15/P-31 outputs; best after those exist (and after C26 fixes the bell). |
| 10 | C25 | Tiered-cover report under a cash budget (P-34) | purchasing engine metrics | 24 | Fast items at 0.57 months cover carry 85% of est. lost margin; slow items hold 2.39M. Read-only; tier values = owner. |

**Total ≈ 168 h** including the two enablers. Near misses: C16 cover warning on the order export (8 h, score 9.3 — just under the value floor), C24 bulk actions (12 h), C23 saved filters (16 h), C07 discount-breach rule (20 h; high loss value, but class-B validation first), C06 out-here-in-stock-there list (20 h).

**Dependency order:** C03 → C02, C04 · C12 with C01 → C29, C28 · C09 → C08 → C10 · C05/C13/C15 → C32 (C26 first) · C06 measurement → C25 sizing. C05 must reuse the doc-30 wave overlap guard so the same stock is not drafted twice.

## 5. Candidate cards

### C01 · Network stock + capture inside the call centre and omni inbox

- **Area / kind:** Sales growth · finish / switch on / connect existing
- **Existing module + reuse:** `frontend/src/components/StockLookupDrawer.jsx` (today only in `POSOrderPage.jsx`); `frontend/src/pages/CallCenterPage.jsx` shows `qty_at_branch` for ONE branch (line ~1059); `frontend/src/pages/OmniInboxPage.jsx` has no item lookup; APIs `/items/{id}/stock/`, `/demand/`, `/reservations/`, `/transfers/` already exist
- **Current problem:** Owner (backlog Batch 6): "most calls are about orders and availability"; agents see one branch's stock and cannot turn "not here" into a reservation, transfer or demand record. The drawer that does exactly this sits only on the POS, which is not live (POS writer OFF).
- **Proposed solution:** Mount the existing drawer on the call-centre item list and the omni conversation side panel (prefill customer/phone, channel=call_center/omni). No new API.
- **Benefit mechanism:** Calls that end in "not available" become a reservation/transfer at another branch instead of a lost customer; captured demand feeds buying.
- **Estimated hours:** 10 (2 mount points, prefill, channel tag, help AR/EN, 3 view/permission tests)
- **Required tests:** drawer renders on both screens; demand/reservation created with channel + branch scope; call_center role cannot see other branches' customers unmasked
- **Measurability:** Direct: count demand/reservation/transfer rows with channel call_center/omni per week
- **Dependencies:** none
- **Owner decision needed:** no (P-47 / P-49 already approved for specification)
- **Value 3.00 · Feasibility 4.25 · Score 12.8 · RoDT 12.8**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 4 | turns availability calls into sales at another branch |
| Profit | 3 | mostly full-margin cash/delivery sales |
| Time saved | 4 | removes phone calls to branches/HQ to ask for stock |
| Waste reduction | 2 | moves slow stock to a buyer |
| Loss prevention | 1 | no loss lever |
| UX | 4 | one drawer agents already know from POS |
| Effort (5=least) | 4 | component exists; wiring + help only |
| Risk (5=least) | 5 | read + internal records only, no SOFTECH write |
| Data readiness | 4 | ItemStock mirror class A; sync lag minutes |
| Confidence | 4 | proven pattern; adoption is the only unknown |

### C02 · Morning brief that says what to do (action lines per branch)

- **Area / kind:** Management · finish / switch on / connect existing
- **Existing module + reuse:** `apps/insights/brief.py` (compose: yesterday, MTD, worst 3 findings, reservations/transfers); `apps/batches/return_calendar.py`; `apps/purchasing/dead_stock.py`; batches rebalance (`/purchase-expiry/rebalance-suggest/`); switch `MORNING_BRIEF_SEND_ENABLED` (off)
- **Current problem:** The brief reports numbers; it never names the 3 actions with money at stake today. Branches "notice too late" (owner, Batch 2).
- **Proposed solution:** Add one "اليوم" section: lots whose return window closes this month (send to HQ by date), top 3 dead-stock "move" lines out of this branch, top near-expiry rescue lots, oldest open transfer. Same text on `/me` so it works while WhatsApp sending stays off.
- **Benefit mechanism:** Turns existing engines into a daily checklist; earlier action on return windows and moves.
- **Estimated hours:** 12 (4 section builders reusing engines, /me widget, help, tests)
- **Required tests:** compose() golden text per branch; no section when empty; closed branches excluded; send still blocked when switch off
- **Measurability:** Expected: share of listed lots actioned within 7 days (ReturnWindowMonthly, transfers)
- **Dependencies:** C03 for full supplier coverage
- **Owner decision needed:** yes: WhatsApp staff number + flip MORNING_BRIEF_SEND_ENABLED (in-app part needs nothing)
- **Value 3.33 · Feasibility 3.75 · Score 12.5 · RoDT 10.4**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 2 | indirect |
| Profit | 3 | avoided write-off + return credit |
| Time saved | 4 | no one has to open 4 screens |
| Waste reduction | 4 | targets the expiring/dead lots |
| Loss prevention | 3 | missed-window losses |
| UX | 4 | one short list |
| Effort (5=least) | 4 | compose from existing engines |
| Risk (5=least) | 4 | text only; send switch already gated |
| Data readiness | 4 | all inputs class A/B already in Postgres |
| Confidence | 3 | needs a branch to act on it |

### C03 · Return-window coverage: more suppliers + weekly branch "send by" list

- **Area / kind:** Inventory & expiry · finish / switch on / connect existing
- **Existing module + reuse:** P-29 built: `apps/batches/return_window.py`, `return_calendar.py`, `procurement.SupplierReturnPolicy` (565 + 260 seeded; editable via `apps/batches/views.py:1249-1300`), `/batches` «📆 تقويم المرتجع», monthly digest to `purchasing`
- **Current problem:** Only 2 suppliers have windows. Measured for those 2: ≈64k EGP in window now, ≈15k closing this month, ≈113k already past the window (docs/product-review/05_PROPOSAL_BACKLOG.md, Batch 2 table). Digest is monthly, branches act on a 14-day lead.
- **Proposed solution:** Owner/purchasing enters the next suppliers' windows (Ramco 30, Egy Drug 786 …) in the existing policy editor; switch the branch "send to HQ by" lines to a weekly digest; add a "window closes in ≤14 days" filter.
- **Benefit mechanism:** Credit notes instead of write-off on stock that is still returnable.
- **Estimated hours:** 6 (weekly schedule + filter + help; supplier data entry is owner time, not dev)
- **Required tests:** window_for() for a new policy row; weekly digest only lists in-window lots; 110 excluded
- **Measurability:** Direct: doc 120 credits per month vs ReturnWindowMonthly "missed" value
- **Dependencies:** owner supplier windows
- **Owner decision needed:** yes: supplier return windows
- **Value 3.33 · Feasibility 4.50 · Score 15.0 · RoDT 25.0**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 4 | direct supplier credit |
| Time saved | 3 | one list instead of manual checking |
| Waste reduction | 5 | core expiry lever |
| Loss prevention | 4 | stops missed-window losses |
| UX | 3 | existing tab |
| Effort (5=least) | 5 | config + a schedule change |
| Risk (5=least) | 5 | read-only advice |
| Data readiness | 4 | policy data must come from the owner |
| Confidence | 4 | measured for 2 suppliers |

### C04 · Near-expiry action worklist with outcome check (P-28)

- **Area / kind:** Inventory & expiry · finish / switch on / connect existing
- **Existing module + reuse:** `/batches` «🔁 إنقاذ قبل الانتهاء» rebalance tab (`apps/batches/views.py` rebalance views), P-26 at-risk rule (`at_risk_by_branch`), spec `docs/product-review/06_SPEC_P-28_near_expiry_worklist.md`, `stock_audit.StockLedgerLine` for outcome
- **Current problem:** ≈232k EGP (1,615 lots) will not sell before expiry at the branch rate; 160k of it has zero local sales (05_PROPOSAL_BACKLOG.md Batch 2). Rescue tab suggests moves but gives no single action per lot and never checks the result.
- **Proposed solution:** One suggested action per lot in order return (window) → move → near-expiry corner → loss; weekly outcome from the ledger (sold / moved / returned / expired).
- **Benefit mechanism:** Converts the at-risk value into sales, transfers or credit; measures it.
- **Estimated hours:** 24 (action rule, outcome job, tab columns, help, tests)
- **Required tests:** action order per lot type; outcome classifier on ledger fixtures; store 110/102/103 excluded
- **Measurability:** Direct: value expired vs value rescued per month
- **Dependencies:** C03 (window rule)
- **Owner decision needed:** yes: build authorisation (spec waiting)
- **Value 3.33 · Feasibility 4.00 · Score 13.3 · RoDT 5.6**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 2 | some lots sold in time |
| Profit | 4 | avoided write-off |
| Time saved | 3 | one ordered list |
| Waste reduction | 5 | expiry waste is the target |
| Loss prevention | 3 | fewer silent losses |
| UX | 3 | extends a known tab |
| Effort (5=least) | 3 | spec written; medium |
| Risk (5=least) | 5 | read-only |
| Data readiness | 4 | branch batches 87–95% match stkbal |
| Confidence | 4 | measured base |

### C05 · Dead-stock "move" lane → one-click internal transfer draft (P-27 part B)

- **Area / kind:** Inventory & expiry · finish / switch on / connect existing
- **Existing module + reuse:** `apps/purchasing/dead_stock.py`, `dead_stock_views.py`, `frontend/src/pages/cash/DeadStockTab.jsx` (move/return/stop lanes, read-only); `apps/transfers` TransferRequest
- **Current problem:** Branch stock with no local sale 6+ months: 1.87M; 1.43M of it sells at other branches and ≈713k fits another branch's 2-month gap (05_PROPOSAL_BACKLOG.md). The tab lists it but nothing moves it.
- **Proposed solution:** Ticked "move" lines create TransferRequest drafts (our internal record, existing approval flow). No ISR/SOFTECH push (stop-and-ask stays).
- **Benefit mechanism:** Avoided purchase at the receiving branch + avoided write-off at the sender.
- **Estimated hours:** 16 (bulk create, duplicate guard vs open transfers/waves, audit, help, tests)
- **Required tests:** one draft per (item, from, to); no draft if an open transfer exists; branch-scope permission; audit row
- **Measurability:** Direct: value moved and later sold at the receiver (90 days)
- **Dependencies:** doc 30 wave rules (overlap guard)
- **Owner decision needed:** yes: P-27 part B approval
- **Value 3.50 · Feasibility 4.00 · Score 14.0 · RoDT 8.8**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 3 | stock sells where it is needed |
| Profit | 4 | cash released |
| Time saved | 4 | removes manual transfer entry |
| Waste reduction | 4 | prevents ageing into expiry |
| Loss prevention | 2 | small |
| UX | 4 | bulk tick → draft |
| Effort (5=least) | 4 | transfer API exists |
| Risk (5=least) | 4 | internal only; overlap with توزيعة waves to guard |
| Data readiness | 4 | engine run #104 |
| Confidence | 4 | owner confirmed "moving it is the fix" |

### C06 · "Out here, in stock there" daily list from current stock (P-30 list without waiting for newqty)

- **Area / kind:** Sales growth · new (small, on existing data)
- **Existing module + reuse:** `apps/purchasing/transfer_engine.py` (deficit vs surplus over `ItemDemandMetrics`), `apps/stock_audit/newqty_check.py` (step-0 gate), `frontend/src/pages/supply/*`
- **Current problem:** Engine root-cause split: "transfer" (stock existed elsewhere) ≈142k of ≈390k est. lost revenue/30d (inferred, 05_PROPOSAL_BACKLOG.md Batch 3). Most often "the branch waits for the next ISR".
- **Proposed solution:** 08:30 list per branch of A/B items at zero here with sellable surplus at another branch, from today's ItemStock; hand-off to transfer draft. newqty stays the gate only for measured stock-out duration.
- **Benefit mechanism:** Shorter stock-outs on fast items without extra purchase cash.
- **Estimated hours:** 20 (list builder over existing engine output, schedule, screen tab, help, tests)
- **Required tests:** surplus never below safety stock; closed branches excluded; matches transfer_engine on fixtures
- **Measurability:** Expected: zero-stock days on listed items (once newqty passes, direct)
- **Dependencies:** owner agrees to decouple from newqty gate
- **Owner decision needed:** yes
- **Value 2.67 · Feasibility 3.25 · Score 8.7 · RoDT 4.3**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 4 | fast items carry 85% of lost margin |
| Profit | 3 | no new stock bought |
| Time saved | 3 | replaces calls/WhatsApp |
| Waste reduction | 2 | uses surplus |
| Loss prevention | 1 | none |
| UX | 3 | a daily list |
| Effort (5=least) | 3 | medium |
| Risk (5=least) | 4 | read-only + drafts |
| Data readiness | 3 | ItemStock A; spec wanted newqty first |
| Confidence | 3 | estimate is inferred |

### C07 · Discount policy-breach report (P-36) as a stock-audit rule

- **Area / kind:** Finance / loss prevention · new (small, on existing data)
- **Existing module + reuse:** `apps/stock_audit/rules.py` RULES registry (has `sale_below_cost`), `customers.PurchaseHistoryLine.disc_customer_pct` + `list_price` (`apps/customers/models.py:537-553`), `Customer.discount_percent`, item ceiling `posdiscp`
- **Current problem:** Owner: no discretionary discount allowed, so above-policy = breach. 15.8% of cash lines carry a discount (avg 7.7%); ≈670 lines below cost in 90 days (05_PROPOSAL_BACKLOG.md Batch 4). Nobody sees who/where.
- **Proposed solution:** New rule `discount_above_policy` (expected = max(class %, item ceiling)); findings by branch/cashier/item with EGP; contracts 10, donations 16, compensations 17 excluded. Read-only; no change to discount calculation.
- **Benefit mechanism:** Margin recovered by enforcing the existing policy.
- **Estimated hours:** 20 (rule fn + params + 20-sample validation export + help + tests)
- **Required tests:** expected-discount calc on fixtures per class; exclusions; branch scope on findings
- **Measurability:** Direct: breach EGP per branch per month (baseline month 1)
- **Dependencies:** finance validates 20 samples
- **Owner decision needed:** no for the rule (answered); finance sample check
- **Value 2.50 · Feasibility 3.25 · Score 8.1 · RoDT 4.1**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 4 | direct margin |
| Time saved | 2 | auto report |
| Waste reduction | 1 | none |
| Loss prevention | 5 | catches leakage |
| UX | 2 | report |
| Effort (5=least) | 3 | B-validation first |
| Risk (5=least) | 4 | read-only; sensitive for staff |
| Data readiness | 3 | class B: is disc_customer_pct policy or manual? |
| Confidence | 3 | size unknown until run |

### C08 · Refill-due list from buying behaviour, into existing call lists (P-46)

- **Area / kind:** Sales growth · finish / switch on / connect existing
- **Existing module + reuse:** `apps/followups/call_lists.py` (criteria → FollowUpTask, agent split), `apps/followups/services.py` (PurchaseHistory-based), consent `apps/customers/consent.py` (built 2026-11-15)
- **Current problem:** Call centre already does refill calls, choosing customers by hand. Behaviour finds 665 lapsed regular cash buyers (233k/month spend) and 249 delivery (90k) (05_PROPOSAL_BACKLOG.md Batch 6); the chronic label matches only 80 of 4,539 pairs.
- **Proposed solution:** New call-list criterion "regular buyer due/overdue" (same item ≥3× in 12 months, interval from own history); flagged categories go to pharmacist review; outcome = matched sale.
- **Benefit mechanism:** Recovered repeat purchases; agent time on the right customers.
- **Estimated hours:** 20 (interval calc, criterion, flagged-category routing, outcome metric, help, tests)
- **Required tests:** interval maths; placeholder/merged/closed PICs excluded; consent respected; branch scope
- **Measurability:** Direct: matched purchase within 14 days of call vs not-called control
- **Dependencies:** C09
- **Owner decision needed:** yes: flagged categories list + build go-ahead
- **Value 2.67 · Feasibility 3.75 · Score 10.0 · RoDT 5.0**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 4 | recovers lapsed repeat spend |
| Profit | 3 | ≈25% cash margin |
| Time saved | 4 | no manual selection |
| Waste reduction | 1 | none |
| Loss prevention | 1 | none |
| UX | 3 | same queue |
| Effort (5=least) | 4 | one criterion + matcher |
| Risk (5=least) | 4 | consent rule exists |
| Data readiness | 4 | PurchaseHistory class A for named customers |
| Confidence | 3 | Walgreens RCT effect modest |

### C09 · Schedule follow-up generation + auto-close, retire the May backlog

- **Area / kind:** Staff productivity · finish / switch on / connect existing
- **Existing module + reuse:** `apps/followups/services.py` `generate_followup_tasks_bulk` and `auto_close_followup_tasks_from_erp` (both now read PurchaseHistory); not in `apps/sync/tasks.py` scheduler (only `followup_reminders`)
- **Current problem:** 76,840 tasks all created May 2026; nothing generated or auto-closed since (05_PROPOSAL_BACKLOG.md Batch 6). Queues are stale, so agents ignore them.
- **Proposed solution:** Nightly job (with SCHEDULER_JOB_GUARDS + freshness domain); one command to close tasks whose refill date passed >60 days with a reason.
- **Benefit mechanism:** Live, trustworthy queue; prerequisite for C08/C10.
- **Estimated hours:** 6 (2 jobs, guard, freshness domain, backlog close command, tests)
- **Required tests:** job idempotent; dry-run count; closed tasks audited
- **Measurability:** Direct: open tasks age distribution
- **Dependencies:** none
- **Owner decision needed:** yes: approve closing the May backlog
- **Value 1.83 · Feasibility 4.00 · Score 7.3 · RoDT 12.2**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 2 | enables refill sales |
| Profit | 2 | indirect |
| Time saved | 3 | no hand-curated lists |
| Waste reduction | 1 | none |
| Loss prevention | 1 | none |
| UX | 2 | cleaner queue |
| Effort (5=least) | 5 | code exists |
| Risk (5=least) | 4 | volume spike risk; dry-run first |
| Data readiness | 4 | PurchaseHistory A |
| Confidence | 3 | chronic list narrow |

### C10 · Switch on WhatsApp refill reminders for consented customers

- **Area / kind:** Sales growth · finish / switch on / connect existing
- **Existing module + reuse:** `apps/followups/refill_reminders.py` (preview screen, caps, stop button), `REFILL_REMINDER_SEND_ENABLED` (off), consent chips on POS/customer page
- **Current problem:** Built and previewable; consent now exists, but no one is opted in yet and the switch is off.
- **Proposed solution:** Collect "yes" via consent chips for 2–4 weeks, then flip the switch for one branch.
- **Benefit mechanism:** Automated repeat purchase prompts with reservation reply buttons.
- **Estimated hours:** 4 (pilot checklist, verify preview, help update)
- **Required tests:** existing tests; pilot branch filter
- **Measurability:** Direct: reservations from reply buttons; matched sales
- **Dependencies:** C09, WhatsApp production channel
- **Owner decision needed:** yes: switch + template + channel
- **Value 2.50 · Feasibility 3.25 · Score 8.1 · RoDT 20.3**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 3 | repeat purchases |
| Profit | 3 | cash margin |
| Time saved | 4 | no manual messaging |
| Waste reduction | 1 | none |
| Loss prevention | 1 | none |
| UX | 3 | reply buttons |
| Effort (5=least) | 5 | switch |
| Risk (5=least) | 3 | customer-facing; template approval |
| Data readiness | 2 | opt-ins start at zero |
| Confidence | 3 | Kooy RCT: reminders alone may be null |

### C11 · Identified-sale rate on the brief and /me (P-37 surfacing)

- **Area / kind:** Sales growth · finish / switch on / connect existing
- **Existing module + reuse:** `apps/gamification/pic.py` (PIC-on-invoice rules), `apps/pic_analytics/queries/numbers.py`, `apps/personal` widgets
- **Current problem:** 55.9% of cash invoices go to anonymous walk-in accounts (05_PROPOSAL_BACKLOG.md Batch 4). The rate is computed for points but not shown where staff look daily.
- **Proposed solution:** Show yesterday's identified-sale % per branch/salesperson in the brief (C02) and a /me tile.
- **Benefit mechanism:** More named customers → refill lists, loyalty, missed-sale follow-up all work better.
- **Estimated hours:** 6 (widget + brief line + help + test)
- **Required tests:** same number as gamification for a fixture day
- **Measurability:** Direct: identified % trend
- **Dependencies:** C02
- **Owner decision needed:** no
- **Value 1.67 · Feasibility 4.50 · Score 7.5 · RoDT 12.5**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 2 | enables CRM |
| Profit | 2 | indirect |
| Time saved | 1 | none |
| Waste reduction | 1 | none |
| Loss prevention | 1 | none |
| UX | 3 | visible target |
| Effort (5=least) | 5 | numbers exist |
| Risk (5=least) | 5 | read-only |
| Data readiness | 5 | class A |
| Confidence | 3 | staff may skip when rushed (owner) |

### C12 · One-tap call reason + outcome (P-49)

- **Area / kind:** Staff productivity · finish / switch on / connect existing
- **Existing module + reuse:** `apps/callcenter/models.py` PURPOSE_CHOICES (9 values, default general), `CallCenterPage.jsx` purpose select (line ~2108)
- **Current problem:** 636 of 647 calls have purpose "general" (05_PROPOSAL_BACKLOG.md Batch 6): no data on why customers call.
- **Proposed solution:** Replace the select with 4 chips (order, availability, refill, complaint) + outcome chip; preselect from screen-pop context; "general" no longer default.
- **Benefit mechanism:** Knows availability-call volume (sizes C01/C06) and refill demand.
- **Estimated hours:** 6 (chips, outcome field (1 migration), analytics count, help, tests)
- **Required tests:** API rejects empty purpose for manual logs; PBX auto-logs keep a pending state
- **Measurability:** Direct: share of calls with a reason
- **Dependencies:** none
- **Owner decision needed:** no (4 reasons approved)
- **Value 1.50 · Feasibility 4.75 · Score 7.1 · RoDT 11.9**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none directly |
| Profit | 1 | none |
| Time saved | 2 | one tap |
| Waste reduction | 1 | none |
| Loss prevention | 1 | none |
| UX | 3 | chips beat a dropdown |
| Effort (5=least) | 5 | UI only |
| Risk (5=least) | 5 | no money |
| Data readiness | 5 | field exists |
| Confidence | 4 | simple |

### C13 · Stock-audit finding → task + targeted count (P-07)

- **Area / kind:** Loss prevention · finish / switch on / connect existing
- **Existing module + reuse:** `apps/stock_audit` (9 rules, statuses open/reviewed/dismissed/escalated), `apps/tasks`, `apps/stockcount`
- **Current problem:** 915 open findings with no owner or action (05_PROPOSAL_BACKLOG.md "later batches").
- **Proposed solution:** "Escalate" creates a branch task and a pre-filled count session for the flagged items; finding closes from the count result.
- **Benefit mechanism:** Shrink found and corrected; findings stop piling up.
- **Estimated hours:** 14 (escalate action, task link, count preset, close-from-count, help, tests)
- **Required tests:** escalation idempotent; branch scope; finding closes on count completion
- **Measurability:** Direct: open-finding age; variance found
- **Dependencies:** none
- **Owner decision needed:** yes: P-07 is not yet carded
- **Value 2.67 · Feasibility 4.00 · Score 10.7 · RoDT 7.6**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 2 | recovered shrink |
| Time saved | 3 | no re-keying |
| Waste reduction | 2 | some expired found |
| Loss prevention | 5 | core loss lever |
| UX | 3 | one button |
| Effort (5=least) | 4 | 3 apps exist |
| Risk (5=least) | 5 | no SOFTECH write |
| Data readiness | 4 | findings exist |
| Confidence | 3 | adoption |

### C14 · Count variance valued at cost + movement netting (P-08)

- **Area / kind:** Loss prevention · finish / switch on / connect existing
- **Existing module + reuse:** `apps/stockcount/engine.py` (`_variance_type`, `refresh_session_counts`)
- **Current problem:** Variances are quantities only and ignore sales between snapshot and count, so managers chase false shortages.
- **Proposed solution:** Value variance at cost_at_sale/current cost; net ledger movements after the snapshot.
- **Benefit mechanism:** Real shrink in EGP; fewer false alarms.
- **Estimated hours:** 14 (valuation + netting + tests + help)
- **Required tests:** netting on fixture ledger; valuation basis label
- **Measurability:** Direct: variance EGP per count
- **Dependencies:** none
- **Owner decision needed:** yes: P-08 not yet carded
- **Value 2.17 · Feasibility 3.50 · Score 7.6 · RoDT 5.4**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 2 | loss focus |
| Time saved | 3 | fewer recounts |
| Waste reduction | 1 | none |
| Loss prevention | 4 | accurate shrink |
| UX | 2 | one column |
| Effort (5=least) | 3 | ledger netting is fiddly |
| Risk (5=least) | 4 | read-only |
| Data readiness | 4 | ledger mirror A/B |
| Confidence | 3 | medium |

### C15 · AP exception review queue: bulk review + weekly finance digest

- **Area / kind:** Finance · finish / switch on / connect existing
- **Existing module + reuse:** `apps/finance/recon_anomalies.py` via `scan_ap_anomalies` (scheduled, `apps/sync/tasks.py:2495`) → ReconException (duplicate_invoice, overpayment, outliers); `frontend/src/pages/ReconciliationPage.jsx`
- **Current problem:** Handoff §11.2: 59 genuine native SOFTECH mis-links and 2,631 held matches await review; exceptions have no digest.
- **Proposed solution:** useGridKeyboard bulk confirm/dismiss with reason on the exception grid; Sunday digest to finance with new duplicate/overpayment rows and EGP.
- **Benefit mechanism:** Duplicate payments caught before cheques; reconciliation backlog cleared.
- **Estimated hours:** 10 (bulk endpoint, grid keyboard, digest, help, tests)
- **Required tests:** bulk action audited; finance-only permission; digest dedup
- **Measurability:** Direct: open exceptions and EGP resolved
- **Dependencies:** none
- **Owner decision needed:** no (finance time)
- **Value 2.83 · Feasibility 4.00 · Score 11.3 · RoDT 11.3**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 3 | recovered overpayments |
| Time saved | 4 | bulk review |
| Waste reduction | 1 | none |
| Loss prevention | 4 | duplicate payment control |
| UX | 4 | keyboard grid |
| Effort (5=least) | 4 | UI + digest |
| Risk (5=least) | 4 | no writer change |
| Data readiness | 5 | 97.8% shadow match |
| Confidence | 3 | size unknown |

### C16 · Show months-of-cover and the "buying despite cover" warning on the order export

- **Area / kind:** Procurement · finish / switch on / connect existing
- **Existing module + reuse:** P-31 rebuilt: `apps/procurement/receipt_check.py`, `/supply` «استلام بدون طلب»; pivot export in `apps/purchasing` (`PivotSheetSnapshot`)
- **Current problem:** Flag fires after receipt: measured ~25 lines/week, EGP 14,164 over 19–29 Oct (00_INDEX ledger, P-31). Cheaper to stop it on the order sheet.
- **Proposed solution:** Add network-cover months column and a ≥6-month warning colour on the pivot/order export and the shortage sheet.
- **Benefit mechanism:** Cash not spent on over-covered items.
- **Estimated hours:** 8 (export column, screen badge, help, golden-export test update)
- **Required tests:** golden export baseline updated; cover calc equals P-31 rule
- **Measurability:** Direct: P-31 flagged lines per week before/after
- **Dependencies:** none
- **Owner decision needed:** no
- **Value 2.33 · Feasibility 4.00 · Score 9.3 · RoDT 11.7**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 3 | cash kept |
| Time saved | 2 | small |
| Waste reduction | 3 | less future dead stock |
| Loss prevention | 2 | small |
| UX | 3 | visible in their sheet |
| Effort (5=least) | 4 | column + style |
| Risk (5=least) | 5 | advisory |
| Data readiness | 4 | same rule as P-31 |
| Confidence | 3 | buyers may still order |

### C17 · "Bought dearer while cheaper was available" monthly report

- **Area / kind:** Procurement · new (small, on existing data)
- **Existing module + reuse:** «يوجد أرخص» flags + supplier price comparison (/supply «مقارنة الموردين», `apps/procurement`), PurchaseLine cost history
- **Current problem:** Arbitrage sized ≈27K EGP/month (05_PROPOSAL_BACKLOG.md Batch 3; memory purchase_margin_leaks_sizing). Order-list split was rejected by the owner, so only visibility remains.
- **Proposed solution:** Read-only monthly report per buyer/supplier: lines bought above the cheapest recent supplier cost for the same item, with EGP difference.
- **Benefit mechanism:** Buyers shift volume; owner sees the gap.
- **Estimated hours:** 10 (query + export via core/export_safety + help + tests)
- **Required tests:** FOC lines excluded; VAT basis consistent; export safety
- **Measurability:** Direct: EGP gap per month
- **Dependencies:** none
- **Owner decision needed:** no (report only; respects rejected split)
- **Value 2.00 · Feasibility 4.00 · Score 8.0 · RoDT 8.0**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 4 | direct cost |
| Time saved | 2 | auto |
| Waste reduction | 1 | none |
| Loss prevention | 2 | small |
| UX | 2 | report |
| Effort (5=least) | 4 | data exists |
| Risk (5=least) | 5 | read-only; no split |
| Data readiness | 4 | cost formula verified |
| Confidence | 3 | bonus terms can justify dearer buys |

### C18 · Missing-bonus check at invoice receipt

- **Area / kind:** Procurement · new (small, on existing data)
- **Existing module + reuse:** `apps/invoices` OCR + `anomalies.py`, `apps/procurement` FOC lines (`pharmacydiscp=100`), «بونص زائد» flag
- **Current problem:** Owner: missing bonus happens "sometimes"; nothing compares received FOC with the last deal.
- **Proposed solution:** Flag doc-10 receipts whose FOC ratio is below the same supplier's last 3 deliveries of the item.
- **Benefit mechanism:** Claims the bonus before paying.
- **Estimated hours:** 16 (ratio history, flag, review list, help, tests)
- **Required tests:** ratio on fixtures; no flag when bonus deal changed
- **Measurability:** Expected: flagged EGP
- **Dependencies:** none
- **Owner decision needed:** yes: is history a fair proxy for the deal?
- **Value 2.00 · Feasibility 3.25 · Score 6.5 · RoDT 4.1**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 3 | bonus value |
| Time saved | 2 | auto |
| Waste reduction | 1 | none |
| Loss prevention | 3 | claim |
| UX | 2 | flag |
| Effort (5=least) | 3 | ratio logic |
| Risk (5=least) | 5 | read-only |
| Data readiness | 3 | agreed bonus not stored; history proxy |
| Confidence | 2 | frequency unknown |

### C19 · One margin basis + channel × branch board (P-35)

- **Area / kind:** Finance · finish / switch on / connect existing
- **Existing module + reuse:** `apps/analytics/views.py:314-1023` (profit = line_total − cost_at_sale × qty, margin by branch)
- **Current problem:** Sale price includes VAT, cost excludes it on 14% items, so margin is overstated; channel view not where the owner looks (05_PROPOSAL_BACKLOG.md Batch 4).
- **Proposed solution:** One helper for VAT-aligned margin used by analytics, LTV and dead-stock values; channel × branch grid incl. delivery fee contribution.
- **Benefit mechanism:** Right decisions on contracts/delivery/discounts.
- **Estimated hours:** 24 (helper, 4 call sites, board, 20-invoice check, help, tests)
- **Required tests:** margin helper on VAT and non-VAT fixtures; equal totals across screens
- **Measurability:** Direct
- **Dependencies:** finance VAT basis
- **Owner decision needed:** yes: VAT basis
- **Value 2.33 · Feasibility 3.25 · Score 7.6 · RoDT 3.2**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 4 | margin truth |
| Time saved | 3 | replaces SOFTECH reports |
| Waste reduction | 1 | none |
| Loss prevention | 2 | small |
| UX | 3 | one board |
| Effort (5=least) | 3 | touches many reads |
| Risk (5=least) | 4 | reporting only |
| Data readiness | 3 | VAT basis to confirm |
| Confidence | 3 | medium |

### C20 · Delivery small-order and fee-less invoice report

- **Area / kind:** Finance · new (small, on existing data)
- **Existing module + reuse:** `apps/delivery`, PurchaseHistory channel 90, D.L.V. item 2
- **Current problem:** 23% of delivery orders < EGP 100; 278 (8%) earned under EGP 10 gross margin; 1,099 fee-less invoices unexplained (05_PROPOSAL_BACKLOG.md Batch 4/6).
- **Proposed solution:** Weekly read-only list by branch: orders below rider cost, fee-less without a same/adjacent-day companion.
- **Benefit mechanism:** Owner can set a minimum-order rule with data.
- **Estimated hours:** 8 (report + export + help + test)
- **Required tests:** companion detection ±1 day; branch scope
- **Measurability:** Direct
- **Dependencies:** C19 helpful
- **Owner decision needed:** yes: any minimum-order rule is pricing (stop-and-ask)
- **Value 1.50 · Feasibility 4.00 · Score 6.0 · RoDT 7.5**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 2 | small money (≤14k fees/90d) |
| Time saved | 1 | none |
| Waste reduction | 1 | none |
| Loss prevention | 2 | small |
| UX | 2 | report |
| Effort (5=least) | 4 | query |
| Risk (5=least) | 5 | read-only |
| Data readiness | 4 | class A |
| Confidence | 3 | policy is owner's |

### C21 · Delivery stuck-order auto-close (P-48 part)

- **Area / kind:** Staff productivity · finish / switch on / connect existing
- **Existing module + reuse:** `apps/delivery/branch_watchdog.py`, CRM 5-minute sync (`sync_crm_orders`)
- **Current problem:** 258 orders stuck in ready/preparing; SLA fields never set (05_PROPOSAL_BACKLOG.md Batch 6).
- **Proposed solution:** Auto-close when the matching sale invoice exists; set sla_due_at; watchdog lists true exceptions only.
- **Benefit mechanism:** Clean board; real late orders visible.
- **Estimated hours:** 8 (matcher + job + tests + help)
- **Required tests:** close only on matched invoice; audit row
- **Measurability:** Direct: stuck count
- **Dependencies:** none
- **Owner decision needed:** no
- **Value 1.67 · Feasibility 4.00 · Score 6.7 · RoDT 8.3**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 1 | none |
| Time saved | 3 | no manual cleanup |
| Waste reduction | 1 | none |
| Loss prevention | 1 | none |
| UX | 3 | clean board |
| Effort (5=least) | 4 | small |
| Risk (5=least) | 5 | internal |
| Data readiness | 4 | mirror |
| Confidence | 3 | match key |

### C22 · Ride-level rider payout ledger (P-48)

- **Area / kind:** Finance · new (small, on existing data)
- **Existing module + reuse:** `apps/delivery` models (6 models, cash collection)
- **Current problem:** Riders are paid from branch cash at shift end; extras are not recorded anywhere we mirror (class C).
- **Proposed solution:** Cashier records rides + fee units + extras per shift; daily minimum applied; reconciles to D.L.V. units.
- **Benefit mechanism:** Visible delivery cost; fewer cash disputes.
- **Estimated hours:** 20 (model + form + reconciliation + help + tests)
- **Required tests:** minimum rule; reconcile to fee units
- **Measurability:** Direct after capture
- **Dependencies:** C19
- **Owner decision needed:** yes
- **Value 2.00 · Feasibility 3.00 · Score 6.0 · RoDT 3.0**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 2 | cost control |
| Time saved | 2 | replaces paper |
| Waste reduction | 1 | none |
| Loss prevention | 3 | cash leakage |
| UX | 3 | one form |
| Effort (5=least) | 3 | new capture |
| Risk (5=least) | 4 | cash handling, internal |
| Data readiness | 2 | class C |
| Confidence | 3 | adoption |

### C23 · Saved filters / default views per user on worklist screens

- **Area / kind:** Staff productivity · new (small, on existing data)
- **Existing module + reuse:** No saved-view model or hook today (grep: none). Reuse `MultiSelectFilter`, `BranchMultiSelect`, `useServerSort`
- **Current problem:** Buyers and store specialists rebuild the same branch/lane/supplier filters every visit on dead stock, purchasing, batches, supply.
- **Proposed solution:** `useSavedViews(screenKey)` + small per-user model: save, set default, share with role. Start with 5 heavy screens.
- **Benefit mechanism:** Seconds saved per visit × daily users; fewer wrong filters.
- **Estimated hours:** 16 (model, API with owner-only access, hook, 5 screens, help, tests)
- **Required tests:** user sees only own/role views; invalid filter keys ignored
- **Measurability:** Expected: views used (P-57 telemetry)
- **Dependencies:** none
- **Owner decision needed:** no
- **Value 2.17 · Feasibility 4.50 · Score 9.8 · RoDT 6.1**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 1 | none |
| Time saved | 4 | daily repeat work |
| Waste reduction | 1 | none |
| Loss prevention | 1 | none |
| UX | 5 | calm UI |
| Effort (5=least) | 4 | one hook + model |
| Risk (5=least) | 5 | no money |
| Data readiness | 5 | n/a |
| Confidence | 4 | common pattern |

### C24 · Bulk actions on the remaining worklists

- **Area / kind:** Staff productivity · finish / switch on / connect existing
- **Existing module + reuse:** `frontend/src/hooks/useGridKeyboard.js` (↑↓ Space Enter M Ctrl+A), dead-stock tab already bulk; return calendar, near-expiry rescue, stock-audit findings, transits are row-by-row
- **Current problem:** Row-by-row clicks on lists of hundreds of lines.
- **Proposed solution:** Bulk mark (sent to HQ / answered / reviewed / dismissed with reason) using the existing hook + one bulk endpoint per list.
- **Benefit mechanism:** Time saved; lists actually get worked.
- **Estimated hours:** 12 (4 bulk endpoints + UI + tests + help)
- **Required tests:** bulk audited per row; permission per row; partial failure reported
- **Measurability:** Expected: time per list
- **Dependencies:** none
- **Owner decision needed:** no
- **Value 2.33 · Feasibility 4.25 · Score 9.9 · RoDT 8.3**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 1 | none |
| Time saved | 4 | hundreds of clicks |
| Waste reduction | 2 | faster action |
| Loss prevention | 2 | faster review |
| UX | 4 | keyboard |
| Effort (5=least) | 4 | pattern exists |
| Risk (5=least) | 4 | audited bulk |
| Data readiness | 5 | n/a |
| Confidence | 4 | proven |

### C25 · Tiered-cover report under a cash budget (P-34, read-only)

- **Area / kind:** Procurement · new (small, on existing data)
- **Existing module + reuse:** `ItemDemandMetrics` (purchasing engine), spec `06_SPEC_P-34_tiered_cover_budget.md`, P-40 cash view new-purchases line
- **Current problem:** Fast items 0.57 months cover carry 85% of est. lost margin (69k/30d); slow items hold 2.39M (05_PROPOSAL_BACKLOG.md Batch 3).
- **Proposed solution:** Report: proposed cover per velocity tier, cash needed vs released, chronic never on-demand. No coverage write.
- **Benefit mechanism:** Same cash, fewer fast-item stock-outs.
- **Estimated hours:** 24 (tier calc, budget compare, screen, help, tests)
- **Required tests:** tier assignment; chronic excluded from on-demand
- **Measurability:** Expected → direct via C06 measurement
- **Dependencies:** C06 measure, C05 cash release
- **Owner decision needed:** yes: tier values
- **Value 2.67 · Feasibility 3.75 · Score 10.0 · RoDT 4.2**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 4 | fast-item availability |
| Profit | 4 | margin on fast items |
| Time saved | 2 | decision aid |
| Waste reduction | 3 | less slow overstock |
| Loss prevention | 1 | none |
| UX | 2 | report |
| Effort (5=least) | 3 | medium |
| Risk (5=least) | 5 | read-only |
| Data readiness | 4 | engine data |
| Confidence | 3 | tier values open |

### C26 · Make the bell useful: verify mark-read + "action items only" default

- **Area / kind:** Management · finish / switch on / connect existing
- **Existing module + reuse:** `apps/notifications` (mark-read APIs `views.py:285,316,458`), `NotificationBell.jsx`, P-55 routing
- **Current problem:** 0 of 758,692 notifications read (2026-11-08, doc 36): either unused or marking broken in live use.
- **Proposed solution:** Owner's one live click to test; then default filter = items needing action, rest in a digest.
- **Benefit mechanism:** Alerts get read; other wins (C02, C15) depend on attention.
- **Estimated hours:** 6 (diagnose + filter + help + test)
- **Required tests:** mark-read end-to-end; filter default
- **Measurability:** Direct: read rate
- **Dependencies:** owner live click
- **Owner decision needed:** yes (one click test)
- **Value 2.00 · Feasibility 4.50 · Score 9.0 · RoDT 15.0**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 1 | none |
| Time saved | 3 | less noise |
| Waste reduction | 1 | none |
| Loss prevention | 2 | missed alerts |
| UX | 4 | calm UI |
| Effort (5=least) | 5 | small |
| Risk (5=least) | 5 | no money |
| Data readiness | 5 | A |
| Confidence | 3 | cause unknown |

### C27 · POS search/discount-suggest debounce + cached reference reads (P-06)

- **Area / kind:** Sales growth · finish / switch on / connect existing
- **Existing module + reuse:** `frontend/src/hooks/usePosOrder.js:401-430`, `apps/catalog/pos_search.py`
- **Current problem:** Discount-suggest fires per keystroke/line; slows the counter once POS goes live.
- **Proposed solution:** Debounce + batch suggest; cache branches/settings reads. No change to discount calculation.
- **Benefit mechanism:** Faster counter; fewer abandoned sales in rush hours.
- **Estimated hours:** 8 (debounce, batch call, cache, tests)
- **Required tests:** same suggestion results; fewer requests
- **Measurability:** Direct: requests per order, p95 latency
- **Dependencies:** P-39 POS go-live for value
- **Owner decision needed:** no
- **Value 2.00 · Feasibility 4.00 · Score 8.0 · RoDT 10.0**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 2 | counter speed |
| Profit | 1 | none |
| Time saved | 3 | seconds per sale |
| Waste reduction | 1 | none |
| Loss prevention | 1 | none |
| UX | 4 | snappier |
| Effort (5=least) | 4 | frontend |
| Risk (5=least) | 4 | POS, not checkout |
| Data readiness | 5 | n/a |
| Confidence | 3 | value starts at POS go-live |

### C28 · Missed-sale suggestions from call-centre items not ordered

- **Area / kind:** Sales growth · finish / switch on / connect existing
- **Existing module + reuse:** `apps/pos_orders/missed_sales.py` (MISSED_SALES_ENABLED; source = POS selections only), callcenter call items
- **Current problem:** POS is not live, so the missed-sale engine has little input; the call centre does know the customer and the items asked for.
- **Proposed solution:** Add call items (no order within N days, customer real, no open reservation) as a second source into the same suggestion list.
- **Benefit mechanism:** Follow-up sales on items asked for by phone.
- **Estimated hours:** 12 (source adapter, idempotency key, help, tests)
- **Required tests:** dedupe with POS source; placeholder customers excluded
- **Measurability:** Direct: suggestions → reservations → sales
- **Dependencies:** C01, C12
- **Owner decision needed:** yes: owner said "our POS only" for the source
- **Value 2.00 · Feasibility 3.50 · Score 7.0 · RoDT 5.8**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 3 | recovered asks |
| Profit | 2 | margin |
| Time saved | 2 | auto list |
| Waste reduction | 1 | none |
| Loss prevention | 1 | none |
| UX | 3 | same list |
| Effort (5=least) | 4 | reuse engine |
| Risk (5=least) | 4 | internal |
| Data readiness | 3 | call items recorded only when agent adds |
| Confidence | 3 | adoption |

### C29 · Verified alternatives in the call centre when out of stock

- **Area / kind:** Sales growth · finish / switch on / connect existing
- **Existing module + reuse:** `apps/composition/alternatives.py` (approved molecule set only; pharmacist confirms), POS already shows it
- **Current problem:** Owner: alternatives are offered "sometimes"; agents have no approved list.
- **Proposed solution:** Show approved-only alternatives with network stock in the C01 drawer; label, never auto-substitute (Rule 5).
- **Benefit mechanism:** Keeps the customer when the item is short.
- **Estimated hours:** 6 (panel in drawer + help + tests)
- **Required tests:** only approved rows; unverified hidden; safety blocks respected
- **Measurability:** Direct: alternative chosen count
- **Dependencies:** C01
- **Owner decision needed:** no (P-47 approved showing approved alternatives)
- **Value 2.00 · Feasibility 3.25 · Score 6.5 · RoDT 10.8**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 3 | saves the sale |
| Profit | 2 | margin |
| Time saved | 2 | no lookup |
| Waste reduction | 1 | none |
| Loss prevention | 1 | none |
| UX | 3 | inline |
| Effort (5=least) | 5 | API exists |
| Risk (5=least) | 3 | clinical: pharmacist confirms |
| Data readiness | 2 | approved index coverage limited |
| Confidence | 3 | coverage |

### C30 · Phantom-substitution monthly review list

- **Area / kind:** Loss prevention · finish / switch on / connect existing
- **Existing module + reuse:** `apps/purchasing/phantom.py`, `/phantom-sales` (278 flagged; stock reduction dormant)
- **Current problem:** Detection exists; nobody is prompted to review new flags.
- **Proposed solution:** Monthly digest of new flags with EGP to the owner/supervisor; decision buttons on the screen. No stock reduction.
- **Benefit mechanism:** Contract buy-back resale abuse reviewed regularly.
- **Estimated hours:** 4 (digest + help + test)
- **Required tests:** only new flags; owner role only
- **Measurability:** Direct: flags reviewed
- **Dependencies:** none
- **Owner decision needed:** yes: reviewer
- **Value 2.00 · Feasibility 4.25 · Score 8.5 · RoDT 21.2**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 2 | small |
| Time saved | 2 | auto |
| Waste reduction | 1 | none |
| Loss prevention | 4 | abuse |
| UX | 2 | digest |
| Effort (5=least) | 5 | digest only |
| Risk (5=least) | 5 | read-only |
| Data readiness | 4 | built |
| Confidence | 3 | flag precision unknown |

### C31 · Fridge log + EDA visit checklist in QA (P-53)

- **Area / kind:** Loss prevention / compliance · new (small, on existing data)
- **Existing module + reuse:** `apps/qa` (QAChecklistTemplate, QAInspection; "fridge" yes/no only)
- **Current problem:** Owner: EDA always asks for the fridge log; visits ≈monthly at random. No readings recorded.
- **Proposed solution:** Twice-daily reading template (temp, min/max, initials), missed-reading alert, printable month sheet.
- **Benefit mechanism:** Inspection readiness; cold-chain stock not lost silently.
- **Estimated hours:** 16 (template, entry form, alert, print, help, tests)
- **Required tests:** missed-reading alert; branch scope
- **Measurability:** Direct: readings completeness
- **Dependencies:** none
- **Owner decision needed:** yes: checklist items, 2–8 °C range
- **Value 2.00 · Feasibility 3.75 · Score 7.5 · RoDT 4.7**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 1 | none |
| Profit | 1 | none |
| Time saved | 2 | replaces paper |
| Waste reduction | 2 | spoiled stock |
| Loss prevention | 3 | fines/stock loss |
| UX | 3 | one form |
| Effort (5=least) | 4 | small app |
| Risk (5=least) | 5 | internal |
| Data readiness | 2 | new capture |
| Confidence | 4 | clear need |

### C32 · Weekly HQ exception digest: money at stake + who acts

- **Area / kind:** Management · new (small, on existing data)
- **Existing module + reuse:** `apps/insights` rules + `apps/notifications` routing (P-55); inputs from batches return calendar, dead stock, stock_audit, ReconException, P-31 receipt check
- **Current problem:** 7.4k narrative findings already have no owner or action (05_PROPOSAL_BACKLOG.md "not worth building now"); each engine alerts separately.
- **Proposed solution:** One Sunday digest: top 10 items by EGP across engines, each with owner role and a link; nothing new computed.
- **Benefit mechanism:** Management attention on the biggest open money first.
- **Estimated hours:** 20 (5 adapters, ranking, digest, in-app page, help, tests)
- **Required tests:** each adapter returns EGP + link; no duplicates across engines
- **Measurability:** Expected: actioned share
- **Dependencies:** C26
- **Owner decision needed:** no
- **Value 3.50 · Feasibility 3.75 · Score 13.1 · RoDT 6.6**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 2 | indirect |
| Profit | 4 | prioritised cash |
| Time saved | 4 | one read |
| Waste reduction | 3 | expiry/dead stock |
| Loss prevention | 4 | audit/AP |
| UX | 4 | short |
| Effort (5=least) | 3 | aggregator over 5 engines |
| Risk (5=least) | 5 | read-only |
| Data readiness | 4 | existing outputs |
| Confidence | 3 | needs a reader |

### C33 · Reservation stock check on every line (not header item only)

- **Area / kind:** Sales growth · finish / switch on / connect existing
- **Existing module + reuse:** `apps/reservations` (03_DATA_OPPORTUNITY_MAP.md: "stock check uses the header item only")
- **Current problem:** Multi-item reservations show "available" when one line is short; customer arrives to a partial order.
- **Proposed solution:** Check each line against the sellable-stock rule (`catalog` one sellable rule, 2026-11-13); line-level badge.
- **Benefit mechanism:** Fewer failed pickups; trust.
- **Estimated hours:** 6 (line check + badge + tests)
- **Required tests:** mixed availability fixture
- **Measurability:** Direct: partial pickups
- **Dependencies:** none
- **Owner decision needed:** no
- **Value 1.67 · Feasibility 4.50 · Score 7.5 · RoDT 12.5**

| Dimension | Score | Reason |
|---|---|---|
| Revenue | 2 | fewer failed pickups |
| Profit | 1 | none |
| Time saved | 2 | fewer callbacks |
| Waste reduction | 1 | none |
| Loss prevention | 1 | none |
| UX | 3 | clear badge |
| Effort (5=least) | 5 | small |
| Risk (5=least) | 5 | internal |
| Data readiness | 5 | A |
| Confidence | 3 | verify current code first |

## 6. Area check: built / switched off / partial / missing

| Area | Opportunity | State in code | Evidence |
|---|---|---|---|
| Sales | Lost-sales capture | **Built, needs POS**: missed sales (`apps/pos_orders/missed_sales.py`, `MISSED_SALES_ENABLED` default False; ON in office per memory); demand capture in POS drawer | C01, C28 |
| Sales | Stock at other branch | **Built in POS only** (`StockLookupDrawer.jsx`, `PosResultRow.jsx` «فروع أخرى»); call centre one branch | C01 |
| Sales | Approved alternatives | **Built** (`apps/composition/alternatives.py`, approved-only) in POS | C29 |
| Sales | Refill reminders | **Built, switched off** (`REFILL_REMINDER_SEND_ENABLED`); generation **unscheduled**; consent **built** 2026-11-15 | C08–C10 |
| Sales | POS search speed | **Built** (pg_trgm, wildcard); P-06 debounce open | C27 |
| Inventory | Near-expiry | **Partial** (P-26 built; rescue tab; P-28 spec waiting) | C04 |
| Inventory | Dead stock | **Partial** (P-27 part A built read-only; part B waiting) | C05 |
| Inventory | Redistribution | **Built engines** (`transfer_engine.py`, توزيعة waves doc 30 B–D); P-30 list missing | C06 |
| Inventory | Return-to-supplier window | **Built** (P-29) for 2 suppliers | C03 |
| Procurement | Duplicate purchase invoice | **Built** (`apps/invoices/duplicates.py`, `scan_pending_duplicates`) | — |
| Procurement | Price variance | **Built** (stock_audit `price_variance_invoice`, `cost_fluctuation`) | — |
| Procurement | FOC validation | **Partial** («بونص زائد» over-bonus only) | C18 |
| Procurement | Cheaper supplier | **Built** («يوجد أرخص», supplier comparison); split rejected | C17 |
| Procurement | Buying despite cover | **Built after receipt** (P-31 rebuilt) | C16 |
| Finance | Duplicate payments | **Built, scheduled** (`scan_ap_anomalies`), review backlog | C15 |
| Finance | Unreconciled invoices | **Built** (A/P recon engine; writer gated) | C15 |
| Finance | Discount breaches | **Missing** (data present) | C07 |
| Finance | Negative margin | **Built** (stock_audit `sale_below_cost`, 915 open findings incl. other rules) | C13 |
| Finance | Cash view | **Built** (P-40/41/42) | — |
| Staff | Bulk actions / shortcuts | **Partial** (`useGridKeyboard`, Ctrl+K, multi-select filters) | C24 |
| Staff | Saved filters / defaults | **Missing** | C23 |
| Management | Exception digests | **Partial** (morning brief built, switched off, numbers not actions; P-55 transit digest) | C02, C32 |

## 7. Benchmarks (generic research; nothing about the company was sent)

| Source | Type | What it says | Fit for a 6-site Egyptian chain |
|---|---|---|---|
| Gruen, Corsten & Bharadwaj 2002 meta-analysis, cited in Corsten & Gruen (Springer chapter) — https://springerlink.bibliotecabuap.elogim.com/chapter/10.1007/978-3-030-20119-7_7 ; summary table in https://epub.uni-regensburg.de/21309/1/Diskussionsbeitrag_Stock-out__management.pdf | Verified research (grocery/FMCG, not pharmacy; full 2002 text not read) | On an out-of-stock about 31% switch store, 26% switch brand, 19% substitute same brand, 15% delay, 9% do not buy | Medium: supports offering another branch (C01) or an approved alternative (C29) at the moment of need. Not a pharmacy number; do not size money with it |
| Supplylogix Pinpoint Transfer — https://supplylogix.com/solutions/pinpoint-suite/pinpoint-transfer | Commercial feature (vendor claims, no data) | Demand-ranked inter-store redistribution to cut unsalable returns | High as a pattern (C05, C06); claims unverified |
| Pulse / iVend pharmacy pack — https://pulse.ivend.com/solutions/topic/drug-expiry-management/ ; ConnectPOS — https://www.connectpos.com/?p=107961 | Commercial feature | Batch days-to-expiry alerts, FEFO, transfer before write-off | High; we already have the batch truth (P-26) |
| commmerce.com blog — https://commmerce.com/blog/multi-store-pharma-inventory-sync-cut-medicine-expiry-loss-60-percent-india/ | Marketing claim (unsourced "8–12% of inventory value", "60% cut") | — | **Not used** for any number |
| Paladin POS Salesperson Exception Report — https://portal.paladinpos.com/knowledge-base/salesperson-exception-report-shows-manual-discounts/ ; NetSuite manager-approval threshold — https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_3904044606.html ; Minfos reportable discounts — https://help.minfos.com.au/support/solutions/articles/51000176162 | Commercial features | Per-cashier list of manual discounts/overrides; approval above a threshold | High: C07 is the report half; the approval half belongs to POS go-live (P-39) and is a pricing stop-and-ask |
| Corpay blog citing APQC — https://www.corpay.com/en-IE/resources/blog/duplicate-payment-detection | Secondary citation of a benchmark (vendor blog) | Duplicate/erroneous payments 0.8%–2% of disbursements (APQC, not read first-hand) | Low–medium: supports keeping C15 alive; our own ReconException count is the real baseline |
| Cegedim Pharmacy Manager (owings) — https://help.cegedim-healthcare.co.uk/PharmacyManager/15.1/Content/Whats_New.htm ; Cegedim blog — https://cegedimrx.co.uk/blog/revenue-recovery-how-community-pharmacies-can-overcome-loss-of-revenue ; P3 Pharmacy — https://www.p3pharmacy.co.uk/missed-sales | Commercial feature + vendor blog | Track "owed" items and frequently-owed lines; accounts record only completed sales, so unmet demand is invisible | High: same logic as demand capture (C01/C28) and P-47 |
| NHS SPS inventory guidance — https://sps.nhs.uk/articles/managing-medicines-inventory/ | Verified practice guidance (UK public body) | Flag medicines that must never be out of stock | Medium: supports "chronic never on-demand" in P-34 (C25) |
| El Ezaby app listing — https://apps.apple.com/us/app/elezaby/id1528993866 ; Egyptian Gazette — https://egyptian-gazette.com/technology/ezaby-new-app-to-provide-communication-tools/ | Commercial feature (Egypt; app-store claims) | Online availability check, delivery via hotline/WhatsApp; reviews complain items not stocked nearby cannot be ordered | High relevance: our call centre is the equivalent channel; C01 gives agents cross-branch availability without building an app (matches backlog "own app not now") |
| Cairo360 on EDA medicine-availability service — https://www.cairo360.com/?p=1806177 | Press report (Egypt) | Free EDA service tells where a medicine is available | Context: customers can already search across pharmacies, which raises the cost of "not here" |
| Walgreens late-to-refill RCT, PMC5338963 (already in `04_BENCHMARK_REGISTER.md`) | Verified RCT (chain-authored, 2017) | Refill within 14 days +6.09 points; PDC≥80% +0.97 points | High for C08; expect a modest effect and measure it |
| Kooy et al. RCT, PMC3665928 (already in register) | Verified RCT | Reminders alone: null overall | Caution for C10: pair reminders with a call/reservation path |

No credible numeric benchmark was found for Egyptian/MENA chains on expiry, dead stock or discount leakage; our own measured baselines in `05_PROPOSAL_BACKLOG.md` are the reference.

## 8. Owner decisions surfaced by this review (not decided here)

1. Supplier return windows for the next suppliers (C03).
2. Build go-ahead for P-28 (C04), P-27 part B (C05), P-34 report (C25); P-07/P-08 carding (C13, C14).
3. Decouple the P-30 daily list from the `newqty` gate (C06).
4. Close the May 2026 follow-up backlog (C09); flagged pharmacist categories for refill lists (C08).
5. Call-centre items as a missed-sale source (C28) — the earlier "our POS only" decision was about SOFTECH `pos_cancel` identity.
6. Finance: VAT margin basis (C19); 20-sample discount check (C07).
7. Pricing stop-and-ask, not proposed for build: branch/batch near-expiry markdown (P-16), minimum delivery order or fee (C20 gives data only).
