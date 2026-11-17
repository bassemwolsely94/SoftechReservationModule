# Unified Item Search — S1 Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the one search engine (`apps/catalog/wildcard.item_search`) fast, SOFTECH-like
and right. It must:
- run in under 40 ms;
- rank names that start with the query first and whole numbers first;
- fold Arabic letter forms and extra spaces;
- understand form and unit synonyms, with an ingredient tier;
- catch single-word typos;
- stop the disease expansion inside pickers.

POS, Ctrl+K and every path-A screen improve with no UI rewiring.

**Architecture:**
- The engine stays in `apps/catalog/wildcard.py`.
- Name tiers move from `UPPER(name) LIKE` to one *folded* SQL expression (upper case, single
  spaces, Arabic letter forms unified), backed by new trigram expression indexes.
- Ranking happens in one SQL query (`CASE` rank + whole-number score + name), cut to a fixed
  60-id window.
- Synonyms live in a new small module.
- Typo and sound tiers stay in Python as today.

**Tech stack:**
- Django 5 / DRF, PostgreSQL with `pg_trgm`, rapidfuzz;
- React 18 + Vite + vitest (one shared chip component);
- Django `TestCase`.

**Spec:** `docs/superpowers/specs/2026-11-16-unified-item-search-design.md` (§5, §6, §7 first
bullet, §9; batch S1 in §10).

## Global Constraints

- `*` and `%` are the same wildcard everywhere. A search is always "contains". Parts must appear
  in the order typed. A space is literal, but a run of spaces equals one space.
- Code and barcode are **exact only** when `code_prefix=False`, which is what POS (`no_live=1`)
  and `universal.py` pass. There is no prefix and no `code_part` on those paths.
- Non-exact rows (`learned`, `synonym`, `sound`, `ingredient`, `approx`, `code_part`) are never
  auto-selected; only exact `code` auto-selects.
- Inside every name tier the order is: whole-number score (descending), then hit in `name`
  before hit in `name_scientific`, then `name` A→Z (SOFTECH order).
- Engine window: always 60 candidate ids before trimming to the caller's `limit`.
- Minimum length (D7):
  - a digits-only query needs 2 or more characters (code/barcode);
  - a name query needs 3 or more characters;
  - a 2-character name query gets the `starts` tier only.
- No price, stock, discount, checkout or SOFTECH-write code changes. POS `addItem` is untouched.
- Tests run serially with a unique `TEST_DB_NAME` (for example `test_search_s1`). Never use
  `--parallel`. Check free RAM first (memory: PC memory incidents).
- Help text is Arabic + English, and the touched screen's `updated` date is bumped
  (CLAUDE.md rule 5b).

## Review Focus

1. **A query of only wildcards or punctuation** (`**`, `%`, `-`, `()`) returns `[]` quietly,
   never a 500 and never the whole catalog. *Task 3 test `test_punctuation_only_returns_nothing`.*
