# 31 — One matching and review flow for «طلبات واتساب» and «صندوق الإتاحة»

**Status:** 🟡 DESIGN, waiting for owner approval. Nothing here is built.
**Date:** 2026-10-24 (batch 5).

The owner's complaint (2026-10-24): matching WhatsApp branch requests is very different from the
availability inbox, and so are the item-matching screen and the exported files. Take the best
of both and match them.

---

## 1. What is shared today and what is not

Both already use the same catalog matcher and learning memory:
- `apps/shortage/matching.find_best_matches`;
- the ItemAlias memory with close spellings, rejections and groups;
- Arabic sound matching.

Everything around the matcher is separate:

| | «صندوق الإتاحة» (supplier lists) | «طلبات واتساب» (branch requests) |
|---|---|---|
| Message splitting | `availability._WA_*` header regexes | `branch_requests._HEADERS`: a second, different set |
| Line reading | supplier terms: price, discount, bonus «N+M», quota, signals, expiry, families «بتركيزاته», variants & / و | quantity only with a unit word («2 علبة», «عدد 3», ×2); a bare number = strength; fillers, names and phones become notes |
| Match path | `ingest.resolve_line` → `_prefer_written` (form / strength tie-break within 0.10) → barcode & supplier-code lookups | `branch_requests.resolve` → its own version logic (brand family, strength narrowing) |
| Auto-match cut-off | 0.55 | 0.70 |
| Review flags | strength_mismatch · form_mismatch · head_mismatch · ambiguous | choose_variant · strength_mismatch · head_mismatch · low_score · pack_not_found · qty_large · qty_maybe_strength · strips |
| Candidates shown | top matches | versions **with branch stock and network sales** (tells an obsolete duplicate code from a real size) |
| Several items for one line | split rows (`split_from`) | `extra_items` M2M + «كل الأنواع» |
| Review screen | keyboard grid (↑↓ Space Enter M Ctrl+A), confirm-all-clean, frozen order while matching, lock / unlock with audit, duplicate merge, branch scope, freshness strip | Enter-to-confirm-next, photo OCR, pack hint («60 قرص ≈ 5 علب × 14»), picks bar |
| Output | supplier order: copy / WhatsApp / Excel «طلب شراء» | ISR-style plan workbook (PlanView) + branch ShortageList + transfer legs |

## 2. Head-to-head benchmark (read-only, 2026-10-24)

- **Test set:** 431 texts a person confirmed (394 inbox, 37 WhatsApp).
- **Memory off** for both pipelines, so the engines themselves are measured; with memory on, anything already confirmed scores 100%.
- **Clean but wrong** = not flagged, yet the wrong item. That is the dangerous case.

| Pipeline | Texts from | n | Top-1 right | Flagged for review | Clean but wrong | Right item among shown candidates |
|---|---|---|---|---|---|---|
| inbox | inbox | 394 | **77.7%** | 25% | **47** | — |
| WhatsApp | inbox | 394 | 38.6% | 58% | 16 | 85% |
| inbox | WhatsApp | 37 | 83.8% | 35% | 1 | — |
| WhatsApp | WhatsApp | 37 | 73.0% | 30% | 0 | 92% |
| **combined** (inbox ranking + both flag sets + "the two disagree") | inbox | 394 | **77.7%** | 67% | **6** | 89% |
| **combined** | WhatsApp | 37 | 83.8% | 49% | 0 | 92% |

Reading it:
- The **inbox ranking picks the right item more often**, mainly thanks to the form / strength tie-break.
- The **WhatsApp flags and version list are safer**: they refuse to guess between versions, and they show stock and sales so the reviewer can choose.
- **Combining them** keeps the inbox's accuracy and cuts "clean but wrong" from 47 to 6. The cost is more lines to review: 67% with memory off.
- **Correction (measured 2026-10-25):** the learned memory resolved only **9%** of the last 30 days' supplier-list lines (73 of 858), so daily review load will stay close to this figure for now, falling as the memory grows. Today's inbox flags about 18% of lines.

