# 02 — Complete module inventory

Full audit, 2026-11-15, commit `56870174` (`main`). Generated from the code by a script that walks the Django
app registry, every `/api/` route (`apps/tests/security/routes.py`), `frontend/src`, the test files, the
scheduler (`apps/sync/tasks.py`), the SOFTECH write manifest and `apps/help/content/`. No database or SOFTECH
was read.

**How to read the columns**
- *Screens calling it*: frontend files that reference one of the app's API prefixes (0 = no screen uses it).
- *Test files*: test files that mention `apps.<app>` or `apps/<app>`. Tests that only hit the URL are not
  counted, so a low number is a lower bound (e.g. `dashboard`, `qa` are exercised by the role × route sweeps).
- *SOFTECH-write refs*: mentions in `apps/tests/security/softech_write_manifest.py` (writer table:
  [06](06_SOFTECH_INTEGRATION_AUDIT.md) §2).
- *Mechanical status* is what the code shows; business adoption (is it used, is its switch on) is in
  [08](08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md) §6 and `docs/handoff/2026-11-15-handoff.md` §5.
- *Audit findings*: IDs from reports 03–07 whose evidence names a file in that app.

## Inventory

| App | Label | Models | API routes | Screens calling it | Test files | Sched. refs | SOFTECH-write refs | Help | Python LOC | Mechanical status | Audit findings |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `access` | الوصول والشبكات | 4 | 14 | 7 | 40 | 0 | 0 | — | 3757 | working | — |
| `analytics` | التحليلات | 0 | 9 | 3 | 2 | 1 | 0 | yes | 2134 | working | — |
| `approvals` | محرك الموافقات | 5 | 8 | 1 | 8 | 1 | 0 | — | 1661 | working | — |
| `audit` | سجلات المراجعة والمراقبة | 3 | 11 | 1 | 92 | 0 | 0 | — | 1250 | working | — |
| `batches` | إدارة الدفعات والصلاحية (FEFO) | 9 | 32 | 1 | 16 | 4 | 0 | yes | 5583 | working | BE-15(P3), BE-21(P3) |
| `branches` | Branches | 2 | 3 | 3 | 86 | 1 | 0 | — | 683 | working | — |
| `callcenter` | مركز الاتصال | 9 | 37 | 4 | 19 | 2 | 0 | yes | 3508 | working | — |
| `campaigns` | حملات واتساب | 2 | 11 | 1 | 3 | 1 | 0 | — | 1401 | working | — |
| `catalog` | Catalog | 14 | 25 | 8 | 107 | 2 | 0 | yes | 4116 | working | — |
| `cheques` | شيكات وخزينة | 3 | 8 | 1 | 5 | 0 | 0 | — | 1031 | working | — |
| `chronic` | الأدوية المزمنة | 9 | 19 | 1 | 7 | 0 | 0 | yes | 2587 | working | — |
| `commerce` | مستندات تجارية | 6 | 12 | 3 | 1 | 0 | 0 | yes | 810 | working | BE-15(P3), BE-21(P3) |
| `composition` | تنقية المواد الفعّالة | 6 | 20 | 1 | 9 | 0 | 0 | — | 2778 | working | — |
| `config` | إعدادات النظام | 4 | 15 | 1 | 32 | 7 | 0 | — | 1303 | working | — |
| `counselling` | إرشادات الاستخدام | 6 | 17 | 5 | 10 | 0 | 0 | yes | 1384 | working | — |
| `crews` | الأطقم | 3 | 14 | 1 | 3 | 0 | 0 | yes | 1366 | working | — |
| `customers` | Customers | 12 | 25 | 10 | 96 | 4 | 3 | yes | 7141 | working | — |
| `dashboard` | Dashboard | 0 | 4 | 1 | 0 | 0 | 0 | — | 491 | working, UNTESTED | — |
| `data_lifecycle` | دورة حياة البيانات | 8 | 9 | 1 | 13 | 0 | 0 | — | 2995 | working | — |
| `delivery` | التوصيل | 10 | 41 | 7 | 14 | 2 | 0 | yes | 4632 | working | SEC-1(P0) |
| `demand` | محرك الطلب والمبيعات الضائعة | 5 | 42 | 11 | 8 | 3 | 0 | yes | 3632 | working | — |
| `discount_approvals` | موافقات تعديل الأسعار والخصومات | 5 | 29 | 1 | 13 | 3 | 4 | — | 2889 | working | S-11(P2), BE-14(P3), BE-15(P3), BE-21(P3) |
| `enrichment` | إثراء الكتالوج | 4 | 14 | 1 | 5 | 0 | 0 | — | 2149 | working | — |
| `erp` | ERP — طبقة المعاملات | 3 | 0 | 0 | 2 | 0 | 0 | — | 695 | working | — |
| `finance` | Finance | 42 | 124 | 12 | 74 | 12 | 8 | yes | 27269 | working | S-2(P1), BE-15(P3), BE-21(P3), SEC-11(P3) |
| `followups` | محرك المتابعة والأدوية المزمنة | 6 | 44 | 3 | 15 | 2 | 0 | yes | 4943 | working | — |
| `forecasting` | محرك التنبؤ بالمبيعات | 15 | 30 | 1 | 21 | 4 | 0 | — | 5423 | working | — |
| `gamification` | التحفيز (النقاط والمستويات) | 15 | 26 | 1 | 6 | 2 | 0 | yes | 3793 | working | — |
| `help` | دليل الاستخدام | 11 | 28 | 4 | 4 | 2 | 0 | — | 30530 | working | — |
| `hr` | الموارد البشرية | 22 | 61 | 4 | 16 | 1 | 0 | yes | 4786 | working | BE-15(P3) |
| `images` | اكتساب صور المنتجات | 5 | 19 | 1 | 7 | 0 | 0 | — | 3229 | working | — |
| `incentives` | Incentives | 8 | 30 | 1 | 17 | 0 | 0 | yes | 4624 | working | BE-10(P2), BE-21(P3) |
| `insights` | التحليلات السردية (Narrative Insights) | 4 | 9 | 1 | 8 | 1 | 0 | — | 5698 | working | — |
| `insurance` | مطالبات التأمين | 30 | 112 | 10 | 25 | 1 | 8 | yes | 18666 | working | BE-16(P3), BE-19(P3), SEC-7(P3) |
| `invoices` | فواتير الموردين | 7 | 39 | 1 | 59 | 0 | 9 | yes | 12308 | working | S-3(P1), S-4(P2), BE-15(P3), BE-17(P3), BE-21(P3), S-13(P3) |
| `lineage` | تتبع المستندات (Transaction Lineage) | 2 | 0 | 0 | 2 | 0 | 0 | — | 161 | working | — |
| `loyalty` | برنامج الولاء | 6 | 10 | 5 | 7 | 1 | 1 | yes | 1570 | working | BE-6(P2), BE-7(P2), BE-8(P2), BE-15(P3), BE-21(P3) |
| `notifications` | الإشعارات والتذكيرات | 13 | 31 | 1 | 44 | 9 | 0 | — | 5205 | working | SEC-3(P2), BE-15(P3) |
| `offers` | العروض والتخفيضات | 4 | 15 | 2 | 20 | 0 | 2 | — | 2814 | working | BE-21(P3) |
| `omni` | منصة التواصل الموحدة | 5 | 14 | 4 | 13 | 0 | 0 | yes | 2863 | working | — |
| `payments` | المدفوعات | 5 | 19 | 1 | 11 | 0 | 0 | — | 1970 | working | — |
| `pbx` | PBX / Issabel | 7 | 17 | 5 | 21 | 3 | 0 | — | 4718 | working | SEC-1(P0), SEC-9(P3) |
| `personal` | اللوحة الشخصية | 4 | 14 | 1 | 4 | 0 | 1 | — | 2139 | working | — |
| `pic_analytics` | تحليلات العملاء (PIC) | 6 | 29 | 1 | 23 | 1 | 0 | — | 3669 | working | — |
| `portal` | بوابة العملاء (Self-Service Portal) | 1 | 8 | 4 | 8 | 0 | 0 | — | 759 | working | SEC-1(P0), SEC-2(P1) |
| `pos_orders` | أوامر نقاط البيع غير المباشرة | 7 | 36 | 6 | 47 | 2 | 5 | — | 6983 | working | BE-1(P1), BE-2(P1), S-1(P1), BE-12(P2), BE-13(P2), BE-4(P2), FE-3(P2), FE-8(P2), S-12(P2), S-6(P2), S-7(P2), BE-15(P3), BE-21(P3), S-13(P3), S-14(P3), S-15(P3), SEC-11(P3) |
| `procurement` | ذكاء المشتريات | 12 | 35 | 5 | 25 | 2 | 0 | — | 5645 | working | BE-15(P3) |
| `product_experience` | تجربة المنتج | 9 | 25 | 9 | 7 | 0 | 0 | — | 2729 | working | — |
| `purchasing` | محرك المشتريات | 24 | 91 | 1 | 67 | 6 | 10 | yes | 20501 | working | PERF-5(P2), S-5(P2) |
| `qa` | مراجعة الجودة (الفروع) | 2 | 4 | 2 | 0 | 0 | 0 | — | 233 | working, UNTESTED | — |
| `recommendations` | محرك التوصيات | 3 | 7 | 2 | 4 | 0 | 0 | — | 1003 | working | — |
| `referral` | نظام الإحالة | 4 | 9 | 1 | 2 | 0 | 0 | — | 901 | working | BE-9(P2), BE-21(P3) |
| `replacement` | بدل الروشتة / شراء الأدوية من العملاء | 12 | 39 | 6 | 17 | 1 | 0 | yes | 5708 | working | — |
| `reservations` | Reservations | 7 | 20 | 17 | 26 | 3 | 0 | yes | 3702 | working | SEC-2(P1), PERF-4(P2), S-8(P2), BE-20(P3) |
| `shortage` | إدخال النواقص | 2 | 20 | 3 | 20 | 0 | 0 | yes | 3943 | working | — |
| `social` | قنوات التواصل الاجتماعي | 3 | 3 | 0 | 2 | 0 | 0 | — | 573 | backend only (no screen calls it) | SEC-4(P2) |
| `stock_audit` | تدقيق حركات المخزون | 7 | 16 | 1 | 13 | 1 | 0 | yes | 2815 | working | — |
| `stockcount` | جرد المخزون | 5 | 21 | 3 | 14 | 1 | 0 | yes | 3476 | working | — |
| `supply` | التزويد والتوريد الذكي | 8 | 43 | 1 | 32 | 1 | 0 | — | 8573 | working | — |
| `sync` | Sync | 6 | 9 | 1 | 58 | 12 | 10 | — | 17081 | working | S-8(P2), S-9(P2), BE-15(P3), S-20(P3) |
| `tasks` | إدارة المهام التشغيلية | 7 | 19 | 5 | 10 | 0 | 0 | yes | 1823 | working | — |
| `tax_invoicing` | الفواتير الضريبية | 25 | 74 | 11 | 7 | 3 | 0 | yes | 6830 | working | BE-15(P3) |
| `tests` | (not an installed app) | 0 | 0 | 0 | 373 | 0 | 1 | — | 2797 | internal / library | SEC-3(P2), BE-21(P3) |
| `trace` | تتبع العبوات (EDA) | 2 | 2 | 0 | 1 | 0 | 0 | — | 225 | backend only (no screen calls it) | — |
| `transfers` | طلبات التحويل بين الفروع | 3 | 21 | 11 | 15 | 2 | 0 | yes | 3207 | working | — |
| `transits` | التحويلات قيد النقل | 6 | 27 | 1 | 15 | 0 | 0 | — | 4881 | working | — |
| `usage_print` | طباعة طريقة الاستخدام | 3 | 5 | 1 | 3 | 0 | 0 | — | 818 | working | — |
| `users` | Users | 10 | 29 | 4 | 116 | 5 | 0 | — | 3689 | working | SEC-1(P0), FE-20(P3), SEC-10(P3) |
| `vision` | الرؤية الحاسوبية (OCR) | 1 | 2 | 1 | 6 | 0 | 0 | — | 648 | working | — |
| `vouchers` | القسائم والـ OTP | 8 | 26 | 2 | 16 | 1 | 0 | yes | 4481 | working | BE-11(P2), BE-5(P2), S-10(P2), BE-15(P3), BE-21(P3) |
| `whatsapp` | واتساب | 6 | 7 | 3 | 17 | 0 | 0 | — | 1406 | working | SEC-4(P2) |

