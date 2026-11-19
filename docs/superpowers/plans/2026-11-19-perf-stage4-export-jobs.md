# Performance Stage 4 — exports off the web request (plan)

**Design:** `docs/superpowers/specs/2026-11-19-performance-boost-design.md` §2, §4 (export start ≤ 1 s),
§6 Stage 4, §9, §10. **Baseline:** `docs/full-project-audit/07_PERFORMANCE_AUDIT.md` §6.1.

## 1. Inventory (34 routes with `export` in the URL + other `openpyxl` / CSV writers in views)

Cost = the slow-request log (P-56) max where it exists, otherwise a reading of the code
(size of the data read). "Job" = moves to the shared export job; "sync" = stays a direct download
(< ~3 s) and only has to use the streaming writer.

| # | Route | Writer | Cost today | Reads SOFTECH live? | Stage 4 |
|---|---|---|---|---|---|
| 1 | `purchasing/export/` (flat xlsx/csv + pivot v2) | `apps/purchasing/views.py` `_export_xlsx`, `_export_csv`, `_export_xlsx_pivot_v2` (already write-only) | **164 s** (log max), 127 s mean | no | **PR 1 — job** |
| 2 | `purchasing/isr/fulfilment/export/` (POST) | `isr_fulfillment.build_workbook` (formulas kept safe) | **49 s** (log max) | yes, when the screen's cached snapshot has expired (`F.collect`) | **PR 1 — job, in-process thread only** (§10) |
| 3 | `pic-analytics/export/jobs/` | `pic_analytics/export.py` | 12-month file > 60 s | no | **PR 1 — moved onto the shared job, same behaviour** |
| 4 | `purchasing/advanced-export/`, `advanced-pivot-export/` | `purchasing/views.py` | engine-size (like #1) | no | PR 2 — job |
| 5 | `purchasing/shortage/export/` | `shortage_views.py` | screen data was 19–33 s before PR 233 | no | PR 2 — job |
| 6 | `purchasing/isr/transfer-preview/export/`, `isr/distribution/plan/<pk>/export/`, `isr/branch-requests/<pk>/analysis/export/` | `isr_views.py`, `branch_request_views.py` | ISR-size | some read SOFTECH | PR 2 — job (SOFTECH ones on the thread) |
| 7 | `batches/stock-expiry/export/`, `…/disposal/export/`, `purchase-expiry/export/`, `return-window/export/` | `batches/views.py` | summary screen was 4–7 s | no | PR 2 — job |
| 8 | `stock-audit/findings/export/` | `stock_audit/views.py` | HQ stktrans mirror, large | no | PR 2 — job |
| 9 | `tax-invoicing/history/{documents,receipts,recon,recon/uncoded}/export/` | `history_views.py` | months of documents | no | PR 2 — job |
| 10 | `finance/receivables`, `cash-view`, `supplier-terms`, `reconciliation/{partial,unpaid,review,returns-chains}` exports | `apps/finance/*` | report-size | no | PR 2 — measure; job if > 3 s |
| 11 | `forecasting/kpi-board/export/`, `gamification/reports/export/`, `hr-attendance/month/export/`, `product_experience/export/`, `vouchers/coupons/batches/<pk>/export/`, `purchasing/rates/pushes/<pk>/export/` | various | small (one board / month / batch) | no | sync — streaming writer check |
| 12 | Other writers in views (supply tab exports, transits sheets, insurance claim exports, invoices, reservations, incentives, cover tiers, dead stock, commerce, GL exports, stockcount, rpa, egs sheet) | various | mostly small; insurance and supply tabs can be large | some | PR 2/3 — measure each, same rule |

`usage-print/sheet/` (132 s in the log) is **not an export**: it is the interactive invoice lookup
that falls back to one live SOFTECH read. The time is the connection to an unreachable node (the
query has a 15 s timeout, the connect has none). That is a SOFTECH-read fix (Stage 6 /
`config/sybase.py` connect timeout), reported to the coordinator, not part of this stage.

## 2. Shared export job (`apps/export_jobs`)

- **Model `ExportJob`** (generalised `PicExportJob`): `kind`, `requested_by`, `params` (raw query
  params or the JSON body), `meta` (effective filters for the audit entry), `status`
  queued/running/done/failed, `progress_pct`, `progress_msg`, `file_name`, `content_type`,
  `data` (bytes in the DB, never under /media), `rows`, `error`, `worker` (thread / service),
  `created_at`, `started_at`, `heartbeat_at`, `finished_at`. One active job per user per kind
  (partial unique constraint). 48 h retention. `PicExportJob` is removed (its rows live 48 h).
- **Kinds** (`registry.py`): key → `allowed(user)`, `validate(request)` (cheap, answers 400 now),
  `build(job, progress)` → bytes + file name + content type, `needs_softech` (thread only),
  `audit_action` (an extra kind-specific audit row at download, PIC keeps
  `pic_analytics_exported`).
- **Builders reuse today's code.** The view body becomes a plain function of a request; the job
  replays a request built from the stored params and the requester (`GET` / `data` / `user`).
  Same code path → same sheets, columns and values; the formula guard, branch labels and masking
  stay where they are.
- **Start** (`POST <module>/…/export/jobs/`): validate, housekeeping, create, dispatch; returns 202
  `{id}` (409 `{id}` when one is already running). No file work in the request → ≤ 1 s.
- **Status / download** (`GET /api/export-jobs/<id>/`, `…/download/`): owner only (another user's
  id = 404), the kind's permission re-checked at download (403 when revoked), file sent as an
  attachment so `ExportAuditMiddleware` writes `export_taken` and stamps the xlsx (N5).
- **Runner:** `manage.py run_export_jobs` claims queued jobs with
  `SELECT … FOR UPDATE SKIP LOCKED` (one at a time, no JVM), unit
  `deploy/elrezeiky-jobs.service`, env `EXPORT_JOBS_RUNNER=service`. Without that env (dev,
  office) a job runs on today's in-process thread. Kinds that read SOFTECH live always use the
  thread (§10). A queued/running job with no progress for 15 min is reported failed (restart).
- **Housekeeping:** every start + nightly (`_run_pic_facts` now calls the shared cleanup).

## 3. Front end

`useExportJob` hook + `ExportJobStatus` (progress bar, error + retry): start → poll 1.5 s →
download once → forget. The job id is kept in sessionStorage per screen so leaving and coming
back keeps the job. PIC, purchasing and ISR fulfilment use it in PR 1.

## 4. PRs

1. Shared job + runner + unit + runbook; PIC move; purchasing/export; ISR fulfilment export.
2. Rows 4–9 as jobs; rows 10–12 measured and either jobbed or confirmed streaming.

## 5. Tests (TDD)

- `apps/tests/test_export_jobs.py`: start/202/409, owner-only 404, revoked 403, stale → failed,
  48 h cleanup, failure message safe, service mode leaves queued + `claim_next` with skip-locked,
  softech kind stays on the thread, download writes `export_taken`.
- Per kind: job file == old direct file (sheets, headers, every cell value), start query budget.
- `apps/tests/test_pic_export_jobs.py` unchanged in behaviour (model name only).
