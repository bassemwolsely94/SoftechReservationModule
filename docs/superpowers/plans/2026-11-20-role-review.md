# Role Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The role matrix decides who sees each screen: hand-picked role lists in menus, guards and in-screen checks give way to matrix grants, and ten tool screens get their own matrix modules.

**Architecture:** Server first. Each new module is a `MODULE_CHOICES` row, a `seed_permissions` row and a data migration that inserts its `RoleModuleAccess` rows (insert only, never overwrites), so every database has them on `migrate`. Endpoints only one tool screen calls move to the new module in `module_access.required()` and in their views. Then the frontend drops role lists for `module:` checks.

**Tech Stack:** Django 5 / DRF, PostgreSQL, React + Vite, vitest, Django TestCase.

**Spec:** `docs/superpowers/specs/2026-11-20-role-review-design.md` (owner-approved 2026-11-20).

## Global Constraints

- Admin is in every new module with every action (as `seed_permissions` gives admin everything).
- A new module's starting view roles are exactly the spec's table; its other actions copy the parent module's grants for those roles, never wider than view.
- Approve and money actions keep their admin / named-manager gates (spec decision 2): price approval, approvals queue on /me, transit force-close, purchasing admin actions, finance admin tabs, insight / recommendation rule edits, supplier segments, purchase-expiry re-check approval.
- Purchasing loses `settings` (every action).
- The data migration never overwrites an existing row except purchasing `settings` (set to False).
- No SOFTECH read or write changes. No pricing / discount logic changes.
- Help (AR + EN) for every screen whose audience changes, `updated: '2026-11-20'`.
- `PERMISSION_MATRIX.md` regenerated; role-literal and overblock baselines shrink only, every remaining entry has a reason.
- Local backend / Playwright runs need the merge coordinator's clearance; CI runs the suite. Vitest + eslint + `node --test` run locally.

## Review Focus

1. A role that sees a tool screen but lacks the parent module still gets the screen's own data (moved endpoints) and a calm empty / refusal state for shared parts — test per moved endpoint.
2. A role in the parent module but not the new one is refused the moved endpoints (403), not just hidden in the menu.
3. Re-running `migrate` or `seed_permissions` after an owner edit on the matrix screen does not undo the edit (insert-only migration; `seed_permissions` behaviour unchanged).
4. Branch pickers opened for all-branch roles: creating a record for another branch passes the server's own branch check, or the picker stays closed for that form.
5. The rider shell still lands the delivery role on /rider and the mobile menu still filters.

---

### Task 1: Ten new modules on the server

**Files:**
- Modify: `apps/users/models.py` (MODULE_CHOICES), `apps/users/management/commands/seed_permissions.py` (ALL_MODULES + PERMISSIONS + purchasing settings removed)
- Create: `apps/users/migrations/00NN_role_review_modules.py` (AlterField choices + RunPython insert)
- Modify: `docs/security/PERMISSION_MATRIX.md` (regenerated), `core/middleware/module_access.py` comment only if module list is documented there
- Test: `apps/tests/security/test_role_review_modules.py`

**Interfaces:**
- Produces: modules `forecast, recommendations, catalog_tools, stock, loyalty, dispatch, rider, reconciliation, access_control, code_maps`.
- Produces: `seed_permissions.ROLE_REVIEW_MODULES: dict[str, tuple[str, frozenset[str]]]` = module → (parent, view roles); later tasks and tests read it.

- [ ] **Step 1: Write the failing tests**

```python
class RoleReviewModulesTests(TestCase):
    def test_every_new_module_is_a_choice_and_in_the_seed(self):
        for m in ('forecast', 'recommendations', 'catalog_tools', 'stock', 'loyalty', 'dispatch',
                  'rider', 'reconciliation', 'access_control', 'code_maps'):
            self.assertIn(m, dict(MODULE_CHOICES)); self.assertIn(m, ALL_MODULES)

    def test_starting_view_roles(self):   # spec table, verbatim
        expect = {'forecast': {'admin','purchasing','supervisor','quality_manager'},
                  'recommendations': {'admin','call_center','pharmacist','purchasing','supervisor','quality_manager'},
                  'catalog_tools': {'admin','purchasing','supervisor','call_center'},
                  'stock': {'admin','pharmacist','purchasing','quality_manager','supervisor','call_center','salesperson'},
                  'loyalty': {'admin','call_center','pharmacist','salesperson','supervisor','quality_manager'},
                  'dispatch': {'admin','call_center','quality_manager','supervisor','pharmacist','salesperson'},
                  'rider': {'admin','delivery','supervisor','call_center'},
                  'reconciliation': {'admin','accountant','purchasing','quality_manager','supervisor'},
                  'access_control': {'admin'},
                  'code_maps': {'admin','purchasing','supervisor'}}
        for m, roles in expect.items():
            self.assertEqual({r for r in ROLES if 'view' in PERMISSIONS[r].get(m, set())}, roles, m)

    def test_other_actions_copy_the_parent_never_wider_than_view(self): ...
        # for each module, role: actions - {'view'} ⊆ PERMISSIONS[role][parent]; empty when no view
    def test_purchasing_has_no_settings(self): self.assertFalse(PERMISSIONS['purchasing'].get('settings'))
    def test_migration_inserts_rows_and_keeps_an_edit(self): ...
        # migrate state: rows exist for every (role, new module, action); flip one row, run the
        # RunPython function again, row keeps the flip.
```

