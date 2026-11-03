# Finance General Ledger — Plan 2 of 3: Drafting Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn SOFTECH activity into **draft** ledger entries on finance's own accounts through finance-editable, versioned posting rules — idempotent per source document, with unmatched rows parked as exceptions in the review inbox — on a schedule and on a «draft now» button.

**Architecture:** Readers (one per source type) turn SOFTECH rows into normalised `SourceDoc`s; every doc is stored once in `GLSourceDoc` (unique `source_key` + content hash). The engine picks exactly one active `PostingRule` per doc, groups docs by the rule's granularity, resolves accounts / branch / party through `GLSourceMap` and `GLParty`, and hands the lines to Plan 1's `save_draft` — the only code that writes entries. Changed or vanished source docs re-draft (draft), reverse-and-redraft (approved, open month) or raise an exception (closed month). Read-only SQL lives in `apps/finance/queries/sybase_gl.py`; mirrors (`APInvoice`, `ReconParty`) are reused where they hold what the GL needs.

**Tech Stack:** Django 5.2 + DRF, PostgreSQL, jConnect/Sybase ASE (SELECT only), APScheduler (`apps/sync/tasks.py`), React 18 + TanStack Query + Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-04-finance-general-ledger-design.md` (§7 GLParty / PostingRule / SourceException, §8, §9 screens 2–3, §10, §11a). **Builds on:** `docs/superpowers/plans/2026-11-04-finance-gl-foundation.md` and its rulings R1–R5 (`.superpowers/sdd/2026-11-04-finance-gl-foundation/progress.md` on `claude/finance-gl`).

## Source verification (2026 data, read-only, 2026-11-04)

Targets are finance's 31-08-2026 workbook (Jan–Aug 2026). Full numbers: shared note `gl-plan2-source-verification.md`. "✓" = reproduces finance within 2 %; "≈" = close, basis differs; "✗" = does not reproduce → owner question (end of plan).

| Source type | SOFTECH data (verified fields) | Evidence vs finance | Seed rule |
|---|---|---|---|
| `sales_tenders` | `branchesales` `branchcode, doccode (115 sale / 30 return), docdate, paymenttype, paymentvalue`; tenders used in 2026: 30 نقدي, 40 بطاقة, 60 خصم فكة (10 أجل → `credit_sales`) | cash = Σ115 − Σ30 per branch: 130 3.883M / 140 5.274M / 150 6.670M / 160 8.304M / 170 4.609M vs 6002 3.910 / 5.276 / 6.667 / 8.304 / 4.531 ✓; card 4.09M vs 6006 3.02M ✗ | Dr 1302 (branch) / Cr 6002 (branch); card Dr clearing map / Cr 6006 |
| `credit_sales` | `branchesales` paymenttype 10 (+`personcode`) joined to `stktransm` (`docvalue` net, `docvalue1` gross before customer discount, `docvalue3` tax) on `branchcode, doccode, docnumber, docdate` | net credit 24.16M vs 6003 − 6021 24.31M ✓; finance books every credit sale on HQ; discount basis ≈ | Dr 1341 party / Cr 6003, both on HQ branch; discount pair Dr 6021 / Cr 6003 |
| HQ store sales (rule, not a reader) | tenders / credit docs with `branchcode='100'` | 589K vs 6011 438K ≈ | `sales_tenders` at 100 → Cr 6011 |
| `purchases` | `finance.APInvoice` mirror, doccode 10/120 (`branchcode, docnumber, docdate, docnumber2, doc_value, due_date, party.softech_personcode`) | all 10: 49.82M vs 5100+5104 49.49M ✓; HQ 10: 36.42M vs 5104 HQ 35.99M ✓; 120: 1.39M vs 5101+5105 3.80M ✗ | HQ: Dr 5104 / Cr 2341 party; HQ 120: Dr 2341 / Cr 5105; branch invoices: **skip** (booked at payment) |
| FOC | free lines are zero-value in purchases | no GL effect under periodic stock (spec §11a) | none — documented, no reader |
| `supplier_payments` | `cheques` with `ptcode=20`: `cheqsno, branchcode, financialdoccode (10 نقدي / 20 شيك بنكي / 90 قيد تسوية), cheqtype (10 receipt / 20 payment), cheqno, cheqdate (= due date), cheqregisterdate (= issue), bankcode, personcode, cheqvalue, chequenote` | cash from boxes 40/50/60/70/80/10: 1.49 / 1.84 / 2.36 / 4.68 / 1.68 / 1.46M vs 5100 per branch 1.53 / 1.76 / 2.33 / 4.74 / 1.64 / 1.46M ✓ | cash: Dr 5100 (box's branch) / Cr box map; cheque: Dr 2341 party / Cr 2343 (cheque no, due date) dated `cheqregisterdate` |
| `cheque_maturity` | same rows, `financialdoccode='20'`; **`cheqcashdate` is NULL on all 664 cheques of 2026** → SOFTECH never records clearing | finance's «اوراق الدفع» sheet is by due date | Dr 2343 / Cr bank map dated `cheqdate` |
| `customer_collections` | `cheques` with `ptcode=10` (`custpayments` is empty) | HQ bank 04/06 receipts 24.8M Jan–Aug | Dr bank/box map / Cr 1341 party; `financialdoccode 90` (virtual bank 05) → exception |
| `expenses` | `dailyexpenses` `branchcode, expensedate, intervalcode, day_sno, expcode, expvalue, expcomment, cheqsno` + paying box via `cheques.bankcode` on (`branchcode, cheqsno`); every 2026 row has a voucher | petty branch expenses ≈ 0.5M; code 43 «كوبون خدمة العملاء» 1.29M at HQ = item issues (stktransm 170), not cash | Dr expense map / Cr box map, branch-day |
| `treasury_other` | `cheques` with `ptcode=-1`, `personcode` −180 / −181 (box↔box / box↔bank transfer legs, `tf_branchcode / tf_bankcode / tf_cheqsno`), other ptcodes (30 موظف, 60 شريك, 70 مورد أصول, 80 شركة شقيقة) | 6 transfer rows in 2026 (36M on 2026-01-01) | transfer legs via 1320 التحويلات; everything else → exception |
| bank movements | `bankstrans` is **empty**; no bank-statement data in SOFTECH | — | none — manual entries (spec §8 manual list) |

Reader rules that keep one SOFTECH row in one place: `cheques` rows with `personcode='-170'` (POS takings, cash `pos####` and card `financialdoccode 30`) are dropped — the cash is already in `sales_tenders`; `personcode='-120'` rows referenced by a `dailyexpenses` row are dropped — posted by `expenses`; an unreferenced −120 row becomes a `treasury_other` doc of kind `expense_unlinked`.

