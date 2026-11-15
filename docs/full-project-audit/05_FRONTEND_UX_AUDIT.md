# 05 — Frontend audit (React / UX), commit 56870174

Scope: `frontend/` in the `full-audit` worktree, read only. Paths below are relative to `frontend/src/`
unless they start with `apps/` (backend). Static review with Grep/Read, plus:

- `vite build` run once from the main checkout (same commit; the worktree has no node_modules) with
  `--outDir` set to the scratchpad. The build passed in 24.9 s.
- `eslint src -f json` run from the main checkout against the worktree source: **0 errors / 188 warnings**
  (124 no-unused-vars, 46 react-hooks/exhaustive-deps, 18 unused disable comments).
- A script checked every literal `api.<verb>('/…')` path (1,600 of them) against the backend's `urls*.py`
  files and `@action` url_paths. **No missing endpoints were found.** The check works on path segments, so
  it is coarse: it catches typos and removed routes, not a wrong HTTP method.

What is solid (no finding): auth uses httpOnly cookies plus `X-Requested-With` (no token in page script),
with a single-flight refresh and a one-time migration away from old localStorage tokens (`api/client.js:6-65`).
Error boundaries sit at app level and page level and detect stale chunks (`components/ErrorBoundary.jsx`).
Every page is lazy-loaded (`App.jsx:11-216`). The route guards say in their own comments that the server is
the real gate (`components/RouteGuards.jsx:5`). Every `setInterval` has a matching `clearInterval`, and the
WebSocket hooks close on unmount. There are no TODO/"coming soon" controls and no empty or console-only
`onClick` handlers. The POS has broad keyboard coverage (`hooks/usePosHotkeys.js`).

Severity counts: **P0 0 · P1 2 · P2 10 · P3 15** (27 findings). Compared with
`docs/security/2026-11-05-r8-frontend-report.md` (R8): 2 findings are KNOWN (FE-20, FE-21) and 25 are NEW.

---

## Findings

### FE-1 · P1 · The offline queue replays one user's writes under whoever is signed in next, and the server ignores its idempotency key — NEW
- **Evidence:** `api/offlineQueue.js:134-147`: `enqueue({ method: 'post', url, body, label })`. Nothing
  records the user. At `:166-171`, `api.request({... headers: { 'X-Idempotency-Key': item.id } })` replays
  each item with the current cookie, and `:200` flushes on every app load. A grep of `apps/` and `core/`
  for `IDEMPOTENCY_KEY` / `X-Idempotency` finds no handler (only counselling has its own body field). At
  `:179`, 5xx responses are retried. Callers are `/m` reservation, demand, shortage add-item and
  bulk-import, stock-count `count-item`, and daily count (`pages/mobile/*:57-146`).
- **Impact:** Staff phones are shared. User A captures items offline and user B signs in later. B's session
  posts A's reservations, demand, shortage lines and stock counts, so the audit trail names the wrong person
  (`apply_single_count(..., by=profile)`), which breaks rule 8. A 502 or timeout after the server committed
  the write causes a duplicate on retry. The file's own header calls this an "accepted" risk, but the
  cross-user part is not mentioned there.
- **Status:** VERIFIED (code path). **Fix:** store `user_id` on each item and flush only items that belong to
  the signed-in user (park the rest and show them). Honour `X-Idempotency-Key` server-side with a small
  key→response table for these 6 endpoints. Treat 5xx as "unknown": check before retrying.
  **Test:** a Vitest test with fake-indexeddb: enqueue as user 1, change the user, flush → no request is
  sent. A Django test: the same key posted twice gives 1 row.

### FE-2 · P1 · Extra reservation lines that fail to save are dropped silently — NEW
- **Evidence:** `pages/NewReservationPage.jsx:397-409`. The header is created first, then each extra line is
  saved in its own request: `for (const line of extraLines) { try { await linesApi.addLine(...) } catch { /* non-fatal */ } }`.
  The page then navigates to the detail page anyway (`:415`).
- **Impact:** The customer's reservation is saved without some of the items they asked for, and nobody is
  told. Staff see "saved" and the missing items are never sourced.
