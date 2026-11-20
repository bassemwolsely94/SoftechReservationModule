# Finance GL — decide parked journal groups by pattern (short design)

Approved by the owner 2026-11-20 ("Yes, go ahead").

## Why
Importing finance's 2026 journals parked 3,587 *mixed* groups in the exceptions inbox: groups whose
accounts include both manual accounts and accounts the drafting engine fills from SOFTECH. Today each
is decided alone, and "include" exists only as the CLI flag `--include-mixed KEY`. A few patterns make
up most of them (e.g. card receivable 1321/1329 vs card sales 6006 in the cash book: 1,266 groups), so
an accountant should be able to settle a whole pattern at once.

## Goals / non-goals / anti-goals
- Goal: list the open `mixed_manual_entry` exceptions grouped by pattern, and let an accountant
  import all of a pattern as drafts or ignore all of it with a reason.
- Non-goal: approving drafts (still one by one through normal approval), saved rules that decide
  future imports, anything for other exception kinds.
- Anti-goals: nothing approved, nothing written to SOFTECH, no decision without a person, no
  decision on a pattern whose membership changed since the screen loaded.

## Approaches
1. **Pattern view in the inbox + bulk decide endpoint (picked).** Pattern computed at read time.
2. CLI-only `--include-pattern`: cheaper, but accountants cannot use it.
3. Saved pattern rules applied by future imports: automatic decisions nobody reviews; not needed for a
   one-time cleanup.

## Design
- **Pattern key** = book + sorted manual accounts + sorted SOFTECH-fed accounts, from the exception's
  stored `proposed_lines` and the current fed set (`plan2_adapter.softech_fed_account_codes`). The
  link account (2354) is left out of the key.
- **GET** `/api/finance/gl/exceptions/mixed-patterns/` → per pattern: key, book, manual accounts,
  SOFTECH accounts, count, debit total, first/last date, three sample descriptions. Permission VIEW.
- **POST** `/api/finance/gl/exceptions/mixed-patterns/decide/` `{pattern, decision: import|ignore,
  expected_count, note}` → 409 `count_changed` when the open count differs. `import`: per exception,
  `save_draft` from the stored lines (each line keeps its branch; book, date, description from the
  source doc; source_type `manual_import`, source_key = the group key) and `settle_parked_manual_entry`
  in one transaction; a refused group is reported, others continue. `ignore`: note required, same
  status/audit as «تجاهل». One summary audit row. Permission CREATE.
- **Screen**: in ExceptionsTab, when the kind filter is «قيد يدوي مختلط», a «حسب النمط» view: sortable,
  keyboard grid; each row has «استيراد الكل كقيود» and «تجاهل الكل»; inline confirm showing the count
  (ignore asks for the reason inline). No modal.
- Help (AR + EN) for the new view; perf budget for the list endpoint; view, permission and
  business-rule tests.

## Left to the builder
Batch size per request, exact wording, sample selection.
