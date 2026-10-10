# 28 — In-app help (دليل الاستخدام)

Status: ✅ BUILT 2026-10-10 — framework + content for every staff route (175 routes, 31 modules).

## What users get

- **«؟ مساعدة» button + F1** in every staff shell (desktop `Layout`, mobile `MobileLayout`,
  rider `RiderLayout`). Opens a docked side panel (not a modal — the page stays usable) with the
  help of the **screen the user is on**, opened on the **tab they are on** (marked «أنت هنا»).
- Each screen's help: purpose · who uses it · tabs (one section per tab) · how-to steps
  (role-filtered) · the module workflow (status → next statuses) · tips / common mistakes · FAQ ·
  trainer's notes · related screens · other screens in the module.
- **Arabic + English** for every text; a «ع / EN» switch inside the panel, independent of the UI
  language.
- **Search** in the panel, on `/help`, and inside Ctrl+K.
- **/help center**: browse modules (grouped like the side menu) → module role + workflows +
  screens → full article; «الجديد» (recently changed help, unread badge); «للمدربين».
- **Feedback**: «مفيد / غير مفيد» + comment on every article.
- **Yellow dot** on the help button when the current screen's help changed since the user last read it.

## Onboarding — «مساري التدريبي» (built 2026-10-10)

- `apps/help/content/onboarding.py`: `ROLE_PATHS` (role → ordered screens, first week first),
  `QUIZZES` (module → short multiple-choice questions, bilingual, with the explanation),
  `PASS_PERCENT = 80`.
- `/help?tab=path`: progress %, «كمّل» (next screen), the checklist (✓ done / ⟳ help changed —
  re-read), and the module quizzes. «فهمت هذه الشاشة ✓» sits at the bottom of every article (panel
  and help center) — it records the help version read (`HelpLearned.version`), so a later text
  change asks the person to re-read.
- Quizzes: options are shuffled per person and sent **without answers**; the server grades and
  only then returns the right answer + explanation (`HelpQuizAttempt`). Best attempt counts.
  Retakes allowed.
- Trainers (help/edit): preview any role's path; «تقدّم الفريق في التدريب» in the trainers tab —
  per person %, failed quizzes, last activity, limited to the branches they can access.
- Tests: every role in `ROLE_CHOICES` has a path of real screens, every module on a path has a
  quiz, answer indexes are valid, every text bilingual; API grading / hiding / permissions.

**Trainer editing (built 2026-10-10):** «للمدربين» → «تعديل المسارات التدريبية والاختبارات»: reorder /
add / remove a role's path screens; edit a module's questions, options, correct answer and
explanation (or add a quiz to a module that has none; an empty quiz removes it). Stored in
`HelpTrainingOverride` (kind `path`/`quiz`, key), replacing the repo version until reverted; every
save/revert → `HelpRevision` with `screen_key` `path:<role>` / `quiz:<module>`; `base_changed`
warns when the repo version changed after the edit. All readers use `apps/help/training.py`.
API: `GET/PUT/DELETE /api/help/training/{path|quiz}/{key}/` (help/edit; GET includes answers).

**Quiz versions + notifications (built 2026-10-10):** every attempt stores the quiz version it
answered (`HelpQuizAttempt.version` = `training.quiz_version(questions)`). A pass counts only while
the quiz is unchanged; after a trainer (or developer) edit it shows as `stale` («⟳ اتغيّر — أعد
الاختبار») and is listed under «يعيد» in team progress. On save/revert (`apps/help/notify.py`, via
`apps.notifications`, never breaks the save): screens **added** to a role's path → everyone in that
role; a quiz changed → everyone who had passed the old version. The editor shows how many were
notified.

**Developer changes too (built 2026-10-10):** `HelpTrainingSnapshot` keeps what people were last
told (each role's path, each quiz's version). `training.announce_changes()` — hourly scheduler job
`help_announce_training` (minute 20) and `manage.py help_announce_training` (run after a deploy to
announce at once) — notifies only the difference, then records it. The first run only records.
Trainer saves record the snapshot too, so nothing is announced twice.

**Rule:** a new screen a role must use → add it to that role's `ROLE_PATHS`; a new rule users
must not get wrong → add a quiz question.

