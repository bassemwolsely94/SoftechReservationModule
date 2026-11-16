"""
Load test for the VPS before Stage B (full audit 2026-11-15, decision D-22; plan in
docs/full-project-audit/07_PERFORMANCE_AUDIT.md "What a Locust test should cover").

READ-ONLY: only GET requests plus the login POST. Nothing is created and nothing reaches a SOFTECH writer.
Run it against the VPS while it is a reader (Stage A) — never against the office writer.

    pip install locust                      # on the machine that drives the test, not on the VPS
    set LOADTEST_USERNAME / LOADTEST_PASSWORD (a test staff account WITHOUT 2FA, branch-scoped role)
    locust -f deploy/loadtest/locustfile.py --host https://<vps-host> \
           --users 20 --spawn-rate 2 --run-time 15m --headless --csv loadtest_20
    then 40 users. Record p50/p95/p99 and failures per route from the CSV; watch on the VPS:
    `htop`, `sudo -u postgres psql -c "select count(*) from pg_stat_activity"`, free -m.
"""
import os
import random

from locust import HttpUser, between, task

SEARCH_TERMS = ['panadol', 'augmentin', 'بانادول', 'فيتامين', 'conco*', '0100']


class StaffUser(HttpUser):
    """One staff screen: the background polls every open tab makes, plus interactive reads."""
    wait_time = between(2, 6)

    def on_start(self):
        r = self.client.post('/api/auth/login/', json={
            'username': os.environ['LOADTEST_USERNAME'], 'password': os.environ['LOADTEST_PASSWORD']},
            name='auth/login')
        if r.status_code != 200 or 'mfa' in r.text.lower():
            raise RuntimeError(f'login failed for the load-test account ({r.status_code}) — use one without 2FA')

    # ── background polls (weights ≈ the 30 / 60 / 90 s intervals in the screens) ─────────────────
    @task(6)
    def bell(self):
        self.client.get('/api/notifications/?limit=20', name='notifications/')
        self.client.get('/api/notifications/category-counts/', name='notifications/category-counts')

    @task(3)
    def freshness(self):
        self.client.get('/api/sync/status/', name='sync/status')
        self.client.get('/api/sync/freshness/', name='sync/freshness')

    @task(2)
    def dashboard(self):
        self.client.get('/api/dashboard/summary/', name='dashboard/summary')

    # ── interactive reads ────────────────────────────────────────────────────────────────────────
    @task(3)
    def search(self):
        q = random.choice(SEARCH_TERMS)
        self.client.get(f'/api/search/?q={q}', name='search')
        self.client.get(f'/api/items/?q={q}', name='items')
        self.client.get(f'/api/customers/?q={q}', name='customers')

    @task(2)
    def worklists(self):
        self.client.get('/api/reservations/', name='reservations')
        self.client.get('/api/supply/cases/', name='supply/cases')
        self.client.get('/api/pos-orders/', name='pos-orders')

    @task(1)
    def purchasing(self):
        self.client.get('/api/purchasing/metrics/', name='purchasing/metrics')
        self.client.get('/api/purchasing/filter-options/', name='purchasing/filter-options')

    @task(1)
    def insurance(self):
        self.client.get('/api/insurance/claims/', name='insurance/claims')
