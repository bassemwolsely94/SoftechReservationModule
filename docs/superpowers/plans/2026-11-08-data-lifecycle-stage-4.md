# Data Lifecycle Stage 4 — Upload Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop upload waste at the source and make every removed or replaced file go through the Stage 3 holding folder.

**Architecture:** Two model signals in `apps/data_lifecycle` cover every upload site at once. A `pre_save` hook shrinks new photos on listed fields. `pre_save`/`post_save`/`post_delete` hooks send an old file to the holding folder after the transaction commits. Duplicate invoice uploads are found by a SHA-256 stored on `SupplierInvoice` and `InvoiceBatch` and shown inline. Helpers go in `core/upload_safety.py`.

**Tech Stack:** Django 5 / DRF, Pillow, PostgreSQL, React + Vite.

**Spec:** `docs/superpowers/specs/2026-11-07-data-lifecycle-design.md` §6 Stage 4, §8 (Upload, Staff deletion).
Builds on Stage 3 (`claude/data-lifecycle-stage-3`, not merged): `apps/data_lifecycle/holding.py`, `HeldFile`,
`references.py`, `register.classified_file_fields()`. **This branch must land after Stage 3.**

## Global Constraints

- No SOFTECH reads or writes. Nothing is applied to the office data. `LIFECYCLE_FILE_RULES_ENABLED` stays OFF.
- Invoice scans (`invoices.*`) and `vision.OcrSample` images (all modules, `pos_rx` included) are **never** shrunk, byte for byte.
- A staff deletion or replacement is held 30 days (`holding.HOLD_DAYS`), then purged; `HeldFile` records who and when. Floors do not apply to it.
- Logs and error text carry ids only, never a file name or phone (§7, `core/errors.public_error`).
- No popup for the duplicate notice: an inline notice in the existing upload form (rule 11).
- In-app help Arabic + English, `updated` bumped, for every changed screen.
- Tests run serially with a unique `TEST_DB_NAME`. Never bare `git stash`.

## Shrink sizes: measured, not guessed

Local samples, no image left the machine (script in the session scratchpad; numbers only):

| Sample | n | Longest side | Tesseract words kept vs original at 2800 / 2400 / 2000 / 1600 / 1200 px (JPEG q85) |
|---|---|---|---|
| Reservation photos (customer / prescription-like) | 25 of 30 | median 2736 | 0.88 / 0.87 / 0.84 / 0.86 / 0.87 (median) |
| Invoice scans | 25 of 92 | median 3507, max 6667 | 0.32 / 0.29 / 0.27 / 0.22 / 0.12 |

- For photos, 2000 px keeps as much as 2800 px; the spread is OCR noise. The file shrinks to about 30% of its size.
- Invoices lose most words at any shrink, so the design's call not to shrink them is right.
- A synthetic 3000×4000 handwritten prescription, with the smallest line about 0.9 mm high, still reads "Amaryl 1mg vs 7mg", "0.5ml q8h" at 2000 px. At 1600 px it reads too, with less margin.
- There are no real handwritten prescriptions in the office media (0 POS, 1 OCR sample), so a pharmacist should look at the first real ones after go-live. That is an owner item.

**Chosen:** prescriptions and customer images get a longest side of **2000 px** at JPEG quality **85**. Chat, task and delivery-proof images get **1600 px** at quality 85. An image already within its limit is left byte for byte. A result that is not smaller is discarded.

## Review Focus

1. **A rolled-back transaction must not move a file.** Hold only in `transaction.on_commit`. Test: an exception after `img.delete()` inside `atomic` leaves the file in media and no `HeldFile`.
2. **A shared file must not move.** Product media and OCR samples share paths (Stage 3 found 607 and 4). Test: deleting one of two rows that use a path holds nothing.
3. **A hold failure must not break the user's request.** Examples are a hold root inside media or a missing file. Test: the delete still returns 204 and the log names no file.
4. **`FieldFile.save()` paths skip `pre_save`.** Stage 3 found `images/views.py:347`, `images/pipeline.py:383`, `images/views.py:599`, `invoices/ingest.py:187` and `product_experience/services.py:188`. None is a shrink-listed field, and a test pins that list.
5. **A HEIC, CMYK, animated or corrupt photo must be stored unchanged**, never lost. Test per case.

