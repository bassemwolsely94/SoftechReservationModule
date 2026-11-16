# ETA production item coding + the bulk EGS sheet — design

Date: 2026-11-16 · Owner decisions taken in conversation, one at a time · Module: `apps/tax_invoicing` (doc 36)

## 1. Why

The receipts reconciliation (PRs 145/148/149) showed that most sales missing at ETA are items with no ETA code:
5,108 items sold since March 2025 with no code, worth **15.19M EGP** of sale lines. Invoicer, the outside program
that uploads receipts, leaves a line off the receipt (and the whole receipt when no line is left) unless the item is
coded in **`ElRezeiky_Bulk_EGS_Items.xlsx`**. Nobody has added to that sheet since **10 May 2026**; before that, coding
was done in batches (Jun 2022: 10,486 items, May 2023: 1,361, Jan 2024: 292, Apr 2024: 585), then ~70 by hand.

Today a person registers each code by hand on invoicing.eta.gov.eg (EGS first; GS1 when EGS is refused), waits for
approval, then adds the row to the sheet. The owner wants this inside our system, for the items that should be on
receipts, while **keeping out** the items that are meant to stay out.

Two outputs per item:
1. **The code registered on ETA production.** Enough for e-invoices: Invoicer checks invoice lines against ETA
   directly, and ETA rejects an invoice with an uncoded item.
2. **The item in the bulk EGS sheet** (coded row). Needed for e-receipts: Invoicer matches receipt lines against the
   sheet only.

### Goals
- One review queue of uncoded sold items, biggest sales first, each pre-marked by a rule, confirmed by a person.
- Codes requested on ETA production through the existing code-request flow, without the portal.
- A GPC brick suggested for every item (learned first, AI for the rest), confirmed by a person.
- A VAT rate for every new sheet row, prefilled from SOFTECH, flagged when unusual, confirmed by a person.
- The bulk EGS sheet regenerated from our records, in Invoicer's exact format, delivered three ways.
- Codes that already exist on ETA production but are missing from the sheet found and added (no new request).

### Non-goals
- Deciding whether keep-out items belong on receipts: that stays the owner's, with the tax adviser (doc 36 /
  memory "declined" list). This feature only codes what a person confirms.
- Coding services (فرق سعر, D.L.V., checks, injections) — kept out for now; the owner may revisit.
- Replacing Invoicer, or our own receipt sending. Invoicer keeps uploading receipts.
- Any SOFTECH write.

### Anti-goals (a failure even if it "works")
- A sheet that drops or blanks a coded item, or a wrong file that stops every receipt upload.
- A code, brick or VAT rate that reaches ETA or the sheet without a person's confirmation.
- An AI-invented brick, or a brick not in the official GPC list.
- A blacklisted / keep-out item made white automatically.
- Sending to ETA production without the gates and the owner's yes on the first request.

## 2. What exists (reuse, don't rebuild)

- `TaxItemProfile` (one per SOFTECH item): `eta_code`, `code_type`, `gpc_code`, `coding_status`
  (missing/pending/approved/rejected), `coding_env`, `list_status` (white/black/none), `tax_treatment`, `vat_rate`,
  `treatment_confirmed_at/by`, `source_vat_rate`. 41,278 rows: 13,088 white (coded), 23,102 black (= not coded in the
  sheet, see §3), 5,088 none (added from the catalog on 13 Nov).
- `TaxCodeRequest` + `coding.py`: prepare → send (switch `TAX_ETA_CODING_ENABLED`, `TAX_ETA_PRODUCTION_ALLOWED` for
  production, `finalize` permission, typed count) → refresh ETA's decision → item `pending`/`approved`/`rejected`.
  Purposes new / mirror / gs1. One open request per item (DB constraint). Only ever sent to preprod (12 open there).
