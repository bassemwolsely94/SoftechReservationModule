# Supplier Portal RPA (روبوت مواقع الموردين) — Design

**Date:** 2026-11-16 · **Status:** draft, awaiting owner approval
**Scope:** part 2 of the RPA programme: ordering and expired-item returns on the **Pharma Overseas
website** (SOFTECH supplier 565) and the **Ibn Sina mobile app** (supplier 260, run inside BlueStacks).
Part 1 (the SOFTECH screen robot) is `docs/superpowers/specs/2026-11-16-softech-screen-rpa-design.md`
on branch `claude/softech-rpa`. This part extends its app, devices and agent. It does not copy them.

---

## 1. Why

Buyers order from the two biggest suppliers by hand, one item at a time, on a website and on a phone
app. Each item means searching, adding it to the cart, reading the stock message, adjusting the
quantity and moving on. Expired returns on the same website are typed in the same way.

The owner wants this faster, and wants three things to come out of it:

- **Orders go out in baskets of 9–10 items**, so that supplier invoices are not crowded.
- **Each item's status on the supplier side is recorded while ordering**: in stock, short or out,
  how much the supplier will take, its price, its bonus and its expiry.
- **The supplier's own product code is captured** for every item ordered. SOFTECH holds almost none
  of them: 565 has 10,166 item links in `itemssuppliers` but only 22 have a `suppitemcode`, and Pharma
  Overseas invoices do not print the code. With the codes, later data entry (OCR invoices, CSV
  import, return files) matches by code instead of by fuzzy name.

Expired returns come second. They use the stock in store 105 together with each batch's own expiry
date and lot number.

## 2. Goals, non-goals, anti-goals

**Goals**
- **Ordering on Pharma Overseas** (first) and on **Ibn Sina** (later): the server builds the baskets,
  the robot fills each one on the supplier's side, a person presses Submit, and the robot records the
  supplier's order number.
- **Recording the supplier's answer for every item**: stock status, the quantity accepted, price,
  discount, bonus, the supplier's expiry, and the supplier's code or exact product name. This feeds
  the existing `/supply` availability inbox and price comparison.
- **Shortages go back to the buyer.** An item the supplier is short on returns to the buyer's list as
  **«الباقي»** (the remainder) with that supplier crossed out. The buyer then picks the next supplier.
- **Expired returns on Pharma Overseas** (and later Ibn Sina, if its app has a returns screen), from
  store **105 only**. Each answer from the supplier is recorded on the existing return-calendar record.
- **Never order twice.** That covers a robot retry, a crash after Submit, a basket re-run, and items
  left in the supplier's cart from an earlier session.
- **Full audit**: who prepared, who approved, what the robot entered, every message the supplier
  showed, the order number, and screenshots at key steps.

**Non-goals**
- Choosing the supplier. That stays the buyer's call per item, guided by the price comparison.
- Robots for other suppliers (Ramco, Masria, Zaytoun, Sherif, Ikhnatoun …). Their orders keep going
  out as today: WhatsApp text or Excel through `apps/supply/execution.py::commit_order`. A future
  portal is added as a new portal driver, not new business logic.
- Any write to SOFTECH. Purchase invoices (10) and supplier returns (120) still reach SOFTECH the way
  they do today, natively or through the part-1 robot. This part only *reads* our own data.
- Calling the suppliers' hidden data feeds (approach B in §3).
- Store 102, shelf stock and HQ stock for returns. Shelf and HQ lines stay on the return calendar, for
  branches to move into 105 first.

**Anti-goals (a failure even if it "works")**
- **The robot pressing Submit Order or Submit Return.** It never does. A person presses it.
- **An order containing items the buyer did not approve**, for example leftovers already in the
  supplier's cart.
- **An order placed on the wrong account**, and so on the wrong credit line.
- **The robot quietly guessing which supplier product an item is**, or moving a shortage to another
  supplier on its own.
- **A login password stored anywhere**, in the database, the repo, the agent's config or the logs.

## 3. Approaches considered

