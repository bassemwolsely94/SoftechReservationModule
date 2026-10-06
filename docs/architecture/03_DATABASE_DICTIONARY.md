# 03 — Database Dictionary

Complete reference for every table in the PostgreSQL database.  
Tables prefixed with their Django app name.

---

## BRANCHES

### branches_branch
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| softech_branch_id | varchar | ERP branch identifier |
| code | varchar | Short branch code |
| name | varchar | Branch name (Arabic) |
| address | text | Physical address |
| phone | varchar | Contact number |
| is_active | bool | Master on/off |
| is_operational | bool | Controls reservation creation gate |

### branches_branchsettings
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| branch_id | FK → branches_branch | OneToOne |
| allow_reservations | bool | Feature flag |
| allow_transfers | bool | Feature flag |
| notifications_enabled | bool | Suppresses branch-wide notification sends |

---

## CATALOG

### catalog_item  (~37,500 rows — synced from SOFTECH)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| softech_id | varchar unique | SOFTECH item code (immutable after sync) |
| name | varchar | Arabic item name |
| barcode | varchar | Primary barcode |
| category_id | FK → catalog_category | |
| pack_price | decimal | Pack selling price |
| unit_price | decimal | Unit selling price |
| cost_price | decimal | Cost (from SOFTECH) |
| medicine_type | varchar | Drug classification |
| family | varchar | Product family |
| supplier | varchar | Supplier name |
| producer | varchar | Manufacturer |
| origin | varchar | Country of origin |
| shape | varchar | Dosage form |
| effect | varchar | Therapeutic effect |
| is_stockable | bool | Whether item holds stock |
| is_fast_moving | bool | High-velocity flag |
| insurance_type | varchar | Insurance classification |
| item_level | varchar | Item hierarchy level |
| pack_qty | int | Units per pack |
| branch_trans | bool | Branch-to-branch transfer allowed |
| supplier_trans | bool | Can be ordered from supplier |
| customer_trans | bool | Can be sold to customer |
| nosale_classif | varchar | No-sale classification code |
| store_classif | varchar | Store type restriction |
| requires_fridge | bool | Cold chain flag |
| has_points | bool | Loyalty points eligible |
| active_ingredients | text | Ingredient list |
| phcode | varchar | ATC/therapeutic code |
| is_active | bool | Active in catalog |
| comment | text | Notes |

### catalog_category
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| softech_id | varchar | ERP category code |
| name_ar | varchar | Category name Arabic |

### catalog_itemstock  (stock levels per branch)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| item_id | FK → catalog_item | |
| branch_id | FK → branches_branch | |
| quantity_on_hand | decimal | Current stock |
| monthly_qty | decimal | Monthly movement |
| on_order_qty | decimal | Quantity on order |

### catalog_itembarcode
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| item_id | FK → catalog_item | |
| barcode | varchar | Secondary/EAN-13 barcode |
| is_active | bool | |

### catalog_chronicmedication
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| item_id | FK → catalog_item | |
| category_label | varchar | Chronic condition category |
| is_active | bool | |

### catalog_catalogvariantgroup
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| name | varchar | Variant group name |
| name_ar | varchar | Arabic name |
| created_by_id | FK → users_staffprofile | |

### catalog_variantmember
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| group_id | FK → catalog_catalogvariantgroup | |
| item_id | FK → catalog_item | OneToOne |
| variant_label | varchar | e.g. "10mg", "20mg" |
| sort_order | int | Display order |

### catalog_productbundle
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| name | varchar | |
| name_ar | varchar | |
| discount_type | varchar | percent / fixed |
| discount_value | decimal | |
| created_by_id | FK → users_staffprofile | |

### catalog_bundleitem
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| bundle_id | FK → catalog_productbundle | |
| item_id | FK → catalog_item | |
| quantity | int | |

---

## CUSTOMERS

### customers_customer  (~40,000 rows — synced from SOFTECH)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| softech_id | varchar | Branch-local ERP ID |
| softech_pic | varchar unique | PIC — globally unique ERP person code |
| softech_ptcode | varchar | Person type code |
| softech_ptclassifcode | varchar | Channel code |
| softech_global_code | varchar | Global customer code |
| name | varchar | Customer name |
| phone | varchar | Primary phone |
| phone_alt | varchar | Secondary phone |
| email | varchar | Email |
| address | text | Address |
| date_of_birth | date | |
| chronic_conditions | text | Free-text notes |
| notes_softech | text | ERP notes |
| is_guest | bool | Guest/anonymous flag |
| discount_percent | decimal | Permanent discount |
| preferred_branch_id | FK → branches_branch | |
| lifetime_value_ltv | decimal | Computed LTV |
| segment | varchar | vip/loyal/regular/at_risk/dormant/new/churned |
| last_visit_date | date | |
| days_since_last_visit | int | |
| purchase_count_90d | int | Rolling 90-day visit count |
| complaint_risk_score | decimal | |
| churn_score | decimal | 0.0–1.0 |
| churn_segment | varchar | low/medium/high/critical |
| whatsapp_phone | varchar | |
| created_by_id | FK → users_staffprofile | |
| created_at | timestamp | |
| updated_at | timestamp | |

### customers_customernote
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| customer_id | FK → customers_customer | |
| note | text | |
| created_by_id | FK → users_staffprofile | |
| created_at | timestamp | |

### customers_customerhealthprofile  (OneToOne to Customer)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| customer_id | FK → customers_customer UNIQUE | |
| has_diabetes | bool | |
| has_hypertension | bool | |
| has_cardiovascular | bool | |
| has_thyroid | bool | |
| has_cholesterol | bool | |
| has_asthma | bool | |
| has_psychiatric | bool | |
| has_epilepsy | bool | |
| has_osteoporosis | bool | |
| has_renal | bool | |
| has_oncology | bool | |
| has_gerd | bool | |
| has_anemia | bool | |
| has_anticoagulant | bool | |
| has_immunosuppressant | bool | |
| has_other_chronic | bool | |
| condition_confidence | jsonb | Per-condition confidence scores |
| active_medications | jsonb | Active medication list |
| known_allergies | jsonb | Allergy list |
| pregnancy_flag | bool | |
| lactation_flag | bool | |
| pediatric_patient | bool | |
| polypharmacy_flag | bool | |
| last_computed_at | timestamp | |
| manually_overridden | bool | |
| updated_by_id | FK → users_staffprofile | |

### customers_purchasehistory  (~3–4M rows/month from SOFTECH)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| softech_invoice_id | varchar unique | |
| doc_code | varchar | '115'=sale, '30'=return |
| docnumber | varchar | Invoice number |
| invoice_date | date | |
| total_amount | decimal | |
| customer_id | FK → customers_customer | nullable |
| softech_phcode | varchar | PIC on receipt |
| softech_user | varchar | Cashier code |
| sales_channel | varchar | Denormalized from customer |
| sales_person_type | varchar | Denormalized from customer |
| branch_id | FK → branches_branch | |
| store_code | varchar | Sub-store code |
| cust_branch_code | varchar | |
| trans_time | time | Actual transaction clock |

### customers_purchasehistoryline
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| purchase_id | FK → customers_purchasehistory | |
| item_id | FK → catalog_item | |
| quantity | decimal | |
| unit_price | decimal | |
| line_total | decimal | |
| cost_at_sale | decimal | SOFTECH authoritative cost |

---

## RESERVATIONS

### reservations_reservation
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| customer_id | FK → customers_customer | nullable |
| item_id | FK → catalog_item | nullable |
| manual_item_name | varchar | For unsynced items |
| quantity_requested | int | |
| contact_phone | varchar | |
| contact_name | varchar | |
| notes | text | |
| channel | varchar | pickup/home_delivery/insurance/inquiry |
| order_source | varchar | |
| fulfillment_method | varchar | |
| status | varchar | pending/available/contacted/confirmed/fulfilled/cancelled/expired |
| priority | varchar | normal/urgent/chronic |
| branch_id | FK → branches_branch | |
| assigned_to_id | FK → users_staffprofile | |
| expected_arrival_date | date | |
| follow_up_date | date | |
| softech_reserve_id | varchar | |
| image | file | |
| erp_reference | varchar | Post-fulfillment ERP match |
| erp_match_status | varchar | pending/matched/partial/not_found/timeout |
| erp_matched_at | timestamp | |
| erp_matched_items | jsonb | |
| erp_receipt_lines | jsonb | |
| erp_customer_info | jsonb | |
| created_at | timestamp | |
| updated_at | timestamp | |

### reservations_reservationdownpayment
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| reservation_id | FK → reservations_reservation | |
| amount | decimal | |
| payment_method | varchar | |
| reference_number | varchar | |
| received_by_id | FK → users_staffprofile | |
| received_at | timestamp | |

### reservations_reservationstatuslog
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| reservation_id | FK → reservations_reservation | |
| old_status | varchar | |
| new_status | varchar | |
| changed_by_id | FK → users_staffprofile | |
| note | text | |
| changed_at | timestamp | |

### reservations_reservationactivity  (Odoo-style chatter)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| reservation_id | FK → reservations_reservation | |
| activity_type | varchar | note/call_made/customer_replied/stock_checked/status_changed/transfer_requested/transfer_replied/item_dispensed/reminder_sent/image_attached/assigned/mention |
| message | text | |
| created_by_id | FK → users_staffprofile | |
| attachment | file | |
| mentioned_users | M2M → users_staffprofile | |
| transfer_request_id_ref | int | Loose ref (not FK) |
| voice_note | file | |
| is_deleted | bool | Soft delete |
| deleted_at | timestamp | |
| deleted_by_id | FK → users_staffprofile | |

---

## DEMAND

### demand_demandrecord
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| demand_number | varchar unique | Auto DEM-XXXXXX |
| phone | varchar | Mandatory customer contact |
| customer_name | varchar | |
| customer_id | FK → customers_customer | nullable |
| phcode | varchar | ERP PIC |
| erp_branch_code | varchar | |
| status | varchar | new/assigned/follow_up/stock_eta/transfer_suggested/purchasing_flagged/fulfilled/lost/cancelled |
| priority | varchar | low/normal/high/urgent/chronic |
| source | varchar | walk_in/phone/whatsapp/delivery/online/call_center/other |
| branch_id | FK → branches_branch | |
| assigned_to_id | FK → users_staffprofile | |
| assigned_at | timestamp | |
| follow_up_date | date | |
| expected_stock_date | date | |
| contacted_at | timestamp | SLA tracking |
| lost_reason | varchar | no_stock/delayed/discontinued/no_response/price/competitor/other |
| erp_invoice_ref | varchar | |
| fulfilled_at | timestamp | |
| sla_deadline | timestamp | Computed property |
| sla_breached | bool | Computed property |
| created_by_id | FK → users_staffprofile | |
| created_at | timestamp | |
| updated_at | timestamp | |

### demand_demanditem
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| demand_id | FK → demand_demandrecord | |
| item_id | FK → catalog_item | nullable |
| item_name_free | varchar | Unmatched item name |
| quantity | int | |
| demand_type | varchar | out_of_stock/low_stock/new_item/price_check |
| item_status | varchar | pending/sourcing/fulfilled/lost/cancelled |
| is_long_shortage | bool | |
| is_discontinued | bool | |
| shortage_note | text | |

### demand_followuptask
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| demand_id | FK → demand_demandrecord | |
| task_type | varchar | call/whatsapp/sms/visit/stock_check/other |
| due_date | datetime | |
| status | varchar | pending/done/missed/cancelled |
| assigned_to_id | FK → users_staffprofile | |
| note | text | |
| completed_at | timestamp | |
| completed_by_id | FK → users_staffprofile | |

### demand_demandlog  (chatter)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| demand_id | FK → demand_demandrecord | |
| log_type | varchar | note/call/whatsapp/sms/system/status |
| message | text | |
| call_outcome | varchar | answered/no_answer/busy/wrong_number/callback |
| call_duration_seconds | int | |
| created_by_id | FK → users_staffprofile | |
| created_at | timestamp | |

### demand_itemdemandstat  (daily aggregation per item/branch)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| item_id | FK → catalog_item | |
| branch_id | FK → branches_branch | nullable (null = network total) |
| demand_count_30d | int | |
| lost_count_30d | int | |
| fulfilled_count_30d | int | |
| lost_qty_30d | decimal | |
| is_long_shortage | bool | |
| is_discontinued | bool | |
| shortage_start | date | |
| suggest_order | bool | |
| suggest_transfer | bool | |

---

## TRANSFERS

