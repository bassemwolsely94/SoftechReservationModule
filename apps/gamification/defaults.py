"""
apps/gamification/defaults.py — starting rules, levels and badges.

`ensure_defaults()` only CREATES missing rows; it never overwrites what an admin has
edited (pass reset=True from the seed command to restore the defaults on purpose).
"""
from decimal import Decimal

# key, category, points, name_ar, name_en, desc_ar, desc_en, extra
RULES = [
    # ── Sales (SOFTECH sales mirror: count + capped value + profit, cash ×1.5) ──
    ('sale_invoice', 'sales', 2, 'فاتورة بيع', 'Sale invoice',
     'لكل فاتورة بيع مسجلة باسمك في SOFTECH', 'Per sale invoice under your SOFTECH user',
     {'daily_cap': 80}),
    ('sale_value', 'sales', 1, 'قيمة المبيعات', 'Sales value',
     'نقطة لكل 500 جنيه صافي مبيعات في اليوم', 'One point per 500 EGP of net daily sales',
     {'unit_value': Decimal('500'), 'daily_cap': 40}),
    ('sale_profit', 'sales', 1, 'ربحية المبيعات', 'Sales profitability',
     'نقطة لكل 100 جنيه مجمل ربح — مبيعات الكاش ×1.5',
     'One point per 100 EGP of gross profit — cash sales ×1.5',
     {'unit_value': Decimal('100'), 'cash_multiplier': Decimal('1.5'), 'daily_cap': 60}),
    ('return_processed', 'sales', 1, 'مرتجع مسجل', 'Return processed',
     'تسجيل مرتجع بشكل صحيح', 'A return recorded correctly', {'daily_cap': 10}),
    # ── Reservations ──
    ('reservation_created', 'reservations', 2, 'حجز جديد', 'New reservation',
     'تسجيل حجز لعميل', 'Recording a customer reservation', {'daily_cap': 30}),
    ('reservation_fulfilled', 'reservations', 5, 'حجز مُسلَّم', 'Reservation fulfilled',
     'إتمام حجز وتسليمه للعميل', 'Completing and handing over a reservation', {}),
    ('reservation_overdue', 'discipline', -2, 'حجز متأخر المتابعة', 'Overdue reservation',
     'حجز مسند إليك فات موعد متابعته ولم يُغلق (لكل يوم)',
     'A reservation assigned to you past its follow-up date and still open (per day)',
     {'daily_cap': -10}),
    # ── Demand / follow-ups ──
    ('demand_created', 'demand', 2, 'تسجيل طلب ضائع', 'Lost-sale recorded',
     'تسجيل طلب عميل غير متوفر', 'Recording a customer request we could not serve',
     {'daily_cap': 30}),
    ('demand_fulfilled', 'demand', 5, 'استرداد طلب ضائع', 'Lost-sale recovered',
     'تلبية طلب ضائع للعميل', 'Serving a lost-sale request', {}),
    ('demand_sla_breach', 'discipline', -2, 'تأخر الرد على الطلب', 'Demand SLA breach',
     'لم يتم التواصل مع العميل خلال 20 دقيقة من الإسناد',
     'Customer not contacted within 20 minutes of assignment', {'grace_hours': 0}),
    ('demand_followup_done', 'demand', 2, 'متابعة طلب منفذة', 'Demand follow-up done',
     'تنفيذ متابعة طلب في موعدها', 'Doing a demand follow-up on time', {'daily_cap': 30}),
    ('demand_followup_missed', 'discipline', -2, 'متابعة طلب فائتة', 'Demand follow-up missed',
     'متابعة طلب مسندة إليك فاتت', 'A demand follow-up assigned to you was missed',
     {'daily_cap': -10}),
    ('followup_call_done', 'demand', 2, 'متابعة عميل مزمن', 'Chronic follow-up done',
     'متابعة عميل (إعادة صرف / مزمن)', 'A customer refill / chronic follow-up', {'daily_cap': 40}),
    ('followup_missed', 'discipline', -1, 'متابعة عميل فائتة', 'Customer follow-up missed',
     'متابعة عميل مسندة إليك فاتت', 'A customer follow-up assigned to you was missed',
     {'daily_cap': -10}),
    # ── Transfers / branch requests ──
    ('transfer_request_created', 'transfers', 2, 'طلب تحويل', 'Transfer request',
     'تقديم طلب تحويل لفرع آخر', 'Submitting a transfer request to another branch',
     {'daily_cap': 20}),
    ('transfer_request_answered', 'transfers', 4, 'الرد على طلب فرع', 'Branch request answered',
     'اعتماد أو رفض طلب تحويل وارد من فرع آخر', 'Approving or rejecting another branch\'s request',
     {}),
    ('transfer_request_fast', 'transfers', 4, 'رد سريع على فرع', 'Fast reply to a branch',
     'الرد على طلب الفرع خلال ساعتين', 'Replying to a branch request within 2 hours',
     {'grace_hours': 2}),
    ('transfer_dispatched', 'transfers', 3, 'تجهيز وإرسال تحويل', 'Transfer dispatched',
     'تجهيز التحويل وإرساله مع المندوب', 'Preparing and dispatching the transfer', {}),
    ('transfer_sent_erp', 'transfers', 3, 'إذن صرف تحويل (125)', 'Transfer issue doc (125)',
     'إصدار مستند صرف تحويل في SOFTECH', 'Issuing a transfer document in SOFTECH',
     {'daily_cap': 30}),
    ('transfer_received', 'transfers', 3, 'استلام تحويل', 'Transfer received',
     'تأكيد استلام تحويل وارد', 'Confirming receipt of an incoming transfer', {'daily_cap': 30}),
    ('isr_created', 'transfers', 4, 'طلب توريد ISR', 'ISR created',
     'إنشاء طلب توريد للمركز الرئيسي', 'Creating a supply request (ISR) to HQ', {'daily_cap': 20}),
    ('isr_approved', 'transfers', 2, 'اعتماد طلب توريد', 'ISR approved',
     'اعتماد طلب توريد', 'Approving a supply request', {'daily_cap': 20}),
    # ── Inventory ──
    ('stockcount_completed', 'inventory', 15, 'جرد مكتمل', 'Stock count completed',
     'رفع نتيجة جرد حتى ظهور الفروقات', 'Uploading a count through to variances', {}),
    ('shortage_submitted', 'inventory', 3, 'قائمة نواقص', 'Shortage list submitted',
     'إرسال قائمة نواقص الفرع', 'Submitting the branch shortage list', {'daily_cap': 15}),
    # ── Tasks ──
    ('task_on_time', 'tasks', 5, 'مهمة في موعدها', 'Task done on time',
     'إنجاز مهمة قبل موعدها النهائي', 'Completing a task before its due date', {}),
    ('task_late', 'tasks', 2, 'مهمة متأخرة', 'Task done late',
     'إنجاز مهمة بعد موعدها', 'Completing a task after its due date', {}),
    ('task_overdue', 'discipline', -2, 'مهمة متأخرة مفتوحة', 'Overdue open task',
     'مهمة مسندة إليك تجاوزت موعدها ولم تُنجز (لكل يوم)',
     'A task assigned to you past its due date and not done (per day)', {'daily_cap': -10}),
    # ── Discipline ──
    ('clean_day', 'discipline', 10, 'يوم نظيف', 'Clean day',
     'يوم عمل بدون أي بند متأخر — لا شيء خلفك', 'A working day with nothing left behind', {}),
    ('streak_week', 'discipline', 25, 'أسبوع نظيف', 'Clean week',
     'مكافأة كل 7 أيام نظيفة متتالية', 'Bonus for every 7 clean days in a row', {}),
    ('abuse_flag', 'discipline', -10, 'ملاحظة مراجعة مؤكدة', 'Confirmed audit flag',
     'نشاط مشبوه تم تصعيده بعد المراجعة', 'Suspicious activity escalated after review', {}),
    # ── Monthly champion (bonuses count for XP + wallet, never for rankings) ──
    ('champion_branch', 'champion', 200, 'بطل الفرع للشهر', 'Branch champion of the month',
     'الأول بين زملاء دورك في فرعك عن الشهر', 'First among your role in your branch for the month', {}),
    ('champion_network', 'champion', 500, 'بطل الشبكة للشهر', 'Network champion of the month',
     'الأول بين كل زملاء دورك في كل الفروع عن الشهر', 'First among your role across all branches for the month', {}),
    ('podium_network', 'champion', 200, 'منصة التتويج (الثاني/الثالث)', 'Network podium (2nd/3rd)',
     'الثاني أو الثالث على الشبكة لدورك عن الشهر', 'Second or third across the network for your role', {}),
    ('champion_revoked', 'champion', 0, 'سحب لقب', 'Title revoked',
     'إلغاء لقب بطل بقرار إداري مكتوب السبب — تُخصم مكافأته', 'A champion title withdrawn by management with a reason — its bonus is reversed', {}),
    ('manual_award', 'manual', 0, 'تقدير يدوي', 'Manual recognition',
     'نقاط يمنحها أو يخصمها المدير بسبب مكتوب', 'Points given or deducted by a manager with a reason',
     {}),
]

