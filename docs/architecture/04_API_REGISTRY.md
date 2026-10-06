# 04 — API Registry

All REST API endpoints grouped by module.  
Base URL: `/api/`  
Authentication: JWT Bearer token (djangorestframework-simplejwt)  
Default pagination: CursorPagination (50 items)

---

## AUTH  `/api/auth/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/login/` | POST | Obtain JWT access + refresh tokens |
| `/api/auth/refresh/` | POST | Refresh access token |
| `/api/auth/logout/` | POST | Blacklist refresh token |

**Inputs (login):** `{ username, password }`  
**Outputs:** `{ access, refresh, user: { id, role, branch, ... } }`

---

## USERS  `/api/users/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/users/staff/` | GET, POST | List / create staff profiles |
| `/api/users/staff/{id}/` | GET, PUT, PATCH, DELETE | Staff detail |
| `/api/users/erp-users/` | GET | List ERP user cache |
| `/api/users/permissions/` | GET | Role-permission matrix |
| `/api/users/me/` | GET | Current user profile |

---

## BRANCHES  `/api/branches/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/branches/` | GET | List all branches |
| `/api/branches/{id}/` | GET, PATCH | Branch detail + settings |
| `/api/branches/{id}/settings/` | GET, PATCH | Per-branch feature flags |

---

## CATALOG / ITEMS  `/api/items/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/items/` | GET | Item list (search, filter by category, barcode) |
| `/api/items/{id}/` | GET | Item detail + stock levels per branch |
| `/api/items/{id}/stock/` | GET | Stock breakdown per branch |
| `/api/items/search/` | GET | Quick search (name, barcode, softech_id) |
| `/api/items/categories/` | GET | Category list |
| `/api/items/bundles/` | GET, POST | Product bundles |
| `/api/items/bundles/{id}/` | GET, PUT, DELETE | Bundle detail |
| `/api/items/variants/` | GET, POST | Variant groups |
| `/api/items/barcodes/` | GET | Barcode lookup |

**Key query params:** `q` (search), `branch` (stock filter), `category`, `is_active`, `is_stockable`

---

## CUSTOMERS  `/api/customers/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/customers/` | GET | Customer list (search by name, phone, PIC) |
| `/api/customers/{id}/` | GET, PATCH | Customer detail |
| `/api/customers/{id}/health-profile/` | GET, PUT | Health profile |
| `/api/customers/{id}/notes/` | GET, POST | Customer notes |
| `/api/customers/{id}/purchase-history/` | GET | Purchase history |
| `/api/customers/{id}/reservations/` | GET | Customer reservations |
| `/api/customers/{id}/demands/` | GET | Customer demands |
| `/api/customers/segment/` | GET | CRM segment stats |
| `/api/customers/churn/` | GET | Churn risk list |

**Key query params:** `q`, `segment`, `churn_segment`, `branch`

---

## RESERVATIONS  `/api/reservations/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/reservations/` | GET, POST | List / create reservations |
| `/api/reservations/{id}/` | GET, PATCH | Reservation detail |
| `/api/reservations/{id}/status/` | POST | Status transition |
| `/api/reservations/{id}/activity/` | GET, POST | Chatter messages |
| `/api/reservations/{id}/downpayment/` | POST | Record downpayment |
| `/api/reservations/{id}/images/` | GET, POST | Reservation images |
| `/api/reservations/{id}/erp-match/` | POST | Trigger ERP match check |
| `/api/reservations/kanban/` | GET | Kanban board view (grouped by status) |
| `/api/reservations/stats/` | GET | Dashboard counts by status |

**Key query params:** `status`, `branch`, `priority`, `assigned_to`, `date_from`, `date_to`, `q`

---

## DEMAND  `/api/demand/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/demand/` | GET, POST | List / create demand records |
| `/api/demand/{id}/` | GET, PATCH | Demand detail |
| `/api/demand/{id}/status/` | POST | Status transition |
| `/api/demand/{id}/log/` | GET, POST | Chatter / call logs |
| `/api/demand/{id}/tasks/` | GET, POST | Follow-up tasks |
| `/api/demand/{id}/tasks/{tid}/` | PATCH | Task status update |
| `/api/demand/stats/` | GET | KPI counts |
| `/api/demand/item-stats/` | GET | Per-item demand aggregations |
| `/api/demand/sla-breached/` | GET | SLA-breached demands |

