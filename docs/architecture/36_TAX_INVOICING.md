# 36 — Tax Invoicing (`apps/tax_invoicing`)

E-invoices for finalized insurance claims and e-receipts for branch POS sales, sent to the Egyptian Tax
Authority (ETA). API prefix `/api/tax-invoicing/`, RBAC module `tax_invoicing`, route `/tax-invoicing`.

**Live sending is off.** Flags `TAX_ETA_SUBMIT_ENABLED` and `TAX_ERECEIPT_SUBMIT_ENABLED` default to False and
go through `writer_allowed`. No SOFTECH writes: e-receipt import is SELECT only.

## Boundaries

`apps/insurance` owns Motalba creation, claim selection, reconciliation and its printouts. This module owns
drafts, review, approval, numbering, payload, submission and notes. A claim shows its documents read-only at
`GET /api/insurance/claims/<id>/fiscal-status/`.

## Claim invoice flow

`draft → approved → submitting → submitted → valid | invalid`, plus `uncertain` and `rejected`.

- One original per claim: constraint `one_original_invoice_per_claim`. `internal_id` never changes.
- Approval freezes the exact JSON text (`payload_text`, `payload_hash`). Once sent, `TaxDocument.save` refuses
  changes to payload or totals.
- A blocked line blocks the document. No path uploads a subset.
- Uncertain result (timeout, 5xx, 422 duplicate): nothing is resent until `reconcile` asks ETA. "Not found" frees
  a retry only after `TAX_RECONCILE_WAIT_MINUTES`; "could not ask" changes nothing.
- After `valid`, changes are credit or debit notes linked to the original and its ETA UUID.
- Returns inside a claim: the prescription totals are negative over positive line amounts, so a line takes its prescription's sign. An item with a return becomes one ETA line, sales less returns; all source lines stay on the document. An item with more returned than sold blocks.

## Item review: three independent fields

| Field | Values | Who changes it |
|---|---|---|
| ETA coding | approved, missing, pending, rejected | `edit` |
| VAT classification | taxable, exempt, zero_rated, unclassified, with confirmation | `approve` |
| Invoice disposition | include, review, exclusion | `approve` |

The owner's whitelist and blacklist are inputs (`list_status`): blacklisted items go to `disposition=review`.
A workbook's VAT columns load as `source_vat_*` and never confirm a treatment.

## Review views

The default shows `approved` lines. `?view=all` needs `approve`, enforced on the server, and shows every line
with status and reason. Counts, totals and reconciliation are identical in both, and nothing in the payload path
reads the filter.

## Three separate fiscal requirements

| Requirement | Default until decided | Resolved by |
|---|---|---|
| Single-line ETA aggregation | Printed layout is one line; ETA gets line detail | Issuer `summary_*` rule marked validated, covering every line's treatment |
| VAT treatment | Per item, from its confirmed classification; draft held if unconfirmed | Confirmed item treatment with reference, or a `zero_vat` basis on the buyer |
| Exclusion from the official payload | Held in review; draft blocked | An active `exclusion` basis, a written reason, a reference, an accepted review |

No basis is seeded. A blacklist entry alone never removes a line.

## Item codes from ETA (EGS)

`coding.py`, tab «🔖 أكواد المصلحة». An item with no approved code blocks every document it is on. For such an item
we ask ETA to register our internal code `EG-<company tax id>-<SOFTECH item code>` under an 8-digit GPC brick, with ETA's
"Create EGS Code Usage" call (`POST /api/v1.0/codetypes/requests/codes`), and follow it with "Search my EGS code usage
requests" (`GET /api/v1.0/codetypes/requests/my?ItemCode=`).

