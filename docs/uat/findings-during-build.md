# UAT findings noticed while building the harness

Folded into the final report (docs/uat/2026-11-role-uat-report.md).

| id | where | what | severity (proposed) |
|---|---|---|---|
| B-01 | `apps/users/mfa.py:60` `mfa_enforced()` | `bool(s.typed_value)` tests the bound method, not its result, so any `security.mfa_enforced` row turns 2FA enforcement on, even one whose value is `false`. An admin cannot switch enforcement off by setting it false; only deleting the row does. | P2 (fails closed, but the switch does not do what it says) |
| B-02 | real staff accounts on the copy | Only 3 of 10 roles have any real active account: admin 2, call_center 1, salesperson 83. pharmacist, purchasing, delivery, viewer, supervisor, quality_manager and accountant have none. Go-live needs these accounts provisioned (and their branch/phone flags set). | P1 (go-live readiness) |
| B-03 | adoption signal | In the last 30 days only one real user (an admin) opened any screen (audit ScreenView); none of the 83 salesperson accounts did. | P2 (training / rollout) |
| B-04 | `auth_user.last_login` | JWT logins never update `last_login` (latest value 2026-07-01), so any "inactive user" report built on it is wrong. | P3 |