---

## TRANSFERS  `/api/transfers/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/transfers/` | GET, POST | List / create transfer requests |
| `/api/transfers/{id}/` | GET, PATCH | Transfer detail |
| `/api/transfers/{id}/submit/` | POST | Draft → Pending |
| `/api/transfers/{id}/approve/` | POST | Pending → Approved |
| `/api/transfers/{id}/reject/` | POST | Pending → Rejected |
| `/api/transfers/{id}/revise/` | POST | → Needs Revision |
| `/api/transfers/{id}/send-to-erp/` | POST | Approved → Sent to ERP |
| `/api/transfers/{id}/complete/` | POST | → Completed |
| `/api/transfers/{id}/messages/` | GET, POST | Chatter |
| `/api/transfers/{id}/erp-match/` | POST | Trigger ERP match |
| `/api/transfers/stats/` | GET | Dashboard counts |

---

## NOTIFICATIONS  `/api/notifications/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/notifications/` | GET | List notifications for current user |
| `/api/notifications/{id}/read/` | POST | Mark as read |
| `/api/notifications/read-all/` | POST | Mark all read |
| `/api/notifications/unread-count/` | GET | Badge count |
| `/api/notifications/chatter/` | GET, POST | Generic chatter messages |
| `/api/notifications/chatter/{id}/` | GET, DELETE | Chatter detail |

**WebSocket channels:**  
- `ws://host/ws/notifications/` → group `notifications_user_{profile_id}`  
- `ws://host/ws/chatter/{model}/{record_id}/` → group `chatter_{model}_{record_id}`

---

## VOUCHERS  `/api/vouchers/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/vouchers/` | GET, POST | List / create vouchers |
| `/api/vouchers/{id}/` | GET, PATCH | Voucher detail |
| `/api/vouchers/{id}/assign/` | POST | Assign to customer phone |
| `/api/vouchers/{id}/assignments/` | GET | List assignments |
| `/api/vouchers/check/` | POST | Check eligibility by phone |
| `/api/vouchers/generate-otp/` | POST | Generate + send OTP via WhatsApp |
| `/api/vouchers/verify-otp/` | POST | Verify OTP code |
| `/api/vouchers/create-document/` | POST | Create redemption document |
| `/api/vouchers/mark-used/` | POST | POS confirms redemption |
| `/api/vouchers/documents/` | GET | List redemption documents |
| `/api/vouchers/redemptions/` | GET | Redemption audit trail |

---

## INCENTIVES  `/api/incentives/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/incentives/programs/` | GET, POST | Programs |
| `/api/incentives/programs/{id}/` | GET, PUT, PATCH | Program detail |
| `/api/incentives/programs/{id}/rules/` | GET, POST | Rules in program |
| `/api/incentives/rules/{id}/` | GET, PUT, PATCH, DELETE | Rule detail |
| `/api/incentives/rules/{id}/items/` | GET, POST | Multi-item rule items |
| `/api/incentives/calculate/` | POST | Run calculation for period |
| `/api/incentives/simulate/` | POST | Simulate (dry run) |
| `/api/incentives/settlements/` | GET | Settlements list |
| `/api/incentives/settlements/{id}/finalize/` | POST | Finalize settlement |
| `/api/incentives/adjustments/` | GET, POST | Manual adjustments |
| `/api/incentives/transactions/` | GET | Transaction audit trail |
| `/api/incentives/logs/` | GET | Calculation run logs |

---

## STOCKCOUNT  `/api/stockcount/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/stockcount/sessions/` | GET, POST | Sessions |
| `/api/stockcount/sessions/{id}/` | GET, PATCH | Session detail |
| `/api/stockcount/sessions/{id}/snapshot/` | POST | Take snapshot (freeze expected_qty) |
| `/api/stockcount/sessions/{id}/export/` | GET | Export count sheet (Excel) |
| `/api/stockcount/sessions/{id}/upload/` | POST | Upload counted quantities |
| `/api/stockcount/sessions/{id}/variance/` | GET | Variance report |
| `/api/stockcount/sessions/{id}/close/` | POST | Close session |
| `/api/stockcount/snapshots/` | GET | Snapshot lines |

---