| | Approach | Trade-off | Decision |
|---|---|---|---|
| **A** | **Text-reading robot on the buyer's PC.** It drives a browser for Pharma Overseas (reading page text and buttons) and BlueStacks through Android's debug link (ADB + UI Automator, reading the app's screen as text). | It breaks when a supplier moves a button, but it fails loudly and stops. It reads stock messages and order numbers reliably. | **Chosen by the owner, 2026-11-16** |
| B | Call the supplier systems' own data feeds from the logged-in session | Fastest, but unofficial and possibly against their terms. It changes without notice, and the Ibn Sina app probably blocks it. | Rejected. It could be reconsidered later, for read-only stock checks only. |
| C | Screen-position clicking (the DataLoad/part-1 style) | It works on anything, but it is blind to text. It cannot read "No Enough material Stock" or the order number. | Rejected for portals |

## 4. What the supplier sides look like (observed 2026-11-16 from the owner's screenshots)

### 4.1 Pharma Overseas website

The address is `shop.pharmaemarket.com/pharma/en/EGP/…`. The site is in English.

- **Login.** Email plus password, entered by the operator. There are **two accounts**, one for each of
  two pharmacies on paper. Both deliver to **HQ**, and each has its own credit line.
- **Product identity.** Every product has an `ID 000000000000052872`: an 18-digit, zero-padded SKU. The
  banners print «كود الصنف 60634», which is very likely the same number without the leading zeros.
  The builder confirms this on a few items (§10).
- **Quick order** (`/my-account/quick-order`):
  - Add products by name or SKU. Each row shows Available Bonus, Qty, Public Price, PH. Price,
    Discount %, Tax %, Fixed Margin, Total Without Tax and **Expiry Date**.
  - **Import Products** takes a CSV with the columns **SKU, quantity**. **Export Product To CSV** also
    exists.
  - The search list marks items **"Out Of Stock"**.
  - Asking for more than is in stock shows a banner, **"<name>: No Enough material Stock"**. When
    nothing is in stock it shows **"No material Stock"**.
  - The page shows **Consumption / Credit / Credit Limit** for the logged-in account.
  - The page offers an **Auto recurring order?** option. The robot always leaves it at "None (one time
    order only)".
- **The cart is server-side and persistent.** "This item was already in your cart. The quantity was
  updated." That means leftovers from any earlier session ride along with the next order.
- **Placing the order.** "Proceed To Next Step" (`/my-account/place-order`) shows the totals, then
  **Submit Order**. The response is "Thank You … Your order number # 2104322530".
- **Order History.** It lists the past orders. The builder confirms its columns.
- **Expired Return** (`/my-account/expired-returns`):
  - Search and add a product. Each line has Qty, **Batch** (free text), **Expiry Date** (dd/mm/yyyy)
    and Price (filled by the site).
  - The page shows **Remaining Value** (an allowance, 8,854.31 when observed) and the Expired Return
    Total.
  - **Submit Return** answers with banners per line:
    - "Material excceds the max. number of Months for return (… - 37216)": outside their window;
    - "Not YRE6 material (… - 59798)": they never take this item back;
    - "Retuned quantity exceeds total vendor max. quantity (… - 37216)": too many.

    On success it says "Expired return request # 6605550038 is submitted successfully. Please deliver
    the items to the warehouse with the driver or representative."
- **Expired Return History.** It can be searched two months at a time. Its columns are Return Order #,
  Sales Order Date, Total and **Credit Memo #**, which is blank until the supplier credits the return.
  A details page lists the lines.

### 4.2 Ibn Sina app (inside BlueStacks)

- **Login.** Pharmacy code plus password, entered by the operator.
- **New Order.**
  - Search in two modes, "Starts with" and "Contains letters", with a cart icon on each result.
  - Each product card shows Price, Public Price, a quantity stepper, Total, **Bonus** and "Pricing
    Details".
  - When an item can't be supplied, a red bar reads "This item is currently out of stock", the card
    shows "Unavailable", and a toast says "Item not available".
  - At the bottom: **Submit Order** and **Review Order**.
- **No supplier product code is visible.** The stable key is the app's **exact product name**, for
  example `PLAVIX 75MG TABS 28'S (LOCAL)`.
- **Stock can't be tested yet.** On 2026-11-16 the account had no available credit, so every item
  showed as unavailable. Real stock behaviour is checked once credit is back (§9, Stage 3).
