# 33 — PIC Analytics (تحليلات العملاء — PIC)

**Status:** BUILT (2026-11-03, branch `claude/pic-analytics`, based on PR 41) · **Design date:** 2026-11-02
**Depends on:** PR 41 (PBX call history `pbx.CdrCall`, linked to PICs).
**Related:** `apps/customers` (PurchaseHistory, segmentation), `apps/analytics` (sales/performance),
`apps/forecasting/kpi.py` (metric resolver, ChannelBucketMap), `apps/stock_audit/access.py`
(named-grant pattern), `apps/callcenter` (call-backs, dial), doc 28 (in-app help).

Each decision is tagged **[owner]** (decided by the owner in conversation, 2026-11-02) or
**[call]** (the author's default — change it if wrong).

---

## 1. Why

The owner wants one place that answers, for any period: who are our customers (PICs), how much they
buy, how often they come back, through which channel, from whom, and how the phone fits in. Today the
numbers are spread over the sales dashboard, the KPI board, customer segments and the call-center
pages, none of which is keyed by PIC over time. Calls in particular could not be trusted until PR 41.

Success looks like: a branch manager or supervisor picks a date range, sees the customer base of that
range broken down every way that matters, exports it to Excel, and gets lists to act on: customers
who are overdue, missed calls nobody returned, and new phone numbers that should become PICs.

## 2. Goals, non-goals, anti-goals

**Goals**
- PIC-centric dashboard + exportable Excel report, filtered by from/to date. **[owner]**
- Sales, gross profit, counts, baskets, categories and channels per PIC and per every grouping.
- New vs returning vs reactivated PICs, by branch / salesperson / call-center agent / all branches /
  any customer classification. **[owner]**
- Frequency classes and spaced visits. **[owner]**
- Calls per PIC (incoming, outgoing, details, time, frequency), joined from the PBX record. **[owner]**
- Missed and unanswered calls joined to their PIC, and unknown numbers as possible new PICs. **[owner]**
- Tight access, enforced on the server. **[owner]**

**Non-goals**
- No writes to SOFTECH of any kind. A new PIC is still created in SOFTECH's own screen (the
  create-PIC writer stays deferred, see `PIC_CREATE_INVESTIGATION.md`).
- No AI-decided numbers; every figure is a deterministic rule (CLAUDE.md rule 10).
- No new targets/incentives logic; this screen reads, it does not pay or rank for money.

**Anti-goals (would make it a failure even if it works)**
- A number that double-counts: a call on a shared phone counted for every PIC on it, a same-day
  second invoice counted as a second visit, a returning customer counted as new.
- A branch manager seeing another branch, or seeing cost / gross profit.
- A screen that takes minutes to load because it scans raw invoice lines on every request.

## 3. Data that already exists (reuse, do not duplicate)

| Need | Source |
|---|---|
| Invoices per PIC | `customers.PurchaseHistory` (`softech_phcode` = PIC, `branch`, `invoice_date`, `trans_time`, `softech_user` = salesperson, `sales_channel` = ptclassifcode, `softech_personcode` = account, `doc_code` 115 sale / 30 return, `total_amount` net). History starts **2024-08-01**. |
| Lines, items, cost | `customers.PurchaseHistoryLine` (`item`, `quantity`, `line_total`, `cost_at_sale`); GP = `line_total − cost_at_sale × quantity`. |
| General category | `catalog.Item.medicine_type` (10 medicine, 20 others, 30 supplements, 40 veterinary, 50 cosmetics, 60 client gifts, 70 services, 00 unclassified) + `medicine_type_name_ar`. |
| Channel buckets | `forecasting.ChannelBucketMap` (cash / credit / insurance / delivery …) over `sales_channel`. |
| Salesperson names | `PurchaseHistory.softech_user` → `StaffProfile.softech_user_id` / ERPUser (`analytics/views.py _build_user_map`). |
| Call-center sales agents | `CallCenterConfig.sales_agent_usercodes`; CRM orders `DeliveryOrder.softech_order_usercode`. |
| Customer classification | `Customer.segment`, `churn_segment`, `customer_type_label`, loyalty tier. |
| Calls per PIC | `pbx.CdrCall` (PR 41): direction, status, agent extension, queue, durations, `pic`, `shared_pics`, `pic_match`. Agent → staff via `AgentExtension.staff`. |
| Call notes / purpose | `callcenter.CallLog` joined to the call by the PBX call id (`CallSession.unique_id` = `CdrCall.unique_id`). |
| Call-backs, dialling | `CallLog` status `callback` + `callback_due` queue; `/api/pbx/dial/`. |
| Freshness | `DataFreshnessBar` domains `sales`, `customers`, `calls`. |

