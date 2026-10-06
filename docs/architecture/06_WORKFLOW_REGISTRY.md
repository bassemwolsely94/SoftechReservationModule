# 06 — Workflow Registry

Complete documentation of every major operational workflow.

---

## 1. RESERVATION WORKFLOW

### Trigger
Customer calls/visits requesting an out-of-stock item. Staff creates a reservation.

### State Machine
```
PENDING → AVAILABLE → CONTACTED → CONFIRMED → FULFILLED
                                            → CANCELLED
        → EXPIRED (automated, no contact)
        → CANCELLED (any stage)
```

### Steps

1. **Create** — Staff creates `Reservation` (item, customer, quantity, channel, branch)
   - Guard: `Branch.is_operational` must be True
   - Guard: Item must have `can_transact=True` if linked
   - Generates `ReservationActivity(type=status_changed)`

2. **Stock Available** — Staff marks item arrived/available in branch
   - Status: `pending → available`
   - Notification sent to assigned staff

3. **Customer Contacted** — Staff logs contact attempt
   - Status: `available → contacted`
   - Activity logged: `call_made` or `customer_replied`

4. **Customer Confirmed** — Customer confirms pickup/delivery
   - Status: `contacted → confirmed`
   - Optional: Record downpayment via `ReservationDownpayment`

5. **Fulfill** — Item dispensed to customer
   - Status: `confirmed → fulfilled`
   - ERP match triggered asynchronously:
     - Searches SOFTECH for matching invoice (customer PIC + item + date window)
     - Stores match in `erp_match_status`, `erp_matched_items`, `erp_receipt_lines`

6. **Cancellation** — Any actor cancels at any stage
   - Status: `→ cancelled`
   - Reason logged in activity

### Failure Points
- ERP match can timeout or find no match (`erp_match_status = not_found`)
- Customer never contacted → reservation expires after configured days
- Missing phone number prevents WhatsApp notification

### Related APIs
`POST /api/reservations/`, `POST /api/reservations/{id}/status/`, `POST /api/reservations/{id}/erp-match/`

---

## 2. DEMAND RECORD WORKFLOW

### Trigger
Walk-in, phone, WhatsApp, or call-center contact for an out-of-stock item.  
More structured than a reservation — includes SLA tracking and follow-up tasks.

### State Machine
```
NEW → ASSIGNED → FOLLOW_UP → STOCK_ETA → TRANSFER_SUGGESTED → PURCHASING_FLAGGED
                                        → FULFILLED
                                        → LOST (with reason)
                                        → CANCELLED
```

### SLA
- `NEW → ASSIGNED`: 10 minutes
- `ASSIGNED → FOLLOW_UP` (first contact made): 20 minutes
- `sla_deadline` = created_at + SLA_MINUTES[status]
- `sla_breached` = now > sla_deadline AND status not resolved

### Steps

1. **Create** — Staff creates `DemandRecord` + one or more `DemandItem` entries
   - `demand_number` auto-generated: DEM-XXXXXX
   - Source: walk_in / phone / whatsapp / delivery / online / call_center / other

2. **Assign** — Supervisor assigns to a staff member
   - Status: `new → assigned`
   - `assigned_at` recorded for SLA

3. **Follow Up** — Staff begins customer contact cycle
   - Create `FollowUpTask` (call/whatsapp/sms/visit/stock_check)
   - Log `DemandLog` entries (call_made, call_outcome, message)

4. **Resolution Paths**:
   - **Stock ETA given** → `stock_eta` + `expected_stock_date` set
   - **Transfer suggested** → creates `TransferRequest` (link by demand)
   - **Purchasing flagged** → signals purchasing team
   - **Fulfilled** → item dispensed, `erp_invoice_ref` set, `fulfilled_at` timestamp
   - **Lost** → `lost_reason` set (no_stock/delayed/discontinued/no_response/price/competitor/other)

5. **Item Demand Stats** — `ItemDemandStat` updated daily via `generate_demand_records` command:
   - `demand_count_30d`, `lost_count_30d`, `fulfilled_count_30d`, `lost_qty_30d`
   - Flags: `suggest_order`, `suggest_transfer`, `is_long_shortage`

### Failure Points
- SLA breach not auto-escalated (manual check only)
- No automated customer notification when stock arrives
- `phcode` linkage to customer is optional — analytics may undercount

### Related APIs
`POST /api/demand/`, `POST /api/demand/{id}/status/`, `GET /api/demand/sla-breached/`

---

## 3. TRANSFER REQUEST WORKFLOW

### Trigger
Branch needs items from another branch (or HQ). Either manual or from purchasing recommendations.

