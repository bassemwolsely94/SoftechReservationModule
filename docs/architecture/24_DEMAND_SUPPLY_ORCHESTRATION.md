# 24 — Intelligent Demand, Allocation & Procurement Orchestration

**Status:** 🟡 DESIGN — discovery complete, awaiting owner review before implementation.
**Author:** discovery pass 2026-09-20.
**Golden rule for this module:** it is an **orchestration layer**, not a CRUD module. It
owns *decisions and provenance*, and **delegates every calculation, match, transfer, ISR
and SOFTECH write to the existing engines**. If this doc ever proposes recomputing demand,
surplus, FOC cost, or a catalog match itself, that is a bug in the design.

---

## 0. TL;DR

~85–90% of the requested capability already exists across `apps/shortage`,
`apps/purchasing`, `apps/procurement`, `apps/catalog`, `apps/vision`, `apps/transfers`,
`apps/reservations`, `apps/demand`, `apps/notifications`, `apps/audit`. What is genuinely
missing is a **thin unifying spine**:

1. A **provenance-aware demand ledger** (`DemandSignal`) that de-duplicates the same
   requirement arriving via WhatsApp / ISR / reservation / lost-sale, so demand is never
   double-counted.
2. A **supplier-availability inbox** (`AvailabilityBatch` / `AvailabilityLine`) — the
   supplier-PUSH counterpart to the branch-PULL `ShortageList`, reusing the *identical*
   extraction/OCR/matching pipeline.
3. A **sourcing/decision orchestrator** that, per residual gap, chains the existing engines
   into one explainable recommendation (need → internal allocation → residual → supplier
   comparison → historical deal) and one **quantity ledger** that never overloads `qty`.
4. A **case lifecycle** (`SupplyCase`) giving each unresolved shortage a durable daily
   follow-up state across days.
5. One **operational workspace** (extend `/supply`) tying it together, reusing existing
   React components.

Everything else = reuse or thin extension.

---

## 1. Discovery — what already exists (code-grounded)

### 1.1 Input / extraction / OCR (Flow A & B ingestion)
| Capability | Where | Notes |
|---|---|---|
| Bulk paste → lines, dedup, auto-match, confirm, learn | `apps/shortage/views.py` (`bulk_import`, `_import_lines`) | Branch-shortage today; the exact UX the inbox needs. |
| Multi-engine OCR (Gemini n-best + EasyOCR + Tesseract), parallel, best-of | `apps/vision/ocr.py` (`run_engines`, `pick_primary`, `build_consensus`) | Input-adapter already abstracted from downstream. |
| Image preprocessing (deskew/CLAHE/denoise/upscale) | `apps/shortage/preprocess.py` | Graceful degrade. |
| Voice transcript → items | `apps/shortage/views.py` (`voice_import`) | Web Speech API. |
| OCR learning corpus (source media + n-best + human confirmations) | `apps/vision/models.py` (`OcrSample`, `record_sample`, `add_confirmation`) | The owned dataset + flywheel feed. |
| Supplier-name → SOFTECH personcode resolution + alias flywheel | `apps/invoices/suppliers.py` (`resolve_supplier`, `get_or_create_vendor`, `main_personcodes`) | Curated top-10 distributors + learned `VendorProfile.aliases`. |

### 1.2 Catalog matching (the heart)
| Capability | Where |
|---|---|
| Confidence-scored fuzzy match (AR normalization, 4 phonetic maps, strength/form/scientific signals) | `apps/shortage/matching.py` (`find_best_matches`, `score_match`) |
| Alias flywheel (learned, vendor-scoped) | `matching.lookup_alias` / `learn_alias` + `catalog.ItemAlias` (`normalized`,`vendor_code`,`item`,`use_count`) |
| Component extraction (strength/form/qty) | `matching.extract_components` |
| Duplicate key (name+strength) | `matching.dedup_key` |
| False-match guards (non-drug, buried-substring, strength mismatch) | `matching.looks_non_drug`, `head_mismatch`; review threshold in `shortage/views._ocr_response` |
| Search index (pg_trgm, Arabic-folded) | `catalog.Item.search_name`, `apps/catalog/search_index.py` |

