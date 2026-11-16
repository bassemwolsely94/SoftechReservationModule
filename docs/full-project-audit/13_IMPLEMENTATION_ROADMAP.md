# 13 — Implementation roadmap

Full audit, 2026-11-15. Ordered by risk first (Category A), then return on development time (Category B).
Estimates are working hours for Claude-built changes with tests; "owner" time is listed separately. Every
wave is one or more separate batches with its own approval (CLAUDE.md batch rules), never one large PR.

## Wave 0 — this week: close the open security hole (Category A)

| Step | What | Findings | Effort | Depends on |
|---|---|---|---|---|
| 0.1 | Replace the office signing key in the safe order (re-key channel credentials first) | SEC-1 | owner 30–60 min + Claude 1 h | D-01 |
| 0.2 | Settings guard refuses a placeholder key in DEBUG | SEC-1 | 1 h | 0.1 |
| 0.3 | DEBUG off on the office; webhooks verify signatures again | SEC-4 | 1 h | D-03 |
| 0.4 | Merge the audit branch fixes (already built, see [11](11_BUG_FIX_REGISTER.md)) | 9 fixes | review only | CI green |
| 0.5 | Escape the remaining print popups (incentives, vouchers, shelf QR) with `utils/escapeHtml.js` | SEC-6 | 2 h | 0.4 |

## Wave 1 — before VPS Stage B (cutover): posting safety and capacity (Category A)

| Step | What | Findings | Effort |
|---|---|---|---|
| 1.1 | POS: settled-table vf2 lookup, atomic + locked `prepare_order`, reconcile `push_failed` | S-1, BE-2/3, S-6, S-7 | 1–2 days + rollback-probe golden test |
| 1.2 | A/P writer lock + in-transaction read | S-2 | 1 day |
| 1.3 | Purchase-invoice `INV<pk>` tag + "outcome unknown" on any post-commit error | S-3, S-4 | 1 day |
| 1.4 | ISR / pos_cancel lost-reply guards | S-5, S-14 | 1 day |
| 1.5 | Web capacity: 3 workers + Redis layer, exports/OCR off the web process, DB statement timeout | PERF-3 | 1 day + owner VPS step |
| 1.6 | Sales-history date index (concurrently) + sargable filters; notification purge + bell default | PERF-1, PERF-2 | 1 day |
| 1.7 | **Load test** (Locust plan in [07](07_PERFORMANCE_AUDIT.md)) on the VPS: 20 users, then step up to the breaking point; record p50/p95/p99 | §12.10 | 0.5 day |
| 1.8 | Offline queue: user binding + server idempotency | FE-1 | 1 day |

## Wave 2 — first weeks after go-live: quick wins (Category B)

The Top 10 from [09](09_TOP_30_QUICK_WINS.md) §4, in its dependency order (~168 h). Cheapest high-return
first: return-window coverage (6 h), network stock in the call centre (10 + 6 h), AP exception queue (10 h),
action-line morning brief (12 h), dead-stock move lane (16 h), stock-audit finding → task (14 h), near-expiry
worklist (24 h), refill-due list (20 + 6 h), weekly HQ exception digest (20 h), tiered cover (24 h).

Alongside, low-cost technical clean-ups that remove daily friction:

| What | Findings | Effort |
|---|---|---|
| TanStack v5 migration leftovers: `invalidateQueries({queryKey})` (140 sites), `placeholderData: keepPreviousData` (21) | FE-4, FE-5 | 4 h (codemod + review) |
| Error states on the 82 screens that show 403/500 as "no data" (shared component) | FE-7 | 1 day |
| Reservation extra-line save errors surfaced; transfer "save and send" in one call | FE-2, FE-11 | 4 h |
| N+1 fixes on reservations / customers / supply lists | PERF-4 | 4 h |
| Approvals inbox keyboard + bulk approve (reuse `useGridKeyboard`) | FE-10 | 6 h |
| Session expiry keeps the page and returns after login | FE-12 | 4 h |
| Lazy-load drawers/help/command palette (entry chunk 715 kB) | FE-19 | 4 h |

## Wave 3 — medium term (Category C)

- Money rules the owner decides: fail-closed vs flagged discount authority (D-11), loyalty `F()` conversion
  (D-13), insurance rounding (D-15), incentive re-calc rule (D-16), audit rows `PROTECT` (D-17).
- Single server-side checkout endpoint (D-18) together with P-39 POS parity.
- SOFTECH delta sync (doc 30 Phase 2) — the largest remaining read load (PERF-6).
- Replace native dialogs and modal create flows screen by screen (FE-9, FE-27).
- Remaining Top-30 candidates C11–C30.

## Wave 4 — strategic (Category D)

- CSP enforce + JWT out of `localStorage` (SEC-5, SEC-8, FE-26) as one frontend-security project.
- `RBAC_ENFORCEMENT=enforce` after go-live (D-26).
- Testing maturity: state-aware sweep builder for the 77 `role_unproven` routes; property-based tests
  (Hypothesis) on strip/pack quantity, tender split, offers cap and VAT; mutation testing on the POS, A/P and
  insurance pricing modules; a concurrency test harness (two threads, `TransactionTestCase`) for every
  writer's idempotency guard.
- Split CI: backend runs 55–70 of 75 minutes; shard the suite or move sweeps to a nightly job.
