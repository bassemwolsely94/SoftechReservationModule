# SOFTECH Screen RPA (روبوت إدخال SOFTECH) — Design

**Date:** 2026-11-16 · **Status:** draft, awaiting owner approval
**Scope:** part 1 of the RPA programme, the SOFTECH side only. Part 2 (Pharma Overseas website and
Ibn Sina app ordering, availability and code capture, expired returns) gets its own design later.

---

## 1. Why

Bulk data reaches the pharmacy as **spreadsheets**: supplier invoices, return lists, branch issue
lists and count results. Today staff get it into SOFTECH with **DataLoad**, a keystroke-replay tool
driven by `.dld` grid templates, or by typing it in. The owner wants an in-house robot that does
DataLoad's job, but sits inside our approval, audit and duplicate-protection system.

The owner chose a **screen robot**, entering data through SOFTECH's real screens, over adding more
direct SQL writers. The main reason this is right for SOFTECH is that its business validations run
**in the PowerBuilder client, not in the database** (`docs/architecture/SOFTECH_PURCHASE_VALIDATIONS.md`).
A robot that types into the screen gets every one of those checks for free. A SQL writer has to copy them.

## 2. Goals, non-goals, anti-goals

**Goals**
- Four screens: **purchase invoice (10)**, **return to supplier (120)**, **إذن الصرف لفرع (branch
  issue, 125)** and **stock count (جرد, producing 50/150)**.
- The flow: upload a spreadsheet → match items and validate → preview → approve → the robot enters
  each document → each document is verified against SOFTECH → a per-document report.
- **Never double post.** That covers a robot retry, a second upload of the same sheet, and the same
  supplier invoice also posted by the existing SQL writer.
- Full audit: who uploaded, who approved, what the robot typed, the SOFTECH document number it got,
  screenshots at each save, and the outcome.
- One robot design that a later screen can join by adding a recipe, not new code.

**Non-goals (this part)**
- Supplier websites and apps (part 2).
- Retiring DataLoad on day one. It stays available until each screen's robot is proven.
- Retiring the direct SQL writer for 10/120. **Both paths stay** (owner decision, 2026-11-16).
- Any new direct SQL write to SOFTECH. The robot only reads SOFTECH through `config/sybase.py`.

**Anti-goals (a failure even if it "works")**
- A document entered twice, or half a document saved and then re-entered.
- The robot "fixing" data on its own: guessing an item, skipping a row, or clicking past a SOFTECH
  warning it does not recognise.
- A robot that only one person can operate or repair.

## 3. Approaches considered

| | Approach | Trade-off | Decision |
|---|---|---|---|
| A | Spreadsheet → our direct SQL writers | Fast and idempotent, but each new screen needs DML capture and re-implemented client validations | Rejected for this programme. The existing 10/120 writer stays as a parallel path. |
| **B** | **Screen robot driving the SOFTECH client** | SOFTECH's own logic runs and it works on any screen. It is fragile and slower, and needs a dedicated PC and careful idempotency. | **Chosen by the owner** |
| C | Shared pipeline, choosing the poster per screen | Least new risk | Not chosen |

## 4. What already exists and is reused (no duplication)

| Need | Existing piece |
|---|---|
| Purchase and return document model | `apps/invoices` `SupplierInvoice` + `InvoiceLine` (doccode 10/120, return linkage to the original purchase) |
| Duplicate check on the supplier invoice number | `apps/invoices/writer.py::check_duplicates` / `find_posted_document` (cust_branch_code + doccode + docnumber2, plus a fuzzy scan) |
| Supplier name and code aliases | `apps/invoices/suppliers.py`, `VendorItemMapping`, `catalog.ItemSupplierLink` |
| Item matching | the unified item-search engine + matching learning (`apps/shortage/learning.py`) |
| Count sheet parse | `apps/stockcount/excel_io.py::parse_count_sheet`, `StockCountSession` |
| Branch issue reads | `apps/transits` (doc 125 mirror `InTransitTransfer`) for read-back verification |
| DataLoad grid precedent | `apps/vouchers/coupons.py::dataload_rows` (`\{ENTER}` / `\{TAB}` / `\{F2}` cells) |
| Writer gating and kill switch | `config/writers.py::writer_allowed` + `WRITER_INSTANCE`; `SOFTECH_READ_ONLY` |
| Write registry | `apps/tests/security/softech_write_manifest.py` (the robot registers as a write site) |
| Preview → apply with expiry | the `SoftechWritePlan` pattern (`apps/insurance/softech_guard.py`) |
| Locks | Postgres advisory locks (7301xxx range) |
| Upload safety | `core/upload_safety` (sha256 duplicate upload) |

