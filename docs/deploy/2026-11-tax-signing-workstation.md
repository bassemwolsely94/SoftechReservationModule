# Tax seal: setting up the signing workstation (2026-11-07)

The Egyptian Tax Authority (ETA) requires each document to carry a CAdES-BES signature made with the company's eSeal, which is the USB token on office PC **192.168.1.8**. That PC is also the SOFTECH HQ database server, and it runs the current outside tax programs. This page takes you from "nothing installed" to "the smoke test passed".

> **Where this stands**
> - **Tested with a software key and a fake token only.** Nobody has run any of this on the real token or the real PC, and ETA has not seen one of these signatures.
> - **Sending to ETA stays OFF.** Nothing on this page turns it on. `TAX_ETA_SUBMIT_ENABLED` and `TAX_ERECEIPT_SUBMIT_ENABLED` stay `False`.
> - A smoke test signs a harmless random text. It never goes to ETA.

> **Golden rules**
> - **Never paste the PIN, the agent account's password or the agent token into a chat, a file in the repo, or `config.ini`.** The agent refuses to start if `config.ini` holds them.
> - **Find out how many wrong PINs lock this token before you type it anywhere.** The token may lock after only a few. Ask the issuer, or check the vendor tool.
> - **If the agent says the PIN was refused, stop.** Don't restart it until you have confirmed the PIN. It stops itself so the token doesn't lock.
> - Don't unplug the token or touch the outside program during its working hours until step 7 is done.

## How it works

```
 Office PC 192.168.1.8                                 VPS (elrezeikyapp.dawalvry.com)
 ┌────────────────────────────┐                       ┌──────────────────────────────┐
 │ USB token (PIN, key)       │   outbound HTTPS      │ Document waiting to be signed│
 │ agent.py  ─ asks "next?" ──┼──── over the VPN ────▶│ signing-agent/next/          │
 │           ◀─ canonical text┼───────────────────────┤                              │
 │ signs on the token         │                       │                              │
 │           ─ signature ─────┼──────────────────────▶│ signing-agent/jobs/N/result/ │
 └────────────────────────────┘                       │ checks signature + thumbprint│
                                                      └──────────────────────────────┘
```

- The agent always calls out. **Nothing connects in to the PC, and no inbound port is opened.**
- The PIN and the key stay on the PC. The server only sees the signature.
- The agent signs what the server sends, so whoever controls the server can get a text sealed. The agent's log keeps its own record of every job (job id, kind, SHA-256), so a signature can be traced later.

## Step 1: Identify the token (no PIN, read-only)

**When.** Any time, with the token plugged in.

**How.** Copy the folder `deploy/tax_signing_agent` from the repo to `C:\ElRezeikyTaxAgent` on the PC. Open PowerShell **as administrator**:

```powershell
cd C:\ElRezeikyTaxAgent
powershell -ExecutionPolicy Bypass -File .\identify_token.ps1
```

It can take a few minutes, because it searches the Program Files folders. It does not load the token's software, log in, or change anything.

**Send back:** the file `C:\ElRezeikyTaxAgent\token_report.txt`. It has no PIN or key, but it does name your programs and certificates, so send it privately.

**What we are looking for.** The names the script searches for, such as `eps2003csp11.dll` and `eTPKCS11.dll`, come from general knowledge of common tokens. Nobody has seen this token yet, so **the script's output decides**. From the report:

| Section | The question it answers |
|---|---|
| LIKELY CANDIDATES | Which DLL is the token's PKCS#11 module, and is it 32-bit or 64-bit? |
| THIS PC | Which Windows is it, and is Python present? |
| CERTIFICATE sections | Is the seal's certificate visible, and which provider owns it? |
| PROCESSES, SERVICES | What else may be holding the token right now? |

If it finds no candidate, tell us the token's maker, and do not install anything yet.

## Step 2: Install the agent

