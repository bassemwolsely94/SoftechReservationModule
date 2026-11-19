# 39 · POS server-side checkout (D-18 / FE-3) — design + test plan

Status: **APPROVED 2026-11-19 ("Yes, start the build") — BUILT behind `POS_SERVER_CHECKOUT=False`.** See §9 for what the build decided where this document left a choice. Owner confirms before merge.
Decision: D-18 in `docs/full-project-audit/14_DECISION_REGISTER.md`; finding FE-3 in `05_FRONTEND_UX_AUDIT.md`.
Owner choice 2026-11-19: "Design first", then build behind a switch.

---

## For the owner — the short version

**What happens today.** When the cashier presses «إرسال», the browser sends up to six requests one
after another: create the order, upload the prescription photo, apply offers, re-read the order, set the
payment split («نقدى / آجل»), and send it to SOFTECH. The browser itself adds up the money to decide how
much is نقدى and how much is آجل.

**Why change it.** Our rule is "the server owns the money". Today, if the network drops in the middle,
an order can be left half done (created, offer already attached, never sent). And the browser does the
sums with ordinary decimals, so the payment split can be off by a piaster from the server's own total,
which then rejects the sale with a confusing message.

**Is there a double-posting risk today?** No new one. The SOFTECH writer already refuses to post the same
order twice (the order's own token, the `vf2` tag in SOFTECH, the "only one sender at a time" lock, and the
"outcome unknown — check SOFTECH first" rule from Wave 1). This design **keeps all of those exactly as they
are**. It does not change how we write to SOFTECH.

**What we propose.** One new server call, «checkout», that does all the steps in one go: it builds the
order, applies offers, computes the prices and the نقدى/آجل split itself, checks everything, and only then
hands the order to the existing SOFTECH writer. Either the whole preparation succeeds or nothing is saved.
The screen shows the server's totals (from a "preview" call) instead of computing its own.

**How it is switched on.** A new switch, `POS_SERVER_CHECKOUT`, **OFF by default**. While it is OFF the
screen works exactly as today. The old path stays in the code until the new one has run cleanly for
weeks. Turning the switch OFF again is the whole rollback.

**What you will be asked to approve, and when** (section 7 lists them all):
1. This design.
2. The rule when the price changed between what the cashier saw and what the server computes (we
   recommend: stop and show the new total; never post silently).
3. A golden-template comparison against a real SOFTECH sale, done by a person, with your approval for
   each run (the same "rollback probe" method used for the writer — nothing is saved in SOFTECH).
4. Switching it on for one branch, then for all.

---

## 1. Today's sequence and where it can fail

Source: `frontend/src/hooks/usePosOrder.js` `submit()` (lines ~1489–1636) and `apps/pos_orders/views.py`.

| # | Browser request | Server code | What it does |
|---|---|---|---|
| 1 | `POST /api/pos-orders/` with `client_token` | `OrderListCreateView.create` / `perform_create` | Idempotent create by `client_token` (unique). Channel RBAC. Seller forced to own usercode unless privileged. Return: `build_return_from_sale` mirrors the sale. Status `draft`. |
| 2 | `POST /api/pos-orders/<id>/prescription/` (multipart, only if a photo) | `upload_prescription` | PG-only metadata. Errors swallowed. |
| 3 | `POST /api/offers/apply-to-order/ {commit:true}` (sales only) | `apps/offers/views.apply_to_order` | Gated by `POS_OFFERS_EXECUTION_ENABLED`; **commits** offer discounts onto the lines. Errors swallowed by the browser. May return `requires_approval` → browser stops before step 5. |
| 4 | `GET /api/pos-orders/<id>/` (only if an offer attached, retail) | `OrderDetailView` | Browser sums `trans_price_total` as floats (`freshNet`) and calls `rebalanceToNet` to rebuild the نقدى tender. |
| 5 | `POST /api/pos-orders/<id>/ready/ {tenders}` (returns send `{}`) | `ready_order` → `writer.prepare_order` (row-locked, atomic) → `validate_order` → contract-discount role rule → live discount-authority read (writer on only) | Computes all money fields with `pricing.compute_line/compute_header` (Decimal, ROUND_HALF_UP), resolves tenders via `pricing.split_payment`, checks Σtenders = docvalue − خصم فكة within 0.01, rebuilds payment rows. Status `ready`. |
| 6 | `POST /api/pos-orders/<id>/push/ {dry_run:false, confirm:true}` | `push_order` → offer-approval gate → `validate_order(for_push=True)` → confirm token → offer usage pre-check → `writer.push_order` → audit → `consume_offer_uses` | The writer path described in §2.4. |