---

### Task 1: Shrink photos on upload

**Files:**
- Modify: `core/upload_safety.py` (add `shrink_image`)
- Create: `apps/data_lifecycle/uploads.py`
- Modify: `apps/data_lifecycle/apps.py` (`ready()` connects the signals)
- Test: `apps/tests/test_lifecycle_uploads.py`

**Interfaces:**
- Produces: `core.upload_safety.shrink_image(data: bytes, longest_side: int, quality: int = 85) -> bytes | None`.
  It returns None when the data is left as is: not an image Pillow opens, animated, a format other than JPEG/MPO/PNG/WEBP, already within `longest_side`, any error, or a result that is not smaller.
  It applies `ImageOps.exif_transpose`, keeps the format (MPO is saved as JPEG), drops EXIF, and catches `Image.DecompressionBombError`.
- Produces: `apps.data_lifecycle.uploads.SHRINK_LONGEST_SIDE: dict[str, int]` maps `'app.Model.field'` to a side length:
  - 2000: `pos_orders.SoftechSalesOrder.prescription_image`, `usage_print.UsageSheet.prescription_image`, `callcenter.CallLog.prescription_image`, `reservations.Reservation.image`, `reservations.ReservationImage.image`, `whatsapp.WAMediaFile.local_file`, `callcenter.CallLogAttachment.file`, `callcenter.CaseEvent.attachment`.
  - 1600: `notifications.ChatterMessage.attachment`, `reservations.ReservationActivity.attachment`, `transfers.TransferRequestMessage.attachment`, `tasks.TaskAttachment.file`, `delivery.DeliveryOrder.pod_photo`.
- Produces: `uploads.connect()`, which connects one `pre_save` receiver per listed model, with a `dispatch_uid`.

- [ ] **Step 1: Write the failing tests**, in a `TestCase` with a temporary `MEDIA_ROOT` like `test_lifecycle_holding.HoldingCase`:
  - `test_prescription_photo_shrinks_to_2000` saves a 4000×3000 JPEG to a `ReservationImage`. The stored file has `max(size) == 2000` and fewer bytes.
  - `test_chat_photo_shrinks_to_1600` does the same through `TaskAttachment.file`, giving `max(size) == 1600`.
  - `test_invoice_scan_unchanged_byte_for_byte` stores a 4000×3000 JPEG as `SupplierInvoice.source_image`, and as `OcrSample.image` with module `pos_rx`. The stored bytes equal the uploaded bytes.
  - `test_small_photo_unchanged` uses a 1200×900 JPEG on a prescription field and gets identical bytes.
  - `test_not_an_image_unchanged` covers a PDF on `CallLogAttachment.file`, random bytes, and a 2-frame GIF. All get identical bytes.
  - `test_exif_orientation_applied` uses a 4000×3000 JPEG with EXIF Orientation=6 and gets a stored size of 1500×2000.
  - `test_shrink_list_is_classified` checks that every key of `SHRINK_LONGEST_SIDE` is in `register.classified_file_fields()` and that no key starts with `invoices.` or `vision.`.
  - `test_fieldfile_save_sites_not_shrink_listed` checks that the 5 `FieldFile.save()` fields in Review Focus 4 are not keys.
