# Security Suite — Batch 1 (SQL injection) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** No value a user can influence is pasted into SQL text. Every user-reachable site in
`baselines/sql_from_text.txt` is parameterised and proven by a test. Every remaining line is either:
- reviewed internal-only, kept with a `# reason:`; or
- a SOFTECH write path, handed to Batch 2 (needs the owner's OK).

**Architecture:**
- Values move out of the SQL string into bound parameters: `cur.execute(sql, params)`, which `config/sybase.py` `CursorWrapper` runs as a JDBC PreparedStatement.
- A reusable `RecordingSybase` test double captures every `(sql, params)` a request sends. A test can then fire SQL-injection payloads through the real HTTP endpoint and assert that the payload lands in the params, never in the SQL text.

**Spec:** [design](../specs/2026-10-26-full-security-test-suite-design.md) · harness: [Batch 0 plan](2026-10-26-security-suite-batch-0-harness.md) · guide: [TEST_SUITE.md](../../security/TEST_SUITE.md)

## Global Constraints

- Batch 0 constraints apply (Django runner, `TEST_DB_NAME=test_elrezeiky_security --keepdb`, no SOFTECH/HTTP in tests, no commits unless asked).
- **SOFTECH reads only.** Any site that INSERTs/UPDATEs/DELETEs SOFTECH is NOT changed here: it gets an `# Owner: Batch 2 (write path — needs owner OK)` block in the baseline.
- Result sets must not change: same columns, same rows, same order.
- IN-lists are chunked at **400** bound parameters. That size is proven live in `discount_approvals/replication.py` and `finance/queries/sybase_reconciliation.py`; stock count chunked at 500 before.
- Dates stay as the same text the code sent before (`'YYYY-MM-DD 00:00:00'`), just bound instead of pasted. Values are also validated at the edge (serializer/view) where the field has a fixed shape (digits, ISO date). This is defence in depth, never a replacement for binding.
- Each fixed site's line is deleted from `sql_from_text.txt` (the ratchet enforces it).

## Review Focus

1. **The payload survives inside the parameter but a second query re-pastes it.** For example, a value read back from SOFTECH and re-inserted into SQL. → each endpoint test asserts on *every* captured statement, not just the first.
2. **Empty or None lists produce `IN ()`,** which is a Sybase syntax error. → test empty, one-item and 401-item lists.
3. **Placeholder/param count mismatch** (an off-by-one when optional clauses are added). → `RecordingSybase` asserts `sql.count('?') == len(params)` on every call.
4. **Arabic and non-ASCII codes.** Bound strings must reach `setString` unchanged. → test with an Arabic category value.
5. **A validation rule that rejects real data.** For example, branch codes with a leading zero, or alphanumeric item codes like `IT001`. → validation tests use real-shaped codes.

---

### Task 1: `RecordingSybase` test double

**Files:**
- Create: `apps/tests/security/sql_recorder.py`
- Test: `apps/tests/security/test_sql_recorder.py`

**Interfaces — Produces:**
- `RecordingSybase(rows=None)`: context manager.
  - Patches `config.sybase.get_sybase_connection` and `get_branch_connection` to return a fake connection whose `cursor().execute(sql, params=None)` records `(sql, list(params or []))` in `.calls`.
  - `fetchall()` returns `rows` (default `[]`). `fetchone()` returns the first row or `None`.
  - Asserts `sql.count('?') == len(params)` on every execute.
- `assert_payload_bound(testcase, calls, payload)`: fails if `payload` occurs in any `sql`, or does not occur in any params value.

- [ ] **Step 1: Write the tests.**
  - `test_records_sql_and_params`
  - `test_placeholder_count_mismatch_raises`
  - `test_assert_payload_bound_fails_when_pasted`
  - `test_assert_payload_bound_passes_when_bound`
- [ ] **Step 2:** Run, expect ImportError → implement → run, expect PASS.

### Task 2: Stock count (`apps/stockcount/engine.py`)

**Files:**
- Modify: `apps/stockcount/engine.py`
  - Templates: replace `'{branch}'`, `{doccodes}`, `'{date_from} 00:00:00'`, `'{date_to}'`, `'{user_code}'`, `'{category_filter}'` and `({item_codes})` with `?` markers.
  - `_run(sql, params=None)`.
  - Chunk 500 → 400.
- Modify: `apps/stockcount/serializers.py`. In `StockCountSessionCreateSerializer.validate`:
  - `branch_code` must exist as a `Branch.softech_branch_id`.
  - `doccodes` must be from the supported set in the module docstring: `10, 25, 30, 50, 80, 115, 125, 150`.
  - `item_codes_filter` entries must match `^[0-9A-Za-z\-]{1,20}$`.
  - Keep the existing rules.
- Test: `apps/tests/security/test_sqli_stockcount.py`

- [ ] **Step 1: Write the failing tests.**
  - Engine level, with `RecordingSybase`:
    - `fetch_transaction_items` with payload `"1' OR '1'='1"` in `branch_code`, `user_code` and each doccode: payload bound, never pasted.
    - `fetch_full_stock` with the payload in `category_filter`.
    - `fetch_stock_balance` / `fetch_filtered_stock` with the payload as an item code, and with 401 codes (→ 2 statements, each ≤ 400 params).
    - Empty list → no SQL sent.
    - An Arabic category round-trips.
  - HTTP level:
    - POST `/api/stockcount/sessions/` as an admin with an injection `user_code_filter` and a bad doccode `"10') --"` → 400 from the serializer.
    - POST `preview-items` with a valid payload-free request → 200, and every captured statement passes `assert_payload_bound` for the user filter.
- [ ] **Step 2:** Run → FAIL (payload found in SQL).
- [ ] **Step 3:** Implement (engine + serializer).
- [ ] **Step 4:** Run → PASS. Remove the 4 `apps/stockcount/engine.py::…` lines from `sql_from_text.txt`. Run `test_static_guards` → PASS.

### Task 3: Near-expiry and incentives reads (`apps/incentives/engine.py`)

**Files:**
- Modify: `apps/incentives/engine.py`
  - `fetch_near_expiry_stock`: `store_codes` / `item_codes` / quarantine IN-lists and the cutoff date become params; chunk item codes at 400.
  - `_fetch_rows`, `_fetch_cross_period_returns`: whatever they interpolate becomes params (read the code first).
- Modify: `apps/incentives/views.py` (`NearExpiryStockView.list`):
  - reject codes not matching `^[0-9A-Za-z\-]{1,20}$` → 400;
  - cap at 2,000 item codes.
- Test: `apps/tests/security/test_sqli_incentives.py`

- [ ] **Step 1: Write the failing tests.**
  - GET `/api/incentives/near-expiry-stock/?store_codes=101','x&item_codes=1' OR '1'='1` → 400 (validation).
  - Engine call with the payload → bound.
  - The `_fetch_rows` / `_fetch_cross_period_returns` payload tests. Their parameters come from what the code reads; a test feeds a crafted value at the outermost function argument.
  - Empty, 1 and 401 item codes.
- [ ] **Step 2–4:** As in Task 2. Remove the 3 incentives lines from the baseline.

### Task 4: Remaining user-reachable read sites (class A from the triage)

The triage (subagent, 2026-10-26) classifies every non-command site as:
- **A** user-reachable
- **B** internal-only
- **C** SOFTECH write path
- **U** unsure

For **each A site that is a read**, repeat the Task 2 pattern:
- one test file per app, `apps/tests/security/test_sqli_<app>.py`
- payload through the real endpoint where one exists, else at the outermost function the endpoint calls
- parameterise, delete the baseline line

**U sites** are read until classified. Write-path A sites go to Task 5's Batch 2 block, flagged **HIGH**.

### Task 5: Annotate what stays

Rewrite `sql_from_text.txt` into labelled blocks. Every remaining line sits under one header:
- `# reason: internal-only — <values> (<file:line evidence>)` — class B, one block per file.
- `# reason: management command — operator CLI only, not HTTP-reachable; reviewed 2026-10-26` — the commands, as one block.
- `# Owner: Batch 2 (SOFTECH write path — needs owner OK)`, with sub-notes for user-influenced values. HIGH ones first.

Add a guard test, `test_sql_baseline_lines_are_all_explained`: every non-comment line in `sql_from_text.txt` must sit below a `# reason:` or `# Owner: Batch 2` header.

### Task 6: Verify and hand over

- [ ] `apps.tests.security` + `test_endpoint_sweep` + every touched app's existing tests → green.
- [ ] Full suite → no new failures compared with the Batch 0 final run.
- [ ] Update `TEST_SUITE.md`: counts, plus the `RecordingSybase` pattern for future SQL.
- [ ] Update the in-app help for stock count / near-expiry only if user-visible messages change (new 400 texts). Arabic + English, bump `updated`.
- [ ] Fresh reviewer, one fix pass, then report:
  - what was fixed
  - what Batch 2 inherits
  - rulings
