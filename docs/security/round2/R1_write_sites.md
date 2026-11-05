# R1: SOFTECH write sites, per-site expectations

- **Generated from:** `apps/tests/security/softech_write_manifest.py` (entries with
  `kind == 'write'`) on 2026-11-05.
- **Plan:** [2026-11-05-full-project-test-plan.md](../2026-11-05-full-project-test-plan.md) §7 R1.
- **Decisions:** [decision_pack.md](decision_pack.md).

## How to read a row

- **Switch off means no connection.** This applies to every row and is already proven by
  `test_softech_writes_unswitched.py`.
- **Dry run by default.**
  - "yes": the default call path does not write.
  - "NO — D5": the call is itself the explicit action. These exceptions are listed in the D5
    section below.
- **Idempotency guard:** what stops a second call writing twice. For an absolute-SET writer, a
  second call must change no value.
- **Audit:** who, what, when, before and after. Cells are cut short here; the manifest has the full
  text.
- **Trigger / role refusal.** HTTP routes are covered by the role sweep. "command only" means there
  is no HTTP route to refuse.

| Site | Flag | Dry run by default | Idempotency guard | Audit | Trigger / role refusal |
|---|---|---|---|---|---|
| `customers/branch_copy.py::copy_one` | `CUSTOMER_BRANCH_COPY_WRITE_ENABLED` | yes | no_change skip; optimistic WHERE on the 5 fields | BranchCopyWrite + AuditLog | command only |
| `customers/merge_write.py::merge_one` | `CUSTOMER_MERGE_WRITE_ENABLED` | yes | vf1 tag 'B7 merge <id>' read back before write | CustomerMergeWrite + AuditLog | command only |
| `customers/points_removal.py::remove_one` | `POINTS_REMOVAL_WRITE_ENABLED` | yes | done-skip; WHERE guard; balance re-read | PointsRemoval + AuditLog | command only |
| `discount_approvals/alignment.py::apply_classification_changes` | `PRICING_SOFTECH_WRITE_ENABLED` | NO — D5 | **lock 7_301_011 + skip-unchanged (Q2, done)** | AuditLog softech_item_class_written | POST `/api/pricing-approvals/alignment/apply/` (admin) |
| `discount_approvals/alignment.py::create_new_tier` | `PRICING_SOFTECH_WRITE_ENABLED` | NO — D5 | code-exists check (*MAX+1 race*) | AuditLog softech_tier_created | POST `…/alignment/tier-create/` (admin) |
| `discount_approvals/replication.py::force_replication` | `REPLICATION_REPAIR_ENABLED` | NO — D5 | **lock 7_301_012 + 10-minute repeat refusal (Q2, done)** | AuditLog `softech_replication_forced` on every repair (**D4, done**) + ReplicationGap.repaired_by | POST force-replication / repair (admin); jobs with `auto_repair` |
| `discount_approvals/services.py::execute_price_change` | `PRICING_SOFTECH_WRITE_ENABLED` | NO — D5 | request status pending/failed only (*no row lock*) | ItemPriceChangeRequest (reviewed_by, old/new) | POST `…/<pk>/approve/` (admin) |
| `finance/recon_writer.py::_live_write._write_steps` | `AP_RECONCILE_WRITER_ENABLED` | yes | existing chequestrans row guard (skip / top-up) | ReconAuditEvent (*no actor from commands*, **D2**) | POST allocations write-softech (admin) |
| `finance/recon_writer.py::_reverse_steps` | `AP_RECONCILE_WRITER_ENABLED` | NO — D5 | origin WRITTEN + audit event + row presence | ReconAuditEvent reversed / failed | POST allocations reverse-softech (admin) |
| `finance/recon_writer.py::_top_up._work` | `AP_RECONCILE_WRITER_ENABLED` | yes | only when the existing row < allocation | ReconAuditEvent | via push_allocation |
| `finance/recon_writer.py::complete_half_reversal` | `AP_RECONCILE_WRITER_ENABLED` | NO — D5 | acts only on a proven half-landed state | ReconAuditEvent on success only (**D3**) | shell only |
| `finance/recon_writer.py::complete_half_write` | `AP_RECONCILE_WRITER_ENABLED` | NO — D5 | failed attempt + nothing written | ReconAuditEvent | shell only |
| `finance/recon_writer.py::fix_due_before._work` | `AP_RECONCILE_WRITER_ENABLED` | yes | writes only differing rows | ReconAuditEvent allocation_due_fixed | after write views |
| `insurance/date_service.py::_set_docdate` | `INSURANCE_SOFTECH_WRITE_ENABLED` | yes | open applied-edit refusal + LOCK_DATE_EDIT | SoftechDateEditRun + InsuranceAuditEvent | POST claims softech-date |
| `insurance/date_service.py::_set_motalba_docdate` | `INSURANCE_SOFTECH_WRITE_ENABLED` | yes | **LOCK_DATE_EDIT + applied-run refusal + expected_old** (the manifest said None; corrected) | SoftechDateEditRun (now keeps `motalba_old_dates`, **Q1**) + InsuranceAuditEvent | POST claims softech-date |
| `insurance/date_service.py::_revert_locked` (**new in R1**) | `INSURANCE_SOFTECH_WRITE_ENABLED` | NO (explicit revert) | LOCK_DATE_EDIT + run re-read; only an APPLIED run; one UPDATE per recorded motalbano | run status + the `motalba_old_dates` it restores | POST claims softech-date revert |
| `insurance/management/commands/backfill_bonusqty.py::Command.handle` | `INSURANCE_SOFTECH_WRITE_ENABLED` | yes | writes only drifted lines | SoftechRepriceRun/Edit (*no user*) | command only |
| `insurance/reprice_service.py::_rebalance_locked` | `INSURANCE_SOFTECH_WRITE_ENABLED` | yes | run lock 7301007 + run re-read | SoftechRepriceEdit + InsuranceAuditEvent | POST claims softech-reprice |
| `insurance/reprice_service.py::_revert_locked` | `INSURANCE_SOFTECH_WRITE_ENABLED` | NO — D5 | APPLIED → REVERTED under the run lock | run status + InsuranceAuditEvent | POST reprice run revert |
| `insurance/reprice_service.py::_write_receipt` | `INSURANCE_SOFTECH_WRITE_ENABLED` | yes | see apply_reprice | SoftechRepriceEdit before/after | via apply_reprice |
| `insurance/reprice_service.py::apply_reprice` | `INSURANCE_SOFTECH_WRITE_ENABLED` | yes | plan previewed → applying atomic flip | SoftechWritePlan + SoftechRepriceRun/Edit | POST claims softech-reprice |
| `invoices/supplier_items.py::inject_mapping` | `INVOICE_SUPPLIER_ITEM_WRITE_ENABLED` | yes | noop when already set; guarded UPDATE; verify | AuditLog supplier_mapping_written | POST invoice line learn |
| `invoices/writer.py::_run_write_batch` | `INVOICE_WRITER_ENABLED` | yes | atomic PG flip into pushing (one writer) | SupplierInvoice payload/readback + AuditLog | POST invoices push / push-batch |
| `loyalty/pic_bridge.py::adjust_softech_points` | `LOYALTY_SOFTECH_WRITE_ENABLED` | NO — D5 | select_for_update + 120 s duplicate window | SoftechPointsLog; vf1/vf2 in SOFTECH | POST loyalty adjust (LOYALTY_ADJUST_ROLES) |
| `offers/channel_a.py::_write_posdiscp` | `POS_OFFERS_POSDISCP_WRITE_ENABLED` | yes | only items whose copy differs | AuditLog softech_posdiscp_written | POST offers posdiscp-apply |
| `offers/channel_b.py::_insert_specialoffer` | `POS_OFFERS_PROMO_WRITE_ENABLED` | yes | identical live offer reused; one transaction | AuditLog softech_promo_written | POST offers promo-apply (admin) |
| `personal/writeback.py::_write_and_verify` | `PERSONAL_COMMENT_WRITE_ENABLED` | NO — D5 | absolute SET; ownership re-read | DocumentCommentEdit / DocumentRevision | POST personal documents (can_edit_erp_comments) |
| `pos_orders/writer.py::_delete_pending_from_softech` | `POS_WRITER_ENABLED` | NO — D5 | a cancelled order returns early; header must exist | order status + AuditLog | POST pos-orders cancel (CanPushPosOrders) |
| `pos_orders/writer.py::_exec_insert` | `POS_WRITER_ENABLED` | yes | per caller (vf2 tag + status) | per caller | push_order / probe_order / reservation |
| `pos_orders/writer.py::_execute_write` | `POS_WRITER_ENABLED` | yes | PG status + 'POS<pk>' vf2 adopt; atomic claim | SoftechSalesOrder payload/readback + AuditLog | POST pos-orders push / flush |
| `purchasing/coverage_writer.py::_apply_coverage_updates` | `COVERAGE_WRITER_ENABLED` | yes | only differing rows; topup_due | CoverageTopUp / AuditLog | command + job coverage_topup |
| `purchasing/coverage_writer.py::_apply_reset` | `COVERAGE_WRITER_ENABLED` | yes | only our non-zero rows | AuditLog softech_coverage_reset | command only |
| `purchasing/isr_writer.py::approve_isr` | `ISR_WRITER_ENABLED` | NO — D5 | fixed target israpp=1 (*re-stamps user/time*) | AuditLog softech_isr_approved | command only (`push_isr --approve`) |
| `purchasing/rate_writer.py::_apply_rate_updates` | `SALES_RATE_WRITER_ENABLED` | yes | only differing rows; push APPROVED → EXECUTED | SalesRatePush/Line + AuditLog | POST rates pushes execute |
| `purchasing/shortage_writer.py::_write_softech` | `SHORTAGE_SOFTECH_WRITE_ENABLED` | NO — D5 | absolute desired state; synced flag in PG | AuditLog softech_shortage_written | POST shortage flag/unflag/dismiss/retrieve; command sync_shortage_softech |
| `sync/management/commands/probe_ap_writeback.py::Command._rehearse` | `SOFTECH_PROBES_ENABLED` | yes (always rolled back) | one transaction, always rolled back | stdout + investigation doc | command only (**D1**) |
| `sync/management/commands/test_replication_cycle.py::Command.handle` | `SOFTECH_PROBES_ENABLED` | n/a (probe) | `--mode restore` puts HQ back | stdout + state JSON | command only (**D1**) |

