# 19 — SOFTECH Indirect-POS Mastery & El-Rezeiky Modernization Roadmap

**Status:** study + plan (no code yet). **Offer-execution flag stays OFF.**
**Companion visual:** published artifact "SOFTECH POS Playbook".
**Sources:** [`SOFTECH_POS_FIELD_GAPS.md`](SOFTECH_POS_FIELD_GAPS.md) (captured from the user's
2026-07-26 screen recording), [`SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md`](SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md),
[`14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md`](14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md), and the live
code (`frontend/src/hooks/usePosOrder.js`, `frontend/src/pages/POSOrderPage.jsx`).

## Sourcing honesty
Everything **codified** is mastered (screen anatomy, three-level customer, item-search modal,
config rules, write path). **UPDATE 2026-09-02: the user re-shared the screen recording**
(`20260902-2017-27.mp4`, 1920×1020, 468 s, two full transactions — a permanent-customer sale and a
cash sale). Frames extracted at 1/3 s to the scratchpad and reviewed. §4a below records what the
video confirmed. Only two micro-details remain (exact global `TAB` sequence, whether `F4` deletes a
main-grid line vs only cancels in popups).

## 4a. Video-confirmed mechanics (2026-09-02 recording)
- **Screen matches** the census exactly: title `In-Direct Point of Sale`, two toolbars, header band,
  item grid, tabs `Items[Ctrl+2]/Payment[Ctrl+3]/Contract Emp.Data[Ctrl+4]`; on-screen hints
  `Ctrl+F2=Cash · Ctrl+F3=Home Delivery · Ctrl+F4=Contract`.
- **Three-level cascade — VISUALLY CONFIRMED on both channels.** Permanent: عميل دائم → نقابة
  التجاريين (A.M.I.S) → PIC `01HD1269`. Cash: عميل نقدى → **Walk-In Customer** → PIC `100HD7601`
  (a real individual attached to the generic cash account — proves level 3 is distinct and optional
  on cash). نوع العميل and إسم العميل are **dropdowns/comboboxes** (not free typeahead).
- **Item entry mechanism:** type a barcode/code into the **bottom empty row** of the grid; on an
  ambiguous match the **Item Search modal** opens inline (`F7` new query · `F8` execute · `Esc` exit;
  column-filter dropdowns نوع الصنف/المنشأ/المورد; scopes non-archived-only / all + has-balance).
  Selecting populates the line and a fresh empty row appears. So "add a line" = type in the empty row.
- **F-key legend (confirmed in every popup — Individual Customers query + its Add/Edit form):**
  `F7` new query · `F8` execute · **`F2` add** · `Ctrl+S` save · **`F4` cancel** · `Ctrl+E` exit.
- **Per-line qty + discount** typed in-grid; permanent customer took a 14% line discount.
- **OOS item auto-flags "Reservation"** with the qty rendered in **red** (PLAVIX, رصيد متاح 0).
- **Status bar** shows per-item `Balance Qty = X & On Order Qty = Y`; on save → `Last Sales S/No = 7864`.
- **PIC points enrollment** = the `نظام نقاط` checkbox in the Add-New-Individual form
  (= `localcustomers.picpoints`); that form also carries Address, Point-System نسبة, Status, Medical,
  and `أقصى مبلغ تحمل للتداخل عن المريض`.
- **Residual to confirm at build time:** the exact global `TAB`/`Shift+TAB` field order, and whether
  `F4` also deletes the *selected main-grid line* (it cancels inside popups; main-grid add is via the
  empty row).

## 1. Screen anatomy — four regions
- **Header band:** مبيعات فرع · من حساب مخزن (branch-dependent) · مسؤول البيع (auto-locked) ·
  **نوع/إسم/PIC العميل** (the three levels) · تاريخ المستند · نوع المستند (بيع 115 / مرتجع 30) ·
  أسلوب السداد (نقدى/آجل) · خصم فكة (≤0.50) · مسلسل صرف (auto) · خصم العميل % · ما يسدده المريض.
