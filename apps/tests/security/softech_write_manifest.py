"""
apps/tests/security/softech_write_manifest.py

Every place in the code that holds an INSERT / UPDATE / DELETE aimed at SOFTECH
(HQ or a branch server), keyed "path::Qualname". test_static_guards fails when a
new write site appears without an entry here, or an entry outlives its code —
so adding a SOFTECH write is always a visible, reviewed change.

Fields (fill from the code, never guess — unknown → None + "# unknown — Batch 2"):
  tables          SOFTECH tables written
  flag            settings switch that must be on for the write to run (None = no switch)
  dry_run_default True when the default call path does not write
  idempotency     what stops a retry writing twice (None = nothing)
  audit           where who/what/when is recorded (None = nowhere)
  trigger         how it runs: HTTP endpoint + permission, scheduler job, or command
  owner_batch     the security batch that reviews it (2 = SOFTECH safety)

Verified 2026-10-26 (Batch 2, P-10) against the code, call chain included: `flag` is the switch
that gates EVERY path to the write (in the function or its callers); kind says whether the site
is a real write, a rehearsal (rolled back), a write-then-restore, an SQL builder, or not a write
at all (SQL held as text). idempotency=None / audit=None mean "nothing" — known gaps.

Callers that delegate to a registered site (pos_cancel_writer → pos_orders.writer._exec_insert,
coupon_push → invoices.writer, replacement.legs → POS/invoice writers) are not SQL sites and
are reviewed with the site they call.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class WriteSite:
    tables: tuple
    flag: object            # str | None
    dry_run_default: object  # bool | None
    idempotency: object     # str | None
    audit: object           # str | None
    trigger: str
    kind: str = 'write'      # write | rehearsal | write-then-restore | sql-builder | not-a-write
    owner_batch: int = 2


WRITE_SITES = {
    # ── customers (B7) ── all CLI-only, admin/supervisor --user, AuditLog ─────────
    'apps/customers/branch_copy.py::copy_one': WriteSite(
        tables=('localcustomers',), flag='CUSTOMER_BRANCH_COPY_WRITE_ENABLED', dry_run_default=True,
        idempotency='no_change skip; optimistic WHERE on the 5 flags (conflict); read-back; no lock',
        audit='BranchCopyWrite + AuditLog customer_branch_copy_written',
        trigger='cmd push_customer_branch_copy --commit'),
    'apps/customers/merge_write.py::merge_one': WriteSite(
        tables=('localcustomers', 'picpoints'), flag='CUSTOMER_MERGE_WRITE_ENABLED', dry_run_default=True,
        idempotency="vf1 tag 'B7 merge <id>' read back before write; optimistic UPDATE; pg_lock 7301005",
        audit='CustomerMergeWrite + AuditLog customer_updated',
        trigger='cmd merge_customer_codes --commit'),
    'apps/customers/points_removal.py::remove_one': WriteSite(
        tables=('localcustomers', 'picpoints'), flag='POINTS_REMOVAL_WRITE_ENABLED', dry_run_default=True,
        idempotency='done-skip; WHERE guard; balance re-read; live run under pg lock 7301009 (P-15)',
        audit='PointsRemoval + AuditLog customer_points_removed',
        trigger='cmd remove_from_points --commit'),
    # ── pricing (discount_approvals) ────────────────────────────────────────────
    'apps/discount_approvals/alignment.py::apply_classification_changes': WriteSite(
        tables=('items',), flag='PRICING_SOFTECH_WRITE_ENABLED', dry_run_default=False,
        idempotency=None, audit='AuditLog softech_item_class_written (who, before → after) — P-16',
        trigger='POST /api/pricing-approvals/alignment/apply/ (admin in view)'),
    'apps/discount_approvals/alignment.py::create_new_tier': WriteSite(
        tables=('itemsorigin', 'custdiscpclassif'), flag='PRICING_SOFTECH_WRITE_ENABLED', dry_run_default=False,
        idempotency='code-exists check (MAX+1 race)', audit='AuditLog softech_tier_created (who, before → after) — P-16',
        trigger='POST /api/pricing-approvals/alignment/tier-create/ (admin in view)'),
    'apps/discount_approvals/replication.py::force_replication': WriteSite(
        tables=('items',), flag='REPLICATION_REPAIR_ENABLED', dry_run_default=False,
        idempotency=None, audit='ReplicationGap.repaired_by (repair_gaps view only); else logger',
        trigger='POST pricing-approvals <pk>/force-replication/ + replication/repair/ (IsAdminRole); '
                'jobs pricing_replication_audit / _full_audit (policy auto_repair); cmd audit_replication --repair'),
    'apps/discount_approvals/services.py::execute_price_change': WriteSite(
        tables=('items',), flag='PRICING_SOFTECH_WRITE_ENABLED', dry_run_default=False,
        idempotency='request status pending/failed only (no row lock)',
        audit='ItemPriceChangeRequest (reviewed_by, old/new/executed values)',
        trigger='POST /api/pricing-approvals/<pk>/approve/ (IsAdminRole)'),
    # ── finance A/P writer (doc 26 سداد) ──────────────────────────────────────────
    'apps/finance/recon_writer.py::_chequestrans_insert_sql': WriteSite(
        tables=('chequestrans',), flag='AP_RECONCILE_WRITER_ENABLED', dry_run_default=True,
        idempotency='see _live_write._write_steps', audit='ReconAuditEvent',
        trigger='SQL builder — executed by _live_write._write_steps', kind='sql-builder'),
    'apps/finance/recon_writer.py::_live_write._write_steps': WriteSite(
        tables=('chequestrans', 'stktransm'), flag='AP_RECONCILE_WRITER_ENABLED', dry_run_default=True,
        idempotency='existing chequestrans row guard (→ skip/top-up); allocation must be APPROVED; atomic',
        audit='ReconAuditEvent (performed_by None from commands)',
        trigger='POST allocations/<pk>/write-softech/ + bulk-write-softech/ (admin); '
                'cmds push_ap_allocation / push_ap_allocations_bulk --commit'),
    'apps/finance/recon_writer.py::_reverse_steps': WriteSite(
        tables=('chequestrans', 'stktransm'), flag='AP_RECONCILE_WRITER_ENABLED', dry_run_default=False,
        idempotency='origin WRITTEN + our audit event + row present & amount match; atomic',
        audit='ReconAuditEvent allocation_reversed / _failed',
        trigger='POST allocations/<pk>/reverse-softech/ + selection-action reverse (admin)'),
    'apps/finance/recon_writer.py::_top_up._work': WriteSite(
        tables=('chequestrans', 'stktransm'), flag='AP_RECONCILE_WRITER_ENABLED', dry_run_default=True,
        idempotency='only when existing row < allocation; our audit event required', audit='ReconAuditEvent',
        trigger='via push_allocation'),
    'apps/finance/recon_writer.py::build_plan': WriteSite(
        tables=(), flag=None, dry_run_default=True, idempotency=None, audit=None,
        trigger='returns plan text only; its patientdata UPDATE is never executed', kind='not-a-write'),
    'apps/finance/recon_writer.py::complete_half_reversal': WriteSite(
        tables=('stktransm',), flag='AP_RECONCILE_WRITER_ENABLED', dry_run_default=False,
        idempotency='acts only on proven half-landed state',
        audit='ReconAuditEvent on success only (failure not audited)',
        trigger='no production caller (shell / tests)'),
    'apps/finance/recon_writer.py::complete_half_write': WriteSite(
        tables=('stktransm',), flag='AP_RECONCILE_WRITER_ENABLED', dry_run_default=False,
        idempotency='failed attempt + no allocation_written + links−header proof', audit='ReconAuditEvent',
        trigger='no production caller (shell / tests)'),
    'apps/finance/recon_writer.py::fix_due_before._work': WriteSite(
        tables=('chequestrans',), flag='AP_RECONCILE_WRITER_ENABLED', dry_run_default=True,
        idempotency='reads SOFTECH; writes only differing rows; atomic', audit='ReconAuditEvent allocation_due_fixed',
        trigger='rechain_after_write (after write views / bulk cmd); cmd fix_ap_due_before --commit'),
    # ── insurance ───────────────────────────────────────────────────────────────
    'apps/insurance/date_service.py::_set_docdate': WriteSite(
        tables=('stktransm', 'stktrans'), flag='INSURANCE_SOFTECH_WRITE_ENABLED', dry_run_default=True,
        idempotency='refused while an applied edit is open on the receipt; date-edit lock 7301008 (P-15)',
        audit='SoftechDateEditRun + InsuranceAuditEvent',
        trigger='POST insurance claims <pk>/softech-date/apply|runs/<id>/revert/ (insurance edit)'),
    'apps/insurance/date_service.py::_set_motalba_docdate': WriteSite(
        tables=('motalba',), flag='INSURANCE_SOFTECH_WRITE_ENABLED', dry_run_default=True,
        idempotency=None, audit='SoftechDateEditRun + InsuranceAuditEvent (motalba before-value not kept)',
        trigger='POST insurance claims <pk>/softech-date/apply/'),
    'apps/insurance/management/commands/backfill_bonusqty.py::Command.handle': WriteSite(
        tables=('stktrans',), flag='INSURANCE_SOFTECH_WRITE_ENABLED', dry_run_default=True,
        idempotency='writes only drifted lines', audit='SoftechRepriceRun/Edit (no user)',
        trigger='cmd backfill_bonusqty --apply'),
    'apps/insurance/reprice_service.py::_write_receipt': WriteSite(
        tables=('stktrans', 'stktransm', 'branchesales'), flag='INSURANCE_SOFTECH_WRITE_ENABLED',
        dry_run_default=True, idempotency='see apply_reprice', audit='SoftechRepriceEdit before/after',
        trigger='via apply_reprice'),
    'apps/insurance/reprice_service.py::apply_reprice': WriteSite(
        tables=('motalba', 'stktrans', 'stktransm', 'branchesales'), flag='INSURANCE_SOFTECH_WRITE_ENABLED',
        dry_run_default=True, idempotency='recomputed from live data (retry is a no-op in SOFTECH, new run row)',
        audit='SoftechRepriceRun/Edit + InsuranceAuditEvent',
        trigger='POST insurance claims <pk>/softech-reprice/apply|apply-batch/ (insurance edit)'),
    'apps/insurance/reprice_service.py::_rebalance_locked': WriteSite(
        tables=('stktransm',), flag='INSURANCE_SOFTECH_WRITE_ENABLED', dry_run_default=True,
        idempotency='run lock 7301007 + run re-read; PG record before SOFTECH commit (P-15)',
        audit='SoftechRepriceEdit + InsuranceAuditEvent',
        trigger='POST insurance claims <pk>/softech-reprice/runs/<id>/rebalance/'),
    'apps/insurance/reprice_service.py::_revert_locked': WriteSite(
        tables=('stktrans', 'stktransm', 'branchesales', 'motalba'), flag='INSURANCE_SOFTECH_WRITE_ENABLED',
        dry_run_default=False, idempotency='status APPLIED → REVERTED under the run lock, re-read (P-15)',
        audit='run status + InsuranceAuditEvent', trigger='POST insurance claims <pk>/softech-reprice/runs/<id>/revert/'),
    # ── invoices ────────────────────────────────────────────────────────────────
    'apps/invoices/management/commands/diag_chained.py::Command.handle.sql_row': WriteSite(
        tables=('stktransm', 'stktrans'), flag='SOFTECH_PROBES_ENABLED', dry_run_default=None,
        idempotency=None, audit='stdout', trigger='cmd diag_chained', kind='rehearsal'),
    'apps/invoices/management/commands/diag_purchase3.py::Command.handle': WriteSite(
        tables=('stktransm', 'stktrans'), flag='SOFTECH_PROBES_ENABLED', dry_run_default=None,
        idempotency=None, audit='stdout', trigger='cmd diag_purchase3', kind='rehearsal'),
    'apps/invoices/management/commands/diag_purchase_insert.py::Command.handle': WriteSite(
        tables=('stktransm', 'stktrans'), flag='SOFTECH_PROBES_ENABLED', dry_run_default=None,
        idempotency=None, audit='stdout', trigger='cmd diag_purchase_insert', kind='rehearsal'),
    'apps/invoices/management/commands/diag_purchase_verbatim.py::Command._insert': WriteSite(
        tables=('stktransm', 'stktrans'), flag='SOFTECH_PROBES_ENABLED', dry_run_default=None,
        idempotency=None, audit='stdout', trigger='cmd diag_purchase_verbatim', kind='rehearsal'),
    'apps/invoices/supplier_items.py::inject_mapping': WriteSite(
        tables=('itemssuppliers',), flag='INVOICE_SUPPLIER_ITEM_WRITE_ENABLED', dry_run_default=True,
        idempotency='noop when already set; guarded UPDATE; verified in-batch',
        audit='AuditLog softech_supplier_mapping_written (who, before → after) — P-16 (cmd seed_supplier_items: no actor)',
        trigger='POST invoices <pk>/lines/<lid>/learn/ (invoices edit, main vendors); cmd seed_supplier_items '
                '(dry run = rehearsal → SOFTECH_PROBES_ENABLED)'),
    'apps/invoices/writer.py::_exec_insert': WriteSite(
        tables=('stktransm', 'stktrans'), flag='SOFTECH_PROBES_ENABLED', dry_run_default=None,
        idempotency=None, audit='stdout', trigger='diag_blocked_purchase / diag_newqty / diag_purchase3',
        kind='rehearsal'),
    'apps/invoices/writer.py::_insert_sql': WriteSite(
        tables=('stktransm', 'stktrans'), flag='INVOICE_WRITER_ENABLED', dry_run_default=True,
        idempotency='see _run_write_batch', audit='see _run_write_batch',
        trigger='SQL builder — executed by _run_write_batch', kind='sql-builder'),
    'apps/invoices/writer.py::_run_write_batch': WriteSite(
        tables=('stktransm', 'stktrans', 'lastdocnumbers'), flag='INVOICE_WRITER_ENABLED', dry_run_default=True,
        idempotency='PG status/softech_docnumber; purchases: SOFTECH docnumber2 duplicate guard; returns: PG only; '
                    'vf2 token defined but never written',
        audit='SupplierInvoice erp_payload/readback + AuditLog softech_invoice_pushed (who) — P-16 (views)',
        trigger='POST invoices <pk>/push|push-batch/ (finalize + admin/purchasing/supervisor); probe → '
                'SOFTECH_PROBES_ENABLED; coupons push/probe; cmd push_coupon_batch; cmd clone_purchase; replacement legs'),
    # ── loyalty ─────────────────────────────────────────────────────────────────
    'apps/loyalty/pic_bridge.py::adjust_softech_points': WriteSite(
        tables=('picpoints',), flag='LOYALTY_SOFTECH_WRITE_ENABLED', dry_run_default=False,
        idempotency='view: select_for_update + 120 s duplicate window (P-4); function itself additive',
        audit='SoftechPointsLog (view); vf1/vf2 in SOFTECH',
        trigger='POST /api/loyalty/customers/<id>/adjust/ (LOYALTY_ADJUST_ROLES); cmd test_pic_points '
                '(also SOFTECH_PROBES_ENABLED)'),
    # ── offers ──────────────────────────────────────────────────────────────────
    'apps/offers/channel_a.py::_write_posdiscp': WriteSite(
        tables=('items',), flag='POS_OFFERS_POSDISCP_WRITE_ENABLED', dry_run_default=True,
        idempotency='only items whose mirror differs', audit='AuditLog softech_posdiscp_written (who, before → after) — P-16',
        trigger='POST /api/offers/<pk>/posdiscp-apply/ (admin)'),
    'apps/offers/channel_b.py::_insert_specialoffer': WriteSite(
        tables=('specialoffers', 'specialoffersitems'), flag='POS_OFFERS_PROMO_WRITE_ENABLED', dry_run_default=True,
        idempotency='identical live offer reused; one transaction; pg lock 7301010 (P-15)',
        audit='AuditLog softech_promo_written (who, before → after) — P-16', trigger='POST /api/offers/<pk>/promo-apply/ (admin)'),
    # ── personal dashboard ──────────────────────────────────────────────────────
    'apps/personal/writeback.py::_write_and_verify': WriteSite(
        tables=('stktransm', 'cheques'), flag='PERSONAL_COMMENT_WRITE_ENABLED', dry_run_default=False,
        idempotency='absolute SET; ownership re-read', audit='DocumentCommentEdit / DocumentRevision',
        trigger='POST /api/personal/documents/comment/ | cheques/note/ | revision/ (can_edit_erp_comments)'),
    # ── POS (indirect) ──────────────────────────────────────────────────────────
    'apps/pos_orders/writer.py::_build_sql': WriteSite(
        tables=(), flag=None, dry_run_default=True, idempotency=None, audit=None,
        trigger='documentation strings for the plan; never executed', kind='not-a-write'),
    'apps/pos_orders/writer.py::_delete_pending_from_softech': WriteSite(
        tables=('branchesalescc5', 'companiesitems5', 'branchesales5', 'stktrans5', 'stktransm5'),
        flag='POS_WRITER_ENABLED', dry_run_default=False,
        idempotency='cancelled order returns early; header must exist',
        audit='order status + AuditLog softech_pos_order_cancelled (who) — P-16',
        trigger='POST /api/pos-orders/<pk>/cancel/ (CanPushPosOrders)'),
    'apps/pos_orders/writer.py::_exec_insert': WriteSite(
        tables=('stktransm5', 'stktrans5', 'branchesales5', 'companiesitems5', 'branchesalescc5', 'pos_cancel'),
        flag='POS_WRITER_ENABLED', dry_run_default=True,
        idempotency='per caller (push_order vf2 tag + status; pos_cancel claim-before-write)',
        audit='per caller', trigger='push_order / probe_order / reservation / write_pos_cancel_batch'),
    'apps/pos_orders/writer.py::_execute_write': WriteSite(
        tables=('stktransm5', 'stktrans5', 'branchesales5', 'companiesitems5', 'branchesalescc5'),
        flag='POS_WRITER_ENABLED', dry_run_default=True,
        idempotency="PG status + 'POS<pk>' vf2 adopt; atomic claim, one flush job (P-11)",
        audit='SoftechSalesOrder erp_payload/readback + AuditLog softech_pos_order_pushed (who) — P-16 (views)',
        trigger='POST pos-orders <pk>/push/ + flush/ (CanPushPosOrders); jobs pos_orders_flush + pos_flush_queued; '
                'cmds flush_pos_orders / pos_probe --commit / pos_writer_live_test; replacement legs'),
    'apps/pos_orders/writer.py::probe_cancel': WriteSite(
        tables=('stktransm5', 'stktrans5', 'branchesales5', 'companiesitems5', 'branchesalescc5'),
        flag='SOFTECH_PROBES_ENABLED', dry_run_default=None, idempotency=None, audit='logger',
        trigger='cmd pos_probe --cancel-probe', kind='rehearsal'),
    # ── purchasing writers ──────────────────────────────────────────────────────
    'apps/purchasing/coverage_writer.py::_apply_coverage_updates': WriteSite(
        tables=('stkbal',), flag='COVERAGE_WRITER_ENABLED', dry_run_default=True,
        idempotency='only differing rows; topup_due',
        audit='CoverageTopUp (top-up) / AuditLog softech_coverage_written (push_coverage) — P-16',
        trigger='cmds push_coverage / topup_coverage --commit; job coverage_topup (+COVERAGE_AUTO_TOPUP_ENABLED)'),
    'apps/purchasing/coverage_writer.py::_apply_reset': WriteSite(
        tables=('stkbal',), flag='COVERAGE_WRITER_ENABLED', dry_run_default=True,
        idempotency='only our non-zero rows', audit='AuditLog softech_coverage_reset — P-16',
        trigger='cmd push_coverage --reset-non-stock --commit'),
    'apps/purchasing/coverage_writer.py::probe_coverage_write._set': WriteSite(
        tables=('stkbal',), flag='SOFTECH_PROBES_ENABLED', dry_run_default=None,
        idempotency='restore in finally (P-13)', audit='logger',
        trigger='cmd push_coverage --probe-branch/--probe-item', kind='rehearsal'),
    'apps/purchasing/isr_writer.py::_insert_sql': WriteSite(
        tables=('stockisrm', 'stockisr'), flag='ISR_WRITER_ENABLED', dry_run_default=True,
        idempotency='push_isr_record: per-draft lock + status re-read + isr_guards duplicate check; '
                    'push_isr --commit retired (P-15)',
        audit='IsrPush + AuditLog softech_isr_pushed (who) — P-16 (+ forced duplicate)',
        trigger='POST purchasing isr/pushes/<pk>/push/ (can_supply_write); cmd generate_isr --auto-approve; '
                'probe → SOFTECH_PROBES_ENABLED', kind='sql-builder'),
    'apps/purchasing/isr_writer.py::approve_isr': WriteSite(
        tables=('stockisrm',), flag='ISR_WRITER_ENABLED', dry_run_default=False,
        idempotency='fixed target israpp=1 (re-stamps user/time)', audit='AuditLog softech_isr_approved — P-16',
        trigger='cmd push_isr --approve'),
    'apps/purchasing/isr_writer.py::probe_approve_isr': WriteSite(
        tables=('stockisrm',), flag='SOFTECH_PROBES_ENABLED', dry_run_default=None,
        idempotency='restore in finally (P-13)', audit='logger',
        trigger='cmd push_isr --probe-approve', kind='rehearsal'),
    'apps/purchasing/rate_writer.py::_apply_rate_updates': WriteSite(
        tables=('stkbal',), flag='SALES_RATE_WRITER_ENABLED', dry_run_default=True,
        idempotency='only differing rows; push APPROVED → EXECUTED (no lock)',
        audit='SalesRatePush/Line + AuditLog softech_sales_rates_written (who) — P-16',
        trigger='POST purchasing rates/pushes/<pk>/execute/ (can_supply_write); cmd push_sales_rates --commit'),
    'apps/purchasing/rate_writer.py::_refresh_maxqty_sql': WriteSite(
        tables=('stkbal',), flag='SALES_RATE_WRITER_ENABLED', dry_run_default=True,
        idempotency='see callers', audit='see callers',
        trigger='SQL builder — rate + coverage writers (COVERAGE_WRITER_ENABLED there)', kind='sql-builder'),
    'apps/purchasing/rate_writer.py::probe_write': WriteSite(
        tables=('stkbal',), flag='SOFTECH_PROBES_ENABLED', dry_run_default=None,
        idempotency='restore NOT in try/finally', audit='logger',
        trigger='cmd push_sales_rates --probe-branch/--probe-item', kind='rehearsal'),
    'apps/purchasing/shortage_writer.py::_write_softech': WriteSite(
        tables=('items',), flag='SHORTAGE_SOFTECH_WRITE_ENABLED', dry_run_default=False,
        idempotency='absolute desired state; synced flag in PG',
        audit='AuditLog softech_shortage_written (who, before → after) — P-16 (queue flush: no actor)',
        trigger="POST purchasing shortage flag|unflag|dismiss|retrieve/ (shortage/approve, P-2); cmd sync_shortage_softech"),
    # ── sync investigations (all SOFTECH_PROBES_ENABLED, P-7) ───────────────────
    'apps/sync/management/commands/investigate_britems.py::Command._investigate': WriteSite(
        tables=('items',), flag='SOFTECH_PROBES_ENABLED', dry_run_default=False,
        idempotency="restored by RowGuards (all columns incl. usercode, even on a crash) — P-14", audit='stdout',
        trigger='cmd investigate_britems', kind='write-then-restore'),
    'apps/sync/management/commands/investigate_britems2.py::Command._investigate': WriteSite(
        tables=('britems', 'items'), flag='SOFTECH_PROBES_ENABLED', dry_run_default=False,
        idempotency="restored by RowGuards (all columns incl. usercode, even on a crash) — P-14", audit='stdout',
        trigger='cmd investigate_britems2', kind='write-then-restore'),
    'apps/sync/management/commands/investigate_crm_orders.py::Command.handle': WriteSite(
        tables=(), flag=None, dry_run_default=True, idempotency=None, audit=None,
        trigger="cmd investigate_crm_orders — SELECT-only; 'INSERT' is label text", kind='not-a-write'),
    'apps/sync/management/commands/investigate_replication.py::Command._investigate': WriteSite(
        tables=('items',), flag='SOFTECH_PROBES_ENABLED', dry_run_default=False,
        idempotency="restored by RowGuards (all columns incl. usercode, even on a crash) — P-14", audit='stdout',
        trigger='cmd investigate_replication', kind='write-then-restore'),
    'apps/sync/management/commands/probe_ap_writeback.py::Command._rehearse': WriteSite(
        tables=('cheques', 'chequestrans'), flag='SOFTECH_PROBES_ENABLED', dry_run_default=True,
        idempotency='NONE — SoftechConnector begin/rollback are no-ops: the "rehearsal" COMMITS (cheques irreversible)',
        audit='stdout + docs/architecture/softech_ap_writeback_investigation.txt',
        trigger='cmd probe_ap_writeback --rehearse --confirm-rollback-rehearsal', kind='write'),
    'apps/sync/management/commands/probe_itemlastupdate.py::Command._investigate': WriteSite(
        tables=('items',), flag='SOFTECH_PROBES_ENABLED', dry_run_default=False,
        idempotency="restored by RowGuards (all columns incl. usercode, even on a crash) — P-14", audit='stdout',
        trigger='cmd probe_itemlastupdate', kind='write-then-restore'),
    'apps/sync/management/commands/probe_repl_queue.py::Command._investigate': WriteSite(
        tables=('items',), flag='SOFTECH_PROBES_ENABLED', dry_run_default=False,
        idempotency="real sale-price change chain-wide while it runs; restored by RowGuards (all columns incl. usercode, even on a crash) — P-14", audit='stdout',
        trigger='cmd probe_repl_queue', kind='write-then-restore'),
    'apps/sync/management/commands/probe_replication_source.py::Command._investigate': WriteSite(
        tables=('items', 'britems'), flag='SOFTECH_PROBES_ENABLED', dry_run_default=False,
        idempotency="restored by RowGuards (all columns incl. usercode, even on a crash) — P-14; trans_time as a literal", audit='stdout',
        trigger='cmd probe_replication_source', kind='write-then-restore'),
    'apps/sync/management/commands/test_replication_cycle.py::Command.handle': WriteSite(
        tables=('items',), flag='SOFTECH_PROBES_ENABLED', dry_run_default=None,
        idempotency='--mode restore puts HQ back (only while the markers are still there); second plant refused; state saved before the write — P-14',
        audit='stdout + state JSON', trigger='cmd test_replication_cycle --mode plant', kind='write'),
    'apps/sync/management/commands/test_sybase_vps.py::_run_write_test': WriteSite(
        tables=('picpoints',), flag='SOFTECH_PROBES_ENABLED', dry_run_default=True,
        idempotency=None, audit='report file', trigger='cmd test_sybase_vps --write-test', kind='rehearsal'),
}