- [ ] **Step 2: Run them and confirm they fail.** Command: `python manage.py test apps.tests.test_lifecycle_uploads` with the env from "Running tests" below.
- [ ] **Step 3: Implement `shrink_image` and `uploads.py`.**
  The receiver skips `raw` saves. For each listed field it reads `f = getattr(instance, name)`. If `f` is set and `f._committed` is False, it reads the bytes, rewinds, calls `shrink_image`, and on a result sets `f.file = ContentFile(new, name=f.name)`. Any exception is logged with the model label and pk only, and the upload is stored as is.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** with `feat(lifecycle): shrink new photos on upload (prescriptions 2000 px, chat 1600 px)`.

### Task 2: Files follow their record into the holding folder

**Files:**
- Modify: `apps/data_lifecycle/models.py` (`HeldFile.deleted_by`), plus migration `0002_heldfile_deleted_by`
- Modify: `apps/data_lifecycle/holding.py`
- Modify: `apps/data_lifecycle/references.py` (`references_to`)
- Modify: `apps/data_lifecycle/display.py` (exclude staff keys)
- Create: `apps/data_lifecycle/follow.py`; connect it in `apps.py`
- Modify the direct deletions: `apps/reservations/views.py:1086-1100`, `apps/callcenter/views.py:460`, `apps/tasks/views.py:609-613`, `apps/product_experience/views.py:259-268`
- Test: `apps/tests/test_lifecycle_follow.py`

**Interfaces:**
- Consumes: `holding.hold_file`, `holding.purge_expired`, `register.classified_file_fields()`, `references.TEXT_PATH_FIELDS` and `media_path_from_url`, and `apps.users.middleware.get_current_user_profile()`.
- Produces:
  - `HeldFile.deleted_by` is an FK to `users.StaffProfile`, `SET_NULL`, nullable, `related_name='+'`.
  - In `holding`: `RECORD_DELETED = 'record_deleted'`, `FILE_REPLACED = 'file_replaced'`, `STAFF_RULE_KEYS = (RECORD_DELETED, FILE_REPLACED)`.
  - `holding.hold_file(path, rows, rule_key, *, origin=None, deleted_by=None)` is unchanged for existing callers. `origin={'model','pk','field'}` fills `primary_*` when `rows` is empty.
  - `holding.restore` refuses a `STAFF_RULE_KEYS` hold with a `HoldError`. The Arabic message says the file can only be retrieved, not put back into a record.
  - `holding.retrieve(held_id, user) -> (bytes, original_name)` refuses a held file that is restored, purged, missing or has a changed hash. It writes `AuditLog` `lifecycle_file_retrieved`. The caller checks that the user is an admin; that wiring is Stage 5's screen.
  - `references.references_to(path) -> set[Ref]` makes one filter per `FileField` (`field=path`) plus `TEXT_PATH_FIELDS` (`contains` basename, then a `media_path_from_url` equality check).
  - `follow.connect()` connects `pre_save`, `post_save` and `post_delete` for each model that owns a classified field.
    - `pre_save` stores the old values of changed classified fields on the instance. It makes one query, and none for a new row, a `raw` save, or an `update_fields` set that excludes them.
    - `post_save` schedules `FILE_REPLACED` for an old value that differs from the new one. A cleared field counts as replaced.
    - `post_delete` schedules `RECORD_DELETED` for each non-empty value.
    - Scheduling means `transaction.on_commit(partial(_hold_after_commit, path, origin, rule_key, user_id))`, with the user captured at signal time.
    - `_hold_after_commit` holds nothing when `references_to(path)` is non-empty or the file is not on disk. It calls `hold_file(path, [], rule_key, origin=..., deleted_by=...)` and catches every exception. The log carries rule key, model, pk and exception type only.