**Pick Python to match the module's bitness.** A 32-bit DLL needs 32-bit Python, and a 64-bit DLL needs 64-bit Python. This is the most common cause of "cannot load the module". Use Python 3.12 from python.org. If this is Windows Server 2012 R2 or older, current Python versions do not support it, so tell us before installing anything.

```powershell
cd C:\ElRezeikyTaxAgent
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
copy config.example.ini config.ini
```

Install on a quiet hour; it only adds a folder and uses no SOFTECH resources. If the PC has no internet access, tell us and we will prepare the packages for offline install.

**Read the certificate from the token, still with no PIN:**

```powershell
.\venv\Scripts\python.exe agent.py identify --module "<the path from the report>"
```

**Pass looks like:** one token, its label, `PIN state: no warnings reported`, and a certificate with subject, issuer, serial, expiry and thumbprint. Check that the subject is your company and the expiry is in the future. If `CKM_SHA256_RSA_PKCS` and `CKM_RSA_PKCS` both say `no`, stop and send us the output.

**Fill in `config.ini`:** set `pkcs11_module` to the same path, and `thumbprint` to the 40-character thumbprint. Setting the thumbprint matters: with it set, the agent will not try the PIN on any other token. Send us the identify output. It contains no secret.

## Step 3: Self-test on the PC (uses the PIN once)

**When.** A quiet time, when the outside program is not signing. This is one PIN login. A wrong PIN uses up one attempt.

```powershell
.\venv\Scripts\python.exe agent.py selftest
```

It prompts for the PIN without showing it, signs a local text, and checks the result. Nothing is sent anywhere.

**Pass looks like:** `Round 1/1: PASS`, with your company's name and the same thumbprint. This proves the token can produce a signature in the right structure. It does **not** prove ETA accepts it.

**Right after this,** use the outside program for its normal work once, and confirm it still signs and is not asking for its PIN again. See step 7.

## Step 4: Open the path to the server

The agent must reach `https://elrezeikyapp.dawalvry.com` **through the tunnel**, at the VPS's tunnel address **10.50.50.77** (ZeroTier), rather than across the internet at 41.196.0.34. Three things have to be in place. If split DNS (T1–T7 in `docs/security/2026-10-31-network-device-access-design.md` §6.8) is already live on this site, some are already done, so check each one first.

**4.1 The PC must route to the tunnel.** On the PC:

```powershell
Test-NetConnection 10.50.50.77 -Port 443
```

If `TcpTestSucceeded` is `True`, go to 4.3. If not, check the PC's gateway with `ipconfig`. If it isn't the MikroTik (192.168.1.201), add routes that survive a reboot:

```powershell
route -p add 10.50.50.77 mask 255.255.255.255 192.168.1.201
route -p add 10.0.0.77 mask 255.255.255.255 192.168.1.201
```

Windows Firewall on the PC allows outbound traffic by default. Only if outbound blocking is on, add this rule. No inbound rule is needed.

```powershell
New-NetFirewallRule -DisplayName 'ElRezeiky tax agent to VPS' -Direction Outbound -Action Allow -Protocol TCP -RemotePort 443 -RemoteAddress 10.50.50.77,10.0.0.77 -Program 'C:\ElRezeikyTaxAgent\venv\Scripts\python.exe'
```

**4.2 The HQ MikroTik must let this PC out to the VPS.** This is the one firewall rule the path needs. The existing rules were written for the opposite direction (VPS to SOFTECH). Take a backup first, and do not use Safe Mode over ZeroTier, because it reverts when the session drops.

```
/system backup save name=before-tax-agent
/ip firewall filter print where chain=forward
/ip firewall filter add chain=forward src-address=192.168.1.8 dst-address-list=elrezeiky-vps-sources protocol=tcp dst-port=443 action=accept comment="tax signing agent to VPS" place-before=<number of the first drop rule in forward>
/ip firewall nat add chain=srcnat src-address=192.168.1.8 dst-address-list=elrezeiky-vps-sources action=accept comment="tax agent: keep real source address" place-before=0
```

