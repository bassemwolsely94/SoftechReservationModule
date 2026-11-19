# Office PC — turn on Postgres query statistics (`pg_stat_statements`)

**Performance stage 1, Task 4.** Spec: `docs/superpowers/specs/2026-11-19-performance-boost-design.md` §6 Stage 1, §9.

## ملخص (عربي)

الخطوات دي بتشغّل «إحصائيات الاستعلامات» في قاعدة بيانات السيرفر علشان نعرف أنهي استعلام
بياخد أكتر وقت فعلاً قبل ما نحسّن أي حاجة. **بتتعمل بعد قفل الصيدلية بس** لأنها محتاجة
إعادة تشغيل خدمة Postgres (السيستم بيقف دقيقة تقريباً). مش بتغيّر أي بيانات، ومش بتلمس SOFTECH.
لو حصلت أي مشكلة، خطوة «التراجع» في الآخر بترجّع كل حاجة زي ما كانت.
بعدها الأمر `manage.py perf_top_queries` بيطلع أتقل الاستعلامات.

## Before you start

- Do this **after closing**. Restarting the Postgres service drops every open connection;
  the app, scheduler and AMI bridge reconnect on their own within a minute.
- You need an **administrator** PowerShell (right-click → Run as administrator).
- A Postgres restart alone is enough. You do **not** need to restart the app. If you ever do,
  stop only `runserver 0.0.0.0:8000`, `run_scheduler` and `run_ami_bridge` — never every
  `runserver` (the UAT server on `:8200` is someone else's).
- Nothing here touches SOFTECH.

## 1. Find and back up `postgresql.conf`

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -d elrezeiky_db -Atc "SHOW config_file;"
```
It prints a path such as `C:\Program Files\PostgreSQL\16\data\postgresql.conf`. Back it up next to itself:
```powershell
$conf = "C:\Program Files\PostgreSQL\16\data\postgresql.conf"   # use the path printed above
Copy-Item $conf "$conf.bak-2026-11-perf"
```

## 2. Add the settings

Open the file in Notepad as administrator (`notepad $conf`) and add these lines **at the end**
(a later line wins over an earlier one, so you do not need to find and edit the old ones):
```
# --- perf stage 1: query statistics ---
shared_preload_libraries = 'pg_stat_statements'
track_io_timing = on
pg_stat_statements.track = top
```
If `shared_preload_libraries` already lists something (it is empty on the office PC today),
keep it and add ours with a comma: `'existing_lib,pg_stat_statements'`.

## 3. Restart the Postgres service

Confirm the service name first, then restart it:
```powershell
Get-Service postgresql*
```
```powershell
Restart-Service postgresql-x64-16
```
`Get-Service postgresql*` should show it `Running` again. If it does **not** start, go to step 6 (undo) at once.

## 4. Create the extension in our database

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -d elrezeiky_db -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
```

## 5. Check it works

From the project folder, after the app has been used for a few minutes:
```powershell
.\venv\Scripts\python.exe manage.py perf_top_queries --limit 5
```
It prints up to five lines (calls, total seconds, mean ms, rows, the start of the SQL).
If it prints `pg_stat_statements is not enabled`, step 2 or 4 did not take — check both.

Other forms:
- `--sort total` (default) — what costs the server the most time overall
- `--sort mean` — the slowest single runs
- `--sort calls` — the most frequent
- `--reset --confirm` — clears the counters (e.g. before measuring one screen)

## 6. Undo

```powershell
Copy-Item "$conf.bak-2026-11-perf" $conf -Force
Restart-Service postgresql-x64-16
```
The extension left in the database does nothing once the library is not preloaded; to remove
it as well: `psql ... -c "DROP EXTENSION IF EXISTS pg_stat_statements;"`.

## Cost

`pg_stat_statements` keeps one row per distinct query shape in shared memory (5 000 by default,
a few MB) and adds well under 1 % CPU. `track_io_timing` adds a clock read per disk block read;
negligible on this hardware. The same settings are in the VPS runbook
(`deploy/LINKDATACENTER_VPS_RUNBOOK.md` §7.3).
