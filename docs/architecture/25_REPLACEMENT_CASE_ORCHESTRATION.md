# 25 — Insurance Replacement / Buy-Back Case Orchestration (بدل الروشتة)

**Status:** DISCOVERY + ARCHITECTURE PROPOSAL (2026-09-28). No code, no migrations, no SOFTECH writes yet.
**Scope:** one governed case per replacement/exchange event, orchestrating the native SOFTECH
documents underneath (purchase 10, contract sale 115, supplier payment voucher, POS sales 115,
returns 30/120). Types: **A = insurance prescription replacement**, **B = physical medicine bought
from a client** (buy-back).

---

## 0. The headline finding — SOFTECH already has the entitlement ledger

Reconstructing the acceptance case (محمد صالح سمره, PIC `130HD16564`) from **our own Postgres
mirror** (`apps/finance` A/P reconciliation, doc 23) shows the native mechanism exactly:

| Step | Native document | Evidence (live mirror, 2026-09-28) |
|---|---|---|
| Contract sale | `stktransm` 130/115/**453805** dated 2026-07-05 | in `customers.PurchaseHistory` |
| Entitlement **created** | purchase `stktransm` 130/**10**/**12095** dated 2026-07-21, supplier **4472 «مورد شركات 25 - Contract Supplier 25%»**, **doc_value 5,700.00** | `finance.APInvoice id=81533`; single line **item 100186 LOKELMA 5MG ×1, public 8,027.00, price 5,700.00, discount 28.9897 %** |
| Entitlement **consumed** | supplier payment vouchers (`cheques`, cheqtype 20, bankcode 40, branch 130) **50830 = 2,023.00** (2026-07-25), **50990 = 2,177.00** (2026-08-02), **51297 = 1,500.00** (2026-08-22) | `finance.Payment`; **all three natively allocated to invoice 12095 via `chequestrans`** (origin=softech); Σ = **5,700.00 = invoice value**, invoice `docvaluepay` 5,700 / `fatcurrentstatus` 90 |
| Products given | cash POS sales same branch, **same day as each voucher**: 455365 (1,176.00) + 455366 (541.50) + 455367 (306.00) on 07-25; 456071 (2,172.00) on 08-02; 457751 (1,335.50) on 08-22 | `PurchaseHistory` |

So, natively:

* **Entitlement = an A/P payable to a virtual "contract supplier"**, created by a doccode-10
  purchase whose value is the replacement value.
* **Each redemption = a supplier payment voucher (سداد) paid out of the branch cash box**, allocated
  to that purchase invoice. The cash then funds an ordinary cash sale of replacement products
  (product redemption) or leaves with the patient (cash settlement).
* **Outstanding entitlement = invoice `docvalue − docvaluepay`.** This is already mirrored, already
  reconciled, and already has a matching engine and a live gated allocation writer (doc 23).

**Design consequence:** our module must **not** keep an independent balance that can drift from
SOFTECH. The case ledger is an *enriched, per-patient projection* of the native A/P sub-ledger,
and **"case ledger balance = native invoice outstanding" is reconciliation invariant #1.**

### 0.1 Scale (mirror, 2023-01 → today; 4471 from 2019)

| Virtual supplier | Invoices | Value | Returns (120) | Still open | Unallocated vouchers |
|---|---|---|---|---|---|
| 4469 مورد شركات 50% | 983 | 700,937 | 16 | 152 / 86,093 | 50 |
| 4470 مورد شركات 40% | 7,481 | 4,796,501 | 57 | 1,722 / 680,556 | 1,114 |
| 4471 مورد شركات 30% | 13,143 | 8,227,051 | 57 | 4,189 / 2,078,820 | 2,775 |
| 4472 مورد شركات 25% | 2,174 | 1,336,274 | 47 | 488 / 181,771 | 300 |
| **Total** | **≈23,800** | **≈15.06M EGP** | 177 | **6,551 / ≈3.03M EGP** | 4,239 |

"Open" mixes genuine unused entitlement with vouchers SOFTECH never linked; the existing A/P
matcher (97.8 % measured precision) separates them. Type-B buy-back accounts (from the phantom
detector, [[phantom_substitution_detection]]): **3068 مورد عام, 4069 مورد عام 50%, 5014 مورد عام
مستورد** (to be confirmed, §16).

### 0.2 Facts the acceptance case already disproves (design must not assume them)

1. **The contract sale came FIRST** (07-05); the purchase was entered **16 days later** (07-21).
   Do not hard-code Purchase → Contract Sale ordering.
2. **The applied deduction was 28.99 %, not the supplier's "25 %".** 5,700 is a rounded figure
   (8,027 × 0.71 = 5,699.17). The supplier-name percentage ≠ the rate actually applied. Store
   *rule applied*, *supplier used* and *actual posted price* as three separate facts.
3. **Purchase has no native reference to the sale.** `docnumber2` = `'21072026'` (the date typed as
   the invoice number). The purchase↔sale link must be matched (branch + item + qty + date window)
   or recorded by us going forward.
4. **Use `stktransm.phcode`, never our `PurchaseHistory.customer` FK.** (Corrected 2026-09-28.)
   455365/455366/455367/456071 **do** carry the patient's phcode `130HD16564`: they are **delivery**
   sales (ptclassif 90, account 1500 HomeDlvry). The mirror's `customer` FK wrongly points them to
   «نيفين مجدى», and 453805 to «منال». That is a customer-resolution defect in the mirror and needs
   its own fix. Receipt **457751 is an anonymous cash sale** (phcode blank, 1510), so it is **not
   linkable by PIC**; its only link is branch + same day + amount. Operator policy: replacement
   sales should carry the patient's PIC or a «عميل تبديل» account (these exist, e.g. 140HD30086,
   160HD33215, 220HD5841); anything else is a matching exception.
5. **Differences are normal:** 2,023.00 vs receipts 2,023.50 (−0.50); 2,177.00 vs 2,172.00 (+5.00);
   1,500.00 vs 1,335.50 (**+164.50**). Owner confirmed: **a positive remainder is handed to the
   patient in cash; a small shortfall is absorbed (not collected).** So voucher − receipts > 0 is an
   *implicit cash settlement* (paid 1:1 out of a product-rate entitlement, which is a control
   point, see §8), and < 0 is an absorbed rounding. Both are classified and audited, never silent.