- **Returns: not seen yet.** Older notes say Ibn Sina accepts self-entered returns. That screen is
  looked at in Stage 4.

## 5. What already exists and is reused (no duplication)

| Need | Existing piece | How it is used |
|---|---|---|
| Robot app, module, permissions | `apps/rpa` (part 1): module `rpa`, `/api/rpa/`, `MatrixPermission` grants | New models live in the same app (§6.1) |
| Robot PCs and their sign-in | `RpaDevice` + `RpaDeviceAuthentication` (`X-ElR-RPA-Agent`), `issue_device` | Reused as is. A paired PC runs both SOFTECH jobs and portal baskets. |
| Tray agent | `rpa_agent/` (client, overlay, stop button, Esc) | Gains two drivers: `portal_web` (Playwright) and `portal_android` (ADB/UI Automator) |
| Screenshots and retention | `RpaScreenshot` + its data-lifecycle entry | Gains a nullable `portal_run` FK. One storage path and one retention rule. |
| Order list sources | `purchasing.PivotSheetSnapshot` (every «الاحتياج» download: item, gap, SOFTECH supplier); `purchasing.IsrPush.lines_snapshot` | A job is created from a snapshot or an ISR, or from an uploaded Excel |
| Recording an order | `apps/supply/execution.py::commit_order` (SupplyDecision per line, `order_ref`, `idempotency_key`, need check, cases → ordered) | Called once per basket, after the order number is read |
| Supplier's offers and stock | `supply.AvailabilityBatch` / `AvailabilityLine` (price, discount, FOC, expiry, `supplier_item_code`, `signals`) | Every portal check is written as an availability batch (new source `portal`). Price comparison and the inbox then see it. |
| Supplier codes | `invoices.VendorItemMapping` (`vendor_item_code`, `raw_name_normalized`), `supply.availability.resolve_vendor_codes`, `learn_vendor_mapping`, `catalog.ItemSupplierLink` | Codes and names are looked up through `resolve_vendor_codes`, and new ones are learnt through `learn_vendor_mapping`. Pushing them to SOFTECH `itemssuppliers` stays with the existing `apps/invoices/supplier_items.py::inject_mapping` (flag `INVOICE_SUPPLIER_ITEM_WRITE_ENABLED`). This part adds no SOFTECH write. |
| Supplier price ranking | `/supply` «مقارنة الموردين» (supplier price comparison) | Shown next to each line when the buyer picks a supplier |
| Return lines | `apps/batches/return_calendar.py::calendar` (window via `return_window.window_for`, supplier attribution, `IN_WINDOW`) + `StockExpiryBalance` (`batch_no`, `expiry_date`, `store_role`) | Return jobs take lines with `location='105'`, `state in IN_WINDOW` and supplier 565/260 |
| Supplier answer per return line | `return_calendar.request_returns` / `record_answer` (accepted / partial / rejected, allowed expiry) on `ExpiryDisposalRecord` | Every site answer goes through `record_answer` |
| Return close-out | `return_calendar.reconcile_returns` (doc 120 lines from `procurement.PurchaseLine`) | Unchanged. It closes the records once the 120 reaches SOFTECH. |
| Return policy | `procurement.SupplierReturnPolicy` (565/260 seeded, `self_entry=True`, `entry_layout`) | `self_entry` marks the suppliers whose returns the robot may enter |
| Supplier records | `invoices.VendorProfile.softech_personcode` | The vendor on every learnt mapping and availability batch |

## 6. Design

### 6.1 Pieces

**1. Portal jobs in `apps/rpa`.** These are new models next to part 1's. Part 1's `RpaJob` /
`RpaDocument` / `RpaRun` are shaped around a SOFTECH screen (screen, recipe of keystrokes, SOFTECH
document number, store), while a portal basket is shaped around a supplier account and an order
number. So the portal side gets its own models, and shares what really is shared: devices, auth,
module, audit, screenshots and the agent.

