# Security Suite — Batch 6 (platform & abuse) Plan

Spec: [full security test suite design](../specs/2026-10-26-full-security-test-suite-design.md),
Batch 6 row: WebSocket chatter / PBX authorization, SSRF, formula injection, uploads, portal
token reuse + reorder bounds, voucher OTP exposure, HSTS / secure defaults, `.gitignore`,
tracked secrets. Stop-and-ask inside: **voucher redemption**.

Branch `claude/security-batch6-platform` (worktree `.claude/worktrees/security-batch6-platform`),
cut from `origin/main` 5e19ab85 (2026-11-01). Same flow as Batches 2–4: a failing test first
(`@pending('W-<n>')` + `PENDING.md`), a diff the owner approves, then apply.

## Survey (2026-11-01, read-only, current `origin/main`)

Already owned elsewhere — not in this batch:
- **PBX live-call socket** broadcasts every caller (name, phone, purchases, vouchers, loyalty) to
  every logged-in user: fixed by PR #21 (Batch 5b, D1 — only agents join).
- Chatter **REST** branch check: PR #18. Network / device holes (forged IP, lockout, admin
  allow-list): PR #23 (N0) — it also edits `config/settings.py` and `deploy/nginx.conf`, so W-7 /
  W-9 below rebase onto it.

| W | Hole (evidence) | Severity | Ask? |
|---|---|---|---|
| W-1 | **Voucher OTP reaches the staff member.** `generate-otp` returns `whatsapp_url` = wa.me link with the plain code in `?text=` (`vouchers/models.py:404-417`) and `qr_code` = PNG of the plain code (`vouchers/views.py:271,296`); the screen opens the link on the staff device. Staff redeem without the customer. | Critical | **yes** — voucher redemption |
| W-2 | **Private voucher not tied to its customer's phone** (`vouchers/models.py:210-212` checks only that a customer is set); per-customer limits are keyed by the phone staff type. | High | **yes** — voucher redemption |
| W-3 | **Chatter socket**: join any `chatter_<model>_<id>` and `post` to any model/record — no model allow-list, branch check or length cap (`notifications/consumers.py:166-234`); push payload carries signed attachment links. | High | — |
| W-4 | **Formula injection**: ~50 export sites, no shared sanitiser. Worst: portal customers' `manual_item_name` / `notes` → staff reservations Excel (`portal/views.py:266,273` → `reservations/views.py:1335-1342`); OCR / voice / pasted text → shortage + supplier-invoice exports; insurance patient names; coupon customers. | High | — |
| W-5 | **Portal**: magic link reusable for its 15 min and stored in plain text in the WhatsApp inbox (`whatsapp/sender.py:165-169`) → staff can take over a customer session; sessions can't be revoked; request-link throttle keyed `phone|IP`; **reorder** has no throttle, no quantity bounds (0 / negative / 99,999,999), any catalog item (`portal/serializers.py:387-392`, `views.py:226-274`). | Medium | one product question (below) |
| W-6 | **SSRF**: `CallLog.recording_url` (call-center editable) fetched on transcribe — no private-IP / scheme block, redirects followed, no size cap (`omni/transcription.py:55-62`). Image downloader accepts `file://` (`images/downloader.py`). | Medium | — |
| W-7 | **Public-media stored XSS**: product / content uploads keep the client's extension in public `products/`; nginx + `core/media.py` script lists miss `.shtml` and similar (`images/views.py:550-576`, `product_experience/models.py:22-29`). | Medium | — |
| W-8 | **Uploads not validated** (type / size) on payments, tasks, reservations, delivery, call center; no `DATA_UPLOAD_MAX_MEMORY_SIZE` / per-file cap; Excel imports with no row / size cap. Signed private storage limits the damage. | Low–medium | — |
| W-9 | **HSTS off** (`SECURE_HSTS_SECONDS` default 0, not set in `deploy/staging.env.example` / runbook, no nginx header); no Content-Security-Policy on the app. | Medium | **yes** — HSTS is sticky in browsers |
| W-10 | **Tracked secret**: real admin username + password in `scripts/smoke_api_live.py:8-9` (inventory C10). | High | owner rotates the password |
| W-11 | Low: Django admin shows the voucher OTP hash + salt (offline brute force of 6 digits); referral OTP model with no endpoint. | Low | — |

## Owner questions (all at once, per the batch rule)

1. **W-1 OTP delivery.** Proposal: the code is only ever sent to the customer by the server
   (WhatsApp Cloud API template); the staff response carries no code — no wa.me text, no QR of
   the code. If the Cloud API is off or the send fails, redemption stops with "couldn't send the
   code" (no manual fallback that reveals it). Alternative: keep a manual wa.me fallback **without**
   the code (opens a chat; the server still sends the code). Which?
