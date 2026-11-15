# 03 — Application security audit (independent, 2026-11-15)

Scope: worktree `.claude/worktrees/full-audit` (branch `claude/full-project-audit`, at `56870174`). Read-only:
code read with Grep/Read; the route list was produced with a small read-only URL-resolver script
(`scratchpad/weak_list.py`, no DB, no SOFTECH). No tests, no management commands, no outbound requests.
Secret values were never printed; the office `.env` was only compared for equality / prefix.

Severity: P0 = exploitable now with severe impact · P1 = high · P2 = medium · P3 = low / hardening.

## Summary

| ID | Sev | CWE | Title | Status | Known? |
|---|---|---|---|---|---|
| SEC-1 | **P0** | 798 / 321 / 1188 | Office runtime signs JWTs, media links, portal, tracking and PBX links with the public placeholder `SECRET_KEY` (DEBUG path of the guard keeps it) | VERIFIED | Partly known (memory "office signing key gap", go-live G1/N9) — the forge-an-admin-token path and the DEBUG hole in the N9 fix are **new** |
| SEC-2 | **P1** | 79 | Stored XSS: portal customer text → staff "print customer receipt" popup (`document.write`, no escaping) | VERIFIED | **New** |
| SEC-3 | P2 | 639 | Record chatter POST has no branch check (GET has one) | VERIFIED | **New** (baseline line says chatter "checks the record's own module inside" — module yes, branch no) |
| SEC-4 | P2 | 347 / 489 | DEBUG=True turns webhook signature checks off and mounts `/admin/` (no 2FA); office runs DEBUG=True with no app secrets | VERIFIED (code + office flags) | Partly known (office DEBUG noted in memory); webhook fail-open on DEBUG not listed anywhere |
| SEC-5 | P2 | 693 | CSP is report-only, so it mitigates none of the XSS sinks (SEC-2, SEC-6) | VERIFIED | Known / accepted (W-9 rollout step) |
| SEC-6 | P2 | 79 | Same unescaped `document.write` pattern in other print helpers | VERIFIED (ReceiptPrint) / SUSPECTED (Incentives, Vouchers) | **New** |
| SEC-7 | P3 | 915 / 284 | Insurance billing group: PATCH can move a group into a *locked* claim (`claim` writable, lock checked on source only) | VERIFIED | **New** |
| SEC-8 | P3 | 922 | Portal session token in `localStorage` on the same origin as the staff SPA | VERIFIED | **New** |
| SEC-9 | P3 | 601 | Signed PBX recording link 302-redirects to a stored, editable `recording_url` | SUSPECTED | **New** |
| SEC-10 | P3 | 312 | TOTP shared secret stored in clear in `StaffProfile.mfa_secret` | VERIFIED | **New** |
| SEC-11 | P3 | 89 | Sybase SQL with f-string `branch_id` / `table_name` (finance queries) — not reachable from HTTP today | VERIFIED (not reachable) | Known (B608 baseline) |
| SEC-12 | P3 | 285 | RBAC still `log`; `matrix_allows` fails open on an unseeded module for legacy roles; production template ships `log` | VERIFIED | Known (D8 open, Z-5c) |

Counts: **P0 1 · P1 1 · P2 4 · P3 6** (12 findings; 7 new, 3 partly known, 2 known/accepted).

---

## Findings

### SEC-1 (P0) — Office signing key is the tracked placeholder; DEBUG keeps it
- **CWE-798 / CWE-321 / CWE-1188.**
- **Evidence**
  - `config/settings.py:81-83`
    ```python
    if not SECRET_KEY or SECRET_KEY.lower().startswith('change'):
        if DEBUG or _RUNNING_TESTS:
            SECRET_KEY = SECRET_KEY or 'dev-only-insecure-' + os.urandom(16).hex()
    ```
    With DEBUG=True a *non-empty* placeholder survives (`SECRET_KEY or …` only replaces an empty value). The
    comment at `:55-57` says DEBUG "falls back to a throwaway per-process key" — the code does not.
  - Office `.env` (main checkout on this PC): `DEBUG=True`, `SECRET_KEY` starts with `change` and is **byte-equal
    to the value in the tracked `.env.example:7`** (checked by equality, value not printed). `OMNI_CREDENTIALS_KEY`,
    `WHATSAPP_APP_SECRET`, `META_GRAPH_APP_SECRET` unset.
  - Everything signed from that key: SimpleJWT (no `SIGNING_KEY` set → `SECRET_KEY`, `settings.py:387-396`),
    media links (`core/storage.py:35-41`), portal magic/session tokens (`apps/portal/tokens.py`), delivery tracking
    (`apps/delivery/views.py:1432`), PBX recording links (`apps/pbx/recordings.py:39-49`), MFA pre-auth tokens
    (`apps/users/mfa.py:72-86`), and (no OMNI key) stored channel credentials.
  - `core/auth_cookies.py:81-91`: a forged access token passes `get_user` (active account, no `dev` claim → not revoked).