## Printable training manual (built 2026-10-10)

- `/help/manual?role=<role>` or `?module=<key>`, `&lang=ar|en` — its own shell (no side menu) so the
  browser's print / "Save as PDF" gives a clean booklet: cover (help last-updated date, print date),
  contents, then one chapter per module (summary + workflows) followed by its screens (purpose,
  audience, tabs, steps, tips, FAQ, trainer's notes). Each chapter starts on a new page.
- By role = that role's `ROLE_PATHS`, with steps/tips limited to the role. By module = all screens.
- Opened from «طباعة دليلي» (My training path) and «طباعة دليل الموديول» (module page).
- Data: `GET /api/help/manual/`. Quizzes are not printed (taken in-app so results are recorded).

## «اعرض لي» guided tours (built 2026-10-10)

- A screen's help may have `tour: [{'target': '<data-tour id>', 'text': T(…)}]`. «👆 اعرض لي» (panel
  footer, or «اعرض لي على الشاشة» in /help, which opens the screen first) spotlights each real
  element (`[data-tour="…"]`) with a card: «التالي» / «السابق» / «إنهاء», Enter / Esc.
- Calm: the dimmed mask ignores clicks (the highlighted button can be pressed for real); leaving the
  screen ends the tour; a step whose element is not visible (other tab, role, nothing selected)
  still shows its text with a note. Runner: `frontend/src/help/Tour.jsx` (mounted by `HelpPanel`).
- Built for 56 screens — desktop: call-center cases, WhatsApp inbox, loyalty program + branch points, refill reminders, cash optimization, supplier performance, market shortages, replacement cases; mobile: demand list + detail, delivery board; reservation / demand / transfer detail, transits, customers list, product catalog + product, omni inbox, dispatch board, rider app, POS exceptions, HR approvals; sales analytics, KPI board, finance dashboard, expenses, insurance
  claims + claim, purchasing engine, supply, users, permissions matrix, sync; POS, reservations board + new, demand list, transfers list + new,
  stock count, follow-ups, delivery dashboard, customer detail, shortages, call-center operator, HR
  requests, tasks, vouchers; mobile: POS, reservations, new demand, transfers, stock count,
  customers. Steps on repeated items (cards) highlight the first one.
- Anchor ids: `<screen key with - instead of .>-<name>`. **Test:** every tour target must exist as
  `data-tour="…"` in `frontend/src` — renaming/removing an anchor fails CI.
- Trainers edit the tour **text** in «تعديل الشرح» (field `tour`, merged by `target` like tabs — the
  steps and their buttons stay fixed by the code).

## «اسأل النظام» (built 2026-10-10)

- Type a question in the panel / help-center search box → «💬 اسأل النظام» (one click, never while
  typing). `POST /api/help/ask/`.
- `registry.retrieve()` picks the 5 best articles (sentence-friendly: ignores common words and
  prefixes; the current screen gets a boost). `apps/help/ask.py` sends **only those articles** to
  Gemini with strict rules: answer only from them, say when they don't cover it, never state
  prices / discounts / totals / doses / substitutes or approve anything, cite the screens used.
  Citations not among the sent articles are dropped. The answer always shows its source screens.
- No model configured or it fails → the matching articles are shown instead (still useful).
- 30 questions per person per hour. Every question is logged (`HelpEvent kind=ask`, `results=0`
  when unanswered) and listed for trainers — unanswered questions = help that needs writing.

## Usage report — help nobody uses (built 2026-10-10)

«للمدربين» → for the selected period: screens whose help nobody opened (those on a role's training
path first — people should have read them), and «اعرض لي» tours: runs, % finished, the step most
people stop after (the next step is probably unclear or its button not visible), tours never run.
The tour runner reports its end once (`POST /api/help/tour-event/` → `HelpEvent kind=tour`,
`results` = steps reached, `query='done'` when finished); report: `GET /api/help/usage/?days=`.

## Trainers (help/edit)

- RBAC module `help`, action `edit` (Permissions Matrix). Admin always; seeds give it to
  `supervisor` and `quality_manager`.
