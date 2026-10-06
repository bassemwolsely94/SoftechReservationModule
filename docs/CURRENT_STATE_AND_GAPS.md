# Current State & Gap Analysis — ElRezeiky Commerce OS

> **Prompt A output.** Read-only audit of the existing repository against the
> "ElRezeiky Sales & Commerce OS" target feature set. No code was changed to
> produce this document. All ratings are grounded in the code cited inline.
>
> **Headline finding:** this is **not** a greenfield build. The repo is a mature
> 52-app Django/DRF + React/Vite + PostgreSQL platform sitting over SOFTECH
> (Sybase ASE). The overwhelming majority of the target features already have
> substantial **backend data models and services** in dedicated apps. The real
> gap is almost never "build the capability from scratch" — it is **surfacing
> existing capability inside the POS** and filling a small number of genuinely
> missing pieces (a customer-facing offers engine, a command palette, a theme
> system, an exception center, and a unified universal search). **Extend, don't
> rebuild** (non-negotiable rule 6).
>
> Cross-references: this audit complements the existing architecture registry —
> `docs/architecture/02_MODULE_REGISTRY.md`, `04_API_REGISTRY.md`,
> `10_FEATURE_INVENTORY.md`, `12_PROJECT_CONTEXT_SUMMARY.md`. The SOFTECH write
> methodology is documented in `SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md`,
> `SOFTECH_POS_DISCOUNT_MODEL.md`, and `SOFTECH_POS_DISCOUNT_WORKFLOW.md`.

---

## 1. Existing implementation

### 1.1 POS components (cashier screen + multi-step checkout)

**Indirect-POS is already built and live-capable** (`apps/pos_orders/`, gated by
`POS_WRITER_ENABLED`).

- **Backend**: `apps/pos_orders/models.py` — `SoftechSalesOrder` (header),
  `SoftechSalesOrderLine`, `SoftechSalesOrderPayment`. PG is the system of record
  for our metadata (channel, referral doctor, prescription, originating call,
  audit); SOFTECH is authoritative for the posted order.
- **Order lifecycle** (`SoftechSalesOrder.STATUS_*`): `draft → ready → queued →
  pushing → pushed → settled` (plus `push_failed`, `cancelled`). `is_locked`
  freezes an order once pushed/settled — corrections go through a return, never a
  mutation. Idempotency via a unique `client_token` UUID
  (`views.OrderListCreateView.create`).
- **API** (`apps/pos_orders/views.py`, `urls.py`): list/create/detail,
  `/ready` (price + validate), `/push` (dry-run plan or gated live write),
  `/cancel`, `/batch-availability`, `/contract-fields`, `/customer-types`,
  `/customer-entities`, `/salespeople`, `/branch-stores`, `/queue-status`,
  `/flush-now`, `/discount-suggest`, `/points-preview`, `/reference-data`.
- **Frontend**: `frontend/src/pages/POSOrderPage.jsx` +
  `frontend/src/hooks/usePosOrder.js` (desktop) and
  `frontend/src/pages/mobile/MobilePOSOrderPage.jsx` (mobile). Tabbed multi-step
  UI (الأصناف / السداد / بيانات التعاقد) with channel hotkeys (Ctrl+F2/F3/F4),
  tab hotkeys (Ctrl+2/3/4), a favorites quick-grid (localStorage), barcode add
  (`addByBarcode`), and an advanced item-search modal (Ctrl+F1). New guided flow
  helper: `frontend/src/hooks/useGuidedFlow.js`.
- **Offline resilience**: `frontend/src/api/offlineQueue.js` + the `queued`
  status + `/flush-now`; documented in `docs/architecture/POS_OFFLINE_RESILIENCE.md`.

### 1.2 SOFTECH integration

- **Connection**: `config/sybase.py` — jConnect JDBC via jpype
  (`get_sybase_connection(charset=None)`), login-timeout bounded. Branch-level
  connection targeting through `Branch.effective_db_host/effective_db_port/db_name`.
- **Sync direction & frequency**: **pull** SOFTECH → PG. `apps/sync/tasks.py`
  runs an APScheduler `BackgroundScheduler`; `run_full_sync()` is split into a
  tiered `run_fast_sync()` (~every 5 min: stock/sales) and `run_slow_sync()`
  (~every 60 min: items/customers). Queries in `apps/sync/sybase_queries.py`;
  health in `apps/sync/network_health.py`.