Why `cheques` is read directly instead of the A/P `Payment` mirror: the mirror holds only supplier and contract-customer vouchers and has no `cheqregisterdate`; the GL needs both. The mirror is not changed (spec §3) and its parties (`ReconParty`) are reused for mapping; Task 5 adds a check command comparing the two.

## Global Constraints

- **Never write to SOFTECH.** Every SOFTECH statement is a `SELECT` in `apps/finance/queries/sybase_gl.py`, run through `_fetch` / `_conn_ctx` from `apps/finance/queries/sybase_accounting.py`. Nothing under `apps/finance/gl/` imports `config.sybase`.
- Entries are created, replaced and reversed **only** through Plan 1's `apps/finance/gl/ledger.py` (`save_draft`, `approve`, `reverse`, `LedgerError`). The engine never approves.
- A SOFTECH document feeds at most one live entry: `GLSourceDoc.source_key` is unique; exactly one rule is chosen per doc; Plan 1's `gl_live_source_key_unique` guards the entry.
- Rules decide amounts from a fixed per-source whitelist of fields; no expressions, no LLM, no fuzzy matching (spec §4, CLAUDE.md rule 10). A computed negative amount moves the line to the other side; zero lines are dropped; an unbalanced result is an exception, never a draft.
- Money is `Decimal`, quantised to 0.01 with `ROUND_HALF_UP` exactly once — when a reader builds a doc's amounts.
- Rules and maps are versioned / audited and never deleted (spec §7, §10). Editing a rule creates a new version; editing a map writes `AuditLog` with before/after.
- Late changes (spec §11a): changed doc in an open month → draft replaced, or approved entry reversed + new draft; in a closed period → `SourceException('late_change_closed')`, nothing posted (Plan 3 posts the correction).
- Unconfirmed party → that doc only becomes an exception (spec §7); other docs keep drafting.
- RBAC module `ledger`: drafting runs and exception handling need `create`; party confirmation needs `approve`; rules and maps need `edit`. All GL views keep Plan 1's all-branch gate (`core.branch_scope.sees_everything`).
- Every engine/sync-fed screen gets the FreshnessBar with a forced-refresh button (`DataFreshnessBar domains=[…] onRefresh`); long runs show a `ProgressBar`; branch names via `useBranchLabels` / `BL`, never bare codes; wording «سيرفر» not «خادم».
- Sortable grids everywhere (`useSortableRows` / `SortTh`); select/approve grids use `useGridKeyboard`; no modal for common actions.
- In-app help (Arabic + English) for every new screen/tab in `apps/help/content/finance.py`, `updated: '2026-11-04'` or later; `apps/tests/test_help.py` passes.
- Tests never touch SOFTECH: readers take an injectable `fetch(sql) -> list[dict]`; tests pass fakes. Unique `TEST_DB_NAME` per run.
- Finance workbooks are never committed.

## Review Focus

1. **A SOFTECH document edited after its entry was approved** (amount or date changed, or the document deleted) → open month: original reversed, one new draft; closed month: an exception, the closed period untouched; re-running the same day changes nothing more. (Task 6)
2. **A day re-drafted while another run is active** (scheduler 08:30 and a «draft now» click) → the second run is refused with 409; no doc drafted twice. (Task 7)
3. **A supplier/customer with no confirmed `GLParty`** → only that doc becomes `unmapped_party`; the rest of the branch-day drafts; confirming the party and re-running drafts it. (Tasks 2, 6)
4. **Two rules match one doc with the same priority**, or a rule's lines don't balance for a doc → `ambiguous_rule` / `unbalanced_rule` exception, nothing drafted. (Tasks 3, 6)
5. **A rule edited mid-month** → docs before `effective_from` keep their entries; re-drafting only touches docs on or after it; the old version stays readable. (Tasks 3, 6)

## Interfaces consumed from Plan 1 (check before Task 1)

`apps/finance/gl/models.py`: `GLAccount(code, is_posting, is_active, party_type, requires_party, requires_branch)`, `LedgerEntry(status draft|approved|reversed, source_type, source_key, period, entry_date, reverses)`, `LedgerLine(party_code, branch, cheque_no, due_date)`, `FinancialPeriod.status`. `apps/finance/gl/ledger.py`: `save_draft(*, user, entry_date, description, lines, book, branch, source_type, source_key, entry=None)`, `reverse(entry_id, *, user, reason, entry_date=None)`, `LedgerError.code`. `apps/finance/gl/names.normalize_ar`.
**Assumption to verify on `claude/finance-gl` before Task 6:** the mirror entry created by `reverse()` has `source_key=''` (otherwise it collides with the re-draft). If Plan 1 copies the key, Task 6 Step 3 sets the reversal's key to `''` via `reverse(...)` returning the new entry — raise it with the Plan 1 session instead of patching around it.

## File Structure

| File | Responsibility |
|---|---|
| `apps/finance/gl/models.py` (modify) | add `GLParty`, `GLSourceMap`, `PostingRule`, `GLSourceDoc`, `SourceException`, `GLDraftRun` |
| `apps/finance/migrations/0021_gl_drafting.py` | tables above |
| `apps/finance/gl/parties.py` | finance party import, name-match proposals, confirm/reject, `resolve_party` |
| `apps/finance/gl/rules.py` | `SOURCE_FIELDS`, `CONDITION_KEYS`, rule validation, versioned save, rule selection, line building |
| `apps/finance/gl/seed.py` + `management/commands/seed_gl_drafting.py` | seed rules and maps from the verification table |
| `apps/finance/gl/sources/__init__.py` | `SourceDoc`, `READERS` registry |
| `apps/finance/gl/sources/sales.py` | `sales_tenders`, `credit_sales` |
| `apps/finance/gl/sources/purchases.py` | `purchases` (APInvoice mirror) |
| `apps/finance/gl/sources/treasury.py` | `supplier_payments`, `cheque_maturity`, `customer_collections`, `treasury_other` (one `cheques` fetch) |
| `apps/finance/gl/sources/expenses.py` | `expenses` |
| `apps/finance/queries/sybase_gl.py` | SELECT-only SQL for the readers |
| `apps/finance/gl/drafting.py` | the engine: `draft_range`, grouping, late-change handling |
| `apps/finance/gl/drafting_views.py`, `drafting_serializers.py` | API for parties, maps, rules, runs, exceptions, source drill-down |
| `apps/finance/management/commands/gl_draft.py`, `gl_check_sources.py` | CLI |
| `apps/sync/freshness.py`, `apps/sync/tasks.py` (modify) | `gl_drafting` domain; 08:30 job |
| `frontend/src/pages/finance/gl/{GLPartiesPage,PostingRulesPage,RuleEditor,SourceMapsPanel,ExceptionsTab,SourcePanel}.jsx` | screens |
| `apps/tests/test_gl_{drafting_models,parties,rules,sources,drafting,seed,drafting_api}.py` | tests |

