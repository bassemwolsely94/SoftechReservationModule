# R8 — Frontend lint, unit tests and browser tests (2026-11-05)

Batch R8 of the round-2 test plan (`docs/security/2026-11-05-full-project-test-plan.md` §7).
Everything ran on a reader copy. The browser tests use `config/settings_e2e.py`: their own
database, the dev `.env` never read, no SOFTECH host, `SOFTECH_READ_ONLY=True`,
`WRITER_INSTANCE=False`, no outbound sends. Nothing was sent to SOFTECH and no message was sent.

## How to run

```bash
cd frontend
npm run lint          # ESLint 9 — errors fail
npm test              # Vitest 3 + jsdom
npm run test:e2e      # Playwright, Chromium (needs the e2e database, below)
```

Browser tests, once per machine (a postgres login in `E2E_PG_*`; database `elrezeiky_e2e` by default):

```bash
DJANGO_SETTINGS_MODULE=config.settings_e2e python manage.py migrate
DJANGO_SETTINGS_MODULE=config.settings_e2e python manage.py seed_e2e_users
cd frontend && E2E_PYTHON=python npx playwright test
```

Playwright starts Django on 127.0.0.1:8100 (e2e settings) and Vite on 127.0.0.1:5190
(`VITE_API_TARGET` points the Vite proxy at that Django). The e2e users (one per role) and their
test password are defined only in `config/settings_e2e.py`; `frontend/e2e/users.js` reads them
from there. `seed_e2e_users` refuses to run under any other settings module or on a writer copy.

## 1. Lint (`npm run lint`)

ESLint 9 flat config in `frontend/eslint.config.mjs`. It is `.mjs` because the package is not
`"type": "module"`, and switching that would break the CommonJS `postcss.config.js`. Plugins:
`eslint-plugin-react` (recommended, with `react/no-danger` as an error) and
`eslint-plugin-react-hooks` (`rules-of-hooks` as an error). `public/` (the vendored, minified
tesseract worker) is not linted.

**Errors: 0.** The 15 real errors in `src/` are fixed (below). **Warnings: 190**, kept as warnings,
each with its reason in the config:

| Rule | Count | Why a warning for now |
|---|---:|---|
| `no-unused-vars` | 126 | dead imports and variables, not a runtime defect |
| `react-hooks/exhaustive-deps` | 46 | many effects run once on purpose; adding every dependency blindly can start request loops, so review per screen |
| unused `eslint-disable` comments | 18 | stale suppressions (usePosOrder.js 9, DeliveryDashboard.jsx 7, ErrorBoundary.jsx 1, NewReservationPage.jsx 1); remove in a clean-up batch |

### Errors fixed (real defects)

| File | Defect | Fix |
|---|---|---|
| `pages/InvoicePage.jsx` | `setAckWarnings` is not defined. Building the SOFTECH push **preview** threw a ReferenceError after the plan was set, so every preview also showed «تعذّر بناء المعاينة» | removed the dead call (display only; no posting logic touched) |
| `pages/TransferDetailPage.jsx` | `setItemSearchText` is not defined. «إلغاء» on «إضافة صنف» threw before clearing the error | removed the dead call |
| `pages/ReferralPage.jsx` | `dangerouslySetInnerHTML` with the server's `qr_code`, which is a `data:image/png` URI, so the QR showed as text | `<img src>`: shows the QR, no raw HTML |
| `components/DataFreshnessBar.jsx` | hooks after an early return (rules of hooks) | split into `DomainFreshness` / `KpiFreshness` components |
| `pages/PurchasingPage.jsx` | `useQuery` after the role guard's early return | query moved above the guard with `enabled: !denied` (a denied user still sends no request) |
| `api/client.js` | `offersApi` declared `list/get/create/update/remove` twice (identical) | duplicates removed |
| `pages/TaskDetailPage.jsx` | element in an array without `key` | `key="status"` |
| `pages/ShortagePage.jsx`, `pages/VouchersPage.jsx` | useless regex / string escapes | removed (same behaviour) |

Two small moves made the code testable without changing behaviour:
- the side-menu data moved from `Layout.jsx` to `components/navGroups.js`, with
  `navItemVisible` (the rule Layout applies);
- `RequireAuth` / `RequireRole` moved from `App.jsx` to `components/RouteGuards.jsx`.

## 2. Unit tests (`npm test`): 87 tests in 5 files, all pass

