# Piece 4 — item and channel codes: SOFTECH findings and design addendum

Date: 2026-11-13 · Status: **approved by owner 2026-11-13** — §6 questions 1–5 all answered
"yes" as proposed · Parent design: `2026-11-13-branch-classification-and-crews-design.md` §7 piece 4.

## 1. What piece 4 fixes

Two SOFTECH code sets have their meanings typed into our code, in several places, and the copies
disagree: the customer sales channel (`ptclassifcode`) and the item general category
(`items.itemmedicine` → our `Item.medicine_type`). A new SOFTECH code today is either dropped,
shown under a wrong label, or put in a guessed bucket. Goal: one editable mapping per code set,
read by every module; an unknown code shows as «غير مصنف» and is never guessed.

## 2. SOFTECH truth (read-only, HQ `SOFTECHDB9`, 2026-11-13)

Queried through `config/sybase.py` (SELECT only, small/aggregated, date-bounded).

### 2.1 Customer channels — `persontypesclassif` where `ptcode='10'` (عـمـيــل)

`ptclassifcode` is scoped by `ptcode` (a supplier's `10` is not a customer's `10`); every invoice
we care about has `ptcode='10'`. Sales = `stktransm` doccode 115, Aug–Oct 2026, all branches.

| code | SOFTECH label | sales Aug–Oct (count / EGP) | customers in `personsdata` |
|---|---|---|---|
| 91 | عميل نقدى | 52,529 / 9.04M | 1 |
| 10 | تعاقدات / آجل | 7,230 / 10.71M | 207 |
| 90 | عميل Delivery | 3,720 / 2.84M | 1 |
| 30 | عميل دائم | 1,729 / 0.74M | 41 |
| 11 | موظفيين شركة الرزيقي | 389 / 0.13M | 117 |
| 16 | تبرعات | 151 / 0.19M | 30 |
| 17 | تعويضات الشركات | 20 / ~0 | 9 |
| 12 | إيصال إلكترونى بالبطاقة الشخصية | 15 / 0.04M | 1 |
| 15 | تأمين صحي | 0 | 0 |
| 31 | مقاصات ... | 0 | 1 |
| 33 | تعاقد - سداد آجل - خصم يدوي | 0 | 0 |
| 99 | Vip | 0 | 0 |

There is **no code 13** for customers. Other person types (00 branch, 09 prospect, 11 individual,
20 supplier, 30 employee job titles, 40 doctors/clinics, 60, 70, 80) also live in this table;
they never appear on a customer sale.

`ChannelBucketMap` (`apps/forecasting/models.py:104`) **already holds every one of these
(ptcode, ptclassifcode) pairs** (owner-validated against تحقيق مايو 2026) and maps them to the KPI
buckets cash / credit / insurance / exclude (+ delivery / regular subtypes). It is the obvious
home for the one mapping.

### 2.2 Item general category — `itemstree` (8 rows) and `items.itemmedicine`

| code | SOFTECH label | items (all / active) |
|---|---|---|
| 10 | Medicine | 15,184 / 11,822 |
| 50 | Cosmetics | 22,884 / 15,215 |
| 20 | Others | 12,319 / 9,475 |
| 30 | Body Building | 549 / 502 |
| 40 | Veterinary | 478 / 471 |
| 60 | هدايا عملاء | 445 / 443 |
| 70 | Services خدمات | 19 / 13 |
| 00 | N A | 38 / 32 |

("active" = `itemarchive=0 and itemnomoreuse!='1'`.) Every item carries one of these 8 codes today.

### 2.3 A third code set seen on the way — `items.itemnosaleclassif`

Dispensing restriction (10 = normal, 20/30/31 restricted; 4,888 null; 17 odd values such as
1110, 4030). It is a safety field, not a category; `apps/insurance/sybase_queries.py:530` and
`apps/catalog/safety.py` already treat "10 or empty = normal, anything else = restricted", which
is fail-safe for a new value. **Left out of piece 4.**

## 3. Channel meanings — what the code says vs SOFTECH

| code | SOFTECH | `followups/models.py:401` | `pos_orders/models.py:23` | `replacement/config.py:55` | KPI bucket (`ChannelBucketMap`) |
|---|---|---|---|---|---|
| 91 | نقدى | كاش / مشي ✓ (favoured, 1) | cash ✓ | — | cash |
| 90 | Delivery | توصيل ✓ (favoured, 1) | delivery ✓ | — | cash / delivery |
| 10 | تعاقدات / آجل | **«بيع عام» general retail ✗** (favoured, 2) | contract ✓ | contract ✓ | credit |
| 11 | موظفيين الرزيقي | **«شركات» corporate ✗** | employee ✓ | contract ✓ | cash |
| 12 | بطاقة شخصية | **«جملة» wholesale ✗** | card_receipt ✓ | — | cash |
| 13 | *(does not exist)* | **«عميل دائم» ✗** (favoured, 2) | — | — | — |
| 15 | تأمين صحي | تأمين ✓ | insurance ✓ | contract ✓ | insurance |
| 16 | تبرعات | **«تأمين طبي» ✗** | donation ✓ | — | exclude |
| 17 | تعويضات الشركات | **«تأمين تكميلي» ✗** | compensation ✓ | contract ✓ | exclude |
| 30 | عميل دائم | **«أخرى» other ✗** | permanent ✓ | — | cash / regular |
| 31 | مقاصات | missing → «قناة 31» | — | — | credit |
| 33 | تعاقد خصم يدوي | missing → «قناة 33» | — | **missing** | credit |
| 99 | Vip | missing → «قناة 99» | vip ✓ | — | exclude |

