# Role-by-role UAT — runbook

Design: `docs/superpowers/specs/2026-11-16-role-uat-design.md` · Plan: `docs/superpowers/plans/2026-11-16-role-uat.md`

Everything runs against **`elrezeiky_uat`**, a restored copy of the office database, under
`config.settings_uat`: reader only, no SOFTECH host, every writer / send switch off, no
WhatsApp / SMS / PBX / tax / AI keys, scheduler off, `RBAC_ENFORCEMENT=enforce`. The office
server (port 8000, `elrezeiky_db`) is never touched except for the read-only `pg_dump`.

## One-time / refresh (heavy — takes the lock)

```powershell
. scripts/uat/uat-env.ps1
scripts/uat/heavy.ps1 -Name "UAT refresh" -Command { scripts/uat/refresh_uat_db.ps1 }
& $env:UAT_PYTHON manage.py seed_uat_users --settings=config.settings_uat --real-auto
& $env:UAT_PYTHON manage.py export_uat_expectations --settings=config.settings_uat
```

`seed_uat_users` writes `frontend/uat/.uat-users.json` (git-ignored, holds the password);
`export_uat_expectations` writes `frontend/uat/.uat-expected.json` (git-ignored, holds real
reference phones) and `docs/uat/permission-drift.md`.

## Running the browser suite

```powershell
. scripts/uat/uat-env.ps1
cd frontend
$env:UAT_WEB_PORT = 5201          # your session's own Vite port (5200 = the main UAT session)
npx playwright test -c playwright.uat.config.js uat/smoke.spec.js       # one spec: not heavy
..\scripts\uat\heavy.ps1 -Name "W2 visibility" -Command { npx playwright test -c playwright.uat.config.js uat/visibility }   # full suite: heavy
```

The Django server on **8200** is shared. Start it once, detached, under the watchdog (it restarts runserver if it exits):

```powershell
Start-Process powershell -ArgumentList '-NoProfile','-File','scripts/uat/serve.ps1' -WindowStyle Hidden
```

A server started by a Playwright run dies when that run ends, so do not rely on it for other sessions.

## Rules

- **Heavy runs one at a time** (DB refresh, a whole workstream suite, load): wrap them in
  `heavy.ps1`. Exit code 3 = someone else holds the lock; wait and retry. Postgres on this PC
  has crashed twice from parallel heavy runs.
- **Findings** go through `uat/lib/findings.js` `finding()` into `frontend/test-results-uat/findings.jsonl`.
  Never write a full phone number anywhere (use `last3()`).
- **Write-capable tests** (POS push, pricing approval) call `assertReaderCopy()` from
  `uat/lib/guard.js` first. Owner approval to complete them covers the copy only.
- Never run `seed_permissions` on the copy — its live role matrix is what is tested.