### State Machine
```
DRAFT → PENDING → APPROVED → SENT_TO_ERP → COMPLETED
              → REJECTED
              → NEEDS_REVISION → PENDING (re-submit)
DRAFT/PENDING/APPROVED → CANCELLED
```

### Steps

1. **Draft** — Staff creates `TransferRequest` + `TransferRequestItem` lines
   - `request_number` auto-generated: TR-XXXXXX (DB sequence)
   - Supplying branch may be null initially
   - Optional: linked to `TransferRecommendation.source_recommendation`

2. **Submit** — Requester submits for approval
   - Status: `draft → pending`
   - Notification sent to approving branch / supervisor
   - System message logged in chatter

3. **Approve / Reject / Revise** — Supervisor reviews
   - `approved`: supplying branch confirms stock and agrees
   - `rejected`: `rejection_reason` required
   - `needs_revision`: `revision_notes` to requester → requester resubmits

4. **Send to ERP** — Approved transfer logged in SOFTECH (manually by staff)
   - Status: `approved → sent_to_erp`
   - `erp_reference` stored, `sent_to_erp_at` timestamp
   - Actual stock movement happens in SOFTECH (not in this system)

5. **Complete** — Stock physically dispatched/received
   - Status: `sent_to_erp → completed`
   - `delivery_person_name`, `dispatched_at` recorded

6. **ERP Match** — Post-completion verification
   - System searches SOFTECH for the transfer doccode (125/25)
   - Stores match in `erp_match_status`, `erp_matched_items`

### Key Properties (computed on TransferRequest)
```python
is_editable        # only draft status
can_submit         # draft + has items
can_approve        # pending
can_reject         # pending
can_request_revision # pending
can_send_to_erp    # approved
can_dispatch       # sent_to_erp
can_cancel         # not completed/cancelled
```

### Chatter
All workflow events auto-logged via `TransferRequestMessage.log_system()`.  
Staff can add messages, images, voice notes.

### Failure Points
- No automatic ERP creation (manual entry into SOFTECH required)
- ERP match can fail if ERP doccode/date doesn't match within window
- No stock validation at time of approval (could approve unavailable stock)

---

## 4. VOUCHER REDEMPTION WORKFLOW

### Trigger
Customer at POS wants to use a voucher code.

### Flow
```
Employee enters voucher code + customer phone
         ↓
System checks eligibility (Voucher.check_customer_eligibility)
         ↓ [eligible]
OTP generated (VoucherOTP.create_for_voucher)
  - 6-digit HMAC-SHA256 hashed, salt stored, plain NEVER persisted
  - WhatsApp URL generated → employee sends to customer
         ↓
Customer shares OTP code to employee
         ↓
Employee enters OTP (VoucherOTP.verify)
  - Max 3 retries; locked after 3 failures
  - 3-minute TTL
         ↓ [verified]
Redemption Document created (VoucherRedemptionDocument)
  - 15-minute expiry window
  - REF-XXXXXXXX reference code for POS
         ↓
POS confirms document used (mark-used)
         ↓
VoucherRedemption created (immutable audit record)
Voucher.times_used incremented
```

### Eligibility Rules
- `voucher.status == 'active'`
- `not voucher.is_expired` (valid_until check)
- `not voucher.is_exhausted` (times_used < max_uses)
- Per-customer limit: `VoucherRedemption.count(voucher, phone) < usage_limit_per_customer`
- Per-day limit: `VoucherRedemption.count(today) < usage_limit_per_day`
- Category rule: assigned vouchers require `VoucherAssignment` record

### Related APIs
`POST /api/vouchers/check/`, `POST /api/vouchers/generate-otp/`, `POST /api/vouchers/verify-otp/`, `POST /api/vouchers/create-document/`, `POST /api/vouchers/mark-used/`

---

## 5. INCENTIVE CALCULATION WORKFLOW

### Trigger
Admin triggers calculation for a program + date range (manual or scheduled).

### Flow
```
Admin selects program + period (start_date, end_date)
         ↓
Engine reads IncentiveRule set for program
         ↓
Engine queries SOFTECH stktrans for period (filtered by rule criteria)
  - item_code / IncentiveRuleItem membership
  - person_code_filter (ERP user code)
  - branch_filter
  - time_window_start/end
  - min_qty per transaction
         ↓
For each matching transaction line:
  - Calculate incentive_amount based on incentive_type
    • percent: quantity × unit_price × (rate/100)
    • fixed_per_unit: quantity × incentive_value
    • fixed_per_transaction: incentive_value per invoice
    • tiered: lookup slab by total period qty → apply rate to ALL units
  - Create IncentiveTransaction (immutable)
         ↓
Returns already-exist check: doc_no + item_code dedup
         ↓
IncentiveSettlement calculated per (user, period):
  total_incentive = SUM(IncentiveTransaction.incentive_amount)
  total_adjustments = SUM(AdjustmentEntry.amount)
  final_payout = total_incentive + total_adjustments
         ↓
IncentiveCalculationLog written (audit trail)
```

