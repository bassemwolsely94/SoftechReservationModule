# SOFTECH Insurance Re-Price Writeback — Investigation & Design

> Status: **DESIGN / INVESTIGATION — no SOFTECH writes built yet.** This document
> is the stop-and-ask deliverable for the "edit the receipt price in SOFTECH so a
> reprinted receipt matches the re-priced claim" initiative. Nothing here writes
> to SOFTECH until the methodology below is approved.

## 1. Problem

When the pharmacy's catalog price for an item rises (e.g. OMEGAL ULTRA 30 CAP
240 → 270), a claim can be re-priced in our system (فحص الفروقات → apply current
master) so we invoice the new price. But the **SOFTECH receipt still holds the
old price**. When the insurance body cross-checks the printed SOFTECH receipt
against the claim, they disagree. To invoice the new price legitimately, the
SOFTECH receipt itself must be edited — across several tables, on **both HQ and
the branch node** — so a reprinted receipt is internally consistent.

The owner has already done this by hand on a couple of motalbas and reports that
earlier edits (especially **taxed items** and **items sold in units**) were not
always fully corrected. The requirement:

- Optional, **only on explicit request**, **per item or per receipt**.
- Change **every** dependent field across `stktrans`, `stktransm`, `branchesales`
  on HQ **and** the branch node, so the printed receipt is correct everywhere.
- Let the owner **review** all spotted (existing) and future edits.
- **Excel export** of every approved edit for revision.

## 2. Confirmed topology & write surface (live-verified 2026-09-13)

- **HQ** = `SOFTECHDB9` on `settings.SYBASE_HOST` (`get_sybase_connection`).
- Each branch runs its **own** ASE instance (`get_branch_connection(db_host)`),
  mapped in `apps.branches.models.Branch.effective_db_host`:
  - 130 `192.168.30.12` · 140 `192.168.4.11` · 150 `192.168.3.10`
  - 160 `192.168.1.5` · 170 `192.168.70.14` · 100/HQ = central host.
- Branch links are intermittent (VPN); connects retry 3× and can time out.
- Insurance sales are **doccode `115`** (the indirect-POS document type our own
  `pos_orders/writer.py` already creates — the *established* write methodology).

### Tables & fields a re-price edit must touch

**`stktrans`** (one row per line):

| field | meaning |
|---|---|
| `itemsaleprice` | public unit price (VAT-inclusive) |
| `itemsaleprice_tax` | price ex-VAT = `itemsaleprice / (1 + vat/100)` |
| `itemsalestax` | VAT portion of the **net** = `transprice × vat/(100+vat)` |
| `additionaldiscp` | **VAT rate** (14 for taxed items, else 0) |
| `custdiscp` | contract discount rate (e.g. 17) |
| `transprice` | net unit = `itemsaleprice × (1 − custdiscp/100)` |
| `transprice_total` | `transprice × transqty` |
| `transqty` | pack fraction (units: 0.66667 etc.) |
| `pharmacydiscp`, `origintaxp` | partial-pack / origin-tax markers |

**`stktransm`** (header): `docvalue` (net total), `docvalue1` (gross total),
`docvalue2`/`docvalue3` (tax/discount splits), `docvaluepay`, `patientpayment`,
`personnewbal` (points running balance).

**`branchesales`** (tender): `paymentvalue` must equal `docvalue`; `paymenttype`
10 = credit/آجل (insurance).

### Verified recompute (from live rows)

Normal item (OMEGAL, 240, 17% contract, no VAT):
`transprice = 240×0.83 = 199.20`, `transprice_total = 199.20`,
`itemsaleprice_tax = 240`, `itemsalestax = 0`, `additionaldiscp = 0`.

Taxed item (LIMITLESS PEA PLUS, 175, 14% VAT-inclusive, 17% contract):
`itemsaleprice_tax = 175/1.14 = 153.51`, `transprice = 175×0.83 = 145.25`,
`itemsalestax = 145.25×14/114 = 17.84`, `additionaldiscp = 14`,
`transprice_total = transprice × transqty` (units: `×1.5 = 217.88`).

