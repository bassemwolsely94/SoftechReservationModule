# Usage-Instructions Print Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pharmacist opens a sale by invoice number, confirms one usage instruction per line (suggested deterministically), and prints an 80 mm slip; everything audited, flag OFF by default.

**Architecture:** New app `apps/usage_print` (models, lookup, suggestions, views). Invoice comes from the `PurchaseHistory` mirror (`softech_invoice_id = f"{branchcode}-115-{docnumber}-{YYYYMMDD}"`), else a bounded read-only live SOFTECH query (selling branch node → HQ). React page `/usage-print` renders and prints via a popup window like `ReceiptPrint.jsx`.

**Tech Stack:** Django 5 / DRF, PostgreSQL, `config/sybase.py` (read-only), `qrcode` (already a dependency), React 18 + Tailwind + TanStack Query.

**Spec:** `docs/superpowers/specs/2026-11-03-usage-instructions-print-design.md`

## Global Constraints

- `USAGE_PRINT_ENABLED = config('USAGE_PRINT_ENABLED', default=False, cast=bool)` in `config/settings.py`. OFF ⇒ every `/api/usage-print/` endpoint 404, `can_usage_print` false on `/api/auth/me/`, menu hidden.
- SOFTECH read-only; invoice identity always (branch, doccode '115', docnumber, docdate). Ints only in SQL (cast with `int()`), date as `YYYYMMDD` from a `date`.
- Branch scoping via `core.branch_scope` (`allows_code`, `scope`).
- RBAC module `usage_print`: `view` open sheets, `create` confirm + print + attach, `edit` presets + slip settings. Seed: pharmacist, salesperson → view/create; supervisor → view/create/edit. Admin bypasses.
- Print refused (409) while any line is `pending`.
- Audit actions (`AuditLog.log`): `usage_line_confirmed`, `usage_line_excluded`, `usage_sheet_printed` (label «طريقة الاستخدام — طلب طباعة»), `usage_rx_attached`, `usage_settings_changed`.
- Suggestion sources (codes): `patient_last`, `item_common`, `curated`, `none`. Curated = `apps.counselling.selectors.approved_usage_text(item) -> str | None` if importable, else None. Never `enrichment.ItemEnrichment`.
- Real named customer = `PurchaseHistory.softech_phcode` non-empty and equals `customer.softech_pic`.
- Arabic RTL; help screen `pos.usage_print` added to `apps/help/content/pos.py` with `updated: '2026-11-03'`.

## Review Focus

1. Same docnumber at another branch / another day → must never open the wrong invoice (test: two mirror invoices same number, different branch → each lookup returns its own).
2. Editing the text of a confirmed line → it must go back to `pending` (test in Task 3).
3. User from branch A types a branch-B invoice → 403, no SOFTECH read (test in Task 3).
4. SOFTECH unreachable / gate denied on live fetch → 503 with calm Arabic message, no 500 (test in Task 2 with a raising fake connection).
5. Invoice that is a return (doccode 30) or has zero lines → «الفاتورة غير موجودة» 404, no sheet created (test in Task 2).

---

### Task 1: App skeleton, flag, models, RBAC, audit actions

**Files:** Create `apps/usage_print/{__init__,apps,models,access,admin}.py`, `apps/usage_print/migrations/0001_initial.py`, `0002_seed.py` (RBAC grants + preset seed). Modify `config/settings.py` (flag + INSTALLED_APPS), `apps/users/models.py` MODULE_CHOICES (+ migration), `apps/users/management/commands/seed_permissions.py`, `apps/audit/models.py` ACTION_CHOICES (+ migration), `apps/users/views.py` (`can_usage_print`).

**Produces:**
- `UsagePreset(kind ∈ amount|frequency|timing|phrase, text, sort_order, is_active)`
- `UsageSheet(branch FK, doccode='115', docnumber str, docdate date, softech_invoice_id unique, purchase FK→PurchaseHistory null, customer FK null, patient_name, pos_order FK→SoftechSalesOrder null, prescription_image ImageField null, invoice_changed bool, print_count int, last_printed_at/by, last_layout, created_by, created_at, source ∈ mirror|live)`
- `UsageSheetLine(sheet FK, item FK null, itemcode, item_name, quantity Decimal, suggested_text, suggestion_source, text, status ∈ pending|confirmed|excluded, confirmed_by, confirmed_at)`; unique (sheet, itemcode).
- `access.Access(user)` with `can_view/can_create/can_edit`; `access.can_open(user)` = flag ON and can_view.
- Slip settings in `SystemSetting` keys `usage_print.footer_text`, `usage_print.hotline`, `usage_print.whatsapp`, `usage_print.qr_url`, `usage_print.qr_caption` (empty = block hidden).

