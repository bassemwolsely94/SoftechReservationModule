# 13 — Demand Module Evolution Roadmap

**Status:** ✅ COMPLETE — Phases 0 · 1 · 1b · 2 · 3 · 4 all done, plus §14 module notifications (+RBAC). All four loops shipped.
**Author/date:** drafted 2026-06-11; completed 2026-06-12.
**Purpose:** Turn `apps/demand` from a passive lost-sales log into an active, long-term
sales-recovery and demand-intelligence engine — without duplicating the statistical
lost-sales engine that already lives in `apps/purchasing` (MODULE 13).

> Read [12_PROJECT_CONTEXT_SUMMARY.md](12_PROJECT_CONTEXT_SUMMARY.md) and
> [11_ERP_INDEX.md](11_ERP_INDEX.md) first. This doc assumes that context.

---

## 1. The strategic thesis

The pharmacy already has three demand-capture surfaces. They are **not** redundant —
each owns a different point on the supply-certainty axis:

| Surface | Trigger | Supply state | Time horizon | Owns |
|---|---|---|---|---|
| **Reservation** (`apps/reservations`) | Customer wants an item **we have** | Certain | Hours–days | Hold → convert to a sale |
| **Demand** (`apps/demand`) | Customer wants an item **we don't have** | Absent / insufficient | Days–months | Source it, or lose it — **with the customer's identity attached** |
| **Lost-Sales Engine** (`apps/purchasing` MODULE 13) | Nightly batch | Inferred from ERP sales gaps | Rolling 30d | **Statistical** EGP loss + root cause, per item×branch, **no customer** |

**Demand's unique, un-replicable asset = a named customer + a specific unmet item + a phone number.**
Neither Reservations nor the purchasing engine can ever have this. Every feature below is
built to exploit that asset. Anything that does *not* need customer identity belongs in the
purchasing engine, not here.

### Do-not-duplicate boundary
- `apps/purchasing` MODULE 13 ([lost_sales_engine.py](../../apps/purchasing/lost_sales_engine.py))
  already computes `stockout_days_30d`, `lost_qty_30d`, `lost_revenue_30d`,
  `lost_margin_30d`, `availability_rate_30d`, and a `root_cause` waterfall — **statistically,
  for all 30k item×branch pairs.** We will **consume** these numbers and **reconcile** against
  them. We will **not** recompute network-wide statistical loss inside `apps/demand`.

---

## 2. The three closed loops

```
                        ┌─────────────────────────────────────────────┐
                        │  DEMAND RECORD  (named customer + item)      │
                        └─────────────────────────────────────────────┘
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        ▼                                 ▼                                 ▼
  LOOP 1 RECOVERY                  LOOP 2 VALUATION                 LOOP 3 PROCUREMENT
  item back in stock →            snapshot price at capture →      real human asked →
  trace customer back →           confirmed lost EGP per           highest-confidence
  win the sale back →             customer/item/reason →           buy signal + in-stock
  record recovered_revenue        reconcile vs purchasing          substitution at capture
```

These map to the user's stated goals:
- "trace those customers back … if the item is available at any point" → **Loop 1**.
- "valuate [lost sales] on the long term" → **Loop 2**.
- "boost sales on the long term … not the short term" → **Loops 1 & 3** (recovery + buying the
  right things), with substitution (Loop 3) as the one deliberate short-term conversion that
  *also* enriches the long-term dataset.

---

## 3. Current-state inventory (what we build on, not around)

Confirmed by reading the code on 2026-06-11:

- **`DemandRecord`** ([models.py:28](../../apps/demand/models.py)) — 9-state machine, phone (mandatory),
  `customer_name`, `customer` FK, `phcode`, `branch`, priority, source, `lost_reason`, SLA props.
- **`DemandItem`** ([models.py:259](../../apps/demand/models.py)) — `item` FK (nullable) or `item_name_free`,
  `quantity`, `demand_type`, `item_status` (pending/sourcing/fulfilled/lost/cancelled),
  `is_long_shortage`, `is_discontinued`. Has live `stock_at_branch` / `stock_network_total` props.
  **No price field anywhere.**
- **`FollowUpTask`** ([models.py:370](../../apps/demand/models.py)) — already has a `stock_check` type.
  Reuse for recovery tasks; do **not** invent a new task model.
- **`DemandLog`** ([models.py:436](../../apps/demand/models.py)) — the module's chatter. Reuse for all
  recovery/valuation events (Golden Rule: never create a new chatter implementation).
- **`ItemDemandStat`** ([models.py:519](../../apps/demand/models.py)) — per item×branch 30d counts,
  `suggest_order`, `suggest_transfer`. Updated by `service._update_item_stats`.
- **`service.py`** — `create_demand`, `transition_status` (state machine `VALID_TRANSITIONS`),
  `schedule_followup`, ERP enrichment, notifications.
- **Stock hook** — [`sync_stock()` in sync/tasks.py:666](../../apps/sync/tasks.py) bulk-upserts
  `ItemStock.quantity_on_hand` every sync. **This is the restock trigger for Loop 1.**
- **Catalog fields available** — `Item.pack_price`, `Item.unit_price`, `Item.cost_price`,
  `Item.name_scientific`, `Item.is_active` ([catalog/models.py:21](../../apps/catalog/models.py)).

---

## 4. Phase 0 — Foundation: price snapshot (prerequisite for Loops 1 & 2)

> **STATUS: ✅ DONE (2026-06-11)** — migration `demand/0003`. Implemented the snapshot in
> `DemandItem.save()` (not only `service.create_demand`) so **every** creation path is covered
> (service, the `add_item` action, admin) and a frozen value is never overwritten. Fields are
> read-only in the API. Verified: priced line snapshots correctly, free-text line stays null,
> `potential_value` sums priced lines only.

ERP prices drift, so loss/recovery value must be frozen at capture time.

**Schema (additive, one migration):** add to `DemandItem`
| Field | Type | Source |
|---|---|---|
| `unit_price_snapshot` | `Decimal(12,2)` null | copy of `item.pack_price` at create |
| `cost_price_snapshot` | `Decimal(12,2)` null | copy of `item.cost_price` at create (for margin) |
| `price_snapshot_at` | `DateTime` null | set when snapshot taken |

**Logic:** in `service.create_demand`, after creating each `DemandItem` with a real `item`,
copy the three values. Free-text items (`item_name_free`) get null (unknowable).

**Computed props on `DemandItem`:**
- `line_value = quantity × unit_price_snapshot`
- `line_margin = quantity × (unit_price_snapshot − cost_price_snapshot)`

**Computed prop on `DemandRecord`:** `potential_value` = Σ line_value over items.

No new endpoints; surface these fields in the existing `DemandItemSerializer` /
`DemandDetailSerializer`. **~0.5 day.** Everything else depends on this.

---

## 5. Phase 1 — Loop 1: Back-in-stock recovery (the headline differentiator)

