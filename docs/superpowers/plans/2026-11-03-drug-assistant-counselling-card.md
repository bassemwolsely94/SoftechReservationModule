# Drug Assistant + Counselling Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship, dark behind three switches, three pieces: pharmacist-approved counselling sheets, a staff drug-assistant panel, and a staff-triggered WhatsApp counselling card with a private link page.

**Architecture:** One new Django app `apps/counselling` holds:
- the content (sheet, linked items, immutable versions)
- the assistant read endpoint, which only aggregates `catalog.safety`, `composition.alternatives` and the sheets
- card sends and opt-outs

The public card page lives under the existing anonymous surface `/api/public/`. The React side:
- extends the existing F7 `PosAlternatives` panel into the assistant (desktop + mobile)
- adds `/counselling` (review screen), a send drawer, and `/c/:token`

**Tech Stack:** Django 4.2 + DRF, PostgreSQL, React 18 + Vite + TanStack Query + Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-03-drug-assistant-counselling-card-design.md`

## Global Constraints

- Switches in `config/settings.py`, all `config('<NAME>', default=False, cast=bool)`: `DRUG_ASSISTANT_ENABLED`, `COUNSELLING_CONTENT_ENABLED`, `COUNSEL_CARD_SEND_ENABLED`.
  Plus `COUNSEL_CARD_DAILY_CAP` (int, default 200), `COUNSEL_CARD_TEMPLATE` (default `counsel_card`), `COUNSEL_CARD_LANGUAGE` (default `ar`), `COUNSEL_CARD_TOKEN_DAYS` (int, 90), `COUNSEL_CARD_DEDUPE_DAYS` (int, 7).
- No SOFTECH access of any kind (no `config/sybase.py` import in the app).
- RBAC module key `counselling`, label «إرشادات الاستخدام».
  - view: admin, pharmacist, salesperson, call_center, supervisor, quality_manager.
  - create/edit/approve: **pharmacist, admin only**. Supervisor is the call-center supervisor and gets no edit or approve.
- Sending a card and reading the assistant are POS actions: module `pos`, view for GET, create for POST.
- Customer-facing text = latest **approved** version only. Drafts are visible only to `counselling` edit holders.
- The WhatsApp template never contains an item name.
- Arabic RTL, calm UI, no modal on the common path. Never show a bare branch code (use `useBranchNames`). Every table sortable (`useSortableRows`).
- Molecule data: never read `Item.name_scientific`. Unverified matches are labelled «غير موثّق» and have no add action.
- Every content change, item link and send writes `AuditLog.log(...)` with a new action key.
- Tests: Django `TestCase` in `apps/tests/`, run with a unique DB:
  `TEST_DB_NAME=test_counselling_p4 ../../../venv/Scripts/python.exe manage.py test apps.tests.<module> --noinput`

## Review Focus

1. **A pharmacist edits an approved sheet; a customer opens an old link.** Expect the current approved version (or the withdrawn notice), never the draft. Test in Task 6 `test_page_shows_current_approved_not_draft`.
2. **A double tap on «إرسال».** Expect exactly one `CounselCardSend` and one WhatsApp call. Test in Task 5 `test_same_idempotency_key_sends_once`.
3. **Phone typed as `01xxxxxxxxx`, `+201…`, `201…`, or with spaces.** Expect one normalised number and one opt-out hash. Test in Task 5 `test_phone_formats_normalise_to_one_hash`.
4. **An item linked to a sheet is later archived or sale-stopped.** Expect the assistant to show the block flag first and the send drawer to still allow guidance (the customer already bought it). Test in Task 4 `test_blocked_item_flags_first`.
5. **A salesperson requests the assistant for an item whose only content is an AI draft.** Expect «لا يوجد إرشاد معتمد بعد» with no draft text in the JSON. Test in Task 4 `test_salesperson_never_sees_draft_text`.

---

### Task 1: App, models, switches, RBAC module, read helpers

**Files:**
- Create:
  - `apps/counselling/{__init__,apps,models,selectors,admin}.py`
  - `apps/counselling/migrations/0001_initial.py`
  - `apps/users/migrations/00NN_counselling_module.py` (next free number; data migration like `0042_tasks_module_incentives_owner.py`)
- Modify:
  - `config/settings.py` (INSTALLED_APPS + switches)
  - `apps/users/models.py` (`MODULE_CHOICES` add `('counselling', 'إرشادات الاستخدام')`)
  - `apps/users/management/commands/seed_permissions.py` (`ALL_MODULES` + per-role sets)
  - `apps/audit/models.py` (`ACTION_CHOICES` add `counselling_drafted`, `counselling_edited`, `counselling_submitted`, `counselling_approved`, `counselling_retired`, `counselling_item_linked`, `counselling_item_unlinked`, `counsel_card_sent`, `counsel_card_opt_out`), with a migration if choices are migrated
- Test: `apps/tests/test_counselling_content.py`

**Interfaces — Produces:**
- `CounsellingContent`:
  - Text fields, all `TextField(blank=True)`: `title`, `what_for_ar`, `how_to_use_ar`, `dose_ar`, `frequency_ar`, `duration_ar`, `warnings_ar`, `storage_ar`, `missed_dose_ar`, and the same eight with `_en`.
  - `frequency_code` (CharField 10, blank), `with_food` (choices before/after/any/'').
  - `status` (draft/pending_review/approved/retired, default draft), `source` (manual/ai_draft), `ai_model` (CharField blank).
  - `version` (int, 0 = never approved), `approved_version` FK→`CounsellingContentVersion` (null).
  - `created_by`/`updated_by`/`approved_by` FK StaffProfile (null), timestamps.
- `CounsellingContentItem(content FK, item OneToOne→catalog.Item, linked_by, linked_at)`.
- `CounsellingContentVersion(content FK, version int, data JSONField, approved_by, approved_at)`.
  - Immutable: `save()` raises if pk exists. `unique_together (content, version)`.
- `CONTENT_FIELDS: tuple[str, ...]`: the 16 text fields + `frequency_code` + `with_food` (the snapshot keys).
- `selectors.approved_content(item) -> dict | None`: `{**version.data, 'version': n, 'approved_at': iso, 'content_id': id}`.
  - Returns None when `COUNSELLING_CONTENT_ENABLED` is off, there is no link, or the sheet is not approved/retired-without-version.
  - A retired sheet → None.
- `selectors.approved_usage_text(item) -> str | None`: joins the non-empty `dose_ar`, `frequency_ar`, with_food label («قبل الأكل»/«بعد الأكل»/''), `how_to_use_ar` with « — ».
- `selectors.sheet_for(item) -> CounsellingContent | None`.

- [ ] **Step 1: Write failing tests**
  - `test_version_row_is_immutable`: create a version, then `save()` again → raises `ValueError`.
  - `test_helpers_none_when_switch_off`: `override_settings(COUNSELLING_CONTENT_ENABLED=False)` → `approved_content(item) is None`.
  - `test_helpers_read_approved_snapshot_not_live_fields`: approve with dose «قرص»; edit the live `dose_ar` to «قرصين» → `approved_content(item)['dose_ar'] == 'قرص'`.
  - `test_usage_text_joins_parts`: dose «قرص واحد», frequency «مرتين يومياً», with_food after, how_to_use '' → `'قرص واحد — مرتين يومياً — بعد الأكل'`.
  - `test_retired_sheet_returns_none`.
  - `test_counselling_module_seeded`: `RoleModuleAccess` rows exist for module `counselling`.
    - pharmacist approve=True, supervisor approve=False, salesperson edit=False, salesperson view=True.
- [ ] **Step 2: Run, expect failures** (import errors).
- [ ] **Step 3: Implement models + migration + selectors + switches + RBAC seed.**
  - The users data migration `get_or_create`s every role × action for `counselling`, with the sets in Global Constraints.
- [ ] **Step 4: Run** `apps.tests.test_counselling_content` and `apps.tests.security.test_rbac_matrix_seeding` → PASS.
- [ ] **Step 5: Commit** `feat(counselling): content models, switches, RBAC module, read helpers`.

### Task 2: Content workflow service + review API

**Files:**
- Create: `apps/counselling/{services,serializers,permissions,views,urls}.py`
- Modify:
  - `config/urls.py` (`path('api/counselling/', include('apps.counselling.urls'))`)
  - `core/middleware/module_access.py`: `MODULE_BY_PREFIX['counselling'] = 'counselling'`. Special-case `counselling/assistant` and `counselling/cards` → `pos`, like the composition/alternatives block. `counselling/content/<id>/approve` → `('approve',)`.
- Test: `apps/tests/test_counselling_content.py` (extend)

**Interfaces — Produces** (`services.py`; every function takes `actor: StaffProfile`, writes `AuditLog.log`, and runs in `transaction.atomic`):
- `create_sheet(actor, data: dict, item_ids: list[int], source='manual', ai_model='') -> CounsellingContent`.
  - Rejects an item already linked elsewhere with `ValidationError('الصنف مرتبط بإرشاد آخر')`.
- `edit_sheet(actor, content, data: dict) -> CounsellingContent`.
  - If `status in (approved, pending_review)`, set it back to `draft`. The `approved_version` stays the serving version.
- `submit(actor, content)`: draft → pending_review.
- `approve(actor, content) -> CounsellingContentVersion`.
  - Allowed from draft or pending_review: a pharmacist may approve their own text (spec).
  - Bumps `version`, writes the snapshot, sets `approved_version`, `status=approved`.
  - Refuses a sheet with empty `how_to_use_ar` and empty `dose_ar`: `ValidationError('أدخل طريقة الاستخدام أو الجرعة')`.
- `retire(actor, content, reason: str)`.
- `link_items(actor, content, item_ids)`, `unlink_item(actor, content, item_id)`.
- `suggest_items(content_or_item, limit=20) -> list[dict]`.
  - Trigram similarity on `Item.search_name` to the first linked item's name, same `shape_name`, active items not linked elsewhere.
  - Suggestions only; never links anything.
- `needs_content_queue(days=90, limit=200) -> list[dict]`: active items with no link, ranked by 90-day sold qty from `customers.PurchaseHistoryLine`.

**API** (`/api/counselling/`; viewset permission `HasCounsellingAccess(action)`, which checks `matrix_allows(profile, 'counselling', action)`):
- `GET status/` (any authenticated) → `{assistant, content, cards}` booleans from the switches.
- `content/` list/retrieve/create/update: `view` for GET, `edit` for writes. Filter `?status=`; sortable via `core.sort_ordering`. The list hides drafts' text for non-editors (a non-editor can't reach it anyway).
- `content/<id>/submit/`, `content/<id>/approve/` (approve), `content/<id>/retire/` (approve), `content/<id>/link/` + `content/<id>/unlink/` (edit), `content/<id>/suggest-items/` (edit), `content/<id>/versions/` (view).
- `content/needs/` (edit).
- When `COUNSELLING_CONTENT_ENABLED` is off, every `content/*` route returns 503 `{'detail': 'الميزة غير مفعّلة'}` (the commerce pattern).

- [ ] **Step 1: Failing tests**
  - `test_salesperson_cannot_create_or_approve` (403)
  - `test_supervisor_cannot_approve` (403)
  - `test_pharmacist_can_create_and_approve_own`
  - `test_edit_after_approve_reverts_to_draft_but_keeps_serving_version`: `approved_content` still returns v1; after the second approve, v2.
  - `test_item_cannot_join_two_sheets`
  - `test_approve_requires_usage_or_dose`
  - `test_every_change_audited`: AuditLog actions present for create/approve/link.
  - `test_content_routes_503_when_switch_off`
  - `test_suggest_items_never_links`
- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement services, serializers, views, urls, middleware mapping.**
- [ ] **Step 4: Run** the module tests + `apps.tests.security.test_static_guards` + `apps.tests.security.test_role_sweep`.
  - PASS. Update `baselines/` only if the guard lists a new item that is genuinely classified, and say why in the commit.
- [ ] **Step 5: Commit** `feat(counselling): sheet workflow, item linking, review API`.

### Task 3: AI draft (draft only)

**Files:**
- Create: `apps/counselling/ai_draft.py`
- Modify:
  - `apps/enrichment/ai_extractor.py`: add `complete_json(prompt: str) -> tuple[dict, str]`, which returns (parsed JSON, model name). It reuses the existing provider chain and limiters; refactor the shared provider loop rather than copying it.
  - `apps/counselling/views.py`: `POST content/ai-draft/ {item_id}` (edit).
  - `apps/counselling/management/commands/draft_counselling.py`: `--top N` over `needs_content_queue`, skipping items already linked.
- Test: `apps/tests/test_counselling_ai_draft.py`

**Interfaces — Produces:** `ai_draft.draft_for_item(actor, item) -> CounsellingContent`.
- It calls `complete_json` with a fixed Arabic prompt asking for the JSON keys `CONTENT_FIELDS` (Arabic only).
- It keeps only known keys, truncates each to 1,000 chars, and creates the sheet via `services.create_sheet(..., source='ai_draft', ai_model=model)`.
- **status is always draft.** No code path in this module calls `approve`.

- [ ] **Step 1: Failing tests** (provider mocked with `mock.patch('apps.enrichment.ai_extractor.complete_json')`)
  - `test_ai_draft_is_draft_with_source_and_model`
  - `test_ai_draft_unknown_keys_dropped`
  - `test_ai_draft_module_never_approves`: static check that `'approve('` is not in `ai_draft.py`'s source.
  - `test_ai_failure_raises_clean_error` (empty dict → `ValidationError('تعذّر إنشاء مسودة')`, no sheet)
  - `test_salesperson_cannot_ai_draft` (403)
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5: Commit** `feat(counselling): AI-drafted sheets (draft only, pharmacist approves)`.

### Task 4: Assistant endpoint + unverified alternatives

**Files:**
- Modify: `apps/composition/alternatives.py`
  - Add `unverified_alternatives_for(item_id, *, branch_id=None, limit=10) -> dict` `{'items': [...]}`.
  - Same molecule-set + `blocks_sale` + active rules as `alternatives_for`, over rows where **any** row is `source='parsed'`.
  - Excludes items that `alternatives_for` already returned.
  - Returns `[]` when the item has no index rows.
  - Rows have the same shape as `build()`, plus `'unverified': True`. Refactor the shared candidate/build code instead of copying it.
- Create: `apps/counselling/assistant.py` with `assistant_payload(item, *, branch_id, profile) -> dict`.
- Modify: `apps/counselling/views.py`: `GET assistant/<item_id>/?branch=` (pos view, `core/branch_scope` validates `branch`). 404 when `DRUG_ASSISTANT_ENABLED` is off.
- Test: `apps/tests/test_counselling_assistant.py`

**Payload keys, in this order:**
- `safety`: `item_safety_flags(item)`; `blocked`: bool
- `identity`: name, name_ar, form = `shape_name_ar or shape_name`, indication = `effect_name_ar or effect_name`, `requires_fridge`, `medicine_type`, pack_price
- `molecules`: `[{molecule, strength, dosage_form, verified: bool}]` from `ItemMoleculeIndex`
- `alternatives`: `alternatives_for(...)` output
- `suggestions`: `unverified_alternatives_for(...)['items']`
- `guidance`: `{'status': 'approved'|'draft'|'none', 'content': dict|None, 'can_edit': bool}`
  - Approved → `approved_content`.
  - Draft content only when the profile has counselling edit; otherwise status `none`, content None.

- [ ] **Step 1: Failing tests**
  - `test_assistant_404_when_switch_off`
  - `test_blocked_item_flags_first` (Review Focus 4: `blocked` True, `safety[0]['severity']=='block'`)
  - `test_verified_and_unverified_split`: approved pair in `alternatives`, parsed pair in `suggestions` with `unverified` True.
  - `test_unverified_excludes_blocked_items`
  - `test_never_reads_name_scientific`: two items with identical `name_scientific` and no index rows → no suggestions.
  - `test_salesperson_never_sees_draft_text` (Review Focus 5)
  - `test_pharmacist_sees_draft_marked`
  - `test_branch_outside_scope_refused` (403 for a branch-scoped salesperson asking another branch)
  - `test_existing_pos_alternatives_unchanged`: run the existing composition alternatives tests.
- [ ] **Step 2–4:** fail → implement → pass. Also run `apps.tests.test_ingredient_composition` and the composition alternatives tests.
- [ ] **Step 5: Commit** `feat(counselling): staff drug assistant endpoint + unverified suggestions`.

### Task 5: Counselling card send

**Files:**
- Modify:
  - `apps/counselling/models.py` + migration:
    - `CounselCardSend`: customer FK null, phone_masked, phone_hash (db_index), branch FK, sent_by FK, source (pos/customer360/assistant), status (queued/sent/failed/blocked_optout), fail_reason, idempotency_key (unique), resend bool, wa_message FK null, first_opened_at, created_at.
    - `CounselCardItem(send FK, item FK, content FK, version FK)`.
    - `CounselCardOptOut(customer FK null, phone_hash db_index, source, created_at)`.
  - `apps/whatsapp/sender.py`: `send_template(..., url_button_params: list[str] | None = None)` adds `{'type':'button','sub_type':'url','index':str(i),'parameters':[{'type':'text','text':p}]}` after the quick replies. Existing callers are unchanged.
- Create: `apps/counselling/cards.py`
- Modify: `apps/counselling/views.py`: `POST cards/preview/` and `POST cards/send/` (pos create); `GET cards/?customer=` (pos view) for the history.
- Test: `apps/tests/test_counselling_cards.py`

**Interfaces — Produces** (`cards.py`):
- `normalise_phone(raw) -> str | None`: Egyptian mobile → `2010xxxxxxxx` (12 digits), else None. Reuse an existing normaliser if `apps/pic_analytics` or `followups.refill_reminders.phone_for` has one; do not write a second one.
- `phone_hash(phone) -> str`: HMAC-SHA256 with `SECRET_KEY`, hex.
- `plan_card(*, customer, phone, item_ids, actor) -> dict`: `{'phone': masked, 'lines': [{item_id, name, has_guidance, recently_sent}], 'blocked_reason': ''|'opted_out'|'bad_phone', 'message_preview': str, 'page_preview': [approved_content…]}`. It never writes.
- `send_card(*, customer, phone, item_ids, actor, branch, source, idempotency_key, resend=False, sender=None) -> CounselCardSend`.

**Rules (send_card):**
- Raises `ValidationError('الإرسال غير مفعّل')` when `COUNSEL_CARD_SEND_ENABLED` is off, before any write.
- Same idempotency_key → returns the existing row, no second call.
- Opt-out by customer or phone hash → row with `blocked_optout`, no call.
- Only items with `approved_content`; none → `ValidationError('لا يوجد إرشاد معتمد للأصناف المختارة')`.
- Items sent to the same phone_hash within `COUNSEL_CARD_DEDUPE_DAYS` are dropped unless `resend`.
- Branch daily cap (Cairo day) → `ValidationError('تم بلوغ الحد اليومي')`.
- **Message:**
  - If the 24-h window is open (`WAConversation.window_open` for that wa_id), `send_text` with «مرحباً {first}، إرشادات استخدام مشترياتك من صيدليات الرزيقي: {url}».
  - Otherwise `send_template(template, language, variables=[first name], url_button_params=[token])`.
  - If `WATemplate` with that name is not `approved`, status `failed`, reason `template_not_approved`.
- Token = `signing.dumps({'s': send.pk}, salt='counsel-card')`. URL = `settings.PUBLIC_BASE_URL + '/c/' + token`. Use the existing setting that the delivery track link uses.
- On success: `AuditLog.log('counsel_card_sent', ...)` and `omni.services.emit('counsel_card_sent', send, customer=..., phone=..., summary='أُرسلت إرشادات الاستخدام', actor=..., attach_only=False)`.

- [ ] **Step 1: Failing tests** (FakeSender like `test_refill_reminders.py`)
  - `test_nothing_stored_or_sent_when_switch_off`
  - `test_same_idempotency_key_sends_once` (Review Focus 2)
  - `test_phone_formats_normalise_to_one_hash` (Review Focus 3: `01012345678`, `+201012345678`, `201012345678`, `010 1234 5678` → one hash)
  - `test_opted_out_phone_blocked`
  - `test_only_approved_versions_pinned`
  - `test_recent_item_skipped_unless_resend`
  - `test_daily_cap`
  - `test_template_has_no_item_name`: no item name appears anywhere in the FakeSender call kwargs.
  - `test_template_not_approved_marks_failed`
  - `test_audit_and_timeline_written`
  - `test_salesperson_can_send`, `test_delivery_role_cannot_send` (pos matrix)
  - `test_preview_never_writes`
  - `test_sender_url_button_component_shape`
- [ ] **Step 2–4:** fail → implement → pass. Also run `apps.tests.test_refill_reminders` (sender change).
- [ ] **Step 5: Commit** `feat(counselling): staff-sent WhatsApp counselling card with audit + opt-out`.

### Task 6: Public card page API

**Files:**
- Create: `apps/counselling/public_views.py` with:
  - `counsel_card_public(request, token)` (GET)
  - `counsel_card_opt_out(request, token)` (POST)
  - Both `authentication_classes([])`, `AllowAny`, `PublicCounselThrottle(AnonRateThrottle)` rate `600/hour`.
- Modify:
  - `apps/access/public_urls.py`: `counsel/<str:token>/`, `counsel/<str:token>/opt-out/`
  - `apps/tests/security/routes.py`: `KNOWN_PUBLIC_VIEWS` add both, with a comment
  - `docs/architecture/04_API_REGISTRY.md`: public rows
  - `apps/portal/views.py` `orders`: add `counsel_cards: [{created_at, item_count, token}]` for the logged-in customer (last 20 sent). Test `test_portal_orders_lists_counsel_cards`.
- Test: `apps/tests/test_counselling_public.py`

**Behaviour:**
- `signing.loads(token, salt='counsel-card', max_age=COUNSEL_CARD_TOKEN_DAYS*86400)`. A bad, expired or junk token → 404 «الرابط غير صالح أو منتهي الصلاحية», never 500.
- The response contains `first_name`, `branch_name` and the branch phone. Per line it contains `name` plus:
  - pinned version data when the sheet's current `approved_version` is the pinned one
  - otherwise the current approved data with `updated: true`
  - or `withdrawn: true` with no text when retired or unlinked
- Footer text is fixed in the frontend.
- It sets `first_opened_at` once.
- No phone, customer id, staff name or price in the response.
- Opt-out creates a `CounselCardOptOut` (customer + phone_hash) once, audits it, and returns 200 both times.

- [ ] **Step 1: Failing tests**
  - `test_valid_token_shows_cards`
  - `test_tampered_and_expired_404`
  - `test_junk_token_404_not_500`
  - `test_page_shows_current_approved_not_draft` (Review Focus 1)
  - `test_retired_shows_withdrawn_without_text`
  - `test_no_personal_data_leaked` (assert the keys)
  - `test_opt_out_idempotent_and_blocks_next_send`
  - `test_staff_cookie_not_required`
- [ ] **Step 2–4:** fail → implement → pass. Also run `apps.tests.security.test_access_public_gate`, `test_public_portal_track`, `test_static_guards`.
- [ ] **Step 5: Commit** `feat(counselling): public tokenised counselling card page + opt-out`.

### Task 7: Frontend

**Files:**
- Modify `frontend/src/api/client.js`: add `counsellingApi`:
  - `status()`, `list(params)`, `get(id)`, `create(d)`, `update(id,d)`, `submit(id)`, `approve(id)`, `retire(id,reason)`
  - `link(id,ids)`, `unlink(id,itemId)`, `suggest(id)`, `needs()`, `aiDraft(itemId)`
  - `assistant(itemId,branch)`, `previewCard(d)`, `sendCard(d)`, `cards(customerId)`
  - public: `publicCard(token)`, `optOut(token)`
- Create `frontend/src/counselling/useCounsellingStatus.js`: `useQuery(['counselling-status'])`, staleTime 5 min.
- Create `frontend/src/counselling/DrugAssistantBody.jsx`, sections in payload order:
  - a block banner at the top when `blocked`
  - verified alternatives reuse `Card` from `PosAlternatives` (export it) with `onPick`
  - suggestions in an amber box titled «اقتراحات غير موثّقة — تأكد من العبوة والتركيز», with `Card` and no `onPick`
  - guidance block; draft shows the «مسودة غير معتمدة» badge
  - «أبلغ عن خطأ» opens `/composition?item=<id>` in a new tab
- Modify `frontend/src/pos/search/PosAlternatives.jsx`: when `status.assistant`, render `DrugAssistantBody` (title «معلومات وبدائل»); otherwise the current body unchanged. Desktop and mobile `sheet` both go through this.
- Create `frontend/src/counselling/SendCardDrawer.jsx`: inline side drawer.
  - Lines pre-ticked when `has_guidance`, greyed otherwise; editable phone; «إعادة الإرسال» checkbox shown only when a line is `recently_sent`.
  - Preview from `previewCard`; send with `idempotency_key = crypto.randomUUID()` made once per drawer open.
  - When `!status.cards`, the button reads «معاينة فقط — الإرسال غير مفعّل».
- Mount points:
  - `POSOrderPage.jsx`: a button «إرسال إرشادات الاستخدام» in the order footer when `status.cards || status.content` and the order has a customer and lines.
  - `pages/mobile/MobilePOSOrderPage.jsx`: the same.
  - `CustomerDetailPage.jsx` `PurchasesTab`: per invoice row an action opening the drawer with that invoice's item ids.
- `CommandPalette.jsx`: for an item result, a secondary action «معلومات» (Shift+Enter) that opens a side drawer with `DrugAssistantBody`, when `status.assistant`.
- `pages/mobile/MobileItemsPage.jsx`: an «ℹ️ معلومات» row action → bottom sheet with `DrugAssistantBody`.
- `ProductDetailPage.jsx`: a `DrugAssistantBody` section when `status.assistant`.
- Create `frontend/src/pages/CounsellingPage.jsx`, route `/counselling`:
  - tabs يحتاج محتوى / مسودات / بانتظار الاعتماد / معتمد / مسحوب; `useHelpTab(tab)`
  - grid with `useGridKeyboard` + `useSortableRows`
  - editor side panel: fields, linked items with suggestions to tick, «مسودة آلية — يجب مراجعة صيدلي» banner for `ai_draft`, buttons حفظ / إرسال للاعتماد / اعتماد / سحب
  - nav entry gated by the `counselling` view permission + `status.content`
- Create `frontend/src/pages/CounselCardPublicPage.jsx`, route `/c/:token` next to `/track/:token` (public, outside the auth layout):
  - cards, «تم تحديث هذه الإرشادات», «تم سحب هذه الإرشادات — راجع الصيدلي»
  - footer «هذه الإرشادات عامة؛ اتبع تعليمات طبيبك أو الصيدلي» + branch phone
  - opt-out link «إيقاف رسائل الإرشادات»
- `data-tour` anchors on every new button referenced by help (Task 8).

- [ ] **Step 1:** Implement.
- [ ] **Step 2:** `cd frontend && npm run build`; the build succeeds with no new warnings from these files. Run `npm run lint` if the script exists.
- [ ] **Step 3:** Preview check (dev server via preview_start with the switches on in local `.env`):
  - F7 panel on a POS row shows the assistant
  - `/counselling` loads
  - the send drawer previews
  - `/c/<token>` from a test send renders
  - Screenshot proof.
- [ ] **Step 4: Commit** `feat(counselling): assistant panel, review screen, send drawer, public card page`.

### Task 8: Help, docs, full verification

**Files:**
- Create `apps/help/content/counselling.py`:
  - `MODULE` with a brief, a workflow `model: 'counselling.CounsellingContent', field: 'status'` covering all four statuses, and a second workflow for `CounselCardSend.status`
  - `SCREENS`: `counselling.review` (`/counselling`, tabs matching the page's keys) and `counselling.public` (`/c/:token`)
  - The assistant panel and send drawer are covered as steps/tips in `pos.py` and `customers.py`.
  - AR + EN. Register it in `content/__init__.py` `MODULE_FILES`.
- Modify `apps/help/content/pos.py` (F7 now «معلومات وبدائل»; the send button) and `apps/help/content/customers.py` (purchases send action); bump `updated` on each touched screen.
- Create `docs/architecture/34_DRUG_ASSISTANT_COUNSELLING.md`: what / switches / rules / code / tests, in doc-26 style.
- Modify `docs/architecture/11_ERP_INDEX.md` (row 34 + API + UI rows).
- Update the shared note `project4-counselling-content-contract.md`: status BUILT, helper names confirmed.

- [ ] **Step 1:** Write the help and docs.
- [ ] **Step 2:** Run `apps.tests.test_help` → PASS.
- [ ] **Step 3:** Full run: `TEST_DB_NAME=test_counselling_p4 python manage.py test apps.tests --noinput --parallel 1`, in the background. Note failures; compare any failure against `main` before claiming it is pre-existing.
- [ ] **Step 4:** `python manage.py makemigrations --check --dry-run` → no changes.
- [ ] **Step 5: Commit** `docs(counselling): in-app help, architecture doc 34, index`.
