# 35 — Finance General Ledger (دفتر الأستاذ العام) — Plan 1: ledger foundation

Status: ✅ Plan 1 (ledger foundation), ✅ Plan 2 (drafting engine, second part of this document) and ✅ Plan 3 (close and
reconcile, third part) BUILT. Plan 3 BUILT 2026-11-07 on `claude/finance-gl-close`; plan:
`docs/superpowers/plans/2026-11-04-finance-gl-close.md`. Not yet done: finance's 2026 journal file for the importer (see the open questions at the end).
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
    exception resolves. Plan 3 (`gl/corrections.py`, `POST corrections/from-exception/`) posts one correction per exception = per group;
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
| `unmapped_account` | bank / expense / card_clearing / intercompany value (or a bank map without branch) has no map | map the value to account + branch |
| `no_rule` | no active rule matches | add / widen a rule (editor opens with the doc's conditions) |
| `ambiguous_rule` | two rules, same priority | change priority or conditions |
| `unbalanced_rule` | the rule's lines don't balance for the doc | fix the rule lines |
| `closed_period_change` | doc changed after its month stopped accepting postings | corrected from the inbox by a late correction drafted into the first open month (`corrections/from-exception/`, one per exception = per group; a brand-new document is drafted whole, dated that month), see Plan 3 |
| `duplicate_source_key` | the same key appeared twice in one read | check the source |
| `ledger_error` | `save_draft` refused (inactive account, before opening…), or `edited_by_user` (P21) | read the message, fix, redraft; for `edited_by_user` compare «القيد بعد تعديلك» / «نسخة سوفتيك الجديدة» and choose «اعتماد نسخة سوفتيك» or «إبقاء تعديلي» (P23) |
| `mixed_manual_entry` | a group of finance's journal (Plan 3 importer) on both manual and SOFTECH-fed accounts; `source_type='manual_import'`, no SOFTECH reader | parked, blocks the month's close: `import_gl_manual_entries --include-mixed KEY` imports it with all its lines (resolved in the same transaction), or «تجاهل» with a reason. `exceptions/redraft/` leaves it alone |

An exception resolves itself on redraft; «تجاهل» needs a reason and keeps the doc status `exception`.

### Finance's manual-only entries (Plan 3, Task 8)

`gl/manual_import.py` + `import_gl_manual_entries <xlsx> [--sheet NAME] [--book cash|credit] [--preview] [--include-mixed KEY ...] [--user USERNAME]`. Built on the 2020 layout; finance's 2026 journal is the input still needed (a renamed header is one more alias in `_COLUMNS`).

- **Header** found by labels with `normalize_ar`, in the first sheet holding them. **Book**: the «اليومية» column, else `--book`, else the file name, else `book_required`.
- **Rows**: «Nothing» / zero rows are counted (`skipped_zero`). Reported with their row number, never guessed: `no_date`, `no_account`, `bad_amount` (negative, text, or more than 2 decimals), `both_sides`, `bad_condition`, `nothing_with_amount` (condition «Nothing» with a figure), `party_too_long`, `cheque_too_long` (over 40 characters: never cut), `bad_book`, `no_book`. A float within 1e-6 of 2 decimals is Excel's noise and is taken. A group that lost a reported row is never treated as balanced.
- **Groups**: (date, book, resolved branch, description); fallback for returns and discounts on 5101/5102/5105/5106/5121/5122/2341, merged per (date, book, branch) when the union balances (`merged_by='date_branch'`).
- **Status**, first match wins: `before_opening` → `unknown_account` (missing, inactive or non-posting) → `softech` (no manual line) → `unknown_branch` → `unbalanced` → `changed_since_import` → `mixed` → `manual`, then `possible_duplicate` below. Only `manual` is imported on its own. `GLAccount.feed` decides, and `auto` = SOFTECH-fed when an active posting rule line or a source map names the account. `both` is not a manual line.
- **Finance's manual account sets**: SystemSetting `gl_import_manual_account_sets`, default `[["1301","1302"],["1302","2404"],["1301","2405"],["1301","2406"],["1301","2408"],["1301","2413"],["1301","2417"]]`; finance owns this list. A group whose accounts (link accounts aside) fit inside one listed set is `manual` whatever the feeds say: mapped boxes, but daily handovers and 1302↔1301 are not in SOFTECH and finance keys them. `softech` groups are summarised by account set with counts and totals (`softech_summary`), so finance sees what is dropped. `party_missing` counts importable lines approval would refuse.
- **`possible_duplicate`**: a group `manual` only through that list, when a live entry from any other source (reversal mirrors aside) exists on the same date and branch (the entry's or a line's) with the same debit and credit on each of the group's accounts, link accounts aside: the engine may already have drafted that transfer from a SOFTECH voucher (P24). Not imported; reported with the other entry's id and number. `--include-mixed KEY` imports it anyway. One query per preview, over the file's date range and those accounts.
- **Link accounts**: SystemSetting `gl_import_link_accounts` (default `["2354"]`). Their lines never decide a status and stay on the entry; preview reports debit / credit / net, and warns on a non-zero net in a file holding both books. A SOFTECH line beside a link line is `softech`, so that side of the cross-book entry is skipped.
- **Branches**: `resolve_branch(name, code)`: name match, then SystemSetting `gl_branch_aliases` added to finance's six names.
- **Idempotent**: `source_key='manual_import:' + sha1(date|book|branch|sorted lines)[:20] + ':' + sha1(date|book|branch|description)[:12]` with the resolved branch, and the description is part of each line. Plan 1's live-source-key constraint makes a re-import `already_imported`; a parked group is raised once. The last part is the group's identity (for a merged group: date, book, branch), read back from the key so an accountant's edit of the draft doesn't hide it. A live import with the same identity under another key makes the group `changed_since_import`: not imported, reported with the existing entry's id and number; the accountant reverses or deletes the old entry, then re-imports. Drafts only; audited `gl_manual_import`, `gl_manual_entry_parked`, `gl_manual_exception_resolved`.

## Journal gaps from finance's 2020 cash book (2026-11-05, Rulings P24–P26)

- **P24 — inter-company cash transfers.** The treasury reader classifies SOFTECH transfer vouchers
  (`personcode` -180 box↔box, -181 box↔bank) by their other side, with `source_key` unchanged
  (`sources/treasury.py::_transfer_kinds`). The kind never depends on the drafted range, so a voucher
  keeps its kind (and entry) whichever window drafts it. `attrs.counterpart_branch` is set on transfer
  vouchers only (other cheques keep their content hash).
  - -180 box↔box: counterpart branch = the voucher's own `tf_branchcode` (when it is another branch),
    else the one branch whose leg points back at it (`tf_branchcode` / `tf_cheqsno`) — first in the
    fetch, then, for an HQ leg, by one extra read-only SELECT over `cheques` with no range bound (±31 days of the leg, P30)
    (`sybase_gl.sql_transfer_legs_pointing_at`, ints and constants only; **P28**). HQ on either side →
    `transfer_branch`; branch↔branch → `transfer_b2b` (**P29**, exception); an HQ leg still unpaired or
    ambiguous → `transfer_unpaired` (**P28**, exception — never the 1320 suspense); a branch leg with no
    counterpart stays `transfer`.
  - -181 box↔bank (**P27**, decided from the row alone): the leg whose own `bankcode` is a bank
    (`banks.banktype` 1) is `transfer_bank_mirror` and the skip rule `treasury.box_bank_mirror` drops it;
    the box leg (banktype 0) with `tf_bankcode` is `transfer_bank` and posts box vs bank(`tf_bankcode`) —
    also when it is alone. A -181 without `tf_bankcode` stays `transfer`.
  - **P30**: the other leg counts only when its `cheqdate` is within ±31 days (cheqsno repeats across
    years), in the fetch and in the SELECT (`DATEDIFF`, re-checked in Python). A bank-side row is the
    mirror only when its box partner exists — the bank row points at it (live 100/16119 → 100/16118;
    the box leg has no `tf_cheqsno`): same branch, partner `cheqsno` = its `tf_cheqsno`, partner
    `bankcode` = its `tf_bankcode`, partner `tf_bankcode` = its `bankcode`, ±31 days — — in the fetch or by one read-only SELECT (`sql_bank_transfer_partners`);
    otherwise it is `transfer_unpaired` (exception), never a silent skip.
  - **P31**: -181 legs are classified by both banktypes — own `banktype` and `tf_type` (banktype of
    `tf_bankcode`, outer join `c.tf_bankcode *= tb.bankcode` in `sql_cheques`). box(0)→bank(1) =
    `transfer_bank`; bank(1)→box(0) = mirror only if its partner exists and is itself a box (banktype 0,
    checked in the fetch and joined in `sql_bank_transfer_partners`). Same-type pairs (box↔box,
    bank↔bank — 5 and 24 rows in 2019–2021) and an unknown tf type are `transfer_unpaired`, so they
    never post zero times or twice. The parties import message shows the skipped master-sheet rows.
  - `transfer` otherwise (unchanged: `treasury.transfer_in/out` via suspense 1320).
  New map kind `intercompany` (SOFTECH branch code → finance's sister-company account, branch = HQ; the
  map PUT needs a branch) and map keys `counterpart_branch` / `tf_bankcode` (migration 0023 changes only
  the choices). Seeded (priority 120, all `financialdoc_in ['10']` so the 1-1-2026 «قيد تسوية» vouchers,
  financialdoc 90, stay `no_rule` exceptions):
  | Rule | Kind / branch / direction | Lines |
  |---|---|---|
  | `treasury.branch_transfer_out` | transfer_branch, not 100, payment | Dr 2404 (doc branch) / Cr box map |
  | `treasury.branch_transfer_in` | transfer_branch, not 100, receipt | Dr box map / Cr 2404 (doc branch) |
  | `treasury.hq_transfer_out` | transfer_branch, 100, payment | Dr intercompany by counterpart (HQ) / Cr box map |
  | `treasury.hq_transfer_in` | transfer_branch, 100, receipt | Dr box map / Cr intercompany by counterpart (HQ) |
  | `treasury.box_bank_in` / `_out` | transfer_bank, receipt / payment | Dr box / Cr bank map by `tf_bankcode` (and reverse) |
  | `treasury.box_bank_mirror` | transfer_bank_mirror (financialdoc 10) | skip |

  `transfer_unpaired` and `transfer_b2b` have no rule on purpose (`no_rule` exceptions). Map rows and the
  exceptions fix keyed by a branch code (intercompany, card clearing) show «code · name».
  Intercompany maps: 130→2408 علياء, 140→2413 الجيزة, 150→2405 عين شمس, 160→2406 باب الحديد, 170→2417 محسن
  (missing accounts skipped and reported, P5). 2404 «شركات شقيقة شركة الرزيقى لادارة الصيدليات» is the
  branch-side account, as in finance's cash book.
- **P25 — cash purchases through 2341.** `supplier.cash` (branch_day) now has four lines: Dr 5100 (box
  branch) / Cr 2341 (party, box branch) / Dr 2341 (party, box branch) / Cr box map, so the 2341
  sub-ledger lists every cash supplier like finance's two-leg booking. 2341 lines aggregate per party
  (one pair per supplier per branch-day) with «مشتريات نقدية {party} {note}» — new placeholder `{note}` =
  the voucher note (usually the invoice no.; of the party's first voucher that day); every rendered line
  description is capped at 500 characters. An unconfirmed supplier → `unmapped_party` for that voucher
  only. **The seed is create-only**: a database seeded before this batch keeps the old two-line
  `supplier.cash` (and gets the new transfer rules / maps on the next `seed_gl_drafting`) until finance
  edits the rule in «قواعد الترحيل» (production is not seeded yet).
- **P26 — party import from the 2020 master sheets.** `parse_party_sheets` also reads finance's master
  sheets by their (code, name) header pair, normalised (`normalize_ar`, trailing spaces ignored):
  «الكود» + «اسم المورد» → supplier, «كود الموظف» + «Name in Arabic» → employee, «كود العميل» +
  «اسم العميل» → customer (same code / name guards). `import_parties(create_only=True)` /
  `import_gl_parties <xlsx> --create-only [--propose]` only adds missing codes and never renames or
  touches an existing party — the 2026 sub-ledger names stay authoritative. Master-sheet rows are
  imported **only** in create-only mode; the default mode (and the «استيراد» button) skips them and
  reports `master_skipped` / `master_sheets` (command: «skipped N master-sheet rows …»). Master rows are
  deduplicated separately, so a skipped master sheet never hides a sub-ledger row.

### Not drafted from SOFTECH (finance keeps booking these by hand)

- Daily branch→HQ cash handovers and 1302↔1301 transfers — not in SOFTECH (branch boxes are never emptied there).
- Shift over / short (1303) — SOFTECH `pos_shiftclosing` exists, but no deterministic formula reproduces finance's 1303.
- Coupons (2354) — in 2026 expense code 43 is HQ store issues (doccode 170, 400 each), not cash; the account is finance's call.
- Card settlement 1327 / 1329 → bank — SOFTECH has no settlement data.

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
| `GET maps/` · `PUT maps/{kind}/{value}/` | view · edit | audited before/after; bank / card / intercompany maps need a branch |
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
python manage.py import_gl_parties <xlsx> [--create-only] [--propose]  # finance parties (P26); --propose runs name matching
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
due date (SOFTECH never records clearing); bank movements / card settlements stay manual (`bankstrans`
empty; box↔bank transfer vouchers are drafted since P24); the 36M of 1-1-2026 transfers (financialdoc 90,
left as exceptions by P24); expense code 43; supplier-invoice dating
basis; rule editing = `ledger.edit` (finance manager).

---

# Plan 3 — Close and reconcile

Status: ✅ BUILT (2026-11-07), branch `claude/finance-gl-close`. Plan: `docs/superpowers/plans/2026-11-04-finance-gl-close.md`
(migrations `0024_gl_close`, `0025_gl_compare_checks_seed`, `0026_period_closing_started_at`, `0027_gl_mixed_manual_entry`).
Finance closes a month on the ledger (checklist, SOFTECH closing stock, auto-reversal, reopen), closes the year, sees
sub-ledgers and ledger-vs-SOFTECH differences, pushes late SOFTECH changes into the first open month, and cuts over by
importing its manual-only journal and validating against its workbook. SOFTECH is **read only**: two modules
(`softech_stock.py`, `softech_checks.py`) call SELECT-only functions in `queries/sybase_gl.py`; nothing under
`apps/finance/gl/` imports `config.sybase`. Every entry goes through `ledger.py` (`save_draft`, `approve`, `reverse`).

## Code (added by Plan 3)

| File | Responsibility |
|---|---|
| `gl/close_models.py` | `ClosingStockSnapshot`, `ClosingStockStore`, `GLSoftechCheck`, `GLComparisonLine` (the check is the field `softech_check`, related name `lines`: `check` clashes with `Model.check()`) |
| `gl/periods.py` | `month_period`, `previous_month`, `next_month`, `accepts_postings`, `first_open_period_after`, `OPENING_DATE` |
| `gl/close.py` | `checklist`, `begin_close`, `close_month`, `run_close`, `reopen_month`, `year_end_close`, `CloseError`; constants `CLOSING_TAKEOVER` (30 min), `DEFAULT_REOPEN_WINDOW` (3) |
| `gl/softech_stock.py` | `store_map`, `valuation(as_of)`, `expected_stores`, snapshot carry-forward; reads `storebal_date` |
| `gl/softech_checks.py` | per-source SOFTECH figures and drill-down: `SOURCES` = sales, purchases, stock_at_cost, expenses, supplier_balance |
| `gl/compare.py` | `compute`, `refresh` (advisory lock `REFRESH_LOCK`, `RefreshBusy`), `explain`, `is_stale`, `detail` |
| `gl/corrections.py` | `effective_lines`, `post_late_correction`, `post_late_document` |
| `gl/subledgers.py` | `SUBLEDGERS`, `subledger`, `supplier_vs_ap` |
| `gl/manual_import.py`, `gl/validation.py` | finance's journal import and the workbook validation (importer rules are in Plan 2's part) |
| `gl/plan2_adapter.py` | the only Plan 3 module that touches Plan 2 models (`open_exception_count`, `closed_period_change`, `mark_exception_resolved`, `last_draft_run_through`) |
| `gl/close_views.py`, `close_serializers.py` | API (below) |
| `frontend/src/pages/finance/gl/{PeriodClosePage,SubledgersPage,SoftechComparePage}.jsx` | screens |
| `apps/sync/tasks.py::_run_gl_compare_refresh` | nightly comparison |
| `apps/tests/test_gl_{close_models,corrections,softech_stock,compare,subledgers,close,year_end,manual_import,validation,close_api,compare_job}.py` | tests |

Other model changes: `FinancialPeriod` gains `closing_started_at` and `closing_stock` (FK to the snapshot);
`LedgerEntry.corrects` (FK to self) points a correction, or the mirror of a late reversal, at the closed-month entry it
corrects; `GLAccount.feed` (`auto|softech|manual|both`).

## Close flow

A month closes in three steps so the slow SOFTECH read holds no database lock (`gl/close.py`):

1. **One transaction**: the month is `open`, its database checklist items pass, status becomes `closing` and
   `closing_started_at` is this run's token. From now on an approval into the month is refused with `period_closing` (409).
2. **No transaction**: SOFTECH's stock at the month-end date (`softech_stock.valuation`).
3. **One transaction** (all of it or none): the items are checked again (a draft may have landed meanwhile), the
   snapshot is saved, the closing-stock entry is posted and approved, its auto-reversal is dated the 1st of the next month, and
   the month becomes `closed`. In **December** the auto-reversal is replaced by the year-end close (below), in the same transaction.

Any failure in step 2 or 3 returns the month to `open` with nothing of step 3 left, audited as `gl_period_close_failed`.
Audit rows: `gl_period_closing`, `gl_period_closed`, `gl_period_close_takeover`, `gl_period_reopened`.

- **Checklist** (`close.checklist`), in this order: `previous_closed`, `no_drafts`, `no_exceptions` (open Plan 2 exceptions in the
  month, including parked `mixed_manual_entry`), `comparison_fresh`, `comparison_explained` (only checks with `blocks_close`),
  `suppliers_explained` (never blocks), `drafting_ran` (never blocks, tells when drafting last covered the whole month), and `stock_snapshot`
  (the SOFTECH read; a failed read fails only that item). Months close in order from January 2026, so closed months are always one
  unbroken run and an open month never has a closed month after it.
- **Stuck close.** A run killed mid-way (a restart) leaves the month in `closing`. After `CLOSING_TAKEOVER` (30 minutes) a new
  close takes it over (audited); before that it answers `close_running`. A run that was only slow finds its token gone at step 3
  and stops with `superseded`, posting nothing. A takeover whose items do not pass returns the month to `open`.
- **Reopen** (`reopen_month`, `ledger.finalize`, reason required): allowed for the last `gl_reopen_window_months` (default 3)
  closed months and **cascades**: every later closed month reopens with it, in one transaction, and each month's close entries
  (closing stock, its reversal, and for December the year-end entries) are reversed by the close service. The months are then
  closed again one by one, in order. A reopen refuses while a later month is `closing`, or when the month after the last one is not open.
- Errors (`CloseError.code`): `not_open`, `checklist`, `outside_window`, `not_closed`, `snapshot_missing`, `reason_required`,
  `close_running`, `superseded`, `next_not_open`, `unknown_branch`, `year_end_account`. Conflicts (409): `not_open`, `close_running`, `superseded`, `next_not_open`; the rest are 400.

## Closing stock

Value = SOFTECH's own stock-at-date snapshot (`storebal_date`) for the exact month-end, `nowqty × nowcostprice`, signed, summed per store
and rounded once per store to 2 decimals (ROUND_HALF_UP). This reproduces finance's 31-12-2025 closing stock of 8,739,116.86 to the piastre.
Entry per branch: **Dr 1390 / Cr 5302** on the included stores' total. The ledger takes positive amounts only, so a branch whose
stock nets negative has the sides flipped; a branch at exactly zero posts no line.

- **Store map** (`softech_stock.store_map`): store code = branch code when a `Branch` has that `softech_branch_id`; HQ stores
  `100 101 102 103 104 105 110` → branch 100; store `152` → branch 150. A store is included unless its role is `closed`
  (`apps.batches.store_roles.resolver`, e.g. 110, 120).
- **Quarantine stores are included** (owner, 2026-11-04): closing stock is an accounting figure; it does not make those stores available
  for sale. This is a GL-only rule; FEFO, replenishment and every operational stock number still exclude quarantine.
- Per-store overrides: SystemSetting `gl_closing_stock_stores`, JSON `{store: {"branch": "150", "included": true}}`; invalid entries are
  logged and ignored; edited through `PATCH closing-stock-stores/` (`ledger.edit`, audited `gl_closing_stock_stores_updated`). A branch we do not have is refused.
- **Missing snapshots.** From the November 2026 month-end finance runs SOFTECH's stock-at-date report every month-end, and a store with no snapshot
  that normally reports blocks the close (`stock_snapshot`, `snapshot_missing`). For month-ends up to `gl_stock_carry_forward_until`
  (default 2026-10-31) such a store takes its latest earlier snapshot, shown as carried («محمول من <date>»); quarters stay exact, the monthly
  split inside a quarter shows the whole stock change in the month that has a snapshot.
- Note on 2409 per branch: the 2026 opening-stock line carries no branch, so the per-branch 2409 figure of 2026 is not a meaningful branch result.

## Comparison checks (ledger vs SOFTECH)

`GLSoftechCheck` rows say what to compare; `GLComparisonLine` holds one figure per (period, check, branch, party): ledger amount,
SOFTECH amount, difference, and finance's explanation. `needs_explanation` = difference over the check's `tolerance` (default 1.00)
and no explanation, or an explanation written against a different difference (a change re-opens it). Seeded checks (migration 0025):
`sales`, `purchases`, `stock_at_cost` (balance, 1390), `expenses`, `supplier_balance` (balance, 2341, per party). **All five seed with
`blocks_close=False`**: finance's own figure is not reproduced from any SOFTECH source yet (card tenders, purchase returns, expenses
being petty cash only), and stock reads about zero before a close by design (1390 is 0 until the close posts it; the `stock_snapshot`
item already blocks a missing snapshot). Finance turns `blocks_close` on for a check once its source reproduces finance's figure.
Supplier-balance differences never block.

