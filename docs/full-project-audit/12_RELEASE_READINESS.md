# 12 — Release readiness (LDC VPS)

Full audit, 2026-11-15. Production = one LDC VPS (4 vCPU / 8 GB, Ubuntu 24.04, PostgreSQL 16); releases only
through Git → PR → CI → `main` → `release.sh` (runbook `deploy/LINKDATACENTER_VPS_RUNBOOK.md`). The office
PC is the SOFTECH writer and development server until cutover (owner, 2026-11-15).

## Recommendation

| Stage | Verdict | Condition |
|---|---|---|
| **A — VPS live as a reader** (no SOFTECH writes, testers told it is a sandbox) | **GO** after owner steps A2–A7 in `docs/deploy/2026-11-15-go-live-status.md` | Unchanged by this audit; nothing found blocks a read-only VPS |
| **B — cutover** (VPS becomes the only SOFTECH writer) | **NO-GO** until Wave 0 and Wave 1 steps 1.1–1.7 of [13](13_IMPLEMENTATION_ROADMAP.md) are done, plus the existing owner steps B7–B12 | 2026-11-16: posting safety and offline idempotency merged (Wave 1, PRs 150–154). Still missing: extra web processes installed on the VPS (§13.6), a measured load test (§13.7), and a UI control for confirming an outcome-unknown POS order before the POS writer is switched on |

## Blockers for Stage B (new from this audit)

| # | Blocker | Finding | Where fixed |
|---|---|---|---|
| 1 | Office signed tokens with the public placeholder key | SEC-1 | **Closed 2026-11-15** (key replaced, guard `eec5a978`). The VPS still needs its own `SECRET_KEY`, `OMNI_CREDENTIALS_KEY` and `COUNSEL_PHONE_HASH_KEY` — do not copy the office values |
| 2 | Double-post paths after a lost commit reply | S-1, S-2, S-3, S-5 | D-05…D-08 |
| 3 | A posted POS order could be deleted through the API | BE-1 | **Fixed** on `claude/full-project-audit` |
| 4 | One web process for HTTP + WebSocket + long exports; no DB statement timeout | PERF-3 | D-21 |
| 5 | No load test at 20 users | §12.10 | D-22 |
| 6 | Hot unindexed sales-history queries and the notification flood polled by every screen | PERF-1, PERF-2 | D-19, D-20 |

## Deployment configuration review

| Area | Evidence | Status |
|---|---|---|
| HTTPS / cookies | `BEHIND_HTTPS_PROXY=True` in `deploy/production.env.example` turns on secure session, CSRF and auth cookies (`config/settings.py:100–146`). `check --deploy` with those flags leaves only HSTS-subdomains/preload and `SECURE_SSL_REDIRECT` (nginx redirects) | OK |
| Secrets present at start | `check --deploy` warns when `NETWORK_PROXY_KEY`, `COUNSEL_PHONE_HASH_KEY`, `OMNI_CREDENTIALS_KEY` are empty — all three must be set on the VPS | Owner step |
| Placeholder key | Refused outside DEBUG (`settings.py:81–90`) | OK on the VPS; not in office DEBUG (SEC-1) |
| nginx | TLS 1.2/1.3, rate limits (`api` 30 r/s, `auth` 5 r/m), media served as attachment with `sandbox` CSP, 50 MB upload cap, 600 s API timeout; CSP is **report-only** | CSP: D-04 |
| Processes | systemd units for web (single Daphne), scheduler (single-instance lock), AMI bridge, OCR (2 GB cap); `Restart=always` | Web: D-21 |
| DB connections | `CONN_MAX_AGE=0` (new connection per request); no pgbouncer | Part of D-21 |
| Release | `release.sh`: `pg_dump` before release, build/check before `migrate`, every process restarted after migrate (P-56) | OK |
| Rollback | pre-release dump + `GO_LIVE_CHECKLIST.md` rollback section and the cutover-day sheet (PR 141) | OK — never rehearsed; rehearse once on the VPS |
| Health / monitoring | `/api/public/health/` (SELECT 1); uptime monitor still an owner step (B10b) | Owner step |
| SOFTECH connectivity | VPS reaches SOFTECH through the private tunnel; Sybase is never exposed publicly (runbook §11). Tunnel loss → POS queues orders (`queued`) and sync lanes retry | Verify latency + reconnect on the VPS during Stage A |
| Migrations | `makemigrations --check` clean on `main`; `check_schema_drift` must run on the VPS DB before cutover (round 2) | Owner step |

## Capacity judgement

The performance audit measured single requests on the office database (12 GB, untuned PostgreSQL): the
dashboard summary takes 1.3–2.3 s, stock-expiry summary 3.7 s and PIC overview 6.6 s, while the bell
count for the admin with 63k unread notifications takes up to 2.4 s cold. With one Daphne process, several
of these polled every 30–90 s by 20 users will queue behind each other. The VPS is judged **adequate after**
D-19/D-20/D-21 and **risky as deployed today**. This is a judgement from single-request timings, not a load
test — see D-22.