Totals: 71 app folders, 1693 /api/ routes, 532 models, 741 migrations, unmapped API prefixes: none.

## What the inventory shows

- **Every API prefix is classified.** All 1,693 routes map to an RBAC module or a reasoned exempt/read-open
  entry in `core/middleware/module_access.py`; none is unmapped.
- **No disconnected backends of note.** Only `social` (inbound webhooks — no screen expected) and `trace`
  (P-58 track-and-trace foundation, dormant by owner decision) have API routes no screen calls. The frontend
  audit checked the other direction: all ~1,600 API paths the frontend calls exist on the backend
  ([05](05_FRONTEND_UX_AUDIT.md)).
- **Dead frontend code:** 10 orphan files (~3,300 lines) and one unlinked route (FE-14).
- **Built but switched off** (flags default `False`): POS writer, offers, usage print, counselling,
  phone alerts, refill reminders, daily count, track-and-trace, the data-lifecycle rules, HR attendance
  agent, GL drafting schedule, tax-invoicing flags. The switch list and owners are in the handoff §5.1.
- **Scheduled jobs:** 37 apps are referenced by the scheduler. The business review found follow-up generation and
  auto-close exist but are not scheduled (C09 in [09](09_TOP_30_QUICK_WINS.md)).
- **Size hot spots** (Python LOC, without tests/migrations): `help` 30.5k (mostly content), `finance` 27.3k,
  `purchasing` 20.5k, `insurance` 18.7k, `sync` 17.1k, `invoices` 12.3k — the findings concentrate in the
  money paths (`pos_orders`, `loyalty`, `vouchers`, `finance`, `invoices`, `purchasing`).