- A manual refresh is allowed on a closed month (it only rewrites the comparison lines and keeps explanations; audited) and refused on a `closing` month.
- `is_stale(period)`: an active check has no line, a check's accounts were edited after the oldest computation, or an entry was approved or reversed after it.
- Editing a check (`PATCH compare/checks/`, `ledger.edit`): tolerance, accounts, groups, `blocks_close`, `is_active`; accounts and groups must exist.

## Corrections and late documents

A closed month is never touched. A SOFTECH change that lands in one raises one `closed_period_change` exception **per group**
(ruling P19); `corrections.py` turns it into a **draft** in the first open month, approved like any draft.

- `post_late_correction(original_id, new_lines, user, reason, exception_id=None)`: drafts the difference between the group's new lines and what the original
  effectively says now (original plus its approved corrections), dated the first open month, `corrects` = the original, source key
  `<group_key>#corr:exc<id>` (from an exception) or `<source_key>#corr:<yyyy-mm>:<n>`; description starts «تصحيح قيد <number>». With `exception_id` the
  exception resolves in the same transaction. Refused: `original_is_draft`, `is_reversal`, `is_correction`, `close_entry`, `period_open` (use redraft),
  `correction_pending` (a draft correction exists), `nothing_to_correct`, `exception_not_open`, `exception_mismatch`, `exception_has_draft`.