### transfers_transferrequest
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| request_number | varchar unique | Auto TR-XXXXXX (DB sequence) |
| requesting_branch_id | FK → branches_branch | |
| supplying_branch_id | FK → branches_branch | nullable |
| status | varchar | draft/pending/approved/rejected/needs_revision/sent_to_erp/completed/cancelled |
| created_by_id | FK → users_staffprofile | |
| reviewed_by_id | FK → users_staffprofile | |
| sent_to_erp_by_id | FK → users_staffprofile | |
| dispatched_by_id | FK → users_staffprofile | |
| notes | text | |
| rejection_reason | text | |
| revision_notes | text | |
| delivery_person_name | varchar | |
| dispatched_at | timestamp | |
| erp_reference | varchar | |
| sent_to_erp_at | timestamp | |
| erp_match_status | varchar | pending/matched/partial/not_found/timeout |
| erp_matched_at | timestamp | |
| erp_matched_items | jsonb | |
| source_recommendation_id | FK → purchasing_transferrecommendation | nullable |
| submitted_at | timestamp | |
| reviewed_at | timestamp | |
| completed_at | timestamp | |
| created_at | timestamp | |
| updated_at | timestamp | |

### transfers_transferrequestitem
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| request_id | FK → transfers_transferrequest | |
| item_id | FK → catalog_item | PROTECT |
| quantity | int | |
| notes | text | |

### transfers_transferrequestmessage  (chatter)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| request_id | FK → transfers_transferrequest | |
| message_type | varchar | message/system/note |
| message | text | |
| created_by_id | FK → users_staffprofile | |
| attachment | file | |
| voice_note | file | |
| is_deleted | bool | |
| deleted_at | timestamp | |
| deleted_by_id | FK → users_staffprofile | |

---

## USERS

### users_staffprofile
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| user_id | FK → auth_user UNIQUE | Django auth user |
| branch_id | FK → branches_branch | Home branch |
| erp_user_id | FK → users_erpuser UNIQUE | |
| softech_username | varchar | |
| softech_user_id | varchar | |
| role | varchar | admin/call_center/pharmacist/salesperson/purchasing/delivery/viewer/supervisor/quality_manager |
| access_all_branches | bool | |
| allowed_branches | M2M → branches_branch | Whitelist |
| restricted_branches | M2M → branches_branch | Blacklist |
| can_see_all_customers | bool | |
| can_see_customer_phone | bool | |
| enable_notifications | bool | |
| enable_sound | bool | |
| enable_browser_push | bool | |
| phone | varchar | |
| is_active | bool | |
| created_at | timestamp | |
| updated_at | timestamp | |

### users_erpuser  (SOFTECH user cache)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| username | varchar unique | SOFTECH username |
| user_id | varchar | SOFTECH user ID |
| full_name | varchar | |
| branch_code | varchar | |
| user_group | varchar | |
| is_active | bool | |
| synced_at | timestamp | |

---

## NOTIFICATIONS

### notifications_notification
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| recipient_id | FK → users_staffprofile | |
| notification_type | varchar | 19 types |
| priority | varchar | Always 'high' |
| title | varchar | |
| body | text | |
| is_read | bool | |
| dedup_key | varchar | 5-min dedup window |
| reservation_id | FK → reservations_reservation | nullable |
| transfer_request_id_ref | int | Loose ref |
| demand_id_ref | int | Loose ref |
| chatter_message_id_ref | int | Loose ref |
| created_at | timestamp | |

### notifications_notificationlog
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| notification_id | FK → notifications_notification | |
| recipient_id | FK → users_staffprofile | UNIQUE with notification |
| delivered_at | timestamp | |
| read_at | timestamp | |

### notifications_chattermessage
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| model_name | varchar | Generic FK model name |
| record_id | int | Generic FK record ID |
| author_id | FK → users_staffprofile | |
| message | text | |
| created_at | timestamp | |
| attachment | file | |
| file_type | varchar | image/voice/doc |
| is_internal | bool | |

---

## VOUCHERS

### vouchers_voucher
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| code | varchar unique | VCH-XXXXXXXX |
| title | varchar | |
| description | text | |
| voucher_category | varchar | public/private/first_time/assigned |
| voucher_type | varchar | discount_pct/discount_fixed/credit/free_item |
| discount_pct | decimal | |
| discount_amount | decimal | |
| credit_amount | decimal | |
| free_item_id | FK → catalog_item | nullable |
| max_discount_cap | decimal | nullable |
| min_order_value | decimal | nullable |
| customer_id | FK → customers_customer | nullable (private) |
| branch_id | FK → branches_branch | nullable |
| applicable_items | M2M → catalog_item | |
| applicable_branches | M2M → branches_branch | |
| max_uses | int | Total usage cap |
| times_used | int | Running count |
| usage_limit_per_customer | int | |
| usage_limit_per_day | int | nullable |
| validity_days_after_assignment | int | nullable |
| valid_from | date | |
| valid_until | date | nullable |
| status | varchar | active/used/expired/cancelled |
| created_by_id | FK → users_staffprofile | |
| created_at | timestamp | |
| updated_at | timestamp | |

### vouchers_voucherassignment
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| voucher_id | FK → vouchers_voucher | |
| customer_phone | varchar | UNIQUE with voucher |
| customer_id | FK → customers_customer | nullable |
| assigned_by_id | FK → users_staffprofile | |
| assigned_at | timestamp | |
| expires_at | timestamp | nullable |
| usage_count | int | |
| is_active | bool | |

### vouchers_voucherotp
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| voucher_id | FK → vouchers_voucher | |
| phone | varchar | |
| code_hash | varchar(64) | HMAC-SHA256 — never plain |
| otp_salt | varchar(32) | Random salt |
| is_used | bool | |
| expires_at | timestamp | 3-min TTL |
| created_at | timestamp | |
| used_at | timestamp | nullable |
| sent_via | varchar | whatsapp |
| retry_count | int | Max 3 |
| resend_count | int | |

### vouchers_voucherredemptiondocument
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| voucher_id | FK → vouchers_voucher | |
| otp_id | FK → vouchers_voucherotp | OneToOne nullable |
| customer_phone | varchar | |
| employee_id | FK → users_staffprofile | |
| branch_id | FK → branches_branch | |
| generated_at | timestamp | |
| expires_at | timestamp | 15-min window |
| status | varchar | active/used/expired/cancelled |
| reference_code | varchar unique | REF-XXXXXXXX |
| discount_applied | decimal | |
| order_amount | decimal | |
| used_at | timestamp | |

### vouchers_voucherredemption  (immutable audit)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| voucher_id | FK → vouchers_voucher | |
| document_id | FK → vouchers_voucherredemptiondocument | OneToOne |
| otp_id | FK → vouchers_voucherotp | OneToOne |
| customer_phone | varchar | |
| redeemed_by_id | FK → users_staffprofile | |
| branch_id | FK → branches_branch | |
| redeemed_at | timestamp | |
| discount_applied | decimal | |
| order_amount | decimal | |

---

## INCENTIVES

### incentives_incentiveprogram
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| name | varchar | |
| description | text | |
| start_date | date | |
| end_date | date | |
| calculation_period | varchar | weekly/monthly/custom |
| is_active | bool | |
| created_by_id | FK → users_staffprofile | |

### incentives_incentiverule
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| program_id | FK → incentives_incentiveprogram | |
| rule_name | varchar | |
| item_code | varchar | Single-item targeting |
| item_name | varchar | |
| category_code | varchar | Informational only |
| incentive_type | varchar | percent/fixed/fixed_per_unit/fixed_per_transaction/tiered |
| incentive_value | decimal | |
| slab_config | jsonb | Tiered slab definition |
| min_qty | decimal | Per-transaction minimum |
| min_total_qty_in_period | decimal | Period minimum |
| person_code_filter | varchar | ERP user code filter |
| branch_filter | varchar | Branch code filter |
| time_window_start | time | nullable |
| time_window_end | time | nullable |
| expiry_within_days | int | nullable |
| priority | int | Lower = higher priority |
| is_active | bool | |

### incentives_incentiveruleitem
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| rule_id | FK → incentives_incentiverule | |
| item_code | varchar | UNIQUE with rule |
| item_name | varchar | |
| incentive_override | decimal | nullable — overrides rule value |

### incentives_incentivetransaction  (immutable audit)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| program_id | FK → incentives_incentiveprogram | |
| rule_id | FK → incentives_incentiverule | nullable |
| user_id | FK → users_staffprofile | |
| item_code | varchar | |
| item_name | varchar | |
| doc_no | varchar | ERP invoice number |
| doc_type | varchar | sale/return |
| ref_doc_no | varchar | Original invoice (returns) |
| quantity | decimal | |
| unit_price | decimal | |
| incentive_amount | decimal | Negative for returns |
| is_reversed | bool | |
| period_start | date | |
| period_end | date | |
| erp_date | date | |
| branch_code | varchar | |
| is_cross_period_return | bool | |

### incentives_incentivesettlement
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| program_id | FK | UNIQUE with user+period |
| user_id | FK → users_staffprofile | |
| period_start | date | |
| period_end | date | |
| total_incentive | decimal | From transactions |
| total_adjustments | decimal | From adjustments |
| final_payout | decimal | total_incentive + total_adjustments |
| transaction_count | int | |
| is_finalized | bool | Locked when true |
| finalized_at | timestamp | |
| finalized_by_id | FK → users_staffprofile | |

### incentives_adjustmententry
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| program_id | FK | |
| user_id | FK → users_staffprofile | |
| period_start | date | |
| period_end | date | |
| amount | decimal | Positive=bonus, Negative=deduction |
| reason | text | |
| created_by_id | FK → users_staffprofile | |

### incentives_incentivecalculationlog
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| program_id | FK | |
| triggered_by_id | FK → users_staffprofile | |
| period_start | date | |
| period_end | date | |
| mode | varchar | calculate/simulate |
| status | varchar | done/failed |
| transactions_created | int | |
| skipped_person_codes | jsonb | |
| user_summaries | jsonb | |
| error_detail | text | |
| started_at | timestamp | |
| finished_at | timestamp | |
| duration_seconds | float | |

---

## STOCKCOUNT

### stockcount_stockcountsession
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| name | varchar | Session label |
| mode | varchar | transaction/full/filtered |
| status | varchar | draft/snapshot_taken/exported/uploaded/variance_ready/closed |
| notes | text | |
| branch_code | varchar | Target branch |
| date_from | date | nullable |
| date_to | date | nullable |
| doccodes | jsonb | ERP doccode filter |
| user_code_filter | varchar | |
| category_filter | varchar | |
| item_codes_filter | jsonb | |
| item_count | int | Set on upload |
| surplus_count | int | |
| deficit_count | int | |
| ok_count | int | |
| created_by_id | FK → users_staffprofile | |
| snapshot_by_id | FK → users_staffprofile | |
| uploaded_by_id | FK → users_staffprofile | |
| created_at / snapshot_at / exported_at / uploaded_at / variance_at / updated_at | timestamps | |

### stockcount_stockcountsnapshot  (IMMUTABLE after snapshot)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| session_id | FK → stockcount_stockcountsession | |
| item_code | varchar | UNIQUE with session |
| item_name | varchar | |
| item_medicine | varchar | |
| category_name | varchar | |
| branch_code | varchar | |
| expected_qty | decimal | Frozen at snapshot time |
| snapshot_time | timestamp | |
| counted_qty | decimal | nullable — set on upload |
| difference | decimal | nullable — counted − expected |
| variance_type | varchar | ok/surplus/deficit (blank=not counted) |

---

## SHORTAGE

### shortage_shortagelist
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| branch_id | FK → branches_branch | |
| created_by_id | FK → users_staffprofile | |
| status | varchar | open/submitted/resolved |
| title | varchar | |
| notes | text | |
| source | varchar | manual/ocr/imported |
| source_image | file | OCR upload |
| created_at / updated_at | timestamps | |

### shortage_shortageitem
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| shortage_list_id | FK → shortage_shortagelist | |
| item_id | FK → catalog_item | nullable |
| raw_name | varchar | As entered/scanned |
| quantity_needed | decimal | |
| unit | varchar | |
| notes | varchar | |
| source | varchar | manual/voice/ocr/bulk |
| match_score | float | rapidfuzz score |
| is_confirmed | bool | |
| is_unmatched | bool | |
| confirmed_by_id | FK → users_staffprofile | nullable |
| confirmed_at | timestamp | nullable |

---

## CONFIG

### config_systemsetting
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| key | varchar unique | Setting key |
| label | varchar | Display name |
| description | text | |
| value | text | Stored as string |
| value_type | varchar | string/integer/decimal/boolean/json |
| category | varchar | general/reservations/transfers/notifications/sync/vouchers |
| is_public | bool | API-readable without auth |
| updated_at | timestamp | |

### config_dropdownoption
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Auto |
| dropdown_key | varchar | Namespaced key (indexed) |
| label | varchar | Arabic label |
| label_en | varchar | English label |
| value | varchar | UNIQUE with dropdown_key |
| icon | varchar | |
| color | varchar | Tailwind class |
| order | int | Display order |
| is_active | bool | |
| is_system | bool | Cannot be deleted |

### config_pharmacyprofile  (singleton pk=1)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | Always 1 |
| name_ar | varchar | صيدليات الرزيقي |
| name_en | varchar | ElRezeiky Pharmacies |
| tagline_ar | varchar | |
| website | varchar | |
| whatsapp_number | varchar | Without + prefix |
| call_center_numbers | text | Newline-separated |
| extra_footer_ar | text | |
| updated_at | timestamp | |

---

