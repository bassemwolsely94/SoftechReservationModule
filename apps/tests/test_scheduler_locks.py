"""
Round 2, R6 step 1 — every scheduler job runs under a guard against a duplicate run.

APScheduler's `max_instances=1` only stops overlap inside ONE process. Two scheduler processes have
run at once before (see the duplicate-scheduler note in the ops memory), and jobs are also re-run
by hand, so each job needs a guard that makes a second, concurrent run harmless. This file is the
documented registry: one entry per job id —

    'job_id': (kind, 'dotted.path.of.the.guard', 'source text that proves it', 'reason')

kinds, strongest first: advisory_lock · row_lock (select_for_update / conditional UPDATE claim) ·
unique_key (DB constraint / idempotency key) · idempotent_upsert (a re-run rewrites the same rows) ·
once_per_period_check (an "already done today?" check — check-then-act, racy) · read_only · none.

The tests prove: every registered job is in the registry (a new job must be classified), each proof
text is still in the named code (a guard can't vanish silently), every job is `max_instances=1`,
and a job that sends WhatsApp / SMS or writes SOFTECH without a real lock is listed in
`KNOWN_GAPS` with where it is tracked. A duplicate-scheduler ALERT (beyond the heartbeat) does
not exist yet — it is optional feature work in the round-2 decision pack, not tested here.
Registry built 2026-11-05 by reading each job's code (notes: r6-scheduler-guards.md).
"""
import importlib
import inspect
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from apps.sync import tasks

