# Item and Channel Codes (piece 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Customer-channel (`ptclassifcode`) and item-category (`medicine_type`) meanings live in one editable mapping each, read by every module; an unknown code is «غير مصنف», never guessed.

**Architecture:** Channels extend the existing `ChannelBucketMap` (apps/forecasting) with `group`, `is_contract_sale`, `followup_rank`; item categories get a new `MedicineTypeMap` (apps/config). Each has one cached reader module; consumers switch from literals to the reader. Sync inserts new SOFTECH codes as unclassified and notifies admins. A `/code-maps` screen (settings module RBAC, audited) edits both.

**Tech Stack:** Django 5 / DRF, PostgreSQL, React + Vite, Django TestCase.

**Spec:** `docs/superpowers/specs/2026-11-13-item-and-channel-codes-design.md` (owner decisions §7); parent `docs/superpowers/specs/2026-11-13-branch-classification-and-crews-design.md` §7–§10.

## Global Constraints

- No SOFTECH write is added or changed. `apps/pos_orders/models.py` and `apps/pos_orders/writer.py` are NOT edited (owner decision 5).
- Do not edit: `apps/forecasting/kpi_export.py`, `apps/branches/*`, `apps/catalog/models.py`, `apps/purchasing/views.py`, `apps/tests/security/static_scan.py` (piece 1 owns them).
- KPI `bucket` / `subtype` / `counts_customer` / `include_in_profit` values never change in this work.
- Unknown code wording: Arabic «غير مصنف», shown with the code: `«غير مصنف (<code>)»`.
- Tests: `TEST_DB_NAME=test_codemaps_1`, focused modules only, `--keepdb`, never `--parallel`, never the full suite or security sweeps. Python: `../../../venv/Scripts/python.exe` from the worktree root. Command form:
  `TEST_DB_NAME=test_codemaps_1 ../../../venv/Scripts/python.exe manage.py test <modules> --keepdb -v 1`
- Frontend: `frontend/node_modules` is a junction to the main checkout's; build with `npm run build` in `frontend/`.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

### Owner-approved meaning table (seed values, copied from spec §2–§7)

Channels (person_type `'10'`):

| code | group | is_contract_sale | followup_rank |
|---|---|---|---|
| 91 | cash | False | 1 |
| 90 | delivery | False | 1 |
| 30 | permanent | False | 2 |
| 99 | vip | False | 2 |
| 10 | contract | True | 3 |
| 33 | contract | True | 3 |
| 11 | employee | True | 3 |
| 12 | card | False | 3 |
| 15 | insurance | True | 4 |
| 16 | donation | False | 4 |
| 17 | compensation | True | 4 |
| 31 | settlement | False | 4 |

Groups and Arabic labels: cash نقدي، delivery توصيل، permanent عميل دائم، contract تعاقد، employee موظفين، insurance تأمين، card بطاقة شخصية، donation تبرعات، compensation تعويضات، settlement مقاصات، vip VIP، other أخرى، unclassified غير مصنف.

Item categories:

| code | group | is_medicine | excluded_from_planning |
|---|---|---|---|
| 10 | medicine | True | False |
| 50 | cosmetics | False | False |
| 20 | others | False | False |
| 30 | body_building | False | False |
| 40 | veterinary | False | False |
| 60 | gift | False | True |
| 70 | service | False | False |
| 00 | na | False | False |

## Review Focus

1. **Fresh / test DB with an empty map** — readers must still give the approved meanings (lazy seed), and a test that already created its own `ChannelBucketMap` row must not hit a unique-constraint error. Test in Task 1 and Task 2.
2. **Production rows already exist** (office DB has every pair) — the migration must set group/rank/contract on existing rows and never change `bucket`. Test in Task 1.
3. **Blank channel code** (6,069 follow-up tasks, 198k customers have `''`) — shows `—` / «عميل» as today, not «غير مصنف ()». Test in Task 3.
4. **Owner edits the map** — the reader cache must drop on save, so the next request sees the edit. Test in Task 5.
5. **A code SOFTECH adds later** — sync creates the row as unclassified, notifies admins once (dedup), and every consumer treats it as not-contract / not-favoured / not-medicine / not-excluded. Test in Task 6.

---

### Task 1: Channel registry (model fields, reader, seed, sync hook)

