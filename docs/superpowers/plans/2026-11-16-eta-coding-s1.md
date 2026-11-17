# ETA Production Coding — S1 (read side + coding queue) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A coding queue of uncoded sold items, pre-marked by the owner's keep-out rule, where a person decides "code it" / "keep out" with a confirmed VAT rate; plus the read-only facts it needs (which codes ETA production already holds, the GPC May-2026 list) and two correctness fixes (recon "coded", preprod requests). Nothing is sent to ETA and no sheet is written in S1.

**Architecture:** New `coding_rule.py` (pure pre-mark function), `coding_queue.py` (queue rows, decide, reopen), `eta_codes.py` (production code-usage mirror via `EtaReader`), one new model `TaxCodingDecision`, one mirror model `EtaCodeUsage`, a new tab «طابور الترميز» in the tax-invoicing page. Reuses `TaxItemProfile`, `services.audit`, `EtaReader`, `EtaReconUncodedItem`, procurement `PurchaseLine` + `SupplierSegmentation`.

**Tech Stack:** Django 5 / DRF, PostgreSQL, React + Vite + react-query, vitest.

**Spec:** `docs/superpowers/specs/2026-11-16-eta-production-coding-design.md` (§4, §6, §8, §14 items 1, 2, 5, 6, 7, 8, 9, 10).

## Global Constraints

- Branch `claude/eta-production-coding`; worktree `.claude/worktrees/eta-production-coding`; python `../../../venv/Scripts/python.exe`.
- Tests: `TEST_DB_NAME=test_eta_coding_s1 ../../../venv/Scripts/python.exe manage.py test <labels> --keepdb` — serial, never `--parallel` (PC memory).
- No SOFTECH write; no ETA write; no new outward channel in S1.
- Decide / reopen need matrix action `approve` on module `tax_invoicing` (same as confirming a tax treatment); reading needs `view`.
- Exempt reference text, verbatim: `سلعة معفاة — قانون الضريبة على القيمة المضافة رقم 67 لسنة 2016، جدول الإعفاءات`
- Official supplier categories: `OFFICIAL_DISTRIBUTOR, DRUG_WAREHOUSE, MANUFACTURER, SMALL_WAREHOUSE`. Ignored: `PATIENT_REPURCHASE, CUSTOMER_REPURCHASE, SISTER_COMPANY, INTERNAL_TRANSFER, EXTERNAL_TRANSFER, CLEARING, SERVICE_VENDOR, FIXED_ASSET_SUPPLIER`. Everything else = other. Categories read as strings from live `SupplierSegmentation`.
- Purchase window: `PurchaseLine.doccode == '10'`, all rows held (from 2025-05-22).
- UI copy Arabic; «سيرفر» not «خادم»; never a bare branch code; every table sortable; grid keyboard via `useGridKeyboard`; help hint ≤ 160 chars.
- Migrations: next numbers after `0014_eta_recon_channel` — re-check `ls apps/tax_invoicing/migrations` before each `makemigrations`.

## Review Focus

1. A keep-out decision then a new official purchase → the row shows the hint but the decision stays keep-out (Task 6).
2. An item already confirmed by the accountant with a different VAT → deciding never overwrites it; the row is flagged and the decision records the accountant's rate (Task 6).
3. Two people deciding the same item at once → one decision row (1:1, `select_for_update`), the second gets a clear 409 (Task 7).
4. An item whose catalog row is missing (profile only) → the queue still lists it with "no purchase" and no crash (Task 6/7).
5. ETA's code-usage list paging stops early / returns 404 for "none" → mirror stores what it got, the probe reports "incomplete", nothing deleted (Task 5).

---

### Task 1: `services.confirm_treatment` (extract, no behaviour change)

**Files:** Modify `apps/tax_invoicing/services.py`, `apps/tax_invoicing/views.py:~452-469`; Test `apps/tests/test_tax_coding_queue.py` (new file, class `ConfirmTreatmentTests`).

**Interfaces — Produces:** `services.confirm_treatment(profile, *, treatment: str, vat_rate, reference: str, actor) -> None` — validates exactly as the view does today (unknown treatment → `TaxRuleError('معاملة ضريبية غير معروفة')`; taxable needs `0 < rate <= 100` → `'الصنف الخاضع يحتاج نسبة ضريبة'`; exempt/zero need reference → `'اذكر مرجع الإعفاء أو النسبة الصفرية'`), sets the five fields as today, does **not** save or audit (callers do). `_apply_item` calls it and turns `TaxRuleError` into the same 400 text.

