# 10 — Test strategy and results

Full audit, 2026-11-15. Everything below says what actually ran, where, and what it proves. Nothing was run
against SOFTECH; the audit worktree ran with `WRITER_INSTANCE=False`, `SOFTECH_READ_ONLY=True` and its own
test database.

## 1. What exists (inventory)

| Layer | Tooling | Size | In CI |
|---|---|---|---|
| Backend unit + API | Django `manage.py test` (unittest), factories in `apps/tests/factories.py` | 578 test files, ~8,875 test methods | yes, with `coverage --fail-under=73` |
| Security sweeps | `apps/tests/security/` — role × route sweeps (log + enforce), branch canaries, Tripwire (no outbound side effects), SQL recorder, static guards (raw SOFTECH connects, write manifest, default-ON switches, tracked secrets, unclassified prefixes, role literals) | 1,693 routes × roles | yes |
| Static | bandit (new findings vs baseline), pip-audit, npm audit (allow-list), ESLint, `makemigrations --check` | — | yes |
| Frontend unit | Vitest + React Testing Library | 11 files, 131 tests (incl. 4 added here) | yes |
| End-to-end | Playwright on `config.settings_e2e` (own DB, no SOFTECH, no sends) | 23 tests | yes |
| Property-based (Wave 4) | Hypothesis, `apps/tests/test_money_properties.py` — strip/pack Q, VAT, tender split, offers cap (SimpleTestCase, derandomized) | 20 tests (3 `expectedFailure` = bug found: negative last-line offer share) | yes |
| Concurrency (Wave 4) | `apps/tests/test_writer_concurrency.py` — two threads + `TransactionTestCase` per writer guard: POS push, pos_cancel, ISR, A/P allocation, purchase invoice (SOFTECH mocked) | 6 tests | yes |
| Mutation / load | — | **none** | no |

## 2. Results of this audit's runs

| Run | Where / how | Result |
|---|---|---|
| `manage.py check` | worktree, office settings | 0 issues |
| `check --deploy` | production template flags (`DEBUG=False`, `BEHIND_HTTPS_PROXY=True`, random key) | 6 warnings: HSTS subdomains/preload, SSL redirect (nginx does it), and 3 project checks for keys that must be set on the VPS (`NETWORK_PROXY_KEY`, `COUNSEL_PHONE_HASH_KEY`, `OMNI_CREDENTIALS_KEY`) |
| `check --deploy` | office `.env` | 7 warnings incl. DEBUG on and a weak `SECRET_KEY` → SEC-1 |
| `makemigrations --check` | worktree | No changes detected |
| bandit (CI gate) | local bandit 1.9.4 | exits 1 locally on `probe_softech_ingredients.py` B608 lines that CI accepts — a baseline-fingerprint difference between bandit versions, not a new finding (CI passes on `main`). Full scan: 593 medium+ issues, 579 are B608 (mostly baselined, reviewed in round 1); 2 B613 are intentional bidi-stripping code; B310/B615/B507/B324 noted in 03 |
| pip-audit | local venv | 1 advisory: `soupsieve 3.0.4` (fix 4.0.0). `requirements.txt` allows ≥2.9.0, so CI installs the fixed version; only the office venv is stale — upgrade it |
| npm audit (CI gate) | main checkout | no advisories beyond the known list |
| ESLint | frontend | 0 errors, 188 warnings (46 exhaustive-deps, 124 unused, 18 stale disables) |
| Vitest | worktree | **131 / 131 passed** |
| Vite build | worktree → scratch dir | passed (17 s); entry chunk 715 kB (209 kB gzip) |
| Backend full suite on `main` | GitHub CI, last completed run on `1057d2d6` (2026-11-15 08:27 UTC) | **success** (backend, frontend build, lint+unit, Playwright). Later runs on `main` were cancelled by newer merges, not failed |
| Backend full suite, local | worktree, with coverage | stopped after ~70 min / 852 tests, **0 failures** — this PC runs the suite far slower than CI (coverage on a OneDrive path); CI is the authoritative full run |
| New regression tests | `apps.tests.test_full_audit_fixes` | **12 / 12 passed** |
| Related existing tests | 153 modules that touch POS, vouchers, loyalty, chatter, filter options, the Sybase cursor and the invoice writer | **2,518 passed**, 0 failed (§3) |

## 3. Related-module regression run

153 test modules that import or call the changed code (POS orders, vouchers, loyalty, chatter, purchasing
filter options, the Sybase cursor, the invoice writer — list kept in the audit scratch notes), run on the
audit branch after all fixes, without coverage:

**Ran 2,518 tests in 2,202 s — OK (12 skipped, 2 expected failures), 0 failures, 0 errors.**

The skips are existing `skipUnless` guards (e.g. optional libraries missing from this venv); the two expected
failures are existing `@expectedFailure` markers. Neither was introduced by this audit.

## 4. Coverage

CI enforces ≥73 % line coverage (R7, measured ≈77.9 % on 2026-11-05). Per-module coverage was not
re-measured here (the local coverage run was stopped, see §2). Known thin areas from the inventory (02):
`dashboard`, `qa` (only route sweeps), and the frontend (11 unit files for ~270 pages).

## 5. Gaps and how to close them (risk-ordered)

| Gap | Risk it leaves | Proposal | Effort |
|---|---|---|---|
| **Concurrency** — no test runs two writers at once (Wave 4: POS push, pos_cancel, ISR, A/P, purchase done; voucher verify + loyalty approve left) | Double posts / lost updates (S-1, S-2, BE-5/6/7 were found by reading, not by tests) | `TransactionTestCase` + two threads + a barrier, one test per idempotency guard (POS push, A/P, ISR, purchase, voucher verify, loyalty approve) | 2 days |
| **Load** — no Locust/k6 | Capacity at 20 users unknown (PERF-3) | Locust plan in [07](07_PERFORMANCE_AUDIT.md) §capacity, run on the VPS in Stage A | 0.5 day |
| **Property-based** (Wave 4: strip/pack, VAT inclusive, tender split, offers cap done; insurance co-pay + VAT exclusive left) | Edge cases in money/quantity math | Hypothesis on strip→pack `transqty` rounding, tender split, offers cap (≤ line gross), VAT inclusive/exclusive, insurance co-pay | 1.5 days |
| **Mutation** | Tests that pass even when the rule changes | mutmut on `pos_orders/pricing`, `finance/recon_writer`, `insurance` pricing, `vouchers` eligibility — fix surviving mutants | 2 days |
| **Resilience** | Behaviour when SOFTECH/PG/Redis drop mid-flow | Fault-injection tests around `get_branch_connection`, commit-reply loss (raise after commit), PG `OperationalError`, channel-layer down | 1.5 days |
| **State-aware sweeps** | 77 `role_unproven` routes (round 2) | Builder that creates records in the state each route needs | **Built (Wave 4, 2026-11-20):** `state_builders.py` + regex-group rendering; `role_unproven` 84 → 0, ratchet `UNPROVEN_CEILING` |
| **Frontend** | Screens without error states, v5 regressions (FE-4/5/6/7) | RTL tests for the shared error state + a lint rule banning `invalidateQueries([` and `keepPreviousData:` | 1 day |
| **CI time** | Backend 55–70 of 75 min | Shard backend tests (2–3 jobs) or move sweeps nightly | 0.5 day |