**Files:**
- Modify: `apps/forecasting/models.py` (`ChannelBucketMap`: add fields + `GROUP_CHOICES`)
- Create: `apps/forecasting/migrations/0014_channel_meaning.py` (schema + update-only data step)
- Create: `apps/forecasting/channels.py`
- Modify: `apps/forecasting/management/commands/seed_kpi_config.py` (use `CHANNEL_DEFAULTS` meaning columns on create / `--reset-defaults`)
- Modify: `apps/sync/tasks.py` — one call after the `SoftechPersonClassif.objects.bulk_create(...)` block (~line 1147): `ensure_channel_rows()`
- Test: `apps/tests/test_code_maps_channels.py`

**Interfaces:**
- Produces (in `apps/forecasting/channels.py`):
  - `CUSTOMER_PT = '10'`
  - `CHANNEL_DEFAULTS: dict[str, dict]` — the approved table above, each value `{'group', 'is_contract_sale', 'followup_rank'}` plus the existing KPI defaults moved from `seed_kpi_config.PT10_DEFAULTS` (`bucket, subtype, counts_customer, include_in_profit`). `seed_kpi_config` imports it (one source).
  - `GROUP_LABELS: dict[str, str]` (group → Arabic label above).
  - `@dataclass(frozen=True) class ChannelInfo: code: str; group: str; group_label: str; label: str; bucket: str; followup_rank: int | None; is_contract_sale: bool; known: bool`
  - `channel(code: str, person_type: str = '10') -> ChannelInfo` — blank code → `ChannelInfo(code='', group='', group_label='', label='', bucket='exclude', followup_rank=None, is_contract_sale=False, known=False)`; unknown non-blank → group `unclassified`, label `«غير مصنف (<code>)»`, bucket `exclude`.
  - `contract_codes() -> tuple[str, ...]` (sorted), `favoured_codes() -> set[str]` (rank 1–2), `rank_map() -> dict[str, int]`, `customer_channels() -> list[ChannelInfo]` (pt 10, ordered by rank then code).
  - `invalidate_cache() -> None`; cache = module dict + `django.core.cache` key `codes:channels:v1`, 10 min; `post_save`/`post_delete` on `ChannelBucketMap` call it (connect in `apps/forecasting/apps.py` ready()).
  - `ensure_defaults() -> int` — when there is no `ChannelBucketMap` row with person_type `'10'`, create the 12 rows from `CHANNEL_DEFAULTS` (label from `SoftechPersonClassif` if present). Readers call it lazily on first load. Returns rows created.
  - `ensure_channel_rows(notify: bool = True) -> list[str]` — for every `SoftechPersonClassif` pair missing from `ChannelBucketMap`: create it (defaults if the code is in `CHANNEL_DEFAULTS` and pt is 10, else group `unclassified`, bucket `exclude`); refresh `label` from SOFTECH on existing rows whose label differs; return new pt-10 unclassified codes; if any and `notify`, send each active admin `Notification.send_to_user(sp, 'system', 'قناة بيع جديدة من SOFTECH', ..., dedup_key=f'code_map_channel_{code}')` (pattern: `apps/discount_approvals/notify.py`). Never raises.
- Model fields: `group = CharField(max_length=20, choices=GROUP_CHOICES, default='unclassified', db_index=True, verbose_name='مجموعة القناة')`, `is_contract_sale = BooleanField(default=False, verbose_name='بيع تعاقد')`, `followup_rank = PositiveSmallIntegerField(null=True, blank=True, verbose_name='أولوية المتابعة')`. `label` stays (SOFTECH label, refreshed by sync).
- Migration data step: for each code in `CHANNEL_DEFAULTS`, `filter(person_type='10', channel=code).update(group=…, is_contract_sale=…, followup_rank=…)` — update only, never create, never touch bucket.

