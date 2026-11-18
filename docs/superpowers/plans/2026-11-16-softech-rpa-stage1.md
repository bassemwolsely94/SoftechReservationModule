# SOFTECH Screen RPA — Stage 1 (foundation + إذن الصرف dry-run) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An operator uploads an إذن الصرف للفروع (doc 125) Excel sheet into `/rpa`. It is matched and
then approved by a second person. A Windows agent on the operator's own PC then types the lines into
their open SOFTECH screen in **dry-run** (it types everything, then cancels without saving), with a
step log and screenshots, and a server-side verifier that can find a saved 125 in SOFTECH.

**Architecture:** A new Django app `apps/rpa` owns the whole flow:
- jobs, documents and lines;
- recipes imported from DataLoad `.dld` files;
- four-eyes approvals;
- the server-built **keyplan** (the exact keystrokes);
- device tokens tied to a StaffProfile;
- the agent API;
- a read-only SOFTECH verifier.

A separate desktop package `rpa_agent/` (pywinauto, tkinter) only executes keyplans, so all business
rules stay in the backend (CLAUDE.md rule 7). Nothing in Stage 1 can save a SOFTECH document. Live
saving is Stage 2: a recipe `save_keys` + the switch + `RpaScreen.live`.

**Tech Stack:** Django 4.2/DRF, PostgreSQL, openpyxl, `config/sybase.py` (read only), React 18 +
TanStack Query, Python 3 + pywinauto + pynput + requests on Windows for the agent.

**Spec:** `docs/superpowers/specs/2026-11-16-softech-screen-rpa-design.md`

## Global Constraints

- Switch `RPA_SOFTECH_ENTRY_ENABLED`: default **False**, read only through
  `config.writers.writer_allowed('RPA_SOFTECH_ENTRY_ENABLED')`, listed in `WRITER_FLAGS` with
  protects `'روبوت إدخال SOFTECH (إذن صرف، جرد، مشتريات، مرتجع)'`.
- Stage 1 never saves: `RpaJob.dry_run` defaults True and the API refuses `dry_run=False` while no
  `RpaScreen.live` is True (no screen is live in Stage 1).
- The SOFTECH reference typed or matched is `f"RPA-{document.pk}"`. The SOFTECH note column is
  `stktransm.comments` (varchar 100).
- The robot never logs in to SOFTECH and never stores SOFTECH passwords.
- Uploader ≠ approver for jobs. Recipe creator ≠ recipe approver.
- Unknown popup, focus lost, wrong window title or timeout → stop, screenshot, and the document goes
  to `needs_person`. It never goes back to the queue automatically.
- Verifier: SOFTECH is read live via `config.sybase.get_branch_connection(branch.effective_db_host, …)`,
  never a mirror. It compares typed fields only, with no totals.
- Module key `rpa`, API prefix `/api/rpa/`, screen `/rpa`, Arabic title «روبوت الإدخال».
- Help text is in Arabic and English with `updated: '2026-11-16'`.
- Never write SOFTECH SQL in `apps/rpa`. Its files that import `config.sybase` hold only SELECT
  strings, with no `insert into` / `update … set` / `select … into` text, because
  `static_scan._WRITE_SQL` would flag them.

## Review Focus

1. **Messy sheets:**
   - Arabic or English headers.
   - Trailing blank rows (the owner's `.dld` grids carry many empty rows).
   - The same item on two rows.
   - qty as `5.0` / `"5"`.
   - Expiry as an Excel date, as `1/5/25`, or blank.

   Expect: blanks are skipped; duplicates are kept as separate lines with a warning; numbers are
   normalised; an unparseable expiry is a line error that blocks approval. Test in Task 4.
2. **The agent dies between typing and reporting.** The document must not stay `in_progress` forever
   or be re-queued. When its lease expires it goes to `needs_person`. Test in Task 8.
3. **The SOFTECH window is not the recipe's window** (another screen open, a title with extra
   spaces). Expect the agent to type nothing and report `wrong_window`. Test in Task 11.
4. **Typed values containing send-keys specials** (`+ ^ % ~ ( ) { } [ ]`). Expect them to be
   escaped, so they are typed literally. Test in Task 7.