---

### Task 1: Drafting models and migration

**Files:**
- Modify: `apps/finance/gl/models.py`; Create: `apps/finance/migrations/0021_gl_drafting.py`
- Test: `apps/tests/test_gl_drafting_models.py`

**Interfaces:**
- Produces (all `app_label='finance'`, Arabic verbose names):
  - `GLParty(party_type supplier|customer|employee|partner|other, code CharField(20), name, softech_personcode CharField(12) blank, recon_party FK finance.ReconParty null SET_NULL, status unmapped|proposed|confirmed|rejected = unmapped, proposal_basis exact|tokens|manual|'' , confirmed_by FK StaffProfile null, confirmed_at null, is_active=True)`. `UniqueConstraint(party_type, code)`; `UniqueConstraint(party_type, softech_personcode, condition=Q(status='confirmed') & ~Q(softech_personcode=''), name='gl_party_personcode_confirmed_unique')`. `supplier` covers both 2341 suppliers and 2351 creditors (finance uses one code space: code 92 تكنوفارم appears in both sheets).
  - `GLSourceMap(kind bank|expense|card_clearing, source_value CharField(20), account FK GLAccount PROTECT, branch FK branches.Branch null — the branch dimension a box carries, note, updated_by, updated_at)`. `UniqueConstraint(kind, source_value)`.
  - `PostingRule(code SlugField(60), version PositiveInteger, source_type CharField(30), description, conditions JSONField(default=dict), action post|skip = post, granularity document|branch_day|party_day = document, lines JSONField(default=list), book cash|credit|general = general, priority SmallInteger = 100, effective_from date, effective_to date null, is_active=True, created_by FK, created_at)`. `UniqueConstraint(code, version)`. Never deleted (`delete()` raises).
  - `GLSourceDoc(source_type, source_key CharField(120) unique, doc_date, branch_code CharField(5) blank, kind CharField(30) blank, personcode CharField(12) blank, amounts JSONField, attrs JSONField, content_hash CharField(64), version PositiveInteger=1, status new|drafted|skipped|exception|vanished = new, rule FK PostingRule null, group_key CharField(160) blank, entry FK LedgerEntry null SET_NULL, first_seen auto, last_seen, last_run FK GLDraftRun null)`. Index `(source_type, doc_date)`, `(group_key)`.
  - `SourceException(source_doc FK CASCADE related_name='exceptions', code unmapped_party|unmapped_account|no_rule|ambiguous_rule|unbalanced_rule|late_change_closed|duplicate_source_key|ledger_error, message, detail JSON, status open|resolved|ignored = open, created_at, resolved_by FK null, resolved_at null, resolution_note)`. `UniqueConstraint(source_doc, code, condition=Q(status='open'))`.
  - `GLDraftRun(started_at auto, finished_at null, status running|success|partial|failed, date_from, date_to, source_types JSON list, triggered_by CharField(60), counts JSON — keys read, new, unchanged, changed, vanished, drafted, skipped, exceptions, reversed —, detail JSON)`. `UniqueConstraint(fields=['status'], condition=Q(status='running'), name='gl_one_running_draft')` — at most one run at a time.
  - Data step: `StaffProfile` `gl-drafting` (inactive login, role `viewer`) created if missing; backwards leaves it. Used as `created_by` of drafted entries.

