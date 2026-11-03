# 34 — Staff Drug Assistant + WhatsApp Counselling Card (Project 4)

**Status:** ✅ BUILT 2026-11-03. All three switches are OFF, so nothing changes until the owner turns them on. SOFTECH is only read.
Design: [spec](../superpowers/specs/2026-11-03-drug-assistant-counselling-card-design.md) · plan: [plan](../superpowers/plans/2026-11-03-drug-assistant-counselling-card.md).

## What it does
1. **Usage sheets** (`/counselling`)
   - A pharmacist writes one sheet, or starts from an AI draft, and approves it.
   - A sheet covers: what it is for, how to use it, dose, frequency, duration, warnings, storage and missed dose, plus `frequency_code` and `with_food` for the label.
   - The pharmacist ticks the items that share the sheet (other packs and codes). The screen suggests items with similar names, but **nothing is linked automatically**.
   - Each approval writes an immutable `CounsellingContentVersion`.
   - Editing an approved sheet turns it back into a draft, and the approved version keeps serving until the edit is approved.
   - Approve/retire needs `counselling → approve`: pharmacist or admin only. `supervisor` is the call-center supervisor and can only view.
2. **Drug assistant** (POS F7 «معلومات وبدائل», Ctrl+K Shift+Enter, `/m/items`, product tab «💊 للصيدلي»). One read, in a fixed order:
   1. safety flags (`catalog.safety`)
   2. identity
   3. molecules (verified or not)
   4. verified alternatives (`alternatives_for`, add allowed)
   5. **unverified suggestions** (`unverified_alternatives_for`, amber, no add)
   6. approved guidance
   Drafts are returned **only to `counselling → edit` holders**. `Item.name_scientific` is never read.
3. **Counselling card**
   - Sent by staff, per sale, from three places: the POS footer «📘 إرشادات», Customer-360 purchases, or the mobile POS.
   - Only items with an approved sheet are sent, and the exact version is pinned on the send.
   - The WhatsApp message never names a medicine. It is the template `counsel_card` (first name + URL button `/c/<token>`), or plain text when the 24-h window is open.
   - The `/c/:token` page shows the pinned approved text. If the sheet was re-approved it shows the current approved text with «تم تحديث». If the sheet was withdrawn it shows «تم سحب هذه الإرشادات — راجع الصيدلي» and no text.
   - The page has an opt-out link.
   - The card also appears in the logged-in portal (`/api/portal/orders/` → `counsel_cards`).

## Deterministic send rules (`apps/counselling/cards.py`)
- Switch off → nothing stored or sent; the drawer previews only.
- Idempotency key per drawer open → a double tap sends one message.
- Opted out by customer **or** phone hash → a `blocked_optout` row with no message. This is separate from the refill-reminder opt-out.
- An item sent to the same phone in the last `COUNSEL_CARD_DEDUPE_DAYS` (7) is dropped unless «إعادة الإرسال» is ticked.
- Branch cap `COUNSEL_CARD_DAILY_CAP` (200) per Cairo day.
- Template not approved in `WATemplate` → `failed` / `template_not_approved`.
- Every send is written to `AuditLog` (`counsel_card_sent`) with the item versions, and to the omni timeline.

## Switches (settings, default False)
| Switch | What it controls |
|---|---|
| `DRUG_ASSISTANT_ENABLED` | The F7 assistant, Ctrl+K drawer, mobile card and product tab. The endpoint returns 404 when off. |
| `COUNSELLING_CONTENT_ENABLED` | `/counselling` (503 when off) and the read helpers. It can go on before sending so pharmacists curate early. |
| `COUNSEL_CARD_SEND_ENABLED` | Real sends. |

Other settings: `COUNSEL_CARD_TEMPLATE` (`counsel_card`), `_LANGUAGE` (`ar`), `_DAILY_CAP` (200), `_TOKEN_DAYS` (90), `_DEDUPE_DAYS` (7).

**Owner action before sending:** in WhatsApp Manager, submit the Utility template `counsel_card` (Arabic):
- Body: «مرحباً {{1}}، إرشادات استخدام مشترياتك من صيدليات الرزيقي جاهزة»
- One URL button: `https://<FRONTEND_BASE_URL>/c/{{1}}`

Then add it in `WATemplate` with status approved.

## Shared with Project 5 (dosage label)
`apps.counselling.selectors.approved_usage_text(item)` / `approved_content(item)` return the latest **approved** snapshot. They return None when the content switch is off, the item has no sheet, or the sheet is retired. Project 5 only reads them.

## Code
- `apps/counselling/`:
  - `models.py`: sheet, item link, version, send, send line, opt-out
  - `services.py`: the workflow, all audited
  - `ai_draft.py`: drafts only; reuses `enrichment.ai_extractor.complete_json`
  - `assistant.py`, `cards.py`, `public_views.py`
  - `views.py` / `urls.py` → `/api/counselling/`
- Public: `/api/public/counsel/<token>/` (+ `opt-out/`)
- Changes elsewhere:
  - `composition/alternatives.py`: shared `_match` + `unverified_alternatives_for`
  - `whatsapp/sender.py`: `url_button_params`
  - RBAC module `counselling` (`users.0045`)
  - middleware maps `counselling/assistant|cards` → `pos`
- Frontend: `src/counselling/*`, `pages/CounsellingPage.jsx`, `pages/CounselCardPublicPage.jsx`
- Management command: `draft_counselling --top N --as <user>` (drafts only).
- Help: `apps/help/content/counselling.py`.
- Tests: `apps/tests/test_counselling_{content,ai_draft,assistant,cards,public}.py`.