- **Write methodology (the two established, tested paths — never bypass these):**
  1. **Indirect-POS pending write** (`apps/pos_orders/writer.py`, 1,219 lines):
     writes only the **pending** surface — `stktransm5` (header) + `stktrans5`
     (lines) + `branchesales5` (tenders), plus `companiesitems5`/`branchesalescc5`
     for contract/insurance. **Never** writes the final `stktransm`/`stktrans`/
     `branchesales`, `stkbal`, `picpoints`, accounting, or e-invoice — the
     cashier's settlement does that. Serial allocated atomically at write
     (`lastdocnumbers`), idempotency marker in `vf2`/comments
     (`softech_token`, `_pending_docnumber_by_vf2`). Arabic via cp1256
     pre-encoding (`_enc_arabic`, `POS_WRITE_CHARSET='iso_1'`). Out-of-stock →
     حجز 80 reservation path (`apps/pos_orders/reservation.py`) where the branch
     enables it, else rejected (native منع الصرف). Loyalty points computed and
     written to `personnewbal` (`apps/pos_orders/points.py`). Spec:
     `docs/architecture/SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md`,
     `14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md`.
  2. **Discount/master-data alignment** (`apps/discount_approvals/`): the
     `UPDATE …items SET <cols>, usercode=?, itemlastupdate=GETDATE() WHERE
     itemcode=?` pattern → SSB9 replicates HQ→branches. `alignment.py` (tier
     evaluation, `apply_classification_changes`), `replication.py` (source
     resolution, `scan_recent`, `force_replication`), `services.py`, `views.py`.
     Spec: `SOFTECH_POS_DISCOUNT_MODEL.md`, `SOFTECH_POS_DISCOUNT_WORKFLOW.md`.
     A third writeback (market-shortage flags) rides the same items-UPDATE path
     (`apps/purchasing/shortage_writer.py`).
- **Discount authority (live read)**: `apps/pos_orders/discount_authority.py` +
  `views.discount_suggest` — retail = cap-only (`items.posdiscp` ∧
  `managerdiscount.max_custdiscp`); contract/insurance = auto-apply
  `custdiscounts` by category, bounded by seller ceiling. Deterministic; degrades
  gracefully when the branch is unreachable.
- **Pricing math**: `apps/pos_orders/pricing.py` — deterministic `compute_line`,
  `compute_header`, `split_payment`. No fuzzy logic (rule 2/10 satisfied).

### 1.3 Customer models

`apps/customers/models.py` is already a near-complete Customer-360 **data** layer:

- `Customer` — SOFTECH identity (`softech_pic` globally-unique PIC,
  `softech_ptclassifcode` = channel), phone/`whatsapp_phone`, guest/merge flag,
  **segmentation** (`segment`, `SEGMENT_CHOICES`), **LTV**, `last_visit_date`,
  `days_since_last_visit`, `purchase_count_90d`, `complaint_risk_score`,
  **churn** (`churn_score`, `churn_segment`) — all computed nightly by
  `segment_customers`.
- `CustomerHealthProfile` (OneToOne) — 16 auto-detected chronic conditions,
  per-condition confidence, `active_medications`, `known_allergies`,
  pregnancy/lactation/pediatric/polypharmacy flags. **Directly relevant to
  pharmacy-safety flags (rule 4) and Phase 7.**
- `PurchaseHistory` + `PurchaseHistoryLine` — full sales/return history with
  per-line cost-at-sale and discount breakdown (list/pharmacy/additional/
  customer/special). Feeds analytics, repeat-order, and basket intelligence.
- `CustomerNote`.

### 1.4 Branch / stock services

- `apps/branches/models.py` — `Branch` (+ `BranchQuerySet`, `BranchSettings`),
  per-branch SOFTECH DB routing.
- `apps/catalog/models.py` — `ItemStock` (`quantity_on_hand`, `monthly_qty`,
  `on_order_qty`, per store) with `stock_status`. Live per-batch reads via
  `apps/pos_orders/batch_availability.py` (FEFO). `EXCLUDED_STORE_CODES` guards
  expired/quarantine stores.
- Network intelligence primitives exist in `apps/transfers`, `apps/transits`,
  and `apps/purchasing`.

### 1.5 Transfer integration

`apps/transfers/models.py` — `TransferRequest`, `TransferRequestItem`,
`TransferRequestMessage`. Full request lifecycle + messaging. Frontend:
`TransfersPage`, `NewTransferPage`, `TransferDetailPage`, `TransfersAnalyticsPage`,
`TransferModuleTabs`. **Reuse this — do not build a parallel transfer flow (rule 6).**

