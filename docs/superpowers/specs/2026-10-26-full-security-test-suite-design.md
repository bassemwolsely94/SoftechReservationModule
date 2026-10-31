# Full security & regression test suite — design

Date: 2026-10-26 · Inputs: [docs/security/2026-10-26-security-inventory.md](../../security/2026-10-26-security-inventory.md)

## Intent

The owner's worries, in order: data leaks, break-ins, unauthorized access to functions and
modules, anyone reaching SOFTECH / its database / the branch servers through this system, and
big bugs. They want a harsh suite that covers every app, backend and frontend, and **every hole
a test exposes gets fixed in the same batch**. A test that exposes a hole is not "known failing"
— the batch isn't done until the hole is closed and the test is green.

Success = the suite fails loudly in CI the moment someone (a) opens an endpoint to the wrong
role or branch, (b) builds SQL from text, (c) opens a SOFTECH connection outside the kill-switch,
(d) adds a SOFTECH write without a flag / dry-run / idempotency / audit, (e) leaks a secret, or
(f) breaks a core flow on the frontend.

## Goals

1. **Generic sweeps that cover every route automatically** (new endpoints are covered the day
   they're added, no per-endpoint test needed to get baseline protection):
   - role × route × method sweep (all 9 roles, GET + write methods), expectations derived from
     the existing RBAC matrix (`seed_permissions` / `RoleModuleAccess`) — not hand-written;
   - cross-branch sweep: real records in branch A, a branch-B user, every list + detail route;
   - anonymous sweep (exists — keep);
   - "no 500 for any role" sweep, and a write sweep with junk bodies (no 500, no SOFTECH call).
2. **Static guards (AST/grep tests that run in the normal suite):**
   - no SQL built with f-string / `%` / `.format` / `+` that reaches `execute` on Sybase or
     PostgreSQL unless the call site is on a reviewed allow-list of internal-constant-only cases;
   - no SOFTECH connection outside `config/sybase.py`'s guarded path (`SybDriver`, `DriverManager`
     anywhere in `apps/` fails);
   - every SOFTECH write site is registered in one manifest (file, tables, flag, idempotency key,
     audit) and the test fails if an INSERT/UPDATE/DELETE against SOFTECH appears that isn't in it;
   - every `*_ENABLED` / `*_WRITE*` flag defaults to False;
   - no hardcoded credentials / tokens in tracked files; `.gitignore` sanity;
   - every view is either in the reviewed public list or has a role/module permission stronger
     than bare `IsAuthenticated` (allow-list for genuinely all-staff endpoints such as `/me`).
3. **SOFTECH-defect suite** — for every write path in the manifest: flag off ⇒ no connection;
   dry-run is the default; same request twice ⇒ one write; audit row written; permission enforced;
   plus a fuzz of the read-only SQL checker (comment/string tricks, batches, `getConnection`).
4. **Injection & abuse suite:** SQL-injection payloads at every parameter that reaches a query,
   CSV/XLSX formula injection on every export, SSRF on URL fields, upload type/size abuse, path
   traversal, oversized / negative quantities, throttle bypass via `X-Forwarded-For`, WebSocket
   subscribe/post to other users' groups and records, portal token reuse.
5. **Auth suite:** login, 2FA (incl. the bypass), refresh/rotation/blacklist, deactivation ends
   sessions, password policy, MFA device token, admin login.
6. **Per-app coverage:** every app gets at least a model/serializer/view test file; the 9 untested
   apps and the thin ones get business-logic tests (money, stock, status transitions).
7. **Frontend:** ESLint (incl. `react/no-danger`, hooks rules); Vitest unit tests for the API
   client, auth store, permission/route guards, number/money formatting, and shared hooks;
   Playwright end-to-end against the local dev server with seeded test users for each role:
   login (+2FA), hidden-vs-forbidden checks (a page hidden in the UI must also 403 on the API),
   and the critical flows (reservation, transfer, POS order to "ready" — never push).
8. **CI:** add bandit, pip-audit, `npm audit --audit-level=high`, ESLint, Vitest, coverage report
   (backend coverage floor set after the first full run, then ratcheted up). Playwright runs in CI
   against the built frontend + test backend.

## Non-goals

- No test ever connects to a real SOFTECH, HQ or branch server. Live probes stay manual
  management commands, outside the suite.
- No pen-test of the VPS/network/nginx host itself (config files are checked statically only).
- No rewrite of working features; fixes are the smallest change that closes the hole.

## Anti-goals (failure even if tests pass)

- Fixing a permission hole by locking real staff out of work they do today. Expectations come
  from the RBAC matrix the owner already maintains; where the matrix and today's behaviour differ,
  that's a question for the owner, not a silent choice.
- A test that "passes" because it mocks away the thing under test (e.g. mocking the permission
  class). Permission and scoping tests go through the real HTTP stack.
- Any fix that changes a SOFTECH write, auth, pricing or checkout without the owner's explicit OK.

## Constraints

- Django test runner only (`manage.py test`) — the SOFTECH isolation in `config/settings.py`
  depends on it. No pytest migration.
- Tests run with `RBAC_ENFORCEMENT=enforce` in the new sweeps (override per test class); the
  production default is a separate owner decision (see "Theirs (open)" below).
- CLAUDE.md batch rules apply to every batch: state change, files, migrations, tests, in-app help
  for any changed screen, run tests/lint/build, regressions, summary, propose next batch.