LEVELS = [
    (1, 0,      'مبتدئ',            'Rookie',          '🌱', 'slate'),
    (2, 300,    'نشيط',             'Active',          '⚡', 'sky'),
    (3, 1000,   'متمكّن',           'Skilled',         '🔧', 'teal'),
    (4, 2500,   'محترف',            'Professional',    '🎯', 'emerald'),
    (5, 5000,   'خبير',             'Expert',          '🧠', 'lime'),
    (6, 9000,   'نجم الفرع',        'Branch star',     '⭐', 'amber'),
    (7, 15000,  'قائد',             'Leader',          '🦁', 'orange'),
    (8, 24000,  'نخبة',             'Elite',           '💎', 'violet'),
    (9, 36000,  'بطل',              'Champion',        '🏆', 'rose'),
    (10, 52000, 'أسطورة الرزيقي',   'ElRezeiky legend', '👑', 'yellow'),
]

# key, icon, criteria, rule_key, threshold, name_ar, name_en, desc_ar, desc_en
BADGES = [
    ('first_sale', '🛒', 'rule_count', 'sale_invoice', 1, 'أول بيعة', 'First sale',
     'أول فاتورة بيع', 'Your first sale invoice'),
    ('sales_100', '🧾', 'rule_count', 'sale_invoice', 100, 'مئة فاتورة', '100 invoices',
     '100 فاتورة بيع', '100 sale invoices'),
    ('sales_1000', '💯', 'rule_count', 'sale_invoice', 1000, 'ألف فاتورة', '1,000 invoices',
     '1000 فاتورة بيع', '1,000 sale invoices'),
    ('reservations_50', '📋', 'rule_count', 'reservation_fulfilled', 50, 'وفيّ بالوعد',
     'Promise keeper', '50 حجزاً مُسلَّماً', '50 reservations fulfilled'),
    ('demand_25', '🔁', 'rule_count', 'demand_fulfilled', 25, 'منقذ المبيعات', 'Sales rescuer',
     'استرداد 25 طلباً ضائعاً', '25 lost sales recovered'),
    ('branch_friend', '🤝', 'rule_count', 'transfer_request_fast', 25, 'صديق الفروع',
     'Branch friend', 'الرد السريع على 25 طلب فرع', '25 fast replies to branch requests'),
    ('stock_guard', '📦', 'rule_count', 'stockcount_completed', 10, 'حارس المخزون',
     'Stock guardian', '10 عمليات جرد مكتملة', '10 completed stock counts'),
    ('task_master', '✅', 'rule_count', 'task_on_time', 50, 'سيد المهام', 'Task master',
     '50 مهمة في موعدها', '50 tasks done on time'),
    ('streak_7', '🔥', 'streak', '', 7, 'أسبوع بلا تأخير', 'Week without delays',
     '7 أيام نظيفة متتالية', '7 clean days in a row'),
    ('streak_30', '🌟', 'streak', '', 30, 'شهر بلا تأخير', 'Month without delays',
     '30 يوماً نظيفاً متتالياً', '30 clean days in a row'),
    ('xp_10k', '🚀', 'xp', '', 10000, 'عشرة آلاف نقطة', '10K XP',
     'تجاوز 10,000 نقطة خبرة', 'Passing 10,000 XP'),
    ('champ_branch_1', '👑', 'champion', 'branch', 1, 'بطل الشهر', 'Champion of the month',
     'بطل فرعك لشهر', 'Branch champion for a month'),
    ('champ_branch_3', '🏅', 'champion', 'branch', 3, 'بطل متكرر', 'Repeat champion',
     'بطل فرعك 3 أشهر', 'Branch champion three times'),
    ('champ_network_1', '🌍', 'champion', 'network', 1, 'على منصة الشبكة', 'Network podium',
     'من أفضل 3 على الشبكة لشهر', 'Network top 3 for a month'),
]