- [ ] **Step 1: Write the failing tests** — `test_second_running_run_refused_by_db`, `test_party_code_unique_per_type`, `test_confirmed_personcode_unique_but_proposals_may_repeat`, `test_rule_version_unique_and_delete_refused`, `test_source_key_unique`, `test_one_open_exception_per_code`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_drafting_models` — Expected: FAIL (import error).
- [ ] **Step 3: Implement** the models; `makemigrations finance` → rename to `0021_gl_drafting.py` (depends on `0020_general_ledger`).
- [ ] **Step 4: Run** tests and `python manage.py makemigrations --check --dry-run` — Expected: PASS, "No changes detected".
- [ ] **Step 5: Commit** — `feat(finance-gl): drafting models (parties, rules, source docs, exceptions)`

### Task 2: Parties — import, proposals, confirmation

**Files:**
- Create: `apps/finance/gl/parties.py`, `apps/finance/management/commands/import_gl_parties.py`
- Test: `apps/tests/test_gl_parties.py`

**Interfaces:**
- Consumes: `normalize_ar` (Plan 1), `ReconParty`.
- Produces:
  - `parse_party_sheets(path) -> list[PartyRow]`, `PartyRow(party_type, code, name)`. Reads finance's sub-ledger pivots by header, not position: header row containing `suppliar code` → `supplier` (sheets «الموردين», «الدائنون»); `customer code` → `customer` («العملاء»). Skips `Total` / `Grand Total` / `الرصيد الافتتاحى` rows and blank codes; codes stored as `str(int(code))`.
  - `import_parties(rows, *, user) -> dict(created, updated)` — upsert by `(party_type, code)`, name updated, never deleted; audited `gl_parties_imported`.
  - `propose_matches(*, user) -> dict(exact, tokens, none)` — for each `unmapped` party, compare `normalize_ar(name)` with `ReconParty.name` of the same type (`supplier`↔`supplier`, `customer`↔`customer`): equal → `proposed/exact`; else equal token sets after removing `STOP_WORDS = {'شركه','شركة','ش','للادويه','لتجاره','الادويه','ادويه','فرع','و','ال'}` → `proposed/tokens`; exactly one candidate required, otherwise stays `unmapped`. Never confirms.
  - `confirm_party(party_id, *, user, personcode: str) -> GLParty`; `reject_party(party_id, *, user)`; `create_party_from_personcode(*, user, party_type, code, personcode) -> GLParty` (confirmed; used from the exceptions inbox). All audited with before/after.
  - `resolve_party(party_type: str, personcode: str) -> GLParty | None` — confirmed + active only.
  - Command: `python manage.py import_gl_parties <xlsx> [--propose]`.

- [ ] **Step 1: Write the failing tests** — synthetic workbook (openpyxl) with «الموردين» / «الدائنون» / «العملاء» shapes incl. a `Total` row, a `الرصيد الافتتاحى` row and code 92 in two sheets:
  - `test_sheets_parsed_by_header_and_totals_skipped`
  - `test_same_code_in_suppliers_and_creditors_is_one_party`
  - `test_exact_name_proposal` (`'فارما اوفرسيز '` ↔ `'فارما أوفرسيز'`)
  - `test_token_proposal_ignores_stop_words`
  - `test_two_candidates_leave_party_unmapped`
  - `test_resolve_party_ignores_proposed` *(Review Focus 3)*
  - `test_confirm_requires_unique_personcode` (second confirm of same personcode → `IntegrityError` surfaced as `ValueError` with Arabic text)
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_parties` — Expected: FAIL.
- [ ] **Step 3: Implement** `parties.py` and the command.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): finance party codes mapped to SOFTECH persons`

### Task 3: Posting rules and source maps — validation, versions, line building

**Files:**
- Create: `apps/finance/gl/rules.py`
- Test: `apps/tests/test_gl_rules.py`

**Interfaces:**
- Create also: `apps/finance/gl/sources/__init__.py` with `SourceDoc`, `content_hash` and an empty `READERS` (Task 4 interface block describes them; readers are registered by Tasks 4–5).
- Consumes: Task 1 models.
- Produces:
  - `SOURCE_FIELDS: dict[str, tuple[str, ...]]` — the amount whitelist:
    `sales_tenders: ('net','sales','returns')` · `credit_sales: ('credit','gross_share','discount_share','tax_share')` · `purchases: ('value',)` · `supplier_payments: ('amount',)` · `cheque_maturity: ('amount',)` · `customer_collections: ('amount',)` · `expenses: ('amount',)` · `treasury_other: ('amount',)`.
  - `CONDITION_KEYS: dict[str, tuple[str, ...]]` — `branch_in`, `branch_not_in` (all types); `kind_in` (all); `paymenttype_in` (`sales_tenders`); `doccode_in` (`purchases`, `credit_sales`); `financialdoc_in`, `direction_in` (`receipt|payment`), `bank_type_in` (`box|bank`) (the four cheques types); `expcode_in` (`expenses`). Values are lists of strings.
  - Line spec (each item of `PostingRule.lines`): `{side: 'debit'|'credit', account: '<code>'} | {side, account_map: 'bank'|'expense'|'card_clearing', map_key: 'bankcode'|'expcode'|'branch_code'}`, plus `amount: <field in SOURCE_FIELDS[type]>`, `branch: 'source'|'hq'|'map'|'none'` (`map` = the `GLSourceMap.branch`), `party: 'source'|'none'`, `cheque: bool` (copy `attrs.cheqno` / `attrs.due_date`), `description: str` with placeholders `{branch}`, `{date}`, `{docnumber}`, `{cheqno}`, `{party}` only.
  - `validate_rule(source_type, conditions, lines, action) -> list[str]` (Arabic errors): unknown source type / condition key / field / placeholder; account missing, inactive or non-posting; `post` with fewer than one debit and one credit line; `skip` with lines.
  - `save_rule(*, user, code, source_type, effective_from, conditions, lines, action='post', granularity='document', book='general', priority=100, description='') -> PostingRule` — validates; if `code` exists, sets the current version's `effective_to = effective_from − 1 day` and creates `version + 1` (refuses `effective_from` ≤ current version's `effective_from`); audited `gl_rule_saved`.
  - `select_rule(doc, rules) -> PostingRule` — active rules of `doc.source_type` with `effective_from ≤ doc_date ≤ effective_to (or open)` and all conditions true; highest `priority` wins; raises `RuleMiss('no_rule')` or `RuleMiss('ambiguous_rule')` on a tie.
  - `build_lines(rule, docs: list[SourceDoc], *, hq_branch_id) -> list[dict]` — Plan 1 line dicts; amounts summed per (side, account, branch, party, cheque) across the group; negative → other side; zero dropped; raises `RuleMiss('unmapped_account', key)` / `RuleMiss('unmapped_party', personcode)` / `RuleMiss('unbalanced_rule')`.
  - `preview_rule(rule_or_draft: dict, date_from, date_to) -> dict(entries: [...], exceptions: [...], totals)` — runs the Task 4 reader for the range and `build_lines` without saving anything (screen 2 «تجربة»).
  - `save_map(*, user, kind, source_value, account_code, branch_id=None, note='') -> GLSourceMap` — audited.

- [ ] **Step 1: Write the failing tests** —
  - `test_unknown_field_or_condition_rejected`
  - `test_skip_rule_with_lines_rejected`
  - `test_edit_creates_new_version_and_closes_old` (v1 `effective_to` = new `effective_from` − 1) *(Review Focus 5)*
  - `test_select_rule_by_date_uses_old_version_before_change` *(Review Focus 5)*
  - `test_equal_priority_tie_is_ambiguous` *(Review Focus 4)*
  - `test_negative_amount_moves_side_and_zero_dropped`
  - `test_group_lines_summed_per_account_branch_party`
  - `test_unbalanced_rule_raises` *(Review Focus 4)*
  - `test_unmapped_box_raises_unmapped_account`
  - `test_party_line_needs_confirmed_party` *(Review Focus 3)*
  - `test_preview_saves_nothing` (`LedgerEntry.objects.count()` unchanged)
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_rules` — Expected: FAIL.
- [ ] **Step 3: Implement** `rules.py`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): versioned posting rules and source maps`

### Task 4: Source readers — sales and purchases

**Files:**
- Create: `sources/sales.py`, `sources/purchases.py`, `apps/finance/queries/sybase_gl.py`
- Test: `apps/tests/test_gl_sources.py`

**Interfaces:**
- Produces:
  - (in `sources/__init__.py`, created in Task 3) `@dataclass(frozen=True) SourceDoc(source_type, source_key, doc_date: date, branch_code: str, kind: str, personcode: str, amounts: dict[str, Decimal], attrs: dict)`; `content_hash(doc) -> str` (sha256 of the canonical JSON of everything except `source_key`).
  - `READERS: dict[str, Callable[[date, date, Fetch], Iterator[SourceDoc]]]`, `Fetch = Callable[[str], list[dict]]`; `sybase_fetch() -> Fetch` (wraps `_conn_ctx`/`_fetch`, one connection per run, closed by the caller via context manager `open_fetch()`).
  - `sybase_gl.py` SELECTs (date bounds `>= from AND < to+1`, one query per calendar month chunk — a cold first query took ~150 s, warm ~2.5 s/month):
    - `sql_branchesales(d1, d2)`: `SELECT branchcode, doccode, docdate, paymenttype, SUM(paymentvalue) s FROM branchesales WHERE doccode IN ('115','30') AND paymenttype <> '10' … GROUP BY branchcode, doccode, docdate, paymenttype`.
    - `sql_credit_docs(d1, d2)`: `stktransm m` (doccode 115/30) with the credit part `SUM(b.paymentvalue)` from `branchesales b` paymenttype `'10'` joined on `branchcode, doccode, docnumber, docdate`, returning `m.branchcode, m.doccode, m.docnumber, m.docdate, b.personcode, credit, m.docvalue, m.docvalue1, m.docvalue3`.
  - `read_sales_tenders`: one doc per `(branchcode, docdate, paymenttype)`; key `bs:{branch}:{date}:{paymenttype}`; `kind` = `cash` (30) | `card` (40) | `change_discount` (60) | `pt<code>` (anything else → no rule → exception); `amounts = {sales, returns, net = sales − returns}`.
  - `read_credit_sales`: one doc per SOFTECH document with a credit tender; key `cs:{branch}:{doccode}:{docnumber}:{date}` (docnumber is per branch+doctype — never key on it alone); `personcode` from `branchesales`; sign −1 for doccode 30; `amounts = {credit, gross_share = credit × docvalue1 / docvalue, discount_share = gross_share − credit, tax_share = credit × docvalue3 / docvalue}` (each quantised once; `docvalue == 0` → shares = credit, discount 0).
  - `read_purchases`: from `APInvoice` (doccode 10/120, `docdate` in range, `party_type='supplier'`); key `ap:{branch}:{doccode}:{docnumber}:{date}`; `kind` = `invoice` | `return`; `amounts = {value}` (returns positive — rules choose sides); `attrs = {doccode, docnumber, docnumber2, due_date}`.
- Note for the implementer: the APInvoice mirror is refreshed by the 07:30 morning chain; the reader reads Postgres only.

- [ ] **Step 1: Write the failing tests** (fake `fetch` returning fixed rows; `APInvoice` rows created in the test DB) —
  - `test_tenders_net_sales_minus_returns_per_branch_day`
  - `test_credit_tender_excluded_from_tenders`
  - `test_unknown_paymenttype_kept_as_kind` (`'pt50'`)
  - `test_credit_doc_shares_prorated_and_quantised` (docvalue 1000, docvalue1 1100, credit 600 → gross_share 660.00, discount_share 60.00)
  - `test_credit_return_is_negative`
  - `test_purchase_keys_include_branch_doccode_and_date` (same docnumber in two branches → two docs)
  - `test_hash_changes_when_amount_changes_not_when_order_changes`
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_sources` — Expected: FAIL.
- [ ] **Step 3: Implement** the package, the two readers and the SQL builders.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): sales and purchase source readers`

### Task 5: Source readers — treasury and expenses; source check command

**Files:**
- Create: `apps/finance/gl/sources/treasury.py`, `sources/expenses.py`, `apps/finance/management/commands/gl_check_sources.py`
- Modify: `apps/finance/queries/sybase_gl.py`
- Test: `apps/tests/test_gl_sources.py` (extend)

**Interfaces:**
- Produces:
  - `sql_cheques(d1, d2)`: `cheques` rows with `cheqdate` **or** `cheqregisterdate` in range; columns `cheqsno, branchcode, financialdoccode, cheqtype, cheqno, cheqdate, cheqregisterdate, bankcode, personcode, CONVERT(varchar(10), ptcode) ptcode, cheqvalue, chequenote, tf_branchcode, tf_bankcode, tf_cheqsno`, plus `banks.banktype` (0 box / 1 bank) and an `EXISTS` flag `has_expense` against `dailyexpenses` on `CONVERT(varchar(20), cheqsno)` + `branchcode` (Sybase refuses implicit varchar↔int — always `CONVERT`; `personcode` compares as a quoted string).
  - `read_cheques(d1, d2, fetch) -> Iterator[SourceDoc]` — one fetch, several source types:
    - drop `personcode='-170'`; drop `personcode='-120' AND has_expense`;
    - `ptcode '20'` → `supplier_payments`, `ptcode '10'` → `customer_collections`, else → `treasury_other` with `kind` = `transfer` (personcode −180/−181) | `expense_unlinked` (−120) | `employee` (30) | `partner` (60) | `asset_supplier` (70) | `sister_company` (80) | `other`;
    - key `chq:{branch}:{cheqsno}`; `doc_date = cheqregisterdate` when `financialdoccode='20'` else `cheqdate`; emitted only when `doc_date` is in range;
    - every `financialdoccode='20'` row with `cheqdate` in range also emits `cheque_maturity`, key `chqdue:{branch}:{cheqsno}`, `doc_date = cheqdate`;
    - `amounts={amount}`; `attrs={financialdoc, direction: 'receipt' if cheqtype=='10' else 'payment', bankcode, bank_type, cheqno, due_date, note, tf_branchcode, tf_bankcode, tf_cheqsno}`.
    - `READERS` registers the four types to the same callable filtered by type (the engine calls it once per run and routes docs).
  - `read_expenses`: `dailyexpenses d` + paying box from `cheques` on `(branchcode, cheqsno)`; key `exp:{branch}:{expensedate}:{intervalcode}:{day_sno}`; `kind=expcode`; `amounts={amount}`; `attrs={expcode, bankcode, cheqsno, comment}`. The reader yields a `duplicate_source_key` marker doc (`kind='__duplicate__'`) instead of merging when two rows share a key.
  - `gl_check_sources --source <type|all> --from --to` — prints per type × month × branch: doc count and Σ amounts; for `supplier_payments` / `customer_collections` also the same totals from the A/P `Payment` mirror and the difference (expected 0 where the mirror covers the party). Read-only; exit 0.

- [ ] **Step 1: Write the failing tests** —
  - `test_pos_rows_dropped` (−170 cash and card)
  - `test_expense_vouchers_dropped_only_when_referenced` (unreferenced −120 → `treasury_other/expense_unlinked`)
  - `test_cheque_emits_issue_on_register_date_and_maturity_on_due_date`
  - `test_issue_outside_range_but_due_inside_emits_only_maturity`
  - `test_ptcode_routes_to_source_type`
  - `test_transfer_legs_are_two_docs`
  - `test_expense_duplicate_key_marked_not_merged`
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_sources` — Expected: FAIL (new tests).
- [ ] **Step 3: Implement** readers, SQL and the command.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Live check (local, not CI):** `SOFTECH_READ_ONLY=True python manage.py gl_check_sources --source all --from 2026-01-01 --to 2026-08-31` — Expected: supplier cash payments per box ≈ 1.49 / 1.84 / 2.36 / 4.68 / 1.68 / 1.46M (40/50/60/70/80/10); no `__duplicate__` expense keys (if any appear, report them — they decide whether the key needs `cheqsno`); paste the output in the task report.
- [ ] **Step 6: Commit** — `feat(finance-gl): treasury and expense source readers, source check`