2. **W-2 private vouchers.** Proposal: a private voucher's OTP goes only to its customer's phone
   on file (the phone field is ignored / must match); public vouchers keep any phone. OK?
3. **W-5 portal reorder.** Proposal: quantity 1…20 per line (configurable), at most 10 reorders
   per customer per day, and only items the customer bought before **or** a free-text request
   that staff review. Or allow any catalog item?
4. **W-9 HSTS.** Proposal: `SECURE_HSTS_SECONDS=31536000` (1 year), no `includeSubDomains` / no
   preload until every sub-domain is HTTPS, set in the production `.env` + runbook; CSP shipped
   **report-only** first. OK?
5. **W-10.** Remove the credential (read it from environment variables); **you rotate the admin
   password** — it stays in git history.

### Owner answers (2026-11-01)

1. **W-1:** server sends the code; staff get a chat link **without** the code (no QR). No send →
   the request fails and the code is cancelled. ⚠ Deploy prerequisite: production needs the
   WhatsApp Cloud API configured (`WHATSAPP_TOKEN` + phone id, or a WhatsApp channel account) and
   an approved `otp_delivery` authentication template — otherwise voucher redemption stops.
2. **W-2:** a private voucher's code goes only to its customer's phone on file (phone or
   alternate phone, compared on the last 10 digits).
3. **W-5:** quantity 1–20 per line, at most 10 reorders per customer per day, any catalog item.
4. **W-9:** HSTS starts at 1 day (`SECURE_HSTS_SECONDS=86400`), no sub-domains / preload; raised
   later. CSP report-only first.

## Order

W-1/W-2 (after answers) → W-3 → W-4 → W-5 → W-6 → W-7/W-8 → W-9 → W-10/W-11. Each: failing
test, diff, approval, apply, suites. Help updated for any screen that changes (voucher redeem
flow, portal).

## Done when

The holes above have green tests; `tracked_secrets` holds only reviewed non-secrets; a static
guard keeps every export going through the formula sanitiser; full suite green on a fresh DB.

## Status (2026-11-01)

| ID | State | Where |
|---|---|---|
| W-1 | **Held** (owner: wait until WhatsApp Cloud API + the approved `otp_delivery` template are live in production). Built: `scratch/batch6/w1/`; tests `test_platform_vouchers.OtpDeliveryTests` stay `@pending('W-1')`. | — |
| W-2 | Applied | `apps/vouchers/models.py` (`_same_phone`) |
| W-3 | Applied | `apps/notifications/chatter_access.py`, `consumers.py` |
| W-4 | Applied (a + b) | `core/export_safety.py`; guard `test_static_guards.test_exports_neutralise_formulas` + `baselines/unsafe_exports.txt` (KPI board, ISR fulfilment = reviewed real formulas) |
| W-5 | Applied | `apps/portal/models.py` (`PortalLogin`, migration `portal.0001`), tokens / auth / throttles / views, `WhatsAppSender.send_text(record_body=)` |
| W-6 | Applied | `core/safe_fetch.py`; `apps/pbx/recordings.fetch_recording`; image downloader |
| W-7 | Applied | `core/upload_safety.public_upload`; `core/media.SAFE_INLINE`; nginx public-media allow-list |
| W-8 | Applied | `core/upload_safety.UploadSizeLimitHandler` (`MAX_UPLOAD_FILE_SIZE` 25 MB), `capped_rows` (`MAX_IMPORT_ROWS` 50,000) |
| W-9 | Applied | `SECURE_HSTS_SECONDS=86400`; nginx `Content-Security-Policy-Report-Only`; `core/csp.py` → `/api/csp-report/` (log `elrezeiky.csp`) |
| W-10 | Applied — **owner: rotate that admin password on every server** (it stays in git history) | `scripts/smoke_api_live.py` reads `SMOKE_ADMIN_USER` / `SMOKE_ADMIN_PASS` |
| W-11 | Applied | `apps/vouchers/admin.py` hides `code_hash` / `otp_salt` |

Also fixed on the way: the role sweep's bearer clients now mint a fresh token per request
(a slow run outlived the 1 h token and hid verdicts behind 401s — `fixtures._BearerClient`), and
`test_replacement_entry_first` no longer assumes yesterday is in the same month.

Deploy: migrate (`portal.0001`); reload nginx (public-media allow-list, CSP report-only); portal
customers log in again once; LAN recording hosts must be the `PBX_RECORDINGS_URL_BASE` host;
`config/settings.py` + `deploy/nginx.conf` overlap PR #23 (simple merge). Known residue: `--keepdb`
test DBs are emptied by the TransactionTestCase files — verify on a fresh `TEST_DB_NAME`.