5. **The wrong person's PC claims work.** A device whose staff did not upload the job gets nothing.
   A revoked device gets a 401. Two concurrent claims never return the same document. Test in Task 8.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/rpa/models.py` | RpaScreen, RpaRecipe, RpaJob, RpaDocument, RpaLine, RpaRun, RpaScreenshot, RpaDevice |
| `apps/rpa/dld.py` | Parse a DataLoad `.dld` → `DldTemplate`; make a recipe from it |
| `apps/rpa/sheet.py` | Parse an issue sheet (xlsx/csv) → rows |
| `apps/rpa/matching.py` | Rows → RpaLine with Item match + errors |
| `apps/rpa/workflow.py` | create_job, approve_job, cancel_job, approve_recipe, claim_next, report_run, resolve_document |
| `apps/rpa/keyplan.py` | `to_send_keys`, `build_keyplan` |
| `apps/rpa/identity.py` | `expected_softech_usercode(profile)` |
| `apps/rpa/verifier.py` | Read-only SOFTECH lookup of a saved 125 |
| `apps/rpa/auth.py` | `RpaDeviceAuthentication` (header `X-ElR-RPA-Agent`), `issue_device` |
| `apps/rpa/serializers.py`, `views.py`, `agent_views.py`, `urls.py` | Staff API + agent API |
| `apps/help/content/rpa.py` | In-app help |
| `frontend/src/pages/RpaPage.jsx` + `frontend/src/pages/rpa/*.jsx` | `/rpa` screen |
| `rpa_agent/` | Windows agent: `client.py`, `driver.py`, `runner.py`, `overlay.py`, `main.py`, `tests/` |
| `apps/tests/test_rpa_*.py` | Backend tests |

---

### Task 1: Module wiring (app, permissions, switch, audit actions)

**Files:**
- Create: `apps/rpa/__init__.py`, `apps/rpa/apps.py`, `apps/rpa/urls.py` (empty `urlpatterns`)
- Modify:
  - `config/settings.py`: INSTALLED_APPS, and `RPA_SOFTECH_ENTRY_ENABLED = config('RPA_SOFTECH_ENTRY_ENABLED', default=False, cast=bool)` next to `CUSTOMER_MERGE_WRITE_ENABLED`
  - `config/writers.py` `WRITER_FLAGS`
  - `config/urls.py`: `path('api/rpa/', include('apps.rpa.urls'))`
  - `apps/users/models.py` `MODULE_CHOICES`: `('rpa', 'روبوت الإدخال')`
  - `apps/users/management/commands/seed_permissions.py` `ALL_MODULES` + `PERMISSIONS`
  - `core/middleware/module_access.py` `MODULE_BY_PREFIX`: `'rpa': 'rpa'`
  - `apps/tests/security/permission_matrix.py` `BRANCH_SCOPE`: `'rpa': 'branch — jobs scoped by RpaJob.branch via core.branch_scope; recipes/devices company-level (admin)'`
  - `apps/audit/models.py` `ACTION_CHOICES`: `rpa_job_uploaded`, `rpa_job_approved`, `rpa_job_cancelled`, `rpa_recipe_imported`, `rpa_recipe_approved`, `rpa_device_issued`, `rpa_device_revoked`, `rpa_document_claimed`, `rpa_run_reported`, `rpa_document_needs_person`, `rpa_document_resolved`, `rpa_document_verified`
  - `.env.example`: `RPA_SOFTECH_ENTRY_ENABLED=False`
- Create migrations: `apps/users/migrations/00NN_rpa_module.py`, copying `0057_crews_module.py` (AlterField choices + RunPython seed), and the audit choices migration.
- Test: `apps/tests/test_rpa_module.py`

**Grants:**

| Role | Actions |
|---|---|
| admin | all |
| supervisor | view, create, approve, edit |
| purchasing | view, create |
| quality_manager | view, create, approve |
| everyone else | none |

`create` = upload / run on my PC. `approve` = approve jobs and recipes. `edit` = resolve a needs_person
document.

- [ ] **Step 1: Write the failing tests**

```python
class RpaModuleWiringTests(TestCase):
    def test_flag_defaults_off_and_is_a_writer_flag(self):
        from config.writers import WRITER_FLAGS, writer_allowed
        self.assertIn('RPA_SOFTECH_ENTRY_ENABLED', WRITER_FLAGS)
        self.assertFalse(settings.RPA_SOFTECH_ENTRY_ENABLED)
        self.assertFalse(writer_allowed('RPA_SOFTECH_ENTRY_ENABLED'))

    def test_prefix_maps_to_module(self):
        from core.middleware.module_access import MODULE_BY_PREFIX
        self.assertEqual(MODULE_BY_PREFIX['rpa'], 'rpa')

    def test_seed_grants(self):
        # import the seed migration via importlib like test_crews_api.py:361, run it
        self.assertTrue(RoleModuleAccess.objects.get(role='supervisor', module='rpa', action='approve').is_allowed)
        self.assertFalse(RoleModuleAccess.objects.filter(role='call_center', module='rpa', is_allowed=True).exists())
```

- [ ] **Step 2:** Run `venv/Scripts/python.exe manage.py test apps.tests.test_rpa_module --noinput`. Expected: FAIL (KeyError / ImportError).
- [ ] **Step 3:** Make the wiring changes above and run `makemigrations users audit`.
- [ ] **Step 4:** Regenerate the matrix: `venv/Scripts/python.exe manage.py shell -c "from apps.tests.security.permission_matrix import write; write()"`.
- [ ] **Step 5:** Run `manage.py test apps.tests.test_rpa_module apps.tests.security.test_permission_matrix --noinput`. Expected: PASS.
- [ ] **Step 6:** Commit `feat(rpa): module wiring, permissions, switch (off)`.

---

### Task 2: Models

**Files:**
- Create: `apps/rpa/models.py`, `apps/rpa/migrations/0001_initial.py`, `apps/rpa/admin.py`
- Modify: `apps/data_lifecycle/register.py`. Register `RpaScreenshot.image` with 180-day retention, following an existing file-field entry there.
- Test: `apps/tests/test_rpa_models.py`

**Interfaces (Produces):**
- `RpaScreen`
  - `key` CharField unique, choices `issue_125` / `stockcount` / `purchase_10` / `return_120`
  - `title_ar`
  - `enabled` bool default False
  - `live` bool default False (False = dry-run only)
  - Data migration seeds the four rows, all False.
- `RpaRecipe`
  - FKs: `screen`
  - Fields:
    - `version` int, with `UniqueConstraint(screen, version)`
    - `status` draft / approved / retired
    - `window_title` str
    - `cell_delay` Decimal default 0.2
    - `form_delay` Decimal default 0.25
    - `header_checklist` JSON (list of Arabic strings the operator confirms before start)
    - `line_cells` JSON (list of `{"kind": "keys"|"field", "value": str}`)
    - `ref_cells` JSON
    - `save_keys` JSON
    - `cancel_keys` JSON
    - `popups` JSON (list of `{"title_contains": str, "text_contains": str, "answer_keys": str}`; empty = every popup stops)
    - `source_filename`
    - `created_by` FK StaffProfile
    - `approved_by` FK StaffProfile null
    - `approved_at`
  - `save()` raises `ValidationError('recipe is immutable once approved')` when an approved row's content fields change.
- `RpaJob`
  - FKs: `screen`, `branch` (FK Branch, supplying), `target_branch` (FK Branch null), `recipe` (FK, frozen at approval), `created_by`, `approved_by`
  - Fields:
    - `store_code` str
    - `source_kind` excel / distribution_plan / reshuffle (Stage 1 uses excel)
    - `source_ref` str
    - `filename`, `upload_sha256` (indexed)
    - `status` uploaded / approved / cancelled / done
    - `dry_run` bool default True
    - `approved_at`, `created_at`
- `RpaDocument`
  - FKs: `job` (`related_name='documents'`), `claimed_by` (FK RpaDevice null)
  - Fields:
    - `seq` int
    - `status` pending / approved / in_progress / dry_run_ok / posted / needs_person / cancelled
    - `claimed_at`, `lease_until`
    - `softech_docnumber` int null
    - `verify_result` JSON
    - `needs_person_reason` str
  - Property `reference` → `f"RPA-{self.pk}"`.
- `RpaLine`
  - FKs: `document` (`related_name='lines'`), `item` (FK catalog.Item null)
  - Fields:
    - `row_no` int
    - `raw` JSON
    - `itemcode` str
    - `qty` Decimal(12, 5)
    - `expiry` date null
    - `status` matched / unmatched / error
    - `message` str
    - `warning` str
- `RpaDevice`
  - FKs: `staff` (FK StaffProfile, `related_name='rpa_devices'`), `created_by`
  - Fields: `label`, `token_hash` unique, `created_at`, `last_seen_at` null, `revoked_at` null
- `RpaRun`
  - FKs: `document` (`related_name='runs'`), `device`, `recipe`
  - Fields:
    - `mode` dry_run / live
    - `started_at`, `finished_at` null
    - `outcome`: '' / dry_run_ok / saved / stopped_by_operator / wrong_window / unknown_popup / timeout / error
    - `steps` JSON (list of `{"i": int, "label": str, "at": iso, "ok": bool, "note": str}`)
- `RpaScreenshot`
  - FKs: `run` (`related_name='shots'`)
  - Fields: `step_index` int, `image` ImageField(`upload_to='rpa/%Y/%m/'`), `created_at`

- [ ] **Step 1: Write the failing tests**
  - `test_screens_seeded_off`: 4 screens, all `enabled=False, live=False`.
  - `test_reference_format`: `doc.reference == f'RPA-{doc.pk}'`.
  - `test_approved_recipe_is_immutable`: change `line_cells` on an approved recipe → `ValidationError`.
- [ ] **Step 2:** Run `manage.py test apps.tests.test_rpa_models --noinput`. Expected: FAIL.
- [ ] **Step 3:** Write the models and `makemigrations rpa`, then add the seed RunPython for the screens.
- [ ] **Step 4:** Run the tests above plus `apps.tests.test_data_lifecycle*`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa): models`.

---

### Task 3: DataLoad `.dld` parser and recipe import

**Files:**
- Create: `apps/rpa/dld.py`, `apps/tests/fixtures/rpa/issue_125.dld`. The fixture is the owner's `Dataload اذن الصرف.dld` trimmed to its delays, header, other block and the first 5 data rows plus 2 blank rows.
- Test: `apps/tests/test_rpa_dld.py`

**Interfaces (Produces):**
- `@dataclass DldTemplate`, with fields:
  - `window_title: str`
  - `cell_delay: Decimal`
  - `form_delay: Decimal`
  - `column_kinds: list[str]` (`'keys'|'data'`, from the `Key Strokes` / `Data` header line)
  - `rows: list[list[str]]` (non-blank data rows only)
- `parse_dld(text: str) -> DldTemplate`. Strip the BOM. Sections are `begindelays/enddelays`, `beginheader/endheader` (the first line is the kinds), `beginother/endother` (`Window=`) and `begindata/enddata`. Cut trailing empty columns. Raise `ValueError` on a missing `Window=`.
- `recipe_from_dld(template, *, screen, field_map: list[str], created_by) -> RpaRecipe`. Each `data` column is mapped in order to `field_map` (for 125: `['itemcode', 'expiry', 'qty']`). Each `keys` column takes its value from the template's **first non-blank row**. The result is a draft recipe at version = max + 1, with `source_filename` set, and audit `rpa_recipe_imported`.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_owner_issue_template(self):
    t = parse_dld(FIXTURE.read_text(encoding='utf-8-sig'))
    self.assertEqual(t.window_title, 'SofTech Smart Business® - MINI - [إذن صـرف للفــروع]')
    self.assertEqual(t.cell_delay, Decimal('0.2'))
    self.assertEqual(t.column_kinds, ['keys','data','keys','keys','keys','data','keys','data','keys','keys','keys'])
    self.assertEqual(t.rows[0], [r'\{F2}','52',r'\{ENTER}',r'\{ENTER}',r'\{TAB}','1/5/25',r'\{TAB}','1',r'\{ENTER}',r'\{ENTER}',r'\{ENTER}'])
    self.assertEqual(len(t.rows), 5)          # blank rows dropped

def test_recipe_from_template_maps_fields_in_order(self):
    r = recipe_from_dld(t, screen=issue, field_map=['itemcode','expiry','qty'], created_by=p)
    self.assertEqual(r.line_cells[1], {'kind':'field','value':'itemcode'})
    self.assertEqual(r.line_cells[5], {'kind':'field','value':'expiry'})
    self.assertEqual(r.line_cells[7], {'kind':'field','value':'qty'})
    self.assertEqual(r.status, 'draft'); self.assertEqual(r.version, 1)

def test_field_map_length_must_equal_data_columns(self):  # ValueError
def test_missing_window_raises(self):                     # ValueError
```

- [ ] **Step 2:** Run `manage.py test apps.tests.test_rpa_dld --noinput`. Expected: FAIL.
- [ ] **Step 3:** Implement `dld.py`.
- [ ] **Step 4:** Run again. Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa): DataLoad .dld parser and recipe import`.

---

### Task 4: Issue sheet parse, matching and job creation

**Files:**
- Create: `apps/rpa/sheet.py`, `apps/rpa/matching.py`, `apps/rpa/workflow.py` (`create_job` only here)
- Test: `apps/tests/test_rpa_sheet.py`

**Interfaces:**
- Consumes: `apps.catalog.item_columns.load_items(codes=...) -> {softech_id: Item}`, `core.upload_safety.sha256_of`, `core.upload_safety.capped_rows`.
- Produces:
  - `parse_issue_sheet(file_bytes: bytes, filename: str) -> list[dict]`.
    - Each row is `{'row_no': int, 'itemcode': str, 'qty': str, 'expiry': str|date|None}`.
    - Header aliases:
      - itemcode: `كود`, `كود الصنف`, `itemcode`, `item code`, `code`
      - qty: `كمية`, `الكمية`, `qty`, `quantity`
      - expiry: `صلاحية`, `تاريخ الصلاحية`, `expiry`, `exp`
    - Rows whose itemcode and qty are both blank are skipped.
    - The number of rows goes through `capped_rows`.
  - `build_lines(document, rows) -> None`, which creates RpaLine.
    - An itemcode is normalised by stripping it, dropping a trailing `.0`, and keeping digits only.
    - Unknown code → `status='unmatched'`, `message='كود غير موجود'`.
    - qty ≤ 0 or not numeric → `error`.
    - An expiry that is a date, `d/m/yy` or `d/m/yyyy` is accepted. Anything else → `error`, `message='تاريخ صلاحية غير مفهوم'`.
    - The same itemcode+expiry seen again → `warning='صنف مكرر في الملف'`, and the line is still kept.
  - `create_job(*, profile, screen_key, branch, target_branch, store_code, upload) -> RpaJob`.
    - Refuses when `branch_scope.allows(profile, branch.id)` is False (PermissionDenied).
    - Refuses when a non-cancelled job has the same `upload_sha256` (ValidationError carrying the existing job id).
    - Refuses a target equal to the source, and source branch code `110`.
    - Creates one RpaDocument (seq 1) with its lines, plus audit `rpa_job_uploaded`.
    - Stage 1: a 125 sheet is one document. The splitting rule is set in Stage 2 with the owner.

- [ ] **Step 1: Write the failing tests**
  - `test_arabic_headers_and_blank_rows`: an xlsx built in-test with headers `كود الصنف|الكمية|تاريخ الصلاحية` and 3 rows + 4 blank rows → 3 rows.
  - `test_qty_and_code_normalisation`: code `52.0` → `'52'`; qty `'5'`/`5.0` → `Decimal('5')`.
  - `test_expiry_formats`: Excel date, `1/5/25` → `date(2025,5,1)`; `'abc'` → line error.
  - `test_duplicate_rows_kept_with_warning`.
  - `test_unknown_code_unmatched`.
  - `test_same_file_twice_refused`.
  - `test_branch_110_and_same_target_refused`.
  - `test_out_of_scope_branch_refused`.
- [ ] **Step 2:** Run `manage.py test apps.tests.test_rpa_sheet --noinput`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run again. Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa): issue sheet parse, item matching, job creation`.

---

### Task 5: Approvals (job four-eyes, recipe four-eyes, cancel)

**Files:**
- Modify: `apps/rpa/workflow.py`
- Test: `apps/tests/test_rpa_workflow.py`

**Interfaces (Produces):**
- `approve_job(job, profile) -> RpaJob`.
  - Requires `profile != job.created_by`, matrix `rpa approve`, and no line in unmatched/error.
  - Requires an approved recipe for the screen; the latest approved one is frozen onto `job.recipe`.
  - Documents → `approved`. Audit `rpa_job_approved`.
  - Errors are `ValidationError` with Arabic messages.
- `cancel_job(job, profile, reason: str)`. Only while no document is `in_progress`/`posted`. Audit.
- `approve_recipe(recipe, profile) -> RpaRecipe`. Requires `profile != recipe.created_by` and an admin role. The previous approved version → `retired`. Audit `rpa_recipe_approved` with `old_data` = the previous version id.

- [ ] **Step 1: Write the failing tests**
  - `test_uploader_cannot_approve`
  - `test_unmatched_line_blocks_approval`
  - `test_approval_freezes_latest_approved_recipe`
  - `test_no_approved_recipe_blocks`
  - `test_recipe_creator_cannot_approve_own`
  - `test_new_recipe_approval_retires_previous`
  - `test_cancel_refused_when_in_progress`
- [ ] **Steps 2–4:** fail → implement → pass (`manage.py test apps.tests.test_rpa_workflow --noinput`).
- [ ] **Step 5:** Commit `feat(rpa): four-eyes approvals for jobs and recipes`.

---

### Task 6: Read-only SOFTECH verifier for doc 125

**Files:**
- Create: `apps/rpa/identity.py`, `apps/rpa/verifier.py`
- Test: `apps/tests/test_rpa_verifier.py` (use `apps/tests/security/sql_recorder.RecordingSybase` or a `_FakeConn` like `test_personal_r7.py:170`)

**Interfaces (Produces):**
- `expected_softech_usercode(profile) -> str | None`. The `person_code` of `profile.softech_identities.filter(kind='salesperson', status='approved')`, else `profile.softech_user_id or profile.softech_username or None`.
- `find_issue_document(document) -> dict | None`.
  - Connects to the supplying branch: `get_branch_connection(job.branch.effective_db_host, job.branch.db_port or 5000, job.branch.db_name or 'SOFTECHDB9')`.
  - **(a)** First it looks for the reference: `SET ROWCOUNT 5 SELECT docnumber, usercode, cust_branch_code, docdate, comments FROM SOFTECHDB9.dbo.stktransm WHERE branchcode=? AND doccode='125' AND comments LIKE ?`. The parameter is `f'%{document.reference}%'`.
  - **(b)** Otherwise it uses a fingerprint: the same table with `usercode=? AND cust_branch_code=? AND docdate=?` (the job's approval date) and `SET ROWCOUNT 50 … ORDER BY docnumber DESC`.
  - For each candidate it reads `stktrans` lines (`itemcode, transqty, itemexpirydate`) by **branchcode + doccode + docnumber**. Never by bare docnumber (memory: docnumber collisions).
  - A match is a candidate whose multiset of `(itemcode, qty rounded to 5 dp)` equals the document's.
  - Returns `{'docnumber', 'usercode', 'matched_by': 'reference'|'fingerprint', 'lines': [...]}` or None.
  - The connection is closed in `finally`.
- `verify_issue_document(document, found: dict) -> dict`. Compares the line set, the expiry where given, `cust_branch_code == target_branch` code, and `usercode == expected_softech_usercode(job.created_by)`. Returns `{'ok': bool, 'problems': [str]}`.

- [ ] **Step 1: Write the failing tests**
  - `test_found_by_reference`
  - `test_found_by_fingerprint_when_no_reference`
  - `test_candidate_with_extra_line_is_not_a_match`
  - `test_lines_queried_with_branch_and_doccode` (assert the recorded SQL params contain the branch code and `'125'`)
  - `test_wrong_usercode_is_a_problem`
  - `test_no_write_sql_in_module`: `static_scan.softech_write_sites` on `apps/rpa/verifier.py` → empty.
- [ ] **Steps 2–4:** fail → implement → pass (`manage.py test apps.tests.test_rpa_verifier --noinput`).
- [ ] **Step 5:** Commit `feat(rpa): read-only SOFTECH verifier for doc 125`.

---

### Task 7: Keyplan builder

**Files:**
- Create: `apps/rpa/keyplan.py`
- Test: `apps/tests/test_rpa_keyplan.py`

**Interfaces (Produces):**
- `to_send_keys(cell: str) -> str`.
  - DataLoad `\{NAME}` → pywinauto `{NAME}`.
  - Any other text is literal: each of `+ ^ % ~ ( ) { } [ ]` is wrapped in braces, e.g. `{+}`.
- `format_field(line, field) -> str`. `itemcode` → code; `qty` → normalised decimal without trailing zeros; `expiry` → `f'{d.day}/{d.month}/{d:%y}'` (the template's `1/5/25` form), blank when None.
- `build_keyplan(document, *, mode: str) -> dict`, where `mode` is `'dry_run'|'live'`. It returns:
  ```
  {'document': id, 'reference': str, 'window_title': str, 'cell_delay': float, 'form_delay': float,
   'checklist': [str], 'popups': [...], 'steps': [
      {'i': n, 'label': 'سطر 1', 'send': '<pywinauto keys>'} ...,
      {'i': n, 'label': 'المرجع', 'send': ...}   # only if recipe.ref_cells
      {'i': n, 'label': 'إلغاء بدون حفظ' | 'حفظ', 'send': ..., 'final': True}]}
  ```
  - One step per line, built by joining the recipe `line_cells` (fields filled, keys converted).
  - `mode='live'` raises `PermissionError` unless `job.screen.live` and `writer_allowed('RPA_SOFTECH_ENTRY_ENABLED')` and `recipe.save_keys`.
  - `mode='dry_run'` raises `ValueError` when `recipe.cancel_keys` is empty.
  - The `checklist` includes generated lines naming the target branch label (via the branch label helper, never a bare code) and the store.

- [ ] **Step 1: Write the failing tests**
  - `test_dataload_keys_converted`: `to_send_keys(r'\{ENTER}') == '{ENTER}'`.
  - `test_specials_escaped`: `to_send_keys('a+b(1)') == 'a{+}b{(}1{)}'`.
  - `test_line_step_matches_owner_template`: line 52 / qty 1 / expiry 2025-05-01 → `'{F2}52{ENTER}{ENTER}{TAB}1/5/25{TAB}1{ENTER}{ENTER}{ENTER}'`.
  - `test_dry_run_ends_with_cancel_never_save`.
  - `test_live_refused_in_stage1` (screen.live False → PermissionError).
  - `test_checklist_names_target_branch_not_code`.
- [ ] **Steps 2–4:** fail → implement → pass.
- [ ] **Step 5:** Commit `feat(rpa): server-built keyplans (dry-run only)`.

---

### Task 8: Device tokens, claim / report / resolve, write-manifest entry

**Files:**
- Create: `apps/rpa/auth.py`, `apps/rpa/agent_views.py`
- Modify: `apps/rpa/workflow.py`, `apps/rpa/urls.py`, `apps/tests/security/softech_write_manifest.py`, `apps/tests/security/test_static_guards.py`
- Test: `apps/tests/test_rpa_agent_api.py`

**Interfaces (Produces):**
- `issue_device(*, staff, label, created_by) -> tuple[RpaDevice, str]`, modelled on `apps/hr/attendance/agent_auth.py`. The secret is `secrets.token_urlsafe(32)`, stored as `token_hash` (SHA-256) and returned once. Audit `rpa_device_issued`.
- `RpaDeviceAuthentication`. Header `X-ElR-RPA-Agent`. It returns `(device.staff.user, device)` so that module access and matrix checks apply to the operator. A revoked or unknown token → `AuthenticationFailed`. It updates `last_seen_at`.
- `claim_next(device) -> RpaDocument | None`, inside `transaction.atomic()`:
  1. **Sweep.** Every `in_progress` document with `lease_until < now` → `needs_person` with reason `'انقطع الروبوت قبل الإبلاغ'`, plus audit.
  2. Refuse (return None) unless `writer_allowed('RPA_SOFTECH_ENTRY_ENABLED')` and `screen.enabled`.
  3. Pick `select_for_update(skip_locked=True)` on the oldest `approved` document whose `job.created_by == device.staff`.
  4. Run `find_issue_document`. If found → `posted` with `softech_docnumber` and verify, return None for this one, and continue to the next.
  5. Set `in_progress`, `claimed_by=device`, `claimed_at`, `lease_until = now + 10 min`. Audit `rpa_document_claimed`.
- `extend_lease(document, device)`: +10 min, only while `in_progress` and claimed by this device.
- `report_run(document, device, payload) -> RpaRun`. Payload: `{'mode', 'outcome', 'steps': [...]}`.
  - `dry_run_ok` → document `dry_run_ok`.
  - `saved` (live only, Stage 2) → run `find_issue_document` + `verify_issue_document`: ok → `posted`, otherwise `needs_person`.
  - Anything else → `needs_person` with the outcome as the reason.
  - Audit `rpa_run_reported`.
- `resolve_document(document, profile, decision: str, reason: str)`. `decision` is `retry` (→ `approved`) / `posted` (requires `find_issue_document` to find it) / `cancelled`. It needs a non-empty reason and matrix `rpa edit`, and only works from `needs_person`. Audit.
- Agent endpoints, all under `/api/rpa/agent/`, with `authentication_classes=[RpaDeviceAuthentication]` and `matrix_permission('rpa', post=('create',))`:
  - `POST claim/` → `{'keyplan': build_keyplan(doc, mode='dry_run' if job.dry_run else 'live')}` or 204.
  - `POST documents/<id>/heartbeat/`
  - `POST documents/<id>/report/`
  - `POST runs/<id>/screenshot/` (multipart `step_index`, `image`; ≤ 2 MB, PNG/JPEG only)
- Manifest:
  - Add a dict `SCREEN_WRITE_SITES` with the same `WriteSite` type:
    ```
    'apps/rpa/workflow.py::claim_next': WriteSite(tables=('stktransm','stktrans'), flag='RPA_SOFTECH_ENTRY_ENABLED', dry_run_default=True, idempotency='RPA-<id> reference + fingerprint lookup before claim; select_for_update skip_locked; 10-min lease → needs_person, never auto-requeue', audit='RpaRun + AuditLog rpa_*', trigger='Windows agent POST /api/rpa/agent/claim/', kind='screen-robot')
    ```
  - In `test_static_guards.py` add `test_screen_write_sites_resolve`: each key's module imports and has the qualname, and its flag is in `WRITER_FLAGS`.

- [ ] **Step 1: Write the failing tests**
  - `test_revoked_device_401`
  - `test_device_only_gets_own_staff_jobs`
  - `test_switch_off_claims_nothing`
  - `test_concurrent_claims_never_share`. Two threads, `TransactionTestCase`, two approved docs: two different docs are returned, and a third claim gets None.
  - `test_already_in_softech_marked_posted_not_typed` (patch `find_issue_document`).
  - `test_expired_lease_goes_to_needs_person_not_queue`.
  - `test_unknown_popup_report_needs_person`.
  - `test_resolve_requires_reason_and_edit_right`.
  - `test_screenshot_type_and_size_limits`.
  - `test_screen_write_sites_resolve`.
- [ ] **Steps 2–4:** fail → implement → pass (`manage.py test apps.tests.test_rpa_agent_api apps.tests.security.test_static_guards --noinput`; run security sweeps serially).
- [ ] **Step 5:** Commit `feat(rpa): device tokens, claim/lease/report, manifest entry`.

---

### Task 9: Staff API

**Files:**
- Create/modify: `apps/rpa/serializers.py`, `apps/rpa/views.py`, `apps/rpa/urls.py`
- Test: `apps/tests/test_rpa_api.py`

**Endpoints:**

| Method + path | Right | Notes |
|---|---|---|
| `GET jobs/` | rpa view | branch-scoped (`branch_scope.scope(qs, profile)`), `useServerSort` ordering via core `sort_ordering` |
| `POST jobs/` | rpa create | multipart: screen, branch, target_branch, store_code, file → `create_job`. Only screen `issue_125` is accepted in Stage 1. |
| `GET jobs/<id>/` | rpa view | documents → lines |
| `POST jobs/<id>/approve/` | rpa approve | |
| `POST jobs/<id>/cancel/` | rpa approve | |
| `GET documents/<id>/` | rpa view | runs + screenshot URLs |
| `POST documents/<id>/resolve/` | rpa edit | |
| `GET recipes/` | rpa view | |
| `POST recipes/` | admin | multipart `.dld` + screen + field_map |
| `POST recipes/<id>/approve/` | admin | |
| `GET devices/` | rpa view | own devices; admin sees all |
| `POST devices/` | rpa create | for yourself → `{'device', 'token'}` once |
| `POST devices/<id>/revoke/` | rpa create | own device; admin any |
| `GET status/` | rpa view | `{'switch_on': bool, 'screens': [...], 'my_devices_online': [...]}`, where online = `last_seen_at` < 2 min |

- [ ] **Step 1: Write the failing tests**
  - Each endpoint: 401 anonymous, 403 for `call_center`, 200/201 for the granted role.
  - `test_jobs_branch_scoped` (a pharmacist-like grant on branch A cannot see a branch B job).
  - `test_stage1_only_issue_screen`.
  - `test_token_shown_once` (a list never includes the token).
  - `test_live_job_refused` (`dry_run=False` → 400).
- [ ] **Steps 2–4:** fail → implement → pass.
- [ ] **Step 5:** Commit `feat(rpa): staff API`.

---

### Task 10: `/rpa` screen + help

**Files:**
- Create:
  - `frontend/src/pages/RpaPage.jsx` (tabs: `jobs` الأوامر, `upload` رفع ملف, `devices` أجهزتي, `recipes` الوصفات — admin only)
  - `frontend/src/pages/rpa/JobsTab.jsx`, `UploadTab.jsx`, `DocumentDrawer.jsx`, `DevicesTab.jsx`, `RecipesTab.jsx`
  - `apps/help/content/rpa.py`
- Modify:
  - `frontend/src/App.jsx` (lazy route `rpa`)
  - `frontend/src/components/navGroups.js` (`{ to: '/rpa', icon: '🤖', label: 'روبوت الإدخال', roles: null, module: 'rpa' }`)
  - `frontend/src/api/client.js` (`rpaApi`)
  - `apps/help/content/__init__.py` `MODULE_FILES`
- Test: `apps/tests/test_help.py` (existing) and `npm run build`

**Rules:**
- `useHelpTab(tab)`.
- Every grid is sortable (`useSortableRows`/`SortTh`). The jobs grid uses `useGridKeyboard`.
- Branch names come from `useBranchLabels`.
- The status strip shows the switch state («الروبوت متوقف من الإعدادات» when off) and the dry-run badge «تجربة بدون حفظ» on every Stage 1 job.
- The document drawer shows:
  - the lines with match status / message / warning;
  - runs with their step list and screenshots;
  - resolve buttons (`needs_person` only) with a required reason field — inline, not a modal (rule 11).
- Devices tab: «إضافة هذا الجهاز» → shows the token once with a copy button and the text «انسخه الآن، لن يظهر مرة أخرى».
- Help:
  - `SCREENS = [{'key': 'rpa.main', 'routes': ['/rpa'], 'updated': '2026-11-16', 'tabs': [jobs, upload, devices, recipes]}]`.
  - Each tab is explained in Arabic and English.
  - It covers the four-eyes rule, dry-run, «يحتاج مراجعة» and «ارفع يدك عن الكيبورد أثناء التشغيل».

- [ ] **Step 1:** Run `manage.py test apps.tests.test_help --noinput`. Expected: FAIL (the `/rpa` route has no help) once the route is added.
- [ ] **Step 2:** Implement the page, route, nav, API and help.
- [ ] **Step 3:** Run `manage.py test apps.tests.test_help --noinput` → PASS, and `cd frontend && npm run build` → no errors, and `npm run lint` → no new errors.
- [ ] **Step 4:** Use the preview to check: upload a fixture sheet, approve as a second user, see the document drawer. Check light and dark themes.
- [ ] **Step 5:** Commit `feat(rpa): /rpa screen and help`.

---

### Task 11: Windows agent `rpa_agent/`

**Files:**
- Create:
  - `rpa_agent/__init__.py`
  - `client.py`: `AgentClient(base_url, token)` with `.claim() -> dict|None`, `.heartbeat(doc_id)`, `.report(doc_id, payload)`, `.screenshot(run_id, step_index, png_bytes)`
  - `driver.py`: `Win32Driver` with `.focus(window_title) -> bool`, `.send(keys: str, pause: float)`, `.popups() -> list[dict(title, text)]`, `.screenshot() -> bytes`, using `pywinauto.Desktop(backend='win32')`, `pywinauto.keyboard.send_keys` and `PIL.ImageGrab`
  - `runner.py`
  - `overlay.py`: an always-on-top tkinter strip with the checklist, «ارفع يدك عن الكيبورد», and a big «إيقاف» button; Esc via a `pynput` global listener sets the stop flag
  - `main.py`: config `%APPDATA%\ElRezeiky\rpa_agent.json` `{base_url, token}`; buttons «ابدأ» / «إيقاف»; the loop is claim → show checklist → operator ticks → run → report
  - `requirements.txt`: `pywinauto`, `pynput`, `requests`, `Pillow`
  - `README.md`: install, pair, run, and a manual dry-run checklist
  - `tests/test_runner.py`
- Test: `rpa_agent/tests/test_runner.py` (stdlib `unittest`, `FakeDriver`)

**Interfaces:**
- `run_keyplan(keyplan: dict, driver, *, stop: threading.Event, on_step=None) -> dict`, which returns `{'outcome': str, 'steps': [...]}`.
- Algorithm (fixed):
  1. If `driver.focus(window_title)` is False → `wrong_window`, with nothing sent.
  2. For each step: check `stop` → `stopped_by_operator`.
  3. Re-check the focus title before every step → `wrong_window`.
  4. Send the step's keys with `cell_delay` between cells, then wait `form_delay`.
  5. Read `driver.popups()`. A popup that matches a keyplan `popups` rule → send its `answer_keys`. Any other popup → `unknown_popup`, screenshot, stop.
  6. Take a screenshot after the first line, after every 10th line and after the final step.
  7. The final step of a dry run → `dry_run_ok`.
  8. Any exception → `error` with the message.

  Never send anything after a stop outcome.
- The window title is compared after `' '.join(title.split())` on both sides (collapsed whitespace), as an exact match.

- [ ] **Step 1: Write the failing tests**
  - `test_wrong_window_types_nothing`
  - `test_title_whitespace_tolerated`
  - `test_stop_flag_halts_before_next_step`
  - `test_unknown_popup_stops_and_screenshots`
  - `test_known_popup_answered_and_continues`
  - `test_dry_run_final_step_outcome`
  - `test_focus_lost_midway_stops`
- [ ] **Step 2:** Run `venv/Scripts/python.exe -m unittest discover -s rpa_agent/tests -t .`. Expected: FAIL.
- [ ] **Step 3:** Implement the runner, then the client, driver, overlay and main.
- [ ] **Step 4:** Run again. Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa): Windows agent (dry-run)`.

---

### Task 12: Whole-stage check

- [ ] **Step 1:** Run `manage.py test apps.tests.test_rpa_module apps.tests.test_rpa_models apps.tests.test_rpa_dld apps.tests.test_rpa_sheet apps.tests.test_rpa_workflow apps.tests.test_rpa_verifier apps.tests.test_rpa_keyplan apps.tests.test_rpa_agent_api apps.tests.test_rpa_api apps.tests.test_help --noinput`. Expected: all pass.
- [ ] **Step 2:** Run the security sweeps **serially** with a unique `TEST_DB_NAME`: `manage.py test apps.tests.security --noinput`. Check RAM first (memory: parallel runs crash Postgres).
- [ ] **Step 3:** Run `cd frontend && npm run build && npm run lint`, and `venv/Scripts/python.exe -m unittest discover -s rpa_agent/tests -t .`.
- [ ] **Step 4: Manual dry-run with the owner** (README checklist). With the switch ON on the writer instance, screen `issue_125.enabled=True`, `live=False`:
  1. Import the owner's `.dld`, map it `itemcode, expiry, qty`, and have a second admin approve it.
  2. Set `cancel_keys` with the owner by watching one manual cancel. For example Esc → «حفظ التعديلات؟» → «لا». Record the popup as a recipe popup rule.
  3. Upload a 5-line sheet, and approve it as a second user.
  4. Pair the operator's PC, open إذن صرف للفروع in SOFTECH, and fill the header by hand per the checklist.
  5. Start the agent and watch it type the lines and cancel.
  6. Confirm in SOFTECH that **no** 125 was saved, and that the run shows `dry_run_ok` with screenshots.
- [ ] **Step 5:** Update `docs/architecture/11_ERP_INDEX.md` (a row for the spec + `apps/rpa`) and `02_MODULE_REGISTRY.md`. Add the `/rpa` route to `05_UI_REGISTRY.md`. Commit `docs(rpa): register Stage 1`.

**Stage 2 (next plan, not here):**
- Record `save_keys` and the reference field with the owner, then flip `issue_125.live`.
- 125 from distribution plans (`PlannedMove` needs an issued link) and from reshuffles.
- The rule for splitting one sheet into several documents.