## SHORTAGE  `/api/shortage/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/shortage/lists/` | GET, POST | Shortage lists |
| `/api/shortage/lists/{id}/` | GET, PATCH | List detail |
| `/api/shortage/lists/{id}/submit/` | POST | Submit list |
| `/api/shortage/lists/{id}/items/` | GET, POST | Items in list |
| `/api/shortage/lists/{id}/ocr/` | POST | OCR image upload |
| `/api/shortage/items/{id}/confirm/` | POST | Confirm item match |
| `/api/shortage/items/{id}/rematch/` | POST | Trigger re-fuzzy-match |

---

## PURCHASING / PROCUREMENT  `/api/purchasing/` + `/api/procurement/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/purchasing/engine/config/` | GET, PATCH | Engine config (singleton) |
| `/api/purchasing/engine/run/` | POST | Trigger demand engine calculation |
| `/api/purchasing/metrics/` | GET | Per-item demand metrics |
| `/api/purchasing/recommendations/` | GET | Transfer recommendations |
| `/api/procurement/dashboard/`, `overview/` | GET | Procurement dashboard KPIs |
| `/api/procurement/history/` | GET | Purchase history analytics |
| `/api/procurement/segments/` (`summary/`, `{id}/update/`) | GET, POST | Supplier segmentation |
| `/api/procurement/foc/`, `expiry-returns/`, `returns/`, `tax-burden/` | GET | FOC / returns / expiry / tax analysis |
| `/api/procurement/suppliers/` (`{code}/`, `{code}/history/`), `suppliers-enhanced/`, `buyers/` | GET | Supplier + buyer performance |
| `/api/procurement/items/{code}/analysis/`, `lines/`, `price-control/` | GET | Item-level purchase analysis |
| `/api/procurement/margins/`, `optimization/`, `branches/` | GET | Margin / optimization / branch spend |
| `/api/procurement/mappings/` | GET, POST | Supplier↔item mappings |
| `/api/procurement/runs/`, `trigger/`, `snapshots/`, `alerts/` (`{id}/resolve/`) | GET, POST | Engine runs + snapshots + alerts |

---

## INVOICES  `/api/invoices/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/invoices/` | GET, POST | Supplier invoices |
| `/api/invoices/{id}/` | GET, PATCH | Invoice detail |
| `/api/invoices/{id}/ocr/` | POST | Trigger OCR extraction |
| `/api/invoices/{id}/lines/` | GET | Invoice lines |
| `/api/invoices/{id}/lines/{lid}/confirm/` | POST | Confirm item match |
| `/api/invoices/vendors/` | GET, POST | Vendor profiles |

---

## ANALYTICS  `/api/analytics/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/analytics/sales/` | GET | Sales dashboard data |
| `/api/analytics/performance/` | GET | Performance metrics |
| `/api/analytics/items/` | GET | Per-item analytics |

---

## DASHBOARD  `/api/dashboard/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/dashboard/` | GET | Aggregated KPIs (reservations, demand, transfers counts) |
| `/api/dashboard/activity/` | GET | Recent activity feed |

---

## CONFIG  `/api/config/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/config/settings/` | GET | All settings (public ones accessible without auth) |
| `/api/config/settings/{key}/` | GET, PATCH | Single setting |
| `/api/config/dropdowns/` | GET | All dropdown options |
| `/api/config/dropdowns/{key}/` | GET | Options for a specific dropdown key |
| `/api/config/pharmacy-profile/` | GET, PATCH | Singleton pharmacy profile |

---

## CALLCENTER  `/api/callcenter/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/callcenter/cases/` | GET, POST | Call center cases |
| `/api/callcenter/cases/{id}/` | GET, PATCH | Case detail |
| `/api/callcenter/analytics/` | GET | Call center KPIs |

---

## FOLLOWUPS  `/api/followups/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/followups/` | GET | Combined follow-up list (reservations + demands) |
| `/api/followups/{id}/complete/` | POST | Mark task complete |

---

## CHRONIC  `/api/chronic/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/chronic/items/` | GET | Tagged chronic medications |
| `/api/chronic/classify/` | POST | Classify item as chronic |

---

## SYNC  `/api/sync/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/sync/status/` | GET | Last sync timestamps per entity |
| `/api/sync/trigger/` | POST | Manually trigger sync for entity |
| `/api/sync/logs/` | GET | Sync operation logs |