## 5. Design

### 5.1 Pieces

1. **Bulk-entry jobs in our app.** A new app, `apps/rpa`.
   - `RpaJob`: one uploaded sheet, for one screen and one branch.
   - `RpaDocument`: one SOFTECH document inside a job, for example one invoice or one issue voucher.
   - `RpaLine`: one row, matched to a `catalog.Item`.
   - `RpaRun`: one robot attempt on one document, with its step log and screenshots.
   - For **10/120**, each `RpaDocument` creates or links a `SupplierInvoice`, so both posting paths
     act on the **same record**. That makes the shared duplicate check automatic, and an invoice
     posted by either path shows as posted to the other.
2. **Screen recipes.** Data (versioned in the DB, editable by an admin) that describes each screen:
   - how to open it;
   - the header fields and their key order;
   - the per-line key sequence (the `.dld` equivalent);
   - how to save;
   - the popups it expects and what to do with each;
   - how to read the assigned document number.

   They are seeded from the owner's existing `.dld` templates.
3. **The robot agent: attended, on the operator's own PC, under their own SOFTECH login** (owner
   decision, 2026-11-16). DataLoad works this way today: whoever owns the task runs it in their own
   SOFTECH session, so the document carries their `usercode`.
   - A small Windows tray program is installed on each operator's PC. The operator opens SOFTECH
     and logs in **themselves**. We never store or type SOFTECH passwords.
   - In `/rpa` the operator presses «تشغيل على جهازي». The agent on that PC picks up **only that
     operator's approved documents**, brings the right SOFTECH window to the front and types.
     While it runs, it shows "hands off the keyboard" and a big **إيقاف** (stop) button, and the
     Esc key also stops it.
   - The agent signs in to our API as the operator, through a device pairing token tied to their
     StaffProfile. It has no database access of its own.
   - **Who is logged in to SOFTECH:** the expected `usercode` comes from the operator's SOFTECH
     identity in `apps/personal` (the `/me` claims). The verifier then checks that the saved
     document's `usercode` matches it.
   - **Stock count rule:** a جرد job can only be run by an operator whose SOFTECH identity is the
     stock count user or a SOFTECH admin. Our server enforces this before handing the job over,
     and the verifier checks it again on the saved document.
   - A dedicated `RPA` SOFTECH user on an unattended PC stays possible later, as a second mode.
     It is not in the first release.
4. **The verifier.** Server side and read-only. After each save it finds the document in SOFTECH by
   our reference and checks the header and every line against what we approved.

### 5.2 How the robot drives PowerBuilder

PowerBuilder DataWindows do not expose cell values to Windows UI Automation reliably. The robot
therefore:
- **types by keystrokes**, the same way DataLoad does (via `pywinauto` keyboard plus win32 window
  focus);
- **watches windows**: the window title and class for the right screen, and any new popup window,
  whose text it reads through win32 and matches against the recipe's known popups;
- **reads results from SOFTECH, not from the screen.** Our verifier is the source of truth for "did
  it save, and what did it save."

**An unknown popup, a lost focus, or a timeout stops that document.** The robot takes a screenshot,
presses nothing further, and the document goes to **needs a person**.