2. **Regex-special characters** in the query (`(`, `+`, `[`, `\`, `.`, `?`) must not break the
   word, number or synonym regex tiers. `augmentin (1g)` and `c++` work as plain text.
   *Task 3 test `test_regex_specials_are_plain_text`.*
3. **Arabic-Indic digits inside a mixed query** (`كونجستال ٢٠`) fold to `20` and get the
   whole-number boost. *Task 2 test `test_arabic_digits_fold`, Task 3 test
   `test_whole_number_boost_with_arabic_digits`.*
4. **A very short common query** (`pa`, `ta`) returns only `starts` rows. On the real catalog it
   stays inside the speed budget. *Task 3 test `test_two_letters_starts_only`; Task 8 probe
   budget.*
5. **An item with an empty or NULL `name_scientific`** must not crash the folded expression or
   rank oddly. *Task 2 test `test_fold_sql_null_safe`.*

---

### Task 1: Exact code and barcode in under 2 ms, plus the `code_part` tier

**Files:**
- Modify: `apps/catalog/wildcard.py` (`item_search`, the code block)
- Test: `apps/tests/test_wildcard_search.py` (new class `CodeTierTests`)

**Interfaces:**
- Produces: `item_search(q, *, limit=20, active_only=True, code_prefix=True) -> list[tuple[int, str]]`.
  The signature is unchanged. New tier value: `'code_part'`. `code_prefix=False` now also
  disables `code_part`.

- [ ] **Step 1: Write failing tests** in `CodeTierTests(TestCase)`. Seed these items with
  `ItemBarcode` rows:
  - `AUGMENTIN 1G (1000MG) 14 TAB`, code `3690`, barcode `6221025032348`;
  - `SOUVENIR ROGO COLORE 250M(3690) PERFUME`, code `990001`;
  - `CONCOR 5MG 30TAB`, code `136900`.

  Tests:
  - `test_exact_code_uses_index`:
    - `CaptureQueriesContext` over `item_search('3690')`;
    - no captured SQL contains `UPPER("catalog_item"."softech_id")` or
      `UPPER("catalog_itembarcode"."barcode")`;
    - the first result is `(augmentin.id, 'code')`.
  - `test_barcode_exact`: `item_search('6221025032348')[0] == (augmentin.id, 'code')`.
  - `test_code_part_outside_pos`:
    - `item_search('690')` contains `(augmentin.id, 'code_part')` and
      `(concor.id, 'code_part')`;
    - every `code_part` row sits after every name-tier row;
    - the SOUVENIR row, a name hit, comes before them.
  - `test_code_part_never_on_pos_path`: `item_search('690', code_prefix=False)` contains no
    `'code_part'` tier.

- [ ] **Step 2: Run, expect FAIL.**
  Run: `$env:TEST_DB_NAME='test_search_s1'; .\venv\Scripts\python.exe manage.py test apps.tests.test_wildcard_search.CodeTierTests`
  Expected: FAIL. The SQL contains `UPPER(`, and `code_part` is missing.

- [ ] **Step 3: Implement.**
  - Replace `__iexact` with exact `=` lookups on `softech_id`, `barcode` and
    `ItemBarcode.barcode`. The input is `raw.strip()`; codes and barcodes are digits, so there is
    nothing to case-fold.
  - Add `code_part` only when `code_prefix` is true, `raw.isdigit()` and `len(raw) >= 2`:
    `softech_id__contains` / `barcode__contains` / `ItemBarcode.barcode__contains`, capped at
    the window.
  - These ids are appended **after** the name tiers (they are collected first, then added
    last).

- [ ] **Step 4: Run, expect PASS.** Run the same command, plus the whole
  `apps.tests.test_wildcard_search` module. All tests pass.

- [ ] **Step 5: Commit**: `fix(search): exact code/barcode lookups use the index; code_part tier outside POS`.

---

### Task 2: Folded name expression and its trigram indexes

**Files:**
- Modify: `apps/catalog/wildcard.py` (add `fold_query`, `FOLD_SQL`, the `fulike` and `fregex`
  lookups)
- Create: `apps/catalog/migrations/0044_folded_name_trgm.py`
- Test: `apps/tests/test_wildcard_search.py` (new class `FoldTests`)

**Interfaces:**
- Produces:
  - `fold_query(q: str) -> str`. It applies, in order:
    1. Arabic-Indic digits `٠-٩` and `۰-۹` → `0-9`;
    2. tashkeel and tatweel removed;
    3. `أإآٱ→ا`, `ة→ه`, `ى→ي`, `ؤ→و`, `ئ→ي`;
    4. upper case;
    5. whitespace runs → one space;
    6. strip.

    Wildcards are kept.
  - `FOLD_SQL = "translate(upper(regexp_replace(coalesce({col},''), '\s+', ' ', 'g')), 'أإآٱةىؤئ', 'ااااهيوي')"`.
    This exact text is used both by the index and by the lookups, so PostgreSQL can match the
    index.
  - Lookup `field__fulike=PATTERN` renders `FOLD_SQL(field) LIKE PATTERN ESCAPE '\'`.
  - Lookup `field__fregex=REGEX` renders `FOLD_SQL(field) ~ REGEX`.
  - `pattern()`, `literal_pattern()` and `parse()` call `fold_query` on their input first.

- [ ] **Step 1: Write failing tests** in `FoldTests`:
  - `test_fold_query`:
    - `fold_query('  أوجمنتين   ١ جم ')` equals `'اوجمنتين 1 جم'`;
    - `fold_query('vol*ren')` equals `'VOL*REN'`.
  - `test_arabic_digits_fold`: `W.pattern('كونجستال ٢٠')` equals `'%كونجستال 20%'`.
  - `test_hamza_matches_literally`:
    - seed `AUGMENTIN 156MG SYRUP 80ML اوجمنتين 156مجم شراب`;
    - `item_search('أوجمنتين')` returns that id with a tier in `{'starts','word','contains'}`,
      not `'sound'`.
  - `test_spaces_collapse`:
    - seed `VOLTAREN   1% 15  GM  EMULGEL`;
    - `item_search('VOLTAREN 1% 15 GM')[0][1]` is in `{'starts','contains'}`, not `'any_order'`.
  - `test_fold_sql_null_safe`:
    - an item with `name_scientific=''`, and one with `name_scientific=None` if the column allows
      it;
    - `Item.objects.filter(name_scientific__fulike='%X%').count()` runs without error.
  - `test_index_used`:
    - on PostgreSQL, `EXPLAIN` of `Item.objects.filter(name__fulike='%PANADOL%')` mentions
      `catalog_item_name_fold_trgm` or `Bitmap Index Scan`;
    - force it with `SET enable_seqscan = off` inside the test.

- [ ] **Step 2: Run, expect FAIL.** The lookups are undefined.

- [ ] **Step 3: Implement** the lookups and `fold_query`. Write migration `0044` with `RunSQL`:
  - `CREATE INDEX IF NOT EXISTS catalog_item_name_fold_trgm ON catalog_item USING gin ((<FOLD_SQL name>) gin_trgm_ops)`;
  - the same for `name_scientific` as `catalog_item_sci_fold_trgm`;
  - a reverse `DROP INDEX IF EXISTS`.

  The migration touches the catalog only, not SOFTECH sync. Move every name-tier query in
  `item_search`, plus `ordered_q`, `any_order_q` and `rank_case`, from `ulike` to `fulike`.
  `WildcardSearchFilter` and `wq()` for other modules keep `ulike`; that is S4.

- [ ] **Step 4: Run, expect PASS.** Run `FoldTests` and the full `test_wildcard_search` module.
  Also run `apps.tests.test_arabic_matching` and `apps.tests.test_matching_learning`
  (regression).

- [ ] **Step 5: Commit**: `feat(search): folded name matching (Arabic forms, digits, spaces) with trigram expression indexes`.

---

### Task 3: Ranking — `starts` / `word` / `contains` / `any_order`, whole numbers, name before scientific name

**Files:**
- Modify: `apps/catalog/wildcard.py` (`item_search` name tiers; new `_rank_name_ids`)
- Test: `apps/tests/test_wildcard_search.py` (new class `RankingTests`; update the expected tier
  names in existing tests: `literal`/`ordered` → the new names)

**Interfaces:**
- Consumes: `fulike`, `fregex`, `fold_query` (Task 2).
- Produces:
  - `_rank_name_ids(q: str, base, *, window: int = 60, starts_only: bool = False) -> list[tuple[int, str]]`;
  - tier values `'starts' | 'word' | 'contains' | 'any_order'`. The old `'literal'` and
    `'ordered'` disappear; `apps/catalog/universal.py:60` must use `'contains'`.

- [ ] **Step 1: Write failing tests** in `RankingTests`. Seed:
  - `VOLTAREN 50MG 20TAB`
  - `DIVOL KIDS SHAMPOO 500ML`
  - `CONCOR 5MG 30TAB`
  - `CONCOR COR 2.5MG 30TAB`
  - `CONCOR 10MG 30TAB`
  - `CONCOR AMLO 5MG/5MG 30TAB`
  - `PANADOL EXTRA 24TAB`
  - `FIRST SURG PAD DRESSING`
  - `HEPATICUM 140 MG 30CAP`
  - `TINOX 1% CREAM 15 GM`
  - `BETNOVATE 0.1 CREAM 30GM`
  - `SOMEBRAND` with `name_scientific='PANADOL GENERIC'`

  Tests:
  - `test_starts_before_contains`: `item_search('vol*50')` has VOLTAREN at index 0 with tier
    `'starts'`, and DIVOL after it.
  - `test_whole_number_first_but_all_digits_match`:
    - `item_search('concor 5')` begins with `CONCOR 5MG 30TAB`;
    - `CONCOR AMLO 5MG/5MG` (whole 5) comes before `CONCOR COR 2.5MG`;
    - `CONCOR COR 2.5MG` **is** in the results (D2: digits match anywhere).
  - `test_whole_number_boost_with_arabic_digits`: `item_search('concor ٥')[0]` is
    `CONCOR 5MG 30TAB`.
  - `test_two_letters_starts_only`: every tier in `item_search('pa')` is `'starts'`; PANADOL is
    present; PAD (`FIRST SURG PAD`) and HEPATICUM are absent.
  - `test_word_tier`: `item_search('pad')` lists FIRST SURG PAD with tier `'word'`.
  - `test_literal_text_before_pattern_in_contains`: for `item_search('1% cream')`, TINOX comes
    before BETNOVATE (keeps today's rule).
  - `test_name_before_scientific`: for `item_search('panadol')`, PANADOL EXTRA comes before
    SOMEBRAND, and both are present.
  - `test_same_tier_sorted_by_name`:
    - with `CONCOR 10MG` and `CONCOR 5MG` both `starts` for `item_search('concor')`;
    - the order within the tier follows the whole-number score, then name A→Z.
  - `test_punctuation_only_returns_nothing`: `item_search(q) == []` for each of
    `('**', '%', '-', '()', '  ')`.
  - `test_regex_specials_are_plain_text`:
    - `item_search('augmentin (1g)')`, `item_search('c++')` and `item_search('a[b')` raise
      nothing;
    - a seeded `AUGMENTIN (1G) TAB` is found for the first query.
  - `test_query_count_bounded`: `CaptureQueriesContext` over `item_search('voltaren 50')` shows
    ≤ 6 queries.

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement `_rank_name_ids`** as **one** queryset:
  - **Filter:** `cond = ordered OR any_order`, where ordered = `fulike(pattern)` on name or sci,
    and any_order = every term `fulike` on name or sci. When `starts_only`, the filter is
    `name fulike 'SEG%'` only.
  - **Annotate `_rank`** with a `Case`, first match wins:
    - 0: name `fulike` `SEG1%…` (the pattern without the leading `%`);
    - 1: name `fregex` `(^|[^A-Z0-9ء-ي])` + the regex-escaped first segment, with the rest of
      the pattern contained;
    - 2: name `fulike` literal_pattern;
    - 3: name `fulike` pattern;
    - 4: sci-only versions of 0–3;
    - 5: any_order.

    Map ranks 0→`starts`, 1→`word`, 2/3→`contains`, 4→the same names as 0–3 (the sci step-down
    is the rank number only), 5→`any_order`.
  - **Annotate `_num`**: the sum over typed numbers *n* of
    `Case(When(name__fregex=r'(^|[^0-9.])' + re.escape(n) + r'($|[^0-9])', then=1), default=0)`.
  - **Order by** `_rank`, `-_num`, `name`. Return the first `window` ids.
  - Regex-escape every user fragment with a PostgreSQL-ARE-safe escape (backslash before every
    non-alphanumeric ASCII character).
  - D7: a non-digit query shorter than 3 characters (after folding, wildcards removed) gets
    `starts_only=True`.

  Wire it into `item_search` in place of the literal/ordered/any_order block, after the `code`
  and `learned` tiers. Update `universal.py:60` to use `'contains'`, and skip that
  `search_name__icontains` extra block when `raw.isdigit()`: the haystack holds codes, which
  breaks the safety rule.

- [ ] **Step 4: Run, expect PASS** for `RankingTests`, the whole `test_wildcard_search` module
  (with the old tier names updated), and `apps.tests.test_pos_search_network`.

- [ ] **Step 5: Commit**: `feat(search): SOFTECH-ordered ranking — starts, word, contains, whole-number boost`.

---

### Task 4: Synonyms (Appendix A)

**Files:**
- Create: `apps/catalog/search_synonyms.py`
- Modify: `apps/catalog/wildcard.py` (`item_search`: the synonym tier after `any_order`)
- Test: `apps/tests/test_wildcard_search.py` (new class `SynonymTests`)

**Interfaces:**
- Produces:
  - `SYNONYMS: dict[str, tuple[str, ...]]`. Keys are folded typed tokens; values are canonical
    tokens. The content is exactly spec Appendix A, folded. For example:
    - `'SYP': ('SYRUP',)`;
    - `'فوار': ('SACH', 'EFF')`;
    - `'G': ('G', 'GM')`.
  - `expand_terms(terms: list[str]) -> list[tuple[str, ...]] | None`. It returns, per term, the
    typed term plus its synonyms, or `None` when no term has a synonym.
  - Tier value `'synonym'`.

- [ ] **Step 1: Write failing tests.** Seed:
  - `AUGMENTIN 457MG/5ML SYRUP 70ML`
  - `AUGMENTIN 1G 14 TAB`
  - `GLUCOSE GEL`
  - `VITAMIN C 500MG 30TAB`
  - `ZYRTEC ORAL DROPS 10ML`

  Tests:
  - `test_form_abbreviation`: `item_search('augmentin syp')` begins with the SYRUP item, tier
    `'synonym'`.
  - `test_arabic_unit`: `item_search('اوجمنتين 1 جم')`. Seed the AUGMENTIN 1G item's name with
    `اوجمنتين` appended. That item is in the results and comes before the SYRUP item.
  - `test_vit`: `item_search('vit c')` includes VITAMIN C 500MG.
  - `test_whole_word_only`: `item_search('gel g')` does not return every item containing the
    letter G.
    - Only items with a whole word `G`/`GM`, or a unit glued to a number (`1G`), match the `g`
      token via a synonym.
    - The test asserts AUGMENTIN 1G is returned and ZYRTEC is not.
  - `test_one_direction`: `expand_terms(['SYRUP'])` is `None`.
  - `test_typed_form_still_literal`: `item_search('augmentin syrup')` still ranks the SYRUP item
    `starts`/`contains`, not `synonym`.

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement.**
  - The synonym tier runs only when `expand_terms` is not `None` and the window is not full.
  - Every term must match: either `fulike` contains the typed term, or the name matches one of
    its canonicals by `fregex` with `(^|[^A-Zء-ي])(ALT1|ALT2)($|[^A-Zء-ي])`.
  - The left boundary allows a digit, so `500MG` and `1G` match.
  - Exclude ids already found.

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit**: `feat(search): fixed synonym table for forms and units (whole-word, one direction)`.

---

### Task 5: Single-word typo fix

**Files:**
- Modify: `apps/catalog/wildcard.py` (`_approx_ids.score`)
- Test: `apps/tests/test_wildcard_search.py` (new class `TypoTests`)

**Interfaces:**
- No signature change. `_approx_ids(text, limit, base) -> list[int]`.

- [ ] **Step 1: Write failing tests** with **long, realistic names**. The short names in the
  existing test hid the bug. Seed:
  - `PANADOL ADVANCE 500MG 24TAB LOCAL EGYPT (2STRIPSX12) SMALL OLD SIZE`
  - `PANADOL EXTRA  48TAB (EGYPT) (4STRIPSX12)`
  - `VOLTAREN - SR - 100MG 20TAB (2STRIPSX10) فولتارين 100 مجم`
  - `AUGMENTIN 1G (1000MG) 14 TAB (2STRIPSX7) اوجمنتين 1جم 14قرص`
  - `CATAFLAM  50MG 20TAB (2STRIPSX10)`
  - `ANTIFLAM 50MG 20TAB`

  Tests:
  - `test_single_word_typos`: the first approx result's name for `panadool`, `voltren` and
    `agmentin` starts with PANADOL, VOLTAREN and AUGMENTIN respectively.
  - `test_spelled_beats_sounds_like`: `item_search('cataflm 50')[0]` is CATAFLAM, and ANTIFLAM is
    not first.
  - `test_gibberish_no_guess`: `item_search('xqzvw') == []`.
  - `test_existing_multiword_typos_unchanged`: the existing `test_typo_fallback_only_when_nothing_found`
    still passes.

- [ ] **Step 2: Run, expect FAIL.** The single-word queries return `[]`.

- [ ] **Step 3: Implement.** In `score`, the weights of `wagree` (0.2) and `agree` (0.1) count
  only when the query has extra words or numbers respectively. Otherwise the score is divided by
  the sum of the weights in use, which keeps the scale 0..1. `APPROX_MIN` stays 0.6.

- [ ] **Step 4: Run, expect PASS** (the whole module).

- [ ] **Step 5: Commit**: `fix(search): single-word typos (panadool, voltren, agmentin) find the brand`.

---

### Task 6: Ingredient tier, disease expansion out of pickers, the `limit` param

**Files:**
- Modify: `apps/catalog/wildcard.py` (`item_search`: the `ingredient` tier before `approx`)
- Modify: `apps/catalog/views.py` (`softech_search`: drop the `_expand_disease_query` call; add
  `limit` and `code_prefix` params; `_search_rows` adds the `ingredient` flag, `ingredient_name`
  and `id`)
- Test: `apps/tests/test_wildcard_search.py` (new class `IngredientAndEndpointTests`)

**Interfaces:**
- Produces:
  - tier `'ingredient'`;
  - row keys `ingredient: True`, `ingredient_name: str`, `code_part: True`, `synonym: True`,
    and `id` (= `item_id`) on every row;
  - endpoint params `limit` (default 20, max 50) and `code_prefix` (`'0'` disables it; forced to
    `'0'` when `no_live=1`).

- [ ] **Step 1: Write failing tests**:
  - `test_ingredient_after_brands`:
    - seed `CATAFLAM 50MG` mapped through `ItemIngredientMap` to ActiveIngredient `DICLOFENAC
      POTASSIUM`, plus an item literally named `DICLOFENAC 50MG TAB`;
    - `item_search('diclofenac')`: the named item comes first (name tier), and CATAFLAM follows
      with tier `'ingredient'`.
  - `test_disease_word_not_expanded_in_picker`:
    - seed an item `GLUCO DR جهاز سكر` and a diabetes-class mapped item;
    - `GET /api/items/softech-search/?q=سكر&no_live=1` returns the device and **not** the mapped
      drug.
  - `test_limit_param`:
    - `?q=concor&limit=2` returns 2 rows;
    - `limit=999` is capped at 50.
  - `test_pos_path_forces_exact_codes`: `?q=690&no_live=1` returns no row with `code_part`.
  - `test_rows_have_id_and_flags`: every row has `id == item_id`, and an ingredient row has
    `ingredient is True` plus `ingredient_name`.

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement.**
  - The ingredient tier runs when the window holds fewer than 60 ids, before `approx`.
  - It searches `ItemIngredientMap.objects.filter(active_ingredient__name` `ulike` pattern,
    restricted to `item__in=base`, and excludes ids already found.
  - Remove the `_expand_disease_query` call and its now-unused helpers. Before deleting, grep the
    repo: if anything else imports them, keep them and only remove the call.
  - In the batch summary, record whether the F7 drug assistant covers disease terms (spec §5.3).
    If it does not, list it as an open follow-up for the owner. Do not build it here.

- [ ] **Step 4: Run, expect PASS.** Run this class plus `apps.tests.test_pos_search_network` and
  `apps.tests.test_wildcard_search`.

- [ ] **Step 5: Commit**: `feat(search): ingredient tier after brands; disease expansion out of pickers; limit param`.

---

### Task 7: Warm start and the shared tier chip

**Files:**
- Modify: `apps/shortage/apps.py` (`ready`: warm the phonetic index on a thread)
- Create: `frontend/src/components/SearchTierChip.jsx`
- Create: `frontend/src/components/SearchTierChip.test.jsx`
- Modify: `frontend/src/components/ItemSearchInput.jsx:208-219` (use the chip)
- Modify: `frontend/src/pos/search/PosResultRow.jsx:65` (show the chip after the name; today POS
  rows show none)
- Test: `apps/tests/test_wildcard_search.py` (`test_warm_start_skipped_for_tests`)

**Interfaces:**
- Produces:
  - `<SearchTierChip row={row} />`. It renders at most one chip, by priority:
    1. `learned` → «من الذاكرة»;
    2. `ingredient` → «مادة فعالة: {ingredient_name}»;
    3. `sound` → «بالنطق»;
    4. `approx` → «تقريبي»;
    5. `code_part` → «جزء من الكود».

    `synonym` and the other tiers get no chip. Keep the existing title texts and colours; the
    new chips use violet for ingredient and gray for code_part.
  - `warm_search_index()` in `apps/shortage/phonetic.py`. It calls `index()` and swallows
    exceptions with a log line.

- [ ] **Step 1: Write failing tests.**
  - vitest `SearchTierChip.test.jsx`:
    - each flag renders its label;
    - `{}` renders nothing;
    - `{learned:true, sound:true}` renders only «من الذاكرة».
  - Django `test_warm_start_skipped_for_tests`: patch `sys.argv` to `['manage.py','test']` and
    call `ShortageConfig.ready`; assert `start_thread` is not called. Patch it to
    `['manage.py','runserver']` with `RUN_MAIN='true'`; assert it is called once with
    `warm_search_index`.

- [ ] **Step 2: Run, expect FAIL.** Run `cd frontend; npx vitest run src/components/SearchTierChip.test.jsx`
  and the Django test.

- [ ] **Step 3: Implement.**
  - `ready()` uses `core.threads.start_thread` (memory: never a bare `Thread`).
  - It skips the same management commands `apps/sync/apps.py` skips (`migrate`, `test`, `shell`,
    and the rest of that list) and the autoreload parent.
  - Replace the three inline chips in `ItemSearchInput` with `<SearchTierChip row={item} />`.
  - Add the chip in `PosResultRow` beside `item.name`.

- [ ] **Step 4: Run, expect PASS.** Then run `cd frontend; npm run build`, which must succeed.

- [ ] **Step 5: Commit**: `feat(search): warm the sound index at start; one tier chip on POS and pickers`.

---

### Task 8: Golden corpus, the `search_probe` command, help text

**Files:**
- Create: `apps/catalog/search_corpus.py`
- Create: `apps/catalog/management/commands/search_probe.py`
- Create: `apps/tests/test_search_corpus.py`
- Modify: `apps/help/content/pos.py:294-297` (the `pos-order-search` entry, and that screen's
  `updated` date)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `CORPUS: list[dict]`. Each entry is
    `{'q', 'expect' (regex the top-1 name must match), 'top': 1|3, 'tier': optional expected tier of that row, 'note'}`.
  - It holds the 52 queries of the 2026-11-16 probe with their expectations, using the **fixed**
    behaviour. Exceptions:
    - `سكر` expects a device row;
    - `diclofenac` expects an ingredient row;
    - `%1%cream` expects `1%.*CREAM` within the top 3.
  - `SEED_NAMES: list[tuple[softech_id, name, name_scientific]]`: the realistic names that make
    the corpus pass on a mini-catalog. Copy the names exactly as the probe printed them,
    including double spaces and the Arabic parts.

- [ ] **Step 1: Write the test.** `test_search_corpus.CorpusTests.test_corpus` seeds
  `SEED_NAMES`, plus barcodes and one `ItemIngredientMap`. For each entry it calls
  `item_search(q)` and asserts the expectation, using `subTest(q=…)`. It also
  `test_corpus_via_endpoint` calls `/api/items/softech-search/?no_live=1` for each `q` and checks
  the same top-1.

- [ ] **Step 2: Run.** Every failure must point to a rule from Tasks 1–6. Fix the **engine**, not
  the corpus, unless an expectation contradicts the spec. Record any such case in the commit
  message.

- [ ] **Step 3: Implement `search_probe`.**
  - Usage: `manage.py search_probe [--repeat 3] [--json PATH]`.
  - It is read-only and runs on the real DB.
  - For each `CORPUS` entry it calls, in-process with `APIRequestFactory(SERVER_NAME='localhost')`
    and an existing superuser:
    - the three endpoints (`softech-search?no_live=1`, `/api/items/?search=`,
      `/api/search/universal?types=items`);
    - `item_search` directly.
  - It prints pass/fail per path and p50/p95 ms per path.
  - Exit code is 1 if any `item_search` p95 is over 40 ms or the top-1 pass rate is under 100%.
  - The other paths are report-only until S2.

- [ ] **Step 4: Update help.** In `pos-order-search`, add one Arabic and one English sentence:
  - results that start with what you typed come first;
  - whole numbers come first, but any match of the digits shows;
  - abbreviations such as syp/شراب work;
  - list the chips «من الذاكرة / بالنطق / تقريبي / مادة فعالة».

  Bump `updated` to the commit date. Run `apps.tests.test_help`.

- [ ] **Step 5: Run.**
  - `apps.tests.test_search_corpus` passes.
  - Then, on the local real DB: `.\venv\Scripts\python.exe manage.py search_probe`. Expected:
    path A 52/52 and p95 ≤ 40 ms. Paste the summary table into the PR body.

- [ ] **Step 6: Commit**: `test(search): golden corpus + search_probe command; POS help updated`.

---

### Task 9: Batch verification and merge

- [ ] **Step 1:** Check free RAM (more than 6 GB free), then run serially:
  `$env:TEST_DB_NAME='test_search_s1'; .\venv\Scripts\python.exe manage.py test apps.tests.test_wildcard_search apps.tests.test_search_corpus apps.tests.test_pos_search_network apps.tests.test_arabic_matching apps.tests.test_matching_learning apps.tests.test_help apps.tests.security`.
  All of them pass.
- [ ] **Step 2:** `cd frontend; npx vitest run; npm run build`. Both pass.
- [ ] **Step 3:** Compare `search_probe` before (main) and after (branch). There must be no query
  that passed before and fails now.
- [ ] **Step 4:** Push the branch `claude/unified-item-search` and open a PR. The PR body holds
  the probe table, the F7-disease note from Task 6, and the migration `0044` note (indexes only).
  Wait for every check, then merge by hand (memory: never `--auto`). Fast-forward local main and
  the laptop folder.
- [ ] **Step 5:** Update memory `wildcard_search_rules.md` with the new tiers and decisions D1–D7.