- **`BuyList` / `BuyListLine`**: the buyer's working list, which sits above the portal jobs.
  - **What it is.** One list per sourcing round, made from a pivot snapshot, an ISR or an upload.
  - **Each line holds:**
    - `item`;
    - `needed_qty`, in **whole packs**: a fractional gap is rounded **up**, the same as the ISR rule,
      and the buyer may edit it;
    - `chosen_supplier` (supplier code), and `tried` (the supplier codes already tried, with what each
      gave);
    - `remaining_qty`;
    - `source_ref` (snapshot id + item, or ISR line).
  - **What it feeds.** Lines whose chosen supplier is a portal go into a `PortalJob`. Lines for any
    other supplier go out through the existing `commit_order` WhatsApp/Excel path from the same
    screen.
  - **«الباقي»** is simply the lines with `remaining_qty > 0`. Their last supplier is already in
    `tried`, so the buyer's next pick is one key.
  - **Duplicate guard.** A source line belongs to at most one open `BuyList`. This is where the guard
    is enforced.
- **`SupplierPortal`**
  - Fields:
    - `key`: `pharma_overseas` / `ibn_sina`;
    - `supplier_code` ('565' / '260');
    - `driver`: `web` / `android`;
    - `enabled`, `live` (both default False);
    - `basket_size` (default 10);
    - `short_expiry_months` (default 12, used to flag an offered expiry closer than this);
    - `price_jump_pct` (default 10, used to flag a price this far above our last cost).
