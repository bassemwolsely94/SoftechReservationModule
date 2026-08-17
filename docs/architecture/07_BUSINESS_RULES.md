# 07 — Business Rules

All extracted business rules, organized by domain.

---

## BRANCH RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| Only operational branches can accept reservations | `Branch.is_operational` checked at reservation creation | `apps/branches/models.py` |
| Branches with `notifications_enabled=False` suppress all notification sends | Checked in `Notification.send_to_branch()` | `apps/notifications/models.py` |
| Store codes `102`, `103`, `105` are excluded from operational stock | `EXCLUDED_STORE_CODES = {'102', '103', '105'}` | `apps/catalog/models.py` |

---

## CATALOG RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| `softech_id` on Item is immutable after initial sync | Never updated post-upsert | `apps/sync/` |
| Items with `can_transact=False` cannot be reserved, transferred, or sold | Gate check in reservation/transfer views | Multiple |
| Items with `is_stockable=False` excluded from stock count sessions | Filter in stockcount snapshot | `apps/stockcount/` |
| `store_classif` controls which stores can hold the item | Enforced by SOFTECH; informational only in Django | `apps/catalog/models.py` |
| Variant groups are virtual (no ERP mutation) | Stored only in PG | `apps/catalog/models.py` |

---

## RESERVATION RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| Reservations require `Branch.is_operational = True` | View-level guard | `apps/reservations/views.py` |
| Only one active reservation per item per customer per branch (recommendation, not enforced) | No DB unique constraint | — |
| ERP match window: 7 days before/after fulfillment date | Hardcoded in ERP match service | `apps/reservations/` |
| ERP match checks customer PIC + item code + date window | Match strategy | `apps/reservations/` |
| Downpayment reduces outstanding balance (informational) | `ReservationDownpayment.amount` stored | `apps/reservations/models.py` |
| Reservation images are soft-deleted via `is_deleted` on activity | `ReservationActivity.is_deleted` | `apps/reservations/models.py` |

---

## DEMAND RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| SLA: NEW → ASSIGNED within 10 minutes | `SLA_MINUTES = {'new': 10, 'assigned': 20}` | `apps/demand/models.py` |
| SLA: ASSIGNED → contacted within 20 minutes | Same | `apps/demand/models.py` |
| `demand_number` format: DEM-XXXXXX (auto-generated) | Model save signal | `apps/demand/models.py` |
| Lost demands require a `lost_reason` | Enforced in serializer | `apps/demand/serializers.py` |
| `ItemDemandStat` refreshed daily via management command | `generate_demand_records` command | `apps/demand/management/` |
| Demand stats drive `suggest_order` and `suggest_transfer` flags | Computed in stat update | `apps/demand/models.py` |

---

## TRANSFER RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| `request_number` format: TR-XXXXXX (DB sequence) | Sequence generator | `apps/transfers/models.py` |
| Only draft transfers are editable | `is_editable` property | `apps/transfers/models.py` |
| Rejection requires `rejection_reason` | Serializer validation | `apps/transfers/serializers.py` |
| Needs-revision requires `revision_notes` | Serializer validation | `apps/transfers/serializers.py` |
| TransferRequestItem uses PROTECT on item deletion | `on_delete=models.PROTECT` | `apps/transfers/models.py` |
| No stock mutations in this system — ERP entry is manual | Architecture decision | Design |
| Transfer chatter messages are soft-deleted | `is_deleted` flag | `apps/transfers/models.py` |
| `source_recommendation` tracks which TransferRecommendation generated this TR | FK with ROI tracking | `apps/transfers/models.py` |

---

## CUSTOMER / CRM RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| `softech_pic` is the globally unique customer identifier across branches | Used as dedup key | `apps/customers/models.py` |
| Customer segments: VIP / Loyal / Regular / At Risk / Dormant / New / Churned | 7-class model | `apps/customers/models.py` |
| Churn score range: 0.0 (no risk) to 1.0 (churned) | Float field | `apps/customers/models.py` |
| Churn segments: low / medium / high / critical | Binned from churn_score | `apps/customers/models.py` |
| `can_see_customer_phone = False` hides phone numbers in API response | Enforced in serializer | `apps/customers/serializers.py` |
| Health profile auto-computed via `segment_customers` daily command | `last_computed_at` updated | `apps/customers/management/` |
| `manually_overridden = True` prevents auto-overwrite of health profile | Checked in command | `apps/customers/management/` |
| `polypharmacy_flag` set when > 5 distinct chronic medication categories purchased | Computed in health profile update | `apps/customers/patient_profile.py` |

---

## VOUCHER RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| OTP plain code NEVER stored — only HMAC-SHA256 hash + salt | Design pattern | `apps/vouchers/models.py` |
| OTP expires after 3 minutes | `expiry_minutes=3` | `apps/vouchers/models.py` |
| Max 3 OTP retries per OTP instance | `MAX_RETRIES = 3` | `apps/vouchers/models.py` |
| Max 3 OTP resends per voucher+phone per 10 minutes | Enforced at view level | `apps/vouchers/views.py` |
| Redemption document expires after 15 minutes | `expires_at = now + 15min` | `apps/vouchers/models.py` |
| Previous active OTPs invalidated on new OTP generation | `cls.objects.filter(...).update(is_used=True)` | `apps/vouchers/models.py` |
| `assigned` vouchers require `VoucherAssignment` for the phone | `check_customer_eligibility` | `apps/vouchers/models.py` |
| `private` vouchers scoped to a single customer FK | `voucher_category = 'private'` | `apps/vouchers/models.py` |
| `usage_limit_per_customer` and `usage_limit_per_day` enforced on eligibility check | `check_customer_eligibility` | `apps/vouchers/models.py` |
| `min_order_value` check before calculating discount | `calculate_discount()` | `apps/vouchers/models.py` |
| `max_discount_cap` limits maximum discount regardless of percentage | `calculate_discount()` | `apps/vouchers/models.py` |
| Discount cannot exceed order value | `min(discount, order_amount)` | `apps/vouchers/models.py` |
| `VoucherRedemption` is immutable once created | No update methods | `apps/vouchers/models.py` |

