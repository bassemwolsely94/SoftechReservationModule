# POS Speed Wave — Design

**Date:** 2026-10-26 · **Status:** design, awaiting owner approval · **Builds on:**
[doc 20 — POS 3.0 Commerce OS](../../architecture/20_POS_3.0_COMMERCE_OS.md) (waves 1, 2, 3, 7, 8 already built).

## 1. Intent — why

The owner watched real sales at the counter and on the phone. Time is lost in six places:

1. Item search by name is slow; only **barcode** entry feels fast.
2. Checking **other-branch stock** is slow — the owner confirmed the slow place is **SOFTECH**, not our `/pos`.
   Staff leave the sale to look it up.
3. **Contract (تعاقد) sales** are re-typed from scratch every visit even for the same patient.
4. Creating a **new PIC** is slow because the **SOFTECH customer screen** demands many fields; retrieving an
   existing PIC is fast.
5. **FEFO / batch splitting** is done by hand.
6. Finding **similar products / alternatives** takes long; staff sometimes leave for the DrugEye website.

The goal: the operator should almost never type a full name, leave the POS to check a branch, or fill a form
from zero. Every field offers what we already know. "Barcode speed" becomes normal for every kind of entry.
Owner's words: *ultra fast, ultra useful, ultra sales-boosting, ultra time-saving.*

## 2. Goals, non-goals, anti-goals

**Goals**
- Fewer keystrokes and zero context switches per sale, in the agreed order: **1+3 (search + branch stock) →
  6 (contract) → 4 (PIC) → 2 (FEFO) → 5 (alternatives)**, with the visual redesign woven into each piece.
- Everything shown comes from data we already mirror; nothing new is read live from SOFTECH during a sale.
- **Owner decision: both surfaces in this wave** — desktop `/pos` (`POSOrderPage.jsx`) **and** mobile `/m/pos`
  (`MobilePOSOrderPage.jsx`). Shared rules/data go through the shared hook and backend so the two cannot drift;
  mobile adapts layout (touch, narrow width — e.g. the side preview becomes a bottom sheet), not behaviour.

**Non-goals (this wave)**
- No change to pricing, discounts, contract rates, co-pay math, tenders, checkout completion or the POS writer
  (`apps/pos_orders/writer.py`).
- No new search widget, no new customer model, no new audit system (CLAUDE.md rule 6; doc 20 §1).
- The rest of the 70-idea brainstorm is a ranked follow-on (§9), not this wave.

**Anti-goals (would be failure even if it "works")**
- A POS screen more crowded than today (owner: "so as not to bombard the POS screen").
- Any automatic drug substitution, or alternatives based on `name_scientific` (dirty — doc 12 rule 11).
- Any SOFTECH write that can double-post or bypass the established writeback discipline.
- Stock numbers shown without their age.

## 3. Constraints (from CLAUDE.md — apply to every piece)

- Backend owns rules; React displays decisions (rule 7). Permissions server-side (rule 9). Auditable (rule 8).
- Stop-and-ask before: anything touching payment/checkout, discount/pricing logic, SOFTECH-sync schema, or a
  new SOFTECH write. **Piece 4 step 2 is a new SOFTECH write → gated (§7).**
- Every batch: tests, `npm run build`, in-app help update (`apps/help/content/pos.py`, AR+EN, bump `updated`).
- Arabic RTL first. Use the existing design system `frontend/src/pos/design/` (Icon, Badge, StockBadge,
  BranchStockPill, ActionTile, SmartSuggestionCard, ErrorState…) — no screen invents its own badge or colour.
- Branch names via `useBranchLabels` — never a bare branch code.
- Wildcard search rules stay exactly as `apps/catalog/wildcard.py` defines them.

## 4. Piece 1+3 — Fast search with inline branch stock (owner chose **Layout A**)

**What exists:** `ItemSearchWidget` (PG-first search, SOFTECH live only when PG finds nothing),
`GET /api/items/{id}/stock/` (PG `ItemStock`, per branch, quarantine stores excluded — one item per call),
`StockLookupDrawer`, `ProductCard` (already supports `item.image`), `ProductMedia` (with `thumbnail`,
`is_primary`, `approved`). Branch stock is mirrored by the fast sync every 5 min (`SYNC_FAST_MINUTES`).

**Decided behaviour (Layout A, from the mockup):**
- One line per result: thumbnail · name with **strength in a bold chip** and form in small text · optional
  offer/cold/batch badges · **this-branch stock pill (bold)** · other-branch pills (green ≥ low threshold,
  amber low, red 0) · price. About 12 results visible.