Replies are covered by your established/related rule. The second line keeps the masquerade rules from rewriting this traffic, and the VPS already has a return route to 192.168.1.0/24. Nothing is needed in `ufw` on the VPS, because 443 is already open.

**Undo:** `/ip firewall filter remove [find comment="tax signing agent to VPS"]` and `/ip firewall nat remove [find comment="tax agent: keep real source address"]`.

**4.3 The name must resolve to the tunnel, on this PC.** The TLS certificate belongs to the name, so the agent must use the name and not the IP.

```powershell
Resolve-DnsName elrezeikyapp.dawalvry.com
```

If it shows 41.196.0.34, add this line to `C:\Windows\System32\drivers\etc\hosts` as administrator. It affects this PC only:

```
10.50.50.77  elrezeikyapp.dawalvry.com
```

**Check the whole path:**

```powershell
Invoke-WebRequest -UseBasicParsing https://elrezeikyapp.dawalvry.com/api/public/health/ | Select-Object StatusCode
```

`200` with no certificate warning means the path works.

**Known limit.** If ZeroTier goes down, the VPS's failover to SSTP does not move this name: the agent backs off and documents wait. To switch by hand, change the hosts line to `10.0.0.77`. An automatic switch has not been built.

## Step 5: Set up the server

**Check the code first.** The release on the VPS must include this signing work, which is not on `main` yet. An older release has no agent address (404), or does not accept the agent's sign-in.

The agent needs two things from the server, and both are checked on every request: **its own staff account**, and **the agent token**. Neither one alone is enough.

### 5.1 The agent's own account

> **Read this first: `finalize` is also the permission to send.** The agent needs `tax_invoicing` → `finalize` to collect documents for signing. The same permission lets its holder submit documents to the Tax Authority once sending is switched on. **Whoever knows this account's password can send.** Treat it like the seal's PIN.

1. **Pick the role. This is a decision for you.** Permissions in this system belong to a role, not to one person, and there are ten fixed roles. **There is no role that only this account holds.** Whatever role gets `finalize`, every account with that role can also sign and send. Two choices:
   - **Recommended:** ask the developers for a dedicated role, for example «جهاز التوقيع», held by this account only. That is a small code change: a new role, a migration and a permission seed.
   - **Until then:** use a role that **no person holds today**, and keep it that way. Check the user list first; `viewer` is a candidate if nobody uses it. Do not use `admin`, `supervisor` or `purchasing`. Those roles need two-factor sign-in once it is enforced, and the agent cannot answer a 2FA code. Do not use `accountant`, because that would give every accountant the right to send.
2. **Create the account** in the app's user management, as an admin. Use the username `tax_signing_agent`, the role from step 1, and a long random password from your password manager. Leave two-factor sign-in **off** for this account. It is not a person's account: nobody logs in with it.
3. **Grant `finalize` to that role only.** In the roles and permissions screen, set module «الفواتير الضريبية» (`tax_invoicing`), action `finalize`, for that role. It needs nothing else.
4. **If zone policy is in use for that role:** the agent comes from inside the network, as an unapproved device (zone Z2), because it is not a browser. That role's Z2 row, if it has one, must allow tax invoicing. From outside the network the agent is refused once the zone policy is enforced, which is why step 4 routes it through the tunnel.

**Rotating the password** every 90 days, and whenever someone who knew it leaves:

1. Stop the agent on the PC (close its window, or stop the task).
2. Change the password in the app. This also ends the account's current sessions.
3. Start the agent again and give it the new password. If you leave the agent running, its next renewal is refused. It then stops with `the server refused the username or password … will not try again`. That is expected; start it with the new password.

The agent never retries a refused password, so a mistake costs one attempt, not a locked account.

### 5.2 The agent token and the settings

**Create the agent token on the VPS:**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Add these to the VPS `.env`, once each. The processes refuse to start on a duplicated key.