### 1.3 Demand / stock / gap (authoritative definitions — **single source of truth**)
| Concept | Authoritative definition | Where |
|---|---|---|
| Monthly consumption | weighted 30/90/365 blend (`monthly_avg`) | `purchasing.ItemDemandMetrics`, `EngineConfig` |
| Safety stock | tiered by `monthly_avg` × config | `EngineConfig.ss_*` |
| Target / coverage | `max(safety_floor, monthly_avg × coverage_months[ABC])` | `EngineConfig.coverage_months_*` |
| **Gap** | `target − current_stock − in_transit_qty` | `ItemDemandMetrics.gap` |
| In-transit netting (doccode 125, freshness-gated) | `in_transit_qty` | `EngineConfig.in_transit_max_age_days` |
| Priority | `(1 − coverage) × gap` | `ItemDemandMetrics.priority` |
| ABC | cumulative network value | `ItemDemandMetrics.abc_class` |
| Lost sales / stockout days / root cause | 30-day stockout estimation | `ItemDemandMetrics.lost_*`, `purchasing/lost_sales_engine.py` |
| Per-branch & network rollup | | `ItemDemandMetrics`, `ItemDemandAggregated` |

### 1.4 Internal surplus & allocation (usable-vs-surplus, multi-branch)
| Capability | Where |
|---|---|
| Deficit↔surplus greedy allocation, **surplus = stock − safety_stock** (never drops source below safety), priority-ordered, partial fills, snapshot per pair | `apps/purchasing/transfer_engine.py` → `TransferRecommendation(Run)` |
| Proactive distribution (dormant/over-piled/new/never-stocked) | `apps/purchasing/distribution.py` |
| Cross-branch on-shelf lookup (excludes quarantine 102/103/105) | `apps/shortage/stock_check.py`; `purchasing/shortage.branch_availability` |

### 1.5 Supplier sourcing, FOC & deal intelligence (Flow A economics)
| Capability | Where |
|---|---|
| Suppliers-per-item + last-bought supplier/cost/date (read-only SOFTECH) | `apps/shortage/supplier_sourcing.build_sourcing` |
| Purchase-line cache with **real FOC** (`bonus_qty`, `is_foc`), **tax-aware `effective_cost` = (net_value+vat)/(qty+bonus)** | `apps/procurement/models.PurchaseLine`, `procurement/engine.enrich_purchase_lines` |
| Per supplier×item price history (`min/max/avg/last_price`, `price_drift_pct`, `is_primary`) | `procurement.SupplierItemMapping` |
| Supplier scoring incl. FOC/tax/effective-cost, segmentation | `procurement.SupplierProfile`, `SupplierSegmentation`, `compute_enhanced_scores` |
| FOC-deterioration / price-spike / overpriced alerts | `procurement.ProcurementAlert`, `generate_advanced_alerts` |
| Supplier matrix export + single-supplier PO (their item codes) | `apps/shortage/export.py` |

### 1.6 Persistent shortage case + follow-up
| Capability | Where |
|---|---|
| Per-run shortage snapshot, delta view (new/recovering/re-entered), stockout-DAYS, recovery tracking, dedup'd notifications | `apps/purchasing/shortage.py` + `ShortageSnapshot`/`ShortageObservation` |
| Confirmed-shortage sticky flag + SOFTECH writeback | `catalog.Item.in_shortage`; market-shortage writeback (memory) |

### 1.7 Execution channels (never bypass)
| Channel | Where | Gate |
|---|---|---|
| Internal transfer request | `apps/transfers` (`TransferRequest` TR-xxx, `requesting_branch→supplying_branch`, `TransferRequestItem.quantity/approved_quantity/received_quantity`, status→`sent_to_erp`) | approval workflow |
| SOFTECH ISR (طلب توريد) writeback | `apps/purchasing/isr_writer.py` + `IsrPush` (proposed→approved→pushed, `stockisrm/stockisr`, `israpp=1`) | `ISR_WRITER_ENABLED` flag |
| SOFTECH indirect-POS pending order | `apps/pos_orders/writer.py` | built |
| Sales-rate writeback | `purchasing/rate_writer.py` + `SalesRatePush` | flag |
| Discount writeback (reference pattern) | `apps/discount_approvals/replication.py` | approval |