Verdict:
- **POS writer table (`CHANNEL_TO_PTCLASSIF`) matches SOFTECH exactly** — all 10 codes, labels
  included. Nothing to fix there.
- **Follow-ups table is wrong on 7 of 10 codes.** Live effect on the office DB: 16,843 follow-up
  tasks on contract sales (10) show as «بيع عام» and rank as *favoured*; 2,965 tasks for real
  permanent customers (30) show as «أخرى» and rank *not favoured*; the priority sort
  (`followups/views.py:256`) favours the non-existent 13 instead of 30.
- **Replacement contract set** (10, 11, 15, 17) agrees with SOFTECH but leaves out 33 (no sales
  yet; would be missed the day it is used).
- **Chronic customer type** (`chronic/classifier.py:38`, copy in `chronic/task_generator.py:23`)
  tests codes that do not exist for customers ('1', 'CASH', '5'…'9', 'INS'…) against
  `Customer.softech_ptclassifcode`, which is blank for 198,809 of 199,035 customers. Result:
  **every customer is classed 'home_delivery'** (the fall-through). The chronic task filter by
  customer type is therefore meaningless today.
- A fifth copy found while checking: `Customer.customer_type_label` / `customer_type_color`
  (`customers/models.py:184`) know only 90 / 91 / 15; every other channel shows as «عميل». It
  switches to the reader in 5.1 too.

## 4. Item-category meanings — what the code says

| meaning in code | code used | places |
|---|---|---|
| "is a medicine" | `medicine_type='10'` | `followups/services.py:494` (refill tasks only for medicine), `stock_audit/engine.py:60`, `purchasing/isr_softech.py:51` (ISR screen default filter) |
| "customer gift / coupon — not real stock" | `medicine_type='60'` | `purchasing/isr_softech.py:236`, `purchasing/rate_writer.py:376`, `purchasing/seasonality.py:196`; and SystemSetting `analytics_excluded_medicine_types` default `'60'` (`insights/rules.py:141`) |

These agree with SOFTECH (10 = Medicine, 60 = هدايا عملاء). The problem is only that the meaning
lives in 6 literals + 1 setting. Not touched: 70 Services (13 active items) is already kept out of
planning by `is_stockable` / `pack_price>0`; 00 N A (32 active) is treated as an ordinary item.

Keyword lists named in the sweep, reviewed and **left alone** (they are not item-code meanings):
`transits/export.py:991` (pack sub-unit nouns from item names), `chronic/classifier.py:58`
(clinical class keywords), `discount_approvals/alignment.py:51` (discount-class label families),
`finance/queries/sybase_discovery.py:80` (schema-discovery heuristic).

## 5. Design

### 5.1 Channels — extend `ChannelBucketMap`, don't add a table

