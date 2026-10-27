# SOFTECH POS Discount & Authority Model (investigation)

Reverse-engineered read-only from branch 130. This is the layered discount resolution
the In-Direct POS screen applies — needed to validate a POS discount "across customer
settings, item line settings, and levels of authority" (the hard part of field fidelity).

> Status: **table map confirmed**. The exact combine/calc logic (`salesdisccalc`,
> `custdiscptype`) likely lives in encrypted procs — still to pin down. For our **clone**
> path this is moot: we copy the source line's resolved discount components verbatim.

## Where discount lives
| Layer | Table.column | Meaning |
|---|---|---|
| **Item line** | `items.posdiscp` | the POS discount baked into the item |
| | `items.pharmacydiscp`, `additionaldiscp`, `specialdiscp` | other per-item discount components |
| **Customer base** | `personsdata.custdiscp` | customer's base discount % |
| | `personsdata.contractdisctype`, `salesdisccalc` | how the contract discount is computed |
| **Discount categories** | `custdiscpclassif` (`custdiscpcode`,`custdiscpdescr`) | product discount categories: 10=Med:Local, 20=مستلزمات, 30=COSMETICS, 50=انسولين, 60=نواقص … |
| **Customer × category** | `custdiscounts` (`personcode`,`custdiscpcode` → `custdiscp`,`custdiscp2/3/4`,`custdiscptype`,`allow_sell`,`custdiscp_nomore`) | the contracted discount the customer gets **per product category**; `allow_sell`=may buy that category at all |
| **Authority ceiling** | `managerdiscount` (`personcode`,`branchcode` → `max_custdiscp`) | the **maximum discount a given user/manager may grant** at a branch — the override-authority level |
| **Lab/insurance** | `profiletestsdiscp` (`profilecode`,`testcode` → `testpricediscp`) | discount for tests/profiles |

The **line** (`stktrans`) stores the *resolved* components: `pharmacydiscp`,
`additionaldiscp`, `custdiscp`, `specialdiscp`. The **header** (`stktransm`) carries
`custdiscp`, `specialdiscp`.

## Resolution (working model — to be confirmed against the procs)
For each line on a fresh (non-clone) order:
1. Determine the item's discount **category** (`custdiscpcode`).
2. Look up the customer's `custdiscounts` row for that category → base `custdiscp`
   (+ tiers); if `allow_sell=0` → **cannot sell** that category to this customer.
3. Apply item-level components (`posdiscp`/`specialdiscp`).
4. Any discount **above** the contracted/auto value must be authorized by a user whose
   `managerdiscount.max_custdiscp` ≥ the granted % — this is the authority override.

## Validation implications (for `validators.py` / `discount_authority.py`)
- Base envelope: `0 ≤ cust_discp ≤ 100` (validators.py).
- **Authority-aware** (discount_authority.py, live read at `/ready`, `POS_DISCOUNT_AUTHORITY`
  default ON): rejects `allow_sell=0` categories and discounts above the customer's
  contracted % that exceed the seller's `max_custdiscp`. Degrades gracefully (only acts on
  resolved data; only escalates ABOVE the contracted rate ⇒ never false-rejects).
- For **clone** orders the per-line components are already correct (verbatim copy).

## Joins (RESOLVED 2026-06-23)
- **item category** = `items.itemstoreclassif` (values match the `custdiscpclassif` catalog
  — e.g. item 100038 → `10` = "Med: Local").
- **seller ceiling** = `managerdiscount.personcode` == seller `usercode` (same numbering;
  e.g. 2050 present in both). `max_custdiscp` 0 = no discount authority, 100 = full.
- **customer** = `custdiscounts` is keyed by the channel/contract customer; confirmed
  channel defaults **cash → `CashCust`, delivery → `HomeDlvry`** (looked up in
  `personsdata.personglobalcode`).

## Open follow-ups
- The individual **contract-patient PIC → contract-entity personcode** (4212+) link is not
  in the visible schema → contract/insurance lines are SKIPPED by the authority check.
  Needs the customer↔contract mapping table (or SOFTECH guidance) to extend coverage.
- Confirm the combine order of the four item discount components + `salesdisccalc`/
  `custdiscptype` (still in encrypted procs).
