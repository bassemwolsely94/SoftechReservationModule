# Phase 3 — Offer → SOFTECH Discount Execution (DESIGN FOR REVIEW)

> **Status: PROPOSAL ONLY. No code on the SOFTECH write path until this is
> signed off.** This document is the stop-and-ask gate required by CLAUDE.md
> (rules 1–3: preserve SOFTECH integrity, deterministic money, idempotent writes,
> no double-post). It plans *how* an approved offer discount reaches SOFTECH,
> grounded in the code that already does it.
>
> Prereqs already built (no SOFTECH writes): `apps/offers` model + deterministic
> `evaluate_offers` engine (26 money-math tests) + margin protection
> (`MarginConfig`, role-masked, `requires_approval` gate; 10 tests). See
> `memory: commerce-os-phase3-offers`.

---

## 1. Headline decision — reuse the POS writer, add NO new write path

An offer discount is a **per-transaction, per-line** discount. SOFTECH already
represents exactly that as **`stktrans5.custdiscp`** on a pending POS line, and we
already write it:

- `pos_orders/models.py` — `SoftechSalesOrderLine.cust_discp` (`DecimalField(6,2)`).
- `pos_orders/writer.py::_line_row` — writes `'custdiscp': f(line.cust_discp)` into
  the pending `stktrans5` row (the established, tested writeback).
- `pos_orders/pricing.py::compute_line` — derives `trans_price` from `cust_discp`
  deterministically (`trans_price = isp × (1 − disc/100)`).
- `pos_orders/discount_authority.py` — bounds an entered `cust_discp` against item
  `posdiscp` / seller ceiling / contract `custdiscounts` at `/ready`.

**Therefore: offer execution = set the right `cust_discp` on each order line, then
push through the EXISTING writer.** We do **not** touch `stktransm`/`stktrans`
finals, `stkbal`, `picpoints`, accounting, or e-invoice (the cashier's settlement
still does that), and we do **not** add a second Sybase write path.

### Why NOT `discount_approvals/replication.py`
That channel is **master-data**: `UPDATE items SET <discount cols>, itemlastupdate=…`
→ SSB9 replicates HQ→branches, changing the item's discount for **all future
sales**. An offer is a *this-sale-only* discount for a specific basket/customer.
Using the master path would corrupt catalog pricing. It stays reserved for
approved permanent item-discount changes.

---

## 2. The amount → `cust_discp %` bridge (the one real subtlety)

The engine computes a per-line discount **amount** (EGP), because `fixed`, `bxgy`,
and `qty_tier` are not naturally percentages. But the SOFTECH line field is a
**percentage** (`custdiscp`, 2 dp). So at execution we convert:

```
cust_discp_line = round( discount_amount_line / line_gross × 100 , 2 )   # 2 dp
```

**SOFTECH's recomputed amount is authoritative, not the engine's.** After we set
`cust_discp`, the *actual* money off is what `compute_line` produces:
`line_gross − round(isp × (1 − cust_discp/100)) × qty`. Because `cust_discp` is
truncated to 2 dp, this can differ from the engine's proposed amount by a few
piastres per line.

