# ElRezeiky Pharmacy Extension — Project Context

## What this project is
An existing, production-oriented Django/DRF + React/Vite + PostgreSQL extension that sits
above the legacy SOFTECH Pharmacy ERP (Sybase ASE). This is NOT a greenfield app — always
inspect the current repo before writing code. Do not unnecessarily rewrite working
functionality.

## Architecture principle
- SOFTECH = ERP / accounting / legacy transactional backbone. Never bypass it or write to it
  outside our established, tested SOFTECH POS discount/posting methodology.
- This extension = operational intelligence, sales, customer experience, workflow layer.
- We already have a working indirect POS: order created here → cashier screen → multi-step
  checkout → synced/posted to SOFTECH via our existing integration methodology.
- The long-term product is "ElRezeiky Sales & Commerce OS": an operational layer that makes
  the pharmacy faster and smarter without becoming "SOFTECH with a nicer UI."

## Non-negotiable rules (apply to every phase, every session)
1. Preserve SOFTECH integrity — never manipulate SOFTECH transactional data outside the
   established integration methodology.
2. Financial accuracy is deterministic and testable — no fuzzy/AI-decided discounts or totals.
3. Every SOFTECH write/posting workflow must be idempotent. Never allow double posting.
4. Pharmacy safety always beats sales — never let an upsell/promotion override a safety flag.
5. Do not trust SOFTECH active-ingredient/product data as clean. No automatic substitution
   until it's explicitly verified (see Phase 7).
6. Reuse existing order, transfer, customer, reservation, notification, and POS infrastructure.
   Don't create parallel/duplicate business logic.
7. Backend owns business rules. React displays and interacts with decisions; it does not make
   them.
8. Every discount, offer override, return, cancellation, stock reservation, and SOFTECH
   interaction must be auditable (who/what/when/why/before-after).
9. Enforce permissions server-side. Never rely on a hidden frontend button as authorization.
10. Never use an LLM to independently decide final totals, inventory deduction, discount
    amounts, or clinical substitutions — deterministic rules only.
11. UI must stay calm — reduce clicks and cognitive load, don't add popups/modals for common
    actions.

## Execution rules for every implementation batch
For every batch of work:
1. State what you're changing and why.
2. List affected files.
3. Make the change.
4. Add/update migrations if needed.
5. Add/update tests.
5b. Update the in-app help (`apps/help/content/<module>.py`, Arabic + English) for every new or
    changed screen, tab or status, and bump that screen's `updated` date; pages with tabs call
    `useHelpTab(tab)`. `apps/tests/test_help.py` fails when a route has no help. See
    docs/architecture/28_IN_APP_HELP.md.
6. Run relevant tests, lint, and build checks.
7. Check for regressions in existing functionality.
8. Summarize the result.
9. Propose the next logical batch — don't silently keep going into scope not yet approved.

Stop and ask before: schema changes that affect SOFTECH sync, any change to discount/pricing
calculation logic, anything touching payment or checkout completion, and anything that could
cause a double-post to SOFTECH.

## Security definition of done for a new module or app
A new app, screen group or API prefix is not done until each item below is true. The security
sweeps in `apps/tests/security/` catch new routes automatically; these are the per-module items
they can't. (Round-2 plan, docs/security/2026-11-05-full-project-test-plan.md.)
1. **Access:** its API prefix is mapped in `core/middleware/module_access.py` (`MODULE_BY_PREFIX`,
   or `EXEMPT_PREFIXES` / `READ_OPEN_PREFIXES` with a comment naming its own gate). Every view has
   a module permission stronger than `IsAuthenticated` (`MatrixPermission` / `matrix_permission`),
   or a reasoned entry on the open-to-all-staff list. New modules get a `MODULE_CHOICES` +
   `seed_permissions.py` row; `PERMISSION_MATRIX.md` is regenerated.
2. **Branches:** branch-level data goes through `core/branch_scope` (or the code says why it is
   company-level and who may see it). The canary planter can build its models (not in `skipped`).
3. **SOFTECH:** reads only through `config/sybase.py`; any write is registered in
   `apps/tests/security/softech_write_manifest.py` with flag (default OFF, in `config/writers.py`),
   dry-run default, idempotency guard and audit — or stop and ask.
4. **Privacy:** phone numbers through `apps/customers/access.py` masking; no secret or phone in
   logs or error text (`core/errors.public_error`); exports through `core/export_safety.py`.
5. **Tests:** view + permission tests and a business-rule test for its money/stock logic.
6. **Suppressions:** no new `# nosec` / `# noqa` or baseline line without a written reason.