### 1.6 Reservations

`apps/reservations/models.py` — `Reservation` (rich status/priority/channel/
contract-subtype lifecycle, ERP match status), `ReservationLine`,
`ReservationDownpayment`, `ReservationStatusLog`, `ReservationImage`,
`ReservationActivity`. Frontend: `ReservationsPage`, `ReservationsKanban`,
`NewReservationPage`, `ReservationDetailPage`, `ReservationsAnalyticsPage`.
**Note two distinct "reservation" concepts:** (a) this customer-facing
reservation module, and (b) the SOFTECH حجز 80 out-of-stock hold inside the POS
writer (`pos_orders/reservation.py`). Phase 4 stock-reservation must be explicit
about which it means.

### 1.7 Notifications, real-time, permissions

- **Notifications** (`apps/notifications/models.py`): `Notification`,
  `NotificationLog`, `PushSubscription` (web-push), `ChatterMessage` (real-time
  chat), `RoleNotificationAccess`, `PersonalReminder`, `Announcement`.
  Real-time transport via Django Channels/daphne (`config/asgi.py`,
  `CHANNEL_LAYERS`); frontend `useNotificationSocket.js`, `useChatterSocket.js`,
  `NotificationBell`, `NotificationPanel`, `ModuleNotificationBell`.
- **Permissions/roles** (`apps/users/models.py`): 9 roles (`ROLE_CHOICES`),
  **dynamic RBAC** `RoleModuleAccess` (role × 28 modules × 8 actions, default-
  deny), `UserBranchAccess`, MFA/TOTP for approval roles
  (`MFA_REQUIRED_ROLES = {admin, supervisor, purchasing}`), and a read-only
  **SOFTECH permission mirror** (`ErpUserGroup`/`ErpScreen`/`ErpGroupPermission`
  → derived `ErpGroupModulePermission`). Frontend gate `usePermission.js`,
  `CanDo.jsx`, `PermissionsMatrixPage`, `ErpPermissionsPage`. Server-side
  enforcement present (rule 9). **Gap:** `MODULE_CHOICES` has no `pos`/`pos_orders`
  entry — POS authorization currently rides its own `pos_orders/permissions.py`
  (`CanOperatePosOrders`, `CanPushPosOrders`), outside the RBAC matrix.

### 1.8 Adjacent capability already present (feeds later phases)

| App | Classes (models.py) | Feeds |
|---|---|---|
| `demand` | `DemandRecord`, `DemandItem`, `DemandFollowUp`, `DemandLog`, `ItemDemandStat` | **Lost-sales capture + analytics (Phase 4)** |
| `delivery` | `DeliveryDriver`, `CustomerLocation`, `DeliveryOrder(+Item)`, `DeliveryAssignment`, `DeliveryStatusLog`, `DeliveryAreaFee`, `DeliveryCSAT`, `CashCollection`, `DeliveryRoute` | **Delivery intelligence (Phase 4/5)** |
| `whatsapp` | `WATemplate`, `WAConversation`, `WAMessage`, `WAMediaFile`, `WAWebhookLog`, `WAMessageQueue` | **WhatsApp (Phase 5)** |
| `pbx` | `AgentExtension`, `PBXQueue`, `PBXEvent`, `CallSession` | **Issabel/call-center (Phase 5)** |
| `callcenter` | `CallLog`, `AddressUpdate`, `CustomerCase`, `CaseEvent`, `CallQualityScore`, `CallItem` | **Call→order (Phase 5)** |
| `omni` / `social` | omnichannel envelope layer (doc 15) | **Phase 5 unification** |
| `loyalty` | `LoyaltyTier`, `LoyaltyAccount`, `PointTransaction`, `RewardCatalog`, `RedemptionRequest`, `SoftechPointsLog` | **Loyalty (Phase 3)** |
| `recommendations` | `RecommendationEngineRun`, `FrequentlyBoughtTogether`, `CustomerRecommendation` | **Basket intelligence (Phase 2)** |
| `approvals` | `ApprovalWorkflowDefinition/Step/Request/Decision/EscalationLog` | **Margin approval (Phase 3), exception routing (Phase 6)** |
| `audit` | `AuditLog`, `AbuseFlag` | **Employee audit + fraud/leakage (Phase 6)** |
| `incentives` | `IncentiveProgram/Rule/Transaction/Settlement`, `SalesTarget` | **Employee efficiency (Phase 6)** |
| `vouchers` | `Voucher`, `VoucherAssignment`, `VoucherOTP`, `VoucherRedemption(+Document)` | **Offer-adjacent (Phase 3)** |
| `catalog` | `CatalogVariantGroup`/`VariantMember`, `ProductBundle`/`BundleItem`, `ItemAlias`, `ItemBarcode`, `ChronicMedication` | **Product intelligence (Phase 1), bundles/substitution (Phase 3/7)** |
| `referral` | `ReferralCode`, `ReferralLead`, `ReferralEvent`, `FraudSignal` | Growth; fraud signals (Phase 6) |

