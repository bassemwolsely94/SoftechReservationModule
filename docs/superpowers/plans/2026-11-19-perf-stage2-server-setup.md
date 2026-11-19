# Performance Stage 2 — server setup (code half)

**Design:** `docs/superpowers/specs/2026-11-19-performance-boost-design.md` §6 Stage 2, §9, §10.
**Scope:** code + runbook only. Installing Redis databases, editing the VPS `.env`, enabling the
extra web processes and restarting anything are owner steps (runbook §13.6).

## What changes and why

| # | Change | Why |
|---|---|---|
| 1 | `config/cache_config.py` builds `CACHES` from env. No env → today's LocMem (dev, tests, office). `CACHE_REDIS_URL` + `LIMITS_REDIS_URL` → two Redis caches. | Three web processes must share one set of counters, or each process gets its own N3–N6 / login limits. |
| 2 | `default` alias = `core.cache_backends.FailOpenRedisCache`: a Redis error is a cache miss (get → default, add → True, incr → ValueError), logged at most once a minute. | §9: plain caches fail open — compute without the cache. |
| 3 | `limits` alias = `core.cache_backends.FailClosedRedisCache`: a Redis error raises `core.limits.LimitsUnavailable` (DRF `APIException`, 503, Arabic "try again shortly", code `limits_unavailable`). | §9: security counters fail closed. |
| 4 | Every security counter reads/writes `core.limits.limits_cache` (a proxy to `caches['limits']`): all DRF throttle classes (12), login unknown-identifier lockout, 2FA code replay + tries, public-form proof-of-work replay + per-phone daily caps (N6), bulk-read counters (N5). A guard test fails when a new throttle class forgets it. | One place; refusal flows through DRF's handler. |
| 5 | N5 bulk-read counting runs in middleware after the view: in `enforce`, a counter that cannot be written replaces the response with the same 503; in `log`/`off` it only logs (nothing is enforced there). | Fail closed only where a limit is actually enforced. |
| 6 | Log-dedupe keys (N3 zone log, N4 gate log, WS refusal log, public-path log) stay on `default`: they already swallow errors and limit nothing. | Not security limits. |
| 7 | Dev/test: `limits` is LocMem with the same LOCATION as `default`, so `cache.clear()` in existing tests still resets throttles. | No test churn. |
| 8 | `DB_CONN_MAX_AGE` env (default 0); `CONN_HEALTH_CHECKS` stays on. | §6. See the finding below before raising it on the VPS. |
| 9 | Web-only statement timeout: `WEB_STATEMENT_TIMEOUT_ENABLED` (default **off**), `WEB_STATEMENT_TIMEOUT_MS` (30000). A first-in-chain middleware marks the request thread; a `connection_created` receiver (and the middleware, for a connection already open on that thread) runs `SET statement_timeout` on `default` and `audit_log`. | §10: scheduler, management commands, background threads (PIC export, OCR) never get it. A process-wide `OPTIONS -c statement_timeout` would hit the web process's own background threads too. |
| 10 | A cancelled statement answers 503 with an Arabic "took too long" message instead of a bare 500. | Calm UI when the flag is on. |
| 11 | Runbook §6, §7.3, §8.2, §13.6: Redis DBs 1 + 2, `noeviction` on the limits DB (separate `redis-server@limits` instance or `maxmemory 0`), exact `.env` lines, install order, counting connections, when pgbouncer is an owner step. | §6 / §9. |

## Finding: `CONN_MAX_AGE` under Daphne

Django's ASGI handler runs each request inside its own `ThreadSensitiveContext`, and asgiref gives
each context a new single-thread executor (`asgiref/sync.py`, `context_to_thread_executor`). Every
HTTP request therefore runs on a fresh thread, and Django's DB connections are per thread. With
`CONN_MAX_AGE > 0` a connection is not reused by the next request (different thread); it stays
open until the dead thread is garbage-collected. Django's docs say the same: disable persistent
connections under ASGI and use a pooler. So the VPS line ships as `DB_CONN_MAX_AGE=0`; the knob
exists for a WSGI/pooled future. The real pooling path is pgbouncer (transaction mode) — an owner
step if the connection count under the load test does not fit (runbook §13.6).

Connections per web process ≈ in-flight HTTP requests (one thread each) + WebSocket DB calls
(Daphne's `ASGI_THREADS` executor) + background job threads. Budget: 3 processes × ~20 + scheduler
~5 + workbench ≤ `max_connections = 100`.

## Tests (TDD, own modules only)

`apps/tests/test_perf_stage2_server.py`:
- cache config: no env → LocMem pair sharing a LOCATION; both URLs → Redis backends with short
  socket timeouts; one URL alone or the same URL twice → `ImproperlyConfigured`.
- fail-open: a `FailOpenRedisCache` pointed at a dead port → get default, add True, set no error,
  incr ValueError (cache-miss path).
- fail-closed: `FailClosedRedisCache` at a dead port → `LimitsUnavailable`; login endpoint with
  `limits` on a dead Redis → 503 + Arabic message; public-guard / 2FA refuse too.
- guard: every `SimpleRateThrottle` subclass in `apps.*`/`core.*` uses `limits_cache`.
- bulk read: enforce + dead limits → 503; log → response unchanged.
- statement timeout: off by default (`SHOW statement_timeout` = 0 inside a request); flag on →
  `30s` inside a request, `0` in a plain thread outside a request.
- `DB_CONN_MAX_AGE` default 0, health checks on.

Existing suites re-run: `apps.users.tests_mfa`, `apps.portal.tests`, lockout / throttle / public
guard security tests touched by the change. `--keepdb`, `TEST_DB_NAME=test_perf_s2_server`, never
`--parallel`.
