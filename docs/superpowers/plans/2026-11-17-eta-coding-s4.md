# ETA Production Coding — S4 (code requests to ETA production) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Items a person decided «كوّد» (with a confirmed brick and VAT) can be prepared and sent as EGS code requests to the ETA **production** system from our screens, followed until ETA decides; an approved code makes the item white; a rejected EGS can be retried as GS1. Everything is built with the production coding switch **off**; the first real send is the owner's yes at that moment.

**Architecture:** a per-system coding client (`eta_coding_client.py`) with its own login/token/pace, `coding.py` send/refresh/check taking an explicit system, gates in one function, a «طلبات الإنتاج» panel on «طابور الترميز».

**Spec:** `docs/superpowers/specs/2026-11-16-eta-production-coding-design.md` §7, §14.2–§14.4, §14.10. Branch base: `claude/eta-coding-s3` (PR 165 — S4's PR targets main after 165 merges).

## Global Constraints
- Worktree `.claude/worktrees/eta-coding-s4`, branch `claude/eta-coding-s4`; python `../../../venv/Scripts/python.exe`; tests serial `TEST_DB_NAME=test_eta_coding_s1c --keepdb` (re-seed permissions when pharmacist tests fail open: `PG_NAME=test_eta_coding_s1c ... seed_permissions`; help tests on `TEST_DB_NAME=test_eta_s1_t8_help`). Never real HTTP in tests.
- **Gates for any production code request, all required:** `TAX_ETA_CODING_PRODUCTION_ENABLED` (new, default False, in `config/writers.py` `WRITER_FLAGS` with an Arabic `protects` text, read via `writer_allowed`; forced False under tests) · matrix `finalize` · typed count equal to the number of requests. `TAX_ETA_PRODUCTION_ALLOWED` is **not** reused (it also unlocks invoice sending).
- **First-request rule:** while no production request has reached `approved`, a production send of more than 1 request is refused («أرسل طلباً واحداً أولاً حتى تعتمده المصلحة»), unless `TAX_ETA_CODING_PRODUCTION_BATCH_OK` (writer flag, default False).
- **Production login:** `TAX_ETA_PRODUCTION_CLIENT_ID/_SECRET`, falling back to `TAX_ETA_READ_PRODUCTION_CLIENT_ID/_SECRET` (owner chose the same registration). Its own token cache and pace (2/s), never `EtaReader`'s state, never `eta_client`'s single-system state. Secrets never logged or in error text (`core.errors.public_error` / `redact`).
- Preprod behaviour unchanged (S1): preprod requests never touch the profile; the server still sends preprod through its existing configured system.
- Prepared from the decision: brick = `decision.brick` (required, `gpc.known`), names from the decision, `active_from` = 1 January of the current year, reason default «صنف صيدلي يُباع للعملاء». Only items with `decision='code'`, a brick, a confirmed treatment, no open production request, not already approved.
- ETA approval of a production request whose item has a `code` decision → profile `coding_status='approved'`, `list_status='white'`, `disposition='include'`, `coding_env='production'` (audited `item_coding_from_eta`). Nothing becomes white otherwise.
- GS1 fallback: when the latest production EGS request is `rejected` and `coding.gtin_for(item)` gives a valid GTIN, the row offers «جرّب GS1» → `prepare_gs1(..., system='production')`. Never automatic.
- Every send/refresh/prepare/cancel audited (already in coding.py); refused rows visible in the UI with their Arabic reason (the S1 `results['refused']` finally surfaced).
- Security definition of done: new routes under `/api/tax-invoicing/` with matrix permissions (prepare/cancel `edit`... keep existing coding view permissions; send `finalize`); the outward ETA channel listed in doc 36 and the writer-flags list; SECURITY sweeps pass.

## Review Focus
1. Server configured for preprod (`TAX_ETA_ENVIRONMENT=preprod`) sending a production request → goes to the production host with the production login, never to preprod; and the reverse never happens.
2. Switch off / not finalize / wrong typed count / first-request rule → nothing is sent, clear Arabic reason, no request leaves `prepared`.
3. Timeout/5xx on send → request `uncertain`, batch stops (existing behaviour) — no resend until refresh.
4. Refresh of a production request on a preprod server uses the production client (S1 limited refresh to the server's own system; S4 refreshes production rows through the production client).
5. An approved production request for an item with no `code` decision (e.g. prepared from the old codes tab) → profile approved but list_status unchanged (stays as is) — only a person's «كوّد» makes it white.

---

### Task 1: production coding client + gates
**Files:** create `apps/tax_invoicing/eta_coding_client.py` (`CodingClient(system)`: `configured()`, `create_egs_codes(items)`, `request_code_reuse(items)`, `my_code_requests(item_code)`, `code_details(code_type, item_code)` — same request/response handling and exceptions (`EtaUncertain`, `EtaRefused`, `EtaNotConfigured`) as `eta_client`, hosts from `environment.ENVIRONMENTS[system]`); `config/settings.py` + `config/writers.py` (two new flags, forced False in tests; the two production client settings); `coding.py`: `production_gate(rows, actor_can_finalize, confirm) -> None | raises TaxRuleError` and `client_for(system)` (production → `CodingClient('production')`; the server's own send system → existing `eta_client` path); `send`, `refresh`, `check_codes` use `client_for(row.environment)`; refresh includes production rows on any server. Tests with mocked `requests`.
- [ ] Commit `feat(tax): production coding client and send gates`.

### Task 2: prepare from decisions, approval → white, GS1 offer
**Files:** `coding.py` (`prepare_from_decisions(itemcodes, actor, system='production') -> {'created','skipped'}`; `_apply_eta_answer` white/include on production approval when a `code` decision exists); `coding_queue.rows()` adds `request` = latest production request {id, status, eta_status, error} and `gs1_offer` (bool + gtin); views/urls: `POST codes/queue/prepare/` (EDITOR/APPROVER as the existing prepare view uses), reuse existing `codes/send/` + `codes/refresh/` + `codes/<pk>/cancel/` with system handled server-side; `POST codes/queue/gs1/`. Tests.
- [ ] Commit `feat(tax): code requests prepared from coding decisions; ETA approval makes the item white`.

### Task 3: «طلبات الإنتاج» panel + help + docs
**Files:** `QueueTab.jsx` / new `ProductionRequestsPanel.jsx`: decided items ready to request (count), «جهّز الطلبات», list of production requests (status, ETA status, error, refused reasons), «أرسل» with typed count (inline input, no modal), switch-off notice (from the API: `{enabled, first_request_pending}`), «حدّث من المصلحة», «جرّب GS1» on rejected rows with a GTIN; client methods; help (AR+EN ≤160, `updated`); doc 36 (production coding: gates, login, first-request rule, approval → white, GS1). vitest + build + help test.
- [ ] Commit `feat(tax): production code requests panel`.

### Task 4: verification
- [ ] Final whole-branch review, PR (base main after PR 165 merges), merge by hand when green. Office: migrate, restart; switch stays OFF; the first real request needs the owner's yes and one item.
