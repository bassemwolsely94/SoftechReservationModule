# 01 — Master Project Document
## ElRezeiky Pharmacy Operations Platform

---

### Project Vision

A unified, real-time pharmacy operations platform for the ElRezeiky pharmacy chain.  
It replaces fragmented spreadsheet workflows with a structured, intelligent system that connects every branch, every team, and every workflow — from customer contact to stock procurement. SOFTECH ERP is the authoritative source and is consumed as a **read-only mirror by default**; the only writes back to SOFTECH happen through a small number of **audited, ERP-client-mimicking writeback channels** (e.g. approved item-discount changes, and call-center pending sales orders) that execute the identical DML the native ERP client would and let the ERP's own triggers/replication propagate it.

---

### System Objectives

1. **Reservation Management** — track customer demand for out-of-stock items end-to-end
2. **Demand Intelligence** — capture lost sales, manage follow-ups, and derive reorder signals
3. **Inter-branch Transfer Coordination** — approval-gated request workflow fed into ERP
4. **CRM & Customer Health Profiling** — segment customers, detect churn, map chronic conditions
5. **Procurement Optimization** — ABC analysis, demand planning, supplier segmentation
6. **Voucher & Incentive Management** — OTP-secured voucher redemption + sales incentive engine
7. **Stock Count & Shortage Tracking** — transaction-based stock validation + shortage list OCR
8. **Financial Intelligence** — invoice capture, incentive settlements, cheque planning
9. **Real-time Collaboration** — WebSocket-based notifications and chatter on every record
10. **ERP Synchronization** — one-way mirror of SOFTECH branches, items, customers, transactions

---

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│        SOFTECH ERP (Sybase ASE — jConnect JDBC via jpype)   │
│   Items · Customers · PurchaseHistory · StockTransactions   │
└──────────────────────────┬──────────────────────────────────┘
                           │  Read-only sync (default) +
                           │  audited writeback channels (jConnect)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              PostgreSQL (Primary Database)                   │
│   ERP Mirror Tables + Platform-Native Tables               │
└────────────┬──────────────────────────────┬─────────────────┘
             │ Django ORM                   │ Django Channels
             ▼                             ▼
┌─────────────────────┐        ┌──────────────────────────────┐
│  Django 4.2 + DRF   │        │  Redis (WebSocket broker +   │
│  Daphne ASGI        │        │  notification dedup cache)   │
│  APScheduler        │        └──────────────────────────────┘
└────────┬────────────┘
         │ REST API (JWT)
         ▼
┌─────────────────────────────────────────────────────────────┐
│              React 18 SPA (Vite + Tailwind)                 │
│   TanStack Query · Zustand · React Router 6                 │
│   75+ screens · 24 reusable components                     │
└─────────────────────────────────────────────────────────────┘
```

---

### Business Domains

| Domain | Core Module(s) | Status |
|--------|---------------|--------|
| Customer Intake | Reservations, Demand | Active |
| CRM & Segmentation | Customers, Chronic | Active |
| Inter-branch Stock | Transfers | Active |
| Purchasing & Planning | Purchasing, Shortage | Active |
| Voucher Platform | Vouchers | Active |
| Sales Incentives | Incentives | Active |
| Invoice & Supplier | Invoices | Partial |
| Stock Validation | StockCount | Active |
| Notifications & Chat | Notifications | Active |
| Analytics | Analytics, Dashboard | Partial |
| Finance Intelligence | Finance (external data) | Partial |
| Call Center | CallCenter, FollowUps | Active |
| ERP Synchronization | Sync, Catalog, Branches | Active |
| Admin & Audit | Users, Audit, Config | Active |

---

### Major Modules (48 Django Apps)

> The table below lists the principal apps. The project now contains **48 Django apps**
> under `apps/` (the earlier "32" figure was stale). Beyond those shown here:
> `analytics`, `approvals`, `audit`, `batches`, `campaigns`, `cheques`, `dashboard`,
> `delivery`, `discount_approvals`, `enrichment`, `erp`, `finance`, `forecasting`, `hr`,
> `images`, `insurance`, `loyalty`, `payments`, `pbx`, `portal`, `procurement`,
> `product_experience`, `qa`, `recommendations`, `referral`, `tasks`, `transits`,
> `whatsapp`, plus the `tests` app.

| App | Role |
|-----|------|
| `branches` | Branch master + per-branch feature flags |
| `catalog` | Item master, stock levels, barcodes, bundles |
| `customers` | Customer master, health profiles, purchase history |
| `reservations` | Reservation workflow with ERP match |
| `demand` | Demand records, SLA tracking, follow-up tasks |
| `transfers` | Inter-branch transfer request workflow |
| `users` | Staff profiles, ERP user cache, roles |
| `notifications` | Persistent notifications + WebSocket push |
| `purchasing` | Demand engine, ABC analysis, transfer recommendations |
| `invoices` | Supplier invoices, OCR, fuzzy item matching |
| `vouchers` | Voucher rules, OTP, redemption documents |
| `incentives` | Sales incentive programs, settlements |
| `stockcount` | Stock count sessions + snapshots |
| `shortage` | Shortage lists + OCR item matching |
| `callcenter` | Call center case tracking |
| `followups` | Follow-up task management |
| `chronic` | Chronic medication detection & tagging |
| `config` | System settings, dropdown options, pharmacy profile |
| `analytics` | Sales & performance analytics |
| `audit` | Platform-wide audit trail |
| `sync` | ERP synchronization management commands |
| `dashboard` | Aggregated KPI views |
| `finance` | Financial intelligence (external data) |
| `enrichment` | Product image enrichment |
| `images` | Image storage + OCR |
| `tasks` | Background task management |
| `deliveries` | Delivery tracking |
| `payments` | Payment tracking |
| `recommendations` | Product recommendation engine |
| `campaigns` | WhatsApp campaign management |
| `cheques` | Cheque planning |
| `erp` | ERP utility layer |

---

### Module Relationships

```
catalog ──────► reservations
catalog ──────► demand
catalog ──────► transfers
catalog ──────► purchasing
catalog ──────► vouchers
catalog ──────► incentives
catalog ──────► shortage
catalog ──────► stockcount

customers ────► reservations
customers ────► demand
customers ────► vouchers
customers ────► callcenter

branches ────► reservations
branches ────► demand
branches ────► transfers
branches ────► stockcount
branches ────► shortage

users ───────► (all modules — created_by, assigned_to)
notifications ◄── (reservations, demand, transfers, chatter mentions)
```

---

### Current Implementation Status

| Area | Completeness |
|------|-------------|
| Backend models | ~95% complete |
| REST APIs | ~85% complete |
| Frontend screens | ~80% complete |
| ERP sync | ~90% complete |
| WebSocket real-time | ~90% complete |
| Business rules enforcement | ~70% complete |
| Permissions/guards | ~65% complete |
| Analytics | ~50% complete |
| Finance module | ~40% complete |
| Documentation | 5% → this document |
