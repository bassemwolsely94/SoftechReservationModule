# ETA Production Coding — S2 (GPC brick suggestion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every item in «طابور الترميز» shows a suggested GPC brick — learned from what is already coded first, AI only for the rest — and a "code it" decision records a brick a person confirmed.

**Architecture:** `gpc_learn.py` (deterministic sources), `gpc_ai.py` (AI over a shortlist, guarded), model `TaxBrickSuggestion` (one per item, cached), queue rows + decide carry the brick, a picker in `QueueTab.jsx`. AI runs only in a background job behind a default-off switch.

**Tech Stack:** Django/DRF, PostgreSQL, React/Vite, existing AI provider chain `apps/enrichment/ai_extractor.complete_json` (Gemini → OpenAI, rate-limited).

**Spec:** `docs/superpowers/specs/2026-11-16-eta-production-coding-design.md` §5 (+ §14.7). New fact (2026-11-17): ETA's code-usage rows carry the brick as `parentItemCode` — 13,070 approved codes, a much stronger learning source than the workbook.

## Global Constraints
- Branch `claude/eta-coding-s2`, worktree `.claude/worktrees/eta-coding-s2`, python `../../../venv/Scripts/python.exe`; tests serial with `TEST_DB_NAME=test_eta_coding_s1c --keepdb` (re-seed with `PG_NAME=test_eta_coding_s1c ... seed_permissions` if permission tests fail open; a clean CI DB is the final check).
- New non-null columns need `db_default` (migration rule test). Next migration after `0018_coding_decision`.
- The AI only proposes a category; it never decides a code, a rate, or whether an item is coded (CLAUDE.md rule 10). A brick reaches a decision only through a person (single decide, or bulk accept of a non-AI or high-confidence suggestion as ruled below).
- An AI brick must be in the shortlist **and** `gpc.known(code)`; otherwise discarded. Medicines (`medicine_type_name == 'Medicine'`) default to `10005845` with no AI call unless a learned source says otherwise.
- AI calls only from the background job / explicit "ask again", never on page load; switch `TAX_GPC_AI_ENABLED` (default False, `config/writers.py` style via settings); new scheduler job registered in `SCHEDULER_JOB_GUARDS`.
- Only item data (names, family, category, type, origin, producer) goes to the AI — no customer data, no prices.
- Arabic UI copy; help hint ≤160 chars; `updated` bumped; every table sortable.

## Review Focus
1. Family with mixed bricks (e.g. 60/40) → no learned suggestion (needs ≥3 and ≥80%), falls through to the next source.
2. AI returns a brick outside the shortlist / unknown / malformed JSON / provider down → stored as "no suggestion" with the reason, nothing raised, job continues.
3. Switch off → job and "ask again" do nothing and say so; learned sources still work.
4. Bulk accept with AI medium/low confidence → skipped «الفئة تحتاج تأكيداً».
5. Item decided in S1 without a brick → can get a brick later (audited) without reopening.

---

### Task 1: ETA mirror keeps the brick
**Files:** `apps/tax_invoicing/eta_codes.py` (`_first(row, 'parentItemCode', 'parentCode', 'gpcCode')`), test `apps/tests/test_eta_codes.py`.
- [ ] Test: a row with `parentItemCode: '10000673'` stores `gpc='10000673'`. Implement, run `apps.tests.test_eta_codes`, commit `fix(tax): keep the GPC brick ETA returns with each code`.

### Task 2: learned brick sources
**Files:** create `apps/tax_invoicing/gpc_learn.py`; test `apps/tests/test_gpc_learn.py`.
**Produces:** `learned(profiles) -> dict[int, dict]` → `{profile_id: {'code', 'source', 'share', 'n', 'basis'}}`, first hit wins, in order:
1. `decisions` — bricks people confirmed on `TaxCodingDecision` (`decision='code'`, `brick` set) for items of the same SOFTECH family (`Item.family_name`): ≥3 and top brick ≥80%.
2. `eta` — bricks of approved/active `EtaCodeUsage` (system production, `gpc` set) for items of the same family (join `itemcode` → `Item.softech_id`): ≥3 and ≥80%.
3. `sheet` — the item's own brick in the owner's sheet (`TaxItemProfile.gpc_code` not in ('', '0'), or the "GPC Applied" import below).
4. `medicine` — `medicine_type_name == 'Medicine'` → `10005845`.
Constant query count (no per-profile queries). Also a command `load_sheet_bricks PATH` reading sheet «ElRezeiky GPC Applied» col «أكواد الضرائب» (header match by name) into `TaxItemProfile.gpc_code` only where empty/'0', 8-digit and `gpc.known()`; audited; prints counts.
- [ ] Tests per source + order + thresholds (60/40 → none) + constant queries + command (temp xlsx). Commit `feat(tax): learned GPC brick suggestions`.