- **Exploit scenario:** anyone who can read the repo (GitHub) and reach the office server (LAN / ZeroTier / tunnel)
  mints an HS256 access token with `user_id` of an admin and calls any API — including the LIVE SOFTECH writers
  (ISR, A/P, insurance re-price) — or forges a portal session for any customer PIC or a signed link to any upload
  (prescriptions, IDs). Network/device/RBAC gates are in `log` mode and do not stop it.
- **Fix:** (1) set a real random `SECRET_KEY` on the office now (this logs everyone out once; re-key channel
  credentials with `manage.py omni_credentials --rekey` per G1 first, or set `OMNI_CREDENTIALS_KEY` to keep them
  readable); (2) make the guard replace *any* `change…` value in DEBUG too:
  `if DEBUG or _RUNNING_TESTS: SECRET_KEY = 'dev-only-insecure-' + os.urandom(16).hex()`; (3) consider a
  separate `SIMPLE_JWT['SIGNING_KEY']`; (4) turn DEBUG off on the office (see SEC-4).
- **Regression test:** run `python -c "import django; …"` in a subprocess with `DEBUG=True SECRET_KEY=change-me-x`
  and assert `settings.SECRET_KEY != 'change-me-x'`; plus a deploy check (`check --deploy` rule) that fails when
  `SECRET_KEY` equals the `.env.example` value.

### SEC-2 (P1) — Stored XSS from the customer portal into the staff receipt popup
- **CWE-79.**
- **Evidence**
  - Source (anonymous-ish external user with a magic link): `apps/portal/serializers.py:30,33` accept
    `manual_item_name` (500 chars) and `notes` (1000) free text; `apps/portal/views.py:318-327` stores them on a
    `Reservation` (`contact_name` = customer name too).
  - `apps/reservations/serializers.py:165` — `item_name` returns `manual_item_name` when no catalog item.
  - Sink: `frontend/src/pages/ReservationDetailPage.jsx:206-300` `printCustomerReceipt` builds HTML by template
    string with **no escaping** — `${allItems[0].name}` (`:247`), `${it.name}` (`:252`), `${r.contact_name}`,
    `${r.contact_phone}`, `${r.branch_name}` — then `window.open('', …)` + `w.document.write(...)` (`:260-262`).
    An `about:blank` popup opened by the SPA shares the SPA's origin. Button at `:1869`.
- **Exploit scenario:** a customer submits a reorder whose item name is HTML with an event handler; when staff
  click "print receipt" the handler runs on the app origin and can call `/api/*` with the staff member's cookies
  (adding `X-Requested-With` itself), e.g. create orders, read customer data, change records. Cookies are httpOnly
  so the token itself is not stolen, but the session is fully usable. CSP is report-only (SEC-5).
- **Fix:** escape every interpolated value (reuse the `esc()` from `components/HRPrint.jsx:30` or
  `UsageSlipPrint.js:9`, ideally one shared `utils/html.js`), or build the popup DOM with `textContent`.
  Server side, optionally strip `<>` from portal free text.
- **Regression test:** Vitest — call `printCustomerReceipt` with `manual_item_name = '<img src=x onerror=…>'` and a
  stubbed `window.open`; assert the written HTML contains `&lt;img` and no `<img src=x`. Add a lint rule /
  grep test that fails on `document.write(` with a `${` not wrapped in `esc(`.

