# 06 · SPEC P-26 — One honest expiry number

**Status:** specification (approved for spec 2026-10-30). **Build:** not yet authorised. The owner's rule is "build
after all discussions".

**Owner input** (ledger row P-26, backlog P-26 "Revision after owner input")
- Store **110** is a **closed branch**. It must hold **zero** stock.
- Store **102** = expired stock that could not be returned → write-off / destroy.
- Store **105** = recently expired, may still be returnable → return candidates.
- Store **103** = expired cosmetics.
- Closed stores are excluded from **every** report.
- A standing alert fires when any closed store holds stock.
- The clean-up of 110 (write-off or transfer) is the **accountant's** decision, posted natively in SOFTECH.


**Owner decisions 2026-10-31** (these override anything below that disagrees)
- Store 110 (closed branch) is **excluded from every number, screen, export and alert**. It "does not matter to us right now".
- So the closed-store alert, the `closed_store_stock` notification type and the accountant clean-up export are **dropped from scope**. The role map keeps `closed` only so that 110 is filtered out everywhere; nothing else reads it.

## 1. Problem (measured)

- **Four expiry sources** exist (`02_CURRENT_STATE_FINDINGS.md` §3.2, §5):
  - `batches.StockBatch` + `NearExpiryAlert` — **dead**. `BatchService.receive_from_invoice` has no caller, so the
    table is empty. The `near_expiry_scan` job (`apps/sync/tasks.py`, daily 06:00) still scans it.
  - `batches.PurchaseExpiryEntry` — the purchase-entry audit trigger. It is a history signal, not on-hand stock.
  - `batches.StockExpiryBalance` — the live `stkbalexpiry` mirror, all 6 nodes, daily 05:30. Branch batch qty
    matches `ItemStock` for 87–95% of items (`03_DATA_OPPORTUNITY_MAP.md`, Batch 2).
  - `purchasing.ItemDemandMetrics.expected_expiry_risk_value` — written by `forecasting/service.py::_expiry_risk`,
    which **reads `StockBatch`**. It is therefore always 0, so the insights rule `rule_near_expiry`
    (`apps/insights/rules.py`) can never fire.
- **The headline mixes book residue with live risk.** The `/batches` KPI card «منتهية ولا تزال بالمخزون» reads
  `stock_expiry_summary(include_quarantine=False)`. That flag only drops stores 102/103/105
  (`stock_expiry._QUARANTINE_STORES`). **Store 110 is counted**:
  - 110 holds **1.61M EGP**, 100% more than 2 years expired, **no movement in 12 months**, absent from `ItemStock`.
  - Quarantine 102/103/105 holds **1.14M EGP** expired (767k more than 2 years).
  - Real branch shelf exposure is about **102k expired** and **232k** that will not sell in 180 days at the local rate.
- The quarantine store set `{'102','103','105'}` is hard-coded in about 12 places (for example
  `catalog.models.EXCLUDED_STORE_CODES`, `stock_expiry._QUARANTINE_STORES`, `supply/position.py`,
  `purchasing/isr_writer.py`). None of them knows that 110 is closed.

## 2. Scope

### 2.1 One store-role map (expiry side only)

1. New module `apps/batches/store_roles.py`. One function, `store_role(node_code, store_code)`, returns one of:

   | Role | Default stores | Bucket label (UI) |
   |---|---|---|
   | `live` | every other store | «مخزون قابل للبيع» |
   | `return_candidate` | HQ 105 | «مرشح للمرتجع (105)» |
   | `write_off` | HQ 102 | «إتلاف / شطب (102)» |
   | `cosmetics_expired` | HQ 103 | «تجميل منتهي (103)» |
   | `closed` | HQ 110, plus every store on a node whose `Branch.kind == 'closed'` | «فرع مغلق (110) — يجب أن يكون صفر» |

2. The map is keyed by **node + store** (`"100:110"`), because the same store code may mean different things on
   different nodes. It is stored in a new SystemSetting `expiry_store_roles` (JSON). Defaults live in code and apply
   when the setting is missing. Only admins edit it.
3. **Migration (batches):** add `StockExpiryBalance.store_role` (CharField, indexed). A data migration back-fills
   existing rows from the default map (deterministic, no SOFTECH access). `is_quarantine` stays for compatibility:
   it equals `role in (return_candidate, write_off, cosmetics_expired)`.
4. `sync_stock_expiry_all` (`apps/batches/stock_expiry.py`) sets `store_role` on every row it writes.
5. The other modules' `{'102','103','105'}` lists are **not** changed in this card. They read `stkbal`, where 110
   already shows zero stock. Moving them onto the map is a later clean-up (see Out of scope).

