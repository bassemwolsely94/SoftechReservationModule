# 09 — Top 30 quick wins and Top 10 best return on development time

Full audit, 2026-11-15. Extracted from [08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md](08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md) §3–§4; each candidate C01–C33 has a full card (problem, reuse paths, 10 scores with reasons, hours, tests, dependencies, owner decision) in §5 of that file. Money figures come only from `docs/product-review/` measurements; none are estimated here.

**Nothing here is authorised for build.** Pick from this list; each pick becomes its own batch.

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

