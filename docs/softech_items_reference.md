# SOFTECH Items Table — Complete Reference

**Table:** `SOFTECHDB9.dbo.items`  
**Total rows:** ~51,372 (includes archived + discontinued)  
**Active rows (after sync filter):** ~37,500  
**Sync filter:** `WHERE itemnomoreuse != '1' AND itemarchive = 0`  
**Last audited:** 2026-05-25  
**Source queries:** `apps/sync/sybase_queries.py → QUERY_ITEMS`  

---

## RULE — SOFTECH IS READ-ONLY

```
ABSOLUTE RULE: SELECT ONLY on Sybase. Never INSERT / UPDATE / DELETE.
```

---

## Django Model

`apps/catalog/models.py → class Item`

---

## Column Reference (all 69 columns)

### ✅ FULLY SYNCED — in Django model

| # | SOFTECH Column | Django Field | Type | Description |
|---|---|---|---|---|
| 1 | `itemcode` | `softech_id` | varchar(6) | Primary key in SOFTECH. Unique in Django. |
| 2 | `itemname` | `name` | varchar(100) | Main item name (Arabic or English). |
| 3 | `itemname_scientific` | `name_scientific` | varchar(100) | Generic/INN scientific name. |
| 4 | `itembarcode` | `barcode` | varchar(15) | Main barcode. |
| 5 | `itemclassifcode` | `category` (FK) | varchar(5) → `itemsclassif` | Dosage form classification: Tablet, Capsule, Injectable, Cream… The `classifapply` field tells you M=Medicine / N=Non-medicine. |
| 6 | `suppcode` | `supplier_code` / `supplier_name` | varchar(8) | Main supplier. Overridden by `itemssuppliers` (main_supp='1') during sync. |
| 7 | `itemsaleprice` | `pack_price` | money | Retail price per full pack/box. |
| 8 | `unitsaleprice` | `unit_price` | money | Price per individual unit (strip, vial, ampoule). |
| 9 | `itemnomoreuse` | drives `is_active=False` | varchar(1) | '1' = discontinued. Items with this flag are excluded from sync query entirely. |
| 10 | `itemarchive` | drives `is_active=False` | int | 1 = archived. Also excluded from sync. |
| 11 | `familycode` | `family_code` / `family_name` / `family_name_ar` | varchar(5) → `itemsfamily` | Dosage form family (Syrup, Tablet, Capsule, Vial, Pre-filled Syringe, Drops…). |
| 12 | `fridgeitem` | `requires_fridge` | varchar(1) | '1' = requires cold chain / refrigeration (239 items). |
| 13 | `itemmedicine` | `medicine_type` / `medicine_type_name` / `medicine_type_name_ar` | varchar(2) → `itemstree` | **Main category.** Values: `10`=Medicine, `50`=Cosmetics, `20`=Others, `30`=Body Building, `40`=Veterinary, `70`=Services, `60`=Customer Gifts, `00`=N/A |
| 14 | `itemcomment` | `comment` | varchar(50) | Free-text comment. |
| 15 | `itemlastupdate` | not stored (sync uses `last_synced`) | datetime | Last catalog update in SOFTECH. |
| 16 | `itemcostprice` | `cost_price` | money | Current catalog cost price (updated on every stock receipt). |
| 17 | `itemproducercode` | `producer_code` / `producer_name` | varchar(5) → `itemsproducers` | Manufacturer / producer. |
| 18 | `unitcode` | `unit_code` / `unit_name` | varchar(2) → `itemsunits` | Pack sub-unit type (Strip, Vial, Ampoule, Sachet, Bottle…). |
| 19 | `itemshapecode` | `shape_code` / `shape_name` / `shape_name_ar` | varchar(5) → `itemshape` | Dosage route/form (Oral, Injectable, Topical…). |
| 20 | `itemorigincode` | `origin_code` / `origin_name` / `origin_name_ar` / `is_imported` | varchar(5) → `itemsorigin` | Country/source of origin. `importedorigin='1'` → `is_imported=True`. |
| 21 | `itemeffectcode` | `effect_code` / `effect_name` / `effect_name_ar` | varchar(5) → `itemseffect` | Primary therapeutic indication (Anti-Biotic, Anti-Hypertensive, Diabetes Treatment…). Extremely detailed—hundreds of codes. |
| 22 | `itemeffectcode2` | `effect_code2` / `effect_name2` / `effect_name2_ar` | varchar(5) → `itemseffect2` | Secondary therapeutic indication. |
| 23 | `itemtrans` | `is_stockable` | varchar(1) | **1=stockable (37,534 items), 0=non-stockable (38 items).** Non-stockable = service items, testers, delivery fees. Excluded from all demand/purchasing calculations. |
| 24 | `hi_typecode` | `insurance_type` | varchar(1) → `hi_types` | Health insurance classification: `0`=غير خاضع للتأمين (not covered, 28,667), `1`=طلبية/Talbia (8,068), `2`=TPA (47), `3`=تكافل/Takaful (9), `4`=Other (781, not in reference table). |
| 25 | `itemslevel` | `item_level` | smallint | Distribution: `0`=standard (50,338), `1`=special (1,014). **Exact meaning not yet confirmed.** Sample level=1 items: CENTRUM SILVER, ADVIL 200MG, ROGAINE, ASHWAGANDHA, BIO SOFT COCONUT — mostly imported brand-name items. NOT narcotics. TODO: confirm with business team. |
| 26 | `itempointsys` | `has_points` | int | `1`=eligible for points program (465 items). |
| 27 | `packqty` | `pack_qty` | smallint | Number of units (strips/vials/ampoules) per pack. Common values: 1(31k), 2(2.3k), 3(2k). |
| 28 | `itemtrans1` | `branch_trans` | smallint | Branch (inter-branch transfer) permissions. `0`=صرف+ارتجاع (full), `1`=صرف فقط, `2`=ارتجاع فقط, `3`=إيقاف كامل (full stop). Most items=0. |
| 29 | `itemtrans2` | `supplier_trans` | smallint | Supplier (purchasing) permissions. `0`=شراء+ارتجاع, `1`=شراء فقط, `2`=ارتجاع فقط, `3`=إيقاف كامل. |
| 30 | `itemtrans3` | `customer_trans` | smallint | Customer (sales) permissions. `0`=بيع+ارتجاع, `1`=بيع فقط, `2`=ارتجاع فقط, `3`=إيقاف كامل. |
| 31 | `itemnosaleclassif` | `nosale_classif` | varchar(5) | **تصنيف منع الصرف للتعاقدات.** Contract dispensing restriction. `10`=normal/no restriction (43,877), `20`=restriction #2 (1,255), `30`=restriction #3 (654), `31`=restriction #4 (648), NULL=unclassified (4,867). 4-digit codes (1110, 4030…) appear to be data entry errors. |
| 32 | `fmi` | `is_fast_moving` | varchar(1) | **Fast Moving Item flag.** `1`=FMI (390 items), `0`=normal. Used by purchasing/demand engine for priority handling. |
| 33 | `itemstoreclassif` | `store_classif` / `store_classif_name` | varchar(5) → `custdiscpclassif` | **تصنيف خصم التعاقدات (Contract Discount Classification).** FK → `custdiscpclassif.custdiscpcode`. Groups items into discount tiers for contract pricing. Distribution: NULL/empty=22,669, `10`=10,776, `9`=2,144 (orphaned — no reference row), `25`=408, `15`=328. Full code map in section below. |
| active ingredients | via `itemsai` junction | `active_ingredients` | text | Comma-separated active ingredient names (ainame). From `activeingredients` table via `itemsai` junction. |