> **STATUS: BACKEND ✅ + UI ✅ DONE (2026-06-11)** — migrations `demand/0004`, `notifications/0014`.
> Backend (rolled-back tests): eligibility rule, restock detection wired into `run_full_sync`,
> recover/notified/disqualify/requalify/opt-out endpoints, recovery queue, dashboard ROI KPIs,
> monthly-reminder section in `send_followup_reminders`. Also fixed a latent bug: `demand/service.py`
> used `models.Q` without importing `models`, so new-demand and status-change notifications were
> silently failing — now fixed.
> UI (`frontend` build green): `/demand/recovery` page with ROI tiles + value-sorted worklist +
> WhatsApp/recover/opt-out/disqualify actions, and a "🔔 عاد للمخزون" tab with an open-count badge
> on the demand header. API client methods added.
> **PENDING:** the Demand↔Reservation bridge (§5.9, **Phase 1b**). Separately requested:
> module-scoped notifications for demand + followups (see §14).
>
> **Found (pre-existing, not fixed):** `DemandDashboardPage.jsx` reads a flat response shape
> (`data.total`, `data.lost`, `data.lost_value_egp`…) but `demand_dashboard` returns nested `{kpis:…}`
> — so most of that page's tiles render `—`. Flagged for a separate fix.

### 5.1 Concept
When an item that some customer asked for (open or lost-for-no-stock demand) comes back
into stock, the system **proactively traces those customers back** and drives a win-back,
then **measures the recovered revenue** so the module proves its own ROI.

### 5.2 State model changes
Add two `DemandItem.item_status` values:
- `available_again` — stock detected; customer not yet recovered.
- `recovered` — customer came back and bought (terminal-success).

Add to `DemandItem`:
| Field | Type | Meaning |
|---|---|---|
| `back_in_stock_at` | `DateTime` null | when restock was detected |
| `notified_customer_at` | `DateTime` null | when we last reached out (used for monthly-reminder cadence) |
| `recovered_at` | `DateTime` null | when the win-back sale happened |
| `recovered_revenue` | `Decimal(12,2)` null | actual recovered EGP (defaults to line_value) |
| `reservation` (FK → `reservations.Reservation`) | null | set when a recovery is converted into a Reservation (§5.8) |
| `contact_opt_out` | `Boolean` default False | customer asked not to be contacted again **about this item** (§5.9) |
| `contact_opt_out_reason` | `CharField` blank | why (not_needed / moved / for_other_person / other) |
| `contact_opt_out_at` | `DateTime` null | when opt-out was recorded |
| `disqualified` | `Boolean` default False | excluded from the recovery loop by approval (§5.7) |
| `disqualified_reason` | `CharField` blank | not_in_egypt / discontinued / not_allowed / unknown_item / never_available / other |
| `disqualified_by` (FK → `users.StaffProfile`) | null | who approved the disqualification |
| `disqualified_at` | `DateTime` null | when |

> **Eligibility rule (single source of truth):** a `DemandItem` is "recovery-eligible" iff
> `disqualified = False` **AND** `contact_opt_out = False` **AND** the parent record was created
> within the **recovery window of 12 months** **AND** `item_status` ∈ {pending, sourcing,
> available_again, or lost with `lost_reason = no_stock`}. Everything downstream (detection sweep,
> recovery queue, reminders) filters on this one rule.

### 5.3 Detection — where the trigger fires
Two options; **recommended = B** (decoupled, cheap, no per-row signals during a 30k bulk sync):

- **Option A (signal):** `post_save` on `ItemStock`. Rejected — `sync_stock` uses
  `bulk_create(update_conflicts=...)`, which **does not fire signals**, and per-row signals
  would be a performance problem.
- **Option B (post-sync sweep) ✅:** a new service `detect_restocked_demand()` called once at
  the end of a stock sync (hook next to the existing post-sync steps in `sync/tasks.py`). It runs
  **one SQL query**: items that (a) currently have `quantity_on_hand > 0` at a branch, and
  (b) have **recovery-eligible** `DemandItem`s for that branch (per the §5.2 eligibility rule —
  i.e. within the **12-month window**, not disqualified, not opted-out). For each match:
  flip `item_status → available_again`, stamp `back_in_stock_at`, create a `stock_check`
  `FollowUpTask`, write a `DemandLog.system`, and emit a `Notification`. **Never** matches a
  disqualified or opted-out line — that's what keeps "weird"/never-available items out of the queue.

### 5.4 Recovery actions — human-in-the-loop (DECISION: never fully automated)
Outreach is **always operator-initiated**. The system surfaces the opportunity and prepares the
message; a human decides to send.
- **Task:** `schedule_followup(demand, task_type='stock_check', …)` — already exists.
- **Notification:** branch pharmacist + call_center, via the existing `_notify_*` pattern in
  `service.py`. New `notification_type='demand_back_in_stock'`.
- **WhatsApp (operator-triggered):** a **"Send WhatsApp"** button on the recovery-queue row sends
  "صنف {name} متوفر الآن في {branch}" via the existing campaigns/notifications integration.
  Stamps `notified_customer_at` and writes a `DemandLog(log_type='whatsapp')`. No auto-send.
- **Closing the loop:** `POST /api/demand/{id}/items/{item_id}/recover/` sets `recovered`,
  stamps `recovered_at`, captures `recovered_revenue`, and (optionally) converts to a Reservation (§5.8).

### 5.5 Monthly reminder cadence (DECISION: at least monthly until resolved)
An open recovery opportunity must not be forgotten. A scheduled job (extend the existing
`generate_followup_tasks` / `send_followup_reminders` commands — do **not** add a new scheduler)
re-surfaces any `available_again` line whose `notified_customer_at` is null or older than **30 days**,
creating/refreshing a `stock_check` `FollowUpTask` and notifying the assignee. Stops when the line
becomes `recovered`, `disqualified`, `contact_opt_out`, or ages past the 12-month window.

### 5.6 New endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/demand/recovery-queue/` | recovery-eligible items in `available_again`, branch-scoped, sorted by value |
| POST | `/api/demand/{id}/items/{item_id}/recover/` | mark recovered + capture revenue (optionally → Reservation, §5.9) |
| POST | `/api/demand/{id}/items/{item_id}/notified/` | stamp `notified_customer_at` (also set by WhatsApp send) |
| POST | `/api/demand/{id}/items/{item_id}/disqualify/` | approval-gated removal from the loop (§5.8) |
| POST | `/api/demand/{id}/items/{item_id}/opt-out/` | record item-level contact opt-out (§5.10) |

### 5.7 UI
- New **"عاد للمخزون / Recovery Queue"** tab on the Demand page — a worklist of customers to
  call, sorted by `line_value` desc, showing phone, item, days-waited, current branch stock,
  a **Send WhatsApp** button, and **Recover / Disqualify / Opt-out** actions per row.
- KPI tiles on the Demand dashboard: **Recovered revenue (30d)**, **Recovery rate %**,
  **Open recovery opportunities (EGP)**.

### 5.8 Disqualification gate (DECISION: approval-gated elimination of non-recoverable demand)
Some demand can never be a genuine recoverable lost sale and must be kept out of the loop:
item **not available in Egypt**, **discontinued**, **not allowed to be sold by the pharmacy**,
**unknown item**, or otherwise **never available**. These are disqualified — but only with
**human/managerial approval** to avoid an operator silently hiding real demand.

