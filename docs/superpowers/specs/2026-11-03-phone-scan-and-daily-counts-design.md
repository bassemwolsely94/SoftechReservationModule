# Project 2 — Phone-camera scanning + small daily stock counts (design)

Date: 2026-11-03 · Status: DRAFT for owner approval · Owner decisions recorded inline as **[owner]**,
builder's own calls as **[call]**.

## 1. Intent and why

The owner approved a set of "futuristic" ideas; Project 2 is about making the shop floor's stock
truthful without a big annual stock-take:

- **(a) Phone-camera barcode scanning** wherever an item is searched, so staff on a phone scan the
  pack instead of typing names. Mobile screens first.
- **(b) Small daily stock counts** (جرد يومي صغير): every salesperson counts ~20 items a day,
  automatically chosen with a bias towards risky items, counted on the phone, differences reviewed by
  the branch manager and escalated to central audit. The goal is to find stock losses and wrong
  balances continuously, and to make it visible whether the counts are really being done.
- **(c) Scan-to-receive** — **[owner] not in this round** (the team doesn't receive by scanning even
  in SOFTECH). Leave it out; it may come later behind its own switch.

The system is going live on a new VPS now; this work must **ship dark** and never block go-live.

## 2. Goals / non-goals / anti-goals

Goals
- A 📷 button on every item search (one shared component), working on **Android and iPhone** **[owner: mixed fleet]**.
- Daily per-salesperson count lists, risk-weighted random, blind counting, manager follow-up, escalation.
- Expected quantity captured **at the moment of counting**, so sales between list creation and counting do
  not show as fake shortages.
- Full audit trail of every count attempt, recount, acceptance, escalation.

Non-goals
- **No SOFTECH writes of any kind.** Stock corrections stay a manual step in SOFTECH by staff, exactly as
  today. (A guarded adjustment writer would be a separate, owner-approved project.)
- No scan-to-receive (c).
- No change to how existing count sessions (transaction / full / filtered / expiry_audit) behave.

Anti-goals (would be a failure even if it "works")
- A second, parallel stock-count system. Daily counts live **inside `apps/stockcount`** and reuse its
  sessions/snapshots/variance logic and the existing mobile count screen patterns.
- Counters seeing the expected quantity (biases the count).
- Anything visible or scheduled while the switches are OFF.
- Noisy UI: no new modals for the common path; scanning and counting must be one-handed and fast.

## 3. Constraints (from CLAUDE.md and the project)

- Every feature behind a switch that **defaults OFF**; tests must not depend on `.env` (settings.py
  already forces `_ENABLED` keys off in tests — follow that pattern).
- Server-side permissions and branch scoping (`core/branch_scope.py`); never trust hidden buttons.
- Audit every state change (who/what/when/why/before-after) via the project's existing `AuditLog`.
- Arabic-first RTL; calm UI; branch names never bare codes (`useBranchLabels`).
- In-app help for every new/changed screen and tab (`apps/help/content/<module>.py`, AR+EN, bump
  `updated`); `apps/tests/test_help.py` must pass. Product tour coverage (`help_tour_coverage`) too.
- Sortable grids (`useSortableRows`/`SortTh`), grid keyboard (`useGridKeyboard`) on review grids.
- Threads only via `core.threads.start_thread`. Scheduler jobs registered the project's usual way and
  gated by the switch.
- Camera needs HTTPS (the VPS is HTTPS; localhost works in dev).
- SOFTECH reads only; quarantine/closed stores (102, 103, 105, 110) excluded from operational stock as
  the existing stock-count engine already does.

## 4. Part (a) — Camera scanning

What exists: `frontend/src/components/ItemSearchWidget.jsx` is used on 23 screens (6 mobile:
items lookup, demand, reservation, transfer, POS, stock count). Its search already matches primary and
secondary barcodes (`Item.barcode`, `ItemBarcode`) with exact barcode ranked first.
`frontend/src/components/QrScanner.jsx` is a QR-only camera modal using native `BarcodeDetector`
(Android Chrome only), used on `/m/customers`.

Design
- Generalise the scanner into one camera component (keep `QrScanner`'s API working for
  `/m/customers`) that reads EAN-13, EAN-8, UPC-A/E, Code-128, Code-39, ITF and QR.
- Engine: native `BarcodeDetector` when present and it supports the formats; otherwise a **bundled**
  JS decoder (e.g. `@zxing/browser` / `@zxing/library`, pinned, served from our own build — no CDN, no
  external service) so iPhones work **[call]**. Library lazy-loaded so it doesn't grow the main bundle.
- `ItemSearchWidget` gets a 📷 button inside the input (all variants, incl. POS) **only when the switch
  is on and the browser has a camera API**. Scan → puts the code into the search → if exactly one item
  matches by barcode/code it is selected immediately (same as choosing it from the list); otherwise the
  normal result list shows. Not found → a calm inline "لم يُعثر على الباركود" with the code shown.
- Haptic/beep feedback on a successful read where the device allows; torch toggle when supported.
- Continuous-scan mode for the daily count screen (scan → qty → next scan without closing the camera)
  **[call]**; single-scan elsewhere.