- `post_late_document(exception_id, ...)`: a brand-new SOFTECH group in a closed month: its proposed lines as they are, drafted once, dated the first open month, source key = the group key.
- The drafting engine nets a group against its approved corrections, so a second change in the same closed month corrects against original + first correction, never the old amount twice.
- `ledger.reverse` of a closed-month entry dates the mirror in the first open month and sets `corrects`.
- Audited `gl_late_correction_drafted`, `gl_late_document_drafted`.
- The exceptions inbox posts it: a `closed_period_change` row shows the lines that will post, the documents count and the original entry's number, takes a required reason and calls `corrections/from-exception/`. A group whose live entry is still a draft gets no button (review or delete the draft first); the server's Arabic 409 message is shown as is. `exception_json` adds `original_entry_number` and `live_entry` ({id, number, status}) to these rows.

## Year-end

December's step 3 posts, instead of the auto-reversal (`close.year_end_close`):

- **Closing entry** dated 31-12 (`source_type='year_end'`, key `year_end:<year>`): clears each (account, branch, party) of the trading and P&L sections and nets each branch to **2409** (retained earnings).
- **Opening stock** dated 1-1 of next year (`year_end_stock`, key `year_end_stock:<year+1>`, book `opening`): Dr **5301** / Cr 1390 per branch for December's closing stock.
- Balance-sheet balances need no carry-forward entry: `trial_balance` opens with everything before its `date_from`.
- `trading_and_pl`, `financial_position`, `branch_pl`, the comparison and `compare.py` movement **exclude** the year-end closing entry (`YEAR_END_CLOSING`); `trial_balance` and `account_statement` still count it. Otherwise the closed year would report zero sales.
- A line the ledger refuses (a deactivated account with a balance) fails the close as `year_end_account` naming the account; fix it and close again.
- Close entries cannot be reversed or corrected from the journal (`close_entry`); reopening is the only route. An entry with live corrections cannot be reversed (`has_corrections`).