- **Status:** VERIFIED. **Fix:** send `lines[]` in the create payload and create them atomically on the
  server (the serializer already has a lines endpoint). Short-term alternative: collect the failures and show
  them on the detail page. **Test:** mock `addLine` to reject → expect a visible error and no silent navigate.

### FE-3 · P2 · POS checkout is run by the browser in 4 separate requests, and the browser computes money — NEW
- **Evidence:** `hooks/usePosOrder.js:1488-1621` runs four requests in a row: `POST /pos-orders/`, then
  `/offers/apply-to-order/ {commit:true}` (errors swallowed), then `/ready/` with tenders that the browser
  rebalanced via `rebalanceToNet` (`:177-190`, `:1576-1586`; it sums line totals itself as `freshNet`), then
  `/push/`. The displayed totals are computed in the browser with float maths and `toFixed` (`:550-580`).
  Nothing tests `usePosOrder` (none of the 10 Vitest files covers it).
- **Impact:** Rule 7 says the backend owns business rules. A failure between steps leaves the order half
  done (created or ready, offer already committed). The server's strict balance check (`apps/pos_orders/views.py:300-306`)
  prevents a wrong posting, so the realistic harm is a confusing rejection or a total that differs by a
  piaster from what the server computes. It is not a double post.
- **Status:** VERIFIED (flow); SUSPECTED (rounding drift). **Fix:** one server endpoint, `checkout`, that
  creates, applies offers, prepares and pushes in one transaction and returns the authoritative totals. The
  browser shows the server's `totals` from a preview call. This touches checkout, so it needs the owner's
  approval first (CLAUDE.md "stop and ask"). **Test:** a backend test that a failure in step 3 rolls back
  steps 1–2; a Vitest test that `rebalanceToNet` is removed or matches the server on 1.005-type values.

### FE-4 · P2 · 140 calls to `invalidateQueries(['key'])` refetch every active query (TanStack v5) — NEW
- **Evidence:** The installed version is @tanstack/react-query 5.100.5. `query-core/build/modern/utils.js:21-35`:
  `matchQuery` reads `filters.queryKey`, and an array argument has no `.queryKey`, so every query matches.
  The repo has 140 such calls, e.g. `pages/NewTransferPage.jsx:85` `qc.invalidateQueries(['transfers'])`
  and `pages/PickZonesPage.jsx:135`.
- **Impact:** Every save marks the whole cache stale and refetches every query that is on screen: the Layout
  notification polls, freshness bars, and heavy dashboards backed by SOFTECH data. That is extra load on the
  server and visible flicker after each action.
- **Status:** VERIFIED (library source). **Fix:** a codemod to `invalidateQueries({ queryKey: [...] })`, plus
  an ESLint `no-restricted-syntax` rule that bans an array or string as the first argument. **Test:** a
  Vitest test with two cached queries where invalidating one leaves the other fresh.

### FE-5 · P2 · `keepPreviousData: true` does nothing in v5 (21 places, including the POS item search) — NEW
- **Evidence:** `components/ItemSearchWidget.jsx:248`, `AdvancedItemSearchModal.jsx:189`,
  `PurchasingDashboard.jsx:463/573/762`, `ProductCatalogPage.jsx:652`, `DiscountAlignmentPage.jsx:146`, and
  14 more. TanStack v5 removed this option (it is now `placeholderData: keepPreviousData`). The widget's own
  comment at `:274-277` assumes the old rows stay on screen and reads `isPlaceholderData`, which can never be
  true.
- **Impact:** At the POS search and on the big paged grids, the list empties to "loading" or "no results" on
  every keystroke and every page change. The Enter-on-stale guard still holds, because it also checks
  `isFetching`.
- **Status:** VERIFIED. **Fix:** `placeholderData: keepPreviousData`, plus a lint rule. **Test:** a widget
  test where a second query keeps the first query's rows while it fetches.

### FE-6 · P2 · The call-quality score modal never loads the existing score; saving overwrites it with zeros — NEW
- **Evidence:** `pages/CallCenterAnalyticsPage.jsx:137-147` passes `useQuery({ ..., onSuccess: q => { setScores(...); setNotes(...) } })`.
  v5 removed `onSuccess` from `useQuery`.
- **Impact:** A supervisor who reopens a call that already has a score sees 0/0/0/0. Saving then wipes the
  earlier score. This damages the QA history.
