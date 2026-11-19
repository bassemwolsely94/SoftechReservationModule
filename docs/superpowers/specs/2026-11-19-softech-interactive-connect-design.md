# SOFTECH connect for screens — fail fast, skip dead nodes

**Status:** DRAFT for owner approval (2026-11-19). Small change. Read-only behaviour only; no SOFTECH
write path changes. Part of the performance boost (`2026-11-19-performance-boost-design.md`, §2:
"no single user … slows everyone").

## Why

`GET /api/usage-print/sheet/` took up to 132 s (slow log, `07_PERFORMANCE_AUDIT.md` §6.1). When the
mirror misses an invoice it reads SOFTECH live: branch node first, then HQ
(`apps/usage_print/lookup.py:97-110`). Every connect in `config/sybase.py` uses the scheduler's
profile: `LOGIN_TIMEOUT` 15 s × `SYBASE_CONNECT_ATTEMPTS` 3 + 2 × 1.5 s pauses ≈ **48 s per dead
node** before the next node is even tried. That profile is right for background syncs over the flaky
branch VPN (retries smooth over transient failures). It is wrong for a person waiting on a screen, and
a web thread held for 1–2 minutes is a thread no other user gets.

Measured (SoftechLoadStat, last 7 days, office): 29,442 connects, average **~1.0 s** (HQ 0.9 s,
branches 0.8–1.9 s), failures 1–5 % per node.

## Approaches

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| **A** | An opt-in **interactive connect profile** for reads made inside a web request: login timeout 5 s, 1 attempt, plus a short **dead-node memory** (a node that just failed is skipped for 60 s) | Callers opt in one by one; schedulers untouched | **Recommended** |
| B | Lower the global timeout / attempts | Also hits every sync over the flaky VPN → more failed syncs and stale data | Rejected |
| C | Auto-detect "in a web request" and switch profile everywhere | Also changes writer connects (POS push, discount and insurance writebacks) without review | Rejected |

## Design (A)

- `config/sybase.py`: `get_sybase_connection(…, interactive=False)` and
  `get_branch_connection(…, interactive=False)`. With `interactive=True`: `LOGIN_TIMEOUT` =
  `SYBASE_INTERACTIVE_LOGIN_TIMEOUT` (default **5 s**), attempts = `SYBASE_INTERACTIVE_CONNECT_ATTEMPTS`
  (default **1**), no pause. Defaults (`interactive=False`) are exactly today's behaviour.
- **Dead-node memory:** after an interactive connect fails, remember the node (host:port) for
  `SYBASE_DEAD_NODE_SECONDS` (default **60 s**, in the shared cache, so all web processes see it once
  Stage 2 Redis is on). An interactive connect to a remembered node raises at once
  (`SoftechNodeUnavailable`, a subclass of the existing connect error), so callers' existing
  `try/except` fallbacks keep working. Background (non-interactive) connects ignore the memory and
  never write it, so syncs behave exactly as today. A successful interactive connect clears it.
- `DriverManager.setLoginTimeout` is process-global today; the interactive path relies on the
  per-connection `LOGIN_TIMEOUT` property only and does not change the global value.
- Telemetry unchanged: each attempt still goes through `record_connect`; the skip is logged once per
  node per window, with no secrets or phones (`core/errors.public_error`).
- **Callers in this change:** only `apps/usage_print/lookup.py` (read-only invoice lookup). Other web
  views that read SOFTECH live (`catalog`, `delivery`, `transfers`, `isr_views`, `coupon_views`,
  `finance/recon_views`) are listed for a follow-up, one by one, after this lands. **Writer paths
  (`discount_approvals`, insurance re-price, POS push) are excluded**: they stay on today's profile.
- Worst case for usage-print after the change: dead branch 5 s (or 0 s when remembered) + HQ connect
  ~1 s + query ≤ 15 s; a dead HQ with a dead branch fails in ≤ 10 s with the existing "could not
  reach SOFTECH" message instead of after ~2 minutes.

## Tests

- Interactive connect: one attempt, `LOGIN_TIMEOUT` property = 5, no sleep (mock driver raising).
- Default connect: still 3 attempts with the 1.5 s pause (existing behaviour pinned).
- Dead-node memory: failure → next interactive call raises `SoftechNodeUnavailable` without calling
  the driver; after expiry it tries again; success clears it; non-interactive calls ignore it.
- usage-print lookup with a dead branch falls through to HQ and returns the HQ result; both dead →
  the existing error response, no 500.
- The SOFTECH static guards in `apps/tests/security/` still pass (no raw connects, no new writes).

## Out of scope

Write paths; sync jobs; the other web callers (follow-up); the query timeout (15 s) itself.