## PURCHASING (Demand Engine)

### purchasing_engineconfig  (singleton pk=1)
| Column | Type | Notes |
|--------|------|-------|
| weight_30d | decimal | 0.5 |
| weight_90d | decimal | 0.3 |
| weight_365d | decimal | 0.2 |
| ss_multiplier | decimal | 1.0 |
| ss_high_threshold | decimal | 2.0 |
| abc_a_threshold | decimal | 70% |
| abc_b_threshold | decimal | 90% |

### purchasing_salestransactionline  (rolling 365-day SOFTECH cache)
| Column | Type | Notes |
|--------|------|-------|
| item_id | FK → catalog_item | |
| branch_id | FK → branches_branch | |
| transaction_date | date | |
| quantity | decimal | |
| ... | | |

### purchasing_itemdemandmetrics  (per-item per-branch)
| Column | Type | Notes |
|--------|------|-------|
| item_id | FK | |
| branch_id | FK | |
| avg_daily_demand | decimal | |
| safety_stock | decimal | |
| reorder_point | decimal | |
| abc_class | varchar | A/B/C |

### purchasing_transferrecommendation
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK | |
| source_branch_id | FK | Has surplus |
| destination_branch_id | FK | Has demand |
| recommended_qty | decimal | |
| roi_score | decimal | |
| is_actioned | bool | True when TR created |

---

## INVOICES

### invoices_vendorprofile
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name | varchar | |
| aliases | jsonb | Name variations |
| typical_discount_pct | decimal | |
| notes | text | |

### invoices_vendoritemmapping  (learning table)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| vendor_id | FK | |
| raw_name_normalized | varchar | Normalized raw text |
| item_id | FK → catalog_item | |
| use_count | int | Incremented on confirmation |

### invoices_supplierinvoice
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| status | varchar | |
| supplier_name | varchar | |
| invoice_number | varchar | |
| invoice_date | date | |
| ... (OCR fields) | | |

### invoices_invoiceline
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| invoice_id | FK | |
| raw_text | varchar | As OCR extracted |
| item_id | FK → catalog_item | nullable — fuzzy matched |
| ... | | |

---

## POS_ORDERS  (Indirect-POS writeback — PG is system-of-record for our metadata; SOFTECH is authoritative for the order once pushed)

### pos_orders_softechsalesorder  (pending indirect-POS order header)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| status | varchar(12) | `draft`→`ready`→`queued`→`pushing`→`pushed`→`settled` (+`push_failed`,`cancelled`); `is_locked` once pushing/pushed/settled/cancelled |
| channel | varchar(12) | cash/delivery/contract/insurance/employee/vip/permanent → SOFTECH `ptclassifcode` |
| doc_kind | varchar(8) | `sale` (doccode 115) / `return` (doccode 30) |
| client_token | uuid | **UNIQUE** idempotency marker (stashed in SOFTECH `vf2`/comments); NULLs distinct so legacy rows unaffected |
| branch_id | FK → branches_branch | PROTECT |
| softech_branchcode / store_code | varchar | SOFTECH branch + store codes |
| customer_id | FK → customers_customer | SET_NULL |
| softech_pic / customer_name / cust_branch_code | varchar | Customer identity (personcode) |
| softech_docnumber | decimal | Pending serial (writer-filled) |
| softech_final_docnumber | decimal | Final invoice # (reconciler-filled) |
| return_of_invoice | decimal | For returns |
| doc_value / _gross / _cogs / _tax / _pay | decimal | Money mirror (pricing.py) |
| patient_payment / change_discount | decimal | Patient payment; خصم فكة (PG-only) |
| referral_doctor_name / _code | varchar | Referral doctor (our extra) |
| prescription_image | image | Roshetta image (our extra) |
| source_call_id / source_call_item_id | FK → callcenter | Originating call (our extra) |
| seller_usercode / cashier_usercode | varchar | SOFTECH user codes |
| source_header_raw / source_companies_raw / source_cc_raw | jsonb | Verbatim native rows for byte-faithful RETURNABLE clones (contract/insurance) |
| alt_price / sell_at_cost / print_receipt / items_reservation | bool | SOFTECH screen flags |
| erp_executed_at / erp_payload / erp_readback / erp_error | dt/jsonb/text | **Immutable execution audit** |
| created_by_id | FK → users_staffprofile | |
| created_at / updated_at | dt | |

### pos_orders_softechsalesorderline  (→ SOFTECH stktrans5)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| order_id | FK → softechsalesorder | CASCADE |
| item_id | FK → catalog_item | PROTECT |
| softech_itemcode / item_name | varchar | |
| qty / bonus_qty | decimal | Quantity; العبوة → `bonusqty` |
| item_sale_price / _tax / sale_tax_pct / cust_discp | decimal | Inputs (per-branch price, tax %, discount %) |
| trans_price / trans_price_total / item_sale_tax / new_cost_price | decimal | Computed (pricing.py); `new_cost_price` from stkbal at push |
| item_expiry / batchno / barcode / pkg_price | varies | Display/audit |
| return_of_invoice | decimal | `r_docnumber` for return lines |
| source_raw | jsonb | Verbatim native stktrans5 row (returnable clone); datetimes as `{'__dt__': '...'}` |

### pos_orders_softechsalesorderpayment  (→ SOFTECH branchesales5; split tenders = multiple rows)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| order_id | FK → softechsalesorder | CASCADE |
| pay_type | varchar(8) | cash(30)/credit(10)/card(40) → SOFTECH `paymenttype` |
| amount | decimal | |
| softech_paymentsno | decimal | SOFTECH payment serial |
| card_brand / cheque_date / ref_invoice | varies | Card type, cheque date, ref doc |
| currency / exchange_rate | varies | `bcurrency` / `bcrate` |
| cheque_card_no / internal_payserial | varchar | Cheque/card no → comment; `localpayment_sno` |

---

## CALLCENTER

### callcenter_calllog  (one log per inbound/outbound/WhatsApp call)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| phone_number | varchar(50) | Indexed; auto-matched to customer on save |
| customer_id | FK → customers_customer | Nullable (auto-match) |
| caller_name | varchar | |
| direction | varchar | inbound / outbound / whatsapp |
| status | varchar | answered / no_answer / busy / voicemail / callback |
| purpose | varchar | reservation/delivery/refill/complaint/new_order/address/followup/demand/general |
| duration_seconds | int | |
| handled_by_id | FK → users_staffprofile | |
| branch_id | FK → branches_branch | |
| notes / summary | text/varchar | |
| reservation_id | FK → reservations_reservation | Linked outcome |
| followup_task_id | FK → demand_followuptask | |
| payment_method | varchar | |
| case_id | FK → callcenter_customercase | |
| recording_url | url | |
| voice_transcript | text | |
| prescription_image | image | |
| ai_summary / ai_intent / ai_sentiment | text/varchar | AI enrichment |
| ai_urgency | smallint | |
| ai_next_action | varchar | |
| ai_processed_at | datetime | |
| quality_score | smallint | |
| called_at | datetime | auto_now_add, indexed |
| updated_at | datetime | |
| callback_due | datetime | |

### callcenter_addressupdate  (address collected on a call → applied to Customer)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| call_log_id | FK → callcenter_calllog | |
| customer_id | FK → customers_customer | |
| label / label_custom | varchar | Home/work/custom |
| address_text | text | |
| area / floor / apartment / landmark | varchar | |
| google_maps_link | url | |
| delivery_phone | varchar | |
| delivery_notes | text | |
| set_as_default | bool | default True |
| status | varchar | pending / applied |
| applied_location_ref | varchar | |
| applied_by_id / applied_at | FK / datetime | |
| collected_by_id / collected_at | FK / datetime | |
| notes | text | |

### callcenter_calllogattachment
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| call_log_id | FK → callcenter_calllog | |
| file | file | |
| file_type | varchar | prescription / voice / document |
| description | varchar | |
| file_size | int | |
| uploaded_by_id / uploaded_at | FK / datetime | |

### callcenter_customercase  (groups interactions into a case; state machine)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| case_number | varchar | |
| customer_id | FK → customers_customer | |
| category / priority / status | varchar | open→working→escalated→resolved→closed |
| title / description / root_cause / resolution | varchar/text | |
| branch_id | FK → branches_branch | |
| demand_id / reservation_id / delivery_id | FK | Linked records |
| opened_by_id / assigned_to_id | FK → users_staffprofile | |
| sla_due / resolved_at / closed_at | datetime | |
| csat_score / csat_note | smallint/text | |
| escalated_to_id / escalated_at / escalation_reason | FK/datetime/text | |
| created_at / updated_at | datetime | |

### callcenter_caseevent  (case chatter/timeline)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| case_id | FK → callcenter_customercase | |
| event_type | varchar | note / status / … |
| message | text | |
| created_by_id / created_at | FK / datetime | |
| attachment / attachment_type | file / varchar | |

### callcenter_callqualityscore  (QA scoring — supervisor or AI; OneToOne to call)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| call_log_id | OneToOne → callcenter_calllog | |
| scored_by_id | FK → users_staffprofile | |
| source | varchar | supervisor / ai |
| greeting / resolution / communication / accuracy | smallint | rubric sub-scores |
| total_score | smallint | |
| notes / scored_at | text / datetime | |

### callcenter_callitem  (items mentioned on a call → convertible to reservation/transfer)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| call_log_id | FK → callcenter_calllog | |
| item_id | FK → catalog_item | Nullable |
| manual_item_name / manual_item_code | varchar | Free-text fallback |
| quantity | decimal | |
| notes | text | |
| converted_to | varchar | reservation / transfer |
| converted_reservation_id / converted_transfer_id | FK | |
| created_at | datetime | |

---

## WHATSAPP  (Cloud API)

### whatsapp_watemplate
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name | varchar | |
| language | varchar | default 'ar' |
| category / status | varchar | Meta template category + approval status |
| body_text | text | |
| header_type / header_text | varchar | |
| footer_text | varchar | |
| variable_map | jsonb | Placeholder → source mapping |
| meta_template_id | varchar | |
| created_at / updated_at | datetime | |

### whatsapp_waconversation
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| wa_id | varchar | **UNIQUE** WhatsApp id (blocks multi-number per contact — see memory) |
| customer_id | FK → customers_customer | |
| status | varchar | |
| window_expires_at | datetime | 24h session window |
| assigned_to_id | FK → users_staffprofile | |
| account_id | FK → omni_channelaccount | Sending number |
| omni_conversation_id | FK → omni_conversation | Envelope link |
| last_message_preview / last_message_at | varchar/datetime | |
| unread_count | smallint | |
| created_at / updated_at | datetime | |

### whatsapp_wamessage
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| conversation_id | FK → whatsapp_waconversation | |
| direction | varchar | inbound / outbound |
| message_type | varchar | text/media/template/location |
| status | varchar | sent/delivered/read/failed |
| wamid | varchar | Meta message id |
| body | text | |
| media_id | FK → whatsapp_wamediafile | |
| template_id | FK → whatsapp_watemplate | |
| template_variables | jsonb | |
| location_lat / location_lng / location_name | decimal/varchar | |
| error_code / error_message / retry_count | varchar/text/smallint | |
| sent_by_id | FK → users_staffprofile | |
| created_at / sent_at / delivered_at / read_at | datetime | |

### whatsapp_wamediafile
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| meta_media_id | varchar | |
| file_type / mime_type / file_name / file_size | varchar/int | |
| local_file | file | |
| uploaded_by_id / created_at | FK / datetime | |

### whatsapp_wawebhooklog
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| received_at | datetime | indexed |
| object_type / entry_id / phone_number_id | varchar | |
| payload | jsonb | Raw webhook |
| processed / processing_error | bool / text | |
| wa_message_id | FK → whatsapp_wamessage | |

### whatsapp_wamessagequeue  (outbound send queue with retry)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| conversation_id | FK → whatsapp_waconversation | |
| priority | smallint | |
| status | varchar | |
| message_type / body / template_name / template_vars | varchar/text/jsonb | |
| media_id | FK → whatsapp_wamediafile | |
| attempts / max_attempts (3) | smallint | |
| next_attempt_at | datetime | indexed |
| last_error | text | |
| wa_message_id | OneToOne → whatsapp_wamessage | |
| created_at / updated_at | datetime | |

---

## PBX  (Issabel AMI)

### pbx_agentextension
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| extension | varchar | |
| extension_type | varchar | |
| staff_id | OneToOne → users_staffprofile | |
| sip_peer / queue_name | varchar | |
| last_status / last_ip | varchar | |
| gateway_type / call_prefix / call_suffix | varchar | Dial string shaping |
| is_active | bool | |
| created_at / updated_at | datetime | |

### pbx_pbxqueue
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name / description | varchar | |
| branch_id | FK → branches_branch | |
| is_active | bool | |

### pbx_pbxevent  (raw AMI events)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| event_type | varchar | |
| payload | jsonb | |
| unique_id / linked_id | varchar | Asterisk channel ids |
| channel / caller_id_num / caller_id_name / extension / queue_name | varchar | |
| received_at | datetime | indexed |
| session_id | FK → pbx_callsession | |