6. **Docnumbers repeat across branches** (456071 and 457751 also exist at branch 140; 12095 exists at
   130/150/160/170). **Every native reference must use the 4-part key (branchcode, doccode,
   docnumber, docdate).**
7. **The contract-sale leg is a sale/return chain, not a single receipt.** The patient's contract
   account is **4479 «D M S 0% بدون تحمل»**. On 07-05: sale **453799 = 14,921.25**, partial return
   **21531 = 3,964.29** (net **10,956.96**), sale **453805 = 10,956.96**, then full return
   **21532 = 10,956.96**. So 453805 was cancelled by its own return, and the standing contract sale
   is 453799 net of 21531. The monthly chronic Rx repeats (446272 on 04-01 and 450341 on 05-21, both
   14,645.8x; 457389 on 08-17, 14,921.25). The 7,545.38 / 11,826 headline figures are still
   unexplained; they will come from the motalba lines. **Design rule:** a case's contract leg is a
   *set* of 115/30 documents, and matching must follow returns and re-issues.

---

## 1. Existing architecture findings

| Area | What exists | Where |
|---|---|---|
| Native A/P sub-ledger mirror | `APInvoice` (4-part key, doc_value/doc_value_pay), `Payment` (cheques voucher), `Allocation` (chequestrans), `ReturnLink`, `MatchCandidate`/`MatchEvidence` (explainable ✓≈⚠✕ scoring), `ReconException`, `ReconAuditEvent`; daily sync 07:30; full history for 307 suppliers | `apps/finance/recon_*.py`, doc 23 |
| Voucher allocation writer (chequestrans + stktransm.docvaluepay) | **LIVE**, gated, idempotent (row-first), verify-readback, integrity stop, reversal | `apps/finance/recon_writer.py` |
| Voucher (cheques header) creation | recipe captured verbatim; accepted only at **branchcode '100' (HQ)**; **IRREVERSIBLE (no rollback — trigger auto-commits)**; not built | doc 23 §§ G, memory |
| Purchase writer (doccode 10) + supplier return (120) | **Live-proven** (real commit 100/10/63668); return validated by rollback probe; `validations.py` = the only business-rule enforcement (SOFTECH enforces none) | `apps/invoices/writer.py`, `validations.py` |
| Contract / cash / delivery sale writer (pending 115 → cashier finalizes) | golden-verified field-for-field for cash, delivery, contract co-pay 25 % and 0 %, employee, permanent + returns; contract co-pay engine from `personsdata`; per-line discount from `custdiscounts`; `companiesitems5` claim row (roshettano, membershipno…) | `apps/pos_orders/writer.py`, doc 14 |
| POS exception flags + Exception Center page | `SoftechSalesOrder.needs_review/review_reason`, `/exceptions` | `apps/pos_orders/reconcile.py`, `ExceptionCenterPage.jsx` |
| Insurance claims (motalba) | contract rates, claim lines, deductions (`InsuranceDeduction`), `MotalbaCache`, `CompaniesItemsCache` (patient/rx/membership) | `apps/insurance` |
| Buy-back account taxonomy | 7 internal accounts identified; phantom detector | `apps/purchasing/phantom.py` |
| Generic approvals | `ApprovalWorkflowDefinition` → steps (role/user/branch-restricted/nominated) → `ApprovalRequest` (GenericFK + context snapshot, SLA) → immutable `ApprovalDecision` | `apps/approvals` |
| Audit | `AuditLog` (user, role, IP, action choices, model/object, old/new JSON) — no correlation id / reason field; plus module-specific `InsuranceAuditEvent`, `ReconAuditEvent` | `apps/audit` |
| RBAC | `RoleModuleAccess(role, module, action)`; actions fixed to view/create/edit/delete/approve/export/assign/finalize (max_length 10); `can_do()`; branch scope via `accessible_branch_ids` | `apps/users` |
| Customer 360 | full profile + compact POS summary | `apps/customers/views.py`, `pos_summary.py` |
| Delivery | `DeliveryOrder.softech_doc_ref` / `softech_doc_number5` link to the sale | `apps/delivery` |
| Notifications | dedup'd notifications + WebSocket + role access | `apps/notifications` |
| Attachments | only module-specific (`CallLogAttachment`, `TaskAttachment`, `SoftechSalesOrder.prescription_image`) — **no generic attachment** | — |
| Transaction links / lineage graph | **none generic** (only `finance.ReturnLink`, `Allocation`) | — |
| Replacement / entitlement concept | **none** (grep: only loyalty "exchange" wording) | — |

## 2. Reuse map

| Concept | Decision | Target |
|---|---|---|
| Native entitlement balance | **REUSE** | `finance.APInvoice`/`Payment`/`Allocation` (no parallel balance) |
| Voucher↔invoice matching (history) | **REUSE** | `finance.recon_engine`, `recon_allocator` |
| Voucher↔invoice write | **REUSE** | `finance.recon_writer.push_allocation` |
| Purchase / supplier-return write | **REUSE** | `invoices.writer` via a `SupplierInvoice` built from the case |
| Contract sale / product sale / POS return | **REUSE** | `pos_orders` (order carries `replacement_case` context) |
| Approvals engine | **REUSE + EXTEND** | `approvals` + a case-side policy router (thresholds, maker-checker, aggregation) |
| Audit | **EXTEND** | `AuditLog`: add nullable `correlation_id`, `reason`, `branch` + action choices |
| RBAC | **EXTEND (no users schema change)** | new modules in `MODULE_CHOICES` mapped to the granular names (§8) |
| Exception Center | **EXTEND** | `/exceptions` gains a «بدل الروشتة» source |
| Customer 360 | **EXTEND** | replacement panel + entitlement badge in full profile and POS drawer |
| Delivery, notifications, customers, items, branches, pricing | **REUSE as-is** | link only |
| Generic document reference + link graph + attachments | **CREATE (shared)** | new `apps/lineage` |
| Case, rules, policies, calculation, case ledger, allocations, exceptions, matcher | **CREATE** | new `apps/replacement` |

## 3. SOFTECH knowledge map