| File | Tests | Covers |
|---|---:|---|
| `src/api/client.test.js` | 15 | cookies + `X-Requested-With`; no token ever in localStorage; URL/body building; 401 → one refresh → retry; no refresh on auth endpoints; single-flight refresh; failed refresh; legacy-token migration |
| `src/store/stores.test.js` | 14 | `authStore` (login, 2FA steps, refused login, logout wipes, loadMe) and `permissionStore` (fail-closed, matrix answers, load once, failed load → viewer + deny, reset) |
| `src/components/RouteGuards.test.jsx` | 17 | `RequireRole`, `RequireAuth`, `navItemVisible` (roles, caps, module) |
| `src/utils/formatting.test.js` | 22 | POS money, GL money/pct, supply money/qty/pct, analytics `fmt`, `toNumber` (Arabic digits, decimal comma) |
| `src/hooks/gridHooks.test.js` | 19 | `useSortableRows` (types, empties last, click cycle, default, getValue, persistence) and `useGridKeyboard` (every key, typing guard, Ctrl passthrough, fallback, rowProps) |

Mutation check: disabling the `RequireRole` refusal makes 5 guard tests fail.

Backend: `apps/tests/test_e2e_seed_guard.py` (3 tests) proves `seed_e2e_users` refuses the normal
settings and a writer copy, and that `settings_e2e.py` pins the reader-copy lines.

## 3. Browser tests (Playwright 1.64, Chromium): 23 tests, all pass locally

| Spec | Tests | What |
|---|---:|---|
| `e2e/login.setup.js` | 10 | log in through the real login screen as each role; lands on `/dashboard` (`/rider` for delivery); `/api/auth/me/` returns the role. Saves the session for the other specs: one login per role, because the login throttle is 10/min |
| `e2e/menu-api.spec.js` | 10 | per role: every side-menu item the role does not see → the API behind that screen must answer 403 |
| `e2e/flows.spec.js` | 3 | a pharmacist creates a reservation; a pharmacist requests a transfer from another branch; a pharmacist takes a POS order to **ready**. The checkout's follow-up push is blocked at the network layer, and the test checks the UI asked only for `dry_run: true` |

### Menu vs API: what the first run found (questions for the owner)

528 (role, screen) checks. 497 of them are screens hidden from the role:

- **349** answer 403. Correct.
- **125, on 45 screens, answer 200.** The menu hides the screen but the API serves the data.
  They are listed in `frontend/e2e/knownGaps.js` and in the table below. They are **owner
  questions, not decisions**: for each, either the menu should show the item to that role, or the
  API should refuse it. The spec stays green only for exactly these pairs. Any new pair fails, and
  an entry that stops applying also fails, so the list cannot go stale.
- **23 inconclusive** (404 / 503). The feature is off in the e2e settings (missed sales,
  counselling), or the screen needs data first (usage print, market shortage, recommendations).
- **4 visible but refused** (the menu shows it, the API says 403): `/demand` for salesperson,
  `/hr` for accountant, `/reconciliation` for pharmacist, `/supply` for supervisor.
- **0 crashes.**

The test plan's default for Q5 is "the matrix wins", but Q5 was about the matrix against views,
not the menu against the API, so each line below needs the owner's answer.