- [ ] **Step 1: Write failing tests** in `apps/tests/test_code_maps_channels.py`:
  - `test_empty_map_lazy_seeds_approved_table`: no rows → `contract_codes() == ('10','11','15','17','33')`; `favoured_codes() == {'91','90','30','99'}`; `channel('30').group == 'permanent'`; `ChannelBucketMap.objects.get(person_type='10', channel='10').bucket == 'credit'`.
  - `test_existing_row_not_reseeded`: create row (10, 91, bucket cash) first → `channel('10').known is False` and no `IntegrityError` (lazy seed runs only on an empty pt-10 set).
  - `test_unknown_code_is_unclassified`: `channel('77')` → group `unclassified`, label `'غير مصنف (77)'`, `is_contract_sale False`, `followup_rank None`.
  - `test_blank_code`: `channel('').group == ''` and `known is False`.
  - `test_migration_update_only_keeps_bucket`: create (10, 10, bucket='insurance', group='unclassified'), call the migration's data function (import it as `apply_channel_meanings(apps_registry_like)` — expose the function at module level taking `ChannelBucketMap` model) → group `contract`, bucket still `insurance`.
  - `test_ensure_channel_rows_creates_and_notifies_once`: `SoftechPersonClassif(ptcode='10', ptclassifcode='77', ptclassifdescr='جديد')` + an admin `StaffProfile` → returns `['77']`, row group `unclassified`, bucket `exclude`; second call returns `[]` and admin has 1 notification.
- [ ] **Step 2: Run** `TEST_DB_NAME=test_codemaps_1 ../../../venv/Scripts/python.exe manage.py test apps.tests.test_code_maps_channels --keepdb -v 1` → FAIL (import error).
- [ ] **Step 3: Implement** model fields, `makemigrations forecasting -n channel_meaning` then add the `RunPython(apply_channel_meanings, noop)` step; `channels.py`; signal hookup; `seed_kpi_config` reads `CHANNEL_DEFAULTS` (delete `PT10_DEFAULTS`, keep behaviour); the sync call wrapped in try/except (log warning).
- [ ] **Step 4: Run** the test module plus `apps.tests.test_kpi_rollup apps.tests.test_insights apps.tests.test_pic_build apps.tests.test_morning_brief` → PASS.
- [ ] **Step 5: Commit** `feat(codes): channel meaning registry on ChannelBucketMap`.

### Task 2: Item-category registry (`MedicineTypeMap`)

**Files:**
- Modify: `apps/config/models.py` (new model `MedicineTypeMap`)
- Create: `apps/config/migrations/0004_medicinetypemap.py` (schema + seed the 8 rows; copy `SystemSetting analytics_excluded_medicine_types` value into `excluded_from_planning` for listed codes)
- Create: `apps/config/item_types.py`
- Modify: `apps/sync/tasks.py` — after the itemstree load (~line 612): `sync_item_types(medicine_names)`
- Test: `apps/tests/test_code_maps_item_types.py`

**Interfaces:**
- Model: `code CharField(max_length=4, unique)`, `label CharField(max_length=100, blank=True)` (SOFTECH `cdldescrar or cdldescr`), `group CharField(max_length=20, choices=GROUP_CHOICES, default='unclassified')`, `is_medicine BooleanField(default=False)`, `excluded_from_planning BooleanField(default=False)`, `updated_at auto_now`. Arabic verbose names; `GROUP_CHOICES` = medicine دواء، cosmetics تجميل، others أخرى، body_building بناء أجسام، veterinary بيطري، gift هدايا عملاء، service خدمات، na غير محدد، unclassified غير مصنف.
- Produces (`apps/config/item_types.py`): `ITEM_TYPE_DEFAULTS` (approved table), `medicine_codes() -> list[str]`, `planning_excluded_codes() -> list[str]`, `label(code: str) -> str` (unknown non-blank → `'غير مصنف (<code>)'`, blank → `''`), `all_types() -> list[MedicineTypeMap]`, `invalidate_cache()`, `ensure_defaults() -> int` (lazy seed on an empty table — survives TransactionTestCase flushes), `sync_item_types(names: dict[str, tuple[str, str]], notify: bool = True) -> list[str]` (upsert labels; new codes → unclassified + admin notification `dedup_key=f'code_map_item_type_{code}'`; never raises). Cache + signals as in Task 1 (`apps/config/apps.py` ready()).

