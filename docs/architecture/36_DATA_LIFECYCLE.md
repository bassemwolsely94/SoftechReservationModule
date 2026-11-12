# 36 — Data lifecycle (Stages 1, 3 and 5)

Status: Stage 1 (retention catch-up, missed-run alert) and Stage 3 (rule register, row and file rules, holding folder,
growth history) BUILT 2026-11-07 on branch `claude/data-lifecycle-stage-3`. Stage 5 (the `/data-health` screen and
its daily snapshot) BUILT 2026-11-12 on branch `claude/data-lifecycle-stage-5-dcb263`. **Every new rule is in
`preview`; nothing new deletes until the owner switches it on.** Stages 2 (compaction) and 4 (upload controls) are
documented with their own branches.
Design: `docs/superpowers/specs/2026-11-07-data-lifecycle-design.md`. Ledger entry: P-56 in
`docs/product-review/00_INDEX_AND_DECISION_LEDGER.md`.

The app is `apps/data_lifecycle`. Company-level by nature (no branch scoping). It never reads or writes SOFTECH.

## Code

| File | Responsibility |
|---|---|
| `register.py` | `RULES`: every rule in code (key, Arabic and English label, kind, floor, default period, reason, breaker margin and ceiling, targets). Admins cannot add a rule or go below its minimum. `KEEP_FOREVER` lists the files kept with no rule. |
| `policy.py` | `get_mode`, `keep_days`, `set_policy`. Refusals hold for admins too: below the minimum period, `on` without a preview under 7 days old, a file rule `on` while `LIFECYCLE_FILE_RULES_ENABLED` is off. |
| `rules_rows.py`, `rules_files.py` | What each rule selects (read only). |
| `references.py` | Reference index over every `FileField` plus the text fields that hold media paths; `partition` splits candidates into movable and shared. |
| `holding.py` | Moves a file and its database references together, holds it 30 days, purges it, restores it. |
| `runner.py` | Preview and real runs, the circuit breaker, the table-size snapshot. Called from `apps/sync/maintenance.py` `run_daily_retention` (lane `retention`). |
| `models.py` | `LifecycleRulePolicy`, `LifecycleRun`, `LifecycleRunLine`, `HeldFile`, `ObsoleteItemSeen`, `UnreferencedFileSeen`, `TableSizeSnapshot`. |
| `health.py`, `problems.py` | Stage 5 daily `DataHealthSnapshot`: database size, estimated empty space (reuses `reclaim_space.table_info`), media sizes per folder and per upload type, disk, and the open data problem counts (each count in its own try; a failure stores None). Step `retention:data_health`. |
| `reports.py`, `views.py`, `urls.py` | Stage 5 API at `/api/data-health/` (payloads in `reports.py`, thin views). |
| `management/commands/lifecycle.py` | `list`, `preview <key>`, `set <key> --mode ... --user ... --reason ...`, `restore <held_id> --user ...`. |

## The register

Mode is `off`, `preview` or `on`. P-56 steps are listed for completeness and are always on.

| Key | Kind | Default period | Breaker margin / ceiling |
|---|---|---|---|
| `rate_runs` | row | last 3 completed runs + last run of each of 24 months + any run still referenced | 150,000 / 1,500,000 |
| `transit_alert_notes` | row | 90 days after the transfer closes (automatic alerts only) | 2,000 / 200,000 |
| `transit_audit_events` | row | 90 days after the transfer closes (`alert_sent` and `synced` only) | 5,000 / 300,000 |
| `prescriptions` | file | 3 years (floor 3 years) | 200 / 5,000 |
| `ocr_pos_rx` | file | 3 years (floor 3 years); image only, readings stay | 200 / 5,000 |
| `conversations` | file | 3 years | 200 / 5,000 |
| `financial_docs` | file | 5 years (floor 5 years) | 100 / 2,000 |
| `bundle_pages` | file | 30 days after the batch's invoices are all finalised or rejected, or the batch failed | 500 / 5,000 |
| `images_rejected` | file | 30 days | 100 / 3,000 |
| `images_unreviewed` | file | 180 days | 100 / 3,000 |
| `images_obsolete` | file | 90 days after the item was first seen obsolete | 100 / 1,000 |
| `delivery_proof` | file | 1 year | 200 / 5,000 |
| `staff_messages` | file | 1 year | 500 / 5,000 |
| `unreferenced` | file | seen on two scans at least 30 days apart | 100 / 1,000 |
| `p56_*` (six) | p56 | engine runs, notifications, PBX events, audit noise, slow requests, screen views | - |