SCHEDULER_JOB_GUARDS = {
    'payment_exception_checks': ('once_per_period_check', 'apps.payments.audit_service.PaymentAuditService', 'PaymentException.objects.get_or_create(',
        'nightly, switch off by default; get_or_create with no unique constraint (racy) - a duplicate run could add a second exception row; in-app only, no sends, no SOFTECH'),
    # ── SOFTECH sync lanes ────────────────────────────────────────────────────
    'softech_sync_fast': ('idempotent_upsert', 'apps.sync.tasks.sync_stock', 'update_conflicts=True',
        'stock/sales mirror is bulk upsert; _manual_run_in_flight only skips when a MANUAL run is live, not a 2nd scheduled one; post-hooks (reservation stock alerts, notify_stock_available) send web push with the 5-min unread dedup (racy)'),
    'softech_sync_slow': ('idempotent_upsert', 'apps.sync.tasks.sync_items', 'update_conflicts=True',
        'items/customers/users mirror is bulk upsert; master hooks only refresh snapshots/balances'),
    'sales_history_catchup': ('idempotent_upsert', 'apps.sync.tasks.sync_sales', 'update_conflicts=True',
        '7-day PurchaseHistory re-read, same bulk upsert as the fast lane'),
    'network_health_probe': ('none', 'apps.delivery.branch_watchdog.record_run', 'streak    = prev_fails + 1',
        'read-modify-write of the health JSON with no lock: two runs double-count the failure streak and both fire the down/chronic transition (dedup key carries each run\'s own now -> duplicate web push)'),
    'scheduler_heartbeat': ('read_only', 'apps.sync.tasks._write_heartbeat', 'SystemSetting.objects.update_or_create(',
        'heartbeat row + stale-run sweep + failing-lane alert (dedup_once per lane per day)'),
    'insurance_cache_sync': ('idempotent_upsert', 'apps.insurance.sync.sync_motalba', 'update_conflicts=True,',
        'motalba / companiesitems 90-day mirror via bulk upsert'),
    'crm_delivery_sync': ('unique_key', 'apps.delivery.models.DeliveryOrder', "fields=['softech_crm_branch', 'softech_crm_order_no'],",
        'piccrmorders import: existing-key check backed by UniqueConstraint (crm branch, order no) - a racing create fails, no duplicate order'),
    'sync_in_transit_transfers': ('unique_key', 'apps.transits.models.InTransitTransfer', "unique_together = [('erp_doc_number', 'erp_supplying_branch_code')]",
        'doccode 125 mirror keyed (docnumber, supplying branch); overdue alerts are once-per-day checks (last_alert_sent_at / dedup_once), racy, web push'),
    'purchase_expiry_sync': ('unique_key', 'apps.batches.expiry_audit.run_backfill', 'ignore_conflicts=True',
        'already-mirrored batch lines skipped by the unique key'),
    'stock_expiry_sync': ('idempotent_upsert', 'apps.batches.stock_expiry.sync_stock_expiry_all', 'StockExpiryBalance.objects.filter(branch_code=bc).delete()',
        'per-branch delete+insert in one transaction'),
    'stock_ledger_sync': ('idempotent_upsert', 'apps.stock_audit.ledger.sync_ledger', 'StockLedgerLine.objects.filter(docdate__gte=d1, docdate__lt=d2).delete()',
        'day-replace of the HQ stktrans mirror in one transaction; audit checks recompute'),
    'stock_ledger_catchup': ('idempotent_upsert', 'apps.stock_audit.ledger.sync_ledger', 'StockLedgerLine.objects.filter(docdate__gte=d1, docdate__lt=d2).delete()',
        'same function as stock_ledger_sync with a wider window'),
    'item_suppliers_sync': ('idempotent_upsert', 'apps.catalog.supplier_links.sync_from_rows', 'ItemSupplierLink.objects.bulk_update(changed,',
        'diff mirror of itemssuppliers (insert new / update changed / delete gone); unique (item_code, supp_code) stops duplicate pairs'),
    'pos_cancel_sync': ('idempotent_upsert', 'apps.pos_orders.pos_cancel_sync.sync_pos_cancel_all', 'PosCancelDaily.objects.filter(branch_code=bc, day__gte=window_start).delete()',
        '30-day per-branch delete+insert in one transaction'),
    'finance_nightly_sync': ('idempotent_upsert', 'apps.finance.engine.sync_engine.FinanceSyncEngine._upsert_snapshot', 'FinancialSnapshot.objects.update_or_create(',
        'finance mirror is update_or_create throughout; SELECT-only on SOFTECH'),
    'pbx_cdr_relink': ('idempotent_upsert', 'apps.pbx.cdr.relink_all', 'CdrCall.objects.bulk_update(batch,',
        're-derives each call\'s PIC link'),
    'pbx_cdr_sync': ('once_per_period_check', 'apps.pbx.missed_callbacks.alert_overdue_callbacks', 'already = set(PhoneAlert.objects.filter(',
        'CDR upsert on cdr_key and call-back creation (IntegrityError) are safe, but the overdue call-back WhatsApp alert is check-then-act with no lock (racy); backstop = phone-alert dispatch dedup (also racy) + R5 send_limits.claim in sender._deliver (uncommitted)'),
    'coupon_lifecycle_sync': ('advisory_lock', 'apps.vouchers.coupon_dashboard.locked_sync', 'with pg_lock(LOCK_SYNC) as got:',
        'pg_try_advisory_lock; the loser raises CommandError before the digest step'),

    # ── Engines / snapshots (PostgreSQL only) ─────────────────────────────────
    'segment_customers': ('idempotent_upsert', 'apps.customers.management.commands.segment_customers.Command.handle', 'Customer.objects.bulk_update(to_update, update_fields)',
        'recomputes segment fields and bulk_updates them'),
    'sales_forecast': ('idempotent_upsert', 'apps.forecasting.service.ForecastService._forecast_one', 'metrics.save(update_fields=[',
        'recomputes forecast fields on ItemDemandMetrics'),
    'kpi_refresh': ('idempotent_upsert', 'apps.forecasting.rollup_refresh.refresh', 'done = rebuild(months)',
        'rebuilds stale month rollups; _lock is a threading lock (one process only)'),
    'procurement_refresh': ('once_per_period_check', 'apps.procurement.refresh.scheduled_tick', 'if not is_due():',
        'is_due (last success > 20 h) + running_run() + threading _lock: check-then-act across processes (racy) -> a 2nd engine run pulls SOFTECH again; no sends, no SOFTECH write'),
    'seasonality_refresh': ('once_per_period_check', 'apps.purchasing.seasonality.scheduled_tick', "return run_now('scheduler') if is_due() else None",
        'is_due + running_run() + threading _lock: racy across processes; SELECT-only on SOFTECH, no sends'),
    'demand_engine_scheduled': ('once_per_period_check', 'apps.sync.tasks._run_demand_engine_scheduled', "DemandCalculationRun.objects.filter(status='running').exists()",
        'running-run check without a lock (racy) -> two engine runs; engine writes PG only, a human still approves rates'),
    'dead_stock_snapshot': ('unique_key', 'apps.purchasing.models.DeadStockSnapshot', "models.OneToOneField(DemandCalculationRun, on_delete=models.CASCADE, related_name='dead_stock')",
        'one snapshot per engine run (OneToOne); a racing second create fails'),
    'cash_view_weekly_snapshot': ('idempotent_upsert', 'apps.finance.cash_view.snapshot', 'CashViewSnapshot.objects.update_or_create(as_of=as_of',
        'one snapshot per date, re-run replaces it'),
    'pic_facts': ('idempotent_upsert', 'apps.pic_analytics.build._build_chunk', 'PicDayFact.objects.filter(day__gte=start, day__lte=end).delete()',
        'day-range delete+insert in one transaction; rollup rebuilt'),
    'daily_retention': ('advisory_lock', 'apps.sync.maintenance.run_daily_retention', 'pg_lock(RETENTION_LOCK_KEY)',
        'pg_try_advisory_lock; the loser returns None and writes no run row'),
    'retention_watch': ('advisory_lock', 'apps.sync.maintenance.run_daily_retention', 'pg_lock(RETENTION_LOCK_KEY)',
        'catch-up shares the retention lock; morning-chain catch-up shares the chain lock (MORNING_CHAIN_LOCK_KEY); missed-run alert is dedup_once per lane per day'),
    'isr_draft_expiry': ('idempotent_upsert', 'apps.purchasing.isr_guards.expire_drafts', 'P.objects.filter(status=P.STATUS_PROPOSED, created_at__lt=cutoff)',
        'status filter; concurrent runs only duplicate the cancel audit row (PG only, never SOFTECH)'),
    'return_window_reconcile': ('once_per_period_check', 'apps.batches.return_calendar.reconcile_returns', '_line_key(pl) not in used',
        'used-lines set read up front, no lock: two concurrent runs can apply the same doc 120 line twice (returned_qty double-counted); PG only'),
    'gl_drafting': ('unique_key', 'apps.finance.gl.drafting.start_run', 'except IntegrityError:',
        'partial UniqueConstraint on GLDraftRun status=running -> DraftBusy; SELECT-only on SOFTECH'),
    'daily_count_job': ('unique_key', 'apps.stockcount.daily.service.generate', 'except IntegrityError:',
        'StockCountSession create per person/day; a concurrent run hits IntegrityError and skips'),
    'missed_sales': ('unique_key', 'apps.pos_orders.missed_sales.detect_missed_sales', 'bulk_create(created, ignore_conflicts=True)',
        'UniqueConstraint (cart_token, item_code)'),
    'gamification_score': ('unique_key', 'apps.gamification.engine.Scorer.award', 'except IntegrityError:',
        'PointEvent UniqueConstraint (staff, rule_key, source_key); level-up notices are in-app check-then-act (racy)'),
    'gamification_day_close': ('unique_key', 'apps.gamification.engine.Scorer.award', 'except IntegrityError:',
        'same engine as gamification_score with finalize=True'),
    'gamification_champions': ('unique_key', 'apps.gamification.champions.crown', 'ChampionMonth.objects.select_for_update().get_or_create(',
        'ChampionMonth.month unique; the loser gets created=False and returns before announcing'),
    'customer_status_drift': ('advisory_lock', 'apps.customers.status_drift.scan_locked', 'with pg_lock(LOCK_KEY) as got:',
        'scan under pg_try_advisory_lock; loser returns None and skips notify; notify is a per-day exists() check (in-app)'),
    'customer_merge_candidates': ('advisory_lock', 'apps.customers.duplicates.rebuild_locked', 'with pg_lock(LOCK_KEY) as got:',
        'queue rebuild under pg_try_advisory_lock'),
    'whisper_tick': ('row_lock', 'apps.callcenter.whisper.run_queue', "select_for_update(skip_locked=True, of=('self',))",
        'each transcript claimed with skip_locked; the tick also queues recent CDR calls via get_or_create on a unique (cdr_call, engine) constraint; caveat: maybe_launch_runner checks run_is_active without a lock and a 2nd runner resets running->pending, so one call can be transcribed twice (CPU only)'),

    # ── SOFTECH writers ───────────────────────────────────────────────────────
    'pos_orders_flush': ('row_lock', 'apps.pos_orders.writer.push_order', ').update(status=SoftechSalesOrder.STATUS_PUSHING, updated_at=timezone.now())',
        'conditional UPDATE claim to PUSHING before any SOFTECH write (P-11); WRITES SOFTECH'),
    'pos_orders_reconcile': ('idempotent_upsert', 'apps.pos_orders.reconcile.reconcile_order', 'order.status = SoftechSalesOrder.STATUS_SETTLED',
        'reads branch DBs, flips pushed->settled from the same facts; never writes SOFTECH'),
    'pos_cancel_write': ('row_lock', 'apps.pos_orders.pos_cancel_writer.write_pos_cancel_batch', 'softech_written_at__isnull=True',
        'claims only still-unclaimed events under a per-run token and inserts only what it won; a second scheduler process claims and inserts nothing (S-3 fix, owner OK 2026-11-05); WRITES SOFTECH'),
    'coverage_topup': ('once_per_period_check', 'apps.purchasing.coverage_writer.topup_due', "qs.filter(status='success').exists()",
        'checks a successful CoverageTopUp for the run, then writes, no lock (racy); the write is an absolute SET of stkbal.maxnowqtymonths/maxnowqty so a duplicate lands the same values, but doubles branch writes and audit rows; WRITES SOFTECH'),
    'pricing_replication_audit': ('advisory_lock', 'apps.discount_approvals.replication.force_replication', 'with pg_lock(LOCK_REPLICATION) as got:',
        'the SOFTECH re-stamp (force_replication) runs under advisory lock LOCK_REPLICATION with a repeat window (round 2 R1); the read-only scan itself is unlocked, so a duplicate run makes a 2nd scan and a 2nd admin push (dedup key = scan id)'),
    'pricing_replication_full_audit': ('advisory_lock', 'apps.discount_approvals.replication.force_replication', 'with pg_lock(LOCK_REPLICATION) as got:',
        'weekly full-catalog variant of pricing_replication_audit, same lock'),

    # ── Customer / staff WhatsApp & SMS senders ───────────────────────────────
    'wa_campaign_drain': ('row_lock', 'apps.campaigns.dispatcher.drain_queue', "filter(pk=item.pk, status='pending').update(status='processing')",
        'each queued CUSTOMER WhatsApp is claimed with a conditional UPDATE before it is sent, so a second drain skips it (round 2 R6 fix; before, a plain save let two drains send it twice)'),
    'refill_reminders': ('advisory_lock', 'apps.followups.refill_reminders.run', 'with pg_lock(_LOCK_KEY) as got:',
        'pg_try_advisory_lock around the send loop + per-task select_for_update / IntegrityError claim on RefillReminder in _send_one; customer WhatsApp'),
    'phone_alerts_tick': ('row_lock', 'apps.notifications.phone_alerts.jobs._process', 'select_for_update(skip_locked=True)',
        'each alert decided under a skip_locked row lock; reminder + first send claimed before delivery; staff WhatsApp/SMS'),
    'morning_brief': ('once_per_period_check', 'apps.insights.brief.send_all', 'created_at__gte=start, created_at__lt=end',
        'skips phones that already got today\'s brief, then creates+sends with no lock (racy); backstop = R5 send_limits.claim in phone_alerts.sender._deliver (uncommitted); staff WhatsApp/SMS'),
    'expiry_worklists': ('once_per_period_check', 'apps.batches.expiry_audit._maybe_whatsapp_worklist', "PhoneAlert.objects.filter(event='expiry_worklist', created_at__gte=week_start)",
        'WhatsApp heads-up is a once-per-ISO-week check without a lock (racy; R5 claim backstop, uncommitted); the in-app worklist in _notify_branch_worklist has NO dedup check (Notification.objects.create every run)'),
    'morning_chain': ('row_lock', 'apps.insights.management.commands.generate_insights.Command._send', "claim(f'insights:{run.domain}:{run.period_type}', rc.wa_number)",
        'chain = AP mirror (update_or_create) + daily insights WhatsApp + supply sweep (select_for_update per case, dedup_once push) + replacement check (get_or_create); the WhatsApp step is guarded ONLY by the uncommitted R5 10-min claim - on main it has no guard'),
    'insights_weekly': ('row_lock', 'apps.insights.management.commands.generate_insights.Command._send', "claim(f'insights:{run.domain}:{run.period_type}', rc.wa_number)",
        'R5 send_limits.claim (atomic UPDATE / unique INSERT) per number per 10 min - uncommitted; InsightRun itself is delete+create; no sent_at check, so a re-run after 10 min re-sends; staff WhatsApp'),
    'insights_monthly': ('row_lock', 'apps.insights.management.commands.generate_insights.Command._send', "claim(f'insights:{run.domain}:{run.period_type}', rc.wa_number)",
        'same as insights_weekly'),

    # ── In-app / web-push notification jobs ───────────────────────────────────
    'followup_reminders': ('once_per_period_check', 'apps.sync.tasks._send_followup_reminders', 'reminder_sent=False,',
        'reads reminder_sent=False, sends, then flags - no lock (racy); dedup_key uses the 5-min unread window; web push'),
    'auto_expire_reservations': ('once_per_period_check', 'apps.sync.tasks._auto_expire_reservations', "status__in=['pending', 'available', 'contacted'],",
        'status filter read then unconditional update by pk: concurrent runs duplicate ReservationStatusLog/Activity rows and the call-center summary (5-min dedup); web push'),
    'demand_recovery_escalation': ('once_per_period_check', 'apps.demand.service.escalate_stale_recoveries', 'Notification.objects.filter(dedup_key=dedup, created_at__gte=cutoff).exists()',
        'prior-escalation exists() check then create, no lock (racy); in-app only + DemandLog'),
    'demand_sla_escalation': ('once_per_period_check', 'apps.demand.service.escalate_breached_demand_sla', 'Notification.objects.filter(dedup_key=dedup, created_at__gte=repeat_cutoff).exists()',
        'repeat-window exists() check then send, no lock (racy); web push'),
    'reminders_and_snoozes': ('once_per_period_check', 'apps.notifications.models.PersonalReminder.fire', 'if self.is_fired:',
        'in-memory is_fired check, no lock (racy); un-snooze re-pushes every due row; web push + websocket'),
    'delivery_sla_alerts': ('once_per_period_check', 'apps.sync.tasks._delivery_sla_alerts', 'dedup_once=True,',
        'per-order per-hour dedup_once key, check-then-create (racy); web push'),
    'delivery_csat_sender': ('idempotent_upsert', 'apps.sync.tasks._delivery_csat_sender', 'DeliveryCSAT.objects.update_or_create(',
        'only marks wa_sent and logs a wa.me link - sends nothing itself'),
    'transfer_sla_check': ('once_per_period_check', 'apps.transfers.management.commands.check_transfer_sla.Command.handle', "dedup = f'sla_breach_{tr.id}_",
        'per-hour key with the 5-min unread window (not dedup_once), racy; web push'),
    'escalate_overdue_approvals': ('once_per_period_check', 'apps.approvals.service.ApprovalService.escalate_overdue_steps', 'last_escalation = req.escalations.filter(step_order=step.order)',
        'last-escalation time check then act, no lock (racy): duplicate escalation logs/notices, and an optional step can get two auto-approve decisions; in-app only'),
    'escalate_breached_cases': ('row_lock', 'apps.callcenter.sla.escalate_breached_cases', 'pk=case.pk, status__in=ESCALATABLE_STATUSES,',
        'conditional UPDATE to escalated; only the winner logs and notifies (dedup_once)'),
    'inflation_reminder': ('once_per_period_check', 'apps.sync.tasks._run_inflation_reminder', "dedup_key=f'inflation_reminder_{date.today():%Y-%m}'",
        'send_to_admins has no dedup_once: the monthly key only suppresses an UNREAD copy younger than 5 min (racy, not really once a month); web push'),
    'return_window_digest': ('once_per_period_check', 'apps.batches.return_calendar.monthly_digest', 'dedup_once=True',
        'snapshot get_or_create (unique) + per-month dedup_once digest, check-then-create (racy); web push'),
    'receipt_check_daily': ('once_per_period_check', 'apps.procurement.receipt_check.send_digest', "dedup_key=f'receipt_check_{today.isoformat()}', dedup_once=True",
        'run_check is an in-transaction upsert; digest is per-day dedup_once, check-then-create (racy); web push'),
    'markdown_revert_reminders': ('none', 'apps.batches.expiry_audit.remind_markdown_reversals', 'Notification.objects.create(',
        'creates the weekly reminder with a dedup_key but never checks it: every run (or duplicate run) adds another copy; in-app only'),
    'help_training_digest': ('once_per_period_check', 'apps.help.digest.send_weekly', "dedup_key=f'help_training_digest_{sup.pk}_{year}w{week}', dedup_once=True",
        'per-ISO-week dedup_once, check-then-create (racy); web push'),
    'help_announce_training': ('once_per_period_check', 'apps.help.training.announce_changes', 'if old is not None and cur != old:',
        'snapshot compare then notify then update_or_create snapshot, no lock (racy); 5-min unread dedup; web push'),
}