### SEC-3 (P2) — Chatter POST ignores the branch scope that GET enforces
- **CWE-639 (IDOR / BOLA).**
- **Evidence:** `apps/notifications/views.py:749-763` (list) checks `_get_record_branch_id` + `branch_scope.allows`;
  `chatter_post` `:821-905` checks only `module_allows` and the model allow-list, then creates the message for any
  `record_id`. The socket path (`chatter_access.can_use_thread`) does check the branch. Tests only cover the list
  (`apps/tests/test_notifications.py:329`). Baseline `apps/tests/security/baselines/open_to_all_staff.txt:39`
  lists the POST as own-data.
- **Exploit scenario:** a branch-A pharmacist posts (text, image, PDF, voice note, `@mentions`) into the thread of a
  branch-B reservation / transfer / invoice / voucher by changing the id; the message is pushed live to branch B and
  can mention-notify anyone.
- **Fix:** run the same branch check as `chatter_list` (better: call `can_use_thread(request.user, model_name,
  record_id)` in both views and 403 when False).
- **Regression test:** in `test_notifications.py`, a branch-scoped user POSTs to another branch's reservation
  chatter → 403 and no `ChatterMessage` row.

### SEC-4 (P2) — DEBUG=True switches off webhook signatures and mounts `/admin/`
- **CWE-347 / CWE-489.**
- **Evidence:** `apps/whatsapp/views.py:72-78` `return bool(settings.DEBUG)` when `WHATSAPP_APP_SECRET` is empty;
  `apps/social/views.py:43-55` same for Meta; `config/settings.py:51` `DJANGO_ADMIN_ENABLED` defaults to `DEBUG`,
  mounted at `config/urls.py:91-92` (admin has no 2FA, N0/H9). Office: DEBUG=True, both app secrets unset.
- **Exploit scenario:** whoever reaches the office webhook URL posts forged inbound WhatsApp / Messenger events
  (fake customer messages into the call-centre inbox); `/admin/` offers a password-only login that bypasses 2FA.
- **Fix:** run the office with DEBUG=False (it is the writer server) — it then also needs a real key (SEC-1); make
  the webhook fail-open depend on an explicit `WEBHOOK_ALLOW_UNSIGNED` dev flag, not DEBUG.
- **Regression test:** `override_settings(DEBUG=True, WHATSAPP_APP_SECRET='')` → unsigned POST to
  `/api/whatsapp/webhook/` answers 403 unless the dev flag is set.

### SEC-5 (P2) — CSP is report-only
- **CWE-693.** `deploy/nginx.conf:170` `Content-Security-Policy-Report-Only "… script-src 'self' …"`.
  Once enforced, `script-src 'self'` (no `'unsafe-inline'`) would block the inline handlers SEC-2/SEC-6 rely on.
- **Fix:** move to enforcing after reviewing `/api/csp-report/` volume. **Test:** `test_go_live`-style assertion on
  the nginx file once flipped. **Known:** W-9 started report-only on purpose.

### SEC-6 (P2) — Other unescaped print popups
- **CWE-79.** `frontend/src/components/ReceiptPrint.jsx:258,313,331,383,461` (contact name, item name, notes,
  transfer notes) written via `document.write` at `:496,:513` with no escaping — `printReservationReceipt` has no
  caller today (latent), `printTransferReceipt` carries staff-typed notes. `pages/IncentivesPage.jsx:1832` and
  `pages/VouchersPage.jsx:1048` use the same pattern (content not fully traced — SUSPECTED). Safe examples:
  `HRPrint.jsx` (`esc`), `UsageSlipPrint.js` (`esc`), `ShelfQrButton.jsx:32` (strips `<`).
- **Fix/test:** as SEC-2; one shared escape helper and a repo test that every `document.write` template escapes.

### SEC-7 (P3) — Billing group can be moved into a locked insurance claim
- **CWE-915 / CWE-284.** `apps/insurance/views.py:3082-3093` serializer `fields` include `'claim'` (writable);
  `update` `:3133-3135` checks only the group's *current* claim (`_group_locked(self.get_object())`).
- **Scenario:** an insurance user PATCHes an open claim's group with `claim=<submitted claim id>`, adding a group
  (and its filters) to a claim that should be frozen; exports by group of the locked claim change.