### 1.8 Provenance sources (customer demand)
| Source | Where | Signals |
|---|---|---|
| Reservation (customer waiting, downpayment, priority=chronic/urgent) | `apps/reservations` (`Reservation`, `ReservationLine`) | confirmed customer demand |
| Structured demand + lost sale (SLA, `whatsapp` source, statuses incl. `transfer_suggested`/`purchasing_flagged`) | `apps/demand` (`DemandRecord`) | already conceptually links transfer + purchasing |
| Branch shortage list | `apps/shortage` (`ShortageList`/`ShortageItem`) | branch pull |
| Market-shortage detector | `purchasing/shortage.py` | statistical unmet demand |

### 1.9 Cross-cutting
| Capability | Where |
|---|---|
| Notifications (roles/user, dedup_key, 5-min bucket) | `notifications.Notification.send_to_roles/send_to_user` |
| Audit | `apps/audit` (`AuditLog.log`) |
| RBAC (server-side, module×action) | `apps/users` (`seed_permissions`; purchasing/supervisor/admin roles) |
| SOFTECH connector | `config/sybase.py` (jConnect); read-only mirror by default |
| Reusable React | `AdvancedItemSearchModal`, `ItemSearchInput/Widget`, `MultiItemPicker`, `PrescriptionOcrModal`, `StockLookupDrawer`, `DataTable`; pages `/supply`, `/shortage`, `/market-shortage`, `/transfers`, `/procurement` |

---

## 2. Reuse matrix

| Required capability (prompt §) | Existing implementation | Reusable? | Modification | New? |
|---|---|---|---|---|
| Universal availability inbox — supplier PUSH (§2,3) | `ShortageList` UX pattern; `vision.run_engines`; `matching`; `suppliers.resolve_supplier` | Pattern yes | New sibling models (supplier-scoped, price/FOC fields) | **AvailabilityBatch/Line** (thin) |
| Bulk paste / multi-message / mixed AR-EN (§2,18) | `shortage.bulk_import`, `_import_lines`, `parse_quantity_from_text` | ✅ | Extract to shared `ingest` service | Shared adapter wrap |
| OCR of screenshots (§4) | `vision.ocr` + `preprocess` | ✅ Direct | — | — |
| Catalog matching + confidence + explanation (§5) | `matching.find_best_matches`/`score_match` | ✅ Direct | Return match-reason breakdown (already has signals; surface them) | Small: reason payload |
| Alias learning / supplier-specific terms (§29) | `ItemAlias` + `learn_alias` (vendor_code) | ✅ Direct | — | — |
| Post-match business picture (§6) | `ItemDemandMetrics`, `ItemStock`, `SupplierItemMapping`, reservations, `in_transit` | ✅ Read | One read-through "position" assembler | **PositionService** (read-only) |
| Demand quantity / gap (§7,19,20) | `ItemDemandMetrics.gap/target/priority` | ✅ Authoritative | — | Never recompute |
| Duplicate-demand prevention (§22) | none unified (separate silos) | ❌ | — | **DemandSignal ledger** |
| Demand provenance (§23) | scattered across apps | ❌ | — | **DemandSignal.source_*** |
| Internal surplus / usable-vs-surplus (§9) | `transfer_engine` (surplus=stock−safety) | ✅ Authoritative | Call on-demand for a scoped item set | Thin wrapper |
| Multi-branch allocation + explainable priority (§10) | `transfer_engine._match_all` + `priority` | ✅ | Expose per-decision explanation | Reason payload |
| Transfer + procurement one flow (§11) | `TransferRequest` + `IsrPush` + procurement | Channels exist | Orchestrate + link | **SupplyCase links** |
| Supplier comparison / effective cost (§12) | `PurchaseLine.effective_cost`, `SupplierItemMapping`, `build_sourcing` | ✅ Data | Rank-for-this-gap service | **SourcingService** (thin) |
| Historical deal intelligence (§13) | `SupplierItemMapping` history + FOC + `ProcurementAlert` | ✅ Data | "better prior deal" comparator | Thin comparator |
| Cash preservation math (§14) | metrics + effective_cost | ✅ | Present incremental cash | Presentation |
| Scarcity / opportunity queue (§15) | `market-shortage` tiers, stockout-days, reservations | ✅ signals | Compose scarcity score | Thin scorer |
| Daily follow-up lifecycle (§16) | `ShortageSnapshot`/`Observation` (item-level) | Partial | Case-level durable state | **SupplyCase** |
| WhatsApp-ready output (§17) | `shortage/export.py` (matrix, PO) | ✅ pattern | Add copy-to-WhatsApp text builder | Thin formatter |
| Exception-driven bulk review (§18) | `DataTable`, aggregate view | ✅ | New review grid | UI |
| Explainable recommendation (§19) | metrics carry all inputs | ✅ | Assemble explanation object | Reason payload |
| Reservations / customer demand (§21) | `Reservation`, `DemandRecord` | ✅ | Feed into `DemandSignal` | Wiring |
| Expiry / FEFO (§33) | `apps/batches` (StockExpiryBalance), quarantine excl. | ✅ | Read into position/allocation | Wiring |
| Supplier performance (§34) | `SupplierProfile`, `SupplierSegmentation` | ✅ Direct | — | — |
| Notifications (§26) | `Notification.send_to_roles` | ✅ Direct | — | — |
| Audit (§27) | `AuditLog.log` | ✅ Direct | — | — |
| RBAC (§39) | `seed_permissions` | ✅ | Add module perms | seed rows |
| SOFTECH writeback (§30) | `IsrPush`, `TransferRequest→ERP`, `discount_approvals` pattern | ✅ Only channels | Gate behind approval | No new write path |
| Concurrency / revalidation (§31) | fresh `ItemStock`; POS revalidate pattern | Pattern | Revalidate before commit | Thin guard |
| Idempotency / duplicate import (§32) | `dedup_key`, `client_token` (pos_orders) | Pattern | Batch fingerprint | Thin |
| AI degrade-gracefully (§28) | engines run without LLM; deterministic math | ✅ By design | — | — |

