# Rich tours — Batch 1 (framework + reservations/POS pilot) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rich «اعرض لي» steps (label / text / when / warn / open_hint), on-screen emphasis, cross-screen module journeys, piloted on the reservations and POS modules.

**Architecture:** Content stays in `apps/help/content/<module>.py`. `registry.py` gains journey merge; `views.py` serves journeys inside the module and screen payloads, accepts journey tour-events, and edits journey text through `HelpOverride` keyed `journey:<module>.<key>`. `Tour.jsx` renders both screen tours and journeys from one runner.

**Tech Stack:** Django/DRF, React 18 + Zustand + Tailwind, Django `TestCase` in `apps/tests/test_help.py`.

**Spec:** [docs/superpowers/specs/2026-10-26-rich-tours-design.md](../specs/2026-10-26-rich-tours-design.md)

## Global Constraints

- Step keys allowed: `target` (required), `text` (required), `label`, `when`, `warn`, `open_hint`; journey steps add `screen` (required) and `perm` (RBAC module key, optional).
- Limits per language: `label` ≤ 40 chars; `text` / `when` / `warn` / `open_hint` ≤ 160 chars.
- ⚠ keywords (whole hyphen tokens of `target`): `push post approve reject discount send cancel delete close settle writeback softech flush`.
- Rules (⚠ + limits) apply only to modules NOT in `TOUR_PENDING`; batch 1 leaves every module pending except `reservations` and `pos`.
- A tour/journey never clicks or submits anything; «روح للشاشة» only navigates to a param-free route.
- Journeys never mix desktop (`/…`) and mobile (`/m/…`) screens. `roles` ⊆ `ROLE_CHOICES` keys.
- Writing style: formal Arabic, Egyptian-friendly; buttons named exactly as on screen «…».
- Bump `updated` to `2026-10-26` on every screen whose tour changes.

## Review Focus

1. Trainer saved the OLD tour format (text only) before this change → effective tour keeps new label/when/warn from the repo, trainer text wins for `text` only. (Task 1 test.)
2. Trainer edit of a journey after the repo removed/reordered a step → edit applies only where index AND target still match. (Task 1 test.)
3. Journey step on a `:id` route when the user is elsewhere → no «روح للشاشة», `open_hint` shown, journey advances by itself when a matching route opens. (Task 3 manual check.)
4. User without RBAC `view` on a step's `perm` → no navigate button, "not available for your role" note, «التالي» still works. (Task 3 manual check.)
5. Long Arabic card on a small mobile viewport → card fits (width ≤ viewport − 24, measured height) and never hides the target. (Task 3 browser check at 375×812.)

---

### Task 1: Backend — rich steps, journeys, validation, events

**Files:** Modify `apps/help/registry.py`, `apps/help/views.py`, `apps/help/urls.py`, `frontend/src/api/client.js` (helpApi.journey get/put/delete); Test `apps/tests/test_help.py`.

**Interfaces — produces:**
- `registry.TOUR_STEP_KEYS = {'target','text','label','when','warn','open_hint'}`, `registry.TOUR_TEXT_KEYS = ('text','label','when','warn','open_hint')`.
- `registry.journeys() -> dict['<module>.<key>', journey]` (each journey dict gets `module`, `id`).
- `registry.effective_journey(journey, override) -> journey` (merge by index when target matches; only TOUR_TEXT_KEYS).
- `_merge_tour` merges all TOUR_TEXT_KEYS by target.
- Module payload (`module_detail`) and screen payload `module.journeys`: journeys filtered by the requester's role, with overrides applied, each step enriched with `route` (first param-free route of its screen, or null) and `routes` (all routes).
- `GET/PUT/DELETE /api/help/journeys/<module>.<key>/` — mirrors `screen_detail` edit semantics (help/edit; HelpRevision with `screen_key='journey:<id>'`).
- `tour_event` accepts `screen_key='journey:<id>'`; `usage` lists journeys in `tours` with `kind: 'journey'`.

- [ ] Tests (fail first): `test_tour_step_format` (allowed keys; bilingual for every present text key; limits + ⚠ for non-pending modules), `test_journeys_valid` (screen exists, anchor exists, `open_hint` when all routes of the screen have `:`, no shell mixing, roles valid, perm in MODULE_CHOICES), `test_every_non_pending_module_has_journey_and_tours` (every screen of reservations/pos has a tour; each has ≥1 journey), `test_merge_tour_keeps_new_fields_with_old_override`, `test_journey_edit_and_revert` (PUT text, revision row, DELETE reverts, non-trainer 403, index/target mismatch ignored), `test_journey_tour_event` (201 + clamped; unknown 400), update `test_tour_targets_exist_in_the_frontend` to use `TOUR_STEP_KEYS` ⊇ keys.
- [ ] Implement; run `python manage.py test apps.tests.test_help` → all pass.

### Task 2: Frontend runner — rich card, emphasis, journeys

**Files:** Modify `frontend/src/help/Tour.jsx`, `helpStore.js`, `HelpPanel.jsx`, `HelpEditor.jsx` (label/when/warn/open_hint fields per step), `frontend/src/pages/HelpCenterPage.jsx` (module page «رحلات العمل» cards + «ابدأ الرحلة» + trainer edit), `frontend/src/index.css` (pulse keyframes, reduced-motion).

**Interfaces:** `helpStore.startTour(key, steps, {journey: bool})` → `tour: {key, steps, i, journey}`; `Tour` reads `step.label/when/warn/open_hint/screen/route/routes/perm`.

- [ ] Card: progress bar + `i/n`, bold «label», text, «متى؟ / When:» line, amber ⚠ box, open_hint when target absent; measured card height for placement; width `min(340, vw-24)`.
- [ ] Ring: brand, amber when `warn`; `.tour-pulse` 3 pulses then steady; `@media (prefers-reduced-motion)` → no animation, 3px ring.
- [ ] Journeys: don't end on navigation; if current path doesn't match `step.routes` → show «روح للشاشة» when `step.route` and (no `perm` or `can(perm,'view')`), else open_hint / role note; auto-continue when path matches.
- [ ] Panel: under «اعرض لي», list `data.module.journeys` as «🧭 <title>» buttons.
- [ ] `npm run build` passes.

### Task 3: Pilot content + anchors

**Files:** `apps/help/content/reservations.py`, `apps/help/content/pos.py`, reservation + POS page JSX (anchors only).

- [ ] Rewrite all 9 existing tours and add tours for `reservations.list` and `pos.offers` in the rich format, every important button a step, ⚠ on costly ones; anchors renamed only where the ⚠ rule needs an action word.
- [ ] Journeys: reservations `reservation_lifecycle` (desktop: new → board → detail status → match), `reservation_mobile` (mobile); POS `pos_order_to_cashier` (desktop order → preview → send → exceptions), `pos_mobile_order`.
- [ ] `updated: '2026-10-26'` on touched screens. `TOUR_PENDING` = all modules except reservations, pos.
- [ ] Tests + build; browser spot-check board tour, POS tour, one journey, mobile width.

### Task 4: Docs

- [ ] Update `docs/architecture/28_IN_APP_HELP.md` (step format, journeys, rules, TOUR_PENDING) and the help screen for the help center if it describes tours.
