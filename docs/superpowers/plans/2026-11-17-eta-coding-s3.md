# ETA Production Coding — S3 (bulk EGS sheet build + downloads) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Our system produces Invoicer's `ElRezeiky_Bulk_EGS_Items.xlsx` from its own records — every coded row carried forward untouched, newly coded items filled in — checked before it is accepted, stored as numbered versions, downloadable in full (A) or as new rows only (C). No automatic write to the seal PC yet (S5).

**Architecture:** `egs_sheet.py` (seed, build, checks, diff), model `TaxEgsSheetVersion`, files kept outside the web root, endpoints + a panel on «طابور الترميز», recon `coded_items()` switches to the latest version.

**Tech Stack:** Django/DRF, openpyxl (full load, not read-only, to keep styles/table/defined names), React.

**Spec:** `docs/superpowers/specs/2026-11-16-eta-production-coding-design.md` §3, §9.1, §9.2 A/C, §14.1, §14.8.

## Global Constraints
- Worktree `.claude/worktrees/eta-coding-s3`, branch `claude/eta-coding-s3`; python `../../../venv/Scripts/python.exe`; tests serial `TEST_DB_NAME=test_eta_coding_s1c --keepdb` (re-seed permissions with `PG_NAME=test_eta_coding_s1c ... seed_permissions` when pharmacist tests fail open; help tests on `TEST_DB_NAME=test_eta_s1_t8_help`). Next migration after `0019_brick_suggestion`; `db_default` on new non-null columns.
- **Rows already coded in the held sheet are never rewritten** (A..P untouched, incl. the 324 sheet-14%/SOFTECH-0% rows). Build only (a) codes an existing uncoded row of a newly coded item, (b) appends a row for an item not in the sheet. Never removes a coded row.
- **A newly coded item** = no keep-out decision AND treatment confirmed (taxable 14 or exempt 0) AND a code ETA holds: profile `coding_status='approved'` with `coding_env='production'`, or an approved/active production `EtaCodeUsage` matched to the item. Code type EGS (B = `EG-499336534-<itemcode>`) or GS1 (B = barcode). Brick: decision.brick → EtaCodeUsage.gpc → profile.gpc_code; none → item not written (reported). Names: decision names → ETA code_name → profile names. ActiveFrom (G) = ETA active_from date, else 1 January of the current year. K = 0 or 0.14 from the confirmed treatment; J = itemcode as a number when numeric.
- Formula columns L, N, O, P on a coded/appended row use the same formulas as the sheet with the row number translated (`openpyxl.formula.translate.Translator`); new rows copy the style of the row above.
- **Checks before a version is accepted** (any failure → no version, Arabic reason): same sheet names and DataEntry header; no duplicate J (itemcode) and no duplicate coded B; every coded row has A in {EGS,GS1}, B, G, I ≠ 0, K in {0, 0.14}; no keep-out item coded; coded-row count ≥ the held sheet's; the saved file re-opens and re-reads the same counts.
- The Invoicer file is a workbook, not a report: no formula neutralising (documented exception to `core/export_safety.py`), but downloads are audited (`TaxAuditEvent` `egs_sheet_download` with version + kind).
- Files stored under `TAX_EGS_SHEET_DIR` (setting; default `BASE_DIR / 'private' / 'egs_sheets'`, outside MEDIA_ROOT and git-ignored), keep the newest 10 versions' files (rows kept).
- Build / seed / download need matrix `approve` (download of the Invoicer master file is sensitive); listing versions needs `view`.
- Never write the owner's original file.

## Review Focus
1. A held sheet whose DataEntry has extra trailing empty rows / the table ref not covering appended rows → appended rows inside the Excel table (update table ref + autofilter).
2. An item coded in the sheet AND newly approved on production → untouched (counts unchanged), not duplicated.
3. Item numeric vs text itemcode in J (sheet stores numbers) → duplicate detection treats '100' and 100 as the same.
4. Build run twice with nothing new → no new version (same content hash) — idempotent.
5. Large file (15 MB, 36k rows): build completes in reasonable time and memory (one load, one save); progress not required.

---

### Task 1: version model, seed, storage
**Files:** models (`TaxEgsSheetVersion`: `number` (unique, int), `sha256` (64), `file_name` (200), `size` (int), `coded_rows` (int), `total_rows` (int), `added` (JSON list of itemcodes), `coded` (JSON list of itemcodes newly coded on existing rows), `skipped` (JSON list of {itemcode, why}), `coded_itemcodes` (JSON list — every coded itemcode in this version, for the recon), `source` ('seed'|'build'), `built_by`, `built_at`, `note`); migration 0020; setting `TAX_EGS_SHEET_DIR`; `.gitignore` entry `private/`; `egs_sheet.store(bytes, **meta) -> TaxEgsSheetVersion` (hash, write file, prune files beyond 10), `egs_sheet.latest()`, `egs_sheet.open_version(v) -> bytes`; command `egs_sheet_seed PATH` (reads the owner's file read-only, computes coded rows/itemcodes from DataEntry (coded = A and G filled), stores version 1 source 'seed', audited; refuses if a version exists unless `--force-new`); `eta_recon.coded_items()` reads `latest().coded_itemcodes` when a version exists, else the workbook rule (unchanged).
- [ ] Tests (temp dir via override_settings; tiny xlsx fixture built in the test with the 16 DataEntry headers incl. formulas): seed counts, idempotent seed refusal, file pruning, coded_items source switch. Commit.

### Task 2: build + checks
**Files:** `egs_sheet.py` (`candidates() -> list[dict]`, `build(actor, note='') -> TaxEgsSheetVersion | dict(refused=[...])`, `checks(wb, held_counts) -> list[str]`), tests.
- [ ] Tests: carries coded rows untouched (cell-by-cell for a coded row); codes an existing uncoded row (A,B,C,D,E,F,G,I,J,K + translated formulas); appends a missing item (style copied, inside the table ref); keep-out excluded; unconfirmed VAT skipped with reason; no brick skipped; GS1 row; each check refusal; no-change build → returns existing latest, no new version; '100' vs 100 duplicates. Commit.

### Task 3: endpoints + panel + help
**Files:** views/urls: `GET codes/sheet/` (VIEWER: versions list + `pending` = candidates count and skipped reasons), `POST codes/sheet/build/` (APPROVER), `GET codes/sheet/<n>/download/?kind=full|new` (APPROVER; full = the stored file; new = a small xlsx with the same 16 headers and only the added/coded rows' values); client methods; panel «ملف أكواد الإيصالات (المحصّل)» on «طابور الترميز»: latest version, counts (coded rows, added, coded, skipped with reasons), build button, two downloads, reminder «بعد استبدال الملف في D:\invoicer_mini أغلق Excel — الملف المفتوح يوقف رفع الإيصالات»; help entry (AR+EN, ≤160, `updated`); vitest.
- [ ] Tests (403 pharmacist / viewer for build+download, audit on download, new-rows file content). Commit.

### Task 4: docs + verification
- [ ] Doc 36 section «ملف الأكواد للمحصّل»; run labels serially; vitest; build; final whole-branch review; PR; merge by hand when green; office: `egs_sheet_seed` with the office copy, first build, show counts.