- `gpc.py` + `TaxGpcBrick` (5,101 bricks loaded from the owner's workbook): `known(code)`, `suggest(profiles)`
  (most-used brick of approved items in the same SOFTECH family / category / type).
- `item_import.py`: the sheet import (13 Nov: 36,190 rows; mapping saved in `TaxAuditEvent` id 4).
- `eta_reader.py`: per-system read-only client; production login `TAX_ETA_READ_PRODUCTION_CLIENT_ID/_SECRET`
  (a production ERP registration created 14 Nov), switch `TAX_ETA_READ_PRODUCTION_ENABLED` (on, office).
- `eta_client.py`: `create_egs_codes`, `request_code_reuse`, `my requests` (GET codetypes/requests/my),
  code details — bound to the one system the server *sends* to (`TAX_ETA_ENVIRONMENT`, office = preprod).
- `eta_recon.py`: `EtaReconUncodedItem` (per day/branch/item: docs, qty, value) — the sales-value source for ordering.
- Procurement: `PurchaseLine` (SOFTECH purchases since 2025-05-22, `doccode` 10/120) + `SupplierSegmentation`
  (category per supplier, manual overrides kept). On 2026-11-16 the owner moved Ikhnatoun (3031) →
  OFFICIAL_DISTRIBUTOR, Sunny Medical (4649) → MANUFACTURER, Concord (4830) → DRUG_WAREHOUSE (done, noted).
- Signing agent (`deploy/tax_signing_agent/agent.py`) on the seal PC 192.168.1.8: pulls `TaxSigningJob`s from our
  server over the VPN (`signing-agent/next/`, `.../result/`), 32-bit Python, no inbound port.
- AI providers: `apps/enrichment/ai_extractor.py` provider chain (Gemini → OpenAI) with per-provider rate limiters,
  keys in settings (`GEMINI_API_KEY`, `OPENAI_API_KEY`).

## 3. The sheet, as it really is

`DataEntry` sheet, 16 columns, one row per SOFTECH item (36,190 rows), table/autofilter A1:P…, defined name `CodeTypes`:

| Col | Header | Content |
|---|---|---|
| A | CodeType | `EGS` / `GS1` when coded; empty when not |
| B | ItemCode | `EG-499336534-<itemcode>` (prefilled on every row), or the GS1 barcode |
| C | CodeName | name |
| D | CodeName2Ar | Arabic name (often empty) |
| E/F | Description / DescriptionAr | |
| G | ActiveFrom | date when coded; empty when not |
| H | ActiveTo | |
| I | GPCItemLinked | brick (number), 0 when none |
| J | EGSRelatedCode | the SOFTECH item code (number) |
| K | VAT % | 0 or 0.14 (percent format) |
| L | formula `=IF(AND(K=0%,A="EGS",I<>0,G<>""),1,0)` | |
| M | (empty) | |
| N | Blacklist, formula `=IF(AND(A="",G=""),"1","0")` | **derived**: "black" = not coded yet |
| O | formula `=K*100` | |
| P | formula `=IF(O=0,"v003","v009")` | VAT code |

Other sheets (`GPC Bricks Cleaned`, `ElRezeiky GPC Applied`) are reference only; the export keeps them untouched.

Invoicer reads the file **on every receipt upload**; an open/locked file blocks uploads. Fixed path on the seal PC:
`D:\invoicer_mini\ElRezeiky_Bulk_EGS_Items.xlsx`. The office copy (same content) is
`…\Claude Development\ElRezeikyTaxAgent\ElRezeiky_Bulk_EGS_Items.xlsx`.

**Consequence:** "black" in the sheet is not a keep-out decision. Keep-out is a new, explicit decision (§4).

## 4. The coding queue and the keep-out rule

### 4.1 Who is in the queue
Every item that (a) has sales in `EtaReconUncodedItem` for production, or is an active catalog item with no profile
(`add_from_catalog` runs first, so the 83 untracked items get profiles), and (b) has no approved/pending code, and
(c) has no confirmed decision yet. Ordered by uncoded sales value (all time in the recon), with a toggle for "sold in
the last 90 days".

### 4.2 The rule (owner-confirmed 2026-11-16) — a pre-mark only; a person confirms every item
Evaluated per item on SOFTECH purchases since 2025-05-22 (`PurchaseLine`, doccode 10), using supplier categories:

- **Official sources** = OFFICIAL_DISTRIBUTOR, DRUG_WAREHOUSE, MANUFACTURER, SMALL_WAREHOUSE.
- **Ignored** = PATIENT_REPURCHASE, CUSTOMER_REPURCHASE ("patient suppliers": never decisive either way).
- **Other** = UNKNOWN, GENERAL_SUPPLIER and anything else.

| Order | Condition | Pre-mark | Note shown | Today: items / value |
|---|---|---|---|---|
| 1 | medicine type Services, or not stockable, or customer gifts (هدايا عملاء) | keep out | «خدمة / هدية — لا تُكوَّد حالياً» | 31 / 0.38M |
| 2 | any purchase from OFFICIAL_DISTRIBUTOR / DRUG_WAREHOUSE / MANUFACTURER | code it | supplier category + last purchase | 3,552 / 10.91M |
| 3 | purchases from SMALL_WAREHOUSE only (among non-ignored) | code it | «اشتُري من مخازن صغيرة فقط — تأكد من تسجيله (هيئة الدواء / سلامة الغذاء)» | 347 / 0.30M |
| 4 | non-ignored purchases exist, none official | keep out | «لم يُشترَ من موزع أو مخزن أو مصنع» | 317 / 2.97M |
| 5 | no non-ignored purchase in the window | person decides (no pre-mark) | «لا مشتريات معتبرة منذ مايو 2025» | 861 / 0.63M |

- The rule lives in one function (`coding_rule.premark(item, buys)`) returning `(premark, reason_code, note)`;
  thresholds/categories are module constants, not settings. Tests pin each row of the table.
- Pre-marks are recomputed on every queue load (cheap: one grouped purchase query). A confirmed decision is never
  changed by the rule; a keep-out item that later gets an official purchase shows a «اشتُري الآن من مصدر رسمي» hint
  but stays kept out until a person reopens it.

### 4.3 The decision record
New model **`TaxCodingDecision`** (one per item, history in `TaxAuditEvent`):
`profile` (1:1), `decision` (`code` | `keep_out`), `premark`, `premark_reason`, `brick` (8 digits), `brick_source`
(`family_memory` | `sheet` | `ai` | `person`), `vat_rate` (0 / 14 …), `vat_flagged` (bool), `names` (code_name,
code_name_ar, description, description_ar), `decided_by`, `decided_at`, `note`, `reopened_*`.
Confirming "code it" also confirms the VAT rate onto the profile (`tax_treatment`, `vat_rate`,
`treatment_confirmed_at/by`) through the existing treatment-confirmation service (audited), and records the brick.
Confirming "keep out" sets nothing on the profile except an audit event; the item never enters a code request or
the sheet as coded. Reopen = audited, needs a reason.

### 4.4 The screen
A new tab in «الترميز الضريبي» (existing coding screen): «طابور الترميز».
- Grid rows (biggest first): item code + name, sales value / receipts / last sold, pre-mark + note, supplier
  summary, brick (code + Arabic name + source + AI reason, editable with a brick picker over `TaxGpcBrick`),
  VAT (prefilled, red flag when unusual), names (editable inline), decision buttons.
- Keyboard: `useGridKeyboard` (↑↓ Space Enter M Ctrl+A) — Enter = accept pre-mark (+ brick + VAT) for the
  selection, K = keep out, C = code it. Sortable (`useServerSort`), filters: pre-mark, decision, family, flag.
- Bulk: "accept pre-marks for the selection" is allowed only for rows whose brick and VAT are both non-flagged.
- Read access: tax module view; deciding: `finalize` permission (same as preparing code requests).

## 5. GPC brick suggestion (owner chose: learned first, AI for the rest)

Order per item, first hit wins:
1. **Family memory**: the brick a person confirmed for another item of the same SOFTECH family (most recent
   majority among confirmed decisions; requires ≥ 3 confirmations and ≥ 80% agreement).
2. **The owner's sheet**: brick in `ElRezeiky GPC Applied` col «أكواد الضرائب» for this item (408 queue items).
3. **AI**: provider chain (Gemini → OpenAI) via a new `gpc_ai.suggest(items)`:
   - Input per item: SOFTECH name, family, category, medicine type, origin, producer; plus a **shortlist** of ≤ 40
     candidate bricks with definitions: the bricks used by approved items of the same family/category (top 15) +
     keyword/segment candidates from the GPC schema (Healthcare 51, Beauty/Personal Care 53, Food/Beverage 50,
     Baby Care, Cleaning, Medical devices).
   - Output (JSON): `brick`, `second`, `reason` (≤ 120 chars, Arabic), `confidence` (high/medium/low).
   - Code checks: brick must be in the shortlist **and** `gpc.known()`; otherwise discarded and the row shows
     "no suggestion". Medicines (medicine type Medicine) default to 10005845 without an AI call unless the family
     memory says otherwise.
   - Cached per item (`TaxCodingDecision.ai_*` fields: brick, second, reason, confidence, model, asked_at) so the
     AI is asked once; "ask again" button per row. Batched in the background (one scheduler job, rate-limited,
     biggest items first); never on page load.
4. Nothing → the person picks.

GPC data: load the GS1 «GPC as of May 2026 (v20260520)» JSON (segments → families → classes → bricks + definitions)
into `TaxGpcBrick` (add `definition`, `segment`, `family`, `klass` fields) via the existing `load_gpc_bricks`
command extended to read GS1's JSON. The owner downloads the file; the command never fetches from the internet.

The AI only proposes a category; it never decides a code, a VAT rate, an amount, or whether an item is coded
(CLAUDE.md rule 10). Item names are not personal data; no customer data goes to the AI.

## 6. VAT for new rows (owner chose: SOFTECH prefill + flag + confirm)

- Prefill = SOFTECH item sales-tax % (`itemsalestaxp`, catalog mirror field; 0 or 14 in practice).
- Flag when: Cosmetics / Others / Body Building at 0%; Medicine at 14%; any rate other than 0 or 14.
  (Measured on the 13,088 coded rows: sheet = SOFTECH on 10,664; sheet 14 / SOFTECH 0 on 324, mostly cosmetics —
  SOFTECH wrong.)
- A row cannot be confirmed "code it" without a VAT rate; flagged rows cannot be bulk-accepted.
- The confirmed rate is what the sheet's column K gets (as 0 / 0.14).

## 7. Sending codes to ETA production

- New `coding` path per system: production requests use the **production ERP registration already configured for
  reading** (owner chose: same registration). Implementation: a small `eta_writer`/`coding_client(system)` that
  takes its token from `TAX_ETA_READ_PRODUCTION_CLIENT_ID/_SECRET` (renamed alias `TAX_ETA_PRODUCTION_CLIENT_*`
  accepted), calls the same two endpoints as `eta_client`, and keeps `eta_client` (the send-system client) unchanged.
- Gates, all required for production: `TAX_ETA_CODING_PRODUCTION_ENABLED` (new, default False, `config/writers.py`)
  · `TAX_ETA_PRODUCTION_ALLOWED` · `finalize` permission · typed count. `TaxCodeRequest.environment` = 'production'.
  Registered in `apps/tests/security/softech_write_manifest.py`? — no: it is not a SOFTECH write; it goes in the
  ETA outward-channel list in doc 36 and the security sweep's flag list.
- **First production request = one item, owner's yes at that moment** (the screen refuses a production batch of
  more than 1 until one production request has reached `approved`; overridable only by the owner flag
  `TAX_ETA_CODING_PRODUCTION_BATCH_OK`).
