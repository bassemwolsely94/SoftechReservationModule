# Rich «اعرض لي» tours + workflow journeys — design

Date: 2026-10-26 · Extends [28_IN_APP_HELP.md](../../architecture/28_IN_APP_HELP.md) · Status: draft for approval

## Why

Staff press buttons without knowing when to press them, what happens next, or which presses are
costly (a SOFTECH push, an approval, a discount). Today's tours exist on 56 of 142 help screens, about
5 steps each, and each step is one ~34-character line that only says *what* a thing is. Nothing walks a
person through a whole process that spans screens (reservation → match → handover).

Success: on every screen, «👆 اعرض لي» explains every important button well enough that a new
employee can do the job without asking; each module has at least one guided walk through its main
process; costly buttons are unmistakably flagged.

## Goals

1. **Richer tour steps** — every step shows the button's on-screen name in bold, then up to three short
   lines: what it does · when to use it / what happens next · ⚠ warning where a mistake is costly.
2. **Workflow journeys** — per-module guided walks through a whole process, moving across screens.
3. **Full coverage** — all 142 help screens get a tour; every important button is a step.
4. **Stronger emphasis** — a pulsing highlight on the target, a visible step counter and progress bar.

## Non-goals

- No videos, GIFs or screen recordings.
- No forced first-run tour or pop-up on login (CLAUDE.md rule 11: calm UI). Tours stay opt-in.
- No change to any business rule, permission, SOFTECH write or calculation. Help/frontend only.
- Customer portal (`/portal`) is out of scope (help covers staff shells only, as today).

## Anti-goals (a failure even if it "works")

- A tour or journey that **clicks, submits, saves or pushes anything by itself.** The user always presses
  real buttons; the tour only highlights and explains.
- Walls of text. A step is a glance, not an article (limits below).
- Tour steps that drift from the real UI (wrong button names, dead anchors).
- A ⚠ warning that states a price, discount, dose or substitute (same rule as «اسأل النظام»).

## Part 1 — Step format (backward-compatible)

```python
'tour': [{
    'target': 'reservations-board-new',          # data-tour anchor (unchanged)
    'label':  T('+ حجز جديد', '+ New reservation'),  # NEW, optional: the button text exactly as on screen
    'text':   T('…what it does…', '…'),           # existing, required
    'when':   T('…when to use it / what happens after…', '…'),   # NEW, optional
    'warn':   T('…the costly mistake to avoid…', '…'),           # NEW, optional
}]
```

- Old steps (`target` + `text` only) keep working unchanged.
- Limits (enforced by test): `label` ≤ 40 chars, `text` / `when` / `warn` ≤ 160 chars each, per language.
- **Mandatory ⚠ rule (test):** a step whose `target` contains one of
  `push | post | approve | reject | discount | send | cancel | delete | close | settle | writeback | softech`
  must have a `warn`. Anchor names therefore must say what the button does (e.g. `pos-order-push`, not
  `pos-btn-2`). The keyword list lives in one constant next to the test.
- Trainers: «تعديل الشرح» edits `label`, `text`, `when`, `warn` per step; `_merge_tour` merges all four by
  `target` (targets and step order stay fixed by code, as today).

### Card layout (Tour.jsx)

```
اعرض لي   ███████░░░░  4 / 9                         إنهاء ✕
«+ حجز جديد»                       ← label, bold, brand colour
يفتح نموذج حجز لعميل طلب صنف مش موجود.        ← text
متى؟ لما الصنف رصيده صفر في الفرع. بعد الحفظ…  ← when (muted, prefixed «متى؟» / "When:")
⚠ اتأكد من رقم موبايل العميل قبل الحفظ…       ← warn (amber box)
[السابق]                                        [التالي]
```

- Card height is measured (not the current hard-coded 180px) so the larger card never covers its target.
- Progress bar + "4 / 9" counter (counter exists; bar is new).

## Part 2 — Emphasis on screen

- Pulsing ring on the highlighted element (CSS keyframes, 2–3 soft pulses then steady ring), plus the
  existing dimmed mask. `prefers-reduced-motion` → no pulse, thicker ring.
- When the step has a `warn`, the ring is amber instead of brand blue.
- The highlighted element stays clickable (unchanged behaviour).

## Part 3 — Workflow journeys (cross-screen)

Defined per module in the module file:

```python
MODULE = {
    …,
    'journeys': [{
        'key': 'reservation_lifecycle',
        'title': T('رحلة الحجز من الطلب للتسليم', 'Reservation: from request to handover'),
        'summary': T('…', '…'),
        'roles': ['pharmacist', 'salesperson'],         # optional; StaffProfile ROLE_CHOICES keys; empty = everyone
        'steps': [
            {'screen': 'reservations.new',   'target': 'reservations-new-customer', 'label': …, 'text': …, 'when': …, 'warn': …},
            {'screen': 'reservations.board', 'target': 'reservations-board-column-available', …},
            {'screen': 'reservations.detail', 'target': 'reservations-detail-match', 'open_hint': T('افتح أي حجز من اللوحة', 'Open any reservation from the board'), …},
        ],
    }],
}
```

Runner behaviour:

- A journey step names a help `screen`. If the user is not on it:
  - screen has a route **without** `:params` → the card shows «روح للشاشة» ("Go to screen"); pressing it
    navigates (a plain page open — nothing is created or changed), then the step continues.
  - screen route **has** `:params` (a record detail) → the card shows `open_hint` ("open any reservation
    from the board"), waits, and continues by itself when the user lands on a matching route.
- Navigating between steps does **not** end a journey (screen tours still end on leaving the screen).
  Esc / «إنهاء» ends it; the step index is kept in `helpStore` (not persisted across reloads).
- Where it is started: the module page in /help («ابدأ الرحلة» per journey), and the help panel shows the
  current module's journeys under the screen's «اعرض لي».
- Usage: the existing tour-event endpoint with `screen_key = 'journey:<module>.<key>'`; the trainers'
  usage report lists journeys alongside tours.
- Tests: every journey step's `screen` exists, its `target` exists as an anchor, `open_hint` present when
  the screen's routes all have params, text bilingual, same length limits and ⚠ rule.
- Trainers edit journey text the same way (merge by step index + target). Journeys are in v1 editable
  for text only; adding/removing steps is code.

Each module gets 1–3 journeys covering its main process (e.g. POS: order → push to cashier → follow-up;
transfers: request → approve → ship → receive; purchasing: run engine → review → ISR → push).

## Part 4 — Coverage

- Every help screen (142) gets a tour. Target 6–12 steps; every primary action (create, save, approve,
  reject, push/post, send, cancel, print, export, import, filter that changes the result) is a step.
- Adding anchors means adding `data-tour="…"` attributes to existing JSX elements only — no layout or
  behaviour change.
- Existing 56 tours are rewritten to the rich format in the same module batch.
- **Coverage test:** every screen must have a tour. While batches are in progress, a shrinking
  `TOUR_PENDING` set in the test lists screens not done yet; the final batch empties it.
- Each touched screen's `updated` date is bumped (users get the "new" dot), and doc 28 is updated.

## Delivery order (batches, each one stops for approval)

1. **Framework** — step format, card, pulse/progress, editor fields, journey runner, tests, doc 28.
   Pilot: reservations + POS (screen tours rewritten + 1 journey each).
2–6. **Modules**, ~5–6 per batch in side-menu order: operations (demand, transfers, follow-ups, delivery,
   stock count, tasks) → customers/vouchers/loyalty/catalog/chronic/batches → shortage, replacement,
   call center, omni → purchasing, invoices, pricing, analytics, incentives → finance, insurance,
   commerce, HR, admin, general, gamification.

Each batch: anchors + rich tours + journeys + `updated` bumps + tests + `npm run build`, then a
spot-check in the browser of 2–3 tours on the real screens.

## Constraints

- Arabic first, formal with Egyptian-friendly wording, buttons named exactly as on screen («…») —
  existing help writing style.
- Content must be checked against the real JSX (button text, which roles see it) — no invented buttons.
- Mobile shells (`/m/...`, rider) use the same runner; card width caps at viewport − 24px.

## Decisions settled after the builder review (author's calls — check these)

1. **Plan scope.** The implementation plan details batch 1 only; batches 2–6 stay an outline and each
   gets its own short plan when it starts.
2. **Journey trainer edits reuse `HelpOverride`** with `screen_key = 'journey:<module>.<key>'` (field is
   a free 80-char key) — same revision/revert/base-hash machinery, **no new model, no migration.**
   Merge = by step index, only when the target still matches.
3. **⚠ rule and length limits apply per module once rewritten.** A `TOUR_PENDING` set (modules not yet
   rewritten) exempts their old steps; batch 1 removes reservations + POS from it. Keyword matching is on
   whole hyphen-separated anchor tokens (`pos-order-push` matches `push`; `purchasing-sendlist-filter`
   does not match `send`), and a small `WARN_EXEMPT` set covers anchors that only *name* a keyword
   (e.g. a «ملغي» status tab) — each entry needs a comment.
4. **Targets that need UI state** (a tab, a status, an open drawer): any step — screen tour or journey —
   may carry an optional `open_hint` ("switch to the «مطابقة» tab", "pick an order in status …"). If the
   anchor is absent, the card shows `open_hint` when present, else today's "not on screen" note.
   No automatic tab switching.
5. **Roles.** `roles` uses `ROLE_CHOICES` keys. A journey whose `roles` excludes the user is not listed.
   «روح للشاشة» is shown only when the user's module access (the same data the side menu uses) allows the
   target screen; otherwise the card says the screen is not available for their role and offers «التالي».
6. **Usage endpoint.** `tour_event` is extended to accept `journey:<module>.<key>` (clamped to that
   journey's length); the trainers' usage report lists journeys with tours.
7. **Desktop vs mobile.** Mobile (`/m/...`) and rider screens are among the 142 and get their own
   screen tours. A journey never crosses shells (test-enforced: all its screens are desktop, or all mobile).

## Left to the builder

- Exact CSS for the pulse/progress bar (within the theme tokens; light + dark).
- Anchor naming beyond the `<screen key with ->-<action>` convention and the ⚠ keyword rule.
- Which buttons count as "important" on a screen, within the list in Part 4.
- Whether the help panel lists journeys as a section or a single «رحلات الموديول» button.
