# Unified Item Search — Design

Date: 2026-11-16 · Status: DRAFT, awaiting owner approval of this document

**Owner decisions (2026-11-16):** D1–D7 are approved as proposed, except D2, which the owner
changed.

| # | Decision |
|---|---|
| D1 | Word starts rank above "contains". |
| D2 (owner) | A digit matches wherever it appears, as SOFTECH does. Whole numbers only rank first. |
| D3 | A fixed synonym table (Appendix A). |
| D4 | Ingredient rows come after brands, tagged «مادة فعالة». |
| D5 | Disease-word expansion leaves the pickers and stays in the F7 drug assistant. |
| D6 | `%` stays a wildcard; the literal text tier makes «1% cream» work. |
| D7 | Minimum length: digits from 2 characters, names from 3 (2 = starts-with only). |

The owner also said:
- `*` and `%` are both valid everywhere;
- search must feel like SOFTECH's;
- wildcards must be standard in **every** search field.

**Calls made by the designer** (marked ⚙ where they appear):
- synonym matching;
- code fragments;
- the `/items/` opt-in;
- the POS row adapter;
- the `limit` window.

## 1. Why

Item search is the most-used action in the system: POS, reservations, transfers, demand,
shortage, purchasing, offers and more. Today the same words give different answers on different
screens. Some screens are slow, and some miss Arabic, typos and wildcards entirely. The owner
wants these four things:

- **One behaviour everywhere.** It should feel like SOFTECH: `*` and `%` are wildcards, and a
  search always means "contains".
- **Smarter than SOFTECH.** It should handle Arabic, typos and learned spellings the same way
  the transcription and OCR matching already does.
- **Ultrafast.**
- **Fast search in every screen**, plus the Ctrl+F1 advanced search. Each screen is single- or
  multi-select as its job requires.

## 2. What exists today (probe of 2026-11-16)

These numbers come from 52 realistic queries run on the local copy of the real catalog
(37,986 active items). The probe script is described in §9.

| Path | Used by | Top-1 correct | Speed |
|---|---|---|---|
| A — `GET /api/items/softech-search/` (`apps/catalog/wildcard.item_search`) | POS, invoices, supply, replacement, pick-zones, call center, OCR review | 44/52 | 160–220 ms |
| B — `GET /api/items/?search=` (`WildcardSearchFilter`); the widget strips `*` | ~20 screens via `ItemSearchWidget` default variant, plus the Ctrl+F1 modal | 29/52 | 350–800 ms |
| C — `GET /api/search/universal` | Ctrl+K | 43/52 | 300–470 ms |

**Defects found**

1. **Single-word typos return nothing on every path** (`panadool`, `voltren`, `agmentin`).
   `phonetic.candidates` finds the right items with a sound score of 1.0. `_approx_ids` then drops
   them because the word-agree and number-agree terms are 0 for a one-word query, so the score
   stays under `APPROX_MIN`.
2. **Code and barcode lookup takes about 80% of the time.** `softech_id__iexact` /
   `barcode__iexact` / `ItemBarcode.barcode__iexact` wrap the column in `UPPER()`, so the b-tree
   indexes are skipped. That costs 70–165 ms per search. The name tiers together take under 5 ms.
3. **Path B is weakest:**
   - The widget deletes `*`.
   - It has no sound, learned or typo tiers.
   - A typed code is not ranked first (`3690` returns cosmetics).
   - It sorts alphabetically within a rank (AUGMACILLIN above AUGMENTIN for «اوجمنتين»).
   - The list query prefetches stock and runs `distinct` over a barcode join.
4. **"Contains" ranking ignores word starts and whole numbers.** `vol*50` puts DIVOL … 500ML
   above VOLTAREN 50, and `pa` returns PAD and HEPATICUM.
5. **No synonyms for forms or units.** `syp` ≠ SYRUP, `vit` ≠ VITAMIN, and `1 جم` / `مجم` / `شراب`
   ≠ G / MG / SYRUP.