- `TaxCodeRequest`: prepared → sending → submitted → approved | rejected; failed (ETA refused the request, or never got
  it) and uncertain (can't tell) as on documents. One open request per item (`one_open_code_request_per_item`).
- The item's coding moves only from ETA's answer: `pending` once ETA holds the request, `approved` or `rejected` on
  its decision. Each change is a `TaxAuditEvent` (`item_coding_from_eta`).
- Sending is one item per call, so each outcome is its own. An uncertain result stops the batch; "Refresh status"
  settles it. "Could not ask" changes nothing.
- Prepare/edit/cancel need `edit`; sending needs `finalize`, `TAX_ETA_CODING_ENABLED`, and a typed count.
- Not built: GS1 "Request Code Reuse" for items whose barcode is a GS1 code, and a scheduled status poll (the
  button and `coding.refresh` do it on demand).

### GPC categories and GS1 codes

- `TaxGpcBrick` holds the GPC bricks (code, English, Arabic), loaded with `manage.py load_gpc_bricks <xlsx>` from the
  owner's GPC workbook (any sheet with a `Brick Code` / `BrickCode` column). Once loaded, a code request must name a
  brick from it; before that, any 8-digit code passes.
- `gpc.suggest` shows, per uncoded item, the brick most used by our approved items of the same SOFTECH family, else
  category, else type, with its share. It is never applied by itself: preparing uses a batch brick, else the item's own,
  else the suggestion only when the person ticks "use the suggested category" after seeing it. The audit records which.
- `add_from_catalog`: active catalog items with no tax profile (new since the owner's workbook) become uncoded profiles
  (name from the catalog), so they can be offered for a code. Treatment and lists stay for the accountant.
- GS1: an uncoded item whose catalog barcode is a valid GTIN can be asked for as-is ("Request Code Reuse",
  `PUT /api/v1.0/codetypes/requests/codeusages`, `TaxCodeRequest.purpose = gs1`). ETA refuses a barcode it does not
  hold; that item then needs an EGS code. Approval sets `code_type = GS1`, `eta_code = barcode`.
- Follow-up of GS1 requests uses the same "my requests" search as EGS; confirmed on the test system before production.

### ETA history mirror

Design: `docs/superpowers/specs/2026-11-14-eta-history-mirror-design.md` (phase 1b = search-based backfill).
`eta_reader.EtaReader(system)` reads one ETA system with its own login (`TAX_ETA_READ_<SYSTEM>_*`, production = an ERP
registration made for us) and has no way to send (a test asserts its surface). ETA's packages only cover what the
requesting ERP itself submitted, so `eta_history` backfills from ETA's **search lists**: documents (sent and received)
in 30-day windows by submission date from `TAX_ETA_HISTORY_START` (2022-06-01), following continuation tokens; receipts
in one-day windows by **issue date** from `TAX_ETA_HISTORY_RECEIPTS_START` (2025-01-01 — ETA holds none earlier), 100 a
page, ETA's 3000-per-query cap → a longer window splits in halves, a single day stays `too_big`. Each window keeps ETA's
count beside ours; "no results" = loaded 0; unreachable → the window keeps its state and the reason goes to
`EtaHistoryState`. Daily top-up re-reads 30 days of documents and 35 days of receipts (Invoicer uploads late, in
bursts around the 5th–7th of the month, up to 29 days after the sale — measured 2026-11-15; a loaded window is never
asked again, so the top-up is the only way a late receipt reaches the mirror).
One round per system at a time (advisory lock); 401/403 stops the round. Jobs `eta_history_backfill` (15 min) and
`eta_history_topup` (04:30) run only for systems whose `TAX_ETA_READ_<SYSTEM>_ENABLED` is on. Progress: Settings →
«سجل المصلحة — التحميل», freshness domains `eta_history_preprod` / `eta_history_production`.
`manage.py eta_history --system production --plan --step 3 --topup --retry-failed`.

### Receipts reconciliation (SOFTECH ↔ ETA)

`eta_recon.reconcile_day` matches every SOFTECH sale (115) and return (30) of a branch-day to ETA's receipt by
(branch's tills, kind, number = docnumber, Cairo day), one outcome each (`EtaReconLine`), and lists ETA receipts with no
sale as `eta_only`. The daily job (05:15) recomputes the last 35 days (`RECENT_DAYS`, same span as the top-up). Each line
may carry a reason (`REASONS`), decided only from SOFTECH lines and ETA's copy:

| Reason | Rule |
|---|---|
| `all_uncoded` / `some_uncoded` | Missing at ETA; all / some of its items have no ETA code (Invoicer leaves those lines off, and sends no receipt with no coded line). |
| `uncoded_lines` | Amount differs by exactly the items with no ETA code (0.06 tolerance). |
| `no_channel_rule` | Missing at ETA, no uncoded item, and its SOFTECH channel (`ptclassifcode`, kept on the line as `channel`) has no decided `TaxChannelRule`. Invoicer sends cash sales only (`fatstatuscode` 30); channels sold on account (11, 17) were never sent — their mode is the owner's decision. |
| `till_silent` | Missing at ETA, no uncoded item, and the branch's tills sent under half of that day's receipt sales (an Invoicer outage: March 2025 start, 12–14 Aug and 9–13 Nov 2026). |
| `eta_other_day` | Not on its own day, but one receipt on the day before or after has the same till, kind, number and amount (0.05), and no SOFTECH sale of its own that day: a sale around midnight. It matches, and that receipt is not listed as `eta_only` on its day. |

Items with no ETA code are totalled per day (`EtaReconUncodedItem`) and ranked by value on the screen («المطابقة»), and
sales missing with no known reason are listed biggest first, with their channel, for checking by hand.

### Where a branch's sending starts

`TaxReceiptBranchConfig.send_from` is required before a branch's first receipt (`config_gaps`). ETA's test system
refused a two-day-old sale with CF313 ("issuance date time value is out of the range of submission workflow parameter"),
and sales before go-live belong to the program used before. `receipts.evaluate` holds any sale before `send_from` with
`before_start`, and `issue_next` never takes one. `set_send_from` (send permission, reason, audited) re-checks the
branch's unsent receipts; once a receipt is issued the start only moves later, so older sales are never issued after
newer ones.

### Test-only branch mapping

`TaxReceiptBranchConfig.test_env` marks a branch setup as test-system-only, for example a live branch's sales sent
through a borrowed test device (Invoicer's preprod POS at ETA branch 3, whose own SOFTECH branch 110 is closed). Each
receipt records the system it was issued for (`TaxReceipt.environment`). `receipts.env_guard` refuses a test-only setup
in any other system, and refuses a real setup while receipts issued for another system remain in the branch.
`end_test_mapping` (reason required, audited) resets those receipts to ready, and clears the device, chain and switch, so
the real device needs its own setup and chain start.

### Code check per ETA system

`coding.check_codes` asks ETA's "Get Code Details by Item Code" for each mapped code and stores the answer with the
system's name (`eta_check_env/status/at/detail`). ETA's test and production systems are separate registries, and the
server that runs the test is the live one, so a status is never trusted across systems:
- `coding_env` records which system an ETA answer set `coding_status` in ('' = the owner's workbook or a manual entry).
  `services.classify` treats a status from another system as uncoded.
- A code ETA reports missing or inactive in the system in use blocks its lines there.
- In a test system, our real EGS codes it lacks can be registered as-is (`prepare_mirror`, `TaxCodeRequest.purpose =
  mirror`). Their answers only mark the code found there; they never change the item's real coding. Never in production.
- Not built: GS1 codes missing in a system ("Request Code Reuse").

## طابور الترميز (Coding queue)

Batch S1 of production item coding. Design: `docs/superpowers/specs/2026-11-16-eta-production-coding-design.md`
(§4, §6, §8, §14). Code: `coding_rule.py` (suggestions), `coding_queue.py` (decisions), `eta_codes.py` (ETA mirror).
Nothing here sends a code to ETA; S1 only reads ETA and records the owner's decisions.

**Keep-out rule** (a pre-mark only; a person confirms every item). Sources are purchase lines (doccode 10) read with the
supplier's live `SupplierSegmentation` category. Official = `OFFICIAL_DISTRIBUTOR`, `DRUG_WAREHOUSE`, `MANUFACTURER`,
`SMALL_WAREHOUSE`. Ignored (not sourcing evidence) = `PATIENT_REPURCHASE`, `CUSTOMER_REPURCHASE`, `SISTER_COMPANY`,
`INTERNAL_TRANSFER`, `EXTERNAL_TRANSFER`, `CLEARING`, `SERVICE_VENDOR`, `FIXED_ASSET_SUPPLIER`; any other category,
including no row (`UNKNOWN`), counts as "other".

| Reason | When | Pre-mark | Note shown |
|---|---|---|---|
| `services` | Services type, non-stockable, or gifts (هدايا) | keep out | خدمة / هدية — لا تُكوَّد حالياً |
| `official` | bought from a distributor, drug warehouse or manufacturer | code | اشتُري من موزع أو مخزن أو مصنع |
| `small_warehouse_only` | official only via `SMALL_WAREHOUSE` | code | تأكد من تسجيله (هيئة الدواء / سلامة الغذاء) |
| `unofficial_only` | bought, but only from other sources | keep out | لم يُشترَ من موزع أو مخزن أو مصنع |
| `no_purchase` | no counted purchase since May 2025 | none | لا مشتريات معتبرة منذ مايو 2025 |

**VAT prefill** (`vat_prefill`). A treatment the accountant already confirmed wins and is never flagged. Otherwise the
rate is SOFTECH's `itemsalestaxp`, flagged "check this" when it is neither 0 nor 14, is 0 on Cosmetics / Others / Body
Building, or is 14 on Medicine. An item with no catalog row gets 0, flagged (`no_catalog`), so a person must look.

**Decisions** (`coding_queue.decide`, `reopen`). Needs the module's approve permission; every decision and reopen is audited
(who, when, before/after; reopen requires a reason). Deciding "code" also confirms the VAT treatment: 14 = taxable,
0 = exempt with the reference `EXEMPT_REFERENCE` (VAT law 67/2016, exemptions schedule). A decision never overwrites a
treatment the accountant already confirmed.

**ETA code-usage mirror** (`EtaCodeUsage`, `eta_codes.fetch`). `manage.py eta_code_usages --system production [--probe]`
reads `codetypes/requests/my` (read only; `--probe` fetches one page, prints its shape, writes nothing). Rows are
kept as the best per code by status rank (approved/active 3, submitted/pending 2, other 1); a partial fetch never
downgrades a row. `eta_codes.report()` buckets: on ETA but not in the sheet, in the sheet but not on ETA, and counts
(usages, active, matched, unmatched, sheet).

**GPC GS1 load.** `manage.py load_gpc_bricks --gs1-json PATH` loads the GS1 brick list (May 2026) with `source` set;
the workbook's own bricks keep `source='workbook'`. `gpc.known(code, official_only=True)` accepts only a brick from a
GS1 list, so a workbook-only brick is not treated as official.

**Reconciliation.** "Coded" in the recon (`eta_recon.coded_items`) means coded in the sheet, not merely mapped in our
records; the usage report above compares against that set.

**Per-system code requests.** Preprod never changes an item's real coding: its answers stay on the request, as `mirror`
requests already do. `coding.refresh` asks ETA only about requests of this server's own system (plus rows with no
system yet), because codes are identical across systems and another system's answer concerns a different request.

### GPC brick per item (batch S2)
Code: `gpc_learn.py` (learned bricks), `gpc_ai.py` (AI proposal), `coding_queue.py` (decide / `set_brick`).
Every brick shown is a suggestion; a person confirms it (CLAUDE.md rule 10).

**Learned sources, in order (first hit wins; `gpc_learn.learned`, constant queries).**
1. `decisions`: bricks people confirmed on `TaxCodingDecision` (`decision='code'`) for items of the same SOFTECH
   family (`Item.family_name`), counted only with at least 3 items and the top brick on at least 80% of them
   (a 60/40 family gives nothing and falls through).
2. `eta`: the brick (`parentItemCode`, kept as `EtaCodeUsage.gpc`) of approved/active ETA production codes of items of
   the same family, same 3 / 80% rule.
3. `sheet`: the item's own brick in the owner's sheet (`TaxItemProfile.gpc_code`, not '' or '0').
   `manage.py load_sheet_bricks PATH` fills it from sheet «ElRezeiky GPC Applied», column «أكواد الضرائب», only where
   empty or '0', 8 digits and `gpc.known()`; audited.
4. `medicine`: `medicine_type_name == 'Medicine'` → `10005845`.

A learned brick that is not on the loaded brick list (`gpc.known`) is dropped; while no list is loaded, all pass.

**AI proposal** (`gpc_ai`). Switch `TAX_GPC_AI_ENABLED`, default off (forced off under tests); off = the nightly job and
"ask again" do nothing and say so, the learned sources still work. Nightly job `gpc_ai_suggest` 02:30
(`SCHEDULER_JOB_GUARDS`), `manage.py suggest_bricks [--limit N] [--itemcode X]`, and «اقترح مرة أخرى» (≤20 items).
Only items with no learned brick are asked; medicines are never asked. The AI picks from a shortlist of at most 40:
the family's bricks from decisions and ETA codes (up to 15), then GS1 bricks sharing an English word with the item's
family / category / name, segments 50/51/53 first. GS1 names are English, so an item with an Arabic-only name gets the
family bricks only. The answer must be in the shortlist and `gpc.known()`; otherwise, or on malformed JSON, it is
stored as "no suggestion" with the reason, nothing raised. Only item descriptors go out (name, family, category, type,
origin, producer): no prices, no customers. Order: biggest uncoded sales first; an answered item is not asked again for
30 days; a "no answer" (provider down) is retried the next night, and a run stops after 5 no-answers in a row.

**Deciding with a brick.** "Code" needs a brick: the one the person picks (8 digits, `gpc.known()`; source `person`
when it differs from the suggestion), else the row's suggestion. Bulk "code" / accept takes a suggestion only when it
is learned or a high-confidence AI one; others are skipped «الفئة تحتاج تأكيداً». Keep-out needs no brick.
`set_brick` (`POST codes/queue/brick/`, audited `coding_brick_set`) sets or changes the brick of an item already
decided "code" without reopening; it is locked only while the item has an open (prepared / sending / submitted /
uncertain) or approved production code request, so after a rejection the brick can be fixed. Queue rows carry
`brick_confirmed`; the screen marks a "code" decision without a brick «تحتاج فئة».

## Which ETA system

`environment.py`: `TAX_ETA_ENVIRONMENT` = `preprod` or `production` picks ETA's published addresses; explicit
`TAX_ETA_API_BASE_URL` / `TAX_ETA_ID_BASE_URL` override them. Production is recognised by the addresses in use, not by the
name. Every sending call in `eta_client` passes `environment.assert_may_send()`: production also needs
`TAX_ETA_PRODUCTION_ALLOWED` (writer instance only). Owner steps: `docs/deploy/2026-11-eta-preprod-golive.md`.

## E-receipts

- Document key: `softech_branchcode + doccode + docnumber + docdate` (`one_receipt_per_softech_document`).
  `docnumber` alone repeats across dates.
- `TaxChannelRule` decides by `ptclassifcode`: receipt, covered by a claim invoice, or undecided (held, never
  dropped). Seeded from the owner's statement of 2026-11-06, unconfirmed by the accountant.
- A receipt with any unresolved line is held whole. A SOFTECH line VAT rate that differs from the confirmed rate
  also holds it.
- UUID: SHA-256 of the serialized receipt with `uuid` empty and `previousUUID` included. One chain per branch device;
  `issue_next` freezes receipts into it under the branch lock, and `submit_branch` sends in chain order.
- Returns reference the original sale. SOFTECH's `r_doccode` is mostly `0` or blank there. A return whose original
  was not issued here is held. Exclusions on receipts are not built: a blacklisted line holds the receipt.
- Secrets stay in the environment; `TaxReceiptBranchConfig` names the variables.
- **Where a device's chain starts** (`receipts.start_chain`, owner decision 2026-11-13: production reuses the POS devices
  Invoicer registered, after ETA's representative approves them). Decided once per branch, before the first receipt,
  and issuing waits for it (`config_gaps`). `chain_lookup` asks ETA's "Search Receipts" for the device's newest
  receipts (`PosSerialNumber`, newest issued first, 400 days back). *Fresh* is allowed only when ETA shows none.
  *Handover* is allowed only to the newest receipt ETA shows, which must equal the one the person reviewed, must be
  valid, and needs the confirmation that the other program stopped on that device. Undo is possible only while
  nothing is issued here. All of it is audited (`receipt_chain_started`, `receipt_chain_start_undone`).

## Signing

`signing.py` has one interface. `NotConfiguredSigner` refuses by default, `MockSigner` is for tests only and can't
reach the production host, `AgentSigner` queues jobs for the agent on the token PC
(`deploy/tax_signing_agent`, steps in `docs/deploy/2026-11-tax-signing-workstation.md`). Live sending also needs a
passed smoke test against the real token, verified on the server, with the expected thumbprint.

## Policies I proposed, for the owner to keep or change

| Policy | Where | Status |
|---|---|---|
| Second person accepts an exclusion | `services.decide_review`, switch `TaxIssuerProfile.exclusion_second_person` (on) | Open |
| EGP 1 unexplained difference blocks approval | `services.blockers` code `unreconciled`, field `reconcile_tolerance` | Open |
| Accountant gets view/create/edit/approve; sending needs `finalize`, so admin until granted | `seed_permissions.py`, migration `0002` | Uses the ERP's matrix; grant is open |
| Claim is "finalized" at status submitted or later | `services.FINALIZED_CLAIM_STATUSES` | Uses the ERP's `InsuranceClaim.LOCKED_STATUSES` |
| Exempt lines in the default view | Removed: default shows `approved` only, as specified | Closed |

## Open: real claims that do not reconcile

Measured 2026-11-07 on 119 local claims after the return fix: 115 within EGP 1. Claims 67, 48, 63 and 61 (all draft) differ by EGP 168 to 4,972 and stay blocked, showing the difference by line, until explained.

## Known limits

- Mocks stand in for ETA. No document has been accepted by ETA or its test environment. Field names `internalID`,
  `signatureType` and the receipt body shape need checking there.
- `TaxReceipt` type `r` follows the v1.2 return type name as read from the docs; confirm on the test environment.
- Permissions: migration `0002` also seeds admin rows. Without them the module counts as unseeded and `matrix_allows` fails open for every other role, because the accountant is an enforced role.
- No scheduler: import, issue, submit and reconcile are buttons until the owner turns it on.