| Setting | Value |
|---|---|
| `TAX_SIGNING_AGENT_TOKEN` | The value you just generated. At least 32 characters, or every agent is refused. |
| `TAX_SIGNING_CERT_THUMBPRINT` | The thumbprint from `agent.py identify` in step 2 |
| `TAX_SIGNER_CLASS` | `apps.tax_invoicing.signing.AgentSigner` |

Leave `TAX_ETA_SUBMIT_ENABLED`, `TAX_ERECEIPT_SUBMIT_ENABLED` and `TAX_ALLOW_MOCK_SIGNER` as they are. Then restart the web process:

```bash
sudo systemctl restart elrezeiky-web
```

### 5.3 Start the agent

**On the PC,** set `username = tax_signing_agent` under `[server]` in `config.ini`. Then start the agent in a PowerShell window that stays open. It prompts for the agent token, the account's password and the PIN, and shows none of them:

```powershell
cd C:\ElRezeikyTaxAgent
.\venv\Scripts\python.exe agent.py run
```

**Pass looks like:** `agent started`, then `signed in as tax_signing_agent`, then silence. No news is good: it polls every 5 seconds and logs only when something happens. It renews its sign-in by itself every hour. It does not use the PIN until a job arrives.

## Step 6: The smoke test

This is the proof that the real token, the real path and the server work together. Live sending can only be switched on after a pass.

**Start it** with the «اختبار الختم» button: open `/tax-invoicing`, then the Settings tab, section «التوقيع الإلكتروني». That screen is on its own branch and is not on `main` yet. Until it ships, log in as an admin and use the browser's developer console on the app's page (F12, then Console):

```js
fetch('/api/tax-invoicing/signing/smoke-test/', {method: 'POST', credentials: 'include',
  headers: {'X-Requested-With': 'XMLHttpRequest'}}).then(r => r.json()).then(console.log)
```

It answers with a `job_id`. Within seconds the agent's window shows `job=<id> kind=smoke sha256=… signed=yes delivered=yes`. A smoke test nobody answers closes by itself after 15 minutes. It leaves the last result as it was, so press the button again once the agent is running.

**Read the result** in the same section of the screen, or at `https://elrezeikyapp.dawalvry.com/api/tax-invoicing/signing/status/`. The screen shows the main facts; the address also shows the thumbprint.

**Pass looks like:**

| Field | Should be |
|---|---|
| `certification.passed` | `true` |
| `certification.thumbprint` | The same as `TAX_SIGNING_CERT_THUMBPRINT` |
| `certification.subject` | Your company |
| `certification.not_after` | The certificate's expiry, in the future |
| `ready_for_live` | `true`, which **only means the seal is ready**. Sending is still off. |

**Fail looks like:** `certification.passed: false`, with the reason in `certification.detail`. See the failure table. A failed smoke test closes the gate until a later one passes.

Send us the `certification` block. It holds no secret.

## Step 7: The outside program and the token

Both the outside program and the agent need the same token. We don't know how the token behaves when shared, so test it on purpose. Note that a program calling itself "E-Services Tool" connects to SOFTECH from this PC, so it may be one of the programs involved.

**Check first, using the report from step 1:**

- Which programs and services are listed in PROCESSES and SERVICES, and is any of them signing all day, or only when someone presses a button?
- Does the outside program keep the token logged in between signatures, or ask for the PIN each time?
- Do its signing hours overlap with when ours would run?

**What can go wrong, in both directions:**

| Risk | Why | What you would see |
|---|---|---|
| The outside program blocks us | Tokens handle one operation at a time | Agent log says `token is busy`, and retries for up to 40 seconds |
| We disturb the outside program | Our logout at the end of each signature may also end its login on some tokens | It asks for its PIN again, or a signature fails |
| Wrong PIN attempts add up | The attempt counter is on the token, shared by all programs | `EARLIER WRONG PIN ATTEMPTS` in `identify`, and the agent refuses to run |

**Test without disturbing the real work.** Choose a quiet time, with no real batch in progress. Agree on it with whoever uses the program.

