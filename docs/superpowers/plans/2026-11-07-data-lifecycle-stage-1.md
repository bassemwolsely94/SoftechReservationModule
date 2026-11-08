# Data Lifecycle Stage 1: Dependable Retention — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A missed retention run catches itself up, and a retention or morning-chain run that stays missing alerts admins.

**Architecture:** A new 15-minute scheduler job, `retention_watch`, first runs retention if it is overdue, then checks for missed lanes. All logic lives in `apps/sync/maintenance.py`; `apps/sync/tasks.py` only registers the job. An advisory lock stops the catch-up and the 04:45 job overlapping.

**Tech Stack:** Django 4.2, APScheduler, PostgreSQL advisory locks.

**Spec:** [docs/superpowers/specs/2026-11-07-data-lifecycle-design.md](../specs/2026-11-07-data-lifecycle-design.md) (§6 Stage 1, §8 first two bullets).

**One departure from the spec, on purpose:** the spec says catch-up runs from "scheduler start and its heartbeat". It runs from its own job instead, which also fires at scheduler start, because a long retention run must not block the one-minute heartbeat. The alert runs right after the catch-up in the same job, so a laptop waking late does not alert about a run that is about to succeed.

## Global Constraints

- Our Postgres only: no SOFTECH reads or writes, no migrations, no new API or screen.
- Overdue threshold: **26 hours** since the last `success`, for both `retention` and `morning_chain`.
- Alerts: at most one per lane per day, to active admins, type `sync_failure`, Arabic text.
- Morning chain **alerts only**, with no automatic catch-up.
- A failing retention is retried at most once per **6 hours**.
- Help update required (CLAUDE.md step 5b). Run tests with a unique `TEST_DB_NAME`, serially, never `--parallel`.
- Work on branch `claude/data-lifecycle-stage-1`, not on `main`.

## Review Focus

1. **Retention keeps failing:** it must not re-run every 15 minutes. Pinned in Task 1, `test_failed_attempt_waits_six_hours`.
2. **Another process holds the lock:** nothing runs, and no `running` row is left behind to look stuck. Pinned in Task 1, `test_lock_busy_leaves_no_run_row`.
3. **Laptop wakes long after the due time and catch-up succeeds:** no alert. Pinned in Task 2, `test_late_wake_successful_catchup_does_not_alert`.
4. **A lane that has never run (fresh install):** no morning-chain alert; retention simply runs. Pinned in Task 2, `test_lane_that_never_ran_does_not_alert`.
5. **Catch-up raises inside the job:** the job survives and the alert check still runs. Pinned in Task 2, `test_watch_alerts_even_if_catchup_raises`.

---

### Task 1: Overlap lock and catch-up

**Files:**
- Modify: `apps/sync/maintenance.py` (`run_daily_retention`, new constants and functions, module docstring)
- Create: `apps/tests/test_retention_watch.py`
- Add to the branch: this plan and the design spec (not yet committed)

**Interfaces:**
- Produces: `run_daily_retention() -> SyncRun | None` (`None` when the lock is busy); `retention_catchup_due(now=None) -> bool`; `run_retention_catchup() -> SyncRun | None`; constants `RETENTION_LOCK_KEY`, `OVERDUE_HOURS = 26`, `RETENTION_RETRY_HOURS = 6`.

- [ ] **Step 1: Create the branch and add the docs**

Branch `claude/data-lifecycle-stage-1` from an up-to-date `main`, then `git add` the spec and this plan. Confirm `7_301_102` is unused: `git grep -n "7_301_102\|7301102"` prints nothing.

- [ ] **Step 2: Write the failing tests** in `apps/tests/test_retention_watch.py`, class `RetentionCatchupTests(TestCase)`

Helper `_run(status, hours_ago, lane='retention')` creates a `SyncRun`, then backdates `started_at` with `.update()`. Patch `apps.sync.maintenance.prune_*` where a real run is not the point.

```python
def test_never_ran_is_due(self):
    self.assertTrue(retention_catchup_due())

def test_recent_success_is_not_due(self):
    self._run('success', 25)
    self.assertFalse(retention_catchup_due())

def test_old_success_is_due(self):
    self._run('success', 27)
    self.assertTrue(retention_catchup_due())

def test_running_row_is_not_due(self):
    self._run('success', 27)
    self._run('running', 0)
    self.assertFalse(retention_catchup_due())

def test_failed_attempt_waits_six_hours(self):
    self._run('success', 40)
    self._run('failed', 5)
    self.assertFalse(retention_catchup_due())
    SyncRun.objects.filter(status='failed').update(started_at=timezone.now() - timedelta(hours=7))
    self.assertTrue(retention_catchup_due())

def test_catchup_runs_once_and_is_logged(self):
    self._run('success', 27)
    self.assertIsNotNone(run_retention_catchup())
    self.assertIsNone(run_retention_catchup())   # now recent
    self.assertEqual(SyncLog.objects.filter(table_name='retention:catchup').count(), 1)

def test_lock_busy_leaves_no_run_row(self):
    # hold RETENTION_LOCK_KEY on a separate raw connection (see scheduler_lock._raw_connection);
    # a same-connection lock would not block, because PG advisory locks are re-entrant per session
    before = SyncRun.objects.filter(lane='retention').count()
    self.assertIsNone(run_daily_retention())
    self.assertEqual(SyncRun.objects.filter(lane='retention').count(), before)
```

