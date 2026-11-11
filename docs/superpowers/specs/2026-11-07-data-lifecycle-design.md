# Data lifecycle and data health — design

**Date:** 2026-11-07. **Status:** awaiting owner approval. Nothing is built.
**Arabic name:** صحة البيانات. **Extends:** P-56 retention
([spec](../../product-review/06_SPEC_P-56_retention_and_sync_health.md), `apps/sync/maintenance.py`).

## 1. Why

The owner wants control of data growth before it becomes a problem. Daily use by more staff will add uploaded
prescriptions, images and scanned invoices, along with engine output that is used once and then replaced.

No dirty record is causing a wrong report or decision today. This is **preventive**: it should make growth visible,
stop waste being created, and remove what has no further use. It must never cost the business a record it needs.

## 2. Goals, non-goals, anti-goals

**Goals**
1. One register lists every kind of file and each large table, with its keep rule and the reason.
2. Nothing is deleted until a rule has been previewed and switched on. Every run is recorded.
3. Waste stops at the source, including repeated alerts, duplicate uploads and oversized photos.
4. One screen shows what is growing, what the rules did, and which data problems are open.
5. A missed cleanup run is noticed.

**Non-goals**
- Merging the several copies of sales data into one. Doc 30 (`30_SOFTECH_LOAD_REDUCTION.md`) already plans that.
- Rebuilding customer merge, ingredient review or phantom detection. The screen links to them.
- Correcting clinical or ingredient data automatically.
- Deleting or changing rows in SOFTECH, or adding any SOFTECH write.
- Automatically restarting the laptop scheduler. The VPS service manager covers this at cutover.
- Managing `backups/` or the VPS dump schedule (`docs/deploy/2026-11-owner-go-live-steps.md` §4).

**Anti-goals: this has failed, even if it works, if:**
- a money, SOFTECH, permission, approval, finance or insurance record is removed automatically;
- a rule removes a prescription image before its keep period ends (a deliberate staff deletion is different, §6 Stage 4);
- a mirrored SOFTECH row is "cleaned" here and simply comes back on the next sync;
- an open ISR, order or review screen breaks because a run or file it needs was removed;
- staff get new popups or alerts for routine cleanup (rule 11).

## 3. Measured baseline (office database, 2026-11-06/07)

| Measure | Value |
|---|---|
| Database size | 11.4 GB (9.9 GB when P-56 was specified) |
| `ItemDemandMetrics` | 2,513 MB for 533,111 rows; real row data about 138 MB, indexes 1,477 MB |
| `ItemDemandAggregated` | 400 MB; real row data about 22 MB |
| `TransferRecommendation` | 200 MB; real row data about 15 MB |
| `Notification` | 1,049 MB for 760,098 rows; real row data about 193 MB; 85% `transit_critical`; **all unread** |
| Indexes with no recorded use | 1,779 (non-unique), 2.6 GB. The counters have no reset date, so this is evidence, not proof |
| Transit notes / audit events | 155,106 / 235,722 for 6,738 transfers; 148,367 of each are repeat automatic alerts |
| Media | 4,482 files, 710 MB |
| Files no `FileField` points to | 770 files, 237 MB, of which `invoice_bundles/pages` is 76 files, 203 MB |
| Exact duplicate copies | 997 files, 271 MB (overlaps the row above) |
| Item image candidates | Rejected 876 (70 MB), never reviewed 1,464 (129 MB), approved 648 (46 MB); on obsolete items 36 (3 MB) |
| Prescription images | Almost none so far (`pos_orders` 0, OCR samples 1) |

**Estimate:** about 3 GB comes back by compacting tables, without deleting a row. Real data is growing slowly today,
and the planned 300 GB VPS disk gives room. This is not an emergency.

**Why retention stopped on 5 Nov.** The job is fine. Windows restarted the laptop at 00:22 on 6 Nov and the scheduler
was not running again until the evening, so the 04:45 run never fired. No alert covers a job that simply does not run.

## 4. Principles

- **Our data only.** Rules apply to platform tables and uploaded files. Mirrored SOFTECH data is reported, never
  removed by a rule, except what P-56 and the existing rolling windows already handle.
- **Backend owns the rules.** What can be deleted, and the minimum keep period, live in reviewed code. Admins can only
  change the mode (off / preview / on) and lengthen a period.
- **Rows outlive files.** For a document, delete the file and keep the record that it existed.
- **Every file gets a safety period.** A file moves to a private holding folder for 30 days before permanent deletion.
- **Default is keep.** A new `FileField` without a classification fails CI (Stage 3).

