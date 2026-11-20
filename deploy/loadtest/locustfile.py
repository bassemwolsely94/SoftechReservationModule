"""
Load test (full audit 2026-11-15, decision D-22; plan in docs/full-project-audit/07_PERFORMANCE_AUDIT.md
"What a Locust test should cover"). Two modes:

* **VPS mode** (one account): set LOADTEST_USERNAME / LOADTEST_PASSWORD (a test staff account
  WITHOUT 2FA, branch-scoped role). Every virtual user signs in as that account.
* **UAT mode** (role mix): set UAT_USERS_JSON to the git-ignored `frontend/uat/.uat-users.json`
  (`{"password": ..., "users": [{"username", "role", ...}]}`). Virtual users are spread over the
  roles below by weight (pharmacist / salesperson heavy) and each signs in as a UAT user of its role.
  Used by scripts/uat/run_light_load.ps1 against the UAT copy (docs/uat/light-load.md).

READ-ONLY: only GET requests plus the login POST. Nothing is created and nothing reaches a SOFTECH
writer. Run it against a reader (VPS Stage A, or the UAT copy) — never against the office writer.

    pip install locust                      # on the machine that drives the test, not on the VPS
    locust -f deploy/loadtest/locustfile.py --host https://<vps-host> \
           --users 20 --spawn-rate 2 --run-time 15m --headless --csv loadtest_20
    then 40 users. Record p50/p95/p99 and failures per route from the CSV; watch on the VPS:
    `htop`, `sudo -u postgres psql -c "select count(*) from pg_stat_activity"`, free -m.

A 403 (the role may not open that screen) is not a server failure: it is recorded as success and
counted once more under request type "403" so the role mix shows up in the stats.

Performance boost (design docs/superpowers/specs/2026-11-19-performance-boost-design.md):
* LOADTEST_POLL_MODE=push (default) models screens after Stage 5: the bell and freshness come over the
  WebSocket, so the HTTP polls run only at the slow fallback rate (weights 1). LOADTEST_POLL_MODE=poll
  restores the old 30/60/90 s mix, to compare.
* LOADTEST_EXPORT_JOBS=1 adds ONE extra virtual user that keeps running the heavy purchasing export as a
  Stage 4 background job (start → poll status → download) — the "interference test": read the other
  routes' p95 with and without it. The job writes only its own export_jobs row in Postgres (no SOFTECH).
  It needs an account that may export purchasing; otherwise its calls show as 403.
"""
import itertools
import json
import os
import random
import time

from locust import HttpUser, between, constant, task

SEARCH_TERMS = ['panadol', 'augmentin', 'بانادول', 'فيتامين', 'conco*', '0100']

# Stage 5: bell / freshness / dashboard arrive over the WebSocket; HTTP polls are only the fallback.
PUSH_MODE = os.environ.get('LOADTEST_POLL_MODE', 'push') != 'poll'
BELL_W, FRESH_W, DASH_W = (1, 1, 1) if PUSH_MODE else (6, 3, 2)
EXPORT_JOBS = os.environ.get('LOADTEST_EXPORT_JOBS') == '1'

# role → weight in the UAT mix (≈ how many of the 20–40 daily staff sit in that role).
ROLE_WEIGHTS = {'pharmacist': 4, 'salesperson': 3, 'call_center': 1, 'supervisor': 1, 'purchasing': 1}


def _load_uat_users():
    path = os.environ.get('UAT_USERS_JSON')
    if not path:
        return None, {}
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    by_role = {}
    for u in data['users']:
        if u.get('shape') == 'real':           # sampled real accounts stay out of the load mix
            continue
        by_role.setdefault(u['role'], []).append(u['username'])
    return data['password'], by_role


UAT_PASSWORD, UAT_USERS_BY_ROLE = _load_uat_users()
_CYCLES = {role: itertools.cycle(names) for role, names in UAT_USERS_BY_ROLE.items()}


class _Staff(HttpUser):
    """One staff screen: the background polls every open tab makes, plus interactive reads."""
    abstract = True
    wait_time = between(2, 6)
    role = None

    def credentials(self):
        if UAT_PASSWORD is not None:
            return next(_CYCLES[self.role]), UAT_PASSWORD
        return os.environ['LOADTEST_USERNAME'], os.environ['LOADTEST_PASSWORD']

    def on_start(self):
        username, password = self.credentials()
        r = self.client.post('/api/auth/login/', json={'username': username, 'password': password},
                             name='auth/login')
        # the user payload carries mfa_* fields, so look at the 2FA gate flag, not the raw text
        mfa_gate = r.status_code == 200 and bool(r.json().get('mfa_required'))
        if r.status_code != 200 or mfa_gate:
            raise RuntimeError(f'login failed for a load-test account ({r.status_code}, 2FA gate={mfa_gate}) '
                               '- use one without 2FA')

    def get(self, url, name):
        with self.client.get(url, name=name, catch_response=True) as r:
            if r.status_code == 403:
                r.success()
                self.environment.events.request.fire(
                    request_type='403', name=name, response_time=0, response_length=0,
                    exception=None, context={})
            elif r.status_code >= 400:
                r.failure(f'HTTP {r.status_code}')

    # ── background polls (weights ≈ the 30 / 60 / 90 s intervals in the screens) ─────────────────
    @task(BELL_W)
    def bell(self):
        self.get('/api/notifications/?limit=20', 'notifications/')
        self.get('/api/notifications/category-counts/', 'notifications/category-counts')

    @task(FRESH_W)
    def freshness(self):
        self.get('/api/sync/status/', 'sync/status')
        self.get('/api/sync/freshness/', 'sync/freshness')

    @task(DASH_W)
    def dashboard(self):
        self.get('/api/dashboard/summary/', 'dashboard/summary')

    # ── interactive reads (every role) ───────────────────────────────────────────────────────────
    @task(3)
    def search(self):
        q = random.choice(SEARCH_TERMS)
        self.get(f'/api/search/universal?q={q}', 'search/universal')
        self.get(f'/api/items/?search={q}', 'items?search')
        self.get(f'/api/customers/?search={q}', 'customers?search')

    @task(2)
    def worklists(self):
        self.get('/api/reservations/', 'reservations')
        self.get('/api/supply/cases/', 'supply/cases')
        self.get('/api/pos-orders/', 'pos-orders')


