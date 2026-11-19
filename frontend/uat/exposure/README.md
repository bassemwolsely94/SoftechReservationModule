# W4 — customer phones and other branches' data, as rendered

Plan Task 8 (`docs/superpowers/plans/2026-11-16-role-uat.md`). Rules: `rules.js` (every rule cites its
source: roles.py, B-1/B-2/B-3, D2–D8, decision 3, the canary baselines). Unknown → `decision` (P2).

| spec | what it checks |
|---|---|
| `screens.spec.js` | every domain's list screens (desktop + `/m/*`) per exposure user: rendered text + every JSON response scanned for reference customers' full numbers and for records of a branch the user may not see |
| `records.spec.js` | other-branch detail records (reservation, demand, transfer, shortage list, POS order) must not open; customer 360 + loyalty account of both branches open with the allowed numbers; own customers not over-masked |
| `search.spec.js` | customers search, universal search (Ctrl+K API and the palette itself), analytics customer search, call-center lookup: name search finds own customers only; full-phone search masks other branches |
| `exports.spec.js` | reservations Excel export and the PIC-analytics background export, unzipped and scanned cell by cell |
| `selftest.spec.js` | the detectors themselves (synthetic numbers, no findings written) |

Users: `pharmacist@B`, `salesperson@B`, `viewer@B`, `delivery@B`, `phoneHidden`, `phoneVisible`, `multi`,
`restricted`, `viewer` (A). Severities: full number where masked → P0 `phone`; other-branch record
where absent → P0 `branch`; masked where full → P3 `phone`; no rule → P2 `decision`.

A number is matched on its last 10 digits after joining digit runs across spaces, dashes, `+`,
bidi marks and Arabic-Indic digits; under 8 digits is not checked. Search-echo keys (`q`, `search`,
the call-center lookup's top-level `phone`) are skipped. Findings name customers by PIC and numbers
by `last3()` only.

Run (heavy): `scripts/uat/heavy.ps1 -Name "W4 exposure" -Command { npx playwright test -c playwright.uat.config.js uat/exposure }`
from `frontend/` after `. scripts/uat/uat-env.ps1`, with `UAT_WEB_PORT=5203`. `W4_DEBUG=1` prints
search statuses and found / masked flags (never numbers).
