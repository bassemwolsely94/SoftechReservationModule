# 30 — «التوزيعة» redesign: one plan, ordered waves, no conflicts

**Status:** 🟢 Phase A BUILT (2026-10-25). Phases B–D waiting for owner approval.
- Code: `apps/purchasing/isr_guards.py`; constraint `isrpush_one_live_draft_per_route` (migration purchasing/0037).
- Cleaned up: drafts #3–#8, #30, #32, #33, #34 cancelled with audit.
- Also includes the leg-order rule: HQ→branch only after its branch→HQ leg is pushed. That is the minimum of decision 3.
**Date:** 2026-10-24 (batch 5).
**Scope:** `apps/purchasing/distribution.py`, `isr_writer.create_distribution_proposals`,
the /supply «التوزيعة» and «طلبات التوريد / ISR» tabs.

The owner's complaint (2026-10-24): «التوزيعة» has
- a lot of redundancy;
- a lot of inter-branch transfers;
- no priority or dependency: nothing says which move should start before which;
- no view of how its ISR drafts conflict with each other.

---

## 1. What happens today (measured, read-only, 2026-10-24)

| Finding | Number |
|---|---|
| Suggestions in one analysis | **5,226**: over_piled 1,729 · never_stocked 1,876 · new_no_rate 1,603 · hq_dormant 18 |
| ISR drafts created by ONE «توليد» click | **45**: 5 HQ→branch + 20 branch pairs × 2 legs (branch→HQ, HQ→branch) |
| Moves that start at a branch (two legs through HQ) | **97%** (5,051 of 5,226) |
| Branch-sourced moves worth < 100 EGP (cost) | **2,586** (half of them) |
| Suggested (item → branch) already in a SOFTECH HQ ISR to that branch, last 3 days | **1,169** |
| Suggested (item → branch) already in transit to that branch | **64** |
| Value proposed (cost) | ≈ 1.25M EGP: never_stocked 474k · new_no_rate 454k · over_piled 305k · hq_dormant 11k |

How it works now:
- One analysis gives one suggestion per item (category, source, targets, quantity).
- «توليد» groups the suggestions by (source, destination). Each branch source becomes two separate ISR drafts; an HQ source becomes one.
- The engine run's stock is used for everything except the branch ceilings, which are read live.

### Defects found while measuring

1. **Double-post risk: duplicate live ISR drafts.**
   - Drafts #30 and #32 are identical to #29 (5,174 lines, 1.91M, HQ → 160), which is already **pushed** to SOFTECH.
   - Nothing stops a second live ISR for the same (kind, source, destination). Approving #30 would send the same ISR again.
   - Pressing «توليد» twice creates all 45 drafts twice.
2. **A leg from HQ to HQ:** draft #34 is «100 → 100», produced by the transfer pairing.
3. **Stale drafts never expire:** drafts from 19–20 Sep are still «proposed».
   - The seeding rotation only reads approved/pushed drafts, so proposed duplicates are invisible to it.
4. **No dependency between legs:** the HQ→branch leg of a transfer can be approved and pushed before its branch→HQ leg. HQ would then dispense from its own stock, or fail.
5. **Blind to every other flow:** it ignores
   - SOFTECH's own daily HQ ISRs (1,169 overlaps);
   - our replenishment drafts;
   - «تلبية طلبات الفروع» returns;
   - WhatsApp transfers;
   - in-transit goods.
6. **No order:** suggestions come out in database order; `limit` cuts at random.
7. **Expensive routes for trial quantities:** a 1–2 pack seed of a never-sold item goes branch → HQ → branch, two documents and two trips, even when HQ holds the item.

---

## 2. Target design

### 2.1 One movement plan per run, not one list per category

One *plan* is computed per run: a ledger of moves keyed `(item, from, to)`.
- An item appears **once per destination**, whatever category qualified it. The reasons are kept as tags.
- The plan is stored with its inputs and its time, for audit.
- New models: `DistributionPlan` (run, created_by, inputs snapshot, status) and `PlannedMove` (item, from, to, qty, wave, reasons, value, depends_on).
- The ISR drafts are generated **from the plan**, and each draft links back to it.

### 2.2 Wave 0: subtract what is already committed

Before any move is proposed, the destination's need is reduced by what is already on its way:
- open SOFTECH ISRs to that branch (server 100, last N days, not yet dispensed);
- our live drafts: IsrPush proposed / approved / pushed but not dispensed;
- in-transit transfers (the shared 14-day rule);
- WhatsApp transfers and fulfilment returns still live.