A file rule removes the file and keeps the row. A row whose file is not on disk is not a candidate.

## Behaviour that is easy to get wrong

- **`rate_runs` replaces the P-56 engine step.** While `rate_runs` is on, the P-56 `retention:engine_runs` step does
  nothing and only the rule deletes, so its circuit breaker stands in front of every delete. While it is off or in
  preview, the P-56 step keeps its old rule (last 10 runs + one per month). Run headers always stay, and reviewed
  transfer recommendations (approved, rejected, executed) are never deleted.
- **A restored file is never selected again** by any file rule, whatever its age, until someone changes the file. A
  restore means a person wanted it.
- **Conversation files wait 3 years even when no record uses them.** Orphans under `whatsapp/media/`,
  `callcenter/attachments/` and `callcenter/case_events/` take the `conversations` period; orphans in the prescription
  folders take the `prescriptions` period; orphans in the financial folders take `financial_docs`. A lost row must not
  let a prescription go before one whose row still exists.
- **Approving an emptied image candidate is refused** (HTTP 400, Arabic message). The candidate stays in the review
  queue and can be rejected. Screens show "removed under retention" instead of a broken image.
- **A file used by anything else is never moved.** One reference index is built per run; `partition` skips a path that
  any other record or text field also uses, and the line counts it as `skipped_shared`.
- **Wrong-folder guard.** If more than 5% of the referenced files are missing from disk, every file rule stops for the
  run and admins get one alert (a wrong `MEDIA_ROOT` or an incomplete restore looks like this).
- **Circuit breaker.** A real run stops a rule when its candidates exceed
  `min(ceiling, 1.5 x the unconsumed preview count + margin)`. Every real line consumes the preview before it. After a
  stop, a person must preview again.
- **Switching a file rule `on` is locked** until `LIFECYCLE_FILE_RULES_ENABLED=True`, set only on the VPS: `MEDIA_ROOT`
  is inside OneDrive here, whose version history would keep "removed" prescriptions. A stored `on` reads as `preview`
  while locked.
- **Holding folder.** Removed files go to `LIFECYCLE_HOLD_ROOT` (outside `MEDIA_ROOT`, never served by URL) for 30 days;
  the `retention:purge_held` step then deletes them. An admin can restore within the 30 days.

## Growth history

`retention:table_sizes` runs daily before the rules and writes one `TableSizeSnapshot` row per table of 20 MB or more
(total, heap, index bytes and the row estimate). It reads PostgreSQL's catalog only and never raises, so a failed
snapshot cannot fail the retention run. Its rows written are counted in the step's log line and are not deletions.

## Data health screen (Stage 5)

`/data-health` «صحة البيانات», RBAC module `data_health` (users migration `0054_data_health_module`; renumber at
merge if needed). Company-level by nature, no branch scoping, no SOFTECH. Who sees what (design §7): admin every
tab; supervisor and quality manager `view` = Growth, Problems and the forced refresh; every other role an explicit
denial. Rules, preview, held files, thumbnails and restore are `IsAdminRole` in `views.py`, so a supervisor gets 403
whatever the matrix says (listed in `role_overblocks.txt` with the reason).