### pbx_callsession  (correlated call — the wallboard unit)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| unique_id / linked_id | varchar | |
| direction / state | varchar | |
| caller_number / caller_name | varchar | |
| destination_ext | varchar | |
| queue_id | FK → pbx_pbxqueue | |
| agent_id | FK → pbx_agentextension | |
| started_at / answered_at / ended_at | datetime | |
| wait_seconds / talk_seconds | int | |
| recording_path / recording_url | varchar/url | |
| customer_id | FK → customers_customer | |
| call_log_id | OneToOne → callcenter_calllog | |
| cdr_disposition / cdr_userfield | varchar | |
| created_at / updated_at | datetime | |

---

## OMNI  (unified inbox / CEP envelope)

### omni_channelaccount
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| channel | varchar | whatsapp/messenger/ig/telegram/call/… |
| name | varchar | |
| phone_or_handle | varchar | |
| branch_id | FK → branches_branch | |
| department | varchar | |
| provider | varchar | Provider abstraction |
| credentials | jsonb | |
| provider_ref | varchar | |
| is_default | bool | |
| status | varchar | |
| last_heartbeat_at | datetime | |
| health / working_hours | jsonb | |
| supervisor_id | FK → users_staffprofile | |
| is_active / created_at / updated_at | bool/datetime | |

### omni_conversation  (customer-grouped timeline root)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| customer_id | FK → customers_customer | |
| contact_phone | varchar | |
| status / priority | varchar | |
| branch_id | FK → branches_branch | |
| assigned_to_id | FK → users_staffprofile | |
| subject | varchar | |
| created_from_channel | varchar | |
| first_inbound_at / last_activity_at | datetime | |
| last_event_preview | varchar | |
| created_at / updated_at | datetime | |

### omni_timelineevent  (generic — GenericFK to underlying WA/call/social record)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| conversation_id | FK → omni_conversation | |
| event_type | varchar | |
| channel | varchar | |
| account_id | FK → omni_channelaccount | |
| content_type_id / object_id | GenericFK | Underlying record |
| summary | varchar | |
| actor_id | FK → users_staffprofile | |
| occurred_at | datetime | indexed |
| payload | jsonb | |
| created_at | datetime | |

### omni_automationrule
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name | varchar | |
| trigger | varchar | |
| conditions / actions | jsonb | No-code rule spec |
| is_active | bool | indexed |
| stop_processing | bool | |
| order | smallint | Evaluation order |
| run_count / last_run_at | int/datetime | |
| created_by_id / created_at / updated_at | FK/datetime | |

### omni_automationrun  (audit of a rule firing)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| rule_id | FK → omni_automationrule | |
| event_id | FK → omni_timelineevent | |
| conversation_id | FK → omni_conversation | |
| matched | bool | |
| actions_run | jsonb | |
| error | text | |
| created_at | datetime | indexed |

---

## SOCIAL  (Messenger / IG / Telegram / TikTok inbound)

### social_socialthread
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| account_id | FK → omni_channelaccount | |
| external_user_id | varchar | Platform user id |
| display_name | varchar | |
| omni_conversation_id | FK → omni_conversation | |
| last_message_preview / last_message_at / last_inbound_at | varchar/datetime | |
| unread_count | smallint | |
| created_at / updated_at | datetime | |

### social_socialmessage
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| thread_id | FK → social_socialthread | |
| direction / message_type / status | varchar | |
| body | text | |
| external_id | varchar | |
| attachment_url | url | |
| sent_by_id | FK → users_staffprofile | |
| error_message | text | |
| created_at | datetime | indexed |

### social_socialwebhooklog
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| source | varchar | meta / telegram / tiktok |
| payload | jsonb | |
| processed / processing_error | bool / text | |
| received_at | datetime | indexed |

---

## CAMPAIGNS

### campaigns_whatsappcampaign
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name / description | varchar/text | |
| status | varchar | draft→approval→queued→completed |
| message_template | text | |
| target_filter | jsonb | Audience segment spec |
| featured_item_id | FK → catalog_item | |
| scheduled_at | datetime | |
| estimated_reach / messages_queued / _sent / _delivered / _failed | int | Counters |
| created_by_id / approved_by_id / rejected_by_id | FK → users_staffprofile | |
| rejection_reason | text | |
| created_at / updated_at / approved_at / queued_at / completed_at | datetime | |

### campaigns_campaignmessage  (per-recipient)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| campaign_id | FK → campaigns_whatsappcampaign | |
| customer_id | FK → customers_customer | |
| phone_number / customer_name | varchar | |
| message_text | text | |
| whatsapp_url | text | Click-to-chat link |
| status | varchar | |
| sent_at / delivered_at / failed_at | datetime | |
| error_message | varchar | |
| created_at | datetime | |

---

## DELIVERY

### delivery_deliverydriver
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| full_name / mobile / national_id | varchar | mobile indexed |
| staff_profile_id | OneToOne → users_staffprofile | |
| branch_id | FK → branches_branch | |
| vehicle_type / vehicle_plate | varchar | |
| status | varchar | available / busy / offline |
| max_daily_orders | smallint | |
| notes / created_at / updated_at | text/datetime | |

### delivery_customerlocation  (saved addresses; GPS)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| customer_id | FK → customers_customer | |
| label / label_custom | varchar | Home/work/custom |
| is_default | bool | indexed |
| address_line / building / floor / apartment / landmark / area / district / governorate | varchar/text | |
| latitude / longitude | decimal | |
| google_maps_url / location_accuracy | varchar | |
| delivery_phone / notes | varchar/text | |
| updated_by_id / updated_at / created_at | FK/datetime | |

### delivery_deliveryorder  (14-status lifecycle; can mirror SOFTECH CRM order)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| order_number | varchar | |
| softech_crm_order_no / _crm_branch / _doc_ref / _branch_code / _order_usercode / _order_status | int/varchar/smallint | SOFTECH CRM linkage |
| source_type | varchar | crm / manual / … |
| branch_id | FK → branches_branch | |
| customer_id | FK → customers_customer | |
| customer_name / customer_phone / customer_phone_alt | varchar | |
| location_id | FK → delivery_customerlocation | |
| delivery_address / _area / _district / _governorate / _landmark | text/varchar | |
| delivery_lat / delivery_lng / google_maps_url | decimal/varchar | |
| items_count | int | |
| total_value / delivery_fees / collected_amount | decimal | |
| payment_method | varchar | |
| status | varchar | 14-status lifecycle |
| cancel_reason / failure_reason | text/varchar | |
| assigned_driver_id | FK → delivery_deliverydriver | |
| sla_due_at / ordered_at / assigned_at / driver_accepted_at / dispatched_at / delivered_at / failed_at / closed_at | datetime | Timestamps per state |
| pod_recipient_name / pod_note / pod_photo / pod_lat / pod_lng | varchar/image/decimal | Proof of delivery |
| delivery_distance_km / pod_backfilled | decimal/bool | |
| route_id | FK → delivery_deliveryroute | |
| route_sequence | int | |
| notes / created_by_id / created_at / updated_at | text/FK/datetime | |

### delivery_deliveryorderitem
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| order_id | FK → delivery_deliveryorder | |
| item_id | FK → catalog_item | Nullable |
| item_name / item_code | varchar | |
| quantity / unit_price / line_total / delivered_quantity | decimal | |
| notes | text | |

### delivery_deliveryassignment  (assignment history)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| order_id | FK → delivery_deliveryorder | |
| driver_id | FK → delivery_deliverydriver | |
| driver_name / vehicle | varchar | Snapshot |
| is_current | bool | indexed |
| assigned_by_id / assigned_at / notes | FK/datetime/text | |

### delivery_deliverystatuslog
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| order_id | FK → delivery_deliveryorder | |
| from_status / to_status | varchar | |
| source | varchar | staff / driver / system |
| notes / recorded_by_id / recorded_at | text/FK/datetime | |

### delivery_deliveryareafee  (area fee matrix)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| branch_id | FK → branches_branch | |
| governorate / area | varchar | indexed |
| fee_amount | decimal | |
| free_above | decimal | Free delivery threshold |
| is_active / notes / updated_at | bool/text/datetime | |

### delivery_deliverycsat  (post-delivery survey; OneToOne)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| order_id | OneToOne → delivery_deliveryorder | |
| score | smallint | |
| feedback | text | |
| channel | varchar | |
| wa_sent_at / wa_sent / responded_at / created_at | datetime/bool | |

### delivery_cashcollection  (COD reconciliation; OneToOne)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| order_id | OneToOne → delivery_deliveryorder | |
| expected_amount / collected_amount / shortage_amount / overage_amount | decimal | |
| status | varchar | |
| collection_time / collected_by_id | datetime/FK | |
| notes / created_at / updated_at | text/datetime | |

### delivery_deliveryroute  (daily route batch)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| branch_id | FK → branches_branch | CASCADE |
| driver_id | FK → delivery_deliverydriver | SET_NULL |
| route_date | date | indexed |
| status | varchar | planned / … |
| notes / created_by_id / created_at / dispatched_at | text/FK/datetime | |

---

## PAYMENTS  (external payments — Instapay / wallet / transfer — + bank reconciliation)

### payments_externalpayment
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| softech_invoice_code / softech_doc_number | varchar | SOFTECH invoice linkage |
| branch_id | FK → branches_branch | |
| customer_id | FK → customers_customer | |
| customer_name / customer_phone | varchar | |
| method | varchar | instapay / wallet / transfer / card |
| amount / invoice_total / remaining_amount | decimal | |
| is_partial | bool | |
| reference_number | varchar | |
| screenshot | image | Proof |
| payment_date | date | |
| status | varchar | pending / confirmed / reconciled / disputed |
| notes | text | |
| created_by_id / confirmed_by_id / confirmed_at | FK/datetime | |
| created_at / updated_at | datetime | |

### payments_paymentreconciliationlog
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| payment_id | FK → payments_externalpayment | |
| action | varchar | |
| notes | text | |
| variance | decimal | |
| performed_by_id / performed_at | FK/datetime | |

### payments_bankstatementimport
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| branch_id | FK → branches_branch | |
| bank_name / account_number | varchar | |
| payment_method | varchar | |
| statement_from / statement_to | date | |
| raw_file | file | |
| status | varchar | |
| total_lines / matched_lines / unmatched_lines | int | |
| error_message | text | |
| imported_by_id / imported_at / completed_at | FK/datetime | |

### payments_bankstatementline
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| statement_import_id | FK → payments_bankstatementimport | |
| transaction_date / value_date | date | txn date indexed |
| reference / description | varchar | reference indexed |
| debit / credit / balance | decimal | |
| matched_payment_id | FK → payments_externalpayment | |
| match_confidence / match_method | decimal/varchar | |
| matched_by_id / matched_at | FK/datetime | |

### payments_paymentexception  (anomaly / abuse detection)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| payment_id | FK → payments_externalpayment | |
| statement_line_id | FK → payments_bankstatementline | |
| exception_type / severity | varchar | |
| anomaly_score | decimal | |
| detail | text | |
| status | varchar | |
| assigned_to_id / resolved_by_id / resolved_at | FK/datetime | |
| resolution_notes | text | |
| abuse_flag_id | int | → audit_abuseflag |
| created_at | datetime | indexed |

---

## TASKS  (operational task management)

### tasks_operationaltask
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| task_number | varchar | |
| title / description | varchar/text | |
| task_type / category / priority / status | varchar | |
| branch_id | FK → branches_branch | |
| created_by_id / assigned_to_id / completed_by_id | FK → users_staffprofile | |
| parent_task_id | FK → self | Subtasks |
| related_model / related_id | varchar/int | Generic soft link |
| due_date | datetime | indexed |
| start_date | datetime | |
| estimated_hours / actual_hours | decimal | |
| completed_at / completion_notes | datetime/text | |
| recurrence | varchar | |
| schedule_id | FK → tasks_taskschedule | |
| tags | varchar | |
| created_at / updated_at | datetime | |

### tasks_taskassignment
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| task_id | FK → tasks_operationaltask | |
| staff_id | FK → users_staffprofile | |
| role | varchar | |
| assigned_by_id / assigned_at | FK/datetime | |
| is_completed / completed_at | bool/datetime | |

### tasks_taskitem  (checklist line)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| task_id | FK → tasks_operationaltask | |
| item_id | FK → catalog_item | Nullable |
| item_name / item_code | varchar | |
| quantity_expected / quantity_actual | decimal | |
| unit / notes | varchar | |
| is_checked / checked_by_id / checked_at | bool/FK/datetime | |
| sort_order | smallint | |

### tasks_taskmessage  (task chatter)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| task_id | FK → tasks_operationaltask | |
| author_id | FK → users_staffprofile | |
| message_type / body | varchar/text | |
| is_deleted / deleted_at / created_at | bool/datetime | |

### tasks_taskattachment
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| task_id | FK → tasks_operationaltask | |
| uploaded_by_id | FK → users_staffprofile | |
| file / file_name / file_type / file_size | file/varchar/int | |
| uploaded_at | datetime | |