- **Status:** VERIFIED. **Fix:** `useEffect(() => { if (existing) {...} }, [existing])`. **Test:** render with
  a mocked existing score → the inputs are prefilled.

### FE-7 · P2 · 82 screens with queries have no error state, so 403/500 looks like "no data" — NEW
- **Evidence:** 210 page files use `useQuery`; 82 of them never read `isError`/`error`. Examples:
  `pages/AuditPage.jsx:177-184` (a failure shows «لا توجد سجلات») and `pages/DispatchBoard.jsx:24,72` (no
  loading or error handling at all: «لا توجد طلبات بانتظار سائق» while loading and on 403/500). No global
  `QueryCache({ onError })` is set (`App.jsx:219-221`).
- **Impact:** A dispatcher or auditor reads "nothing pending" while the API is actually down or refusing,
  and acts on that false picture.
- **Status:** VERIFIED. **Fix:** a global `QueryCache.onError` toast (with the status text from the server's
  public error), plus a shared `<QueryState q={…}>` wrapper for the loading/empty/error trio. **Test:** an RTL
  test of the wrapper; a Playwright test that routes `/api/delivery/**` to 500 and expects an error banner.

### FE-8 · P2 · The POS preview returns raw SOFTECH SQL to every cashier and shows it — NEW
- **Evidence:** `apps/pos_orders/writer.py:738` puts `'sql': sql` in the plan. `apps/pos_orders/views.py:281`
  documents that the dry-run "returns the payload + exact SQL". `pages/POSOrderPage.jsx` (PlanModal, about
  lines 176-185) shows a «عرض SQL» toggle to anyone with `CanPushPosOrders`.
- **Impact:** This exposes ERP table and column names to counter staff and adds clutter to a common screen.
- **Status:** VERIFIED. **Fix:** strip `sql` unless the user is admin, or put it behind a debug flag on the
  server. **Test:** an API test that a pharmacist's dry-run response has no `sql` key.

### FE-9 · P2 · Native browser dialogs used throughout: about 100 `confirm`, 100 `alert` and 6 `prompt` (rule 11) — NEW
- **Evidence:** Counted by grep: `window.confirm`/`confirm(` 100, `alert(` 102, `prompt(` 6. A `ToastProvider`
  exists (`main.jsx:5`), so these are inconsistent with it. On the most frequent action, every live POS sale
  shows a blocking dialog: `hooks/usePosOrder.js:1493` `window.confirm('سيتم إرسال أمر بيع فعلي…')`.
  Free-text reasons are collected with `prompt()`: `InsuranceClaimDetailPage.jsx:258,1862,5189`,
  `PhantomSalesPage.jsx:51`, `DemandDetailPage.jsx:744`.
- **Impact:** Each sale costs an extra keypress and a focus jump. Native dialogs cannot be styled, block the
  tab, and their text appears in the OS language and direction.
- **Status:** VERIFIED. **Fix:** an inline "press F10 again to confirm" (two-stage key) for POS. A small
  shared `useConfirm()` that renders an inline bar. Replace `alert` with toasts. **Test:** a POS hotkey test:
  F10 F10 → one push and no `window.confirm` call.

### FE-10 · P2 · The approvals inbox has no keyboard support and no bulk action; each decision opens a modal — NEW
- **Evidence:** `pages/ApprovalsPage.jsx:182` `onClick={() => setSelected(req)}` opens `DecideModal`
  (`:35-90`), where the user picks approve/reject and then confirms. The page has no `useGridKeyboard` and
  no multi-select. 30 files use `useGridKeyboard`; this one does not, although the project convention
  (memory "Review Grid Keyboard") calls for it on every approve grid.
- **Impact:** A supervisor clearing 30 approvals needs about 90 clicks and 30 modals.
- **Status:** VERIFIED. **Fix:** add `useGridKeyboard` (↑↓, Space, Ctrl+A), an inline approve/reject
  bar with an optional note, and bulk approve. Keep the server's per-step eligibility check. **Test:** extend
  `gridHooks.test.js`, plus a Playwright test that bulk-approves 3 items.