---

## INCENTIVE RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| IncentiveTransaction is immutable audit trail | Only engine writes it | `apps/incentives/models.py` |
| Tiered slab: rate applied to ALL units (not incrementally) | Slab match applies to full period quantity | `apps/incentives/engine.py` |
| Cross-period returns flagged separately | `is_cross_period_return = True` | `apps/incentives/models.py` |
| Returns produce negative `incentive_amount` | Signed amounts | `apps/incentives/models.py` |
| Finalized settlements are locked — no further adjustments | `is_finalized` check | `apps/incentives/views.py` |
| `priority` field: lower number = higher priority for conflict resolution | `ordering = ['priority', 'item_code']` | `apps/incentives/models.py` |
| `IncentiveRuleItem.incentive_override` overrides rule-level value for specific SKU | Engine checks override first | `apps/incentives/engine.py` |
| Simulate mode: no records written | `mode='simulate'` branch in engine | `apps/incentives/engine.py` |

---

## STOCK COUNT RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| `StockCountSnapshot.expected_qty` is IMMUTABLE after snapshot | No update allowed | `apps/stockcount/models.py` |
| Variance types: ok / surplus / deficit | Computed on upload | `apps/stockcount/views.py` |
| `difference = counted_qty − expected_qty` | Computed on upload | `apps/stockcount/views.py` |
| Session modes: transaction / full / filtered | Determines snapshot strategy | `apps/stockcount/models.py` |
| Store code `102/103/105` excluded from stock count | Same as catalog rule | `apps/stockcount/` |

---

## SHORTAGE RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| rapidfuzz match score stored for audit | `match_score` field | `apps/shortage/models.py` |
| Items with low match score require manual confirmation | Threshold in matching logic | `apps/shortage/matching.py` |
| `confirmed_by` + `confirmed_at` logged for audit | Model fields | `apps/shortage/models.py` |
| Source options: manual / voice / ocr / bulk | Per-item granularity | `apps/shortage/models.py` |

---

## NOTIFICATION RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| Notifications deduplicated within 5-minute window per `dedup_key` | Redis cache + `dedup_key` field | `apps/notifications/models.py` |
| `BranchSettings.notifications_enabled = False` suppresses all branch sends | Checked in factory methods | `apps/notifications/models.py` |
| Notifications always created with `priority = 'high'` | Hardcoded | `apps/notifications/models.py` |
| ChatterMessage `@mention` supports ASCII and Arabic usernames | Regex: `@([\w؀-ۿ]+)` | `apps/notifications/models.py` |
| @mention triggers notification to mentioned user | `_process_mentions()` | `apps/notifications/models.py` |
| ChatterMessage triggers real-time push on save | `_push_chatter_realtime()` | `apps/notifications/models.py` |

---

## PURCHASING / DEMAND ENGINE RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| Weighted average demand: 30d×0.5 + 90d×0.3 + 365d×0.2 | `EngineConfig` singleton | `apps/purchasing/models.py` |
| ABC A class: top 70% of revenue items | `abc_a_threshold = 0.70` | `apps/purchasing/models.py` |
| ABC B class: next 20% (70%–90%) | `abc_b_threshold = 0.90` | `apps/purchasing/models.py` |
| ABC C class: remaining 10% | Computed | `apps/purchasing/models.py` |
| Safety stock multiplier: 1.0× base | `ss_multiplier = 1.0` | `apps/purchasing/models.py` |
| High-demand safety stock: 2.0× | `ss_high_threshold = 2.0` | `apps/purchasing/models.py` |
| Transfer recommendations include ROI score | `roi_score` field | `apps/purchasing/models.py` |

---

## USER / PERMISSION RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| `access_all_branches = True` bypasses branch filtering | Checked in views | `apps/users/models.py` |
| `allowed_branches` whitelist restricts visible branches | `StaffProfile.allowed_branches` | `apps/users/models.py` |
| `restricted_branches` blacklist excludes specific branches | `StaffProfile.restricted_branches` | `apps/users/models.py` |
| `can_see_customer_phone = False` redacts phone in API | Serializer conditional | `apps/customers/serializers.py` |
| `can_see_all_customers` controls cross-branch customer visibility | View filter | `apps/customers/views.py` |
| ERP username must exist in `ERPUser` cache before staff account creation | Validation in user creation | `apps/users/views.py` |

---

## CONFIG RULES

| Rule | Implementation | Location |
|------|---------------|----------|
| `PharmacyProfile` is a singleton (pk=1) | `get_or_create(pk=1)` | `apps/config/models.py` |
| `EngineConfig` is a singleton (pk=1) | Same pattern | `apps/purchasing/models.py` |
| `SystemSetting.is_public = True` allows unauthenticated API read | View-level check | `apps/config/views.py` |
| `DropdownOption.is_system = True` prevents deletion | Admin guard | `apps/config/admin.py` |
| `DropdownOption(dropdown_key, value)` is unique | DB unique_together | `apps/config/models.py` |