---

### ❓ UNMAPPED — Confirmed field exists, meaning unclear or not yet implemented

| # | SOFTECH Column | SOFTECH Label | Status | Notes |
|---|---|---|---|---|
| 25 | `itemslevel` | **تصنيف جدول مخدرات** (Narcotics Schedule) | **UNCONFIRMED** | The SOFTECH UI label says this is the narcotics schedule. But sample items with `itemslevel=1` include CENTRUM SILVER, ADVIL, ROGAINE, ASHWAGANDHA — NOT narcotics. Either: (a) `itemslevel` is NOT the narcotics field and narcotics maps to a different column; or (b) the label in the screenshot refers to a different control entirely. Currently stored as `item_level` (neutral name). **Action: verify with business team.** |

---

### 🔴 DELIBERATELY EXCLUDED — Not worth syncing

| Column | Reason |
|---|---|
| `itemcomment` | Free-text, unstructured — synced but low value |
| `itemsearchkey` | Internal SOFTECH search index, not needed |
| `itemperformrate` | All zeros in this DB |
| `itemmodified`, `itemsort` | Internal maintenance flags |
| `print_barcode` | POS printer setting |
| `usercode` | Who entered the item in SOFTECH |
| `itemupdt_monthlyqty` | Internal update flag |
| `itempartno` | Unclear usage, low distribution |
| `itemrefcode` | Legacy reference code |
| `costcentercode`, `itemexpcode` | Accounting cost center — handled by accounting module |
| `testcode` | Unknown purpose, appears unused |
| `gtin` | All NULL in this DB (GS1 GTIN not populated) |
| `gpcclassifcode` | All NULL/empty (GPC classification not populated) |
| `taxcode`, `subtaxcode`, `etaxcodetype` | Egyptian e-invoicing tax codes — handled separately by tax module |
| `itemsaleprice2` | Duplicate alternative price |
| `itemsaleprice_extrap` | Price markup factor |
| `itemsalestax`, `itemsalestaxp`, `itemsaleprice_tax` | Tax amounts — managed at transaction level |
| `itemstoreclassif` TABLE | Per-item store mapping (not a lookup table — returned empty) |
| `itemmanuf` | Manufacturer flag, unclear usage |
| `itemonweb` | E-commerce availability (not relevant to current modules) |
| `itemcode_alt1`, `itemcode_alt2`, `itemcode_alt3` | Alternative codes (low value, inconsistent) |
| `hasdifforigin` | Multiple origins flag (221 items) — low priority |
| `hasdiffpacks` | Multiple pack sizes flag — low priority |
| `suppitemcode` | Supplier's own SKU — useful for EDI but not current scope |
| `itemglobalcode` | EAN-13 global barcode (partially populated, quality issues) |
| `pharmacydiscp`, `additionaldiscp`, `specialdiscp`, `posdiscp` | Discount %s — negative values exist (data quality issues). Consider syncing when discount management module is built. |