- «تعديل الشرح» edits title, purpose, audience, steps, tab texts, tips, FAQ and trainer's notes in
  both languages. Tabs are fixed by the code (text only). A save shows to everyone at once.
- Every save / revert → `HelpRevision` (who, when, before, after, reason). «الرجوع للشرح الأصلي»
  drops the override.
- When developers change the repo text after a trainer edit, the editor warns «base changed»
  (`HelpOverride.base_hash`).
- «للمدربين» tab: screens whose help is opened most, by role, ratings (worst first), searches
  (incl. ones with no result), open comments to resolve.

## Architecture

| Piece | Where |
|---|---|
| Help text (source of truth) | `apps/help/content/<module>.py` — one file per module, `T(ar, en)`; order in `content/__init__.py` |
| Loader / merge / search | `apps/help/registry.py` (repo text + `HelpOverride` → effective; Arabic-normalized search) |
| DB | `HelpOverride`, `HelpRevision` (immutable), `HelpFeedback`, `HelpEvent` (open/search/ask; `results=0` = nothing found), `HelpLearned`, `HelpQuizAttempt`, `HelpTrainingOverride` |
| Onboarding | `apps/help/content/onboarding.py`, `apps/help/training.py`, `apps/help/onboarding_views.py`, `frontend/src/help/Onboarding.jsx`, `frontend/src/help/TrainingEditor.jsx` |
| API | `/api/help/` — see 04_API_REGISTRY |
| Manual | `views.manual`, `frontend/src/pages/HelpManualPage.jsx` (route `/help/manual`, outside `Layout`) |
| Frontend | `frontend/src/help/` — `HelpPanel`, `HelpButton`, `HelpArticle`, `HelpEditor`, `HelpFeedback`, `helpStore`, `useHelpIndex` (route → screen via react-router `matchPath`), `useHelpTab`; page `pages/HelpCenterPage.jsx` |

Reading help is open to every logged-in staff member (`/api/help/` is exempt from
`ModuleAccessMiddleware`); edit / revisions / feedback list / stats check `help/edit` in the views.
Nothing here touches SOFTECH.

### Tab awareness

Pages report their visible tab with one line: `useHelpTab(tab)`. The value must equal a tab `key`
in the screen's help. Drawers with their own tabs call it too (a stack: the innermost open tab wins,
closing the drawer falls back to the page tab). Pages that keep the tab in `?tab=` need nothing.

## Keeping it up to date (enforced)

`apps/tests/test_help.py` fails CI when:

1. a route in `frontend/src/App.jsx` has no help screen (or help points at a route that no longer exists);
2. any text is missing Arabic or English;
3. a workflow linked to a model (`model` + `field`) does not explain **exactly** that field's choices;
4. a workflow linked to the server's transition table (`transitions` dotted path) lists different next steps;
5. a `related` / `workflows` reference points at something that does not exist.

**Rule for every feature batch:** new screen / tab / status → update the matching
`apps/help/content/<module>.py` and bump that screen's `updated` date (users get the "new" dot).

## Adding help for a new screen

```python
# apps/help/content/<module>.py
{
    'key': 'module.screen',            # '<module>.<screen>'
    'routes': ['/path', '/path/:id'],  # exactly as in App.jsx
    'title': T('…', '…'), 'summary': T('…', '…'),
    'audience': T('…', '…'),
    'tabs': [{'key': 'items', 'title': T('…', '…'), 'body': T('…', '…')}],
    'steps': [T('…', '…'), {'text': T('…', '…'), 'roles': ['admin']}],
    'tips': [T('…', '…')],
    'faq': [{'q': T('…', '…'), 'a': T('…', '…')}],
    'related': ['other.screen'],
    'workflows': ['key'],              # optional: only these module workflows
    'tour': [{'target': 'module-screen-btn', 'text': T('…', '…')}],  # optional «اعرض لي»; add data-tour="module-screen-btn" to the element
    'updated': 'YYYY-MM-DD',
}
```

Writing style: formal Arabic with Egyptian-friendly wording; short sentences; name buttons exactly
as they appear on screen («…»).

## Next steps (proposed, not built)

- Tours for the remaining screens (only ~56 of 176 have one; the panel shows the button only where one exists).
