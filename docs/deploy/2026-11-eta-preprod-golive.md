# Tax Authority go-live: pre-production first (2026-11-13)

This is the order the go-live follows. Each step has a pass line. Nothing goes to ETA's **production**
system until pre-production has passed and the owner says yes for that first send.

> **Secrets never go in a chat, a ticket or the repository.** The seal's PIN, ETA client secrets, POS client
> secrets and pre-shared keys are typed by the owner, into the server's environment file or into the agent's prompt
> on the seal PC.

## Before anything: answers only the owner can get

| What | Why | Where to get it |
|---|---|---|
| The token's maker and model, and **how many wrong PINs lock it** | A locked seal stops all sending | The certificate issuer, or the vendor tool on 192.168.1.8 |
| The company tax registration number (RIN) | Every document and every item code carries it | Already on the company's tax card |
| Pre-production access for the company | The test system is separate from production, with its own login | Ask ETA's e-invoicing support or the company's ETA contact |
| Whether pre-production accepts the real eSeal, or needs a test certificate | If it needs a test token, the smoke test is repeated on that token | Same contact |
| For each branch that issues e-receipts: the POS device serial, OS version and model/framework | ETA registers each POS, and each logs in on its own | The branch POS PCs; registered on ETA's portal |

## Step 1: The seal, in place on 192.168.1.8

Follow `docs/deploy/2026-11-tax-signing-workstation.md`, steps 1–6. The seal is used where it is. Its key is never
copied or exported.

1. `identify_token.ps1` (no PIN). Send back `token_report.txt` privately.
2. Install the agent, then the self-test, which uses the PIN once, at a quiet time.
3. Create the agent's own staff account with `tax_invoicing` → `finalize`.
4. Start the agent, then run **Test the seal** from Tax invoicing → Settings.

**Pass:** the settings screen shows a passed certification, with the company's certificate subject and its
thumbprint. Put the thumbprint in `TAX_SIGNING_CERT_THUMBPRINT` on the server.

## Step 2: Register on ETA's pre-production portal (owner)

Pre-production addresses, from ETA's SDK site:

| | Address |
|---|---|
| Registration portal | `https://profile.preprod.eta.gov.eg` |
| Invoicing portal | `https://preprod.invoicing.eta.gov.eg` |
| API (the server sets this itself) | `https://api.preprod.invoicing.eta.gov.eg` |
| Login service (the server sets this itself) | `https://id.preprod.eta.gov.eg` |

1. Register **one ERP system** for the company. ETA shows a client ID and a client secret **once**. Keep the secret
   for step 3 only.
2. Register **one POS device per branch** that will send e-receipts, with its serial, OS version and model. Each gives
   its own client ID, client secret and pre-shared key.

## Step 3: Point the server at pre-production (owner types the secrets)

On the server that sends (the writer instance), in its environment file:

```
TAX_ETA_ENVIRONMENT=preprod
TAX_ETA_CLIENT_ID=<from step 2.1>
TAX_ETA_CLIENT_SECRET=<typed by the owner>
TAX_SIGNER_CLASS=apps.tax_invoicing.signing.AgentSigner
TAX_SIGNING_CERT_THUMBPRINT=<from step 1>
```

For each branch POS, the client ID and serial go in Tax invoicing → Receipts → Branch setup. The secret and the
pre-shared key go in the environment file under the variable names that screen asks for.

Restart, then Tax invoicing → **ETA codes** → *Authority system* → **Test login**.

**Pass:** "تم الدخول لمنظومة المصلحة بنجاح", and the badge says pre-production.

## Step 4: One item code, one invoice and one receipt, in pre-production

Turn on, in pre-production only, one switch at a time: `TAX_ETA_CODING_ENABLED`, then `TAX_ETA_SUBMIT_ENABLED`, then
`TAX_ERECEIPT_SUBMIT_ENABLED` and the branch's *enabled* flag.

1. **Item code:** ETA codes → pick one item → *Prepare requests* → send → *Refresh status*. Pass: ETA's portal
   shows the request. Approval is up to ETA's staff, and can take days.
2. **One claim invoice:** approve one invoice built from a real claim whose items all have approved codes, then
   send it. Pass: it reaches *Valid*. Fail: send us ETA's exact message and the document's UUID.
3. **One branch receipt:** issue and send one receipt from one branch. Pass: *Accepted*.

Each failure tells us which field name or format ETA wants. We fix it in code and send again. The open questions are
`internalID`, `signatureType`, the receipt body, and the return type `r`.

## Step 5: Production

Only after step 4 passes, and only when the owner says yes at that moment:

```
TAX_ETA_ENVIRONMENT=production
TAX_ETA_CLIENT_ID / TAX_ETA_CLIENT_SECRET = the production ERP's
TAX_ETA_PRODUCTION_ALLOWED=True
```

The first live invoice and the first live receipt are each sent with the owner's explicit yes. Receipts go on
branch by branch. Each branch's *enabled* flag stays off until its own first receipt is approved.

## Switches

| Switch | Default | Opens |
|---|---|---|
| `TAX_ETA_ENVIRONMENT` | empty, so nothing is reachable | `preprod` or `production` |
| `TAX_ETA_CODING_ENABLED` | False | Sending item-code requests |
| `TAX_ETA_SUBMIT_ENABLED` | False | Sending invoices and notes |
| `TAX_ERECEIPT_SUBMIT_ENABLED` | False | Sending receipts, for branches whose *enabled* flag is on |
| `TAX_ETA_PRODUCTION_ALLOWED` | False | Any send to production; pre-production does not need it |

Every switch counts only on the writer instance (`WRITER_INSTANCE=True`).
