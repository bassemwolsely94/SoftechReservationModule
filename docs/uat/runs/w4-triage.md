# W4 exposure — results (2026-11-17)

Suite: `frontend/uat/exposure/` (rules in `rules.js`, each citing its source). Files here hold PICs and
last-3 digits only.

| run | result | counts? |
|---|---|---|
| 1 | 387 passed / 3 failed, 0 findings | **no** — shared backend 8200 refused connections 02:37–02:55, ~260 tests scanned nothing |
| 2 | 386 / 4, 0 findings | **no** — saved sessions die after 1 h (SIMPLE_JWT access 1 h + refresh rotation/blacklist); reference-only number check blind to non-reference customers |
| 3 | 397 / 3 (2.8 h, heavy.ps1), 32 raw findings → `w4-findings.jsonl` | yes, after triage below |
| verify | 37 / 1, targeted rerun of every test that produced a finding, with detector fixes → `w4-verify-findings.jsonl` | confirms triage |

## Triage of run 3's 32 raw findings

| raw | verdict |
|---|---|
| 7 × P0 phone — phoneHidden, reservations Excel export (5 numbers) + `GET /api/reservations/<id>/print/` (#71, 70, 64, 30, 12, 3) | **real** (verify re-found all 7) |
| 8 × P0 phone — viewer@B and viewer (A), `/followups` → `/api/followups/tasks/grouped/` customer.phone / whatsapp_phone (384 and 798 numbers; 4 field paths each) | **real**, 2 issues (verify re-found all 8) |
| 9 × P0 phone — `/api/config/pharmacy/` whatsapp_number on reservation detail screens | detector false positive (the pharmacy's own number); excluded |
| 3 × P0 phone — `/api/delivery/drivers/` results[].mobile | detector false positive (driver = staff); excluded |
| 2 × P0 branch — restricted `/transfers` TR-000005 | false positive: supplying branch 3 is the user's, decision 3 allows it; `transferSides` read transfers with an expired admin session; now signs in via API |
| 3 × P3 phone — restricted call-center lookup of branch-B customers masked | false positive: B-2 masks another branch's customer; over-mask now checked only for customers of branches the user sees |

## Real P0s (owner)
1. **phoneHidden sees full numbers in reservation exports and receipts.** `apps/reservations/views.py`
   `_PII_ROLES` role check (`_bulk_export`, `print_receipt`, `share_whatsapp`) ignores
   `can_see_customer_phone` (D3). Not covered by `access.py`.
2. **Viewers see every follow-up customer's number.** `apps/followups/views.py:87-99`
   `get_serializer_context` gates on role/`can_see_customer_phone` only, not
   `access.record_phones_visible`, so D4/D7 viewer masking never applies (viewer@B 384, viewer A 798 numbers).

## Not a leak, still worth a look
- Same follow-ups gate lets admin/call_center/**supervisor** bypass `can_see_customer_phone`; no UAT user
  has that combination, so untested.
- `phoneRule` returns `decision` for insurance and for rider-assigned delivery numbers (D5); no decision
  finding fired in run 3 (no matching reference numbers seen there).
- Failures were timeouts, not exposure: customer 360 page (viewer@B), phoneHidden `/m/shortage`, phoneHidden
  full-phone search, viewer other-branch detail records (verify). Looping tests now get 10 min.

## Harness notes (lib/config not changed, per the brief)
- `lib/page.js` `gotoSettled` throws when `page.goto` itself times out instead of returning `slow`.
- Playwright clears `test-results-uat/` (incl. findings.jsonl) each run; HTML report folder sits inside it.
- `login.setup.js` states outlive the 1 h access token; any suite > 1 h silently goes signed-out.
