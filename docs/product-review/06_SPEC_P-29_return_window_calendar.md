# 06 · SPEC P-29 — Return-window calendar

**Status:** **BUILT 2026-10-31** (owner go-ahead; **top of Batch 2**). Lines cover branch shelves, HQ live stores and
store 105 (102 / 103 not shown); branch lead time 14 days. P-28 (near-expiry worklist) reuses this card's window rule, and P-31
depends on fast returns.

**Owner input** (ledger row P-29, backlog "Owner input 2026-10-30" and P-29 "Revision after owner input")
- Suppliers accept expiry returns, but not everything. Credit is given.
- **Window = expiry month −2 to expiry month +1**, configurable per supplier.
- **Pharma Overseas (SOFTECH supplier 565)** and **Ibn Sina (260)** let us enter return items in their own system.
  They answer at once: accepted or not, and which expiry dates are allowed. **No API or export is known.**
- Staff record that answer per line, which builds a per-supplier **acceptance history**.
- The list covers **branch shelf stock and store 105** alike. Branches get "send to HQ for return by <date>" lines.
- A line closes automatically when doc 120 (return to supplier) for that supplier + item appears.
- **Advisory only.** No return document is drafted or posted by us (owner rule 2026-09-15).
- Store meanings come from P-26: 105 = return candidates, 102 = write-off, 103 = expired cosmetics, 110 = closed.


**Owner decisions 2026-10-31** (these override anything below that disagrees)
- Supplier returns are owned by the **HQ purchasing and replenishment specialists**. Today both use the `purchasing` role (HQ only); there is no separate replenishment role. The monthly digest and the worklist go to that role. Confirm at build time that every replenishment specialist holds it.
- Store 110 is excluded (P-26 decision).

## 1. Problem (measured)

- Measured with the owner's window rule (backlog, Batch 2). A stock batch was matched to a 565 / 260 purchase entry
  by item + expiry month; this is a heuristic.

  | Location | In window now | Window closes this month | Window opens next month | Window already missed |
  |---|---|---|---|---|
  | Branch shelves | 47k | 7k | 33k | 17k |
  | Store 105 | 16k | 8k | — | 64k |
  | Store 102 | — | — | 1k | 32k |
  | **Total (2 suppliers)** | **≈64k** | **≈15k** | **≈36k** | **≈113k** |

- About 206k EGP a year leaves quarantine through doc 120. Chain-wide purchase returns are about 1.95M EGP in 12
  months (`stock_audit.StockLedgerLine`, `03_DATA_OPPORTUNITY_MAP.md`).
- **Nothing in the system says which supplier should take back which batch, and by when.** Branches notice too late.
- `batches.ExpiryDisposalRecord` (decision `return_supplier`) exists, but it has **0 records** and is never
  reconciled to doc 120 (`02_CURRENT_STATE_FINDINGS.md` §3.2).

## 2. Scope

### 2.1 Window rule (one pure function, shared with P-28)

1. New module `apps/batches/return_window.py`, function
   `window_for(expiry_date, policy, today) → {opens, closes, state}`:
   - `opens` = first day of (expiry month + `open_offset`), default −2;
   - `closes` = last day of (expiry month + `close_offset`), default +1;
   - `state` is one of:

   | State | Arabic label | Rule |
   |---|---|---|
   | `opens_next_month` | «تفتح الشهر القادم» | `opens` falls in next month |
   | `open` | «داخل النافذة» | opens ≤ today ≤ closes, and `closes` is after this month |
   | `closes_this_month` | «تُغلق هذا الشهر» | open, and `closes` falls in this month |
   | `missed` | «فاتت النافذة» | closes < today |
   | `later` | — | not shown |

2. Pure, with no DB access. P-28 imports it; nothing else re-implements the rule.

### 2.2 Supplier return policy

1. **New model** `procurement.SupplierReturnPolicy`, one row per supplier code. Fields:
   - `accepts_expiry_returns` (bool);
   - `open_offset` (−2) and `close_offset` (+1);
   - `self_entry` (bool);
   - `entry_layout` (JSON column order for the self-entry export, set once from the supplier sample);
   - `notes`, `updated_by`, `updated_at`.

   **Migration (procurement)**, plus a data migration seeding **565** and **260** with `accepts=True`,
   `self_entry=True` and the default offsets (owner-stated facts). No other supplier is seeded.
