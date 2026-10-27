# 22 — Cash & Inventory Optimization Layer

**Status:** DESIGN (iterating on paper before build). Owner-validated 2026-09-15.
**Companion built module:** Phantom Substitution (`apps/purchasing/phantom.py`) — the
first "action-flag" detector; this doc generalizes the same pattern into a
cash-recovery + over-purchase-prevention layer over شيت النواقص.

---

## 1. Problem & vision

The demand sheet today answers one question — **"what to buy."** But a large slice
of our cash is trapped or wasted in ways the buy-signal can't see:

- **Frozen cash** — stock sitting with no demand (dead / overstock).
- **Self-inflicted dead stock** — we chase a short demand *spike* (a doctor hitting
  a manufacturer target, a seasonal pop) with a big purchase; the spike fades and
  the stock is stranded.

**Vision:** turn شيت النواقص into a **cash & inventory action layer**. Each item can
carry one or more *action flags* — the same mechanism as 🩹 مبيعات وهمية (phantom)
and 📉 نقص السوق (shortage) — so the same sheet also answers **"what NOT to buy, what
to return, what to transfer, and what cash to free."**

Every flag is **auto-detected + human-reviewable** (confirm / exclude / override),
**config-driven**, and — where it changes ordered quantity — **dormant/opt-in**
(default OFF, activated per engine run), exactly like the phantom reduction.

---

## 2. The measured cash picture (run #67, 2026-09-09, network)

| Lever | Size | Notes |
|---|---|---|
| **Total on-hand inventory** | **≈ 10.05M EGP** (cost) | 12,353 items |
| 🧊 **Dead stock** (stock>0, ~0 sales) | **≈ 1.47M EGP** (15% of inventory) | 3,558 items |
| 📦 **Overstock** (coverage > 6 mo) | **≈ 415K EGP** releasable to a 6-mo cover | 769 items |
| 📈 **Spike over-projection** | **≈ 58K EGP/mo** of inflated demand at ≥6× | 52 items (+30 new-burst) |

Dead-stock **by location** (the master discriminator — see §4.2):

| Where stuck | Items | Value | Likely cause |
|---|---|---|---|
| Only at **HQ (100)** | 31 | 116K | central over-buy / **supplier pushed without our order** / never distributed |
| Only at a **branch** | 3,221 | **1,037K** | **local demand died** (doctor hit target & shifted) / over-transfer |
| At **both** | 306 | 315K | cumulative / obsolete / variant-cannibalized |

---

## 3. The four detectors

Two roles: **preventive** (stop *creating* trapped cash — touches المطلوب) and
**curative** (recover *existing* trapped cash — annotation + recovery screen).
Dead & overstock items are *already* not reordered (negative gap), so they are
**cash-recovery annotations, not gap cuts.** Only the spike detector touches المطلوب.

### 3.1 📈 Spike over-purchase (PREVENTIVE) — the behavioral one

The "doctor-target" pattern: a doctor prescribes a drug hard until he hits a
manufacturer target, then shifts. We chase the burst with a big buy; it fades → dead
stock. **The referral-doctor field is empty in SOFTECH**, so we detect the *shape*,
not the doctor.

- `recent = qty_90d / 3` (last-quarter monthly rate)
- `prior  = (qty_365d − qty_90d) / 9` (the 9 months *before* the recent quarter)
- Consider only items with `recent ≥ 5/mo`. Then **two tiers (owner-locked 2026-09-15):**
  - **STRONG** = `prior < 0.15/mo` (*new burst, no history*) **OR** `recent/prior ≥ 10×`
    → **cap-eligible** (Awadist 80×, Jutoxib 41×, ROQARIK new-burst; ~59 items).
  - **WATCH** = `6× ≤ recent/prior < 10×` → **flag/monitor only, never capped**
    (~23 items, e.g. TARGOCID 9×).
  - `< 6×` → not flagged (the 4–6× band is mostly legitimate growth on established
    sellers — PAPIA, VATIKA — capping it would starve real demand).