---

## Reference Lookup Tables

These are synced as separate Django models or used in-memory during sync.

| Table | Django Model / Usage | Description |
|---|---|---|
| `itemsclassif` | `catalog.Category` | Dosage form (Tablet, Capsule, Injectable…). `classifapply`: M=Medicine, N=Non-medicine. |
| `itemsfamily` | `item.family_code/name` fields | Dosage form sub-family (Syrup, Vial, Pre-filled Syringe…). |
| `itemsproducers` | `item.producer_code/name` | Manufacturer names. |
| `itemssuppliers` | `item.supplier_code/name` | Supplier names (main_supp='1' is authoritative). |
| `itemshape` | `item.shape_code/name` | Dosage route/shape. |
| `itemsorigin` | `item.origin_code/name`, `is_imported` | Country of origin + import flag. |
| `itemseffect` | `item.effect_code/name` | Primary therapeutic indication. |
| `itemseffect2` | `item.effect_code2/name2` | Secondary therapeutic indication. |
| `itemsunits` | `item.unit_code/name` | Pack sub-unit type (Strip, Vial, Ampoule…). |
| `activeingredients` + `itemsai` | `item.active_ingredients` | Active ingredient names via junction table. |
| `hi_types` | `item.insurance_type` (decoded in UI) | Insurance type names. Codes: 0/1/2/3. Note: code 4 (781 items) is NOT in this table. |
| `itemstree` | `item.medicine_type/name` | Main category names (Medicine, Cosmetics, Others…). |
| `custdiscpclassif` | `item.store_classif` / `item.store_classif_name` | Contract discount classification. PK=`custdiscpcode`, name=`custdiscpdescr`. FK from `items.itemstoreclassif`. 37 active codes. See code map below. |
| `contractstypes` | Not synced | Payment types for contracts (paytypecode 1-8, a-h). NOT the item discount classification. |
| `itemstoreclassif` TABLE | Not synced (empty per-item override table) | A per-item store mapping table — returns EMPTY in this deployment. It is a different concept from the `items.itemstoreclassif` column (which is the FK). |

---

## `itemmedicine` Code Map

| Code | English | Arabic |
|---|---|---|
| `10` | Medicine | دواء |
| `50` | Cosmetics | مستحضرات تجميل |
| `20` | Others | أخرى |
| `30` | Body Building | بودي بيلدينج |
| `40` | Veterinary | بيطري |
| `70` | Services | خدمات |
| `60` | Customer Gifts | هدايا عملاء |
| `00` | N/A | — |

---

## `hi_typecode` (Insurance Type) Code Map

| Code | English | Arabic | Count |
|---|---|---|---|
| `0` | Not covered | غير خاضع للتأمين | 28,667 |
| `1` | Talbia | طلبية | 8,068 |
| `2` | TPA | TPA | 47 |
| `3` | Takaful | تكافل | 9 |
| `4` | Other (not in reference table) | — | 781 |

