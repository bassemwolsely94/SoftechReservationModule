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

## The bulk EGS sheet (agent version 2)

From version 2 the agent also looks after Invoicer's sheet `ElRezeiky_Bulk_EGS_Items.xlsx`. The server
asks for one of two jobs:

- **Read the current file** (`egs_fetch`): the agent copies the live sheet to a temporary file outside the
  Invoicer folder and uploads the copy. It never opens the live sheet itself, and writes nothing.
- **Write a new version** (`egs_write`): the agent downloads the version and checks its SHA-256. Then:
  - **Preview** (the server's write switch `TAX_EGS_SHEET_AGENT_WRITE_ENABLED` is off, the default): nothing
    is written in the Invoicer folder. The agent only reports what it would do: the live sheet's size and
    hash, whether it is in use, whether the backup folder looks writable.
  - **Write** (switch on, and the job and the download both say `write`): the agent checks the live sheet is
    still the one the server last read (otherwise it refuses: `live_changed`), writes
    `ElRezeiky_Bulk_EGS_Items.new.xlsx` beside it, copies the live sheet to
    `backup\ElRezeiky_Bulk_EGS_Items.<YYYYMMDD-HHMMSS>.xlsx`, and swaps the new file in. If Invoicer or Excel
    holds the sheet, it retries 5 times over about 2 minutes, then reports **busy**, removes the `.new` file
    and leaves the live sheet as it was. Before every swap attempt it reads the live sheet again: if someone
    saved a change while it waited, it refuses (`live_changed`) and keeps that change. Any other failure also
    leaves the live sheet as it was. The server counts a write as done only when the agent read the live
    sheet back as the new version.

The folder comes only from `config.ini`; the server never sends a path. Backups are kept in
`D:\invoicer_mini\backup`, newest 30.

**Signing waits during a sheet job.** The agent does one job at a time. A write held by Invoicer can take
several minutes (retries while reading, backing up and swapping), and a signing job waits behind it. This is
fine while signing through the agent is not live; revisit it before it is.

### Updating the agent on the seal PC (192.168.1.8)

1. Stop the agent: close its console window, or end the scheduled task
   (`Stop-ScheduledTask -TaskName 'ElRezeiky Tax Signing Agent'`).
2. Copy `agent.py` (and `cades.py`, `requirements.txt`, `config.example.ini`) from this folder over the ones
   in `C:\ElRezeikyTaxAgent`. Keep your `config.ini`.
3. Open `C:\ElRezeikyTaxAgent\config.ini` and add this line under `[agent]`:

   ```ini
   invoicer_dir = D:\invoicer_mini
   ```

4. Start the agent again as before (console window and PIN, or `Start-ScheduledTask`). Signing works exactly
   as before. On the panel «ملف أكواد الإيصالات (المحصّل)» the agent now shows as version 2.
5. Press «اقرأ الملف الحالي» once and check the agent log shows `kind=egs_fetch status=done`.

Writing stays a preview until the owner turns the write switch on, on the server.

### Rolling back the sheet

0. **First** ask the owner to turn `TAX_EGS_SHEET_AGENT_WRITE_ENABLED` off on the server. Otherwise the 03:00
   nightly job writes the latest version over the restored file.
   اطلب من المالك إيقاف `TAX_EGS_SHEET_AGENT_WRITE_ENABLED` أولاً — وإلا تكتب مهمة الساعة 3 فجراً أحدث نسخة
   فوق الاسترجاع.
1. Close Excel, and close Invoicer if it is open.
2. In `D:\invoicer_mini\backup`, pick the backup to go back to (the name is the time it was taken).
3. Copy it to `D:\invoicer_mini` and rename it to `ElRezeiky_Bulk_EGS_Items.xlsx`, replacing the live file.
4. Press «اقرأ الملف الحالي» so the server knows what the live sheet is now.

A rollback lasts only while the switch stays off, or until a newer version supersedes it: a restored backup
is one of our own versions, so with the switch on the next write replaces it with the latest.

To roll back the agent itself, copy the previous `agent.py` back and remove nothing else: an older agent
ignores `invoicer_dir`, and the server then offers it signing jobs only.

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
