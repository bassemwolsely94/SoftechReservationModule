# Role-by-role UAT — report (DRAFT, 2026-11-17)

Design `docs/superpowers/specs/2026-11-16-role-uat-design.md` · Plan `docs/superpowers/plans/2026-11-16-role-uat.md`
· Runbook `scripts/uat/README.md`

> **Status: draft.** W4, W5a, W5b, W6 and W7 are in, with their fixes in PR 161 and PR 163
> (not merged). W2 (screens) and the W3 live button sweep are re-running with a relogin guard,
> because runs longer than an hour went on signed out.

## How it was tested

- **Where:** `elrezeiky_uat`, a restored copy of the office database (2026-11-16), served by
  `config.settings_uat`: reader only, no SOFTECH host, every writer and send switch off, scheduler off,
  `RBAC_ENFORCEMENT=enforce`. The office server and `elrezeiky_db` were not touched apart from the read-only dump.
- **Who:** 19 accounts — one `uat_*` user per role in branch A (160 باب الحديد), branch-B twins of the
  branch roles (150 عين شمس), a multi-branch pharmacist, a restricted-branch supervisor, phone-hidden and
  phone-visible pharmacists, and the one recently active real user (admin).
- **Expected results** come from the copy's live role matrix (`RoleModuleAccess`) and `core/branch_scope`,
  not from code defaults. `docs/uat/permission-drift.md`: no drift between live rows and code `PERMISSIONS`.
- **Owner approval used:** on the copy only, POS orders may be pushed (dry run) and pricing / discount
  requests approved end to end; every such test first asserts a reader copy.

## Severity

P1 = wrong person can see or do something they must not, or a workflow is broken · P2 = leak of
lesser data, misleading screen, or a rule bent · P3 = polish, owner decision, or stricter-than-matrix.

## Owner decisions (answered 2026-11-17)

| # | Decision | Fixed on |
|---|---|---|
| D1 | Require the full-phone search first: another branch's customer opens by id only within 12 h of a full-phone find (`CustomerFound`, `CUSTOMER_FOUND_HOURS`). | `claude/uat-fixes` |
| D2 | Yes — POS locked to the user's own branches (picker + every POS lookup; order creation was already checked). | `claude/uat-fixes` |
| D3 | No — returns off the POS screen (`POS_RETURNS_ENABLED`, default off; existing returns keep their posting path). | `claude/uat-fixes` |
| D4 | Real user roles to be revised together with the owner before go-live. | open |
| D5 | Tighten the code to the matrix: the 24 looser frontend gates now also ask the matrix grant their API checks. Backend role lists that are looser than the matrix are listed as follow-ups. | `claude/uat-fixes` |

The questions as originally asked:

| # | Question | From |
|---|---|---|
| D1 | Customer read by numeric id across branches: a branch user opening another branch's customer by id sees name, date of birth and lifetime value (phone masked). By design ("a found customer opens whatever their branch"), but ids are sequential. Accept, or require the full-phone lookup first? | W6 |
| D2 | POS branch picker: a branch-A seller can pick any branch, and the POS lookups answer for it (staff list, stores, SOFTECH customer directory). Should POS be locked to the user's own branches? | W6 |
| D3 | POS document type offers «مرتجع (30)» to sellers. Earlier scope said no returns on the POS screen — is it now in scope? | W6 |
| D4 | 7 of 10 roles have no real active account; most real accounts are role salesperson (incl. «Admin»). Assign real roles before go-live. | B-02 |
| D5 | Code role checks looser than the matrix (24 P1, W3): keep the matrix as the truth and tighten the code? | W3 |

## Findings

### Found while building the harness

| id | sev | finding |
|---|---|---|
| B-01 | P2 | `apps/users/mfa.py:60` reads `bool(s.typed_value)` without calling it, so any `security.mfa_enforced` row — even "false" — means enforced. |
| B-02 | P1 | Only admin (2), call_center (1) and salesperson (83) have real active accounts; 7 roles have none. |
| B-03 | P2 | Only 1 real user opened any screen in the last 30 days (audit ScreenView). |
| B-04 | P3 | JWT logins never update `last_login` (latest 2026-07-01), so "last seen" columns are wrong. |

### W3 — buttons and role checks (branch `claude/uat-w3-buttons-f7eb02`)

- **Live sweep:** 19 users × 11 screens — every `data-perm` button showed or hid exactly as the matrix
  says, and every allowed primary action was present. **No findings from the live screens.**