## Sub-ledgers

`subledgers.subledger(kind, from, to)` → opening, debit, credit, closing per party for any period, from approved and reversed lines:
`suppliers` (2341), `creditors` (2351), `notes_payable` (2343, by due-date month), `customers` (1341), `employees` (1351), `partners` (group «جارى الشركاء», one row per account).
Rows with no party are one «بدون طرف» row, included in the total. 2354 is finance's cross-book clearing account, never a creditor.
A confirmed `GLParty` links to its SOFTECH counterpart (supplier → A/P reconciliation, customer → receivables). `supplier_vs_ap(as_of)` sets the 2341 balance beside the A/P reconciliation balance (bulk, one query).

## Cutover commands

```
python manage.py import_gl_manual_entries <xlsx> [--sheet NAME] [--book cash|credit] [--preview] [--include-mixed KEY ...] [--user USERNAME]
python manage.py gl_validate_workbook <xlsx> [--through 2026-08-31] [--out report.xlsx]   # read-only; exit 1 while differences remain
python manage.py gl_reproduce_workbook <xlsx> --year 2025 --closing-stock <figure>        # Plan 1 proof, rolled back
```

The importer groups finance's journal rows into entries and gives each group one status (first match wins): `before_opening`, `unknown_account`,
`softech` (skipped: drafting replaces it), `unknown_branch`, `unbalanced`, `changed_since_import`, `mixed`, `manual`, then `possible_duplicate`. Only `manual` is imported
on its own, as a draft; `mixed` is parked as a `mixed_manual_entry` exception on a `manual_import` source doc; re-importing the same file is `already_imported`.
Full rules (header, books, link accounts, the manual account sets, idempotency key) are in "Finance's manual-only entries" in Plan 2's part. The API takes `.xlsx` only (`.xls` gets a clear message).
`gl_validate_workbook` compares ledger and workbook per account and branch, per month, and per supplier / creditor / customer / employee; only differences are listed; the workbook's float noise is read to the cent once (ROUND_HALF_UP).