---

## FINANCE  `/api/finance/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/finance/dashboard/` | GET | Financial summary KPIs |
| `/api/finance/coa/` | GET | Chart of accounts |
| `/api/finance/pnl/` | GET | Profit & loss |
| `/api/finance/cashflow/` | GET | Cash flow |
| `/api/finance/expenses/` | GET | Expense analytics |

---

## AUDIT  `/api/audit/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/audit/` | GET | Audit event log |
| `/api/audit/export/` | GET | Export audit trail |

---

## PRODUCTS (product_experience)  `/api/products/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/products/` , `search/`, `popular/`, `filter-options/`, `export/` | GET | Product catalog list/search/export |
| `/api/products/slug/{slug}/`, `barcode/{barcode}/`, `card/{softech_id}/` | GET | Lookups |
| `/api/products/{softech_id}/` | GET, PATCH | Product detail |
| `/api/products/{softech_id}/media\|content\|attributes\|seo/` | GET, POST | Content editor (media/content/attributes/SEO) |
| `/api/products/{softech_id}/related\|similar\|recommend/` | GET, POST | Relations + recommendations |
| `/api/products/{softech_id}/availability\|demand\|track\|share/` | GET, POST | Availability, demand, telemetry |
| `/api/products/bulk-initialize/` | POST | Bulk-seed product experience records |

---

## CAMPAIGNS  `/api/campaigns/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/campaigns/` (`{id}/`) | GET, POST | WhatsApp campaigns |
| `/api/campaigns/{id}/preview-audience/` | POST | Preview target audience |
| `/api/campaigns/{id}/request-approval\|approve\|reject/` | POST | Approval gate |
| `/api/campaigns/{id}/queue\|cancel/` | POST | Queue send / cancel |
| `/api/campaigns/{id}/messages/` (`{msg}/status/`), `stats/` | GET, POST | Per-recipient messages + delivery stats |

---

## TASKS  `/api/tasks/`  *(operational tasks — not background jobs)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/tasks/` (`{id}/`) | GET, POST | Operational tasks |
| `/api/tasks/{id}/complete\|reopen/` | POST | Status transitions |
| `/api/tasks/{id}/assignments\|items\|messages\|attachments\|audit/` | GET, POST | Assignees, checklist items, chatter, files, audit |
| `/api/tasks/schedules/` (`{id}/run/`) | GET, POST | Recurring schedules + run-now |
| `/api/tasks/my/`, `dashboard/`, `options/` | GET | My tasks, dashboard, filter options |

---

## CHEQUES  `/api/cheques/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/cheques/plans/` (`{id}/`) | GET, POST | Cheque plans + instalments |
| `/api/cheques/plans/{id}/activate\|cancel/` | POST | Activate / cancel plan |
| `/api/cheques/preview/`, `treasury/`, `holidays/` | GET | Plan preview, treasury dashboard, Egyptian holidays |

---

## DELIVERY  `/api/delivery/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/delivery/` (`{id}/`) | GET, POST | Delivery orders |
| `/api/delivery/{id}/assign\|accept\|dispatch\|complete\|partial\|fail\|cancel\|return\|close/` | POST | Order lifecycle transitions |
| `/api/delivery/{id}/collect-cash\|csat\|tracking-link\|whatsapp/` | POST | Cash collection, CSAT, share tracking link, WA message |
| `/api/delivery/track/{token}/` | GET | Public tokenized tracking (no auth) |
| `/api/delivery/summary\|dashboard\|driver-performance\|area-heatmap\|shift-report\|csat-report/` | GET | Analytics |
| `/api/delivery/drivers/`, `area-fees/`, `routes/` (`{id}/dispatch/`) | GET, POST | Drivers, area fees, route planning |
| `/api/delivery/app/my-orders\|my-route/`, `app/orders/{id}/location/` | GET, POST | Rider app |

## PAYMENTS  `/api/payments/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/payments/` (`{id}/`) | GET | External payments (Instapay/wallet/transfer) |
| `/api/payments/{id}/confirm\|reconcile\|dispute\|screenshot/` | POST | Confirm / reconcile / dispute / upload proof |
| `/api/payments/summary/` | GET | Payment KPIs |
| `/api/payments/audit/…` | GET | Payment-audit router |

---

