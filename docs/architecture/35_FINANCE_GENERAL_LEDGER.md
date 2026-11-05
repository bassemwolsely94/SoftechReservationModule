# 35 — Finance General Ledger (دفتر الأستاذ العام) — Plan 1: ledger foundation

Status: ✅ Plan 1 (ledger foundation) and ✅ Plan 2 (drafting engine, see the second part of this document) BUILT
(2026-11-04). Plan 3 (close & reconcile) is planned in `docs/superpowers/plans/2026-11-04-finance-gl-close.md`.
Spec: `docs/superpowers/specs/2026-11-04-finance-general-ledger-design.md`.

Finance keeps its own double-entry ledger on its own 4-digit chart of accounts, so its Excel journal
can be replaced by entries keyed, reviewed and approved here. **No SOFTECH reads or writes** in Plan 1: `apps/finance/gl/` never imports `config.sybase`.

## Code

| File | Responsibility |
|---|---|
| `apps/finance/gl/models.py` | `GLAccountGroup`, `GLAccount`, `LedgerEntry`, `LedgerLine`, `GLSequence` (app label `finance`, re-exported from `apps/finance/models.py`); `FinancialPeriod.status` open/closing/closed |
| `apps/finance/gl/ledger.py` | the only code that changes entry state: `save_draft`, `approve`, `reverse`, `LedgerError(code, message)`; fatal audit rows |
| `apps/finance/gl/coa_import.py`, `names.py` | parse finance's trial-balance pivot → groups / accounts (`GROUP_MAP`, `BS_LINE_BY_ACCOUNT`, party types, system accounts 1390 / 5302) |
| `apps/finance/gl/opening.py` | the 1-1-2026 opening entry from the 31-12-2025 trial balance (source key `opening:2026`) |
| `apps/finance/gl/balances.py` | `trial_balance`, `account_statement` (approved + reversed lines; drafts never count) |
| `apps/finance/gl/statements.py` | `trading_and_pl`, `financial_position`, `branch_pl` (report-time HQ allocation), `comparison` |
| `apps/finance/gl/views.py`, `urls.py`, `exports.py` | REST API under `/api/finance/gl/` and Excel exports |
| `frontend/src/pages/finance/gl/*` | screens (below) |
| `apps/tests/test_gl_*.py` | tests per layer |

## Rules (deterministic)

- Money is `Decimal(18,2)`; more than 2 decimals or a negative amount is **rejected**, never rounded.
- One side per line; a draft may be unbalanced, approval needs Σdebit = Σcredit > 0.
- Approval: open period, `entry_date ≥ 2026-01-01`, active posting accounts, party / branch when the
  account demands it; number `JV-<year>-<6 digits>` from a locked `GLSequence` row (concurrent approves →
  exactly one wins, the other gets `not_draft` → HTTP 409).
- Approved entries are immutable. Corrections are reversing entries (`reverse`): an approved mirror with
  debit↔credit; the original becomes `reversed`. A reversal cannot be reversed; an entry is reversed once.
- A source key belongs to one live (draft/approved) entry (`gl_live_source_key_unique`).
- Any user with `ledger.approve` may approve, including their own entry; creator and approver are stored.
- Every save / approve / reverse / delete / account edit / import is audited (who, when, before/after).
  A confirmed chart import writes one `gl_coa_imported` row inside its transaction with the per-account
  before/after of each changed field; `updated` counts only accounts that changed.

Entry statuses (help workflow `gl_entry`): `draft` → `approved` → `reversed`.

## RBAC

Module `ledger` (الحسابات العامة). Role `accountant` (all-branch): `ledger` view, create, approve, export;
`finance` view/export, `cheques` view, `dashboard` view. `ledger.edit` (chart edits, import) and
`ledger.finalize` (period close, Plan 3) are granted by the owner in «الصلاحيات». Every GL endpoint also
refuses users who are not all-branch (`core.branch_scope.sees_everything`, security batch 5 decision B-1).
The RBAC middleware (`core/middleware/module_access.py`) maps `/api/finance/gl/` to `ledger` (not
`finance`): reads need `ledger.view`, writes any of `ledger` create / edit / approve; each view then
checks its exact action. Writes also need a staff profile (403 `no_profile` otherwise).

