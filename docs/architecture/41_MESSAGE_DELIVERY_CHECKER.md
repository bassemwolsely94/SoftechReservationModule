# 41 — Message delivery checker (OTP / portal links)

Status: ✅ BUILT 2026-11-25. Owner asked for "a checker that checks if the OTP or voucher code was actually
sent". Read-only. No SOFTECH involvement.

## How we know

Meta answers every WhatsApp Cloud-API send with receipts on our webhook: sent → delivered → read, or failed
with an error code. `apps/whatsapp/webhook._handle_status_update` writes them on `WAMessage`. A record that
keeps the message's id (`wamid`) can therefore be checked.

| Record | New field | Set by |
|---|---|---|
| `VoucherOTP` | `wamid`; `sent_via` = `whatsapp_api` (Meta accepted the send) or `qr` (not sent; QR / wa.me at the counter) | `vouchers.views.generate_otp` (migration `vouchers/0010`) |
| `PortalLogin` | `wamid` | `portal.services.send_magic_link` (migration `portal/0002`) |

`apps/whatsapp/delivery.status(wamid)` maps a message to one state:

| State | Meaning |
|---|---|
| `not_sent` | never handed to WhatsApp (no `wamid`) |
| `pending` | handed over, no receipt yet |
| `sent` | Meta accepted it (single tick) |
| `delivered` | reached the phone (double tick) |
| `read` | opened (only when the customer has read receipts on) |
| `failed` | Meta could not deliver it, with the error code and reason |
| `no_receipt` | accepted but no "delivered" after 2 minutes |

The OTP digits and the login link are never stored: the inbox keeps the template name or a placeholder.

## Where it shows

- **Redemption screen** (desktop `/vouchers` step 3, and mobile `/m/vouchers`): `OtpDeliveryStatus` polls
  `GET /api/vouchers/vouchers/<id>/otp-status/?otp_id=` every 3 seconds until there is a final answer (at most
  3 minutes). On failed / no receipt / not sent it tells staff to show the QR.
- **Daily check** at 07:10 (`check_message_delivery --notify`; switch `MESSAGE_DELIVERY_CHECK_ENABLED`) covers
  yesterday's OTPs and portal links:
  - counts by state and the delivery rate;
  - the ones that failed, got no receipt, or were never sent (phones masked);
  - **webhook silence**: we sent at least 5 messages in 2 hours and none got any receipt. That means Meta's
    receipts are not reaching us, so "no receipt" says nothing about the customers.
- The in-app notice `message_delivery` (monitoring feed) goes to `COUPON_DIGEST_ROLES`, once a day, and only
  when something did not arrive.

## Limits

- "Delivered" proves the message reached the phone, not that the customer read it. "Read" depends on the
  customer's read-receipt setting.
- Receipts need Meta to reach our webhook. On the VPS that means the public HTTPS webhook URL set in Meta.
- There is no SMS fallback (no SMS provider yet). Gift-coupon serials are paper and are not sent by us.

Tests: `apps/tests/test_message_delivery.py` covers the states, webhook silence, the OTP flow (sent and
failed), the portal link, the report and notice, and the command.