### tasks_taskschedule  (recurring task generator)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name | varchar | |
| task_type / category / priority | varchar | |
| title_template / description_template | varchar/text | |
| branch_id | FK → branches_branch | |
| assign_to_id | FK → users_staffprofile | |
| assign_to_role | varchar | |
| frequency | varchar | daily/weekly/monthly |
| day_of_week / day_of_month | smallint | |
| time_of_day | time | |
| advance_days | smallint | Create N days ahead |
| is_active | bool | |
| last_run_at / next_run_at | datetime | next indexed |
| created_by_id / created_at / updated_at | FK/datetime | |
| estimated_hours | decimal | |

### tasks_taskauditlog
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| task_id | FK → tasks_operationaltask | |
| action | varchar | |
| actor_id | FK → users_staffprofile | |
| field_name / old_value / new_value | varchar/text | |
| extra | jsonb | |
| created_at | datetime | |

---

## CHEQUES  (post-dated cheque planning — holiday-aware)

### cheques_egyptianholiday
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| date | date | **UNIQUE**, indexed |
| name_ar / name_en | varchar | |
| holiday_type | varchar | |
| is_annual | bool | Recurs yearly |

### cheques_chequeplan
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| title / notes | varchar/text | |
| status | varchar | |
| payee_name / bank_name / account_number | varchar | |
| total_amount | decimal | |
| reference_doc | varchar | |
| cheque_count | smallint | |
| first_due_date | date | |
| interval_value / interval_unit | smallint/varchar | Spacing between cheques |
| created_by_id | FK → users_staffprofile | |
| branch_id | FK → branches_branch | |
| created_at / updated_at | datetime | |

### cheques_chequeinstalment
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| plan_id | FK → cheques_chequeplan | |
| instalment_no | smallint | |
| amount | decimal | |
| nominal_date | date | Calculated date |
| due_date | date | Adjusted off holidays/weekends |
| cheque_number | varchar | |
| status | varchar | |
| issued_at / cleared_at | date | |
| notes | varchar | |

---

## BATCHES  (FEFO batch + expiry)

### batches_stockbatch
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | |
| branch_id | FK → branches_branch | |
| batch_number | varchar | |
| expiry_date | date | indexed |
| vendor_id | FK | Supplier |
| invoice_id | FK → invoices_supplierinvoice | |
| invoice_number / manufacturer | varchar | |
| purchase_price | decimal | |
| original_qty / current_qty | decimal | |
| storage_condition | varchar | |
| is_quarantined / quarantine_reason | bool/text | |
| is_expired | bool | |
| received_by_id / received_at | FK/datetime | |
| created_at / updated_at | datetime | |

### batches_batchmovement
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| batch_id | FK → batches_stockbatch | |
| movement_type | varchar | in / out / adjust / quarantine |
| qty_change / qty_after | decimal | |
| branch_id | FK → branches_branch | |
| performed_by_id | FK → users_staffprofile | |
| reference_type / reference_id | varchar/int | Generic soft link |
| notes / created_at | text/datetime | created indexed |

### batches_nearexpiryalert
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| batch_id | FK → batches_stockbatch | |
| threshold_days | smallint | 30 / 60 / 90 / 180 |
| alerted_at / resolved_at | datetime | |
| resolution | varchar | |

---

## INSURANCE  (SOFTECH motalba claim mirror + client hierarchy + print/export)

> **Money triad.** Most insurance rows carry a `{local, imported, tarsia}_before`
> + `{...}_discount` + `gross_before` + `total_discount` + `net_after` block —
> local-origin vs imported vs "tarsia" (contract-rate) sub-totals. Documented once
> here; per-table rows below say "money triad" for that block. See memory
> [[insurance-tarsia-finals-bug]] — stored `final_*` can drift from fresh totals.

### insurance_insuranceparentclient / insurance_insuranceclient / insurance_insurancesubclient  (3-level hierarchy)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| client_id (subclient only) | FK → insurance_insuranceclient | |
| name / name_short | varchar | |
| softech_personcode | varchar | SOFTECH account code (parent/client/subclient level) |
| additional_personcodes (subclient) | text | Comma list of extra personcodes |
| address / contact_name / contact_phone (client) | varchar/text | |
| notes / is_active / created_at / updated_at | text/bool/datetime | |

### insurance_insurancecontract
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| subclient_id | FK → insurance_insurancesubclient | |
| name | varchar | |
| effective_from / effective_to | date | |
| local_discount_pct / imported_discount_pct / tarsia_discount_pct | decimal | Contract discount rates |
| softech_ptclassifcodes | varchar | Mapped SOFTECH price-class codes |
| notes / created_at | text/datetime | |

### insurance_insuranceclaim  (period claim; snapshot vs final totals)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| claim_number | varchar | |
| subclient_id | FK → insurance_insurancesubclient | |
| contract_id | FK → insurance_insurancecontract | |
| period_from / period_to | date | |
| softech_motalba_no | varchar | SOFTECH motalba number |
| imported_personcodes / imported_branches | text | Import scope |
| imported_at / imported_by_id | datetime/FK | |
| snapshot_rx_count, snapshot_local_before, snapshot_imported_before, snapshot_tarsia_before, snapshot_gross_before, snapshot_total_discount, snapshot_net_after | int/decimal | **Snapshot** money triad (frozen at import) |
| final_rx_count, final_local_before, final_imported_before, final_tarsia_before, final_gross_before, final_total_discount, final_net_after | int/decimal | **Final** money triad (⚠ can drift — recompute) |
| applied_local_disc_pct / applied_imported_disc_pct / applied_tarsia_disc_pct | decimal | Applied rates |
| status | varchar | draft → submitted → … |
| submitted_at / expected_payment_date | datetime/date | |
| notes / created_at / updated_at / created_by_id | text/datetime/FK | |

### insurance_insuranceclaimprescription  (one motalba prescription/doc)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| claim_id | FK → insurance_insuranceclaim | |
| softech_docnumber / softech_docdate / softech_branchcode / softech_personcode | varchar/date | SOFTECH doc identity |
| patient_name | varchar | |
| sequence | int | Order within claim |
| local_before, imported_before, tarsia_before, gross_before, {local,imported,tarsia,total}_discount, net_after | decimal | Money triad |
| softech_net | decimal | SOFTECH-reported net (reconciliation) |

### insurance_insuranceclaimline  (item line under a prescription)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| prescription_id | FK → insurance_insuranceclaimprescription | |
| softech_itemcode / item_name | varchar | |
| item_category | varchar | local / imported / tarsia bucket |
| softech_origin_code / softech_imported_flag / softech_store_classif | varchar/bool | SOFTECH origin metadata |
| quantity / unit_price / line_total | decimal | |
| discount_pct / discount_amt / net_amount | decimal | |

### insurance_insuranceclaimadjustment  (manual per-Rx override; OneToOne)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| prescription_id | OneToOne → insurance_insuranceclaimprescription | |
| local_before / imported_before / tarsia_before | decimal | Nullable overrides |
| net_override | decimal | Force net |
| reason | text | |
| adjusted_by_id / adjusted_at | FK/datetime | |

### insurance_insuranceclaimmanualrx  (manually-added prescription not in SOFTECH import)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| claim_id | FK → insurance_insuranceclaim | |
| softech_docnumber / softech_docdate / softech_branchcode / softech_personcode / patient_name | varchar/date | |
| original_client_warning | text | Warns if personcode belongs to another client |
| (money triad: local/imported/tarsia_before, gross_before, {..}_discount, net_after) | decimal | |
| position | varchar | before / after |
| print_date | date | |
| sequence | int | |
| added_by_id / reason / added_at | FK/text/datetime | |

### insurance_insuranceclaimexclusion  (exclude an Rx from the claim; OneToOne)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| prescription_id | OneToOne → insurance_insuranceclaimprescription | |
| reason | text | |
| excluded_by_id / excluded_at | FK/datetime | |

### insurance_insuranceclaimsupplement  (extra rows appended to a claim)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| claim_id | FK → insurance_insuranceclaim | |
| supplement_type / supplement_number / label | varchar | |
| print_date | date | |
| (money triad) + rx_count | decimal/int | |
| notes / sort_order / created_by_id / created_at | text/smallint/FK/datetime | |

### insurance_insurancepayment
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| claim_id | FK → insurance_insuranceclaim | |
| payment_date / amount / reference | date/decimal/varchar | |
| notes / recorded_by_id / recorded_at | text/FK/datetime | |

### insurance_insurancededuction
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| claim_id | FK → insurance_insuranceclaim | |
| prescription_id | FK → insurance_insuranceclaimprescription | Nullable |
| item_name | varchar | |
| reason_code / reason_detail | varchar/text | |
| amount | decimal | |
| recorded_by_id / recorded_at | FK/datetime | |

### insurance_insuranceclaimbillinggroup  (sub-billing filter within a claim)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| claim_id | FK → insurance_insuranceclaim | |
| code / name / description | varchar/text | |
| filter_relative_degree / filter_dept_name / filter_hi_type_code / filter_patient_no_prefix | varchar | Grouping filters |
| rx_count / gross_before / total_discount / net_after | int/decimal | |
| sort_order / created_by_id / created_at | smallint/FK/datetime | |

### insurance_motalbacache  (read-only SOFTECH motalba mirror)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| personcode / motalbano / docnumber / docdate | varchar/int/date | all indexed |
| branchcode | varchar | |
| motalbasdate / motalbafdate | date | claim start/finish |
| doccode | varchar | 30 = مرتجع (return) |
| docvalue_grandtotal / docvaluerequired | decimal | |
| motalba_docorder / ppersoncode / patientcode / custbranchcode / usercode | int/varchar | |
| synced_at | datetime | |

### insurance_companiesitemscache  (read-only SOFTECH companiesitems mirror)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| branchcode / docnumber / doccode | varchar | branch+doc indexed |
| docdate | date | indexed |
| patientname / patientno / financialno / fileno / roshettano / membershipno | varchar | roshettano indexed |
| deptname / relativedegree / hi_typecode | varchar | |
| examdate / synced_at | date/datetime | |

### insurance_insuranceapplymasterrun  (bulk price/category apply — reversible)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| claim_id | FK → insurance_insuranceclaim | |
| applied_at / applied_by_id | datetime/FK | |
| apply_price / apply_category | bool | What was applied |
| lines_updated / prescriptions_updated | int | |
| net_before / net_after | decimal | |
| pre_state | jsonb | Snapshot for revert |
| reverted / reverted_at / reverted_by_id | bool/datetime/FK | |

### insurance_insuranceclaimlinebackup  (per-line pre-apply backup)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| run_id | FK → insurance_insuranceapplymasterrun | |
| line_id | FK → insurance_insuranceclaimline | |
| item_category / unit_price / line_total / discount_pct / discount_amt / net_amount | varchar/decimal | Pre-apply snapshot |

### insurance_insuranceexportprofile  (Excel/print styling)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name / is_default | varchar/bool | |
| subclient_id | FK → insurance_insurancesubclient | Nullable (global) |
| header_{left,center,right} / footer_{left,center,right} | text | Placeholders like `{page}`/`{pages}` |
| font_name / header_font_size / header_fill / header_font_color | varchar/int | Styling |
| subtotal_font_size / subtotal_fill / total_font_size / total_fill | int/varchar | |
| border_style / day_block_blank_rows / repeat_header_each_page | varchar/int/bool | |
| watermark_image / watermark_width_cm / watermark_anchor | file/decimal/varchar | |
| base_template_note / created_at / updated_at | text/datetime | |

### insurance_insurancepivottemplate  (saved pivot config)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name / source | varchar | e.g. prescriptions |
| row_dim / col_dim / measure | varchar | Pivot axes + measure (net/…) |
| is_shared / created_by_id / created_at | bool/FK/datetime | |

---

## LOYALTY

### loyalty_loyaltytier
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name | varchar | **UNIQUE** |
| name_ar | varchar | |
| order | smallint | Tier rank |
| min_points | int | Threshold |
| color / icon | varchar | |
| earn_multiplier | decimal | Point earn multiplier |
| benefits_description | text | |

### loyalty_loyaltyaccount  (OneToOne per customer)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| customer_id | OneToOne → customers_customer | |
| tier_id | FK → loyalty_loyaltytier | |
| points_balance | int | Platform-native balance |
| points_lifetime / points_redeemed | int | |
| softech_points_balance | int | Mirror of SOFTECH picpoints (reconciled) |
| is_active / created_at / updated_at | bool/datetime | |

### loyalty_pointtransaction  (immutable ledger)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| account_id | FK → loyalty_loyaltyaccount | |
| points | int | Signed |
| transaction_type | varchar | earn / redeem / adjust |
| source_type / source_id | varchar/int | Generic soft link (indexed) |
| reason / notes | varchar/text | |
| balance_after | int | |
| created_by_id / created_at | FK/datetime | indexed |