6. **Ingredient search barely works.** `name_scientific` is mostly a copy of the brand name
   (memory: catalog scientific name is dirty). Only `ItemIngredientMap` hits work.
7. **The disease expansion fires the wrong way round.** It runs only when there are fewer than 3
   results, so `سكر` returns glucose meters and a sugar bowl, never the diabetes drugs.
8. **UI split:**
   - There are 4 item components: `ItemSearchWidget` (2 variants), `ItemSearchInput`,
     `AdvancedItemSearchModal`, and `MultiItemPicker` (unused).
   - About 10 screens have ad-hoc search boxes.
   - The Ctrl+F1 modal returns only one item.
   - Every mounted widget listens to Ctrl+F1, so pages with two widgets open two modals.
   - The arrow keys work only in the POS variant.
9. **Wildcards are not standard in non-item search fields:**
   - 7 viewsets use plain DRF `SearchFilter`: audit, erp, payments, recommendations, transfers,
     transits, users.
   - About 59 views read `q`/`search` by hand.
   - About 7 frontend local filters use `.includes(q)` instead of `wildcardMatch`.

What already works and must not regress:
- wildcards on path A;
- any word order;
- Arabic by sound;
- Arabic-Indic digits;
- hamza forms;
- mixed Arabic and English;
- barcodes;
- learned aliases;
- the «من الذاكرة / بالنطق / تقريبي» chips;
- the POS `network=1` enrichment;
- the POS `no_live=1` rule.

## 3. Goals, non-goals, anti-goals

**Goals**
- One engine (`apps/catalog/wildcard.item_search`) behind every item search box, the Ctrl+F1
  modal and Ctrl+K.
- SOFTECH parity: every item SOFTECH's own search would return for the typed pattern is in our
  results. SOFTECH runs `LIKE '%…%'` on code, name, scientific name and barcode, ordered by name.
- Speed budget:
  - engine, server side: ≤ 40 ms p95 warm;
  - one picker round trip: ≤ 120 ms p95 on the office LAN;
  - path B list with filters: ≤ 150 ms p95.
- Ctrl+F1 in every screen that has an item box, honouring that screen's selection mode.
- Arrow keys, Enter and Esc in every item box.
- `*` and `%` as wildcards in every search field in the system, not only item fields, with a
  guard test that keeps it that way.

**Non-goals**
- No Arabic item names created or edited. The catalog stays SOFTECH's.
- No external search server and no new infrastructure.
- No change to prices, totals, stock or SOFTECH writes.
- No changes to the OCR/transcription matcher's own review flows, beyond reusing the same
  learning memory.

**Anti-goals** (failure even if it "works")
- A cashier lands on the wrong medicine. Codes and barcodes stay **exact only** on POS and Ctrl+K
  (`universal.py` safety rule).
- A non-exact row (sound, typo, ingredient, synonym) is auto-selected or auto-added. A person
  always picks it, and only an exact code or barcode scan auto-selects.
- An ingredient row reads as a substitute. It is shown for finding, never as "replace with"
  (rule 5).
- Any LLM decides results (rule 10).

## 4. Approaches considered

1. **Extend the existing engine and move every screen onto it.** *Chosen.* It reuses
   `wildcard.py`, the phonetic index, the learning memory and the trigram indexes that already
   exist, and adds no infrastructure. Most of the gap is wiring and two engine bugs, not missing
   capability.
2. **An external search server** (Meilisearch or Elasticsearch on the VPS). Rejected:
   - It adds a service to deploy, sync and secure.
   - Its relevance model diverges from SOFTECH's `LIKE` semantics, which the owner wants
     preserved.
   - The probe shows PostgreSQL answers the name tiers in under 5 ms already.
