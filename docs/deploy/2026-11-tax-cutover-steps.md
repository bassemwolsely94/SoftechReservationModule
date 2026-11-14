# Tax (ETA) at cutover — office → LDC VPS (2026-11-14)

Adds the tax module to `docs/GO_LIVE_CHECKLIST.md` W0–W9. Every tax **sending** flag goes through `writer_allowed`,
so W1 (office becomes a reader) already stops office sending. This page covers what W1 does not.

Today (2026-11-14) the office `.env` talks to ETA's **pre-production** system: `TAX_ETA_ENVIRONMENT=preprod`,
`TAX_ERECEIPT_SUBMIT_ENABLED=True`, `TAX_ETA_CODING_ENABLED=True`, a stand-in signer
(`TAX_SIGNER_CLASS=…MockSigner`, `TAX_ALLOW_MOCK_SIGNER=True`) for receipt tests, and the ETA history read logins.
**Nothing has been sent to ETA production.** The cutover does not change that: production sending stays a separate,
later owner decision.

## W1 — office becomes a reader (add to the PowerShell block's checks)

The history reader is **not** a writer flag (it reads ETA, it never writes SOFTECH), so W1 does not stop it. Two
servers reading the same ETA login share one rate allowance and fill two databases. On every office `.env`:

```
TAX_ETA_READ_PREPROD_ENABLED=False
TAX_ETA_READ_PRODUCTION_ENABLED=False
```

## W3 — tax drain (add beside the POS / ISR / invoice drain)

All must be **zero** on the office before W4. If not: stop and ask; never copy the database with any of these open.

| What | Where to look | Must be |
|---|---|---|
| Tax documents being sent or unsure | Tax invoicing → Documents, status «جارٍ الإرسال» (`submitting`) or «نتيجة غير مؤكدة» (`uncertain`) | 0 |
| Branch receipts being sent or unsure | Tax invoicing → Receipts, status `submitting` / `uncertain`; each branch row shows no open attempt | 0 |
| Item-code requests in flight | ETA codes tab: `sending` / `uncertain` | 0 (`submitted` is fine: ETA holds it, refresh continues on the VPS) |
| Signing jobs | `TaxSigningJob` `pending` / `claimed` (Settings → electronic signature) | 0 |
| History rounds | Settings → «سجل المصلحة — التحميل»: no round running (both read switches already off from W1) | idle |

```
venv\Scripts\python manage.py shell -c "from apps.tax_invoicing.models import *; print(TaxDocument.objects.filter(status__in=['submitting','uncertain']).count(), TaxReceipt.objects.filter(status__in=['submitting','uncertain']).count(), TaxCodeRequest.objects.filter(status__in=['sending','uncertain']).count(), TaxSigningJob.objects.filter(status__in=['pending','claimed']).count())"
```
Expected: `0 0 0 0`.

## W5 — the database copy carries the tax state

`pg_dump` → restore copies, and nothing needs re-entering:
- issuer details and the accountant's confirmations, item tax profiles (36k+), GPC bricks, code requests;
- **each branch's receipt chain** (`TaxReceiptBranchConfig.last_uuid`, `chain_start`, `send_from`): the VPS continues
  every chain exactly where the office stopped. The office must not issue a receipt after W3 — that is why W3 drains;
- the ETA history mirror (`EtaMirror*`, windows, round state);
- the signing certification record and the agent's staff account.