### Task 6: Drafting engine — idempotent drafts, exceptions, late changes

**Files:**
- Create: `apps/finance/gl/drafting.py`, `apps/finance/management/commands/gl_draft.py`
- Test: `apps/tests/test_gl_drafting.py`

**Interfaces:**
- Consumes: `READERS`, `select_rule`, `build_lines`, `resolve_party`, `save_draft`, `reverse`, `LedgerError`.
- Produces:
  - `system_user() -> StaffProfile` — the `gl-drafting` profile from Task 1's data step.
  - `draft_range(date_from, date_to, *, source_types=None, run: GLDraftRun, fetch=None) -> GLDraftRun`. Per source type:
    1. Read docs; for each: upsert `GLSourceDoc` by `source_key`. New → `new`. Same hash → untouched (counts `unchanged`). Different hash → `version += 1`, `changed`.
    2. Docs of this type in the window that the reader no longer returned → `vanished` (only for types whose read covered the whole window without error).
    3. For each `new`/`changed` doc: `select_rule`; `skip` → status `skipped`; `post` → `group_key` = `source_key` (document) | `{rule.code}:{branch}:{date}` (branch_day) | `{rule.code}:{personcode}:{date}` (party_day).
    4. For each touched group: rebuild from **all** member docs with status in (`new`, `changed`, `drafted`) and that group key; `build_lines`; then by the group's current live entry:
       - none → `save_draft(user=system_user(), entry_date, description, lines, book=rule.book, branch, source_type, source_key=group_key)`;
       - draft → `save_draft(..., entry=existing)` (lines replaced);
       - approved, period open → `reverse(entry, user=system_user(), reason='تغير مستند سوفتيك')` then `save_draft` (counts `reversed`);
       - approved, period `closed`/`closing` → `SourceException('late_change_closed')` on each changed doc, entry untouched.
       Members → `drafted`, `entry` set. A group whose members all vanished: draft deleted / approved reversed / closed → exception.
    5. `RuleMiss` / `LedgerError` → `SourceException(code, message, detail)` on the doc(s), status `exception`; an open exception of a doc that now drafts → `resolved` (`resolution_note='حُلّ تلقائياً عند إعادة الترحيل'`).
    6. `run.counts` filled; `success` if no reader failed, `partial` if one failed (others still drafted), `failed` on a fatal error.
  - `start_run(*, triggered_by, date_from, date_to, source_types) -> GLDraftRun` — first marks `running` runs older than 2 h `failed` (crashed process), then creates the run; the `gl_one_running_draft` constraint turns a concurrent start into `DraftBusy` (the API maps it to 409).
  - Entry date: the doc date; book from the rule; description from the rule's first line template.
  - Command: `python manage.py gl_draft --from YYYY-MM-DD --to YYYY-MM-DD [--source TYPE ...] [--dry-run]` (`--dry-run` = `transaction.atomic()` + rollback, prints counts).