**Net-new code is small and mostly orchestration + provenance + one inbox.**

---

## 3. Proposed architecture

New app: **`apps/supply`** (orchestration spine). It **imports** the existing engines;
it does **not** re-implement them.

```
INPUT ADAPTERS (reuse)                CORE SPINE (apps/supply — new, thin)
  paste / OCR / voice / file  ─┐
  ISR / reservation / demand  ─┼─►  IngestService ──► DemandSignal (ledger, dedup+provenance)
  market-shortage detector    ─┘                         │  AvailabilityBatch/Line (supplier PUSH)
                                                          ▼
  matching.find_best_matches ──►  Resolution (confidence + explanation, learn_alias)
                                                          ▼
  ItemDemandMetrics (gap/target) ─►  PositionService (read-only assembler: stock, gap,
  ItemStock / batches / in_transit    reservations, incoming, days-cover, scarcity)
                                                          ▼
  transfer_engine (surplus)  ─────►  AllocationService (usable-vs-surplus, multi-branch,
                                       explainable) ──► proposed internal transfers
                                                          ▼  residual gap
  SupplierItemMapping + PurchaseLine  SourcingService (effective-cost rank + historical
  build_sourcing + effective_cost  ─►  deal comparator) ──► supplier options
                                                          ▼
                               RecommendationService (quantity ledger + reasons + cash)
                                                          ▼
                               SupplyCase (durable lifecycle, daily follow-up)
                                                          ▼   HUMAN REVIEW / APPROVAL / OVERRIDE
   EXECUTION (reuse, gated):  TransferRequest  |  IsrPush→SOFTECH  |  WhatsApp/Excel output
                                                          ▼
                               AUDIT (AuditLog) · NOTIFY (Notification) · LEARN (ItemAlias/OcrSample)
```

**Adapter principle (§35):** `IngestService.ingest(source_adapter, payload)` — WhatsApp
paste, OCR, file, or future automated webhook all produce the same normalized lines. The
procurement engine never sees "WhatsApp".

---

## 4. Proposed data model (new — deliberately thin)

Only entities that don't already exist, and none that duplicate authoritative calc.

1. **`DemandSignal`** — the provenance/dedup ledger (the key new idea).
   - `item` (FK, nullable pre-match), `raw_name`, `branch` (nullable = network), `qty`
   - `source_type` {reservation, demand_record, isr, shortage_list, availability_reply,
     market_shortage, manual}, `source_ref` (id), `customer` (nullable)
   - `dedup_group` (name+strength+branch key) — collapses the same requirement across sources
   - `status` {open, allocated, ordered, fulfilled, cancelled, superseded}
   - `consumed_by_case` (FK SupplyCase, nullable)
   - Rule: net demand for an item×branch = engine gap **reconciled against** open
     DemandSignals so ISR + WhatsApp + reservation for the same need ≠ sum.

