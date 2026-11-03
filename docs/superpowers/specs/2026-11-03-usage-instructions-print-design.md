# Usage-Instructions Print («طباعة طريقة الاستخدام») — Design

Date: 2026-11-03 · Owner-approved idea, Project 5 of 5 · Status: design, awaiting owner approval

## Intent and why

Patients leave the pharmacy with several boxes and a verbal explanation they forget. The owner
wants the pharmacist/salesman to hand over a printed receipt-paper slip that says, per item, how
to take it — e.g. «Brilique 90 — قرص واحد مرتين يوميا بعد الأكل», «Aspirin Protect — قرص واحد
صباحا بعد الفطار». Mostly used against prescriptions. It must be fast at the counter (a few
clicks) and safe: **everything the system proposes is only a suggestion; a human confirms every
line before anything prints.** Later the same paper becomes a customer-touch surface (QR codes,
hotline, WhatsApp, social/e-commerce links, product ads, return policy, fridge-storage notes).

## Goals

1. Pick a sale by invoice number (branch + today by default) and show its lines.
2. Suggest one instruction per line from deterministic sources only (below), with its source shown.
3. One-or-two-click quick presets to build an instruction; free text always allowed.
4. Per-line confirm; print is locked until every line is confirmed or marked «لا يطبع».
5. Print on the existing 80 mm receipt printer; the user picks layout per invoice:
   **one slip with all items (default)** or **one cut piece per item**.
6. Show the prescription photo when the sale came through our POS; otherwise allow attaching one
   on this screen.
7. Remember confirmed instructions and suggest them next time.
8. Full audit: who confirmed which instruction for which invoice line, when; every print/reprint.
9. A slip layout built from ordered blocks so footer/marketing content can be added later without
   code changes to the core flow.

## Non-goals (v1)

- Writing anything to SOFTECH (strictly read-only).
- Any LLM generating, rewriting or choosing an instruction.
- Clinical checks (interactions, max-dose validation) — Project 4 (drug assistant) owns clinical
  content; this screen only displays approved text.
- Product ads, per-item fridge-storage notes, return-policy text blocks — the block framework
  supports them, but only the blocks listed under "Slip blocks v1" ship now.
- Native/ESC-POS printing — browser print at 80 mm, same as `ReceiptPrint.jsx`.

## Anti-goals (failure even if it "works")

- A slip prints with an instruction nobody confirmed.
- A suggestion silently becomes the printed text without the human seeing its source.
- Looking up an invoice by bare docnumber (collides across branches/doctypes) → wrong patient's
  items.
- The screen blocks go-live: it must be invisible and inert while the flag is OFF.
- A modal-heavy flow; this must feel like a calm one-screen task.

## Constraints

- Feature flag `USAGE_PRINT_ENABLED` (env, `config/settings.py` style, default **False**). OFF ⇒
  API returns 404/403, route + nav entry hidden, no scheduler jobs.
- SOFTECH read-only. Invoice identity is always (branch, doccode, docnumber, docdate) — never
  docnumber alone (see SOFTECH docnumber collision rules). Sales (doccode 115) only in v1;
  returns (30) are rejected with a clear message.
- Server owns rules: suggestion ranking, "all lines confirmed" gate, and audit live in the backend;
  the print endpoint refuses unless every non-excluded line is confirmed. React only renders.
- Server-side permissions; branch scoping via `core/branch_scope.py` (a user only opens invoices of
  branches they may access).
- Arabic RTL, calm UI, keyboard friendly (Enter = confirm line and move on; F9 = print).
- In-app help (`apps/help/content/…`, AR+EN) for the new route; `apps/tests/test_help.py` passes.

## How it works (decided)

### 1. Finding the invoice
- Inputs: invoice number (focused field), branch (defaults to the user's branch; selectable only
  among allowed branches), date (defaults today; can go back a few days).
- Lookup order:
  1. Our sales mirror (`customers.PurchaseHistory` + lines, `doc_code='115'`, branch, docnumber,
     invoice_date on that day). Fast sync runs every 5 min.
  2. **If not found → live read-only fetch from SOFTECH** of that one invoice (owner decision),
     bounded by branch + doccode 115 + docdate (indexed), lines from stktrans aggregated per item
     (multi-batch rows summed). Goes through the existing `config/sybase.py` gate (network/device
     gating, read path). Result is not written into PurchaseHistory (the normal sync does that);
     it is snapshotted into our own sheet record only.
  3. Not found anywhere → «الفاتورة غير موجودة لهذا الفرع/اليوم».
- If the sale matches a POS order (`SoftechSalesOrder.softech_final_docnumber` + same branch +
  date) its `prescription_image` is shown.

### 2. The instruction sheet (our record)
One sheet per invoice (unique on branch+doccode+docnumber+docdate). Re-opening the invoice
re-opens the same sheet (shows previous confirmations; reprint allowed and logged). Lines are a
snapshot of the invoice lines (item, name, qty) plus: suggested text, suggestion source, final
text, status (pending / confirmed / excluded), confirmed_by, confirmed_at.

