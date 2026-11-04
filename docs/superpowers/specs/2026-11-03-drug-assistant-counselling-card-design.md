# Project 4 — Staff Drug Assistant + WhatsApp Counselling Card (design)

**Status:** DRAFT for owner approval — 2026-11-03
**Ships dark:** both switches default OFF; nothing here blocks the VPS go-live.
**SOFTECH:** read-only. No SOFTECH write of any kind.

## 1. Why

Counter staff need one calm place to answer "what is this, is it safe to sell, what else do we have, how
is it used" without leaving the POS. Customers leave the counter with no written instructions; a short,
pharmacist-approved "how to use" card on WhatsApp improves adherence and trust.

Safety constraints (CLAUDE.md rules 4, 5, 10) shape everything:

- SOFTECH molecule data is dirty. Today only **7 items** have pharmacist-approved molecules
  (`composition.ItemMoleculeIndex.source='approved'`); **13,182** have parsed, unverified molecules.
- There is **no approved clinical text** anywhere: `product_experience.ProductContent` has 9 rows, 0 with
  usage text, and no approval status. `enrichment.ItemEnrichment` has 38,287 AI rows, 0 published, and its
  suggestion generator auto-approves clinical fields at ≥0.90 confidence. It is NOT used as a customer
  source by this project. That auto-approval is reported as a separate follow-up and is not changed here.
- An LLM never decides clinical content. AI may only pre-fill a **draft** that a pharmacist edits and approves.

## 2. Owner decisions (2026-11-03)

| Question | Decision |
|---|---|
| Content source | **Both**: AI drafts for a pharmacist to approve, **and** pharmacists may write by hand. |
| Approve / send | **Pharmacist approves** content; **any POS staff** may send an already-approved card. |
| Which customers | **Staff choose per sale.** No automatic sending at launch. |
| Card format | WhatsApp template **without the medicine name** + link to a **private page** showing the cards. |
| Grouping | **Write once, pharmacist ticks the items** that share the sheet (pack sizes / brand codes). |

## 3. Goals / non-goals / anti-goals

**Goals**
- G1: a staff drug assistant panel reachable from POS search (desktop + mobile), Ctrl+K and `/m/items`.
- G2: one curated, versioned, pharmacist-approved counselling record per item, shared with Project 5
  (dosage label printer). Curate once, use in both places.
- G3: a staff-triggered WhatsApp counselling card with a full audit trail.

**Non-goals (this project)**
- Automatic sends after every sale or first purchase (possible later behind its own switch).
- Drug–drug interaction checking against the basket (the 40 seeded interactions are too thin; later).
- Writing molecules back to SOFTECH (Track B, separate and gated).
- Fixing the enrichment auto-approval (separate follow-up).

**Anti-goals: these would be failures even if the feature "works"**
- Any unverified molecule match presented as a safe substitute, or a one-click swap from an unverified match.
- Any customer-facing clinical text that a pharmacist did not approve, including text edited after approval
  without re-approval.
- A sales suggestion shown above, or instead of, a blocking safety flag.
- A popup or modal on the common POS path.

## 4. Part A — Curated counselling content

**New app `apps/counselling`.** `ProductContent` stays as marketing/catalog content. It has no approval and
is writable by purchasing, so it is not extended for clinical text.

**Grouping (owner decision 2026-11-03): write once, the pharmacist ticks the items.**
`CounsellingContent` is one instruction sheet. `CounsellingContentItem` links it to `catalog.Item`.
- `item` is unique, so an item belongs to at most one sheet.
- The pharmacist picks which items share a sheet. The screen *suggests* items with similar names, the same
  `shape_name` and the same manufacturer, by trigram similarity on `search_name`.
