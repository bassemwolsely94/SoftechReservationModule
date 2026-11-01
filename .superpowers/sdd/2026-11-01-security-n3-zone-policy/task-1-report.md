# Task 1 report - proxy key
Status: DONE. Added network.proxy_key_ok, key check in zone_from_request, NETWORK_PROXY_KEY setting, access.E003 (enforce+trusted+no key) and access.W002 (trusted+no key, not DEBUG), nginx include + deploy/nginx-proxy-key.conf.example, env/DEPLOY docs, runbook "Batch N3 on the live server" step 1.
Tests: 42 OK (network, context, checks, nginx label); manage.py check clean.
Concerns: a logged traceback "access log line failed" appears in test output (from a pre-existing test path in apps/access/middleware.py); tests still pass. TDD red run was skipped (tooling), tests written first.