| Workflow | Known (verified) | Still to reverse-engineer |
|---|---|---|
| Purchase 10 from virtual supplier | Full write recipe, serials (`lastdocnumberin_supp`+1), unchained batch, validations, stock effect via trigger, A/P credit via trigger; example 12095 lines | Nothing blocking. Confirm operator convention for docnumber2/comments so we can *stamp the case id* |
| Supplier return 120 | Recipe (patientpayment = original docnumber, newcostprice from original, r_doc*), probe-validated | One real committed test; how returns interact with a *partly paid* virtual invoice |
| Contract sale 115 (contract channel) | Pending writer golden-matched; co-pay; companiesitems5 | Where prescription no. / approval no. / insurer receipt no. (453805 "insurance receipt") live — assumed `companiesitems.roshettano` + motalba; confirm |
| Cash POS sale / return | Golden-matched, points, pre-split, reservation | none for v1 |
| Supplier payment voucher (سداد) at a **branch** | HQ recipe; branch 130 vouchers exist (bankcode 40, usercode 1330/1309) | Voucher created on the **branch server** (replicates up). Is bankcode 40 the branch cashier box? Which user is the cashier? Is there a shift? **Irreversible insert** ⇒ last to automate |
| Cashier shift / drawer | nothing known | Does SOFTECH have shifts / box closing (تقفيل خزينة)? Table + screen |
| Customer receipt / refund to patient without supplier | n/a | whether cash-only settlements ever bypass the virtual supplier |

## 4. Proposed domain model

Two apps. Names are proposals.

### 4.1 `apps/lineage` (shared, reusable by every module)

```
DocumentRef              one row per native/internal document (the graph node)
  system        softech | pos_order | delivery | pg
  branchcode, doccode, docnumber, docdate     ← 4-part key; UNIQUE(system,branchcode,doccode,docnumber,docdate)
  doc_kind      purchase | supplier_return | contract_sale | sale | sale_return | payment_voucher | delivery | transfer
  amount, party_code, party_name, usercode, doc_time, status_snapshot, synced_at
  (nullable FKs to existing mirrors: finance.APInvoice / finance.Payment / pos_orders.SoftechSalesOrder / delivery.DeliveryOrder)

DocumentEdge             doc → doc relationship (FUNDED_BY, PAYS, RETURNS, REVERSES, CORRECTS, RELATED_TO, GENERATED_FROM)
  from_ref, to_ref, relation, amount, origin (native | matched | manual | generated),
  confidence, evidence JSON, confirmed_by, confirmed_at, superseded_by (never deleted)

Attachment               generic evidence file (GenericFK to any object) + optional document_ref
  kind (prescription, approval, insurance_card, whatsapp, payment_proof, signature, other),
  file, uploaded_by, uploaded_at, access_scope (role/permission), sha256
```

### 4.2 `apps/replacement`

```
ReplacementCase          IRC-YYYY-NNNNNN (type A) / BBC-YYYY-NNNNNN (type B)
  source_type    insurance_rx | client_buyback
  branch, customer (FK customers.Customer), softech_pic, patient snapshot (name, mobile, card, membership, national_id)
  contract_personcode (SOFTECH cust_branch_code, e.g. 4478), insurance subclient (FK, nullable), copay_pct snapshot
  prescription_no, approval_no, physician, prescription_date, original_receipt (DocumentRef)
  settlement_mode  products | cash | mixed
  status (§5), version (optimistic lock), created_by, correlation_id (UUID), origin (live | reconstructed)
  money snapshots (all DERIVED, recomputable): public_value, contract_value, entitlement, redeemed_products,
  redeemed_cash, customer_topup, outstanding, unexplained

ReplacementItem          one per prescription line
  item, softech_itemcode, qty_prescribed, qty_dispensed, qty_replaced, disposition
  (dispensed_as_prescribed | selected_for_replacement | partially_replaced)
  public_unit_price, contract_unit_price, insurer_portion, patient_copay   ← kept separate, never collapsed
  physical_disposition (kept_in_pharmacy | returned_to_supplier | …) vs erp_stock_effect (derived)

ReplacementRule          versioned, immutable once used
  rule_key, version, effective_from/until, priority, source_type, settlement_mode,
  conditions JSON (contract, item, category, branch, …), basis (public_price), deduction_pct,
  target_supplier_personcode (4469–4472, 3068…), rounding (e.g. nearest 50 / none)

ContractReplacementPolicy  per contract personcode (versioned)
  products_allowed, cash_allowed, mixed_allowed, requires_approval, allowed/prohibited categories,
  max_pct, required_documents, penalty formula, allowed_branches, return_window_days, month_end_rule

ReplacementCalculation   immutable snapshot per calculation run (a case may have several; one is 'active')
  per-item: eligible_public_value, deduction_pct, deduction, entitlement; rule+version; override (pct, by, reason, approval)

EntitlementLedgerEntry   APPEND-ONLY (§6)
RedemptionAllocation     redemption → one or more cases' ledger credits (§6.3)

PostingOperation         one per intended SOFTECH write (idempotency unit)
  op_id UUID (unique), case, kind (purchase | supplier_return | contract_sale | voucher | allocation),
  idempotency_key (unique), requested_by, approval, target_branch, expected_value, expected_stock_effect JSON,
  status planned → posting → posted_verified | verification_failed | failed → reversed,
  result DocumentRef, readback JSON, error

CaseException            type, severity (info/warning/high/critical), status, owner, evidence JSON, resolution …
MatchCandidate (history) proposed link + explainable evidence (reuses finance scoring style)
```

## 5. Proposed state machine

Instead of 20 flat states, use a **case lifecycle** plus **per-leg operation status** (on
`PostingOperation`) and **derived** fulfilment/reconciliation (from the ledger). This covers
every listed state without boolean flags or state explosion.

```
Case lifecycle (explicit TRANSITIONS map, select_for_update, audited):

 DRAFT ──calculate──▶ CALCULATED ──submit──▶ AWAITING_APPROVAL ──approve──▶ APPROVED
   │                      ▲  │                      │ reject                    │ execute
   └──cancel──▶ CANCELLED │  └── edit (new calc) ◀──┘ (back to CALCULATED)      ▼
                          │                                                 EXECUTING
                          │                        (purchase + contract-sale legs; each leg its own op status)
                          │                                                     │ all required legs posted_verified
                          │                                                     ▼
                          │                                              ENTITLEMENT_ACTIVE ◀──┐
                          │                                                     │ ledger balance = 0
                          │                                                     ▼          return credit
                          │                                                  SETTLED ──────────┘
                          │                                                     │ reconcile() passes
                          │                                                     ▼
                          │                                                 RECONCILED ──close()──▶ CLOSED
                          │
 Post-posting only: any of EXECUTING/ACTIVE/SETTLED/RECONCILED ──reverse──▶ REVERSING ──▶ REVERSED (terminal)
 force_close (permission + reason + unresolved-exception acknowledgement) ──▶ CLOSED
```