**Test-only branch mappings** (`test_env = preprod`, today: Ain Shams 150 on Invoicer's test device 2VA0280VY1) are
copied as they are. They keep working only against the test system, and a real (production) setup refuses to send
while test receipts remain. Before the first **production** receipt of such a branch: Receipts → branch setup →
«إنهاء الإعداد التجريبي» (reason) — it puts the test receipts back to ready and clears the test device.

## W6 — the VPS `.env`: tax keys (names only; values typed by the owner, never in chat or the repo)

| Key | VPS value at W6 |
|---|---|
| `TAX_ETA_ENVIRONMENT` | `preprod` (same as the office today). `production` only by a later owner decision |
| `TAX_ETA_CLIENT_ID`, `TAX_ETA_CLIENT_SECRET` | the ERP login for the environment above (preprod today) |
| `TAX_ETA_API_BASE_URL`, `TAX_ETA_ID_BASE_URL`, `TAX_ETA_CA_BUNDLE` | empty (the published addresses and the public certificate roots work) |
| `TAX_POS_SECRET_PREPROD_3` (and any other `secret_env` / `preshared_key_env` names in Receipts → branch setup) | the device secrets, same names as on the office |
| `TAX_SIGNER_CLASS` | `apps.tax_invoicing.signing.AgentSigner` once the seal agent is connected; until then the office value |
| `TAX_ALLOW_MOCK_SIGNER` | the office value (test system only; the code refuses it against production) |
| `TAX_SIGNING_AGENT_TOKEN` | **the same token** the agent on 192.168.1.8 presents (otherwise the agent is refused) |
| `TAX_SIGNING_CERT_THUMBPRINT`, `TAX_SIGNING_WAIT_SECONDS` | the office values |
| `TAX_ETA_READ_PREPROD_CLIENT_ID` / `_SECRET` | optional (preprod falls back to `TAX_ETA_CLIENT_*` when the server is on preprod) |
| `TAX_ETA_READ_PRODUCTION_CLIENT_ID` / `_SECRET` | the history-reader ERP registration made for us on the production portal (never Invoicer's) |
| `TAX_ETA_READ_PREPROD_ENABLED`, `TAX_ETA_READ_PRODUCTION_ENABLED` | `False` at W6; turned on in W7 |
| `TAX_ETA_HISTORY_START` | `2022-06-01` |
| `TAX_ETA_SUBMIT_ENABLED`, `TAX_ERECEIPT_SUBMIT_ENABLED`, `TAX_ETA_CODING_ENABLED`, `TAX_ETA_PRODUCTION_ALLOWED` | `False` at W6 (writer flags; W7 turns them on one at a time) |

## W7 — tax flags in the one-at-a-time order (after the SOFTECH writers)

Tax flags never write SOFTECH; they go **last**, after every SOFTECH writer is read back. One at a time, each with a
check:

1. `TAX_ETA_READ_PREPROD_ENABLED=True` (and production read when the owner wants production history) → Settings →
   «سجل المصلحة — التحميل» shows a round, the freshness bar moves.
2. `TAX_ETA_CODING_ENABLED=True` → ETA codes → «تحديث الحالة من المصلحة» answers (refresh of requests ETA already holds).
3. `TAX_ERECEIPT_SUBMIT_ENABLED=True` → only if receipts were being tested on the office; one test receipt on the
   test system, «استعلام من المصلحة» reads it back.
4. `TAX_ETA_SUBMIT_ENABLED=True` → only once the seal agent passes «اختبار الختم» on the VPS.
5. `TAX_ETA_PRODUCTION_ALLOWED` stays **False**. Production sending is the owner's yes, at that moment, per document
   kind — not part of the cutover.

## The signing agent on 192.168.1.8

Its `config.ini` already points at `https://elrezeikyapp.dawalvry.com` (the VPS, through the tunnel at 10.50.50.77),
so its settings do not change. On cutover day:
- the VPS `.env` needs the **same** `TAX_SIGNING_AGENT_TOKEN` the agent presents, and its staff account (copied by W5)
  must still have `tax_invoicing → finalize`;
- restart the agent after W6, so it logs in to the VPS afresh (it waits by itself while the server is unreachable);
- Settings → electronic signature → «اختبار الختم» on the VPS; pass = the company certificate and the thumbprint in
  `TAX_SIGNING_CERT_THUMBPRINT`.

## Rollback

If the VPS can't carry the day: tax sending was already drained, so switching back loses no receipt. List any tax
action taken on the VPS since W5 from its audit log (`TaxAuditEvent`) before switching back, as for the rest.
