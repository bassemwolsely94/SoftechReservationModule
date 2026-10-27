# Prompt — Complete the Insurance Replacement module (بدل الروشتة / Buy-back)

> Paste everything below the line into a new Claude Code session at the repo root.

---

You are continuing development of the ElRezeiky Sales & Commerce OS (Django/DRF + React/Vite +
PostgreSQL, sitting above the SOFTECH Pharmacy ERP on Sybase ASE).

## 0. Read first (source of truth, in this order)

1. `CLAUDE.md` (non-negotiable rules and the per-batch execution rules)
2. `docs/architecture/11_ERP_INDEX.md`
3. `docs/architecture/12_PROJECT_CONTEXT_SUMMARY.md`
4. **`docs/architecture/25_REPLACEMENT_CASE_ORCHESTRATION.md`**: the design of THIS module,
   including §0 (native SOFTECH facts), §16 (owner decisions), §17 (Phase 0 as built), §18
   (Phase 1 as built), §19 (parallel native entry as built)
5. `docs/architecture/23_SOFTECH_AP_RECONCILIATION.md` (the A/P/سداد engine that the entitlement ledger
   mirrors), `SOFTECH_SUPPLIER_INVOICE_WRITEBACK.md`, `SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md`,
   `20_POS_3.0_COMMERCE_OS.md`, `28_IN_APP_HELP.md`

**THIS MODULE ALREADY EXISTS. Do not build a new one.** Do not create a second case model,
a second balance/wallet, a second approval engine, or a second audit trail. Extend what is there.

Before suggesting anything:
- Search for existing implementation, APIs, database structures, workflows and screens.
- Never duplicate functionality.
- **Your first reply is findings + a gap analysis + the proposed batch plan. Write no code in it.**

## 1. What the business does (plain terms)

An insurance patient (or a client) has medicines they are entitled to but don't want. We buy that
entitlement at a discount off the **public price**. The patient then takes either **other products**
(the common case, as a walk-in or home-delivery sale) or **cash** (less common), or a **mix** of both.

SOFTECH is used natively, with no special document type:

1. **Purchase** of the un-wanted items from a **virtual supplier** («مورد شركات xx%» / «مورد عام»)
   at public price minus the replacement %. This creates real stock and credits an A/P balance.
   **That A/P balance IS the patient's entitlement.**
2. **Contract sale** of the full prescription on the insurance contract channel, exactly like a
   normal insurance sale. It deducts the stock again, so physically nothing moves.
3. **Product sales** (cash walk-in or home delivery) of whatever the patient takes instead, at the
   normal public price or the current POS price after normal promotions.
4. **سداد voucher** to the virtual supplier, made by the cashier from the branch cash drawer.
   It pays the receipts (products) and any remainder handed to the patient (cash).

Voucher − receipts > 0 means cash given to the patient. < 0 means the pharmacy absorbed it.

### Acceptance example (real, must keep reproducing)