2. **`AvailabilityBatch`** / **`AvailabilityLine`** — supplier PUSH inbox (sibling of
   `ShortageList`/`ShortageItem`, not a fork).
   - Batch: `supplier` (VendorProfile FK), `source` {whatsapp, image, excel, email, manual},
     `raw_content` (original text/file ref), `raw_fingerprint` (duplicate-import detection),
     `operator`, `status`, timestamps.
   - Line: `raw_text`, `item` (FK), `match_score`, `match_reason` (JSON), `is_confirmed`,
     plus **supplier economics**: `supplier_qty`, `price`, `discount`, `foc_qty`, `expiry`,
     `supplier_item_code`, `notes`. Missing values allowed (§4).
   - Reuses OcrSample banking + learn_alias exactly like shortage.

3. **`SupplyCase`** — durable per (item[, branch]) operational case (§16).
   - `status` {detected, searching, availability_found, awaiting_decision, allocated,
     ordered, partially_fulfilled, transfer_pending, received, fulfilled, closed}
   - links: `demand_signals` (M2M), `availability_lines` (M2M), `transfer_requests`
     (loose ref), `isr_pushes` (loose ref)
   - `first_detected`, `last_activity`, `days_open`, `scarcity_score`, `assigned_to`
   - Feeds the Daily Follow-up queue; retains state across days.

4. **`SourcingProposal`** / **`AllocationProposal`** (may be JSON snapshots on SupplyCase
   rather than tables — decide in Phase 3) carrying the **explicit quantity ledger** (§20):
   `supplier_offered, requested, calculated_demand, shortage, transferable_surplus,
   internally_allocated, residual_gap, proposed_purchase, approved_purchase,
   confirmed_supplier, received, unfulfilled` — never one generic `qty`.

**No new** item, stock, supplier, transfer, ISR, demand-metric, alias, or OCR-corpus tables.

---

## 5. Decision engine (centralized, deterministic, testable)

All rules live in `apps/supply/engine/` pure functions over authoritative inputs:

- **`net_demand(item, branch)`** = `ItemDemandMetrics.gap` reconciled with open
  `DemandSignal`s (dedup) + confirmed reservations not already in the run window.
  → returns the quantity ledger inputs + a reason list. *Deterministic.*
- **`internal_allocation(items, branches)`** = call `transfer_engine` matching scoped to the
  requested items; surplus = `stock − safety_stock`; explainable per-pair. *Reuse.*
- **`residual_gap`** = `net_demand − confirmed_incoming − internally_allocated`.
- **`supplier_options(item, residual, availability_lines)`**: rank by
  `effective_cost = (net_value + vat) / (qty + foc)` (reuse formula), annotate MOQ, expiry,
  supplier score, and **`better_prior_deal`** flag from `SupplierItemMapping` history.
- **`scarcity_score(item)`**: composite of zero-stock, reservations, stockout-days,
  historical scarcity, limited supplier qty — NOT raw sales volume (§15).
- **`recommend_purchase`**: quantity from `net_demand`, capped by cash/expiry/overstock
  guards; explanation object always attached (§19).

**LLM boundary (§28):** LLM only assists parsing/normalization/alias suggestion inside
`IngestService`. Every number above is deterministic; the module degrades gracefully with
no LLM (EasyOCR/Tesseract + fuzzy matching still work).

---

## 6. UX plan (extend, don't multiply screens)

Extend the existing **`/supply`** workspace into a tabbed Control Tower (reuse
`DataTable`, `AdvancedItemSearchModal`, `MultiItemPicker`, `PrescriptionOcrModal`,
`StockLookupDrawer`):

1. **Availability Inbox** — one paste/upload box → seconds-later review grid:
   `Item | Match(%+reason) | Supplier Qty | Need | Company Stock | Surplus Elsewhere |
   Residual Gap | Supplier Price/FOC | Priority | Recommendation`. Exception-driven:
   only uncertain matches / abnormal prices / unusual transfers flagged.
