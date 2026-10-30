# 02 — Current-State Findings (incl. duplication & cross-module dependencies)

**As of 2026-10-30.** Evidence labels: **[M]** measured (read-only query on the office PG instance, 30-day window
2026-09-30 → 2026-10-29 unless stated) · **[C]** strongly supported by code (file:line) · **[H]** hypothesis needing
measurement. Office instance ≠ production (VPS cutover pending); staff may also work directly in SOFTECH.

---

## 1. The headline: wide build, thin adoption, open loops

1. **Breadth.** 62 functional apps, ~255k backend LOC, ~60 scheduled jobs. Engines and mirrors run reliably;
   the human workflow layer on top of them is barely used.
2. **Human-created workflow records are tiny [M]:** reservations 54 (none since 2026-07-01), demand records 3 (June),
   transfer requests 25, POS orders 58 (none since 2026-09-06), stock-count sessions 14 (none in 30d), tasks 1,
   approvals 3, vouchers 11, loyalty accounts 14, offers 1, QA inspections 0. Audited user actions in 30d come from
   **3 named users** (mostly owner/admin bulk operations).
3. **Engine output with no consumer [M]:**
   - TransferRecommendation 527,841 pending / 1 approved / 7 rejected (168k generated in 30d).
   - SupplyCase 745 → 11 fulfilled, 349 cancelled.
   - StockAuditFinding 915, all `open`.
   - InsightFinding 7,413, no status field at all [C].
   - `forecast_30d/90d` written nightly, read by nothing [C].
4. **Outcomes are self-reported or unmeasured [C].**
   - "Recovered" demand and "fulfilled" reservations are clicked by staff. Recovered revenue defaults to the
     estimated line value (`demand/service.py:562-570`).
   - The only sale-matching auto-close (follow-ups) reads the `erp` mirror. **That mirror's last data is 2026-04-30 [M]**
     and its sync is unscheduled, so the loop is dead.
   - No module checks whether a rebalance transfer cleared at-risk stock, whether a markdown sold through, or whether
     a "done" disposal matches a SOFTECH movement.

> **Owner correction (2026-10-30):** the system **has not gone live yet** ("we are so close now"). The tiny
> workflow counts (reservations, demand, POS orders, tasks) reflect **pre-launch testing, not rejected adoption**.
> They remain a useful baseline. Usage will be measured properly after cutover.

**Implication for this review:** the highest-value work is mostly **finishing, connecting, simplifying and measuring**
what exists, not adding capabilities. Every new capability proposal must name the queue owner and the outcome measure.

## 2. Notification overload [M]

- 1.69M notifications stored, no retention job [C].
- **399,018 created in 30d for 90 recipients.** Two users each received ~31k (~1,000/day).
- By type: `transit_critical` 334,333 (84%), `transit_overdue` 36,953, `transit_approaching_cancel` 12,627,
  `transfer_request` 7,003, `delivery_sla_alert` 3,552, `branch_connectivity` 2,308.
- **No notification created in the last 30 days has been marked read**; the last read flag is 2026-10-19.
- Effect: real alerts (demand SLA, a stock-out on a reserved item) are buried. Staff have rationally stopped reading.

## 3. Cross-module workflows as built

### 3.1 Customer demand → availability → transfer/purchase → fulfilment → sale
- **Capture** has four unlinked doors: reservation, demand record, branch shortage list or pasted WhatsApp branch
  request, and the omni/WhatsApp inbox (which has no capture action) [C].
  - The call centre can convert a call to a reservation or transfer, but **not to a demand record**
    (`callcenter/models.py:800`).
- **Availability** has three stock sources: live `stkbal` (engine, ISR, invoice grid), the `ItemStock` mirror
  (POS, shortage, supply), and transits [C].
- **Decision** has about six overlapping planners: DemandEngine, AdvancedEngine, the SOFTECH-rule ISR, the greedy
  TransferEngine, L3 distribution, and the ISR fulfilment donor plan. None has a stated authority [C].
- **Execution splits three ways:**
  - (a) DRAFT TransferRequest → staff key it into SOFTECH → type the doc number back → transits links by docnumber only.
  - (b) ISR push writes SOFTECH `stockisr` directly, bypassing TransferRequest.
  - (c) External purchase leaves as WhatsApp text/Excel. **No PurchaseOrder is created**, so invoice PO-matching has
    nothing to match.
- **Customer notified** by wa.me click or phone. Auto-WhatsApp is OFF.
- **Sale** happens in SOFTECH.
- **Outcome** is not matched automatically anywhere (§1.4).