class StaffUser(_Staff):
    """VPS mode: the original single-account mix (purchasing + insurance included)."""
    abstract = UAT_PASSWORD is not None

    @task(1)
    def purchasing(self):
        self.get('/api/purchasing/metrics/', 'purchasing/metrics')
        self.get('/api/purchasing/filter-options/', 'purchasing/filter-options')

    @task(1)
    def insurance(self):
        self.get('/api/insurance/claims/', 'insurance/claims')


# ── UAT mode: one class per role, extra tasks for the screens that role lives on ────────────────
class PharmacistUser(_Staff):
    role, weight = 'pharmacist', ROLE_WEIGHTS['pharmacist']
    abstract = 'pharmacist' not in UAT_USERS_BY_ROLE

    @task(2)
    def counter(self):
        self.get('/api/batches/stock-expiry/summary/', 'batches/stock-expiry/summary')


class SalespersonUser(_Staff):
    role, weight = 'salesperson', ROLE_WEIGHTS['salesperson']
    abstract = 'salesperson' not in UAT_USERS_BY_ROLE

    @task(2)
    def counter(self):
        self.get('/api/customers/', 'customers')


class CallCenterUser(_Staff):
    role, weight = 'call_center', ROLE_WEIGHTS['call_center']
    abstract = 'call_center' not in UAT_USERS_BY_ROLE

    @task(3)
    def calls(self):
        self.get('/api/customers/', 'customers')
        self.get('/api/reservations/', 'reservations')


class SupervisorUser(_Staff):
    role, weight = 'supervisor', ROLE_WEIGHTS['supervisor']
    abstract = 'supervisor' not in UAT_USERS_BY_ROLE

    @task(2)
    def oversight(self):
        self.get('/api/insurance/claims/', 'insurance/claims')
        self.get('/api/dashboard/supply/', 'dashboard/supply')


class PurchasingUser(_Staff):
    role, weight = 'purchasing', ROLE_WEIGHTS['purchasing']
    abstract = 'purchasing' not in UAT_USERS_BY_ROLE

    @task(3)
    def purchasing(self):
        self.get('/api/purchasing/metrics/', 'purchasing/metrics')
        self.get('/api/purchasing/filter-options/', 'purchasing/filter-options')


# ── interference test (Stage 4): one user keeps a heavy export running as a background job ───────
class ExportJobUser(_Staff):
    """LOADTEST_EXPORT_JOBS=1: start the purchasing export as a job, poll it the way the screen does
    (every 1.5 s, up to 5 min), download the file, pause, repeat. Exactly one such user."""
    abstract = not EXPORT_JOBS
    fixed_count = 1
    wait_time = constant(10)
    role = 'purchasing'

    def credentials(self):
        if UAT_PASSWORD is not None and 'purchasing' in UAT_USERS_BY_ROLE:
            return next(_CYCLES['purchasing']), UAT_PASSWORD
        return os.environ['LOADTEST_USERNAME'], os.environ['LOADTEST_PASSWORD']

    @task
    def export_job(self):
        with self.client.post('/api/purchasing/export/jobs/', json={}, name='purchasing/export/jobs [start]',
                              catch_response=True) as r:
            if r.status_code == 403:
                r.success()
                return
            if r.status_code not in (200, 201, 202):
                r.failure(f'HTTP {r.status_code}')
                return
            job_id = r.json().get('id')
        started = time.monotonic()
        status = 'queued'
        while status in ('queued', 'running') and time.monotonic() - started < 300:
            time.sleep(1.5)
            with self.client.get(f'/api/export-jobs/{job_id}/', name='export-jobs/<id> [poll]',
                                 catch_response=True) as r:
                if r.status_code != 200:
                    r.failure(f'HTTP {r.status_code}')
                    return
                status = r.json().get('status')
        if status != 'done':
            self.environment.events.request.fire(
                request_type='JOB', name=f'purchasing export job {status}', response_time=0,
                response_length=0, exception=RuntimeError(status), context={})
            return
        self.environment.events.request.fire(
            request_type='JOB', name='purchasing export job total', response_length=0, exception=None,
            response_time=(time.monotonic() - started) * 1000, context={})
        self.get(f'/api/export-jobs/{job_id}/download/', 'export-jobs/<id>/download')