- [ ] **Step 1: Write the failing tests** (fake readers injected through `fetch`/`READERS` override; COA built with Plan 1 models) —
  - `test_first_run_drafts_second_run_changes_nothing` (entry ids, line amounts and counts `unchanged`)
  - `test_branch_day_groups_tenders_into_one_entry`
  - `test_changed_doc_replaces_draft_lines`
  - `test_changed_doc_after_approval_reverses_and_redrafts` (original `reversed`, one new draft, re-run → no further change) *(Review Focus 1)*
  - `test_changed_doc_in_closed_period_raises_exception_only` *(Review Focus 1)*
  - `test_vanished_doc_reverses_approved_entry` *(Review Focus 1)*
  - `test_unmapped_party_blocks_only_that_doc` (two credit docs same day, one unconfirmed) *(Review Focus 3)*
  - `test_exception_auto_resolves_after_party_confirmed` *(Review Focus 3)*
  - `test_ambiguous_and_unbalanced_rules_become_exceptions` *(Review Focus 4)*
  - `test_rule_edit_redrafts_only_from_effective_from` *(Review Focus 5)*
  - `test_skip_rule_marks_doc_skipped_no_entry`
  - `test_second_run_while_running_refused` (`DraftBusy`) *(Review Focus 2)*
  - `test_reader_failure_gives_partial_and_no_vanish`
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_drafting` — Expected: FAIL.
- [ ] **Step 3: Verify the Plan 1 assumption** (reversal entry's `source_key`) on `claude/finance-gl`, then implement `drafting.py` and the command.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): idempotent drafting engine with late-change handling`

### Task 7: Seed rules and maps; schedule, freshness, «draft now»

**Files:**
- Create: `apps/finance/gl/seed.py`, `apps/finance/management/commands/seed_gl_drafting.py`
- Modify: `apps/sync/freshness.py` (`DOMAINS['gl_drafting'] = {'label_ar': 'ترحيل القيود من سوفتيك', 'source': 'gl_drafting', 'cadence_min': 1440, 'kind': 'snapshot'}`, `_SOURCES['gl_drafting']` reading `GLDraftRun` like `_source_stock_audit`), `apps/sync/tasks.py` (job `gl_drafting` cron 08:30 — after the 07:30 morning chain refreshes the A/P mirror — `max_instances=1`, `misfire_grace_time=3600`; window = first day of the earliest **open** period among the last two months → yesterday)
- Test: `apps/tests/test_gl_seed.py`