Patient محمد صالح سمره, PIC `130HD16564`, contract DMS 0 % copay, branch Nozha 130.
- Prescription: 11 items, public 11,826 EGP. The real contract leg is sale 453799 (14,921.25)
  minus return 21531. 453805 was cancelled by return 21532 (void pair, don't count it).
- Patient does not take LOKELMA 5 mg (item 100186, public 8,027).
- Purchase 130/10/12095 on supplier 4472 «مورد شركات 25%» = **5,700 EGP entitlement**
  (actual deduction 28.99 %, not 25 %: supplier % is an indicator only).
- Vouchers 50830 = 2,023 · 50990 = 2,177 · 51297 = 1,500.
- Receipts 455365/455366/455367 (2,023.50, delivery, patient PIC) · 456071 (2,172) · 457751
  (1,335.50, anonymous cash sale).
- Expected result: products 5,530.50 · cash 169.50 · absorbed 0.50 · balance 0 · reconciled.
  Already reproduced by Phase 0 (`IRC-2026-014405` after rebuild). Keep it green.

## 2. Calculation rule (deterministic, server-side only)

`replacement value = public price × (1 − rule %)`. "30 % products" means a 10,000 public Rx gives
**7,000** of products. "40 % cash" means **6,000** cash. Copay doesn't matter: the % always
applies to the public price of the replaced items. Per-unit rounding DOWN, as already implemented
in `apps/replacement/rules.py` (`rules.compute`). No minimum-profitability block (owner: no).

An authorized employee may change the % per transaction, within their grant (`ReplacementGrant`),
with a reason. Patient-favourable changes always need approval. % may vary by source type,
settlement mode, contract, item, and employee authorization.

## 3. What already exists (verify each one, then build on it)

| Area | Where |
|---|---|
| Lineage graph | `apps/lineage` (`DocumentRef`, `DocumentEdge`) |
| Case, items, case documents, append-only ledger, exceptions, reconstruction runs | `apps/replacement/models.py` |
| Versioned rules + immutable fingerprinted calculation | `rules.py`, `ReplacementRule`, `ReplacementCalculation`, `seed_replacement` |
| Role matrix + per-employee grants | `authz.py`, `ReplacementGrant`, RBAC module `replacement` |
| Workflow (create/calc/submit/approve/reject/reopen/cancel, maker-checker, 409 on stale version, anti-splitting) | `workflow.py` on `apps.approvals` |
| Legs + idempotent `PostingOperation`, writers gated by `REPLACEMENT_POSTING_ENABLED` (OFF) | `legs.py` → `invoices.writer` (purchase), `pos_orders` (contract + product orders) |
| Parallel native entry (link purchase / product receipts posted natively) | `legs.link_native_purchase`, `link_native_product_sale` |
| Historical reconstruction + daily check 08:40 | `reconstruct.py`, `matching.py`, `ledger.py`, cmd `reconstruct_replacement_cases`, job `replacement_daily_check` |
| UI | `/replacement`, `/replacement/new`, `/replacement/:id` (+ `pages/replacement/WorkflowPanel.jsx`) |
| Tests | `apps/tests/test_replacement*.py` (4 files) |

**Invariant I-1 (never break):** case balance in our ledger == native SOFTECH A/P outstanding for
that purchase. The ledger is a projection of SOFTECH, not a parallel balance.

## 4. Owner decisions to respect (consolidated)

- **Rule matrix (confirmed by owner 2026-10-26):**

  | Source | Products | Cash |
  |---|---|---|
  | Our insurance Rx | 30 % → 4471 | 40 % → 4470 |
  | Our insurance Rx, item in shortage | 25 % → 4472 | — |
  | Insurance medicines not dispensed by us | 40 % → 4470 | 50 % → 4469 |
  | Non-insurance client selling medicines | 40 % → **3068** | 50 % → **4069** |

  The 3068 = products / 4069 = cash mapping is now confirmed, not assumed. 5014 is NOT a buy-back
  account. 3068 also carries normal general purchases, so never assume every 3068 document is a case.
- **Mixed case = ONE purchase** at the product rule. The cash part is taken from that entitlement.
- **Purchase:** the module writes it directly to SOFTECH (via the existing invoices writer).
  **Sales (contract + products):** the module prepares them as POS orders and they go to the
  **cashier screen** for an employee to post (existing indirect POS flow).
- **Case token** only on internal fields (purchase `comments`/`docnumber2`, voucher note).
  **Never** on the contract receipt or any printed patient/insurer document. The patient is
  given **no record** of a balance.
- Balance may stay open and be redeemed later. It never expires. Several prescriptions may feed
  one patient balance and one sale may consume several cases (oldest-first or explicit). The
  patient may take more and pay the difference (top-up).
- Any product category is allowed today. Design for **per-contract prohibited categories**
  (config, off by default).
- One customer = one insurance contract. Identify by SOFTECH PIC and mobile first, plus card no.,
  national ID, membership no. and name. Use **Customer 360**, don't build a new lookup.
- Every branch may do these. Contract and replacement products come from the **same branch**.
  Stock gaps are handled by normal transfers. HQ-creates-branch-fulfils is a future plan only.
- Home delivery goes through the **existing delivery module** unchanged (address, agent, status,
  fees, collection). The case only links the sale.
- Insurance settlement/reconciliation with insurers stays in SOFTECH. Out of scope.
- Profitability is visible **only to advanced authorized users** (field-level, server-enforced):
  `contract proceeds + patient payments − acquisition cost of Rx items − cost of replacement
  products − cash given − delivery/transaction costs = contribution`.
- **Approval matrix (owner 2026-10-26, all values configurable and versioned):**

  | Control | Rule |
  |---|---|
  | Entitlement value | auto ≤ 500 EGP · manager > 500 |
  | Cash to patient | supervisor always · manager > 1,500 |
  | % lowered in the patient's favour | supervisor ≤ 5 points · manager above |
  | Backdate | same day auto · ≤ 3 days supervisor · older or crossing month-end manager |
  | Reversal / supplier return | supervisor · manager if any of the balance was already used |
  | Always | approver ≠ creator · bands apply to the patient's rolling 7-day total (anti-splitting) |

- **Cash vouchers (سداد) stay native, permanently.** The cashier makes the voucher in SOFTECH. The
  module issues the instruction, then links and checks the voucher (amount, cashier/shift user,
  branch, date, approval present). No voucher writer.
- **Change of mind:** the contract sale may be returned within **7 days** of the sale **and**
  before the end of that month (both conditions). After that, products can still be returned and
  re-taken, but the contract sale stands.
- **Redemption sales must be on the patient's PIC or the «عميل تبديل» account.** From now on, the
  module refuses to fund a product sale on any other customer, and an anonymous redemption receipt
  is an exception. For **historical** data, anonymous receipts stay as *proposed* links for human
  review. Never auto-confirm them.

## 5. Remaining scope: propose these as separate batches, in this order

**B0. Switch from matcher-first to entry-first (owner 2026-10-26, top priority).**
Today the module mainly *reconstructs* cases after the fact: the matcher reads native purchases,
sales and vouchers and guesses how they belong together. The owner wants the opposite: **every
case is initiated and entered in the module first**, and the SOFTECH documents follow from it.

| | Matcher-first (today) | Entry-first (target) |
|---|---|---|
| Who creates a case | nightly reconstruction, from a native virtual-supplier purchase | a staff member, at the counter, in `/replacement/new` |
| Patient, items, % | inferred by matching | entered and approved up front (calculation snapshot) |
| Purchase | posted natively, then guessed | created from the case (writer when enabled; until then the native number is linked on the case) |
| Contract sale / product sales | matched by scoring | prepared from the case as POS orders → cashier screen; native ones linked by number |
| Voucher | matched by amount/date | instruction issued by the case, cashier posts natively, module links + checks |
| Role of the matcher | builds cases | **verification and safety net only**: confirm what the case declared, and flag gaps |

Required behaviour:
- New virtual-supplier purchases (4469–4472, and 3068/4069 when flagged as buy-back) without a
  case become a **«شراء بدون حالة» (case-less purchase) exception** with branch, user and value.
  No auto-built case. This is how adoption is measured, per branch and per employee.
- The daily check keeps running, but for live cases it only **verifies and links**: what was
  declared vs what SOFTECH has (purchase value, supplier, contract leg, receipts, voucher).
  Mismatches become exceptions. It never re-decides operator data.
- Reconstructed history (before a cut-over date, configurable per branch) stays as it is and stays
  reviewable. Don't delete or rebuild it.
- The case workspace becomes the single place where staff start and finish a replacement, with
  the minimum clicks: patient (Customer 360) → pick Rx items → settlement mode → calculate →
  submit → legs. Calm UI, no popups for the common path.
- Define the cut-over per branch (flag) with branch 130 as pilot, and show the adoption rate
  (cases entered first ÷ virtual-supplier purchases) on `/replacement`.

Present the exact code changes to `reconstruct.py`, `legs.py`, `workflow.py` and the scheduler job
before changing them. This changes behaviour on live data.

**B1. Pilot readiness for the purchase writer (gate stays OFF until owner says go).**
Re-verify the purchase write against a native golden template (rollback probe, every field diffed;
see memory "POS Writer Golden-Template Verify"). Write the per-branch flag plan and the pilot
runbook (branch 130, one case per leg). Keep parallel native entry working side by side.

**B2. Customer 360 + POS redemption.**
Show the open replacement balance on Customer 360 and at the POS (authorized users only). Let a
walk-in or delivery order be **funded by the entitlement** (multi-case allocation, top-up, partial
use leaving a balance). The order becomes a product leg of the case(s) automatically. Reuse the
POS order, channel and delivery flows. No new checkout.

**B3. Cash settlement workflow.**
Request → approve (supervisor always, manager > 1,500) → instruction to the cashier → **cashier
makes the سداد voucher natively in SOFTECH** under the user of the active shift → the module links
it and checks amount, user, branch, date and that the approval exists. No voucher writer, ever.
Capture the optional payment proof, the employee's acknowledgement, the timestamp and the branch.
Exceptions: voucher without approval, voucher amount ≠ instruction, voucher user = case creator
above the threshold, instruction never executed (ageing).

**B4. Returns, reversals and corrections.** Reversal, never deletion. Implement as compensating
documents:

| Event | Required handling |
|---|---|
| Insurance contract sale cancelled | flag on the case + exception to authorized users |
| Insurer rejects later | nothing reversed ("what's done is done"), only recorded |
| Patient changes mind | return the replacement products; offer the contract-sale return only within **7 days** (configurable) **and before month end** |
| Replacement sale returned | patient can take other products (balance restored). If ALL are returned and they want cash: first a supplier return of the un-needed purchase, then a new purchase at the cash rule |
| Home delivery failed | return the product sale, redo later; entitlement restored |
| Wrong % used | supplier return (authorized employees only) + new purchase at the right % |
| Wrong prescription / processed twice | supplier return reverses the purchase |
| Part already consumed | return the consumed product sale(s) first, then reverse |

Each one: who / what / when / why / before-after, approval per matrix band G, idempotent,
never a double-post.

**B5. Attachments and evidence (cross-cutting).**
A generic attachment model (doc 25 proposed it in `apps/lineage`. First check `callcenter` and
`tasks`, which already have attachment models, and reuse or generalize rather than add a third).
Attach optionally: prescription image, insurance approval, insurance card, WhatsApp conversation,
cash/payment proof, notes, other. The owner wants the same attachment capability **embedded in
every POS transaction, per sales channel**. Design it once and attach it to POS orders too.
No delivery proof needed here.

**B6. Exception Center for managers.**
Reuse `CaseException`. One manager screen with severity, owner, ageing, acknowledge/resolve with
reason. Checks: duplicate Rx/approval numbers (weak key: Rx numbers are often empty), same
entitlement processed twice, unusual %, excessive overrides, replacement without a contract leg,
cash without approval, POS sale cancelled/returned after the balance was consumed, inventory
mismatch, self-approval, retroactive/backdated edits, unusual supplier discount, high frequency per
patient/employee, cross-branch voucher, anonymous redemption receipts, purchase value ≠ approved
calc, contract cancelled after redemption. Many already exist; list which ones before adding any.

**B7. Reports (read-only, exportable, branch labels never bare codes).**
Profitability (gated) by case / patient / contract / insurer / branch / user. Public value,
acquisition value, entitlement, products supplied, cash paid, open balances, unredeemed ageing,
supplier discount vs rule %, pending/incomplete, reversals, overrides, suspicious activity. Every
row must drill down to the full lineage: every linked SOFTECH document with branch/doctype/number/date.

## 6. Permissions (concept confirmed, multiple permissions wanted)

Separate, server-enforced permissions for: view · create · calculate · edit · approve · post to
SOFTECH · cancel · reverse · pay cash · override % · backdate · view profitability · view reports ·
manage grants. Branch scope on every action. Approver ≠ creator, always. Voucher user ≠ case
creator above the cash threshold. Extend `authz.py`, `ReplacementGrant` and the RBAC module.
Don't add a new permission system. Hidden buttons are never authorization.

## 7. SOFTECH rules (hard gate)

Do not invent SOFTECH posting logic or write to any ERP table until the native workflow is decoded
and validated: document types, master/detail relationships, stock effects, accounting effects,
serial generation, reversal behaviour (supplier return, sale return, voucher). Use the existing
rollback-probe / golden-template method. Ask for screenshots or DB samples when needed. Every write
is idempotent (`PostingOperation`), verified after write, behind a feature flag defaulting OFF, and
audited. Never double-post. Never touch the A/P auto-allocations on the six virtual accounts
(owner: keep them).

**Stop and ask before:** any change to discount/pricing calculation, anything touching payment or
checkout completion, any schema change affecting SOFTECH sync, turning on any writer flag, any new
SOFTECH write (supplier return, voucher), and anything that could double-post.

## 8. Owner decisions 2026-10-26 (settled: do not re-ask, record them in doc 25 §16)

- Q1 Rule matrix confirmed as in §4, including 3068 = non-insurance products 40 %, 4069 = non-insurance cash 50 %.
- Q2 Cash vouchers stay native (cashier). The module links and checks them. No voucher writer.
- Q3 Approval matrix as in §4 (cash: supervisor always, manager > 1,500).
- Q4 Contract-sale return on change of mind: 7 days and before month end.
- Q5 Redemption sales must use the patient's PIC or «عميل تبديل». Historical anonymous receipts stay proposed, for review.
- Behaviour switch: entry-first, the matcher only verifies (§5 B0).

If anything else is unclear, ask before the batch that needs it. Don't guess.

## 9. Execution rules (every batch)

Follow CLAUDE.md: state what and why → affected files → change → migrations → tests (keep the Samra
acceptance and all existing `test_replacement*` green; add concurrency/idempotency tests for any
write path) → **update in-app help** (`apps/help/content/<module>.py`, Arabic + English, bump
`updated`, `useHelpTab` for tabs) → run tests/lint/build → regression check → summary → update doc 25
with a new "as built" section → propose the next batch and **stop**. UI stays calm: no new popups
for common actions, Arabic-first, `useGridKeyboard` on review grids, branch labels never bare codes,
a forced-refresh button for synced data.