- **Item grid:** باركود · كود · الصنف · رصيد صلاحية متاح · رصيد متاح · ت الصلاحية · باتش · العبوة ·
  الكمية · سعر الوحدة · سعر العبوة · ض.ق% · خصم% · مبلغ الضريبة · الإجمالي. Qty = one field, in
  packs, default 1 (Sales Setup "One Field" / "ONE Package").
- **Payment tab:** نقدى + آجل ONLY at this install (card/cheque disabled → entered on the SOFTECH
  cashier screen post-push). ما يسدده المريض drives the cash-copay / claim split.
- **Contract Emp. Data tab:** 12 standard titles, relabeled per contract via `motalba_fields`.

## 2. The customer is a THREE-level cascade (user correction 2026-08-31)
Not "channel + free search" — a cascade where each level constrains the next, and **PIC is level 3
of the same selector**, not a separate row.

| Level | SOFTECH source | Drives | Required |
|---|---|---|---|
| **1. نوع العميل** (type) | `persontypesclassif.ptclassifcode` — 91 نقدى · 90 توصيل · 30 دائم · 10 تعاقد · 15 تأمين · موظفين · تعويضات | channel + **discount source** (retail = cap-only; contract = `custdiscounts`) | always |
| **2. إسم العميل** (account) | `personsdata WHERE ptclassifcode=type` → `personname, personcode, personglobalcode` | billing account + (contract) discount-schedule key | always (often a lone account for cash/delivery) |
| **3. العميل الفعلي / PIC** (person) | `personglobalcode`/phcode via the Individual-Customers directory | `softech_pic` stamp · **loyalty points** (enrolled PIC) · history + suggestions · patient in billing | **delivery = mandatory**; else optional (still enables history/points) |

**The close relationship:** level-2's `personglobalcode` **is a PIC pointer** — so when the account
is itself a named individual (walk-in with a real person, permanent customer), **levels 2 and 3
collapse into one**; for contract/delivery, level 2 is an *account* and level 3 a *distinct person*
under it. ⇒ level 3's option list and requirement are **derived from levels 1–2**. Today we model
1→2 as a cascade but PIC (3) is a separate row — the fix is to make it the third stage of the same
selector, with 2/3 collapsing when the account is a person.

## 3. Field-to-field dependencies (what recomputes what)
- مبيعات فرع → من حساب مخزن (balances + item search become per-store).
- نوع → إسم → PIC (channel + discount source/cap → billing account → person + points).
- القناة/العميل → per-line discount (contract auto-applies; retail = 0, capped at
  `min(item posdiscp, seller max_custdiscp)`; points NEVER discount a line).
- الأصناف + المخزن → FEFO batch/expiry; OOS → linked حجز-80 line.
- نوع = تعاقد → Contract Emp. Data tab (12 claim fields).
- الأصناف + خصم فكة → الإجمالي/الصافي → السداد (ما يسدده المريض splits patient-cash / claim).
- Governing config: seller "auto + locked", default qty 1 pack, fakka ≤ 0.50, max line qty 10000,
  منع الصرف if qty > (available − reserved), PIC-required-to-save = delivery only.

## 4. Keyboard-driven entry — the heart of SOFTECH's speed
SOFTECH is keyboard-driven; **our module is mouse-driven** (the biggest data-entry-speed gap).

| Key | SOFTECH function | Confidence |
|---|---|---|
| `TAB` / `Shift+TAB` | forward/back through editable fields, fixed order, no mouse | **needs-video** (exact order) |
| `F2` | add a new item line in the grid | **needs-video** (F2 = add inside the individuals modal, confirmed) |
| `F4` | delete the selected item line | **needs-video** (F4 = cancel inside modals) |
| `F7` / `F8` | search modals: F7 new query · F8 execute query | confirmed |
| `Ctrl+S` | save (add/edit an individual) | confirmed |
| `Ctrl+F2/F3/F4` | pick channel cash/delivery/contract | confirmed (we show as label only) |
| `Ctrl+M` | override discount cap via user OFFERS/123456 → stamps `stktransm5.supp_main_code=89` | confirmed (documented + implemented) |
| `Ctrl+F1` | advanced item-search modal (wildcards + column filters) | confirmed |

