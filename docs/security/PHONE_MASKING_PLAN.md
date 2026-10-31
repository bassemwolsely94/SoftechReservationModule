# Customer phone numbers outside the customers screens — plan (Batch 5b)

Status: **built 2026-10-31 (Batch 5b).** The owner approved every recommendation D1–D8 as written,
with one adjustment to D8 (below). Written from a code audit of every API response that returns a
customer phone outside `apps/customers`. Sites marked ✓ were re-checked by hand.

What was built:
- `apps/customers/access.py` gained `record_phones_visible` / `record_phone` (the D2–D4 record rule),
  `customer_phone` (B-2 per customer) and `mask_payload` (nested dicts; drops wa.me links).
- `apps/customers/phone_mask.py` holds the `RecordPhoneMask` / `CustomerPhoneMask` serializer mixins,
  applied to 24 serializers. 43 view calls now pass the request, so the mixins apply.
- Not branch-scoped, so numbers are for the all-branch roles only: vouchers, the WhatsApp inbox,
  PBX call sessions, referral leads.
- Tests: `test_phone_canary_sweep.py` (39 leaks → 0; baseline = drivers' and channel accounts' own
  numbers) and `test_phone_rules.py` (D1, D2, D4, D5, D6, D8, the full-number rule, no over-masking).

**D8 adjustment:** a referral lead has no "staff member who added it" — the referring *customer*
submits it. So lead numbers show to the all-branch roles only.

## The rule we are extending (owner decision B-2, `apps/customers/access.py`)

- Staff see a customer's **full number** only for **their own branches' customers** (`is_own`: the
  customer's home branch is one of theirs, or a branch-less customer they created).
- Any customer can be **found by typing the full number** (10+ digits); what comes back is masked
  (`mask()`: last digits only) unless the customer is theirs.
- `can_see_customer_phone = False` on a staff profile → **every** number masked for that person.
- All-branch roles (admin, call center, purchasing, supervisor, quality manager) see everything.

Today only the customers screens, the universal search (`/api/search/`) and the analytics customer
search apply this. Everything below does not.

## How we will prove it (built first)

A **phone canary sweep**, reusing the Batch 5 canary planter: a customer of branch A with a known
number, plus the records that carry a phone (reservations, delivery orders, follow-ups, vouchers,
calls, campaign messages, leads, conversations). Every GET route, plus the detail and lookup routes
listed below, is called as:

1. a branch-B pharmacist holding every module action — the full number must never appear;
2. the same with `can_see_customer_phone = False` on their **own** customers — must never appear;
3. an admin — must appear (positive control).

Routes where the full number is operationally required are listed in a reviewed baseline, each with
its reason, like the other sweeps. That baseline is effectively the list of decisions below.

## Part 1 — clear fixes (no owner decision needed)

Highest risk first. "Mask" = `access.mask_dict` / `phones_visible` exactly as the customers screens do.

| # | Where | Today | Fix |
|---|---|---|---|
| 1 ✓ | `customers/<id>/pos-summary/`, `/receipt/`, `/patient-profile/` | Any id, raw `phone`, `phone_alt`, WhatsApp links. Only the list is scoped. | Mask. The record still opens, because POS must serve a walk-in. |
| 2 ✓ | `loyalty/customers/<id>/softech-balance/` | Any id (customers view gate only) returns `customer_phone`. | Mask. |
| 3 ✓ | `callcenter/calls/lookup/?phone=` | Matches the **tail of whatever is typed, no minimum length**, so typing `7` lists up to 10 customers with full `phone` and `phone_alt`. Reaches the read-only viewer role. | Require 10+ digits (the B-2 full-phone rule) for branch roles. Mask non-own results. |
| 4 | `delivery/customer-profile/?phone=` | Matches on 9 digits; also returns `phone_alt`, which was not typed. | 10+ digits; mask `phone_alt` unless own. |
| 5 | `delivery/customers/<id>/locations/`, `locations/<pk>/` | Any customer's saved addresses and their `delivery_phone`. | Same rule as #1: mask unless own. |
| 6 | `replacement/…/patient-sales/?pic=` | 8-digit tail match; returns `phone` even when the match was on another field. | 10+ digits; mask. |
| 7 | `demand/erp-lookup/` | Any PIC returns the SOFTECH phone; phone search is `LIKE %x%`. | Mask for branch roles. Phone search needs 10+ digits. |
| 8 | Vouchers: `assignments`, `redemptions`, documents | Unscoped. The document response sends the **raw number next to its own masked copy**. Only print masks. | Drop the raw field and mask for branch roles. OTP still works: it uses the number the operator typed. |
| 9 | `analytics/customers/` top customers, `analytics/churn/` | Sales are now own-branch, but buyers whose home branch is elsewhere are shown unmasked. | Mask non-own. |
| 10 | `delivery/csat-report/` low scores | Unscoped; includes `customer_phone`. | Mask. It is a report; nobody calls from it. |
| 11 | Follow-ups `whatsapp_url` / `whatsapp_url_with_message`, `upsell-message` | `phone` is masked when `can_see_customer_phone = False`, but the WhatsApp link still contains the full number. | Apply the same flag to the links: no link when the phone is hidden. |
| 12 | Refill-reminder overview | Already masked; branch-scoped in Batch 5. | None; covered by the sweep. |

Estimated size: one batch, similar to Batch 5 part 2.

## Part 2 — needs your decision first

**D1. The live-call pop-up (PBX).** ✓ Every logged-in user's browser joins the "all agents" channel,
so every incoming caller's number and matched customer is pushed to everyone (pharmacists, riders,
viewers), whether or not they ever open the call screen.
*Recommendation:* only call-center module holders (and staff with a configured extension) join it.
Nobody else receives calls.