- **Code catalogue:** 200 hard-coded role checks compared with the matrix: 80 match, 14 looser, 93 stricter,
  10 both, 3 routing. Full list: `docs/uat/role-checks-catalogue.md` on the W3 branch.
- **24 P1 — the code lets a role in that the matrix denies.** Highest:
  - `/pos/exceptions`: pharmacist, supervisor without `pos:approve`.
  - `/phantom-sales`, `/cash-optimization`: pharmacist, quality_manager without `purchasing:view`.
  - `/phone-alerts`: supervisor without `settings:view`. `/missed-sales`: quality_manager without `pos:view`.
  - Announcements create/delete for supervisor without `settings:create/delete`.
  - Batches: supervisor (and quality_manager) get `catalog:edit/approve` controls.
  - Call center / cases: quality_manager gets `callcenter` edit, approve, create.
  - Insights run for purchasing, supervisor, quality_manager without `analytics:create`.
  - Freshness-bar refresh (`sync:edit`) open to purchasing on FOC / margin / supplier-performance pages;
    vouchers coupons tab open to quality_manager.
  - These are frontend gates; whether the server also refuses is W2/W5's check (*pending*).
- **103 P3 — the code is stricter than the matrix** (a role the matrix allows is kept out). Matrix wins → loosen or update the matrix.
- **3 P3 — role words that do not exist:** `'manager'` (`MobileReservationDetailPage.jsx:33,108`), `'branch'` (`navGroups.js:66`).

### W6 — hands-on pass (this branch, `docs/uat/runs/w6-findings.jsonl`)

| sev | user | screen | finding |
|---|---|---|---|
| P2 | salesperson | `/pos` | POS lookups `customer-entities`, `salespeople`, `branch-stores` (`apps/pos_orders/views.py` ~1063/1087/1109) take any `?branch=` without `branch_scope`: a branch-A seller lists branch B's staff and SOFTECH customer directory (names + PIC). → D2 |
| P2 | salesperson | `/pos` | Four POS views (`apps/pos_orders/views.py:1081,1103,1124,1358`) return `f'تعذّر القراءة: {e}'`; the cashier sees the raw Java exception with the SOFTECH host. Must go through `core/errors.public_error` (security DoD item 4). |
| P3 | phoneHidden | `/api/customers/<id>/` | cross-branch read by id → D1 |
| P3 | salesperson | `/pos` | «مرتجع (30)» offered → D3 |
| pass | phoneHidden | `/customers/:id` | phone masked on screen and in the API for own and other-branch customers; name search does not find a branch-B customer |
| pass | accountant | `/finance/dashboard` | consolidated figures (accountant is all-branch, B-1) |
| pass | supervisor | `/approvals` | inbox across branches with decision buttons |
| pass | admin | `/users`, `/insurance` | list and claims load; no phones on the user list |

### W2 — screen visibility (*pending*, branch `claude/uat-w2-visibility-f91f78`)

Known so far: `/stock-count` (call_center, accountant) and `/vouchers` (accountant) get a clean 403 from the
server, but the page leaves it unhandled and shows a misleading empty state («لا توجد جلسات جرد») instead of
"no access" — P2 where the menu shows the screen, P3 where it hides it.

### W4 — phones and other branches on screen (branch `claude/uat-w4-exposure-e89046`)

Third full run (the first two do not count: the shared server was down 02:37–02:55, then the suite
ran signed out after its first hour and only looked for the reference customers' numbers): 397
passed, 3 failed (slow-screen timeouts), 32 raw findings → after triage **2 real P0, 0 branch
leaks, 0 owner decisions**.

| sev | finding | fixed |
|---|---|---|
| P0 | Phone-hidden staff got full numbers in the reservations Excel export, the receipt (`/print/`) and the WhatsApp share — `apps/reservations/views.py` decided by role only (`_PII_ROLES`). | PR 161: role list **and** `access.record_phones_visible` |
| P0 | Viewers saw every follow-up customer's number (798 for branch A, 384 for B); admin / call center / supervisor bypassed `can_see_customer_phone` — `apps/followups/views.py` never used the shared rule. | PR 161: `record_phones_visible` |

17 raw findings were the detector's own false positives (the pharmacy's WhatsApp number, drivers'
mobiles, a transfer branch 3 supplies, three lookups B-2 says to mask) — fixed in the spec.

### W5a — operational workflows (branch `claude/uat-w5a-ops-91fcb2`)

39 passed, 1 failed; 3 P1, 3 P2, 3 P3. Reservations, demand + follow-up, transfers (incl. refusing
a pharmacist approving their own transfer), shortage, stock-count daily review and the call-center
case flow all worked per role.