- **Cap = REVIEW-GATED + opt-in (owner-locked):** a STRONG spike is flagged
  automatically, but المطلوب is cut **only after a human confirms** "yes, unsustained
  burst" (`spike_confirmed`) **and** the cap is activated for the run. This protects
  genuine new-product ramps (some ≥10× items are real launches — PAPIA tissue,
  ROQARIK — indistinguishable mechanically from a doctor-burst). When confirmed +
  active: order only **~1 month of coverage** at the recent rate ("buy a month, watch
  it"). When the burst sustains, prior rises next run → ratio drops → flag clears.

> **Calibration note:** rank by *ratio*, never by *value*. Value-ranking surfaces big
> steady sellers (CH-Alpha, CRESTOR, PLAVIX at 1–2×) that are normal growth, not
> spikes. The `%-of-year-in-last-quarter` confirms the split: STRONG items are 86–100 %
> recent, the excluded 4–6× band only 60–66 %.

### 3.2 🧊 Genuine dead stock (CURATIVE) — cash recovery

- **Dead** = `stock > 0` **AND** no sales in the last **6 months** **AND** not a
  `strategic_hold` (see §4.1).
- **Location-classified** for the right action: HQ-only → return; branch-only →
  transfer/redistribute/liquidate; both → obsolete (mark موقوف).
- **Cause hint** (heuristic tag, human-confirmable):
  - *supplier-push / central over-buy* — HQ-only + purchased but never sold.
  - *demand-died* — had sales earlier, none in 6 mo (the faded spike).
  - *variant-cannibalized* — an active sibling (same name-family/size) is selling
    (reuse the phantom name-prefix matcher).
  - *obsolete* — dead at both + aged / `itemnomoreuse=1`.
- **Value & aging:** frozen value = `stock × cost`; days since last sale.

### 3.3 📦 Overstock (CURATIVE) — trim & release

- **Overstock** = `coverage_months >` the per-ABC ceiling: **A = 4, B = 5, C = 6**
  (owner-set; distinct from the reorder *target* horizon).
- **Excess** = `stock − monthly_avg × ceiling`; releasable cash = `excess × cost`.
- Location-aware: excess at HQ → hold distribution; excess at branch → transfer back.

### 3.4 ↩️ Returnable (helper for dead/overstock actions)

- An item's stranded stock is **returnable** when its stock was sourced from a
  **returning supplier class** — distributor (ptclassif 20/60), manufacturer (70),
  drug warehouse (50). Buy-back/individual accounts do **not** take returns.
- Drives the **HQ-return list** vs the branch-transfer/liquidate list.

---

## 4. Business rules (owner-locked 2026-09-15)

### 4.1 Strategic hold
A **manual boolean** we set on the item (`strategic_hold`) — e.g. oncology / fridge
biologics deliberately kept for a known contract patient. Held items are **excluded**
from dead-stock flagging so they never nag.

### 4.2 Location is the master signal
HQ (softech branch `100`) vs branch tells the cause and the action. HQ-only dead ⇒
procurement/supplier-push (return centrally). Branch-only dead ⇒ demand died locally
(transfer/redistribute). Both ⇒ obsolete.

### 4.3 Aging window
Dead = **no sales in 6 months** (config `CASH_DEAD_MONTHS`).

### 4.4 Overstock ceilings
**A = 4 mo, B = 5 mo, C = 6 mo** (config, per-ABC).

### 4.5 Returns reality
Only **big distributors / manufacturers / warehouses** accept returns. HQ-return
suggestions are gated on the item's sourcing supplier class.

---

## 5. Validation (real data)

- **Awadist 1000 (130001):** sales Apr 1 / May 1 → **Aug 48 (burst)** → Sep 12; we
  **bought 130 in Aug** to chase it → 71 units stranded; already موقوف. Spike = **80×**.
- **Jutoxib 90mg (130892):** sales May 8 / Jun 6 → **Jul 46** → Aug 38 → Sep 28; we
  **bought 108 in Aug** → 17 units stranded; already موقوف. Spike = **41×**.
- Both are already `itemnomoreuse=1` — today's process is **manual and reactive**;
  this layer makes it **proactive**.
- Dead-stock location split and spike distribution as in §2.

---

## 6. Impact on شيت النواقص & the exported files

**On-screen** — a dedicated **«مخزون راكد / تجميد الكاش»** screen (mirrors the phantom
review page): tabs for spike / dead / overstock; split into an **HQ-return list** and
a **branch-transfer list**; `strategic_hold` toggle; confirm / exclude / override.

**Pivot export (شيت النواقص)** — new annotation columns (colored like the نقص/بديل &
وهمية columns), populated per item:

| Column | Content |
|---|---|
| `حالة الكاش` | راكد / فائض / ذروة غير مؤكدة / — |
| `القيمة المجمّدة` | frozen/excess value (EGP) |
| `مكان الركود` | الرئيسي / فرع / الشبكة |
| `السبب المرجّح` | supplier-push / demand-died / variant / obsolete |
| `الإجراء` | أرجِع للمورد / حوّل / أوقف / راقب |

**المطلوب (order qty)** — only the **spike cap** changes it, and only when activated
(`CASH_APPLY_SPIKE_CAP` / per-run flag, default OFF). Dead & overstock never change
المطلوب — they're already not ordered; they add the recovery annotations above.

---

## 7. Config (all tunable via settings/.env)

| Setting | Default | Meaning |
|---|---|---|
| `CASH_DEAD_MONTHS` | 6 | dead = no sales in N months |
| `CASH_OVERSTOCK_A/B/C` | 4 / 5 / 6 | overstock coverage ceiling per ABC |
| `CASH_SPIKE_MIN_RECENT` | 5 | min recent monthly rate to consider a spike |
| `CASH_SPIKE_RATIO` | 6 | recent/prior multiple to flag a spike |
| `CASH_SPIKE_CAP_MONTHS` | 1 | coverage to order for a spike item when capping |
| `CASH_APPLY_SPIKE_CAP` | False | DORMANT — activate the order cap per run |
| `CASH_SCAN_IN_ENGINE_RUN` | True | run the scan inline (MODULE 16) or via command |

---

## 8. Build sequence

1. **Spike-cap** (preventive; highest ROI, smallest, opt-in) — pure `spike_flag()` +
   an engine reduction step mirroring phantom's MODULE 10.6, dormant by default.
2. **Dead-stock recovery** — location-aware detector + `strategic_hold` field +
   recovery screen + export annotations.
3. **Overstock trim** — coverage-ceiling detector + excess-cash column.

Shared: one location-aware scan (MODULE 16 in the engine run), one review screen,
one set of export columns, catalog `strategic_hold` + `cash_*` fields.

---

## 9. Relationship to existing modules (extend, don't duplicate)

- **Phantom** (§built) — order *cut* for fake demand; this layer's spike cap reuses
  the same dormant/opt-in engine pattern (MODULE 10.6).
- **Transfer engine** (MODULE 12) — the branch-transfer actions reuse it, not a new one.
- **Advanced replenishment engine** — already has winsorize/Croston; the spike cap is
  a lighter, production-path guard aimed at the specific over-purchase behavior.
- **FEFO / purchase-expiry** — expiry-risk stock is a *related* frozen-cash lever;
  keep separate for now, cross-link on the recovery screen later.
- **Market shortage** — an item can be both; show the overlap badge as phantom does.

---

## 10. Decisions & future patterns

**Owner decisions (2026-09-15):**
- **Overstock returns stay ADVISORY** — the sheet/screen *recommends* returns; it does
  NOT auto-draft return-to-supplier documents. (Revisit only if the manual process
  proves too slow.)
- **Expiry backlog stays ADVISORY and separate** — do NOT fold FEFO/purchase-expiry
  into this recovery screen; surface it as an advisory cross-reference at most.
- **Spike threshold (6×) & cap (1 mo):** pending owner pick from enumerated examples
  (see the item lists provided 2026-09-15) — default 6× until confirmed.

**Future patterns (sized, not yet designed):** negative/thin-margin repeat buys,
supplier price arbitrage (buy cheapest reliable source), bonus/FOC over-buy, seasonal
misalignment.
