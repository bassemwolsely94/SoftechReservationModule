# R3 — enforce readiness (round 2, authorization)

Batch R3 of [the round-2 plan](../2026-11-05-full-project-test-plan.md) §7. Measured on a reader copy
(`WRITER_INSTANCE=False`, `SOFTECH_READ_ONLY=True`, worktree without `.env`), `manage.py test`, own
`TEST_DB_NAME`. Branch `claude/round2-r3r4-access-803ed1`.

## 1. Verdict

**RBAC_ENFORCEMENT can go to `enforce`.** Switching it changes the answer for exactly two
role × route pairs (below), neither called by any screen. Every other request the matrix denies is
already refused by the view itself in today's `log` mode (`role_leaks_log`), and `enforce` adds no leak
(`role_leaks_enforce` empty). The owner's switch, at the VPS cutover (owner decision 1).

## 2. Would-deny summary (what `enforce` changes)

| Role × route | Today (log) | Under enforce | Impact |
|---|---|---|---|
| pharmacist `POST /api/config/settings/by_key/` | answered (holds settings view) | 403 from the middleware (POST counted as a write) | none — no frontend caller (`configApi.byKey` is unused) |
| purchasing `POST /api/config/settings/by_key/` | same | same | same |

These are the only two lines of `role_leaks_log`, each with its reason (Z-4). If a screen ever
starts calling `by_key`, map it to `settings view` in `module_access.required()` first (an auth change:
stop-and-ask).

**Before flipping in production**, look at a few days of real would-deny lines (the sweep sees every
route, not what staff actually click):

```bash
grep "would-deny" logs/platform.log | awk '{print $NF}' | sort | uniq -c | sort -rn | head -50
```

Any line there for a role and screen that should work is a matrix gap to fix before `enforce`.

## 3. What R3 changed in the sweep

- **Real records behind detail routes (R3.1).** `sweep.seed_detail_paths()` plants one row per detail
  route that admin cannot reach with the dummy id (the canary `Planter`), picking the model by the
  view's queryset, then the app's models closest in name to the path, and keeping the first one admin
  actually reaches. RESULTS_SEEDED
- **Route catalogue fix.** DRF's `<drf_format_suffix:format>` api-root pattern rendered as
  `/api/<prefix>/x`, a path that does not resolve; it accounted for the `/api/config/x`, `/api/hr/x`,
  `/api/qa/x`, `/api/enrichment/x` unproven lines. `routes._render` now skips it.
- **Feature flags on (R4.3, used by R3 too).** The sweeps run with `sweep.FEATURE_FLAGS_ON`
  (daily counts, usage print, missed sales, missed-call call-backs, counselling content), so those
  screens are really checked instead of answering 503. Send and SOFTECH-write switches stay off.
- **Every view gated (R3.3).** `test_static_guards.EveryViewGatedTests`: a viewer with every matrix
  row off, in log mode, calls every protected route and method. Whatever still answers is open to all
  staff and is listed, with a reason, in `baselines/open_to_all_staff.txt`.
- **New-module cases (R3.4).** `test_named_grants.py`: PIC analytics + stock audit named grants
  (granted / ungranted / revoked / other branch, every route and method); counselling, tasks and
  missed sales (whole role sweep restricted to those prefixes, must be clean); usage print (own gate,
  flag on and off).
- **Break-in delta (R3.5).** `test_breakin_delta.py`.

## 4. Baselines

BASELINE_TABLE

## 5. `role_overblocks` by module and reason source (R3.2)

463 lines on `main` before R3, in 47 reasoned groups. None is unreviewed. Sources:

OVERBLOCK_TABLE

## 6. Matrix-vs-view questions for the owner

QUESTIONS

## 7. Break-in delta since 2026-11-03

| Added | Login / session / one-time code? | Test |
|---|---|---|
| `/api/public/counsel/<token>/` + opt-out (Project 4) | signed token, salt `counsel-card`, 90-day max age | existing `test_counselling_public` (tampered, expired, other salt, opt-out idempotent) + new cross-purpose replay (delivery-track / portal salts) |
| phone-alert «استلمت» tap `alert:<token>:ack` (Project 1) | random token in a WhatsApp quick reply | existing `test_phone_alerts` (other phone ignored, unknown token, duplicate tap no-op) |
| `/api/public/challenge/`, `/api/public/health/` (N6, go-live) | proof-of-work challenge (signed) | existing `test_access_public_gate`, `test_public_guard` |
| WebSocket groups | none new (only a `personal_group` robustness fix in `pbx/consumers.py`) | existing `test_access_ws_consumers` |
| every new staff route (counselling, finance/gl, usage-print, stockcount/daily, phone-alerts, missed-sales, pic-analytics, forecasting) | session (JWT) | new: anonymous caller refused on **every** protected route and method, public gate `off` and `enforce` |