# Reward catalog. Rewards that cost the company money or working time start INACTIVE —
# management sets the price in points and switches them on (/gamification → settings).
# icon, category, cost, active, limit/month, min_level, name_ar, name_en, desc_ar, desc_en
REWARDS = [
    ('📜', 'recognition', 500, True, None, 1, 'شهادة تقدير', 'Certificate of appreciation',
     'شهادة تقدير موقعة من الإدارة', 'A certificate signed by management'),
    ('🌟', 'recognition', 1000, True, 1, 2, 'موظف الأسبوع على لوحة الإعلانات',
     'Employee of the week spotlight', 'صورتك وإنجازك في إعلانات الشركة لمدة أسبوع',
     'Your photo and achievement in company announcements for a week'),
    ('🔄', 'perk', 1200, True, 1, 2, 'اختيار ورديتك المفضلة لأسبوع', 'Pick your preferred shift for a week',
     'حسب ما يسمح به جدول الفرع', 'Subject to the branch schedule'),
    ('🍽️', 'perk', 800, False, 2, 1, 'وجبة غداء على الشركة', 'Lunch on the company',
     'وجبة غداء من الشركة', 'A lunch paid by the company'),
    ('🕐', 'time_off', 1500, False, 1, 3, 'نصف يوم إجازة', 'Half day off',
     'نصف يوم إجازة مدفوعة بالتنسيق مع مدير الفرع', 'A paid half day off, agreed with the branch manager'),
    ('🏖️', 'time_off', 3000, False, 1, 4, 'يوم إجازة إضافي', 'Extra day off',
     'يوم إجازة مدفوع إضافي بالتنسيق مع مدير الفرع', 'An extra paid day off, agreed with the branch manager'),
    ('🎟️', 'voucher', 2500, False, 1, 3, 'قسيمة شراء 200 جنيه', '200 EGP shopping voucher',
     'قسيمة شراء من متجر تختاره الإدارة', 'A shopping voucher from a store chosen by management'),
    ('🎓', 'development', 4000, False, None, 5, 'دورة تدريبية', 'Training course',
     'دورة تدريبية مهنية تختارها مع الإدارة', 'A professional training course chosen with management'),
]


