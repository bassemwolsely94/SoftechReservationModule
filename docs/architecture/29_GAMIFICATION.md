# 29 — Gamification (التحفيز: النقاط والمستويات)

**Status:** Phase 1 BUILT (2026-10-10) — points, levels, badges, rankings. Phase 2 BUILT (2026-10-10) — reward catalog. Phase 3 BUILT (2026-10-10) — monthly champion (بطل الشهر).
**App:** `apps/gamification` · **API:** `/api/gamification/` · **Screens:** card on `/dashboard` + `/me`, `/gamification`, `/m/gamification`

## Decisions (agreed with the owner)

| Question | Decision |
|---|---|
| Money? | **Recognition only** (levels, titles, badges, ranking). A reward catalog (redeem points via `apps/approvals`) comes later. Money incentives stay in `apps/incentives` — not duplicated. |
| Sales scoring | **Count + capped value + profitability, cash higher**: +2 per sale invoice (cap 80/day), +1 per 500 EGP net daily sales (cap 40), +1 per 100 EGP gross profit with cash (`sales_channel='91'`) ×1.5 (cap 60). |
| Penalties | **Mild**: −1/−2 per overdue item (capped −10/day per rule). Levels never drop — XP = positive points only; penalties affect the period ranking (net). |
| Visibility | **Full ranking inside your branch + network top 10.** Managers (`gamification`/`view`) see all. |

## How it works

The engine **reads** records that already exist and writes only its own tables. It never touches SOFTECH (sales come from the PostgreSQL mirror `customers.PurchaseHistory`) and never changes another module.

| Source | Rule(s) | Who gets it |
|---|---|---|
| `PurchaseHistory` doc 115 / 30 | `sale_invoice`, `sale_value`, `sale_profit`, `return_processed` | `StaffProfile.softech_user_id` = `softech_user` |
| `Reservation` | `reservation_created`, `reservation_fulfilled`, `reservation_overdue` (−) | `created_by` / `assigned_to` |
| `DemandRecord`, `DemandFollowUp` | `demand_created`, `demand_fulfilled`, `demand_sla_breach` (−, 20-min SLA), `demand_followup_done`, `demand_followup_missed` (−) | creator / assignee / completer |
| `followups.FollowUpTask` | `followup_call_done`, `followup_missed` (−) | completer / assignee |
| `TransferRequest` | `transfer_request_created`, `transfer_request_answered`, `transfer_request_fast` (≤ 2 h), `transfer_dispatched` | creator / reviewer (other branch) / dispatcher |
| `transits.InTransitTransfer` (125) | `transfer_sent_erp`, `transfer_received` | `erp_user_code` / `manually_received_by` |
| `purchasing.IsrPush` | `isr_created`, `isr_approved` | `created_by` / `approved_by` (auth user → staff) |
| `StockCountSession`, `ShortageList` | `stockcount_completed`, `shortage_submitted` | uploader / creator |
| `tasks.OperationalTask` | `task_on_time`, `task_late`, `task_overdue` (−) | completer / assignee |
| `audit.AbuseFlag` (escalated) | `abuse_flag` (−10) | flagged staff |
| Day close | `clean_day` (+10), `streak_week` (+25 every 7) | anyone who worked with no deduction that day |

**Idempotency:** each `PointEvent` stores `source_key` (e.g. `ph:123`, `res_overdue:55:2026-10-09`); `(staff, rule_key, source_key)` is UNIQUE. Daily aggregates (value/profit) top up only the difference, with deterministic keys. The ledger is append-only (no update/delete in API or admin).

**Schedule:** `gamification_score` every 30 min (today); `gamification_day_close` 00:20 closes yesterday (penalties for open overdue items judged on current state, clean day, streak). Flag: `GAMIFICATION_ENABLED`. Manual: `python manage.py run_gamification --days N`.

**Levels (default, editable):** مبتدئ 0 · نشيط 300 · متمكّن 1,000 · محترف 2,500 · خبير 5,000 · نجم الفرع 9,000 · قائد 15,000 · نخبة 24,000 · بطل 36,000 · أسطورة الرزيقي 52,000. Promotion → `LevelHistory` + notification `gamification_level_up`; badge → `gamification_badge`.

**Fairness:** daily caps per rule; branch ranking by average points per active player; role filter on rankings.

**Governance:** rules / levels / badges editable at `/gamification?tab=settings` (`gamification`/`edit`); every edit and every manual award (reason required, ±500 max, never to yourself) is written to `GamificationChange` (who / what / before / after / why). Seed grants: supervisor + quality_manager get `view` + `export`; admin everything.