- **Fix:** make `claim` read-only on update (or check the target claim's lock too) and audit the move.
- **Test:** PATCH `{claim: locked.pk}` on a group of an open claim → 423/400; group stays on the open claim.

### SEC-8 (P3) — Portal session token in localStorage, same origin as staff
- **CWE-922.** `frontend/src/portal/portalApi.js:13,28`. Any XSS on the origin (SEC-2) can read customer portal
  sessions (12 h). **Fix:** httpOnly cookie scoped to `/api/portal/`, or a separate sub-domain for the portal.
  **Test:** frontend test that the portal client never writes `localStorage`.

### SEC-9 (P3) — Open redirect from a signed recording link
- **CWE-601.** `apps/pbx/views.py:399-401` `HttpResponseRedirect(recordings.resolve_remote_url(session))`, which
  returns `session.recording_url` verbatim (`apps/pbx/recordings.py:96-99`); `core/safe_fetch.py` says this URL is
  editable by the call centre / named by a PBX webhook. Link needs a valid signed token, so impact is small.
  **Fix:** redirect only to `PBX_RECORDINGS_URL_BASE` hosts, otherwise proxy via `safe_fetch`.
  **Test:** session with `recording_url='https://example.invalid/x'` → no 302 to that host.

### SEC-10 (P3) — TOTP secret in clear
- **CWE-312.** `apps/users/models.py:242` `mfa_secret = CharField(...)`. A DB dump / backup gives every user's
  second factor. **Fix:** encrypt with the same Fernet helper as channel credentials (`OMNI_CREDENTIALS_KEY`-style
  key). **Test:** saved row's column ≠ base32 secret; `verify_totp` still passes.

### SEC-11 (P3) — Sybase SQL built with f-strings (latent)
- **CWE-89.** `apps/finance/queries/sybase_finance.py:428,475,526,574,742,811,923,1030` (`branchcode = '{branch_id}'`),
  `sybase_discovery.py:220,264` (`'{table_name}'`). Callers today pass no `branch_id` (`finance/engine/sync_engine.py`)
  or are management commands — not HTTP-reachable. POS / invoice writers build inline literals but escape `'`
  (`apps/pos_orders/writer.py:996-1020`, ASE has no backslash escape). **Fix:** bound `?` params when next touched.
  **Known:** B608 baseline; R5 fixed the one reachable case (typed supplier code).

### SEC-12 (P3) — RBAC log mode and fail-open edges
- **CWE-285.** `config/settings.py:1123` default `log`; `deploy/production.env.example:29` `RBAC_ENFORCEMENT=log`.
  `core/permissions.py:121-125` `matrix_allows` returns True for an unseeded module (legacy roles).
  Middleware enforce-mode safety net uses a *global* "seeded" flag (`module_access.py:498-501`).
- **What log mode exposes today:** little, because view-level `RouteModulePermission` (`core/permissions.py:215`)
  asks the matrix independently of the mode and the R3/R4 sweep put it on every module view. What remains open is
  by design: exempt prefixes with their own gates (verified below), the staff picker, and any module whose rows are
  missing from `RoleModuleAccess` (fail-open). **Known:** D8 open, owner decision after go-live.

### Note (not a vulnerability) — approvers cannot reach other people's requests
`apps/approvals/views.py:54-66`: for any role except admin/supervisor `get_queryset` returns only the caller's own
requests, so `decide` (`:105`, `get_object`) 404s for a pharmacist / purchasing / quality approver on someone
else's request, while `pending/` lists it. Over-restrictive, not a leak; worth a functional check.

---

## Exempt / weak-route verification (each read in the view)

| Prefix / app | Weak routes | Gate found | Verdict |
|---|---|---|---|
| `help` (28) | IsAuthenticated | read for all; trainer edits check help/edit (per middleware comment) | by design (not deep-read) |
| `pic-analytics` (29) | IsAuthenticated | `apps/pic_analytics/access.py` `Access`: mgmt via matrix, named grants own-branch only, calls tabs mgmt-only, export jobs owner-only (`views.py:553-559`) | OK |
| `gamification` (26) | IsAuthenticated | `_can()` = `can_do('gamification', …)` on every manage/adjust/fulfil/crown (`views.py:40,228-797`); redemption cancel owner-or-edit | OK |
| `hr-attendance` (26) | IsAuthenticated | `@gate('view'|'manage'|'admin')` on every view; export checks `can_export` (`attendance/views.py:48-62,237-241`); company-level by design | OK |
| `hr` (mapped) | — | `RouteModulePermission` / `_ManagerWrites`; querysets own-or-manager | OK |
| `notifications` (22) | IsAuthenticated | own-recipient filters on read/snooze/delete/bulk; reminders `owner=profile`; announcements author/admin | OK except **SEC-3** |
| `users` / `auth` (20) | IsAuthenticated/AllowAny | staff CRUD admin-only via `get_permissions`; list = slim picker; matrix GET/POST admin-only | OK |
| `stock-audit` (16) | IsAuthenticated | `Access` + `acc.scope()` / `allows_branch` on detail & review | OK |
| `personal` (14) | IsAuthenticated | widgets/identities `staff=profile`; review admin-only; person search throttled+audited, parameterised, names/codes only | OK |
| `stockcount/daily` (10) | IsAuthenticated | counter owns pick (`assigned_to`/`recount_by`); reviewers via stock-audit `Access.scope` | OK |
| `usage-print` (5) | IsAuthenticated | flag + matrix `_access`; `branch_scope.allows` on sheet/line | OK |
| `counselling` (5) | IsAuthenticated | `CanViewPos`/`PosCreate` in `get_permissions`; branch check on send | OK |
| `cheques` (3) | IsAuthenticated | `deny_unless(…approve/finalize)` + `branch_scope.get_or_404` | OK |
| `pbx/recordings` | none | signed 1 h token | OK (see SEC-1, SEC-9) |
| webhooks | none | HMAC / secret token, constant-time compare | OK in prod; **SEC-4** in DEBUG |
| `portal` | AllowAny | throttled per phone + IP, single-use nonce, session row revocable, customer resolved server-side | OK |
| `demand/public`, `public/*` | AllowAny | throttled + `core/public_guard`, always-200 answer | OK |

## What is solid (evidence)

- **Token handling:** JWT only in httpOnly, `SameSite=Strict` cookies; refresh cookie scoped to `/api/auth/`;
  cookie writes require `X-Requested-With` (`core/auth_cookies.py:28-79`); disabled accounts and revoked devices
  refused per request (`:81-91`); refresh rotation + blacklist (`settings.py:392-395`); password change / reset /
  disable end sessions (`apps/users/views.py:520`, reset, toggle).
- **Login:** DRF throttle 10/min + nginx `auth` zone 5 r/m, account lockout with indistinguishable unknown-user
  handling (`apps/users/views.py:184-228`), 10-char password policy; 2FA pre-auth tokens single-use with try cap
  (`apps/users/mfa.py:303-345`); backup codes hashed.
- **Separation of duties** in approvals (`apps/approvals/service.py:128-132`).
- **Media:** signed, expiring URLs; traversal-safe path; allow-list of inline types, everything else
  `sandbox` + attachment (`core/media.py`, `core/storage.py`).
- **SSRF:** `core/safe_fetch.py` checks every resolved address and every redirect hop; the remaining `urlopen`
  calls (`apps/enrichment/ai_extractor.py:256,354,454`, `apps/images/searcher.py:46`) hit fixed public hosts with
  quoted query terms — not user-chosen URLs.
- **Settings guards:** non-DEBUG refuses placeholder keys, explicit `ALLOWED_HOSTS`, HSTS, nosniff, `X_FRAME_OPTIONS=DENY`,
  upload size cap handler, import row cap, log redaction installed on the record factory (`settings.py:505-506`).
- **Object scoping** on POS orders (`apps/pos_orders/views.py:90-99`, idempotent replay checks branch `:110-131`),
  payments (`BranchScopedMixin` + editable-state gate `apps/payments/views.py:96-125`), insurance claims (no generic
  PATCH, lock 423), cheques, usage print, stock audit.
- **Exports:** `core/export_safety.py` neutralises formulas; the remaining unguarded `save()` hits are PNG / DOCX.
- **No dangerous primitives** reachable: no `pickle`/`yaml.load`/`eval`; `subprocess` only launches our own
  `manage.py` jobs with fixed args.
- **Tracked secrets:** only `.env.example` / `deploy/*.env.example` (placeholders) are tracked; a tracked-secrets
  baseline test exists (`apps/tests/security/baselines/tracked_secrets.txt`).