1. Run the outside program's own normal test, or sign one real item that is due anyway. Note the time it takes.
2. **Agent idle:** keep `agent.py run` polling for 10 minutes, then repeat step 1. The agent only reads the slot list while idle, so this should change nothing.
3. **Agent signing, outside program idle:** run five rounds, 10 seconds apart. Then repeat step 1. Watch for the outside program asking for its PIN again.

   ```powershell
   .\venv\Scripts\python.exe agent.py selftest --count 5 --pause 10
   ```

4. **Both at once, only if the first three pass:** start `agent.py selftest --count 20 --pause 3`, and during it sign one item in the outside program. A `FAILED - busy` round is acceptable. A failure in the outside program is not.
5. Run `agent.py identify` at the end. `PIN state` must still say `no warnings reported`.

**Send back** the agent output and what the outside program did at each stage. If the outside program is disturbed at step 3, **do not run the agent during its working hours**, and tell us. The options then are separate time windows, or a separate token.

## Failure table

| What you see | Likely cause | What to do |
|---|---|---|
| `cannot load the PKCS#11 module … bitness` | Wrong path, or Python and DLL differ in bitness | Compare the bitness in `token_report.txt` with the Python; reinstall the matching Python |
| `no token is present` | Token unplugged, or the wrong module for this token | Plug it in; try the other candidate from the report. The agent resumes by itself. If it does not see the token come back, restart it. |
| `STOPPED: the token refused the PIN` | Wrong PIN | **Do not restart.** Confirm the PIN from your records. Each try costs an attempt. |
| `STOPPED: the token reports earlier wrong PIN attempts` | Someone or something typed a wrong PIN | Find out who, confirm the PIN, then run `selftest --allow-low-pin-count` once. A correct login usually clears it. |
| `STOPPED: the token reports one PIN attempt left` | Nearly locked | **Stop everything using the token,** including the outside program. Confirm the PIN with the vendor tool. |
| `the PIN is locked` | Too many wrong attempts | Contact the issuer. Outside signing is affected too. |
| `this token does not hold the expected certificate` | Different token plugged in, or the seal was renewed | Plug in the right token. If renewed: update `thumbprint` in `config.ini` and `TAX_SIGNING_CERT_THUMBPRINT`, then repeat the smoke test. |
| `0 signing certificates found` / `No certificate is visible without login` | This token hides certificates until login | Send us the output. The agent checks the certificate before the PIN, so this needs a code change. |
| `expired on …` | The seal expired | Renew with the issuer, then as above. |
| `the token is busy` | The outside program is using it | Occasional is fine: it retries. Constant: see step 7. |
| `cannot reach the server` | Tunnel, route or DNS | Repeat the checks in step 4. The agent backs off by itself, up to every 5 minutes. |
| `cannot reach the server: SSLError` | PC clock wrong, or the name resolves to something else | Check the clock and step 4.3. |
| `the server refused the username or password … will not try again` | Wrong password, or it was rotated (step 5.1) | **Do not restart blindly.** Check the password in your password manager, then start it once. |
| `asks for two-factor sign-in` | 2FA is on for the account, or its role requires it | Use a role outside `admin` / `supervisor` / `purchasing`, with 2FA off for this account (step 5.1). |
| `sign-in … is locked or throttled` | Too many wrong passwords, from anywhere | Find out who tried. An admin can lift the lock, after the password is confirmed. |
| `the server refused sign-in … (403)` | Account disabled, or its role is blocked in this zone | The reason is in the message. Check the account and step 5.1 point 4. |
| `set [server] username` | `config.ini` has no username | Add `username = tax_signing_agent` under `[server]`. |
| `the server refused the agent (401)` | Signed in, but refused even after renewing: the release is older than this work | See step 5. Update the release. |
| `the server refused the agent (403)` | The agent token differs between PC and server or is under 32 characters, or the account's role lacks `finalize` | Check the role's grant (step 5.1). Then set it again on both sides, and restart the web process. |
| `the server answered with a redirect` | `url` in `config.ini` is wrong, or not https | Use exactly `https://elrezeikyapp.dawalvry.com`. |
| `canonical text does not match its SHA-256` | The text changed on its way, or a bug on our side | The agent refused to sign. Send us the job id. |
| Document error: `جهاز الختم لم يرد في الوقت المحدد` | Agent not running, or token busy for over 60 seconds | Start the agent. Jobs that timed out are never signed later; send the document again. |
| Document error: `بصمة شهادة الختم لا تطابق` | `TAX_SIGNING_CERT_THUMBPRINT` differs from the last smoke test | Fix the setting, or repeat the smoke test. |
| Document error: `المستند موقّع بشهادة غير المسجلة` | The agent signed with another certificate | Check which token is plugged in. |
| `smoke test: does not verify`, `does not cover` | A real problem in the signature | Send us `certification.detail`. |