## 5. Keep rules

"Owner" means the owner decided it. "Draft" means Claude proposed it and the owner has not objected; it can be changed
when reviewing this document.

### 5.1 Files

| Data | Fields | Keep for | Then | Source |
|---|---|---|---|---|
| Prescriptions | `pos_orders.SoftechSalesOrder.prescription_image`, `usage_print.UsageSheet.prescription_image`, `callcenter.CallLog.prescription_image`, `reservations.Reservation.image`, `reservations.ReservationImage.image` | **3 years, floor 3 years** | Remove file, keep row | **Owner**, legal check pending |
| Prescription scans in the OCR store | `vision.OcrSample.image`, module `pos_rx` | **3 years, floor 3 years** | Remove image, keep the text readings for learning | **Owner** |
| Customer conversations that may contain prescriptions | `whatsapp.WAMediaFile.local_file`, `callcenter.CallLogAttachment.file`, `callcenter.CaseEvent.attachment` | 3 years | Remove file, keep row | Draft |
| Financial documents | `invoices.SupplierInvoice.source_image`, `invoices.InvoiceBatch.source_file`, `payments.ExternalPayment.screenshot`, `payments.BankStatementImport.raw_file`, `hr.ExpenseClaim.receipt` | 5 years, floor 5 years | Remove file, keep row | Draft, accountant to confirm |
| Invoice bundle page images | `media/invoice_bundles/pages/batch_<id>/` (no field) | 30 days after every invoice in the batch is finalised or cancelled | Remove folder; the source PDF stays | Draft |
| Rejected item images | `images.ImageCandidate.local_file`, status `rejected` | 30 days | Remove file, keep row so the image is not fetched again | Draft |
| Unreviewed item images | same, status `scored` or `pending_review` (today all 1,464 are `scored`) | 180 days | Remove file, keep the row so `seen_urls` stops a re-download | Claude's call |
| Images of obsolete items | `ImageCandidate.local_file`, `product_experience.ProductMedia.file` + `thumbnail` | 90 days after the item is first seen obsolete | Remove; stops if the item returns to use | Draft |
| Delivery proof | `delivery.DeliveryOrder.pod_photo` | 1 year | Remove file, keep order | Draft |
| Staff messages and attachments | `notifications.ChatterMessage` (attachment, voice), `reservations.ReservationActivity` (attachment, voice), `transfers.TransferRequestMessage` (attachment, voice), `tasks.TaskAttachment.file`, `supply.AvailabilityBatch.source_image`, `shortage.ShortageList.source_image` | 1 year | Remove file, keep row | Draft |
| Files no record uses | anything under `media/` not referenced | Found on 2 scans 30 days apart | Remove, after the Stage 3 check of paths held in text fields | Draft |
| Live content and learning data | `images.ImageCandidate` approved on live items, `ProductMedia` on live items, `product_experience.ProductSEO.og_image`, `insurance.InsuranceExportProfile.watermark_image`, `vision.OcrSample` modules other than `pos_rx` (image, audio) | Forever | — | Draft |

"Obsolete" means `no_more_use`, archived, or inactive on the mirrored item. The item has no date for when that
happened, so this app records the date it first saw the state. It does not change the mirrored item.

### 5.2 Rows

| Data | Rule | Source |
|---|---|---|
| Rate runs: `ItemDemandMetrics`, `ItemDemandAggregated`, pending `TransferRecommendation` | Keep the last **3** completed runs + the last run of each month for 24 months + any run still referenced (below). Run headers stay | Owner's wish to drop used rates; replaces the earlier "last 10" decision; 24 months is draft |
| Executed rate writebacks: `SalesRatePush` + lines | Forever (rule 8) | Existing |
| Repeat transit alert notes: `InTransitNote` type `alert` whose body is an automatic stuck-transfer alert | 90 days after the transfer closes; for still-open transfers, keep the latest per level | Draft |
| Transit audit events `alert_sent` (same alerts only) and `synced` | Same as above | Draft |
| ERP-mismatch alerts, manual notes, other transit audit actions | Forever | Draft |
| Notifications, PBX events, audit noise, slow requests | Unchanged P-56 / P-55 rules | Existing |
| Screen-view telemetry | Unchanged: 12 months | Existing |
| Other tables over 20 MB | Shown as "not classified" until decided. Never deleted by default. This includes `erp_*`, which follow-ups and patient profile still read | Draft |

