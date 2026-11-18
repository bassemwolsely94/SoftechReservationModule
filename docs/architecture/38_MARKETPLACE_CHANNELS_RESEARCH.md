# 38 — Marketplace & Delivery-App Channels (research + proposed design)

**Status:** 🟡 M1 INFRASTRUCTURE BUILT (2026-11-18), switches OFF, no platform connected. (Research / proposal 2026-11-17.)
**Scope:** selling our products through Talabat, Instashop, Chefaa, Amazon.eg and Noon Egypt,
and connecting their orders to our stock, POS writer, delivery and finance.

---

## 1. What already exists (reuse, don't rebuild)

| Need | Existing piece | Notes |
|---|---|---|
| Per-branch stock | `catalog.ItemStock` (item × branch × store), full SOFTECH snapshot every 5 min (doc 30) | Good enough for marketplace stock pushes. Quarantine stores 102/103/105 and closed 110 must stay excluded. |
| Live stock check before sale | `pos_orders/stock.py` (`check_order_stock`, live `stkbal` read) | Re-check at acceptance time. |
| Sale order into SOFTECH | `pos_orders` writer → pending `stktransm5/stktrans5/branchesales5`; `client_token` UNIQUE = idempotency; offline queue | A marketplace order becomes a normal pending sale for the branch cashier. No new SOFTECH write channel. |
| Channel → SOFTECH customer class | `CHANNEL_TO_PTCLASSIF` in `pos_orders/models.py` (`delivery`=90, `contract`=10…) | Platforms need a decided mapping (see §5 Q1). |
| Delivery with own riders | `apps/delivery` (`DeliveryOrder`, 14 statuses, rider app `/rider`, cash collection, tracking `/track/:token`) | `source_type` only has `call_center` / `branch_pos` today; add a marketplace source. |
| Product content / images | `apps/product_experience`, `apps/enrichment`, `apps/images` | Marketplaces need name, image, barcode, description. |
| Safety flags (Rx / narcotics schedule) | Product-intelligence safety flags (derived) | Gate for "can this be listed". |
| Webhook intake + notifications | `apps/whatsapp` / `apps/omni` webhook pattern, `apps/notifications` | Same pattern for order webhooks + branch alerts. |
| Finance | `apps/finance` GL; 2020 books already had «مبيعات اطلب» (marketplace customer 75), «مبيعات H D» via Souq.com customer 1341, and accounts 3194/3195 (marketplace delivery / commission) | Settlement import + commission posting fits here. |

Nothing marketplace-specific exists in code today (searched apps/, docs/, frontend: no
Talabat/Instashop/Chefaa/Amazon/Noon integration).

---

## 2. How each platform works (web research, Nov 2026)

| | Seller model | Listing | Stock sync | Order intake | Delivery | Rx | API |
|---|---|---|---|---|---|---|---|
| **Talabat EG** | Each pharmacy **branch** is a vendor | **Per branch** (own assortment + delivery area) | Delivery Hero **Q-Commerce Partner API** (Assortment: price, qty, active, max qty; bulk) or SFTP/portal | **Webhook** (Order Transmission API) or Vendor tablet app | Talabat riders **or** our riders | Not confirmed in Egypt (UAE has Rx upload) | Partner-only; token in Vendor Portal per vendor or chain; ~60 req/min |
| **Instashop EG** | Local-store marketplace, owned by Talabat since Feb 2025 | Per store | Not public | Store/picker app | Not public | Not public | None public |
| **Chefaa** | Pharmacy network; routes the order to a nearby partner pharmacy (GPS) | Per pharmacy | None documented | "Chefaa – Pharmacies" app | Pharmacy | **Yes** — core use case (photo of prescription) | None public |
| **Amazon.eg** | 3rd-party seller, self-ship or FBA | **National** | SP-API Listings / Feeds / Inventory | SP-API Orders + Notifications | Us or Amazon | **No**; drugs/supplements/cosmetics gated | Public SP-API (marketplace `ARBP9OOSHTCHU`) |
| **Noon EG** | 3rd-party seller, FBP or FBN (noon Minutes = Noon's own stock) | **National** | Noon Partner API | Partner API / portal | Us or Noon | **No**; health category gated | Partner API (API user from portal) |

**Legal frame:** Egyptian law and the Pharmacists Syndicate treat medicine sales as the licensed
physical pharmacy's act. So medicine fits only the **branch-fulfils** platforms (Talabat,
Instashop, Chefaa). Amazon/Noon realistically = beauty, personal care, devices, maybe supplements,
from one HQ stock point. EDA Decree 475/2025 (track & trace) may reach online sale later.

