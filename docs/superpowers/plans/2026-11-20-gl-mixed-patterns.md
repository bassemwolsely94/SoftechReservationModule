# GL mixed groups — decide by pattern: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an accountant import or ignore all parked `mixed_manual_entry` exceptions of one pattern at once.

**Architecture:** A small service module computes each open mixed exception's pattern from its stored
`proposed_lines` and decides a whole pattern (draft via `save_draft` + `settle_parked_manual_entry`,
or ignore). Two DRF views expose it; a panel in the GL Exceptions tab lists patterns.

**Tech Stack:** Django/DRF, React (Vite), existing GL ledger + plan2_adapter.

**Spec:** `docs/superpowers/specs/2026-11-20-gl-mixed-patterns-design.md`

## Global Constraints
- Nothing approved; nothing written to SOFTECH.
- Pattern key = book + sorted manual accounts + sorted SOFTECH-fed accounts; link account 2354 left out.
- `decide` refuses with 409 `count_changed` when the open count ≠ `expected_count`.
- Ignore needs a note (same limit `MAX_NOTE` as «تجاهل»); import needs none.
- List = permission VIEW; decide = permission CREATE (same as `exception_ignore`).
- No modal: inline confirm with the count.
- Help AR + EN for the new view, `updated` bumped; perf budget row + test.

## Review Focus
- A group whose draft is refused (closed period, inactive account) — others still import; refused ones stay open and are listed.
- Two accountants deciding the same pattern at once — row locks; second sees `count_changed`, never a double draft.
- A group already imported by the CLI meanwhile (source_key live) — counted as settled, no second draft.
- Lines with no SOFTECH account (all manual, e.g. after a rule change) — still listed under an empty SOFTECH set.
- Ignore with an empty or too-long note — 400, nothing changes.

---

### Task 1: Pattern service

**Files:**
- Create: `apps/finance/gl/mixed_patterns.py`
- Test: `apps/tests/test_gl_mixed_patterns.py` (reuse `GLManualBase` from `apps.tests.test_gl_manual_import`; park groups with `run_import(self.mixed_rows()...)`)

**Interfaces:**
- Produces: `class PatternError(Exception)` with `.code` in {`bad_decision`, `note_required`, `count_changed`, `unknown_pattern`}; `pattern_key(book: str, manual: list[str], softech: list[str]) -> str` (`f'{book}|{",".join(manual)}|{",".join(softech)}'`); `list_patterns() -> list[dict]` (keys: `pattern, book, manual_accounts, softech_accounts, count, debit, date_from, date_to, samples`) sorted by count desc; `decide(*, pattern: str, decision: str, expected_count: int, note: str, user) -> dict` (keys: `decision, decided, imported, already_imported, ignored, failed: [{'key','code'}]`).

- [ ] **Step 1: Failing tests** — `test_groups_by_book_manual_and_softech_accounts` (two mixed groups same accounts + one on another account → 2 patterns, counts 2 and 1, link 2354 not in key); `test_import_all_creates_drafts_and_resolves` (draft per group, lines keep branch, status draft, exceptions `resolved`, doc `drafted`, `LedgerEntry.status=='draft'`); `test_ignore_all_needs_a_note_and_ignores`; `test_count_changed_refused_and_nothing_changes`; `test_a_refused_draft_leaves_its_group_open_others_import` (mock `save_draft` to raise `LedgerError('closed_period')` for one key); `test_already_live_key_is_settled_not_duplicated`; `test_summary_audit_row`.
- [ ] **Step 2: Run** `manage.py test apps.tests.test_gl_mixed_patterns` → fail (module missing).
- [ ] **Step 3: Implement.** Open rows: `SourceException.objects.filter(kind=MIXED_MANUAL_KIND, status='open').select_related('source_doc')`. Fed set once via `plan2_adapter.softech_fed_account_codes()`; links via `manual_import._link_accounts()`. Import per row in its own `transaction.atomic()`: `select_for_update` the row, skip if no longer open; `save_draft(user, entry_date=doc.doc_date, description=doc.attrs['description'][:500], lines=<proposed_lines with Decimal debit/credit, due_date parsed>, book=doc.attrs['book'], branch=Branch by doc.branch_code, source_type=MANUAL_IMPORT_SOURCE, source_key=doc.source_key)` then `plan2_adapter.settle_parked_manual_entry`; live key → settle onto the live entry; `LedgerError` → `failed`. Ignore mirrors `exception_ignore` (status, resolver, note, `parties._audit('gl_exception_ignored', ...)`). Count check under `select_for_update` of the pattern's rows. One `_audit('gl_mixed_pattern_decided', ...)` with counts only.
- [ ] **Step 4: Run** → pass. **Step 5: Commit.**

### Task 2: API views + perf budget

**Files:** Modify `apps/finance/gl/drafting_views.py`, `apps/finance/gl/urls.py`, `apps/tests/perf/budgets.py`, `apps/tests/perf/test_budget_lists.py`; Test `apps/tests/test_gl_mixed_patterns.py`.

**Interfaces:** Consumes Task 1. Produces `GET exceptions/mixed-patterns/` → `{'results': list_patterns()}`; `POST exceptions/mixed-patterns/decide/` body `{pattern, decision: 'import'|'ignore', expected_count, note}` → 200 result dict | 400 `{code, detail}` | 409 `count_changed`.

- [ ] **Step 1: Failing tests** — `test_list_and_decide_api` (accountant 200, pharmacist 403 on both, viewer-only 403 on decide); `test_decide_409_on_count_changed`; `test_decide_400_on_bad_decision_and_missing_note`; budget test `test_gl_mixed_patterns` with row `'finance/gl/exceptions/mixed-patterns': Budget('list', <measured+2>, 'measured N on 2026-11-20')`, grow = park 3 more groups.
- [ ] **Step 2–4:** run (fail), implement views (`@permission_classes(VIEW)` / `(CREATE)`, `_need_profile`, map `PatternError` → 400/409 with Arabic `detail`), run (pass).
- [ ] **Step 5: Commit.**

### Task 3: Inbox panel + help

**Files:** Create `frontend/src/pages/finance/gl/MixedPatternsPanel.jsx`; Modify `frontend/src/pages/finance/gl/ExceptionsTab.jsx` (show panel toggle «حسب النمط» when kind filter = `mixed_manual_entry`), `frontend/src/api/client.js` (`glMixedPatterns()`, `glDecideMixedPattern(body)`), `apps/help/content/finance.py` (exceptions tab text AR+EN, bump `updated`).

- [ ] **Step 1:** Panel: sortable table (`useSortableRows` + `SortTh`, `useGridKeyboard`) columns الدفتر / حسابات يدوية / حسابات سوفتيك / عدد / إجمالي / من–إلى / أمثلة; per row «استيراد الكل كقيود» and «تجاهل الكل»; inline confirm row showing «N قيد» (ignore shows a reason input); on 409 reload with «العدد اتغير — راجع تاني»; after success show counts and reload list + counts badge.
- [ ] **Step 2:** `npm run build` and `npm run lint` pass; `manage.py test apps.tests.test_help` passes.
- [ ] **Step 3: Commit.**

### Task 4: Verify + PR
- [ ] Ask coordinator (local_13f78718) for clearance; run `apps.tests.test_gl_mixed_patterns apps.tests.test_gl_manual_import apps.tests.test_gl_drafting_api apps.tests.perf.test_budget_lists apps.tests.test_help` serially with a unique `TEST_DB_NAME`.
- [ ] Push, open PR, hand to coordinator.
