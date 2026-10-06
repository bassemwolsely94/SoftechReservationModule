# 23 — SOFTECH Supplier A/P Reconciliation (سداد فواتير الموردين) — Discovery & Spec

**Investigation date:** 2026-09-18
**Target:** SOFTECHDB9.dbo (Sybase ASE — HQ `192.168.1.8`, branch data consolidated at HQ)
**Mode:** read-only probe — `apps/sync/management/commands/probe_ap_reconciliation.py`
**Raw output:** `docs/architecture/softech_ap_reconciliation_investigation.txt`
**Status:** ✅ **Phase A COMPLETE** — the native سداد mechanism is fully reverse-engineered
from a real ground-truth voucher. No SOFTECH writes performed. No module code written yet.

**Owner decisions (2026-09-18):**
- **Scope:** BOTH supplier payables (doccode 10/120) **and** customer receivables (doccode 115/30) in the
  first build. ⇒ models are **party-agnostic** (`party_type ∈ {supplier, customer}`). This is natural:
  `cheques.personcode` is either, and `chequestrans` points at any `stktransm` doc via `doccode`.
- **Home:** extend **`apps/finance`** (it already reads `cheques`/`personsdata`/`stktransm` and owns the
  accounting query layer + schema-discovery infra). New models/engine/API/permissions live there.