Cutover order: import COA and opening (Plan 1) → drafting (Plan 2) → `import_gl_manual_entries --preview`, finance confirms the manual-account list → import → approve the drafts →
`gl_validate_workbook` until every difference is fixed in a rule or explained → close Jan to Aug in order, then Sep–Oct; go-live = the first open month after sign-off.

## API additions — `/api/finance/gl/`

| Method · path | Action | Notes |
|---|---|---|
| `GET periods/?year=` · `periods/{id}/` · `periods/{id}/checklist/` | view | months of the year (rows created up to today), one month, checklist with `can_close` |
| `POST periods/{id}/close/` | finalize | 202; step 1 runs in the request (refusals reach the caller), steps 2–3 in a background thread; poll the period |
| `POST periods/{id}/reopen/ {reason}` | finalize | returns every month it reopened |
| `GET periods/{id}/closing-stock/?preview=1` | view | saved snapshot with stores; `preview=1` reads SOFTECH now and saves nothing (503 `softech_unavailable` if down) |
| `GET compare/?period=&check=` | view | lines, `stale`, refresh state |
| `POST compare/refresh/ {period, checks?}` | view | 202, background; 409 `compare_running`; `period_closing` on a closing month |
| `GET compare/checks/` · `PATCH compare/checks/ {key, ...}` | view · edit | check settings, audited `gl_softech_check_updated` |
| `GET compare/lines/{id}/` · `POST compare/lines/{id}/explain/ {text}` | view · approve | drill-down by day with ledger and SOFTECH lines; explanation |
| `GET subledgers/{kind}/?from=&to=` · `GET subledgers/suppliers-vs-ap/?as_of=` | view | `?format=xlsx` needs `ledger.export` |
| `POST corrections/ {original_id, lines, reason, exception_id?}` | create | 201 with the draft |
| `POST corrections/from-exception/ {exception_id, reason}` | create | one per exception = per group; a correction if the group has an original entry, else a late document |
| `POST manual-import/preview/` · `POST manual-import/` | create | multipart `file`, `sheet`, `book`; import also `include_mixed` (list of keys); drafts only; rows over the screen limit → `too_many_rows` (use the command) |
| `POST validation/` | export (+ view) | multipart `file`, `through`; returns the differences as an xlsx with headers `X-GL-Validation-Differences` and `X-GL-Validation-Difference-Total` |
| `GET closing-stock-stores/` · `PATCH closing-stock-stores/ {stores: {code: {branch?, included?} or null}}` | view · edit | the store map with overrides; null restores the default |