2. **Shortage Control Tower** — SupplyCase list, scarcity-sorted, daily follow-up, state chips.
3. **Allocation Planner** — reuse transfer-recommendation review; shows usable vs surplus.
4. **Supplier Comparison** — effective-cost table + historical-deal callout.
5. Sticky bulk actions; **Copy-to-WhatsApp** (one action) + Excel/PO export (reuse
   `shortage/export.py`).

Keyboard-first, RTL, semantic design tokens, no modal spam (per CLAUDE.md §11).

---

## 7. Phased implementation plan (each phase ships + tests + no regressions)

- **Phase 0 — Refactor to shared services (no behavior change). ✅ DONE (2026-09-20).**
  `apps/supply` created (registered). `apps/supply/ingest.py` = `parse_entry` /
  `resolve_line` / `teach_alias` (model-agnostic, thin wrapper over `shortage.matching`;
  thresholds `AUTO_MATCH_IMPORT=0.55`, `AUTO_MATCH_SINGLE=0.70`). `apps/supply/position.py`
  = `PositionService.for_items` (read-only assembler over `ItemDemandMetrics`, `ItemStock`
  excl. 102/103/105, open `Reservation`s). `apps/shortage/views.py` re-pointed
  (`_import_lines` + `add_item`) verbatim. Tests: `apps/tests/test_supply_ingest.py` (17)
  + 64 existing shortage/vision/catalog = **81 OK, no regression**. Known faithful quirk
  logged: bare trailing number read as qty ("Recormon 4000" → 4000) — Phase-2 target.
- **Phase 1 — DemandSignal ledger + provenance/dedup. ✅ DONE (2026-09-20).**
  `apps/supply/models.py` `DemandSignal` (mig 0001) — provenance + `unique(source_type,
  source_ref)` idempotency + `provenance_class` {customer_commitment / branch_replenishment
  / statistical} + status lifecycle. `reconcile.py`: customer=SUM, branch=MAX-per-branch
  (dedup echoes) then sum, statistical=indicator (not added); returns `deduped_total`,
  `raw_total`, `double_count_avoided`, and the full provenance list. `demand_signals.py`
  adapters (read-only, idempotent, close-stale): reservations (+ basket lines), DemandItem,
  shortage items, market-shortage → statistical; `sync_all` + `sync_demand_signals` command.
  Tests: `test_supply_demand_signals.py` (17) incl. the §22 end-to-end (two shortage lists ×
  qty 5 → branch_request **5**, not 10); **76 regression OK**, sources untouched. No SOFTECH writes.
- **Phase 2 — Availability Inbox (supplier PUSH). ✅ DONE (2026-09-21).**
  `AvailabilityBatch` / `AvailabilityLine` (mig 0002) — sibling of `ShortageList`, carrying
  supplier economics (price / discount / FOC / qty / expiry / supplier code, all optional).
  `availability.py`: deterministic economics parser (Arabic→Latin digits, FOC `N+M`,
  price/discount/expiry markers; all 5 prompt examples verified), `compute_fingerprint` +
  `find_duplicate_batch` (warn-not-block, §32), `ingest_batch`/`build_line` (reuse
  `ingest.resolve_line`), `confirm_line` (vendor-scoped `learn_alias`, §29),
  `resolve_batch_supplier` (reuse `invoices.suppliers`). `resolve_line` gained a
  backward-compatible `vendor_code` passthrough. DRF viewset `/api/supply/availability/`
  (paste create + `ocr` via `vision.run_engines` + `import-file` xlsx/csv + `add-line` +
  `lines/{id}/matches` + PATCH confirm + `check-duplicate`). Tests:
  `test_supply_availability.py` (19); **83 supply+regression OK**. No SOFTECH writes.
- **Phase 3 — Orchestrator + quantity ledger + explanations. ✅ DONE (2026-09-25).**
  `apps/supply/engine/` (pure read-only, no models): `net_demand` (required =
  **max**(engine gap, reconciled ledger) — max not sum, catches gap-0 scarce items with a
  waiting customer), `allocate_internal` (imports transfer_engine's `MIN_TRANSFER_QTY`,
  same surplus = stock − safety rule, richest-first), `supplier_options` (effective cost =
  price × qty / (qty + foc); live `AvailabilityLine` offers + `SupplierItemMapping`;
  `historical_best_deal` from `PurchaseLine.effective_cost`; better-deal flag at 2%),
  `recommend` (explicit quantity ledger §20 + scarcity + Arabic reasons §19). §11 worked
  example verified (15 → 6 internal → 9 external). Tests: `test_supply_engine.py` (11);
  **125 regression OK**. Known gaps: pending supplier POs not yet counted as incoming;
  MOQ / pack rounding deferred to order time.
  **Phase-3 bugfix (2026-09-26):** the engine gap is already net of in-transit
  (`gap = calc_gap(current_stock + in_transit, …)`), so `recommend` no longer subtracts
  incoming a second time; and ledger demand is now netted against stock + in-transit
  (`ledger_need`) so a reservation the shelf can already serve never triggers a purchase.
- **Phase 4 — SupplyCase lifecycle + Daily Follow-up + scarcity queue + notifications.
  ✅ DONE (2026-09-26).** `SupplyCase` (mig 0003) — one open case per (item, branch),
  enforced by two partial unique constraints (branch and network). Engine-driven statuses
  (detected / searching / availability_found / awaiting_decision) vs human statuses
  (transfer_pending / ordered / partially_fulfilled / received) that re-evaluation never
  overwrites; auto-close only when a real demand run shows net requirement 0. `cases.py`:
  `evaluate_case`, validated + row-locked `transition` (cancel requires a reason),
  `assign`, `sweep_cases`, follow-up `open_queue` buckets + `queue_summary`, and
  `notify_actionable` (urgent / availability-for-waiting-customers / overdue 3·7 days —
  once per case, capped, gated by `SUPPLY_CASE_NOTIFY`, default OFF). Every case event is
  written to `AuditLog` (4 new actions, audit mig 0003, choices only). Server-side RBAC
  (`permissions.CanOperateSupply`, purchasing view/edit via `can_do`) now guards both the
  case and the availability endpoints. API `/api/supply/cases/`; command
  `sweep_supply_cases`; scheduler job `supply_case_sweep` 08:00. Tests:
  `test_supply_cases.py` (24); **203 regression OK**. Case accuracy depends on the
  freshness of the latest demand run, which is triggered manually from `/purchasing`.
- **Phase 5 — Execution wiring. ✅ DONE (2026-09-27).** Owner decisions: an approved
  internal allocation creates **draft** `TransferRequest`s only (the transfers team submits
  and approves them in the normal flow); external purchasing produces a **WhatsApp / Excel
  order list** only — ISR generation stays OFF. `SupplyDecision` (mig 0004) records
  recommended vs decided vs outcome, the override reason, an idempotency key and receipt
  status. `engine/commitments.py` counts open undispatched transfer drafts (surplus
  reserved at the source, incoming at the destination) and open orders placed through this
  module, and `net_demand` nets them out so nothing is transferred or ordered twice.
  `execution.py`: `approve_internal_transfer` (per-item Postgres advisory lock, idempotency
  checked inside the lock, **live** revalidation, reason required to move more than
  recommended), `preview_order` / `commit_order` (all-or-nothing, reason required to buy
  more than the live need), `export_order_excel`, receipt settlement on case
  received/fulfilled/cancelled. Endpoints `cases/{id}/approve-transfer/`,
  `order-list/preview|commit|excel/`, `decisions/`. Tests `test_supply_execution.py` (20)
  including a real two-thread race, mutation-checked (without the lock the donor is
  over-drawn 10 > 7; with it, exactly 7). **265 regression OK.** Open item (needs owner
  go-ahead): SOFTECH `stkbal.onorderqty` is only mirrored where `nowqty > 0`, so supplier
  POs raised outside this module are not yet counted as incoming.
- **Phase 5 (original plan text) — Execution wiring (gated).** Generate `TransferRequest` and `IsrPush`
  (existing channels, existing gates) from approved recommendations; WhatsApp/Excel output;
  revalidation-before-commit + idempotency.