**Interfaces:**
- Produces `seed_gl_drafting(*, user) -> dict` (idempotent: creates a rule only when its `code` has no version; a map only when its `(kind, source_value)` is absent; `effective_from=2026-01-01`; never edits finance's later changes):
  - Maps — `bank`: 10 → 1301 (HQ), 40 → 1302 (branch 130), 50 → 1302 (140), 60 → 1302 (150), 70 → 1302 (160), 80 → 1302 (170), 04 → 1310, 06 → 1308, 01 → 1316. `card_clearing`: none (owner question 3). `expense` (name-verified only): 92 → 3173, 45 → 3113, 46 → 3116, 47 → 3169, 108 → 3119, 11 → 3112, 16 → 3114, 14 → 3115, 19 → 3111, 17 → 3125, 10 → 3117, 102 → 3188, 97 → 3156, 50 → 3122, 86 → 3200, 32 → 1304, 109 → 1351. Every other code raises `unmapped_account` until finance maps it.
  - Rules (code · source · conditions · action/lines · granularity · book):
    - `sales.cash` · tenders · kind cash, branch_not_in [100] · Dr 1302 (source) / Cr 6002 (source), `net` · branch_day · cash
    - `sales.hq_store` · tenders · kind cash, branch_in [100] · Dr 1301 (hq) / Cr 6011 (hq), `net` · branch_day · cash
    - `sales.card` · tenders · kind card · Dr map card_clearing by branch_code (map) / Cr 6006 (source), `net` · branch_day · cash
    - `sales.change_discount` · tenders · kind change_discount · Dr 6022 / Cr 6002 (source), `net` · branch_day · cash
    - `sales.credit` · credit_sales · — · Dr 1341 party (hq) `credit` / Cr 6003 (hq) `credit`; Dr 6021 (hq) / Cr 6003 (hq) `discount_share` · party_day · credit
    - `purchases.hq` · purchases · branch_in [100], kind invoice · Dr 5104 (hq) / Cr 2341 party (hq), `value` · document · credit
    - `purchases.hq_return` · purchases · branch_in [100], kind return · Dr 2341 party / Cr 5105, `value` · document · credit
    - `purchases.branch` · purchases · branch_not_in [100] · **skip** («تُسجل عند السداد النقدي من خزينة الفرع»)
    - `supplier.cash` · supplier_payments · financialdoc_in [10], direction payment · Dr 5100 (map) / Cr map bank by bankcode (map), `amount` · branch_day · cash
    - `supplier.cheque` · supplier_payments · financialdoc_in [20], direction payment · Dr 2341 party (hq) / Cr 2343 (hq, cheque) `amount` · document · credit
    - `cheque.maturity` · cheque_maturity · direction payment · Dr 2343 (hq, cheque) / Cr map bank by bankcode, `amount` · document · general
    - `customer.collection` · customer_collections · financialdoc_in [10, 20], direction receipt · Dr map bank by bankcode / Cr 1341 party (hq), `amount` · document · general
    - `expenses.box` · expenses · — · Dr map expense by expcode (source) / Cr map bank by bankcode (map), `amount` · branch_day · cash
    - `treasury.transfer_in` / `treasury.transfer_out` · treasury_other · kind transfer, direction receipt / payment · Dr box map / Cr 1320 and Dr 1320 / Cr box map, `amount` · document · general
    - No rule (→ exception for the accountant): supplier receipts, `financialdoc 90` settlements, customer refunds, card tenders until a clearing map exists, `expense_unlinked`, employee / partner / asset-supplier / sister-company vouchers, unknown tenders.
- `POST /api/finance/gl/drafting/run/ {date_from, date_to, source_types?}` (`ledger.create`) → `start_run` + `start_thread` (`core.threads.start_thread`, never bare `Thread`) → 202 `{run_id}`; `DraftBusy` → 409. `GET drafting/runs/?limit=` and `GET drafting/runs/{id}/` (`ledger.view`) for the ProgressBar (counts).

- [ ] **Step 1: Write the failing tests** — `test_seed_is_idempotent_and_keeps_finance_edits` (edit `sales.cash` to v2, re-seed → still v2, no v1 duplicate), `test_seed_rules_all_validate`, `test_freshness_domain_reads_last_run`, `test_run_endpoint_202_then_409_while_running` *(Review Focus 2)*, `test_run_endpoint_needs_ledger_create`, `test_scheduler_window_starts_at_earliest_open_month`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_seed` — Expected: FAIL.
- [ ] **Step 3: Implement** seed, command, freshness domain, scheduled job and run endpoints (urls under `apps/finance/gl/urls.py`).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Dry run on real data (local, read-only, not CI):** after Plan 1's COA import on the dev DB, `seed_gl_drafting` then `SOFTECH_READ_ONLY=True python manage.py gl_draft --from 2026-08-01 --to 2026-08-31 --dry-run` — Expected: counts per type and an exception list grouped by code; paste in the task report together with August `sales.cash` per branch vs SOFTECH tenders (e.g. 160: pt30 sales 1,187,916.69 − returns 16,872.60 = 1,171,044.09 on 6002).
- [ ] **Step 6: Commit** — `feat(finance-gl): seed rules, scheduled drafting and draft-now`

### Task 8: API — parties, maps, rules, exceptions, source drill-down

**Files:**
- Create: `apps/finance/gl/drafting_views.py`, `apps/finance/gl/drafting_serializers.py`; Modify: `apps/finance/gl/urls.py`
- Test: `apps/tests/test_gl_drafting_api.py`

**Interfaces:** (prefix `/api/finance/gl/`, `matrix_permission('ledger', …)` + Plan 1 all-branch gate)

| Method · path | Action | Notes |
|---|---|---|
| `GET parties/?type=&status=&q=` | view | wildcard search (`WildcardSearchFilter`), shows proposal + SOFTECH name |
| `POST parties/import/` (xlsx), `POST parties/propose/` | edit | Task 2 |
| `POST parties/{id}/confirm/ {personcode}` · `POST parties/{id}/reject/` · `POST parties/ {type, code, name, personcode}` | approve | |
| `GET maps/?kind=` · `PUT maps/{kind}/{source_value}/ {account_code, branch_id, note}` | view · edit | |
| `GET rules/?source_type=&active=` · `GET rules/{code}/versions/` | view | |
| `POST rules/ {…}` (new or new version) | edit | `validate_rule` errors → 400 `{errors:[…]}` |
| `POST rules/preview/ {rule, date_from, date_to}` | view | `preview_rule`; range ≤ 31 days (400 otherwise) |
| `GET exceptions/?status=open&code=&source_type=&date_from=&date_to=&branch=` | view | cursor-paginated, with doc summary |
| `POST exceptions/{id}/ignore/ {note}` · `POST exceptions/redraft/ {ids}` | create | redraft = `draft_range` on those docs' dates and types (same lock) |
| `GET entries/{id}/source/` | view | member `GLSourceDoc`s (amounts, attrs, SOFTECH key parts, version, rule code+version) |

- [ ] **Step 1: Write the failing tests** — `test_rule_edit_needs_ledger_edit`, `test_party_confirm_needs_approve`, `test_preview_range_limit`, `test_exceptions_filter_and_ignore_audited`, `test_entry_source_lists_member_docs`, `test_non_all_branch_user_403`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_drafting_api` — Expected: FAIL.
- [ ] **Step 3: Implement** serializers, views, urls (decimals as strings).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): drafting API (parties, maps, rules, exceptions, source)`

### Task 9: Frontend — parties, posting rules, maps

**Files:**
- Modify: `frontend/src/api/client.js` (`glApi`: one method per Task 7/8 endpoint), `frontend/src/pages/FinanceHubPage.jsx` (tabs), `frontend/src/App.jsx` (routes)
- Create: `frontend/src/pages/finance/gl/GLPartiesPage.jsx`, `PostingRulesPage.jsx`, `RuleEditor.jsx`, `SourceMapsPanel.jsx`

**Interfaces:**
- Routes / hub tabs (after «كشف حساب»): `/finance/parties` «الأطراف» 👥, `/finance/rules` «قواعد الترحيل» ⚙️ (tabs `rules`, `maps`; `useHelpTab(tab)`).
- `GLPartiesPage`: status filter (default `proposed`), grid code · name · type · SOFTECH person · basis · status; `useGridKeyboard` with Enter = confirm proposal, M = pick another person (person search on `ReconParty`), import + «اقتراح المطابقة» buttons (`ledger.edit`). `data-tour`: `finance-gl-parties-grid`, `finance-gl-parties-propose`.
- `PostingRulesPage` `rules` tab: grid by source type (code, version, conditions summary, lines summary, granularity, effective dates, active); row → `RuleEditor` side panel: conditions as chips from `CONDITION_KEYS`, line rows (side, account picker or map, amount field from `SOURCE_FIELDS`, branch, party, cheque), effective-from date, «تجربة» (date range ≤ 31 days → preview entries + exceptions inline), save = new version (`ledger.edit` only; read-only otherwise), version history list. `maps` tab = `SourceMapsPanel` (kind switch, inline account picker per source value, unmapped values highlighted from open `unmapped_account` exceptions). `data-tour`: `finance-gl-rules-grid`, `finance-gl-rule-test`, `finance-gl-maps-grid`.

- [ ] **Step 1: Implement** client methods, routes, tabs, pages.
- [ ] **Step 2: Run** `cd frontend && npm run build` — Expected: success (`check-sort` passes).
- [ ] **Step 3: Verify in the app** (preview server, dev DB seeded): confirm a proposed party with Enter; edit `sales.cash` → v2 appears with v1 closed; «تجربة» on 2026-08-01..08 shows entries without saving; console clean. Screenshot in the task report.
- [ ] **Step 4: Commit** — `feat(finance-gl): parties, posting rules and maps screens`

### Task 10: Frontend — review inbox extensions on the journal

**Files:**
- Modify: `frontend/src/pages/finance/gl/JournalPage.jsx`, `EntryEditor.jsx` (Plan 1 Task 10)
- Create: `frontend/src/pages/finance/gl/ExceptionsTab.jsx`, `SourcePanel.jsx`

**Interfaces:**
- `JournalPage` gains: a `DataFreshnessBar domains={['gl_drafting','ap_reconciliation']} canEdit={can('ledger','create')} onRefresh={draftNow}` (draft-now = run for the current open month, `ProgressBar` from `drafting/runs/{id}` counts); a `source` filter (source types + «يدوي»); tabs «المسودات» (existing) and «الاستثناءات» (`ExceptionsTab`, badge = open count); `useHelpTab(tab)`.
- `ExceptionsTab`: grouped by code with counts; grid date · branch (`BL`) · source · SOFTECH reference · amount · message; actions inline per row by code — `unmapped_party` → confirm/create party; `unmapped_account` → map now (kind/value prefilled); `no_rule`/`ambiguous_rule` → open rule editor prefilled with the doc's type and conditions; `late_change_closed` → read-only note «يُصحح عند إقفال الفترة» (Plan 3); any → ignore with note; multi-select + «إعادة الترحيل» (redraft). `useGridKeyboard`.
- `SourcePanel` (inside `EntryEditor` for entries with `source_type`): member docs, their amounts/attrs, SOFTECH key, version history, rule code + version, link to the rule.
- `data-tour`: `finance-gl-journal-freshness`, `finance-gl-exceptions-grid`, `finance-gl-entry-source`.

- [ ] **Step 1: Implement** the components.
- [ ] **Step 2: Run** `cd frontend && npm run build` — Expected: success.
- [ ] **Step 3: Verify in the app**: «draft now» for August shows progress then drafts; an `unmapped_party` exception resolves after confirming the party and redrafting; an entry's source panel lists its branchesales rows; refresh during a running draft shows «يعمل بالفعل». Screenshot.
- [ ] **Step 4: Commit** — `feat(finance-gl): exceptions inbox, source drill-down and draft-now`

### Task 11: Help, docs, regression

**Files:**
- Modify: `apps/help/content/finance.py` — new screens `finance.gl_parties`, `finance.gl_rules` (tabs `rules`, `maps`), and the `finance.gl_journal` tabs (`drafts`, `exceptions`) with the exception codes explained; Arabic + English; `updated` bumped; targets from Tasks 9–10.
- Modify: `docs/architecture/34_FINANCE_GENERAL_LEDGER.md` (drafting section: readers, verified fields table from this plan, rules model, late-change behaviour, schedule), `02_MODULE_REGISTRY.md`, `04_API_REGISTRY.md`, `05_UI_REGISTRY.md`, `03_DATABASE_DICTIONARY.md`.

- [ ] **Step 1: Write** help and docs.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_help apps.tests.test_gl_drafting_models apps.tests.test_gl_parties apps.tests.test_gl_rules apps.tests.test_gl_sources apps.tests.test_gl_drafting apps.tests.test_gl_seed apps.tests.test_gl_drafting_api apps.tests.test_gl_ledger apps.tests.test_gl_api apps.tests.test_finance_freshness` (unique `TEST_DB_NAME`) — Expected: all PASS.
- [ ] **Step 3: Run** the full suite `python manage.py test apps.tests` and `cd frontend && npm run build` — Expected: no new failures vs main.
- [ ] **Step 4: Commit** — `docs(finance-gl): drafting help, architecture and registries`