### FE-11 · P2 · A transfer request is saved as a draft by default; "save and send" is 2 separate calls, so a retry creates a duplicate — NEW
- **Evidence:** `pages/NewTransferPage.jsx:31` `useState(false)` for `submitAndSend`. At `:82-84`,
  `transfersApi.create(...)` is followed by `if (submitAndSend) await transfersApi.submit(newId)`. If
  submit fails, the error is shown but the draft already exists, and pressing «حفظ» again creates a second
  one. After a scan, the quantity field is not focused (`:206`, no autoFocus).
- **Impact:** Most requests are meant to be sent. The default adds a second visit (open draft → submit), and
  forgotten drafts block stock.
- **Status:** VERIFIED. **Fix:** default to "send", with `?submit=1` handled atomically on the server; focus
  the quantity after the item is added; Enter goes back to the search. **Test:** a Playwright test where the
  transfer reaches `pending` in one action.

### FE-12 · P2 · When the session expires, the page hard-reloads to /login, loses work in progress, and does not return afterwards — NEW
- **Evidence:** `api/client.js:59-62` sets `window.location.href = '/login'` after the refresh fails.
  `RouteGuards.jsx:17` uses `<Navigate to="/login">` with no `state.from`. `pages/LoginPage.jsx:35` sends
  the user to `targetAfterAuth(role)`, which is always the home page for that role.
- **Impact:** A cashier's unparked POS basket, a half-filled reservation, or a claim being edited is lost,
  and after signing in again the user lands on the dashboard instead of the screen they were on.
- **Status:** VERIFIED. **Fix:** an in-app re-login overlay that keeps React state, or at minimum
  `?next=<path>` plus an auto-park of the POS basket before redirecting. **Test:** a client.test.js case
  where a failed refresh sends to `/login?next=/pos`.

### FE-13 · P3 · No 404 route, and RequireRole redirects silently — NEW
- **Evidence:** `App.jsx` has no `path="*"`. An unknown URL under `/` renders the Layout with an empty
  outlet. `RouteGuards.jsx:22` sends the user to `<Navigate to="/dashboard" replace />` with no message.
- **Impact:** Old bookmarks show a blank page. A user sent through a deep link from a notification lands on
  the dashboard without knowing why.
- **Fix:** add a `*` route with a "page not found" screen, and make RequireRole show a "not allowed — ask
  your manager" panel. **Test:** RouteGuards.test for both cases.

### FE-14 · P3 · Dead code: 10 orphan files (about 3,300 lines) and 1 route nothing links to — NEW
- **Evidence:** Not imported anywhere: `pages/PurchasingPage.jsx` (881 lines; R8 fixed a hook bug in this
  dead file), `pages/UsersPage.jsx` (441), `pages/CashFlowPage.jsx` (171), `pages/CashFlowRetired.jsx`,
  `components/ReceiptPrint.jsx` (534), `ChatterBox.jsx` (360), `CustomerLocationsPanel.jsx` (316),
  `ActivityLogPanel.jsx`, `CustomerTagsPanel.jsx`, `MultiItemPicker.jsx`. The route `delivery/analytics`
  (`App.jsx:382`) has no link in the menu, the command palette or any page.
- **Fix:** delete the files (git keeps the history); link or drop `/delivery/analytics`. **Test:** a
  `knip`/`unimported` step in CI.

### FE-15 · P3 · Logout runs `localStorage.clear()`: parked baskets, favourites and preferences are wiped — NEW
- **Evidence:** `store/authStore.js:31`. POS keeps `pos_parked` and `pos_favorites` in localStorage
  (`hooks/usePosOrder.js:280-281`). So does the language/theme preference (`store/langStore.js`), even though
  the comment in `loadMe` says "keep the UI prefs".
- **Impact:** Held baskets disappear at a shift change. On the other side, if a session simply expires
  without a logout, the next cashier sees the previous cashier's parked baskets, which include customer
  names.
- **Fix:** key the POS data by user, and on logout remove only keys with the user's prefix.

### FE-16 · P3 · Two numeral systems on screen — NEW
- **Evidence:** `<html lang="ar-u-nu-latn">` (`store/langStore.js:22`) means Latin digits, but 40 call sites
  use `toLocaleString('ar-EG')`, which gives Eastern digits (٣٢): HRPage ×7, HRPrint ×6, SupplyPage ×5,
  PaymentAuditPage ×4, InsuranceClaimDetail ×4. 239 sites use `en`/default.