- Switch: `CAMERA_SCAN_ENABLED` (settings/env, default False), exposed to the frontend through the
  existing client-config/feature endpoint the app already uses for flags (builder: find it; do not
  invent a new mechanism if one exists).
- No backend change needed for lookup unless the builder finds the exact-barcode path is not first in
  the shared search for some variant.

## 5. Part (b) — Small daily counts

### 5.1 Who gets a list **[owner]**
- **Everyone on the branch roster**: every active `StaffProfile` whose primary `branch` is the
  branch and whose role is `salesperson` **[owner said "per salesperson"]**. Whether `pharmacist`
  is included is a setting, default **off** **[call]**.
- **[owner] Skip approved leave**: anyone with an approved `apps/hr` `LeaveRequest` covering the date
  gets no list that day (their items are simply not drawn). Weekly days off are not known to the system,
  so those lists show as missed.
- A branch manager (see 5.4) who is also on the roster still gets a list, but **their own differences go
  straight to the central auditor** — nobody reviews their own count **[call]**.
- Only branches that are switched on for the pilot (per-branch flag on `BranchSettings`, default False)
  **[call]**, and only operational branches (`is_operational`).
- **20 items per person per day [owner]** — a setting (`DAILY_COUNT_ITEMS_PER_PERSON`, default 20).
- Lists are created by a daily scheduled job early morning (Cairo time, ~07:00, setting) **[call]**, and
  can be (re)generated on demand by an admin for a branch/date (idempotent: one list per person per day;
  re-running never duplicates).

### 5.2 Which items **[owner: all four signal groups; random but weighted to risk]**
Eligible pool per branch: items with non-zero on-hand in the branch's operational stores (from the
`ItemStock` mirror; **negative balances are eligible and high-risk**), stockable items only, not
archived. Each eligible item gets a risk weight from these signals (all from data we already mirror):

| Signal | Source |
|---|---|
| High value (on-hand × cost) | `ItemStock.quantity_on_hand` × `Item.cost_price` |
| Fast mover | `ItemStock.monthly_qty` (sales rate) |
| Recent SOFTECH adjustments (doccode 50/150) | `apps/stock_audit` `StockLedgerLine` (last 60 days) |
| Open stock-audit findings for the item at the branch | `apps/stock_audit` findings |
| Frequent losses / fluctuations | past daily-count differences + count of adjustments + stock-out findings |
| Near expiry (≤ 90 days) | `apps/batches` `StockExpiryBalance` mirror |
| Not counted for a long time | last count date per (branch, item) across all our count sessions |

- Weights and windows are editable settings with sensible defaults **[call]**; the exact formula is left
  to the builder but must be deterministic given a seed, explainable, and unit-tested.
- Selection = **weighted random sample without replacement** per branch per day, seeded by
  (branch, date) so a re-run reproduces the same picks **[call]**. Then split across the branch's
  salespeople so **no two people in the same branch get the same item the same day**.
- Rotation: an item counted in the last N days (default 14) is skipped unless it has an open
  difference/flag; items never counted get a bonus so coverage grows over time **[call]**.
- Each picked item stores its **reasons** (e.g. «قيمة عالية», «سريع الحركة», «تسوية حديثة»,
  «قرب انتهاء», «لم يُجرد منذ 120 يوم») — shown to the manager, **not** to the counter.
- Near-expiry picks also ask the counter for the earliest shelf expiry (reuse `physical_expiry`).
- If a branch has fewer eligible items than needed, give fewer; never pad with repeats.

### 5.3 Counting (salesperson, phone)
- `/m/stock-count` shows «جردي اليوم» at the top: today's list, progress «7 / 20».
- **Blind count [call, owner did not object]**: the counter sees item name, pack picture/barcode,
  and enters what is on the shelf (packs + strips where the item has units — reuse the POS
  strips→qty rule). They never see expected qty or the difference.
- **[owner] Count everything the branch holds** — shelf, back room, drawers — **including reserved /
  set-aside packs**. Expected = the SOFTECH branch balance over operational stores (no deduction for our
  reservations or unposted POS orders). The count screen shows a one-line reminder:
  «اجرد كل الكمية بالفرع: الرف + المخزن + المحجوز».
- Camera continuous-scan or tap the item in the list. Scanning an item not on today's list says so
  calmly and does nothing.
- On submit, the server reads the **live** balance for that one item at that branch (branch node first,
  HQ fallback — reuse `stockcount.engine` SQL; record which source and the read time). If SOFTECH is
  unreachable, the count is still stored with the `ItemStock` mirror value and flagged
  «المتوقع من نسخة محلية» so the reviewer knows **[call]**. Offline phones use the existing
  `queuedPost` queue; the expected qty is read when the count reaches the server.
- Each submission is an immutable **count attempt** (who, when, counted, expected, source, difference,
  value EGP = |diff| × cost). Nothing is overwritten; a recount is a new attempt.
