# ETA Production Coding — S5 (seal agent writes the bulk EGS sheet) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The signing agent on the seal PC (192.168.1.8) can (a) report the live `D:\invoicer_mini\ElRezeiky_Bulk_EGS_Items.xlsx` back to our server read-only, and (b) replace it with a built sheet version — atomically, with a dated backup, retrying while Invoicer holds the file — nightly and on demand. Built with the write switch **off** and preview as the default mode.

**Architecture:** new model `TaxAgentFileJob` (kinds `egs_fetch`, `egs_write`) on the existing agent pull channel (`signing-agent/next/`, token + finalize account), a file download endpoint and a file upload endpoint for the agent, an agent version handshake, `agent.py` dispatching by kind, a scheduler job, and controls on the «ملف أكواد الإيصالات (المحصّل)» panel.

**Spec:** `docs/superpowers/specs/2026-11-16-eta-production-coding-design.md` §9.2 B, §14.10. S3 (`egs_sheet.py`, `TaxEgsSheetVersion`) is on main.

## Global Constraints
- Worktree `.claude/worktrees/eta-coding-s5`, branch `claude/eta-coding-s5` from main; python `../../../venv/Scripts/python.exe`; tests serial `TEST_DB_NAME=test_eta_coding_s1c --keepdb` (re-seed permissions with `PG_NAME=test_eta_coding_s1c ... seed_permissions` when pharmacist tests fail open; never run test_tax_invoicing on that kept DB); agent tests are plain unit tests with a fake filesystem/HTTP (`deploy/tax_signing_agent/test_agent.py` style if present, else `apps/tests/test_tax_agent_file.py` importing the agent module by path). Next migration after the latest tax_invoicing migration on main (check; S4's PR adds none).
- **Never write without the switch:** `TAX_EGS_SHEET_AGENT_WRITE_ENABLED` (writer flag, default False, forced False in tests). With it off, `egs_write` jobs are created in **preview** mode only: the agent downloads and verifies the hash but writes nothing in `D:\invoicer_mini`; it reports what it would do (live file size/hash, whether it is locked, backup folder writable).
- **Swap procedure on the agent (write mode):** download → verify SHA-256 of the received bytes against the job's `sha256` (computed by the server over exactly the bytes it serves) → write `ElRezeiky_Bulk_EGS_Items.new.xlsx` in the same folder → copy the live file to `D:\invoicer_mini\backup\ElRezeiky_Bulk_EGS_Items.<YYYYMMDD-HHMMSS>.xlsx` (keep newest 30) → `os.replace(new, live)`. If replace raises PermissionError (file in use), retry 5× over ~2 minutes, then remove `.new` and report `busy`, leaving the live file untouched. Any failure → the live file is untouched and the job reports the error.
- **Never open the live file in place:** to read it the agent copies it (to a temp file) and uploads the copy.
- **Only a version that differs from the live file is written:** the server compares the version's coded itemcodes with the last `egs_fetch` report; if the live file's coded rows differ from our last held version (hand edits), the write is **held** and the panel shows the difference; a person chooses «استورد التعديلات» (seed a new version from the fetched copy) or «اكتب فوقها» (audited).
- **Handshake:** the agent sends its version (`X-Tax-Agent-Version`); file jobs are offered only to agent version ≥ 2 (old agents keep receiving only signing jobs — no breakage on the seal PC until it is updated).
- **Paths on the agent are fixed in its config** (`invoicer_dir = D:\invoicer_mini`), never taken from the server.
- Schedule: nightly 03:00 job `egs_sheet_agent_nightly` creates one `egs_fetch` then, if the latest version differs and the switch is on, one `egs_write`; plus panel buttons «اقرأ الملف الحالي» and «اكتب الآن» (approve). Registered in `SCHEDULER_JOB_GUARDS`.
- Every job and outcome audited (`egs_sheet_fetched`, `egs_sheet_written`, `egs_sheet_busy`, `egs_sheet_failed`, `egs_sheet_write_held`).
- Agent endpoints keep the existing auth (token header + dedicated finalize account). File endpoints never take a path from the request; served bytes are exactly the stored version file (no export stamping — bypass/exclude the export middleware for this route and test the served hash).
- Security definition of done: routes under `/api/tax-invoicing/` with matrix permissions; outward write channel listed in `config/writers.py` and doc 36; upload size cap (20 MB) and xlsx validation (zip + DataEntry header) on uploads.

## Review Focus
1. Hash mismatch / truncated download → nothing written, job failed.
2. Invoicer holding the file for the whole retry window → `busy`, live untouched, `.new` removed.
3. Old agent (no version header) polling → never gets a file job.
4. Hand-edited live file → write held, not overwritten.
5. Switch off → preview only, nothing written in `D:\invoicer_mini`.

---

### Task 1: server side — job model, endpoints, handshake
`TaxAgentFileJob` (kind, mode 'preview'|'write', status pending/claimed/done/failed/busy/held, version FK, sha256, result JSON, error, requested_by, timestamps); migration; `signing-agent/next/` returns a file job to agents ≥ 2 when one is pending (signing jobs first); `GET signing-agent/files/<job>/download/` (agent auth; exact bytes; hash header); `POST signing-agent/files/<job>/result/` (agent auth; JSON result, optional multipart upload for `egs_fetch` → stored as a fetched copy, compared with latest version: coded itemcodes diff); creation helpers `egs_agent.request_fetch(actor)`, `egs_agent.request_write(actor)` (mode from the switch; held when the last fetch shows hand edits); scheduler job; writer flag. Tests.

### Task 2: agent side
`deploy/tax_signing_agent/agent.py`: version 2 header, `handle()` dispatch by job kind, `fetch_live(config)` (copy → upload), `write_sheet(config, job)` (procedure above, preview mode), config key `invoicer_dir`, backup pruning; README steps for updating the seal PC; unit tests with temp dirs and a fake locked-file (PermissionError) path.

### Task 3: panel + help + docs
On «ملف أكواد الإيصالات (المحصّل)»: agent status (last seen, version), last fetch (live coded rows, differs-from-latest list), «اقرأ الملف الحالي», «اكتب الآن» (disabled with reason when switch off → preview), held state with «استورد التعديلات» / «اكتب فوقها», job history; help (AR+EN ≤160, `updated`); doc 36 section. vitest + build + help test.

### Task 4: verification
Final whole-branch review, PR, merge by hand when green. Office: migrate, restart (only :8000/scheduler/ami). The seal PC agent update and turning the switch on are the owner's steps (README).
