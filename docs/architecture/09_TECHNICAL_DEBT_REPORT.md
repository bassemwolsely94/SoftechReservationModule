# 09 — Technical Debt Report

Identified issues organized by severity.

---

## CRITICAL

---

### TD-C001: No Role-Based UI Action Guards

**Status: ✅ RESOLVED 2026-06-05**

**What was built:**
- Backend: `GET /api/users/my-permissions/` — returns `{role, permissions: {module: {action: bool}}}` for current user
- Frontend: `src/store/permissionStore.js` — Zustand store; loads once after login, resets on logout
- Frontend: `src/hooks/usePermission.js` — `usePermission(module, action)` and `usePermissions(module)` hooks
- Frontend: `src/components/CanDo.jsx` — `<CanDo module action fallback>` guard component
- Applied to: ReservationsKanban ("حجز جديد"), TransfersPage ("طلب تحويل جديد"), DemandPage ("تسجيل طلب جديد"), VouchersPage ("قسيمة جديدة"), StockCountPage ("جلسة جديدة")
- `App.jsx` calls `loadPerms()` on auth change

**Remaining:** Apply `CanDo` to edit/delete buttons inside detail pages as each is touched.

---

### TD-C002: ERP Write Operations Are Manual

**Area:** Transfers, Reservations  
**Description:** Both transfer and reservation fulfillment require staff to MANUALLY enter data into SOFTECH. The system has no way to verify if the ERP entry was actually made (it relies on post-hoc ERP match). A completed transfer in this system doesn't guarantee the ERP transaction happened.  
**Impact:** Data integrity between this platform and SOFTECH depends entirely on staff discipline  
**Fix:** Implement mandatory ERP match verification before allowing "completed" status; escalate to supervisor if unmatched after N days

---

### TD-C003: No Automated SLA Escalation

**Status: ✅ RESOLVED 2026-06-21**

**Area:** Demand module  
**Was:** `sla_breached` was a computed property with no push — breaches were only visible on manual review. No notification was sent.

**What was built:**
- `apps/demand/service.escalate_breached_demand_sla()` — escalates two tiers from `DemandRecord.SLA_MINUTES`: `new` unassigned > 10 min, and `assigned` stalled > 20 min. Tiered recipients: `new` → call-center + supervisors/admins + branch supervisor; `assigned` → the assignee + supervisors/admins. Re-escalates at most once per `demand_sla_repeat_minutes` (config, default 60) per record+tier via `Notification.dedup_key` (`demand_sla:{id}:{tier}`). Writes a `DemandLog.system` audit line per fire.
- New notification type `demand_sla_breach` (migration `notifications/0026`) — mapped to the demand module feed but added to `ALARM_HIGH_TYPES` so it fires the audible/visual alarm (same pattern as mentions). Deep-links to `/m/demand/{id}` via `Notification.push_url`.
- Scheduler job `demand_sla_escalation` (hourly) in `apps/sync/tasks.py` (`_demand_sla_escalation`), beside the recovery-escalation job.
- Management command `python manage.py check_demand_sla` for manual / cron runs.
- Tests: `apps/tests/test_demand_sla.py` — new-tier, assigned-tier, within-SLA no-op, idempotent within window.

**Note on cadence:** chosen interval is **hourly** (consistent with the transfer/approval SLA jobs and pairs with the once-per-hour repeat policy). Because the `new` window is 10 min, first-alert lag can be up to ~1h; tightening is a one-line `add_job` interval change if needed. Other SLA escalations already shipped: transfer (`check_transfer_sla`), approval (`escalate_overdue_approvals`), delivery (`delivery_sla_alerts`), demand recovery (`demand_recovery_escalation`).

---

### TD-C004: `followups` App Unclear Relationship to `demand.FollowUpTask`

**Area:** apps/followups vs apps/demand  
**Description:** `apps/followups` has 7 migrations and its own views/serializers/urls, but it's unclear whether it has its own model or delegates to `demand.FollowUpTask`. This creates ambiguity about the authoritative follow-up tracking system.  
**Impact:** Developers don't know which app to extend for follow-up features  
**Fix:** Audit `apps/followups/models.py`; consolidate to one app

