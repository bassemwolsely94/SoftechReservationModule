# Batch 4 — Overblock review (owner decision 3)

`role_overblocks` lists every request the **code matrix allows** but the server answers **403**.
After Z-1 … Z-10 it holds **772** lines: 157 already carry a `# reason:` from their Z item, 615 are
unreviewed. Every unreviewed line was resolved to its view and the check that refuses it
(script: the sweep path → Django `resolve()` → permission classes + role checks in the handler).

| Cause | Lines | What it is | Proposal |
|---|---:|---|---|
| A. Export counted as a write | 105 (+99 reviewed) | The middleware accepts a POST if the role holds any of `create / edit / approve / assign / finalize / export`; roles with view + export (quality manager, purchasing, delivery) pass it and the view refuses | **Decision 1** |
| B. Sweep noise | 161 | The view has no handler for that method (e.g. GET on a POST-only action); a strict permission answers 403 before DRF can answer 405 | Tooling fix — not a lockout |
| C. Stricter on purpose | 305 | Admin-only or role-specific checks inside the view, finer than the matrix (SOFTECH writes, system triggers, pricing approvals, PBX supervision…) | Keep, add `# reason:` |
| D. Screen shown, server refuses | 44 | The role holds the matrix grant and (usually) sees the screen, but a hard-coded role list in the view refuses | **Decisions 2 – 9** |

## Decision 1 — export is not a write (A, 204 lines)

Today a POST passes the middleware with an `export` grant alone, so the matrix *appears* to grant
quality manager / purchasing / delivery writes on chronic, follow-ups, reservations, call center,
demand, transfers, incentives, delivery, customers, stock count, shortage — and the views refuse.

**Proposal:** drop `export` from the middleware's POST tuple; map the few POST endpoints that
really are exports (Excel builds sent by POST) to `export` explicitly. The middleware then refuses
what the view refuses — same outcome for users, the 204 lines disappear, and the matrix stops
over-stating what quality manager and purchasing can do. No grant changes.

## Decision B — sweep noise (161 lines)

Teach the sweep that a 403 on a method the view does not implement is "no such endpoint", not an
overblock. Test tooling only; no app behaviour changes.

## Keep — stricter on purpose (C, 305 lines)

| Area | Who is refused | Why it stays |
|---|---|---|
| Pricing approvals (approve / reject / force replication / replication scans / policy / alignment / who-changed-what / branch health / discount impact) | everyone but admin | `IsAdminRole` — price changes and SOFTECH replication (Z-6) |
| System triggers (`bulk-initialize`, procurement engine / reclassify / segmentation) | non-admins | Django-staff only; heavy or global jobs |
| Users / ERP systems / permissions matrix / staff activity | supervisor | Admin screens |
| PBX diagnostics / spy / extension map & status, whisper control, omni automations | call center, quality manager, viewer | Admin / supervisor supervision tools |
| Gift coupons (batches, push / probe / verify / sync, customers, no-serial) | call center, pharmacist, salesperson, viewer | Coupon tab is management / purchasing / quality; push writes to SOFTECH |
| Voucher cancel | purchasing, supervisor | Admin only, by design (help says so) |
| Customer merges, loyalty point adjustment | non-managers | Sensitive customer / money data |
| Product content / media / SEO | pharmacist, purchasing | Content managers |
| Offers channel apply (`posdiscp` / `promo`) | supervisor | Writes SOFTECH (Z-5a) |
| Finance reconciliation writes & SOFTECH allocation, recon reports / exports | purchasing, quality manager | Finance approve / export + SOFTECH writes (Z-3) |
| Demand cancel / fulfil / disqualify / requalify / from-reservation | call center, pharmacist, salesperson, supervisor | Need `delete` / `finalize` / `approve`, finer than the POST check |
| Delivery assign / routes / dispatch / backfill, delivery-role order & fee edits | delivery, pharmacist, salesperson | Need `assign`; drivers do not create orders |
| Driver app (my orders / route / location) | anyone without a linked driver record | Not a driver |
| Follow-up maintenance (dedupe / cleanup / backfill / priority scores / reminders run-now) | non-admins | Batch jobs |
| Pick-zone writes, procurement supplier categories / rules | non-purchasing / non-admin | Z-7c / procurement config |
| Purchasing branch requests / ISR recent | viewer | Purchasing + supply groups only (owner decision 4) |
| Vision corpus stats | call center, delivery, quality manager, salesperson, viewer | OCR internals |
| Replacement grants / rule versions | pharmacist, supervisor | Replacement managers |

## Decisions — screen shown, server refuses (D, 44 lines + earlier flags)

| # | Where | Today | Proposal |
|---|---|---|---|
| 2 | **Payment confirm** (`/payments/<id>/confirm/`) | Matrix and help: finance approve = purchasing + admin. View hard-codes admin + **pharmacist**. Net: admin only | Confirm = finance approve holders (admin, purchasing); drop the role list. *Payments — owner sign-off* |
| 3 | **Demand analytics** (dashboard, capture leaderboard, lost-value, price objections, purchase suggestions, substitutions) | Mapped to analytics (Z-8c); view allows admin / purchasing / call center only | Open to analytics view (pharmacist, supervisor, quality manager, viewer) — or keep and say so in help |
| 4 | **Omni wallboard & analytics** | Agents (call center) refused; admin / supervisor / quality manager only | Wallboard to call center (it is the agents' screen); analytics stays supervisors |
| 5 | **Purchasing catch-up / sync items now** | Purchasing refused (inner role list) | Allow purchasing — the refresh-button rule for engine-fed screens |
| 6 | **Expiry sync triggers** (stock-expiry / purchase-expiry) | Django `is_staff` only — the screen's refresh fails for purchasing / pharmacist | Catalog edit or purchasing (refresh-button rule) |
| 7 | **Transfer discrepancy report** | Admin / purchasing only; supervisor & pharmacist hold transfers view | Open to supervisor (branch oversight) or keep |
| 8 | **Abuse-flag summary / audit for-user** | Admin only; quality manager & supervisor hold audit view | Quality manager yes (QA role); supervisor keep |
| 9 | **Matrix vs screen gaps** (flagged during Z-8/9) | Supervisors have no stock-count grant but see the screen; chronic classifier shown to call center & supervisor; mobile Reservations / Transfers tabs shown to delivery & purchasing | Decide grant or hide each |

Open from Z-10 (for this review):

- **Self-approval in the shared approvals engine** — anyone eligible for a step can approve their
  own request, discount / price approvals included (HR submit already blocks it, Z-10c). Proposal:
  refuse `decided_by == requested_by` in the engine. *Pricing — owner sign-off.*
- **Editing a confirmed supplier invoice** goes around the confirmer. Proposal: an edit after
  confirm sends the invoice back to review for a second confirm.

## After the decisions

Each accepted change is a Z-11 diff with its own failing test, like Z-1 … Z-10. Kept lines get
their `# reason:` in one pass; Decision 1 and the sweep fix remove ≈365 lines outright.