LedgerError states that answer 409: `not_draft`, `not_approved`, `already_reversed`, `is_reversal`, `source_conflict`, `has_corrections`, `close_entry`, `period_closing`,
`period_open`, `correction_pending`, `original_is_draft`, `is_correction`, `exception_not_open`, `exception_has_draft`, `exception_has_original`. RBAC: `core/middleware/module_access.py`
maps each route above to its exact action (tested in `test_rbac_accountant`).

## Screens added (hub `/finance`)

| Route | Page | Notes |
|---|---|---|
| `/finance/close` (tabs months · stock · cutover) | `PeriodClosePage` | months with status, checklist with links, close / reopen with a reason, closing-stock preview and store map, importer preview and validation upload |
| `/finance/subledgers` (tab = kind) | `SubledgersPage` | per-party sub-ledgers, supplier comparison with A/P, rows link to the account statement |
| `/finance/softech-compare` | `SoftechComparePage` | per-month ledger vs SOFTECH, refresh with progress, drill-down and explanation |

Help: `finance.gl_close`, `finance.gl_subledgers`, `finance.gl_softech_compare`; `finance.gl_journal` explains corrections and the new refusals.

## Schedule and freshness

`apps/sync/tasks.py::_run_gl_compare_refresh` (job id `gl_compare_refresh`, 03:30, after the 02:15 finance sync) plus a one-off `gl_compare_catchup` five minutes after start.
It follows the **same switch as drafting**: off unless `GL_DRAFTING_SCHEDULE_ENABLED=True`. It refreshes every **open** month from January 2026 that holds at least one approved or reversed
entry (an empty month's comparison is meaningless nightly and each month costs a SOFTECH read of about 97 seconds; the close checklist's `comparison_fresh` still forces a manual refresh before that month closes).
A busy refresh or a failing month is logged and skipped. Freshness domain `gl_compare` («مقارنة الحسابات بسوفتيك», 1440 min). It never creates a period.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `gl_reopen_window_months` | 3 | how many of the latest closed months may be reopened |
| `gl_stock_carry_forward_until` | 2026-10-31 | month-ends up to this date may carry a store's earlier snapshot |
| `gl_closing_stock_stores` | `{}` | per-store branch / included overrides |
| `gl_branch_aliases` | none | extra journal branch names for the importer, beside finance's six |
| `gl_import_link_accounts` | `["2354"]` | accounts whose lines never decide an import status |
| `gl_import_manual_account_sets` | 1301+1302, 1302+2404, 1301 with 2405/2406/2408/2413/2417 | account sets finance keys by hand although mapped |