### Task 3: `TaxBrickSuggestion` + AI job
**Files:** models (`TaxBrickSuggestion`: `profile` OneToOne PROTECT related_name `brick_suggestion`; `brick` (8, blank, db_default ''), `second` (8, blank), `reason` (200, blank), `confidence` ('high'|'medium'|'low'|''), `source` ('ai'|'none'), `model` (60, blank), `error` (200, blank), `asked_at`); migration 0019; create `apps/tax_invoicing/gpc_ai.py`; command `suggest_bricks [--limit N] [--itemcode X]`; scheduler job `gpc_ai_suggest` nightly 02:30 in `apps/sync/tasks.py` + `SCHEDULER_JOB_GUARDS` entry; setting `TAX_GPC_AI_ENABLED` (False; forced False under tests like the other TAX_* switches); tests `apps/tests/test_gpc_ai.py` (provider mocked).
**Produces:** `gpc_ai.shortlist(item, limit=40) -> list[dict(code, name, definition)]` (family's top bricks from `eta` + `decisions` usage up to 15, then GS1 bricks (`source != 'workbook'`) whose name/definition shares a word with the item's family/category/name, segments 50/51/53 first; falls back to all `known()` bricks of the same segments when GS1 not loaded). `gpc_ai.suggest_one(profile) -> TaxBrickSuggestion` (skips when `learned()` has one or medicine default; builds a short JSON-only prompt; validates; stores). `gpc_ai.run(limit=200) -> dict` (queue items without a learned suggestion and without a suggestion younger than 30 days, biggest uncoded value first; stops on the switch; per-item errors stored, never raised).
- [ ] Tests: switch off → nothing called; brick outside shortlist discarded with error; malformed JSON; provider returns '' ; medicine skipped; learned skipped; order biggest first; scheduler guard test passes. Commit `feat(tax): AI GPC brick suggestions behind a switch`.

### Task 4: queue + decide carry the brick
**Files:** `coding_queue.py` (`rows`: add `brick`, `brick_name`, `brick_source` (decisions/eta/sheet/medicine/ai), `brick_confidence`, `brick_reason`, `brick_second`), `decide(..., brick=None)`, new `set_brick(profile_id, actor, brick)`; views/urls `POST codes/queue/brick/` (APPROVER) and `POST codes/queue/suggest/` (APPROVER, runs `gpc_ai.suggest_one` for ≤20 itemcodes, refuses when switch off); tests in `test_tax_coding_queue.py`.
**Rules (controller rulings):** `decision='code'` needs a brick: the one passed, else the row's suggestion; `brick` must be 8 digits and `gpc.known()`; store `brick`, `brick_source` ('person' when passed and different from the suggestion). Bulk 'code'/accept uses the suggestion only when source ≠ 'ai' or confidence == 'high'; otherwise skip «الفئة تحتاج تأكيداً». `set_brick` allowed on a 'code' decision (any time before a code request exists), audited `coding_brick_set`. Keep-out needs no brick.
- [ ] Tests for each rule; constant query count still holds. Commit `feat(tax): the coding decision records a confirmed GPC brick`.

### Task 5: screen + help
**Files:** `QueueTab.jsx` (column «الفئة (GPC)»: code + Arabic name + source badge (من قرارات سابقة / من أكواد المصلحة / من ملف الشركة / دواء / اقتراح ذكي + confidence) + reason in title; picker = search box over existing `GET codes/gpc/?q=` with keyboard; «اقترح مرة أخرى» per row/selection; bulk disabled reason when AI medium/low), `client.js` (`codingSetBrick`, `codingSuggest`), help `apps/help/content/tax_invoicing.py` (queue tab: brick sources + "the AI only suggests; a person confirms"), vitest.
- [ ] vitest + build + `apps.tests.test_help`; commit `feat(tax): GPC brick column and picker in the coding queue`.

### Task 6: docs + verification
- [ ] Doc 36 section update (brick sources, AI guard, switch, job). Run the S2 test labels serially, vitest, build. Final whole-branch review, PR, merge by hand when green.