There are 37 real write sites: 36 at the start of R1, plus the motalba revert the owner asked for.
*Italics* mark weak guards and audit gaps.

**Done in R1 (owner decisions of 2026-11-05):**

- **Q2:** both idempotency guards.
- **Q1 and its follow-up:** the old motalba dates are kept, and a revert restores them.
- **D1:** probes now refuse on a reader copy that has read-only off.
- **D2:** `--actor` is required on the live A/P commands.
- **D3:** failed half-reversals are audited.
- **D4:** every forced repair is audited.
- **D5:** the 13 exceptions below are accepted. **D1–D5, Q1, Q2** refer to
[decision_pack.md](decision_pack.md).

## D5: write sites with no dry-run default (13)

The decision pack's D5 default is to **accept** these where the call is already the explicit
confirmation step, and to **fix** any that write without a person deciding. This default is pending
the owner's confirmation.

| Site | Why there's no dry run | Default verdict |
|---|---|---|
| `alignment.apply_classification_changes` | An admin applies a reviewed alignment plan. | Accept. It also gets the Q2 guard. |
| `alignment.create_new_tier` | An admin creates one tier. | Accept. The MAX+1 race is a weak guard (follow-up 5). |
| `replication.force_replication` | An admin repair action, **and** the `pricing_replication_audit` / `_full_audit` jobs when their policy is `auto_repair`. | Accept for the admin action. **The job path writes with no person deciding**, so the Q2 guard must land before go-live if `auto_repair` is on. |
| `services.execute_price_change` | An admin approves a pending price-change request; the request is the preview. | Accept. "No row lock" is a weak guard (follow-up 5). |
| `recon_writer._reverse_steps` | An admin reverses one A/P allocation. | Accept. |
| `recon_writer.complete_half_reversal` / `complete_half_write` | Recovery tools with no production caller (shell only). | Accept. Failure audit is D3. |
| `reprice_service._revert_locked` | Reverts one applied re-price run. | Accept. |
| `pic_bridge.adjust_softech_points` | Staff adjust one customer's points. | Accept. |
| `personal.writeback._write_and_verify` | Staff save one ERP comment or note. | Accept. |
| `pos_orders.writer._delete_pending_from_softech` | Cancels one pending POS order. | Accept. This is the checkout area, so no change. |
| `isr_writer.approve_isr` | `push_isr --approve`, an explicit flag. | Accept. "Re-stamps user/time" is a weak guard (follow-up 5). |
| `shortage_writer._write_softech` | Staff flag, unflag, dismiss or retrieve one item, and the manual `sync_shortage_softech` command (not scheduled). | Accept. |

## Follow-ups

The owner sees each one as a diff before it merges.

1. **Q2 guards (approved).**
   - `apply_classification_changes`: lock 7_301_011, and skip any item that is already unchanged.
   - `force_replication`: lock 7_301_012, and refuse a repeat within 10 minutes.
2. **Q1 (approved):** keep the old motalba date in `SoftechDateEditRun`.
3. **Manifest correction:** set `_set_motalba_docdate`'s idempotency field to its real guard. Done
   in this table; the manifest file changes with the guards PR.
4. **D1–D4:** shown as diffs.
5. **Weak guards** in `create_new_tier`, `execute_price_change`, `approve_isr` and the rate push:
   proposals only, after go-live unless the owner asks sooner.
6. **Checked 2026-11-05.**
   - `sync_shortage_softech` is **not** scheduled. It runs only from the command and the staff
     action views.
   - `ReplicationPolicy.auto_repair_enabled` defaults to **False**. It can be turned on from the
     pricing screen, so **before go-live the owner checks its live value**. While it is off,
     `force_replication` writes only from the admin action.
