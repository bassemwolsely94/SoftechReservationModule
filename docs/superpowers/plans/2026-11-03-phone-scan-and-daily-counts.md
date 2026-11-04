# Phone Scan + Daily Counts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Camera barcode scanning in the shared item search, and risk-weighted blind daily counts (20 items per salesperson) with manager → auditor review — all dark by default, no SOFTECH writes.

**Architecture:** (a) one generalised camera component plugged into `ItemSearchWidget`. (b) a new `mode='daily'` inside `apps/stockcount`: a `DailyCountPick` per assigned item and an immutable `DailyCountAttempt` per count; the existing `StockCountSnapshot` row is written from the latest attempt so stock-audit and existing screens keep working. Picker = pure deterministic function over mirrored data.

**Tech Stack:** Django 4.2 + DRF, PostgreSQL, APScheduler (`apps/sync/tasks.py`), React 18 + Vite + TanStack Query, `@zxing/browser` (bundled, lazy-loaded).

**Spec:** `docs/superpowers/specs/2026-11-03-phone-scan-and-daily-counts-design.md`

## Global Constraints

- Switches default OFF: `CAMERA_SCAN_ENABLED`, `DAILY_COUNT_ENABLED` (settings.py via `config(..., default=False, cast=bool)`; tests already force `_ENABLED` off) + `BranchSettings.daily_count_enabled` (default False).
- No SOFTECH writes. Reads only through `apps.stockcount.engine.fetch_stock_balance` (existing HQ path) **[plan call: HQ instead of branch-node-first — existing tested reader]**.
- Server-side permission + branch scope; reviewer = `apps.stock_audit.access.Access` (named branch managers + management).
- Every state change → `AuditLog.log(<new action>, user=profile, obj=..., old_data/new_data, note)`.
- Counter APIs never return `expected_qty`, `difference`, `value_egp`, or pick reasons.
- Defaults: 20 items/person, rotation 14 days, near expiry ≤ 90 days, adjustments window 60 days, escalate at |value| ≥ 200 EGP or ≥ 3 differences on same item/branch in 30 days, pharmacists excluded, day end = branch close or midnight Cairo.
- Help AR+EN for every touched screen (`apps/help/content/stockcount.py`, `catalog.py`/screens with 📷), `apps/tests/test_help.py` green.
- Tests run with a unique `TEST_DB_NAME` (other sessions share the server).

## Review Focus

1. A salesperson with no `branch` or an inactive profile → no list, no crash in the job.
2. Same item scanned twice / count submitted twice quickly (double tap, offline replay) → one attempt per submit, result = latest; no duplicate pick rows.
3. SOFTECH unreachable at submit → count stored with mirror expected and `expected_source='mirror'`; never 500.
4. Job re-run the same day (scheduler restart) → no duplicate sessions/picks (unique constraint + get_or_create).
5. Camera denied / no camera / iPhone without BarcodeDetector → calm message, typing still works; button hidden when switch off.

---

### Task 1: Camera scanning in the shared item search

**Files:**
- Create: `frontend/src/components/BarcodeScanner.jsx`, `frontend/src/hooks/useFeatures.js`
- Modify: `frontend/src/components/QrScanner.jsx` (thin wrapper over BarcodeScanner, formats `['qr_code']`), `frontend/src/components/ItemSearchWidget.jsx`, `frontend/package.json` (`@zxing/browser` pinned), `config/settings.py` (`CAMERA_SCAN_ENABLED`, `DAILY_COUNT_ENABLED`), `apps/users/views.py` (`_MeSerializer.features`)
- Test: `apps/tests/test_daily_count_flags.py`

**Interfaces:**
- Produces: `/api/auth/me/` → `features: {camera_scan: bool, daily_count: bool}`; `useFeatures()` → `{cameraScan, dailyCount}` from authStore user; `<BarcodeScanner onScan(text) onClose continuous? formats? />`.