### 2.2 Every expiry number reads the buckets

1. `stock_expiry_summary` returns a `buckets` block: one entry per role with `items`, `qty`, `value` (qty × catalog
   unit cost, today's basis) and, for `live`, the existing bands (`expired`, `lt_30`, `lt_90`, `lt_180`).
   - The existing top-level keys stay, but are computed over **`live` only**.
   - `closed` is **never** added into any total.
2. `stock_expiry_report` and `stock_expiry_stores` get a `roles` filter.
   - The default is `live`. `include_quarantine=true` keeps working and maps to the three quarantine roles.
   - `closed` rows appear **only** in the clean-up list (2.4). No other report shows them.
3. `rebalance._load` filters `store_role='live'`. Today it already skips expired batches; this makes the rule
   explicit.
4. **One at-risk definition.** New helper `stock_expiry.at_risk_by_branch(within_days=180)`:
   - live batches only, per item × branch, in FEFO order;
   - at-risk qty = max(0, batch qty − daily rate × days left);
   - daily rate = `ItemDemandMetrics.qty_90d / 90`, the same rate `rebalance.py` uses;
   - value = at-risk qty × unit cost.
5. `insights.rules.rule_near_expiry` reads that helper instead of `ItemDemandMetrics.expected_expiry_risk_value`.
   `forecasting.service._expiry_risk` also calls it, so the stored field stops being a silent 0.

### 2.3 Screens

1. **`/batches` KPI row** (`BatchesPage.jsx`, around line 1405):
   - The first cards stay (30 / 90 / 180 days, value at risk). They now count live stock only.
   - «منتهية ولا تزال بالمخزون» becomes **«منتهية على الرف»**, showing live expired only.
   - A second row shows four cards: «مرشح للمرتجع (105)», «إتلاف / شطب (102)», «تجميل منتهي (103)» and
     «فرع مغلق (110)».
   - The 110 card is red when non-zero, links to the clean-up list, and reads "must be zero".
2. **Store dropdown** in `LiveStockExpiryTab`: each store shows its role label. Closed stores are not offered.
3. **Main dashboard tile** (`DashboardPage.jsx`), shown to users with `BATCH_READ`:
   - one line per bucket, for example "Shelf: X expired · Y at risk in 180 days | Return candidates: … | Write-off: … |
     Closed branch: … (must be 0)";
   - a compact `DataFreshnessBar domains={['expiry']}` chip;
   - the tile links to `/batches`.
4. Freshness: `/batches` already shows the `StockExpirySyncRun` status and the admin «مزامنة الآن» button
   (`CanRefreshExpiry`). No new button is needed.

### 2.4 Closed-store clean-up list and alert

1. `GET /api/batches/stock-expiry/closed-stores/` lists closed-role rows with item, batch, expiry, qty, unit cost and
   value. `POST …/closed-stores/export/` produces the xlsx for the accountant:
   - branch labels via `BL`, never a bare code;
   - one sheet for 110 and one for 102 (write-off candidates), so the accountant decides both in one pass.
2. **Our system only lists and verifies.** Staff post the SOFTECH adjustment or transfer natively. After the next
   `sync_stock_expiry`, the 110 card should read 0. That is the verification.
3. **Standing alert:**
   - At the end of `sync_stock_expiry_all`, if any `closed` row has qty > 0, send one notification per recipient per
     day via `Notification.send_to_user`, with `dedup_key = closed_store_stock_<date>`.
   - New notification type `closed_store_stock` («🏚️ رصيد في مخزن مغلق»). This is a label-only migration on
     notifications, so the P-55 `notification_routing` table can switch it off or route it.
   - Recipients: new SystemSetting `closed_store_alert_recipients` (staff ids; default = admins), the same pattern
     as `transit_digest_recipients`.
   - The body shows the value and line count and links to the clean-up list.
   - A node that failed in this run does not raise or clear the alert. Its old rows are kept, as today.

### 2.5 Retire the dead path (no data deletion)

1. Remove the `near_expiry_scan` job registration from `apps/sync/tasks.py`. Keep the command file, marked
   deprecated.
2. `forecasting._expiry_risk` stops reading `StockBatch` (2.2.5).
3. Keep the `StockBatch` / `BatchMovement` / `NearExpiryAlert` models, tables and the `/api/batches/` router
   endpoints, marked deprecated in their docstrings. **No drop migration.**
4. Remove the unused `QuarantineModal` from `BatchesPage.jsx`: it is defined at line 50 and rendered nowhere, so
   the help tip «عزل دفعة» describes a button that does not exist.

### 2.6 Tests (new file `apps/tests/test_expiry_buckets.py`, plus an extended scheduler test)

| Test | Proves |
|---|---|
| role map defaults | 100:110 → closed, 100:105 → return_candidate, 100:102 → write_off, 100:103 → cosmetics_expired, others → live |
| setting override | `expiry_store_roles` replaces a default; a bad JSON falls back to the defaults |
| closed node | a store on a `kind='closed'` branch maps to `closed` |
| sync tags roles | `sync_stock_expiry_all` with a fake connection writes `store_role` |
| summary excludes closed | a 110 row adds nothing to the live `expired` value or to any total |
| report default | the default report has no closed or quarantine rows; `include_quarantine` still returns 102/103/105 |
| at-risk helper | FEFO + rate maths on a small fixture (whole, deterministic values) |
| insights rule | `rule_near_expiry` fires from `StockExpiryBalance` with no `StockBatch` rows |
| alert | a closed row with qty > 0 sends 1 notification per recipient; a second sync the same day sends 0 |
| alert silent | no closed stock → no notification; a failed node does not alert |
| export | clean-up xlsx has branch labels, both sheets |
| scheduler | `near_expiry_scan` no longer registered (`test_scheduler_jobs.py`) |

Existing tests to keep green: `test_purchase_expiry_audit.py` (incl. `StockExpiryReportTests`),
`test_expiry_rebalance.py`, `test_expiry_count_spawn.py`, `test_help.py`.

### 2.7 Help

`apps/help/content/batches.py`, screen `batches.main`:
- explain the five buckets and the "110 must be zero" card;
- the alert and the accountant clean-up export;
- drop the «عزل دفعة» tip;
- bump `updated`.

`apps/help/content/general.py`, the `/dashboard` screen: one line for the new tile; bump `updated`.

## 3. Acceptance criteria

- One function decides a store's role. Every expiry number on `/batches`, the dashboard tile and the insights rule
  comes from `StockExpiryBalance` through it (code review + tests above).
- With today's data, «منتهية على الرف» no longer includes the 1.61M of store 110 (test with a fixture; a read-only
  check on the office DB after deploy).
