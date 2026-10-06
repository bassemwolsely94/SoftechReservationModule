# SofTech ASE 12.5 — Install MDA Monitoring Tables (to capture the full purchase-Save SQL)

**Why:** the supplier-invoice writeback is blocked by SofTech's encrypted `tr_stktrans` trigger
(error 2732). To learn exactly what the native Save does (full `insert into stktransm/stktrans`
statements + any session setup), we must read the server's SQL-text pipe (`master..monSysSQLText`).
That MDA table is **not installed** on this server, and `dbcc sqltext` truncates long statements.
This runbook installs MDA (one-time, DBA/`sa`) so we can capture the complete SQL.

**Risk:** low & reversible. Installing MDA only adds proxy tables in `master`. The monitoring
configs are dynamic and can be turned off after. No SofTech business data is touched.

---

## Do this ONCE on the SofTech database server (as `sa`)

### 1. Install the MDA tables (server host, sybase OS account, `$SYBASE` set)
The install script ships with ASE. On this ASE 12.5 it is under the ASE scripts dir, e.g.:
- Windows: `%SYBASE%\ASE-12_5\scripts\installmontables`
- Unix:    `$SYBASE/$SYBASE_ASE/scripts/installmontables`

Run it against the server (replace `<SERVER>` and the `sa` password):
```
isql -Usa -P<sa_password> -S<SERVER> -i "%SYBASE%\ASE-12_5\scripts\installmontables"
```
This creates `monSysSQLText`, `monProcessSQLText`, `monProcess`, etc. in `master`.

### 2. Grant mon_role to the login we connect with
The app connects as the `SYBASE_USER` in our `.env`. Grant it monitoring rights (then that login
must reconnect — our command opens a fresh connection each run, so nothing else needed):
```
sp_role "grant", mon_role, <SYBASE_USER>
```
(If we connect as `sa`, still run this — `mon_role` is required to read the mon tables.)

### 3. Enable the SQL-text pipe (dynamic — no restart on 12.5.0.3+)
```
sp_configure "enable monitoring", 1
sp_configure "max SQL text monitored", 16384
sp_configure "sql text pipe active", 1
sp_configure "sql text pipe max messages", 20000
```
> If `sp_configure` reports any of these as **static** on this exact build, a one-time ASE
> restart is needed for that value to take effect. `enable monitoring` and the pipe settings
> are normally dynamic.

### 4. Verify
```
sp_help monSysSQLText          -- table exists
select count(*) from master..monSysSQLText   -- returns a number (0+), not an error
```

---

## Then tell me — I run the capture (no further server changes needed)
```
python manage.py capture_save_sql --spid 0 --seconds 180 --profile prod
```
You do **one** purchase Save during the window. `monSysSQLText` returns the **full, untruncated**
batches (reassembled by SPID + BatchID + SequenceInBatch), so we get the complete
`insert into stktransm (...) values (...)` and each `insert into stktrans (...)`, plus any
temp-table / `set` setup the client does before them. I then diff that against what our writer
produces and close the gap.

## Turn monitoring back off afterwards (optional)
```
sp_configure "sql text pipe active", 0
sp_configure "enable monitoring", 0
```
(The MDA tables can stay installed — harmless.)

---
### What we already know the Save does (from the dbcc capture, 2026-07-02)
`begin tran` → dup-guard (`select count(*) from stktransm where cust_branch_code,doccode='10',
docwritedate,docnumber2`) → per-item `select count(*) from stkbal` + `select sum(itemqty) from
stkbalexpiry` → **insert(s)** (the part we still need in full) → writes `temp_r_stk` (the
on-screen `doctext` blob) → `commit tran`.
