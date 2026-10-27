# SOFTECH Permission Model — Investigation Findings

**Date:** 2026-06-05
**Purpose:** Map the SOFTECH authorization model before inheriting it into Django.
**Status:** STUDY COMPLETE — design decisions needed before building.

---

## 1. The model (4 tables)

SOFTECH uses a fine-grained, **per-screen × per-action ACL keyed by user group**:

```
users.usergroup ──► usergroups ──► mglevels (usergroup × mitemname) ──► mitems
   (each user        (22 groups)     (5,035 permission rows,            (528 screens/
    has ONE group)                    12 action flags each)              functions)
```

### `usergroups` — the 22 user types
| col | type | meaning |
|-----|------|---------|
| `usergroup` | int (PK) | group id |
| `groupdescr` | varchar(40) | group name |
| `groupblocked` | tinyint | disabled flag |

Groups in use (id → name → # screens enabled):

| id | group | enabled screens |
|----|-------|-----------------|
| 10 | **Administrator** | 520 (full) |
| 11 | مدير الفرع (branch mgr) | 113 |
| 12 | امين مخزن (storekeeper) | 84 |
| 13 | … | 50 |
| 14 | كاشير (cashier) | 54 |
| 16 | … | 60 |
| 19 | … | 77 |
| 23 | **Accountant** | 138 |
| 24 | **Call Center** | 36 |
| 25 | … | 90 |
| 26 | **OFFERS** | 5 |
| 27 | **Internal Auditor** | 117 |
| 29 | **Multi Branch Access** | 14 |
| 30 | … | 54 |
| 31 | PIC Customer Data | 5 |

(others: 15, 17, 18, 20, 21, 22, 28 — smaller/specialized)

### `users.usergroup`
Each ERP user belongs to exactly **one** group. (We already sync `users` → `ERPUser`; the `usergroup` column is available and partly captured.)

### `mitems` — the screen / function catalog (528 rows)
| col | meaning |
|-----|---------|
| `mitemname` (PK) | screen code, e.g. `m_1002000200` |
| `mitemdescr` / `mitemedescr` | Arabic / English name |
| `mitemsys` | 2-char **system** (top-level module) |
| `mitemsubsys` | subsystem |
| `mitemorder` | menu order |

### `mglevels` — the permission matrix (5,035 rows)
One row per **(usergroup × mitemname)**, with 12 per-action flags (0/1):

| flag | action |
|------|--------|
| `mitemenable` | accessible at all |
| `mitemshow` | visible in the menu |
| `mitemretrieve` | view / query |
| `mitemsave` | create / edit |
| `mitemdatain` | data entry |
| `mitemprint` | print |
| `mitemscan` / `mitemscanedit` | scan / scan-edit |
| `mitemdata` | data access |
| `mitemmoney` | see/handle money |
| `mitemcost` | see cost prices |
| `mitembrmb` | branch / multi-branch |
| `mitemshortcut` | shortcut |
| `usercode` | who granted it |

> Example — group 10 (Administrator) has all flags = 1 on ~520 screens; group 24 (Call Center) has them mostly 0 except its 36 allowed screens.

This is a genuine enterprise ACL: **action-level**, not just module on/off.

---

## 2. The 27 SOFTECH systems (top-level modules)

| sys | screens | description (English) | likely Django counterpart |
|-----|--------:|----------------------|---------------------------|
| IM | 45 | Items Basic Data | **catalog** / pricing |
| AR | 66 | Cash Discounts, A/R Permissions | **customers** / **pricing** / vouchers |
| AP | 30 | Imports / Purchasing | **purchasing** / **invoices** |
| MB | 18 | Sales to Branch | **transfers** / **branches** |
| BC | 11 | Download Transactions MAIN→Branch | **sync** / replication |
| DR | 2 | Replication Scheduler | **sync** / replication |
| CS | 4 | Customer Care / Call Center | **callcenter** |
| DM | 10 | Delivery Task Force | **delivery** |
| ET | 31 | e-TAX | **invoices** (e-invoice) |
| GL | 12 | Chart of Accounts mapping | **finance** |
| FA | 15 | Fixed Assets | finance |
| BD | 2 | Budget | finance |
| OM | 2 | Cost Centers | finance |
| HY/HT | 36 | Payroll / Attendance | (HR — no Django module) |
| HP | 16 | Basic Data (HR) | (HR — none) |
| MD | 91 | Patients Registration | (clinic/lab — none) |
| FM | 47 | Batteries & Tires | (not pharma — none) |
| CM | 34 | (Arabic) | ? |
| SA | 23 | (Arabic) | ? |
| MI | 14 | Service Provider Statement | insurance? |
| HC | 5 | Health insurance forms | insurance |
| MS | 4 | Messages Classification | notifications? |
| AM | 6 | Activities Basic Data | ? |
| SC/SS/MF | 4 | Reports / misc | — |

**Key insight:** the overlap is **NOT 1:1.**
- Some SOFTECH systems have **no Django module** (MD patients, FM tires, HR payroll).
- Some Django modules are **platform-native with no SOFTECH equivalent** (reservations, demand, the pricing-approval workflow itself, chronic, analytics).
- So inheritance means **mapping**, not mirroring.

---

## 3. Django side (what we map INTO)

- `StaffProfile.role` — 9 roles (admin, call_center, pharmacist, salesperson, purchasing, delivery, viewer, supervisor, quality_manager).
- `ModulePermission` (module × action) with `MODULE_CHOICES` (~11 modules) and `ACTION_CHOICES` (view, create, edit, delete, approve, export).
- `ERPUser` cache already stores `user_group`.

---

## 4. Proposed inheritance design (for confirmation)

**Stage A — Mirror SOFTECH reference data (safe, read-only):**
1. Sync `usergroups` → new `ErpUserGroup` model.
2. Sync `mitems` → `ErpScreen` (with `sys`, `subsys`, names).
3. Sync `mglevels` → `ErpGroupPermission` (group × screen × 12 flags).
4. Capture `users.usergroup` on `ERPUser` (already partly there).

**Stage B — Mapping layer (the business decisions):**
5. A `SoftechModuleMap` table: **SOFTECH system (or specific screen) → Django module**, editable in admin. Seeded with the table in §2 above as defaults, then confirmed by you.
6. A flag→action map: `mitemenable/show/retrieve → view`, `mitemsave/datain → edit/create`, `mitemmoney/cost → a "see financials" gate`, etc.

**Stage C — Derive Django permissions:**
7. For each Django user linked to an ERP user → look up their `usergroup` → aggregate `mglevels` over the screens mapped to each Django module → produce effective `ModulePermission` rows (view/create/edit/approve/export) per module.
8. Re-derive on login and on a daily sync. Admin override stays possible.

**Stage D — Enforce:**
9. Backend: DRF permission classes already exist per module — feed them from the derived permissions.
10. Frontend: the sidebar/role gates already read `user.role`/module perms — extend to read derived module permissions.

---

## 5. Decisions needed from the business BEFORE building

1. **System→module mapping** — confirm/adjust the §2 table. Especially: which SOFTECH system governs **pricing approvals** (IM? AR?), **transfers** (MB? BC?), **sync/replication** (BC+DR), **insurance** (MI? HC?).
2. **Flag→action semantics** — is `mitemsave` = our `edit`+`create`, or just `edit`? Does `mitemmoney`/`mitemcost` map to a special "view costs/prices" gate (relevant to *this* pricing module)?
3. **Native modules** (reservations, demand, pricing-approvals, analytics) — these have no SOFTECH screen. Keep them governed by Django role only? Or attach them to the closest SOFTECH system (e.g. pricing-approvals ⇐ IM "Items Basic Data" + AR "Cash Discounts Permissions")?
4. **Direction of truth** — SOFTECH groups are authoritative (re-derive nightly, Django overrides are temporary), or seed-once then manage in Django?
5. **Granularity** — do you want the full 12-flag action model surfaced in Django, or collapse to our 6 actions (view/create/edit/delete/approve/export)?

---

## 6. Immediate relevance to THIS pricing module

For the pricing-approval module specifically, the natural SOFTECH governance is:
- **IM — Items Basic Data** (who may edit item master) and
- **AR — Cash Discounts Permissions** (who may change discounts),
- gated further by **`mitemmoney`/`mitemcost`** (who may see/alter financial fields).

So "who may submit a pricing request" and "who may approve" can be derived from a user's group permissions on the IM/AR screens — replacing the current hardcoded `role=='admin'` check with the real SOFTECH entitlement.