### loyalty_rewardcatalog
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name / name_ar | varchar | |
| reward_type | varchar | voucher / discount / gift |
| points_cost | int | |
| description | text | |
| reward_data | jsonb | Type-specific payload |
| min_tier_id | FK → loyalty_loyaltytier | Gate |
| valid_from / valid_to | date | |
| stock_limit / redeemed_count | int | |
| is_active / created_at | bool/datetime | |

### loyalty_redemptionrequest
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| account_id | FK → loyalty_loyaltyaccount | |
| reward_id | FK → loyalty_rewardcatalog | |
| points_spent | int | |
| status | varchar | pending / approved / fulfilled |
| notes | text | |
| voucher_id | FK → vouchers_voucher | Issued voucher |
| approved_by_id / approved_at / fulfilled_at | FK/datetime | |
| created_at / updated_at | datetime | indexed |

### loyalty_softechpointslog  (audit of SOFTECH picpoints writes)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| customer_id | FK → customers_customer | |
| softech_pic | varchar | indexed |
| delta | int | Points change |
| reason | varchar | |
| balance_before / balance_after | int | |
| success / error_message | bool/text | |
| created_by_id / created_at | FK/datetime | indexed |

---

## REFERRAL

### referral_referralcode  (OneToOne per customer)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| customer_id | OneToOne → customers_customer | |
| code | varchar | Unique share code |
| is_active | bool | |
| total_leads / validated_leads / total_points_earned | int | Denormalized counters |
| created_at / updated_at | datetime | |

### referral_referrallead
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| referral_code_id | FK → referral_referralcode | |
| referrer_id | FK → customers_customer | |
| lead_name / lead_phone | varchar | phone indexed |
| relationship | varchar | |
| notes | text | |
| status | varchar | pending → invited → validated → rewarded |
| registered_customer_id | FK → customers_customer | On conversion |
| otp_attempts | smallint | |
| invitation_sent_at / invitation_expires_at | datetime | |
| fraud_score | smallint | |
| fraud_flags | jsonb | |
| device_fingerprint | varchar | indexed (fraud) |
| created_at / updated_at / validated_at / rewarded_at | datetime | |

### referral_referralevent
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| lead_id | FK → referral_referrallead | |
| event_type | varchar | indexed |
| message | text | |
| created_by_id / created_at | FK/datetime | indexed |
| meta | jsonb | |

### referral_fraudsignal
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| lead_id | FK → referral_referrallead | |
| signal_type | varchar | |
| score_delta | smallint | Added to lead.fraud_score |
| detail | text | |
| detected_at | datetime | |

---

## PRODUCT_EXPERIENCE  (storefront/content layer over catalog_item)

### product_experience_productmapping
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | |
| softech_id | varchar | Denormalized (indexed) |
| external_code | varchar | GS1 / NDC |
| barcode | varchar | indexed |
| is_primary | bool | |
| sync_status / last_synced | varchar/datetime | |
| notes | varchar | |

### product_experience_productmedia
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | |
| media_type | varchar | image / video |
| file / thumbnail / alt_text | file/image/varchar | |
| order | smallint | indexed |
| is_primary / approved | bool | indexed |
| source | varchar | manual_upload / … |
| uploaded_by_id / created_at | FK/datetime | |

### product_experience_productcontent  (OneToOne)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | OneToOne → catalog_item | |
| display_name_ar / display_name_en | varchar | |
| short_description / long_description / instructions | text | |
| storage / usage / contraindications / benefits / marketing_text | text | Content blocks |
| keywords | text | |
| faq / adherence_icons | jsonb | |
| whatsapp_preview | text | |
| last_updated_by_id / updated_at | FK/datetime | |

### product_experience_productattribute  (OneToOne)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | OneToOne → catalog_item | |
| strength / concentration | varchar | |
| prescription_required | bool | |
| special_warnings | text | |
| flavor / color / size / pack_size_label | varchar | |
| count_per_pack | smallint | |
| temperature_storage | varchar | |
| shelf_life_months | smallint | |
| updated_at | datetime | |

### product_experience_productseo  (OneToOne)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | OneToOne → catalog_item | |
| slug | slug | **UNIQUE**, unicode |
| title_ar / title_en / description_ar / description_en / keywords | varchar/text | |
| canonical / og_image | url/image | |
| updated_at | datetime | |

### product_experience_productexperience  (engagement counters; OneToOne)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | OneToOne → catalog_item | |
| views / shares / wishlist_adds / reservations / refills / call_requests | int | Counters |
| popularity_score | float | indexed |
| last_interaction / updated_at | datetime | |

### product_experience_productrelation  (item↔item graph)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| from_item_id / to_item_id | FK → catalog_item | |
| relation_type | varchar | related / alternative / cross-sell (indexed) |
| order / is_active | smallint/bool | |
| added_by_id / created_at | FK/datetime | |

### product_experience_productavailabilitycache
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | |
| branch_id | FK → branches_branch | |
| status | varchar | in_stock / low / out |
| last_checked | datetime | |

### product_experience_productreview  (disabled until e-commerce)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | |
| customer_name | varchar | |
| rating | smallint | 1–5 |
| title / body | varchar/text | |
| is_approved / is_active | bool | is_active default False |
| created_at | datetime | |

---

## ENRICHMENT  (AI product enrichment + approval)

### enrichment_itemenrichment  (OneToOne)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | OneToOne → catalog_item | |
| name_ar / brand_name | varchar | |
| manufacturer_ar/_en, country_ar/_en, dosage_form_ar/_en | varchar | AR/EN pairs |
| atc_code / strength / volume / pack_size_label | varchar | |
| indication_ar/_en, contraindication_ar, warning_ar | text | |
| pregnancy_category / age_range | varchar/text | |
| storage_condition / administration_route_ar | text | |
| dosage_ar / frequency_ar / duration_ar | text | |
| side_effects_ar/_en, drug_interactions_ar | text | |
| rx_otc | varchar | |
| image_url / image_secondary_url | url | |
| seo_desc_ar/_en, medical_keywords_ar/_en | text | |
| completeness_score | float | indexed |
| is_published | bool | indexed |
| last_enriched_at / enriched_by_id | datetime/FK | |
| created_at / updated_at | datetime | |

### enrichment_enrichmentbatch
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name | varchar | |
| status | varchar | pending → running → done (indexed) |
| scope_type / scope_params | varchar/jsonb | all / filtered |
| auto_publish_threshold | float | |
| total_items / processed_items / suggestions_generated / auto_published / error_count | int | |
| error_log | text | |
| created_by_id / started_at / finished_at / created_at | FK/datetime | |

### enrichment_enrichmentsuggestion
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | |
| enrichment_id | FK → enrichment_itemenrichment | |
| batch_id | FK → enrichment_enrichmentbatch | |
| field_name | varchar | indexed |
| suggested_value / current_value / approved_value | text | |
| source | varchar | ai / gemini / … |
| confidence | float | |
| status | varchar | pending / approved / rejected (indexed) |
| notes | text | |
| reviewed_by_id / reviewed_at / created_at | FK/datetime | |

### enrichment_enrichmentapprovallog  (learning corpus)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | |
| field_name / source | varchar | |
| confidence_at_review | float | |
| outcome | varchar | accepted / rejected / edited |
| accepted_value | text | |
| reviewer_id / reviewed_at | FK/datetime | |

---

## IMAGES  (product image search / candidates / review)

### images_productnormalization  (OneToOne — parsed search terms)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | OneToOne → catalog_item | |
| canonical_name / normalized_name | varchar | |
| search_query_en / search_query_ar | varchar | |
| brand / strength / dosage_form / pack_size | varchar | Parsed attributes |
| aliases | jsonb | |
| parse_confidence | float | |
| updated_at | datetime | |

### images_imagesearchjob
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | |
| status | varchar | |
| current_stage / priority | smallint | Pipeline stage |
| attempt_count / max_attempts (3) | smallint | |
| auto_approve_threshold (0.85) / review_threshold (0.50) | float | |
| candidates_found / candidates_scored / best_score | int/float | |
| triggered_by_id | FK → users_staffprofile | |
| last_error / started_at / finished_at / created_at | text/datetime | |

### images_imagecandidate
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| job_id | FK → images_imagesearchjob | |
| item_id | FK → catalog_item | |
| source_url / source_page_url / query_used | url/varchar | |
| source_type | varchar | |
| local_file | image | |
| width / height / file_size_bytes / format | int/varchar | |
| phash | varchar | Perceptual hash (indexed, dedup) |
| quality_score / confidence_score / total_score | float | |
| score_breakdown | jsonb | |
| status | varchar | pending / approved / rejected |
| reviewed_by_id / reviewed_at / review_note | FK/datetime/varchar | |
| scraper_metadata | jsonb | |
| created_at | datetime | |

### images_imagesource  (scraper source config)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name | varchar | **UNIQUE** |
| source_type / base_url | varchar/url | |
| priority | smallint | lower = tried first |
| rate_limit_rpm | smallint | |
| requires_js | bool | Playwright |
| is_active | bool | indexed |
| total_requests / successful_hits / avg_quality_score / last_used_at | int/float/datetime | |
| headers | jsonb | |

### images_imageapprovalinsight  (learning: which sources work per brand)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| brand | varchar | indexed |
| source_type | varchar | |
| approved / considered | int | |
| avg_quality_score | float | |
| last_updated | datetime | |

---

## RECOMMENDATIONS

### recommendations_recommendationenginerun
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| started_at / finished_at | datetime | |
| status | varchar | running / done (indexed) |
| pairs_generated / invoices_scanned / customers_scored | int | |
| error_message | text | |
| min_support (0.001) / min_confidence (0.05) / lookback_days (365) | float/int | Apriori params |

### recommendations_frequentlyboughttogether
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| run_id | FK → recommendations_recommendationenginerun | |
| item_a_id / item_b_id | FK → catalog_item | |
| co_occurrences / item_a_occurrences | int | |
| confidence | float | indexed |
| support / lift / score | float | score indexed |

### recommendations_customerrecommendation
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| run_id | FK → recommendations_recommendationenginerun | |
| customer_id | FK → customers_customer | |
| item_id | FK → catalog_item | |
| score | float | indexed |
| reason | varchar | |
| is_chronic_related | bool | |

---

## CHRONIC  (chronic detection + active-ingredient map + interactions)