Sources: developers.deliveryhero.com/documentation/qc-API-integration.html ·
developer-docs.amazon.com/sp-api · helpcenter.noon.partners · chefaa.com ·
wamda.com/2025/03/talabat-fully-acquires-instashop-32-million · wamda.com/2022/01/issue-e-pharmacy-egypt.
Commission, acceptance timeouts and substitution rules are **not public** for any platform.

---

## 3. Answers to the owner's questions

- **Per branch or all together?** Talabat / Instashop / Chefaa: **per branch** — each branch is
  its own store with its own stock and delivery radius. Amazon / Noon: **one national listing**,
  which we'd fulfil from one place (HQ or one chosen branch).
- **Do they use our live stock?** Only if we push it. Talabat has an API for that; Amazon/Noon
  too. Instashop/Chefaa: staff toggles items in their app (no documented API).
- **How does the order reach us?** Talabat: webhook to our server (or their tablet). Amazon/Noon:
  API/notifications. Instashop/Chefaa: their pharmacy app on a tablet.
- **Who delivers?** Talabat: their rider or ours. Chefaa: the pharmacy. Amazon/Noon: us (FBP)
  or them (FBA/FBN, needs stock sent to their warehouse).

---

## 4. Proposed chain (one thin app over what exists)

New app **`apps/marketplace`** — adapters only, no second order/stock/delivery logic.

```
SOFTECH stkbal ─5 min─► ItemStock ─► Availability calc ─► Platform adapter ─► Talabat / Amazon / Noon
                                     (per branch: on-hand − open orders           (push qty + price,
                                      − safety buffer; Rx / fridge / narcotics     only listed items)
                                      / quarantine stores excluded)

Platform order ─webhook/poll─► ExternalOrder (unique platform+external_id = no duplicates)
      │                         │ auto-accept rules OR branch pharmacist accepts on our screen
      │                         ▼
      │                 live stock re-check (pos_orders/stock.py)
      │                         ▼
      │                 SoftechSalesOrder (pending, channel=<platform>) ─► branch cashier settles in SOFTECH
      │                         ▼
      │                 own rider? → DeliveryOrder(source=marketplace) ; platform rider? → "ready for pickup"
      ▼
Status back to platform (accepted / ready / cancelled)

Platform payout file ─► Settlement import ─► match to orders ─► commission + delivery fee journal (finance GL)
```

**Tablet-only platforms (Instashop, Chefaa):** a quick **manual intake** screen — staff types the
platform order number + items (barcode scan) so the order still goes through stock check, the POS
writer, audit and settlement matching. Same `ExternalOrder` model, `source=manual`.

Proposed models (sketch): `MarketplaceChannel` (platform, enabled switch, default OFF),
`ChannelStore` (branch ↔ platform vendor id, delivery mode), `ChannelListing` (item ↔ platform
SKU, listed yes/no, price rule, buffer), `ExternalOrder` / `ExternalOrderLine` (raw payload kept,
status log, link to `SoftechSalesOrder` + `DeliveryOrder`), `StockPushLog`, `SettlementLine`.

Rules that follow CLAUDE.md:
- Listing allowed only if the item is not Rx-only / narcotics schedule / fridge (unless approved);
  safety beats sales.
- Price on the platform = deterministic rule (SOFTECH price, or SOFTECH price + fixed platform
  markup), never edited per order by hand.
- Every accept / reject / substitution / cancellation audited; module permission + branch scope.
- All platform pushes behind a switch, dry-run first; stock push rate-limited (Talabat ~60/min).

---

## 5. Decisions needed before any build (owner)