- Nothing is ever linked automatically, and molecule data is never used to link.
- Linking or unlinking an item is audited.
- Adding an item to an already-approved sheet takes effect at once (that is the pharmacist's act).
- Only pharmacists/admin may link or unlink.

`CounsellingContent` fields:
- Arabic fields (English optional, same names `_en`):
  - `what_for_ar`: plain-language indication
  - `how_to_use_ar`: route and technique, e.g. shake, before or after food
  - `dose_ar`: usual dose text; the label printer may pre-fill it per sale
  - `frequency_ar`
  - `duration_ar`
  - `warnings_ar`: when to stop or see a doctor, pregnancy, driving
  - `storage_ar`
  - `missed_dose_ar`
- Structured hints Project 5 can print: `frequency_code` (e.g. `1x1`, `1x2`, `1x3`, `prn`), `with_food` (before/after/any).
- `status`: draft → pending_review → approved; or → retired.
  - Any edit to an approved record creates a new draft version. The approved version keeps serving until
    the new one is approved.
- `source`: manual | ai_draft. The AI model name and prompt version are kept on the draft.
- `approved_by` / `approved_at`, `version` (int), `updated_by` / `updated_at`.

`CounsellingContentVersion` is an immutable snapshot written at each approval. A card send points to the
exact version it sent.

**AI draft:** an action on the item, plus an optional batch over the top-N sold items without content.
- It reuses the existing Gemini/OpenAI client in `apps/enrichment/ai_extractor.py`. No new provider code.
- It writes **only** a `draft`. It can never set `approved`, and a test enforces this.
- The draft screen shows a fixed banner «مسودة آلية — يجب مراجعة صيدلي».

**Review screen `/counselling`** (pharmacist / supervisor / admin):
- Queue tabs: يحتاج محتوى (no content, ranked by sales) / مسودات / بانتظار الاعتماد / معتمد.
- Side-by-side form with the item's identity and safety flags.
- Approve = one button that records who and when.
- Keyboard grid via `useGridKeyboard`, sortable via `useSortableRows`.

**Permissions:** the module uses the server-side RBAC matrix (`RoleModuleAccess`), never frontend hiding.
- `counselling.view`: POS-capable roles. Note that `view` never exposes drafts; see §5.
- `counselling.edit`: **pharmacist, admin**. Drafting, editing, linking items.
- `counselling.approve`: **pharmacist, admin**.
  - `supervisor` is the call-center supervisor, not a clinician, so it gets neither right.
  - `quality_manager` gets view only.
- Approver ≠ AI. A human approver is always recorded.
- Self-approval of one's own hand-written text is allowed for pharmacists. This is my call: the approver is
  the pharmacist; flag it if a second pair of eyes is wanted.

**Retiring or replacing content (my call):**
- `/c/:token` pins the version that was sent, *unless* that sheet has since been retired or re-approved.
- If re-approved, the page shows the **current approved version** with a note «تم تحديث هذه الإرشادات».
- If retired with no approved successor, the item shows «تم سحب هذه الإرشادات — راجع الصيدلي» and no text.
- Retired text is never shown to a customer again.

**Audit:** every create, edit, approve and retire is written to `AuditLog` with before/after.

## 5. Part B — Staff drug assistant

**One read endpoint** `GET /api/counselling/assistant/<item_id>/?branch=<id>` (permission `CanViewPos`,
branch-scoped via `core/branch_scope.py`). It aggregates existing pieces and adds no new business logic:

| Section (display order) | Source |
|---|---|
| 1. Safety flags (block/warn/info), always first | `catalog.safety.item_safety_flags` |
| 2. Identity: names, form, indication (`effect_name_ar`), Rx/OTC if known, fridge | `catalog.Item` |
| 3. Molecules: approved, or parsed + «غير موثّق» | `composition.ItemMoleculeIndex` (never `name_scientific`) |
| 4. Alternatives — verified | `composition.alternatives.alternatives_for` (unchanged) |
| 5. Alternatives — suggestions (unverified) | new `unverified_alternatives_for`, same rules on `source='parsed'` rows |
| 6. How to use / warnings | `CounsellingContent` **approved version only** for everyone. Unapproved drafts (AI or hand-written) are returned **only to `counselling.edit` users**, marked «مسودة غير معتمدة». Counter staff see «لا يوجد إرشاد معتمد بعد». A test enforces this (my call, rule 10). |

Rules:
- Unverified suggestions:
  - They need the same molecule set, all rows parsed or approved, and the item active.
  - `blocks_sale()` items are dropped. Results are sorted by stock here, then network.
  - They are shown in an amber block titled «اقتراحات غير موثّقة — تأكد من العبوة والتركيز».
  - **There is no add-to-basket action on them.** Staff search the item normally if they decide to sell it.
  - A «أبلغ عن خطأ» / «أكّد التطابق» link sends the pair to the existing `/composition` review queue
    (feedback only; approval stays in `/composition`).
- Verified alternatives keep their existing POS add behaviour (F7 panel).
- An item with a blocking flag shows the block banner above everything else, and no alternatives
  section is ranked above it.

**UI** is one shared component `DrugAssistantPanel` (calm, RTL, no modal):
- Desktop POS: a new tab in the existing `PosItemPreview` side panel for the highlighted search row,
  hotkey **F6** (unused there; the builder confirms it).
- Mobile `/m/pos` and `/m/items`: a bottom sheet from an «ℹ️ معلومات» action on the row.
- Ctrl+K: an item result gets a secondary action that opens the panel in a side drawer.
- Item page `/products/:id`: the same panel as a section.

## 6. Part C — WhatsApp counselling card

**Trigger (staff-chosen per sale):** a «إرسال إرشادات الاستخدام» button in three places:
1. POS order screen, once the order has a customer and lines.
2. Customer-360 recent purchases (from `PurchaseHistory` / `PurchaseHistoryLine`, i.e. real SOFTECH sales).
3. The drug assistant panel, with a customer picker.

The button opens an inline drawer (not a modal):
- Lines with **approved** content are pre-ticked. Lines without approved content are listed greyed «لا
  يوجد إرشاد معتمد».
- Phone: `whatsapp_phone`, else `phone` (same `phone_for()` rule as refill reminders), editable, Egyptian
  mobile validated.
- One send button.

**Server rules (deterministic):**
- Only approved versions are sent. The send pins the version ids.
- The customer is not opted out.
- At most one card per customer per item per 7 days unless the staff member ticks "إعادة الإرسال"
  (logged). This is my call, to avoid spam from double clicks.
- An idempotency key comes from the client, so a double click sends once.
- Daily cap per branch (default 200), via the setting `COUNSEL_CARD_DAILY_CAP`.

**Message:** a Meta template `counsel_card` (Utility, Arabic), submitted by the owner in WhatsApp Manager.
Body:

> {{1}} first name — «إرشادات استخدام مشترياتك من صيدليات الرزيقي جاهزة» — button URL `/c/{{2}}`

- It never names the medicine, the same principle as doc 26.
- Inside an open 24-h window, it is sent as plain text with the same link.
- Uses `WhatsAppSender.send_template` → `WAMessage` log (existing).

**Private page `/c/:token`:**
- A public tokenized page, like the existing `/track/:token`, that follows the N6 public-page rules
  (no staff auth, rate limits, junk tokens → 404 not 500).
- The token is a `django.core.signing` value bound to the `CounselCardSend` id, valid 90 days.
- It shows the customer's first name and the pinned approved versions of each item:
  - name, how to use, dose, frequency, duration, warnings, storage, missed dose
  - fixed footer «هذه الإرشادات عامة؛ اتبع تعليمات طبيبك أو الصيدلي» + branch phone
- It has an opt-out link «إيقاف رسائل الإرشادات».
- It also appears in the logged-in portal under the customer's orders when a PIC exists.

**Audit / models:**
- `CounselCardSend`:
  - customer, phone (stored masked + hash for dedupe; full number in the existing `WAMessage`)
  - branch, sent_by, created_at
  - items + content version ids (through `CounselCardItem`)
  - `wa_message` FK, status (queued/sent/failed/blocked_optout/skipped_off)
  - idempotency key, resend flag, source (pos/customer360/assistant), first-opened-at
- `CounselCardOptOut` (customer nullable + phone hash, created_at, source).
  - A send is blocked if **either** the customer **or** the phone hash is opted out.
  - It is separate from `RefillReminderOptOut` and campaigns, which are different message types (my call).
  - A refill opt-out does not block a card the customer asked for at the counter, and vice versa.
- Every send is also `omni.services.emit()`'d to the customer timeline (Customer-360 shows "أُرسلت إرشادات").

**Switches (settings, default False, forced off in tests unless set):**
- `DRUG_ASSISTANT_ENABLED`: hides the panel and the endpoint returns 404 when off.
- `COUNSELLING_CONTENT_ENABLED`: the `/counselling` review screen. It may be turned on early so
  pharmacists start curating before launch.
- `COUNSEL_CARD_SEND_ENABLED`: while off, the drawer shows an in-drawer preview of the message and the card
  page (staff endpoint, no public route), and nothing is sent or stored (doc-26 pattern). `/c/:token` only
  serves real sends.

**Sender change (my call):**
- `WhatsAppSender.send_template` gains an optional `url_button_params` argument, alongside the existing
  `quick_reply_payloads`, to fill the URL button suffix. This is a backwards-compatible addition.
- If the template is missing or not approved in `WATemplate`, the send is stored `failed` with reason
  `template_not_approved`. When the 24-h window is open, plain text is used instead.

## 7. Shared with Project 5 (dosage label)

Agreed with Project 5 on 2026-11-03. Project 5 has no dosage-text model and drops `ItemEnrichment` as a source.

Project 5 reads approved content through two stable read helpers in `apps.counselling.selectors`, not
through our fields directly:

- `approved_usage_text(item) -> str | None`: a short Arabic line. Project 5 uses it as the third source in
  its order, after this patient's last confirmed instruction and the item's most-confirmed instruction.
- `approved_content(item) -> dict | None`

Both helpers return None when nothing is approved or the content switch is off. The contract is posted in the shared session notes.

Later, not v1: promote Project 5's "most-confirmed instruction per item" into a DRAFT here for a pharmacist to approve.

## 8. In-app help and docs

- `apps/help/content/counselling.py` (AR + EN) covers `/counselling`, the assistant panel (POS tab and
  mobile sheet), the send drawer, `/c/:token` (public, exempt if the help test allows public routes), and
  the statuses draft/pending_review/approved/retired and the send statuses.
- `apps/help/content/pos.py` gets a new F6 tab, with its `updated` date bumped.
- Architecture doc `docs/architecture/34_DRUG_ASSISTANT_COUNSELLING.md` + an index row in `11_ERP_INDEX.md`.

## 9. Tests (minimum)

- AI draft can never reach `approved`. Editing an approved record makes a new draft, and the approved
  version keeps serving.
- Approve permission enforced server-side (salesperson → 403).
- Assistant:
  - safety flags first
  - verified vs unverified split
  - unverified excludes `blocks_sale()` items and never uses `name_scientific`
  - branch scoping
  - 404 when the switch is off
- Send:
  - only approved versions
  - opt-out blocks
  - 7-day dedupe and the resend override
  - idempotency
  - daily cap
  - nothing stored or sent when the switch is off
  - template has no item name
  - audit row + `WAMessage` link
- `/c/:token`: valid, expired, tampered → 404, opt-out works, no staff data leaked.
- Help test passes for the new routes.

## 10. Left to the builder

- Exact panel layout and copy within the calm-UI rules; F6 confirmation.
- Ranking of the "needs content" queue (by 90-day sold quantity is the default).
- Batch size and rate limits for AI drafting (reuse the enrichment limiters).
- Migration numbering and URL names.