**Runs still in use.** `apps/purchasing/isr_fulfillment.py`, `distribution.py`, `dead_stock.py`, and
`apps/supply/comparison.py` + `price_history.py` read rows by a given run. Before tightening the rule, list every
foreign key and stored reference to `DemandCalculationRun`, and keep any run referenced by a row that is not finished.
Keeping only 3 recent runs is too few by itself: the engine runs twice a week, so an open ISR could outlive them.

For `IsrPush`, "not finished" means `proposed` or `approved`, and only for 90 days from creation, so a forgotten draft
cannot hold a run forever. `pushed` has no local closing state and does not count; the builder confirms each reader
tolerates a pruned run, as `isr_fulfillment` is reported to. (Claude's call.)

**Comparison reports.** `apps/insights/rules.py` `rule_dead_stock_growth` compares against a run at least 20 days old.
The monthly runs satisfy this; a test must prove it after pruning.

**Readers that do not filter by run.** `apps/forecasting/service.py:60` and `apps/incentives/views.py:1544` read
`ItemDemandMetrics` across all kept runs, so items are processed once per run. Fix both to use the latest run in the
same batch, using `apps.purchasing.shortage._latest_run`.

## 6. Stages

Each stage ships alone and is approved alone. Stages 1 and 2 need no new screen.

### Stage 1 — Make retention dependable

- **Catch-up:** when the scheduler starts, and from its heartbeat, run retention if the last successful run is older
  than 26 hours. It must not overlap a running retention.
- **Missed-run alert:** extend `alert_failing_lanes` in `apps/sync/maintenance.py` to also send one deduplicated admin
  notification per day when `retention` or `morning_chain` has no successful run for 26 hours. Morning chain alerts
  only, with no automatic catch-up, because it includes SOFTECH reads and downstream work.
  **Changed by the owner 2026-11-11:** the morning chain also catches up, at most once a day after its
  07:30 slot, only once a fast sync has succeeded in the last 30 minutes (its steps swallow their own
  errors, so a run while SOFTECH is down would read as a success). All four steps are read-only towards
  SOFTECH; a chain lock stops the catch-up and the 07:30 job overlapping.
- Any new scheduler job gets an entry in `SCHEDULER_JOB_GUARDS` (`apps/tests/test_scheduler_locks.py`).

### Stage 2 — Reclaim space

- **Tune autovacuum** per table on the high-churn tables (engine tables, notifications).
- **Add `manage.py reclaim_space`:** dry run by default, it prints each table's size, real data size and expected gain.
  `--apply --table X` runs `VACUUM FULL` on one table. It refuses to run inside business hours or while the demand
  engine is running, and it needs disk space for a table copy. Run by hand only, never scheduled.
- **VPS:** restoring a dump at cutover compacts tables without this command. Measure after restore and use the
  command only if needed. Do not run it on the office database just before cutover.
- **Indexes:** after the VPS has run at least 30 days including a month-end, list indexes with no use. Drop them through
  normal model and migration changes in a reviewed list. Unique and primary-key indexes are out of scope.

Dropping an index on a table fed by sync requires owner approval of the list (CLAUDE.md "stop and ask").

### Stage 3 — Register, rules and first row and file cleanup

**New app `apps/data_lifecycle`.** `apps/sync/maintenance.py` stays as the engine for existing P-56 steps. The
`daily_retention` job and `retention` lane stay, and call into the new register.

**Models**
- `LifecycleRulePolicy`: rule key, mode (`off` / `preview` / `on`), keep-period override, changed by / when / why.
- `LifecycleRun` + `LifecycleRunLine`: per-rule counts and bytes, preview or real, errors.
- `HeldFile`: original path, model / pk / field, rule, size, sha256, moved at, purge after, restored at / by, purged at.
- `ObsoleteItemSeen`: item, first seen obsolete, cleared at.

**Rules are code.** Each rule declares: key, labels (Arabic + English), kind, target, floor, reason, and a function that
returns candidates. Admins cannot add rules or go below a floor. Existing P-56 steps are listed in the register, in mode
`on`, so the owner sees one complete list.

**Safety**
- New rules start in `preview`, and switching to `on` needs a preview less than 7 days old.
- Batched deletes (reuse `_batched_delete`).
- **Circuit breaker:** a real run that would remove more than 1.5× its latest preview plus a small margin, or more than
  a per-rule ceiling, stops that rule and alerts admins. Other rules continue.
- Every mode or period change writes `AuditLog` with before / after and a reason (rule 8).
- A file move and its row update happen together: if the database step fails, the file goes back.

**Where file rules run (Claude's call).** File rules stay locked to `preview` until the VPS, through a new
`LIFECYCLE_FILE_RULES_ENABLED` setting, default OFF. Today `MEDIA_ROOT` is inside OneDrive, whose version history would
keep "removed" prescriptions, and held files would need a separate copy at cutover. Row rules may run in the office.
The VPS media backup must include the holding folder: add that line to the go-live steps as part of this stage.

**Holding folder.** `LIFECYCLE_HOLD_ROOT` is outside the served `MEDIA_ROOT`, and prescriptions in it are never
reachable by URL. An admin can restore within 30 days. A daily step purges expired files. Screens must show "removed
under retention on <date>" instead of a broken image wherever a removed file was displayed.

**Source fixes in this stage**
- `sync_in_transit`: write a note and `alert_sent` event only when an alert **level changes**, not once per day. The
  daily digest and the existing `alert_notification_count` / `last_alert_*` fields remain.
- **Notifications all unread:** first find out whether marking as read is broken or nobody reads them. Fix if it is a
  bug. Report to the owner if not, because that changes whether these alerts are useful at all.

**Classification test.** A test walks every `FileField` and fails if it has no rule or
keep-forever reason, in the same style as `SCHEDULER_JOB_GUARDS`. Before the "files no record uses" rule can run, the
builder confirms no text or JSON field holds media paths. The likely sources of current unreferenced files are test
runs and bundle pages; this is unverified.

### Stage 4 — Upload controls

Extends `core/upload_safety.py`, which already enforces `MAX_UPLOAD_FILE_SIZE`.

- **Duplicates:** hash `SupplierInvoice` and `InvoiceBatch` uploads. A repeat shows a calm inline notice linking to the
  existing document, and the user can continue. Other upload types are not checked.
- **Shrink photos on upload:** longest side about 2000 px for prescriptions and customer images, about 1600 px for
  chat, tasks and delivery. **Invoice scans and `pos_rx` OCR samples are not shrunk**, because that could hurt OCR
  (Claude's call). A prescription must stay readable: test with real samples before choosing final numbers.
- **Files follow their record:** deleting a row or replacing a file sends the old file to the holding folder, for
  classified fields, after the transaction commits. This replaces direct deletion such as
  `apps/reservations/views.py:1095-1100`, and covers overwrites such as `apps/pos_orders/views.py:690`.
- **Staff deletions (owner decision):** a deliberate deletion or replacement counts as intended, even before the keep
  period ends. The file is held for 30 days and then purged, the same as other files. `HeldFile` records who did it and
  when, and outlives the deleted row. A file whose row is gone cannot be restored into a record; an admin can only
  retrieve the file during the 30 days. The floors limit rules and admin settings, not these staff actions.
- **Bundle pages** rule from §5.1 switches on after the builder confirms no reprocess or review path needs them after
  finalisation (only the first page is copied to `source_image` today, `apps/invoices/ingest.py:181-189`).

### Stage 5 — Data health screen

Route `/data-health` (صحة البيانات), API `/api/data-health/`, new RBAC module `data_health`. A daily
`DataHealthSnapshot` stores table sizes (total, heap, index, row count) and media size per folder and per classified
type, so growth trends start from day one. Consider shipping the snapshot job in Stage 3 so history exists early.

| Tab | Shows |
|---|---|
| **النمو** Growth | Database and media size over time, fastest-growing tables and upload types, estimated empty space, days until a set disk level at the current rate, tables not classified |
| **القواعد** Rules | The whole register: what, keep period, reason, mode, last run, last count and bytes, preview result, switch control with required reason |
| **الملفات المحجوزة** Held files | Files in the holding period, purge date, who deleted it for staff deletions, restore (admin). Thumbnail for non-prescription files only; `pos_rx` samples count as prescriptions |
| **المشكلات** Problems | Open data problems, with count, trend, owner role and a link to the existing tool (below) |

**Problems list: read-only counts, no new fix logic here**

| Problem | Baseline | Links to |
|---|---|---|
| Customers sharing a phone | 27,181 rows | `/customers/merge` (0 candidates: `CUSTOMER_MERGE_QUEUE_ENABLED` to be checked) |
| Phones not in the mobile format | 16,263 | Report only; some are landlines |
| Customers with no sales in our mirror | 46,941 | Report only; not proof of junk |
| Ingredient entries awaiting review | 7,254 pending + 600 needs review, of 7,857 | Composition screen |
| Items with "undefined" scientific name | 881 | Composition screen |
| Follow-up tasks `missed` over 90 days | 72,692 | Follow-ups; decide a rule after reviewing how reports use them |
| Deliveries stuck in an open status over 90 days | 489 | Existing `cleanup_stale_delivery_orders` |
| Supply cases open over 90 days | 409 | `/supply` |
| Stock count sessions not closed over 90 days | 13 | `/stock-count` |
| POS orders `ready` over 90 days | 3 | `/pos`; never auto-closed (payment rule) |

Screen conventions: Arabic RTL, sortable grids, forced-refresh button, `BL` / branch labels, no modals for routine
actions, counts only for customer data (no phones or names on this screen).

## 7. Security definition of done

- **Access:** `/api/data-health/` mapped in `MODULE_BY_PREFIX`; `MODULE_CHOICES` + `seed_permissions.py` row;
  `PERMISSION_MATRIX.md` regenerated. Grants: admin all; supervisor and quality manager view Growth and Problems. Rule
  changes, restore and held-file view are admin only, checked on the server.
- **Branches:** company-level by nature; the code says so, and only these roles may see it. Canary planter can build
  the new models.
- **SOFTECH:** no reads and no writes in this app's rules. No manifest entry needed. Problem counts use mirrors only.
- **Privacy:** counts only; no phones or secrets in logs or errors (`core/errors.public_error`). No exports in the first
  version. Held prescriptions are never served by URL.
- **Tests:** view and permission tests, plus the business-rule tests in §8.
- **Help:** new `apps/help/content/` entry, Arabic + English, all four tabs, `useHelpTab(tab)`.
- **Docs:** add `docs/architecture/36_DATA_LIFECYCLE.md`, index in `11_ERP_INDEX.md`, update the P-56 ledger entry.

## 8. Acceptance tests

- **Retention catch-up:** no successful run for 27 hours + scheduler start → exactly one run. Recent success → none.
- **Missed-run alert:** one notification per lane per day.
- **Rate rule:** 15 fake runs over 3 months → last 3 + monthly + referenced runs remain. A run tied to an open ISR
  survives. `rule_dead_stock_growth` still finds its older run. Forecasting and incentive readers use one run.
- **Protected data:** no rule can select money, SOFTECH-write, permission, approval, finance or insurance records.
- **Preview:** changes nothing (row counts and files identical) and matches the later real run on unchanged data.
- **Floors:** API refuses a period below a floor, and refuses `on` without a fresh preview, for admin too.
- **Circuit breaker:** an oversized run stops that rule, alerts, and other rules continue.
- **Files:** file moves to hold, row keeps the record; restore returns the original path and bytes; purge removes it
  only after 30 days; failed database step puts the file back; held file has no URL.
- **Prescription:** a 2-year-11-month image stays; a 3-year-1-month image moves to hold; the same for `pos_rx` OCR
  samples, whose text readings stay, while `purchasing_invoice` samples are never selected.
- **Staff deletion:** a deleted or replaced prescription moves to hold with who and when, and is purged after 30 days,
  including when its row no longer exists.
- **Obsolete items:** clock starts when first seen; returning to use clears it; image survives.
- **Classification:** adding an unclassified `FileField` fails CI.
- **Transit:** same-level day-after-day alert writes no new note; level change writes one; mismatch alerts always kept.
- **Upload:** a repeat invoice file shows the notice and can continue; a shrunk prescription stays readable on samples;
  invoice scans are unchanged byte for byte.
- **Permissions:** role × endpoint sweep passes; non-admin cannot switch, restore or view held files.

## 9. Measures

Reported on the Growth tab: database size, real vs. empty space, monthly growth by table and upload type, rows and
bytes removed per rule, missed retention runs (target 0), restores (expect near 0; a rise means a rule is wrong).

## 10. Open owner items

1. Confirm the legal minimum for prescription images with a pharmacist or lawyer; 3 years stands until then. Ask at
   the same time whether a staff deletion before the end of that period is acceptable (currently 30 days).
2. Confirm 5 years for financial documents with the accountant.
3. Approve the index list before Stage 2 drops anything.
4. Decide about `CUSTOMER_MERGE_QUEUE_ENABLED` once the Problems tab shows the counts.

## 11. Left to the builder

Exact catch-up mechanics, per-rule ceilings, autovacuum values, final model field names, chart choices, batch sizes,
and the order of work within a stage.