3. **An in-browser catalog index** (38k rows cached per tab). Rejected for now:
   - Stock, learned aliases, permissions and freshness live on the server.
   - It costs memory per tab and goes stale.
   - It could come back later for offline POS only.

## 5. Search rules (the contract)

These rules are owned by `apps/catalog/wildcard.py`, mirrored by `frontend/src/utils/wildcard.js`,
and documented in the help page.

### 5.1 Matching
- **Wildcards:** `*` and `%` are interchangeable everywhere (owner, 2026-10-05, reconfirmed
  2026-11-16). A search is always "contains". A leading or trailing wildcard changes nothing.
  Parts must appear in the order typed.
- **Spaces** are literal between parts. Runs of spaces count as one space on both sides, because
  the catalog has `VOLTAREN   1%`.
- **Case and letter forms:** case-insensitive. Arabic is folded with the existing
  `search_index.normalize_search_text` rules (أإآ→ا, ة→ه, ى→ي, tashkeel removed). Arabic-Indic
  digits are folded to Latin.
- **Words in any order** also match, as a lower tier.
- **Numbers (D2, owner):** a typed number matches wherever the name contains those digits.
  `5` matches 5MG, 2.5MG and 500MG, the same as SOFTECH `LIKE`. Ranking puts whole-number hits
  first (§5.2), so all of them appear but the most likely one leads.
- **Synonyms (D3):** a fixed, owner-approved table (Appendix A) adds variants of a typed token.
  For example, `syp` also searches SYRUP, and `جم` also searches G/GM. The typed form still
  matches literally. The table is code, reviewed like any rule, and never learned automatically.
- **Minimum length (D7):**
  - digits-only queries search codes and barcodes from 2 characters (exact);
  - names need 3 characters;
  - a 2-character name query is "starts with" only.

### 5.2 Ranking (best first; inside each tier, SOFTECH's order = by name)

| Tier | Meaning | Chip |
|---|---|---|
| `code` | exact SOFTECH code or any barcode (`Item.barcode`, `ItemBarcode`). Pickers outside POS/Ctrl+K also get a code prefix for ≥4 digits. | — |
| `code_part` ⚙ | SOFTECH parity: the typed digits appear **inside** a code or barcode (`690` → 3690). Only for digits-only queries, only outside POS and Ctrl+K, and always below every name tier. POS and Ctrl+K keep the exact-only safety rule (`universal.py`). | «جزء من الكود» |
| `learned` | a spelling people confirmed (shortage/OCR learning memory) | «من الذاكرة» |
| `starts` | the name starts with the typed text or pattern (D1) | — |
| `word` | the pattern starts at a word boundary in the name | — |
| `contains` | the pattern anywhere: literal text first, then the wildcard pattern in order | — |
| `any_order` | every word present, any order | — |
| `synonym` | matched only through Appendix A | — |
| `sound` | Arabic by sound (`phonetic`) | «بالنطق» |
| `ingredient` | `ItemIngredientMap` active-ingredient match (D4), after all brand tiers | «مادة فعالة» |
| `approx` | typo-tolerant, only when no text tier matched | «تقريبي» |

⚙ **Fields.** Name tiers search `name` and `name_scientific`, as SOFTECH does. A hit found only
in `name_scientific` ranks one step below the same hit in `name`, because the scientific field is
dirty. Code and barcode are searched only by `code` and `code_part`. A haystack that mixes code
and name text must not leak code hits into name tiers.

⚙ **Window.** The engine always collects a fixed candidate window of 60 ids before trimming to
the client's `limit`. Whether the ingredient or approx tiers run is decided on that window, never
on the client `limit`.

Inside the `starts`, `word` and `contains` tiers, items whose typed numbers match **whole**
numbers rank first (D2). The other rows follow by name. Over-matching is fine; mis-ordering is
the bug.

### 5.3 Removed from item pickers
- **Disease-word expansion (D5)** leaves `softech-search`. «سكر» in a picker means the product. The
  expansion lives on in the drug assistant (F7 «معلومات وبدائل»), which already owns
  disease-to-drug discovery.