- [ ] **Step 1: Write failing tests**: `test_seeded_meanings` (`medicine_codes() == ['10']`, `planning_excluded_codes() == ['60']`); `test_empty_table_lazy_seeds` (delete all → same answers); `test_unknown_code` (`label('85') == 'غير مصنف (85)'`, `'85' not in medicine_codes()`); `test_owner_flag_edit_visible` (set `70.excluded_from_planning=True` via `.save()` → `planning_excluded_codes() == ['60','70']`); `test_sync_new_code_notifies_once` (`sync_item_types({'85': ('X','س')})` twice → returns `['85']` then `[]`, one notification per admin).
- [ ] **Step 2: Run** `... manage.py test apps.tests.test_code_maps_item_types --keepdb -v 1` → FAIL.
- [ ] **Step 3: Implement** model, migration (`makemigrations config -n medicinetypemap` + RunPython seed), reader, sync call in try/except.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(codes): MedicineTypeMap registry for item categories`.

### Task 3: Channel consumers switch to the reader

**Files:**
- Modify: `apps/followups/models.py:397-432` (remove `_CHANNEL_MAP`, `FAVOURED_CHANNEL_CODES`; `sales_channel_label`, `channel_is_favoured`, `channel_priority` read `channel()`)
- Modify: `apps/followups/views.py:172` (`favoured_codes()`), `:250-260` (priority `Case` built from `rank_map()`; unranked → 9), `:515-525` (channel list from `customer_channels()` ∪ actual codes)
- Modify: `apps/followups/services.py:867` (`favoured_codes()`)
- Modify: `apps/replacement/config.py:55` → `def contract_channels() -> tuple[str, ...]: return channels.contract_codes()`; remove `CONTRACT_CHANNELS` and `NON_REDEMPTION_CHANNELS` constants; update callers `apps/replacement/legs.py:334,677`, `reconstruct.py:157`, `reversal.py:274`, `views.py:499` and `config.py:144` users (grep `NON_REDEMPTION_CHANNELS`) to call `C.contract_channels()`.
- Modify: `apps/chronic/classifier.py:33-53` and `apps/chronic/task_generator.py:19-41` — one function `customer_type(customer, latest_channel: str | None) -> str` in `classifier.py` (task_generator imports it; duplicate sets removed). Mapping: group cash → `'walkin'`, delivery → `'home_delivery'`, contract/employee/insurance/compensation/donation/card → `'b2b'`, anything else or no sale → `'unclassified'`. `latest_channel` = `PurchaseHistory.sales_channel` of the customer's most recent sale; task_generator builds one `{customer_id: channel}` dict for its candidate customers in a single query (`order_by('customer_id', '-invoice_date').distinct('customer_id')`), not per customer.
- Modify: `apps/customers/models.py:183-200` — `customer_type_label`: blank → `'عميل'` (unchanged), else `channel(code).label`; `customer_type_color`: by group (`delivery` blue, `cash` gray, `insurance` green, `unclassified` amber, else gray).
- Test: `apps/tests/test_code_maps_consumers.py`; run existing `test_replacement*`, `test_pic_followups`, `test_callcenter_followup`, `test_followup_autoclose`, chronic tests (grep `apps/tests` for `chronic`).

**Interfaces:** Consumes Task 1 `channel`, `contract_codes`, `favoured_codes`, `rank_map`, `customer_channels`. Produces `apps.replacement.config.contract_channels()` and `apps.chronic.classifier.customer_type(customer, latest_channel)`; `'unclassified'` is a new chronic customer-type value (add to any choices / filter list the chronic view validates against, label «غير مصنف»).

- [ ] **Step 1: Failing tests**: `test_followup_label_uses_softech_meaning` (task channel `'10'` → label `'تعاقدات / آجل'` after seeding with SoftechPersonClassif label, or the row label; `channel_is_favoured` False; `'30'` → favoured True, priority 2); `test_followup_blank_channel_label_is_dash` (`''` → `'—'`); `test_priority_sort_order` (tasks on 91, 30, 10, 15, 77 sorted by_priority → `['91','30','10','15','77']`); `test_replacement_contract_includes_33`; `test_chronic_customer_type` (latest `'91'` → walkin, `'90'` → home_delivery, `'11'` → b2b, `'30'` → unclassified, none → unclassified); `test_customer_type_label_blank_and_known` (`''` → `'عميل'`, `'10'` → row label).
- [ ] **Step 2: Run** `... test apps.tests.test_code_maps_consumers --keepdb` → FAIL.
- [ ] **Step 3: Implement** the switches listed above.
- [ ] **Step 4: Run** the new module + the existing modules listed in Files → PASS (fix tests only where they asserted the old wrong labels, and say which in the commit message).
- [ ] **Step 5: Commit** `refactor(codes): follow-ups, replacement, chronic, customers read the channel registry`.

### Task 4: Item-category consumers switch to the reader

**Files:**
- Modify: `apps/followups/services.py:494` (`item__medicine_type__in=medicine_codes()`)
- Modify: `apps/stock_audit/engine.py:60` (`medicine_type__in=medicine_codes()`)
- Modify: `apps/purchasing/isr_softech.py:51` (default filter = first of `medicine_codes()`, `''` if none — the screen filter is a single code; keep `SCREEN_DEFAULTS` a function or fill it at request time, whichever the file's callers allow), `:236` (`.exclude(medicine_type__in=planning_excluded_codes())`)
- Modify: `apps/purchasing/rate_writer.py:376`, `apps/purchasing/seasonality.py:196` (`.exclude(item__medicine_type__in=planning_excluded_codes())`)
- Modify: `apps/insights/rules.py:141` — `xtypes = planning_excluded_codes()` (the SystemSetting is no longer read; leave the setting row in place, add a one-line comment that `MedicineTypeMap` replaced it)
- Test: `apps/tests/test_code_maps_consumers.py` (append); run `test_isr_softech`, `test_isr_guards`, stock-audit, seasonality, rate-writer and insights tests (grep `apps/tests` for the module names).

**Interfaces:** Consumes Task 2 `medicine_codes()`, `planning_excluded_codes()`.

- [ ] **Step 1: Failing tests**: `test_planning_excludes_follow_registry` (item type `70` included in the seasonality/ISR candidate queryset until `70.excluded_from_planning=True`, then excluded); `test_rate_writer_same_set_as_before` (with seeded registry the rate-writer queryset over items of types 10/60/50 equals the old `.exclude(medicine_type='60')` result — guards the live SOFTECH rate writer from any behaviour change at seed).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the six switches + insights.
- [ ] **Step 4: Run** new + existing listed modules → PASS.
- [ ] **Step 5: Commit** `refactor(codes): planning, refill, stock-audit read MedicineTypeMap`.

### Task 5: API, audit, RBAC and guard tests

**Files:**
- Create: `apps/config/code_maps.py` (views + serializers)
- Modify: `apps/config/urls.py` — `path('code-maps/channels/', …)`, `path('code-maps/channels/<int:pk>/', …)`, `path('code-maps/item-types/', …)`, `path('code-maps/item-types/<int:pk>/', …)` (under `/api/config/`, already module `settings` in `core/middleware/module_access.py`; no middleware change)
- Modify: `apps/audit/models.py` ACTION_CHOICES + `('code_map_changed', 'ترميزات SOFTECH — تعديل')`; create `apps/audit/migrations/0041_code_map_changed_action.py` (renumber if main has moved — check `git ls-tree origin/main apps/audit/migrations/` before committing)
- Test: `apps/tests/test_code_maps_api.py`, `apps/tests/test_code_maps_new_values.py`

**Interfaces:**
- `GET /api/config/code-maps/channels/` → `[{id, code, label, group, group_label, bucket, bucket_label, is_contract_sale, followup_rank, sales_90d}]` for person_type `'10'`, unclassified first then rank, code. `sales_90d` = count of `PurchaseHistory` with `doc_code='115'`, `sales_channel=code`, last 90 days (one grouped query).
- `PATCH …/channels/<pk>/` accepts only `group`, `is_contract_sale`, `followup_rank` (bucket stays in Django admin / KPI config — not editable here; spec: KPI figures do not move).
- `GET /api/config/code-maps/item-types/` → `[{id, code, label, group, group_label, is_medicine, excluded_from_planning, item_count}]` (`item_count` = active `Item` per code, one grouped query); `PATCH` accepts `group`, `is_medicine`, `excluded_from_planning`.
- Permissions: `matrix_permission('settings')` — GET needs `view`, PATCH `edit`. Every PATCH writes `AuditLog.log('code_map_changed', user=…, obj=row, old_data=…, new_data=…, request=request)` and invalidates the reader cache (signals already do).

- [ ] **Step 1: Failing tests** (`test_code_maps_api.py`): list returns 12 channels with `'10'` group `contract`; admin PATCH `group='cash'` on 99 → 200, `channel('99').group == 'cash'` immediately, one `AuditLog` with `action='code_map_changed'` and old/new group; PATCH with `bucket` in body → bucket unchanged; user without settings edit (e.g. `salesperson`) → 403 on PATCH; unauthenticated → 401; item-types list shows `60` excluded; PATCH `excluded_from_planning` audited.
- [ ] **Step 2: Failing tests** (`test_code_maps_new_values.py`): `test_pos_channels_registered` — for every `(name, code)` in `apps.pos_orders.models.CHANNEL_TO_PTCLASSIF`, `channel(code).known` and group equals `{'cash':'cash','delivery':'delivery','contract':'contract','insurance':'insurance','employee':'employee','vip':'vip','permanent':'permanent','compensation':'compensation','donation':'donation','card_receipt':'card'}[name]`; `test_new_channel_flows_unclassified` (pair `10/77` via `ensure_channel_rows`; a follow-up task on 77 lists, label «غير مصنف (77)», not favoured; replacement contract set excludes it; chronic → unclassified; channels API lists it first); `test_new_item_type_flows_unclassified` (type `85` item: not in refill/medicine set, not excluded from planning, API lists it first).
- [ ] **Step 3: Run** both modules → FAIL.
- [ ] **Step 4: Implement** views, urls, audit action + migration.
- [ ] **Step 5: Run** both modules → PASS; also `apps.tests.test_permission_matrix` if present (grep) to confirm no matrix regressions.
- [ ] **Step 6: Commit** `feat(codes): code-maps API with audit and settings RBAC; drift + new-value tests`.

### Task 6: `/code-maps` screen, nav and help

**Files:**
- Create: `frontend/src/pages/CodeMapsPage.jsx` (two tabs «قنوات البيع» / «تصنيف الأصناف»; inline selects/checkboxes save on change via PATCH; unclassified rows on top with a «غير مصنف» badge; `useSortableRows` + `SortTh`, `useGridKeyboard` per review-grid convention; `useHelpTab(tab)`; calm UI — no modals)
- Modify: `frontend/src/api/client.js` (`codeMapsApi.channels()`, `.patchChannel(id, data)`, `.itemTypes()`, `.patchItemType(id, data)`)
- Modify: `frontend/src/App.jsx` — `<Route path="code-maps" element={<RequireRole roles={['admin']}><CodeMapsPage /></RequireRole>} />` beside `settings`
- Modify: `frontend/src/components/navGroups.js` — entry after «الإعدادات»: `{ to: '/code-maps', icon: '🏷️', label: 'ترميزات SOFTECH', roles: ['admin'] }`
- Create: `apps/help/content/code_maps.py`; Modify: `apps/help/content/__init__.py` `MODULE_FILES` (insert `'code_maps'` before `'admin'`)
- Test: `apps/tests/test_help.py` (existing)

**Interfaces:** Consumes Task 5 endpoints and field names.

- [ ] **Step 1: Help content** (AR + EN, `updated: '2026-11-13'`, route `/code-maps`, tabs `channels` / `item-types`): what each column means, that SOFTECH labels come from SOFTECH and refresh on sync, that «غير مصنف» means a new SOFTECH code nobody has classified (it counts as nothing — not contract, not favoured, not medicine, not excluded — until classified), that KPI buckets are not edited here, that every change is audited. Model the file on an existing help module (e.g. `apps/help/content/data_health.py`).
- [ ] **Step 2: Run** `... test apps.tests.test_help --keepdb` → PASS.
- [ ] **Step 3: Build the page, client, route, nav.**
- [ ] **Step 4: Run** `npm run build` in `frontend/` → success, no new warnings from the new files; start the dev preview and check both tabs load, a change saves and survives reload, and RTL layout is sound (screenshot).
- [ ] **Step 5: Commit** `feat(codes): /code-maps screen with help`.

### Task 7: Docs and wrap-up

- [ ] Add to the spec §8 that the static-scan extension for literal `medicine_type` / channel codes is deferred to piece 1's scanner (file is piece 1's), and list the call sites now routed through the readers.
- [ ] Run all piece-4 test modules together once (serially) → PASS; `flake8` (or the repo's lint command, see CI workflow) on changed Python files → clean.
- [ ] Check migration numbers against `origin/main` for `forecasting`, `config`, `audit` (crews/roles sessions may have added some); renumber + fix dependencies if needed.
- [ ] Commit `docs(codes): piece 4 notes`; push branch; open PR to `main` (do not merge).
