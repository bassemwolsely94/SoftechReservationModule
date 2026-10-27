# Implementation Plan — ElRezeiky Commerce OS

> **Prompt B output.** Planning only — no code changed. Derived from
> `CLAUDE.md` and `docs/CURRENT_STATE_AND_GAPS.md`. Each phase is delivered in a
> fresh Claude Code session, in order, and is not started until the previous
> phase is merged and sanity-checked in the real POS.
>
> **Ordering principle:** highest ROI / lowest risk first *within* each phase.
> Because the audit found most capability already exists, most work is
> **"surface & stitch" existing apps**, not new domains. The two hard, new,
> money-critical items — the **Offers engine (Phase 3)** and **stock-reservation
> concurrency (Phase 4)** — are called out for extra testing and a stop-and-ask
> gate before merge.
>
> **Legend.** Complexity: **S** (≤1 batch) · **M** (2–3) · **L** (4–6) · **XL**
> (7+). Risk: **Low / Med / High**. SOFTECH dependency: **None** (PG-only) /
> **Read** (live branch read) / **Write** (posts via an established methodology —
> triggers the stop-and-ask gate).

---

## Phase 1 — POS speed & UX foundation

*Composition over existing catalog/search infra + two genuinely new pieces
(command palette, theme). Low SOFTECH risk, high daily value. Do this first.*

| Feature | Backend work | Frontend work | Database changes | SOFTECH dep | Risk | Tests required | Complexity | Depends on |
|---|---|---|---|---|---|---|---|---|
| Theme (light/dark/system) | — | Design-token layer over brand palette; `useTheme`, `data-theme`, `prefers-color-scheme`; migrate POS surfaces | None | None | Low | Snapshot/visual; token contrast | M | — |
| Command palette (Ctrl+K) + shortcut registry | Search endpoint reuse | `cmdk`-style palette; central shortcut registry replacing scattered Ctrl+F keys | None | None | Low | Keyboard nav; action dispatch | M | Universal search |
| Product-intelligence overlay | Extend `catalog.Item` (`search_name`, `tags`, explicit `safety_flags`); backfill command | Show on product card | Add fields + GIN/`pg_trgm` index (additive, no write-back) | None | Low | Migration; backfill; index | M | — |
| Categorization + subcategories/tags | Subcategory hierarchy + tag model on `catalog` | Tag/subcat filters | Additive tables/FK | None | Low | Model + filter | S | Product intel |
| Universal search (unified) | One `catalog/search.py` service + `GET /api/search/universal` fanning item/customer/order/reservation; **no fuzzy on safety fields** | One POS search box + result grouping | Indexes only | Read (optional) | Med | Precision on codes/barcodes; **safety no-fuzzy**; perf | L | Product intel |
| Product cards (image/stock/offer/safety) | Compose `Item`+`ItemStock`+images+safety | Card component w/ live branch stock + badges | None | Read (stock) | Low | Render + stock accuracy | M | Product intel, images |
| Product images on POS | Reuse `apps/images` | Wire onto card | None | None | Low | Fallback/missing image | S | Product cards |
| Quick Sell / favorites / recently-used | Per-branch top-sellers + recently-used from `PurchaseHistory`/`ItemDemandStat` | Server-backed quick grid (keep localStorage favs) | None (read) | None | Low | Ranking; per-branch scoping | M | — |
| Smart barcode mode | Multi-barcode resolve (`ItemBarcode`) | Scan→identify→add, scanner focus, minimal interruption | None | None | Low | Scan resolve; ambiguity | S | Product cards |
| Smart defaults / progressive entry | Extend `reference-data` defaults | Hide-irrelevant / don't-re-ask field logic | None | Read | Low | Field-visibility per channel | M | — |
| Multiple carts + hold/resume | Persist parked carts (extend `SoftechSalesOrder` draft or a light park table) | Cart switcher + hold/resume | Additive (park state) | None | Med | Concurrency of parked carts; no double-submit | M | — |
| One-click contextual actions | Reuse existing endpoints | Action menus on product/customer/order | None | None | Low | Action routing | S | — |
| Add `pos` to RBAC | Add `pos` to `MODULE_CHOICES`; route `CanOperate/PushPosOrders` through `RoleModuleAccess`; seed grants | Permission-gated POS controls | Seed row(s) | None | Med | Server-side authz; deny-by-default | S | — |

**Phase-1 exit:** POS is faster and calmer (rule 11); no offers/loyalty/discount-
posting or checkout/payment logic touched.

---

## Phase 2 — Customer & sales intelligence