def ensure_rewards():
    """Seed the reward catalog once (only when it is completely empty)."""
    from .models import Reward
    if Reward.objects.exists():
        return 0
    for i, (icon, cat, cost, active, lim, lvl, nar, nen, dar, den) in enumerate(REWARDS):
        Reward.objects.create(icon=icon, category=cat, cost=cost, is_active=active,
                              limit_per_month=lim, min_level=lvl, name_ar=nar, name_en=nen,
                              desc_ar=dar, desc_en=den, sort=i * 10)
    return len(REWARDS)


def ensure_defaults(reset=False):
    from .models import Badge, Level, PointRule

    created = 0
    for i, (key, cat, pts, nar, nen, dar, den, extra) in enumerate(RULES):
        values = dict(category=cat, points=pts, name_ar=nar, name_en=nen,
                      desc_ar=dar, desc_en=den, sort=i * 10,
                      unit_value=extra.get('unit_value'),
                      cash_multiplier=extra.get('cash_multiplier', Decimal('1')),
                      daily_cap=extra.get('daily_cap'),
                      grace_hours=extra.get('grace_hours'))
        if reset:
            PointRule.objects.update_or_create(key=key, defaults=values)
        else:
            created += PointRule.objects.get_or_create(key=key, defaults=values)[1]
    for num, xp, tar, ten, icon, color in LEVELS:
        values = dict(min_xp=xp, title_ar=tar, title_en=ten, icon=icon, color=color)
        if reset:
            Level.objects.update_or_create(number=num, defaults=values)
        elif not Level.objects.filter(number=num).exists() and \
                not Level.objects.filter(min_xp=xp).exists():
            Level.objects.create(number=num, **values)
            created += 1
    for i, (key, icon, crit, rk, th, nar, nen, dar, den) in enumerate(BADGES):
        values = dict(icon=icon, criteria=crit, rule_key=rk, threshold=th, name_ar=nar,
                      name_en=nen, desc_ar=dar, desc_en=den, sort=i * 10)
        if reset:
            Badge.objects.update_or_create(key=key, defaults=values)
        else:
            created += Badge.objects.get_or_create(key=key, defaults=values)[1]
    return created