- **`PortalAccount`**
  - Fields:
    - `portal` FK;
    - `label` (e.g. «حساب صيدلية …»);
    - `paper_branch` FK Branch (the pharmacy the account belongs to on paper);
    - `identity_text` (what the robot must see on the page to know it is in this account, e.g. the
      account's display name or pharmacy code);
    - `active`.
  - **No password field, ever.**
- **`PortalJob`**: one approved list for one portal.
  - Fields:
    - `kind` order / return;
    - `portal`, `account`;
    - `source_kind`: pivot / isr / upload / return_calendar;
    - `source_ref`;
    - `status`: draft / approved / cancelled / done;
    - `dry_run` (default True);
    - `created_by`, `approved_by`, `approved_at`.
- **`PortalBasket`**: one supplier order or one return request.
  - Fields:
    - `job` FK, `seq`;
    - `status` (§6.4);
    - `claimed_by` FK RpaDevice, `claimed_at`, `lease_until`;
    - `filled_at`;
    - `portal_ref` (the supplier's order or return number);
    - `submitted_seen_at`;
    - `order_ref` (the `commit_order` key, `portal-basket-<pk>`);
    - `credit_seen` JSON;
    - `needs_person_reason`.
  - Constraint: `portal_ref` is unique per portal when it is not blank.
- **`PortalLine`**: one item in a basket.
  - Fields:
    - `basket` FK, `item` FK catalog.Item;
    - `wanted_qty`, `accepted_qty`;
    - `status`: pending / ok / short / out / not_found / rejected / removed;
    - `supplier_key` (the SKU or the exact app name used);
    - `supplier_name_seen`;
    - `price`, `discount_pct`, `bonus_text`, `supplier_expiry`;
    - `flags` JSON (`short_expiry`, `price_jump`);
    - `message` (the supplier's exact text);
    - `availability_line` FK.
  - Return lines also carry: `batch_text`, `expiry_date`, `store_code`, `branch_code` and
    `disposal_record` FK (`ExpiryDisposalRecord`).
- **`PortalRun`**: one robot attempt on one basket.
  - Fields: `basket` FK, `device` FK, `mode` (dry_run / live), `started_at`, `finished_at`, `outcome`,
    `steps` JSON.
  - Screenshots go in part 1's `RpaScreenshot` through a new nullable `portal_run` FK. Exactly one of
    `run` / `portal_run` is set (CheckConstraint).

**2. Portal drivers in the tray agent.**

- **`portal_web` (Pharma Overseas).**
  - It runs Playwright on a **persistent browser profile kept on the operator's PC** (under the user's
    AppData, never in the repo).
  - The operator logs in themselves in that window. The profile keeps the session, so they don't log
    in again every day.
  - The driver reads the page's text and buttons by name (role / label / visible text) and acts
    through them, never through screen coordinates.
- **`portal_android` (Ibn Sina).**
  - It reaches BlueStacks through ADB and reads the UI tree with UI Automator (e.g. the
    `uiautomator2` library).
  - The operator opens the app and logs in themselves.
  - ADB has to be switched on in BlueStacks settings. That is a one-time step for the owner.
- **Both drivers use a step plan built by the server** (§6.3). They report every step, every supplier
  message (exact text) and the screenshots back to the server.
- **The drivers hold a deny-list of controls they will never press:**
  - Submit Order, Submit Return, Recurring order, Sign Out;
  - any password field (never typed into).

  This is enforced in the driver code and covered by tests. The server plan can't override it.

**3. The basket builder (server).** It takes an approved job and splits its lines into baskets of
`basket_size`, in the buyer's order, each line with its known supplier key (if any). Lines without a
key first go through **code discovery** (§6.2).

**4. The checker (server).** It is read-only and reads the supplier side through the robot only:
- It reconciles each basket's reported order number with the portal's **Order History**.
- For returns, it does the same with **Expired Return History**, including the Credit Memo # when it
  appears.
- It runs on demand, and once a day for open records.

### 6.2 Ordering, step by step (Pharma Overseas; Ibn Sina is the same flow with its own driver)

1. **Prepare.** The buyer opens `/rpa` «طلبيات الموردين» and starts a job from:
   - the latest «الاحتياج» pivot download (`PivotSheetSnapshot`), filtered to the lines whose chosen
     supplier is this portal;
   - an ISR (`IsrPush`);
   - an uploaded Excel (item + qty).

   For each line the buyer sees the supplier ranking from the price comparison, and the default
   supplier follows the buyer's usual order. Only lines assigned to Pharma Overseas or Ibn Sina enter a
   portal job. The rest go out the existing WhatsApp/Excel way.
2. **Pick the account.** The screen shows both accounts' last-seen credit (Consumption / Credit /
   Limit, captured on each run). The default is the one with more headroom, and the buyer can change it.
3. **Approve.** The server runs `commit_order`'s **preview** checks:
   - a line above the live residual need still needs a reason, as today;
   - an item can't appear twice;
   - lines with no item match block approval.

   The approver must hold `rpa.approve` (§6.6).
4. **Code discovery (only for lines with no known code).**
   - The robot searches the item on the site by name and reports the top candidates: name, SKU, price
     and stock mark.
   - A person confirms the right one in a review grid (`useGridKeyboard`: ↑↓, Enter = confirm, M =
     none of these). Confirming calls `learn_vendor_mapping`, so the code is known from then on.
   - Discovery puts **nothing** in the cart.
5. **Fill one basket.** Per basket the robot does the following.
   1. **Checks the account.** It reads the account identity on the page and compares it with
      `PortalAccount.identity_text`. A mismatch → stop, needs a person.
   2. **Checks the cart is empty.** If the cart is not empty → stop, needs a person. The robot never
      deletes cart items it did not add. They may be a buyer's manual work in progress.
   3. **Adds each line at its wanted quantity**, by SKU through quick order. If the site answers "No
      Enough material Stock", the robot steps the quantity down, never above `wanted_qty`, to the
      largest quantity the site accepts, within a few tries. "No material Stock" / "Out Of Stock" →
      `out`.
   4. **Reads back** every row: accepted quantity, price, discount, bonus, expiry. It flags
      `short_expiry` and `price_jump`.
   5. **Reads the whole cart** and compares it with the basket: only these items, and only these
      quantities. Any difference → stop, needs a person.
   6. **Proceeds to the review page** and reads its totals and the account's credit.
   7. **Stops** with the overlay message «راجع ثم اضغط Submit Order بنفسك».

   Once the robot's check is done, there are two cases.
   - **Dry run (the default until the portal goes `live`).** The robot removes **only the lines it
     added**, leaving the cart as it found it, and marks the basket `dry_run_ok`.
   - **Live.** The basket is `awaiting_submit`. The person looks at it and presses **Submit Order**
     themselves. The robot watches for the "Thank You … order number" dialog, reads the number and
     reports it.
6. **Record.** Once the number arrives, the robot first opens that order's **Order History details**
   and reads what was actually ordered. The person may have changed the cart after the handover, and
   the record must show what really went out. Any difference from the handed-over basket is shown on
   the basket and audited. The recorded quantities are the ones from Order History. Then the server,
   in one transaction:
   - stores `portal_ref` and the account used (also kept in `SupplyDecision.result_refs`);
   - calls `commit_order(lines with accepted_qty, idempotency_key='portal-basket-<pk>',
     supplier=VendorProfile(565))`;
   - writes the checked lines into an `AvailabilityBatch` (source `portal`), so that offers and
     stock are kept;
   - writes the audit.

   A replayed call is harmless, because `commit_order` replays on the same key.
7. **The remainder.** Lines that came back `short` or `out` put their missing quantity back on the
   buyer's list as **«الباقي»**, with this supplier marked as tried. The buyer picks the next supplier
   per item. A remainder that goes to another portal becomes a new job; one that goes to a WhatsApp
   supplier goes out the existing way.

**Faster path once codes are known.** When every line in a basket has a confirmed SKU, the robot may
use **Import Products** with a two-column CSV (SKU, quantity) instead of adding rows one by one. It
then does the same stock step-down, read-back and cart check. The CSV is written to a temp folder on
the PC and deleted afterwards.

### 6.3 Expired returns (Pharma Overseas)

1. **Prepare.** A return job takes the return-calendar lines with:
   - supplier = this portal's supplier;
   - location **105**;
   - `state in IN_WINDOW`;
   - no record already `done`.

   The lines are split into baskets the same way.
2. **Check the allowance.** The robot reads **Remaining Value**. It stops adding lines once the return
   total would pass it, and leaves the rest for the next request.
3. **Fill.** Per line: product (by SKU), quantity, expiry (dd/mm/yyyy) and **Batch**. For the batch:
   - use `StockExpiryBalance.batch_no` when it is a real lot number;
   - otherwise use the expiry digits `ddmmyyyy` (e.g. `01082026`).

   If the site turns a line down over the batch, a person can switch that item to the other form, and
   it is remembered per (supplier, item). The robot stops at «راجع ثم اضغط Submit Return بنفسك».
4. **The supplier answers.** After the person submits, the robot reads every banner. Each banner names
   the item ID, so it is matched to its line.
   - **Max months** → `record_answer(rejected, reason='window')`.
   - **Not YRE6 material** → `rejected, reason='not_returnable'`. The (supplier, item) is also marked
     never-returnable, and the calendar stops proposing it to that supplier.
   - **Max quantity** → the robot steps that line's quantity down and asks the person to submit again;
     the recorded answer is `partial` with the accepted quantity.
   - **The success banner** → `portal_ref` = the return request number; the submitted lines are
     `accepted`.
**Return-calendar extensions (Stage 2).** These live in `apps/batches` / `apps/procurement`, not in
`apps/rpa`, because they are facts about returns, not about the robot:
- `record_answer` gains an optional `reason`, one of: window / not_returnable / max_qty / batch /
  other.
- A new `SupplierItemReturnRule (supplier_code, item_code, never_returnable, batch_form)` stores the
  never-returnable mark and the per-item batch form.
- `calendar()` stops proposing a never-returnable (supplier, item) to that supplier, for **every**
  user. The line then shows as «المورد لا يقبله» rather than vanishing.

5. **Credit.** The daily check reads Expired Return History, two months at a time, and stores the
   Credit Memo # once it appears.

The return itself still reaches SOFTECH as doc 120, natively or through the part-1 robot, and
`reconcile_returns` closes the records as today. Handing the goods to the driver is a physical step
outside this system.

### 6.4 Basket lifecycle

```
pending → (discovery) → ready → in_progress → dry_run_ok
                                     ↘ awaiting_submit → submitted (number read) → recorded
                                     ↘ needs_person → retry | link_order | cancelled
```

- **A basket is claimed by an atomic `ready → in_progress` change** under an advisory lock, and only by
  a device whose staff (`RpaDevice.staff`) is the job's creator. Each device works on one basket at a
  time.
  - The robot runs **attended, on the buyer's own PC**, as in part 1. The browser profile and BlueStacks
    are installed there.
  - A dedicated robot PC is a later option, not part of this design.
- **The lease covers a crashed agent.** It is renewed by every step report. A crashed agent's basket
  goes to `needs_person` when the lease runs out, and **never back to the queue on its own**.
- **A crash after Submit is resolved from Order History.** If the agent dies after Submit could have
  been pressed (`awaiting_submit`), the basket goes to `needs_person`. The person then opens Order
  History, through the robot's read, and either links the order (`link_order`) or confirms that
  nothing was placed, which allows a retry.
- **Approved snapshots are frozen.** Changing a line after approval means a new approval.

### 6.5 Never order twice

- **The robot never presses Submit.** Every order needs a person's click.
- **The cart must be empty before filling**, and the full cart must equal the basket before handover.
- **One basket, one order:**
  - `portal_ref` is unique per portal;
  - `commit_order` is keyed on `portal-basket-<pk>`;
  - a basket in `submitted` or `recorded` can never be claimed again.
- **A retry after an unclear outcome goes through Order History.** The robot reads the orders placed
  since the basket's `filled_at`. If one matches the basket's items, the basket is linked to it, not
  refilled. A person confirms the link.
- **The same pivot line cannot go into two open jobs.** The job builder refuses a (snapshot, item)
  that is already in a job that is not cancelled.

### 6.6 Switches, permissions, audit, privacy

- **Switches.**
  - `RPA_SUPPLIER_PORTAL_ENABLED` is default OFF, in settings and `.env.example`.
  - The claim endpoint serves baskets only where `writer_allowed('RPA_SUPPLIER_PORTAL_ENABLED')` is
    true. That keeps the queue to the one writer instance through the VPS cutover, exactly as part 1
    does. These aren't SOFTECH writes, but one queue must have one home.
  - On top of that, each portal has `SupplierPortal.enabled` (may run) and `live` (may reach the
    Submit handover; otherwise dry run only).
- **Permissions.** These reuse module `rpa` and its actions:
  - `create` = prepare a job, run it on my PC;
  - `approve` = approve a job;
  - `edit` = resolve a needs-a-person basket, confirm discovery matches.

  Purchasing gets `view` + `create` + `approve` on portal jobs (§8 call). Portal accounts and portal
  switches are admin only.
- **Branch scope.** Portal jobs are **company level**: they are ordered for HQ and seen by purchasing
  and admin. `permission_matrix.BRANCH_SCOPE['rpa']` is updated to say so.
- **Audit.** These AuditLog actions are added:
  - `rpa_portal_job_created`, `rpa_portal_job_approved`, `rpa_portal_basket_claimed`;
  - `rpa_portal_basket_filled`, `rpa_portal_submit_seen`, `rpa_portal_basket_recorded`;
  - `rpa_portal_needs_person`, `rpa_portal_resolved`;
  - `rpa_portal_code_learnt`, `rpa_portal_return_answer`.

  Each carries the before/after where something changed.
- **Credentials.** None are stored. The browser profile and the BlueStacks session live on the
  operator's PC. If a login page appears mid-run, the robot pauses with «سجّل الدخول ثم اضغط متابعة».
  The robot never types into a password field.
- **Logs.** No supplier password, cookie or session token in any log or step report. Step reports keep
  page text only. Errors go through `core/errors.public_error`.

### 6.7 Screen

`/rpa` gains a tab group «مواقع الموردين», with these tabs:

- **«طلبيات»**: jobs; per-line supplier pick with the price ranking; account pick with credit; approve.
- **«اكتشاف الأكواد»**: the code discovery review grid.
- **«السلال»**: each basket's lines with the supplier's answer, flags, step log, screenshots and the
  order number; the needs-a-person actions.
- **«الباقي»**: remainders waiting for a next supplier.
- **«مرتجع صلاحية»**: return jobs, answers per line, Credit Memo status.
- **«الحسابات»** (admin): portal accounts and switches.

Every grid is sortable (`useSortableRows` / `SortTh`), and every select or approve grid uses
`useGridKeyboard`. Branches show as «code · name» (`useBranchLabels`). There is a forced-refresh button
for the history check. In-app help comes in Arabic and English (`apps/help/content/rpa.py`), with
`useHelpTab(tab)`.

## 7. Dependency on part 1

This part needs part 1's Stage 1 Tasks 1 (module wiring), 2 (models: `RpaDevice`, `RpaScreenshot`),
8 (device tokens and the agent auth) and 11 (the `rpa_agent/` skeleton).

**Status on 2026-11-16:** `claude/softech-rpa` has Task 1 and the agent skeleton, but **not yet** the
models or the device auth.

**Part 2 waits for them and does not build its own copies.** Its Stage 1 plan has a gate task: confirm
that part 1's Tasks 2 and 8 are committed, then branch from there. The server-side pieces that need no
devices can start straight away from `main`, in their own files:
- `BuyList`;
- the basket builder;
- code-discovery review;
- the recording service.

The part-2 build starts from `claude/softech-rpa` once those tasks are committed there, or from `main`
once part 1's Stage 1 is merged. Part 2 adds only:
- new models;
- one nullable FK on `RpaScreenshot`;
- new agent drivers.

It changes no part-1 behaviour. The two sessions coordinate through the shared notes folder, and
migration numbers are re-checked before every push.

## 8. Calls made by the designer (owner to check)

- **Purchasing may approve its own portal jobs.** The person's own Submit click on the supplier side
  is the final approval. A second approver is not required by default. If you want four-eyes above a
  value, it is one setting (`portal_four_eyes_above`, default empty = off).
- **A non-empty cart stops the robot instead of being cleared**, because it may be someone's manual
  order in progress.
- **The quantity step-down never goes above the approved quantity.** It finds the largest accepted
  quantity within a few tries and records what the site allowed.
- **Flags are shown, never acted on.** `short_expiry` (supplier expiry inside 12 months) and
  `price_jump` (price ≥ 10 % above our last cost) are shown on the line before the person submits. The
  robot doesn't drop the line.
- **The basket order is the buyer's list order**, cut every 10 lines. It is not sorted by value or
  category.
- **Codes go into VendorItemMapping only.** Captured codes are learnt there. Pushing them into SOFTECH
  `itemssuppliers` stays with the existing `inject_mapping` flow and its own switch, outside this part.
- **Quantities are whole packs everywhere.** A fractional gap is rounded up, and the buyer can edit
  it.
- **What was really ordered is read back.** After Submit, the robot reads the order's lines from Order
  History and records those, so edits the person made before submitting are captured.
- **A buy list sits above the portal jobs** (`BuyList`). It holds the per-item supplier pick and
  «الباقي», and it also feeds the existing WhatsApp/Excel path.
- **The two Pharma Overseas accounts are one supplier (565).** The account used is kept on the basket
  and in `SupplyDecision.result_refs`.
- **Never-returnable items leave the 565 return proposals for everyone** (Stage 2), shown as «المورد
  لا يقبله».
- **The robot runs on the buyer's own PC, attended.** It claims only that buyer's jobs.
- **Every portal check becomes an `AvailabilityBatch`** (source `portal`), so the price comparison
  learns from robot runs too.

## 9. Order of work

1. **Stage 1: Pharma Overseas ordering, dry run first.**
   - Models, jobs from pivot / ISR / upload, approval, basket builder and code discovery.
   - The `portal_web` driver with account and cart checks, step-down, read-back and the review-page
     handover.
   - Order-number capture, `commit_order` recording, the availability batch, remainders, the history
     check, the `/rpa` tabs and help.
   - The owner watches dry runs, then switches `live` on.
2. **Stage 2: Pharma Overseas expired returns** from 105, with answers into `record_answer` and the
   Credit Memo check.
3. **Stage 3: Ibn Sina ordering**, with the `portal_android` driver (ADB + UI Automator), keyed by
   exact product name. It starts once the account has credit to test with.
4. **Stage 4: Ibn Sina returns**, if the app has a returns screen. Its screens are recorded first.

## 10. Left to the builder

- **Confirm the SKU forms are the same item.** Check that the 18-digit ID and the short «كود الصنف»
  are the same number on 3–5 items, and store the SKU in one canonical form (digits, no leading zeros)
  plus the padded form for typing.
- **The stable account-identity text on each portal** (display name, pharmacy code or delivering-to
  label).
- **The selectors and labels per page.** Keep them as data in one recipe module per driver, so a
  redesign is a one-file fix.
- **Whether Submit Return submits the valid lines and rejects the bad ones in the same request, or
  rejects the whole request.** Check this on one small real return in Stage 2, and shape the
  "submit again" step to match.
- **Playwright and browser packaging** inside the existing agent installer, and the profile location.
- **BlueStacks ADB port discovery.**
- **Exact retry counts and waits** for the step-down and page loads.