- Search box shows "stock as of N min ago" (from the stock sync timestamp / freshness API).
- Keyboard: ↑↓ move · Enter add · **→ opens side preview** (large image, every branch's stock, last purchase
  by the current customer if any) · Esc closes. Barcode path unchanged.
- When stock here is 0, the row shows **one prominent next action**: transfer from the branch with most stock
  (opens the existing transfer create, prefilled) · else reserve (existing reservation) · if the whole network
  is 0 → record demand (existing `apps/demand`). Plus a secondary reserve button where relevant.
- Separate **image search view** (opened by a key; builder picks it): grid of product photos with this-branch
  pill + other-branch hint + badges; picking a tile adds it to the order and returns.

**Backend need (builder designs the shape):** the search response must carry, per result, primary approved
thumbnail URL and per-branch stock **in the same request** (no N+1 per-item stock calls). Extend the existing
item search endpoint/serializer; do not add a parallel search.

## 5. Piece 6 — Contract sales autocomplete and "last prescription"

**What exists:** the contract tab's 12 claim fields (`patientname, patientno, financialno, fileno, roshettano,
membershipno, deptname, patientnationality, relativedegree, comment, examdate, hi_typecode` — `blankClaim()`
in `usePosOrder.js`), per-contract field config via `apps/pos_orders/contract_fields.py` /
`contract_fields_view` (motalba f/t/te 1..12), revalidating repeat-order in `apps/customers/repeat_order.py`,
insurance claim mirror (`apps/insurance`), our own `SoftechSalesOrder` history.

**Decided behaviour:**
- Typing patient name or membership no. autocompletes from earlier sales **under the same contract**. Choosing
  one fills the stable fields (name, membership, file no., department, relationship, nationality, …).
- **Per-visit fields are cleared, highlighted and required** before send. Owner-confirmed principle; *my
  call:* default per-visit set = prescription/approval no. (`roshettano`) + exam date; which field carries the
  approval number is **configurable per contract**, since contracts differ.
- **«آخر روشتة» (last prescription)**: compact cards of this patient's last 3–5 contract sales (date, items,
  total). One click copies the items; each line is revalidated like repeat-order (current price, stock here,
  safety flags) and stays fully editable (qty, remove, add).
- *My call:* re-used approval number → **warning, not block**.
- *My call:* per-visit fields are **cleared and highlighted**, but only **block send** where that contract's
  existing field config already marks them required — no sale that goes through today may be stopped by this
  wave. The per-visit / approval-number mapping must point at one of the **existing 12 claim fields** (no new
  claim field → no SOFTECH writeback schema change); seeded default, editable by admin.
- Free-text contract fields (e.g. department) suggest values already used on that contract.
- Source of history: *left to builder* — our POS orders and/or the insurance motalba mirror; must not query
  SOFTECH live during the sale.

## 6. Piece 2 — Automatic FEFO split

**What exists:** server-side batch matrix `batch_availability.batch_action` (CASE 1–5) and `fefoFill` in
`usePosOrder.js` (distributes qty across batches earliest-expiry-first; shortfall → reservation line) — but
only inside the batch modal.

**Decided behaviour:**
- On qty entry for an item with multiple batches, the split is applied **without opening the modal**; the line
  shows "N batches" with expiry dates in small text; the modal opens only to change it.
- `batch_required` items (9 items, e.g. Entresto) keep the **explicit pick** (CASE 1) — unchanged. Single
  available batch stays auto-selected (CASE 2).
- The split rule lives on the server (rule 7); the existing client `fefoFill` becomes a consumer of it.
  Builder decides whether the server returns the split plan or validates it.
- *My call:* a **shortfall is never reserved silently** — the line shows a one-click «حجز الباقي» chip;
  creating the reservation stays an explicit human action (audit rule 8).
- *My call:* batch data source stays **as today** (live `stkbalexpiry` read on the branch node, via
  `batch_availability`), fetched **once per item add**; qty edits re-split from that cached result without new
  SOFTECH reads. The PG stock-expiry mirror is the fallback when the node is unreachable. (This is the one
  existing live read the §2 goal tolerates; no new live reads are added.)

## 7. Piece 4 — New PIC (SOFTECH customer creation)

The slow part is SOFTECH's own customer screen. Our POS «إضافة جديد» tab (`POSCustomerModal`) saves to our DB
only and produces no PIC.

- **Step 0 — quick wins (no SOFTECH write):** phone-first entry runs the existing recognizer
  (`GET /api/customers/recognize/`) and offers existing PICs with that number before anything is created
  (11.4k shared numbers already exist — doc 27). Autocomplete names, **areas, districts, streets/landmarks**
  from values already stored (`delivery` address fields `area`, `district`, `landmark`, `address_line`;
  customer `address`). Minimum fields only.
- **Step 1 — read-only study (IN this wave):** decode how SOFTECH creates a customer natively from
  **SELECTs only** — schema, required/NOT NULL columns, triggers, PIC number allocation, how recently created
  customers look at HQ vs branch nodes (replication). **Owner decision: no safe test server exists → no
  rollback probe, no trial inserts of any kind.** Output: a written findings doc.
- **Step 2 — create-PIC writer: OUT of this wave.** Deferred until a safe SOFTECH test target exists and the
  owner approves the step-1 findings. When it comes: minimum fields, idempotent (client token), read-back
  verified, audited, kill-switch default OFF, dry-run first — the existing writer discipline.
- New PICs continue to be created in SOFTECH during this wave.

## 8. Piece 5 — Similar products and alternatives

**What exists:** `apps/composition` (verified active-ingredient classes, `molecule_groups`, `molecules`,
search), Track A = search-first, Track B (auto substitution) gated.

**Decided behaviour:**
- A key on any search row opens a side-by-side comparison: same verified ingredient + strength first, then same
  ingredient other strength/form. Columns: image, name, strength, form, price, stock here, branch pills.
- Only **verified** ingredient data; never `name_scientific`. Every alternative shows "pharmacist confirmation
  required"; nothing is swapped automatically; choosing one adds it as a normal line.
- «ابحث في DrugEye» button opens `https://www.drugeye.pharorg.com/...` with the name prefilled (exact query
  parameter: builder verifies; if the site has no prefill URL, it opens the site and copies the name to the
  clipboard). We never scrape or store their data.

