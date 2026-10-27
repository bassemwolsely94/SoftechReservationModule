# PIC creation study (read-only)

Status: probe built, NOT yet run against SOFTECH. Owner decision 2026-10-26 (POS speed wave, piece 4).

## Purpose
Today a new customer is created in SOFTECH's own screen (slow), and our POS «إضافة جديد» tab saves to
PostgreSQL only, so it produces no PIC. Before any create-PIC writer is designed we need to know, from
SOFTECH itself, what a native customer row looks like: required columns, defaults, triggers, how the
PIC number is allocated, and how long a new PIC takes to reach the branch nodes.

## Hard limits
- **No trial inserts of any kind, no rollback probe, no temp tables.** There is no safe SOFTECH test
  server. The command issues `SELECT` statements and catalogue reads only (a unit test with a fake cursor
  asserts every statement is a read).
- The create-PIC writer is **deferred until a safe SOFTECH test target exists and the owner approves the
  findings below.** When it comes: minimum fields, idempotent (client token), read-back verified, audited,
  kill-switch default OFF, dry-run first.
- New PICs continue to be created in SOFTECH during this wave. Our Add tab never writes to SOFTECH.

## What the probe reads
| Section | Reads |
|---|---|
| C1 | `syscolumns`/`sysobjects`: columns of `localcustomers`, NOT NULL flag, whether a default exists |
| C2 | every table with a `phcode` / `picphcode` / `pphcode` column, and its NOT NULL-without-default columns |
| C3 | triggers (names only) on those tables — bodies are read by an operator with `sp_helptext` in a SOFTECH client |
| C4 | the 50 newest customers (`SET ROWCOUNT` + `ORDER BY trans_time DESC`): per branch prefix the highest serial and the gaps |
| C5 | with `--branch-nodes`: how many of those 50 codes each branch node already holds (replication lag) |

Only PIC codes are selected. Names, phones and any other personal data are never read and never written
to the report.

## How to run (operator, on a machine that can reach SOFTECH; kill-switch `SOFTECH_READ_ONLY` may stay ON)
```
venv/Scripts/python.exe manage.py investigate_pic_create                 # HQ only
venv/Scripts/python.exe manage.py investigate_pic_create --branch-nodes  # + replication check
```
Output: console and `scratch/pic_create_probe.txt` (git-ignored). Paste the result under Findings.

## Findings
_To be filled from the operator's run._

- `localcustomers` required columns / defaults:
- Other PIC-carrying tables a native create must also fill:
- Triggers and what they do (`sp_helptext`):
- PIC allocation rule (prefix, serial source, gaps, concurrency):
- Replication lag HQ → branch nodes:
- Open questions for the owner before a writer is designed:
