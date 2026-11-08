# Tax signing agent

Runs on the PC that holds the eSeal USB token. It pulls canonical documents from the server over
outbound HTTPS, signs each one on the token (CAdES-BES, SHA-256), and returns the signature. The PIN
and the private key never leave this PC.

**Status:** tested with a software key and a fake PKCS#11 session only. It has never run against the
real token. Full owner steps: [docs/deploy/2026-11-tax-signing-workstation.md](../../docs/deploy/2026-11-tax-signing-workstation.md).

| File | What it is |
|---|---|
| `identify_token.ps1` | Read-only report of middleware, certificates, readers and programs. No PIN. Run this first. |
| `agent.py` | `identify` (no PIN), `selftest` (PIN, local only), `run [--once]`. |
| `cades.py` | Exact copy of `apps/tax_invoicing/cades.py`. A test fails if the two differ. Do not edit it here. |
| `requirements.txt` | Python packages. Python and the PKCS#11 DLL must have the same bitness. |
| `config.example.ini` | Copy to `config.ini`. It holds no secrets, and the agent refuses to start if it does. |

## Exit codes

| Code | Meaning | Restart it automatically? |
|---|---|---|
| 0 | Done, or `--once` found nothing to do | Yes |
| 1 | `--once`: the job failed and the reason went to the server | Yes |
| 2 | **Stopped on purpose:** PIN refused, wrong or expired certificate, no usable mechanism | **No.** A restart could use up PIN attempts |
| 3 | `--once`: no token present | Yes |
| 4 | Configuration problem | No |
| 5 | The server refused the agent: wrong password, 2FA, locked account, 401/403, redirect, wrong address | **No.** A restart with a wrong password counts toward the account lock |
| 6 | `--once`: server unreachable | Yes |

`run` without `--once` waits by itself for a missing token or an unreachable server. It only exits on
2, 4 or 5.

## Keeping it running

**Start with a console window.** Run `python agent.py run` in a window that stays open, and type the
PIN at the prompt. The PIN then exists only in that process's memory. The cost is that after a reboot
someone has to start it and type the PIN again. Signing simply waits until then, and documents show
the "seal did not answer" error.

**Unattended start, only if the owner accepts the trade-off.** A task can start the agent at boot, but
it can only get the PIN from an environment variable. Windows stores that variable unencrypted in the
registry, so anyone with administrator rights on this PC can read it. This PC is also the SOFTECH HQ
database server. To do it, in an administrator PowerShell:

1. Create a dedicated local user, for example `taxagent`, with a strong password.
2. Log in as that user once. In its own PowerShell, run the three commands below. They ask for the
   values without showing them, and store them for that user only. The second is the password of the
   agent's staff account in the app (`tax_signing_agent`), not of this Windows user:

   ```powershell
   [Environment]::SetEnvironmentVariable('TAX_TOKEN_PIN', [Net.NetworkCredential]::new('', (Read-Host -AsSecureString 'PIN')).Password, 'User')
   [Environment]::SetEnvironmentVariable('TAX_AGENT_PASSWORD', [Net.NetworkCredential]::new('', (Read-Host -AsSecureString 'Agent account password')).Password, 'User')
   [Environment]::SetEnvironmentVariable('TAX_SIGNING_AGENT_TOKEN', [Net.NetworkCredential]::new('', (Read-Host -AsSecureString 'Agent token')).Password, 'User')
   ```

   When the account's password is rotated, run the second command again, then restart the task.

3. Create a task that starts at boot, as that user, with no restart on failure (see exit code 2):

   ```powershell
   $action = New-ScheduledTaskAction -Execute 'C:\ElRezeikyTaxAgent\venv\Scripts\python.exe' -Argument 'agent.py run' -WorkingDirectory 'C:\ElRezeikyTaxAgent'
   $trigger = New-ScheduledTaskTrigger -AtStartup
   $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries
   Register-ScheduledTask -TaskName 'ElRezeiky Tax Signing Agent' -Action $action -Trigger $trigger -Settings $settings -User 'taxagent' -Password (Read-Host 'taxagent password')
   ```

**Not verified:** some token middleware only works in a logged-in user's desktop session, not in a
background task. Run the task, then the smoke test, before relying on it. If the token is not visible
from the task, stay with the console window.