KINDS = {'advisory_lock', 'row_lock', 'unique_key', 'idempotent_upsert', 'once_per_period_check',
         'read_only', 'none'}

# Jobs whose duplicate run could double a WhatsApp / SMS or a SOFTECH write, with no lock today.
# Each says where it is tracked. Remove a line when its job gains a lock.
KNOWN_GAPS = {
    'morning_brief': 'racy once-a-day check; backstopped by send_limits.claim (10 min, R5)',
    'expiry_worklists': 'racy once-a-week check; backstopped by send_limits.claim (R5)',
    'pbx_cdr_sync': 'overdue call-back alerts: racy check; backstopped by send_limits.claim (R5)',
    'insights_weekly': 'insights texts: backstopped by send_limits.claim (R5); sent_at not re-checked',
    'insights_monthly': 'insights texts: backstopped by send_limits.claim (R5); sent_at not re-checked',
    'morning_chain': 'daily insights texts: backstopped by send_limits.claim (R5)',
    'coverage_topup': 'racy check before an absolute SET on stkbal — a duplicate writes the same values',
}
SENDS_OR_WRITES_SOFTECH = set(KNOWN_GAPS) | {'wa_campaign_drain', 'phone_alerts_tick',
                                              'pos_orders_flush', 'pos_orders_reconcile'}