- The existing `StockCountSnapshot.expected_qty` immutability rule must hold. Builder decides the exact
  data shape (e.g. a daily-count session per person per day in `StockCountSession` with
  `mode='daily'` + `assigned_to` + `count_date`, a pick row per item, an attempt row per count), but:
  existing modes, endpoints, Excel flows, the stock-audit `adjustment_after_count` check and the
  gamification `stockcount_completed` rule must keep working, and the stock-audit check must be able to
  see daily-count differences (with the attempt time as the count time).

### 5.4 Manager follow-up and review **[owner: branch manager, then auditor]**
- **Branch manager** = the named branch managers already granted in `StockAuditAccess` (reuse — no new
  grant system) **[call]**. **Central auditor** = all-branch staff with the stock-count approve
  permission (supervisor / quality_manager / admin per the RBAC matrix) **[call]**.
- Manager screen (desktop `/stock-count` new tab «الجرد اليومي» + mobile view): per salesperson today —
  done / partly / not started; list of differences with reasons for the pick, expected, counted, value.
- For each difference the manager either:
  1. **Requests a recount** — by the same person or another salesperson at the branch (still blind);
     appears on that person's list today (or tomorrow if after hours).
  2. **Accepts** with a reason (dropdown + note: e.g. "سرقة/فقد", "خطأ إدخال في SOFTECH",
     "صرف بدون فاتورة", "تالف", "تحويل لم يُسجل", other), and marks whether a SOFTECH adjustment is needed
     (a reminder for staff to do it in SOFTECH manually — we do **not** post it).
- **Escalation to the auditor** automatically when |value| ≥ 200 EGP, or the same item had ≥ 3
  differences at the branch in 30 days, or the manager escalates by hand **[call — thresholds editable]**.
  The auditor sees all branches, can request a recount, accept with reason, or close.
- **End of day** = the branch's closing time from `Branch.working_hours`; 24-hour branches (`is_24h`)
  and branches without hours close at midnight Cairo time. A list's date is the Cairo date it was
  generated for; counts after midnight still land on that list until it closes **[call]**.
- **Small differences**: a difference smaller than one strip/unit (for items sold in strips) counts as a
  match; tolerance is an editable setting **[call]**. After recounts, the **latest** attempt is the
  item's result; earlier attempts stay in the history **[call]**. Pilot branches with no named manager
  send differences straight to the auditor **[call]**.
- **Not done**: a list not completed by end of day becomes «لم يُنجز» (missed) and does not roll over
  **[call]**; the manager and auditor see completion rates per person/branch over time. Notification to
  the manager about missed lists / new differences uses the existing notifications app (and Project 1's
  phone alerts if merged) — off while the switch is off.
- All review actions are server-side permission-checked, branch-scoped, and written to `AuditLog`.

### 5.5 Reporting
- Small dashboard on the daily-count tab: completion % per branch/person (7/30 days), differences found,
  value, accepted-reason breakdown, items with repeat differences. Sortable grids, Excel export using the
  project's export helpers (branch names, not codes).

### 5.6 Switches
- `DAILY_COUNT_ENABLED` (global, default False) — hides UI, stops the scheduler job, rejects the API.
- Per-branch pilot flag on `BranchSettings` (default False).
- `CAMERA_SCAN_ENABLED` (default False) — independent of daily counts; daily counts work with typing
  too.

## 6. Gamification **[call]**
Seed a new rule `daily_count_completed` (recognition only), **inactive by default** so 20 people × N
branches don't inflate points via the existing per-session `stockcount_completed` rule; make sure daily
sessions are excluded from `stockcount_completed`.

## 7. Help, docs, tests
- Help: `/m/stock-count`, `/stock-count` daily tab, every item-search screen gets a line about 📷
  (AR+EN), statuses (pending / counted / recount requested / accepted / escalated / missed).
- Architecture docs: update `11_ERP_INDEX.md`, `02_MODULE_REGISTRY.md`, `07_BUSINESS_RULES.md`
  (stock count rules), `12_PROJECT_CONTEXT_SUMMARY.md` mobile row.
- Tests: picker (weights, determinism, no duplicates across people, rotation, fewer-than-needed),
  generation idempotency, permission/branch scoping (salesperson sees only own list; manager only own
  branches; auditor all), blind API (expected never in salesperson responses), live-expected read +
  fallback, recount/accept/escalate state machine + audit rows, switches OFF ⇒ 404/403 + no scheduler,
  existing stock-count tests still pass. Frontend: build + lint.

## 8. Left to the builder
Exact models/migrations, weight formula details, endpoint names, component structure, decoder
library choice (pinned, bundled), scheduler wiring, how the frontend learns the flags (reuse existing
mechanism).

## 9. Delivery order
1. (a) camera scanning in the shared search (switch OFF) — smallest, independent, useful immediately.
2. (b) daily counts backend (picker, generation, attempts, review) + tests.
3. (b) phone counting UI, then manager/auditor UI + reports + help.
Commit on branch `claude/intelligent-jackson-8c13dc`; merge to main only with the owner's consent.