- [ ] Step 1: tests — taxable 14 sets vat 14 + confirmed_at/by; exempt without reference raises; exempt with reference sets vat 0; unclassified clears confirmed_at.
- [ ] Step 2: run, expect FAIL (no attribute).
- [ ] Step 3: implement + switch the view.
- [ ] Step 4: run new tests + `apps.tests.test_tax_invoicing apps.tests.test_tax_coding` — PASS.
- [ ] Step 5: commit `refactor(tax): confirm_treatment service shared by the item screen and the coding queue`.

### Task 2: preprod requests stop touching the item; one open request per system

**Files:** Modify `apps/tax_invoicing/models.py` (`TaxCodeRequest.Meta.constraints`), `apps/tax_invoicing/coding.py` (`prepare`, `prepare_gs1`, `prepare_mirror`, `_mark_profile_pending`, `_apply_eta_answer`); migration `0015_code_request_per_system`; Test `apps/tests/test_tax_coding.py` (new class `PerSystemTests`).

**Interfaces — Produces:** `prepare(..., system: str = '')` / `prepare_gs1(..., system='')` / `prepare_mirror(..., system='')` set `environment` at prepare time (`system or environment.name()`). Helper `_touches_profile(row) -> bool` = `row.purpose != MIRROR and row.environment == 'production'`. `_mark_profile_pending` and the profile branch of `_apply_eta_answer` run only when it is True. Constraint `one_open_code_request_per_item_system` on (`profile`, `environment`) with the same open-status condition; old constraint dropped.

- [ ] Step 1: tests — (a) preprod `new` request approved → profile coding_status unchanged, request approved; (b) production approved → profile approved (existing behaviour); (c) an open preprod request + preparing production for the same item → both exist; (d) two open production → IntegrityError path returns skipped 'يوجد طلب مفتوح لهذا الصنف'.
- [ ] Step 2: FAIL. Step 3: implement + `makemigrations tax_invoicing -n code_request_per_system`. Step 4: PASS incl. whole `apps.tests.test_tax_coding`.
- [ ] Step 5: commit `fix(tax): test-system code requests no longer change the item's real coding`.

### Task 3: production recon counts "coded" as coded in the sheet

**Files:** Modify `apps/tax_invoicing/eta_recon.py:coded_items`; Test `apps/tests/test_eta_recon.py` (class `CodedItemsTests`).