2. It lives in `procurement` beside `SupplierSegmentation`, so P-42 (supplier terms) can extend it rather than add a
   second supplier-terms table.
3. Edits are allowed for admin and `purchasing` edit (`matrix_permission('purchasing', post=('edit',))`), checked
   server-side. Every change writes `AuditLog.log` with before/after.

### 2.3 Which supplier sent this batch (attribution)

1. Stock rows: `StockExpiryBalance` with `qty > 0`, roles `live`, `return_candidate`, `write_off` and
   `cosmetics_expired` (P-26 role map). **Closed stores are never listed.**
2. Candidates: `PurchaseExpiryEntry` rows with the same `item_code` and the same `entered_expiry` **month**, from
   suppliers with `accepts_expiry_returns=True`.
3. Confidence, shown as a chip on every line:

   | Confidence | Arabic label | Rule |
   |---|---|---|
   | `exact` | «مطابق» | one supplier, same exact date |
   | `month` | «نفس الشهر» | one supplier, same month only |
   | `ambiguous` | «أكثر من مورد» | several suppliers; all are listed and a person picks one |
   | `none` | «مورد غير معروف» | no entry; these lines go to the "no policy / unknown" section |

4. **Ingestion change.** `expiry_audit.run_backfill` mirrors the union of the main suppliers and suppliers that have
   an active policy.
   - `audit_candidates`, `supplier_scorecard` and `expiry_prone_items` keep filtering by
     `MAIN_SUPPLIER_CATEGORIES`, so the audit's meaning is unchanged.
   - Rows are additive and idempotent (existing unique key).
5. **Known limit.** The mirror holds only those suppliers. If a non-mirrored supplier delivered the same item and
   expiry month, we cannot see it. That is why every line shows its confidence and needs a person's confirmation.
6. Value = qty × catalog unit cost, the same basis as P-26 and today's report.

### 2.4 Persisted actions: reuse `ExpiryDisposalRecord`

No new ledger. A line someone acts on becomes an `ExpiryDisposalRecord` with `decision='return_supplier'`.

**Migration (batches)** adds:
- `source` (`manual` | `return_window`);
- `window_opens`, `window_closes` (snapshot);
- `match_confidence`;
- `supplier_answer` (`''` | `accepted` | `partial` | `rejected`);
- `allowed_expiry` (date, null);
- `accepted_qty`;
- `answered_by`, `answered_at`;
- `returned_qty`;
- `softech_doc_refs` (JSON list of consumed doc-120 line keys);
- `closed_by_ledger_at`.

| Step | Who | What happens |
|---|---|---|
| «طلب مرتجع» (bulk tick) | `BATCH_DISPOSAL` | Creates draft records. **Idempotent:** one open record per supplier + node + store + item + batch + expiry; a second click creates nothing |
| Record answer | `BATCH_DISPOSAL` | accepted / partial (+ accepted qty, allowed expiry) / rejected. Rejected → status `cancelled`, reason «رفض المورد» |
| Approve | existing gate (admin / quality_manager / supervisor) | Unchanged |
| Close | automatic (2.6) or the existing manual «تم التنفيذ» | `done` |

Every create, answer and status change writes `AuditLog.log`.

### 2.5 Acceptance history (deterministic counts)

1. Read from answered records: per supplier × item, accepted n, rejected n, last answer and last allowed expiry.
2. Each calendar line shows a hint column «سابقاً», for example «قُبل 3 من 3» or «رُفض آخر مرة».
3. The supplier header shows the acceptance rate by value.
4. Lines are only sorted and hinted. No rule hides a line automatically.

### 2.6 Auto-close from doc 120

1. Source: `procurement.PurchaseLine` with `doccode='120'` (supplier = `stktransm.cust_branch_code`, verified in
   `procurement/queries.py`), refreshed by the procurement engine (`purchases` freshness domain).
2. Match on same supplier + item, with `doc_date ≥ record created date`. Open records are filled oldest-first by
   qty.
   - Each `PurchaseLine` key is consumed **once** (stored in `softech_doc_refs`). Re-running changes nothing.
   - Full qty → `done` with the reference. Partial → stays open with `returned_qty` shown.
3. `PurchaseLine` collapses expiry splits, so matching cannot use the expiry date. This is stated in the help.
4. Runs daily after the procurement refresh (new scheduler job `return_window_reconcile`, catch-up when due, like
   `procurement/refresh.py`), and when the tab's refresh button is pressed.

