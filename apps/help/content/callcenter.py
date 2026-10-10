from . import T

MODULE = {
    'key': 'callcenter', 'group': 'callcenter', 'icon': '📞',
    'title': T('مركز الاتصال والحالات', 'Call center & cases'),
    'summary': T(
        'عمل الكول سنتر اليومي: البحث برقم المتصل يفتح ملف العميل كاملاً (الشريحة، القيمة، الحالات والطلبات المفتوحة)، تسجيل المكالمة وغرضها ونتيجتها، '
        'فتح «حالة» لأي شكوى أو طلب يحتاج متابعة حتى الحل، وجدولة متابعة. ومعه لوحة المكالمات الحية من السنترال (Issabel)، ولوحة جودة المكالمات للمشرفين '
        'مع تقييم المكالمات وتحليل مشاعر العملاء بالذكاء الاصطناعي.',
        'The call center\'s daily work: searching the caller\'s number opens the full customer profile (segment, value, open cases and requests), logging the call, its purpose and outcome, '
        'opening a "case" for any complaint or request that needs follow-up until resolved, and scheduling a follow-up. Alongside: the live calls board from the PBX (Issabel), and a call-quality board for supervisors '
        'with call scoring and AI customer-sentiment analysis.'),
    'workflows': [{
        'title': T('مراحل حالة العميل', 'Customer case stages'),
        'model': 'callcenter.CustomerCase', 'field': 'status',
        'states': [
            {'key': 'open', 'label': T('مفتوحة', 'Open'), 'desc': T('سُجّلت ولم يبدأ العمل عليها.', 'Recorded, work not started.'), 'next': ['working', 'escalated']},
            {'key': 'working', 'label': T('قيد المعالجة', 'Working'), 'desc': T('موظف يعمل على حلها («بدء المعالجة»).', 'An agent is working on it ("Start working").'), 'next': ['waiting', 'escalated', 'resolved']},
            {'key': 'waiting', 'label': T('انتظار العميل', 'Waiting for customer'), 'desc': T('ننتظر رد العميل أو معلومة منه.', 'Waiting for the customer\'s reply or information.'), 'next': ['working', 'resolved']},
            {'key': 'escalated', 'label': T('مُصعَّدة', 'Escalated'), 'desc': T('رُفعت لمشرف (أو تجاوزت موعد SLA).', 'Raised to a supervisor (or past its SLA).'), 'next': ['working', 'resolved']},
            {'key': 'resolved', 'label': T('محلولة', 'Resolved'), 'desc': T('حُلّت مع شرح الحل والسبب الجذري، ويمكن تسجيل تقييم العميل (CSAT).', 'Resolved with the solution and root cause; the customer rating (CSAT) can be recorded.'), 'next': ['closed']},
            {'key': 'closed', 'label': T('مغلقة', 'Closed'), 'desc': T('أُغلقت نهائياً.', 'Closed for good.')},
        ],
    }],
}