- [ ] **Step 1: Write the failing tests** (`captureOnCommitCallbacks(execute=True)`):
  - `test_deleted_prescription_held_with_who_and_when` deletes a `ReservationImage` through the API `delete_image` as a pharmacist. It expects 204, the file gone from media, one `HeldFile(rule_key='record_deleted', deleted_by=pharmacist, primary_model='reservations.ReservationImage', primary_field='image')` with `purge_after == moved_at + 30 days`, and the bytes in the hold folder.
  - `test_replaced_pos_prescription_held` calls `upload_prescription` twice. It expects the first file in hold as `file_replaced` with `deleted_by` set, and the second still in media.
  - `test_purged_after_30_days_with_row_gone` runs `purge_expired(now=moved_at + 31 days)` after the delete. It expects `purged_at` set and the file gone. At day 29 nothing is purged.
  - `test_rollback_moves_nothing` raises inside `atomic` after `img.delete()`. The file stays and there is no `HeldFile`.
  - `test_shared_path_not_moved` gives two `ReservationImage` rows the same name and deletes one. Nothing is held.
  - `test_hold_failure_does_not_break_delete` sets `LIFECYCLE_HOLD_ROOT` inside media. The API still returns 204, the file stays, and the log has no file name.
  - `test_restore_refused_for_staff_hold`, plus `test_retrieve_returns_bytes_and_audits`.
  - `test_staff_clear_shows_no_retention_note`: after a staff `file_replaced` that left the field empty, `removed_dates` returns nothing.
  - `test_no_direct_file_delete_left` scans `apps/**/*.py`, excluding tests, migrations and `data_lifecycle`, for `.delete(save=` and `default_storage.delete(`. Each hit must be in an allowlist with a written reason.
  - `test_cascade_delete_holds_children`: deleting a `Reservation` holds its `ReservationImage` files.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** the model field and migration, `holding`, `references_to`, `display` (exclude `rule_key__in=STAFF_RULE_KEYS`), and `follow.py`. Then remove the four direct deletions, which the signal now covers. Keep each view's response unchanged.
- [ ] **Step 4: Run the new tests, then `apps.tests.test_lifecycle_holding`, `test_lifecycle_display`, `test_lifecycle_file_rules`, and the reservations, tasks, callcenter and product_experience view tests. Confirm they pass.**
- [ ] **Step 5: Commit** with `feat(lifecycle): deleted and replaced files go to the holding folder with who and when`.

### Task 3: Duplicate invoice upload notice