**Design rule:** the execution layer MUST recompute the discount from the final
`cust_discp` via the existing `pricing.compute_line`, and surface **that**
number as the committed discount (never the engine's pre-conversion amount).
A reconciliation test asserts `|engine_amount − softech_amount| ≤ tolerance`
(tolerance = piastres from 2-dp rounding × line count) for every offer type.

> **DECIDED — D1 = round in the customer's favour (`ROUND_HALF_UP`).** Owner: offers
> come mostly from the mother company, which compensates ElRezeiky, so a piastre of
> *over*-discount is acceptable. Conversion uses `ROUND_HALF_UP` (same convention as
> `pricing.py`); ties and rounding never *under*-give the customer. The
> SOFTECH-recomputed amount remains the audited figure.

---

## 3. Lifecycle — where offers attach

```
basket change ──▶ evaluate_offers (already built, read-only, no writes)
     │                     │ plan: per-line discount amounts + requires_approval + margin
     ▼                     ▼
  POS /ready  ──▶ ATTACH: convert plan → per-line cust_discp on SoftechSalesOrderLine
     │             (offer-sourced), then run EXISTING discount_authority + margin gate
     ▼
  approval gate (if requires_approval) ──▶ apps/approvals request; block push until granted
     │
     ▼
  POS /push  ──▶ EXISTING writer.py posts pending stktrans5 rows (cust_discp included)
     │           + write OfferApplication audit rows (was_applied, discount, reason)
     ▼
  cashier settles in SOFTECH (finals, points, e-invoice) — unchanged
```

- **Attach point:** `/ready` (already the pricing+validation step). Offer discounts
  are written onto `SoftechSalesOrderLine.cust_discp` there, tagged as offer-sourced
  (new nullable `applied_offer` FK / `discount_source` on the line — additive PG-only
  migration, no SOFTECH column).
- **Push point:** the existing `writer.py` — **unchanged write DML**. It already
  serializes `cust_discp`. OfferApplication rows are written in the **same
  transaction** as the writer's serial allocation / `vf2` idempotency marker.

---

## 4. Discount MAGNITUDE comes from the item card — DECIDED (D2 + Q1)

> **DECIDED — the item card's POS discount (`items.posdiscp`) IS the discount
> magnitude.** The offer/engine defines only the **structure** — which items
> qualify, the buy-X/get-Y condition, and the cheapest-unit pairing. The percent
> taken off a discounted unit **= that item's `Item.pos_discp`** (synced into the PG
> mirror — no live read needed). So a true **1+1** is an item whose `posdiscp = 100`;
> a **1 + ½** is an item whose `posdiscp = 50`. `Offer.value` / `get_discount_percent`
> are **not** the money magnitude for these general offers.

Two authorization modes on the offer (`authorization_source`):

| mode | magnitude | approval |
|------|-----------|----------|
| **`item_card`** (default — the general case) | per-unit % = `Item.pos_discp` | none — it's already the authorized POS discount |
| **`offer`** (the exception — owner may request) | % = `Offer.value` (may exceed `posdiscp`) | **requires supervisor approval BEFORE the order is saved to the cashier** (§8) |

So the engine never posts a discount the item card doesn't authorize **unless** a
supervisor has explicitly approved an `offer`-mode promo up front. Manual cashier
discounts remain bound by `posdiscp`/seller ceiling as today.

**Consequence:** for `item_card` offers there is no shortfall — the magnitude is the
authorization. Only `offer`-mode promos route through approval.

---

## 5. BXGY mechanic (the real offer shape) + manual-discount stacking — DECIDED

> **DECIDED — D3.** Two parts:
> 1. **Manual vs offer:** the line takes the **offer** discount (`max(offer, manual)`
>    in effect — the offer is the promo, the smaller manual is audited as superseded).
> 2. **The real BXGY shape is cross-item, cheapest-unit:** most offers are **"1+1"**
>    (2nd unit free) or **"1 + 50% off the 2nd"** — and the discounted unit MUST be
>    the **lesser-priced** eligible unit. This is *not* same-line grouping; it pairs
>    units **across the qualifying items** and discounts the cheaper one.

### Cross-item "cheapest-unit" BXGY — deterministic spec
Given the offer's qualifying units (expand each qualifying line into `qty` unit
prices), for a `buy B get G at P%` offer:

1. Build the flat list of eligible **units** (unit price + source line + that
   item's `pos_discp`) across all qualifying lines.
2. Sort by price ascending. Form groups of `(B + G)` units; in each complete group
   the **G cheapest** units are the discounted ones (customer buys the dearer, the
   cheaper is the promo unit) — matching "لازم يكون الصنف الأقل سعرًا".
3. **Magnitude = the discounted unit's own `pos_discp`** (item_card mode):
   `discount = Σ (unit_price × unit.pos_discp / 100)` over the G cheapest units of
   every complete group. (In `offer` mode, use `Offer.value` instead — approval-gated.)
4. Map each discounted unit back to its source line → per-line `cust_discp`. A line
   may be only partly promo (some of its units discounted, some not) → its
   `cust_discp` is the **blended %** = line discount ÷ line gross × 100 (`ROUND_HALF_UP`),
   which is exactly what SOFTECH re-derives on the pending line.

This replaces the current same-line `_bxgy` (which only handled "buy N of the SAME
item"). Both remain valid: add an offer field **`bxgy_scope`** =
`group_cheapest` (default, the cross-item spec above) | `same_item` (existing).
Every unit's before/after price is recorded in the `OfferApplication.detail` for
audit.

### Every transaction audited + flagged (owner requirement)
- `OfferApplication` row per applied offer (already modeled), plus a per-line
  marker (`SoftechSalesOrderLine.applied_offer` FK + `discount_source='offer'`) so
  the order and each discounted line are unambiguously flagged as offer-driven.
- The push writes these in the **same transaction** as the SOFTECH pending write —
  no order can post an offer discount without its audit row.

---

## 6. Loyalty / points interaction (already safe — no double-count)

Confirmed in `writer.py` (lines ~928–939): **native SOFTECH awards points ⊻
discounts** — any line with `custdiscp>0` earns **0 points** (a PIC is either a
points customer or a discount customer). The writer already enforces this.

**Consequence:** applying an offer to a line trades that line's points for the
discount. This is correct native behavior and carries **zero double-count risk** —
offers never grant points, and the discounted line's points auto-zero.

**Design rule:** the plan surfaces "points forgone" so staff/customer see the
trade-off; execution changes nothing about points math (the writer owns it).

---

## 7. Idempotency, audit, usage limits

- **Idempotency:** rides the EXISTING mechanisms — `SoftechSalesOrder.client_token`
  (unique) + the writer's `vf2`/comments `softech_token` pending marker
  (`_pending_docnumber_by_vf2`). A replayed push finds the existing pending doc and
  does **not** re-post. OfferApplication rows are keyed to `(pos_order, offer)` so a
  retry never duplicates them.
- **Audit (rule 8):** `OfferApplication` (already modeled) written at push:
  `offer, customer, branch, pos_order, discount_amount (SOFTECH-recomputed),
  was_applied, reason, detail{per-line, before/after}`.
- **Usage limits:** ✅ **BUILT (step 4)** — `apps/offers/usage.py`. `offer_exhausted`
  is wired into the engine's eligibility so an offer past `max_uses_total` /
  `max_uses_per_customer` **never attaches** (rejected with a reason). `consume_offer_uses`
  (called by the push in step 5) flips this order's `OfferApplication` to
  `was_applied=True` under **`select_for_update`** on the Offer row — two concurrent
  cashiers can't both take the last use (the loser gets `UsageLimitExceeded`);
  idempotent per order. A **real threaded test** confirms the serialization on PG.
  8 tests.

---

## 7b. Detect pre-existing MANUAL offer transactions (owner requirement) — ✅ BUILT (step 2)

> **BUILT, read-only, no SOFTECH writes.** `apps/offers/detection.py` +
> `ManualOfferMatch` model (mig offers/0004) + `detect_manual_offers` command +
> `GET /api/offers/manual-matches/` + `POST /api/offers/detect-manual/`
> (admin/supervisor/purchasing). Scans `customers_purchasehistoryline`
> (`disc_customer_pct>0`, sales only) with full-invoice context; classifies
> exact_offer (HIGH) / bxgy_cheapest 1+1·1+½ (MEDIUM) / unmapped_discount (LOW);
> idempotent update-in-place. 9 tests. Details below were the spec.

Before/after go-live, cashiers have been applying these promos **by hand** in
SOFTECH. Owner asks that such historical transactions be **detected and flagged**
so reporting is complete and we can reconcile module vs manual.

Approach (read-only, PG mirror first; SOFTECH read only if needed):
- Scan `customers_purchasehistory(line)` (the synced sales mirror) for **discount
  fingerprints** that match an offer's shape, e.g.:
  - a line whose effective discount ≈ an active/ां historical offer's `cust_discp`
    on a qualifying item, or
  - a **cheapest-unit pattern**: within one invoice, two eligible items where the
    lesser-priced one carries ~50%/100% discount and the dearer none (a hand-keyed
    1+1 / 1+½).
- Emit a **`ManualOfferMatch`** record (new PG table): `invoice, line(s), matched
  offer (nullable — may be "unmapped promo"), confidence, detected_at`. **Never
  writes to SOFTECH; never mutates the invoice.** It's a detection/annotation layer.
- Surfaced in offer analytics + flagged in the invoice/receipt views.

> Open question **Q2:** matching precision — do we match only against **defined**
> `Offer` rows (miss promos never entered in the module), or also **infer** likely
> promos from the discount pattern and flag them as "unmapped"? Recommend **both**:
> exact-match to defined offers first, then a pattern-inference pass labelled
> low/medium confidence for review. This is deterministic (fixed thresholds), read
> only, and never auto-creates an Offer.

---

## 8. Approval gate (offer-mode magnitude / margin breach) — ✅ BUILT (step 3)

> **BUILT, PG-only, no SOFTECH push.** `apps/offers/order_attach.py`
> `apply_offers_to_order(order, actor)` — gated by `POS_OFFERS_EXECUTION_ENABLED`
> (default False). Writes each promo line's `cust_discp` + `applied_offer` +
> `discount_source='offer'` (mig pos_orders/0010), recomputes pricing, records
> `OfferApplication` (was_applied=False). When the plan `requires_approval`
> (offer-mode magnitude, or a NON-item_card margin breach — item_card is
> pre-authorized by posdiscp so a genuine free 1+1 needs no sign-off), it raises an
> `apps/approvals` request via `ApprovalService.submit` (get-or-create
> `offer_override` single-step supervisor workflow). `push_order` blocks a LIVE push
> when `push_blocked_by_offer_approval` finds a pending/rejected request — no-op for
> non-offer orders. `POST /api/offers/apply-to-order/`. 7 tests. Original spec below.

When `plan.requires_approval` (offer flagged, margin breached, **or an
authorization-shortfall vs `posdiscp`** per §4):
- `/ready` creates (or references) an **`apps/approvals`** request (reuse
  `ApprovalWorkflowDefinition/Request`; new category `offer_override`).
- Push is **blocked** until a supervisor grants it (server-side — rule 9). The
  order sits in `ready` (not `pushed`).
- Cost/margin remain role-masked in the approval UI (already implemented in the
  evaluate view).

---

## 9. Rollout & safety controls

- **Feature flag:** `POS_OFFERS_EXECUTION_ENABLED` (default **False**), mirroring
  `POS_WRITER_ENABLED`. Off ⇒ offers evaluate + display only; nothing writes.
- **Dry-run:** the writer already supports a dry-run plan on `/push`; offer
  execution reuses it — produce the exact `cust_discp` set + SOFTECH-recomputed
  discounts + audit preview, write nothing.
- **Reconciliation:** the existing `reconcile_pos_orders` read-back confirms the
  pending→final docnumber; OfferApplication is reconciled alongside.
- **Offline:** rides the existing offline queue (`queued` status + `flush`).

---

## 10. Required tests before merge (acceptance criteria)

1. **Money-math incl. SOFTECH recompute** — for every offer type, assert the
   `cust_discp`-derived discount reconciles with the engine amount within the 2-dp
   tolerance (per line + basket). (Extends the 26 engine tests.)
2. **No double-post** — replayed push (same `client_token`) posts once; one set of
   OfferApplication rows.
3. **Idempotent OfferApplication** — retry does not duplicate audit rows.
4. **Points ⊻ discount** — a discounted (offer) line earns 0 points; undiscounted
   lines unaffected; total `personnewbal` matches native.
5. **Authority** — per the chosen D2 policy; offer-sourced vs manual bounds.
6. **Approval gate** — margin-breach/flagged order cannot push without a granted
   approval (server-enforced).
7. **Usage-limit concurrency** — two concurrent pushes can't over-consume a limit.
8. **Dry-run writes nothing** — DB + SOFTECH untouched.
9. **Flag off** — no attach, no write.

Every one of these must pass, plus a **manual dry-run on a real branch** reviewed
by the owner, before `POS_OFFERS_EXECUTION_ENABLED` is turned on anywhere.

---

## 10b. Step 5 — WIRED (flag OFF) + LIVE DRY-RUN PROTOCOL (for owner sign-off)

> **Code wired, but `POS_OFFERS_EXECUTION_ENABLED` stays False — nothing posts an
> offer discount until this protocol passes and the owner flips the flag.**

**What's wired** (`apps/pos_orders/views.py::push_order`, inert for non-offer orders):
1. **Pre-check** (before the SOFTECH write): `usage.precheck_order` → a live push of
   an order whose attached offer is exhausted is refused **409 `offer_usage_exhausted`**;
   the writer is never called.
2. **Post-consume** (only after a confirmed successful live post — not queued, not
   stock-error): `usage.consume_offer_uses` flips this order's `OfferApplication` to
   `was_applied=True` under `select_for_update`. Idempotent; a rare race that
   over-consumes *after* the sale already posted is **logged + flagged**
   (`offer_overuse`), never fails the posted sale.
3. **Offline queue:** a queued order does NOT consume here — its uses are consumed
   when the flush actually posts it (**protocol item Q3 below — wire/verify in flush**).

### Live dry-run protocol (run on ONE reachable test branch, owner present)

**Pre-conditions**
- `POS_OFFERS_EXECUTION_ENABLED=False`, `POS_WRITER_ENABLED=False` initially.
- Pick 2–3 real promo items whose SOFTECH `posdiscp` is already set for the promo
  (a genuine 1+1 ⇒ `posdiscp=100`); confirm `catalog_item.pos_discp` matches after a sync.
- Define the matching `Offer`(s) in the module (item_card mode, target those items).

**A. Evaluation dry-run (no writes at all)**
1. `POST /api/offers/evaluate/ {attach_preview:true}` with a real basket.
2. Verify: the cheaper unit is the promo unit; `cust_discp` per line; `reconciliation.max_line_delta ≤ 0.01`; `requires_approval` correct (false for item_card).

**B. Attach dry-run (PG only)**
3. Turn `POS_OFFERS_EXECUTION_ENABLED=True` on the test node ONLY.
4. Build a real POS order; `POST /api/offers/apply-to-order/`.
5. Verify in PG: each promo line has `discount_source='offer'`, correct `cust_discp`,
   `applied_offer`; `OfferApplication` rows exist `was_applied=False`; order totals
   recomputed. **No SOFTECH write yet** (writer still off).

**C. Push DRY-RUN (writer still off ⇒ push is a dry plan)**
6. `POST /api/pos-orders/{id}/push/` (default dry). Verify the returned payload/SQL
   carries the offer `cust_discp` exactly, and the points block shows **0 points on
   discounted lines** (native ⊻). Compare the plan's discount to §2 reconciliation.

**D. ONE controlled LIVE post** (owner authorises; `POS_WRITER_ENABLED=True` on the
test node, single order)
7. `POST …/push/ {dry_run:false, confirm:true}` for ONE order.
8. Read back in SOFTECH: the pending `stktrans5` line carries the exact `cust_discp`;
   the settled totals match the plan; **no double `stktransm5`** (idempotency);
   points match native. `OfferApplication.was_applied=True`; usage decremented.
9. Have the cashier settle it; reconcile via `reconcile_pos_orders`.

**E. Guards**
10. Exhaust an offer's `max_uses_total`, attempt another live push → **409** (no write).
11. An `offer`-mode / margin-breach order → push blocked until a supervisor approves
    via the approvals inbox, then posts.

**Go / No-Go before enabling anywhere:** every one of steps 2, 5, 6, 8, 10, 11 passes,
and the owner signs off on the reconciled money on the real settled order.

**Rollback:** set `POS_OFFERS_EXECUTION_ENABLED=False` (attaches stop; existing
attached orders keep their `cust_discp` — clear it by re-`/ready` if needed). No
schema rollback required; all columns are additive.

> **Open protocol items:** **Q3** — wire `consume_offer_uses` into the offline
> **flush** path so queued orders consume on eventual post (small, do before turning
> the flag on in production). **Q4** — decide whether a receipt shows the promo as a
> blended line % or an explicit "free item" line (money is identical; presentation only).

---

## 11. Decisions — RESOLVED (owner, this review)

| # | Decision | **Owner's answer** |
|---|----------|--------------------|
| D1 | Amount→% rounding | **Round in customer's favour** (`ROUND_HALF_UP`) — mother company compensates, minor over-discount OK |
| D2 / Q1 | Where the discount magnitude comes from | **Item card `posdiscp` IS the magnitude** (item_card mode); offer defines only structure. Exception: `offer`-mode promos carry their own %, **approval-gated before saving to the cashier** |
| D3 | BXGY shape + manual stacking | **Offer wins over manual**; BXGY is **cross-item, cheapest-unit** (1+1 / 1+½ on the lesser-priced item), magnitude = that unit's `posdiscp` — must be built + tested. Every txn audited + flagged |
| D3+ | Detect historical manual promos | **Yes** — detection/annotation layer over the sales mirror (§7b), match-defined **+ infer unmapped** |
| D4 | SOFTECH reachable for live dry-run | **Yes, reachable** |

**All blocking questions resolved.** Remaining detail settled at build time:
per-item `pos_discp` is read from the synced PG mirror (`catalog_item.pos_discp`);
`offer`-mode approval reuses `apps/approvals` (§8).

---

## 12. Proposed build order (only after Q1 answered)

**Step 1 — PG-only, ZERO SOFTECH writes — ✅ BUILT (50 offers tests):**
- Engine enhancement: **cross-item cheapest-unit BXGY** (`bxgy_scope=group_cheapest`,
  `_bxgy_group_cheapest`) — the G cheapest units of every complete (B+G) group are the
  promo units. Magnitude source via `authorization_source`: `item_card` → discounted
  unit's own `Item.pos_discp` (a genuine 1+1 = posdiscp 100); `offer` → `Offer.value`/
  `get%`, always `requires_approval`. `item_card` percent/fixed/qty_tier capped at
  each line's `pos_discp` (`_cap_to_posdiscp`). Mig `offers/0003`.
- **Attach service** `offers/attach.py::build_attach_plan` — engine plan → per-line
  `cust_discp` (amount÷gross×100, `ROUND_HALF_UP`) + SOFTECH-recompute via
  `pos_orders.pricing.compute_line`; returns `reconciliation.max_line_delta`
  (≤ 0.01/line). **DRY-RUN only, no persistence, no SOFTECH contact.** Exposed at
  `POST /api/offers/evaluate/ {attach_preview:true}` (`offersApi.attachPreview`).
- Tests: `test_offers_bxgy_execution.py` (14) — 1+1, 1+½, per-item posdiscp magnitude,
  multi-group cheapest, offer-mode approval, same-item scope, item-card cap, attach
  reconciliation (delta 0 / within tolerance), dry-run API.
- **Not yet done in step 1 (deferred to execution steps):** the `applied_offer` FK +
  `discount_source` columns on `SoftechSalesOrderLine`, and writing cust_discp onto a
  real order — those land with step 3+ so the marker + audit ship together with the
  gated write. Step 1 proved the math + conversion end-to-end without touching orders.
- No write path touched; `POS_OFFERS_EXECUTION_ENABLED` stays off.

**Step 2 — detection layer (read-only, §7b):** `ManualOfferMatch` scan over the
sales mirror; analytics/flags. No writes.

**Step 3 — approval gate (reuse `apps/approvals`):** server-enforced push block for
margin/shortfall/flagged offers.

**Step 4 — usage-limit commit + concurrency** (`select_for_update`).

**Step 5 — execution ON:** flip `POS_OFFERS_EXECUTION_ENABLED` only behind a live
dry-run on the reachable SOFTECH, reviewed by the owner. The live write is the
EXISTING `writer.py` posting the `cust_discp` it already posts today — no new Sybase
write path anywhere in steps 1–5.

---

## 13. Channel A live write (A2) + the SOFTECH Ctrl+M / OFFERS discount override

### 13.1 A2 — the gated posdiscp write (WIRED, flag OFF)
`apps/offers/channel_a.py::apply_posdiscp` performs the live Channel-A write, gated
FOUR ways (any missing ⇒ dry-run plan only, zero SOFTECH contact):
1. `settings.POS_OFFERS_POSDISCP_WRITE_ENABLED` (default **False**)
2. `commit=True`  3. `confirm=True` (anti-fat-finger)  4. actor has a linked
`StaffProfile.softech_user_id` (author stamp).
The write mirrors `discount_approvals.alignment`: `UPDATE items SET posdiscp=?,
usercode=?, itemlastupdate=GETDATE() WHERE itemcode=?` → SSB9 replicates HQ→branches,
**read-back verified per item**, PG `Item.pos_discp` updated only on a verified write,
per-item isolation. Endpoint `POST /api/offers/{id}/posdiscp-apply/` (admin;
409 `requires_confirm` until confirmed). **Before enabling:** review a real
`posdiscp-plan` on a live offer, run one item as a controlled write, read it back.

### 13.2 The Ctrl+M / OFFERS override (walk-in POS discount authority)
On the SOFTECH indirect-POS screen, **Ctrl+M** opens a "different user max-discount"
prompt; entering user **`OFFERS`** / `123456` elevates the current user's max POS
discount to **100%** for the transaction. Mechanically this is the seller-ceiling
check (`managerdiscount.max_custdiscp`) being overridden by the `OFFERS` user's own
ceiling (=100). It is how a cashier keys a 1+1 (100% on the 2nd line) today.

**Our side (done):** `discount_authority.check_order` now **skips offer-sourced
lines** (`discount_source='offer'`) — the approved offer is the authority, the direct
analogue of the `OFFERS` override — so our `/ready` never rejects an offer discount
for exceeding the normal user's ceiling.

**The open question (must be answered in the live dry-run, §10b step D):** when the
cashier **settles** our pending order, does SOFTECH **re-validate** the line discount
against the seller's ceiling?
- If **NO** (the gate is client-side only, at data entry) → our direct `stktrans5`
  write already bypasses it; high offer discounts settle cleanly. **No further work.**
- If **YES** → we must replicate whatever Ctrl+M stamps so settlement accepts it —
  e.g. write the pending order under an authorized seller/authority, or set the
  override field the native screen writes.

### 13.3 Read-only investigation (owner runs; informs the answer above)
```sql
-- 1. the OFFERS user's usercode + its max-discount rows
SELECT usercode, userid FROM SOFTECHDB9.dbo.users WHERE userid = 'OFFERS';
SELECT personcode, branchcode, max_custdiscp
  FROM SOFTECHDB9.dbo.managerdiscount WHERE personcode = <OFFERS usercode>;
-- 2. compare a Ctrl+M-overridden sale vs a normal one: diff stktransm + stktrans
--    columns to spot any 'override user / authority' stamp the screen writes.
```
Findings feed the writer design: if a stamp exists, `pos_orders/writer.py` sets it on
offer orders; if not, nothing to do. **Gated — no code writes this until confirmed.**

### 13.4 RESOLVED (2026-08-30, live DB query via `investigate_override`)
- `OFFERS` = **usercode 89**; `managerdiscount[89] = 100%` on every branch.
- **The override IS stamped on the header: `stktransm5.supp_main_code = '89'`** (empty
  on a normal sale). No line-level stamp. SOFTECH repurposes that column for the
  authorizing manager on a POS sale.
- **Answer to the §13.2 open question:** a settled offer line DOES need the override,
  and replicating it is trivial — set `supp_main_code = <override usercode>` on the
  header. **WIRED:** `writer._header_row` sets `supp_main_code =
  POS_OFFERS_OVERRIDE_USERCODE` (default `'89'`) whenever the order has an
  offer-sourced discounted line, else `''`. Offer discounts are now pre-authorized
  exactly like a manual Ctrl+M sale. Final confirmation is the §10b live dry-run
  (post one offer order → cashier settles → discount holds).

---

## 14. Channel C — ONE-ORDER LIVE DRY-RUN runbook (for the owner)

Goal: post exactly ONE offer-discounted order to SOFTECH on a test branch, have a
cashier settle it, and confirm the discount holds + `supp_main_code=89` is written.
This is the final confirmation before flipping `POS_OFFERS_EXECUTION_ENABLED`.

**Prep (test node only)**
1. Pick a cheap test item; note its code. Set (or confirm) its `posdiscp = 100` in
   SOFTECH so a 1+1 is authorized. Re-sync so `catalog_item.pos_discp` = 100.
2. In `/offers`, create an offer: type **bxgy**, `buy=1 get=1`, scope `group_cheapest`,
   `authorization_source=item_card`, target = that item, status **active**,
   `require_stock` off (or ensure branch stock).
3. Turn ON, on the test node ONLY: `POS_OFFERS_EXECUTION_ENABLED=True`,
   `POS_WRITER_ENABLED=True`. Leave every other node OFF.

**Run (one order)**
4. Build a POS order (`/pos`) at the test branch with **2 units** of that item.
5. `POST /api/offers/apply-to-order/ {order:<id>}` → confirm in the response/PG: the
   cheaper line has `discount_source='offer'` and `cust_discp≈100`; `requires_approval`
   is false (item_card).
6. `POST /api/pos-orders/<id>/push/ {dry_run:true}` first → check the plan/points show
   **0 points on the discounted line**.
7. `POST …/push/ {dry_run:false, confirm:true}` → it should return `pushed` (not
   queued). Note the SOFTECH `docnumber`.

**Verify (read-back — read-only)**
8. Run: `python manage.py investigate_override --override <docnumber> --normal <docnumber>`
   (or query directly). Confirm on the pending rows:
   - `stktrans5.custdiscp` on the promo line ≈ 100 (the offer discount is there);
   - **`stktransm5.supp_main_code = '89'`** (the override stamp we now write);
   - one header only (no double `stktransm5`).
9. Have the cashier **settle** the order in SOFTECH. Confirm: it settles **without**
   prompting for a manager discount, and the **discount holds** on the final sale.
   (This is the answer to §13.2 — if it settles clean, the stamp works.)
10. Confirm points on the final sale match native (0 on the discounted line).

**Result**
- All of 5–10 pass → `POS_OFFERS_EXECUTION_ENABLED` is safe to enable. Turn
  `POS_WRITER_ENABLED` back to its normal setting; roll the offers flag out per branch.
- Any step fails → turn both flags OFF (rollback; attached `cust_discp` clears on a
  fresh `/ready`) and paste the read-back — no data is stranded.