- Action `POST …/disqualify/` requires `disqualified_reason` ∈ {`not_in_egypt`, `discontinued`,
  `not_allowed`, `unknown_item`, `never_available`, `other`} and is **permission-gated** (approve
  permission on the `demand` module — see RBAC matrix). Stamps `disqualified_by` / `disqualified_at`,
  writes a `DemandLog`, and the line drops out of every recovery query via the §5.2 eligibility rule.
- Reversible by the same permission (un-disqualify) if it was a mistake.

### 5.9 Demand ↔ Reservation bridge (DECISION: bidirectional, approval-gated)

> **STATUS: ✅ DONE (2026-06-12, Phase 1b)** — no new migration (reuses the
> `DemandItem.reservation` FK from `0004`, which also gives idempotency in both
> directions). Verified end-to-end (rolled-back tests). Forward: recovery-queue
> "حجز" button → `POST /demand/{id}/items/{item_id}/to-reservation/`
> (gated `reservations.create`) creates a `status='available'` Reservation, links the
> line, marks it recovered. Reverse: reservation-detail "تحويل لطلب ضائع" button
> (shown for expired/cancelled) → `POST /demand/from-reservation/`
> (gated `demand.approve`) creates a lost `DemandRecord` (price-snapshotted),
> optionally disqualifying it on convert to keep non-recoverable items out of the
> loop. Auto-expiry stays automatic; only the *conversion* is gated.

Both directions are explicit, logged, and require approval — we **link**, never fork intake (respects DUP-001).
- **Recovered demand → Reservation:** when an `available_again` line is recovered and the item is
  in stock at the branch, the operator may convert it into a `Reservation` (hold for pickup). Sets
  `DemandItem.reservation`, marks the line `recovered`, logs both sides. Needs `reservations.create` permission.
- **Expired/incomplete Reservation → lost Demand:** an expired or abandoned Reservation can be
  converted into a lost `DemandRecord` (`lost_reason='no_stock'` or appropriate), so the unmet
  intent re-enters the demand dataset — **but only after human/managerial approval**, and the
  disqualification gate (§5.8) applies so junk items don't pollute the recovery loop. Hook point:
  the existing `_auto_expire_reservations` job ([sync/tasks.py:1657](../../apps/sync/tasks.py)) flags
  candidates; a human approves the conversion. (Auto-expiry stays automatic; the *conversion* is gated.)

### 5.10 Item-level contact opt-out (DECISION: consent captured after first follow-up)
After the **first** outreach, a customer may decline further contact **about that specific item**
(reasons: item no longer needed, customer moved away, was buying for someone else, etc.). Recording
it sets `contact_opt_out=True` + reason + timestamp, which removes the line from the recovery loop
via the §5.2 eligibility rule. Scope is **per `DemandItem`** (this item only) — a global customer
do-not-contact is out of scope here and, if needed, belongs in the `customers` module.

### 5.11 The ROI metric
`recovered_revenue` summed over 30/90d is the single number that proves the module pays for
itself. Surface it on the dashboard and in `demand_dashboard` ([views.py:348](../../apps/demand/views.py)).

**Estimate:** ~3–4 days (detection sweep + state + endpoints + bridge + disqualify/opt-out gates + recovery tab).

---

## 6. Phase 2 — Loop 2: Confirmed customer-level valuation

> **STATUS: ✅ DONE (2026-06-12)** — migration `demand/0005`. Persisted
> `ItemDemandStat.lost_value_30d` (Σ qty×frozen price of lost lines), populated in
> `service._update_item_stats`. New `GET /api/demand/lost-value-reconciliation/`
> joins confirmed (named) lost value against the purchasing engine's *inferred*
> `ItemDemandAggregated.total_lost_revenue_30d` (latest `calc_date`) → per-item
> coverage % + overall coverage. UI: a reconciliation table on the demand dashboard
> (confirmed vs inferred vs coverage, color-graded). Verified end-to-end (confirmed
> 180 vs real inferred 103k → 0.2% coverage). Cost-price caveat honored: valuation
> uses `pack_price` (populated); margin is not asserted where cost is 0/None.
>
> Also cleaned up two pre-existing issues: the `DemandDashboardPage` flat-vs-`{kpis}`
> shape mismatch (rebound to the real response; `?days=` window now functional;
> added `sla_breached`, `lost_value_30d`, `top_lost_items`, `discontinued`), and the
> `send_followup_reminders` Windows-console emoji crash (safe-stdout wrapper).

### 6.1 Concept
With Phase 0 price snapshots in place, every lost demand line now carries a **confirmed** EGP
value attached to a **named** customer and a **stated reason** — something the statistical
engine structurally cannot produce.

### 6.2 Aggregations (extend `ItemDemandStat`, don't add a model)
Add to `ItemDemandStat`:
- `lost_value_30d` (Decimal) — Σ line_value of lost items, item×branch.
- (already has `lost_qty_30d`, `lost_count_30d`.)

Update `service._update_item_stats` to also sum value.

### 6.3 Reconciliation view (the credibility feature)
A read-only endpoint `GET /api/demand/lost-value-reconciliation/` that puts the two estimates
side by side per item:
| item | confirmed_lost_value (demand) | inferred_lost_revenue_30d (purchasing) | coverage % |
|---|---|---|---|

Joins `ItemDemandStat` (this module) with `purchasing.ItemDemandAggregated.total_lost_revenue_30d`.
"Coverage %" = how much of the inferred loss we actually captured a named customer for. Rising
coverage = the capture discipline is improving. **Read-only join; no new write paths.**

### 6.4 UI
- Demand dashboard: **Confirmed lost EGP (30d)** tile + **lost-by-reason (value-weighted)** chart
  (the existing `lost_by_reason` is count-only — add a value variant).
- Per-customer: an **"unmet demand"** strip on the customer profile (see Phase 4).

**Estimate:** ~1.5 days.

---

## 7. Phase 3 — Loop 3: Procurement signal + substitution

> **STATUS: ✅ DONE (2026-06-12)** — migration `demand/0006`.
> **Value-weighted buy signal:** `_update_item_stats` now sets `suggest_order` when
> `lost_count_30d ≥ 3` **OR** `lost_value_30d ≥` a config threshold
> (`demand_suggest_order_value_threshold`, default 1000 EGP, seeded in `seed_config`).
> Dashboard `suggest_order` list is value-sorted and exposes `lost_value_30d`.
> Verified: a single 1,824 EGP lost line (count=1) now flags for purchase.
> **Substitution at capture:** `GET /api/demand/substitutes/?item=&branch=[&network=]`
> + `service.find_substitutes` returns in-stock same-`name_scientific` alternatives;
> a "💊 بدائل متوفرة" strip with one-click add appears in **both** the create modal AND the
> demand-detail item rows (self-hiding when none / for open demands), and the chosen line
> records `DemandItem.substitute_for_item` (a queryable acceptance signal).
> **⚠️ Data-safety guard (critical):** catalog scientific names are dirty — the placeholder
> `"UnDefined Item"` groups **353 unrelated products**, so naïve matching suggested an
> antidepressant as a substitute for a slimming product. `find_substitutes` now rejects a
> blocklist of placeholders **and** any "molecule" whose group exceeds `_MAX_MOLECULE_GROUP=40`
> (implausible for a real INN). Verified: junk molecule → 0 results; real molecule → correct
> in-stock matches only.