Speed: inbox 57 ms average (p95 129 ms); WhatsApp 88 ms (p95 158 ms).

## 3. Target design

### 3.1 One matching core: `apps/supply/line_matching.py`

`match_text(text, *, context)` returns item, score, candidates, versions, flags and provenance. Context = `{'source': 'supplier'|'branch', 'vendor_code', 'branch', 'qty_info'}`.

1. **Lookups:** learned group / alias, then barcode and supplier code (source supplier only), then `find_best_matches`.
2. **Ranking:** `_prefer_written`, the form / strength tie-break, for every source.
3. **Versions:** the WhatsApp version logic for every source. Candidates carry branch stock and network sales. Versions are never auto-picked when several fit.
4. **Flags:** the inbox `review_flags`, the WhatsApp version / pack / qty flags, and a new `engines_disagree` flag. The flag policy is the owner's choice (§4).
5. **One cut-off for both**, owner's choice: 0.55, 0.70, or per source.

The parsers stay separate, because a supplier line and a branch request mean different things. They will share:
- **one WhatsApp message splitter**, so one header format is maintained, not two;
- **one cleaner** for digits and invisible characters.

### 3.2 One review grid: `MatchReviewGrid` (frontend), the union of both screens

- **Keyboard:** ↑↓ Space Enter M Ctrl+A (`useGridKeyboard`), with frozen order while matching (already the project rule).
- **Confirming:** confirm-all-clean, and Enter confirms and moves to the next line.
- **Candidate panel:** versions with branch stock and network sales, multi-pick checkboxes, «كل الأنواع», «فقط هذا».
- **Hints:** pack hint and qty hint, never auto-applied.
- **Input:** paste, photo OCR, and Excel / CSV upload on both screens.
- **List housekeeping:** duplicate merge, and lock / unlock with reason and audit.
- **Context strip:** freshness, with refresh buttons, on both screens.
- **Sorting:** every column sorts.

Each screen keeps its own side panel: «طلب الشراء» for the inbox, the fulfilment plan and transfers for WhatsApp.

### 3.3 One export family: `apps/supply/exports.py`

- **Same item block, same order and names, in both files:**
  - code, item, written text, qty;
  - matched-by (learned / barcode / supplier code / fuzzy), flags;
  - branch stock, network sales per month, in transit, need.
- **Branches** always as «code · name» (project rule). Arial, right-to-left, frozen header, filters, an explanation sheet.
- **Purpose sheets on top:** «طلب شراء» (inbox) and the fulfilment plan (WhatsApp, the existing formula workbook).

### 3.4 Learning stays as it is

Teach on confirm and record a rejection on correction, as today on both screens. The memory store does not change.

## 4. The strict flags, one by one (owner chose strict, 2026-10-25)

Measured on the same 431 confirmed texts, learned memory off:
- **Fires:** how many lines the flag marks.
- **Catches:** marked lines whose first match was really wrong.
- **False alarms:** marked lines whose first match was right; the reviewer only confirms them.
- **Only catch:** wrong lines that no other flag marked.

Overall: 94 first matches are wrong; strict marks 281 lines and catches 88 of the 94.

