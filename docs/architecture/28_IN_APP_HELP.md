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
| DB | `HelpOverride`, `HelpRevision` (immutable), `HelpFeedback`, `HelpEvent` (open/search; `results=0` = nothing found) |
| API | `/api/help/` — see 04_API_REGISTRY |
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
    'updated': 'YYYY-MM-DD',
}
```

Writing style: formal Arabic with Egyptian-friendly wording; short sentences; name buttons exactly
as they appear on screen («…»).

## Next steps (proposed, not built)

- «اعرض لي» guided tours that highlight the real buttons (same pattern as the POS guided mode).
- Role onboarding checklists + short quizzes per module, with a supervisor view of completion.
- Printable training manual per role/module generated from the same content.
- «اسأل النظام»: answers grounded only in this help content, with a link to the source article.
