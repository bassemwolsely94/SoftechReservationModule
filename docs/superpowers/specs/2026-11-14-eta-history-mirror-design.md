# ETA history mirror — design (2026-11-14)

Owner request (2026-11-14): bring in what ETA already holds for ElRezeiky — from BOTH the test (pre-production) and the
live (production) ETA systems — with screens to retrieve historical documents "approved, signed and uploaded", for
cutover reconciliation and audits, reprinting, revising, and issuing credit notes / corrected invoices when issues
exist. Full history since Invoicer started (≈2022). Approach chosen: **A — local mirror + Invoicer's SOFTECH log,
reconciled three ways.**

## Why

1. **Cutover:** before we take over each branch device and the ERP from Invoicer, prove every sale and invoice Invoicer
   sent reached ETA and was accepted; find gaps, rejections, duplicates.
2. **Audit:** a searchable, durable record of what ETA holds in each system: status, dates, signature, submitter.
3. **Retrieve and reprint:** open any past invoice or receipt (ours or Invoicer's) and print it.
4. **Correct properly:** from a retrieved document, start a credit note that references it, or a corrected new
   invoice, through the existing document workflow (deterministic totals, accountant approval, audit).

## Goals

- Read-only mirror, per ETA system (`preprod`, `production`), of: e-invoices sent and received (i/c/d/ii/ei/ec/ed),
  e-receipts (s/r), and our item-code usage requests and codes.
- Full history backfill since Invoicer's first submission, resumable, inside ETA's limits; then a daily top-up and a
  per-screen refresh button (project rule: every engine-fed screen gets a forced refresh + freshness bar).
- Mirror of Invoicer's own sent log from SOFTECH (`einv_*` tables, read-only via `config/sybase.py`).
- Three-way reconciliation per document: SOFTECH sale/invoice ↔ Invoicer log ↔ ETA copy.
- Screens: browse/search/export, document detail with ETA's validation results, official PDF, reprint, and
  "start credit note / corrected invoice" from a retrieved document.

## Non-goals

- No sending of anything as part of this module. Credit notes and corrected invoices go through the existing document
  workflow and its existing gates (`TAX_ETA_SUBMIT_ENABLED`, `TAX_ETA_PRODUCTION_ALLOWED`, owner yes for the first live).
- No cancelling or rejecting documents at ETA from these screens (separate, later decision).
- No writes to SOFTECH. No change to Invoicer.

## Anti-goals (a failure even if it "works")

- A production read that can send. The production reader must be unable to call any submit/cancel/reject endpoint.
- Treating "could not ask ETA" as "ETA has nothing" (the chain-lookup lesson). Every gap must be distinguishable from
  an unfinished or failed fetch.
- Mixing systems: a preprod document must never appear as production evidence, and vice versa.
- Silent truncation: ETA package option `truncateifexceeded` must be `false`; an oversized window is split, never cut.
- Phone numbers / national IDs of buyers in logs or error text (privacy rule 4); exports through `core/export_safety.py`.

## Constraints (from ETA, verified 2026-11-14 on sdk.invoicing.eta.gov.eg)

- Documents search `GET /api/v1.0/documents/search`: window ≤ 30 days (configurable by ETA), continuation-token paging,
  newest first, `direction` Sent/Received.
- Document packages `POST /api/v1.0/documentpackages/requests` → poll package requests → get package: async, JSON/XML
  full or CSV summary, filters by dates/types/statuses/branch; oversized → 400 `OperationExceedsLimit` (with count);
  403 if ETA tagged the profile "B2B Deny ERP Document Retrieval".
- Receipt packages `POST /api/v1.0/receiptpackages/requests`: max **3000** receipts per package, filters dates, POS
  serial, branch, types; oversized → 400 `OperationExceedsLimit` with count.
- Rate limits per ERP/POS system: search docs / get doc / details / receipts search / receipt get 2 per second;
  recent 3 per second; document printout PDF **1 per 5 s**; my code usage requests 1 per 5 s; published codes 1 per 10 s.
  429 carries Retry-After; 503 → retry after 1–3 s. (We already hit 429 on code requests.)
- Volume estimate: ~6 branches × ~120 receipts/day ≈ 700/day → a 3000 package ≈ 4 days → ≈ 300 receipt packages for
  ~3.5 years. Invoices are far fewer (claims, B2B).
- Credentials: the test system uses the laptop's preprod ERP client (already set). **Production uses a new ERP
  registration for us** (owner decision), typed into the office server's `.env`. Receipt reads by package should work with the ERP
  token (to be confirmed on preprod first); if ETA requires POS tokens, per-device production secrets are needed.
- One server talks to one ETA system for **sending** (`environment.py`). Reading both requires per-system read clients,
  separate from the sending client.

## Approaches considered

- **A (chosen):** local mirror per system via packages (backfill) + search/recent (top-up), Invoicer's SOFTECH log
  mirrored, three-way reconciliation. Most to build; the only one that answers "is everything accepted?" completely
  and keeps working when ETA is slow or rate-limiting.
- B: search ETA live, store only what is opened. Light, but full-history reconciliation is impossible under ETA's
  limits and every screen depends on ETA being up.
- C: Invoicer's SOFTECH log first, ETA checked per document. Fast, but blind to what Invoicer didn't send (supplier
  invoices to us, portal-issued documents) and to ETA's verdict until someone looks.

## Owner decisions (2026-11-14)

- **Production reads use a new ERP registration made for us** on the production portal — never Invoicer's login, so
  our backfill never spends the rate allowance Invoicer sends live sales with. Its client ID + secret are typed by the
  owner into the reading server's `.env`.
- **Where the mirror lives:** the test system's history on the laptop (already the preprod server); **production history
  on the office server for now**. At cutover to the LDC VPS the production mirror moves with the database or is
  re-imported there (packages make a re-import cheap); the office `.env` gap noted for the cutover (placeholder
  SECRET_KEY, no OMNI key) does not affect this mirror, which stores no encrypted secrets.
- A host may **read** a system it does not **send** to: the office keeps its sending configuration as it is, and gains
  only the production read client.

## Design

### Reading both systems

- New `apps/tax_invoicing/eta_reader.py`: a read-only client built per system name (`preprod` / `production`), with its
  own base URLs (from `environment.ENVIRONMENTS`), its own ERP client ID/secret settings
  (`TAX_ETA_READ_<SYSTEM>_CLIENT_ID` / `_CLIENT_SECRET`, env only, never DB), its own token cache, and only GET calls plus
  the two package-request POSTs. It must not import or call any submit/cancel/reject function; a test asserts its
  public surface. A switch per system, `TAX_ETA_READ_PREPROD_ENABLED` / `TAX_ETA_READ_PRODUCTION_ENABLED`
  (default OFF, `config/writers.py`-style flag but read-only), gates the jobs.
- Throttle: one shared limiter per (system, endpoint family) honouring the published limits and Retry-After.

### Mirror models (company-level data; who may see it: `tax_invoicing` VIEWER; branch-scoped lists filter by
`branchNumber`→our branch mapping where present)