**Files:**
- Modify: `apps/invoices/models.py` (`source_sha256` on `SupplierInvoice` and `InvoiceBatch`), plus migration `0023_upload_sha256`
- Modify: `core/upload_safety.py` (`sha256_of`)
- Create: `apps/invoices/duplicates.py`
- Modify: `apps/invoices/views.py` (both viewsets' `create`)
- Create: `apps/invoices/management/commands/backfill_upload_hashes.py`
- Modify: `frontend/src/pages/InvoicePage.jsx` (`CreateInvoiceModal`) and `frontend/src/pages/invoices/BundleWorkbench.jsx` (`UploadBundle`)
- Test: `apps/tests/test_invoice_upload_duplicates.py`

**Interfaces:**
- Produces:
  - `source_sha256 = CharField(max_length=64, blank=True, default='', db_index=True, editable=False)` on both models.
  - `core.upload_safety.sha256_of(f) -> str` hashes in chunks and leaves `f` rewound to 0.
  - `apps.invoices.duplicates.find_duplicate(sha: str) -> dict | None` checks invoices first, then batches, newest first. It returns `{'kind': 'invoice'|'batch', 'id', 'label', 'status_label', 'created_at'}`. It is company-level, like the invoices module querysets, with no branch filter.
  - API: when a `POST` carries a file whose hash matches, and `allow_duplicate` is not `1`/`true`, the response is **200 `{'duplicate_of': {...}}`** and nothing is saved. Otherwise the row is created as today with `source_sha256` set.
  - `manage.py backfill_upload_hashes` is a dry run by default and prints counts only. `--apply` fills empty hashes with `queryset.update`. It skips invoices with a `batch` (rendered pages) and rows whose file is missing.
  - Frontend: on `duplicate_of`, the existing form shows an inline amber notice: «رفعت هذا الملف من قبل: <label> (<status>) · فتح · رفع على أي حال». «فتح» opens the existing invoice or batch. «رفع على أي حال» resends with `allow_duplicate=1`. There is no new modal.

- [ ] **Step 1: Write the failing tests:**
  - `test_repeat_invoice_file_shows_notice_and_saves_nothing`: a second POST of the same bytes gets 200 with `duplicate_of.kind == 'invoice'` and `id` equal to the first, and the row count is unchanged.
  - `test_continue_creates_with_allow_duplicate`.
  - `test_different_file_creates_normally`.
  - `test_batch_repeat_and_cross_kind`: the same PDF as a batch after an invoice reports `kind='invoice'`.
  - `test_invoice_scan_stored_byte_for_byte`.
  - `test_hash_stored`.
  - `test_backfill_dry_run_changes_nothing_apply_fills` (batch child skipped).
  - `test_no_file_no_check`.
  - `test_permission_unchanged`: a user without invoices create still gets 403.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** the backend, then the frontend. The `ocr_engine` / OCR start-up in `perform_create` stays as it is.
- [ ] **Step 4: Run the tests and `apps.tests.test_invoice*`, then `cd frontend && npm run build`. Confirm they pass.**
- [ ] **Step 5: Commit** with `feat(invoices): calm notice when the same invoice file is uploaded again`.

### Task 4: Bundle pages confirmation, help, docs, notes

**Files:**
- Test: `apps/tests/test_lifecycle_bundle_pages_unused.py`
- Modify: `apps/help/content/invoices.py`, `reservations.py`, `pos.py`, `tasks.py` (the screens whose uploads change; bump `updated`)
- Modify: `docs/architecture/36_DATA_LIFECYCLE.md` (Stage 4 section), `docs/deploy/2026-11-owner-go-live-steps.md` (after the media copy: run `backfill_upload_hashes --apply`; switch `bundle_pages` on after its first VPS preview; `media_hold` now also receives staff deletions), and the design status line
- Create: a hand-over note for Stage 5 in the shared notes folder

**Bundle pages finding (verified on this branch):** `invoice_bundles/pages` is written and read only inside `ingest.process_bundle`. `reprocess` renders again from `source_file`, which stays. Each invoice's own scan is a copy in `invoice_images/`. The two management commands (`benchmark_vs_softech`, `validate_learning_flywheel`) render into their own folders. The rule therefore stays as Stage 3 wrote it. "Switching on" is an owner step on the VPS, because file rules are locked to preview until `LIFECYCLE_FILE_RULES_ENABLED` and a fresh preview exist.

- [ ] **Step 1: Write the tests:**
  - `test_finalised_batch_works_without_pages`: with the pages folder deleted, batch detail and invoice detail return 200 and keep `source_image_url`.
  - `test_reprocess_renders_from_source_file`: `render_pages` is mocked and called with `batch.source_file.path`.
  - `test_only_ingest_reads_pages`: a source scan finds `invoice_bundles` / `'pages'` work-dir use only in `apps/invoices/ingest.py`, `apps/invoices/models.py` and `apps/data_lifecycle/`.
- [ ] **Step 2: Run them and confirm they pass.** They pin the current behaviour, so they pass first time.
- [ ] **Step 3: Update help (AR + EN), docs and go-live steps; write the Stage 5 note.** The note covers `deleted_by`, `STAFF_RULE_KEYS`, `restore` refusal, `retrieve`, and migration `0002` (Stage 5 renumbers if it adds one).
- [ ] **Step 4: Run `apps.tests.test_help`.**
- [ ] **Step 5: Commit** with `docs(lifecycle): stage 4 help, go-live steps, bundle pages confirmed unused after finalisation`.

## Running tests

Serially, never `--parallel`, with a unique DB:
`TEST_DB_NAME=test_lifecycle_s4_<n> python manage.py test <labels> --keepdb` from the worktree. The worktree's `.env` is a copy with
`WRITER_INSTANCE=False` and `SOFTECH_READ_ONLY=True`.