Placeholders (`ACCT-…`, `is_account_placeholder`) and merged codes (`merged_into_pic`) are excluded
everywhere. Returns (doc 30) reduce net sales but are never a visit.

## 4. Definitions

All dates are Cairo local. "Period" = the report's from/to (inclusive).

**Visit** — a PIC's invoices on the same calendar day count as one visit ("spaced transactions").
**[owner]** Invoice count is still shown separately. A same-day purchase at two branches is one visit
chain-wide and one visit for each branch, so branch rows can add up to more than the all-branches
total; the screen says so under the table. **[call]**

**Returns** — counted on their own date (as the sales dashboard does): they reduce that day's net
sales, are never a visit, and never change a PIC's first-purchase date or "new" status. **[call]**

**Sales with no PIC** — invoices with no PIC, on `ACCT-…` placeholders or merged codes are not in any
PIC count, but appear as one "بدون PIC" line in the sales totals so the overview reconciles with the
sales dashboard and KPI board. **[call]**

**Channel** — the same channel the KPI board uses: `ChannelBucketMap` over the invoice's
(`sales_person_type`, `sales_channel`) pair, so channel numbers match the KPI board. **[call]** (Note:
`sales_channel` is stamped from the linked customer's classification at sync time, not typed per
invoice — the same limitation the KPI board already has.)

**Call-center agent attribution** — two different questions, two rules **[call]**:
- *Sales by an agent* (new PICs sold, net, basket): invoices whose `softech_user` is in
  `CallCenterConfig.sales_agent_usercodes` — the existing KPI-board rule.
- *Calls by an agent* (calls, talk time, call → purchase): the extension on the call
  (`CdrCall.agent_ext` → `AgentExtension.staff`).

**New PIC** — first purchase (ever, in our history) falls in the period **and** SOFTECH's
`localcustomers.custdate` is no earlier than period start − 30 days. **[owner]** custdate was verified
(198,462 of 198,463 PICs filled, one per PIC, never after the first invoice, 97% on the same day as it).
Without it, 14,794 old customers would look new because our history only starts in 2024-08.
**Fallback [owner]:** if custdate is not approved or turns out unreliable, "new" uses first purchase
only and is labelled reliable from 2025-08 onward, with a warning on earlier periods. Phase 1 does
not wait: it ships with the fallback and switches to custdate once approved.
New-to-a-branch or new-to-a-salesperson is **not** new. **[owner]**

**Returning PIC** — bought in the period and is not new. **[owner]**
**Reactivated** — returning, and the previous purchase was 12+ months before this one. **[owner]**
Shown as a sub-count of returning.

**Attribution of a new PIC** — to the branch, salesperson and channel of its **first** invoice in the
period. **[call]** A returning PIC counts for every branch/salesperson that sold to it in the period
(each grouping counts distinct PICs, so a PIC appears once per group, never twice in one group).