---

## HIGH

---

### TD-H001: ChatterMessage Missing Voice Note Support

**Status: ✅ RESOLVED 2026-06-05**

**What was built:**
- Model already had `attachment` (FileField) + `file_type` choices (`voice`, `image`, `doc`) — no migration needed
- `ChatterMessageSerializer`: added `attachment`, `attachment_url` (absolute URL), `file_type` fields
- `chatter_post` view: now accepts `multipart/form-data`; auto-detects `file_type` from MIME; allows voice-only (no text required); validates content type + 20 MB size limit
- `notificationsApi.chatterPostWithFile()` added to API client
- `useChatterSocket`: added `postMessageWithAttachment()` REST method
- `ChatterBox.jsx`: integrated `VoiceNoteRecorder`, renders audio player / image / doc in `MessageBubble`, toggleable mic button in input bar

**Parity upgrade 2026-06-21 — dedicated `voice_note` field:**
The 2026-06-05 fix routed voice through the single multi-purpose `attachment` field
(`file_type='voice'`), so a message could carry *either* an image *or* a voice note.
To reach full parity with `reservations.ReservationActivity` and
`transfers.TransferRequestMessage` (which keep a voice note beside an image),
`ChatterMessage` now has a dedicated `voice_note` FileField:
- Model: `voice_note` (migration `notifications/0025_chattermessage_voice_note`); `attachment` stays for image/doc.
- `chatter_post` view: accepts a separate `voice_note` upload, audio-only validation via `_validate_chatter_file` + `_ALLOWED_AUDIO_TYPES`. `attachment` keeps legacy audio→`file_type='voice'` for backward compat.
- `ChatterMessageSerializer`: added `voice_note` + `voice_note_url`.
- API client `chatterPostWithFile(…, { attachment, voiceNote })` + hook `postMessageWithAttachment(text, { attachment, voiceNote })`.
- `ChatterBox.jsx`: separate paperclip (image/doc) + mic (voice) controls; `MessageBubble` renders `attachment` and `voice_note_url` together.
- Tests: `apps/tests/test_notifications.py::ChatterPostTests` — voice-only, image+voice-together, non-audio-rejected.

---

### TD-H002: ERP Match Loose References (not FK)

**Area:** notifications_notification, reservations_reservationactivity  
**Description:** `transfer_request_id_ref`, `demand_id_ref`, `chatter_message_id_ref` are plain integers, not ForeignKeys. This means:
- No referential integrity
- No `select_related()` optimization
- Stale references if records are deleted

**Fix:** Gradually migrate to proper FKs with `null=True, on_delete=SET_NULL`

---

### TD-H003: Missing Pagination on Several API Endpoints

**Area:** Multiple API views  
**Description:** Some views (analytics, dashboard) return unpaginated querysets. With 40,000 customers and 37,500 items, this can cause memory/timeout issues.  
**Fix:** Enforce `CursorPagination` or `PageNumberPagination` on ALL list endpoints

---

### TD-H004: `catalog_itemstock` Sync Frequency Unknown

**Area:** Sync / Catalog  
**Description:** `ItemStock.quantity_on_hand` is synced from SOFTECH, but the sync interval is not documented. If sync runs daily, stock levels shown in the UI could be 24 hours stale — causing incorrect transfer approvals.  
**Fix:** Document sync interval; consider real-time stock lookup for critical decisions (transfer approval)

---

### TD-H005: No Error Boundaries on React Detail Pages

**Area:** Frontend  
**Description:** Detail pages (ReservationDetailPage, TransferDetailPage, etc.) have no React error boundary. An API error or malformed data will crash the entire screen.  
**Fix:** Wrap all detail page routers in `<ErrorBoundary>` components with graceful fallback UI

---

### TD-H006: `purchasing_salestransactionline` Scope Unknown