### 2.7 Screen: `/batches` new tab «📆 تقويم المرتجع» (key `return_window`)

1. **Header:**
   - month picker, defaulting to this month;
   - supplier and location filters (branch shelves · HQ live stores · 105 · 102 · 103), with branch labels via
     `useBranchLabels`.
2. **Freshness:**
   - `DataFreshnessBar domains={['expiry','purchase_expiry','purchases']}`.
   - A new freshness domain `purchase_expiry` reads `PurchaseExpiryAuditRun` (cadence 1440).
   - The existing stock-expiry and purchase-expiry sync buttons (`CanRefreshExpiry`) and a procurement refresh
     (`procurement.refresh.start_background`, as `/supply` uses) appear on the tab, each with a `ProgressBar`.
3. **Per-supplier summary row:** four values, «تفتح الشهر القادم» · «داخل النافذة» · «تُغلق هذا الشهر» ·
   «فاتت النافذة». Each value can be clicked to filter the grid.
4. **Grid** (uses `useGridKeyboard`: ↑↓, Space tick, Ctrl+A, Enter = record "accepted"). Columns:
   - item, location, batch, expiry, qty, value;
   - window closes, state chip, confidence chip;
   - «سابقاً» history, record status.

   Answers are recorded inline (select + qty + allowed expiry). There is no modal.
5. **Actions:**
   - «طلب مرتجع» on the ticked rows;
   - «⬇️ تصدير للمورد»: Excel for one supplier. For `self_entry` suppliers the columns follow `entry_layout`. Until
     the sample arrives, the columns are supplier item code (from `invoices.VendorItemMapping.vendor_item_code`
     where known), item name, our code, qty, expiry, batch;
   - «⬇️ تصدير Excel» of the grid.
6. **Section «موردون بدون سياسة مرتجع»:** value by supplier for in-window stock whose supplier has no policy or is
   unknown. This tells purchasing which policies to enter next.
7. **Policy table** at the bottom: inline row edit, for policy editors only.
8. **Branch users:**
   - They see only their branch's shelf lines, enforced server-side. Until Security batch 5's branch-scope helper
     merges, the view filters by `StaffProfile.branch`.
   - Each line reads «أرسل للرئيسي للمرتجع قبل <date>», where date = `closes` − `return_window_branch_lead_days`
     (SystemSetting).
   - The physical move to HQ is a native SOFTECH transfer.

### 2.8 Notifications (reuse existing jobs)

1. **Branches:**
   - The weekly `send_expiry_worklists` notification (`expiry_audit._notify_branch_worklist`, same recipients,
     same ISO-week dedup) gets a second section: "send to HQ for return by <date>" lines for that branch.
   - The message stays one per week.
2. **Returns owner:**
   - A monthly digest on the 1st: in window · closes this month · opens next month, per supplier.
   - Recipients: SystemSetting `return_window_recipients` (default = admins).
   - Dedup key `return_window_<YYYY-MM>`.
   - New notification type `return_window_digest`: a label-only migration on notifications, so P-55 routing applies.

### 2.9 Monthly snapshot for the KPI

1. **New model** `batches.ReturnWindowMonthly`: supplier + month → values of the four states, written on the 1st by
   the digest job.
2. **Migration (batches).** It is needed because `StockExpiryBalance` is a replace-snapshot and keeps no history.

### 2.10 Tests (new file `apps/tests/test_return_window.py`)

| Test | Proves |
|---|---|
| window maths | expiry 2026-12-15 → opens 2026-10-01, closes 2027-01-31; year roll-over; custom offsets |
| states | each of opens_next_month / open / closes_this_month / missed on fixed dates |
| attribution | exact / month / ambiguous / none on fixtures |
| closed excluded | a 110 row never appears |
| ingestion union | policy supplier mirrored; `audit_candidates` still main-only |
| request idempotent | second «طلب مرتجع» creates 0 records |
| answer + audit | answer stored, `AuditLog` row written, rejected → cancelled |
| permissions | viewer cannot request/answer; non-purchasing cannot edit policy (server-side 403) |
| branch scope | a branch pharmacist sees only own-branch lines |
| auto-close | doc 120 line closes a record; a re-run consumes nothing twice; partial qty stays open |
| history | counts per supplier × item |
| digest dedup | one monthly digest per recipient; a re-run sends 0 |
| snapshot | 1st-of-month row written once |
| freshness | `purchase_expiry` domain returns `stale` correctly (`test_sync_freshness.py`) |
| scheduler | `return_window_reconcile` registered (`test_scheduler_jobs.py`) |