| sev | finding | fixed |
|---|---|---|
| P1 | Rider «complete» → HTTP 500 (`collected_amount` sent as text) and the order was already saved as delivered with no cash-collection row. | PR 163: Decimal parse (400 on junk) + one transaction |
| P1 | Stock count «+ جلسة جديدة» gated on admin create; a pharmacist with `stockcount:create` could not open a session. | PR 163 |
| P2 | New shortage list / call-center case answered without its id → did not open; list not refreshed. | PR 163 |
| P3 | Stock-count snapshot error showed the JDBC text with the connection URL. | PR 163 (`public_error` no longer DEBUG-dependent) |
| P3 | Delivery dashboard «اليوم» used the UTC date (00:00–02:00 Cairo hides new orders). | PR 163 |
| P3 | Counting / variance / close need SOFTECH — not exercised on the copy; check on the office server. | open |
| P3 | Daily count is off (`DAILY_COUNT_ENABLED`) — on at go-live? | owner |

### W5b — money and approval workflows (branch `claude/uat-w5b-money-bca2fa`)

68 passed, 2 failed (both real); 2 P0, 3 P1, 2 P2, 7 P3. POS sell → ready → push was a dry run with
correct totals for every selling role (and refused for branch B selling for A); insurance totals,
vouchers (5% of 300 = 15), the approvals inbox and the HR leave chain worked.

| sev | finding | fixed |
|---|---|---|
| P0 | Purchasing approved their own ISR. | PR 163: maker-checker (admin exempt while `SELF_APPROVAL_ADMIN_EXEMPT`) |
| P0 | Accountant drafted and approved the same GL entry. | PR 163: maker-checker on the approve API (single + bulk) |
| P1 | Pricing approve had no requester check (only the writer-off 503 stopped an admin approving their own). | PR 163: same rule; closes fully when the admin exemption is switched off (D4) |
| P1 | Viewer and quality manager could file leave without `hr:create`. | PR 163: all HR request filing needs `hr:create` |
| P2 | A submitted insurance claim could be moved back to draft. | PR 163: 409; admin reopens with a written reason |
| P2 | The voucher OTP is in the reply to the staff screen (`whatsapp_url`, `qr_code`). | owner decision |
| P3 | ISR push-review error showed raw JDBC text. | PR 163 |
| P3 | Pricing approve is admin-only in code; voucher cancel hard-codes manager/admin (both stricter than the matrix). | open (stricter) |
| P3 | GL form shows «متوازن» for a line with no account (server refuses). | open |

### Found while fixing (owner)

- Delivery cash: a collected amount of 0 is recorded as fully collected; mixed-payment orders
  count the whole total as expected cash; `delivery_collect_cash` goes through float.
- The office server runs `DEBUG=True` on the LAN; `public_error` used to show technical text to
  every user in that mode (fixed in PR 163, but DEBUG itself should be off in production).

### Harness lessons (for the next UAT round)

- Logins expire after one hour and refreshes rotate the token, so any run longer than an hour
  silently runs signed out — W4's relogin guard is the fix; W2 and W3 reran with it.
- Every Playwright run empties `test-results-uat` (findings included) — copy findings per run.
- One shared dev server for six sessions: it dropped once for 18 minutes; a run must fail, not
  pass, when the backend is unreachable.

## Speed and load (W7, branch `claude/uat-w7-load-8dc62f`, `docs/uat/light-load.md`)

- **0 failures in 2,635 requests** at 5 and 10 virtual users (each several times busier than a real user);
  p95 2.7 s → 3.0 s; free RAM never below 5.8 GB (floor 3 GB).
- The server was one dev `runserver` process sharing the PC with Postgres and five test sessions, so the
  numbers rank routes rather than predict the VPS. Slowest under load: `sync/freshness` (p95 5.1 s,
  max 8.8 s), `dashboard/summary` (max 7.7 s), `search/universal` (p95 3.3 s), `batches/stock-expiry/summary` (p95 4.4 s).
- In the browser, desktop screens took 5–30 s to settle (W3: 164 of 209 visits over 5 s, mean 20.8 s), much of
  it the Vite dev server compiling on first visit. Re-measure on a production build before judging.
- The full 20–40-user test stays a VPS cutover item.

## Not covered

- Real SOFTECH reads and writes (no SOFTECH host on the copy) — stock, salespeople, customer directory
  lists come back empty with an error note.
- Mobile / rider screens were only visited, not worked through.
- 2FA (switched off on the copy; covered by backend tests).
