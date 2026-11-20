# Role review — the matrix decides who sees what (design)

Owner decisions, 2026-11-20, in the role review that closes the role-UAT report's "stricter than the
matrix" item (93 frontend checks that keep out a role the matrix allows). Source: the role-check
catalogue re-scanned on main 62e3305d against the UAT copy's matrix export of 2026-11-16.

## Intent

One place decides who sees which screen: the role matrix (`seed_permissions` → `RoleModuleAccess`,
edited on the matrix screen). Today menus and screen guards carry hand-picked role lists that are
narrower than the matrix, so changing a role on the matrix screen does not do what it says.

## Decisions (owner)

1. **The matrix wins.** A menu, route guard or in-screen check that keeps out a role the matrix allows
   is changed to ask the matrix.
2. **Exception — approve and money actions** stay with admin / named managers even where the matrix is
   wider (price approval, the approvals queue on /me, force-closing a transit, purchasing admin
   actions, finance admin tabs, editing insight / recommendation rules, supplier segments, the
   purchase-expiry re-check approval). These stay as named exceptions with a written reason.
3. **Whole-module grants are kept and the screens open** (viewer: shortage, vouchers, follow-ups,
   delivery, stock count, chronic; salesperson: delivery, chronic, counselling; purchasing: delivery,
   stock count; delivery role: catalog; QM + pharmacist: campaigns; QM: chronic; supervisor + call
   center: counselling) — **except purchasing's `settings` grant, which is removed** from the matrix.
   Edits keep following each role's own create / edit grants.
4. **Branches:** supervisor, quality manager, accountant and purchasing (all-branches flag) see the
   dashboard's per-branch breakdown and may pick any branch on new reservation / demand / transfer /
   shortage / QA round, and see branch names on the reservations board.
5. **Call center** gets everything the matrix allows in call center / omni (analytics, accounts,
   automations, PBX settings).
6. **Call lists and mobile reservation cancel** follow the matrix (followups create; reservations edit),
   as on desktop.
7. **Tool screens inside a module get their own matrix modules** (below), so they are managed on the
   matrix screen too.

## New modules (decision 7)

Starting roles set by the owner module by module (2026-11-20). Admin is in every module. A module's
view grant opens its screens; data still also needs the parent module's grant on the server unless
the API is moved (column "API").

| new module | screens | parent | starts with (view) | change from today | API |
|---|---|---|---|---|---|
| `forecast` | /forecasting, /forecast-scenarios, /salesperson-board | analytics | admin, purchasing, supervisor, QM | pharmacist loses /forecasting; supervisor gains it; QM gains scenarios + the salesperson board | forecasting/* → forecast |
| `recommendations` | /recommendations | analytics | admin, call_center, pharmacist, purchasing, supervisor, QM | supervisor + QM gain | stays analytics (read-open for POS, Z-1) |
| `catalog_tools` | /catalog-intelligence, /image-enrichment, /vision-corpus | catalog | admin, purchasing, supervisor, call_center | pharmacist loses all three; supervisor gains two; call center gains | their prefixes → catalog_tools |
| `stock` | /inventory, /batches | catalog | admin, pharmacist, purchasing, QM, supervisor, call_center, salesperson | call center + salesperson gain | batches/*, inventory/* → stock |
| `loyalty` | /loyalty, /loyalty/branch, /referral | customers | admin, call_center, pharmacist, salesperson, supervisor, QM | union of today + QM | loyalty/*, referral/* → loyalty |
| `dispatch` | /delivery/dispatch | delivery | admin, call_center, QM, supervisor, pharmacist, salesperson | pharmacist + salesperson gain | dispatch actions → dispatch |
| `rider` | /rider, /rider/security, mobile rider shell | delivery | admin, delivery, supervisor, call_center | call center gains | rider endpoints → rider |
| `reconciliation` | /reconciliation | finance | admin, accountant, purchasing, QM, supervisor | supervisor gains | reconciliation/* → reconciliation |
| `access_control` | /access/networks, /access/devices, /access/zone-policy | settings | admin | none | access/* → access_control |
| `code_maps` | /code-maps | settings | admin, purchasing, supervisor | purchasing + supervisor gain | code-maps → code_maps |

`/loyalty/branch` names a role `branch` that does not exist — dead entry, dropped. "Starts with" is
the view grant; create / edit / approve rows for each new module copy the parent module's grants for
those roles (so a role that can edit catalog today can still edit in catalog_tools), never wider than
view. Edits keep their decision-2 exceptions.

## Constraints

- Backend owns the rule (CLAUDE.md 7, 9): each new module is a `MODULE_CHOICES` + `seed_permissions`
  row, mapped in `core/middleware/module_access.py`, `PERMISSION_MATRIX.md` regenerated.
- **Unseeded databases behave as today.** `seed_permissions` is not run on the VPS (flagged to the
  owner). While a new module has no rows, the server and the menus fall back to today's role list
  (the PR 197 pattern: `seeded_modules()` first). Running `seed_permissions` is a go-live step.
- The role-literal guard shrinks; every remaining literal is a decision-2 exception with a reason in
  the overblock baseline.
- Help (AR + EN) for every screen whose audience changes; `updated` bumped.
- No SOFTECH read or write changes; no money rule changes (decision 2 keeps them as they are).

## Approaches considered

- **Trim the matrix to today's menus** — rejected by the owner (decision 3 keeps the grants).
- **Keep the tool screens as code exceptions** — rejected by the owner (decision 7).
- **One module per tool screen** (~25) — more rows than the owner needs to manage; screens with the
  same purpose are grouped (10 modules).

## Left to the builder

The exact API prefixes per new module (checked against urls), and the order of batches (suggested:
1 server modules + seed + fallback; 2 menus / guards to the matrix; 3 branches + call center + create
/cancel; 4 help + catalogue regenerated).