- `EtaMirrorDocument`: system, uuid (unique per system), submission_uuid, internal_id, type (i/c/d/…), version,
  direction (sent/received), issuer RIN/name/branch, receiver type/id/name (id masked in lists), issued_at,
  received_at, status (valid/invalid/rejected/cancelled/submitted), totals (net, tax, total), currency,
  references (for c/d), raw JSON (compressed, from package "full" or Get Document), validation steps (from details,
  fetched on demand), fetched_at, source (package/search/recent/detail).
- `EtaMirrorReceipt`: system, uuid, submission_uuid, previous_uuid, receipt_number, pos_serial, branch_number,
  issued_at, type (s/r), status, totals, buyer type, raw JSON, fetched_at.
- `EtaMirrorLine` only if the screens need item-level search (decide in phase 2; raw JSON may suffice).
- `EtaMirrorRun` / `EtaMirrorWindow`: per (system, kind, window) state — planned / requested / ready / loaded / failed
  / too_big (then split) — with counts from ETA and loaded counts, so "unfinished" is always visible.
- `InvoicerLogRow`: mirror of SOFTECH `einv_transm` (+ status/uuid tables) — branch, doc keys, uuid, submit status,
  dates — read-only, idempotent upsert.
- Code requests/codes: extend the existing `TaxCodeRequest`/check data with a per-system listing of "my code usage
  requests" (1 per 5 s) rather than a new mirror, unless phase 1 shows otherwise.

### Backfill and top-up

- Backfill walks windows from Invoicer's first month to today, per system and kind. Receipt windows start at 4 days and
  halve on `OperationExceedsLimit` (the error carries the count, so the split can be computed). Invoice windows start
  at 30 days. Packages are requested, polled, downloaded, parsed, upserted (idempotent on system+uuid).
- Top-up: daily job over the last 3 days via recent/search (cheap), plus the refresh button per screen.
- Scheduler: new jobs registered with `SCHEDULER_JOB_GUARDS`, started via `core.threads.start_thread`; one run per
  (system, kind) at a time.
- Freshness: a `tax_eta_history` domain on the existing `/api/sync/freshness/` bar, per system.

### Reconciliation (phase 3)

Per SOFTECH document (receipt doccode 115/30 per branch/day; invoices from claims/documents): match to Invoicer log by
branch+doc keys, and to ETA by uuid (and by internal ID / receipt number where uuid is missing). Outcomes: matched-valid,
matched-not-valid (invalid/rejected/cancelled), sent-but-missing-at-ETA, at-ETA-but-not-in-Invoicer-log,
not-sent, duplicate. Results stored per run with counts; drill-down lists; export.