- Batches of ≤ 200 (existing `MAX_PER_ACTION`), one item per HTTP call (existing), ETA pace respected.
- Prepared from the decision: `prepare()` takes brick + names + active_from from `TaxCodingDecision`.
  **Active from = 1 January of the current year** (owner's practice; protects late receipts).
- Refresh of ETA decisions for production runs on the existing refresh path, per system.
- **GS1 fallback**: when an EGS request ends `rejected` and the item has a valid GTIN (`gtin_for`), the queue row
  offers «جرّب GS1» → `prepare_gs1`. Never automatic.
- The 12 preprod requests are untouched. Fix: `eta_recon.coded_items()` counts a profile as coded only if
  `coding_env in ('', 'production')` (preprod-pending codes no longer count as coded in the production recon).

## 8. Codes already on ETA but missing from the sheet (first, read-only)

- `eta_reader` (production) lists the company's code usages (GET codetypes/requests/my, all pages, status
  Approved/active) into a new mirror `EtaCodeUsage(system, code_type, item_code, name, active_from, active_to,
  status, gpc, fetched_at)`.
- Match to items: EGS `EG-499336534-<itemcode>` → itemcode; GS1 → `ItemBarcode`.
- Report: "on ETA, not in the sheet" (→ added to the sheet as coded, after a person confirms VAT; no new request),
  "in the sheet, not on ETA / inactive" (→ shown, nothing automatic), counts per status.