## API — `/api/finance/gl/`

| Method · path | Action | Notes |
|---|---|---|
| `GET groups/` | view | `[{id, name, section, order}]` |
| `GET accounts/?q=&group=&active=` | view | list, `group` nested; `q` uses the shared wildcard search |
| `PATCH accounts/{code}/` | edit | name, statement_line (known lines only), is_active, requires_branch, party_type; system accounts (1390 / 5302) cannot be deactivated or re-lined |
| `POST accounts/import/` (multipart `file`, `dry_run`) | edit | `.xlsx` only, ≤ `MAX_UPLOAD_FILE_SIZE`, ≤ `MAX_IMPORT_ROWS`; `{created, updated, unknown_groups, rows, warnings}` |
| `GET entries/?status=&book=&date_from=&date_to=&branch=&account=&q=` | view | cursor pages `{next, previous, results}`; row has `total_debit`, `created_by_name` |
| `GET entries/{id}/` | view | with `lines` |
| `POST entries/` · `PUT entries/{id}/` | create | manual books general/cash/credit (a PUT may keep a draft's own non-manual book, R15); dates before 2026-01-01 → `before_opening`; text over its column size → 400 (never truncated); PUT on non-draft → 409; `notes` (≤ 4000, omitted = unchanged) saved and audited with the draft |
| `DELETE entries/{id}/` | create | drafts only (409 otherwise); audited |
| `POST entries/{id}/approve/` · `POST entries/approve/ {ids}` | approve | bulk (≤ 500, repeated ids once) → `{results:[{id, ok, number | code, detail}]}` |
| `POST entries/{id}/reverse/ {reason, entry_date?}` | approve | returns the reversal |
| `GET reports/trial-balance/?from&to&branch&by` | view | list + `is_total` row; every row has `balance` (closing Dr − Cr), the total row `balanced` (bool) |
| `GET reports/account-statement/?code&from&to&party&branch` | view | opening, lines with running balance, closing |
| `GET reports/statements/?from&to&closing_stock` · `position/?as_of&closing_stock` · `branch-pl/?from&to` · `comparison/?years=` | view | statements / position carry `stock_basis` (entries · supplied · missing) and `warnings` (position also `unclosed_pl`); optional `closing_stock` (≥ 0, ≤ 2 dp, else 400 `bad_amount`) overrides 5302; `branch-pl` → `{columns}`; `comparison` → `[{year, empty, values, pct_of_sales}]` |

Errors: `LedgerError` → 400 `{code, detail (Arabic, with «السطر n»), extra}`; the state conflicts
`not_draft`, `not_approved`, `already_reversed`, `is_reversal`, `source_conflict` → 409. A `from` after
`to` → 400. Decimals are strings; ratios are fractions. Any report with `?format=xlsx` needs
`ledger.export` (checked before the report is computed) and returns finance's layout (RTL, Arabic headers,
`#,##0.00`, branch "code · name", server warnings «⚠ …» under the title, formulas neutralised).
`URL_FORMAT_OVERRIDE` is off, so `format` is an ordinary query parameter here.

## Screens (hub `/finance`, tabs shown only with `ledger.view`)

| Route | Page | Notes |
|---|---|---|
| `/finance/coa` | `GLAccountsPage` | tree ↔ list, search, balance to date (from the trial balance), import preview → confirm and inline edit with `ledger.edit` |
| `/finance/journal` | `JournalPage` + `EntryEditor` | drafts first, review keyboard (↑↓ Space Enter Ctrl+A), bulk approve with per-row refusals, side-panel editor, reverse with reason |
| `/finance/trial-balance` | `TrialBalancePage` | month / quarter / year / custom, branch, by account or group, Excel |
| `/finance/ledger` | `AccountStatementPage` | account + party + period, row → entry panel |
| `/finance/statements?tab=` | `StatementsPage` | trading · position (check in red when ≠ 0) · branches · comparison; print + Excel; server warnings shown |

The SOFTECH freshness bar is hidden on these routes (the ledger is not a SOFTECH mirror).

## Commands and cutover