### 1.1 Failure points

**F1 — half-done orders (real, common on a bad network).** Each step commits on its own. A drop after
step 1 leaves a `draft`; after step 3 a draft **with an offer discount already committed**; after step 5 a
`ready` order with tenders. Nothing cleans these up automatically; the cashier retries with the same
`client_token`, which returns the existing order and re-runs steps 3–6 on it (works, but by luck of each
step being re-runnable, not by design).

**F2 — browser-computed tender (real).** The نقدى/آجل amounts come from browser float maths:
`totals` (`usePosOrder.js` ~558–590, `toFixed(2)` on floats), `setPatientCopay` (~1242), and after an offer
`rebalanceToNet` (~177) over `freshNet` (a float sum of line totals). The server's Decimal total can differ
by a piaster (classic `1.005` cases). Outcome: either a confusing «مجموع طرق السداد لا يساوي المطلوب»
rejection, or — because the balance check allows **±0.01** (`writer._prepare_order_unlocked`,
`validators.validate_order`) — a sale posted with payment rows that differ from `docvalue` by one piaster.
The second case is SUSPECTED, not observed; the test plan (§4.2) measures it.

**F3 — swallowed offer failure (real, by design today).** If step 3 errors, the sale goes ahead without the
offer and the cashier is not told. Acceptable while offers are OFF; not acceptable once they are ON.

**F4 — the double-post window (protected today, kept protected).** There is no window in our code that
posts twice; the protections live in the writer and in `push_order`, not in the browser:

| Guard | Where | Protects against |
|---|---|---|
| `client_token` unique + get-or-create | `OrderListCreateView.create` | A replayed create making a second order |
| Row lock + "status unchanged" check | `writer.prepare_order` | A stale tab re-preparing an order that a flush job just pushed |
| Already pushed → return the docnumber | `writer.push_order` (top) | Retry of a landed order |
| Atomic claim `UPDATE … SET status='pushing' WHERE status IN (…)` | `writer.push_order` (P-11) | Two senders (button + flush job + command) writing the same order |
| `vf2 = 'POS<pk>'` lookup in `stktransm5` before insert | `_pending_docnumber_by_vf2` | Commit landed, reply lost, order still pending at the cashier |
| `outcome-unknown:` marker, never auto-retried; only «راجعت SOFTECH ولم يُحفظ» re-pushes | `push_order` + S-1 | Commit landed and the cashier already settled it (SOFTECH drops `vf2` on the final document) |
| Confirm token | `views.push_order` | Fat-finger live write |
| `writer_allowed('POS_WRITER_ENABLED')` | `config/writers.py` | Any write from a non-writer instance |

The only browser-side contributor is a double click / two tabs: the second submit reuses the same order and
ends in a confusing error after the first one posted (the second `ready` hits "status changed"). No double
post, but a frightening message for the cashier.

**F5 — no tests on the orchestration.** None of the Vitest files cover `usePosOrder`; the backend tests
cover each step alone, not the sequence.

---

## 2. Proposed design: one `checkout` endpoint

### 2.1 Endpoints

```
POST /api/pos-orders/checkout/preview/   → prices only; saves nothing
POST /api/pos-orders/checkout/           → prepare (one PG transaction) + push (existing writer)
```

Both live under the existing `pos-orders` prefix, so `core/middleware/module_access.py` already maps them to
module `pos`. Permissions: `preview` = `CanOperatePosOrders`; `checkout` = `CanOperatePosOrders` for the
prepare phase **and** `CanPushPosOrders` before the push phase (checked inside the view, same as today's two
endpoints; a user with only operate rights gets the order prepared and a 403 for the push part, exactly what
they get today).

### 2.2 Request

The body is today's create payload (unchanged field names, so the serializer is reused) plus a small
checkout block. **The browser no longer sends tender amounts; it sends the cashier's intent.**

```jsonc
{
  "client_token": "7c0e…",          // REQUIRED for checkout; the idempotency key (§2.5)
  "branch": 130, "channel": "cash", "doc_kind": "sale",
  "customer": 1234, "softech_pic": "130HD8007", "seller_usercode": "…",
  "change_discount": 0.25, "lines": [ … same as today … ], "claim": { … }, "return_lines": [ … ],

  "checkout": {
    "mode": "dry_run" | "live",       // live also needs confirm=true (anti-fat-finger, as today)
    "confirm": true,
    "expected_due": "412.75",          // the amount the cashier SAW in the preview (string, 2 dp)
    "tender_intent": {                 // one of:
      "kind": "default"                //   channel default (cash = all نقدى; contract/employee/platform = rules)
      // "kind": "credit_portion", "credit": "100.00"   // آجل fixed, نقدى absorbs the rest
      // "kind": "patient_copay", "patient": "50.00"    // claim channels: ما يسدده المريض; blank → contract rule
    },
    "tender_extras": { "currency": "L.E", "exchange_rate": 1, "internal_payserial": "" }
  }
}
```