- **The SOFTECH live fallback** stays as today: PG first, live only when PG has nothing and not on
  POS (`no_live=1`), behind the breaker.

## 6. Engine changes (`apps/catalog/wildcard.py` and friends)

1. **Code tier.**
   - Use exact `=` on `softech_id`, `Item.barcode` and `ItemBarcode.barcode`; codes and barcodes
     are digits, so case folding is unnecessary.
   - If a non-digit code is ever valid, normalise the input instead of wrapping the column.
   - The target is under 2 ms, which removes defect 2.
2. **Ranking.** Add the `starts` and `word` tiers and the whole-number boost. The `word` tier can
   use PostgreSQL `~*` with a `\m` word-start on the already-trigram-indexed `UPPER(name)`, or a
   Python re-rank of the ≤ limit×3 candidate ids. The builder picks whichever meets the budget.
3. **Space and Arabic folding.**
   - Literal and pattern tiers compare against folded text: `Item.search_name` (already
     normalised, trigram-indexed) or a collapsed-space expression.
   - Today `أوجمنتين` only matches by sound; after this it matches literally.
   - Note that `search_name` also contains the code and barcode. Name tiers must not report a
     code-only hit as a name hit.
4. **Synonyms** ⚙.
   - `apps/catalog/search_synonyms.py` holds Appendix A as a dict.
   - Expansion runs one way only, from the typed token to its canonical form. Typing SYRUP does
     not search `syp`.
   - Only a **whole typed token** expands: `syp` does, `sypx` does not.
   - The canonical form must match as a **whole word** in the name, or as a unit glued to a
     number (`500MG`, `1G`), never as a bare substring. So `g` → G does not hit every name
     containing a G.
   - A token mapping to several forms (`فوار` → SACH, EFF) searches all of them.
   - Synonym-only matches get the `synonym` tier.
5. **Typo fix (defect 1).** In `_approx_ids`, when the query has no second word and no number,
   the word-agree and number-agree terms are excluded from the denominator and do not count as
   zero. The rule must pass `panadool` / `voltren` / `agmentin` / `cataflm 50` and still reject
   pure sound-alikes (ANTIFLAM for «cataflm»).
6. **Ingredient tier (D4).**
   - Source: `ItemIngredientMap.active_ingredient.name` ulike the pattern.
   - It runs only when brand tiers return fewer than `limit` rows.
   - It is never mixed above brand rows.
   - Ingredient data is read only; nothing about substitution changes.
7. **Disease expansion** is removed from `softech_search` (D5).
8. **Warm start.** Build the phonetic index at process start (scheduler and web), not on the first
   keystroke. This removes the 890 ms cold first call.
9. **Response shape** ⚙.
   - One row shape for every consumer: the current `_search_rows` dict, plus `tier`,
     `id` (= `item_id`) and `all_barcodes`.
   - The POS `addItem` and the pricing and line logic stay **untouched**. A small adapter in the
     widget maps any row to the object `addItem` receives today.
   - A golden test asserts that the same item added from the quick box and from Ctrl+F1 produces
     byte-identical line fields: `pack_price`, `unit_price`, `pack_qty`, `unit_name`,
     `batch_required`, `is_stockable`.
   - No price, discount or checkout code changes. If the builder finds that `addItem` itself must
     change, they stop and ask.

## 7. Endpoints

**No new endpoint (rule 6).**

- **`GET /api/items/softech-search/`** stays the picker endpoint. Its params are `q`, `branch_id`,
  `network`, `no_live`, `limit` (default 20, max 50) and `code_prefix`. The server forces
  `code_prefix` off when `no_live=1` (POS).