**Area:** apps/purchasing  
**Description:** This table caches 365 days of SOFTECH stktrans. Its exact schema, sync strategy, and update cadence are not fully documented. The demand engine depends on it.  
**Impact:** If the table is stale, purchasing recommendations are wrong  
**Fix:** Add sync timestamp + staleness check to engine config; warn if data > 24 hours old

---

### TD-H007: VoucherOTP `hmac.new` Bug

**Area:** apps/vouchers/models.py line 325  
**Description:** `hmac.new(...)` should be `hmac.new(...)` — this is `hmac.new` but the Python stdlib function is `hmac.new`. Actually the correct call is `hmac.new(key, msg, digestmod)`. This needs verification — the current code may throw `AttributeError: module 'hmac' has no attribute 'new'` (it should be `hmac.new` but Python's `hmac` module uses `hmac.new()` correctly). **Verify in runtime.**  
**Fix:** Test OTP generation; correct to `hmac.new(salt.encode(), plain.encode(), hashlib.sha256).hexdigest()` if broken

---

## MEDIUM

---

### TD-M001: Finance Module is Scaffolded, Not Functional

**Area:** apps/finance, FinanceHubPage  
**Description:** Finance module has 4 migrations and 6 UI tabs but the backend reads external data sources without clear schema. P&L, cash flow, and expense analytics are not connected to real data.  
**Impact:** Feature appears complete but returns empty/mock data  
**Fix:** Define data source clearly; either connect to SOFTECH financial tables or mark as "coming soon" in UI

---

### TD-M002: Analytics Module Partially Wired

**Area:** apps/analytics, SalesDashboard, PerformanceDashboard  
**Description:** Analytics tabs exist but several charts/metrics are not connected to real queries.  
**Fix:** Audit each analytics endpoint; implement missing aggregation queries

---

### TD-M003: Delivery and Payment Screens are Stubs

**Area:** DeliveryDashboard, PaymentTracking  
**Description:** These screens exist in the router but appear to be placeholder implementations.  
**Fix:** Either implement or remove from nav; do not leave stubs visible to users

---

### TD-M004: No Offline/WebSocket Reconnection Indicator

**Area:** Frontend — WebSocket hooks  
**Description:** When the WebSocket disconnects (network issue, server restart), the UI shows no indication. Users continue working without knowing notifications have stopped.  
**Fix:** Add connection status indicator in navbar; show "reconnecting..." banner on disconnect

---

### TD-M005: Incentive `category_code` Field is Informational Only

**Area:** apps/incentives — IncentiveRule  
**Description:** `category_code` is documented as "informational only — not applied in engine." This creates confusion since users may assume it filters transactions by category.  
**Fix:** Add UI tooltip explaining this; or remove from create form to prevent misuse

---

### TD-M006: `applicable_items` M2M on Voucher Not Enforced at POS

**Status: ✅ RESOLVED 2026-06-21**

**Was:** `Voucher.applicable_items` defined which items qualify, but eligibility never looked at the cart — the discount applied regardless of which items were in the order. (`applicable_branches`/`branch` were likewise unenforced, and neither was even settable via the API.)

**What was built (eligibility-gate model — a gate, like `min_order_value`, not a reprice):**
- `Voucher.check_items_eligibility(item_ids)` — empty `applicable_items` ⇒ unrestricted; when restricted, the redemption MUST supply item ids and at least one must qualify, else **reject** (no silent bypass). Bundled `Voucher.check_branch_eligibility(branch)` (over `applicable_branches` ∪ `branch`) and a `check_full_eligibility(phone, item_ids, branch)` orchestrator.
- Wired into `validate` / `generate-otp` / `verify-otp`. The gate runs in `verify-otp` **before the OTP is consumed**, so an ineligible attempt never burns the customer's code. Branch is taken from the redeeming employee's `StaffProfile.branch`.
- `item_ids` added to the three action serializers. `applicable_items`/`applicable_branches` are now **exposed** on the list serializer (`applicable_items_detail` for the UI) and **accepted** on the create serializer (previously admin-only). Viewset prefetches both (no N+1).
- Frontend: redeem flows (desktop `RedemptionFlow` + `MobileVoucherRedeemPage`) show the eligible items and require ≥1 selection, sending `item_ids`; the create modal gained an `applicable_items` picker (ItemSearchWidget chips) + `applicable_branches` checkboxes.
- Tests: `apps/tests/test_voucher_eligibility.py` (model unit + view gate + branch gate + "ineligible verify preserves OTP").

**Note:** this is an eligibility GATE — the discount still applies to `order_amount` (the POS handles final per-line pricing). Scoped per-line discounting was considered and deliberately not adopted (would require per-line amounts and change the discount semantics).

---

### TD-M007: Missing `UNIQUE` Constraints on Demand Number

**Area:** apps/demand — DemandRecord  
**Description:** `demand_number` has `unique=True` but the generation logic may have race conditions under high concurrency.  
**Fix:** Use database sequence (like transfers use) instead of application-level generation

---

## LOW

---

### TD-L001: `ChatterMessage.model_name` is a Raw String

**Area:** apps/notifications — ChatterMessage  
**Description:** Generic FK uses string `model_name` + integer `record_id`. This is not a proper Django `ContentType` generic FK, so Django admin, prefetch, and reverse lookups don't work.  
**Fix:** Migrate to `django.contrib.contenttypes.fields.GenericForeignKey`

---

### TD-L002: `WhatsApp URL` Hardcoded in VoucherOTP

**Area:** apps/vouchers/models.py  
**Description:** WhatsApp URL format (`wa.me/{phone}`) is hardcoded. Phone normalization logic (strip leading zeros, add `20`) is also in the model.  
**Fix:** Move to a utility function `format_whatsapp_url(phone, message)` shared by vouchers and notifications

---

### TD-L003: No Automated Tests

**Area:** Entire project  
**Description:** No test files found. Zero test coverage for business-critical logic including OTP verification, incentive calculations, and ERP match.  
**Impact:** Regressions are invisible; confidence in changes is low  
**Fix:** Start with unit tests for: `VoucherOTP.verify()`, `IncentiveEngine.calculate()`, `Reservation` status transitions

---

### TD-L004: README is a Placeholder

**Area:** Project root README.md  
**Description:** README contains only 56 bytes (placeholder text). No setup instructions, no environment requirements, no deployment guide.  
**Fix:** Write README with: setup steps, .env variables, management commands, deployment notes

---

### TD-L005: `category_code` on IncentiveRule Not Indexed

**Area:** apps/incentives  
**Description:** `category_code` is queried in engine runs but has no database index.  
**Fix:** Add `db_index=True` to `IncentiveRule.category_code`

---

### TD-L006: Soft Delete Without Queryset Manager

**Area:** ReservationActivity, TransferRequestMessage  
**Description:** `is_deleted` soft-delete pattern used, but no custom manager filters deleted records by default. API must manually filter `is_deleted=False` in every query.  
**Fix:** Add `SoftDeleteManager` as default manager

---

### TD-L007: `VendorItemMapping.use_count` Not Automatically Incremented

**Area:** apps/invoices  
**Description:** `use_count` is supposed to increment when a match is confirmed, building the learning table. If this isn't wired in the confirm endpoint, the learning table never learns.  
**Fix:** Verify confirm endpoint increments `use_count`; add if missing

---

## OBSOLETE / DEAD CODE CANDIDATES

| Item | Location | Reason |
|------|----------|--------|
| `fix.py`, `fix_migrations.py`, `fix_transfer_numbers.py` | Root | One-off fix scripts; should be removed or moved to `scripts/` |
| `_smoke_followup.py` | Root or tests | Test script; should be in tests/ or removed |
| `diagnose.py` | Root | Diagnostic utility; should be in `scripts/` |
| `IncentiveRule.incentive_type = 'fixed'` | apps/incentives | Marked as "backward-compat alias"; if unused, remove |