| Route | Who | What |
|---|---|---|
| `GET growth/` | viewers | current sizes, 180-day series, forecast, tables (classified or not), upload types, folders, measures |
| `GET problems/` | viewers | counts only, with the previous count and the change |
| `POST refresh/` | viewers | 202; one background `take_snapshot(include_tables=True)` at a time (`cache.add` guard, 15 min) |
| `GET rules/`, `PATCH rules/<key>/`, `POST rules/<key>/preview/` | admin | `policy.set_policy` / `runner.preview_rule`; refusals 400 with the Arabic message |
| `GET held/`, `GET held/<id>/thumbnail/`, `POST held/<id>/restore/` | admin | never `hold_path`, `original_path`, `sha256` or `rows`; thumbnails only for item-image rules on `ImageCandidate` / `ProductMedia` (allowlist), otherwise 404 |

Forecast: rate from the oldest and latest snapshot in the last 30 days of database + media bytes; none when the span
is under 7 days; no date when the rate is zero or negative; level = `DATA_HEALTH_DISK_LEVEL_PERCENT` (default 80).
The Problems tab fixes nothing: each row links to the screen that does. Thumbnails are limited to item images;
prescriptions, `pos_rx` samples, conversations and orphan files never get one. Help: `apps/help/content/data_health.py`.

## Findings

- **Notifications: nothing has been marked read.** The websocket path (`consumers.py _mark_read`) and the REST paths all set both
  `Notification.is_read` and `NotificationLog.read_at`; `test_ws_mark_read_updates_row_and_log` passed on the first run.
  On the office database (read-only counts, 2026-11-08): 758,692 notifications, 0 with `is_read`; 758,456 logs, 0 with
  `read_at`. Both read paths work in tests and nothing has been marked read, so the counts alone do not say whether the
  bell is unused or marking is broken in live use; the owner's one live click settles which it is. Until then, the P-56
  rule "read after 30 days" never fires; only the 90-day unread rule
  removes anything.
- **Transit alerts were written daily.** `sync_in_transit` now writes a note and an `alert_sent` event only when the
  level changes (about 148,500 repeat notes and 148,400 repeat events exist from before). The daily digest
  notification is unchanged.
- **Same-date engine runs.** Five readers that take no run filter can mix two runs of the same date; pruning does not
  cause this. Forecasting and incentives were fixed to use the latest run only.
- **Dead-stock comparison.** After pruning, `rule_dead_stock_growth` may compare against a run about 20 to 50 days old
  (not about 30). The message prints the date.
- **Follow-ups, not built:** 19 `image_url` values point at `http://localhost:8000/...` (save a relative path in
  `views.py`, and correct those rows before cutover); `reprocess` leaves the deleted invoices' images behind (Stage 4).

## How to switch a rule

1. `python manage.py lifecycle list` shows mode and period for every rule.
2. `python manage.py lifecycle preview <key>` counts what the rule would remove and writes a preview line. Nothing
   changes. Read the count against the rule's margin and ceiling.
3. `python manage.py lifecycle set <key> --mode on --user <admin> --reason "..."` needs a preview under 7 days old
   with no error, and writes an `AuditLog` row with before and after. `--keep-days N` only lengthens a period.
4. After a first large cleanup (count above the margin), preview again right before it. The day after, the margin
   applies.
5. To undo: `lifecycle set <key> --mode off ...`, and `lifecycle restore <held_id> --user <admin>` for a file still in
   the holding folder.

File rules also need `LIFECYCLE_FILE_RULES_ENABLED=True`, which is set on the VPS only after the media copy is
verified (see `docs/deploy/2026-11-owner-go-live-steps.md` section 4).

## Office rehearsal (2026-11-07, read only)

Figures from a read-only script on the office database (it has no lifecycle tables, so policies read as defaults):
`rate_runs` 352,163 rows over 99 of 110 runs (above the 150,000 margin, so it needs its own preview first),
`transit_alert_notes` 100,755 and `transit_audit_events` 111,643 (both above their margins, below their ceilings),
`images_rejected` 798 files / 63 MB, every other file rule 0 or "clock not started", and the wrong-folder guard at
0 of 3,712 referenced files missing. Nothing was switched on.