*Service-layer orchestration over an already-rich customer data layer (§1.3).
Recommendation must never obscure a safety flag (rule 4).*

| Feature | Backend work | Frontend work | Database changes | SOFTECH dep | Risk | Tests required | Complexity | Depends on |
|---|---|---|---|---|---|---|---|---|
| Customer recognition by phone + dup detection | Recognize-on-type endpoint over indexed `phone`/`whatsapp_phone`; duplicate surfacing | Live recognition in POS customer field | None | None | Low | Match precision; dup grouping | M | P1 search |
| Customer 360 side-drawer | Compose `Customer`+segment/churn/LTV+`CustomerHealthProfile`+`PurchaseHistory`+reservations+delivery+loyalty | Slide-over drawer that doesn't abandon basket | None (read) | None | Low | Aggregation correctness; perf | M | Recognition |
| Repeat order (re-validating) | `RepeatOrderService`: revalidate stock/price/offer/discount/status before rebuild — never blind-copy | "Reorder" action | None | Read | Med | Revalidation matrix (price/stock/status drift) | M | Customer 360 |
| Smart basket display | Compose line + discount + savings + stock/safety + loyalty | Clean basket, contextual secondary info | None | Read | Low | Render; safety visibility | M | P1 cards |
| Basket intelligence service | `BasketIntelligenceService` over `recommendations.FrequentlyBoughtTogether`/`CustomerRecommendation` + `ProductBundle` + refill signals; ranked, high-value only | Contextual (non-modal) suggestions | Cache table (rebuildable) optional | None | Med | Ranking; **never override safety**; latency | L | Customer 360, smart basket |
| Sales Opportunity Engine (backend) | Server-side deterministic ranking over basket+customer+product+stock+history (rule 7/10) | Render ranked opportunities | Optional cache | None | Med | Determinism; ranking snapshot | L | Basket intel |
| Customer segmentation (configurable) | Formalize rules over existing `segment_customers` | Segment views/filters | Config table optional | None | Low | Rule application | S | — |
| Digital receipts + reorder | `ReceiptService` (print/WhatsApp/email-SMS stubs); buy-again revalidates | Receipt actions + buy-again | None | Read | Low | Channel stubs; revalidation | M | Repeat order |

**Phase-2 exit:** intelligence is server-owned and ranked; safety flags always win.

---

## Phase 3 — Offers & loyalty  ⚠ MONEY — highest care level

*The one high-risk, partially-greenfield domain. **Every batch needs money-math
tests before it is considered done.** Stop-and-ask before merging anything that
changes how a discount is posted to SOFTECH (rules 1–3).*

| Feature | Backend work | Frontend work | Database changes | SOFTECH dep | Risk | Tests required | Complexity | Depends on |
|---|---|---|---|---|---|---|---|---|
| Offer model + types | New `apps/offers`: `Offer` (pct/fixed/BXGY/BXSY/bundle/mix&match/qty-tier/brand-mfr-cat/segment/branch scope, date-time windows, clearance, loyalty), `OfferRule`, usage limits, stackability, approval flag, status, audit history | Offer admin CRUD | New tables (money) | None (definition) | Med | Schema + eligibility unit tests | L | P1 catalog tags, P2 |
| Automatic offer evaluation | Evaluate on basket change; compute discount deterministically | "Offer Applied — Save EGP X" (no cashier recall) | — | None (calc) | High | **Money-math per offer type**; boundary/qty tiers | L | Offer model |
| Bundle completion | Reuse `catalog.ProductBundle`; "Complete the Bundle" | Bundle suggestion | — | None | Med | Completion logic | M | Auto-eval |
| Offer conflict resolution | Explicit rule engine (stackable/non-stackable, priority, best-customer-saving, margin restriction); **store selected/rejected reason** | Show applied + why | Audit rows | None | High | **Conflict matrix**; reason-logging; idempotency | L | Auto-eval |
| Margin protection | Configurable min margin + supervisor approval path (reuse `apps/approvals`); hide cost/margin from unauthorized roles | Approval prompt; role-masked cost | Config | Read (cost) | High | Margin floor; **role masking**; approval flow | M | Conflict res |
| **SOFTECH discount execution** | **Reuse existing tested methodology** (`discount_approvals` items-UPDATE / `pos_orders/discount_authority`); eligibility→discount→SOFTECH instruction→verification→audit; **idempotent** | Status/verification surface | `OfferApplication` audit | **Write** | **High** | **End-to-end idempotency; no double-post; readback verify; points no double-count** | L | Margin, conflict res |
| Loyalty at checkout | Surface `loyalty` balance/tiers/redemption/expiry; reuse `points.py`/`SoftechPointsLog` | Non-blocking checkout widget | None (read) | Read/Write (points already written) | Med | Points math vs `personnewbal`; redemption | M | — |