---

## `itemtrans1/2/3` (Channel Transaction Permissions)

| Value | Branch (trans1) | Supplier (trans2) | Customer (trans3) |
|---|---|---|---|
| `0` | صرف+ارتجاع (full) | شراء+ارتجاع (full) | بيع+ارتجاع (full) |
| `1` | صرف فقط | شراء فقط | بيع فقط |
| `2` | ارتجاع فقط | ارتجاع فقط | ارتجاع فقط |
| `3` | إيقاف كامل | إيقاف كامل | إيقاف كامل |

Most active items have `0` (full operations). Value `3` is predominantly on discontinued/archived items.

---

## `itemnosaleclassif` (Contract Dispensing Restriction — تصنيف منع الصرف للتعاقدات)

| Code | Label | Count |
|---|---|---|
| `10` | Normal / No restriction | 43,877 |
| `20` | Restriction #2 | 1,255 |
| `30` | Restriction #3 | 654 |
| `31` | Restriction #4 | 648 |
| NULL | Unclassified | 4,867 |
| 4-digit codes | Data entry anomalies (e.g. 1110, 4030, 4220) | ~60 |

---

## `fmi` (Fast Moving Item)

| Value | Meaning | Count |
|---|---|---|
| `0` | Normal item | 50,962 |
| `1` | Fast Moving Item | 390 |

---

## `itemstoreclassif` → `custdiscpclassif` (Contract Discount Classification — تصنيف خصم التعاقدات)

**Reference table:** `SOFTECHDB9.dbo.custdiscpclassif`  
**Columns:** `custdiscpcode` (PK), `custdiscpdescr` (name)  
**Django fields:** `item.store_classif` (code), `item.store_classif_name` (resolved name)

### Medicine tiers

| Code | English Name | Count in items | Notes |
|---|---|---|---|
| `10` | Med: Local | 10,776 | Standard locally-manufactured medicines |
| `11` | Med: Local Under License 20% | — | Under-license local production |
| `12` | Med: Local 25% | — | Local, higher discount tier |
| `13` | Med: Imported / Egydrug 12% | — | Imported via Egyptian distributor |
| `14` | Med: Imported / Agent 15% | — | Imported via agent |
| `15` | Med: Imported / Imported 18% | 328 | Direct import |
| `16` | Med: Extemporaneous Prep. | — | Compounded/extemporaneous |
| `19` | Med:Local 20% Shortage ناقص | — | Local shortage tier |
| `25` | Med:Local 25% Shortage ناقص | 408 | Local shortage, 25% discount |
| `26` | Med:Imported 12% Shortage ناقص | — | Imported shortage |
| `27` | Med:Imported 15% Shortage ناقص | — | Imported shortage |
| `28` | Med:Imported 18% Shortage ناقص | — | Imported shortage |

### Non-medicine tiers

| Code | English Name | Count in items | Notes |
|---|---|---|---|
| `20` | Body Building supplements | — | |
| `21` | Herbals | — | Herbal products |
| `17` | Body Building | — | |
| `18` | Veterinary | — | |
| `30` | COSMETICS | — | |
| `40` | Baby food 9% | — | |
| `50` | مستلزمات (Medical Supplies) | — | |
| `60` | ورقيات (Paper/Stationery) | — | |
| `70` | أدوات (Tools/Equipment) | — | |
| `80` | أجهزة + أدوات (Devices + Tools) | — | |
| `84` | SERVICES | — | Service items |
| `85` | أجهزة تعويضية (Orthopedic Devices) | — | |
| `86` | ورقيات (Paper Products) | — | |
| `87` | Children Supplies | — | |
| `88` | Baby Formula | — | |
| `89` | Baby Care | — | |
| `90` | مستلزمات مستوردة Imported (Imported Medical Supplies) | — | |

### Other / Admin codes

| Code | Name | Notes |
|---|---|---|
| `0` | **** | Default/null placeholder |
| `81` | 1 | Admin placeholder |
| `82` | N/A | Not applicable |
| `83` | Perfumes | |
| `22` | حليب صناعي (Infant Formula) | |
| `23` | حليب طبيعي (Natural Milk) | |
| `24` | حليب مقوى (Fortified Milk) | |

### Orphaned values (in items, no reference row)

| Code | Count | Note |
|---|---|---|
| `9` | 2,144 | **No matching row in custdiscpclassif.** Legacy/orphaned value. |
| `1`, `2`, `3`, `6`, `7` | ~200 total | Legacy values without reference rows. |
| `00000` | 939 | Appears to be "unclassified / reset" — treat as empty. |
| `31`, `32` | ~46 | No reference row. |