## Confirming against ETA's test environment

The steps above prove the token and the path. Only ETA can prove the signature is acceptable, and these steps come **after** the smoke test passes. Don't run them against production.

1. Get pre-production credentials from ETA for the company (client ID and secret for the ERP) and access to ETA's pre-production portal. Confirm the current addresses with ETA or its SDK site rather than taking them from this page.
2. On a **non-production** setup, set `TAX_ETA_API_BASE_URL` and `TAX_ETA_ID_BASE_URL` to those addresses, with `TAX_ETA_CLIENT_ID` and `TAX_ETA_CLIENT_SECRET`. Turning on sending, even against pre-production, is a separate decision. Discuss it first, because the switch is also what protects production.
3. Ask ETA whether pre-production accepts your real eSeal, or requires a test certificate. If it needs a test token, `TAX_SIGNING_CERT_THUMBPRINT` and the smoke test must be repeated for that token.
4. Submit **one** test invoice built from a real claim, then read its status in the pre-production portal.
5. **Pass:** the document reaches `Valid`, and the portal shows the signature as correct. **Fail:** send us ETA's exact rejection text and the document's UUID.
6. Repeat with one e-receipt, if your e-receipt flow needs the seal at all (see below).

## What remains unverified

Tested so far with a software RSA key, a self-signed certificate and a fake PKCS#11 session:

- The CMS structure was built field by field to ETA's **Digital Signature Format v1.1** (ITIDA, November 2020), and OpenSSL verifies it independently. ETA itself has not seen it.
- Agent behaviour on wrong PIN, token removed, busy token, and server down, as far as a fake token can show it.

Not verified, and only the real token or ETA can settle these:

| Question | Settled by |
|---|---|
| Which middleware, DLL, bitness and mechanisms this token has | Steps 1–2 |
| Whether this token shows its certificate without login | Step 2 |
| Whether real error codes match the standard ones the agent relies on (wrong PIN above all) | Step 3, and only ever by accident: **do not test a wrong PIN on purpose** |
| Whether a token removed and put back is seen without restarting the agent | Plug test in a quiet hour |
| Whether the token works from a background task, or only a logged-in desktop | README, Keeping it running |
| How the token behaves when shared with the outside program | Step 7 |
| Whether the MikroTik rules match the live router (written from project notes, not checked on it) | Step 4 |
| Whether ETA accepts our structure and our hashing: the message digest is one SHA-256 of the canonical UTF-8 text | ETA pre-production |
| Whether ETA's validator accepts the optional issuer-and-serial field we include in signing-certificate-v2 | ETA pre-production |
| Whether the e-receipt API expects this same signature shape | ETA pre-production, and ETA's e-receipt documents |
| The canonical text and the document JSON around the signature | ETA pre-production (outside this page's code) |

**Worth doing later, not built:** an nginx rule limiting `/api/tax-invoicing/signing-agent/` to this PC's address, so a leaked agent token alone is not enough. It depends on step 4 keeping the real source address, so it must wait until that path is confirmed.