- **Fix:** one `fmtNum`/`fmtDate` helper (there is already `utils/formatting`) with `ar-EG-u-nu-latn`.

### FE-17 · P3 · The English/LTR mode cannot work, and some arrows point the wrong way in RTL — NEW
- **Evidence:** 424 hard-coded `dir="rtl"`. 1,747 physical classes (`ml-/mr-/pl-/pr-/left-/right-/text-left`)
  against 210 logical ones. `SettingsPage.jsx:177` and `InsightsPage.jsx:512` still offer `setLang('en')`.
  The "back" buttons use `←` (`NewReservationPage.jsx:513`, `NewTransferPage.jsx:113`), which points forward
  in RTL. The project already has `utils/flowArrow`.
- **Fix:** either remove the English switch, or migrate to logical classes (`ms-/me-/start-`) and drop
  page-level `dir`. Use `fa()/ba()` for arrows.

### FE-18 · P3 · Accessibility basics — NEW
- **Evidence:** 1,333 `<input>` and 392 `<select>` against 5 `htmlFor` and 56 `aria-label`. Most `<label>`s
  are siblings of their field, not linked to it. 116 `fixed inset-0` overlays but only 1 `role="dialog"`,
  with no focus trap or focus return. The POS PlanModal has no Escape handling while the POS hotkeys are
  muted (`POSOrderPage.jsx:61`), so a keyboard-only cashier must use the mouse. 165 clickable
  `div/span/tr/td`. Status badges do pair colour with text (OK).
- **Fix:** a shared `<Modal>` (role=dialog, aria-modal, Esc, focus trap, focus return); `<Field label>` that
  sets the id. **Test:** add an axe-core pass to the Playwright flows.

### FE-19 · P3 · The entry chunk is 715 kB (209 kB gzip) — NEW
- **Evidence:** See the bundle table. `components/Layout.jsx:13-23` statically imports CustomerDrawer,
  DrugAssistantDrawer, CommandPalette, HelpPanel/HelpButton and date-fns `ar`. `api/client.js` (3,347
  lines) is in the entry chunk too.
- **Fix:** lazy-load the drawers, the palette and the help panel on first open; split `api/client.js` per
  domain.

### FE-20 · P3 · Literal role lists in the frontend drift from the server's permission matrix — KNOWN (R8 menu/API table), partly NEW
- **Evidence:** `App.jsx:447-604` has 20 `RequireRole roles=[...]` literals, and `components/navGroups.js`
  has about 95 items with role arrays. `/loyalty/branch` lists role `'branch'`, which does not exist in
  `apps/users/roles.py` (the roles are admin, call_center, pharmacist, salesperson, purchasing, delivery,
  viewer, supervisor, quality_manager, accountant) — that part is NEW. Under CLAUDE.md rule 8, literal role
  lists are tracked by the role_literals baseline.
- **Fix:** drive guards and the menu from `usePermission(module)` (the matrix) rather than role names.

### FE-21 · P3 · Lint warnings: 46 exhaustive-deps, 124 unused vars, 18 stale disables — KNOWN (R8: 190 → 188 now)
- **Notable:** `ItemSearchWidget.jsx:250` `results = found?.rows || []` creates a new array every render,
  so the scroll effect at `:334` runs on every render of the POS search. `usePosHotkeys.js:100` rebinds the
  window keydown handler whenever P changes. `InsuranceClaimDetailPage.jsx:4710` is missing 4 loaders.
- **Fix:** as in R8. Memoise `results` with `useMemo`.

### FE-22 · P3 · Fetches started in effects are not cancelled, so a late response can overwrite a newer one — NEW, SUSPECTED
- **Evidence:** Only 8 files use `AbortController`/`signal` or an `alive` flag. Many filter screens do
  `useEffect(() => { api.get(...).then(setRows) })`, e.g. `InsuranceClaimDetailPage.jsx:900,1035,3198`
  (`load()`) and `InsuranceClientsPage.jsx:203`.
- **Fix:** move these to `useQuery` (keyed by the filters), or guard with an `alive` flag.