## Rulings (Plan 3)

Decisions taken while building, in plain words (the working notes are deleted after the merge):

- **Account feed.** `GLAccount.feed` is `auto|softech|manual|both`, default `auto`, derived from active rules and maps. The plan's default of "manual" would have imported SOFTECH-fed accounts twice. Finance can override per account.
- **SOFTECH access.** The SQL lives in `queries/sybase_gl.py`, as doc 35 says; `gl/` never imports `config.sybase`.
- **Journal layout.** The importer follows the 2020 layout (no book column, "Nothing" rows, date plus branch fallback, the 2354 link account). If the 2026 file differs, only header aliases change.
- **Mixed entries.** An entry on both manual-only and SOFTECH-fed accounts is parked as a `mixed_manual_entry` exception and blocks that month's close until an accountant includes it or ignores it with a reason. We do not guess.
- **Link account.** Imported history keeps its 2354 lines; the preview warns when their net is not zero. Finance's question on 2354 is open.
- **Workbook format.** `.xlsx` only; a `.xls` gets a clear message. Finance saves as xlsx.
- **Seeded comparison checks.** None blocks a close (see Comparison checks). Stock reads about zero before a close by design, so a blocking stock check would demand explaining the whole stock every month.
- **Correction vs reversal.** Reversing an entry that has corrections reverses its approved corrections and deletes its draft ones in the same transaction, or fails with `closed_period_change` if a correction's month is closed. This avoids counting twice after a reopen. A manual `ledger.reverse` refuses an entry with live corrections (`has_corrections`).
- **Ignoring a closed-month change** means "accept the old figure until the next change": the group's members go back to drafted. A brand-new group that is ignored keeps its group key and its members are skipped; the next change proposes everything.
- **Stuck close.** A close stuck in `closing` is taken over by a new close after 30 minutes (same idea as Plan 2's run takeover), audited. A real close over 30 minutes would be superseded; none is expected.
- **Negative stock.** A branch with negative stock flips to Cr 1390 / Dr 5302; zero posts no line. Plan 1 refuses negative amounts.
- **Close entries.** They cannot be reversed or corrected from the journal (`close_entry`). Reopen is the only route, so a wrong closing stock always needs a reopen. A journal reverse would have bypassed the close service's approval step.
- **Year-end closing entry** is excluded from the trading and P&L statements, branch P&L and the comparison, but counted in the trial balance and account statements (otherwise the closed year shows no sales).
- **Returns fallback in the importer.** It stays as designed although it merged none of the 2020 credit book's return sets; such groups stay unbalanced and are reported, not imported. 5105 and 2341 are SOFTECH-fed and should be skipped as SOFTECH anyway. Revisit with the 2026 file.
- **Manual account sets.** The default sets (1301+1302, 1302+2404, 1301 with the intercompany accounts) count as manual although mapped, because those handovers are not in SOFTECH. Finance owns the list.
- **`changed_since_import`.** A live imported entry with the same date, book, branch and description under another key stops a re-import (a re-export would double silently). The accountant reverses or deletes the old one, then re-imports.
- **`possible_duplicate`.** An account-set group is not imported when a live non-import entry has the same date, branch, accounts and total (the engine may have drafted that transfer). It can be included by key. An aggregated engine entry is still not detected; finance must check on the 2026 file.
- **Manual comparison refresh** is allowed on a closed month and refused on a closing month.
- **Nightly job** skips open months with no approved or reversed entries.
- **Security baseline.** The count of allowed suppression lines was raised from 10 to 15 for the SOFTECH readers, with the reasons written down.
- **Tests.** The closing-status refusal is tested with a plain `TestCase`: a `TransactionTestCase` flushes the kept test database and wipes migration seeds. The row-lock path is covered by review, not by a two-connection race test.

## Open owner / finance questions (Plan 3)

- Finance's 2026 journal file: the importer is built on the 2020 layout. A different header is one more alias.
- How entries mixing manual-only and SOFTECH-fed accounts should be imported; until answered they are parked and block that month's close.
- Which comparison checks should block a close, and when: turn `blocks_close` on once a source reproduces finance's figure.
- Finance runs SOFTECH's stock-at-date report on every month-end from November 2026 (earlier gaps are carried forward).
- The opening-stock figure for the production import; the 2354 coupons account; the 2409 view per branch for 2026.
- Whether the nightly comparison and drafting schedules are switched on (`GL_DRAFTING_SCHEDULE_ENABLED`).