---

## `itemslevel` (item_level) — MEANING UNCONFIRMED

| Value | Count | Sample Items |
|---|---|---|
| `0` | 50,338 | Most items |
| `1` | 1,014 | CENTRUM SILVER MEN, ADVIL 200MG, ROGAINE 2%, ASHWAGANDHA, BIO SOFT COCONUT, NEORUB GEL, NUBIT FOOD SUPPLEMENT… |

**Current status:** Stored neutrally as `item_level`. NOT narcotics (sample items are supplements, brand OTC, cosmetics). SOFTECH UI label `تصنيف جدول مخدرات` likely maps to a different column. **TODO: confirm with business team.**

---

## Django Filter Params (`_apply_item_filters`)

All filters work on any queryset with an `item` FK to `catalog.Item`. Used in purchasing, transfer recs, metrics, aggregated, and export endpoints.

| URL Param | Django Filter | Example |
|---|---|---|
| `medicine_type=10` | `item__medicine_type=10` | Show only Medicines |
| `medicine_type=50` | `item__medicine_type=50` | Show only Cosmetics |
| `supplier_code=XXX` | `item__supplier_code=XXX` | Filter by supplier |
| `family_code=XXX` | `item__family_code=XXX` | Filter by dosage family |
| `category=<id>` | `item__category_id=id` | Filter by dosage form (itemsclassif) |
| `requires_fridge=1` | `item__requires_fridge=True` | Cold chain items only |
| `is_active=1` | `item__is_active=True` | Active items only |
| `is_stockable=1` | `item__is_stockable=True` | Stockable only |
| `is_fast_moving=1` | `item__is_fast_moving=True` | FMI items only |
| `insurance_type=1` | `item__insurance_type=1` | Talbia-covered only |
| `insurance_type=0` | `item__insurance_type=0` | Not covered by insurance |
| `item_level=1` | `item__item_level=1` | Special tier items |
| `has_points=1` | `item__has_points=True` | Points-eligible items |
| `branch_trans=3` | `item__branch_trans=3` | Blocked for branch transfers |
| `supplier_trans=3` | `item__supplier_trans=3` | Blocked from purchasing |
| `customer_trans=3` | `item__customer_trans=3` | Blocked from selling to customers |
| `nosale_classif=10` | `item__nosale_classif=10` | Normal (no restriction) |
| `nosale_classif=20` | `item__nosale_classif=20` | Restriction #2 |
| `store_classif=10` | `item__store_classif=10` | Local medicines only |
| `store_classif=15` | `item__store_classif=15` | Imported medicines 18% |
| `store_classif=84` | `item__store_classif=84` | Services only |
| `store_classif=88` | `item__store_classif=88` | Baby Formula only |

---

## Sync Flow

```
SOFTECH QUERY_ITEMS (sybase_queries.py)
    ↓ 33 columns, index [0]–[32]
sync_items() in tasks.py
    ↓ bulk_create(update_conflicts=True)
catalog_item table in PostgreSQL
    ↓ read by
purchasing engine (engine.py)
    → PG_AGGREGATE_SQL filters: is_stockable=True
    → Item map: is_active=True, is_stockable=True
    → All downstream modules (Transfer Engine, Lost Sales) inherit these filters
```

---

## Known Issues / TODOs

1. **`تصنيف خصم التعاقدات` — RESOLVED ✅** — `items.itemstoreclassif` → `custdiscpclassif.custdiscpcode`. Django fields: `store_classif` (code) and `store_classif_name` (resolved name). Migration 0017 applied. Orphaned value `9` (2,144 items) has no matching reference row — stored as-is with empty `store_classif_name`.

2. **`item_level` (items.itemslevel)** — stored as raw value 0/1, exact business meaning unconfirmed. Sample items with level=1 are imported brand-name products. The SOFTECH UI label `تصنيف جدول مخدرات` visible in the same panel likely maps to a DIFFERENT column not yet identified. **TODO: confirm with business team.**

3. **`hi_typecode=4`** — 781 items have insurance_type='4' but this code is NOT in the `hi_types` reference table. Appears to be an undocumented local classification.

4. **Discount fields** (`pharmacydiscp`, `posdiscp`) — contain data quality issues (negative values, values > 100%). Consider syncing when a discount management module is built, with validation.

5. **`gtin`** — all NULL. Not currently populated in SOFTECH for this deployment.