- [ ] Test `test_me_features_default_off` (both False) and `test_me_features_on` with `override_settings(CAMERA_SCAN_ENABLED=True, DAILY_COUNT_ENABLED=True)`; run → fail.
- [ ] Add settings + `features` SerializerMethodField; run → pass.
- [ ] BarcodeScanner: native `BarcodeDetector` when `getSupportedFormats()` covers ean_13; else dynamic `import('@zxing/browser')` `BrowserMultiFormatReader.decodeFromVideoDevice`. Formats: ean_13, ean_8, upc_a, upc_e, code_128, code_39, itf, qr_code. Torch toggle if `track.getCapabilities().torch`. `navigator.vibrate?.(60)` on read. Continuous mode ignores the same code within 1.5 s.
- [ ] ItemSearchWidget: 📷 button inside input when `cameraScan && navigator.mediaDevices?.getUserMedia`; scan → set query to code → when the results resolve to exactly one item whose `barcode`/`softech_id` equals the code (or the API's exact-match marker) call `onSelect(item)`; none → inline «لم يُعثر على الباركود: <code>».
- [ ] `npm run build` + lint pass; commit `feat(scan): camera barcode scanning in the shared item search (CAMERA_SCAN_ENABLED, off)`.

### Task 2: Daily-count models + picker

**Files:**
- Modify: `apps/stockcount/models.py` (MODE `('daily', 'جرد يومي')`; `StockCountSession.assigned_to` FK StaffProfile null, `count_date` Date null; UniqueConstraint (assigned_to, count_date, branch_code) where mode='daily'), `apps/branches/models.py` (`BranchSettings.daily_count_enabled`)
- Create: `apps/stockcount/daily/__init__.py`, `daily/models_` → put models in `apps/stockcount/models.py`: `DailyCountPick`, `DailyCountAttempt`, `DailyCountSettings` (singleton); `apps/stockcount/daily/picker.py`; migrations
- Test: `apps/tests/test_daily_count_picker.py`

**Models:**
- `DailyCountPick(session FK, item_code, item_name, reasons JSON list[str], weight Decimal, status in pending|counted|recount|accepted|escalated|missed, latest_attempt FK null, assigned_recount_to FK null, review_reason, review_note, reviewed_by, reviewed_at, escalated bool, escalation_reason)` unique (session, item_code).
- `DailyCountAttempt(pick FK, counted_by FK, counted_qty, expected_qty, expected_source in live|mirror, expected_read_at, difference, value_egp, physical_expiry null, client_token unique null, created_at)` — no update path.
- `DailyCountSettings` fields = defaults from Global Constraints + weights (`w_value, w_rate, w_adjust, w_finding, w_loss, w_expiry, w_never` default 1) + `include_pharmacists`, `job_hour=7`.

**Interfaces:**
- Produces: `picker.candidates(branch, today) -> list[Candidate(item_code, item_name, weight, reasons)]`; `picker.draw(candidates, people:list[int], per_person:int, seed:str) -> dict[int, list[Candidate]]`.

- [ ] Tests: `test_weights_reasons` (high value item gets «قيمة عالية»), `test_negative_stock_eligible`, `test_quarantine_and_zero_excluded`, `test_recently_counted_skipped_unless_flagged`, `test_draw_deterministic_same_seed`, `test_draw_no_overlap_between_people`, `test_fewer_items_than_needed`. Run → fail.
- [ ] Implement: signals from `ItemStock` (branch, exclude store codes 102/103/105/110), `Item.cost_price`, `ItemStock.monthly_qty`, `StockLedgerLine` doccode 50/150 within window, open `StockAuditFinding`, past `DailyCountAttempt` differences, `StockExpiryBalance` ≤ 90 d, last count date. Normalise each signal to 0..1 by branch percentile; weight = 0.1 + Σ wᵢ·sᵢ; reason when sᵢ ≥ 0.7 (or boolean signals true). Draw = Efraimidis–Spirakis keys `u**(1/w)` with `random.Random(seed)`, then round-robin to people.
- [ ] Migrate, tests pass; commit.

### Task 3: Generation, counting, review services + API

**Files:**
- Create: `apps/stockcount/daily/service.py`, `apps/stockcount/daily/views.py`, `apps/stockcount/daily/serializers.py`
- Modify: `apps/stockcount/urls.py`, `apps/audit/models.py` (actions `daily_count_generated, daily_count_counted, daily_count_recount, daily_count_accepted, daily_count_escalated`), `apps/sync/tasks.py` (job `daily_count_generate` hourly at :05, runs per branch whose local time ≥ job_hour and no list yet; also marks missed after close), `apps/stockcount/views.py` (exclude `mode='daily'` from the session list unless `?mode=daily`), `apps/gamification` defaults (new rule `daily_count_completed` inactive; exclude daily from `stockcount_completed`)
- Test: `apps/tests/test_daily_count_api.py`

**Interfaces:**
- `service.generate(branch, day, by=None) -> int` (idempotent; skips approved `LeaveRequest` covering day; roster = active `StaffProfile.branch=branch`, role salesperson [+pharmacist if setting]).
- `service.record_count(pick, profile, counted_qty, physical_expiry=None, client_token=None) -> DailyCountAttempt` (live read via `fetch_stock_balance`, fallback `ItemStock` sum; writes snapshot row expected/counted/difference; pick → counted, or escalated per rules; manager-own-count or branch without named manager → escalated).
- `service.request_recount(pick, reviewer, assignee) / accept(pick, reviewer, reason, note, needs_softech_adjustment) / escalate(pick, reviewer, note)`.
- `service.close_day(branch, day)` → pending picks → missed.
- Endpoints under `/api/stockcount/daily/`: `my/` GET (today's list, blind), `my/count/` POST, `board/` GET (manager/auditor: per-person progress + differences, `?branch=&date=`), `picks/{id}/recount|accept|escalate/` POST, `generate/` POST (admin), `report/` GET (+ `?export=xlsx`), `settings/` GET/PATCH (management edit).
- All return 404 when `DAILY_COUNT_ENABLED` False; branch flag checked on generate/count.

- [ ] Tests: `test_switch_off_404`, `test_generate_idempotent_and_skips_leave`, `test_my_list_is_blind` (no `expected_qty` key anywhere in JSON), `test_count_uses_live_then_mirror` (patch `fetch_stock_balance` to raise → source 'mirror'), `test_double_submit_same_token_one_attempt`, `test_salesperson_cannot_review`, `test_manager_other_branch_403`, `test_manager_own_count_goes_to_auditor`, `test_escalate_on_value_and_repeat`, `test_accept_writes_audit`, `test_close_day_marks_missed`, `test_existing_session_list_hides_daily`. Run → fail.
- [ ] Implement; tests pass; run existing `test_stockcount_close`, `test_stock_audit_*`, `test_scheduler_jobs`, gamification tests; commit.

### Task 4: Phone counting screen

**Files:** Modify `frontend/src/pages/mobile/MobileStockCountPage.jsx` («جردي اليوم» card at top when `dailyCount` feature + list exists), Create `frontend/src/pages/mobile/MobileDailyCountPage.jsx` (route `/m/stock-count/today`), `frontend/src/api/client.js` (`dailyCountApi`), router file.
- [ ] List of 20 with done ticks, reminder line «اجرد كل الكمية بالفرع: الرف + المخزن + المحجوز», continuous camera scan → jumps to item → packs (+ strips when unit item) qty → submit via `queuedPost` with `client_token`; near-expiry picks show expiry field. Item not on list → «هذا الصنف ليس ضمن جردك اليوم».
- [ ] Build + lint; commit.

### Task 5: Manager / auditor screens + reports

**Files:** Create `frontend/src/pages/stockcount/DailyCountTab.jsx` (tab «الجرد اليومي» in `StockCountPage.jsx`, visible when `dailyCount` && can review), mobile manager section in `MobileDailyCountPage` for reviewers.
- [ ] Progress per person (done/partial/not started/missed), differences grid (sortable `useSortableRows`, `useGridKeyboard`), actions recount (pick assignee) / accept (reason dropdown + note + «يحتاج تسوية في SOFTECH» checkbox) / escalate; 7/30-day report + Excel (`useBranchLabels`).
- [ ] Build + lint; commit.

### Task 6: Help, docs, full verification

- [ ] Help AR+EN: stockcount (daily tab, `/m/stock-count/today`, statuses), 📷 line on item-search screens; bump `updated`; `useHelpTab` on the new tab. Docs: 02, 07, 11, 12. `manage.py help_tour_coverage` if tours required.
- [ ] Run: full `apps/tests` relevant suites + `test_help`, `npm run build`, `npm run lint`. Commit.
