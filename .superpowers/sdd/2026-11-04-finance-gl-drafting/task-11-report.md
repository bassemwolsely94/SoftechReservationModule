# Task 11 report - help, docs, regression

Commit: 36568cd2 `docs(finance-gl): drafting help, architecture and registries`

## Files
- apps/help/content/finance.py: new screens finance.gl_parties (/finance/parties) and finance.gl_rules (/finance/rules, tabs rules|maps, tour on finance-gl-rules-grid / rule-editor / rule-test / maps-grid, parties-propose / parties-grid); finance.gl_journal exceptions tab body now explains all 8 kinds (unmapped_party, unmapped_account, no_rule, ambiguous_rule, unbalanced_rule, closed_period_change, duplicate_source_key, ledger_error). Arabic + English, updated 2026-11-04. (gl_journal's tabs entries/exceptions, tour and hints were already extended by Task 10.)
- docs/architecture/35_FINANCE_GENERAL_LEDGER.md: Plan 2 part (flow, code map, SOFTECH verification table, models, rules model, idempotency, late changes, vanish guard P10, heartbeat P11, P1/P4/P5/P8/P9/P12/P14/P15/P17/P18, exception kinds, schedule 08:30, API, RBAC, screens, commands, cutover, open owner questions); status line updated.
- docs/architecture/02, 03, 04, 05 registries updated (module, 6 tables, API routes, UI routes/tabs).

## Tests (TEST_DB_NAME=test_gl_drafting, --keepdb)
- apps.tests.test_help alone: Ran 103 tests OK.
- test_help + all apps.tests.test_gl_* (15 modules) + test_finance_freshness + test_scheduler_jobs + security.test_rbac_accountant: Ran 399 tests in 436.7s OK.
- Full suite `manage.py test apps.tests --noinput --keepdb`: Ran 5957 tests in 5196s, FAILED (failures=105, errors=50, skipped=12, expected failures=2).
- Frontend `npm run build`: built in 13.75s, only the usual >500 kB chunk warning; staticfiles output is git-ignored.

## Full-suite failures vs main
All 150 failing tests (154 FAIL/ERROR lines incl. subtests) are in 17 modules with no GL involvement. Re-ran exactly those 17 modules on a clean checkout of origin/main (cc0da16a, includes 11 commits newer than this branch's merge): Ran 457 tests, failures=105, errors=50 - the identical counts and an identical sorted FAIL/ERROR list (diff empty). Verdict for every one: PRE-EXISTING (fails on main; environment/data dependent), not caused by Plan 2.

| Module | failing | Verdict |
|---|---|---|
| security.test_access_policy / _middleware / _preflight / _session_policy / _softech_gate / _final_wave / _final_parked / _leakage / _n3_enforce_ready | 2+7+1+9+6+4+13+2+1 = 45 | pre-existing (same on main): zone/network access policy tests expecting different zone/read_only decisions, Sybase gate JZN URL errors |
| test_phone_alerts | 60 | pre-existing (same on main) |
| test_stock_audit_api | 15 | pre-existing (same on main) |
| test_usage_print | 14 | pre-existing (same on main) |
| test_commerce | 9 | pre-existing (same on main) |
| test_counselling_content / _assistant / _ai_draft | 4+1+1 | pre-existing (same on main) |
| test_insurance (RbacTests) | 1 | pre-existing (same on main) |

No fixes made: no failure is attributable to Plan 2 code. Every GL, help, finance-freshness, scheduler-jobs and RBAC-accountant test passes.