```
python manage.py import_gl_coa <xlsx> [--sheet NAME] [--dry-run]
python manage.py import_gl_opening <xlsx> --closing-stock <confirmed figure> [--sheet NAME] [--dry-run]
python manage.py gl_reproduce_workbook <xlsx> --year 2025 --closing-stock <figure>   # rolled back; exit 1 on any difference
```

1. Finance confirms the opening-stock figure (spec §13).
2. On production: `import_gl_coa` on the 2026 trial-balance sheet → review accounts in `/finance/coa` →
   `import_gl_opening --closing-stock <confirmed>`.
3. Grant `accountant` to finance staff; grant `ledger.edit` / `ledger.finalize` to the finance manager.

---

# Plan 2 — Drafting engine (SOFTECH → draft entries)

Status: ✅ BUILT (2026-11-04). Plan: `docs/superpowers/plans/2026-11-04-finance-gl-drafting.md`.
SOFTECH activity becomes **draft** ledger entries on finance's own accounts through finance-editable,
versioned posting rules — idempotent per source document, unmatched rows parked as exceptions in the
review inbox. The engine **never approves** and **never writes to SOFTECH** (every statement is a
`SELECT` in `apps/finance/queries/sybase_gl.py`; nothing under `apps/finance/gl/` imports
`config.sybase`). Entries are created / replaced / reversed only through `ledger.py`
(`save_draft`, `reverse`).

## Flow

```
SOFTECH SELECT ──reader──▶ SourceDoc ──upsert──▶ GLSourceDoc (unique source_key + content_hash)
                                                   │ classify: new / unchanged / changed / vanished
                       PostingRule (1 per doc) ◀───┤ select_rule: conditions + priority + effective dates
                                                   ▼
        group by rule granularity (document | branch_day | party_day) ──build_lines──▶ save_draft
        accounts / branch via GLSourceMap · party via confirmed GLParty · else SourceException
```

## Code (added by Plan 2)

| File | Responsibility |
|---|---|
| `models.py` | `GLParty`, `GLSourceMap`, `PostingRule`, `GLSourceDoc`, `SourceException`, `GLDraftRun` (migrations `0021_gl_drafting`, `0022_gldraftrun_heartbeat`) |
| `sources/__init__.py` | `SourceDoc`, `READERS` registry (one reader per source type) |
| `sources/sales.py` · `purchases.py` · `treasury.py` · `expenses.py` | readers (below) |
| `queries/sybase_gl.py` | SELECT-only SQL, run through `_fetch` / `_conn_ctx` of `sybase_accounting.py` |
| `rules.py` | `SOURCE_FIELDS` (amount whitelist per source), `CONDITION_KEYS`, `validate_rule`, versioned save, `select_rule`, `build_lines`, `preview_rule` |
| `parties.py` | finance party import, name-match proposals, confirm / reject, bulk confirm from the reviewed suggestions sheet (`parse_confirm_sheet` + `bulk_confirm`, `POST parties/confirm-upload/` with `dry_run`, ledger.approve), `resolve_party` |
| `seed.py` + `seed_gl_drafting` | seed rules and maps from the verification table |
| `drafting.py` | the engine: `start_run`, `draft_range`, grouping, late changes, `system_user()` |
| `drafting_views.py` / `drafting_serializers.py` | API for parties, maps, rules, runs, exceptions, source drill-down |
| `management/commands/gl_draft.py`, `gl_check_sources.py`, `import_gl_parties.py`, `seed_gl_drafting.py` | CLI |
| `sync/freshness.py`, `sync/tasks.py` | `gl_drafting` freshness domain; 08:30 job |
| `frontend/src/pages/finance/gl/{GLPartiesPage,PostingRulesPage,RuleEditor,SourceMapsPanel,ExceptionsTab,SourcePanel}.jsx` | screens |
| `apps/tests/test_gl_{drafting_models,parties,rules,sources,drafting,seed,drafting_api}.py` | tests |

## Source verification (SOFTECH, read-only, 2026-11-04, Jan–Aug 2026 vs finance's 31-08-2026 workbook)

"✓" reproduces finance within 2 %; "≈" close, basis differs; "✗" does not reproduce (owner question).