### 1.9 Reusable UI components worth keeping

`ItemSearchWidget`, `ItemSearchInput`, `AdvancedItemSearchModal`,
`MultiItemPicker`, `CustomerSearchWidget`, `POSCustomerModal`,
`CustomerLocationsPanel`, `CustomerTagsPanel`, `SalespersonPicker`,
`BranchSelect`, `PrintReceiptModal`/`ReceiptPrint`, `QrScanner`/`ShelfQrButton`,
`WhatsAppShareButton`, `StatusBadge`, `DataTable`, `Layout`/`MobileLayout`,
`NotificationBell`/`NotificationPanel`, `ChatterBox`, `BrandMark`. Design tokens
partially exist via the brand rebrand (navy `#022871`, self-hosted fonts) — see
memory `brand-identity-rebrand`.

---

## 2. Gap analysis against the target feature list

Legend: **✅ Exists** · **🟡 Partial** (backend/data present, not surfaced in POS,
or missing pieces) · **❌ Missing** · **♻ Requires refactor**.

| # | Feature | Rating | Where it stands / what's missing |
|---|---|---|---|
| 1 | Product Intelligence overlay | 🟡 | `catalog.Item` already carries clean names (AR/EN), scientific name, aliases (`ItemAlias`), barcodes (`ItemBarcode`), category/family/producer, dosage form/shape, origin, effect, active ingredients, and operational flags. **Missing:** a normalized search-name field, curated tags, and explicit safety flags surfaced on the POS card. Do NOT duplicate `Item` — extend it. |
| 2 | Product categorization + subcategories/tags | 🟡 | `Category` + `CatalogVariantGroup` exist; SOFTECH `medicine_type`/`family`/`store_classif` present. **Missing:** subcategory hierarchy + free tags. |
| 3 | Universal search (code/barcode/name AR-EN/alias/customer/phone/order/reservation) | 🟡♻ | Per-domain search exists (`catalog.softech_search`, `product_experience.product_search`, `analytics.customer_search`, `personal.persons_search`) + rich widgets. **Missing:** one unified endpoint + one POS search box spanning items+customers+orders+reservations. Fuzzy on names, **never** fuzzy on safety-relevant matches (rule 4/5). |
| 4 | Product images | ✅🟡 | `apps/images` + `ImageEnrichmentPage`, `product_image_search`, `ProductContentAdminPage`. **Missing:** wiring images onto the POS product card. |
| 5 | Product cards (image/name/strength/form/price/branch stock/offer+safety indicators) | 🟡 | All data exists (`Item`, `ItemStock`, health/safety). **Missing:** the composed POS card component with live branch stock + offer/safety badges. |
| 6 | Quick Sell / favorites / recently used | 🟡 | Favorites quick-grid exists (`usePosOrder.js`, localStorage). **Missing:** server-side per-branch top-sellers + recently-used (data is in `PurchaseHistory`/`ItemDemandStat`). |
| 7 | Smart barcode mode | 🟡 | `addByBarcode` + `ItemBarcode` (multi-barcode) + `QrScanner`. **Missing:** streamlined scan→identify→add with minimal interruption + scanner-focus handling. |
| 8 | Keyboard shortcuts + command palette (Ctrl+K) | 🟡❌ | Scattered hotkeys exist (Ctrl+F1–F4, Ctrl+2–4). **Missing:** a centralized shortcut registry and a **command palette (Ctrl+K)** — none present in `frontend/src`. |
| 9 | Smart defaults / progressive data entry | 🟡 | Channel-driven field visibility + `reference-data` defaults (auto seller/branch) exist. **Missing:** systematic "hide irrelevant, don't re-ask known info" across the form. |
| 10 | Customer recognition by phone + duplicate detection | 🟡 | `Customer.phone`/`whatsapp_phone` indexed, guest-merge flag, `CustomerSearchWidget`, `POSCustomerModal`. **Missing:** real-time recognize-on-type in POS + explicit duplicate surfacing. |
| 11 | Customer 360 | 🟡 | Data layer essentially complete (§1.3) + `CustomerDetailPage`. **Missing:** a **POS side-drawer** that shows it without abandoning the basket. |
| 12 | Repeat order | 🟡 | `PurchaseHistory(+Line)` present. **Missing:** a re-validating rebuild service (stock/price/offer/status revalidation — never blind-copy). |
| 13 | Digital receipts | 🟡 | `PrintReceiptModal`/`ReceiptPrint`/`InsurancePrint` + `WhatsAppShareButton`. **Missing:** unified receipt service (print/WhatsApp/email-SMS stubs) + buy-again that revalidates. |
| 14 | Smart basket + basket intelligence | 🟡 | Basket UI exists; `recommendations.FrequentlyBoughtTogether`/`CustomerRecommendation` + `catalog.ProductBundle` back it. **Missing:** the ranked, contextual basket-intelligence service wired to the live cart. |
| 15 | Upsell / sales-opportunity engine | 🟡❌ | Signals exist (recommendations, bundles, health profile, demand). **Missing:** a **backend** Sales Opportunity service that ranks opportunities (must be server-side, deterministic — rule 7/10). |
| 16 | Offers & promotions engine | ❌🟡 | **Biggest true gap.** No customer-facing offers engine. Partial bases: `catalog.ProductBundle` (static bundles), `vouchers`, `incentives`, `campaigns` (WhatsApp only). **Phase 3 must build** offer types/priority/conflict resolution and execute via the existing SOFTECH discount methodology — money-critical. |
| 17 | Loyalty | ✅🟡 | `apps/loyalty` full model set + `SoftechPointsLog`; POS `points-preview` + `points.py` compute `personnewbal`. **Missing:** checkout-surfaced balance/redemption without slowing the cashier. |
| 18 | Branch network intelligence | 🟡 | Multi-branch stock (`ItemStock`), transfers, transits, purchasing network views. **Missing:** a POS panel distinguishing physical vs reserved vs available-to-sell, with explicit SOFTECH-staleness handling. |
| 19 | Stock reservation (lifecycle + concurrency) | 🟡♻ | Two partial bases: `apps/reservations` (customer-facing) and POS حجز 80 (`pos_orders/reservation.py`). **Missing:** an Available→Reserved→Picked→Sold/Released lifecycle with expiry + **explicit locking** for concurrent cashiers. Concurrency-sensitive. |
| 20 | Transfer integration from POS | 🟡 | `apps/transfers` complete. **Missing:** inline "transfer from POS" action (reuse, don't fork — rule 6). |
| 21 | Lost-sales capture + analytics | ✅🟡 | `apps/demand` (`DemandRecord`/`DemandItem`/`ItemDemandStat`) + `DemandPage`/`DemandRecoveryPage`/`DemandDashboardPage`. **Missing:** the inline "capture" hook from POS out-of-stock. |
| 22 | Prescription mode | 🟡 | POS has `prescription_image` + referral doctor; `CustomerHealthProfile` clinical context. **Missing:** a dedicated prescription workflow (deferred to Phase 7 for substitution). |
| 23 | Safety flags | 🟡 | Rich clinical data (`CustomerHealthProfile` allergies/pregnancy/interactions-adjacent; `Item` restriction flags `branch/supplier/customer_trans`, `nosale_classif`, fridge). **Missing:** a POS safety-flag surface that can **block** an upsell (rule 4). |
| 24 | Exception center | ❌ | Not present (`grep` found none). **Phase 6 build.** Inputs exist (push_failed orders, sync health, approval requests, `AbuseFlag`). |
| 25 | Hold/resume + multiple carts | 🟡❌ | Single active order + offline queue. **Missing:** multiple concurrent named carts + hold/resume. |
| 26 | Customer queue | ❌ | Not present as a POS concept. |
| 27 | Delivery intelligence | ✅🟡 | `apps/delivery` very complete (drivers, locations, orders, assignment, routes, CSAT, cash). **Missing:** delivery context embedded in POS/order screen. |
| 28 | WhatsApp integration | ✅🟡 | `apps/whatsapp` full stack + `WhatsAppShareButton`/inbox/campaign pages. **Missing:** order-lifecycle sends (confirmation/ready/availability) wired from the order screen; confirm live API creds (rule: stub if unavailable). |
| 29 | Issabel / call-center integration | ✅🟡 | `apps/pbx` + `apps/callcenter` + `PbxLivePage`/`CallCenterPage`. **Missing:** incoming-call → recognize → Customer-360 → new-order flow stitched end-to-end. |
| 30 | Employee activity audit + efficiency analytics | 🟡 | `apps/audit.AuditLog`, `users.UserActivityLog`, `incentives`. **Missing:** the POS-action audit coverage (discount/override/cancel/return/manual-price) + efficiency reporting surface. |
| 31 | Customer segmentation | ✅ | `Customer.segment`/`churn_*` + `segment_customers`. Configurable rules could be formalized but the capability exists. |
| 32 | Fraud/leakage controls | 🟡 | `audit.AbuseFlag`, `referral.FraudSignal`. **Missing:** a configurable scoring engine over POS events (alert/approve/audit only — never auto-block, rule per spec). |
| 33 | Role-based UX | ✅🟡 | Dynamic RBAC (§1.7) + frontend gates. **Missing:** a `pos` module in `MODULE_CHOICES` and role-shaped POS layouts. |
| 34 | Light/dark theme | ❌ | No theme system in `frontend/src` (no `dark:`/`data-theme`/`useTheme`). Brand tokens exist but single-mode. **Build a design-token theme.** |
| 35 | Notification center | ✅🟡 | `apps/notifications` + bell/panel/inbox. **Missing:** unifying operational alerts (order-waiting/transfer/stock/offer/sync) into one actionable, click-through center. |
| 36 | Real-time updates | ✅ | Django Channels/daphne + web-push + socket hooks. Sound. |
| 37 | Offline / degraded resilience | ✅🟡 | `offlineQueue.js` + queued status + `flush-now`; `POS_OFFLINE_RESILIENCE.md`. Extend to new POS surfaces as they land. |

**Summary:** 0 features are truly from-zero except **Offers engine (#16)**,
**Exception center (#24)**, **Command palette (#8)**, **Theme (#34)**, and
**Customer queue (#26)**. Everything else is "surface existing capability" or
"add a thin missing piece."

---

## 3. Architecture proposal (mapped onto the existing structure)

Guiding constraint: **extend existing apps; add a thin POS-facing orchestration
layer; never duplicate business logic** (rule 6). Backend owns all decisions;
React renders them (rule 7).

- **Product intelligence** → extend `catalog.Item` (add `search_name`
  normalized, `tags`, explicit `safety_flags`); a `catalog/search.py` service +
  one `GET /api/search/universal` endpoint fanning across item/customer/order/
  reservation with a strict "no fuzzy on safety matches" rule. Index-backed
  (Postgres `pg_trgm` / `GIN`).
- **POS orchestration app** (new, thin) — e.g. `apps/pos_intel/` **services only,
  no duplicate persistence**: `BasketIntelligenceService`,
  `SalesOpportunityService`, `RepeatOrderService`, `ReceiptService`. Each
  composes existing apps (recommendations, catalog bundles, customers, demand,
  loyalty). Deterministic, ranked outputs.
- **Offers engine** (new, `apps/offers/`) — the one genuinely new domain.
  `Offer`, `OfferRule`, `OfferApplication` (audit). Evaluation on basket change;
  conflict resolution engine stores the reason each offer was
  selected/rejected; **execution goes through the existing SOFTECH discount
  methodology** (`discount_approvals` path / `pos_orders/discount_authority`), not
  a new pricing path. Idempotent + fully audited end-to-end. Reuse
  `catalog.ProductBundle` for bundles.
- **Stock reservation** → consolidate onto one lifecycle service reusing
  `apps/reservations` + POS حجز 80; add `select_for_update`/DB-level locking and
  expiry. Clarify the two "reservation" meanings.
- **Network fulfillment** → a `find-it-elsewhere` service over `ItemStock` +
  `transfers` + `demand` (lost-sale capture) + `delivery`.
- **Omnichannel** → build on `omni`/`whatsapp`/`pbx`/`callcenter`; reuse Phase-2
  customer/order matching so channels never duplicate records.
- **Control layer** → new `ExceptionCenter` aggregator (read model over
  push_failed orders, sync health, `approvals`, `AbuseFlag`); extend `audit` for
  POS-action coverage; a deterministic `NextBestAction` rule service.
- **Real-time / caching / jobs** → reuse Channels for live POS/notification
  push; add Postgres/Redis caching for search + basket-intel; keep APScheduler
  for batch (segment/demand/recommendation runs). No new event bus needed.
- **Permissions/audit** → add `pos` to `MODULE_CHOICES`; route POS authorization
  through `RoleModuleAccess`; every offer/override/return/cancel/reservation/
  SOFTECH-write emits an audit record (rule 8).

---

## 4. Database impact

New/changed tables and fields (all PG-side; **none rewrite SOFTECH**):

- **Extend `catalog.Item`** (migration): `search_name`, `tags` (M2M or JSON),
  `safety_flags`. GIN/`pg_trgm` indexes for universal search. *Sync-adjacent*
  (synced table) — additive only, no SOFTECH write.
- **`apps/offers`** (new): `Offer`, `OfferRule`, `OfferApplication`. **Touches
  money** → the only schema whose *execution* hits SOFTECH-synced discount data;
  needs the strictest financial testing and a stop-and-ask before merge.
- **`apps/pos_intel`** (new): ideally **no new tables** (compute/read services);
  any cache tables clearly derived + rebuildable.
- **Stock-reservation lifecycle**: extend `reservations` (status/expiry/lock
  columns) rather than a new table. **Concurrency-sensitive.**
- **Exception center**: a read model / lightweight `ExceptionEvent` table
  aggregating existing signals; no SOFTECH coupling.
- **Audit coverage**: extend `audit.AuditLog` usage (likely no schema change).
- **`pos` module row** in `RoleModuleAccess` seed data.

**SOFTECH-synced data touched:** only `catalog.Item` (additive PG columns, no
write-back) and — at *execution* time, not schema — the offers engine via the
established discount path. Everything else is net-new PG-only.

---

## 5. Risk assessment

- **SOFTECH integrity (highest).** The offers engine (Phase 3) must reuse the
  tested discount methodology and be idempotent + auditable; a new pricing path
  is the single largest correctness/double-post risk (rules 1–3). The POS writer
  already enforces pending-only writes, atomic serials, and `vf2` idempotency —
  new code must not weaken these. **Stop-and-ask gate before any change to
  discount posting.**
- **Data quality (high).** SOFTECH product master is dirty — `name_scientific`
  holds product (not molecule) names, `active_ingredients` unreliable (memory:
  `catalog-scientific-name-is-dirty`). **No automatic substitution before the
  Phase 7 verified-data gate** (rule 5). Universal search must never fuzzy-match
  on safety-relevant fields.
- **Financial (high).** Offer conflict resolution, margin floors, and
  loyalty/points interaction need deterministic money-math tests per batch
  (rule 2/10). Points already write `personnewbal` — offers must not
  double-count.
- **Inventory / concurrency (high).** Stock reservation with concurrent cashiers
  needs explicit `select_for_update` locking + expiry; stale SOFTECH stock (5-min
  fast-sync lag) must be shown as "physical vs available-to-sell," never as
  guaranteed.
- **Performance (medium).** Universal search + live basket intelligence on every
  cart change must be indexed/cached to keep the POS instant; live branch reads
  (discount authority, batch availability) already degrade gracefully — preserve
  that.
- **Security (medium).** Enforce the new `pos` permissions server-side (rule 9);
  keep cost/margin data invisible to unauthorized roles; MFA already gates
  approval roles.
- **UX complexity (medium).** The spec demands a *calm* UI (rule 11) — new
  intelligence must surface as ranked, contextual hints, not popups/modals for
  common actions. Command palette + theme reduce load; over-surfacing
  recommendations would increase it.
- **External-dependency (Phase 5).** WhatsApp/Issabel live availability must be
  confirmed before assuming an integration path; stub + flag if creds are absent.

---

### Bottom line for the plan (Prompt B)

Sequence to **maximize reuse and minimize SOFTECH risk**: Phase 1 is mostly
composition + two new pieces (command palette, theme) → low risk, high daily
value. Phase 2 is service-layer orchestration over an already-rich data layer.
**Phase 3 (offers) is the one high-risk, money-critical, partially-greenfield
build — gate it behind exhaustive financial tests.** Phases 4–6 are largely
"surface and stitch" existing apps. Phase 7 stays blocked on product-master
cleanup (rule 5).
