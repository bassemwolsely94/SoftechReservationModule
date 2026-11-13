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