**The existing `.dld` format** (read 2026-11-16 from the owner's folder
`C:\Users\basse\OneDrive\Apps\Dataload Ready Made Files`) is plain UTF-8 text:
- `begindelays…enddelays`: per-cell 0.2 s and per-form 0.25 s delays, plus hourglass waits.
- `beginother`: the **target window title**, for example
  `SofTech Smart Business® - MINI - [إذن صـرف للفــروع]`.
- `beginheader`: the column types (`Key Strokes` / `Data`).
- `begindata`: a tab-separated grid, one row per line.

The branch issue line recipe is `\{F2}` (new line) · item code · `\{ENTER}` `\{ENTER}` · `\{TAB}` ·
expiry `d/m/yy` · `\{TAB}` · qty · `\{ENTER}`×3.

The recipe importer parses `.dld` files directly, so the owner's templates become recipe version 1.
Templates found: اذن الصرف (several copies), جرد 2020 من Excel, إذن إرتجاع من فرع, امر توريد, and
item-card edits. **No purchase invoice or supplier return template is in the folder.**

### 5.3 Never double post

The same idea as rule 3 in CLAUDE.md, applied to a robot:

- **Our reference on every document:** `RPA-<document id>`, typed into a free-text header field
  (notes / remarks; the exact field per screen is a recipe item).
- **Before typing,** the server checks SOFTECH for that reference. For 10/120 it also runs the
  existing `check_duplicates` (supplier + docnumber2). A hit means **already posted**: the document
  is linked and nothing is typed.
- **Claiming:** a document is handed to the robot only by an atomic `approved → in_progress` change
  under an advisory lock, handed only to the agent of the operator who owns it. Each agent works on
  one document at a time. A document can never be claimed by two agents.
- **After a stop mid-document:**
  - the document never goes back to the queue automatically;
  - the verifier looks for the reference;
  - **found** → mark it posted and check that its lines match (a mismatch goes to a person);
  - **not found** → a person decides whether to retry, using the screenshots.
- **The SQL writer path** (10/120) honours the same states. A `SupplierInvoice` whose `RpaDocument`
  is `in_progress` or `needs_person` cannot be pushed by the writer, and the reverse holds too.

### 5.4 Lifecycle of a document

```
uploaded → matched (unmatched rows block) → approved → in_progress → posted (verified)
                                                          ↘ needs_person → retry | posted | cancelled
```

- Approval is per job, by a role that already holds the module right; the uploader cannot approve
  their own job.
- The approved snapshot is frozen. Edits after approval mean a new approval.

### 5.5 Per-screen notes

| Screen | Sheet columns (minimum) | Extra rules |
|---|---|---|
| 10 purchase | supplier, supplier invoice no, date, item, qty, bonus qty, price, discount, expiry | Matching reuses vendor codes. The duplicate check is shared with the writer. |
| 120 return | supplier, original purchase (optional), item, qty, expiry, reason | Over-return check (received − already returned) reused from the writer |
| 125 branch issue | from-store/branch, to-branch, item, qty, expiry | **Three sources** (owner, 2026-11-16): an uploaded Excel sheet, a doc 30 **distribution plan**, or a **stock reshuffle** (transfer requests / the `/batches` rebalance worklist). `RpaDocument` stores a generic source link, and when the 125 is verified the source record is marked as issued, so the plan ledger sees it. Never from store 110; quarantine stores only by explicit choice. |
| جرد stock count | branch, store, item, counted qty (+expiry if the screen asks) | Links to a `StockCountSession` when one exists. Counts against stores 102/103/105 are refused unless the job says so. **The robot saves the count lines but never approves them.** Approval stays a human step inside SOFTECH. SOFTECH already flags any item that moved between save and approval, showing stock at save, stock now and the counted quantity, so we add no freshness cutoff of our own. |

### 5.6 Switches, permissions, audit

- **Switch** `RPA_SOFTECH_ENTRY_ENABLED`, read through `writer_allowed()`. It is OFF by default and
  only ever on for the writer instance. There is a per-screen switch on top: `RpaScreen.enabled`.