* `CANCELLED` is allowed **only before any leg is posted**. After posting, the only path is compensation (`REVERSING`).
* `PARTIALLY_FULFILLED`, `CASH_PENDING` and `RETURN_PENDING` are **derived badges** (from the ledger or open operations), not states.
* `EXCEPTION` is a **flag**: an open blocking exception blocks `RECONCILED`/`CLOSED`, not the whole lifecycle.
* Reconstructed historical cases start at the matching derived state with `origin='reconstructed'`.

## 6. Entitlement ledger

### 6.1 Entries (append-only, signed, Decimal(12,2))

| entry_type | sign | native anchor |
|---|---|---|
| `ENTITLEMENT_CREATED` | + | purchase 10 (virtual supplier) |
| `PRODUCT_REDEMPTION` | − | voucher (PAYS purchase) + FUNDED_BY → POS receipt(s) |
| `CASH_SETTLEMENT` | − | voucher with no product receipt (or its unmatched remainder, once classified) |
| `POS_RETURN_CREDIT` | + | POS return 30 of a funded receipt (only if cash is re-deposited: see §16 Q4) |
| `SUPPLIER_RETURN_REVERSAL` | − | return 120 against the purchase |
| `CORRECTION` | ± | corrected purchase / re-rate, always paired via `reverses` |
| `WRITE_OFF` / `EXPIRY` | − | future, config-gated |