## Reward catalog (Phase 2)

- **Wallet** = lifetime net points − points of redemptions that are `pending` (held), `approved` or `fulfilled` (spent). Spending lives in `Redemption`, never in `PointEvent`, so **XP, level and rankings are unchanged by redeeming**.
- **Request** (`POST /api/gamification/redemptions/`): checks active, role, min level, stock, monthly limit and balance under a row lock on the player (no double spend), takes one from stock, and submits an `ApprovalRequest` with workflow `gamification_reward` (seeded in `seed_approval_workflows`, created on demand if missing): **branch manager (supervisor, own branch) → management (admin)**. Rewards with `requires_approval=False` are approved at once.
- **Outcome** hook (`register_outcome_handler('gamification.redemption', …)`): approved → `approved`; rejected → `rejected` + refund + restock. An approval decided by the requester themselves is refused (→ rejected + refund).
- **Cancel**: requester while pending (also cancels the approval request); admin any open request; managers with `gamification/edit` an approved-but-undelivered one with a written reason. Expired / inbox-cancelled approvals are refunded by `reconcile()` on every engine run.
- **Fulfil** (`gamification/edit`, never your own): `approved → fulfilled` with delivery details; the employee is notified (`gamification_reward`).
- **Catalog** seeded once: certificate, employee-of-the-week spotlight, preferred shift (ON); lunch, half day off, extra day off, 200 EGP voucher, training course (OFF until management prices them). Edited at `/gamification?tab=settings`; every change audited in `GamificationChange`.
- **Screens**: `?tab=rewards` (everyone), `?tab=redemptions` (managers), catalog editor in settings, balance on the dashboard card and `/m/gamification`; report + Excel include redemptions.

## Monthly champion — بطل الشهر (Phase 3)

`apps/gamification/champions.py`. Job `gamification_champions` runs on the **1st of each month at 01:05** and crowns the month that just ended (`crown(month)`; also `run_gamification --crown YYYY-MM` and `POST /api/gamification/champions/crown/` for editors). `ChampionMonth.month` is UNIQUE → a month is crowned exactly once; a running month is refused.

| Title | Who | Bonus (rule) |
|---|---|---|
| بطل الفرع | #1 of each role in each branch — group needs ≥ `GAMIFICATION_CHAMPION_MIN_PLAYERS` (2) | +200 `champion_branch` |
| بطل الشبكة | #1 of each role across all branches | +500 `champion_network` |
| منصة الشبكة | #2 / #3 of each role across all branches | +200 `podium_network` |
| فرع الشهر | #1 of the branch ranking (avg per player), ≥ `GAMIFICATION_BRANCH_OF_MONTH_MIN_PLAYERS` (3) players | recognition |

- **Eligible:** month net > 0, no `abuse_flag` deduction in the month, role not in `GAMIFICATION_CHAMPION_EXCLUDED_ROLES` (`admin,viewer`).
- **Fair:** bonuses use the new `champion` category — counted in XP and the wallet, **excluded from every ranking**, so last month's winner starts level.
- **Published:** one pinned, high-priority `notifications.Announcement` (network-wide, fanned out to the bell, expires in 10 days) + a `gamification_champion` notification to each winner. Badges: `champ_branch_1` (👑 بطل الشهر), `champ_branch_3` (بطل متكرر), `champ_network_1` (على منصة الشبكة).
- **Revoke** (`POST champions/{id}/revoke/`, `gamification/edit`, written reason): marks the title revoked, books a `champion_revoked` reversal (−bonus; XP counts the champion category at its net value), drops champion badges no longer earned, audited in `GamificationChange`.
- **Screens:** `/gamification?tab=champions` — live race this month (my branch + network leaders per role, days left) and the hall of fame per month; crown chip on the dashboard card for 2 months; champions listed in the executive report.

## Known limits (Phase 1)

- Sales score only for staff whose SOFTECH user code is linked (`softech_user_id`).
- SOFTECH receipt docs (25) carry no user in our mirror, so `transfer_received` counts in-app receipt confirmations only.
- "Branch requests waiting" is shown to the branch but not penalised per person (no single owner).
- Open-item penalties use current state → only applied for the most recent closed day (back-fills award activity, not penalties).

## Next phases

1. ~~Reward catalog~~ ✅ built (above).
2. ~~Monthly champions~~ ✅ built (above).
3. Team goals per branch (shared challenges), per-role rule sets.