**D2. A number needed to serve your own branch's record.** Reservations, delivery orders, follow-up
calls, POS "share on WhatsApp" and today's follow-ups all need the customer's number to call or
message them. The customer's *home* branch may be a different branch from the one handling the
record.
*Recommendation:* if you can see the record (your branch's reservation, order or follow-up), you
see the number needed to serve it. The B-2 home-branch rule applies to browsing customers, not to
serving your own branch's work.

**D3. Staff with "can't see phone numbers" (`can_see_customer_phone = False`) on operational screens.**
Masking the number also breaks the call and WhatsApp buttons, because they are built from it.
*Options:* (a) hide the number and the buttons for those staff; (b) keep the buttons through a
server-side "open WhatsApp / call" link that never shows the number and is logged.
*Recommendation:* (a) now; (b) later if those staff need to contact customers.

**D4. Reservations: salesperson and viewer.** Today they see the full number in the reservation
list and detail, but print and export hide it from them. That is inconsistent.
*Recommendation:* follow D2 (own-branch staff who handle reservations see it), but mask for the
read-only viewer role.

**D5. Delivery riders from another branch.** A rider assigned another branch's order needs the
recipient's number.
*Recommendation:* keep the full number for orders assigned to that rider. That is the delivery
rule from Batch 5 part 1.

**D6. Campaign message lists.** Pharmacists hold read-only campaigns access and can read every
recipient's number and WhatsApp link in a campaign.
*Recommendation:* only people who can send or approve campaigns see numbers; read-only access is
masked.

**D7. Call-center inbox screens for the viewer role** (WhatsApp, omni, PBX session lists).
The viewer role holds read-only call-center access; the inbox is now branch-scoped (Batch 5), but
it still shows full numbers.
*Recommendation:* mask for viewer. Agents (all-branch roles) are unaffected.

**D8. Referral leads.** Leads are prospects, not customers yet, and have no home branch. Any
customers-view holder sees every lead's number.
*Recommendation:* leads list masked except for the staff member who added the lead and the
all-branch roles.

## Out of scope

- Numbers stored inside old notification texts (they name the customer and number for the branch
  that must call). They stay; new ones follow D2.
- SOFTECH itself; nothing here writes to it.
- Screenshots: masking is the control (B-2).

## Order of work

1. Phone canary sweep (red today), Part 1 fixes, tests and help text: one batch.
2. Your answers to D1–D8, then Part 2 as a second, smaller batch.