### Simulate Mode
Same flow but no records written — returns preview totals.

### Settlement Finalization
- Admin reviews settlement → `is_finalized = True`
- Locked: no further adjustments or recalculations
- `finalized_by` / `finalized_at` recorded

---

## 6. STOCK COUNT WORKFLOW

### Trigger
Branch manager initiates a count session.

### Flow
```
Create StockCountSession (branch, mode, date range, doccodes)
         ↓ [draft]
Take Snapshot → query SOFTECH stktrans for doccodes in date range
  - Compute expected_qty per item from transactions
  - Write StockCountSnapshot rows (IMMUTABLE)
         ↓ [snapshot_taken]
Export → generate Excel file with item list + expected_qty
  - Staff uses Excel for physical count
         ↓ [exported]
Upload counted quantities → match by item_code
  - difference = counted_qty - expected_qty
  - variance_type = ok / surplus / deficit
  - Update session counters: surplus_count, deficit_count, ok_count
         ↓ [uploaded → variance_ready]
Review variance report
         ↓
Close session
         ↓ [closed]
```

### ERP Doccode Reference
- `10`: Purchases from suppliers
- `25`: Incoming transfer (branch/HQ)
- `50`: Surplus stock adjustment
- `80`: Reservation sales
- `115`: Standard sales
- `120`: Returns to suppliers
- `125`: Outgoing transfer
- `150`: Deficit stock adjustment

---

## 7. SHORTAGE LIST WORKFLOW

### Trigger
Branch identifies items needed to order. Can be manual, voice, OCR from image, or bulk text.

### Flow
```
Create ShortageList (branch, title, source)
         ↓
Add ShortageItems:
  - Manual: type raw_name
  - OCR: upload image → Gemini OCR extracts names → create items
  - Bulk: paste text list
  - Voice: speech-to-text (browser-side)
         ↓
Fuzzy matching (rapidfuzz):
  - Each raw_name matched against catalog_item.name
  - match_score stored
  - High-confidence: auto-confirmed
  - Low-confidence: manual confirmation required
         ↓
Confirm items (confirmed_by audit trail)
         ↓
Submit list (status: open → submitted)
  - Purchasing team receives the list
         ↓
Resolved (status: submitted → resolved)
```

---

## 8. ERP SYNCHRONIZATION WORKFLOW

### Trigger
Scheduled (APScheduler) or manual trigger via SyncPage.

### Entities Synced (SOFTECH → PostgreSQL)

| Entity | Target Table | Strategy |
|--------|-------------|----------|
| Branches | branches_branch | Upsert by softech_branch_id |
| Items | catalog_item | Upsert by softech_id |
| Stock | catalog_itemstock | Upsert by (item, branch) |
| Customers | customers_customer | Upsert by softech_pic |
| Purchase History | customers_purchasehistory | Upsert by softech_invoice_id |
| Purchase Lines | customers_purchasehistoryline | Cascade upsert |
| ERP Users | users_erpuser | Upsert by username |
| Sales Transactions | purchasing_salestransactionline | Rolling 365-day window |

### Direction: SOFTECH → PostgreSQL (READ-ONLY from SOFTECH)
No mutations ever written back to SOFTECH from Django.

---

## 9. CUSTOMER SEGMENTATION WORKFLOW

### Trigger
Daily management command: `python manage.py segment_customers`

### Steps
1. For each customer with purchase history:
   - Calculate `days_since_last_visit` from last PurchaseHistory
   - Calculate `purchase_count_90d` (rolling 90-day)
   - Calculate `lifetime_value_ltv` from PurchaseHistoryLine totals
   - Assign `segment`:
     - VIP: LTV > threshold AND recent purchase
     - Loyal: frequent purchases
     - Regular: normal activity
     - At Risk: dropping frequency
     - Dormant: 90+ days no purchase
     - New: < 30 days since first purchase
     - Churned: 180+ days no purchase
   - Calculate `churn_score` (0–1) based on recency + frequency decay
   - Assign `churn_segment`: low / medium / high / critical

2. Update `CustomerHealthProfile` — scan PurchaseHistoryLine items tagged as chronic:
   - Set `has_diabetes`, `has_hypertension`, etc. based on medication categories
   - Set `polypharmacy_flag` if > 5 distinct chronic medications
   - `last_computed_at` updated