- [ ] **Step 2: Run, watch it fail** — CI or cleared local run: `python manage.py test apps.tests.security.test_role_review_modules`. Expected: FAIL (modules missing).
- [ ] **Step 3: Implement.** `ROLE_REVIEW_MODULES` in `seed_permissions.py` builds the rows after `PERMISSIONS` (same pattern as `RPA_GRANTS`): view for the listed roles, plus `PERMISSIONS[role][parent] - {'view'}` for them. The migration freezes its own literal copy of the resulting dict (migrations never import app code) and uses `get_or_create(defaults=...)`; it sets purchasing `settings` rows to False. Regenerate `PERMISSION_MATRIX.md` with the existing generator.
- [ ] **Step 4: Run tests + `makemigrations --check`.** Expected: PASS, no new migration.
- [ ] **Step 5: Commit** `feat(rbac): ten tool modules from the role review (matrix rows, no screen change yet)`.

### Task 2: Moved endpoints ask the new modules

**Files:**
- Modify: `core/middleware/module_access.py` (`required()` special rules), `apps/images/views.py`, `apps/vision/views.py`, `apps/referral/views.py`, `apps/access/views.py`, `apps/config/code_maps.py`, `apps/finance/recon_views.py`, `apps/forecasting/views.py`, `apps/analytics/views.py` (inventory views only), `apps/delivery/` rider app views
- Test: `apps/tests/security/test_role_review_endpoints.py`

**Interfaces:**
- Consumes: Task 1 modules.
- Moved (exclusive to one screen, from the API map): `images/*`, `vision/*` → catalog_tools; `analytics/inventory*` → stock; `referral/*` → loyalty; `delivery/app/*` → rider; `finance/reconciliation/*` → reconciliation; `access/{networks,devices,zone-policies}` → access_control; `config/code-maps/*` → code_maps; `forecasting/{runs,seasonality,accuracy,salesperson-board}` → forecast.
- Stay on the parent (shared prefixes): `forecasting/scenarios`, `incentives/targets`, `recommendations`, `enrichment`, `items/bundles`, `loyalty/*`, `delivery/` list + dispatch, `batches/*`. Ruling: the new module gates the screen there; the data keeps its parent grant. A role in the new module without the parent sees the screen with a refusal note on those parts (Review Focus 1).

- [ ] **Step 1: Failing tests** — per moved path, with `seed_code_matrix()` and `RBAC_ENFORCEMENT='enforce'`: a role with the new module and without the parent gets non-403 (e.g. call_center on `GET /api/images/jobs/`); a role with the parent and without the new module gets 403 (e.g. pharmacist on `GET /api/images/jobs/`); `access/*` refuses supervisor and admits admin; `access/whoami` stays open.
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement** — special rules in `required()` before the prefix lookup (same style as the `transfers/analytics` rule, PR 186); in each view swap the parent module for the new one (`matrix_permission('catalog_tools', ...)`, etc.); `IsAdminRole` on the access viewsets becomes `matrix_permission('access_control')`; the vision inline role list goes (its audience is now the module). Keep write actions mapped to the same action names as before.
- [ ] **Step 4: Run tests + `apps.tests.security` sweeps (serial).** Overblock baseline: drop stale lines; any new line needs a reason.
- [ ] **Step 5: Commit** `feat(rbac): tool-screen endpoints ask their own modules`.

### Task 3: Menus and screen guards follow the matrix