## 9. Visual redesign woven through, and the follow-on roadmap

Each piece above is delivered with the doc-20 design system, not as a separate redesign batch. Gaps in the
system to fill as pieces need them: `EmptyState` (actionable), a small sparkline/`MiniTimeline`, `CustomerChip`.
Emoji in mockups → Lucide icons in production.

**Follow-on (next waves, ranked by owner value; not in this wave):**
1. Server-backed held carts + "unfinished order" warning (today `localStorage` only).
2. Next-Best-Action moved server-side (today `workflow` is derived in `usePosOrder.js`).
3. Refill radar + "customer usually buys" strip in the POS (data in `apps/chronic`, refill reminders doc 26).
4. Customer savings indicator; "better offer found" (offers engine already picks best saving).
5. Search analytics + zero-result help (search → no click → demand).
6. Variant/strength chips.
7. WhatsApp text → draft basket (reuse the `/supply` WhatsApp-group matcher).
8. Packing screen with image + barcode verification.
9. Order completeness / split fulfilment / promise dates.
10. Manager live floor view, customer queue, time-saved (ROI) telemetry.
11. Look-alike/sound-alike warnings (needs a verified pairs list first).

## 10. Left to the builder

API shapes, component boundaries, caching, key bindings not named above, image-view entry key, thumbnail
sizes, how to measure the speed gain (suggested: time from first keystroke to line added — before/after).

## 11. Calls made by Claude (owner to check)

- Per-visit contract fields default to prescription/approval no. + exam date, configurable per contract.
- Re-used approval number = warning, not block.
- FEFO split rule moves server-side.
- DrugEye = link-out only, no data copying.
- FEFO shortfall → one-click «حجز الباقي», never a silent reservation.
- Batch source stays live `stkbalexpiry` (once per item add, cached for qty edits; PG mirror fallback).
- Contract per-visit fields block send only where the contract already requires them; mapping uses the
  existing 12 claim fields only.

## 12. Owner decisions recorded

- Order: 1+3 → 6 → 4 → 2 → 5, visual redesign woven through. Search layout **A** (one line + → preview).
- Slow branch-stock check was in SOFTECH. Slow PIC creation is the SOFTECH customer screen.
- Scope: desktop `/pos` **and** mobile `/m/pos`.
- No safe SOFTECH test server → PIC piece = quick wins + read-only study; no trial inserts; writer deferred.