| Screen (menu) | Roles that do not see it but get data | Why the API answers |
|---|---|---|
| `/analytics` | call_center | the role matrix gives this role analytics:view, wider than the menu |
| `/approvals` | viewer | CanViewApprovals lets this role read pending approvals |
| `/batches` | call_center, delivery, salesperson, viewer | the role matrix gives this role catalog:view, wider than the menu |
| `/callcenter` | quality_manager, viewer | the role matrix gives this role callcenter:view, wider than the menu |
| `/callcenter/analytics` | call_center, viewer | the role matrix gives this role callcenter:view, wider than the menu |
| `/campaigns` | pharmacist, quality_manager | the role matrix gives this role campaigns:view, wider than the menu |
| `/cash-optimization` | call_center, viewer | the role matrix gives this role analytics:view, wider than the menu |
| `/catalog-intelligence` | call_center, delivery, quality_manager, salesperson, supervisor, viewer | the role matrix gives this role catalog:view, wider than the menu |
| `/chronic-classifier` | purchasing, quality_manager, salesperson, viewer | the role matrix gives this role chronic:view, wider than the menu |
| `/composition` | call_center, quality_manager, salesperson, viewer | the role matrix gives this role chronic:view, wider than the menu |
| `/delivery` | purchasing, salesperson, viewer | the role matrix gives this role delivery:view, wider than the menu |
| `/delivery/dispatch` | delivery, pharmacist, purchasing, salesperson, viewer | shares /api/delivery/ with /delivery; the API cannot tell dispatch roles apart |
| `/demand` | purchasing | the role matrix gives this role analytics:view, wider than the menu |
| `/discount-alignment` | quality_manager, supervisor, viewer | the role matrix gives this role approvals:view, wider than the menu |
| `/followups` | viewer | the role matrix gives this role followups:view, wider than the menu |
| `/followups/reminders` | pharmacist, salesperson, viewer | CanViewReminders also admits any followups:view role |
| `/forecast-scenarios` | call_center, pharmacist, quality_manager, viewer | the role matrix gives this role analytics:view, wider than the menu |
| `/forecasting` | call_center, supervisor, viewer | the role matrix gives this role analytics:view, wider than the menu |
| `/image-enrichment` | call_center, delivery, quality_manager, salesperson, supervisor, viewer | the role matrix gives this role catalog:view, wider than the menu |
| `/ingredient-search` | salesperson, viewer | the role matrix gives this role chronic:view, wider than the menu |
| `/insights` | call_center, pharmacist | the role matrix gives this role analytics:view, wider than the menu |
| `/inventory` | call_center, viewer | the role matrix gives this role analytics:view, wider than the menu |
| `/kpi-board` | call_center | the role matrix gives this role analytics:view, wider than the menu |
| `/loyalty` | delivery, purchasing, quality_manager, viewer | the API is open to every signed-in user (IsAuthenticated only) |
| `/omni/accounts` | call_center, quality_manager, viewer | the role matrix gives this role callcenter:view, wider than the menu |
| `/omni/inbox` | quality_manager, viewer | the role matrix gives this role callcenter:view, wider than the menu |
| `/payment-audit` | accountant, quality_manager | the role matrix gives this role finance:view, wider than the menu |
| `/pbx/live` | quality_manager, viewer | the role matrix gives this role callcenter:view, wider than the menu |
| `/phantom-sales` | call_center, viewer | the role matrix gives this role analytics:view, wider than the menu |
| `/pos/exceptions` | call_center, salesperson | any pos:view role (the menu and RequireRole allow admin/supervisor/pharmacist only) |
| `/pricing-approvals` | quality_manager, supervisor, viewer | the role matrix gives this role approvals:view, wider than the menu |
| `/procurement` | viewer | the role matrix gives this role purchasing:view, wider than the menu |
| `/products` | delivery | the API is open to every signed-in user (IsAuthenticated only) |
| `/reconciliation` | quality_manager | CompanyFinance admits this role (finance matrix + all-branch) |
| `/referral` | delivery, pharmacist, purchasing, quality_manager, salesperson, viewer | the API is open to every signed-in user (IsAuthenticated only) |
| `/referral-stats` | call_center, purchasing | the role matrix gives this role analytics:view, wider than the menu |
| `/settings` | accountant, call_center, delivery, purchasing, quality_manager, salesperson, supervisor, viewer | the role matrix gives this role settings:view, wider than the menu |
| `/shortage` | viewer | the role matrix gives this role shortage:view, wider than the menu |
| `/stock-count` | purchasing, viewer | the role matrix gives this role stockcount:view, wider than the menu |
| `/supply` | viewer | the role matrix gives this role purchasing:view, wider than the menu |
| `/targets` | call_center | the role matrix gives this role analytics:view, wider than the menu |
| `/tasks` | accountant, delivery, purchasing, quality_manager, salesperson, viewer | the role matrix gives this role tasks:view, wider than the menu |
| `/users` | accountant, call_center, delivery, pharmacist, purchasing, quality_manager, salesperson, viewer | the staff list is a picker open to every signed-in user (only retrieve/write are guarded) |
| `/vouchers` | viewer | the role matrix gives this role vouchers:view, wider than the menu |
| `/whatsapp/inbox` | quality_manager, viewer | the role matrix gives this role callcenter:view, wider than the menu |

## 4. CI (`.github/workflows/ci.yml`)

- `frontend-quality`: `npm ci`, `npm run lint`, `npm test`. Blocking.
- `e2e`: postgres service; `migrate` + `seed_e2e_users` under `config.settings_e2e`; Chromium;
  `npx playwright test`; the report is uploaded as an artifact. `continue-on-error: true` for its
  first week (owner decision Q4). Remove that line once the job has been green for a week.
- `npm_audit_check.cjs` stays the audit gate (frontend-build job). The new dev dependencies add no
  advisory.

## 5. Follow-ups (not done here)

- The owner's answers to the 125 menu/API pairs and the 4 visible-but-refused screens. Then align
  the menu or the API per answer and shrink `knownGaps.js`.
- Bring the 190 lint warnings down (unused code first, then `exhaustive-deps` per screen), then
  make those rules errors.
- After a green week, drop `continue-on-error` from the `e2e` job.