| Source type | SOFTECH data (verified fields) | Evidence vs finance | Seed rule |
|---|---|---|---|
| `sales_tenders` | `branchesales` `branchcode, doccode (115 sale / 30 return), docdate, paymenttype, paymentvalue`; tenders used: 30 نقدي, 40 بطاقة, 60 خصم فكة (10 أجل → `credit_sales`) | cash = Σ115 − Σ30 per branch: 130 3.883M / 140 5.274M / 150 6.670M / 160 8.304M / 170 4.609M vs 6002 3.910 / 5.276 / 6.667 / 8.304 / 4.531 ✓; card 4.09M vs 6006 3.02M ✗ | Dr 1302 (branch) / Cr 6002 (branch); card Dr clearing map / Cr 6006 |
| `credit_sales` | `branchesales` paymenttype 10 (+`personcode`) joined to `stktransm` (`docvalue` net, `docvalue1` gross before customer discount, `docvalue3` tax) on `branchcode, doccode, docnumber, docdate` | net credit 24.16M vs 6003 − 6021 24.31M ✓; finance books every credit sale on HQ | Dr 1341 party / Cr 6003, both on HQ; discount pair Dr 6021 / Cr 6003 |
| HQ store sales (rule, not a reader) | tenders / credit docs with `branchcode='100'` | 589K vs 6011 438K ≈ | `sales_tenders` at 100 → Cr 6011; HQ change discount (tender 60) `sales.hq_change_discount` (priority 110 over `sales.change_discount`) Dr 6022 / Cr 6011 on HQ |
| `purchases` | `finance.APInvoice` mirror, doccode 10/120 (`branchcode, docnumber, docdate, docnumber2, doc_value, due_date, party.softech_personcode`) | all 10: 49.82M vs 5100+5104 49.49M ✓; HQ 10: 36.42M vs 5104 HQ 35.99M ✓; 120: 1.39M vs 5101+5105 3.80M ✗ | HQ: Dr 5104 / Cr 2341 party; HQ 120: Dr 2341 / Cr 5105; branch invoices: **skip** (booked at payment) |
| FOC | free lines are zero-value in purchases | no GL effect under periodic stock (spec §11a) | none — no reader |
| `supplier_payments` | `cheques` `ptcode=20`: `cheqsno, branchcode, financialdoccode (10 نقدي / 20 شيك بنكي / 90 قيد تسوية), cheqtype (10 receipt / 20 payment), cheqno, cheqdate (= due date), cheqregisterdate (= issue), bankcode, personcode, cheqvalue, chequenote` | cash from boxes 40/50/60/70/80/10: 1.49 / 1.84 / 2.36 / 4.68 / 1.68 / 1.46M vs 5100 per branch 1.53 / 1.76 / 2.33 / 4.74 / 1.64 / 1.46M ✓ | cash: Dr 5100 (box's branch) / Cr box map; cheque: Dr 2341 party / Cr 2343 (cheque no, due date) dated `cheqregisterdate` |
| `cheque_maturity` | same rows, `financialdoccode='20'`; **`cheqcashdate` is NULL on all 664 cheques of 2026** → SOFTECH never records clearing | finance's «اوراق الدفع» is by due date | Dr 2343 / Cr bank map dated `cheqdate` |
| `customer_collections` | `cheques` `ptcode=10` (`custpayments` is empty) | HQ bank 04/06 receipts 24.8M Jan–Aug | Dr bank/box map / Cr 1341 party; `financialdoccode 90` (virtual bank 05) → exception |
| `expenses` | `dailyexpenses` `branchcode, expensedate, intervalcode, day_sno, expcode, expvalue, expcomment, cheqsno` + paying box via `cheques.bankcode` of the linked voucher (**P20** link below); a row without one gets `bankcode ''` → `unmapped_account` | petty branch expenses ≈ 0.5M; code 43 «كوبون خدمة العملاء» 1.29M at HQ = item issues, not cash | Dr expense map / Cr box map, branch-day |
| `treasury_other` | `cheques` `ptcode=-1`, `personcode` −180 / −181 (box↔box / box↔bank transfer legs, `tf_branchcode / tf_bankcode / tf_cheqsno`), other ptcodes (30 موظف, 60 شريك, 70 مورد أصول, 80 شركة شقيقة) | 6 transfer rows in 2026 (36M on 2026-01-01) | transfer legs via 1320 التحويلات; everything else → exception |
| bank movements | `bankstrans` is **empty**; no bank-statement data in SOFTECH | — | none — manual entries |

Reader rules that keep one SOFTECH row in one place: `cheques` rows with `personcode='-170'` (POS takings)
are dropped — the cash is already in `sales_tenders`; `personcode='-120'` rows linked to a
`dailyexpenses` row are dropped (posted by `expenses`); an unlinked −120 row becomes a
`treasury_other` doc of kind `expense_unlinked`. **P20 — the expense↔voucher link** (both
`sql_cheques.has_expense` and the expenses reader's paying box, `sybase_gl._expense_link`): same branch,
same `cheqsno` (`CONVERT(varchar(20), …)` on both sides), `cheques.personcode = '-120'` and
`ABS(DATEDIFF(day, expensedate, cheqdate)) <= 31`; the reader re-checks the returned voucher columns
(`expense_voucher_linked`). At HQ `cheqsno` is not a voucher link and it repeats across years, so an
unbounded match dropped vouchers silently; now a non −120 voucher is never dropped and an expense with no
linked voucher is a visible `unmapped_account`. Tender docs carry `attrs.paymenttype`, so the
`paymenttype_in` rule condition works. `cheques` is read directly (not via the A/P `Payment`
mirror, which lacks `cheqregisterdate` and holds only supplier / contract-customer vouchers); one
fetch per run is memoised across the four cheques readers (P3). `gl_check_sources` compares the readers
with the A/P mirror (live check, 2026: diff 0 for all months, expenses 6802 docs, 0 duplicate keys).

## Models

| Model | Notes |
|---|---|
| `GLParty` | `party_type` supplier/customer/employee/partner/other, `code` (finance's ledger code), `softech_personcode`, `recon_party`, `status` unmapped → proposed → confirmed / rejected, `proposal_basis` exact/tokens/manual; unique (type, code); one **confirmed** party per (type, personcode). Only confirmed parties are used by the engine. |
| `GLSourceMap` | unique (`kind` bank / expense / card_clearing, `source_value`) → account + optional branch; edits write `AuditLog` before/after |
| `PostingRule` | unique (`code`, `version`); `source_type`, `conditions` (whitelisted keys), `action` post/skip, `granularity`, `lines` (JSON), `book`, `priority`, `effective_from/to`, `is_active`. **Never deleted** (`delete()` raises, no API exposes it); a save closes the previous version the day before the new one's `effective_from` |
| `GLSourceDoc` | one row per SOFTECH document: unique `source_key`, `content_hash`, `version`, `status` new / drafted / skipped / exception / vanished, `rule`, `group_key`, `entry`, `attrs` |
| `SourceException` | `kind` (below), `original_entry` + `proposed_lines` for closed-period changes, `status` open / resolved / ignored; one open exception per (doc, kind) |
| `GLDraftRun` | one run: window, source types, `counts`, `detail`, `heartbeat_at`, `status` running / success / partial / failed; **one running row at a time** (partial unique index) |

## Rules model

- Amounts come from a fixed per-source whitelist of fields (`SOURCE_FIELDS`); no expressions, no LLM
  (CLAUDE.md rule 10). Money is `Decimal`, rounded to 0.01 `ROUND_HALF_UP` exactly once, when a reader
  builds a doc's amounts. A negative computed amount moves the line to the other side; zero lines are
  dropped; an entry that does not balance is an exception, never a draft.
- Selection: rules of the doc's source type, active, `effective_from ≤ doc_date ≤ effective_to`, all
  conditions true; highest priority wins; a tie → `ambiguous_rule`; none → `no_rule`.
- Line branch modes: fixed, the doc's branch, `hq`, or `map` = the branch of the doc's bank map (the
  cash box's branch, **Ruling P14**: finance's 5100 is per box branch). A map with no branch →
  `unmapped_account` (reason «map has no branch»), never a NULL branch (**P15**); seeded bank maps
  04 / 06 / 01 carry HQ (100) — company bank accounts.
- Descriptions: placeholders render the branch display name, never the bare SOFTECH code (**P18**).
- Editing creates a version; new rules default to `effective_from` 2026-01-01, a new version of an
  existing rule to the first of the current month (**P17**). Docs before `effective_from` keep their
  entries; re-drafting touches only docs on or after it.
- `preview_rule` (the «تجربة» button, ≤ 31 days) runs the editor's rule text over a past range through
  the real readers (read-only SOFTECH) and returns entries / exceptions without saving.

## Idempotency, late changes and safeguards

- **Idempotent**: re-running a day changes nothing (`content_hash` equal → no work); `source_key` is
  unique on `GLSourceDoc`, and Plan 1's `gl_live_source_key_unique` guards the entry. Source keys: tenders
  `bs:{branch}:{date}:{paymenttype}`, credit sales `cs:{branch}:{doccode}:{docnumber}:{date}`, purchases `ap:…`,
  cheques `chq:{branch}:{cheqsno}` (maturity `chqdue:…`), expenses
  `exp:{branch}:{date}:{interval}:{day_sno}:{cheqsno}` (**P8** — the `cheqsno` part fixes 1,181 duplicate
  keys found on live 2026 data). A credit-sale doc with several personcodes becomes `unmapped_party`.
- **One run at a time**: a second start (scheduler 08:30 vs «تحديث الآن») raises `DraftBusy` → HTTP 409;
  a run whose `heartbeat_at` is older than 30 minutes may be taken over, and a run whose row is no longer
  `running` aborts as `superseded` (**P11**). The heartbeat is refreshed per group.
- **Late changes** (spec §11a), per changed or vanished doc:
  - draft entry → replaced (or deleted when the group disappears, audited `gl_entry_draft_deleted`, **P4**);
  - approved entry in a month that accepts postings → reversed (`reverse()`, source_type `reversal`) and a new draft;
  - approved entry (or live draft) in a month that does not accept postings → **one**
    `closed_period_change` exception per group (**P19**), on the group's first member (lowest
    `source_key`), with `detail.group_key`, `detail.member_source_keys`, `proposed_lines` and
    `original_entry` (approved) or `detail.entry_id` (live draft); nothing posted. The other members are
    held (status `exception`, no row of their own), retried with the group, and released when that one
    exception resolves. Plan 3 posts one correction per exception = per group;
  - **accountant edits are never overwritten (P21)**: before replacing, deleting or reversing a live entry
    the engine looks for an `AuditLog` `gl_entry_draft_saved` on it by anyone but `gl-drafting`; if found the
    entry is left alone and the group gets a `ledger_error` exception with `detail.code='edited_by_user'`,
    `entry_id`, `group_key`, `entry_status` and `proposed_lines` (the fresh rule lines) (resolves with the group);
  - **the accountant decides (P23)** on such an exception, from the inbox (`ledger.approve`, all-branch):
    «اعتماد نسخة سوفتيك» (`POST exceptions/{id}/accept-softech/`) writes `AuditLog`
    `gl_entry_edit_released` on the entry, resolves the group's `edited_by_user` rows, puts the held docs
    back to `new` and starts a redraft over the group's dates / source types (202 `{run_id}`; release and
    run start commit together, so a busy engine 409 changes nothing). P21 now counts only
    `gl_entry_draft_saved` rows **newer** (higher AuditLog id) than the latest release, so the draft is
    replaced, an approved entry in an open month is reversed + redrafted, a closed month raises
    `closed_period_change` as usual — and an edit saved after the release is protected again.
    «إبقاء تعديلي» (`POST exceptions/{id}/keep-edit/`) writes `gl_entry_edit_kept`, resolves the rows and
    relinks the held docs to the live entry as `drafted` (group_key unchanged): nothing happens until
    SOFTECH changes the group again, which asks again. Keep is refused (409) while a drafting run is
    active («الترحيل يعمل الآن»), when a doc moved to another group (date / rule change), now falls under
    a skip rule (own message), or is still linked to another live entry (moved in from an edited group
    whose row it overwrote) — any of those would count its amount twice — or when the entry is no longer
    live; a vanished doc is unlinked on keep so it never re-raises. Both need `version` = the exception's
    `proposal_version` (sha256 of the canonical `proposed_lines`, in the list JSON) the accountant saw;
    a different one is 409 «تغيّرت نسخة سوفتيك — راجعها مرة أخرى» (missing = 400). Locks follow the
    engine's order (LedgerEntry → GLSourceDoc → SourceException) and re-check after locking. The detail
    also carries `proposed_entry_date`, `proposed_description` and `held_out` (group docs held by their
    own exception, not in `proposed_lines`). Both 404 unknown / 409 not open or not `edited_by_user`;
    the audit row carries the exception id, group, source keys and the note. If the background accept run
    fails, the released docs stay `new` and wait for the next run («تحديث الآن» or the schedule) — the
    release is not undone. A recurring wrong account belongs in the rule / map, not in per-draft edits;
  - an entry deleted/reversed by hand is re-drafted as a new **draft** on the next run covering its date
    (**P9**) — never approved automatically; use «تجاهل» to silence a doc permanently.
- **Vanish guard** (**P10**): per source type per run, if the docs about to be marked vanished exceed 20 %
  of that type's previously seen docs in the window **and** 10 docs, none is marked vanished; the run is
  `partial` with `detail.vanish_guard`. A real mass deletion needs `gl_draft --allow-mass-vanish`. This
  prevents a short or empty SOFTECH read from mass-reversing approved entries.
- **System user** (**P1/P12**): drafts are created by `gl-drafting` (inactive login, unusable password,
  StaffProfile role `viewer`); `drafting.system_user()` get-or-creates it, so a test flush or production
  loss self-heals.
- An unconfirmed party affects only that doc (`unmapped_party`); the rest of the branch-day drafts.
  Seed skips (and reports in `skipped`) any rule or map whose account is missing from the chart (**P5**).

## Exception kinds

| Kind | Meaning | Fix in the UI |
|---|---|---|
| `unmapped_party` | doc's person has no confirmed `GLParty` | confirm the proposal / create a party |
| `unmapped_account` | bank / expense / card_clearing value (or a bank map without branch) has no map | map the value to account + branch |
| `no_rule` | no active rule matches | add / widen a rule (editor opens with the doc's conditions) |
| `ambiguous_rule` | two rules, same priority | change priority or conditions |
| `unbalanced_rule` | the rule's lines don't balance for the doc | fix the rule lines |
| `closed_period_change` | doc changed after its month stopped accepting postings | read-only; corrected in an open month (Plan 3 posts it) |
| `duplicate_source_key` | the same key appeared twice in one read | check the source |
| `ledger_error` | `save_draft` refused (inactive account, before opening…), or `edited_by_user` (P21) | read the message, fix, redraft; for `edited_by_user` compare «القيد بعد تعديلك» / «نسخة سوفتيك الجديدة» and choose «اعتماد نسخة سوفتيك» or «إبقاء تعديلي» (P23) |

An exception resolves itself on redraft; «تجاهل» needs a reason and keeps the doc status `exception`.

## Schedule and freshness

`apps/sync/tasks.py::_run_gl_drafting` — daily **08:30** (after the 07:30 morning chain refreshes the A/P
mirror), **OFF by default (P22)**: it returns at once (one info log per process) unless
`GL_DRAFTING_SCHEDULE_ENABLED=True` (settings via env, default `False`; listed in
`deploy/production.env.example` / `staging.env.example`). The owner flips it once the COA, opening
balances and rules are in; «تحديث الآن» works either way. When on: window = first day of the earliest open
month among (previous, current) → yesterday (`_gl_drafting_window`); a busy run is logged and skipped; a
crash marks the run `failed` with `finished_at` and `detail.error`. Draft-now and exception redraft refuse a
range starting before `OPENING_DATE` (2026-01-01) with 400. Freshness
domain `gl_drafting` («ترحيل القيود من سوفتيك», cadence 1440 min) feeds the journal's freshness bar;
«تحديث الآن» starts the same engine for a chosen range (`ledger.create`).

## API additions — `/api/finance/gl/`

| Method · path | Action | Notes |
|---|---|---|
| `GET entries/{id}/source/` | view | docs grouped into the entry, versions, rule link, attrs |
| `GET parties/?type=&status=&q=` · `POST parties/` | view · approve | list (cursor); create/confirm a party (rename audited) |
| `GET parties/persons/?type=&q=` | view | ReconParty search for the picker (wildcards) |
| `POST parties/import/` · `parties/propose/` | edit | Excel import; name-match proposals |
| `POST parties/{id}/confirm/` · `reject/` | approve | audited; a personcode already confirmed to another party is refused |
| `GET maps/` · `PUT maps/{kind}/{value}/` | view · edit | audited before/after; bank / card maps need a branch |
| `GET rules/` · `POST rules/` · `GET rules/meta/` · `GET rules/{code}/versions/` | view · edit | list, versioned save, constants for the editor (source fields, conditions, modes), history |
| `POST rules/preview/` | view | «تجربة»; computes only |
| `GET exceptions/` · `exceptions/counts/` · `exceptions/unmapped-values/` | view | server-side filters (`kind`, `status`, `source`, dates, branch); counts for the badge and chips |
| `POST exceptions/redraft/` · `exceptions/{id}/ignore/` | create | redraft selected exceptions' dates; ignore with a reason |
| `POST drafting/run/` · `GET drafting/runs/` · `drafting/runs/{id}/` | create · view | async run (409 while another is active) with progress |
| `POST exceptions/{id}/accept-softech/` · `exceptions/{id}/keep-edit/` | approve | P23 decision on an `edited_by_user` exception; accept = 202 `{run_id}`, keep = 200; audited on the entry |

RBAC (`core/middleware/module_access.py`, tested in `test_rbac_accountant`): rules / maps / party import and
propose = `ledger.edit`; party confirm / reject / create = `ledger.approve`; rule preview = view;
exceptions and drafting = `ledger.create`; the P23 accept / keep decisions = `ledger.approve`. The accountant role has no `ledger.edit` by design (spec §10).

## Screens added

| Route | Page | Notes |
|---|---|---|
| `/finance/parties` | `GLPartiesPage` | import + propose, grid with keyboard confirm (Enter) |
| `/finance/rules?code=` | `PostingRulesPage` + `RuleEditor` + `SourceMapsPanel` | rule list + side editor with «تجربة»; maps grid; entry source panel links here |
| `/finance/journal` (tabs entries · exceptions) | `JournalPage` + `ExceptionsTab` + `SourcePanel` | freshness bar with «تحديث الآن» and `ProgressBar`, source filter, exceptions grouped by kind with in-row fixes and redraft |

## Commands

```
python manage.py seed_gl_drafting                      # rules + maps from the verification table (idempotent)
python manage.py import_gl_parties <xlsx> [--propose]  # finance parties; --propose runs name matching
python manage.py gl_draft --from YYYY-MM-DD --to YYYY-MM-DD [--source TYPE]... [--dry-run] [--allow-mass-vanish]
python manage.py gl_check_sources --from … --to … [--source all]   # readers vs the A/P mirror (read-only)
```

Cutover order: import COA → `seed_gl_drafting` → import parties + propose → finance confirms parties →
maps for bank boxes / expense codes → `gl_draft --dry-run` → first real run → review drafts → approve.

## Open owner / finance questions (change seed data, not code)

Purchases split (branch invoices booked at payment vs HQ credit); cash purchase returns 5101 (3.11M, not
from SOFTECH returns); card sales (4.09M vs 3.02M; processor per branch) — card tenders stay exceptions
until answered; credit-sales presentation (6003 gross / 6021 discount vs net) and credit returns (6018
vs netting); VAT source (docvalue3 ≠ 2362 / 2363, no VAT lines seeded); cheque maturity posted on the
due date (SOFTECH never records clearing); bank movements / card settlements / box→bank deposits stay
manual (`bankstrans` empty); the 36M of 1-1-2026 transfers; expense code 43; supplier-invoice dating
basis; rule editing = `ledger.edit` (finance manager).