**To change the price P→P′**, recompute per line with the *same* formulas using P′,
then re-foot the header: `docvalue1 = Σ(P′ × transqty)`,
`docvalue = Σ transprice_total′`, and set `branchesales.paymentvalue = docvalue`.
Points (`personnewbal`) only change if the item earns points — out of scope for v1
(flag, don't touch, unless approved).

## 3. Forensic sweep (BUILT — read-only)

`manage.py scan_softech_receipt_edits` compares every receipt line across
**frozen import vs HQ vs branch node** and flags:

- **EDITED** — SOFTECH ≠ our import snapshot (someone re-priced it in SOFTECH).
- **INCONSISTENT** — HQ ≠ branch (edit applied to one node only → printed branch
  receipt won't match HQ; this is the "imperfect earlier edits" detector).

Offline branch → degrades to EDITED-only for its receipts (never fails the sweep).
`--out report.json` emits the full structured diff (feeds the Excel export).

> **Findings (claim 74):** of 3,227 distinct (doc,branch,item), exactly **2 lines**
> are EDITED (SOFTECH ≠ import), both **taxed items on branch 140**:
> - `#549566` BETADINE 10% **85 → 95** · `#550282` OXIFREE **295 → 250**.
>
> **Verified golden — the owner's edits are complete & correct on HQ:** for both
> receipts the line recompute is right (95/1.14=83.33 ex-VAT, 95×0.83=78.85 net,
> ×14/114=9.68 VAT) **and** the header + tender were refooted:
> `docvalue`(net)=Σ`transprice_total`, `docvalue1`(gross)=Σ(`itemsaleprice`×qty),
> `docvalue3`=VAT total, `branchesales.paymentvalue`=`docvalue` — all exact.
> This is the **target end-state** the writeback must reproduce.
>
> **Unverified risk:** the branch-140 **node** was offline, so I could not confirm
> the same edit exists on the branch DB — if HQ was edited but the branch wasn't,
> the printed branch receipt is still wrong. The sweep's INCONSISTENT check covers
> this when the branch is reachable. Still TODO: decode `docvalue2` (net-ex-VAT
> component) before any write.

## 4. Proposed writeback (NOT built — needs approval)

A gated service extending `pos_orders/writer.py` conventions:

1. **Preview / dry-run (read-only, default).** For a chosen item/receipt, compute
   every field change on every table for HQ **and** branch, old→new, and show the
   re-footed header + tender. Nothing is written.
2. **Apply (explicit confirm, per item / per receipt).** Wrap HQ and each branch
   node in a real Sybase transaction (`conn.begin/commit/rollback`, `charset='cp1256'`
   for Arabic), write the recomputed line(s) + header + tender, verify by re-reading,
   commit; roll back both nodes on any error. **Idempotent** — re-applying the same
   target is a no-op if SOFTECH already matches the target.
3. **Full recompute** for normal / taxed / unit items per §2 (fixes the taxed & unit
   cases the owner had trouble with).
4. **Audit** every field change (who/when/receipt/branch/item/table/field/before→after)
   in a dedicated model; **revert** support (restore the recorded `before`).
5. **Review surface** listing all EDITED / INCONSISTENT receipts (from the sweep) and
   all applied edits, so the owner can revise.
6. **Excel export** of approved edits: receipt#, branch, item code/name, each changed
   field old→new, node (HQ/branch), applied-by/at.

## 5. Risks & safeguards

- Highest-risk operation in the system (writing posted transactional tables). Every
  write is **opt-in, per-target, dry-run-first, transactional, idempotent, audited,
  revertible**, and never batch-applied silently.
- Both nodes must succeed or both roll back (no half-edited receipt).
- Never touch fields outside the confirmed set; `personnewbal`/points left untouched
  in v1.
- Offline branch → **block** the apply for that receipt (can't keep nodes consistent),
  only preview.

## 6. Resolved decisions (owner, 2026-09-13)

**Field-change set for a price edit P→P′** (everything else is left byte-for-byte):

| table | CHANGE | LEAVE UNCHANGED |
|---|---|---|
| stktrans (edited line) | `itemsaleprice`, `itemsaleprice_tax`, `itemsalestax`, `transprice`, `transprice_total` | `transqty`, `custdiscp`, `additionaldiscp`(VAT rate), `newcostprice`, `rcostprice` |
| stktransm (header) | `docvalue`(net), `docvalue1`(gross), `docvalue3`(VAT total) | **`docvalue2` = total cost** (Σ newcostprice×qty — verified; independent of sale price) |
| branchesales | `paymentvalue` = new `docvalue` | `paymenttype` |

1. **`docvalue2` = total cost** (Σ `newcostprice`×qty — verified against goldens
   #549566=330.35, #550282=998.51). Used for profit calc; a sale-price edit does
   **not** change cost → writeback never touches it.
2. **`personnewbal` is NOT loyalty points** — it is the **contract client's
   cumulative credit/sales running total** (owner-confirmed). Recurrence verified
   exactly on live data: `personnewbal[i] = personnewbal[i−1] + docvalue[i]` — the
   running Σ `docvalue` for one contract client, keyed on **`cust_branch_code`**,
   ordered by `trans_time` **across all branches** (cust_branch_code=4227: every
   Δbal = that receipt's docvalue to the piaster).

   **Resolution — decoupled, idempotent forward-rebuild (best solution).** Do NOT
   cascade inside the per-line price edit. The price edit changes only the *local*
   receipt (`stktrans` lines + `docvalue`/`docvalue1`/`docvalue3` + tender). Then a
   **separate "rebalance" pass** recomputes `personnewbal` as the running Σ
   `docvalue` for each affected `cust_branch_code`, from the earliest edited receipt
   forward, across HQ + every branch node. Why this is the right answer:
   - **Correct** — matches SOFTECH's own verified recurrence.
   - **Self-healing** — also repairs any *prior* break (an earlier manual price edit
     that changed `docvalue` but not the downstream running balance).
   - **Idempotent & batched** — run once after all a claim's edits, safe to re-run;
     no fragile per-edit ripple.
   - **Bounded** — one contract client's chain from the edit date forward.
   - Atomic per node, audited (every touched `personnewbal` before→after),
     revertible; the preview shows the affected-receipt count per node first.
   - TODO: confirm returns/payments (`docvaluereturn`/`docvaluepay`, other doccodes)
     enter the running sum the same way before enabling the rebalance pass.
3. **Locked claims — BLOCK.** Apply is allowed only on `draft` claims; `submitted`/
   `paid` claims are refused (preview still allowed).

## 7. Phased plan

- **P0 (done):** schema + formula confirmation; read-only sweep command.
- **P1:** run sweep → catalogue the owner's existing edits; validate formulas against
  a real edited golden; finalize the recompute + open questions.
- **P2:** dry-run preview engine (read-only) + review surface + Excel export.
- **P3 (gated):** transactional apply (HQ + branch) + audit + revert. Owner live
  dry-run sign-off before enabling writes.