### FE-23 · P3 · The reservation create page logs the full 400 response body to the browser console — NEW
- **Evidence:** `pages/NewReservationPage.jsx:432` `console.error('[NewReservation] 400 body:', errData)`.
  The body can echo the contact phone. Rule 4 of the security definition of done requires no phone numbers
  in logs.
- **Fix:** remove it, or log only the field names.

### FE-24 · P3 · Large lists are rendered without virtualization — NEW, SUSPECTED
- **Evidence:** `DiscountAlignmentPage.jsx:144` `limit: 3000`. GL accounts `page_size: 2000` in 7 places
  (`finance/gl/*`). `InsuranceClaimDetailPage.jsx` (5,320 lines) renders whole claims. There is no
  virtualization library in `package.json`.
- **Fix:** `@tanstack/react-virtual` for grids above about 500 rows.

### FE-25 · P3 · 25 files render tables without the sortable-grid helpers — NEW
- **Evidence:** No `SortTh`/`useSortableRows`/`useServerSort`/`DataTable` in, among others,
  `POSOrderPage.jsx`, `PermissionsMatrixPage.jsx`, `ProfitLossPage.jsx`, `KpiBoardPage.jsx`,
  `SalespersonBoardPage.jsx`, `ProductCatalogPage.jsx`, `InsuranceSeparationListsPage.jsx`,
  `supply/OrderPanel.jsx`, `taxinvoicing/ReconSection.jsx`, `finance/gl/StatementsPage.jsx`. Some, such as
  the POS lines and print layouts, are fine as they are.
- **Fix:** add sorting to the report grids (KPI board, salesperson board, separation lists, order panel).

### FE-26 · P3 · The customer-portal token is stored in localStorage — NEW
- **Evidence:** `portal/portalApi.js:13-18`. Unlike the staff session, any XSS on the origin can read it.
- **Fix:** an httpOnly cookie scoped to `/api/portal`, the same pattern as staff auth.

### FE-27 · P3 · Common create actions open modals (rule 11) — NEW
- **Evidence:** Demand capture uses `CreateDemandModal` (`pages/DemandPage.jsx:143,797`). Shortage list
  creation uses `CreateModal` (`ShortagePage.jsx:1691,1811`). The reservation duplicate warning is also a
  modal (`NewReservationPage.jsx:459`).
- **Fix:** an inline drawer or inline row form, and an inline duplicate banner with «إنشاء على أي حال».

---

## UX workflow table

How the numbers were counted: by reading the handlers and the hotkeys in code, assuming a typical case of a
walk-in customer, an item found by typing 4 characters or scanning, and Enter to pick. A "key" is one
keypress; typed text counts as its characters. These are estimates, not timed measurements.

| Workflow | Current clicks/keys (estimate) | Friction | Proposed reduction | Effort (h) |
|---|---|---|---|---|
| POS cash sale, 3 items (`/pos`) | Per item: 4 chars + Enter + qty (1–2) + F2 back to search ≈ 8 keys → 24. Finalize: F10 + Enter on the native confirm (`usePosOrder.js:1493`) = 2. Total ≈ 26 keys, 0 clicks. | Native confirm on every sale. The search list blanks on each keystroke (FE-5). Every preview creates a real order. | Two-stage F10 (inline "press again"): −1 key and no popup. Enter on qty jumps back to the search (no F2): −3 keys. Fix FE-5. ≈ 22 keys (−15%). | 6 |
| Reservation create (`/reservations/new`) | Customer search ≈ 6 keys + 1 click; item 4 chars + Enter; qty; branch preselected; 1 click «حفظ». Extra line: 1 click «+» and item. Duplicate case: +1 modal click. ≈ 4 clicks + 15 keys. | No `<form>` (0 forms in the file), so Enter does not submit. Duplicate warning is a modal. Extra lines can be lost (FE-2). | Wrap in a `<form>` with Ctrl+Enter to save, an inline duplicate banner, lines inside the create call. −2 clicks. | 5 |
| Transfer request (`/transfers/new`) | Pick the supplying branch (1 click + select); per item: scan + click qty + type; tick «إرسال» (1) or later open the draft and submit (+2–3 clicks); save (1). ≈ 5 clicks + per-item click. | Draft by default (FE-11); qty not focused after a scan. | Default send; autofocus qty; Enter goes back to the search. −1 click per item, −1 to −3 per request. | 4 |
| Demand capture (desktop `/demand`) | Open the modal (1), customer search, item, qty, save (1) ≈ 3 clicks + typing. From POS, F7 / Find-Stock drawer → «طلب مفقود» ≈ 2 clicks. | Modal on a common action (FE-27). | Make the POS drawer path the default; inline form on `/demand`. −1 click and no modal. | 3 |
| Shortage entry (`/shortage`) | Create list via modal (2 clicks), then per item: search + add. Rows have `useGridKeyboard` (good). | Modal to create the list. | Auto-create today's list per branch; inline add row. −2 clicks. | 3 |
| Approvals (`/approvals`) | Per request: click row (1) → modal → pick approve/reject (0–1) → confirm (1) ≈ 2–3 clicks. 30 requests ≈ 75 clicks. | No keyboard, no bulk (FE-10). | `useGridKeyboard` + Space to select, Enter/A to approve, R to reject with an inline note, Ctrl+A bulk. 30 requests ≈ 5 keys. | 6 |