- [ ] **Step 3: Run them and see them fail**

Run: `TEST_DB_NAME=test_retention_watch venv/Scripts/python.exe manage.py test apps.tests.test_retention_watch`
Expected: FAIL with an import error for `retention_catchup_due`.

- [ ] **Step 4: Implement in `apps/sync/maintenance.py`**

- `RETENTION_LOCK_KEY = 7_301_102`.
- `run_daily_retention`: wrap the whole body in `apps.vouchers.coupon_dashboard.pg_lock(RETENTION_LOCK_KEY)` (import inside the function). If not acquired, log and return `None` **before** creating the `SyncRun`.
- `retention_catchup_due`: `False` if a `running` row exists for the lane; `False` if the last `success` is under 26 hours old; `False` if the latest attempt of any status started under 6 hours ago **and** failed; otherwise `True`.
- `run_retention_catchup`: if due, call `run_daily_retention()`; when it returns a run, add `SyncLog(sync_run=run, table_name='retention:catchup', records_processed=1)` and return the run. Otherwise return `None`.
- Update the module docstring.

- [ ] **Step 5: Run the tests and see them pass**

Run: same as Step 3. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/sync/maintenance.py apps/tests/test_retention_watch.py docs/superpowers/specs/2026-11-07-data-lifecycle-design.md docs/superpowers/plans/2026-11-07-data-lifecycle-stage-1.md
git commit -m "feat(sync): retention catch-up with an overlap lock (data lifecycle stage 1)"
```

---

### Task 2: Missed-run alert and the `retention_watch` job

**Files:**
- Modify: `apps/sync/maintenance.py` (`alert_failing_lanes` shares a helper; new `alert_missed_runs`, `retention_watch`)
- Modify: `apps/sync/tasks.py` (near `_run_daily_retention`, and job registration near line 3730)
- Modify: `apps/tests/test_scheduler_locks.py` (registry)
- Modify: `apps/tests/test_retention_watch.py`

**Interfaces:**
- Consumes: `run_retention_catchup()`, `OVERDUE_HOURS` from Task 1.
- Produces: `alert_missed_runs(now=None) -> list[str]` (lanes alerted); `retention_watch() -> None`; scheduler job id `retention_watch`.

- [ ] **Step 1: Write the failing tests**, class `MissedRunAlertTests(TestCase)`, admin from `make_admin` as in `test_notification_routing.py`

```python
def test_missed_morning_chain_alerts_once_a_day(self):
    self._run('success', 27, lane='morning_chain')
    self.assertEqual(alert_missed_runs(), ['morning_chain'])
    alert_missed_runs()
    self.assertEqual(self._alerts(), 1)

def test_recent_success_does_not_alert(self):
    self._run('success', 25, lane='morning_chain')
    self.assertEqual(alert_missed_runs(), [])

def test_running_lane_does_not_alert(self):
    self._run('success', 27, lane='morning_chain')
    self._run('running', 0, lane='morning_chain')
    self.assertEqual(alert_missed_runs(), [])

def test_lane_that_never_ran_does_not_alert(self):
    self.assertEqual(alert_missed_runs(), [])

def test_only_failures_count_from_the_first_attempt(self):
    self._run('failed', 27, lane='morning_chain')
    self.assertEqual(alert_missed_runs(), ['morning_chain'])

def test_late_wake_successful_catchup_does_not_alert(self):
    self._run('success', 50)                    # retention lane
    retention_watch()
    self.assertEqual(self._alerts(), 0)
    self.assertEqual(SyncRun.objects.filter(lane='retention', status='success').count(), 2)

def test_failed_catchup_alerts(self):
    self._run('success', 50)
    with mock.patch('apps.sync.maintenance.prune_notifications', side_effect=RuntimeError('x')):
        retention_watch()
    self.assertEqual(self._alerts(), 1)

def test_watch_alerts_even_if_catchup_raises(self):
    self._run('success', 27, lane='morning_chain')
    with mock.patch('apps.sync.maintenance.run_retention_catchup', side_effect=RuntimeError('x')):
        retention_watch()                       # must not raise
    self.assertEqual(self._alerts(), 1)