Each entry: id (UUID), case, customer, branch, amount, entry_type, `document_ref`, employee,
approver, created_at, `reverses` (FK self, **UNIQUE** so an entry can't be reversed twice),
note, correlation_id. DB constraints: `CHECK amount <> 0`, sign consistent with type; no
UPDATE/DELETE (model `save()` refuses updates; DB trigger optional).

### 6.2 Balance and invariants

* `case_balance = Σ amount` (never stored as the truth; a cached snapshot is recomputable).
* **I-1:** `case_balance == Σ over the case's purchase invoices (doc_value − doc_value_pay)` from the native mirror.
* **I-2:** Σ `PRODUCT_REDEMPTION` == Σ `RedemptionAllocation` of the linked POS receipts ± classified differences.
* **I-3:** balance ≥ 0 unless an approved `negative_entitlement` exception exists.

### 6.3 Allocation (multi-entitlement, top-ups)

`RedemptionAllocation(redemption_event, case, ledger_entry, amount)`: one POS receipt of 3,000
can draw 1,200 from case A and 1,800 from case B. The default is **oldest eligible credit first**
(deterministic), and the operator may pick explicitly. The receipt's remainder is recorded as
`CUSTOMER_TOPUP` (not a ledger debit): the POS receipt stays 6,250, allocated as 5,700 entitlement
+ 550 top-up. Allocation runs under `select_for_update` on every affected case row, with capacity
checks inside the lock (the pattern already proven in `supply/execution.py` and
`finance/recon_actions.py`).

## 7. Transaction lineage

The graph is built from `DocumentRef` nodes and `DocumentEdge`/`CaseLink` edges. The case view
renders the tree from the prompt, with each node clickable to a document drawer (type, 4-part
number, amount, date, branch, user, status, reversal state, **origin native/matched/manual and
confidence**). The React component `LineageGraph` is generic (props: a root ref) so procurement,
POS and A/P can reuse it.

For case IRC-2026-… (Samra) the graph comes out of reconstruction as:

```
Case ─ Rx (11 items; Lokelma 100186 selected)
  ├─ ContractSale chain (acct 4479): 453799 14,921.25 − return 21531 3,964.29 = 10,956.96
  │    (453805 10,956.96 + full return 21532 = cancelled pair, shown greyed)
  ├─ Purchase 130/10/12095 (07-21) 4472  +5,700.00           [match: item 100186 + branch + qty + 16-day window]
  │    ├─ Voucher 130/50830 2,023.00 (native chequestrans)
  │    │    └─ FUNDED_BY delivery 455365 1,176 + 455366 541.50 + 455367 306 = 2,023.50  (Δ −0.50 absorbed)
  │    ├─ Voucher 130/50990 2,177.00 (native)
  │    │    └─ FUNDED_BY delivery 456071 2,172.00           (Δ +5.00 → implicit cash to patient)
  │    └─ Voucher 130/51297 1,500.00 (native)
  │         └─ FUNDED_BY cash 457751 1,335.50 (anonymous 1510 — medium confidence, needs confirm)
  │                                                           (Δ +164.50 → implicit cash to patient, rule C)
  └─ Balance 0.00  | products 5,530.50 · implicit cash 169.50 · absorbed 0.50
```

## 8. Approval and RBAC architecture

**RBAC.** `RoleModuleAccess.action` is fixed to 8 short verbs, so adding 28 new actions would mean
a users-schema change. Instead, add **five modules** and map every granular name onto a
`module × action` pair in one table (`replacement/permissions.py`), checked server-side by a
`CanReplacement(perm)` DRF permission plus branch scope (`accessible_branch_ids`):

| Module | view | create | edit | approve | finalize | export | delete |
|---|---|---|---|---|---|---|---|
| `replacement` | view | create | edit_draft, calculate, submit | approve, reject | cancel, close | export | — |
| `replacement_post` | view_postings | post_purchase, prepare_contract_sale | manual_link | — | reverse, supplier_return, sales_return | — | — |
| `replacement_cash` | — | request_cash | — | approve_cash | pay_cash | — | — |
| `replacement_ctrl` | view_audit, view_reports | — | resolve_exception | override_percentage, backdate | force_close | export | — |
| `replacement_admin` | view_profitability | configure_rules | configure_contract_policy | — | admin | — | — |

Open question §16: roles only, or per-user grants? Today `can_do` is role-based only.

**Approvals.** Reuse `apps/approvals` (workflow definitions + immutable decisions). Add a
server-side **policy router** in `replacement/approval_policy.py`: configurable rules
(amount band, mode, override Δ %, backdate, penalty, reversal, exception severity, branch,
contract) resolve to a workflow code. It enforces **maker-checker** (configurable:
creator ≠ approver, approver ≠ cashier) and **aggregation against threshold-splitting**
(patient + day, or patient + rolling N days, summed across cases before banding). Approval is
bound to the calculation snapshot's hash: any edit after approval invalidates it.

## 9. Reconciliation engine

`reconcile(case)` is pure and idempotent. It runs on each ledger or link change and nightly after
the A/P sync, and produces per-leg lines with **expected / posted / fulfilled / paid / reversed /
remaining / unexplained**:

1. Rx expected public value vs Σ selected items.
2. Purchase expected (calculation) vs posted (native doc_value); rule and supplier consistency.
3. Contract sale expected vs posted (native docvalue; motalba line where available).
4. Entitlement: ledger credit vs native invoice value (I-1).
5. Product fulfilment: vouchers vs FUNDED_BY receipts (per-voucher Δ, classified).
6. Cash: approved vs voucher paid; cashier identity.
7. Top-up: receipt − allocated entitlement.
8. Returns: POS returns vs ledger credits; supplier returns vs reversals.
9. Overall: `unexplained = Σ unclassified Δ`. Any non-zero unexplained value opens a `CaseException`
   (`payment_mismatch`) that stays open until it is classified (another receipt found,
   rounding within tolerance, change given, adjustment approved). Tolerances are configurable
   (e.g. ≤ 1.00 EGP auto-classified as rounding, **audited**, never silently).

`RECONCILED` requires: all required legs `posted_verified`; I-1..I-3 hold; unexplained = 0 or
every difference classified; no open blocking exception; approvals complete.

## 10. Exception and fraud-control framework

The `CaseException` catalogue follows the prompt §48. Detection runs on every write, from the
nightly scan, and from the reconstruction matcher. Highest-value detectors given the data we
already hold:

* **Orphans:** virtual-supplier purchase with no matched contract sale; voucher with no receipt
  (cash payout or missing link); receipt claimed by two vouchers.
* **Duplicates:** same PIC + same item + contract sale within N days → second purchase; same
  approval_no / roshettano reused; same purchase line cloned.
* **Threshold splitting:** Σ vouchers per patient/day vs approval band.
* **Rate anomalies:** deduction applied ≠ rule (the 28.99 % vs 25 % case), supplier tier ≠ rule, per-employee override rate.
* **Behavioural:** voucher usercode == purchase usercode == sale seller (self-dealing), off-hours vouchers, a patient with more than N cases per month, cancellation or return after consumption.
* **Supplier return without entitlement reversal**, and **POS return without ledger credit**.

Severity, owner, evidence, notes, resolution, resolver and timestamps are recorded on each
exception. Scoring is explainable (weights shown), and AI is suggestion-only.

## 11. SOFTECH write-back strategy

The order below is by risk and readiness. Every write goes through `PostingOperation`
(op_id + idempotency key + lock + post once + readback + verify → `posted_verified`, or
`verification_failed` → CRITICAL exception, never a retry-post).

| # | Leg | Writer (existing) | Readiness | Gate |
|---|---|---|---|---|
| W1 | Link / allocate an existing voucher to the case purchase | `finance.recon_writer` | **LIVE** | `AP_RECONCILE_WRITER_ENABLED` |
| W2 | Purchase 10 on virtual supplier | `invoices.writer` | **live-proven** | `INVOICE_WRITER_ENABLED` + case approval |
| W3 | Contract sale (pending → cashier) | `pos_orders.writer` (contract channel) | **golden-verified** | `POS_WRITER_ENABLED` |
| W4 | Replacement product sale (pending cash → cashier) | `pos_orders.writer` | **golden-verified** | same |
| W5 | Supplier return 120 | `invoices.writer` return path | probe-validated | new sub-gate |
| W6 | POS return | `pos_orders` return path | golden-verified | same |
| ~~W7~~ | ~~Create the payment voucher~~ | **DROPPED (D11)** | the cashier always creates vouchers natively; the module links them (W1) and checks each one for amount, rate, user and timing discrepancies | — |

The case id is stamped where SOFTECH allows free text (purchase `comments`/`docnumber2` convention,
voucher `chequenote`, `stktransm5.comments`/vf2 on POS) so native documents carry a
back-reference. That format must be agreed (§16).

## 12. Frontend / UI architecture

The screen is a single **case workspace** at `/replacement/:id`, not an accounting form:

* **Header strip:** patient, PIC, branch, contract, status chip, entitlement / remaining (big numbers), warning badges.
* **Progress rail:** Prescription → Purchase → Contract sale → Entitlement → Fulfilment → Reconciled (each node shows its leg status and document number).
* **Tabs:** الروشتة (item picker + disposition) · الحساب (public → deduction → entitlement, rule and version shown) · الصرف (products / cash / mixed actions, "open POS with case") · المستندات + **LineageGraph** · الدفتر (ledger) · الاستثناءات · المرفقات · السجل (timeline) · التدقيق and الربحية (permission-gated; the API omits the fields for unauthorized users).
* **List** `/replacement`: universal search box (case, PIC, mobile, card, rx, approval, any docnumber resolved through `DocumentRef`) + buckets (awaiting approval, active balance, unreconciled, exceptions).
* **Dashboard:** a section inside the existing `DashboardPage` (pattern used by supply KPIs).
* **POS:** a case badge + "رصيد بدل متاح" in the customer drawer; at checkout the entitlement is a funding line computed by the server.
* **Customer 360:** a "بدل الروشتة" panel.
* The existing `/exceptions` page gains a new source; the reconstruction review screen reuses the A/P candidates UI pattern.

## 13. Implementation phases

| Phase | Deliverable | SOFTECH writes |
|---|---|---|
| **P0** | `apps/lineage` + `apps/replacement` models; **read-only historical reconstruction** from the finance mirror (4469–4472 + buy-back accounts) + purchase lines + contract-sale matching + voucher→receipt matching; auto-built `reconstructed` cases; Samra acceptance case green; case view + lineage graph + outstanding-entitlement report (≈3.03M split into real vs unlinked) | none |
| P1 | Rules/policy engine, calculation, live case creation → approval (maker-checker, aggregation) → ledger; **guided mode**: the operator still posts natively and the system auto-links and verifies expected docs | none |
| P2 | Customer 360 + POS integration (entitlement funding, top-up, allocation); delivery link | none new (POS writer existing) |
| P3 | W2 purchase from the case (+ W1 allocation) | gated |
| P4 | W3 contract sale from the case | gated |
| P5 | Cash settlement workflow (request → approve → cashier voucher natively → linked + verified); W7 only after discovery | W1 only |
| P6 | Returns/reversals/corrections (W5, W6, re-rate) | gated |
| P7 | Fraud analytics, profitability, dashboards, reports, export | none |

## 14. Migration and rollout strategy

1. Reconstruct **all history** (read-only) → cases with `origin='reconstructed'`. Only
   high-confidence links auto-confirm (the A/P precision bar); medium and low links need review.
2. Pilot branch 130: new cases in **guided mode** (no writes). Compare expected vs native daily.
3. Switch on W2/W3 per branch behind flags. Keep native fallback always available.
4. Cash automation only after the voucher/shift discovery questions (Q3, Q7, Q11 in §16) are answered.
5. Nothing is forced: native entries made outside the module are picked up by the nightly matcher
   and surface as "case-less virtual-supplier purchase" exceptions, which is how adoption is measured.

## 15. Testing strategy

* **Pure unit:** calculation (30/40/40/50, override, copay kept separate, rounding rule), ledger invariants, allocation (oldest-first, explicit, multi-case, top-up), state transitions (illegal ones rejected), approval routing (bands, maker-checker, split aggregation), permission matrix (each granular perm, branch scope, profitability fields absent).
* **Concurrency:** `TransactionTestCase` 2-thread races for double approval, double redemption and double posting (pattern from `test_supply_execution`).
* **Idempotency:** a replayed `PostingOperation` returns the same document; verification failure → exception with no re-post (writers mocked at the connector boundary, as in `test_invoice_writer`/`test_pos_writer`).
* **Reconciliation:** perfect / missing POS / missing voucher / amount mismatch / returns / missing supplier return.
* **Acceptance fixture:** the Samra case, using the exact documents in §0. Expected: entitlement 5,700.00, balance 0.00, 3 native allocations, receipts matched, **unexplained 164.50 + 5.00 − 0.50 surfaced, not hidden**.
* **Writers:** rollback-probe golden diffs (the existing loop) before any flag flip.

## 17. Phase 0 — as built (2026-10-01)

**Scope delivered:** read-only historical reconstruction. No SOFTECH reads or writes at all:
every input is an existing Postgres mirror (`finance` A/P, `procurement.PurchaseLine`,
`customers.PurchaseHistory(+Line)`).

| Piece | Where |
|---|---|
| Shared lineage graph | `apps/lineage` — `DocumentRef` (unique 4-part key), `DocumentEdge` (pays / funded_by / returns / cancels · native / matched / manual · proposed / confirmed / rejected / superseded · `decided_by` never overwritten) |
| Case model | `apps/replacement/models.py` — `ReplacementCase` (one per virtual-supplier purchase, IRC-/BBC- numbers, lifecycle choices for all phases), `ReplacementItem` (replaced vs dispensed), `CaseDocument` (roles incl. `contract_void` pairs and `return_settlement`), `EntitlementLedgerEntry` (append-only: `save()`/`delete()`/queryset `update()`/`delete()` refused, sign rules, `reverses` UNIQUE, idempotent per (case, type, document)), `CaseException`, `ReconstructionRun` |
| Tunables | `config.py` — supplier matrix (§16.1), windows, tolerances, `RULES_VERSION` (every case stamps it) |
| Pure matcher | `matching.py` — `pair_returns` (full same-day return ⇒ void pair; partial ⇒ reduces standing sale), `resolve_contract_sale` (items/qty/public price/timing/channel + voucher-day-receipt patient hint; ambiguity penalty), `select_funding` (patient / «عميل تبديل» receipts ⇒ can auto-confirm; anonymous ⇒ capped below HIGH, always *proposed*), `applied_deduction_pct` |
| Ledger service | `ledger.py` — `ensure` (idempotent), `reverse`, `reclassify_voucher` (compensating entries only) |
| Adapter | `reconstruct.py` — `reconstruct_invoice` (atomic per invoice, case row locked), `run`, guarded `reset_reconstructed` |
| Human decisions | `actions.py` — confirm/reject a proposed receipt link (audited, then re-runs the case), acknowledge/resolve exception (reason required) |
| API / RBAC | `/api/replacement/` (§11 index) · RBAC module `replacement` (view/edit; fallback view = admin/supervisor/purchasing/quality_manager, edit = admin/supervisor) · branch-scoped queryset |
| UI | `/replacement` (KPIs, outstanding split, exception chips, universal search) · `/replacement/:id` (rail, lineage tree with inline confirm/reject, items, ledger, exceptions, reconciliation) |
| Command | `reconstruct_replacement_cases` |
| Tests | `test_replacement.py` (Samra acceptance, ledger immutability, matcher units, API/RBAC/branch scope) + `test_replacement_regressions.py` — 26 green; 412 adjacent finance/supply/permission tests green |

**Acceptance (Samra, live data):** IRC-2026-000001 → PIC 130HD16564, contract 453799 − 21531
(453805/21532 shown as void pair), 11 Rx items (Lokelma replaced, 10 dispensed), entitlement
5,700, deduction 28.99 % vs tier 25 %, vouchers 50830/50990/51297 native, receipts 455365-7 +
456071 auto-confirmed, 457751 (anonymous) *proposed*. Before confirmation: products 4,195 · cash 5
· unclassified 1,500. After confirming 457751: **products 5,530.50 · cash 169.50 · absorbed 0.50 ·
balance 0 · status reconciled**; the change is a reversal + two new entries, nothing edited.

**Real-data findings fixed during the first run:**
1. `procurement.PurchaseLine.doc_date` is one day early on rows synced before the 2026-06-25 date
   fix → lines are matched on docdate or docdate−1 (supplier + per-branch serial keep it unique).
2. Supplier returns are closed by a voucher (patient cash back = مقبوضات, or netting in a payment
   voucher). The settlement is a ledger credit (`return_settled`); only an **open** return leaves a
   case negative, which is money owed back (HIGH exception). Native outstanding =
   doc − Σ purchase allocations − Σ open returns.
3. Several patients share the same chronic Rx → the patient whose PIC appears on voucher-day
   receipts wins (+20, ranked uncapped).
4. Performance: claimed-receipt exclusion scoped to the candidate pool; funding window filtered
   in SQL.
5. (p0-v3) Duplicates are CAPACITY-aware: a sale line can only be bought back up to its sold qty,
   consumed by earlier cases first (purchase_date, id — order-independent). Over-claim after
   earlier buy-backs = `duplicate_purchase` (HIGH); one sale simply holding fewer units than were
   bought back = `qty_exceeds_sale` (WARNING — likely several prescriptions; multi-sale matching is
   a Phase-1 item). Partial item coverage scores proportionally; same-day ties broken by the
   purchase↔sale clock distance.

**Full reconstruction result (Run #5, rules p0-v3, purchases 2025-06-01 → 2026-09-28):**

| Measure | Value |
|---|---|
| Cases | 17,302 (A insurance Rx 10,857 · B1 external 1,099 · B2 client buy-back 5,346) |
| Entitlement created | 13,224,540.36 EGP |
| Redeemed as products / cash / **unclassified** | 1,444,488 / 974,886 / **9,295,234** |
| Outstanding (= SOFTECH native) | 1,427,626.09 — **invariant I-1 holds for 17,302 / 17,302 cases** |
| Contract sale matched | 4471 80.8 % · 4470 67.6 % · 4469 74.8 % · 4472 61.2 % |
| Status | reconciled 1,947 · settled (needs review) 13,360 · balance open 1,995 |
| Top exceptions | anonymous receipt 6,367 (4.54M) · voucher without receipt 5,580 (2.38M) · cross-branch voucher 2,257 · rate deviation 2,422 · ambiguous patient 1,972 · aged balance 1,318 (0.94M) · **true duplicate 497** · qty exceeds sale 985 · negative (open return) 31 |

The dominant gap is **unclassified redemption**: most redemption receipts are anonymous cash
sales (not on the patient's PIC, contrary to D5), and by design an anonymous link is never
auto-confirmed. Closing it needs an owner policy (see session summary), not more matching.

**Known limits (Phase 0):** contract matching needs `PurchaseHistoryLine` (from 2024-08) and
`PurchaseLine` for virtual suppliers (from 2025-05) → default window from 2025-06-01; older
history would need a live SOFTECH line read. The mirror's `PurchaseHistory.customer` FK is
unreliable for these receipts; the case uses `softech_phcode` (separate fix task raised). No
scheduling yet (run after the daily A/P sync once the owner is happy with quality).

## 18. Phase 1 — live data-entry workflow (built 2026-10-02, postings OFF)

**Goal (owner 2026-10-02):** one governed, traceable, lockable workflow for entering the
virtual-supplier purchase, the insurance contract sale and the cash / home-delivery product sales
worth the purchase value, "with certain discount and for certain employees".

**Flow:** `/replacement/new` (type + settlement + patient PIC → pick the Rx from the patient's
recent contract sales or add items) → case workspace «سير العمل»: **Calculate** (server, versioned
rule) → **Submit** (auto-approve within limits, else apps.approvals workflow) → **Approve / Reject**
→ legs: **purchase** (SupplierInvoice → invoices writer), **contract sale** (link the sale already
made, or draft a contract POS order), **product sales** (cash / delivery POS orders funded by the
entitlement, top-up allowed) → **Post** each leg → cashier makes the سداد voucher natively from the
on-screen instruction → nightly reconstruction links + verifies it.

| Control | Implementation |
|---|---|
| Deduction rules | `ReplacementRule` versioned (rule_key+version, effective dates, contract/branch scope, priority, rounding DOWN). Seeded (`seed_replacement`): A 30 % → 4471, A shortage 25 % → 4472, A cash 40 % → 4470, B1 products 40 % → 4470, B1 cash 50 % → 4469. **B2 (3068/4069) seeded INACTIVE — rates not confirmed.** New version = new row; old calculations keep theirs. |
| Calculation | `rules.compute` — per unit: unit_net = ⌊public × (1 − %)⌋₃dp, line = unit × qty; rounding absorbed by the largest line → the snapshot equals exactly what the purchase posts. `ReplacementCalculation` immutable, fingerprinted. |
| Discount per employee | Lowering the rule's % (patient-favourable) needs a reason and is capped: per-employee `ReplacementGrant.max_override_pp`, else role default (admin 100 pp, supervisor 5 pp, others 0). Raising it is always allowed. Any lowering forces approval. |
| Who may do what | `authz.py`: role matrix module `replacement` (view/create/edit/approve/finalize=post; seed updated: pharmacist view+create, supervisor all) + optional per-employee `ReplacementGrant` (can_create/can_approve/can_post, allowed source types & settlement modes, max case value, approval limit). Branch scope on every action. Grants editable by admin only (`/api/replacement/grants/`). |
| Approval | `approval_route`: cash/mixed → supervisor; rate lowered → supervisor; patient's rolling 7-day total > 2,000 → supervisor, > 6,000 → supervisor + manager (anti-splitting). Runs on the EXISTING `apps.approvals` (workflows `replacement_supervisor` / `replacement_manager`, branch-restricted step, existing /approvals inbox). |
| Maker-checker | Creator can never approve — refused in the workspace AND, for decisions taken in the generic /approvals inbox, the outcome hook refuses the case + raises `self_approval` (HIGH). Approval bound to the calculation fingerprint (`stale_approval`). |
| Locking | Submit locks the case (no item/calc edits). Unlock only by reject (back to maker) or `reopen` (approver, reason) — and only while NOTHING is posted; after posting, corrections are compensating documents. Cancel likewise (withdraws the pending approval). |
| Concurrency | Every mutation: `select_for_update` on the case + client `version` check → HTTP 409 on a stale screen. |
| Idempotency | `PostingOperation` unique key per leg (`<case>:purchase`, `:contract`, `:product:n`). Purchase `docnumber2` = token `9`+case id (internal purchase field only, D14) → the invoices writer's own SOFTECH dup-guard; POS orders keep client_token + vf2 recovery. A retried post returns the same op and never re-writes. |
| Post-write verification | Purchase: finalized + docnumber + Σ lines = approved entitlement (±0.05) + supplier = rule + readback ok → `posted_verified`, ledger credit, case `entitlement_active`. Otherwise `failed` + HIGH `posting_failed`; nothing booked. Nightly reconstruction attaches to the live case (never a duplicate case), keeps operator data, flags `purchase_value_mismatch`. |
| Gates | `REPLACEMENT_POSTING_ENABLED` (default False, forced False under tests) + the writers' own `INVOICE_WRITER_ENABLED` / `POS_WRITER_ENABLED`. With the gate off a post returns the writer's dry-run plan (`dry_run` status). |
| Audit | `AuditLog` actions replacement_case_created/updated/calculated/submitted/approved/rejected/reopened/cancelled, leg_prepared/posted/failed, contract_linked — each with the case correlation id. |
| Tests | `test_replacement_workflow.py` (27) — rules/versions/rounding/override caps, authz & grants, auto-approval, supervisor/manager routing, maker-checker (both paths), rejection, anti-splitting, stale version, reopen/cancel, legs, dry-run, mocked live post + idempotent retry, failed verification, top-up cap, contract draft, nightly attach, API end-to-end, admin-only grants. 60 replacement tests green. |

**Owner decisions 2026-10-03:**
- A/P auto-links on the six replacement accounts stay ON (1a = no). Note: cross-branch written links
  grew 7,812 → 7,822 between 10-02 and 10-03.
- Read-only review list produced (`manage.py export_link_review` → `exports/`, git-ignored):
  sheet «بين فروع» 7,822 links / 2,191,962.10 and «نفس الفرع - ثقة منخفضة» 2,579 / 646,900.61, with
  same-branch suggestions only when within ±1 EGP / 1 % (cross-branch: voucher found 4,053, invoice
  4,775, both 2,954). Removal from SOFTECH deferred (1c = later).
- Approval limits: auto ≤ 500, manager workflow above 500 (`config.APPROVAL_AUTO_MAX/MANAGER_ABOVE`).
- B2 (non-insurance) rates: products 40 % → 3068, cash 50 % → 4069 (migration 0005 adds active v2 rules;
  v1 placeholders kept inactive). **Supplier mapping 3068/4069 assumed — to confirm.**

**Still open before switching postings on:** owner confirmation of approval thresholds (§16.2) and B2
rates; one supervised pilot case per leg on a branch (rollback-probe already proven for both writers);
the A/P virtual-supplier misallocation decisions (session 2026-10-02).

## 16. Owner decisions (2026-09-28)

| # | Decision |
|---|---|
| D1 | Preferred order is purchase **before** contract sale; the reverse is allowed **within a limited window** → configurable `sale_purchase_window_days`; outside it = exception. |
| D2 | Supplier name % is an **indicator only**; the line discount may differ. The rule engine records rule %, supplier used and the actual posted line discount separately. |
| D3 | Voucher `usercode` = the person who made the voucher (1330 salesperson-type, 1309 cashier-type). The cashier is resolved from the voucher, not from the case creator. |
| D4 | Voucher − receipts > 0 ⇒ remainder handed to the patient in cash; < 0 ⇒ absorbed. |
| D5 | Replacement sales should use the patient's PIC or a «عميل تبديل» account; anything else is an exception. |
| D6 | 453805 was a wrong pick; the real contract leg is the 453799/21531 chain (§0.2-7). |
| D7 | SOFTECH has cashier shifts / box closing; screenshots will come on request (needed before P5). |
| D8 | **5014 مورد عام مستورد is NOT a buy-back account** (exclude). 3068 / 4069 مورد عام = non-insurance clients selling medicines for products or cash. |
| D9 | Mixed cases = **one purchase** at one line discount (SOFTECH purchase allows one discount per line). The cash part is taken out of that entitlement. |
| D10 | Prescription/approval numbers live on the contract-sale claim row but are often empty → **not** a reliable matching key (low weight only). |
| D11 | **Vouchers stay manual (cashier) permanently.** The module links each voucher and checks it for discrepancy / human error / fraud. W7 is dropped. |
| D12 | Permissions per role, with **per-user grants for certain channels** (same idea as `StaffProfile.allowed_pos_channels`). |
| D14 | Case back-reference: **never on the contract-sale receipt or any printed customer/insurer document.** Allowed only on internal fields (purchase `comments`, voucher note), and only as an opaque short token; the mapping lives in our DB. |

### 16.1 Replacement rule matrix (defaults, all configurable and versioned)

| Source | Settlement | Virtual supplier | Default deduction |
|---|---|---|---|
| A — our insurance Rx, item **in shortage / cannot be supplied physically** | products | 4472 مورد شركات 25% | 25 % |
| A — our insurance Rx (standard) | products | 4471 مورد شركات 30% | 30 % |
| A — our insurance Rx | cash | 4470 مورد شركات 40% | 40 % |
| B1 — insurance medicines **not dispensed by us** | products | 4470 مورد شركات 40% | 40 % |
| B1 — insurance medicines not dispensed by us | cash | 4469 مورد شركات 50% | 50 % |
| B2 — non-insurance client selling medicines | products / cash | 3068 مورد عام / 4069 مورد عام 50% | **to confirm** |
| Mixed (any source) | one purchase at the **product** rule | per product row | cash part = see approvals §16.2 C |

Caveat seen in the data: 3068 also carries very large vouchers (max 397,080), so it is probably
used for ordinary general purchases as well. Reconstruction must not assume every 3068 document is
a buy-back case.

### 16.2 Approval thresholds (proposal, awaiting owner values)

Grounded in last-12-month value distributions (purchase `doc_value`): 4471 p50 445 / p90 1,641 /
p99 4,817 / max 15,300; 4470 p50 518 / p90 1,751 / p99 4,055; 4472 p90 2,793 / p99 5,969;
4469 p90 1,554 / p99 4,517.

| Control | What it protects | Proposed default |
|---|---|---|
| A. Entitlement (product) | creating value owed to a patient | ≤ 2,000 auto · 2,000–6,000 supervisor · > 6,000 manager |
| B. Cash settlement (explicit) | cash leaving the drawer | ≤ 500 supervisor-free only if a same-case receipt exists, else supervisor · > 3,000 manager |
| C. Cash remainder paid 1:1 from a product-rate entitlement (the 164.50 pattern) | patient gets cash at the product rate (10–20 pp richer than the cash rule) | ≤ 200 or ≤ 15 % of the voucher auto (audited) · above → supervisor or convert at the cash rule |
| D. Rate deviation (applied vs rule) | margin leakage | patient-favourable ≤ 1 pp or ≤ 50 EGP auto (rounding) · ≤ 5 pp supervisor · above manager; pharmacy-favourable auto |
| E. Backdate | period / claim manipulation | same day auto · ≤ 3 days supervisor · earlier or crossing month-end manager |
| F. Sale ↔ purchase window | orphan / late purchases | purchase ≤ 30 days after sale (and same claim month) auto · beyond → exception + supervisor |
| G. Reversal / supplier return | undoing value | always supervisor · manager if any entitlement already consumed |
| H. Aggregation | splitting to dodge A/B | bands apply to Σ per patient over a rolling 7 days, not per document |
| I. Maker-checker | self-approval | approver ≠ creator always · for cash > B-threshold, voucher user ≠ case creator |