SCREENS = [
    {
        'key': 'callcenter.operator',
        'routes': ['/callcenter'],
        'title': T('شاشة موظف الكول سنتر', 'Call center operator screen'),
        'summary': T('شاشة العمل أثناء المكالمة: ابحث برقم المتصل ← اختر العميل (لو أكثر من عميل بنفس الرقم) ← ملفه الكامل ← سجّل المكالمة وغرضها ← افتح حالة أو اجدول متابعة.',
                     'The screen to work during a call: search the caller\'s number → choose the customer (if several share the number) → their full profile → log the call and its purpose → open a case or schedule a follow-up.'),
        'audience': T('موظفو الكول سنتر والمشرفون.', 'Call center agents and supervisors.'),
        'tabs': [
            {'key': 'operator', 'title': T('📱 موظف', '📱 Operator'),
             'body': T('البحث وملف العميل وتسجيل المكالمة (الغرض: استفسار حجز، متابعة توصيل، إعادة صرف، شكوى، طلب جديد، تحديث عنوان، متابعة مزمن، صنف غير متوفر…)، فتح حالة، جدولة متابعة، وزر «تلخيص بالذكاء الاصطناعي» بعد الحفظ.',
                       'Search, customer profile and call logging (purpose: reservation inquiry, delivery follow-up, refill, complaint, new order, address update, chronic follow-up, item unavailable…), open a case, schedule a follow-up, and the "AI summarize" button after saving.')},
            {'key': 'manager', 'title': T('📊 مدير', '📊 Manager'),
             'body': T('مؤشرات الفريق: مكالمات 30 يوماً واليوم، انتظار المعاودة، متوسط المدة، الحالات المفتوحة والمُصعَّدة والمحلولة اليوم، متوسط CSAT، تحليل المشاعر، وتوزيع الأغراض وتصنيف الحالات.',
                       'Team KPIs: calls in 30 days and today, pending callbacks, average duration, open/escalated/resolved-today cases, average CSAT, sentiment analysis, and purpose and case-type distributions.')},
        ],
        'steps': [
            T('أثناء المكالمة اكتب الرقم؛ لو العميل جديد سجّله.', 'During the call type the number; register the customer if new.'),
            T('سجّل الغرض والنتيجة (تمت الإجابة، لا رد، مشغول، بريد صوتي، طلب معاودة) والملاحظات.', 'Record the purpose and result (answered, no answer, busy, voicemail, callback requested) and notes.'),
            T('شكوى أو طلب يحتاج متابعة؟ «فتح حالة جديدة» (التصنيف، الأولوية، العنوان، الوصف).', 'A complaint or request needing follow-up? "Open new case" (type, priority, title, description).'),
            T('«جدولة متابعة» لتذكير بموعد (تذكير إعادة صرف، متابعة مزمن، متابعة طلب، مهمة مخصصة).', '"Schedule follow-up" for a reminder (refill reminder, chronic follow-up, request follow-up, custom task).'),
        ],
        'tips': [T('«مخاطر الشكوى» تظهر للعملاء ذوي التاريخ السلبي — تعامل بعناية.', '"Complaint risk" shows for customers with a negative history — handle with care.')],
        'related': ['callcenter.cases', 'omni.inbox', 'customers.detail'],
        'workflows': [],
        'tour': [
            {'target': 'callcenter-operator-mode', 'text': T('اختار البحث بالهاتف أو بالاسم / PIC.',
                                              'Choose search by phone or by name / PIC.')},
            {'target': 'callcenter-operator-phone', 'text': T('اكتب رقم المتصل.',
                                              'Type the caller\'s number.')},
            {'target': 'callcenter-operator-search', 'text': T('«🔍 بحث» يجيب ملف العميل.',
                                              '"🔍 Search" brings up the customer\'s profile.')},
            {'target': 'callcenter-operator-profile', 'text': T('ملف العميل: بياناته ومشترياته وحجوزاته.',
                                              'The customer profile: details, purchases and reservations.')},
            {'target': 'callcenter-operator-log', 'text': T('سجّل سبب المكالمة ونتيجتها.',
                                              'Record the call\'s reason and outcome.')},
            {'target': 'callcenter-operator-save', 'text': T('«💾 حفظ المكالمة» — لازم كل مكالمة تتحفظ.',
                                              '"💾 Save call" — every call must be saved.')},
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'callcenter.cases',
        'routes': ['/callcenter/cases'],
        'title': T('إدارة حالات العملاء', 'Customer case management'),
        'summary': T('كل الحالات (شكوى، استفسار، طلب، بيعة مفقودة، توصيل، دعم، إرجاع/استبدال) بحالاتها وأولويتها وموعد SLA، مع سجل الأحداث والملاحظات والمرفقات والرسائل الصوتية، وحل الحالة وتقييم العميل.',
                     'All cases (complaint, inquiry, request, lost sale, delivery, support, return/exchange) with status, priority and SLA, the event log, notes, attachments and voice notes, resolving the case and the customer rating.'),
        'audience': T('الكول سنتر والمشرفون.', 'Call center and supervisors.'),
        'steps': [
            T('صفِّ بالحالة والتصنيف، وابدأ بالمُصعَّدة وما تجاوز SLA.', 'Filter by status and type, and start with escalated and past-SLA cases.'),
            T('افتح الحالة ← «بدء المعالجة» ← سجّل كل خطوة في الملاحظات (@ لذكر زميل).', 'Open the case → "Start working" → log each step in notes (@ to mention a colleague).'),
            T('«حل الحالة» واشرح الحل والسبب الجذري، ثم «إغلاق».', '"Resolve case" with the solution and root cause, then "Close".'),
        ],
        'related': ['callcenter.operator', 'callcenter.analytics'],
        'updated': '2026-10-10',
    },
    {
        'key': 'callcenter.analytics',
        'routes': ['/callcenter/analytics'],
        'title': T('جودة الاتصال (لوحة المشرف)', 'Call quality (supervisor board)'),
        'summary': T('لوحة المشرف والجودة للكول سنتر.', 'The supervisor and QA board for the call center.'),
        'audience': T('المدير والمشرفون ومدير الجودة.', 'Admin, supervisors and the quality manager.'),
        'tabs': [
            {'key': 'kpi', 'title': T('📊 مؤشرات الأداء', '📊 KPIs'), 'body': T('مكالمات اليوم، نسبة الإجابة، متوسط المدة، متوسط الجودة، المعاودات المتأخرة، توزيع الأغراض وتحليل المشاعر.', 'Calls today, answer rate, average duration, average quality, overdue callbacks, purpose distribution and sentiment.')},
            {'key': 'calls', 'title': T('📞 سجل المكالمات', '📞 Call log'), 'body': T('بحث في المكالمات وتقييم جودة كل مكالمة من 100: الترحيب والتعريف (20)، حل المشكلة (30)، وضوح التواصل (25)، دقة المعلومات (25).', 'Search calls and score each call out of 100: greeting (20), problem resolution (30), communication clarity (25), information accuracy (25).')},
            {'key': 'cases', 'title': T('📋 لوحة الحالات', '📋 Cases board'), 'body': T('مؤشرات الحالات (مفتوحة، مُصعَّدة، حُلّت اليوم، متوسط زمن الحل) وقائمتها.', 'Case KPIs (open, escalated, resolved today, average resolution time) and the list.')},
            {'key': 'agents', 'title': T('👤 أداء المندوبين', '👤 Agent performance'), 'body': T('حجم مكالمات كل موظف وترتيبه في الجودة خلال 30 يوماً.', 'Each agent\'s call volume and quality ranking over 30 days.')},
        ],
        'workflows': [],
        'related': ['omni.wallboard'],
        'updated': '2026-10-10',
    },
    {
        'key': 'callcenter.pbx',
        'routes': ['/pbx/live'],
        'title': T('المكالمات الحية', 'Live calls'),
        'summary': T('لحظياً من السنترال: المكالمات النشطة (رنين، متصل، في الطابور) وسجل المكالمات الأخيرة. عند مكالمة واردة تظهر بطاقة العميل: الاسم، الشريحة، آخر المشتريات، القسائم والحالات المفتوحة، ورصيد النقاط.',
                     'Live from the PBX: active calls (ringing, connected, queued) and recent calls. On an incoming call the customer card shows: name, segment, last purchases, open vouchers and cases, and points balance.'),
        'audience': T('الكول سنتر والمشرفون.', 'Call center and supervisors.'),
        'tips': [T('لو الحالة «غير متصل» أعد تحميل الصفحة؛ البيانات تصل لحظياً عبر اتصال مباشر.', 'If the status shows "disconnected", reload the page; data arrives live over a direct connection.')],
        'workflows': [],
        'related': ['callcenter.operator', 'omni.wallboard'],
        'updated': '2026-10-10',
    },
]