### 3.2 Expiry & waste: detect → act → outcome
- **Detect (strong):** the `stkbalexpiry` mirror, the purchase-expiry audit, weekly worklists, insights.
- **Four expiry sources** exist, one of them dead (`StockBatch`/FEFO; `near_expiry_scan` scans an empty table) [C].
- **Act:**
  - Rebalance → DRAFT transfer.
  - Markdown → OFF by default and **chain-wide** `special_discp`, not branch- or batch-scoped [C].
  - Disposal record → never reconciled to SOFTECH doc 120/150.
- **Outcome:** no realised write-off KPI and no sell-through tracking.

### 3.3 Stock accuracy & shrinkage
- stock_audit rules (live since 2026-10-26) plus stockcount variance.
- "Escalate" creates no task or notification [C].
- Count variance has **no money value**, and does not net out sales or transfers after the snapshot, so busy branches
  show false variances [C].

### 3.4 Sale → margin → retention
- POS orders store COGS per line, but no report reads it [C].
- Margin is not used in:
  - customer LTV (revenue only);
  - discount impact (quantity and revenue only);
  - recommendation ranking (VIP boost **by price**, `basket_intelligence.py:91`);
  - referral and doctor stats.
- The `analytics` "capital tied in inventory" metric is valued at **selling price** (`analytics/views.py:1958`).
- Six discount-granting paths each have their own guard, with **no single order-level discount-vs-margin-floor
  check** [C].
- Loyalty runs two ledgers (SOFTECH `picpoints` vs Django). The customer portal shows the Django one [C].

## 4. Pharmacy safety & compliance findings

| # | Finding | Evidence | Label |
|---|---|---|---|
| S1 | POS basket suggestions ignore the customer's allergies/interactions; another recommendation path applies them | `recommendations/basket_intelligence.py:87` uses only item-level `blocks_sale`; `engine.py:386` has `_get_unsafe_items_for_customer` | C (verified) |
| S2 | Offers targeting has no Rx/medicine-class exclusion (buy-X-get-Y on prescription medicines possible) | `offers/targeting.py:181` | C |
| S3 | Incentive rules can pay on any item, including Rx/antibiotics, and allow supplier-sponsored programmes; no exclusion field | `incentives/models.py:41-46,75-231` | C |
| S4 | AI enrichment auto-approves suggestions ≥0.90 confidence **including clinical fields** (indication, rx_otc, contraindications…) | `enrichment/suggestion_generator.py:305-319`; 78 `indication_en` + 11 `rx_otc` approved [M] | C+M |
| S5 | Interaction/contraindication base (40 + 35 rows) has a source field but no reviewer/review date; not used at POS | `chronic/models.py:459-520` | C |
| S6 | Gamification awards points for gross profit (cash ×1.5) and none for counselling, safety or training | `gamification/defaults.py:11-21` | C |
| S7 | **No customer-level marketing consent**; campaign audience ignores refill/demand opt-outs and closed/deceased accounts; campaigns can target by chronic condition (health data) | `campaigns/views.py:122-160`; grep for consent finds nothing | C |
| S8 | Refill reminders are triggered by purchase cadence alone, with no pharmacist review (sending is OFF today) | `followups/refill_reminders.py` | C |

Rule 4 (safety beats sales) is honoured at the item level (`catalog/safety.py`) but **not at the customer level or in
the commercial engines.** These are prerequisites before turning on offers execution, campaigns or refill sends.

## 5. Technical performance (staff-facing)

| Finding | Where | Label |
|---|---|---|
| Live Sybase reads inside HTTP requests (node outage = blocked screen, latency) | pos_orders discount-suggest (≈1–2 queries per item, **no debounce**, `usePosOrder.js:401-430`), stock check (2/item), batches expiry candidates (serial per-branch loop), stockcount snapshot, transfers validate-erp-ref, invoices grid, insurance discover, incentives calculation, shortage exports, delivery item detail | C |
| Offers evaluation N+1 (~5 queries per active offer per basket edit) | `offers/engine.py:101-118` | C |
| Full 130k-row `ItemStock` upsert every 5 min regardless of change (WAL/bloat) | `sync/tasks.py:888-955` | C |
| Manual "trigger sync" runs in a web thread and can overlap scheduled lanes | `sync/views.py:74,91` | C |
| No retry/alerting on repeated job failure; freshness tracked for 9 domains only | `sync/tasks.py`, `freshness.py` | C |
| Synchronous heavy work in requests: insights generate, `discount_impact` (unbounded loop), analytics (48 aggregates, no rollup), advanced export, invoice push-batch, rate-push execute | various | C |
| Table growth with no retention: notifications 1.69M, NotificationLog 1.67M, ItemDemandMetrics 3.27M, TransferRecommendation 528k, PBXEvent 218k | [M] | M |
| Actual page/API latency | not measured (no APM, no request timing in logs reviewed) | H — needs instrumentation |

