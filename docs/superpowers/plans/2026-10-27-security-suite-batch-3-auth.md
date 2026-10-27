# Security Suite — Batch 3 (authentication) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Nobody gets a session without the password AND (when enrolled) the second factor; a
session ends when the account is disabled or its password is reset; WebSocket and IP-based
controls can't be fooled.

**Owner rule (design §Stop-and-ask):** every auth fix lands only as a small diff the owner
approved — same flow as Batch 2 (failing test `@pending('A-<n>')` → `scratch/batch3/A-<n>.patch`
→ OK → apply, run, next).

**Spec:** [design](../specs/2026-10-26-full-security-test-suite-design.md) item 5 + Batch 3 row ·
[inventory](../../security/2026-10-26-security-inventory.md) C1, C11, WebSocket, XFF, passwords.

## Verified in the code (2026-10-27)

| A | Hole | Where |
|---|---|---|
| A-1 | **2FA bypass with the password only.** Login hands back a `login` pre-auth token; `setup_2fa_view` / `enable_2fa_view` accept it → the attacker installs their own secret over the enrolled one and `enable` returns JWTs + fresh backup codes. `setup` also overwrites an enrolled user's secret for a JWT caller (silent lock-out / takeover with a stolen session). | `apps/users/mfa.py` `_actor_from_request`, `setup_2fa_view`, `enable_2fa_view` |
| A-2 | **Second factor guessable / replayable.** `verify_2fa` has no throttle and the 5-minute pre-auth token is reusable for unlimited guesses; an accepted TOTP code can be used again inside its ±30 s window. | `mfa.py` `verify_2fa_view`, `verify_totp` |
| A-3 | **Disabling an account / resetting its password does not end the session.** `toggle_active` flips `StaffProfile.is_active` only; `refresh_view` keeps rotating; the access token keeps working; admin password reset leaves refresh tokens alive; the 30-day trusted-device token survives a password change, reset or 2FA reset. | `apps/users/views.py` `toggle_active`, reset, `refresh_view`; `core/auth_cookies.py`; `mfa.py` device token |
| A-4 | **WebSocket accepts any token type.** `UntypedToken` takes a 7-day refresh token (blacklisted ones too); no active-account check; no Origin validator. | `apps/notifications/middleware.py`, `config/asgi.py` |
| A-5 | **Password policy is 6 characters.** No `AUTH_PASSWORD_VALIDATORS`; change / reset / create don't call `validate_password`. | `config/settings.py`, `apps/users/views.py`, serializers |
| A-6 | **Client IP is spoofable.** `_get_client_ip` trusts the left-most `X-Forwarded-For` (client-controlled; nginx `proxy_params` appends), so auth logs record a forged IP; DRF throttles key on the whole XFF string (`NUM_PROXIES` unset) → a new header = a new bucket. (nginx `limit_req` per real IP still caps `/api/auth/` in production.) | `apps/users/middleware.py`, `REST_FRAMEWORK` |

HSTS (default 0) stays with Batch 6 (platform).

## Owner decisions (2026-10-27)

1. **A-5 password rule:** minimum 10 characters + Django's common / all-numeric /
   similar-to-username checks. Existing passwords keep working; the rule applies when a password
   is set.
2. **A-2 attempts:** 5 wrong codes per login → the pre-auth token dies, log in again.
3. **A-6 production proxy count:** `NUM_PROXIES=1` in the VPS `.env` (owner adds it; nginx is the
   one proxy). Default 0 (dev, no proxy → the socket address is used), but 1 when
   `BEHIND_HTTPS_PROXY=True` — with 0 behind nginx every user is 127.0.0.1 and shares one login
   bucket (approved with A-6).
4. **A-3 device token:** a password change, admin reset or 2FA reset cancels every
   "remember this device".

A-1 … A-6 applied 2026-10-27 — Batch 3 done. A-5 also fixed create-user answering 500 after
saving the user.

## Order

A-1 → A-3 → A-2 → A-4 → A-5 → A-6 (risk first). Each: pending test, patch, owner OK, apply,
run `apps.tests.security` + `apps.tests.test_users*` / `test_mfa*` / auth suites.

## Done when

- `PENDING.md` holds only deferred items; every A-item has a passing test.
- The auth suite (login, 2FA incl. bypass, refresh/rotation/blacklist, deactivation, password
  policy, device token, WebSocket) runs in `apps/tests/security/test_auth_*.py`.