class _FakeScheduler:
    def __init__(self, *a, **kw):
        self.jobs = []
        self.running = False

    def add_job(self, func, trigger, *args, **kwargs):
        self.jobs.append((kwargs.get('id'), kwargs))

    def add_listener(self, *a, **kw):
        pass

    def start(self):
        self.running = True

    def shutdown(self, *a, **kw):
        self.running = False


def _registered():
    with mock.patch.object(tasks, 'BackgroundScheduler', _FakeScheduler), \
            mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
            mock.patch.object(tasks, '_scheduler', None), \
            mock.patch('config.writers.writer_instance', return_value=True):   # writer jobs too
        tasks.start_scheduler()
        return dict(tasks._scheduler.jobs)


def _resolve(dotted):
    parts = dotted.split('.')
    for i in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module('.'.join(parts[:i]))
        except ImportError:
            continue
        for name in parts[i:]:
            obj = getattr(obj, name)
        return obj
    raise ImportError(dotted)


class SchedulerLockRegistryTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.jobs = _registered()

    def test_every_job_is_classified_and_no_entry_is_stale(self):
        self.assertEqual(sorted(set(self.jobs) - set(SCHEDULER_JOB_GUARDS)), [],
                         'new scheduler job: add it to SCHEDULER_JOB_GUARDS with its guard')
        self.assertEqual(sorted(set(SCHEDULER_JOB_GUARDS) - set(self.jobs)), [], 'stale entry')

    def test_every_job_is_single_instance_in_process(self):
        self.assertEqual([j for j, kw in self.jobs.items() if kw.get('max_instances') != 1], [])

    def test_every_guard_is_still_in_the_code(self):
        missing = []
        for job, (kind, where, proof, reason) in SCHEDULER_JOB_GUARDS.items():
            self.assertIn(kind, KINDS, job)
            self.assertTrue(reason.strip(), job)
            try:
                src = inspect.getsource(_resolve(where))
            except (ImportError, AttributeError, TypeError, OSError) as exc:
                missing.append(f'{job}: cannot read {where} ({exc})')
                continue
            if proof not in src:
                missing.append(f'{job}: "{proof}" not in {where}')
        self.assertEqual(missing, [], '\n'.join(missing))

    def test_senders_and_softech_writers_without_a_lock_are_known_gaps(self):
        weak = {'none', 'once_per_period_check'}
        open_ = sorted(j for j in SENDS_OR_WRITES_SOFTECH
                       if SCHEDULER_JOB_GUARDS[j][0] in weak and j not in KNOWN_GAPS)
        self.assertEqual(open_, [])
        self.assertEqual(sorted(j for j in KNOWN_GAPS if j not in SCHEDULER_JOB_GUARDS), [])

    def test_campaign_drain_claims_each_message_once(self):
        self.assertEqual(SCHEDULER_JOB_GUARDS['wa_campaign_drain'][0], 'row_lock')