**Siblings that already solved the hard problems (REUSE, don't reinvent):**
[`SOFTECH_SUPPLIER_INVOICE_WRITEBACK.md`](SOFTECH_SUPPLIER_INVOICE_WRITEBACK.md) (purchase doc = the
liability side) · [`14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md`](14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md)
(the safe-writer pattern) · [`apps/payments`](../../apps/payments/models.py) (matching/exception/anomaly
engine, customer side) · [`apps/finance/queries/sybase_accounting.py`](../../apps/finance/queries/sybase_accounting.py)
(verified read-only accounting query layer).

---

## 0. The question this answers
Does SOFTECH record an **explicit invoice↔payment allocation**, or is A/P only a running balance?
**Answer: it records an explicit allocation.** The "المدفوعات و المقبوضات → سداد فواتير" screen writes a
**payment voucher** (`cheques`) plus one **allocation line per settled invoice** (`chequestrans`), and also
stamps the invoice header's paid amount. So historical un-matched payments can be reconstructed by
recreating the missing `chequestrans` allocation (and the balance postings) — the same class of gated,
verified write-back already proven for POS sales and purchase invoices.

---

## 1. The three write surfaces of a سداد (CONFIRMED on a real document)

Ground truth = branch 130 voucher, serial **51703**, settling supplier invoice **12207** for **743.40 EGP**
(supplier `personcode=4471`, cash box "خزينة علياء" `bankcode=40`, 2026-09-18):

| # | Table | Role | Twin (staging) |
|---|---|---|---|
| 1 | **`cheques`** | Payment-voucher **header** (the صرف/استلام receipt) | `cheques5` / `cheques_5` |
| 2 | **`chequestrans`** | Invoice↔voucher **allocation lines** (the سداد فواتير grid) | `chequestrans5` |
| 3 | **`stktransm`** (the invoice) | Header `docvaluepay`↑ + `fatcurrentstatus`→`90` on full settle | `stktransm5` |

Plus balance side-effects (SOFTECH triggers own the math): supplier running balance
`personsdata` debit/credit buckets → `cheques.personnewbal` snapshot; cash/bank balance
`banks` → `cheques.banknewbal` snapshot.

### 1a. `cheques` — the voucher header (VERIFIED row + full 38-col schema)
```
cheqsno=51703        ← top مسلسل (voucher serial; key = branchcode + cheqsno, NOT globally unique)
cheqno='451'         ← inner مسلسل  (varchar(20))
ourcheqsno=31789     ← رقم إيصال الصرف/الإستلام (disbursement/receipt no; int)
financialdoccode='10'← payment instrument (see §2 master) — '10'=نقــدي (cash) here
cheqtype='20'        ← cheque-lifecycle dimension (separate from instrument)
cheqdate=2026-09-18  ← voucher date
bankcode='40'        ← cash box / bank ("خزينة علياء"); banks master, banktype 0=خزينة 1=bank
personcode='4471'    ← THE SUPPLIER (ptcode='20')
cheqvalue=743.40     ← صافي مبلغ مسدد (net paid); deductions in cheqvaluediscount/tax/damgha
chequenote='مورد 12207'  ← ملاحظات مورد — free text; here it echoes the settled invoice serial
personnewbal=-1598644.04 ← supplier running balance AFTER this voucher (negative = payable)
banknewbal=13272723.36   ← cash-box balance AFTER
open_trans=0  blockinv=0 ← blockinv=1 ⇔ the "منع سداد فواتير" checkbox
branchcode='130'  usercode  phcode  handedto  cheqvaluediscount/tax/damgha  bcurrency/bcrate ...
```

### 1b. `chequestrans` — the allocation line = **ReconciliationAllocation** (VERIFIED)
Full schema is only **10 columns** — clean and purpose-built:
```
cheqsno          int      ← FK → cheques.cheqsno (+ cheqbranchcode) = the voucher
branchcode       varchar  ← the settled INVOICE's branch
doccode          varchar  ← settled doc type: '10' purchase invoice ('120' return, etc.)
docnumber        numeric  ← settled invoice docnumber  ┐
docdate          datetime ← settled invoice docdate    �four-part FK → stktransm(invoice)
docvaluepaid     numeric  ← cumulative paid on this invoice (مسدد)
docvaluepaynow   numeric  ← amount paid by THIS voucher (المسدد الآن)  ← the allocation amount
usercode         varchar
cheqbranchcode   varchar  ← branch that owns the voucher (with cheqsno)
table_dumped     datetime
```
Real row: `cheqsno=51703, branchcode=130, doccode=10, docnumber=12207, docdate=2026-08-15,
docvaluepaid=743.40, docvaluepaynow=743.40, cheqbranchcode=130`.

**This one table gives us every cardinality natively:**
- **1↔1 / partial:** one row; `docvaluepaynow` < invoice `docvalue` ⇒ partial.
- **N payments → 1 invoice:** many rows across vouchers with the same `(branchcode,doccode,docnumber,docdate)`; `docvaluepaid` accumulates.
- **1 payment → N invoices:** many `chequestrans` rows with the same `cheqsno`.
- **Closed (مغلق ✓):** `Σ docvaluepaynow` over the invoice == invoice `docvalue` (and the invoice header shows `docvaluepay=docvalue`, `fatcurrentstatus=90`).

### 1c. The invoice header write-back (`stktransm`, VERIFIED)
The settled invoice `stktransm(130,10,12207,2026-08-15)` now reads `docvalue=743.40`,
**`docvaluepay=743.40`** (was 0 at credit-entry), `fatcurrentstatus=90`, `cust_branch_code=4471`,
`docnumber2=5213` (supplier printed no), `docpaydue=NULL`. ⇒ full settlement lifts `docvaluepay` to
`docvalue` and advances `fatcurrentstatus`. **Outstanding per invoice = `docvalue − docvaluepay`.**

---

## 2. `financialdocs` — payment-instrument master (VERIFIED, 8 rows)
| code | name | | code | name |
|---|---|---|---|---|
| 10 | نقــدي (cash) | | 40 | كمبيالة (bill of exchange) |
| 20 | شيك بنكي (bank cheque) | | 50 | إيصال أمانة (trust receipt) |
| 25 | ورقة دفع داخلية (internal pay note) | | 60 | سند إذني (promissory note) |
| 30 | بطاقة إئتمان (credit card) | | 90 | قيد تسوية (settlement/adjustment entry) |

`cheques.financialdoccode` = instrument. `'90' قيد تسوية` is how a **pure balance adjustment** (no real
money) is booked — relevant for reconstructing legacy write-offs / opening differences.

---

## 3. Balances & opening balances (for the حصر equation)
- **A/P is NOT a general ledger** — `acctrans/2/3` are EMPTY (accounting module inactive), `custpayments`
  and `empsalaries` empty too. Supplier A/P = a **running `personsdata` balance**
  (`persondebit+1+2 − personcredit+1+2`), snapshotted as `personnewbal` on every doc/voucher.
  Trigger math (captured earlier, `fa_fixedassetsm` analog):
  `personnewbal = personoldbal ∓ (docvalue − docvaluepay)`.
- **Opening balances:** `personsopenbal` (with an `opentrans` flag) — the opening term of
  `Opening + Purchases − Payments ± Adjustments = Closing`. `banksopenbal` / `expensesopenbal` mirror it.
- **Reconciliation equation (per supplier):** reconstruct from `stktransm` (10/120 = purchases/returns) +
  `cheques`/`chequestrans` (payments/allocations) + `personsopenbal`, and compare the computed closing
  against SOFTECH's `personnewbal`. Target: **unexplained variance = 0** or every remainder explained.

---

## 4. Canonical internal model → SOFTECH mapping
| Internal entity | Fed from (read) | Written back to (Phase G) |
|---|---|---|
| `Supplier` (thin; maps `VendorProfile.softech_personcode`) | `personsdata` ptcode='20' | — |
| `PurchaseInvoice` | `stktransm/stktrans` doccode 10/120 | `docvaluepay`/`fatcurrentstatus` on settle |
| `Payment` (voucher) | `cheques` (financialdoccode, personcode, cheqvalue, personnewbal, banknewbal) | INSERT `cheques` |
| `ReconciliationAllocation` | **`chequestrans`** (docvaluepaynow) | INSERT `chequestrans` |
| `Reconciliation` (run/group) | derived | — |
| `MatchCandidate` / `MatchEvidence` | engine | — |
| opening term | `personsopenbal` | — |
| `AuditEvent` | reuse `apps/audit.AuditLog` + `AbuseFlag` | — |

Allocation is stored as **"invoice ← amount from voucher"** (mirrors `chequestrans.docvaluepaynow`), never
merely "invoice = paid".

---

## 5. Write-back architecture (Phase G — GATED, not built)
`SOFTECH → Read Layer → Engine → Proposal → Validation → Approval → Write Adapter → SOFTECH`.
The adapter reuses the proven [`apps/invoices/writer.py`](../../apps/invoices/writer.py) /
[`apps/pos_orders/writer.py`](../../apps/pos_orders/writer.py) playbook verbatim:
- Dedicated `AP_RECONCILE_WRITER_ENABLED` kill-switch (default **off** → dry-run plan only).
- Serial allocation the native way: read the branch's `cheques` serial (+ `ourcheqsno`) under HOLDLOCK, **+1**,
  INSERT, let triggers settle — never pre-UPDATE. (Confirm the exact counter in `lastdocnumbers` via a
  rollback probe — same `trigger_bumped_counter` check used for the invoice writer.)
- Inline-literal INSERTs, cp1256 charset, verify-readback, idempotency tag, queue-on-unreachable.
- **Pre-write validation:** invoice & voucher still exist and unchanged (snapshot hash), supplier matches,
  `Σ docvaluepaynow ≤ voucher cheqvalue` and `≤ invoice outstanding`, not already allocated, not
  cancelled/reversed, no concurrent change.
- **Idempotent:** re-running an approved allocation must not double-post (guard on
  `(cheqbranchcode, cheqsno, branchcode, doccode, docnumber, docdate)`).
- **Unknown to settle before any commit:** the exact side-effect set — does inserting `chequestrans`
  alone fire triggers that bump `stktransm.docvaluepay` + `personnewbal` + `banknewbal`, or does the
  native client write all four surfaces itself? Resolve by a **rollback probe / clone-and-diff** on a real
  voucher (real INSERT → read back → ROLLBACK, zero residue), exactly like `clone_purchase`.

---

## 6. Shadow-mode validation (Phase D)
4–5 years of `cheques`+`chequestrans` are already correctly reconciled in SOFTECH → a free labelled set.
Hide `chequestrans` from the matcher, ask it to reconstruct each voucher's allocations from
supplier+amount+`chequenote`+date+`docvaluepay`, and measure precision/recall/confidence calibration to
set safe auto-reconcile thresholds. The *historical problem set* (payments with **no** `chequestrans`) is
found by: `cheques` rows (financialdoccode payment, supplier personcode) with **no** matching
`chequestrans`, against invoices with `docvaluepay < docvalue`.

---

## 7. Candidate generation & scoring (Phase C)
Block by supplier `personcode` (hard), then within supplier by amount band, `chequenote` token overlap
(the note frequently embeds the invoice serial, e.g. `مورد 12207`), date window vs the supplier's learned
pay-lag, and branch. Global (not greedy) resolution per supplier via weighted bipartite matching, subset-sum
only inside small amount clusters. Every signal → an explainable `MatchEvidence` row; confidence class
HIGH/MEDIUM/LOW/CONFLICT.

---

## 8. Open items before Phase C build (small)
1. Confirm the `cheques` serial counter in `lastdocnumbers` (which column bumps for financialdoc payments)
   — read-only rollback probe. *(Phase G concern, not C.)*
2. Confirm behaviour when a voucher settles across branches (`cheqbranchcode` ≠ invoice `branchcode`) —
   the schema supports it; capture one real example.
3. Confirm returned-cheque / reversal path (`refuse_reason`, `payrefusesno`, `cheques_del`) for §23 reversal.
4. Owner: is scope supplier A/P **only** (money out), or also customer receipts (same tables, doccode 115/30)?

## 9. Build progress
- ✅ **Phase C batch 1 (2026-09-18)** — canonical read-only models shipped in `apps/finance`
  (`recon_models.py`, migration `finance/0005`): `ReconParty`, `APInvoice`, `Payment`, `Allocation`,
  `ReconciliationRun`, `MatchCandidate`, `MatchEvidence`, `ReconException`, `ReconAuditEvent`. Party-agnostic
  (supplier + customer). Admin registered. 17 model tests green (`apps/tests/test_reconciliation.py`),
  incl. the golden 51703→12207 allocation + all four cardinalities. **No SOFTECH writes.**
- ✅ **Phase C batch 2 (2026-09-18)** — read-only ingest shipped: `apps/finance/recon_ingest.py` (pure,
  SOFTECH-free transform/upsert core) + `apps/finance/queries/sybase_reconciliation.py` (3 bounded
  SELECT-only feeds: `stktransm` invoices, `cheques` vouchers, `chequestrans` allocations) +
  `sync_ap_reconciliation` command (`--party-type/--from/--to/--days/--branch/--personcode/--dry-run`,
  records a `ReconciliationRun`). 12 ingest tests green (`apps/tests/test_reconciliation_ingest.py`).
  **Live-validated** on supplier 4471 / branch 130 / Aug–Sep 2026: 70 invoices, 73 vouchers, 1 allocation
  → **72/73 vouchers flagged `is_unallocated`** — the historical under-reconciliation, surfaced directly.
  Golden link reproduced (130/51703 → 10/12207 @ 743.40). Idempotent + drift-detecting `source_hash`.
  **Open item:** some `personsdata.personname` are NULL for suppliers (real name lives in a branch-level
  table e.g. `customerbranches.custbranchname`) → party `name` can be blank; personcode is the key, so
  non-blocking. Resolve the canonical supplier-name source in C3/C4.
- ✅ **Phase C batch 3 (2026-09-18)** — matching engine shipped: `apps/finance/recon_engine.py`
  (versioned scoring `SCORING_V1`/`RULES_VERSION='v1'` — weights amount 45 / reference 35 / temporal 15 /
  branch 5; blocked candidate gen; capacity-aware non-greedy resolution; invoice-side conflict marking;
  anomaly emission) + `run_ap_matching` command + 13 tests (`apps/tests/test_reconciliation_engine.py`).
  Matches **unallocated payments → invoices by *unlinked* amount** (doc_value − Σ allocations), so
  SOFTECH-paid-but-unlinked invoices are still matchable. **Live-validated** on supplier 4471: **75
  candidates — 42 HIGH (100% score), 29 medium, 3 conflict — + 5 exceptions (3 orphan, 2 duplicate
  payment)**. The dominant signal is the invoice serial embedded in the voucher note (`"مورد 12348"`),
  exactly reconstructing links SOFTECH never recorded. **Proposals only — no Allocation rows, no SOFTECH
  writes.** Confidence classes: HIGH ≥85 / MEDIUM ≥60 / LOW; CONFLICT = ≥2 amount-exact payments claiming
  one invoice.
- ✅ **Phase C batch 4 (2026-09-18)** — read-only API shipped: `apps/finance/recon_serializers.py` +
  `apps/finance/recon_views.py`, mounted under `/api/finance/reconciliation/` (`dashboard/`, `parties/`,
  `parties/<personcode>/ledger/`, `invoices/`, `payments/`, `candidates/`, `exceptions/`, `workbench/`,
  `runs/`). All `IsAuthenticated`, paginated, filterable (party_type/personcode/branch + per-list facets);
  `workbench/?invoice=|?payment=` returns the 3-pane payload (focus + candidates-with-evidence + existing
  allocations); `ledger/` computes `Opening + Purchases − Returns − Payments = Expected Closing` vs
  `softech_balance`. 12 API tests (`apps/tests/test_reconciliation_api.py`). **Live-validated** on supplier
  4471: dashboard = 70 inv / 73 pay / 72 unallocated / 75 candidates (42 high) / 5 exceptions; ledger
  expected_closing 1,679.52. **All read-only — no approval mutation, no SOFTECH writes.**
  **Open item:** `ReconParty.softech_balance` is not populated by C2 ingest yet (defaults 0), so
  `unexplained_variance` is not meaningful until we snapshot the SOFTECH running balance — do this in the
  ingest / Phase F (read `cheques.personnewbal` latest + `personsopenbal`).
- ✅ **Phase E (2026-09-18)** — approval actions shipped: `apps/finance/recon_actions.py` (pure,
  capacity-guarded: `approve_candidate` [full/partial], `reject_candidate`, `manual_allocate`,
  `undo_allocation`) + 4 POST endpoints (`candidates/<id>/approve|reject/`, `allocations/manual/`,
  `allocations/<id>/undo/`, all RBAC-gated to admin/pharmacist) + `APInvoice.linked_amount/unlinked_amount`
  properties. Every action writes an immutable `ReconAuditEvent` (before/after snapshot). Guards: amount>0,
  ≤ invoice unlinked, ≤ payment unallocated, same party, one Allocation per (payment,invoice); native
  `origin='softech'`/`'written'` allocations are NOT undoable here (that's Phase-G reversal). Approving
  creates an `origin='approved'` Allocation — **still NO SOFTECH write** (Phase G consumes these). 14 tests
  (`apps/tests/test_reconciliation_actions.py`). **Live-validated**: approved real candidate (inv 12362 ←
  pay 51684 @ 840.00) → allocation + flag flip + audit, then clean undo. Full suite = **68 tests green**.
- ✅ **Phase F (2026-09-18)** — حصر reconstruction + balance snapshot shipped:
  `queries/sybase_reconciliation.get_party_balances` (personsdata, OWED convention: `softech_balance =
  Σcredit−Σdebit`, `opening = personopencredit−personopendebit`, batched IN) + `recon_balances.py`
  (`apply_balances` snapshot + name/ptclassif backfill; `reconciliation_equation`; `build_ledger_timeline`
  chronological signed events + running owed balance) + `snapshot_ap_balances` command (also auto-run at the
  end of `sync_ap_reconciliation`) + `parties/<pc>/timeline/` endpoint. 6 tests
  (`apps/tests/test_reconciliation_balances.py`). **Live on 4471:** name backfilled
  ("مورد شركات 30 - Contract Supplier 30%" — closes the C4 blank-name item), `softech_balance` 1,593,666.38
  owed, equation `0 + 73,898.02 − 2,214.10 − 70,004.40 = 1,679.52`, 143-event timeline.
  **NOTE:** `unexplained_variance` is only meaningful after a **full-history ingest** — with a 2-month
  window vs an all-time balance the variance is expectedly large (1.59M); it converges to ~0 once the owner
  runs `sync_ap_reconciliation` across the full 4–5-yr range. Read-only throughout.
- 🔬 **Phase G step 1 (2026-09-18) — write-path DISCOVERY (read-only) DONE:**
  `apps/sync/management/commands/probe_ap_writeback.py` (discovery default = SELECT-only; a
  double-gated `--rehearse` rollback harness is built but NOT run). Raw:
  `docs/architecture/softech_ap_writeback_investigation.txt`. Findings:
  - **Write surface = bare DML, no stored proc.** `sysdepends` shows the ONLY object referencing
    `cheques`/`chequestrans` is `tr_cheques_insert` — there is no save PROC (same as the purchase/sales
    writers). `chequestrans` has **no trigger at all**.
  - **`tr_cheques_insert` is ENCRYPTED** (35 syscomments rows, 0 with text) — its balance-posting math
    (`personnewbal`/`banknewbal` → `personsdata`/`banks`) cannot be read; must be observed empirically.
  - **Serial = per-branch dense sequence.** No cheque counter in `lastdocnumbers` (its `paymentsno=8343`
    at HQ `000` is the branchesales/localpayment serial, unrelated). Branch 130: `MAX(cheqsno)=51709`,
    `COUNT=51709` (dense 1..N) and `MAX(ourcheqsno)=31793` ⇒ allocate `cheqsno/ourcheqsno = MAX+1` per
    branch under HOLDLOCK.
  - **Implied writer = THREE statements:** INSERT `cheques` (trigger posts balances) + INSERT
    `chequestrans` (no trigger) + **UPDATE `stktransm.docvaluepay`(+`fatcurrentstatus`)** — because nothing
    cascades the invoice-header paid amount when `chequestrans` has no trigger.
  - **Still UNKNOWN (only the rollback rehearsal answers, zero-residue):** (1) is a client-chosen `cheqsno`
    accepted or does the trigger assign it? (2) does `tr_cheques_insert` auto-set `personnewbal`/`banknewbal`
    or must the client compute them? (3) is the `stktransm.docvaluepay` update client-side (almost
    certainly yes)? (4) is a bare INSERT even permitted, or rejected like `tr_stktrans` (err 2732)?
- ⛔ **Phase G step 2 (2026-09-18) — ROLLBACK REHEARSAL RAN (owner-approved, zero residue) → BARE-DML
  WRITE-BACK IS BLOCKED.** With both gates, allocated `cheqsno=51710`, inserted a minimal `cheques` voucher
  (marker note, `personnewbal/banknewbal=0` sentinels) inside one transaction. Result:
  - the INSERT "executed" with **no client exception**, but the row was **not visible in-transaction** on
    read-back by its marker, and a combined `INSERT … SELECT @@error,@@rowcount` batch returned **no result
    set** (the batch was aborted mid-way);
  - **residue check = 0**, `MAX(cheqsno)` unchanged at 51709 — the rehearsal was truly side-effect-free.
  - This is the exact **`rollback trigger`** signature of `tr_stktrans` (err 2732) documented in
    [`SOFTECH_SUPPLIER_INVOICE_WRITEBACK.md`](SOFTECH_SUPPLIER_INVOICE_WRITEBACK.md). The encrypted
    `tr_cheques_insert` silently discards a bare-DML insert that lacks the native client's session context
    (temp tables / running-balance state / duplicate guard).
  ⇒ **Direct bare-DML write-back of سداد is NOT viable**, the same blocker as the purchase-invoice writer.
  The gated bare-DML writer will **not** be built. Two real options for actual write-back (owner-driven,
  separate effort): **(a)** obtain the vendor's `tr_cheques_insert` source/spec, or **(b)** capture the
  native client's exact Save-time DML + session setup during one real سداد via ASE monitoring
  (`monSysSQLText`) and replay it — the same approach flagged for the invoice writer.
- ✅ **Net Phase-G outcome:** the RECONSTRUCTION/analysis side (A–F) is fully viable and shipped and needs
  no SOFTECH write. The correct product today is the **read-only reconstruction + human-approved mirror
  allocations**; the optional SOFTECH write-back is gated behind vendor source or session-capture and is out
  of scope until the owner pursues (a)/(b). Approved allocations (`origin='approved'`) remain the queue a
  future writer would consume.
- ✅ **Reconciliation UI (2026-09-19)** — `frontend/src/pages/ReconciliationPage.jsx` at `/reconciliation`
  (RBAC admin/purchasing/pharmacist; sidebar «سداد الموردين» in the finance section; `reconciliationApi`
  in `api/client.js`). KPI tiles + supplier/customer + personcode scope; three tabs: **المقترحات**
  (candidate review rows — expand to invoice/payment detail + ✓≈⚠✕ evidence chips + Approve/Reject, gated
  by confidence filter), **الاستثناءات** (open anomalies by severity), **الحصر** (party list → ledger
  drawer with the equation + running-balance timeline). Approve/Reject call the Phase-E endpoints (mirror
  only). `npm run build` green (1262 modules, no errors). Verified at build + API level (54 API tests);
  in-browser render pending owner login.
- 🔎 **Full-history ingest — validated on supplier 4471 (2026-09-19):** ingested its complete history
  (2019-06 → 2026-09, all branches): **12,940 invoices, 12,945 vouchers, but only 1,110 native
  `chequestrans` allocations — 11,893 payments (92%) were never formally reconciled in SOFTECH.** Matching
  at scale: 23,532 candidates (418 HIGH ≈ 381K EGP, 3,455 medium, 6,806 low, **12,857 conflict**) + 11,157
  exceptions. The high conflict share is *correct caution* — over 8 years many same-amount payments compete
  for an invoice, so the engine flags rather than guesses; the invoice-serial-in-note signal is the
  discriminator that isolates the 418 slam-dunks.
- ⚠️ **حصر variance does NOT converge with the simple model — an honest, important finding.** For 4471:
  `Opening 0 + Purchases 8,047,003 − Returns 51,258 − Payments 8,173,308 = Expected −177,563`, but
  `softech_balance` (personsdata `Σcredit−Σdebit`) = **1,593,666 owed** → variance ≈ **1.77M**. Data is fully
  captured (min date 2019-06 inside the window; cheques clean — 0 refused, all `financialdoccode=10`), so
  the gap is real: SOFTECH's `personcredit` (9.56M) exceeds our stktransm `docvalue` sum (8.05M) by ~1.5M
  (~18% — consistent with VAT/other postings entering the A/P balance beyond net `docvalue`). ⇒ purchases +
  payments alone don't explain the ledger balance; the true running balance lives in the per-document
  `personnewbal` snapshots. **Refinement (future F2):** drive the timeline's running balance from the
  `personnewbal`/`banknewbal` snapshots (SOFTECH's own truth) and treat the purchases−payments equation as a
  cross-check, so `unexplained_variance` isolates genuinely-missing money rather than posting-model gaps.
  This is the same "SOFTECH posting semantics are richer than they look" lesson as the write path — the tool
  is correctly *surfacing* it (§15), not hiding it.
- ✅ **Phase F2 (2026-09-19) — personnewbal-snapshot balance reconstruction DONE.** Added
  `APInvoice.person_new_bal`/`trans_time` + `Payment.trans_time` (migration `finance/0006`), captured in the
  ingest (`get_invoices`/`get_vouchers` now select `personnewbal`+`trans_time`; `_as_datetime` normalises the
  ISO `T` separator — the bug that first left `trans_time` NULL). `recon_balances` now derives
  `snapshot_balance = −(latest doc's personnewbal)` and splits the variance:
  `model_vs_snapshot` (posting-model gap) + `snapshot_vs_softech` (should ≈0). Ledger drawer UI shows the new
  tiles and a **real SOFTECH balance-after-each-event** trail. 2 new tests (76 total green); `npm run build`
  green. **Live on 4471 (full history):** `snapshot_balance = softech_balance = 1,593,666.38` →
  **`snapshot_vs_softech = 0.00`** (the personnewbal trail reconstructs the master ledger EXACTLY), and the
  1.77M is now correctly attributed as `model_vs_snapshot` = **a posting-model gap (VAT/other), not missing
  money**. The حصر now *explains* the variance instead of merely flagging it (§15).
- ⛔ **Phase F3 investigation (2026-09-19) — the model canNOT be honestly made to tie out; snapshot stays
  authoritative.** Goal was to recover the `model_vs_snapshot` gap (4471: 1.77M) as VAT/tax so
  `expected_closing` == `snapshot_balance`. Empirically ruled out **every** available source:
  `origintaxp` = 0 (no header tax), line `itemsalestax` ≈ 977 (negligible), line gross
  `Σ(transprice_total+tax)` = 8,052,329 ≈ header `docvalue` 8,049,143, `docvaluebc` = `docvalue`, voucher
  deductions (discount/tax/damgha/other) = 0. Yet `personcredit` = 9,565,589 exceeds every purchase-value
  measure (~8.05M) by ~1.5M, and `persondebit` (7.97M) is ~0.2M below the cheque total (8.18M). ⇒ the extra
  personsdata movement has a **source outside the purchase(10/120)+cheque docs** (manual/other postings) and
  is **not deterministically recoverable** from the fields we have — the same encrypted-posting-semantics
  wall as the write path. **Decision:** do NOT fabricate a tax tie-out; the `personnewbal` SNAPSHOT (F2)
  remains the authoritative balance (ties to master exactly), and `model_vs_snapshot` is honestly labelled a
  "SOFTECH posting difference (source outside purchase/payment docs)" in the UI + `recon_balances`. (Also
  noted: per-doc delta attribution is confounded by `trans_time` ties — another reason the snapshot total,
  not per-doc model deltas, is the source of truth.)
- ✅ **Phase H (2026-09-19) — deeper anomaly scan.** `apps/finance/recon_anomalies.py` + `scan_ap_anomalies`
  command: **duplicate_invoice** (same supplier doc-no `docnumber2` + value on ≥2 of our docs within a
  90-day window — the window excludes year-over-year invoice-number reuse), **overpayment** (Σ allocations >
  invoice `doc_value`), and **statistical payment outliers** (per-party z-score > 3, floor 1000). Idempotent
  (no duplicate open exception), emits `ReconException`, read-only. 8 tests
  (`apps/tests/test_reconciliation_anomalies.py`); full suite = **84 green**. Live on 4471: 1,021 duplicate
  candidates + 17 payment outliers (0 overpayments). *Caveat:* duplicate-invoice sensitivity depends on
  `docnumber2` quality per supplier — a review queue, tune per owner feedback.
- ✅ **Bulk backfill (2026-09-19) — `backfill_ap_reconciliation` command.** Chunked (month|year), idempotent/
  resumable, read-only; iterates the range so no query scans the base tables wholesale, snapshots balances at
  the end, optional `--match`. Designed to run **scheduled off-hours** (one busy supplier ≈ 13K invoices /
  24K candidate rows). Verified end-to-end on a bounded slice: a 10-day all-supplier window ingested 776
  invoices / 622 vouchers / 342 allocations across **46 distinct supplier parties**. The full multi-year
  estate run is an owner-scheduled job.
- ✅ **Multi-year backfill run (2026-09-20):** `backfill_ap_reconciliation --party-type supplier
  --from-year 2023 --chunk month` — 48 chunks, **0 errors, 79,637 invoices / 60,115 vouchers / 36,055
  allocations across 307 suppliers**, balances snapshotted for all 307. Estate-wide the mirror now holds
  84,369 invoices / 62,474 payments / 36,055 allocations — **49,294 payments (79%) never formally reconciled
  in SOFTECH.**
- ✅ **Daily schedule (2026-09-20):** APScheduler job `ap_reconciliation_sync` (07:30, `apps/sync/tasks.py`
  `_run_ap_reconciliation_sync`) — daily INCREMENTAL `sync_ap_reconciliation` over a rolling ~4-month window
  (idempotent; catches new + back-dated سداد) + balance snapshot. Takes effect on the `run_scheduler`
  process. The one-time historical load stays the manual `backfill_ap_reconciliation` run.
- 🔬 **Write-back pursuit — Phase G option (b) capture harness READY (2026-09-20).** Since bare-DML is blocked
  by the encrypted `tr_cheques_insert`, the viable path is to capture the native client's exact Save-time DML
  + session context during a REAL سداد and replay it (the method that de-risked the purchase/POS writers).
  `apps/sync/management/commands/capture_save_sql.py` extended with `--out` (write to
  `softech_ap_save_sql_capture.txt`, not clobber the purchase capture) and `--preflight-only`. **Preflight
  confirmed: ASE monitoring is ON** (`enable monitoring`=1, `sql text pipe active`=1) and `monSysSQLText` is
  readable. **Owner step required (interactive):** identify your SofTech client SPID (preflight lists
  `sysprocesses` hostnames/logins), then run
  `capture_save_sql --spid <SPID> --seconds 90 --out softech_ap_save_sql_capture.txt` and click **Save** on
  ONE سداد within the window. The captured `cheques`+`chequestrans`+`stktransm.docvaluepay` DML sequence
  (and any temp-table/proc session setup) is what the gated writer will replicate. NO SOFTECH business data
  is modified by the capture (read-only MDA).
- 🔬 **Capture progress (2026-09-20).** `monSysSQLText` is a shared ring buffer and got flooded/evicted by a
  concurrent `stkbal` stock report + the branch-150 replication agent (`…table_dumped…` sweeps), so early
  captures missed the save. Switched to `--source procsql` (`monProcessSQLText`, per-process current SQL) at
  0.1s poll and **captured the third write surface verbatim** from a real سداد of invoice 12363 (406.70) on
  **SPID 30** (BASSEM):
  `UPDATE stktransm SET fatcurrentstatus='90', docvaluepay=406.70, docvaluepaybc=406.70 WHERE branchcode='130'
  AND doccode='10' AND docnumber=12363 AND docdate='9-17-2026 0:0:0.000'` — **confirms the client-side
  invoice-header write-back exactly as predicted** (docvaluepay + `docvaluepaybc` + fatcurrentstatus→90).
  Still MISSING the `cheques` header INSERT + `chequestrans` allocation INSERT (they executed between polls).
  Next capture: `--source syssql --spid 30 --pipe-messages 200000` (completed-statement pipe, buffer
  enlarged so the flood can't evict the save; `--pipe-messages` added to the command, restored after) → gets
  all three statements in order + any preceding `set`/temp-table/proc that lets `tr_cheques_insert` accept
  the insert.
- ✅ **Capture 2 (2026-09-20) — the SETTLEMENT transaction captured verbatim** (SPID 30, `syssql`,
  pipe=200000), settling invoice 12362 (840.00) by voucher `cheqsno=51684`. Full ordered sequence:
  1. `SELECT docvaluepay,docvalue,bcurrency,docvaluebc,docvaluepaybc,bcrate FROM stktransm WHERE …12362…`
     (pre-read the invoice state);
  2. `UPDATE stktransm SET fatcurrentstatus='90', docvaluepay=840.00, docvaluepaybc=840.00 WHERE …12362…`;
  3. `UPDATE patientdata SET custtotalpay = custtotalpay + 840.00 WHERE branchcode='130' AND labno=12362`
     (a running paid-total side table — 4th surface, investigate whether supplier-relevant or a generic
     docnumber-keyed bump);
  4. **`INSERT INTO chequestrans (cheqsno,branchcode,doccode,docnumber,docdate,usercode,docvaluepaid,
     docvaluepaynow,cheqbranchcode) VALUES (51684,'130','10',12362,'9-17-2026 0:0:0.000','1509',840.0,840.0,
     '130')`** — the allocation insert, **plain bare DML** (confirms `chequestrans` has no trigger);
  5. `commit tran`.
  ⇒ `chequestrans` + `stktransm`(+`patientdata`) are plain DML the writer can replicate directly. **STILL
  MISSING: the `cheques` header INSERT** — this transaction only *allocated* against the pre-existing voucher
  51684, so the header was inserted when the voucher was first CREATED. Capture #3 must record a **brand-new
  voucher creation** (new `cheqsno`) to get the `cheques` INSERT + whatever pre-computes `personnewbal`/
  `banknewbal` (our rollback probe's bare `cheques` insert was rejected precisely because it lacked that).

## 10. Files
| File | Purpose |
|---|---|
| `apps/sync/management/commands/probe_ap_reconciliation.py` | the read-only Phase-A probe (this discovery) |
| `docs/architecture/softech_ap_reconciliation_investigation.txt` | raw probe output |
| `apps/sync/management/commands/probe_ap_writeback.py` | Phase-G write-path probe (read-only + gated rehearsal) |
| `docs/architecture/softech_ap_writeback_investigation.txt` | raw write-path discovery output |
| `apps/finance/recon_models.py` + `migrations/0005_*` | Phase-C canonical mirror models |
| `apps/finance/admin.py` (recon section) | admin inspection of the mirror |
| `apps/finance/recon_ingest.py` | pure SOFTECH-free transform/upsert core (C2) |
| `apps/finance/queries/sybase_reconciliation.py` | 3 read-only SOFTECH feeds (C2) |
| `apps/finance/management/commands/sync_ap_reconciliation.py` | bounded read-only ingest command (C2) |
| `apps/finance/recon_engine.py` | matching engine — scoring/blocking/resolution/anomalies (C3) |
| `apps/finance/management/commands/run_ap_matching.py` | run the engine → proposals (C3) |
| `apps/finance/recon_serializers.py` + `recon_views.py` | read-only API (C4) |
| `apps/finance/urls.py` (`reconciliation/` block) | API routes (C4) |
| `apps/tests/test_reconciliation.py` | C1 model tests (17) |
| `apps/tests/test_reconciliation_ingest.py` | C2 ingest tests (12) |
| `apps/tests/test_reconciliation_engine.py` | C3 engine tests (13) |
| `apps/tests/test_reconciliation_api.py` | C4 API tests (12) |
| `apps/finance/recon_actions.py` | approval actions — approve/reject/manual/undo (E) |
| `apps/tests/test_reconciliation_actions.py` | Phase-E action tests (14) |
| `apps/finance/recon_balances.py` | balance snapshot + حصر equation + ledger timeline (F) |
| `apps/finance/management/commands/snapshot_ap_balances.py` | read-only balance snapshot command (F) |
| `apps/tests/test_reconciliation_balances.py` | Phase-F tests (6) |
| `apps/finance/recon_anomalies.py` + `management/commands/scan_ap_anomalies.py` | Phase-H anomaly scan |
| `apps/finance/management/commands/backfill_ap_reconciliation.py` | chunked historical backfill |
| `apps/sync/management/commands/capture_save_sql.py` (extended) | native Save-SQL capture (`--source`/`--pipe-messages`/`--out`) |
| `apps/finance/recon_writer.py` + `management/commands/push_ap_allocation.py` | **Phase-G gated allocation writer** |
| `apps/tests/test_reconciliation_anomalies.py` (8) · `test_reconciliation_writer.py` (11) | H + G tests |
| **this file** | the spec |

## 11. Phase-G writer — BUILT (gated OFF, 2026-09-20)
The full native سداد was captured + validated, but the key realisation is that **reconstruction never
creates a `cheques` voucher** — the 49k unallocated payments are *existing* vouchers (balances already moved
when they were made), and `temp_r_mon` (the proprietary, uncomputable replication checksum) is only written
on voucher *creation*. So `apps/finance/recon_writer.py` records only the MISSING pieces of an
**approved** allocation, all plain DML:
1. `INSERT INTO chequestrans (…)` — the allocation link (no trigger ⇒ reversible; also the **idempotency
   key**), using the existing voucher's `cheqsno`/branch;
2. `UPDATE stktransm SET docvaluepay += amount, docvaluepaybc, fatcurrentstatus=('90' full | '15' partial)`.

**Correct-by-construction (there is NO rollback net — a cheques insert could not be rolled back, verified):**
chequestrans is inserted FIRST so a retry that finds it skips entirely (docvaluepay can never double-count);
every write is verify-read-back; the invoice is re-validated live (over-pay guard) before writing. Gated by
`AP_RECONCILE_WRITER_ENABLED` (default **False** → dry-run plan only); `patientdata` side-update gated
separately OFF (unclear supplier→patient `labno` keying). `push_ap_allocation --allocation <id>` is dry-run
unless `--commit` **and** the flag. 11 writer tests; full recon suite **95 green**; real dry-run verified.
**Before flipping the flag:** owner-approved pilot on a few tiny real allocations (documented manual reverse
= delete chequestrans + subtract docvaluepay), confirm HQ→branch replication of the allocation without
`temp_r_mon`, and wire a "write to SOFTECH" action in `/reconciliation`.

## 12. Live UI test + shadow-mode precision (2026-09-21)
- **Estate-wide matching (all 307 suppliers, 141 with candidates):** 77,857 candidates →
  **5,373 very-high-confidence (100%) matches worth 6,301,132.75 EGP** + 23,356 medium + 30,522 conflict,
  out of **49,294 unallocated payments**. UI driven live at `/reconciliation` (KPI tiles, status/confidence
  filters, candidate → invoice/payment + ✓ evidence chips, approve, gated write-to-SOFTECH dry-run notice).
  *Note:* `run_ap_matching` wraps all parties in ONE `@transaction.atomic` (giant txn — commits only at end,
  locks block concurrent UI writes); estate runs should commit per-party.
- **Shadow-mode precision (`shadow_validate_ap` — Phase D):** blind-reconstructed each of SOFTECH's **36,055
  ground-truth allocations**; the engine's HIGH pick vs the true invoice = **8,281 correct / 185 wrong of
  8,466 predictions → PRECISION 97.81%** (recall@high 22.97%; 25,477 no-candidate = a recall limit, not
  error). **FP inspection: several "errors" are the engine reading the invoice# from the note while SOFTECH
  allocated to a DIFFERENT same-amount invoice** (e.g. two 100.00 vouchers `ف 11552`/`ف 11548` whose SOFTECH
  allocations are *swapped*) — so true precision is likely higher, and shadow mode doubles as a
  **SOFTECH-mis-allocation detector**. ⇒ the 5,373 estate high-confidence reconstructions are ~97.8%+
  trustworthy (≈5,256+ correct). This calibrates a safe auto-approve threshold from evidence (§19).

## 13. Estate operationalisation (2026-09-25)
Three follow-ups turned the estate run into daily-usable, re-runnable machinery:
- **Bulk approve (`bulk_approve` + `/candidates/bulk-approve/` + «اعتماد كل الثقة العالية»):**
  approves *every* PROPOSED candidate of a confidence class (default HIGH) in scope in one
  action, creating the mirror `Allocation` rows — **no SOFTECH write**. Bounded per call
  (`limit`, default 2000, highest-confidence first, RBAC admin/pharmacist); the response's
  `remaining` lets the UI loop until drained. Each candidate still goes through
  `approve_candidate` (per-row capacity/party guards + audit event), so a candidate that no
  longer fits is *skipped*, not fatal — the run stays idempotent and re-runnable.
- **Mis-allocation anomaly (`ReconException.TYPE_MISALLOCATION` + `_misallocations`):** promotes
  the shadow-mode FP pattern into a first-class detector. Flags any SOFTECH allocation whose
  payment note names a *different* same-party invoice A (and not the settled invoice B) whose value
  the payment matches exactly — the swapped-pair signature. Severity **warning** when B's value
  differs (money on the wrong invoice), **info** when equal (reference swap only — the motivating
  150/55481–55482 `ف 11548`/`ف 11552` pair were both 100.00). Read-only, never auto-repairs the
  SOFTECH link. Wired into `scan()` (`misallocation` count). First live run: **58 flagged across
  9 suppliers — 32 warning (77,903.56 EGP) + 26 info.**
- **Per-supplier commit in `run_matching`:** dropped the single giant `@transaction.atomic`; each
  party now matches inside its own `with transaction.atomic()` (try/except → `n_err`, run status
  `partial` on any party error). Estate runs no longer hold one estate-wide lock that blocks
  concurrent UI approvals, and a mid-run failure keeps every already-committed party's candidates.

## 14. Maximum سداد — writer live + max-allocation pass (2026-09-26)
**Writer (Phase G) is LIVE** (`AP_RECONCILE_WRITER_ENABLED=True`), after a verified 3-allocation pilot
(br130/150/170): only `stktransm.docvaluepay/docvaluepaybc/fatcurrentstatus` moved and one `chequestrans`
row landed per allocation; `cheques` and `personsdata` untouched. Native HQ سداد does **not** update the
branch-node copies either (months-old HQ settlements still show `docvaluepay=0` on the branch nodes) ⇒ HQ
is SOFTECH's system of record for A/P settlement; our behaviour is identical.
- **Bug fixed before any write:** `chequestrans.docvaluepaid` is the invoice's CUMULATIVE paid after the
  voucher (verified 100/63418: 1874.21 → 26990.21 → 43703.68), not the voucher amount.
- **Live guards:** invoice over-pay, voucher over-allocation (Σ docvaluepaynow ≤ cheqvalue), foreign
  currency refused, header verify-readback; `ReconWriteIntegrityError` (half-landed write) STOPS a batch.
  Every live attempt is audited (`allocation_written / _skipped / _write_failed`). Mirror header synced.
- **Reversal:** `reverse_allocation` deletes OUR chequestrans row + lowers docvaluepay, only for rows with
  our `allocation_written` audit; candidate → rejected. UI «↩ عكس من SOFTECH».
- **Bulk:** `push_ap_allocations_bulk --commit [--shard i/N]` (one connection, reconnect/wait on HQ
  outage, shards disjoint by supplier ⇒ safe in parallel); UI «🖊 كتابة كل المعتمد في SOFTECH».
- **Tests can never reach live SOFTECH:** settings force the flag off under `manage.py test`.

**Reference signal `cheqno`:** the voucher's inner مسلسل equals the allocated invoice in SOFTECH truth
8,801× vs another invoice 443× (95.2% alone). Added (with Arabic-Indic digit folding) → pairwise HIGH
precision 97.85% (TP 8,281→8,901). It unlocked the empty-note vouchers created straight from a purchase
invoice (cheqno = invoice no, same amount/day/branch) — +14,860 high pairs.

**Max-allocation pass** (`recon_allocator.py`, runs per supplier after pairwise; capacity = SOFTECH-open
minus approved minus this run's high/medium reservations). Back-tested on 6,008 SOFTECH vouchers by
replaying history (`backtest_ap_allocator`):

| strategy | rule | precision | tier |
|---|---|---|---|
| multi_ref | voucher names ≥2 invoices = their sum | 100% (n small) | high 95 |
| exact_unique | amount = exactly one open invoice, no rival voucher | **99.51%** | high 92 |
| subset_window | unique consecutive-invoice run = voucher | **99.12%** | high 90 |
| subset_oldest | oldest open invoices = voucher («بالأقدم») | **96.74%** | high 88 |
| installments | consecutive vouchers = one invoice | 84.62% | medium 70 |
| fifo_residual | leftover money oldest-first, partial | 5.6% exact / 36% by amount | low 40 (review) |

**Estate result (run 9, 307 suppliers, 0 errors):** HIGH ≈17.7k pairs (pairwise 14,863 / 17.66M,
subset_window 1,619, exact_unique 928, multi_ref 290, subset_oldest 32) → all bulk-approved (17,728);
MEDIUM 14.7k (installments 706); LOW 25.8k incl. fifo_residual 12,200 (4.10M) for review.
**Finance view** («غير المسددة (للمالية)» + `/reconciliation/unpaid/` + Excel): SOFTECH-open 55.60M over
46,646 invoices → covered by matches 21.29M · under review 17.32M · **no voucher at all 16.99M (4,459
invoices)** — for suppliers without vouchers this ties to the SOFTECH balance (RAMCO 2,454,099 vs 2,452,977).
Review export: `/reconciliation/review/export/` (medium+low, grouped by voucher).

## 15. Auto-write policy + incomplete payments (owner decision 2026-09-26)
Owner: *"auto write all matched unless there is a huge discrepancy that needs revision … as long as revert
is available everything can be fixed."* ⇒ `recon_actions.auto_approve()` approves EVERY proposal (high →
medium → low; specific strategies before `fifo_residual`, so capacity goes to the strongest evidence) except
those `hold_reason()` flags. Held ones stay `proposed` with `decision_note = 'يحتاج مراجعة: <reason>'`
(UI filter «⚠ يحتاج مراجعة», API `?held=1`). Hold rules (deterministic):
- `conflict` class — two+ equally plausible invoices;
- voucher carries an open duplicate-payment / misallocation exception;
- voucher > 7 days BEFORE the invoice, or > 365 days after it;
- amount ≥ 50× smaller than the invoice (outside FIFO) — e.g. 31.26 vs 31,262.40 (×1000 entry error);
- pairwise LOW (neither invoice number nor amount matches);
- pairwise voucher LARGER than the invoice with only a reference (historical precision 23–34%).
Shadow precision by evidence pattern (top pick, ≥ medium): exact+note 97.82% · exact+cheqno 98.26% ·
exact/no-ref 91.57% · **partial+note 90.24%** · partial+cheqno 84.32% · over+ref 23–34%.
Rounds: `run_ap_matching` → `scan_ap_anomalies` → `auto_approve` → `push_ap_allocations_bulk --confidence
all --commit --shard i/3` repeated until nothing new is approved. Every written row is reversible
(«↩ عكس من SOFTECH»).

**Incomplete payments** (`recon_reports.partial_payments`, `/reconciliation/partial/` + Excel, UI filter
«مسددة جزئياً / سندات لم تُستكمل»): invoices with some voucher money applied (SOFTECH, written, or approved
awaiting write) but a balance left — listing every voucher that paid them — plus vouchers whose money is only
partly allocated. First snapshot: 816 part-paid invoices (1.44M paid / 1.02M left, 83 paid by ≥2 vouchers);
911 part-used vouchers (524K unallocated).

**Who / where / when on every row (2026-09-26):** `recon_labels.py` resolves SOFTECH branch code → Branch name and usercode → SOFTECH username (ERPUser.username = usercode, ERPUser.user_id = login name; 116/118 codes resolve). Candidate rows, exceptions, the ledger drawer, the unpaid and partial tables and all three Excel exports now carry supplier code + name, invoice/voucher date, branch code + name and the creating user (code + name); candidates also show who approved them. Finance reports treat remainders < 1 EGP as SOFTECH rounding, not debt. The 2,345 over-payment exceptions are all SOFTECH-native (none involve our allocations).

## 16. Correctness fixes + measured improvements (2026-09-26, late)
- **Receipt vouchers (cheqtype 10 = مقبوضات):** money received FROM the supplier (refunds, return settlement, «دخول خطأ» reversals). SOFTECH links them to RETURNS (47 of 51). The sync marks every supplier voucher `direction=out`, so ~206 type-10 vouchers had been matched to PURCHASE invoices (≈99K written, 103 queued). Fixed at four layers (engine `is_receipt_voucher`, allocator, `hold_reason`, writer push guard — kept out of `build_plan` so reversal still works); written ones reversed after round-2 writes.
- **Branch-aware precision (shadow):** exact amount + reference 98–100% at any branch; partial + reference 92–93% same-branch but 79% cross-branch and 37% for HQ-voucher cheqno ⇒ hold partial matches whose voucher branch ≠ invoice branch. SOFTECH's referenced links are 98.5% same-branch; invoice numbers repeat per branch, which explains most 'voucher before invoice' / '> 365 days' holds.
- **Ambiguous same amount (conflicts):** oldest invoice = 12.16% (wrong), nearest-in-date = **95.45%** on 352 real cases ⇒ `same_amount_nearest` (medium 80, mig 0009); exact date ties stay with a human.
- **Queue hygiene:** proposals < 1 EGP are dropped (rounding), held matches whose invoice/voucher got fully settled elsewhere are retired.

## 17. مدفوعات / مقبوضات correction chains + returns logic (2026-09-26, owner-confirmed)
**Owner-confirmed reading:** a same-amount مقبوضات (cheqtype 10) to the same supplier shortly after a مدفوعات (cheqtype 20) CANCELS that payment; a following same-amount مدفوعات (same or another supplier) is the corrected one. Evidence: 293 receipts follow their payment the same day, 217 within 3 serials.
- `recon_chains.detect_chains` (runs first in every `run_matching`): roles on `Payment.chain_role` — reversed / reversal / reissue / refund (mig 0010). Live: 347 reversals, re-issued 118 same supplier + 74 other supplier, 173 genuine refunds. Cancelled payment + reversal are excluded from engine, allocator, policy and writer. SOFTECH-native links on a cancelled payment → `cancelled_reversed` revision item; re-issues to another supplier → `supplier_mismatch` (info).
- **Correction of our writes (owner-approved):** every written allocation on a cancelled payment / its reversal / a receipt settling a purchase is reversed (`fix_cancelled.py`, after the in-flight writers finish).
- **Returns:** a return (doccode 120) is a CREDIT. SOFTECH nets it inside a مدفوعات (voucher = Σ purchases − Σ returns, positive docvaluepaynow on the return row; 716 native vouchers) or refunds it with a مقبوضات (36). ⇒ voucher capacity is SIGNED everywhere (`Payment.allocation_effect`, writer guard SQL). `ReturnLink` (mig 0011, `sync_ap_return_links`) mirrors stktrans r_docnumber (≈1 in 4–5 return lines; 1,670 links, 1,656 resolved).
- `recon_returns.analyse` (in `scan()`): **paid_returned** only when the linked return's credit is still OPEN (netted returns are correct) — 94 paid-after-return + 34 returned-after-payment; **open_return** — 641 returns / 1,308,600.99 EGP the suppliers still owe. A purchase with an open linked return is payable only for what was kept (allocator capacity) and any match on it is held.
- **Netting strategy** `net_returns` (mig 0013): 90% when it fires on real netting vouchers, 79% in realistic order (19/24), recall 10% ⇒ always held for review.
- **Stub invoices:** 2,368 out-of-range invoices referenced by native links had doc_value 0 → `backfill_ap_invoice_stubs` filled all; 2,343 of 2,345 over-payment flags were false and auto-closed (2 genuine remain).
- **Auto-approve paused** (`AP_RECONCILE_AUTO_APPROVE=False`) until owner resumes; queued approvals re-checked against the new rules → 401 (249,773 EGP) pulled back to revision; 5,667 (3.28M) still eligible. Already-written rows the new rules would have held are tagged «مكتوبة — تحتاج مراجعة» (not reversed). Reports: unpaid deducts open returned parts, supplier summary adds open returns + net payable; `/reconciliation/returns-chains/export/` (open returns · paid-although-returned · full chains with supplier/branch/date/user).

## 18. Shared filters + UI review (2026-09-27)
- `recon_filters.py` — one definition used by every list, the dashboard, all reports/exports AND bulk approve/reject/write: multi-select suppliers (`personcodes` CSV; legacy `personcode` kept), **separate** invoice-date (`inv_date_from/to` → docdate) and payment-date (`pay_date_from/to` → voucher date) ranges (owner: they must be differentiated — a match/exception must satisfy both when both are set; an invoice-date filter never narrows the voucher list), and a document-value range (invoice value / voucher amount / proposed amount). `_scope` re-implemented on top of it; `/reconciliation/supplier-options/` feeds the searchable multi-select.
- UI: filter bar above the tabs (supplier chips, green invoice-date range, blue voucher-date range, value range, clear-all); paging on candidates / exceptions / suppliers (lists previously showed only the first 50 rows); exception type + severity filters; supplier search + sort; every date label says which date it is (تاريخ الفاتورة / تاريخ السند).
- Auto-approval resumes automatically (`resume_rounds.sh`) only after round-2 writes → cancellation reversal → retry pass have finished, so no two writers ever overlap.

## 19. Incident 2026-09-27 — HQ lock chain + orphaned reversal statements
- SOFTECH replication agent **SSB-SBRep150 (spid 24)** sat idle in an open transaction; its UPDATEs (spid 65) and the SBRep140/150/160/170 queue were blocked 40+ min. Our reversal DELETEs queued behind it; each client-side timeout left the DELETE **queued on HQ**, where it would have run later with nobody to lower the invoice header (half-reversal).
- Handled: pipeline stopped; our own 8 queued sessions (re-verified host Bassem_HPZ, lock-sleep DELETE/SELECT) killed with owner approval; Windows did not propagate TaskStop to bash/python children — processes had to be stopped by PID. Dirty-read sweep (AT ISOLATION 0): all 539 pending rows intact, **0 half-landed**.
- Fix: every writer/reversal connection sets `set lock wait 30` (server cancels a blocked statement cleanly instead of leaving an orphan). Pipeline now waits for HQ's blocking chain to clear (max time_blocked < 60 s) before writing. spid 24 left for SOFTECH/IT (not ours).

**Notes, serials and item lines (2026-09-27):** `APInvoice.comments` (stktransm.comments, mig 0014; ingest + `backfill_ap_invoice_comments` filled 3,248) shown on every tab and in every export; vouchers show المسلسل (cheqsno), المسلسل الداخلي (cheqno), رقم الإيصال (ourcheqsno) and ملاحظات السند everywhere. Item lines are **on demand only** (`/reconciliation/invoices/<id>/lines/`, `recon_lines.py`): live SOFTECH stktrans read AT ISOLATION 0, cached 10 min, names from catalog Item, FOC lines (pharmacydiscp=100) flagged; UI button «📦 أصناف الفاتورة» on candidates, exceptions, unpaid and partial lists.

- 03:0x — owner instructed cancelling spid 24 (SSB-SBRep150, idle open tran 60+ min); re-verified and killed. A branch-170 agent (spid 63) briefly became head, then released on its own; replication resumed with normal short holds. Gated pipeline cleared at 03:07 and started the reversal.

- 03:2x — one reversal (allocation 74553, 153.00) half-landed: its DELETE auto-committed, then the header UPDATE hit the 30 s lock limit (replication agents take EXCLUSIVE TABLE locks on chequestrans for minutes while syncing). Repaired with `complete_half_reversal` (acts only when SOFTECH proves it: our row gone, we wrote it, header − links == amount) → header 2,468.98 → 2,315.98. **Writer and reversal are now ATOMIC** (`_atomic`: one transaction; a failed rollback is re-read and proven, else integrity stop). Reversal script retries lock timeouts patiently (5×20 s per row, 10 passes).

- 2026-09-27/28 — correction finished: all 713 cancelled/receipt allocations reversed (0 left). The retry pass then hit two integrity stops (80415, 75981): **half-landed WRITES** from the pre-atomic 2026-09-26 read-timeouts — the server ran the chequestrans INSERT, the client never saw it, so the header was never raised (in 75981 a later write of ours even set the header from the stale live value). Sweep of all approved allocations with a failed attempt: **22 half-landed (21 invoices)**, all completed with `complete_half_write` (acts only when: allocation still approved, our failed attempt is audited, our row present with exactly this amount, and Σ links − header == amount — or Σ of all such siblings on the same invoice, e.g. 76887+76844 = 729). Audited as `allocation_written` (steps `half_write_completed`) so they stay reversible; re-sweep: 0 left. The pipeline now runs this proof-gated repair once on an integrity stop and halts if it recurs.

- 2026-09-28 — rounds CONVERGED (auto-approve 2,258 → 182 → 16 → 1 → 0). Two stops in round 1 were HQ drops mid-transaction (proven clean afterwards); `_atomic` now proves a rollback on a FRESH connection when the original died (`rollback_verified_fresh_connection`), else still an integrity stop. Owner authorised killing blocking sessions: `lock_watchdog.py` killed SSB-SBRep170 11× (it repeatedly idles in an open transaction, blocking our writers and the 140/150/160 agents) — rule: head blocker, AWAITING COMMAND with open tran on two samples 30 s apart, blocking our host or a replication agent; never active sessions, never ours. **Final: 42,656 allocations written (33.73M EGP)**; 713 reversed; 20 approved refused by live guards (invoice/voucher already settled natively); 16,051 held for review (6,838 ambiguous same-score, 1,701 weak signal, 1,277 voucher>invoice…); 1,008 written rows tagged for review. Finance: 12,524 invoices open 22.28M → 3.44M under review, 0.56M matched pending, **18.28M (4,610 invoices) with no voucher at all**.

## 20. 2026-09-28 — review grid, human decisions, «مبلغ مستحق» semantics, timestamps

- **Mass approve bypassed the holds**: «اعتماد كل الثقة العالية» (bulk_approve) ignored hold_reason → owner's click approved 666 held matches (500 voucher>invoice, 128 flagged). None written; all returned to review. bulk_approve now skips `يحتاج مراجعة` rows unless a reviewed group (group_key) is approved.
- **Human decisions survive re-matching**: run_matching deletes/recreates every proposed candidate nightly → a REJECTED pair is now never re-proposed (engine + allocator skip_pairs) and a manual «إرسال للمراجعة» hold (`MANUAL_HOLD_PREFIX`) is carried over and never auto-approved; manual written-review flags (`WRITTEN_MANUAL_PREFIX`) are never cleared by the scan.
- **Grid**: sortable columns (server-side, id + entry-time tie-break), page size ≤500, multi-select with a selection bar (approve / reject / send to review / write selected / reverse selected — SOFTECH actions need a second click); `/candidates/selection-action/` (reject_ids = «approve these, dismiss the rest»).
- **Grouped review** (`recon_groups.py`, `/candidates/groups/?by=invoice|payment&only=multi|over|all`): all vouchers proposed for one invoice together (or all invoices for one voucher), capacity, Σ proposed, «exceeds» warning, existing links, duplicate-voucher twins. Live: 5,817 invoice groups where proposals exceed what is owed (2.55M).
- **chequestrans.docvaluepaid = amount still OWED BEFORE this payment** («مبلغ مستحق»), NOT cumulative paid-after. SOFTECH ticks «مغلق» where paynow == docvaluepaid. Proof: 735 native multi-payment invoices in entry order → 674 due-before vs 45 (old vouchers linked years later); owner's native 140/10746. Writer fixed; `fix_ap_due_before` (dry-run default) repairs OUR rows only, per invoice live, our links chained chronologically after native ones (latest payment closes). Owner case 140/10653 (our 44995): 13,750 → 4,750 «مغلق».
- **Ingest re-labelled our writes 'softech'** (update_or_create forced origin) → 4,332 of our links (3.88M) had lost reversal/review; ingest now keeps 'written', labels restored. Real total written = 46,988 links / 37.62M.
- **Conflict rule bug** (owner case 160/32325: voucher inner serial = invoice no., 100 score, still «تعارض»): `resolve()` counted the top candidate as its own rival, so ANY second same-amount voucher (here a 2023 one scoring 50) made the clear winner a conflict. Fixed to the rule the shadow validation always used (≥2 contenders, each ≥ medium, within conflict_delta). Re-match: conflicts 6,747 → 527 (480 of them sub-1-EGP rounding, 47 real), high 663 → 7,306; 6,335 pass the auto-policy — all exact amount + explicit invoice reference, same branch (4,832 via cheqno, 1,499 via note).
- **Correction run**: `fix_ap_due_before` corrected 5,486 invoices / 13,053 links; «مغلق» now on 3,422. An HQ drop left an ORPHAN session holding invoice 81122's UPDATE uncommitted — a dirty read wrongly looked «done»; fixed by killing our dead session (rolled back) + redo; the repair now decides from COMMITTED reads, and the watchdog also clears our own idle-in-transaction orphans that block others ≥45 s.
- **Auto re-chain after every write round** (`recon_writer.rechain_after_write`): bulk command, screen bulk write and single write re-chain «مبلغ مستحق» oldest-first on the invoices they just wrote (our links only); failures reported, never undo the writes.
- **«المتبقي (محسوب)» ƒ** (`APInvoice.remaining_calc` = value − max(SOFTECH paid, links) − approved-unwritten; ≤1 EGP → «✓ مسددة بالكامل») on grid (+ «بعد هذا المقترح»), panels, groups, exceptions, unpaid (+ export); `net_remaining` = remaining − open credit of returns that reference the purchase («الصافي بعد المرتجع»).

## 21. 2026-09-29 — returns & مقبوضات bound to their documents (owner decisions)

- Survey: 3,890 returns (6.35M), mostly netted natively in مدفوعات (3,011) or refunded; 648 open (1.34M), 265 reference their purchase. 524 مقبوضات: 350 reversals already paired 1:1 with the cancelled مدفوعات (chain), 174 refunds.
- Backtests on SOFTECH truth: netting a voucher with ITS OWN linked return is not native practice (return references the netted purchase 6%) → bind for display/net, no matching strategy. Refund↔single return 95.7% but matches none of today's open refunds.
- `recon_bindings.bind_all` (runs in run_matching; mig finance/0015): (1) refund → the مدفوعات its note/serial names (same branch, ≤60 d, smaller) → `bound_payment`, payment `refunded_amount`, matched NET everywhere (engine `_unallocated`, allocator cap, hold rules, groups, reports); 6 bound (e.g. 130/50400 11,954 − 10,780 = 1,174 = inv 11954; 100/31504 net 10,695.25). (2) receipt → purchase invoice its serial names → `bound_invoice` + exception `receipt_on_invoice` (48) — owner undecided (money back vs credit) → numbers unchanged. (3) `chain_partners` readable on every chain member. Returns ↔ purchase shown + «الصافي بعد المرتجع». Export sheet «ربط المقبوضات».
- **fifo_residual finding**: backtest 5.6% exact, yet the policy auto-wrote 10,337 links (3.22M). Now ALWAYS held; written ones tagged for review (9,808 written rows tagged). 258 FIFO links (57.6K) provably took an invoice from a voucher that names it; 140/41249 (397,080 to General Supplier avg 877; same-day receipt 397.08 names it) spread over 442 invoices (368.6K) — owner decision pending on reversal.
- **Top-up** (2026-09-29): a further amount on a pair WE linked raises our chequestrans row + header (`_top_up`, atomic, audited) instead of a 2nd row; native links never modified (held «مربوط في SOFTECH مباشرة»); undo refuses a link already in SOFTECH. 12 partial links (written while fifo held part of the invoice) topped up.
- **Slight overage**: «السند أكبر من الفاتورة» no longer holds a voucher that names the invoice, same branch, ≤1% (or ≤1 EGP) over — SOFTECH truth 97.8% (≤1 EGP, n=45) / 100% (≤1%) vs 31.8% above 5%. 336 released.
- **Reference lock + rivals**: the old conflict bug had let amount/date strategies take vouchers away from the invoice their serial names → 5,529 written links (1.75M) contradict their reference (e.g. supplier 4471 630-vouchers shifted one invoice back). Engine + allocator now lock a voucher to the open invoice it names; `recon_rivals` shows on each row the other vouchers on the same invoice (⚔) and the invoice the voucher names when different (🔎); 4,755 tagged «الربط يخالف المرجع». Repair estimate: 3,589 would re-land on their named invoice; 1,919 name an invoice already correctly paid by another naming voucher (review only); 21 native. Twin vouchers (26892/21831/29223): no same-amount مقبوضات/return/chain at any supplier → genuine double payments.
- **Exports**: all four buttons were broken — `downloadBlob` was never defined in the page (silent ReferenceError after a good server response); fixed + `runExport` shows errors. sync/0005: SyncRun.progress DB default (stale scheduler inserts failed).
- **Timestamps**: invoice/voucher `trans_time` (SOFTECH entry, Cairo local) shown under every date in the grid, groups, exceptions, unpaid/partial tables, and as «وقت إدخال …» columns in every export.