1. ✅ **DECIDED 2026-11-17 (owner, after revisiting): B — credit sale to that platform's
   account.** One SOFTECH customer per platform (owner creates it); orders go through the
   existing `contract` channel (changed 2026-11-18 → `permanent` + forced آجل, see below); the platform receivable and payout/commission settle against
   that account. **Own-rider cash on delivery also posts as B (owner, 2026-11-17)** — one rule for
   every platform order. Consequence: the cash our rider brings back (`apps/delivery`
   `CashCollection`) is booked as a **receipt against the platform account**, not as a cash sale;
   the platform's commission for that order then arrives as an invoice/deduction against the same
   account. The settlement screen must show both, so each platform account nets to zero order by
   order.

   **Update 2026-11-18 (owner):** the first platform account, Talabat **4292**, is classed
   «عميل دائم» (ptclassif 30), not «تعاقدات» (10). Owner chose to keep it: platform drafts now use the
   `permanent` channel, and because a «عميل دائم» sale otherwise defaults to cash,
   `pos_orders/platform_accounts.py` makes any sale on a platform account (`MarketplaceChannel.softech_personcode`)
   **100% آجل**: no tenders → one credit tender; a cash/card tender is refused by the writer and the
   validator; a partial return refunds credit. Other «عميل دائم» customers are unchanged.

   History of the decision: owner first chose "cash/delivery sale", then asked for a clearer
   comparison, below.
   **How a platform sale posts in SOFTECH.** Example: Talabat order, 500 EGP, commission 20 %.

   | | A. Cash / delivery sale (ptclassif 90) | B. Credit sale to a platform account (آجل, like 2020's «اطلب» 75 / Souq 1341) |
   |---|---|---|
   | SOFTECH invoice | 500 cash sale, anonymous delivery customer | 500 credit sale to customer «طلبات» |
   | Branch cash drawer | Expects 500 cash. If Talabat's rider / card collected it, the drawer is **500 short** unless the cashier uses another tender | Unaffected — nothing expected in the drawer |
   | "Talabat owes us 500" | **Not in SOFTECH**; only in our app + finance GL | **In SOFTECH** as a receivable on the Talabat account |
   | Payout 400 arrives weeks later | Matched in our app; commission 100 booked in our GL | Accounting receives 400 + books 100 commission against the account → balance 0 |
   | Writer work | Existing `delivery` channel | Existing `contract` channel (claim + cost-center records already supported); needs one SOFTECH customer per platform created by the owner |

   **Recommended rule — "whoever holds the money":** if the platform collects (its rider's cash,
   online card) → **B** (credit to the platform account). If **our** rider collects cash on
   delivery → **A** (normal delivery sale; cash really comes to the drawer). The rule is
   deterministic per order (payment method + delivery mode from the platform payload).
   Either way the platform order number goes on the order for traceability.
2. ✅ **Platform price — APPROVED 2026-11-18 (owner):** shelf price = round2(pack_price × (1 + sale_tax_pct/100)); never `pack_price_tax` (lower than the shelf price on ~12k untaxed items). A per-platform markup rule (shelf + %, rounded to the nearest quarter pound) stays available in the channel setup.
3. **Which branches** go live first, and own riders vs platform riders per branch.
4. **Commercial facts only the account managers can give:** Talabat — is the Partner API open to
   pharmacy vendors in Egypt, one chain token for all branches, acceptance timeout, substitution
   rules, commission. Instashop — any integration path after the Talabat merger. Chefaa — API,
   commission, routing. Amazon/Noon — is OTC medicine allowed for us at all.

## 6. Suggested order of work

| Step | What | Why first |
|---|---|---|
| M0 | Owner talks to Talabat / Chefaa / Instashop account managers (questions in §5.4) | Nothing technical is decidable without it |
| M1 | `apps/marketplace` core + **manual intake** screen + listing eligibility (Rx/safety) | Works for every platform on day one, even tablet-only ones |
| M2 | **Talabat adapter**: stock/price push per branch + order webhook → POS writer | Only platform with a documented per-branch API; biggest Egyptian reach |
| M3 | Settlement import + commission journal (finance GL) | Money reconciliation |
| M4 | Amazon / Noon adapter for non-medicine catalog from HQ | Only after category approval |
| M5 | Instashop / Chefaa API adapters | Only if they offer an API |