### 3. Suggestions (deterministic, in this order, first hit wins; the source is shown as a tag)
1. «آخر مرة لنفس المريض» — this customer's last confirmed instruction for this item (only when the
   invoice has a real named customer).
2. «الأكثر استخداما» — the most frequently confirmed instruction for this item (ties → most
   recent), from confirmed lines across all sheets.
3. «محتوى معتمد» — pharmacist-approved curated content owned by Project 4 (drug assistant):
   one per-item record in `apps/counselling` with status draft→approved, approved_by/at,
   version. This screen reads **approved versions only**, through a read helper Project 4 exposes
   (`apps.counselling.selectors.approved_usage_text(item)`; contract in the shared notes folder, project4-counselling-content-contract.md). Until it exists this
   source returns nothing. `enrichment.ItemEnrichment` is **not** used: its clinical fields are
   AI-filled and auto-approved at ≥0.9 confidence (verified live 2026-11-03: 10 of 38,287 rows have
   dosage, 0 published).
4. Nothing → empty field with the preset chips.

### 4. Quick presets
Two kinds, both admin-editable lists (seeded with sensible Egyptian-pharmacy defaults):
- Chip builder: amount (قرص واحد / نصف قرص / كبسولة / ملعقة صغيرة / … نقط / بخة …) ×
  frequency (مرة يوميا / مرتين / ٣ مرات / كل ٨ ساعات / عند اللزوم …) × timing (قبل الأكل / بعد
  الأكل / صباحا بعد الفطار / قبل النوم …). Clicking chips composes the sentence in the line's
  text field; text stays editable.
- Whole-phrase presets for common full sentences.
Chips are just text helpers; nothing is parsed or validated clinically.

### 5. Confirm and print
- Each line: text field + ✓ confirm + «لا يطبع» (exclude). Editing a confirmed line un-confirms it.
- Print button enabled only when no line is pending. On print the server re-checks, stamps the
  sheet (printed_by, printed_at, print_count++, layout), writes `AuditLog` entries, and returns the
  render payload; the browser prints at 80 mm.
- Layout choice per print: single slip (default) or cut-per-item (page break per item).
- Confirmed lines feed suggestion sources 1 and 2 (no separate "memory" table needed if the
  ranking query over confirmed lines is fast enough; builder may add a denormalised table).

### 6. Prescription photo
- Sale from our POS with a photo → thumbnail, click to enlarge.
- Otherwise → «إرفاق صورة الروشتة» on the sheet, reusing the POS upload validation/limits
  (`apps/pos_orders/views.py` upload rules; shared helper, not a copy). Stored on the sheet.

### 7. Slip blocks (extensible layout)
The slip is an ordered list of blocks; header/footer blocks come from runtime settings
(`SystemSetting`) so marketing can change them without a release.
Slip blocks v1: pharmacy header (logo/name/branch), invoice no + date, patient name (only if a
real named customer — owner decision), item blocks, footer text (e.g. «استشر الصيدلي»), hotline /
WhatsApp line, optional one QR code (URL from settings; rendered server-side with the existing
`qrcode` package). Each footer block can be switched on/off. Later blocks (ads, fridge storage per
item, returns policy, multiple QRs, social links) plug into the same list.

### 8. Permissions
New RBAC module `usage_print`: `view` (open sheets), `create` (confirm + print), `edit` (manage
presets + slip settings). Seed: pharmacist + salesperson → view/create; supervisor/admin → all.

## Calls made by the designer (not owner decisions — owner may override)

- **Real named customer** = the sale's customer has a real `softech_pic` (not the `ACCT-<personcode>`
  placeholder from the sales-link fix). Only then: patient name printed and source 1 used. On the
  live path, the patient is identified by the header's PIC field the same way the sales sync does;
  no PIC → treated as unnamed.
- **Live fetch reads the selling branch's own server first** (it has today's sales before HQ),
  then HQ, through the existing `config/sybase.py` connection + network/device gate, read-only,
  short interactive timeout. Gate denial or unreachable server → calm message «تعذر الوصول للفاتورة
  الآن — حاول بعد دقائق»; never an error page.
- **Invoice changed after the sheet was created** (sync brought different lines, partial return):
  on reopen the sheet re-checks against the current invoice. Unchanged items keep their
  confirmations; new/changed items come back as pending; removed items are dropped and a quiet
  banner says the invoice changed. A fully returned invoice shows a warning and printing stays
  allowed only after re-confirmation.
- **"Printed" means print was requested** — the server stamps and audits when the user presses
  print (the browser dialog can still be cancelled). Labeled «طلب طباعة» in the audit.

## Left to the builder

- App placement (new small app vs inside `pos_orders`) and model names.
- Exact preset seed lists and chip UI arrangement.
- How many days back the date picker allows (suggest 7).
- Whether suggestion ranking needs a denormalised table.
- Print CSS details, staying within the existing `ReceiptPrint.jsx` approach.
- Help-content wording.