### 7.1 Value-weighted buy signal
`ItemDemandStat.suggest_order` is currently `lost_count >= 3` ([service.py:310](../../apps/demand/service.py)).
Upgrade to value-aware: also suggest when `lost_value_30d >= threshold` (config-driven). Feed the
**named-demand** signal into the purchasing hub as a distinct, higher-confidence input
(a real person asked, vs. a statistical inference). Surfaced in the existing Procurement UI, not a new one.

### 7.2 Therapeutic substitution at capture (the one intentional short-term win)
When a `DemandItem` is added for an out-of-stock item, look up catalog items with the **same
`name_scientific`** that have `quantity_on_hand > 0` at the branch (or network). Offer the
operator an immediate swap → convert now. Captured as a `DemandLog` event
(`substitution_offered` / `substitution_accepted`) so we still learn from it.

- New endpoint: `GET /api/demand/substitutes/?item={id}&branch={id}` → in-stock same-molecule items.
- UI: an inline "بدائل متوفرة / Available alternatives" suggestion in the create modal and the
  demand detail item row.

This deliberately *does* drive short-term sales — but because it's logged, it strengthens the
substitution dataset (which molecules customers accept swaps for) rather than hiding demand.

**Estimate:** ~2 days.

---

## 8. Phase 4 — Customer unmet-demand profile (CRM / churn amplifier)