**Our current state:** audit of `usePosOrder.js`/`POSOrderPage.jsx` — `Ctrl+F2`, `Ctrl+2`, `Ctrl+F1`
and the numpad are rendered **as text labels only**; there is **no global `keydown` handler**, no
`F2` add-line / `F4` delete-line, no managed `TAB` order. Entry relies on the search widget + mouse.

## 5. End-to-end sales process
- **SOFTECH:** ① branch/store → ② channel via `Ctrl+Fn` → ③ type→name→PIC → ④ `F2` add items,
  qty/price/discount by keyboard, `F4` delete a line → ⑤ contract emp-data if needed → ⑥ payment
  tab (نقدى/آجل, patient-pays) → ⑦ save → "Cashed from Customer" popup → handed to cashier to close
  cash + award points.
- **Ours:** ① branch/store (default from seller) → ② channel/customer (three-level cascade) →
  ③ items via widget + FEFO batch + reservation logic → ④ dry-run preview (no write) → ⑤ live push:
  `POST /pos-orders/` → `ready` → `push` → writes `stktransm5/stktrans5` as pending → cashier
  finalizes. Points via per-line `vf4`; discount via `cust_discp`; offer override stamps 89.

## 6. Parity matrix (grounded in code)
- **Have:** type→name cascade, retail-cap / contract-auto discount, FEFO+batch+reservation, shared
  item search + advanced modal, 12-field contract emp-data, SOFTECH push (points/discount/89
  override), offers + PIC-suggestions + basket-intel panels (preview only).
- **Partial:** PIC as a unified level-3 (exists as a separate row); referral-doctor (fields in the
  payload, no image upload / stats).
- **Missing:** full keyboard nav (TAB/F2/F4/Fn are labels only); TAB order matching the legacy
  screen (needs-video); OCR-Rx / voice entry in the POS; per-employee channel RBAC.

## 7. Modernization roadmap
- **Phase A — Keyboard-speed parity (start here, "not a tremendous change"):** a global `keydown`
  handler that makes the shown shortcuts real (`Ctrl+Fn` channels, `Ctrl+1/2/3` tabs, `Ctrl+F1`
  search); `F2` add-line (opens+focuses search), `F4` delete selected line, arrow-key line
  navigation, `Enter` accept→jump-to-qty; a **managed `TAB` order** matching the legacy sequence
  (needs-video); **fold PIC into the single customer selector as level 3** with 2/3 collapse.
- **Phase B — Intelligence:** wire the built offers / PIC-suggestions / basket-intel panels to
  moment signals; loyalty & retention via Customer-360 + points + revalidated repeat-order → "next
  expected" / "due to repeat"; CLV & acquisition via segments → tier-up nudges + fast new-individual
  add mid-sale. (Reuse — do not rebuild.)
- **Phase C — Modern entry:** OCR-Rx → suggested lines (reuse shortage/invoice OCR pipeline, human
  confirm); voice item entry (`apps/omni/transcription.py` exists) → confirmed match, no auto-decide;
  Rx image upload on our order + **referral-doctor field → doctor-referral stats**.
- **Phase D — Governance:** per-employee allowed-channels RBAC (server-enforced, filters the channel
  list + rejects unauthorized push); full audit trail (who/what/when/why/before-after).
- **Phase E — Gate:** flip offer execution ONLY after the owner's live §10b/§14 SOFTECH dry-run.
  The tender-recompute is already built + wired; `POS_OFFERS_EXECUTION_ENABLED` stays OFF.

## 8. Open questions (what the video confirms)
Q1 exact `TAB` order across header + grid. Q2 `F2` add-line / `F4` delete-line on the main grid
(and where focus lands after). Q3 is إسم العميل a full dropdown or typeahead. Q4 item-search modal
detail (compound filters, On-Order column). Q5 any other daily cashier shortcuts not in the docs.

## 9. Non-negotiable guardrails
SOFTECH integrity (no writes outside the tested methodology; idempotent; no double-post); deterministic
money (no AI-decided totals/discounts); pharmacy safety beats upsell; server-side permissions; and the
offer-execution flag stays OFF until the owner's live dry-run.