- **`GET /api/items/?search=`** (Ctrl+F1 modal, list screens) ⚙. The engine path is
  **opt-in** with `rank=engine`, which the widget and the modal send. Other callers keep today's
  `WildcardSearchFilter`, which already follows the wildcard rules, so they lose nothing:
  - no inactive items dropped;
  - no 500-row cap;
  - no pagination change.

  When `search` and `rank=engine` are both present:
  - the queryset is filtered to the ids from `item_search(q, limit=500)`;
  - it is ordered by the engine's rank unless the user picked a column sort; the rank still leads
    within that sort, as today;
  - the modal's filters (category, supplier, price, …) stay `AND` filters on top.

  Avoid prefetching `stock_levels` for picker-sized pages, and avoid `distinct` over the barcode
  join (the engine already resolved barcodes).
- **`GET /api/search/universal`** already calls `item_search`. It inherits every engine fix.

## 8. Frontend

### 8.1 One component
`ItemSearchWidget` becomes the only item box. The name is kept to avoid churn.

- The default variant calls `softech-search` and keeps `*`/`%`.
- Arrow keys, Enter and Esc work in every variant.
- Tier chips and match highlighting (`utils/wildcard.highlightRanges`) appear in every variant.
- `ItemSearchInput` call sites (invoices, supply, replacement, pick-zones, shortage OCR review)
  move to the widget. `ItemSearchInput` and `MultiItemPicker` are then deleted.

The new `mode` prop:

| Mode | Behaviour |
|---|---|
| `single` | Pick one item; shows the selected card with «تغيير». |
| `list` | Each pick calls `onSelect` and the box clears and keeps focus for the next line. |
| `multi` | Tick several rows (Space), then Enter adds all; `onSelect` receives an array. |

The new `exactCodeOnly` prop is for code-entry places such as insurance re-code. It shows the
search but prefers the exact code row.

**Ctrl+F1.** One global listener lives in a small provider. It opens the modal for the widget that
last had focus, or the first widget on the page if none did. In `multi` mode the modal shows a
checkbox column and «إضافة المحدد (n)». In `single` and `list` mode it behaves as today.

### 8.2 Screen modes (my proposal; owner may change any row)

| Mode | Screens |
|---|---|
| `list` (add lines one after another) | POS + mobile POS, new transfer (+ mobile), demand (+ mobile), new reservation (+ mobile), stock count (mobile), call center items |
| `multi` | offers item scope, vouchers eligible items, incentive rules, replacement extra items / add product, supply availability line mapping, catalog-intelligence bundle items |
| `single` | transfer / reservation / demand detail «add item», shortage line link, shortage OCR override, invoice line match, pick-zone override, pricing approval, counselling, catalog-intelligence variant member and FBT filter, `/m/items`, insurance re-code and item override (`exactCodeOnly`), market-shortage manual add, branch-request line search |

**Out of scope** (they are their own browse or search tools and keep their screens):
- `/products`
- `/ingredient-search`
- `/image-enrichment`
- the report filter boxes listed in §8.3.

Those report boxes still follow the wildcard rules.

### 8.3 Wildcard standardisation outside item pickers
- **Backend.** The 7 plain `filters.SearchFilter` viewsets move to `WildcardSearchFilter`. Each of
  the ~59 hand-rolled `q`/`search` readers is reviewed:
  - a text "contains" filter → `wq(q, fields…)` / `filter_and_rank`;
  - an exact-id lookup stays exact, with a comment saying why.
- **Frontend.** Local grid filters that use `.includes(q)` move to `wildcardMatch`. Report item
  filter boxes (purchasing, recommendations, supply, procurement, stock-audit, follow-ups, …)
  keep their own endpoints but pass through `wq`.
- **Guard test**, like the role-literals guard:
  - It fails on a new `filters.SearchFilter` in `apps/`, and on new
    `.toLowerCase().includes(q|search|query|filter)` in `frontend/src`.
  - It has an allow-list for reasoned exceptions.

## 9. Tests and measurement