> **Data-safety:** use `chronic_activeingredient` + `chronic_itemingredientmap` as the
> authoritative molecule source — NOT `catalog_item.name_scientific` (dirty; see
> [[catalog-scientific-name-is-dirty]] and Key Business Rule #11).

### chronic_medicationtag
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name | varchar | **UNIQUE** |
| name_ar | varchar | |
| tag_type | varchar | |
| color | varchar | |
| description / is_active | text/bool | |
| created_by_id / created_at | FK/datetime | |

### chronic_activeingredient
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name | varchar | indexed |
| name_ar / name_scientific | varchar | |
| atc_code | varchar | indexed |
| is_chronic | bool | indexed |
| chronic_class | varchar | |
| tags | M2M → chronic_medicationtag (via IngredientTag) | |
| notes / created_by_id / created_at / updated_at | text/FK/datetime | |

### chronic_ingredienttag  (M2M through)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| active_ingredient_id | FK → chronic_activeingredient | |
| tag_id | FK → chronic_medicationtag | |
| added_by_id / added_at | FK/datetime | |

### chronic_itemingredientmap  (item ↔ molecule)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | |
| active_ingredient_id | FK → chronic_activeingredient | |
| concentration | varchar | |
| is_primary | bool | |
| mapped_by_id / mapped_at | FK/datetime | |

### chronic_followupprotocol
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| active_ingredient_id | FK → chronic_activeingredient | |
| name | varchar | |
| frequency_type / days | varchar/int | Refill cadence |
| trigger_condition / customer_type_filter | varchar | |
| task_type / priority | varchar | Generated follow-up |
| message_template | text | |
| applies_to_branches | M2M → branches_branch | |
| is_active / sort_order | bool/int | |
| created_by_id / created_at / updated_at | FK/datetime | |

### chronic_druginteraction
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| ingredient_a / ingredient_b | varchar | Molecule pair |
| severity | varchar | |
| mechanism / clinical_effect / management_ar / management_en | text | |
| is_active | bool | indexed |
| source | varchar | |
| created_by_id / created_at / updated_at | FK/datetime | |

### chronic_drugcontraindication
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| ingredient | varchar | |
| condition | varchar | Disease/state |
| severity / population | varchar | |
| description_ar | text | |
| is_active | bool | indexed |
| source / created_by_id / created_at | varchar/FK/datetime | |

---

## FINANCE  (finance intelligence — read/derive from SOFTECH; no SOFTECH writes)

### finance_financeschematable  (SOFTECH schema discovery/catalog)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| table_name | varchar | **UNIQUE** |
| inferred_purpose | varchar | |
| row_count | bigint | |
| columns / sample_rows | jsonb | Discovered schema + up to 3 sample rows |
| is_confirmed / sync_enabled | bool | |
| category | varchar | |
| discovered_at / notes | datetime/text | |

### finance_account  (chart of accounts — hierarchical)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| code | varchar | **UNIQUE**, indexed |
| name / name_ar | varchar | |
| account_type | varchar | asset/liability/equity/revenue/expense/unknown |
| nature | varchar | debit / credit |
| parent_id | FK → self | Tree |
| level / is_leaf / is_active | int/bool | is_leaf = posting account |
| softech_code | varchar | Original key |
| description / synced_at | text/datetime | |

### finance_financialperiod
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| year / month | int | month 0 = annual, 1–12 monthly |
| period_type | varchar | month / quarter / year |
| period_start / period_end | date | |
| label | varchar | e.g. "2024-Q1" |
| is_closed / created_at | bool/datetime | |

### finance_journalentry
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| softech_number | varchar | indexed |
| entry_date | date | indexed |
| branch_id | FK → branches_branch | |
| description / description_ar | varchar | |
| entry_type | varchar | manual / synced / … |
| reference | varchar | |
| total_debit / total_credit | decimal | |
| is_balanced | bool | |
| period_id | FK → finance_financialperiod | |
| source_table / synced_at | varchar/datetime | |

### finance_journalline
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| entry_id | FK → finance_journalentry | CASCADE |
| line_number | int | |
| account_id | FK → finance_account | |
| account_code | varchar | Raw SOFTECH code |
| description | varchar | |
| debit / credit | decimal | |
| cost_center / party_code / party_name | varchar | |

### finance_accountbalance  (per account × period × branch)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| account_id | FK → finance_account | CASCADE |
| period_id | FK → finance_financialperiod | CASCADE |
| branch_id | FK → branches_branch | |
| opening_balance / total_debit / total_credit / closing_balance | decimal | |
| movement_count | int | |

### finance_treasurymovement
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| softech_number | varchar | indexed |
| movement_date | date | indexed |
| movement_type | varchar | receipt / payment |
| direction | varchar | in / out |
| payment_method | varchar | cash / bank / cheque |
| account_code | varchar | |
| branch_id | FK → branches_branch | |
| amount | decimal | |
| description / reference | varchar | |
| party_code / party_name / party_type | varchar | |
| cheque_number / cheque_date / bank_name | varchar/date | |
| period_id | FK → finance_financialperiod | |
| source_table / synced_at | varchar/datetime | |

### finance_expenserecord
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| softech_ref | varchar | indexed |
| expense_date | date | indexed |
| category / sub_category | varchar | |
| branch_id | FK → branches_branch | |
| amount | decimal | |
| description / vendor / reference / account_code / cost_center | varchar | |
| is_recurring | bool | |
| period_id | FK → finance_financialperiod | |
| source_table / synced_at | varchar/datetime | |

### finance_financialsnapshot  (computed KPI cube per period × branch)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| period_id | FK → finance_financialperiod | CASCADE |
| branch_id | FK → branches_branch | |
| gross_revenue / returns_value / net_revenue | decimal | |
| cogs / gross_profit / gross_margin_pct | decimal | |
| total_purchases / total_purchase_returns / net_purchases | decimal | |
| total_expenses / payroll_expenses / rent_expenses / utility_expenses / other_expenses | decimal | Expense breakdown |
| operating_profit / ebitda / net_profit / net_margin_pct | decimal | |
| cash_inflow / cash_outflow / net_cash_flow | decimal | |
| total_assets / total_liabilities / equity / working_capital | decimal | Balance-sheet |
| inventory_value / total_receivables / total_payables | decimal | |
| current_ratio / quick_ratio / debt_ratio | decimal | Ratios |
| data_sources | jsonb | Which sources contributed |
| is_complete / computed_at | bool/datetime | |

### finance_financesyncrun
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| started_at / finished_at | datetime | |
| status | varchar | pending / running / done |
| sync_type | varchar | incremental / full |
| period_start / period_end | date | |
| records_synced | jsonb | `{table: count}` |
| errors | jsonb | `[{table, message}]` |
| triggered_by | varchar | |
| notes / duration_seconds | text/int | |

---

## APPROVALS  (generic operational + HR approval engine)

### approvals_approvalworkflowdefinition
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| code | varchar | Unique workflow key |
| category | varchar | operational / hr / pricing |
| name / name_ar / description | varchar/text | |
| is_active | bool | indexed |
| reject_terminates | bool | Reject ends whole request |
| sla_hours | int | |
| created_at / updated_at | datetime | |

### approvals_approvalstepdefinition
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| workflow_id | FK → approvals_approvalworkflowdefinition | |
| order | smallint | indexed (step sequence) |
| name / name_ar | varchar | |
| approver_role | varchar | Role-based approver |
| approver_user_id | FK → users_staffprofile | Specific approver |
| restrict_to_branch | bool | |
| is_optional | bool | |
| escalation_hours | smallint | |
| on_reject | varchar | terminate / continue / back |

### approvals_approvalrequest
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| workflow_id | FK → approvals_approvalworkflowdefinition | |
| requested_by_id | FK → users_staffprofile | |
| requested_at | datetime | indexed |
| title / body | varchar/text | |
| content_type_id / object_id | GenericFK | Subject record |
| context_data | jsonb | Snapshot for approvers |
| status | varchar | pending / approved / rejected |
| current_step_order | smallint | |
| due_at | datetime | indexed |
| is_overdue | bool | indexed |
| completed_at / completion_note | datetime/text | |

### approvals_approvaldecision
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| request_id | FK → approvals_approvalrequest | |
| step_id | FK → approvals_approvalstepdefinition | |
| step_order / step_name | smallint/varchar | Snapshot |
| decision | varchar | approve / reject / delegate |
| decided_by_id / decided_at | FK/datetime | |
| notes | text | |
| delegated_to_id | FK → users_staffprofile | |

### approvals_approvalescalationlog
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| request_id | FK → approvals_approvalrequest | |
| step_order | smallint | |
| escalated_at | datetime | |
| notified_users | jsonb | |
| note | varchar | |

---

## FORECASTING

### forecasting_seasonalityindex
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | Nullable |
| category_id | FK → catalog_category | Nullable |
| month | smallint | 1–12 |
| index_value | decimal | Seasonal multiplier |
| computed_from_years | smallint | |
| computed_at | datetime | |

### forecasting_forecastrun
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| started_at / completed_at | datetime | |
| status | varchar | running / done (indexed) |
| items_processed | int | |
| triggered_by_id | FK → users_staffprofile | |
| parameters | jsonb | |
| error | text | |

### forecasting_forecastaccuracy
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | CASCADE |
| branch_id | FK → branches_branch | CASCADE |
| forecast_date | date | indexed |
| mape / mae | decimal | Accuracy metrics |

---

## QA  (branch inspections)

### qa_qachecklisttemplate
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name / name_ar | varchar | |
| items | jsonb | `[{key, label}]` checklist |
| is_active | bool | indexed |
| created_at | datetime | |

### qa_qainspection
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| template_id | FK → qa_qachecklisttemplate | PROTECT |
| branch_id | FK → branches_branch | PROTECT |
| inspector_id | FK → users_staffprofile | SET_NULL |
| status | varchar | draft / submitted |
| results | jsonb | `[{key, pass/fail/na}]` |
| score | decimal | Computed % |
| notes | text | |
| created_at | datetime | indexed |
| submitted_at | datetime | |

---

## TRANSITS  (SOFTECH doccode-125 in-transit cache + picking/stocking classification)

### transits_intransittransfer  (read-only cache of a SOFTECH 125 issue)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| erp_doc_number | varchar | SOFTECH docnumber (per-branch sequence, not globally unique) |
| erp_doc_code | varchar | 125 |
| erp_supplying_branch_code / erp_receiving_branch_code | varchar | receiver = header `cust_branch_code` |
| erp_receipt_doc_number | varchar | Linked 25-doc (via docnumber2) |
| erp_user_code / erp_store_code | varchar | |
| issue_date / erp_received_date / cancellation_expires_at | date | |
| supplying_branch_id / receiving_branch_id | FK → branches_branch | |
| linked_request_id | FK → transfers_transferrequest | |
| doc_value / item_count / total_quantity | decimal/int | |
| items_snapshot / received_items_snapshot / reconciliation | jsonb | Line-level snapshots + 125↔25 reconciliation |
| has_discrepancy | bool | |
| transit_status | varchar | |
| priority | varchar | |
| days_in_transit | int | |
| cancellation_available | bool | |
| alert_notification_count / last_alert_sent_at / last_alert_level | int/datetime/varchar | Aging alerts |
| internal_notes | text | |
| manually_received_at / manually_received_by_id | datetime/FK | |
| force_close_reason / force_closed_by_id | text/FK | |
| first_seen_at / last_synced_at / updated_at | datetime | |

### transits_pickzone  (per branch × purpose classification zone)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| branch_id | FK → branches_branch | NULL = default config |
| purpose | varchar | picking / stocking |
| name | varchar | |
| sort_key | smallint | Walk order |
| location | varchar | |
| color | varchar | |
| is_active | bool | |
| is_price_zone | bool | Price-threshold zone |
| is_fridge_zone | bool | Fridge (catalog flag + FRIDGE keyword) |
| is_fallback | bool | Uncategorized bucket |
| created_at / updated_at | datetime | |

### transits_pickzonerule  (keyword/column match → zone)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| zone_id | FK → transits_pickzone | |
| match_field | varchar | name / shape / medicine_type / family / producer / origin / unit |
| keywords | jsonb | Match list |
| priority | smallint | Reorderable |
| is_active / note | bool/varchar | |
| created_at / updated_at | datetime | |

### transits_itempickoverride  (per-item zone pin)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| branch_id | FK → branches_branch | NULL = default |
| purpose | varchar | picking / stocking |
| item_id | FK → catalog_item | |
| zone_id | FK → transits_pickzone | |
| tag | varchar | |
| created_by_id / created_at / updated_at | FK/datetime | |

### transits_intransitnote  (chatter on a transit)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| transfer_id | FK → transits_intransittransfer | |
| note_type | varchar | |
| body | text | |
| created_by_id / created_at | FK/datetime | |

### transits_intransitauditevent
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| transfer_id | FK → transits_intransittransfer | |
| action | varchar | |
| actor_id | FK → users_staffprofile | |
| detail | text | |
| created_at | datetime | indexed |

---

## AUDIT

### audit_auditlog  (cross-module audit trail)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| user_id | FK → users_staffprofile | |
| user_name / user_role | varchar | Snapshot |
| ip_address | inet | |
| action | varchar | create / update / delete / login / … |
| model_name / object_id / object_repr | varchar | Target |
| old_data / new_data / changes | jsonb | Field-level diff |
| extra | jsonb | |
| note | varchar | |
| created_at | datetime | indexed |

### audit_abuseflag  (staff abuse detection)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| staff_id | FK → users_staffprofile | |
| flag_type | varchar | |
| severity | varchar | |
| status | varchar | open / reviewed / dismissed |
| description | text | |
| evidence | jsonb | |
| count / window_hours | int | Detection window |
| reviewed_by_id / review_note | FK/text | |
| detected_at | datetime | indexed |
| reviewed_at | datetime | |

---

## DISCOUNT_APPROVALS  (item-discount writeback to SOFTECH — reference channel)

### discount_approvals_itempricechangerequest
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | FK → catalog_item | |
| requested_by_id | FK → users_staffprofile | |
| requested_at | datetime | |
| old_values / new_values / executed_values | jsonb | Price/discount before, requested, actually written |
| reason | text | |
| status | varchar | pending / approved / rejected / executed / rolled_back |
| reviewed_by_id / reviewed_at / review_notes | FK/datetime/text | |
| erp_executed_at | datetime | When replicated to SOFTECH |
| erp_usercode / erp_username | varchar | Executed under approver's SOFTECH identity |
| erp_error | text | |
| rolled_back_from_id | FK → self | |
| source | varchar | direct / import |

### discount_approvals_replicationscan  (HQ→branch price replication audit)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| started_at / finished_at | datetime | |
| days_window | int | default 30 |
| status | varchar | running / done |
| triggered_by_id | FK → users_staffprofile | |
| is_scheduled | bool | |
| items_checked / items_ok / items_with_gaps | int | |
| branches_down | jsonb | |
| error | text | |

### discount_approvals_replicationgap  (a stale HQ↔branch price)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| scan_id | FK → discount_approvals_replicationscan | CASCADE |
| item_softech_id | varchar | indexed |
| item_name | varchar | |
| branch_code | varchar | indexed |
| branch_name | varchar | |
| hq_itemlastupdate / branch_itemlastupdate | datetime | Drift detection |
| hq_usercode / source_user | varchar | |
| source_channel | varchar | direct / … |
| diff_summary | jsonb | |
| status | varchar | stale / repaired (indexed) |
| repaired_at / repaired_by_id / repair_note | datetime/FK/varchar | |

### discount_approvals_replicationpolicy  (singleton)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| auto_repair_enabled | bool | |
| max_items_per_run | int | |
| daily_window_days | int | |
| weekly_full_audit | bool | |
| updated_at / updated_by_id | datetime/FK | |

---

## HR  (geofenced attendance + leave / shift / OT / advances / expenses)

### hr_leavetype
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| code | varchar | **UNIQUE** |
| name / name_ar | varchar | |
| is_paid / accrues_balance | bool | |
| max_days_per_year / max_days_per_request | smallint | |
| approval_workflow_code | varchar | → approvals workflow |
| is_active | bool | |

### hr_leavebalance  (per staff × type × year)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| staff_id | FK → users_staffprofile | |
| leave_type_id | FK → hr_leavetype | |
| year | smallint | |
| entitled_days / consumed_days / carried_forward | decimal | |
| updated_at | datetime | |

### hr_leaverequest
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| staff_id | FK → users_staffprofile | |
| leave_type_id | FK → hr_leavetype | |
| start_date / end_date | date | |
| days_requested | decimal | |
| reason | text | |
| status | varchar | draft / pending / approved / rejected |
| approval_request_id | OneToOne → approvals_approvalrequest | |
| rejection_reason | text | |
| created_at / updated_at | datetime | |

### hr_shifttemplate
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| name / name_ar | varchar | |
| branch_id | FK → branches_branch | |
| start_time / end_time | time | |
| days_of_week | varchar | CSV of weekday indices |
| is_active | bool | |

### hr_shiftassignment
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| staff_id | FK → users_staffprofile | |
| shift_id | FK → hr_shifttemplate | |
| valid_from / valid_until | date | |
| assigned_by_id / assigned_at | FK/datetime | |

### hr_overtimerequest
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| staff_id | FK → users_staffprofile | |
| branch_id | FK → branches_branch | |
| date | date | |
| hours | decimal | |
| reason | text | |
| status | varchar | draft / … (indexed) |
| approval_request_id | OneToOne → approvals_approvalrequest | |
| created_at | datetime | |

### hr_salaryadvance
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| staff_id | FK → users_staffprofile | |
| amount | decimal | |
| repayment_date | date | |
| reason | text | |
| status | varchar | draft / … (indexed) |
| approval_request_id | OneToOne → approvals_approvalrequest | |
| finance_record_id | int | → finance record |
| settled_at / created_at / updated_at | datetime | |

### hr_expenseclaim
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| staff_id | FK → users_staffprofile | |
| branch_id | FK → branches_branch | |
| category | varchar | indexed |
| expense_date | date | |
| amount | decimal | |
| description | text | |
| receipt | file | |
| trip_destination / trip_purpose / trip_start / trip_end | varchar/text/date | Travel claims |
| distance_km / transport_type / allowance_amount | decimal/varchar | Mileage/allowance |
| status | varchar | draft / … (indexed) |
| approval_request_id | OneToOne → approvals_approvalrequest | |
| finance_record_id | int | |
| paid_at / rejection_reason / created_at / updated_at | datetime/text | |

### hr_attendancerecord  (geofenced clock in/out)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| staff_id | FK → users_staffprofile | |
| branch_id | FK → branches_branch | |
| work_date | date | indexed |
| check_in_at | datetime | |
| check_in_lat / check_in_lng | decimal | GPS |
| check_in_distance_m | int | Distance from branch coords |
| check_in_ok | bool | Within geofence? |
| check_out_at | datetime | |
| check_out_lat / check_out_lng / check_out_distance_m / check_out_ok | decimal/int/bool | |

---

## PROCUREMENT  (analytics over SOFTECH purchase data — doccode 10 buy / 120 return)

### procurement_purchaseline  (rolling cache of SOFTECH purchase lines)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| branch_code / supplier_code / item_code | varchar | all indexed |
| doc_number / doc_date / store_code | varchar/date | doc_date indexed |
| doccode | varchar | '10' buy / '120' return |
| is_return | bool | indexed |
| raw_qty / raw_value / unit_price / cost_price | decimal | As-invoiced |
| net_qty / net_value | decimal | Buy − return |
| public_price / margin_pct | decimal | |
| buyer_code / doc_value | varchar/decimal | |
| is_foc / foc_type | bool/varchar | Free-of-charge |
| vat_value / tax_rate_pct / effective_cost | decimal | Tax-adjusted true cost |
| return_type / supplier_category | varchar | |
| item_id | FK → catalog_item | |
| branch_id | FK → branches_branch | |
| synced_at | datetime | |

### procurement_supplierprofile  (per-supplier scorecard)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| supplier_code | varchar | **UNIQUE** |
| supplier_name / classif_code | varchar | |
| net_purchase_value / net_purchase_qty / net_return_value / return_pct | decimal | |
| distinct_items / invoice_count / branches_supplied | int | |
| avg_margin_pct / purchase_frequency | decimal | Avg days between orders |
| score_margin / score_availability / score_returns / score_price_stability / total_score | decimal | Base score |
| score_effective_cost / score_foc_benefit / score_tax_efficiency / enhanced_total_score | decimal | Enhanced score |
| foc_rate_pct / avg_tax_burden_pct | decimal | |
| supplier_category | varchar | |
| avoidable_loss_value / service_level_pct | decimal | |
| first_purchase_date / last_purchase_date / last_updated | date/datetime | |

### procurement_supplieritemmapping  (supplier↔item price history; feeds OCR learning)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| supplier_code | varchar | indexed |
| supplier_name | varchar | |
| item_code | varchar | indexed |
| item_id | FK → catalog_item | |
| item_name | varchar | |
| purchase_count / first_purchase_date / last_purchase_date | int/date | |
| net_qty_total / net_value_total | decimal | |
| min_price / max_price / avg_price / last_price / price_drift_pct | decimal | |
| confidence_score | decimal | |
| is_primary | bool | Supplier is item's primary source |
| ocr_match_count / ocr_correction_count | int | OCR learning signals |
| last_updated | datetime | |

### procurement_procurementenginerun
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| started_at / finished_at | datetime | |
| status | varchar | running / done |
| period_days | int | Lookback window (365) |
| lines_synced / lines_upserted / suppliers_updated / mappings_updated / alerts_generated | int | |
| error_message / triggered_by | text/varchar | |

### procurement_procurementsnapshot  (daily KPI snapshot)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| snapshot_date | date | **UNIQUE**, indexed |
| engine_run_id | FK → procurement_procurementenginerun | SET_NULL |
| purchase_growth_pct_mom / purchase_growth_pct_yoy | decimal | + other aggregate KPI columns |
| created_at | datetime | |

### procurement_buyerperformance
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| buyer_code / buyer_name | varchar | code indexed |
| period_start / period_end | date | |
| net_purchase_value / invoice_count / distinct_items / distinct_suppliers | decimal/int | |
| avg_margin_pct / return_pct / estimated_savings / procurement_score | decimal | |
| engine_run_id | FK → procurement_procurementenginerun | |
| created_at | datetime | |

### procurement_procurementalert
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| alert_type | varchar | indexed |
| severity | varchar | warning / … |
| entity_type / entity_code / entity_name | varchar | supplier/item/buyer/branch |
| title / message | varchar/text | |
| metric_value / threshold | decimal | |
| detected_at | datetime | indexed |
| is_resolved | bool | indexed |
| resolved_at / resolved_by / resolution_notes | datetime/varchar/text | |
| engine_run_id | FK → procurement_procurementenginerun | |

### procurement_suppliersegmentation
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| supplier_code | varchar | **UNIQUE**, indexed |
| supplier_name / supplier_category | varchar | |
| persontype / persontypeclassif / ptcode / ptclassifcode | varchar | SOFTECH classification codes |
| classified_at | datetime | |
| auto_classified / manual_override | bool | manual_override = don't auto-reclassify |
| notes | text | |
| foc_rate_pct / return_pct | decimal | |

---

## SYNC  (ERP sync orchestration)

### sync_syncrun
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| status | varchar | running / done / failed |
| started_at / completed_at | datetime | |
| records_synced | int | |
| error_message | text | |

### sync_synclog  (per-table detail)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| sync_run_id | FK → sync_syncrun | CASCADE |
| table_name | varchar | |
| records_processed | int | |
| created_at | datetime | |

### sync_softechpersontype  (SOFTECH person-type reference)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| ptcode | varchar | **UNIQUE**, indexed |
| ptdescr / ptedescr | varchar | AR/EN description |

### sync_softechpersonclassif  (person-type sub-classification)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| ptcode | varchar | indexed |
| ptclassifcode | varchar | indexed |
| ptclassifdescr | varchar | |

---

## FOLLOWUPS  (chronic refill follow-up — distinct from demand.DemandFollowUp; see DUP-004)

### followups_chronicmedicationprofile  (OneToOne per item)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| item_id | OneToOne → catalog_item | |
| is_chronic | bool | |
| avg_daily_usage / pack_size | decimal | |
| expected_duration_days / followup_before_days | int | Refill-due math |
| notes / source | text/varchar | |
| created_by_id / created_at / updated_at | FK/datetime | |

### followups_followuptask  (generated refill/chronic follow-up)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| customer_id | FK → customers_customer | Nullable |
| local_customer_id | FK → erp_localcustomer | Nullable |
| phcode | varchar | ERP customer code |
| item_id | FK → catalog_item | |
| branch_id | FK → branches_branch | |
| chronic_profile_id | FK → followups_chronicmedicationprofile | |
| assigned_to_id | FK → users_staffprofile | |
| task_type | varchar | |
| due_date | date | |
| status | varchar | |
| source_erp_transaction / source_sale_date / source_softech_branch_code | varchar/date | Origin sale |
| source_total_amount / source_item_qty / source_item_price | decimal | |
| closing_erp_transaction | varchar | Refill-completing sale |
| notes / result_note / attempts | text/int | |
| sales_channel | varchar | |
| priority_score / priority_score_updated | float/datetime | |
| phone_invalid / phone_invalid_at | bool/datetime | |
| demand_record_id | FK → demand_demandrecord | |
| source_campaign_id | FK → campaigns_whatsappcampaign | |
| is_pinned / pinned_by_id / pinned_at | bool/FK/datetime | |
| reminder_at / reminder_sent | datetime/bool | |
| created_by_id / created_at / updated_at / completed_at / completed_by_id | FK/datetime | |

### followups_followuptaskassignment
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| task_id | FK → followups_followuptask | |
| staff_id | FK → users_staffprofile | |
| assigned_by_id | FK → users_staffprofile | |
| assignment_reason | varchar | |
| assigned_at | datetime | |

---

## ERP  (local (non-SOFTECH) customer + ERP transaction mirror)

### erp_localcustomer  (branch-local customer not in central SOFTECH personsdata)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| phcode | varchar | ERP local customer code |
| name / phone / phone_alt | varchar | |
| erp_branch_code | varchar | |
| branch_id | FK → branches_branch | |
| address / area | text/varchar | |
| customer_type | varchar | |
| is_active | bool | |
| linked_customer_id | OneToOne → customers_customer | Bridge to central customer |
| synced_at | datetime | |

### erp_erptransaction  (mirror of an ERP sale/return header)
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| transaction_id | varchar | |
| doccode | varchar | |
| reference_number | varchar | |
| branch_id | FK → branches_branch | |
| softech_branch_code | varchar | |
| phcode | varchar | |
| local_customer_id | FK → erp_localcustomer | |
| personsdata_customer_id | FK → customers_customer | |
| transaction_date | datetime | |
| total_amount | decimal | |
| synced_at | datetime | |

### erp_erptransactionline
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| transaction_id | FK → erp_erptransaction | |
| item_id | FK → catalog_item | |
| item_code / item_name | varchar | |
| quantity / unit_price / line_total | decimal | |
| store_code | varchar | |

---

## ERD Relationship Summary

```
branches_branch ◄──── virtually all scoped tables

catalog_item ◄──────── catalog_itemstock (M)
                ◄──────── catalog_itembarcode (M)
                ◄──────── catalog_chronicmedication (M)
                ◄──────── catalog_variantmember (1)
                ◄──────── catalog_bundleitem (M)
                ◄──────── reservations_reservation
                ◄──────── demand_demanditem
                ◄──────── transfers_transferrequestitem
                ◄──────── vouchers_voucher (free_item)
                ◄──────── shortage_shortageitem
                ◄──────── customers_purchasehistoryline

customers_customer ◄── customers_customernote (M)
                   ◄── customers_customerhealthprofile (1)
                   ◄── customers_purchasehistory (M)
                   ◄── reservations_reservation
                   ◄── demand_demandrecord

users_staffprofile ◄── virtually all created_by / assigned_to fields

reservations_reservation ◄── reservations_reservationactivity (M)
                         ◄── reservations_reservationdownpayment (M)
                         ◄── reservations_reservationstatuslog (M)

transfers_transferrequest ◄── transfers_transferrequestitem (M)
                          ◄── transfers_transferrequestmessage (M)

vouchers_voucher ◄── vouchers_voucherassignment (M)
                 ◄── vouchers_voucherotp (M)
                 ◄── vouchers_voucherredemptiondocument (M)
                 ◄── vouchers_voucherredemption (M)

pos_orders_softechsalesorder ◄── pos_orders_softechsalesorderline (M) ──► catalog_item
                             ◄── pos_orders_softechsalesorderpayment (M)
                             ──► branches_branch, customers_customer, callcenter_calllog/callitem
```