A move that would duplicate one of these is dropped and listed under «متعارض» with the document that already covers it.

### 2.3 Priority waves, in this order

| Wave | What | Source rule | Why first |
|---|---|---|---|
| 1 | **HQ first**: everything HQ can supply directly (never_stocked / new_no_rate / hq_dormant) | HQ only | one leg, one document; frees HQ dead stock |
| 2 | **over_piled**: excess above a branch ceiling → branches that sell it and have room | the piled-up branch | frees cash; ranked by excess value |
| 3 | **never_stocked from branches**: only from a branch that is itself over its ceiling | over-piled branches only | never strips a branch's only working stock |
| 4 | **new_no_rate trial seeds from branches**: only when HQ has none and the move is above the value threshold | branch, threshold-gated | the most speculative |

Within a wave, moves are ranked by value. The plan shows the waves in order, with totals per wave.

### 2.4 Value and handling thresholds (owner-configurable)

- **Minimum value per moved line**, default 100 EGP. Below that, a branch-sourced move is dropped. HQ moves stay, because HQ ships to that branch anyway.
- **Minimum value per route document**, default 1,000 EGP. A route below that is folded into the next run, not sent alone.

### 2.5 Fewer documents: one per source and one per destination

- Today one click produces 45 drafts. After consolidation there are at most:
  - **one branch→HQ ISR per source branch**;
  - **one HQ→branch ISR per destination**.
- With 5 branches that is at most 10 drafts. The HQ→branch draft has two parts:
  - **«جاهز الآن»:** lines HQ already holds.
  - **«بعد الاستلام من X»:** lines that arrive first from branch X.
- **Dependency (enforced by the server, not a hidden button):**
  - a «بعد الاستلام» part cannot be approved or pushed until its branch→HQ leg is pushed;
  - optionally, it waits until that leg is received at HQ (owner to choose).

### 2.6 Conflict and idempotency guards (also fixes defects 1–3)

- **One live draft per (kind, source, destination):**
  - a database constraint, like the existing origin constraints;
  - a new generation **supersedes** the old draft: cancelled with reason and link, audited; it is never duplicated.
- **Push guard:** a draft whose (kind, source, destination, lines) matches a pushed ISR from the last N days is refused. A deliberate re-send needs a reason.
- **Expiry:** an unpushed draft older than N days (default 7) expires with audit. The seeding rotation reads every live draft, not only approved/pushed ones.
- **Validation:** an HQ→HQ or branch→same-branch leg is rejected at creation.

### 2.7 Freshness and explanation

- **Live inputs:** branch stock and HQ stock are read live from server 100, the same read as the new ISR rule, instead of the engine snapshot. The plan shows the read time.
- **Why per move:** each move shows its reasons (category tags, ceiling vs stock, sells at N branches, item age), its wave and its value.

### 2.8 Screen

The «التوزيعة» tab becomes:
1. **Plan header:** time, inputs, totals per wave.
2. **Waves:** one sortable grid per wave.
3. **«متعارض» panel:** each conflicting move and the document that already covers it.
4. **Routes:** the documents, their dependencies and their status. Approve in order.

---

## 3. Small fixes that can go first (need the owner's OK)

1. Guard against a second live ISR draft for the same (kind, source, destination), plus the push guard (§2.6).
2. Reject HQ→HQ legs, and fix the transfer pairing that produced #34.
3. Clean up the existing drafts, after the owner looks at the list:
   - #30 and #32 are duplicates of pushed #29;
   - #3–#8 are from September.

These close the double-post risk without waiting for the redesign.

## 4. Phasing

| Phase | Content |
|---|---|
| A | §3 guards + cleanup (small; tests for each guard) |
| B | Plan ledger (`DistributionPlan`, `PlannedMove`) + wave 0 (committed-flow subtraction) + live inputs |
| C | Waves 1–4, thresholds, consolidation, dependency rule |
| D | Screen (§2.8) + help + Excel of the plan |

## 5. Decisions for the owner

1. Thresholds: 100 EGP per line and 1,000 EGP per document. Keep or change?
2. Wave order (§2.3). Keep or change?
3. Does the «بعد الاستلام» part wait for the leg to be **pushed** or **received at HQ**?
4. Draft expiry: 7 days?
5. Phase A now, separately, before the redesign?