- **CI golden corpus.** `apps/catalog/tests/test_search_corpus.py` seeds a mini-catalog. It uses
  realistic names copied from the probe (PANADOL …, VOLTAREN   1%, CATAFLAM  50MG,
  CONCOR 5MG / COR 2.5MG, AUGMENTIN … اوجمنتين, CONGESTAL كونجستال, CERELAC, DIVOL 500ML,
  ItemIngredientMap rows, barcodes). It asserts the expected top-1 or top-3 and the tier for
  every probe query and every bug in §2. Each new bug adds a row.
- **Real-catalog probe.** A `manage.py search_probe` command turns the 2026-11-16 scratch probe
  into a kept tool. It runs the corpus against the live DB through all three endpoints and
  prints pass/fail and p50/p95 ms. It is read-only and run before and after each batch.
- **Speed.** A CI test asserts the query count per `softech-search` call (no N+1, no seq-scan
  code lookup). The ms budget is checked by `search_probe` on real data, not in CI.
- **Frontend.**
  - Widget tests for each mode.
  - Ctrl+F1 targets one widget only.
  - The modal multi-select returns an array.
  - Keyboard navigation works in the default variant.
- **Help (rule 5b).** A new help topic «البحث عن الأصناف / Item search» (rules, wildcards, chips,
  Ctrl+F1, modes). Every screen whose picker changes behaviour gets its `updated` date bumped.

## 10. Delivery batches

Each batch is tested, merged to main, and the laptop fast-forwarded.

1. **S1 — Engine:**
   - code-tier index fix;
   - typo fix;
   - `starts`/`word`/whole-number ranking;
   - space and Arabic folding;
   - synonyms;
   - ingredient tier;
   - disease expansion out;
   - warm start;
   - corpus test plus the `search_probe` command.

   Instantly improves POS, Ctrl+K and every screen on path A.
2. **S2 — Path B onto the engine:** `/items/?search=` through `item_search`; the widget default
   variant switches to `softech-search` and stops stripping `*`; keyboard support in the default
   variant.
3. **S3 — Modes and Ctrl+F1:** `mode` prop, single Ctrl+F1 owner, modal multi-select, one row
   shape; migrate the `ItemSearchInput` and ad-hoc screens; delete the dead components.
4. **S4 — Wildcards everywhere:** the 7 `SearchFilter`s, the q/search readers, the frontend local
   filters, and the guard test.
5. **S5 — Help topic and per-screen help dates.** Can ride with S2 and S3.

## 11. Left to the builder
- `word`-tier implementation: SQL regex vs Python re-rank, whichever meets the budget.
- Whether folded comparison uses `search_name` or a new expression index. A migration is allowed
  if needed; it is catalog-only and does not touch SOFTECH sync.
- Exact chip wording for `synonym` (probably no chip) and `ingredient` («مادة فعالة»).

## Appendix A — Synonym table (D3, for owner review)

Applied per token, both directions where shown (↔). The typed form always also matches as
typed.

| Typed | Also searches |
|---|---|
| syp, syr, شراب | SYRUP |
| susp, معلق | SUSP, SUSPENSION |
| tab, tabs, قرص, اقراص | TAB |
| cap, caps, كبسول, كبسولات | CAP |
| amp, حقن, حقنة, امبول | AMP |
| vial, فيال | VIAL |
| supp, لبوس, تحاميل | SUPP |
| drops, drop, نقط, نقاط | DROPS |
| cr, crm, كريم | CREAM |
| oint, مرهم | OINT |
| gel, جل | GEL |
| sach, sachet, فوار, اكياس | SACH |
| eff, effervescent, فوار | EFF |
| inh, بخاخ | INHALER, SPRAY |
| vit, فيتامين | VITAMIN |
| mg, مجم, مللجم | MG |
| g, gm, gram, جم, جرام | G, GM |
| ml, مل | ML |
| mcg, ميكروجرام | MCG |
| iu, وحدة | IU |
