# 27 — Customer-code (PIC) duplicates & merge (B7)

**Status:** 🔍 INVESTIGATION (read-only) — design not yet written / approved. No SOFTECH write exists.
Probe: `python manage.py investigate_pic_merge [--suggest] [--pic A --pic B …]` (apps/customers).

## Confirmed facts (live probe 2026-10-08, HQ)

| Topic | Finding |
|---|---|
| Customer master | `localcustomers` — ONE row per PIC (197,779 rows = 197,779 codes; `branchcode` = creating branch). No triggers. `personsdata` holds no retail PICs. |
| Deactivation | `localcustomers.phcodestatus`: `'1'` active (197,759) · `'0'` = deactivated (6) · `'5'` (2, meaning unknown) · blank (12 = NOT deactivated, just unset). Companion columns `phcodestatususercode` / `phcodestatustime` (set on 1 code, 2018). `piclock`=1 on 6 codes. **Owner-confirmed:** 03HD3059 (`'0'`) is a deactivated duplicate of 06HD8958 (same name + address); 04HD1532 (blank) is a duplicate of 04HD2371 that staff simply stopped using. |
| Duplicates in practice | Almost never deactivated: 24 non-active codes vs 11,409 real shared phone numbers / 24,540 codes (pairs 9,948). Placeholder numbers (01000000000-style, > 10 codes) excluded. |
| Main-code link | `pphcode` = the code itself on all but 27 codes; those 27 point to the neighbouring code (`01HD188 → 01HD187`). Owner: data do NOT match → likely concurrent-save accidents, but the mechanism is SOFTECH's own and is examined further (probe section [13]). `relativecode` = 0 everywhere. |
| Points | Balance = `localcustomerspoints` (one row per PIC; `totpoints` earned − `conpoints` consumed), maintained only by trigger `tr_picpoints` on INSERT into the `picpoints` log. `localcustomers.picpoints` = enrollment flag 1/0. 34 balance rows have no customer row. |
| History | 189 SOFTECH tables carry a customer-code column (sales, claims, points log, patient data …) → a merge can never move history; it stays under the old code. |

## Direction (to be designed and approved before any build)
1. Candidate queue from shared phones, classified by name/address match (probe [12]) — same name ± address =
   duplicate; different names on one phone = family → never merged (link instead, see relatives tables [14]).
2. Human approval per merge (maker-checker, audited).
3. SOFTECH writes, each through a reviewed, verified, idempotent channel:
   * old code `phcodestatus='0'` + `phcodestatususercode` / `phcodestatustime` (the fields SOFTECH reserves for it);
   * points: −balance on the old code, +balance on the main code via the `picpoints` log (trigger keeps the
     balances) — reuse `apps/loyalty/pic_bridge.adjust_softech_points`;
   * `pphcode` link only after its semantics are confirmed (probe [13]).
4. Our mirror: map old → main so reports, coupons (B2) and refill reminders follow the main code.

## Open questions
* What SOFTECH does when selling on a `'0'` code (refuse / warn / allow).
* Meaning of `phcodestatus='5'`.
* `pphcode` semantics (probe [13]) and the relatives tables (probe [14]).
