# Unified Search S4 — Wildcards Everywhere Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every search box in the app follows the same wildcard rules: list endpoints, hand-written `q` filters, and frontend local filters. A guard test keeps it that way.

**Architecture:**
- Backend: swap the plain DRF `filters.SearchFilter` for `apps.catalog.wildcard.WildcardSearchFilter`, and turn every hand-written `<field>__icontains=<search text>` into `wq(q, fields…)`.
- Frontend: swap `.toLowerCase().includes(q)` local filters for `utils/wildcard.wildcardMatch`.
- Two guard tests, one Python and one Vitest, fail on new occurrences.
- No new search logic, no migration.

**Tech Stack:** Django/DRF, PostgreSQL (`ulike` lookup), React/Vite, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-16-unified-item-search-design.md` §8.3 and §10 item 4. It folds in S5 (help), whose item-search topic already shipped in S3.

## Global Constraints
- `*` and `%` are ALWAYS wildcards. The space is literal. The match is "contains" and case-insensitive. Parts match in the order typed, with any word order as the second tier (`wq` = ordered OR any_order).
- `_` is never a wildcard (`_esc` already escapes it).
- An exact-id lookup (`=q`, `__iexact=q`, `docnumber=q`, `personcode=q`, `__startswith` code prefixes) stays exact, with a one-line comment saying why.
- A `wq` over a to-many relation (`items__…`, `links__…`, `lines__…`) must end in `.distinct()` when the old code had it or the relation can duplicate rows.
- An empty or whitespace-only query does not filter (`wq` returns `Q()`; keep the existing `if q:` guards).
- A filter backend keeps its current position in `filter_backends`; only the class changes.
- No new `# noqa` / `# nosec`. Phone masking (`apps/customers/access.py`) and the fields searched are unchanged. Only how the text matches changes.
- Do not edit `apps/tests/security/` (it needs the owner's yes).
- Help: Arabic + English. Text lines are ≤160 characters (help test cap). Bump `updated` to `2026-11-18` on the topics you touch.

## Review Focus
1. **`%` and `_` in a query.** `50%` must still find «50%» rows (the literal tier). `a_b` must not match `axb`.
2. **To-many search fields** (transfers `items__item__name`, erp `lines__item_code`, counselling `links__item__name`) must not return duplicate rows.
3. **Two-word queries on name boxes** («ahmed ali») now also match «ali … ahmed». This is intended, but the list must still be ordered by the view's own ordering, not a random order.
4. **Code/number fields** (`softech_id`, `docnumber` as text, `user_id`) still match a pasted code, including one with leading zeros.
5. **Local filters that searched both name and code** (`BatchesPage`, `MarketShortagePage`, `SupplyPage`, `InsuranceClaimDetailPage`, `ReconciliationPage`, `MultiSelectFilter`, `BranchSelect`) must still find by code after the swap. Pass both texts to `wildcardMatch([name, code], q)`.

---

### Task 1: The 7 plain `SearchFilter` apps → `WildcardSearchFilter`

**Files:**
- Modify:
  - `apps/audit/views.py:39`
  - `apps/erp/views.py:27,114`
  - `apps/payments/views.py:51`
  - `apps/recommendations/views.py:113`
  - `apps/transfers/views.py:151`
  - `apps/transits/views.py:120`
  - `apps/users/views.py:545,681`
- Test: `apps/tests/test_search_rules_viewsets.py` (create)

**Interfaces:**
- Consumes: `from apps.catalog.wildcard import WildcardSearchFilter` (existing; it strips DRF `^=@$` prefixes, applies `filter_and_rank`, then `.distinct()`).

- [ ] **Step 1: Write the failing tests.** One test per viewset (9). Each seeds one matching row and one non-matching row, GETs the list as an admin with `?search=<pattern>`, and asserts the matching row is present and the other is absent. Use a pattern that plain `SearchFilter` cannot match:
  - `audit`: `user_name='Ahmed Samir'`, search `ahm*sam`
  - `erp` transactions: `reference_number='INV-2026-77'`, search `inv*77`
  - `erp` customers: `name='Mona Adel'`, search `mon*del`
  - `payments`: `customer_name='Karim Nabil'`, search `kar*nab`
  - `recommendations`: `item_a__name='PANADOL EXTRA'`, search `pan*xtra`
  - `transfers`: `request_number='TR-000123'`, search `tr*123`. Also seed the request with TWO lines of the same item and assert it is returned exactly once.
  - `transits`: `erp_doc_number='125-4471'`, search `125*71`
  - `users` (both viewsets): username `pharm_ali`, search `pha*ali`

  Plus `test_percent_is_literal_tier`: on audit, `note='discount 50%'` is found by `50%`.
- [ ] **Step 2:** Run `python manage.py test apps.tests.test_search_rules_viewsets --keepdb` → the pattern tests FAIL.
- [ ] **Step 3:** In each file, replace `filters.SearchFilter` with `WildcardSearchFilter` at the same list position and add the import. Remove the `filters` import only if nothing else uses it.
- [ ] **Step 4:** Re-run → PASS. Also run the existing tests of the touched apps (`apps.tests` modules matching `audit|erp|payments|recommendation|transfer|transit|users`).
- [ ] **Step 5: Commit** `feat(search): wildcard rules on the remaining SearchFilter lists (S4)`

### Task 2: Hand-written `q`/`search` readers → `wq`

**Files (modify; line numbers are as of `main` 45c51516):**
- `apps/analytics/views.py:1669-1672`, `apps/campaigns/views.py:303`
- `apps/chronic/views.py:71,100-101,283-286`
- `apps/composition/views.py:83,145,190,402,411`
- `apps/catalog/views.py:751,802`
- `apps/customers/merge_views.py:53`
- `apps/counselling/views.py:91`
- `apps/enrichment/views.py:64-65`
- `apps/discount_approvals/views.py:968`
- `apps/whatsapp/views.py:121-123`
- `apps/finance/views.py:73` (read the loop first; if `s` comes from a fixed list, not user text, leave it and add it to the guard allow-list in Task 4 with that reason)
- `apps/vouchers/views.py:148`
- `apps/product_experience/selectors.py:45-59,140-144`
- `apps/pbx/views.py:293-295`
- `apps/procurement/views.py:132,255-256,841-844,1077,1500` (the `__icontains` code parts next to `wq`)
- `apps/notifications/views.py:208`
- `apps/tasks/views.py:191-193`
- `apps/transits/views.py:977,1224-1225`
- `apps/stock_audit/views.py:143,558-559`
- `apps/purchasing/views.py:606,628`, `purchasing/spike_views.py:94`, `purchasing/shortage_views.py:222`, `purchasing/phantom_views.py:69`
- `apps/replacement/views.py:47-48`
- `apps/pic_analytics/views.py:119-120`, `pic_analytics/queries/pics.py:48`
- `apps/stockcount/views.py:555`
- `apps/omni/views.py:108-111`
- `apps/tax_invoicing/views.py:148,197,495,1026-1027,1046`, `tax_invoicing/history_views.py:85-86,99,353`, `tax_invoicing/gpc.py:242`
- `apps/insurance/views.py:2416,2823`
- `apps/hr/attendance/views.py:309,685-686`
- `apps/images/views.py:439`
- Sweep for anything this list missed:
  `rg -n "__icontains=\s*(q|search|query|term|s|needle|text)\b" apps --glob '!**/tests/**' --glob '!**/migrations/**' --glob '!**/management/**'`.
  Management commands are not search boxes and stay as they are.
- Test: `apps/tests/test_search_rules_readers.py` (create)

**Interfaces:**
- Consumes: `from apps.catalog.wildcard import wq`. `wq(q, *fields) -> Q`, an OR over the fields, with fields given as ORM paths.

**Rule for each site:**
- `Q(a__icontains=q) | Q(b__icontains=q) | …` becomes `wq(q, 'a', 'b', …)`.
- Existing `wq(...) | Q(code__icontains=q)` folds into one `wq(q, 'name_field', 'code_field')`.
- Exact parts (`Q(itemcode=q)`, `Q(personcode=q)`, `softech_pic__iexact=q`, `docnumber=q`, `receiver_id=q`, `code__startswith=q`) stay, OR-ed in, with a `# exact id: <why>` comment.
- Keep `.distinct()` where the old code had it. Add it where a to-many path is now searched and it was missing.

**S3 leftovers (verify only; change only if the endpoint does NOT already use `wq`):**
- market-shortage manual add and dismiss-match (the endpoints behind `MarketShortagePage.jsx:448` and `:182`)
- branch-request line re-match (`supply/BranchRequestsTab.jsx:497`)
- insurance reprice-by-item (`apps/insurance/views.py:2416`, converted above)
- POS F6 image search (`apps/images/views.py:439`)

Record what each one uses in the task report.

- [ ] **Step 1: Write the failing tests.** Six endpoint tests, one per query shape. Each seeds a hit and a miss and asserts the hit is in, the miss is out, and no duplicates:
  - single text field: `/api/vouchers/?search=sum*sale` finds title «Summer Big Sale»
  - several fields: `/api/tasks/?q=fix*print` finds title «Fix the printer»
  - related to-many field: counselling `?q=pan*xtra` through `links__item__name`, one row only, with two links
  - code field: transits list `?q=1000*45` finds `softech_id='10000345'`
  - phone field: omni `?q=0100*567` finds `contact_phone='01001234567'`. Assert the response phone is still masked exactly as before for a role without phone access.
  - exact part kept: stock_audit `?q=<itemcode>` still finds by exact itemcode

  Take each endpoint's URL and its query-param name (`q` or `search`) from the view. Do not guess.
- [ ] **Step 2:** Run them → FAIL (except the exact-kept case).
- [ ] **Step 3:** Convert every listed site by the rule above, then run the sweep `rg` again until it prints nothing outside the allow-list you will hand Task 4. Write that allow-list (path:line, reason) into the task report.
- [ ] **Step 4:** Run the new tests plus every existing test module of each touched app (`python manage.py test apps.tests --keepdb -k <app>` per app, serially; never `--parallel`; see memory on PC load) → PASS.
- [ ] **Step 5: Commit** `feat(search): wildcard rules for every hand-written search filter (S4)`

### Task 3: Frontend local filters → `wildcardMatch`

**Files (modify):**
- `frontend/src/components/AnalyticsFilterPanel.jsx:48`
- `frontend/src/components/BranchSelect.jsx:59-60`
- `frontend/src/components/CustomerTagsPanel.jsx:59`
- `frontend/src/components/HRForm.jsx:98`
- `frontend/src/components/MultiSelectFilter.jsx:38`
- `frontend/src/components/NotificationPanel.jsx:259`
- `frontend/src/pages/BatchesPage.jsx:330,989`
- `frontend/src/pages/CasesPage.jsx:97-98`
- `frontend/src/pages/crews/CrewEditor.jsx:283`, `pages/crews/util.jsx:70`
- `frontend/src/pages/ImageEnrichmentPage.jsx:1158`
- `frontend/src/pages/InsuranceClaimDetailPage.jsx:3331-3332`
- `frontend/src/pages/InsuranceClaimsPage.jsx:640`
- `frontend/src/pages/MarketShortagePage.jsx:99`
- `frontend/src/pages/PurchasingDashboard.jsx:1120`
- `frontend/src/pages/ReconciliationPage.jsx:1337`
- `frontend/src/pages/SupplyPage.jsx:340`
- Test: `frontend/src/utils/wildcardLocalFilters.test.jsx` (create)

**Interfaces:**
- Consumes: `import { wildcardMatch } from '../utils/wildcard'`. `wildcardMatch(text | text[], q) -> boolean`. An empty query returns true, so drop now-redundant `!q ||` guards only when the behaviour is identical.

**Rule:** every `a.includes(q) || b.includes(q)` becomes `wildcardMatch([a, b], q)`. Remove a separate `.toLowerCase()` of `q`, because `wildcardMatch` lowercases both sides. Not search filters, so leave them: `PicAnalyticsPage.jsx:176` (`RUNNING.includes`) and `supply/AvailabilityInboxTab.jsx:360` (`r.flags.includes(filter)`).

- [ ] **Step 1: Write the failing tests.**
  - `MultiSelectFilter`: typing `pan*xtra` shows option «PANADOL EXTRA», and typing its code `10023` still shows it.
  - `BranchSelect`: typing a branch code finds it, and `ma*di` finds «Maadi».
  - `NotificationPanel`: `stock*low` filters to a notification titled «Stock running low».
- [ ] **Step 2:** `npx vitest run src/utils/wildcardLocalFilters.test.jsx` → FAIL.
- [ ] **Step 3:** Convert every listed site.
- [ ] **Step 4:** Run `npx vitest run` (full) → all pass. Then `npm run build` → OK, and `npx eslint <changed files>` → no new warnings.
- [ ] **Step 5: Commit** `feat(search): wildcard rules in every local grid filter (S4)`

### Task 4: Guard tests + help

**Files:**
- Create: `apps/tests/test_search_rules_guard.py`
- Create: `frontend/src/searchRulesGuard.test.js` (model it on `components/noLegacyItemPickers.test.js`)
- Modify: `apps/help/content/general.py` (the item-search topic)

**Backend guard:**
- It walks `apps/**/*.py`, excluding `tests/`, `migrations/` and `management/`.
- `test_no_plain_search_filter` fails on `filters.SearchFilter` or a bare `SearchFilter` in a `filter_backends` list. `apps/catalog/wildcard.py` is allowed, because it subclasses it.
- `test_no_icontains_on_search_text` fails on `__icontains=\s*(q|search|query|term|s|needle|text)\b`.
- `ALLOW = {'path/to/file.py': 'reason', …}` is keyed by path relative to the repo root. Each entry must give a reason of at least 10 characters (assert it). It starts with Task 2's allow-list.
- The failure message names file:line and says «use apps.catalog.wildcard.wq / WildcardSearchFilter».

**Frontend guard:**
- It reads every `src/**/*.{js,jsx}` except `*.test.*` and `utils/wildcard.js`.
- It fails on `/\.toLowerCase\(\)\s*\.includes\(/`, or on `/\.includes\(\s*(q|search|query|needle|term|ql|filter)\s*\)/`, unless the line is in the `ALLOW` map (`'pages/PicAnalyticsPage.jsx': 'RUNNING status list, not a search'`, `'pages/supply/AvailabilityInboxTab.jsx': 'flag list, not a search'`).
- Each `ALLOW` entry is a file plus a reason, and a stale entry (a file with no match any more) fails, so the list cannot rot.

**Help:**
- One new line in the item-search topic, Arabic + English: the same rules (`*`/`%`, word order) now apply to every search box in the system, not just item boxes.
- Bump `updated` to `2026-11-18`.

- [ ] **Step 1: Write both guards.** They must pass on the tree after Tasks 1–3, and they must fail when you temporarily add one `filters.SearchFilter` line and one `.toLowerCase().includes(q)` line to a scratch copy. Show both failures in the report, then remove the lines.
- [ ] **Step 2:** Help line, then run `python manage.py test apps.tests.test_help --keepdb` → PASS.
- [ ] **Step 3:** Full verification, serial:
  - `python manage.py test apps.tests --keepdb` (unique `TEST_DB_NAME`)
  - `npx vitest run`
  - `npm run build`
  - `python manage.py search_probe` (read-only; do NOT pass `--with-temp-indexes`). Compare against the S3 numbers in `.superpowers/sdd/2026-11-17-unified-item-search-s3-modes/perf-report.md`; S4 must not change item-picker results.
- [ ] **Step 4: Commit** `test(search): guard wildcard rules in every search box; help (S4)`
