# Final-review fix wave — report

Branch `claude/supplier-portal-rpa`, base 13d27f9f. Commits:
- 67733709 fix(rpa-portal): order safety from the final review (C1, I1-I4, M-a..c)
- 4d6078de fix(rpa-agent): handover needs the server's awaiting_submit; history reports every order; pager guard
- d1a28573 feat(rpa-portals): link-with-lines editor, acknowledge, held remainders; help

No migration (no model change; `makemigrations --check --dry-run` → "No changes detected").
No SOFTECH writes, no external site contacted, nothing under `apps/tests/security/` touched, no push.

## Findings

### C1 — placed order dead end / unguarded cancel
- (a) `apps/rpa/portal/queue.py` `may_have_placed()` (~l.769): true when `submitted_seen_at`, `portal_ref`,
  a reason naming an order (`ORDER_REASONS`: history_found, record_failed, history_unmatched,
  submit_seen*, need_check, order_ref_conflict) or `may_have_ordered()` and no clearing history read.
  `resolve` cancel (~l.925) raises `PlacedOrderCancel` (409) unless `confirm_placed_order_cancel` + reason.
- (b) `_hold_lines()` (~l.838): on a confirmed cancel, each buy line gets a `tried` note
  `{supplier, accepted: 0, basket, cancelled, may_have_ordered, portal_ref}` and `chosen_supplier` is cleared
  (only when it is this portal's code). `remaining_qty` is untouched. So no job (`_job_lines`) or order list
  (`send_other`) takes it until a person re-picks (audited pick). Audit row: `held_buylines`,
  `cancelled_portal_ref`. `recording._apply_results` (l.334) ignores `cancelled` notes, so a basket linked
  after such a cancel is still credited exactly once. `serializers.remainder_rows`: `may_have_ordered` rows
  have no one-key `next_supplier`.
- (c) link-with-lines: `resolve` link_order validates person lines with `_person_history_lines()` (supplier
  code + whole packs, else QueueError). `basket_detail` now carries `cancel_needs_confirmation`,
  `suggested_order_ref`, `history_orders` (every order the robot read, for the prefill). UI:
  `frontend/src/pages/rpa/portals/BasketsTab.jsx` `LinkLinesEditor` (inline, no popup): one row per basket
  line, prefilled from the read order or the handed-over `accepted_qty`, stray history rows listed, sent as
  `history_lines` with `order_ref`. The cancel confirmation shows up front when the server says so.
- Job-done note: `_history_jobs()` (queue.py l.354): `_claim_history` takes baskets of `approved` **and**
  `done` jobs, so a basket pulled back to needs_person after its job finished still gets its read.
- Tests (`apps/tests/test_rpa_portal_order_safety.py`): `test_empty_history_cancel_needs_confirmation_and_holds_the_lines`
  (the reviewer's scratch scenario 1), `test_live_basket_stuck_before_history_cancel_needs_confirmation`,
  `test_link_with_person_lines_records_and_clears_the_reason`, `test_history_unmatched_is_reconciled_with_person_lines`,
  `test_cancelled_basket_linked_later_is_credited_once` (also covers the done-job history claim).

### I1 — retried handover / late Submit sighting
- Robot: `rpa_agent/main.py` `report_with_retry` returns the server's answer (dict, else True; False on
  failure); `rpa_agent/client.py` `portal_report` returns the JSON. `runner.py` `handed_over()` + `live()`:
  HANDOVER_MSG only when the answer says `status == 'awaiting_submit'`; otherwise it leaves the review page
  and reports error.
- Server: `report()` (queue.py l.475) takes a late `submit_seen` on **any** closed fill run of the device.
  `_submit_seen_late`: recorded + same ref → no change; recorded + other/no ref → stays recorded with reason
  `submit_seen:<ref>` (needs_person() true; cleared by acknowledge); needs_person already naming the ref →
  no change; otherwise → needs_person as before. Retried handover still closes the run `handover_twice`
  (server unchanged: a person looks).
- Tests: `test_retried_handover_is_not_a_handover_and_late_sighting_is_taken` (scratch scenario 2, via the
  agent API), `test_late_sighting_after_operator_stop_is_taken`, `test_late_sighting_on_recorded_basket`;
  robot `test_retried_handover_refused_by_server_does_not_hand_over`, `test_report_answer_reaches_the_runner`.

### I2 — history read reported `orders[0]`
- Robot `runner.history()`: reports `orders: [{order_ref, date, lines}]` (≤50); `order_ref`/`history_lines`
  only when the plan's own ref matched.
- Server `_history_orders` / `_orders_for` / `_may_be_ours` / `_report_history` (queue.py l.524–597): own
  `portal_ref` wins; else orders whose `portal_key` is on another basket are dropped, and an order counts only
  if it shares a supplier code with this basket or has any unreadable row (or no rows). None → run
  `history_none`; one → `history_found:<ref>` with its lines stored; several → `history_found:a,b` (no
  suggested ref, person picks). The step keeps every order read (audit). Old one-order shape still read.
- `resolve` retry: `confirm_none` while `_history_found_stands()` needs a written reason (audited).
- Tests: `test_history_with_several_orders_picks_only_this_baskets`, `test_history_with_only_other_baskets_orders_is_none`,
  `test_history_order_with_unreadable_row_counts_as_found`, `test_history_old_shape_still_read`; robot
  `test_history_reports_every_order_in_the_window`, updated `test_history_found_and_none`,
  `test_history_keeps_the_plan_order_and_ambiguous_dates`; existing queue test updated to pass a reason.

### I3 — cancel_job vs claim
- `apps/rpa/portal/jobs.py` `cancel_job` (l.209): locks basket rows (`_lock_baskets`, select_for_update),
  re-checks, cancels only pending/ready rows and raises (whole transaction rolled back) when the updated
  count differs. Audit inside the transaction.
- Tests: `test_cancel_job_never_overwrites_a_claimed_basket` (claim injected between lock and update),
  `test_cancel_job_cancels_waiting_baskets`.

### I4 — linked basket stays "needs a person"
- `resolve` link_order clears `needs_person_reason` when the result is `recorded` (old reason in the audit
  row's old_data). New `acknowledge` action (`_acknowledge`, queue.py l.947): recorded + reason only,
  written reason required, rpa.edit, audited. UI `AcknowledgePanel`.
- Tests: `test_link_with_person_lines_records_and_clears_the_reason`, `test_late_sighting_on_recorded_basket`.

### I5 — Order History pagination
- `rpa_agent/portal_web/driver.py` `_paged()` + `order_history()`: a pager (recipe `PAGER`, link/button next
  to the table, never pressed) on the history list while the last row may still be in the window →
  `PortalError` (run error, never "none"); a details pager or a mismatch with `DETAILS_COUNT_LABEL` → an
  extra row `{'sku': '', 'qty': 'more rows than read'}` → server holds it (history_unmatched / found).
  Recipe values marked CONFIRM. Fixtures `order_history.html` / `portal.js` gained page-size / count knobs.
- Tests: `test_history_details_pager_marks_the_order_unreadable`, `test_history_details_count_mismatch_marks_the_order_unreadable`,
  `test_history_list_pager_inside_the_window_is_an_error`.

### M-a / M-b / M-c
- M-a: `buylist.is_known_supplier()` (VendorProfile personcode or SupplierPortal code) checked in `pick` and
  `send_other` (before anything is recorded); `views.buylist_send_other` filename sanitised to
  `[A-Za-z0-9_-]`. Tests: `SupplierCodeTests` (3). Test fixtures now create VendorProfile '30'.
- M-b: approval audit inside the atomic block with `over_need_reasons`, lines, unpriced, limit.
  Test `test_approval_audit_carries_over_need_reasons`.
- M-c: `test_other_buyer_gets_404_on_approve_and_cancel`, `test_four_eyes_through_the_api`.

## Help
`apps/help/content/rpa_portals.py`: baskets and remainders tab text (link-with-lines editor, cancel that may
have ordered, held lines, acknowledge, reason needed for confirm_none over a found order), recorded /
cancelled status text (cancelled → needs_person), FAQ entry, two tour steps (`rpa-portals-link-lines`,
`rpa-portals-acknowledge`), resolve warn updated; `updated` 2026-11-18.

## Commands and results
- Backend (fresh test DB, serial, no --parallel), env `TEST_DB_NAME=test_portal_rpa_fix`:
  `../../../venv/Scripts/python.exe manage.py test apps.tests.test_rpa_portal_api apps.tests.test_rpa_portal_buylist
  apps.tests.test_rpa_portal_jobs apps.tests.test_rpa_portal_models apps.tests.test_rpa_portal_plans
  apps.tests.test_rpa_portal_queue apps.tests.test_rpa_portal_recording apps.tests.test_rpa_portal_skus
  apps.tests.test_rpa_portal_wiring apps.tests.test_rpa_portal_order_safety apps.tests.test_rpa_api
  apps.tests.test_rpa_module apps.tests.test_supply_execution apps.tests.test_help --noinput`
  → `Ran 314 tests in 417.550s  OK`.
  (An earlier keepdb run of the same list showed 11 errors + 1 failure from missing migration-seeded rows
  — the keepdb flush gotcha below — plus one real help failure, a tour `warn.en` over 160 chars, fixed.)
- Robot: `RPA_PORTAL_TEST_BROWSER=msedge <scratch agentvenv>/python -m pytest rpa_agent/portal_web/tests rpa_agent/tests -q`
  → 60 passed (portal_web 31 + rpa_agent/tests 29 incl. the new report-answer test).
- Frontend: `npm run lint` → 0 errors, 185 warnings, none in `pages/rpa/portals`; `npm run build` → built OK.
- `makemigrations --check --dry-run` → No changes detected. `bandit -q -r apps/rpa rpa_agent/portal_web -ll` → nothing (no Medium/High).
- Not run (per brief): `apps.tests.security`.

## Proposed rulings / concerns
- R17 (proposed, I2): an order in the window that is not on another basket and shares no supplier code with
  this basket, with every row readable, is "not this basket's" → the read counts as history_none (retry
  allowed). This is what the finding asks; it relies on Order History codes being read correctly. Any
  unreadable row, empty order, or pager keeps it "found".
- R18 (proposed, C1b): a confirmed cancel of a may-have-placed basket clears chosen_supplier only when it is
  the portal's own code and leaves remaining_qty; the Remainders tab shows no one-key next supplier for such
  lines. A person must pick from the buy list.
- Retried handover: server behaviour kept (run closed `handover_twice`, person looks); an idempotent
  "same handover again → awaiting_submit" was not done (safer: no Submit message on doubt).
- `PAGER` / `DETAILS_COUNT_LABEL` recipe values are guesses (CONFIRM on the real site, with the other locators).
- Test DB gotcha: after a keepdb run that includes `ConcurrentClaimTests` (TransactionTestCase flush), the
  migration-seeded rows (SupplierPortal, RpaScreen) are gone for the next keepdb run; part-1 dropped
  serialized_rollback. The final run below used a fresh DB.
- UI not browser-checked (lint + build only).