**Phase-3 exit gate:** no merge without passing money-math tests + explicit
sign-off on any change to discount posting.

---

## Phase 4 — Network fulfillment

*Mostly surface & stitch existing `transfers`/`demand`/`delivery`/`ItemStock`.
The one hard sub-item is stock-reservation concurrency — call out locking first.*

| Feature | Backend work | Frontend work | Database changes | SOFTECH dep | Risk | Tests required | Complexity | Depends on |
|---|---|---|---|---|---|---|---|---|
| Branch network intelligence | Physical vs reserved vs available-to-sell over `ItemStock` + reservations; explicit SOFTECH-staleness (5-min lag) handling | Network-stock panel | None (read) | Read | Med | Availability math; staleness labeling | M | P1 |
| "Find it somewhere else" panel | Compose network stock + transfer + reserve + pickup + lost-sale | Inline panel, no POS exit | None | Read | Med | Action routing | M | Network intel |
| **Stock reservation lifecycle** | Consolidate `apps/reservations` + POS حجز-80 into Available→Reserved→Picked→Sold/Released + expiry; **`select_for_update`/DB locking**; handle cancel/failed-checkout/concurrent cashiers | Reservation state UI | Extend `reservations` (state/expiry/lock) | Read/Write (حجز 80) | **High** | **Concurrency/race tests; expiry; double-reserve; state machine** | L | Network intel |
| Transfer integration from POS | Reuse `apps/transfers` (no parallel flow) | Inline transfer action | None | None | Low | Reuse path | S | Find-elsewhere |
| Lost-sales capture | Reuse `apps/demand` (`DemandRecord`/`DemandItem`); capture product/qty/customer/branch/employee/ts/reason/outcome | Inline capture on OOS | None | None | Low | Capture completeness | S | Find-elsewhere |
| Lost-sales analytics | Extend demand analytics (by SKU/cat/branch/employee; conversion via transfer/alt; permanently lost; notified) | Dashboards (reuse Demand pages) | None | None | Low | Aggregation | M | Capture |
| Delivery intelligence in POS | Reuse `apps/delivery` (address/zone/rider/status) | Delivery context in order screen | None | None | Low | Context render | M | Customer 360 |

**Phase-4 exit:** OOS never dead-ends; reservation locking strategy documented &
tested before implementation.

---

## Phase 5 — Omnichannel

*Build on `omni`/`whatsapp`/`pbx`/`callcenter`. External-dependency risk — confirm
live creds before assuming an integration path; stub + flag if absent. Reuse
Phase-2 matching so channels never duplicate customer/order records.*

| Feature | Backend work | Frontend work | Database changes | SOFTECH dep | Risk | Tests required | Complexity | Depends on |
|---|---|---|---|---|---|---|---|---|
| WhatsApp lifecycle sends | Wire `apps/whatsapp` templates/queue to order events (confirmation/receipt/ready/delivery/availability/reservation) | Send from customer/order screen | None | None | Med (ext) | Template render; queue; delivery status; stub path | M | P2, P4 |
| Issabel/call-center integration | Incoming call → recognize phone → Customer 360 → pending orders → new order; log call relationship | Live call panel (reuse `PbxLivePage`) | Link tables (reuse `callcenter`) | None | Med (ext) | Recognition; call→customer link | L | P2 recognition |
| Call → Order flow | Call-center agent: recognized call → submitted order (products/stock check/address/fulfillment) w/o app switch | In-call order builder | None | Read (stock) | Med | End-to-end; **no dup customer/order** | L | Call integration, P2 |
| Communication timeline | Unify WA/PBX/callcenter events per customer (reuse `omni`) | Timeline in Customer 360 | Optional index | None | Low | Merge/order correctness | M | Customer 360 |

**Phase-5 exit:** channels reuse existing customer/order matching; no duplicate
records; unavailable integrations stubbed and flagged, not guessed.

---

## Phase 6 — Control & intelligence

*Aggregate existing signals into control surfaces. No new SOFTECH coupling.
Analytics are read-only; never auto-restrict/auto-block without a human (per spec).*