## RECOMMENDATIONS  `/api/recommendations/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/recommendations/` | GET | Product recommendations |

---

## ENRICHMENT & IMAGES

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/enrichment/` | GET, POST | Item enrichment (DRF router) |
| `/api/enrichment/report/` | GET | Completeness report |
| `/api/enrichment/recompute-scores/` | POST | Recompute enrichment scores |
| `/api/enrichment/items/{item_pk}/` | GET | Per-item enrichment detail |
| `/api/enrichment/items/{item_pk}/generate/` | POST | Generate enrichment for an item |
| `/api/images/jobs/` | GET, POST | Image search jobs (+ `bulk/`, `revise-all/`) |
| `/api/images/jobs/{id}/` (`cancel/`) | GET, POST | Job detail / cancel |
| `/api/images/candidates/` (`{id}/review\|redownload/`) | GET, POST | Candidate images + review |
| `/api/images/products/{item_pk}/gallery\|upload\|set-primary\|reorder/` | GET, POST | Product gallery management |
| `/api/images/report/`, `review-queue/`, `insights/`, `filter-meta/` | GET | Coverage report / review queue / learning insights |

---

# ─────────── RECONCILED API GROUPS (added 2026-07-25) ───────────

## POS ORDERS  `/api/pos-orders/`  *(live SOFTECH pending-order writeback)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pos-orders/` | GET, POST | List / create pending indirect-POS order (draft) |
| `/api/pos-orders/reference/` | GET | Reference data (channels, pay types, branches, seller/cashier codes) |
| `/api/pos-orders/batches/` | GET | Batch availability for an item/branch |
| `/api/pos-orders/discount-suggest/` | POST | Suggested discount within operator authority |
| `/api/pos-orders/queue-status/` | GET | Offline retry-queue depth/health |
| `/api/pos-orders/flush/` | POST | Force-drain the offline queue now |
| `/api/pos-orders/{id}/` | GET, PATCH | Order detail (editable only while `draft`) |
| `/api/pos-orders/{id}/ready/` | POST | Mark ready → enqueue for push |
| `/api/pos-orders/{id}/push/` | POST | Push to SOFTECH (`stktransm5`/`stktrans5`/`branchesales5`) |
| `/api/pos-orders/{id}/cancel/` | POST | Cancel (pre-push) |

## INSURANCE  `/api/insurance/`  *(DRF router)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/insurance/claims/` | GET, POST | Insurance claims (motalba) |
| `/api/insurance/clients/`, `subclients/`, `parent-clients/`, `contracts/` | GET, POST | Client/contract hierarchy |
| `/api/insurance/billing-groups/` | GET, POST | Claim billing groups |
| `/api/insurance/export-profiles/`, `pivot-templates/` | GET, POST | Print/export profiles + pivot templates |
| `/api/insurance/sync-cache/` | POST | Sync SOFTECH motalba/companiesitems cache |

## PRICING APPROVALS  `/api/pricing-approvals/`  *(discount writeback to SOFTECH)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pricing-approvals/` | GET, POST | Item price-change requests |
| `/api/pricing-approvals/{id}/` | GET, PATCH | Request detail |
| `/api/pricing-approvals/{id}/approve\|reject\|rollback/` | POST | Decision + rollback |
| `/api/pricing-approvals/{id}/replication\|force-replication/` | POST | Replicate approved change to SOFTECH |
| `/api/pricing-approvals/preview/`, `items/{softech_id}/prices/`, `history/{softech_id}/` | GET | Price preview / current prices / history |
| `/api/pricing-approvals/sla/`, `pending-count/`, `branch-health/`, `who-changed-what/`, `discount-impact/` | GET | Dashboards |
| `/api/pricing-approvals/replication/scan\|scans\|repair\|item/{softech_id}/` | GET, POST | Replication reconciliation + gap repair |
| `/api/pricing-approvals/import/`, `policy/`, `approver-info/` | GET, POST | CSV import, policy, approver SOFTECH identity |

## APPROVALS  `/api/approvals/`  *(operational + HR workflows)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/approvals/workflows/` | GET, POST | Workflow + step definitions (DRF router) |
| `/api/approvals/requests/` | GET, POST | Approval requests |
| `/api/approvals/requests/{id}/` | GET, PATCH | Request detail + decisions/escalation |