### Screens (new tab «🗂️ سجل المصلحة» in Tax invoicing; help + `useHelpTab`)

- System switch (التجريبية / الفعلية) always visible; nothing mixes systems.
- Browse: invoices / receipts / codes; filters date, branch, type, direction, status, counterparty, amount; sortable,
  keyboard grid; export.
- Detail: header, lines, ETA status and validation steps, signature presence, previous/next receipt in chain;
  **Official PDF** (Get Document Printout, invoices; on demand, cached) and **our reprint** layout (receipts and
  invoices); **Start credit note** / **Start corrected invoice** (phase 4).
- Backfill progress: per system and kind, windows done / pending / too big / failed, with counts.
- Reconciliation (phase 3): summary tiles and drill-down.

### Credit notes and corrected invoices (phase 4)

From a mirrored, Valid, Sent invoice: create a draft `TaxDocument` of type c (or a new i) prefilled from the mirrored
raw JSON, with `references=[original uuid]`, then the normal review → approve → submit path. Totals come from the
existing deterministic engine, not from the mirror. Receipts: return receipt (r) referencing the original receipt uuid
via the existing receipts flow. Stop and ask before building: this touches document creation and submission.

### Security definition of done

API prefix stays `/api/tax-invoicing/` (already mapped); VIEWER for reads, EDITOR for refresh/backfill start,
SENDER/APPROVER unchanged for phase 4. No secret or buyer ID in logs/errors (`core/errors.public_error`). Exports via
`core/export_safety.py`. Not a SOFTECH write (read-only), so no write-manifest entry. Tests per phase, including the
"reader cannot send" surface test and "unfinished ≠ empty" tests.

## Phase 1b — backfill from search, not packages (proof run 2026-11-14, owner: "Yes, rebuild it")

Read-only probes on production (our own ERP registration) showed:
- Document and receipt **packages** answer "Sorry, Your Criteria does not return any results" for periods that hold
  hundreds of documents — they appear to cover only what the requesting ERP itself submitted (Invoicer submitted
  everything). Packages are not used for backfill.
- **Documents search** sees all of the company's invoices (sent and received) back to at least 2022-06; 30-day windows,
  continuation tokens.
- **Receipts search** sees all receipts: 357,163 in total, **only from 2025-01-01** (none before), ≤ 3000 per query
  (30 pages of 100). Invoicer uploads receipts late and in bursts (a received day can be 0 or several thousand),
  while issue dates spread evenly (~600 a day), so windows go by **DateTimeIssued** and the top-up re-reads 14 days.
- Real field names: documents `uuid, submissionUUID, internalId, typeName ('I'), typeVersionName, issuerId, issuerName,
  receiverId, receiverName, receiverType, dateTimeIssued, dateTimeReceived, status, netAmount, totalSales,
  totalDiscount, total`; receipts flat `uuid, submissionUuid, receiptNumber, posSerialNumber, dateTimeIssued,
  dateTimeReceived, totalAmount, status, typeName, issuerId, submitterName, direction`.

So: documents from `TAX_ETA_HISTORY_START` (2022-06-01) in 30-day windows by submission date; receipts from
`TAX_ETA_HISTORY_RECEIPTS_START` (2025-01-01) in 1-day windows by issue date, split when ETA reports more than 3000.
A window is fetched completely in one round (all pages) and loaded with ETA's own count beside ours; "no results"
(404 NoResult) is a loaded window with 0. Everything else from phase 1 stands (states, lock, round record, top-up).

## Phases (one PR each)

1. Reader (both systems, read-only surface), mirror models, window/run tracking, package backfill + top-up, refresh,
   freshness. Proven on preprod first, then production read once the owner types the production read credentials.
2. Screens: browse, detail, official PDF, reprint, export, backfill progress.
3. Invoicer SOFTECH log mirror + three-way reconciliation screens.
4. Credit note / corrected invoice / return receipt from a retrieved document (stop-and-ask gate).

## Settled later (by phase)

- Phase 1: whether receipt packages accept the ERP token — try on the test system; if ETA wants POS tokens, ask the
  owner before using any device secret (Invoicer's registered devices).
- Phase 3: the set of SOFTECH documents that should have reached ETA, per kind and per branch start date (returns,
  closed branch 110, invoices from claims vs B2B doccodes), and where Invoicer's `einv_*` log tables live (HQ only or
  every node) — proposed to the owner at the start of phase 3.

## Left to the builder

- Exact JSON shapes of package contents and receipt package fields (confirm on preprod; write fixtures from real
  responses with personal data removed).
- Whether receipt packages accept the ERP token (try preprod first; fall back to POS tokens per device).
- Storage format for raw JSON (JSONField vs compressed bytes) — pick by measured size after the first month.
- Mapping ETA branchNumber → our branch codes for branch scoping (ETA 0..7 vs SOFTECH 100..220 — needs a small mapping
  table; ETA 3 = 110 closed branch).