| Flag (screen label) | Fires when | Fires | Catches | False alarms | Only catch | Real catch |
|---|---|---|---|---|---|---|
| **اختر النسخة** (choose_variant / version not picked) | several versions of the product fit (strength, pack size, form) and the text does not settle it | 213 | 57 | 156 | — | «اميكاسين كوته» → AMIKACIN lotion spray; really AMIKIN 100 MG vial |
| **التركيز مختلف** (strength_mismatch) | a number written in the text is not in the item's name | 57 | 20 | 37 | 2 | «اولوباتسون 120 … 250 جرعه» → 120 dose; really 240 dose |
| **منتج آخر قريب** (ambiguous) | a *different* product scores within 0.05 of the winner | 37 | 11 | 26 | 1 | «اس جولد 1» → S-26 GOLD; really S-26 PRO GOLD (1) |
| **لا يوجد تطابق** (no_match) | nothing in the catalog is close enough | 20 | 18 | 2 | 18 | «لاكريفريش» → none; really LACRIFRESH drop |
| **الشكل مختلف** (form_mismatch) | the text names a form (tab / cap / amp / syrup …) different from the item's | 15 | 6 | 9 | 5 | «زيثرون 500 مجم 3 اقراص» → ZITHROKAN 3 CAP; really XITHRONE 3 TAB |
| **حجم العبوة غير موجود** (pack_not_found) | a written pack size («60tab») exists in no version | 12 | 2 | 10 | — | «باور كابس 20 كبسول» → a cup; really POWER CAPS 20 CAP |
| **المحركان مختلفان** (engines_disagree), new | the two engines pick different items | 6 | 4 | 2 | — | «ناو سى 1000» → NO-URIC 100; really NOW C-1000 |
| **اسم الدواء مختلف** (head_mismatch) | the match latched onto a different leading drug word | 4 | 1 | 3 | — | MINOXILOOK lotion → STRONGVILLE lotion |
| **تطابق ضعيف** (low_score) | the best score is below the auto-match cut-off | 2 | 1 | 1 | — | as above |
| **شرائط / كمية كبيرة / الرقم قد يكون تركيزاً** (strips / qty_large / qty_maybe_strength) | quantity safety: strips not packs, > 10 packs, or the qty number is also a strength («كارفيد 25 علبة») | 1 each | — | — | — | these guard the **quantity**, not the item, so this test cannot score them |

What the numbers say:
- **The version flag carries the load.** It is the noisiest (about 1 in 4 firings is a real mistake), but without it 39 more wrong matches would slip through: 6 → 45, with 130 lines flagged instead of 281. It stays.
- **No match** and **form mismatch** are the sharpest. Each catches mistakes nothing else does.
- **The quantity flags** fire rarely and protect the qty, so they stay.

The 6 wrong matches that still slip through, and the fix each suggests (part of phase A):
1. «تي 4ثيرو 100» → T4-THYRO **50**MCG 100TAB: "100" was taken as present because the name has "100TAB", a pack count. Fix: compare strengths with strengths only, never with pack counts.
2. «بانادول اكسترا … أوبتيزورب 48» → PANADOL **ADVANCE**; really EXTRA OPTIZORB. The same happened for the 24-tab pack. Fix: Arabic «اكسترا / ادفانس» must agree with EXTRA / ADVANCE.
3. «جينيرا كوته 10» → GENETTERA; really GYNERA.
4. «بيبي كريم» → BABY CARE 30 MG CREAM; really BABY CREAM 60G.
5. «اينامكس حقنه شرجيه» → NAMIX; really ENEMAX solution.

Cases 3–5 are close sound-alikes. The memory learns them after the first correction.

How the screen keeps the extra review fast:
- A flagged line shows its reason as a short Arabic label, plus the candidate versions with branch stock and network sales.
- Space or Enter picks a version. Once a person picks one for a spelling, the memory stops flagging that spelling.

## 5. Decisions for the owner

1. **Flag policy:** ✅ strict (2026-10-25).
2. **Auto-match cut-off:** one value (0.55 or 0.70) or per source?
3. **Photo OCR and Excel upload on both screens:** yes?
4. **Order:** this unification before or after the «التوزيعة» redesign (doc 30)?

## 6. Phasing

| Phase | Content |
|---|---|
| A | `line_matching.py` + one message splitter; both screens switch to it. The benchmark is a test: no regression on the 431 texts |
| B | `MatchReviewGrid` replaces both review tables |
| C | `exports.py` + both Excel files on it |
| D | Help, and the benchmark command extended to report "clean but wrong" |