**Files:**
- Modify: `frontend/src/components/navGroups.js`, `frontend/src/App.jsx` (routes + MOBILE_TABS), the in-screen checks listed in the catalogue for decisions 3/5/6 (`CallListsPanel.jsx`, `MobileReservationDetailPage.jsx`, `PbxLivePage.jsx`, `VouchersPage.jsx` coupons tab, `CallCenterPage.jsx` omni links)
- Modify: `apps/tests/security/baselines/role_literals_js.txt` (shrinks)
- Test: `frontend/src/components/RouteGuards.test.jsx` (+ cases), `frontend/src/components/navGroups.test.js` (create if absent)

**Interfaces:**
- Consumes: Task 1 module names.
- Rule: every menu item / route in the catalogue's stricter list becomes `roles: null, module: <its module>` (new module for the ten tool screens, parent otherwise). Decision-2 items keep their role list and get a reason comment.

- [ ] **Step 1: Failing vitest** — `navItemVisible({to:'/vision-corpus', roles:null, module:'catalog_tools'}, {role:'call_center', perms:{catalog_tools:{view:true}}})` is true; with `perms:{catalog:{view:true}}` only, false. Same shape for `/shortage` with viewer + `shortage.view`, `/settings` with purchasing and no settings grant (false), `/delivery/dispatch` with salesperson + `dispatch.view` (true).
- [ ] **Step 2: Run** `npx vitest run src/components` — FAIL.
- [ ] **Step 3: Implement** the item / route changes; drop `'branch'` from `/loyalty/branch`.
- [ ] **Step 4: Run** vitest + eslint + `npm run build`; role-literal guard baseline regenerated (count only goes down).
- [ ] **Step 5: Commit** `feat(nav): menus and guards follow the matrix (role review)`.

### Task 4: Branches, call center, create / cancel

**Files:**
- Modify: `DashboardPage.jsx:687`, `DemandPage.jsx:551`, `NewReservationPage.jsx:232`, `MobileNewDemandPage.jsx`, `MobileNewReservationPage.jsx`, `MobileNewShortagePage.jsx`, `MobileNewTransferPage.jsx`, `MobileQAPage.jsx`, `ReservationsKanban.jsx:343`; `PbxLivePage.jsx:206`; `CallListsPanel.jsx:12,186`; `MobileReservationDetailPage.jsx:33,108`
- Test: vitest per changed predicate; backend test `apps/tests/test_role_review_branches.py`

- [ ] **Step 1: Failing tests** — backend: a supervisor / QM / accountant / purchasing with `access_all` creating a reservation, demand, transfer request and shortage line for branch B (not home) gets 201 (or the server's documented refusal, which then keeps that picker closed — Review Focus 4); frontend: the shared predicate `canPickAnyBranch(user)` = `user.role === 'admin' || user.access_all`.
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement** — one helper `canPickAnyBranch` in `frontend/src/utils/branchAccess.js` used by every picker; PBX config and call lists use `usePermission('callcenter','edit')` / `usePermission('followups','create')`; mobile cancel uses `usePermission('reservations','edit')`.
- [ ] **Step 4: Run** vitest + eslint; backend test in CI.
- [ ] **Step 5: Commit** `feat(rbac): branches, call center and create/cancel follow the matrix`.

### Task 5: Exceptions, help, catalogue, report

**Files:**
- Modify: decision-2 sites (`PricingApprovalsPage.jsx:472`, `MyDashboardPage.jsx:85`, `InTransitTab.jsx:235,1181`, `PurchasingDashboard.jsx:1480`, `FinanceHubPage.jsx:59`, `InsightsPage.jsx:123`, `RecommendationsPage.jsx:102`, `SupplierSegmentationPage.jsx:96`, `BatchesPage.jsx:1254`) — reason comment `// role review decision 2: <why>` only
- Modify: `apps/help/content/*.py` for every screen whose audience changed (AR + EN, `updated`, `change_note`)
- Modify: `docs/uat/role-checks-catalogue.md` (regenerated), `docs/uat/2026-11-role-uat-report.md` (D4 / stricter item closed with the decisions)
- Test: `apps/tests/test_help.py` (existing) passes

- [ ] **Step 1:** Regenerate the catalogue with the static scan (no browser): expect stricter = only decision-2 rows, looser = 0 real.
- [ ] **Step 2:** Help entries; `node --test`, vitest, eslint, `py_compile`.
- [ ] **Step 3: Commit** `docs(role-review): exceptions, help, catalogue`.

## Go-live note (for the coordinator)

`migrate` on the office and the VPS inserts the ten modules' rows and removes purchasing's settings grant. It changes who sees screens (spec table), so it ships after the owner has seen the PR. No `seed_permissions` run is needed for these modules; the general "VPS never ran `seed_permissions`" item stays open.