- [ ] Write models + migrations; `python manage.py makemigrations --check` clean afterwards.
- [ ] Commit.

### Task 2: Invoice lookup (mirror → live)

**Files:** Create `apps/usage_print/lookup.py`, `apps/tests/test_usage_print.py`.

**Produces:** `find_invoice(branch: Branch, docnumber: int, docdate: date) -> InvoiceData | None` where `InvoiceData` = dataclass(`invoice_id, branch, docnumber, docdate, customer, patient_name, lines: list[(itemcode, item, qty)], source, purchase`); raises `LiveUnavailable` when the mirror misses and SOFTECH can't be reached. Lines aggregated per itemcode (multi-batch rows summed). Live: `get_branch_connection(branch.effective_db_host, branch.effective_db_port)` then `get_sybase_connection()`; single query on stktrans⋈stktransm bounded by branchcode, doccode '115', docnumber, docdate; timeout 15 s; no PurchaseHistory writes.

Tests: `test_mirror_hit_by_branch_and_date` (same number in two branches → correct one), `test_return_doc_not_found`, `test_live_used_when_mirror_misses` (patched connection returns rows → InvoiceData source 'live'), `test_live_unreachable_raises`.

### Task 3: Sheets, suggestions, confirm, print, attach, presets (API)

**Files:** Create `apps/usage_print/{services,suggest,slip,serializers,views,urls}.py`; modify `config/urls.py` (`api/usage-print/`), `apps/pos_orders/views.py` (extract `validate_prescription_image(f) -> str | None`, reused by both).

**Produces endpoints:**
- `GET /api/usage-print/sheet/?branch=<code>&number=<int>&date=YYYY-MM-DD` → sheet JSON (lines with suggestion + source, rx image url, patient, invoice_changed, presets, perms). 404 not found, 403 branch, 503 live unavailable, 400 date older than 7 days.
- `POST /api/usage-print/lines/<id>/` `{action: confirm|exclude|reset, text}` → line JSON. Confirm needs non-empty text; any text change on a confirmed line → pending.
- `POST /api/usage-print/sheets/<id>/print/` `{layout: single|per_item}` → 409 if pending; else slip payload `{header, invoice, patient_name, items:[{name, text}], footer_blocks:[...], qr_svg}` + stamps + audit.
- `POST /api/usage-print/sheets/<id>/prescription/` multipart.
- `GET/PUT /api/usage-print/settings/` presets + slip settings (PUT needs `edit`).

`services.open_sheet(invoice, user) -> UsageSheet` re-syncs lines: unchanged itemcode+qty keep status; new or qty-changed → pending; removed → deleted; sets `invoice_changed`. `suggest.suggest_for(item, customer) -> (text, source)` in the fixed order.

Tests: flag off → 404; scoping 403; suggestion order (patient_last beats item_common beats none); edit-unconfirms; print 409 with pending, 200 after confirm/exclude with audit row and print_count=1; reprint increments; reopen with changed invoice flags + pending; rx upload rejects >12 MB / pdf; settings PUT forbidden for salesperson.

### Task 4: Frontend page + slip print

**Files:** Create `frontend/src/pages/UsagePrintPage.jsx`, `frontend/src/components/UsageSlipPrint.js`; modify `frontend/src/api/client.js` (`usagePrintApi`), `frontend/src/App.jsx` (route `usage-print`), `frontend/src/components/Layout.jsx` (nav item `cap: 'can_usage_print'`).

Page: number field (autofocus, Enter = open), branch select (allowed branches), date (today, ≤7 days back); lines list: item name + qty, source tag, text input, chip rows (amount/frequency/timing append to text) + phrase chips, ✓ / «لا يطبع»; layout toggle (one slip / per item); print button (F9) disabled while pending; rx thumbnail or attach button. Tab «القوالب والإعدادات» for `edit`. `data-tour` anchors `usage-print-*`.

### Task 5: Help, checks, commit

- [ ] Add `pos.usage_print` screen in `apps/help/content/pos.py` (AR+EN, tabs `print`, `settings`, `updated: '2026-11-03'`); page calls `useHelpTab(tab)`.
- [ ] Run `python manage.py test apps.tests.test_usage_print apps.tests.test_help apps.tests.test_pos_prescription` (unique TEST_DB_NAME), `npm run lint`, `npm run build`.
- [ ] Commit on branch; report.