`ChannelBucketMap` already has one owner-edited row per SOFTECH (ptcode, ptclassifcode). It gains:
- `label_ar` — SOFTECH `ptclassifdescr`, refreshed by sync (owner may not edit; it is SOFTECH's).
- `group` — what the channel *is*, one of: `cash` نقدي، `delivery` توصيل، `permanent` عميل دائم،
  `contract` تعاقد، `employee` موظفين، `insurance` تأمين، `card` بطاقة شخصية، `donation` تبرعات،
  `compensation` تعويضات، `settlement` مقاصات، `vip` VIP، `other` أخرى، `unclassified` غير مصنف.
- `is_contract_sale` — feeds the replacement (بدل الروشتة) matcher.
- `followup_rank` — 1 (most favoured) … 4; null = not favoured, sorted last.

The existing `bucket` / `subtype` stay exactly as they are (KPI figures do not move).

One reader, `apps/forecasting/channels.py`: `channel(ptcode, code)` → (group, label, bucket,
rank, is_contract); cached; an unknown pair returns group `unclassified`, label
«غير مصنف (<code>)», bucket `exclude` (today's KPI behaviour), rank none. Consumers switch to it:
followups label / favoured / priority sort; replacement `CONTRACT_CHANNELS`; chronic customer type
(see 5.3). Sync: a SOFTECH pair not yet in the table is inserted as `unclassified` / `exclude`
and admins get one notification (same pattern as piece 1's pending branch).

**POS writer is not changed.** `CHANNEL_TO_PTCLASSIF`, `CLAIM_CHANNELS` and `_CHANNEL_CUST_PROF`
are the writer's verified posting contract with SOFTECH; making them editable would let a
settings edit change what is posted. Instead a guard test asserts every POS channel code exists
in the registry with the matching group, so the two can never drift apart silently.

### 5.2 Item categories — new `MedicineTypeMap`

New small table (in `apps/config`, beside `SystemSetting` / `DropdownOption`): `code`, `label`
(from SOFTECH `itemstree`, refreshed by sync), `group` (medicine, cosmetics, others,
body_building, veterinary, gift, service, na, unclassified), `is_medicine` (bool),
`excluded_from_planning` (bool — gift/coupon codes: no ISR, rate, seasonality, analytics).
Seeded from §2.2: 10 → is_medicine; 60 → excluded_from_planning; the current value of
`analytics_excluded_medicine_types` is copied into the flags, and that setting is then read from
the table (setting key kept as a deprecated alias for one release). Reader:
`apps/config/item_types.py` — `medicine_codes()`, `planning_excluded_codes()`, `label(code)`;
unknown code → «غير مصنف», not medicine, not excluded. The six literals in §4 switch to it. A new
SOFTECH category arrives as `unclassified` with an admin notification.

### 5.3 Chronic customer type

Replace the dead code lists with the customer's channel group: the channel of the customer's most
recent sale (`PurchaseHistory`, which stores the invoice `ptclassifcode`), mapped through 5.1:
cash → walk-in, delivery → home delivery, contract / employee / insurance / compensation /
donation / card → b2b, anything else or no sale → «غير مصنف» (never guessed as home delivery).

### 5.4 Admin screen

`/settings/code-maps` «ترميزات SOFTECH», two tabs: «قنوات البيع» (every customer channel row:
code, SOFTECH label, sales in the last 90 days, group, KPI bucket, contract, follow-up rank) and
«تصنيف الأصناف» (code, label, item count, group, medicine, excluded from planning). Unclassified
rows on top with a badge. Inline edit, sortable grids, review-grid keyboard. Every change goes
to `AuditLog` (before/after). Server-side permission (RBAC module per CLAUDE.md definition of done
— the existing settings/admin module if one fits, else a new `code_maps` module), help AR + EN.

### 5.5 Guards

- `apps/tests/test_new_values.py` (parent design §8) plants a new channel pair and a new item
  category and asserts: they show as «غير مصنف», follow-ups/replacement/chronic/ISR/analytics do
  not crash and do not put them in a guessed bucket.
- Guard test: POS writer channels ⊂ registry, groups match.
- Static guard (piece 1's scanner, extended later): flags new literal `medicine_type='..'` or
  `ptclassifcode`/`sales_channel` literals outside the reader modules.

## 6. Questions for the owner (must be answered before any code)

1. **Channel table (§3):** is the SOFTECH label the true meaning for every code — in particular
   10 = contract/آجل (not "general retail"), 11 = employees, 30 = permanent?
2. **Contract set for بدل الروشتة:** add 33 «تعاقد - سداد آجل - خصم يدوي» to 10/11/15/17?
3. **Follow-up favouring** (today effectively 91, 90, 10 favoured, 30 not). Proposed:
   rank 1 = 91 cash + 90 delivery; rank 2 = 30 permanent + 99 VIP; rank 3 = 10/33 contract +
   11 employee + 12 card; rank 4 = 15 insurance, 16 donation, 17 compensation, 31 settlement.
4. **Item categories (§4):** 10 = medicine and 60 = excluded from planning — confirm; any other
   code (e.g. 70 services, 00 N A) to exclude too?
5. **POS writer:** confirm we leave `pos_orders/models.py` / `writer.py` untouched and only add the
   drift guard test (recommended).

## 7. Owner decisions (2026-11-13)

1. Yes — SOFTECH's labels are the meanings (10 contract/آجل, 11 employees, 30 permanent, …).
2. Yes — 33 joins the بدل الروشتة contract set (10, 11, 15, 17, 33).
3. Yes — follow-up rank: 1 = 91, 90; 2 = 30, 99; 3 = 10, 33, 11, 12; 4 = 15, 16, 17, 31.
4. Yes — 10 = medicine, 60 = excluded from planning; 70 and 00 stay as they are.
5. Yes — `pos_orders/models.py` and `writer.py` stay untouched; only a drift-guard test is added.

## 8. Build notes (2026-11-13)

- Readers: `apps/forecasting/channels.py` (channels, on `ChannelBucketMap`) and
  `apps/config/item_types.py` (item categories, new `MedicineTypeMap`). Now routed through them:
  follow-ups label / favoured / priority / filter list / score, بدل الروشتة contract set,
  chronic customer type, `Customer.customer_type_label` / colour, refill tasks, stock audit,
  ISR default + candidates, sales-rate writer candidates, seasonality, analytics exclusions.
- The static-scan extension that would flag new literal `medicine_type='..'` / channel-code
  filters is deferred to piece 1's scanner (`apps/tests/security/static_scan.py` is piece 1's file).
- Not changed: `apps/pos_orders/models.py` / `writer.py`; `test_code_maps_new_values.py`
  asserts every POS channel code is in the registry with the matching group.
- Screen: `/code-maps` «ترميزات SOFTECH» (admin; API `/api/config/code-maps/…`, settings
  module view/edit, audited as `code_map_changed`). At least one category must stay «دواء».
- An edit reaches the editing server at once and other server processes within 10 minutes
  (per-process reader cache).