Existing tests to keep green: `test_purchase_expiry_audit.py`, `test_expiry_count_spawn.py`,
`test_expiry_rebalance.py`, `test_notification_routing.py`, `test_help.py`.

### 2.11 Help

`apps/help/content/batches.py`, screen `batches.main`:
- new tab `return_window`: window rule, states, confidence chips, history hint, self-entry export, auto-close limit
  (no expiry on doc 120 lines), branch "send by" lines;
- tab count «سبعة» → «ثمانية» in the summary and tour;
- bump `updated`.

`BatchesPage` already calls `useHelpTab(tab)`.

## 3. Acceptance criteria

- One function computes every window. P-28 can import it without copying it.
- For 565 and 260, the tab shows the four states for branch shelves and 105, with values that reconcile to the
  backlog baseline within the heuristic's limits. Checked read-only on the office DB after deploy; differences are
  explained, not hidden.
- A buyer can tick lines, export the self-entry sheet, and record answers without a modal. History hints appear on
  the next visit.
- A doc 120 for the same supplier + item closes the record automatically, once.
- No SOFTECH write anywhere in this card (code review: no writer import, no `writer_allowed` call).
- Help updated; `test_help.py` passes; frontend build passes.

## 4. Measurement

- **KPI:** % of window-eligible value returned before the window closed, per supplier per month. Eligible =
  `ReturnWindowMonthly` "closes this month" value; returned = `done` records with close ≤ `window_closes`.
- Value entering «فاتت النافذة» per month. Baseline ≈113k already missed (2 suppliers).
- Return credit per month: doc 120 value from quarantine stores (`PurchaseLine.return_type='expiry'`). Baseline
  ≈206k a year.
- Acceptance rate by value per supplier, from recorded answers. There is no baseline; it starts at go-live.

## Out of scope

- **Any SOFTECH write:** drafting or posting a doc 120 return, a transfer to HQ, or a write-off. All stay native.
- Integration with the suppliers' own systems. None is known; we only export a sheet in their order.
- The decision between return, move, near-expiry corner and loss. That is P-28; this card only supplies the window.
- EDA Decree 47/2025: press-reported, not verified. No rule is built on it.
- Return windows for suppliers other than 565 and 260 until purchasing enters them.

## Open questions (owner inputs still needed)

1. **Self-entry screen sample** for 565 and 260: fields and order (sets `entry_layout`). The ledger lists this as
   evidence still needed.
2. **Other main suppliers' windows** (Ramco, Egy Drug, …): same −2/+1, or different? Do they take expiry returns at
   all?
3. **Returns owner:** who receives the monthly digest and records answers (`return_window_recipients`)?
4. **Branch lead time** before the window closes for "send to HQ by <date>". Proposed 14 days; owner to confirm.
5. Should a supplier's "accepted" answer **auto-approve** the record, or keep today's separate approval step?
6. Should **store 102** lines with an open window be shown? The owner calls 102 unreturnable, but the baseline found
   ≈1k opening next month. Should 103 cosmetics be shown when a cosmetics supplier has a policy?
7. Is **Ibn Sina (260)** classified as a main supplier in `SupplierSegmentation` today, so its history is already in
   `PurchaseExpiryEntry`? To verify (read-only). If not, the ingestion union (2.3.4) plus one backfill run covers it.
8. **Units:** do `stkbalexpiry.itemqty` and doc 120 `transqty` use the same unit (packs), so qty matching in the
   auto-close is exact? To verify (read-only sample of 20 returns).
9. Credit basis: does the supplier credit at purchase cost (our value basis) or at another price? This only affects
   how the KPI is read, not the list.
10. Does "in window now" in the baseline include the "closes this month" value? This spec keeps them separate; the
    baseline is re-measured with this definition at build time.

## Stop-and-ask

- Any SOFTECH write (return document, transfer, adjustment). Not part of this card.
- Seeding a policy for any supplier beyond 565 and 260 without the owner's or purchasing's confirmation.
- A one-off `sync_purchase_expiry --years 3` backfill for newly added policy suppliers. It is SOFTECH SELECT-only and
  idempotent, but the owner runs it off-hours.
