# 29 — Gamification (التحفيز: النقاط والمستويات)

**Status:** Phase 1 BUILT (2026-10-10) — recognition only. Reward catalog = Phase 2.
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

## Known limits (Phase 1)

- Sales score only for staff whose SOFTECH user code is linked (`softech_user_id`).
- SOFTECH receipt docs (25) carry no user in our mirror, so `transfer_received` counts in-app receipt confirmations only.
- "Branch requests waiting" is shown to the branch but not penalised per person (no single owner).
- Open-item penalties use current state → only applied for the most recent closed day (back-fills award activity, not penalties).

## Next phases

1. **Reward catalog** — redeem points (day off, voucher …) through `apps/approvals`; points ledger gets a `redeemed` spend.
2. Monthly champions («بطل الشهر») per branch/role + announcement.
3. Team goals per branch (shared challenges), per-role rule sets.