- **Stop and ask** before any fix that touches SOFTECH writes, auth/login/2FA/sessions, pricing or
  discount logic, payment or checkout completion, or double-post risk. Each such fix is presented
  as a small diff for approval before it lands.
- The working tree has a large amount of unrelated uncommitted work. Commits (when asked for)
  include only this suite's files and fixes.

## Batches (order)

| # | Batch | Stop-and-ask items inside |
|---|---|---|
| 0 | Harness: shared fixtures (two branches, one user per role, records per branch), sweep framework, static-guard framework, write-site manifest, CI scanners + coverage | — |
| 1 | SQL injection: tests + parameterise stockcount, near-expiry, and every other user-reachable site the static guard finds | stockcount/near-expiry are SOFTECH **reads** — no ask; any write-path SQL → ask |
| 2 | SOFTECH safety: kill-switch bypass (`diag_appname`, `probe_connection`), read-only checker holes, default-ON flags, ungated writes (tier-create, probes), shortage endpoints permission, loyalty idempotency, unflagged live-writing commands | **all of it → ask** |
| 3 | Auth: 2FA bypass, verify throttle, TOTP replay, deactivation kills sessions, WebSocket token checks, password validators, XFF/`NUM_PROXIES` | **all of it → ask** |
| 4 | Authorization: role × route sweep; fix every view that's weaker than the matrix (finance, cheques, payments, incentives, campaigns, analytics, procurement, customers, pos_orders DELETE, purchasing exports…); middleware gaps (POST action mapping, unmapped prefixes, exempt `search`); mass-assignment | payments/POS/pricing views → ask |
| 5 | Branch scoping: cross-branch sweep; make `allowed_branches`/`restricted_branches`/`access_all_branches` actually apply through one helper; fix fail-open scoping | — (unless POS/payments) |
| 6 | Platform & abuse: WebSocket chatter/PBX authorization, SSRF, formula injection, uploads, portal token reuse + reorder bounds, voucher OTP exposure, HSTS/secure defaults, `.gitignore`, tracked secrets/data files | voucher redemption → ask |
| 7 | Per-app coverage: every app, untested first; business-logic bugs found get fixed | pricing/checkout bugs → ask |
| 8 | Frontend: ESLint, Vitest, Playwright per-role e2e, CI wiring | — |

Each batch ends green (full backend suite + build) before the next starts.

## Decided

- Test and fix in the same batch (owner, 2026-10-26).
- Stop-and-ask list as above (owner).
- Django runner kept; expectations from the RBAC matrix; frontend tooling = ESLint + Vitest +
  Playwright; scanners = bandit + pip-audit + npm audit (my calls).

## My calls (owner to check)

- **Code base:** build on the current working tree — it is the code that will ship. No commits
  unless the owner asks; when asked, stage only suite files and fixes hunk by hunk.
- **Pending stop-and-ask fixes don't block later batches.** At the start of each batch all its
  stop-and-ask items are put to the owner together. A test waiting on a decision is marked
  `expectedFailure` with the decision id, and listed in `apps/tests/security/PENDING.md`; a guard
  test fails if that list and the markers drift apart. The marker comes off the day the fix lands.
- **Playwright never touches the dev `.env`.** A dedicated `config/settings_e2e.py` imports the
  normal settings and then applies the same SOFTECH isolation block the test runner uses
  (no host, read-only on, every write flag False), with its own empty database seeded only with
  fixture users and records. Extends the isolation; never weakens it.

## Owner decisions (2026-10-26)

1. **Role matrix truth = the code defaults in `seed_permissions`** (production isn't live yet).
   The role sweep derives every expectation from it.
2. **RBAC:** tests run with `RBAC_ENFORCEMENT=enforce`, and every sensitive view also gets its
   own permission check so it's safe in `log` mode too. Production stays `log`; the owner switches
   to `enforce` after a week of reading the would-deny log.
3. **Branch access:**
   - `allowed_branches` is the real extra-branch list; `UserBranchAccess` folds into it (data
     migration copies its rows, then one helper reads only `allowed_branches`).
   - A restricted branch always wins, even over `access_all_branches` and all-branch roles.
   - Branch roles (pharmacist, salesperson, …) may **read** other branches' stock and the transfer
     screens. Customers, orders (POS/reservations), payments, cheques and finance stay limited to
     the user's own branch(es).
   - One helper, fail-closed (a branch role with no branch sees nothing).
4. **Tracked secrets/exports:** delete from the tree going forward, owner rotates the admin
   password, no history rewrite unless the exports contain patient data. Checked: the two
   gift-voucher exports hold supplier/document data and one customer code, no patient names or
   phones → no history rewrite; they're removed from git and moved to the ignored scratch area.

5. **Branch scope details (2026-10-30, B-1…B-3):** supervisor and quality manager are all-branch roles;
   company-wide finance (consolidated, every branch's P&L, supplier A/P) is for the all-branch roles, a branch
   user sees their own branch's finance only; customers are findable by anyone through their full phone
   number (numbers of other branches masked), while browsing, name search, edits and exports stay with the
   customer's own branch — call center edits anyone.

## Left to the builder

Fixture shapes, file layout under `apps/tests/` (suggest `apps/tests/security/` package), the
static-guard allow-list format, how the sweep renders URL kwargs for real records, Playwright
project layout.