- **Dry run:** the robot can run a recipe to the save key and then **cancel** instead of saving. This
  is the default for the first runs of every new recipe.
- **Manifest:** a `WRITE_SITES` entry for the robot, with its tables per screen, the flag,
  the idempotency rule above and the audit trail.
- **Module access:** a new `rpa` module in `MODULE_CHOICES` + `seed_permissions.py`, prefix
  `/api/rpa/` in `MODULE_BY_PREFIX`, `MatrixPermission` on every view, and a separate agent endpoint
  for the robot service account only.
- **Audit:** AuditLog on upload, approve, claim, every save, verify, needs_person and every retry
  decision.
- **Screen:** `/rpa` «روبوت الإدخال», with tabs for upload, jobs, document detail (row matching,
  step log, screenshots, SOFTECH document link) and the robot's health (online, last heartbeat,
  current document). It gets in-app help (Arabic + English).

### 5.7 Calls made by the designer (owner to check)

- **Purchases and returns reuse the full `SupplierInvoice` flow.** A robot upload creates a normal
  `SupplierInvoice` with lines, with the same states and the same review and matching screens as
  OCR invoices. `/rpa` links to that existing review instead of building its own (rule 6). Only
  125 and جرد get matching screens inside `/rpa`.
- **The queue and verifier run on the writer instance only** (`writer_allowed`), and read SOFTECH
  **live** through `config/sybase.py`, never a mirror. A stale mirror could report "not found" for a
  document that did save, and that would lead to a double post. This rule follows the writer
  instance through the VPS cutover.
- **"Verified" compares what we approved:** header fields, item, qty, bonus, price, discount,
  expiry and the line count. SOFTECH's own totals are stored and shown, but **not recomputed or
  matched**. That keeps this module out of pricing logic (CLAUDE.md: stop before pricing changes).
- **Popup rules are owner-approved data.** By default every popup that is a warning or a question
  means **stop**. A recipe may auto-answer a popup only through a versioned rule that a second
  admin approves (four-eyes), with the before and after recorded in the audit. Recipe versions are
  immutable, and each run records the recipe version it used.

## 6. Order of work (proposal)

1. Foundation: models, upload/match/approve, the agent API and device pairing, the verifier, the
   `.dld` importer, the tray agent, and the **إذن الصرف (125)** recipe from the owner's template,
   in dry-run. It goes first because a working template exists and it moves no money.
2. 125 live, then from distribution plans and reshuffles.
3. Stock count (template `جرد 2020 من Excel.dld`), under the stock count user or an admin.
4. Purchase invoice, then return to supplier. Their key sequences have no template, so we record
   them together with the owner: a guided "record one manual entry" step in the recipe editor.

Each step ends with the owner switching that screen on after watching dry runs.

## 7. Left to the builder

- The exact keystroke recipe per screen: from the owner's `.dld` files, confirmed by recording one
  manual entry.
- The free-text header field that carries `RPA-<id>` on each screen.
- Agent packaging, installation and auto-update on staff PCs, and what happens when the SOFTECH
  window is closed or frozen. The agent never logs in to SOFTECH: it asks the operator to.
- Screenshot storage and retention: reuse the data-lifecycle rules, and screenshots are not
  customer data.

## 8. Owner answers (2026-11-16)

- **Login:** the operator's own SOFTECH user. For stock count, only the stock count user or an
  admin. → attended agent on the operator's PC (§5.1 item 3).
- **Purchase and return templates:** none exist. We build the sequences together when we get to
  them (§6 step 4).
- **125 sources:** distribution plans, Excel imports and stock reshuffles (§5.5).
- **Stock count:** SOFTECH flags movement between save and approval itself. The robot saves and
  never approves (§5.5).
- **Robot user:** a dedicated user is possible, but the operator's own user is preferred. The
  dedicated user is deferred.

Still pending: the folder's other `.dld` files are being downloaded by OneDrive. On 2026-11-16
the provider still reported them cloud-only. Read them in step 1.