- **Phase 6 — Workspace UI. ✅ DONE (2026-09-27).** The existing `/supply` page gained two
  tabs (first in order; initial tab = `?tab=` → the user's last tab → inbox):
  **صندوق الإتاحة** (paste / screenshot / Excel → exception-driven review grid → select
  what is needed → order panel with copy / WhatsApp / Excel / record) and **متابعة
  النواقص** (bucket chips → prioritized queue → case panel with the quantity ledger,
  reasons, live transfer-draft status, approve-transfer, order, status moves, decision log).
  Files `frontend/src/pages/supply/*.jsx`; `supplyApi` extended; `WhatsAppShareButton`
  gained a `text` prop. Backend: `availability/{id}/analysis/`, `confirm-matches/`, case
  `transfer_requests` field. **Network-scope correction:** the engine's `total_gap` sums only
  positive branch gaps, so company-level (supplier-offer) recommendations now net out stock
  above target at other branches via `network_internal_cover` (authoritative gaps only).
  Verified on real dev data; fixed three issues found there (price-above-history flag on
  unpriced lines, fractional order quantities → whole units, confirm-button labelling) plus
  SOFTECH name spacing in the order text. Tests `test_supply_workspace.py` (13);
  **277 regression OK**; production build clean.
- **Phase 6 (original plan text) — Workspace UI** (`/supply` tabs) + exports.
- **Phase 7 — KPIs + validation on messy real lists. ✅ DONE (2026-09-28).**
  KPIs: `apps/supply/kpis.py` (each formula in `DEFINITIONS`; empty denominators → "—")
  served by the existing dashboard app at `GET /api/dashboard/supply/` (supply view RBAC) and
  shown as a section on `DashboardPage` — open queue, days to resolve (avg/median), internal
  vs external sourcing share, **cash avoided** (realized internal transfers × latest actual
  purchase cost), supplier fill rate, catalog-match precision / correction / auto / manual
  rates, override rate, committed value, FOC savings. Validation: probing the parser with
  real WhatsApp copies exposed serious failures (message dates read as expiry, FOC = strength,
  fabricated quantities, greetings as items); the supplier parser was rewritten as an ordered
  pipeline (header/noise stripping, explicit markers first, "a single bare number is the
  strength" safety rule, grams ≠ pounds) and now detects the WhatsApp sender as a supplier
  hint. A deterministic match-safety guard (`ingest.review_flags`: strength / form / head
  conflict, close rival brand) holds risky matches for review. Harness
  `manage.py validate_supply_matching` over a 37-case ground-truth corpus from the live
  catalog: **dangerous wrong-confident matches 6 → 0**, top-1 77.8 %, top-3 83.3 %, quantity
  extraction 100 %. **308 regression OK.** First real daily sweep (2026-09-28 08:00) opened
  537 cases — 503 network-level from market-shortage signals, 247 urgent — tuning pending.
- **Queue-scope tuning (owner decision 2026-09-28). ✅ APPLIED.** A company-wide
  (market-shortage) item opens a follow-up case only if a person confirmed it on
  «نواقص السوق» **or** its estimated lost sales ≥ `supply_network_case_min_lost_egp`
  (SystemSetting, default 2,000 EGP/month). Unconfirmed, lower-value items stay on the
  detector's watchlist; a branch/customer request still opens a branch case for any item.
  Urgency rule unchanged. Each daily sweep closes out-of-scope company-wide cases that are
  still in a system status (audited, reason «خارج نطاق المتابعة»; human-handled cases are
  never auto-closed); these closures are reported separately from "cancelled" in the KPIs.
  Dev result: 537 → 197 open cases, urgent 247 → 82. Tests `test_supply_scope.py` (7);
  **315 regression OK.**
- **Phase 7 (original plan text) — KPIs/dashboard** (reuse dashboard infra) + validation against messy real data.

**⚠ Stop-and-ask gates (per CLAUDE.md):** anything that (a) changes gap/surplus/FOC
calculation, (b) writes to SOFTECH (transfer→ERP, ISR push), or (c) could double-post.
These reuse existing gated channels only — no new write path is introduced by this module.

---

## 8. Open questions for the owner

1. Confirm **`DemandSignal`** as the single dedup ledger (vs. leaving silos and reconciling
   read-only). Recommended: build it — it's the core value of §22/§23.
2. Should the Availability Inbox live as new models, or as an extended `ShortageList` with a
   `direction` flag? Recommended: **separate sibling models** — supplier economics
   (price/FOC/expiry) don't belong on a branch shortage line.
3. Confirm we drive internal moves through **`TransferRequest`** and external supply through
   **`IsrPush`** (both existing) — no new execution channel.
4. Scarcity score weights + auto-match confidence thresholds: tune against real data in
   Phase 3 rather than hard-coding (§5 warns against arbitrary thresholds).