## BATCHES  `/api/batches/`  *(FEFO + near-expiry)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/batches/` | GET, POST | Stock batches (DRF router) — FEFO, movements, near-expiry alerts |

## FORECASTING  `/api/forecasting/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/forecasting/seasonality/` | GET | Seasonality indices |
| `/api/forecasting/runs/` | GET, POST | Forecast runs |
| `/api/forecasting/accuracy/` | GET | Forecast accuracy tracking |

## LOYALTY  `/api/loyalty/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/loyalty/tiers/`, `rewards/` | GET | Tiers + reward catalog |
| `/api/loyalty/customers/{id}/account\|transactions\|adjust\|redeem\|redemptions/` | GET, POST | Per-customer account + point ops |
| `/api/loyalty/redemptions/{id}/approve/` | POST | Approve redemption |
| `/api/loyalty/customers/{id}/softech-balance\|softech-log/` | GET | SOFTECH points reconciliation |

## REFERRAL  `/api/referral/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/referral/my-code/`, `customers/{id}/code/` | GET | Referral codes |
| `/api/referral/leads/` (`{id}/`, `events/`) | GET, POST | Referral leads + events |
| `/api/referral/leads/{id}/validate\|invite/` | POST | Validate / invite lead |

## HR  `/api/hr/`  *(DRF router — attendance + leave)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/hr/attendance/` | GET, POST | Geofenced GPS clock in/out |
| `/api/hr/leave-types\|leave-balances\|leave-requests/` | GET, POST | Leave management |
| `/api/hr/overtime\|salary-advances\|expense-claims/` | GET, POST | OT / advances / expense claims |
| `/api/hr/shifts\|shift-assignments/` | GET, POST | Shift scheduling |

## QA  `/api/qa/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/qa/templates/` | GET | Checklist templates |
| `/api/qa/inspections/` | GET, POST | Branch QA inspections (pass/fail/na + score) |

## WHATSAPP  `/api/whatsapp/`  *(Cloud API)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/whatsapp/webhook/` | GET, POST | Meta webhook (verify + inbound) |
| `/api/whatsapp/conversations/` (`{id}/`, `messages/`) | GET | Conversations + messages |
| `/api/whatsapp/conversations/{id}/send\|send-template/` | POST | Send text / template |
| `/api/whatsapp/templates/` | GET | Approved message templates |

## PBX  `/api/pbx/`  *(Issabel AMI)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pbx/agents/` (`{id}/`, `my-extension/`) | GET | Agent extensions |
| `/api/pbx/queues/`, `sessions/` (`{id}/`) | GET | Queues + call sessions |
| `/api/pbx/live/`, `spy/`, `recordings/{id}/` | GET, POST | Live wallboard, spy/whisper, recordings |

## OMNI  `/api/omni/`  *(unified inbox / CEP)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/omni/conversations/` (`{id}/`, `timeline/`, `reply/`, `ai-assist/`) | GET, POST | Unified conversation timeline + reply |
| `/api/omni/accounts/` (`{id}/`, `health/`) | GET | Channel accounts + health |
| `/api/omni/wallboard/`, `analytics/` | GET | Supervisor wallboard + cross-channel BI |
| `/api/omni/automations/` (`{id}/`, `automation-runs/`) | GET, POST | No-code automation rules + runs |
| `/api/omni/events/{id}/transcribe/` | POST | Transcribe a call/voice event |

## SOCIAL  `/api/social/`  *(inbound webhooks)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/social/webhook/meta/` | GET, POST | Messenger + Instagram (Meta Graph) |
| `/api/social/webhook/telegram/` | POST | Telegram |
| `/api/social/webhook/tiktok/` | POST | TikTok (stub) |

## TRANSITS  `/api/transits/`  *(also `pick-zones/`, `pick-rules/`, `item-overrides/`)*

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/transits/` (`{id}/`, `mark-received/`) | GET, POST | In-transit (doccode-125) transfers |
| `/api/transits/{id}/export-picking\|export-stocking/` | GET | ورقة التجميع / ورقة الترصيص export (+ bulk POST) |
| `/api/transits/pick-zones\|pick-rules\|item-overrides/` | GET, POST | Classification config (per location+purpose) |
| `/api/transits/settings\|preview\|uncategorized\|classify-items\|seed-defaults/` | GET, POST | Threshold, preview, bulk classify |