Keyboard coverage. **Good:** the POS (F2/F4/F6/F7/F9/F10, Ctrl+F2/F3, Q, arrows, Delete, Ctrl+F1), the
Ctrl+K command palette, and 30 grids with `useGridKeyboard`. **Missing:** approvals, the transfer form, the
reservation form (no Enter-to-save), and the modals (no Esc in 115 of 116 overlays). Loading, empty and
error states: see FE-7.

---

## Bundle sizes (`vite build`, commit 56870174)

Totals: 253 asset files, JS ≈ 6.41 MB raw (all chunks), dist 8.0 MB (including fonts and
`tesseract-worker.min.js`). CSS: `index-*.css` 144 kB, `DeliveryDashboard-*.css` 16 kB. Vite warns about
the entry chunk being over 500 kB.

| Chunk | Raw | Gzip | Loaded |
|---|---:|---:|---|
| `index-FqvIcEGl.js` (entry: React, router, query, axios, Layout + drawers + help, api client) | 715.30 kB | 209.03 kB | every page |
| `index-DD9CTm96.js` (@zxing barcode) | 416.03 kB | 108.70 kB | lazy, via BarcodeScanner |
| `JsSIP-*.js` (soft-phone) | 277.29 kB | 62.81 kB | lazy |
| `InsuranceClaimDetailPage-*.js` | 230.56 kB | 54.85 kB | route |
| `SupplyPage-*.js` | 205.36 kB | 53.01 kB | route |
| `DeliveryDashboard-*.js` (Leaflet) | 198.01 kB | 54.67 kB | route |
| `POSOrderPage-*.js` | 136.49 kB | 37.26 kB | route |
| `TaxInvoicingPage-*.js` | 135.40 kB | 34.01 kB | route |
| `IncentivesPage-*.js` | 106.53 kB | 22.57 kB | route |
| `InvoicePage-*.js` | 103.14 kB | 25.62 kB | route |
| `usePosOrder-*.js` | 45.70 kB | 16.21 kB | with POS |

Headline: the first load is about 209 kB gzip of JS plus the CSS. That is acceptable on a LAN but slow on
branch 4G. Lazy-loading the drawers, palette and help (FE-19) should cut roughly 25–35% (estimate). The
largest page chunks (claims, supply) match their file sizes (5.3k and 2.7k+ lines).

---

## Comparison with R8 (2026-11-05)

- **KNOWN:** FE-20 (menu/route roles against the matrix: R8's menu-vs-API table and `knownGaps.js`) and
  FE-21 (lint warnings; R8 had 190, now 188).
- **NEW:** FE-1 to FE-19 and FE-22 to FE-27. R8 covered lint, guards, cookies and three e2e flows. It did
  not look at TanStack v5 API misuse (FE-4/5/6), the offline queue (FE-1), the silent loss of reservation
  lines (FE-2), checkout orchestration (FE-3), error states (FE-7) or UX click cost.
- R8 follow-ups still open: the e2e job's `continue-on-error`, and moving the lint rules from warnings to
  errors.