Tenders stay **نقدى / آجل only** (locked scope, "POS screen scope decisions"); card/cheque details remain on
the SOFTECH cashier screen. Returns ignore `tender_intent`: the refund is the sale's own payment rows
(`build_return_from_sale`), as today.

### 2.3 Response

```jsonc
{
  "order_id": 98765,
  "status": "pushed" | "queued" | "ready" | "push_failed" | "awaiting_offer_approval",
  "replayed": false,                       // true when the client_token already finished (§2.5)
  "totals": {                              // authoritative, Decimal → string, 2 dp
    "gross": "450.00", "discount": "37.00", "tax": "0.00", "net": "413.00",
    "change_discount": "0.25", "due": "412.75",
    "patient_pays": "0.00", "claim_amount": "0.00"
  },
  "tenders": [ { "pay_type": "cash", "amount": "412.75" } ],
  "offers": { "enabled": false, "attached": false, "requires_approval": false },
  "softech": { "mode": "commit", "docnumber": 7901, "wrote_to_softech": true },   // = writer.push_order result
  "plan": { … }                            // dry_run only, as today
}
```

Errors keep today's shape (`{detail, errors}`) so the screen's error list works unchanged. New codes:

| HTTP | When | Body flag |
|---|---|---|
| 409 | Server `due` ≠ `expected_due` | `totals_changed: true` + fresh `totals`/`tenders`; **nothing saved** |
| 409 | `client_token` reused with a different basket | `token_reused: true` |
| 202 | Same `client_token` is mid-push | `busy: true` (writer's own `mode: 'busy'`) |
| 202 | Branch unreachable → queued | `queued: true` (unchanged) |
| 409 | Offer needs supervisor approval | `requires_offer_approval: true`; order kept `draft`, not pushed |

The preview endpoint returns the same `totals` + `tenders` + `offers` blocks, and `ready_errors` (the
validation messages `ready` would give), but no `order_id`.

### 2.4 Server flow

```
checkout(request):
  0. auth + channel RBAC + branch scope            (same helpers as create: _staff, can_pos_channel, branch_scope)
  1. token replay check (§2.5)                      → may return early, no work
  ┌─ PHASE A — one PostgreSQL transaction (transaction.atomic) ───────────────────────────┐
  │ 2. create the order via OrderSerializer + perform_create logic (incl. returns mirror)   │
  │ 3. offers: apply_offers_to_order(order, commit=True)   (sales only; flag-gated; errors   │
  │    ABORT the checkout when the flag is ON, instead of being swallowed — F3)             │
  │    requires_approval → save as draft, leave PHASE A committed, return 409 (no push)    │
  │ 4. tenders = pricing.resolve_tenders(channel, due, tender_intent)   ← NEW pure function │
  │ 5. writer.prepare_order(order, tenders=tenders, live=settings.POS_LIVE_PRICING)  UNCHANGED │
  │ 6. validate_order(order) + validate_contract_discount_role + validate_discount_authority│
  │    (the same calls ready_order makes today — moved into a shared helper, not copied)    │
  │ 7. compare order.due with checkout.expected_due → mismatch = raise → ROLLBACK all       │
  └─ commit ──────────────────────────────────────────────────────────────────────────────┘
  PHASE B — exactly today's push_order view body, moved into a shared helper:
  8. offer-approval gate → validate_order(for_push) → confirm check → offer usage pre-check
  9. writer.push_order(order, dry_run=…)                                        UNCHANGED
 10. _audit_pos(...) ; consume_offer_uses(...) on a real post                    UNCHANGED
 11. build the response from the saved order
```

**Why two phases and not "one transaction" end to end.** PostgreSQL and SOFTECH (Sybase) cannot share a
transaction. The writer's own design already relies on PostgreSQL rows being committed *before* the SOFTECH
write: its atomic claim (`status → pushing`) must be visible to the flush job, and its outcome-unknown marker
must survive a crash. Wrapping the SOFTECH write inside a PostgreSQL transaction would roll those markers back
on an exception after the SOFTECH commit — **re-opening the double-post window S-1 closed.** So:

- **Phase A is atomic**: any failure (validation, blocked contract item, discount authority, total mismatch,
  offers error) rolls back the order, its lines, the offer attachment and the payment rows. No half-done
  orders (fixes F1).
- **Phase B is the existing writer, untouched**: it leaves the order `pushed`, `queued`, `push_failed` or
  `push_failed + outcome-unknown`, exactly as today, and every existing recovery tool (flush job,
  `flush_now`, `reconcile_pos_orders`, cancel with `confirmed_not_landed`, the exceptions screen) works on it.

**Reuse, not duplication (CLAUDE.md rule 6).** The build moves the bodies of `ready_order` and
`push_order` (views) into two helpers in a new module `apps/pos_orders/checkout.py`:
`prepare_for_checkout(order, user, tenders)` and `push_for_checkout(order, user, live, confirmed)`. The old
views call the same helpers, so both paths run identical guards. `writer.py`, `pricing.compute_*`,
`pricing.split_payment`, `validators.py`, `discount_authority.py`, `apps/offers/*` are **not modified**.

### 2.5 Idempotency key

The key is the order's existing `client_token` (UUID, unique in `SoftechSalesOrder`). The browser already
creates one per cart (`cartTokenRef`, regenerated on reset) and it already doubles as the selection-telemetry
token, so no new client concept is needed. Checkout **requires** it (400 without it).

We do **not** use `core/middleware/idempotency.py` (`X-Idempotency-Key`): on replay it returns only a status
with no body, and the cashier needs the SOFTECH docnumber back.

Replay rules (step 1, under `select_for_update` on the existing row):

| Existing order with this token | Same basket? | Result |
|---|---|---|
| none | — | normal checkout |
| any, other branch outside the user's scope | — | 409 «client_token مستخدم» (as today) |
| `pushed` / `settled` | any | 200, `replayed: true`, the stored docnumber. **No writer call.** |
| `pushing` | any | 202 `busy` |
| `push_failed` with outcome-unknown | any | 409 with the writer's «راجع SOFTECH» message; only the existing manual path re-pushes |
| `draft` / `ready` / `queued` / `push_failed` | yes | skip Phase A's create, re-run prepare (row-locked) and Phase B (writer rules decide) |
| same | no | 409 `token_reused` — never silently overwrite a basket under an old token |

"Same basket" = a SHA-256 over the normalised request (branch, channel, doc_kind, customer, PIC, lines
[itemcode, qty, price, discount, batch, reservation], change_discount, tender_intent, return_lines). It is
stored in one new nullable PG column `checkout_request_hash` on `SoftechSalesOrder`. This is a PostgreSQL-only
column, not synced to or from SOFTECH (see stop-and-ask S2).

Double click / two tabs: both requests carry the same token. The second waits on the row lock, then follows
the table above (`busy`, or `replayed` with the docnumber). No confusing error, no second post.

### 2.6 Server-side tender split — `pricing.resolve_tenders`

A new **pure** function (no DB, no I/O) beside `split_payment`, all `Decimal`, ROUND_HALF_UP to 2 dp:

```
resolve_tenders(channel, doc_value, change_discount, intent, *, is_platform, copay_rule) -> list | None
  due = doc_value − change_discount
  platform              → [credit = due]                 (any other intent → ValueError, as today)
  intent default        → None                           (let prepare_order keep today's rules:
                                                           contract co-pay from personsdata, employee
                                                           100% آجل, cash/delivery/permanent 100% نقدى)
  credit_portion(c)     → 0 ≤ c ≤ due ; [cash = due − c] + [credit = c]   (drop a zero row)
  patient_copay(p)      → claim channels only; 0 ≤ p ≤ due ; [cash = p] + [credit = due − p]
```

Invariants (property-tested, §4.2): Σamounts = due exactly; no negative amount; no zero row; at most one
cash and one credit row; platform never has a cash row; the cash row is rounded and the credit row is
`due − cash` (so rounding can never break the sum). Returning `None` for `default` means `prepare_order`'s
existing co-pay and channel rules stay the single source of truth — the function does not re-implement them.

The ±0.01 tolerance in the balance check stays unchanged for the old path. On the new path the sum is exact
by construction; a test asserts `Σtenders == due` with zero tolerance for every new-path order.

### 2.7 Screen changes (when built)

- The totals panel calls `checkout/preview/` (debounced ~300 ms after a basket change, cancelled on the next
  change) and shows the server's `totals`. The browser `totals` memo is kept only as an instant placeholder
  while the preview is in flight, greyed, never sent.
- The نقدى/آجل fields edit the *intent* (`credit` or `patient` amount), not two free amounts.
- `submit()` with the switch ON = prescription upload stays a separate best-effort call (multipart, PG-only)
  **after** checkout returns the order id; then one `POST checkout/`. `rebalanceToNet` and the GET re-read are
  not used on this path.
- On `totals_changed`: show the new total in the existing message area (no modal — rule 11) and keep the
  basket; the cashier presses «إرسال» again.
- Help: `apps/help/content/` POS page gets a short Arabic + English paragraph on the new behaviour and the
  `totals_changed` message; `updated` date bumped.

---

## 3. The switch and the old path

- `POS_SERVER_CHECKOUT` in `config/settings.py`, `config('POS_SERVER_CHECKOUT', default=False, cast=bool)`;
  `False` in `settings_uat.py`; `True` in `settings_e2e.py` only for the Playwright job that tests it.
- Optional `POS_SERVER_CHECKOUT_BRANCHES` (comma list of branch ids; empty = all) for a one-branch rollout.
- It is **not** a SOFTECH writer flag: it adds no new write. The write is still gated by
  `writer_allowed('POS_WRITER_ENABLED')`. So it does not go into `config/writers.py` `WRITER_FLAGS` or the
  `softech_write_manifest.py` (stop-and-ask S6 confirms this reading).
- `reference_data` (already fetched by the POS screen) returns `server_checkout: true|false` for the user's
  branch. The hook picks the path from it at submit time.
- With the switch OFF the endpoints answer 404 `{detail: 'disabled'}` and the screen runs today's code
  byte-for-byte. The old endpoints (`/ready/`, `/push/`, `apply-to-order`) stay — they are also used by the
  queue screen, flush, exceptions and returns tooling.
- The old browser path is deleted only by a separate, later decision after at least 4 weeks clean on all
  branches (S8).

---

## 4. Test plan

### 4.1 Golden-template diff (person-run, owner approval per run)

Method: the one in the "POS writer golden-template verify" note and `writer.probe_order` /
`manage.py pos_probe` — the owner rings a real sale natively on the SOFTECH cashier and gives the pending
docnumber; we build the **same basket through the new `checkout` endpoint in `dry_run`**, then run the
rollback probe on that order (real inserts on the next serial, read back every field, **always rolled back**),
and diff header / every line / every payment row against the native row.

- Run by a person on the writer instance, `SOFTECH_PROBES_ENABLED` switch on only for the session (`require_probes`),
  off-peak, one branch, with the owner's written OK for each run.
- Baskets, one per channel already golden-verified for the old path: cash 1 item; cash strip (partial pack,
  `transqty = round(K/N, 5)`); cash with discount (points ⊻ discount → `vf4 = 0`); delivery mixed
  dispensed + reservation (`personnewbal = Σ vf4`); contract co-pay 25 %; contract 0 %; employee; permanent;
  platform (100 % آجل); one partial return.
- Pass = every field equal except the known time-dependent ones (`hour_of_day`, live FEFO batch moves, live
  price drift since the native sale — each named in the report).
- Extra check for this design: the same basket through the **old** path and the **new** path produces an
  identical `build_payload` plan (automated, §4.4) **and** an identical probe readback (manual, here).
- Output: `docs/architecture/39a_POS_SERVER_CHECKOUT_GOLDEN.md` with the diff tables.

### 4.2 Property tests on the tender split

`resolve_tenders` is pure, so it is tested with many generated inputs. `hypothesis` is not in
`requirements*.txt`; the plan uses a **seeded random generator in plain Django `SimpleTestCase`** (10 000 cases,
fixed seed, failing case printed) so no dependency is added (S7 if the owner prefers `hypothesis`).

Generators: `doc_value` from 0.01 to 99 999.99 including the edge set {0.005, 1.005, 2.675, 0.015, x.x5};
`change_discount` 0 to 0.50; intents of every kind with amounts below 0, 0, inside, equal to due, above due;
every channel; platform yes/no.

Properties: Σ = due exactly (Decimal equality); no negative or zero rows; ≤ 1 cash + ≤ 1 credit; out-of-range
intents raise `ValueError` with an Arabic message; platform never cash; idempotent (same input → same output);
`resolve_tenders` + `split_payment` + the balance check accept every output with **zero** tolerance.

Parity property (old vs new): for generated baskets run through `pricing.compute_line/compute_header`,
the browser formula ported to Python (float + `toFixed`) is compared with the server's Decimal total, and the
count of 1-piaster disagreements is reported. This measures F2 instead of guessing.

### 4.3 Concurrency and double-submit tests

PostgreSQL test DB, `TransactionTestCase`, real threads, writer mocked at the `_execute_write` /
`get_branch_connection` boundary (no SOFTECH). Run serially (never `--parallel`; see the PC-memory note).

1. Two threads, same `client_token`, same basket → exactly one `_execute_write` call; the other gets
   `busy` or `replayed` with the same docnumber.
2. Same token, different basket → second gets 409 `token_reused`; the first basket is untouched.
3. Checkout racing the flush job (`flush_pos_orders`) on a queued order → one writer call (P-11 claim).
4. Commit sent, reply lost (mock raises after `conn.commit`) → `push_failed` + outcome-unknown; a replayed
   checkout returns the «راجع SOFTECH» 409 and **does not** call the writer.
5. Pending recovered by `vf2` (mock returns a docnumber) → `idempotent_recovered`, no insert.
6. Failure in every Phase A step (serializer, offers error with flag ON, blocked contract item, discount
   authority, total mismatch) → no order, no lines, no payments, no `OfferApplication` row left (FE-3's
   "step 3 rolls back steps 1–2" test).
7. Offer requiring approval → order `draft`, writer not called, live push refused until approved.
8. Old and new path interleaved on the same token (old `ready` then new `checkout`) → still one post.
9. Permission matrix: operate-only user → prepared, 403 on push; other branch → 404/409; channel not allowed
   → 403; switch OFF → 404.
10. Business-rule test (security DoD #5): money fields of a new-path order equal the old path's for the
    same basket on every channel (dry run, `build_payload` compared key by key).

### 4.4 Automated parity (no SOFTECH)

`apps/pos_orders/tests/test_checkout_parity.py`: for a fixture set (one per channel + return + platform +
offer-attached + strip qty), run old path (create → ready → push dry_run) and new path (checkout dry_run) in
the same test DB and assert identical `build_payload` output, identical payment rows and identical
`doc_value*` fields. This is the gate before any person-run probe.

### 4.5 Playwright

New spec `frontend/e2e/pos-checkout.spec.js`, in the existing e2e job (`settings_e2e`: `POS_WRITER_ENABLED =
False`, so **every run is dry-run; Playwright never writes to SOFTECH**):

- switch ON: add 2 items → totals panel shows the preview's numbers → «إرسال» → one `POST checkout/` in
  the network log (no `/ready/`, `/push/`, `apply-to-order`) → dry-run plan shown;
- strip quantity (Q key) → preview due matches the plan's `docvalue`;
- contract co-pay: type ما يسدده المريض → tenders shown as returned by the server;
- `totals_changed`: test hook changes a price between preview and submit → message shown, basket kept,
  no order created;
- double click «إرسال» → one order id;
- network drop simulated (`page.route` aborting the checkout response) → retry with the same token returns
  `replayed`;
- switch OFF: the old request sequence still happens (regression guard).
- A Vitest test for the new hook branch (intent → request body; response → screen state).

### 4.6 Checks before each merge of the build

Backend tests for `pos_orders`, `offers`, `tests/security` (serially), `test_help`, coverage floor, `npm run
build`, Vitest, the Playwright job. Lint with no new `# noqa`/`# nosec`.

---

## 5. Rollout and rollback

| Stage | What | Who / gate | Exit criterion |
|---|---|---|---|
| 0 | Build behind `POS_SERVER_CHECKOUT=False`; old path unchanged | PR review, coordinator merges | All §4.2–4.5 tests green; switch OFF in every settings file except the e2e job |
| 1 | **Shadow**: switch still OFF; the screen also calls `checkout/preview/` and logs (server-side, no phone/PII) any difference between the browser's tenders and the server's | Owner OK to deploy | 1–2 weeks of logs; every difference explained |
| 2 | Golden-template probes (§4.1) on the writer instance | Person-run, owner OK per run | All channels match; report 39a committed |
| 3 | Switch ON for one branch (`POS_SERVER_CHECKOUT_BRANCHES=<id>`), live writer as today | Owner OK | 1 week: zero `totals_changed` surprises unexplained, zero new exceptions on `/pos-orders/exceptions/`, reconcile clean |
| 4 | Switch ON for all branches | Owner OK | 4 weeks clean |
| 5 | Remove the old browser path (keep server endpoints used by tooling) | Separate decision (S8) | — |

**Rollback** at any stage = set `POS_SERVER_CHECKOUT=False` (or remove the branch from the list) and restart
the web process. The next submit uses the old path. Orders made by the new path are ordinary
`SoftechSalesOrder` rows with the same statuses; the flush job, cancel, reconcile and the exceptions screen
handle them unchanged. The only schema change is one nullable column, which the old path ignores, so no
migration rollback is needed.

What rollback cannot undo: a sale already posted to SOFTECH. That is the same as today and is handled by the
existing cancel (pending) / return (settled) flows.

---

## 6. Out of scope

- Any change to `writer.py`, the SOFTECH payload, points (`vf4` / `personnewbal`), FEFO, strip quantity, or
  the contract co-pay rules.
- Card / cheque tenders (stay on the SOFTECH cashier screen).
- The mobile POS (it keeps the old endpoints until a separate decision).
- Making `POS_LIVE_PRICING` default ON (separate switch, separate decision).
- Changing the ±0.01 tolerance on the old path.

---

## 7. Stop-and-ask points

The build stops and asks the owner at each of these. Owner decisions so far (2026-11-19, "approved — go with your
recommendations on S3 and S4"; S2: "Yes, approve S2"): **S1, S2, S3, S4 approved**. Every other point is still open,
including S5 (each golden probe run) and S8 (rollout stages and removing the old path).

| # | Point | Why it needs the owner | Recommendation |
|---|---|---|---|
| S1 | Approve this design | Touches checkout (CLAUDE.md) | **Owner-approved 2026-11-19.** |
| S2 | Add the nullable PG column `checkout_request_hash` on `SoftechSalesOrder` | Schema change on the order table (PG only, not synced to SOFTECH) | Approve; alternative is comparing lines field by field, which is slower and easier to get wrong. **Owner-approved 2026-11-19** ("Yes, approve S2") — built: migration `0019_softechsalesorder_checkout_request_hash` |
| S3 | Rule when `due ≠ expected_due` | Decides whether a sale can post at a total the cashier did not see | **Block with 409 and show the new total.** Never post silently. **Owner-approved 2026-11-19** — built: `checkout._check_expected` in Phase A; `expected_due` required for a live send (B12) |
| S4 | Offers error with `POS_OFFERS_EXECUTION_ENABLED` ON: abort the sale, or post without the offer and say so | Sales vs promotion correctness | Abort with a clear message (the cashier can remove the offer item); today's silent skip hides lost discounts. **Owner-approved 2026-11-19** — built: `checkout._apply_offers` aborts the checkout (nothing saved) |
| S5 | Each golden-template probe run (§4.1) | Real DML on SOFTECH, then rolled back | Off-peak, one branch, person present |
| S6 | Confirm `POS_SERVER_CHECKOUT` is not a writer flag (no new SOFTECH write) | Security DoD #3 | Agree — the write stays behind `POS_WRITER_ENABLED` |
| S7 | Add `hypothesis` as a test dependency, or keep the seeded generator | New dependency | Keep the seeded generator |
| S8 | Each rollout stage 1, 3, 4, and the removal of the old browser path | Live checkout behaviour | As in §5 |
| S9 | Anything found during the build that would require changing `writer.py`, `pricing.compute_*`, `split_payment`, the balance tolerance, points or co-pay rules | Pricing / posting logic | Stop; separate decision |
| S10 | Any sign during tests of a path that could post twice | Rule 3 | Stop the build; report before continuing |

---

## 8. Files the build would touch (for estimating; nothing changed now)

- New: `apps/pos_orders/checkout.py` (helpers + two views), `apps/pos_orders/tests/test_checkout*.py`,
  `frontend/e2e/pos-checkout.spec.js`, a Vitest file for the hook branch.
- Changed: `apps/pos_orders/urls.py` (two routes), `views.py` (`ready_order`/`push_order` call the shared
  helpers — behaviour identical), `pricing.py` (add `resolve_tenders` only), `models.py` + one migration
  (S2), `config/settings*.py` (switch), `reference_data` (flag), `frontend/src/hooks/usePosOrder.js` (new
  branch in `submit`, preview call), the POS totals/tenders panel, `apps/help/content/` POS page,
  `PERMISSION_MATRIX.md` regenerated.
- Unchanged by design: `writer.py`, `validators.py`, `discount_authority.py`, `points.py`, `stock.py`,
  `apps/offers/*`, `config/writers.py`, `core/middleware/idempotency.py`.

---

## 9. Build notes (2026-11-19)

What was built, and every place the build had to choose. Nothing here changes the old path, `writer.py`,
`pricing.compute_*`, `split_payment`, the ±0.01 tolerance, the `vf2` tag or what SOFTECH receives.

| # | Point | What the build does | Why |
|---|---|---|---|
| B1 | Where the shared helpers live | `views._ready_checks` / `views._push_checks` (the old view bodies, lines unchanged) instead of `checkout.py` | Keeps the move line-for-line so PR 215 (D-11/D-12, which edits those bodies) still merges cleanly. `checkout.py` holds the endpoint and the orchestration. |
| B2 | Double click / two tabs | A PostgreSQL session advisory lock on the `client_token` (`pg_try_advisory_lock`, namespace 7301018) around Phase A + B; the second request answers **202 busy** at once | The row lock in §2.5 only exists once the order exists; two first submits would race on the unique index. The writer's PUSHING claim stays the real guard. |
| B3 | Tenders need the net before pricing | When the intent needs an amount (آجل / co-pay / خصم فكة), `prepare_order` runs once inside a **savepoint that is always rolled back** to learn the net, then for real with the resolved rows | Reuses prepare_order (live prices, contract discounts, blocked items) instead of re-implementing pricing. Costs a second branch price read only for those intents when live pricing is on. |
| B4 | `default` intent with خصم فكة | One row of the channel's default type (`credit` for contract/employee, else `cash`) for exactly the amount due. With no خصم فكة: `None` — today's rules, including the contract co-pay from personsdata | `split_payment`'s default is `doc_value`, which would fail the balance check when خصم فكة > 0 (true on the old path too). |
| B5 | `patient_copay` blank | Treated as `default` (the contract rule, i.e. 100 % آجل or the personsdata co-pay), as §2.2 says | The old screen showed a blank co-pay as "patient pays all"; on the new path the screen shows the server's split from the preview. |
| B6 | Offer needs approval | Stops before prepare **only for a live send** (order kept `draft`, 409); a dry run continues, as the old screen does. The push gate still blocks any live push of an unapproved offer | Matches today's dry-run behaviour. |
| B7 | An order made by the old path under the same token (no hash) | 409 `token_reused` unless it is already pushed/settled (then `replayed`) | Never takes over an order whose basket we cannot compare. |
| B8 | `cancelled` under the token | 409 `token_reused` | Not listed in §2.5. |
| B9 | Currency | Only L.E / rate 1 on the new path (anything else → 400) | Tenders are نقدى / آجل only. |
| B10 | Mobile POS | Uses the same hook but never opts in (`usePosOrder({allowServerCheckout})`, desktop page only) | §6: mobile keeps the old endpoints. |
| B11 | Rollout list | `POS_SERVER_CHECKOUT_BRANCHES` holds **SOFTECH branch codes** (e.g. `130`), like `POS_RESERVATION_BRANCHES` | Stable across databases; e2e turns it on for test branch `992` only. |
| B12 | Live mode without `expected_due` | 400 — the total the cashier saw is required for a live send | S3. |

**F2 measured** (`apps/tests/test_pos_checkout_tenders.py::BrowserVsServerTotalTests`, seeded): the browser's
float total differs from the server's Decimal total in **≈13 % of whole-pack baskets (worst 0.06)** and
**≈55 % of strip-quantity baskets (worst 0.05)**. Whole packs: `toFixed` on a float unit price misses the
half-piaster cases the server rounds up, ×qty, over several lines. Strips: the browser multiplies an
already-rounded unit price by the fraction without rounding the line. On the old path these show up as
«مجموع طرق السداد لا يساوي المطلوب» (> 0.01) or as payment rows one piaster off `docvalue` (≤ 0.01).

**Files:** `apps/pos_orders/checkout.py` (endpoints), `pricing.resolve_tenders`, `golden.py` + command
`pos_checkout_golden` (§4.1, prepared, not run), migration `0019_softechsalesorder_checkout_request_hash`,
`frontend/src/hooks/usePosOrder.js` (new branch; old `submit` body unchanged except the shared payload builder),
`frontend/e2e/pos-checkout.spec.js`, tests `apps/tests/test_pos_checkout*.py`.

**Golden probe — how to run (person, owner OK per run, off-peak, one branch, writer instance):**

```
python manage.py pos_checkout_golden --basket basket.json --user <seller> --plan-only          # no SOFTECH statement
SOFTECH_PROBES_ENABLED=True python manage.py pos_checkout_golden --basket basket.json --user <seller>     --native <pending docnumber> --live-pricing --confirm-rollback-probe --title "cash 1 item"
```

`basket.json` is the checkout request body (create payload + `checkout.tender_intent`). The command turns the
switch on for that process and branch only, runs the new endpoint in dry run, reads the native pending rows,
runs the writer's own `_execute_write` inside one transaction, reads our rows back, **always rolls back**, and
appends a field-by-field section to `39a_POS_SERVER_CHECKOUT_GOLDEN.md`.