- This runs before the queue so the queue excludes items already coded on ETA.

## 9. The bulk EGS sheet: generate, deliver, swap

### 9.1 Generation (one function, all three outputs use it)
`egs_sheet.build()`:
- Starts from the **last sheet we hold** (the file the agent last fetched, or the office copy imported once) — the
  workbook is loaded with openpyxl (not read-only), and only `DataEntry` cells A, B, C, D, E, F, G, I, J, K of the
  affected rows are written; formulas L, N, O, P copied from the row above's pattern for new rows; other sheets,
  styles, widths, freeze panes, table and defined names kept.
- An item gets a coded row when: profile approved (production or workbook) **and** decision is not keep-out **and**
  confirmed VAT. Items without a row (new since the sheet) are appended in item-code order.
- **Checks before the file is accepted** (any failure → no file, reason shown):
  same sheets + same header row; no duplicate J (itemcode) and no duplicate coded B; every coded row has A, B, G,
  I ≠ 0, K ∈ {0, 0.14}; no keep-out item coded; **coded-row count ≥ the current file's coded-row count** unless
  a person removed rows on purpose (each removal is an audited action with a reason); file opens and re-reads.
- Output: bytes + SHA-256 + a diff summary (added / changed / removed coded rows, with item lists).
- Stored as `TaxEgsSheetVersion(n, sha256, coded_rows, added, changed, removed, built_by, built_at, file)`
  (file in media storage, ≤ 20 MB; keep the last 30).