**Frequency (all three, over the 12 months ending at the report's to-date)** **[owner]**
- **A — months bought:** distinct months with a visit, 1–12. Classes "1 month" … "12 months".
- **B — longest streak:** longest run of consecutive months with a visit, 1–12.
- **C — buying cycle:** average days between visits (needs ≥ 2 visits), bucketed: every month or less
  (≤ 31 d), every 2 months, 3, 4–6, 7–12, once a year or less. **Overdue** = days since last visit
  > 1.5 × own cycle. **[call]** for the 1.5 factor and bucket edges.
- **Loyal** = A ≥ 10. **[call]** (the owner's "loyal customer" class; adjustable setting.)

**Retention (period over period)** — of PICs who bought in the previous period of equal length, the
share that bought again in this period. **[call]** Plus a monthly cohort table (month of first
purchase × months since) for the last 12 months.

**Basket** — per visit: net sales, items (units), lines, distinct categories. Averages are per visit,
not per invoice. **[call]**

**Shared phone** — a call on a number held by several PICs counts **once**, on the PIC that bought most
recently on/before the call date; all sharing PICs are listed beside it. **[owner]** (Implemented in PR 41.)

**Call statuses** (from the PBX record):
- **Missed call** — incoming, not answered by anyone: hung up while waiting in the queue/IVR, no
  answer, busy or failed.
- **Unanswered call** — outgoing, the customer did not pick up: no answer, busy or failed.
- **Returned** — a missed call followed by an answered call (either direction) with the same number
  within 24 hours. **[call]** The window is a setting. Time-to-return is measured.
- **Not returned** — missed, and no answered contact within the window. These are the action list.
- **Reach attempts** — for outgoing calls to one number on one day: how many attempts before the first
  answer, or "not reached".
- Transfer legs never count as calls.

**Call → purchase** — an answered call followed by a purchase by the same PIC within 7 days (and the
same-day subset). **[call]**

**Unknown number (possible new PIC)** — a customer call whose number matches no PIC. **[owner]**

## 5. Placement and access

- Route `/customers/pic-analytics`, menu item «تحليلات العملاء» in the **العملاء** group. **[call]**
  (The owner allowed العملاء or مركز الاتصال; the missed-calls and leads tabs are also linked from
  مركز الاتصال → تحليلات التواصل as a shortcut to the same screen, not a copy.)
- **Admin + supervisor:** all branches, everything, export. **[owner]**
- **Named branch managers:** granted one by one by admin (copy `StockAuditAccess`: grant/revoke kept,
  AuditLog). They see **only their own branch**; the branch filter is locked server-side; their
  Excel is their branch only. **[owner]**
- **Branch managers never see cost, gross profit or margin** — removed by the server from the API and
  the Excel, not hidden in React. **[owner]**
- **A PIC who also buys elsewhere:** for a branch manager every amount (sales, visits, basket, lifetime
  value, first/last purchase) comes from **their branch's invoices only**; the customer's labels (new /
  returning / reactivated, frequency class, segment) are computed chain-wide and shown as labels, never
  with the other branches' figures. **[owner]**
- **Calls for branch managers:** in the PIC list, call counts only for PICs who bought at their branch
  in the period. The Call-center, Missed & unanswered and New numbers tabs are admin + supervisor only.
  **[owner]**
- New RBAC module key `pic_analytics` (seeded: admin all, supervisor view+export, nobody else) plus
  a `can_pic_analytics` cap flag for the menu. A module that is never seeded is open
  (`matrix_allows`), so seeding is part of the batch. **[call]**
- Phone numbers follow the existing masking (`apps/customers/access.py phones_visible`).
- Every export → `AuditLog` (new action `pic_analytics_exported`) with user, filters, row counts.

## 6. The screen

One page, a filter bar, tabs. Filters: from/to (required), branch (locked for branch managers),
salesperson, call-center agent, channel bucket, general category, customer segment, customer type
classification, frequency class. A `DataFreshnessBar` with `sales`, `customers`, `calls`.

| Tab | Shows |
|---|---|
| **نظرة عامة** Overview | KPI cards: distinct PICs, new, returning, reactivated, visits, invoices, net sales, GP & GP% (management only), items, avg basket (net / items / categories per visit), visits per PIC, retention %, calls in/out, missed not returned. Trend by month. |
| **العملاء** PIC list | One row per PIC: name, PIC, branch of last visit, segment, net sales, GP (mgmt), visits, invoices, items, avg basket, categories bought, channels used, first/last purchase, days since last, A/B/C frequency, overdue flag, calls in/out, missed, last call, avg days between calls, talk time, call→purchase. Sort, search, filter by any column. |
| **الفروع** Branches | Per branch and all branches: distinct PICs, new, returning, reactivated, visits, net, GP (mgmt), basket, retention, PICs per frequency class. |
| **البائعون** Salespeople | Per salesperson: distinct PICs served, new PICs (first-invoice attribution), returning PICs, visits, net, GP (mgmt), basket, items per visit, categories per visit, share of returning. |
| **مركز الاتصال** Call center | Per agent: calls in/out, answered, talk time, distinct PICs reached, new PICs sold (agent sales codes), call→purchase rate, unanswered outgoing and reach attempts. |
| **القنوات والأصناف** Channels & categories | Distinct PICs and net per channel bucket and per general category (medicine, others, cosmetics, supplements …); cross-category rate. |
| **الولاء والتكرار** Retention & frequency | Counts per class for A (1–12 months), B (streaks), C (cycles); loyal; overdue list; retention %; cohort table. |
| **المكالمات الفائتة** Missed & unanswered | See §7. |
| **أرقام جديدة** New numbers | See §8. |

Tabs follow the house rules: `useHelpTab(tab)`, `useGridKeyboard` on grids, branch labels via
`useBranchLabels` (never a bare code), refresh button, no modals for common actions.

## 7. Missed and unanswered calls

Data from `pbx.CdrCall`, never from the live bridge. October 2026 for scale: 107 missed incoming
calls from 48 numbers, of which **only 19 were followed by an answered contact within 24 h**; misses
peak 12:00–14:00. 3,715 of 6,022 outgoing calls were not answered.

- **KPIs:** missed calls, missed numbers, returned within window, not returned, median
  time-to-return, missed rate by hour × weekday (heatmap), by queue; unanswered outgoing per agent,
  reach rate per number, average attempts to reach.
- **Joined to PIC:** each row shows the PIC (or "number shared by N PICs" with the list), customer name,
  segment, last purchase, whether they bought anyway within 7 days, and lifetime value — so the most
  valuable missed customers sort to the top.
- **Actions (reuse, no new workflow):** «اتصل» → existing `/api/pbx/dial/`; «جدولة معاودة» → existing
  CallLog call-back (`status='callback'`, `callback_due`); the row leaves the not-returned list as soon
  as an answered call to that number appears in the PBX record.

## 8. New numbers (possible new PICs)

October 2026 for scale: 366 calls from 229 numbers with no PIC (155 of them called in).

- One row per unknown number: calls in / out, answered, missed, first and last call, the agent who last
  talked to it, talk time, whether it is a mobile or landline.
- **Labels** to keep the list clean: "not a customer" with a reason — staff, supplier, branch,
  doctor, spam. A small `PhoneLabel` table (number key, label, note, who, when). Labelled numbers drop
  out of this list and out of the "unknown" counts. **[call]**
- **Becoming a PIC:** the PIC is created in SOFTECH as today. After the customer sync, the nightly
  call re-link attaches **all past calls** of that number to the new PIC automatically. The tab shows
  "became a PIC" with the date and whether it then bought — the conversion KPI (unknown numbers that
  became PICs and bought, per agent and branch).
- No create-PIC button that writes to SOFTECH (deferred, §2). The row offers «نسخ الرقم» and a link to
  the existing customer add flow if the builder finds one that fits; otherwise list-only. **[call]**

## 9. Excel export

One workbook per export: a sheet per tab with the active filters, plus a "filters & definitions" sheet.
RTL, frozen header, navy header fill (`022871`, pattern in `apps/finance/cash_views.py`), branch labels
via `recon_labels.branch_label`. Large PIC lists use openpyxl write-only mode. GP/cost columns are
absent for branch managers. Export is a separate permission (`pic_analytics.export`) and is audited.

## 10. Performance

Do not aggregate raw invoice lines per request. A nightly build (after the 03:45 sales catch-up and the
03:55 call re-link) writes a fact table; the screen aggregates the fact table.

- **`PicDayFact`** — grain: PIC × day × branch × salesperson × channel. Columns: invoices, returns,
  net, cost/GP, units, lines, net per general category (fixed columns or JSON — builder's choice),
  is-first-purchase flag. Built from `PurchaseHistory` + lines; rebuilt for the last 7 days nightly,
  full backfill once.
- **Per-PIC rollup** (A/B/C frequency, first purchase, last purchase, cycle) for the 12 months ending
  "yesterday", rebuilt nightly. A report whose to-date is not yesterday computes A/B/C from
  `PicDayFact` on the fly (bounded: 12 months × active PICs).
- Calls aggregate straight from `pbx.CdrCall` (≈ 130K rows, indexed on `pic, call_at`).
- Target: any tab under 3 s for a one-month range across all branches.

## 11. Schema and sync changes

| Change | Note |
|---|---|
| `Customer.softech_created_at` from `localcustomers.custdate`, read in the customer sync | **Stop-and-ask item (CLAUDE.md): changes what the SOFTECH sync stores.** Read-only; one more column in the existing query. Needs owner approval before building. |
| `PicDayFact`, per-PIC rollup table | Our tables only. |
| `PicAnalyticsAccess` (named grants) | Copy of `StockAuditAccess`. |
| `PhoneLabel` | Our table only. |
| RBAC module `pic_analytics`, cap flag, AuditLog action | Seed in the same batch. |
| Setting: return window (24 h), call→purchase window (7 d), loyal threshold (A ≥ 10), overdue factor (1.5) | `apps/config` system settings. |

## 12. Phases (each one shippable and tested)

1. **Foundation** — custdate in the customer sync (after approval), `PicDayFact` + rollup + nightly
   job + backfill, access grants + RBAC seed + cap flag, the definitions as tested pure functions
   (visit, new/returning/reactivated, A/B/C, retention).
2. **Dashboard** — page, filters, Overview, PIC list, Branches, Salespeople, Channels & categories,
   Retention & frequency; GP masking; help + tour.
3. **Calls** — Call-center tab, calls columns in the PIC list, Missed & unanswered tab with actions,
   New numbers tab with labels and conversion.
4. **Export** — the workbook, audit, export permission; help updated.

## 13. Left to the builder

Fact-table column layout, chart components (the app has no chart library; follow
`SalesDashboard.jsx` / `ReservationsAnalyticsPage.jsx`), API shape and pagination, exact Excel styling,
how the "add customer" link works if a fitting flow exists.

## 14. Open questions for the owner

Branch-manager scope and call visibility: decided 2026-11-02 (§5).

1. Approve adding `custdate` to the customer sync (§11).
2. The **[call]** defaults above: 24 h return window, 7-day call→purchase, loyal = bought in ≥ 10 of 12
   months, overdue = 1.5 × own cycle, new-PIC attribution to the first invoice's salesperson, returns on
   their own date, a "بدون PIC" sales line, KPI-board channel rule.

---

## 15. As built (deviations decided during the build)

- **Gross profit follows the KPI board rules.** `PicDayFact.gp_net` / `gp` use profit channels, excluded items and line revenue (Σ line total − qty × cost at sale); `gp_pct = gp / gp_net`. The header-total-minus-cost version was wrong.
- **Grantee scope** = home branch + allowed branches − restricted branches; a granted branch manager never gets the all-branch shortcut, cost, GP or margin.
- **Options endpoint.** `GET options/` returns the scoped lists for the filter selects (salespeople, categories, customer types, segments, channels, frequency buckets, agents for management only).
- **New-PIC date fallback.** A PIC without `softech_created_at` falls back to its first purchase; `new_reliable_from` (2025-08-01) is returned only when no customer has `softech_created_at` yet.
- **Channel bucket** is mapped by sales channel only (as the KPI board does); unmapped = `other`; the `exclude` bucket stays in PIC totals and shows as its own line «مستبعدة من مؤشرات KPI».
- **Frequency is computed at the report to-date**, not only from the rollup (rollup reused only when the to-date is yesterday); labels (new/returning/reactivated, frequency) are chain-wide, amounts are scoped.
- **New-PIC category** = the category with the largest positive net on its first visit day.
- **Number handles are call ids.** Unknown numbers never reach the browser: rows carry `number_id` / `call_id` (latest `CdrCall` pk), and dial / label / call-back resolve on the server.
- **Server-side dial** (`calls/missed/<call_id>/dial/`, `numbers/<id>/dial/`, management, audited) reuses the PBX dial logic; «نسخ الرقم» was dropped from New numbers.
- **Call-back** = `POST calls/missed/<call_id>/callback/` creating a `callcenter.CallLog` (`status='callback'`), reusing the existing call-back queue.
- **Masking.** Unlinked numbers stay masked even for management (existing phone rules, incl. the external-zone block).
- **Call cards stay chain-wide** under branch / salesperson / category / segment filters (calls have no branch) and are labelled «كل مكالمات العملاء»; `missed_not_returned` ignores the agent filter.
- **Fact grain.** The unique grain includes the nullable branch, so builds delete + rebuild per day range; rules take only visit days ≤ the end date.
- **Export** column letters use `get_column_letter` (more than 26 columns).
- **Scheduled jobs:** `pic_facts` 04:15, `pbx_cdr_sync` every 10 min, `pbx_cdr_relink` 03:55. Deploy: migrate, `seed_permissions`, `build_pic_facts --since 2024-08-01`, restart the scheduler.
- **Period block.** Every read endpoint returns `period: {from, to, data_from, data_to, clamped}`. `data_to` = min(requested end, latest built `PicDayFact` day) and the report end is clamped to it; the page shows «البيانات حتى …» (+ «تم ضبط الفترة على البيانات المتاحة»).
- **Missed-calls action list** drops a row as soon as ANY answered call (either direction) on its number follows it; the returned / not-returned KPIs keep the 24 h window. A row with a pending call-back (`CallLog` status `callback` on that number, due ≥ the missed call) carries `callback_pending` and a second call-back for it is refused with 409.
- **Export computes each list once** (internal `page_size=None` = all rows, never reachable from the HTTP params; the API cap stays 200), resolves phone visibility once per user (`customers.access.phones_checker`) and shares the classification / overdue maps within one request. It also carries the overdue sheet and the unanswered-outgoing sheet, with labels instead of codes. Measured on the local dev DB (all branches, management): one month 8.8-14 s; twelve months (2025-11-01..2026-10-31, 45,615 PICs) 55-72 s, noisy machine. That is at nginx's 60 s limit: raise `proxy_read_timeout` for `/api/pic-analytics/export/` (or make it a background job) before offering year-long exports.

### Follow-ups (not built)

- PIC search (name / PIC / phone) in the PIC list.
- Conversion KPI (call → purchase) per agent and per branch.
- New PICs sold per agent (today one team figure, because SOFTECH user codes are not tied to PBX extensions).
- Same-day call → purchase subset next to the 7-day figure.
- `basket_lines` (lines per visit) basket metric.
- Undo for a number label, and a «labelled numbers» list to review / reverse labels.