| Feature | Backend work | Frontend work | Database changes | SOFTECH dep | Risk | Tests required | Complexity | Depends on |
|---|---|---|---|---|---|---|---|---|
| Exception Center | Aggregator read-model over push_failed orders + sync health + offer failure + payment/reservation/safety/sync issues; recommended action + who-can-resolve | Exception inbox → opens object | `ExceptionEvent` read table | None | Med | Aggregation; routing; resolve flow | L | P3, P4 |
| Employee activity audit | Extend `audit.AuditLog`/`UserActivityLog` to POS actions (order/item/qty/discount/override/cancel/return/transfer/reservation/manual-price/approval) w/ before-after + reason | Audit views | Possibly none | None | Med | Coverage; before/after fidelity (rule 8) | M | P1–P4 events |
| Employee efficiency analytics | Read-only metrics (orders/hr, avg time, items/order, basket, upsell conv, offer util, lost-sales capture, cancel/return, discount, wait, error) | Dashboards | Aggregates | None | Low | Metric correctness; **read-only** | M | Audit |
| Fraud/leakage risk engine | Configurable scoring over POS events (excess discount, freq cancels, unusual returns, price overrides, neg margin, suspicious refunds); **alert/approve/audit only — never auto-block** | Risk alerts/approvals | Score/config tables (reuse `AbuseFlag`/`FraudSignal`) | None | Med | Scoring; **no auto-block**; false-positive handling | M | Audit |
| Global notification center | Unify operational alerts (order-waiting/transfer/prescription/stock/offer/sync/reservation/delivery) into one actionable, click-through center (reuse `apps/notifications`) | Consolidated center | None | None | Low | Routing; click-to-object | M | Exception Center |
| Next Best Action | Deterministic rule-based single next step (no LLM — rule 10) | NBA hint in transaction | None | None | Low | Rule determinism | S | P2 |

**Phase-6 exit:** control surfaces live; all intelligence deterministic and
human-in-the-loop.

---

## Phase 7 — Advanced product intelligence  🔒 GATED

*Do not start until Phases 1–6 are merged AND the user confirms directly that
product-master data cleanup has actually happened (rule 5). Substitution logic
must fail closed — unclear verification ⇒ treat as unverified, suggest nothing.*

| Feature | Backend work | Frontend work | Database changes | SOFTECH dep | Risk | Tests required | Complexity | Depends on |
|---|---|---|---|---|---|---|---|---|
| Verified active-ingredient mapping | Ingredient map sourced only from data explicitly marked verified; `name_scientific`/`active_ingredients` are dirty today | Verified badge | `verified` flag + map table | Read | High | **Verification gating**; dirty-data guard | L | Data cleanup (external) |
| Curated substitution relationships | Pharmacist-curated pairs; always "Potential Alternative — Pharmacist Review Required"; **never auto-applied to Rx** | Review-required substitution UI | Substitution table | None | High | **Fail-closed**; no auto-apply on Rx | L | Verified AI map |
| Product relationship graph | Feed curated relationships into P2 basket intelligence | — | Graph/edges | None | Med | Graph correctness | M | Curated subs, P2 |
| Prescription intelligence workflow | Verification + alternatives + stock validation on curated data | Rx workflow | Reuse | Read | High | Verification; stock validation | L | Curated subs |

**Phase-7 exit:** every substitution is verified-source, review-required, and
fails closed.

---

## Cross-cutting testing & release discipline (all phases)

- Follow the `CLAUDE.md` per-batch execution rules (state → files → change →
  migrations → tests → run tests/lint/build → regression check → summarize →
  propose next). Stop and ask before: SOFTECH-sync schema changes, discount/
  pricing logic changes, payment/checkout completion, and anything that could
  double-post to SOFTECH.
- **Idempotency & audit** are acceptance criteria, not extras (rules 3, 8).
- **Determinism**: no LLM decides totals/inventory/discounts/substitutions
  (rule 10). LLMs may assist search ranking hints only where a wrong rank is
  harmless and never touches safety or money.
- **Safety-over-sales** is a hard gate in every recommendation/offer path
  (rule 4).

## Critical-path summary

```
P1 (foundation) ─┬─▶ P2 (customer/sales intel) ─┬─▶ P3 (offers ⚠money) 
                 │                               └─▶ P5 (omnichannel, needs P2 match)
                 └─▶ P4 (fulfillment, hard: reservation locking)
P3 + P4 ─▶ P6 (control: exception center, audit, fraud, NBA)
P1–P6 merged + data cleanup confirmed ─▶ P7 (advanced product intel 🔒)
```

Highest-attention gates: **P3 SOFTECH discount execution** (money, double-post),
**P4 stock-reservation concurrency** (races), **P7 substitution** (fail-closed on
dirty master data).