> **STATUS: ✅ DONE (2026-06-12)** — no new migration (read-only join + a churn-signal
> tweak). New `GET /api/customers/{id}/unmet-demand/` matches demands by **customer FK OR
> phcode OR phone/phone_alt** (demands aren't always FK-linked), returns unmet lines
> (pending/sourcing/available_again/lost) with status, value, days-waited + a summary.
> UI: a "🧩 طلبات لم تُلبَّ" strip on the Customer detail page (above the tabs, renders only
> when unmet demand exists); each row links to its demand where recovery actions live.
> **Churn signal:** strengthened the existing `segment_customers` `demand_map` to count
> **open AND recent-lost** demands (lost = stronger frustration signal; 180-day window) — it
> already feeds `_compute_risk_score` (≤20 pts) and `_compute_churn_score` (5% factor). No
> churn maths duplicated here, per the original plan. Verified: phone-matched demands returned
> correctly (summary `{open:1, lost:1, value:135}` for an unlinked customer).

The compounding long-term play: roll demand up **per customer**, not just per item.

- `GET /api/customers/{id}/unmet-demand/` — every item this customer asked for and didn't get,
  with status (lost / awaiting / recovered) and value.
- Surface a strip on the Customer detail page: "طلبات لم تُلبَّ" with one-click "notify when back".
- Feed `customers` segmentation / churn scoring: a chronic patient whose refill we **repeatedly**
  miss is a high-value churn risk — exactly the signal CRM wants. Coordinate with the existing
  `segment_customers` command rather than computing churn here.

**Estimate:** ~1.5 days. Depends on Phases 0–2.

---

## 9. Consolidated schema changes (all additive, no drops/renames)

`DemandItem` (Phases 0 + 1):
```
# Phase 0 — price snapshot
unit_price_snapshot    Decimal(12,2) null
cost_price_snapshot    Decimal(12,2) null
price_snapshot_at      DateTime null
# Phase 1 — recovery
back_in_stock_at       DateTime null
notified_customer_at   DateTime null
recovered_at           DateTime null
recovered_revenue      Decimal(12,2) null
reservation            FK → reservations.Reservation null   # §5.9 bridge
# Phase 1 — contact opt-out (§5.10)
contact_opt_out        Boolean default False
contact_opt_out_reason CharField blank   # not_needed / moved / for_other_person / other
contact_opt_out_at     DateTime null
# Phase 1 — disqualification gate (§5.8)
disqualified           Boolean default False
disqualified_reason    CharField blank   # not_in_egypt / discontinued / not_allowed / unknown_item / never_available / other
disqualified_by        FK → users.StaffProfile null
disqualified_at        DateTime null
# item_status: + 'available_again', + 'recovered'
```
`ItemDemandStat` (Phase 2):
```
lost_value_30d         Decimal(14,2) default 0
```
New `notification_type` values: `demand_back_in_stock`. New `DemandLog`/event labels for
substitution, disqualification, opt-out, and bridge conversions. **No new tables.** The
Reservations bridge (§5.9) reuses the existing Reservation model via FK link — does not fork
demand intake (respects DUP-001).

---

## 10. Sequencing & dependencies

```
Phase 0 (price snapshot)  ──┬──► Phase 1 (recovery loop)  ──► ROI metric live
                            └──► Phase 2 (valuation) ──► Phase 4 (customer profile)
Phase 3 (substitution + buy signal)  — independent, can slot anywhere after Phase 0
```

**Recommended build order:** 0 → 1 → 2 → 3 → 4. Phase 1 delivers the visible differentiator and
the ROI number earliest; Phase 0 is the small prerequisite it rides on.

**Rough total:** ~8–10 dev-days across all phases.

---

## 11. Success metrics (instrument from day one)

| Metric | Definition | Loop |
|---|---|---|
| **Recovered revenue (30d)** | Σ `recovered_revenue` | 1 |
| **Recovery rate** | recovered items ÷ items that came back in stock | 1 |
| **Time-to-recover** | `recovered_at − back_in_stock_at` | 1 |
| **Confirmed lost EGP (30d)** | Σ lost line_value | 2 |
| **Capture coverage %** | confirmed lost ÷ inferred lost (purchasing) | 2 |
| **Substitution conversion** | accepted ÷ offered | 3 |
| **Churn-at-risk from unmet demand** | customers w/ ≥N missed refills | 4 |

---

## 12. Risks & guardrails

- **Don't recompute statistical loss here** — consume `apps/purchasing` numbers (§1 boundary).
- **No SOFTECH writes** — recovery/valuation are platform-native only (Golden Rule 4).
- **Restock sweep must be one SQL query**, post-sync, not per-row signals (§5.3) — 30k×branch scale.
- **Outreach automation is opt-in** behind a config flag — avoid spamming customers (§5.4).
- **Free-text items** (`item_name_free`) can't be valued or restock-matched — degrade gracefully (null).
- **Privacy** — back-in-stock outreach must respect any customer contact-consent flag if one exists;
  verify before auto-WhatsApp.

---

## 13. Resolved product decisions (2026-06-11)

1. **Outreach = human-in-the-loop, WhatsApp-capable.** Never auto-sends. The recovery queue
   surfaces the opportunity and the operator triggers a WhatsApp send (§5.4).
2. **Recovery window = 12 months; reminders at least monthly.** Restock matching ignores demand
   older than 12 months; open recovery opportunities are re-surfaced at least every 30 days until
   resolved (§5.2 eligibility rule + §5.5 cadence).
3. **Demand ↔ Reservation is bidirectional and approval-gated** (§5.9). Recovered demand can
   convert to a Reservation; expired/incomplete Reservations can convert to lost Demand — both
   after human/managerial approval. The **disqualification gate** (§5.8) keeps non-recoverable items
   (not in Egypt, discontinued, not allowed, unknown, never available) out of the loop.
4. **Contact opt-out is per-item, captured after the first follow-up** (§5.10). If the customer
   declines further contact about a specific item (no longer needed / moved / buying for someone
   else / etc.), that line leaves the recovery loop. A global do-not-contact, if ever needed, lives
   in the `customers` module, not here.

### Remaining items to verify during Phase 1 build
- Confirm the campaigns/notifications WhatsApp send path and template mechanism to reuse for §5.4.
- Confirm `reservations.Reservation` creation API + required fields for the §5.9 forward bridge.
- Confirm `_auto_expire_reservations` ([sync/tasks.py:1657](../../apps/sync/tasks.py)) exposes the
  hook needed to flag expired reservations as bridge candidates (§5.9 reverse).

---

## 14. Module-scoped notifications (demand + followups)

> **STATUS: ✅ DONE (2026-06-12)** — migration `notifications/0015`.
> **Why:** the single global bell was flooded by every module, so staff with broad access skipped
> everything. Demand and Followups now route their notifications to **per-module feeds** instead of
> the global bell. (Decision: only these two modules; global bell keeps reservations/transfers/etc.)

**Design (no duplicate infra):**
- `Notification.category` field (`global` | `demand` | `followups`), **derived from
  `notification_type`** in `save()` via `TYPE_CATEGORY` — zero changes at call sites. Migration
  backfills existing rows. Also fixed two **mislabeled** demand notifications (`reservation_created`
  → `demand_created`, `follow_up_due` → `demand_follow_up`) so they categorize correctly.
- **Global feed excludes** `MODULE_CATEGORIES` by default; `?category=` returns a single module
  feed. `unread_count` and `mark_all_read` are category-scoped the same way (so the bell's "mark all"
  can't silently clear an unseen module feed). New `GET /api/notifications/category-counts/` returns
  all unread counts in one call.
- **Out-of-module behaviour = tiny global hint** (chosen): a small unread badge on the sidebar nav
  item (rail group icon + panel item), never a toast or bell entry. Powered by a `notificationStore`
  (zustand) the global WS hook keeps in sync — module-category `new_notification` events are routed
  to the store and **skipped** by the bell.
- **In-module:** a reusable `ModuleNotificationBell` component (mounted in the Demand and Followups
  page headers) shows that category's feed with mark-one / mark-all-read — "active only inside the
  module," as requested.
- **RBAC guard (2026-06-12):** module feeds are gated by the same matrix as the rest of each module —
  reading/marking a `?category=demand|followups` feed requires `can_do(module, 'view')`; `category-counts`
  zeroes out categories the user can't view; the in-module bells are wrapped in `<CanDo module=… action="view">`.
  Global notifications are unaffected (they remain recipient-scoped only).

**Files:** `apps/notifications/{models,views,serializers,urls}.py`, migration `0015`,
`apps/demand/service.py` (type relabel); frontend `store/notificationStore.js`,
`hooks/useNotificationSocket.js`, `components/{ModuleNotificationBell,Layout}.jsx`,
`pages/{DemandPage,FollowUpsPage}.jsx`, `api/client.js`.

---

## 15. Intake hardening (2026-06-12)

- **Phone validation** (migration-free): Egyptian format enforced on demand intake — mobile = 11 digits starting `01` (e.g. `01003280328`); landline = `0` + area code + 8-digit subscriber (e.g. `0225740408`). Frontend shows an inline warning + blocks submit ([DemandPage.jsx] `validateEgyptPhone`); backend mirrors it in `DemandCreateSerializer.validate_phone` (normalises to digits). Verified live: warning appears for invalid, clears for valid.
- **Uncoded items with manual pack value** (migration `demand/0007` adds `DemandItem.price_is_manual`): the create modal and the detail add-item flow now accept a free-text (uncoded) item with an optional hand-entered pack price, stored with `price_is_manual=True` and surfaced everywhere with a "\u2702 يدوي · غير مكوَّد" badge + an explicit "not from ERP" disclaimer. Coded items still auto-snapshot the ERP price (manual price rejected for them). Verified via HTTP 201 round-trip: `price_is_manual=true`, `line_value` correct, `cost_price_snapshot=null`.

---

## 16. ROI & operations features (2026-06-12)

- **Auto-WhatsApp on restock** (opt-in, gated): `service._auto_whatsapp_restock` fires inside the restock detection sweep, gated by `demand_auto_whatsapp_enabled` (default off), respects `contact_opt_out`, uses a Meta template (`demand_restock_whatsapp_template`) or plain text, stamps `notified_customer_at` + logs. Never raises. Config seeded in `seed_config`.
- **Demand-driven purchase suggestions** (migration `demand/0008`): `ItemDemandStat.suggested_order_qty` = open + lost demand units, computed in `_update_item_stats`. `GET /api/demand/purchase-suggestions/` (per-item, qty + demand count + lost value + network stock); `POST /api/demand/purchase-suggestions/push/` creates `demand_reorder` `ProcurementAlert`s (new type, migration `procurement/0007`). Dashboard panel with CSV export + "push to procurement".
- **Bulk list actions**: `POST /api/demand/bulk/` (assign / cancel / flag_purchasing), each item still validated through the state machine (invalid transitions skipped, not forced); permission-gated per action. UI: row + header checkboxes and a bulk action bar with an assignee picker.
- **Per-salesperson capture leaderboard**: `GET /api/demand/capture-leaderboard/?days=N` ranks staff by demands captured, with fulfilment rate + captured value. Dashboard panel.

All verified backend (HTTP) + live UI (DOM). No new console errors; no missing migrations.

---

## 17. ERP customer-lookup fix + live UI verification (2026-06-12)

- **Sybase lookup query fixed** (`service.lookup_customer_in_erp`): it used the wrong schema (`ptcode`/`personname`/`personid`/`phonenumber`, no DB prefix) and violated documented jConnect quirks (`TOP 1`, `IN (list)`). Rewrote against the real schema (`SOFTECHDB9.dbo.localcustomers.phcode/branchcustname/branchcode/mobileno`, `personphones.personcode=phcode`/`phoneno`) using `RTRIM` on CHAR equality, `EXISTS` instead of `IN`, and `fetchone()` instead of `TOP 1`. Verified live: lookup by PIC and by phone both return data; demand create now enriches `erp_branch_code` from ERP and links the customer. See [[catalog-scientific-name-dirty]] sibling memory for other SOFTECH data quirks.
- **Recovery loop verified end-to-end in the real UI**: simulated a restock → opportunity appeared in `/demand/recovery` → clicked Recover → `recovered_revenue=90`, dashboard ROI updated to recovered 90 ج.م / 100% rate. Also verified live: list bindings, create-modal phone validation + uncoded items, detail action buttons + state-machine gating, the now-working Assign picker, dashboard KPIs/reconciliation/leaderboard, bulk-action bar, and the module-scoped notification badge on the sidebar.

---

## 18. Notification-split expansion + staff-name fix (2026-06-14)

- **Global bell de-flooded 136,653 → 85 unread.** Diagnosed the flood: delivery (~95k) + transit/transfer (~40k) + reservation_status (~816). Extended the module-scoped split (§14) from {demand, followups} to also cover **delivery, transfers, reservations** — each now routed out of the global bell into its own in-module `ModuleNotificationBell` + sidebar hint. The global bell keeps only genuinely cross-cutting alerts (branch_connectivity, system, @mentions, churn, summaries). Migrations `notifications/0016` & `0017` (additive choices + backfill). RBAC `view`-gated per category as before.
- **Staff display names fixed.** `StaffProfile.full_name` now falls back to `softech_username` (e.g. "Aya Samy") before the numeric login username — fixes the capture leaderboard + assignee pickers showing employee codes. No migration (property change).

---

## 19. Customer self-service + recovery escalation + intelligence panels (2026-06-14)

- **Customer self-service "notify me" (public, shelf QR / link).** New source `self_service` (migration `demand/0009`). Public, throttled, unauthenticated endpoints: `GET /api/demand/public/item/`, `GET /api/demand/public/branches/`, `POST /api/demand/public/interest/` (Egyptian-phone validated, deduped 30d, no sensitive data returned). Standalone public page `/notify?item=&branch=` (outside auth) lets a customer leave a phone → lands as a demand with zero staff labor. Staff-side `GET /api/demand/shelf-qr/` generates a printable shelf-label QR (base64 PNG, qrcode lib); `ShelfQrButton` on the product page → branch picker + print. Verified: public POST creates a demand with no token.
- **Recovery SLA + escalation.** `service.escalate_stale_recoveries()` escalates `available_again` lines uncontacted beyond `demand_recovery_escalation_hours` (config, default 24) to supervisors/admins; deduped so it never spams. Wired as an hourly APScheduler job (`demand_recovery_escalation`). 
- **Substitution-acceptance analytics.** `GET /api/demand/substitution-analytics/` — which out-of-stock items customers accept a same-molecule substitute for (from `substitute_for_item`); dashboard panel. Tells purchasing what to stock / drop.
- **Price-objection feedback.** `GET /api/demand/price-objections/` — items lost to `lost_reason='price'` with current price + lost value; dashboard panel for the pricing team.
- All verified (endpoints 200, public create 201, escalation runs); frontend builds; backend check clean; new config keys seeded.

---

## 20. Notification priority tiers + cog/monitoring split (2026-06-14)

Reworked the notification surfaces from "module-scoped quiet feeds" into **priority tiers**, driven by `Notification.category` + a new `alarm_tier` property. Four surfaces:

| Surface | Categories | Behaviour |
|---|---|---|
| **🔔 Bell** | reservations, delivery (critical); transfers (high); global | In bell + sound + visual alarm for critical/high. global rides silently. |
| **📡 Monitoring** | monitoring (SLA, transit, routine status) | Quiet feed, OUT of the bell. Header dropdown. |
| **⚙️ Settings** | settings (system, branch_connectivity) | Quiet cog feed, OUT of the bell. |
| **(module)** | demand, followups | Quiet in-module feeds (sidebar hint + module bell). |

- **Alarm tiers** (`Notification.alarm_tier`): CRITICAL = `delivery_new, delivery_cash_variance, reservation_created, reservation_assigned, stock_available`; HIGH = `transfer_request, transfer_response, unfulfilled_transfer_flag`. Only these actionable "new" events sound/flash; routine + monitor types never do.
- **Sound**: Web Audio (no asset). Critical = double-beep (988 Hz ×2), High = single-beep (740 Hz). Per-device **mute toggle** in the bell; AudioContext primed on first user gesture (autoplay policy).
- **Visual alarm**: prominent coloured toast — critical red ring + pulse + "عاجل" badge, high amber + "هام" badge — 8s (vs 5s routine).
- **Migration `notifications/0018`**: added `monitoring` + `settings` categories; backfilled the ~136k SLA/transit/routine-status rows into `monitoring` and system/connectivity into `settings`. Net effect: the main **bell dropped from ~136k to actionable-only** (e.g. admin: 16), with the flood quarantined in the quiet 📡 feed.
- `category-counts` now returns `monitoring`, `settings`, and a `bell` sum.
- Verified live: header shows 🔔/📡/⚙️ + mute with correct counts; bell carries actionable reservations/transfers; critical/high toasts render with ring+pulse+badge; monitoring/quiet produce no alarm; WS connects.

### 20a. Remaining-type tiering (resolved, migration `0019`)

- **`churn_alert`** → promoted to a **HIGH bell alarm** (amber + "هام" + single-beep). Stays category `global` so it rides the bell; added to `ALARM_HIGH_TYPES`.
- **`weekly_summary` / `monthly_report`** → new quiet **`reports`** category, surfaced as a 📊 header feed (out of the bell).
- **`mention` / `chatter_mention`** → new quiet **`mentions`** category, surfaced as a 💬 header feed (out of the bell), **but with a HIGH alarm** (amber "هام" toast + single-beep). The front-end fires the alarm on `alarm_tier` even for quiet-feed categories, so the @-mention sounds + flashes without inflating the bell count or entering the bell list.

Header now carries six notification surfaces: 🔔 bell (alarming) · 💬 mentions · 📊 reports · 📡 monitoring · ⚙️ settings · 🔊 mute. Verified live (routing + counts: churn→bell/high, weekly→reports, mention→mentions).

---

## 21. Per-role notifier visibility (permissions-controlled) (2026-06-14)

Admins can now choose **which notifiers (notification categories/feeds) appear to which role**, from the Permissions Matrix page.

- **Model** `notifications.RoleNotificationAccess(role, category, is_allowed)` (migration `0020`). The 10 notifiers = the `Notification.CATEGORY_CHOICES`.
- **Resolution** (`notifications.views._can_view_category` / `_visible_categories`): admin → always; explicit row → its value; else **INHERIT the module 'view' permission** (non-breaking; ungated categories default visible).
- **Full suppression** when hidden for a role: filtered from the default bell list + `unread-count` + `mark-all-read`; zeroed in `category-counts`; the front-end **drops it from the real-time WS stream** (no count/toast/sound, in `useNotificationSocket`) and **hides the header feed icon** (Layout, via `category-counts.visible`).
- **API**: `GET /api/users/permissions/` now also returns `notifiers` + `notifier_matrix` (effective per role×category); `POST` accepts `{role, category, is_allowed}` items (alongside the existing `{role, module, action}` items) → `RoleNotificationAccess.update_or_create`. Admin-only.
- **UI**: Permissions Matrix page gained a **"🔔 ظهور الإشعارات"** tab — a per-role notifier grid (show/hide each feed, إظهار/إخفاء الكل), sharing the same dirty/save flow.
- **Bug fixed in passing**: the matrix toggle updaters mutated nested state, so React StrictMode's dev double-invoke flipped toggles twice (saved the wrong boolean in dev). Made `toggleCell` + `toggleNotifier` pure.
- Verified end-to-end: resolution logic (inherit/explicit/admin-bypass), API (matrix payload, save, enforcement → 403 + zeroed counts + `visible[]`), and live UI (tab renders all 10 notifiers; toggle→save persisted `is_allowed:false`).

### 21a. Generation suppression — 3-state notifier control (2026-06-14)

Extended the per-role notifier control from visibility-only to a **3-state mode** (migration `0021` adds `RoleNotificationAccess.generate`):

| Mode | generate | is_allowed | Effect |
|---|---|---|---|
| **Show** (إظهار) | True | True | created · appears · alarms |
| **Mute** (كتم) | True | False | created/recorded · hidden (no feed/count/alarm) |
| **Off** (إيقاف) | False | — | **not created at all** for the role |

- **Generation suppression** enforced in `Notification.send_to_user` (the single choke-point all factories funnel through) → **per-recipient**: a mixed-audience event still generates for recipients whose role allows it, skips those with the notifier Off. Admins bypass.
- Resolved via `RoleNotificationAccess.can_generate(role, category)` with a 30s in-process cache (tiny table), busted on save/delete for immediate effect in the web process.
- Default (no row) = generate **on**; visibility still inherits module 'view' (so the effective default mode is Show where the role has module view, else Mute — matching prior behaviour).
- API: `notifier_matrix` now returns `'show' | 'mute' | 'off'`; `POST` accepts `{role, category, mode}` (back-compat: bare `is_allowed` still maps to show/mute).
- UI: the notifier grid uses a 3-segment selector (إظهار · كتم · إيقاف) with إظهار/كتم/إيقاف-all bulk actions.
- Verified end-to-end: suppression (off→no row, mute/show→row, admin bypass, cache bust), API mode round-trip, and live UI (selector renders, Off→save persisted `generate=False`).

---

## 22. Snooze + personal reminders (2026-06-14)

Two user-facing features added on top of the notification system (migration `0022`).

**Snooze ("remind me later")**
- `Notification.snoozed_until` + `snooze_count`. While `snoozed_until` is in the future the row is excluded from the bell list, unread-count, category-counts and mark-all-read.
- `POST /api/notifications/{id}/snooze/` — body `{preset: 15m|1h|3h}`, `{minutes:N}` (0 = un-snooze), or `{until: ISO}`.
- A **1-minute scheduler worker** (`_process_reminders_and_snoozes` in sync/tasks.py) clears due snoozes and **re-pushes** them → they **re-alarm** (sound + visual) per the user's choice.
- UI: a clock/snooze control on each bell row → preset menu (١٥ دقيقة · ساعة · ٣ ساعات · غداً ٩ ص); item leaves the bell immediately (optimistic).

**Personal reminders (private, lightweight — separate from FollowUpTask)**
- New `PersonalReminder(owner, title, note, remind_at, is_fired, optional deep-links)` model. Distinct from operational `FollowUpTask`: no assignment/workflow/audit — it just fires a Notification.
- New `personal_reminder` notification type → `global` category, **HIGH alarm**.
- The same 1-min worker fires due reminders via `PersonalReminder.fire()` (idempotent). `fire()` uses `send_to_user(bypass_role_gate=True)` so a user's own reminder always reaches them even if their role has the `global` notifier Off.
- Endpoints: `GET/POST /api/notifications/reminders/`, `DELETE/PATCH /api/notifications/reminders/{id}/` (owner-scoped).
- UI: a **⏰ تذكير** toggle in the bell panel header opens a quick-add (title + datetime) + a pending-reminders list with delete.
- Verified end-to-end: snooze hide→worker clears+re-push→visible/re-alarm; reminder fire (global/high, idempotent); snooze + reminder APIs; live UI (snooze menu → `snoozed_until` set; reminder form → row created).

> Operational note: the 1-min worker is a new scheduler job — the running `run_scheduler` must be on current code (relaunch) for snooze-returns and reminder-firing to occur live.

---

## 23. Browser / desktop push (Notification API) (2026-06-14)

The `enable_browser_push` pref existed but was a **dead toggle** (never wired — no Notification API, no service worker, no push backend). Wired it up via the in-page **Notification API** (OS notification when the tab is open but unfocused — matches the requested behaviour without a service worker / VAPID backend).

- **Trigger** (`useNotificationSocket.maybeDesktopPush`): fires `new Notification(...)` only for **alarm-tier** events (critical/high) **when the tab isn't focused** (`!document.hasFocus()`), and only if desktop push is enabled + browser permission granted. Clicking it focuses the window and navigates to the linked record (via a `notif:navigate` CustomEvent handled in Layout).
- **Toggle**: a 🖥️ button beside the mute toggle in the bell — requests `Notification.requestPermission()` on enable, persists to the `enable_browser_push` server pref + a per-device `localStorage` flag (permission is inherently per-device). Hidden where the Notification API is unsupported; shows a "blocked in browser" tooltip when permission is denied.
- Verified live (Notification API mocked): pushes alarm-tier when unfocused; **skips** when focused or non-alarm; click → navigated to `/reservations/42` + closed.

**Upgrade path (not built):** true background Web Push (browser fully closed) needs a service worker + VAPID keys + a `PushSubscription` model + `pywebpush` send integration — a separate, larger piece.

---

## 24. Preferences Center + in-app banner + notifications inbox (2026-06-14)

Three UI features (migration `users/0016`).

**Preferences Center** (`NotificationPreferencesModal`, opened from the bell footer ⚙️)
- Per-user toggles: master `enable_notifications` (gates generation in `send_to_user`), `enable_sound` (synced with the per-device mute), `enable_browser_push` (requests permission).
- **Personal per-category mute**: `StaffProfile.muted_notification_categories` (JSON). Hides a category for *this user* on top of role-level visibility (still recorded). Integrated into `_can_view_category` / `_visible_categories` (applies even to admins). `preferences` endpoint now reads/writes it + returns the notifier list.

**In-app banner** (new delivery channel)
- `useNotificationSocket` raises a persistent top-of-screen **red banner** for **critical-tier** events (in addition to the toast). View → navigates to the record; ✕ dismisses. Rendered by `NotificationBell` (`NotificationBanner`).

**Notifications inbox** (`/notifications`, `NotificationsInboxPage`)
- Full-page list with filters (category dropdown, search, unread-only) + **bulk actions** (mark read / snooze 1h / delete) via new `POST /api/notifications/bulk/` + **offset pagination** ("load more"; `notification_list` now takes `offset`).
- Linked from the bell footer (📥 كل الإشعارات).

Verified live: inbox renders + filters + select-all → bulk bar (mark/snooze/delete); prefs modal renders all sections + mute monitoring → save → persisted (`muted=['monitoring']`); critical banner renders with view/dismiss. Backend: prefs GET/PATCH (mute reflected in `category-counts.visible`), bulk read, offset pagination all pass. `check` clean, build green.

---

## 25. Targets & Goals + Internal Announcements (2026-06-14)

Two new modules (migrations `incentives/0009`, `notifications/0023`).

**Targets & Goals** (`apps/incentives` → nav under Analytics, `/targets`)
- `SalesTarget(scope_type=chain|branch|salesperson|category, branch?, softech_user?, category?, metric=net_revenue|orders, period_start, period_end, target_value)`.
- **Live attainment** computed from `customers.PurchaseHistory` (net = Σ doc 115 − Σ doc 30; category via `PurchaseHistoryLine.item.category`; orders = count of 115). `.attainment()` returns actual / target / pct / **pace** (ahead·behind·met·missed vs elapsed-time expectation) / days-left.
- `SalesTargetViewSet` (`/api/incentives/targets/`, CRUD, create/edit/delete gated to admin·supervisor·purchasing). Page shows progress bars with an expected-to-date marker.

**Internal Announcements** (`apps/notifications`, `/announcements`, in nav for all roles)
- `Announcement(title, body, author, audience_roles[], audience_branch_ids[], priority, is_pinned, expires_at)` + `AnnouncementRead` (ack receipts).
- On publish → `fan_out()` sends a bell notification (`announcement` type → global) to every targeted staff member. Recipients **acknowledge**; author/admin sees **read stats (X of Y, %)**.
- Endpoints under `/api/notifications/announcements/` (list audience-scoped + my read-state, create gated to admin·supervisor, `/ack/`, `/{id}/` stats+delete).
- Verified: target create→attainment on real sales (chain June net 196k/2M, pace behind); announcement publish→fan-out (85 staff) + ack + stats; both pages render live.

---

## 26. Delivery: dispatch board + route batching + POD + driver app (2026-06-14)

Built the missing *layer above* the already-complete delivery order lifecycle (drivers, 14-status orders, assign/accept/dispatch/complete/cash, CSAT, dashboard, read-only route-plan, driver-API). Migration `delivery/0007`.

**Proof of Delivery** — added `pod_recipient_name`, `pod_note`, `pod_photo` (image), `pod_lat/lng` to `DeliveryOrder`; `delivery_complete` now captures them (multipart photo + geo) alongside cash. Exposed in the order serializer.

**Route batching (persisted runs)** — new `DeliveryRoute(branch, driver, route_date, status, …)` + `DeliveryOrder.route`/`route_sequence`. Endpoints: `POST /api/delivery/routes/` (build a run from ordered `order_ids` → assigns driver + sequence), `POST /routes/{id}/dispatch/` (moves the whole run to out-for-delivery in one action), `GET /routes/` + `/{id}/`. (The existing read-only `route-plan` suggests the grouping; this persists & dispatches it.)

**Driver app** (`/delivery/my`, mobile-first) — `GET /api/delivery/app/my-route/` returns the driver's sequenced run; the screen does accept → out → **deliver-with-POD** (recipient, cash, photo, auto-geo) per stop.

**Dispatch board** (`/delivery/dispatch`) — ready orders (multi-select) + driver picker → create route; today's routes with live progress (delivered/total, expected cash) + one-tap dispatch.

Nav: added لوحة التوزيع + مهام السائق under Operations. Verified end-to-end (route create→dispatch→POD over HTTP + in-process; both pages render). Note: earlier curl failures were shell artifacts (var capture + Arabic-in-payload), not code.

---

## 27. Delivery geofencing — pickup-at-branch + delivery-at-address (2026-06-14)

Two location double-checks in the driver app (migrations `branches/0005`).

- **Pickup**: added `Branch.latitude/longitude`. `delivery_dispatch` (driver "out") now requires `driver_lat/lng` and rejects unless within `delivery_pickup_radius_m` (default 200 m) of the order's branch.
- **Delivery**: `delivery_complete` — *if* the order had `delivery_lat/lng` set before pickup — requires the driver's current `pod_lat/lng` to be within `delivery_dropoff_radius_m` (default 300 m) of that address; otherwise rejected.
- Both controlled by `delivery_geofence_enabled` (default on) + the two radius settings (seeded in `seed_config`, category `delivery`). Skipped gracefully when the branch/order has no coordinates.
- Helpers in `delivery/views.py`: `_haversine_m`, `_geofence_on/_geofence_radius`, `_geofence_violation` → 400 with `{geofence, distance_m, allowed_m}`.
- Driver app (`DriverDeliveryApp`): captures GPS via `navigator.geolocation` on pickup + delivery, sends it, and shows the geofence rejection message (with distance) inline.
- Branch serializer exposes `latitude/longitude` so coordinates can be set.
- Verified: pickup 8 km → rejected, at branch → OK; delivery 2.9 km from address → rejected, at address → delivered.

---

## 28. Branch coords editor + always-log delivery location/distance/fee (2026-06-14)

**Branch coordinates editor** — Settings → 🏪 الفروع → each `BranchCard` edit form now has latitude/longitude inputs + a "use my current location" button (capture from inside the branch), and a chip showing the coords or an ⚠️ "no coordinates" warning. Saves via the existing `PATCH /branches/{id}/` (empty → null). Closes the geofence prerequisite.

**Always-log delivery location + metrics** (migration `delivery/0008`) — `delivery_complete` now, whenever the driver's `pod_lat/lng` are present:
- **logs the confirmed delivery location even if the order had none** (and backfills `delivery_lat/lng` from it, so the address is captured for next time);
- computes & stores `delivery_distance_km` (branch → confirmed drop, Haversine);
- exposes `delivery_minutes` (dispatch→delivered, existing) and a config-driven `suggested_driver_fee` = `delivery_driver_fee_base` + `delivery_driver_fee_per_km` × distance (both seeded, category `delivery`).
- Serializer adds `delivery_distance_km` + `suggested_driver_fee`.

Note: the "no prior location" path still skips the *drop-off geofence* (nothing to compare against) but **does** log location/distance/fee — so every delivery yields actual distance, time, and a fee estimate for driver payout.

Verified: order with no delivery location → completed, location logged + backfilled (30.07), distance 3.07 km, suggested fee 19.21 (= 10 + 3×3.07); branch coords editor renders (lat/lng inputs + use-my-location + missing-coords chip).

---

## 29. Branch backfill (map pin) + mobile rider shell (2026-06-14)

**Branch-user backfill** (migration `delivery/0009` adds `pod_backfilled`) — for when a rider never logs pickup/delivery. `POST /api/delivery/{id}/backfill/` (roles admin·supervisor·call_center·pharmacist, **no geofence**): confirm pickup and/or delivery, optionally assign a driver, capture POD (recipient/cash/note) and an **approximate drop location chosen on a map**; recomputes `delivery_distance_km` + flags `pod_backfilled=True`. Occasional/optional by design.
- Frontend: **Leaflet** map picker (`MapPicker.jsx`, free OSM tiles, no API key — tap/drag to drop a pin) inside `DeliveryBackfillModal.jsx`, opened from the order detail panel via a "✍️ إدخال يدوي" button. Verified live: 403 for salesperson; admin confirm + map pin → delivered, backfilled, distance 2.29 km, fee 16.87; map renders (tiles + draggable marker).

**Mobile rider shell** — `RiderLayout.jsx`: a lean full-screen mobile shell (slim green top bar + logout, no desktop sidebar) wrapping the rider app at a standalone **`/rider`** route. Login now redirects `role='delivery'` straight to `/rider`; the "مهام السائق" nav points there too. The driver screen (`DriverDeliveryApp`) is already mobile-first (max-w-md, big tap targets, tel: links, GPS capture). Verified: lean shell renders with no sidebar on a phone-width window.

**Branch coordinates editor** (from §28) lives in Settings → 🏪 الفروع.
