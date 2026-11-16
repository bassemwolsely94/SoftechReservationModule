# UAT findings noticed while building the harness

Folded into the final report (docs/uat/2026-11-role-uat-report.md).

| id | where | what | severity (proposed) |
|---|---|---|---|
| B-01 | `apps/users/mfa.py:60` `mfa_enforced()` | `bool(s.typed_value)` tests the bound method, not its result, so any `security.mfa_enforced` row turns 2FA enforcement on, even one whose value is `false`. An admin cannot switch enforcement off by setting it false; only deleting the row does. | P2 (fails closed, but the switch does not do what it says) |
