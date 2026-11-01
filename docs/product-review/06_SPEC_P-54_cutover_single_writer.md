# 06 · SPEC P-54 — Cutover safety: one writer instance, one signed-off switch table

**Status:** specification, approved for spec 2026-10-30.
**Build:** NOT authorised yet. This is a **stop-and-ask** item, because SOFTECH writes and double-post risk apply.

**Owner decisions it implements**
- All 15 SOFTECH writers are ON at go-live, **on the VPS only**.
- The **office instance runs read-only** as the development copy (confirmed 2026-10-30).

## 1. Problem (measured)

**The office `.env` turns these 15 writer flags ON**, while every code default in `config/settings.py` is OFF:
- AP_RECONCILE_WRITER;
- POS_OFFERS_EXECUTION, POS_OFFERS_POSDISCP_WRITE, POS_OFFERS_PROMO_WRITE;
- CUSTOMER_BRANCH_COPY_WRITE, POINTS_REMOVAL_WRITE;
- ISR_WRITER, SALES_RATE_WRITER;
- COVERAGE_WRITER, COVERAGE_WRITE_MAXQTY, COVERAGE_AUTO_TOPUP;
- INVOICE_WRITER, INVOICE_SUPPLIER_ITEM_WRITE;
- SHORTAGE_SOFTECH_WRITE;
- DEMAND_ENGINE_SCHEDULE (COUPON_POS_GUARD is a guard, not a writer).

**Other problems**
- 5 keys appear twice. python-decouple keeps the last value, which is silent.
- Two instances with these flags ON would both write: a double post (Rule 3).

## 2. Scope

1. **Instance role**
   - New setting `WRITER_INSTANCE` (bool, default **False**).
   - Every SOFTECH writer gate checks `WRITER_INSTANCE and <feature flag>`. Implement it as one helper,
     `config.sybase.writer_allowed(flag_name)`, used by every existing gate. **No gate logic is duplicated.**
   - On a non-writer instance the scheduler **does not register** writer jobs. Writer jobs:
     - pos_orders_flush / pos_cancel_write;
     - coverage_topup;
     - demand_engine_scheduled, if it writes;
     - any job calling a writer service.
2. **Office = development copy**
   - Office `.env`: `WRITER_INSTANCE=False` + `SOFTECH_READ_ONLY=True`. The existing driver-level kill-switch
     (`config/sybase.py:207-303`) blocks every non-read statement.
   - Claude Code keeps working here, reading live SOFTECH.
3. **Startup guard** (both the web and `run_scheduler` processes)
   - **Refuse to start** if `.env` contains a duplicated key. The error names the key and both line numbers.
   - Log at INFO, at boot: `WRITER_INSTANCE`, `SOFTECH_READ_ONLY`, and the list of writer flags that are ON.
   - **Refuse to start** if `WRITER_INSTANCE=True` and `SOFTECH_READ_ONLY=True`. That is a contradictory setup.
4. **Switch table**
   - A read-only admin endpoint `GET /api/sync/writer-switches/` lists every writer flag with:
     - effective value;
     - code default;
     - the module it protects;
     - `WRITER_INSTANCE`;
     - `SOFTECH_READ_ONLY`.
   - Shown as a card on `/sync` (admin only).
   - Help text in `apps/help/content/` (Arabic + English), per CLAUDE.md 5b.
5. **Signed-off production table**
   - The appendix below, filled by the owner at cutover (value, initials, date).
   - Kept in the runbook (`deploy/LINKDATACENTER_VPS_RUNBOOK.md` §11).

## 3. Go-live order (runbook §11 addendum)

1. Office: set `WRITER_INSTANCE=False`, `SOFTECH_READ_ONLY=True`, restart the web process and the scheduler. Confirm
   the boot log shows "read-only, no writers".
2. VPS:
   - `migrate`, including `customers/0029`, `sync` 0006, `help` 0007–0012;
   - restart **all** processes after migrating. A process started before a migration writes with the old column set:
     that was the cause of the 20 schema-mismatch sync failures.
3. VPS: **kill-switch test.** Start with `SOFTECH_READ_ONLY=True` and confirm a writer dry-run is refused. Then
   switch it OFF.
4. VPS: `RBAC_ENFORCEMENT=enforce` (already planned).
5. VPS: `WRITER_INSTANCE=True`. Enable the writers **one module at a time**; after each, run one real operation and
   **read it back** in SOFTECH (the existing read-back paths of each writer).

## 4. Acceptance criteria

- With `WRITER_INSTANCE=False` and every feature flag True, **no writer service executes a SOFTECH write** (test
  per writer gate via `writer_allowed`) and **no writer job is registered** (scheduler test).
- A duplicated `.env` key prevents startup, with a clear message (test using a temp env file).
- `WRITER_INSTANCE=True` + `SOFTECH_READ_ONLY=True` prevents startup.
- `/api/sync/writer-switches/` returns all flags; admin only (RBAC test); help entry present (`test_help.py` passes).
- The existing writer tests still pass. The test runner forces `SOFTECH_READ_ONLY=True` (`settings.py:426-432`);
  keep that.

## 5. Out of scope

- Changing any writer's own logic.
- Automatic failover between instances.

## Appendix — production switch table (owner to fill at cutover)

| Flag | Protects | Prod value | Initials / date |
|---|---|---|---|
| WRITER_INSTANCE | the whole instance | True (VPS) / False (office) | |
| SOFTECH_READ_ONLY | kill-switch | False (VPS) / True (office) | |
| ISR_WRITER_ENABLED | ISR (stockisr) | ON (owner) | |
| SALES_RATE_WRITER_ENABLED | stkbal.monthlyqty | ON | |
| COVERAGE_WRITER_ENABLED / COVERAGE_WRITE_MAXQTY / COVERAGE_AUTO_TOPUP_ENABLED | stkbal max stock | ON | |
| INVOICE_WRITER_ENABLED / INVOICE_SUPPLIER_ITEM_WRITE_ENABLED | purchase posting, itemssuppliers | ON | |
| SHORTAGE_SOFTECH_WRITE_ENABLED | items shortage flags | ON | |
| AP_RECONCILE_WRITER_ENABLED | A/P allocations | ON | |
| POS_OFFERS_EXECUTION_ENABLED / _POSDISCP_WRITE / _PROMO_WRITE | offers | ON (note: promotions also need the P-38 gate) | |
| CUSTOMER_BRANCH_COPY_WRITE_ENABLED / POINTS_REMOVAL_WRITE_ENABLED | customer flags / points | ON | |
| DEMAND_ENGINE_SCHEDULE_ENABLED | engine schedule | ON | |
| POS_WRITER_ENABLED | indirect POS | OFF until P-39 parity | |
| PRICING_SOFTECH_WRITE_ENABLED, REPLICATION_REPAIR_ENABLED, LOYALTY_SOFTECH_WRITE_ENABLED, PERSONAL_COMMENT_WRITE_ENABLED, POS_CANCEL_WRITE_ENABLED, REPLACEMENT_POSTING_ENABLED, INSURANCE_SOFTECH_WRITE_ENABLED, CUSTOMER_MERGE_WRITE_ENABLED | (currently OFF everywhere) | owner to decide | |