# ── Only one scheduler process (owner OK 2026-11-05) ──────────────────────────────────────


class SingleSchedulerLockTests(TestCase):

    def tearDown(self):
        from apps.sync import scheduler_lock
        scheduler_lock.release()

    def test_a_second_process_cannot_take_the_lock(self):
        from apps.sync import scheduler_lock as L
        self.assertTrue(L.acquire())
        self.assertTrue(L.acquire())                         # same process: idempotent
        other = L._raw_connection()                          # stands in for a second process
        try:
            with other.cursor() as cur:
                cur.execute('SELECT pg_try_advisory_lock(%s)', [L.SCHEDULER_LOCK_KEY])
                self.assertFalse(cur.fetchone()[0])
            L.release()
            with other.cursor() as cur:
                cur.execute('SELECT pg_try_advisory_lock(%s)', [L.SCHEDULER_LOCK_KEY])
                self.assertTrue(cur.fetchone()[0])
                cur.execute('SELECT pg_advisory_unlock(%s)', [L.SCHEDULER_LOCK_KEY])
        finally:
            other.close()

    def test_holder_is_recorded_for_the_status_api(self):
        from apps.sync import scheduler_lock as L
        L.acquire()
        self.assertIn('pid', L.current_owner())

    def test_second_scheduler_starts_no_jobs_and_alerts_admins(self):
        from apps.notifications.models import Notification
        from apps.tests.factories import make_admin
        make_admin('sched_admin')
        with mock.patch('apps.sync.scheduler_lock.acquire', return_value=False), \
                mock.patch('apps.sync.tasks.start_scheduler') as start, \
                mock.patch('config.writers.run_startup_checks'):
            with self.assertRaises(CommandError) as ctx:
                call_command('run_scheduler')
            with self.assertRaises(CommandError):
                call_command('run_scheduler')                # same day, same host: one alert only
        start.assert_not_called()
        self.assertEqual(ctx.exception.returncode, 2)
        self.assertEqual(Notification.objects.filter(title__contains='مجدول ثانٍ').count(), 1)