**Interfaces — Produces:** `coded_items() -> set[str]` = itemcodes with `list_status='white'` and `eta_code != ''` and `coding_env == ''` (the owner's sheet import). Docstring: until S3's sheet versions exist, the 13-Nov workbook import is the sheet; S3 replaces the source.

- [ ] Step 1: tests — white workbook item counted; profile approved with `coding_env='preprod'` not counted; profile approved with `coding_env='production'` but `list_status='black'` not counted.
- [ ] Step 2 FAIL → Step 3 implement → Step 4 `apps.tests.test_eta_recon` PASS → Step 5 commit `fix(tax): receipts recon counts an item coded only when it is coded in the bulk EGS sheet`.

### Task 4: GPC May-2026 list (GS1 JSON) with definitions and source

**Files:** Modify `apps/tax_invoicing/models.py` (`TaxGpcBrick`: `source` CharField(20, default 'workbook', db_default), `definition` TextField(blank), `segment_code`/`family_code`/`class_code` CharField(8, blank), `segment_name`/`family_name`/`class_name` CharField(300, blank)); `apps/tax_invoicing/gpc.py` (`read_gs1_json(path) -> list[dict]`, `load_gs1(rows, version='gs1-20260520') -> dict`, `known(code, *, official_only=False)`); the `load_gpc_bricks` command gains `--gs1-json PATH`; migration `0016_gpc_brick_gs1`; Test `apps/tests/test_tax_coding.py` class `GpcGs1Tests` with a 2-segment fixture JSON written to a temp dir.

**Interfaces:** `read_gs1_json` walks GS1's JSON (`Schema` → Segment → Family → Class → Brick; keys `Code`, `Title`/`Description`, `Definition`, `Childs`) — tolerate both `Childs` and `children` and missing definitions. `load_gs1` upserts bricks with `source=version` and the hierarchy fields; never deletes; a brick already present from the workbook keeps its Arabic name and gets `source=version`. `known(code, official_only=True)` = exists with `source != 'workbook'`.

- [ ] Step 1: tests — fixture with brick 10005845 under 51000000/51160000/51160100 and one cosmetics brick; load twice = idempotent counts; workbook-only brick `known()` True, `known(official_only=True)` False; Arabic name preserved.
- [ ] Step 2 FAIL → Step 3 implement + migration → Step 4 PASS → Step 5 commit `feat(tax): load GS1's GPC list (May 2026) with definitions`.

### Task 5: what ETA production already holds (`EtaCodeUsage` mirror + probe)

**Files:** Create `apps/tax_invoicing/eta_codes.py`, `apps/tax_invoicing/management/commands/eta_code_usages.py`; Modify `models.py` (`EtaCodeUsage`), `history_views.py` or `views.py` (one GET endpoint), `urls.py` (`codes/eta-holds/`); migration `0017_eta_code_usage`; Test `apps/tests/test_eta_codes.py`.

**Interfaces — Produces:**
- Model `EtaCodeUsage(system, code_type, item_code, code_name, active_from (date, null), active_to (date, null), status (str 30), gpc (str 10), itemcode (str 10, blank — our SOFTECH code when matched), fetched_at)`; unique (`system`, `code_type`, `item_code`).
- `eta_codes.fetch(system='production', *, page_size=100, max_pages=2000) -> dict` — `EtaReader(system).get('/api/v1.0/codetypes/requests/my', {'Ps': page_size, 'Pn': n, 'OrderDirections': 'Descending'})` until an empty page; 404 = no rows; upserts; returns `{'pages', 'rows', 'complete': bool, 'error'}`. Requires `EtaReader(system).enabled()`.
- `eta_codes.match(system) -> int` — EGS `EG-<issuer tax id>-<itemcode>` → itemcode; GS1 → `ItemBarcode.barcode` → item softech_id. Sets `itemcode`.
- `eta_codes.report(system) -> dict` — `{'on_eta_not_in_sheet': [...], 'in_sheet_not_on_eta': [...], 'counts': {...}}`, "in the sheet" = `coded_items()` (Task 3); only approved/active usages count as "on ETA".
- Command `eta_code_usages --system production [--probe]` — `--probe` fetches 1 page and prints the row shape and total if ETA returns one, writes nothing.
- Endpoint GET `/api/tax-invoicing/codes/eta-holds/?system=production` (VIEWER) → `report()`.

- [ ] Step 1: tests with a fake reader: 2 pages + empty → complete; 404 first page → 0 rows complete; exception mid-way → stored rows kept, `complete False`; EGS and GS1 matching; report buckets; endpoint 403 for pharmacist.
- [ ] Step 2 FAIL → Step 3 implement → Step 4 PASS → Step 5 commit `feat(tax): mirror the item codes ETA production holds and compare with the sheet`.
- [ ] Step 6 (office, read-only, after merge — not in CI): `eta_code_usages --system production --probe`; report the shape to the owner before a full fetch.

### Task 6: the keep-out rule, VAT prefill/flag, and the decision model

**Files:** Create `apps/tax_invoicing/coding_rule.py`, `apps/tax_invoicing/coding_queue.py`; Modify `models.py` (`TaxCodingDecision`); migration `0018_coding_decision`; Test `apps/tests/test_tax_coding_queue.py` (classes `RuleTests`, `VatTests`, `DecisionTests`).

**Interfaces — Produces:**
- `coding_rule.OFFICIAL`, `coding_rule.IGNORED` (frozensets, Global Constraints values).
- `coding_rule.purchase_sources(itemcodes) -> dict[str, Counter]` — category → qty, from `PurchaseLine` doccode 10 grouped by supplier, category from live `SupplierSegmentation` (missing → 'UNKNOWN'), ignored categories dropped.
- `coding_rule.premark(item, sources: Counter | None) -> tuple[str, str, str]` → `(premark, reason_code, note)`; premark ∈ `'code' | 'keep_out' | ''`; reason codes and notes exactly:
  1. `services` — medicine type starts with 'Services' or `is_stockable is False` or 'هدايا' in medicine type → `keep_out`, «خدمة / هدية — لا تُكوَّد حالياً»
  2. `official` — any of OFFICIAL minus SMALL_WAREHOUSE → `code`, «اشتُري من موزع أو مخزن أو مصنع»
  3. `small_warehouse_only` → `code`, «اشتُري من مخازن صغيرة فقط — تأكد من تسجيله (هيئة الدواء / سلامة الغذاء)»
  4. `unofficial_only` → `keep_out`, «لم يُشترَ من موزع أو مخزن أو مصنع»
  5. `no_purchase` (sources empty/None) → `''`, «لا مشتريات معتبرة منذ مايو 2025»
  `item=None` (no catalog row) → treated as case 5 unless sources say otherwise.
- `coding_rule.vat_prefill(item, profile) -> tuple[Decimal, bool, str]` → `(rate, flagged, why)`: if profile treatment confirmed → `(profile.vat_rate, False, 'confirmed')`; else rate = `item.sale_tax_pct or 0`; flagged when (medicine type in Cosmetics/Others/Body Building and rate == 0) or (Medicine and rate == 14) or rate not in {0, 14}.
- Model `TaxCodingDecision`: `profile` OneToOne(TaxItemProfile, PROTECT, related_name='coding_decision'); `decision` ('code'|'keep_out'); `premark`, `premark_reason` (str 30); `vat_rate` Decimal(5,2) null; `vat_flagged` bool; `code_name`, `code_name_ar` (200), `description`, `description_ar` (300); `brick` (str 8, blank), `brick_source` (str 15, blank); `note` (300); `decided_by` FK user; `decided_at`; `reopened_by`, `reopened_at`, `reopen_reason`. (AI fields come in S2.)
- `coding_queue.decide(profile_id, actor, *, decision, vat_rate=None, names=None, note='') -> TaxCodingDecision`:
  - `select_for_update` on the profile; an existing non-reopened decision → `TaxRuleError('للصنف قرار سابق — أعد فتحه أولاً')` (view → 409).
  - `decision='code'` needs `vat_rate` in {0, 14}; if the profile's treatment is already confirmed, `vat_rate` must equal it, else `TaxRuleError('النسبة تخالف المعاملة المعتمدة من المحاسب')`; when not confirmed, calls `services.confirm_treatment` with taxable/14 or exempt/0 + the exempt reference text, saves the profile.
  - names default to the catalog/profile name (both EN and AR fields, description = name).
  - audits `coding_decision` (before/after) — and `item_mapping_changed` when the treatment was set.
  - `keep_out` touches nothing on the profile.
- `coding_queue.reopen(profile_id, actor, reason)` — reason required; clears decision fields into `reopened_*` (the row is kept, `decision=''`), audited `coding_decision_reopened`.

- [ ] Step 1: tests — one per rule row (5) + "ignored-only purchases = no_purchase" + "official beats unofficial"; VAT: cosmetic at 0 flagged, medicine at 14 flagged, 13 flagged, confirmed profile wins; decide code 14 on unconfirmed → profile taxable 14 confirmed; decide code 0 → exempt with the exact reference text; decide on accountant-confirmed 14 with 0 → error; decide twice → error; keep_out leaves profile unchanged; reopen without reason → error; audit rows written.
- [ ] Step 2 FAIL → Step 3 implement + migration → Step 4 PASS → Step 5 commit `feat(tax): keep-out rule, VAT prefill and the coding decision record`.

### Task 7: queue API

**Files:** Modify `coding_queue.py` (`rows`), `views.py`, `urls.py`; Test `test_tax_coding_queue.py` class `QueueApiTests`.

**Interfaces — Produces:**
- `coding_queue.rows(*, recent_days: int | None = None, premark=None, decided=None, q='') -> list[dict]` — candidates = profiles with production sales in `EtaReconUncodedItem` (system production; `recent_days` filters `day >= today - n`) (items with no profile get one through the existing POST `codes/add-from-catalog/` button, shown on the queue tab when `coding._catalog_without_profile().exists()`; never on page load), excluding `coding_status in ('approved','pending')` with `coding_env in ('', 'production')`, and excluding itemcodes in `EtaCodeUsage` approved/active. Each row: `itemcode, name, value, docs, last_day, premark, premark_reason, note, sources {category: qty}, vat_rate, vat_flagged, vat_why, decision (or null), decided_by, decided_at`. Sorting/paging in the view.
- GET `/api/tax-invoicing/codes/queue/` (VIEWER) params `recent`, `premark`, `decided` ('yes'|'no'), `q`, `ordering` (whitelist: `value, docs, last_day, itemcode, premark` with `-`), `page` (size 100) → `{count, page, pages, total_value, rows}`.
- POST `/api/tax-invoicing/codes/queue/decide/` (APPROVER) body `{itemcodes: [..≤200], decision, vat_rate?, names?, note?}` → `{decided: [...], skipped: [{itemcode, why}]}`; a single-item 409 when that one item already has a decision. Bulk with `decision='code'` uses each row's prefilled rate and skips flagged rows with why «النسبة تحتاج تأكيداً».
- POST `/api/tax-invoicing/codes/queue/reopen/` (APPROVER) `{itemcode, reason}`.

- [ ] Step 1: tests — ordering biggest first; recent filter; decided filter; pharmacist 403 on GET, accountant 200; accountant decide works, viewer-only role 403; bulk skips flagged; already-decided → skipped (bulk) / 409 (single); item coded on ETA (EtaCodeUsage) not listed; profile with no catalog row listed with `no_purchase`.
- [ ] Step 2 FAIL → Step 3 implement → Step 4 PASS → Step 5 commit `feat(tax): coding queue API`.

### Task 8: «طابور الترميز» tab, «ما لدى المصلحة» panel, help

**Files:** Create `frontend/src/pages/taxinvoicing/QueueTab.jsx`; Modify `frontend/src/pages/TaxInvoicingPage.jsx` (tab key `queue`, label «طابور الترميز», after the codes tab), `frontend/src/api/…` tax-invoicing api module (`codingQueue`, `codingDecide`, `codingReopen`, `etaHolds`), `apps/help/content/tax_invoicing.py` (tab entry + targets `tax-invoicing-queue-grid`, `tax-invoicing-queue-eta-holds`, `updated: '2026-11-16'`, change_note), `frontend/src/pages/taxinvoicing/taxinvoicing.test.jsx`.

**UI:** grid columns الصنف · المبيعات بلا كود · آخر بيع · المصدر (sources summary) · المقترح (pre-mark + note) · الضريبة (rate, red when flagged) · القرار; filters المقترح / القرار / آخر 90 يوماً / بحث; `useServerSort`; `useGridKeyboard` (↑↓ Space Enter M Ctrl+A) — Enter = accept pre-mark for the selection (code → «كوّد», keep_out → «استبعد»), C = كوّد, K = استبعد; per-row VAT select (0 / 14) before deciding a flagged row; «إعادة فتح» with a reason input inline (no modal). Panel «ما لدى المصلحة» (collapsible): counts + list of "on ETA, not in the sheet". Decide buttons hidden without `approve`, but the server is the gate.

- [ ] Step 1: vitest — renders rows biggest first; flagged row's bulk-accept disabled; pressing K on a selected row calls `codingDecide` with `keep_out`; help test passes (`apps.tests.test_help`).
- [ ] Step 2 FAIL → Step 3 implement → Step 4 `npx vitest run src/pages/taxinvoicing` + `npm run build` + `apps.tests.test_help` PASS → Step 5 commit `feat(tax): coding queue screen`.

### Task 9: verification + docs

- [ ] Doc 36: section «طابور الترميز» (rule table, VAT rule, ETA-holds mirror) + link to the spec.
- [ ] Run serially: `apps.tests.test_tax_coding apps.tests.test_tax_coding_queue apps.tests.test_eta_codes apps.tests.test_eta_recon apps.tests.test_tax_invoicing apps.tests.test_help`, then `apps.tests.security` (module access + permission sweeps), `flake8`/`ruff` as CI, `npm run build`.
- [ ] Re-run the §4.2 counts on the office DB (read-only script) and put the new numbers in the PR body.
- [ ] Commit, push, open PR; merge by hand only when every check is green.