---

## Owner / finance questions (do not block coding; they change seed data or rules, not code)

1. **Purchases split.** Evidence says finance books branch purchases as *cash purchases when paid from the branch box* (5100) and HQ invoices as credit purchases (5104 on the supplier). Seeded that way. Confirm — and say what happens to a branch invoice paid later by HQ cheque (today it would hit 2341 with no matching purchase).
2. **Cash purchase returns 5101 = 3.11M** (0.75/1.53/0.78M in Apr–Jun) do not come from SOFTECH returns (doccode 120 = 1.39M in total). What are they (expired-goods settlements?) — rule from SOFTECH or manual entry?
3. **Card sales.** SOFTECH card tender net 4.09M vs finance 6006 3.02M. Which processor (PAYMOB 1321 / CIB 1329) per branch, and is finance's visa figure the bank settlement rather than the till? Until answered, card tenders stay exceptions.
4. **Credit sales presentation.** Seeded as 6003 gross / 6021 discount using SOFTECH's `docvalue1 − docvalue` pro-rated to the company share; finance's 6021 is ~15 % lower than that basis in August. Keep, or post 6003 net?
5. **Credit returns.** SOFTECH credit returns are 1.61M but finance's 6018 is 43K — finance nets returns into 6003. Keep netting (seeded) or use 6018?
6. **VAT.** SOFTECH `docvalue3` (sales 1.30M, purchases 0.70M) does not match 2362 (0.57M) / 2363 (1.23M). Where does finance take VAT from? No VAT lines are seeded.
7. **Cheque maturity date.** SOFTECH never records clearing (`cheqcashdate` empty); maturity is posted on the due date. OK?
8. **Bank movements, card settlements, branch-box → bank deposits** are not in SOFTECH (`bankstrans` empty). Stay manual, or import bank statements later?
9. **1-1-2026 transfers** (36M across HQ box, branches 150/160, bank 04, settlement code 90): real money or balance clean-up? They will draft through 1320 / raise exceptions.
10. **Expense code 43 «كوبون خدمة العملاء»** (1.29M at HQ, item issues): which account, or skip?
11. **Dating basis for supplier invoices** — docdate (seeded) vs supplier invoice date; per-supplier monthly totals differ by up to ~10 % from finance's «مشتريات الموردين».
12. Rule editing is `ledger.edit` (finance manager) — confirm (spec §10 "my call").