- The 110 card and the alert both show non-zero until the accountant's SOFTECH clean-up, then 0 after the next sync.
- `near_expiry_scan` is not scheduled. Nothing reads `StockBatch` for a number.
- Help updated; `test_help.py` passes. Frontend build passes.

## 4. Measurement

- Shelf-risk value per branch, weekly: live expired + live at-risk ≤180 days. Baseline ≈102k expired, ≈232k at risk.
- Closed-store value: baseline 1.61M, target **0** after the accountant's decision.
- Write-off (102) value, monthly: baseline is part of the 1.14M quarantine. It should fall as destroy/write-off is
  posted.
- Return-candidate (105) value by age: handed to P-29, which measures the cash recovered.

## Out of scope

- Any SOFTECH write: stock adjustment, write-off or transfer for 110 or 102. Staff post these natively.
- Moving the other modules' hard-coded `{'102','103','105'}` lists onto the role map. That is a later consolidation;
  they read `stkbal`, not this mirror.
- Dropping the `StockBatch` tables.
- Return-window logic (P-29) and the near-expiry action worklist (P-28).
- Changing the value basis (cost vs selling price, VAT). That belongs to P-35.

## Open questions

1. **Accountant's decision for 110:** write-off, or transfer back into a live store? (Ledger "evidence still
   needed".) Until then the card stays red by design.
2. Is **110 the only closed store**? Are there closed stores on branch nodes, or on old nodes that are no longer swept
   (`is_operational=False`)? To verify (read-only check of `stock_expiry_stores` output).
3. Do 102/103/105 exist on **branch** nodes, or only on HQ? The map is keyed node + store, so the answer only changes
   the defaults. To verify (read-only).
4. Alert recipients: admins only, or also a named accountant or quality manager? There is no accountant role in
   `ROLE_CHOICES`.
5. Should store 103 (expired cosmetics) also feed P-29's return calendar when a cosmetics supplier takes returns, or
   is it always destroy?

## Stop-and-ask

- Any write to SOFTECH to clear 110 or 102: not part of this card. It stays native.
- A migration that deletes the `StockBatch` / `NearExpiryAlert` tables.
- Changing the value basis of the expiry KPIs.