def test_morning_chain_is_never_run_by_the_watch(self):
    self._run('success', 27, lane='morning_chain')
    with mock.patch('apps.sync.tasks._run_morning_chain') as chain:
        retention_watch()
    chain.assert_not_called()
```

- [ ] **Step 2: Run them and see them fail**

Run: `TEST_DB_NAME=test_retention_watch venv/Scripts/python.exe manage.py test apps.tests.test_retention_watch`
Expected: FAIL with an import error for `alert_missed_runs`.

- [ ] **Step 3: Implement in `apps/sync/maintenance.py`**

- Move the admin send loop out of `alert_failing_lanes` into `_alert_admins(title, body, dedup_key)`, behaviour unchanged (type `sync_failure`, `dedup_once=True`, `bypass_role_gate=True`).
- `MISSED_RUN_LANES = ('retention', 'morning_chain')`.
- `alert_missed_runs`: for each lane, skip if it has no rows or a `running` row. The reference time is the latest `success`, or the earliest attempt when it has never succeeded. Alert when the reference is older than `OVERDUE_HOURS`. Dedup key `missed_run_{lane}_{today}`. Exact text, with `label = LANE_LABELS[lane]`:
  - Title: `f'🟠 لم تكتمل مهمة «{label}»'`
  - Body: `f'لم تنجح مهمة «{label}» منذ أكثر من {OVERDUE_HOURS} ساعة. غالباً كان المجدول أو الجهاز متوقفاً، أو أن المهمة فشلت — راجع صفحة المزامنة.'`
- `retention_watch`: call `run_retention_catchup()` in `try/except Exception` with `logger.exception`, then `alert_missed_runs()` in its own `try/except`. It never raises.

- [ ] **Step 4: Register the job in `apps/sync/tasks.py`**

Add `_run_retention_watch()` beside `_run_daily_retention`, same shape. Register right after `daily_retention`: `'interval', minutes=15, id='retention_watch', replace_existing=True, max_instances=1, misfire_grace_time=300, next_run_time=timezone.now()`.

- [ ] **Step 5: Update `SCHEDULER_JOB_GUARDS`** in `apps/tests/test_scheduler_locks.py`

- Change `daily_retention` to kind `advisory_lock`, proof text `pg_lock(RETENTION_LOCK_KEY)`.
- Add `retention_watch`: `('advisory_lock', 'apps.sync.maintenance.run_daily_retention', 'pg_lock(RETENTION_LOCK_KEY)', 'catch-up shares the retention lock; missed-run alert is dedup_once per lane per day')`.

- [ ] **Step 6: Run the affected tests**

Run: `TEST_DB_NAME=test_retention_watch venv/Scripts/python.exe manage.py test apps.tests.test_retention_watch apps.tests.test_notification_routing apps.tests.test_scheduler_locks`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/sync/maintenance.py apps/sync/tasks.py apps/tests/test_scheduler_locks.py apps/tests/test_retention_watch.py
git commit -m "feat(sync): alert when retention or the morning chain misses a run"
```

---

### Task 3: Help, docs and final checks

**Files:**
- Modify: `apps/help/content/admin.py` (the `/sync` screen entry)
- Modify: `docs/product-review/00_INDEX_AND_DECISION_LEDGER.md` (P-56 line)

- [ ] **Step 1: Update the `/sync` help** in Arabic and English, and bump its `updated` date

Say: if the daily database cleanup was missed because the scheduler or device was off, it now runs by itself within 15 minutes of coming back. If the cleanup or morning tasks still have no successful run after 26 hours, admins get one alert a day.

- [ ] **Step 2: Add to the P-56 ledger line:** `Stage 1 of the data lifecycle design: catch-up + missed-run alert`, with the build date and a link to the spec.

- [ ] **Step 3: Run the regression set, serially**

Run: `TEST_DB_NAME=test_retention_stage1 venv/Scripts/python.exe manage.py test apps.tests.test_retention_watch apps.tests.test_notification_routing apps.tests.test_scheduler_locks apps.tests.test_help apps.tests.security`
Expected: all PASS, with no new baseline lines.

- [ ] **Step 4: Commit**

```bash
git add apps/help/content/admin.py docs/product-review/00_INDEX_AND_DECISION_LEDGER.md
git commit -m "docs(help): explain retention catch-up and missed-run alerts"
```

- [ ] **Step 5: Check on the running system after merge**

After the scheduler restarts on the new code, confirm: job `retention_watch` is registered; a `retention` run with a `retention:catchup` log row appears if overdue; `/api/sync/scheduler-status/` stays healthy. Do not force an alert on the live system.