## 6. Staff productivity (separate from technical speed)
- **Double entry:** transfers (app + SOFTECH + typed doc number), count adjustments (Excel → SOFTECH), disposals
  (Excel → SOFTECH), external payments, cheques, voucher discounts, supplier orders (WhatsApp/Excel, no PO).
- **Dead ends:** shortage stock-check has no "create transfer"; the omni inbox has no "capture demand"; stock-audit
  escalation does nothing; insight findings cannot be acknowledged.
- **Hidden help:** the POS suggestions/offers panel is collapsed by default (`POSOrderPage.jsx:733`).
- **Unscheduled maintenance:** task schedules never fire (`tasks/scheduler.py:74` has no caller); the shortage-flag
  retry, follow-up generation/auto-close, abuse detection and the FBT miner are manual only.
- **Adoption blocker (owner decision, not a defect):** `POS_WRITER_ENABLED=False` means the POS cannot be used for
  real orders.

## 7. Duplication & dependency map (supersedes nothing; extends `08_DUPLICATION_REPORT.md`)

| Area | Parallel implementations | Recommended authority (provisional) |
|---|---|---|
| Demand intake | Reservation · DemandRecord · ShortageList · WhatsApp branch request · supply DemandSignal (projection) | DemandRecord = intake; Reservation = "commitment" stage; DemandSignal = read model |
| Replenishment/allocation | DemandEngine · AdvancedEngine · SOFTECH-rule ISR · TransferEngine · L3 distribution · ISR fulfilment · shortage stock-check | Owner to name one per decision (buy vs move) |
| Stock truth | live `stkbal` · `ItemStock` mirror · `StockExpiryBalance` | Mirror for screens (with a freshness badge); live only at commit |
| Expiry truth | StockBatch (dead) · PurchaseExpiryEntry · StockExpiryBalance · ItemDemandMetrics risk value | StockExpiryBalance |
| Supplier↔item mapping | procurement.SupplierItemMapping · invoices.VendorItemMapping · catalog.ItemSupplierLink · live `itemssuppliers` | catalog.ItemSupplierLink + learned aliases |
| Discounts | posdiscp approvals · contract discounts · offers · vouchers · gift coupons · loyalty redemptions | One order-level margin-floor check over all paths |
| Points/loyalty | SOFTECH picpoints · Django LoyaltyAccount · referral rewards · gamification (staff) | SOFTECH for customers |
| Customer scoring | segmentation · followups · campaigns · insights · analytics | customers segmentation |
| Recommendations | basket_intelligence · recommendations engine · product_experience · composition alternatives | basket_intelligence (+ safety filter) |
| Approvals | approvals engine · discount_approvals · replacement workflow | approvals engine over time |
| Tasks/queues | tasks · followups tasks · DemandFollowUp · callcenter cases · approvals inbox | Owner decision (Batch 5/6) |
| Inbox | omni inbox · /whatsapp/inbox | omni |
| Audit-type rules | stock_audit · insights (below-cost, variance, high discount) | stock_audit for transactions; insights narrates |
| Sales mirrors | customers.PurchaseHistory (live to 2026-10-27) · erp.ERPTransaction (stale since 2026-04-30) | PurchaseHistory; retire `erp` |

## 8. Open evidence gaps (smallest validation step)
1. **Real usage per screen.** No page-view telemetry exists. → Add lightweight screen-view events before cutover
   (proposal P-04).
2. **Whether staff work around the app in SOFTECH/WhatsApp.** → Interview 3 branch managers plus the call-centre lead
   (30 min each). Cross-check SOFTECH doc counts against app records, e.g. 125 transfers vs TransferRequest.
3. **Production `.env` writer flags.** The office `.env` turns ISR/rate/coverage/invoice writers ON while settings
   default OFF. → Confirm the intended production state at cutover (single-writer rule).
4. **Margin basis (VAT-inclusive price vs ex-VAT cost)** in offers and analytics. → Reuse the verified formula
   (memory: purchasing OCR column engine) and confirm with finance.
5. **Notification read tracking.** 0% read could be a UI path that doesn't set `is_read`. → Check the bell/mark-read
   API before redesigning.
6. **PDPL deadline and obligations** (see the benchmark register). → Legal confirmation.
7. **EDA track-and-trace pharmacy obligations (Decree 475/2025, guideline 804/2025).** → Read the guideline;
   confirm how SOFTECH will handle it.