### 9.2 Delivery
- **A. Full download**: button on the coding screen → latest built version, `TaxAuditEvent` `egs_sheet_download`.
  The screen reminds: close Excel after replacing the file (an open file blocks uploads).
- **C. New rows only**: download of only added/changed rows (same columns), for pasting.
- **B. Automatic write via the seal agent**:
  - New agent job kind `egs_sheet` on the existing pull channel (agent asks `signing-agent/next/`; server returns a
    sheet job with version id + SHA-256 + download URL on our server; agent downloads over the VPN).
  - Agent steps on 192.168.1.8: download → verify SHA-256 → write `ElRezeiky_Bulk_EGS_Items.new.xlsx` in
    `D:\invoicer_mini\` → copy current file to `D:\invoicer_mini\backup\ElRezeiky_Bulk_EGS_Items.<timestamp>.xlsx`
    (keep 30) → `os.replace(new, live)` (single rename). If the rename is refused (file in use), retry 5× over
    ~2 minutes, then give up leaving the old file in place → result `busy`.
  - Agent never opens the live file in place; to report the current file it copies it first and uploads the copy
    (job kind `egs_sheet_fetch`, read-only; used to seed §9.1 and to detect hand edits).
  - Schedule: nightly at 03:00 (no sales), plus a «اكتب الآن» button. Only a version that passed §9.1 checks and
    differs from the live file's SHA is sent.
  - Switch `TAX_EGS_SHEET_AGENT_WRITE_ENABLED` (default False) + per-run mode: preview (agent fetches and reports,
    writes nothing) is the default until the owner turns writing on.
  - Result logged (`TaxAuditEvent` `egs_sheet_written` / `egs_sheet_busy` / `egs_sheet_failed`: who/what, version,
    rows added).
  - Hand edits: if the fetched live file's coded rows differ from our last version (someone edited it by hand),
    the next write is held and the screen shows the difference for a person to accept (import those rows) or
    overwrite.
- The agent is in this repo (`deploy/tax_signing_agent/`); the seal PC copy is updated by hand (README steps).

## 10. Approaches considered (owner picked in conversation)

- Sheet delivery: **all three** (A full download, B agent write, C new rows); A and B are the deployed ones.
- Agent vs shared folder for B: **seal agent** (no new inbound path to the seal PC).
- Keep-out: **rule + person, biggest first**; rule derived from history and confirmed (§4.2). Rejected: XX in name,
  price line, the sheet's Blacklist column (all shown not to be decisive).
- Brick: **learned + AI** (picked) vs AI on every item (≈5,000 calls, no learning) vs word rules only (weak on
  brand names).
- VAT: **SOFTECH prefill + flag + confirm** (picked) vs accountant sets every rate.
- Production login: **same production ERP registration** (picked) vs a second registration for coding.

## 11. Security / CLAUDE.md definition of done
- Access: under `/api/tax-invoicing/` (already mapped); read = tax module view, decide/send/download/agent-write =
  `finalize` (matrix permission). Agent endpoints keep the agent-token auth.
- Branches: company-level data (items, codes), tax module only.
- SOFTECH: reads only (catalog, purchases mirror); no SOFTECH write.
- Outward channels: ETA production code requests and the Invoicer file write are new outward channels — each has a
  default-OFF flag in `config/writers.py`, a dry-run/preview default, idempotency (one open request per item; sheet
  writes keyed by version SHA, a re-sent version is a no-op), and audit.
- Privacy: no phone/customer data; item names only go to the AI.
- Exports through `core/export_safety.py` (neutralise formulas only on our own report exports — **not** on the
  Invoicer sheet, whose formulas are intended; that file is a byte-for-byte workbook, not a report, and is
  documented as the reasoned exception).
- Help: «طابور الترميز» tab + sheet section in `apps/help/content/tax_invoicing.py` (AR/EN), `updated` bumped.
- Tests: rule table, decision/audit, brick pipeline (shortlist + known() guard, cached, no call for medicines),
  VAT flag, production gates + first-request rule, sheet build checks (each refusal), agent swap (busy/retry/backup)
  with a fake filesystem, recon `coded_items` env fix, ETA code-usage mirror matching.

## 12. Batches (each proposed and approved before starting)
1. **S1 — read side**: ETA production code-usage mirror + "on ETA, not in sheet" report; recon `coded_items` fix;
   `TaxCodingDecision` + rule + queue (read-only pre-marks, decisions, VAT confirm); GPC May-2026 load.
2. **S2 — bricks**: family memory + sheet + AI suggestion job, brick picker.
3. **S3 — sheet**: `egs_sheet.build` + checks + versions + downloads A and C.
4. **S4 — production requests**: per-system coding client, gates, first-request rule, GS1 fallback offer.
5. **S5 — agent write (B)**: agent job kinds, swap, backup, nightly + now, preview default; README for the seal PC.

## 13. Left to the builder
Exact field names, the brick shortlist size within ≤ 40, the AI prompt wording, the queue page size, how the
family memory is cached, migration numbering, and where the sheet versions are stored inside media.

## 14. Settled after the builder check (2026-11-16)

These override anything above that says otherwise. "Builder's call" = settled by Claude, open to the owner's
correction; "owner" = the owner's answer.

1. **Existing coded rows are carried forward untouched** (builder's call). `build()` copies every row already coded
   in the last held sheet as is — A, B, C…K never rewritten from our records, including the 324 rows where the
   sheet says 14% and SOFTECH 0% (the sheet wins; a read-only report lists those disagreements). `build()` only
   (a) codes rows for newly approved items (A, B, G, I, K, names) and (b) appends rows for items not in the sheet.
   "Confirmed VAT" is required only for those. A "changed" row = an uncoded row that becomes coded. Removing a coded
   row is a separate audited person action with a reason; `build()` never does it.
2. **Preprod and production coding coexist** (builder's call, schema change in the tax module only): preprod `new`
   / `gs1` requests stop changing the item profile (as `mirror` already doesn't); their answer is kept on the
   request only. The one-open-request constraint becomes per system (`profile`, `environment`), and `prepare()`
   records the target system at prepare time. The profile's coding state is production's (or the workbook's). The
   12 open preprod requests stay as they are; items in them can be requested on production.
3. **Coding is production-only, and its gate is independent** (builder's call): `TAX_ETA_CODING_PRODUCTION_ENABLED`
   (default off, `config/writers.py`) alone opens production code requests — not `TAX_ETA_PRODUCTION_ALLOWED`, which
   also unlocks invoice sending on a production-send server. The sending server is the office (writer until
   cutover), the VPS after. `refresh`, `send` and `check_codes` take an explicit system (rework of `coding.py`, not
   only a new client); the coding client has its own token and pace state, separate from `EtaReader`.
4. **A person's "code it" + ETA's approval makes the item white** (builder's call): on approval of a production
   request that came from a confirmed decision, `list_status = white`, `disposition = include` (audited). This is
   the confirmation the anti-goal requires; nothing becomes white without both.
5. **The rule reads supplier categories as strings from the live `SupplierSegmentation`** (not the copy on
   `PurchaseLine`), so today's three reassignments count. SISTER_COMPANY, INTERNAL_TRANSFER, EXTERNAL_TRANSFER,
   CLEARING, SERVICE_VENDOR, FIXED_ASSET_SUPPLIER are **ignored** like patient suppliers (not sourcing evidence);
   INDIVIDUAL_SUPPLIER counts as "other" (builder's call). The table's counts in §4.2 were computed from the live
   segmentation; they'll be re-run in S1.
6. **ETA code-usage listing is probed first** (builder's call): S1 starts with a read-only probe of
   `codetypes/requests/my` (all pages, no ItemCode filter) on production. If it does not return the hand-registered
   history, §8 falls back to per-item `code_details` checks on production, run as a background job at ETA's pace
   (biggest-selling uncoded items first, so the useful answers come early).
7. **GPC list** (builder's call): `TaxGpcBrick` gets `source` (`workbook` | `gs1-20260520`) and the GS1 definition
   fields. AI and the picker suggest only GS1-list bricks. A workbook-only brick is still accepted when a person
   picks it (with a warning), since ETA has accepted those for existing codes. Existing approved items are untouched.
8. **"Coded" in the production receipts recon = coded in the sheet** (builder's call): `coded_items()` for
   production reads the latest sheet version we hold (or the 13-Nov workbook import until the first version), not
   `eta_code`. So an ETA-approved item not yet in the sheet still shows as "no code" — which is what Invoicer does.
9. **Tax treatment from the VAT rate**: 14% → taxable 14; 0% → the sheet's own mapping (col P: 0% → `v003`, ETA's
   "exempted good or service") → **exempt**. The queue never overwrites a treatment the accountant already
   confirmed; a disagreement shows as a flag on the row instead. The exempt reference text is **the owner's**
   (open, see conversation).
10. **Code corrections to the text above:** there is no treatment-confirmation service — S1 extracts the inline
    logic from the profile-edit view (`views.py`) into `services.confirm_treatment` and both use it. The agent work
    (S5) needs: a new job model or wider `kind` (current `max_length=10`, choices document/smoke), a file-upload
    result endpoint, an agent version handshake so sheet jobs go only to an updated agent (an old agent would treat
    them as text to sign), and the agent's `handle()` dispatching by kind.
