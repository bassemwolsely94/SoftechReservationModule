from . import T

CHANGE_NOTE = T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour')

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
    'flows': [
        {
            'key': 'call',
            'title': T('المكالمة ← حالة ← متابعة', 'A call → case → follow-up'),
            'summary': T('استقبال المكالمة وتسجيلها، وفتح حالة للشكوى، وجدولة متابعة للعميل.',
                         'Taking and logging a call, opening a case for a complaint, and scheduling a follow-up for the customer.'),
            'roles': ['admin', 'call_center', 'supervisor'],
            'steps': [
                {'target': 'nav-callcenter', 'nav': '/callcenter',
                 'text': T('شاشة المكالمات من القائمة.',
                           'The calls screen from the menu.'),
                 'more': T('دي الشاشة اللي بتكون مفتوحة طول الشيفت: كل مكالمة بتبدأ وتخلص هنا.\n'
                           '• فوق فيها «📋 طابور انتظاري» بالحالات المسندة ليك، وتحتها البحث وملف العميل وتسجيل المكالمة.',
                           'This is the screen kept open all shift: every call starts and ends here.\n'
                           '• At the top is "📋 My queue" with the cases assigned to you; below are search, the customer profile and call logging.')},
                {'target': 'callcenter-operator-phone', 'route': '/callcenter',
                 'text': T('اكتب رقم المتصل…',
                           'Type the caller\'s number…'),
                 'more': T('اكتب الرقم زي ما ظاهر عندك (010…). البحث مش بيشتغل غير لما الرقم يبقى 8 أرقام على الأقل.\n'
                           '• Enter في الخانة بيعمل بحث على طول.\n'
                           '• لو المتصل مش فاكر رقمه، فيه بحث بالاسم أو PIC فوق.',
                           'Type the number as shown (010…). Search only works once the number has at least 8 digits.\n'
                           '• Enter in the box searches straight away.\n'
                           '• If the caller does not remember their number, there is a name or PIC search above.')},
                {'target': 'callcenter-operator-search', 'route': '/callcenter',
                 'text': T('…و«🔍 بحث» يجيب ملفه.',
                           '…and "🔍 Search" brings up their profile.'),
                 'more': T('لو أكتر من عميل بنفس الرقم بيظهر اختيار العميل الأول.\n'
                           '• لو الرقم مش مسجّل بيظهر «عميل جديد — لا توجد بيانات سابقة».\n'
                           '• «مسح» جنبه بيفضّي الشاشة للمكالمة اللي بعدها.',
                           'If several customers share the number, you pick the customer first.\n'
                           '• If the number is not registered, "New customer — no previous data" appears.\n'
                           '• "Clear" next to it empties the screen for the next call.')},
                {'target': 'callcenter-operator-profile', 'route': '/callcenter',
                 'text': T('ملف العميل: بياناته ومشترياته وحجوزاته ومهام المتابعة المفتوحة.',
                           'The customer profile: details, purchases, reservations and open follow-up tasks.'),
                 'more': T('قبل ما ترد بص على: الحالات المفتوحة، الحجوزات، الطلبات المعلقة، وآخر المكالمات.\n'
                           '• لو شريط «مخاطر الشكوى» عالي (أحمر من 60) يبقى تاريخ العميل سلبي — اتعامل بحرص.\n'
                           '• تاريخ المشتريات بيغطي آخر 365 يوم.',
                           'Before answering, look at: open cases, reservations, pending requests and recent calls.\n'
                           '• If the "Complaint risk" bar is high (red from 60), the customer has a negative history — handle with care.\n'
                           '• Purchase history covers the last 365 days.')},
                {'target': 'callcenter-operator-purpose', 'route': '/callcenter',
                 'text': T('«الغرض» من المكالمة.',
                           'The call\'s "Purpose".'),
                 'more': T('اختار السبب الحقيقي: استفسار حجز، متابعة توصيل، إعادة صرف، شكوى، طلب جديد، تحديث عنوان، متابعة مزمن، صنف غير متوفر، أو استفسار عام.\n'
                           '• الغرض ده بيدخل في تقارير المدير وتوزيع الأغراض.',
                           'Choose the real reason: reservation inquiry, delivery follow-up, refill, complaint, new order, address update, chronic follow-up, item unavailable or general inquiry.\n'
                           '• The purpose feeds the manager\'s reports and purpose distribution.')},
                {'target': 'callcenter-operator-outcome', 'route': '/callcenter',
                 'text': T('نتيجة المكالمة: أجاب، لا رد، مشغول، معاودة.',
                           'The call outcome: answered, no answer, busy, call back.'),
                 'more': T('جنبها «الاتجاه»: واردة، صادرة، أو واتساب.\n'
                           '• «معاودة» معناها لازم نكلّمه تاني — المعاودات المتأخرة بتظهر للمشرف.\n'
                           '• تحتها «ملخص سريع» و«ملاحظات تفصيلية».',
                           'Next to it is "Direction": inbound, outbound or WhatsApp.\n'
                           '• "Call back" means we must call again — overdue callbacks show to the supervisor.\n'
                           '• Below are "Quick summary" and "Detailed notes".')},
                {'target': 'callcenter-operator-case', 'route': '/callcenter',
                 'text': T('شكوى أو طلب محتاج متابعة؟ «🗂️ فتح حالة جديدة».',
                           'A complaint or request that needs handling? "🗂️ Open a new case".'),
                 'more': T('بيفتح نافذة: التصنيف، الأولوية (منخفضة لحد عاجلة)، «عنوان الحالة» إجباري، والوصف.\n'
                           '• بعد «🗂️ فتح الحالة» بيظهر «✅ تم فتح الحالة» برقمها ورابط «عرض الحالات».\n'
                           '• متاح قبل حفظ المكالمة وبعدها.',
                           'Opens a window: category, priority (low to urgent), "Case title" (required) and description.\n'
                           '• After "🗂️ Open case", "✅ Case opened" shows with its number and a "View cases" link.\n'
                           '• Available before and after saving the call.')},
                {'target': 'callcenter-operator-followup', 'route': '/callcenter',
                 'text': T('محتاج تكلّمه تاني؟ «🔔 جدولة متابعة»: نوع المهمة وتاريخ الاستحقاق وموعد التذكير.',
                           'Need to call again? "🔔 Schedule follow-up": task type, due date and reminder time.'),
                 'more': T('الأنواع: مهمة مخصصة، تذكير إعادة صرف، متابعة مريض مزمن، متابعة طلب عميل.\n'
                           '• «تاريخ الاستحقاق» إجباري؛ «موعد التذكير» اختياري وبيبعتلك إشعار في وقته.\n'
                           '• المهمة بتظهر بعدين في «متابعة المزمن».',
                           'Types: custom task, refill reminder, chronic patient follow-up, customer request follow-up.\n'
                           '• "Due date" is required; "Reminder time" is optional and sends you a notification at that time.\n'
                           '• The task then shows in "Chronic follow-up".')},
                {'target': 'callcenter-operator-save', 'route': '/callcenter',
                 'text': T('«💾 حفظ المكالمة» — كل مكالمة لازم تتحفظ. (في الجولة مش هنحفظ.)',
                           '"💾 Save call" — every call must be saved. (In this tour we will not save.)'),
                 'more': T('بعد الحفظ بيظهر «✅ تم التسجيل بنجاح» ورقم المكالمة، ومعاه: فتح حالة، جدولة متابعة، و«🤖 تلخيص AI».\n'
                           '• لو الغرض «شكوى» بيفكّرك «تذكر فتح حالة بعد الحفظ».\n'
                           '• «📞 تسجيل مكالمة أخرى» يجهّز للي بعدها.',
                           'After saving, "✅ Logged successfully" shows with the call number, plus: open case, schedule follow-up and "🤖 AI summary".\n'
                           '• If the purpose is "Complaint", it reminds you to open a case after saving.\n'
                           '• "📞 Log another call" gets ready for the next one.')},
                {'target': 'callcenter-cases-list', 'route': '/callcenter/cases',
                 'text': T('الحالات كلها هنا.',
                           'All the cases are here.'),
                 'more': T('دي شاشة «إدارة الحالات»: كل حالة بحالتها وأولويتها وموعد SLA.\n'
                           '• «⏰ SLA!» بالأحمر = الحالة عدّت وقتها — ابدأ بيها.\n'
                           '• فلتر الحالة فوق يخليك تشوف المفتوحة بس.',
                           'This is "Case management": each case with its status, priority and SLA time.\n'
                           '• "⏰ SLA!" in red = the case is past its time — start with it.\n'
                           '• The status filter above lets you see open ones only.')},
                {'target': 'callcenter-cases-card', 'route': '/callcenter/cases',
                 'text': T('اضغط على حالة تفتح تفاصيلها جنب القائمة.',
                           'Click a case to open its details beside the list.'),
                 'more': T('التفاصيل فيها سجل كل اللي حصل، والملاحظات (اكتب @ عشان تنادي زميل)، والمرفقات والرسائل الصوتية.\n'
                           '• سجّل كل خطوة في الملاحظات عشان أي حد يكمّل من بعدك.',
                           'The details hold the log of everything that happened, notes (type @ to mention a colleague), attachments and voice notes.\n'
                           '• Log every step in the notes so anyone can carry on after you.')},
                {'target': 'callcenter-cases-actions', 'route': '/callcenter/cases',
                 'text': T('«⚙️ بدء المعالجة» ← «✅ حل الحالة» ← «🔒 إغلاق».',
                           '"⚙️ Start working" → "✅ Resolve" → "🔒 Close".'),
                 'more': T('• «بدء المعالجة» بيظهر للحالة المفتوحة وبيسندها ليك.\n'
                           '• «حل الحالة» بيطلب شرح طريقة الحل وبعدين «✅ تأكيد الحل».\n'
                           '• بعد الحل: «إغلاق»، وتقدر تسجّل تقييم العميل CSAT من 1 لـ 5.',
                           '• "Start working" shows for an open case and assigns it to you.\n'
                           '• "Resolve" asks you to explain the solution, then "✅ Confirm resolution".\n'
                           '• After resolving: "Close", and you can record the customer\'s CSAT rating from 1 to 5.')},
                {'target': 'nav-followups', 'nav': '/followups',
                 'text': T('المتابعات: «العمليات» ← «متابعة المزمن».',
                           'Follow-ups: "Operations" → "Chronic follow-up".'),
                 'more': T('هنا بتلاقي مهام المتابعة اللي اتجدولت من المكالمات ومن تذكيرات الصرف.\n'
                           '• ده المكان اللي بتشتغل منه على المكالمات الصادرة.',
                           'Here you find the follow-up tasks scheduled from calls and from refill reminders.\n'
                           '• This is where you work your outbound calls from.')},
                {'target': 'followups-tasks-groups', 'route': '/followups',
                 'text': T('مهام المتابعة مجمّعة بالعميل — افتح عميل.',
                           'Follow-up tasks grouped by customer — expand a customer.'),
                 'more': T('كل عميل بيظهر مرة واحدة ومعاه كل أصنافه المستحقة، عشان تكلّمه مكالمة واحدة عن كله.\n'
                           '• افتح العميل تشوف كل صنف وتاريخ استحقاقه.',
                           'Each customer appears once with all their due items, so one call covers everything.\n'
                           '• Expand the customer to see each item and its due date.')},
                {'target': 'followups-tasks-group-log', 'route': '/followups',
                 'text': T('«تسجيل» نتيجة كل صنف بعد ما تكلّمه.',
                           '"Log" the outcome for each item after the call.'),
                 'more': T('الزر بيظهر للمهام النشطة بس، وبيفتح تسجيل نتيجة الصنف ده.\n'
                           '• سجّل النتيجة الحقيقية حتى لو العميل مارد — ده اللي بيحدد المتابعة الجاية.',
                           'The button shows for active tasks only and opens the outcome entry for that item.\n'
                           '• Record the real outcome even if the customer did not answer — it decides the next follow-up.')},
            ],
        },
    ],
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
            {'target': 'callcenter-operator-mode', 'text': T('اختار «📞 بحث بالهاتف» أو «👤 بحث بالاسم / PIC».',
                                              'Choose "📞 Search by phone" or "👤 Search by name / PIC".'),
             'more': T('العادي البحث بالهاتف وقت المكالمة.\n'
                       '• لو المتصل من رقم تاني، ابحث بالاسم أو كود PIC؛ أول ما تختار العميل ملفه بيتحمّل برقم تليفونه.',
                       'Normally you search by phone during the call.\n'
                       '• If the caller uses another number, search by name or PIC code; once you pick the customer, their profile loads by their phone number.')},
            {'target': 'callcenter-operator-phone', 'text': T('اكتب رقم المتصل.',
                                              'Type the caller\'s number.'),
             'more': T('البحث مش بيشتغل غير لما الرقم يبقى 8 أرقام على الأقل.\n'
                       '• Enter في الخانة بيعمل بحث على طول.\n'
                       '• «مسح» جنبه بيفضّي الشاشة للمكالمة الجاية.',
                       'Search only works once the number has at least 8 digits.\n'
                       '• Enter in the box searches straight away.\n'
                       '• "Clear" next to it empties the screen for the next call.')},
            {'target': 'callcenter-operator-search', 'text': T('«🔍 بحث» يجيب ملف العميل.',
                                              '"🔍 Search" brings up the customer\'s profile.'),
             'more': T('لو أكتر من عميل بنفس الرقم بتختار العميل الأول، أو تسجّل المكالمة كـ «👤 متصل غير محدد».\n'
                       '• لو الرقم مش مسجّل بيظهر «عميل جديد — لا توجد بيانات سابقة».',
                       'If several customers share the number you pick one first, or log the call as "👤 Unknown caller".\n'
                       '• If the number is not registered, "New customer — no previous data" appears.')},
            {'target': 'callcenter-operator-profile', 'text': T('ملف العميل: بياناته وحالاته ومشترياته وحجوزاته ومتابعاته.',
                                              'The customer profile: details, cases, purchases, reservations and follow-ups.'),
             'more': T('فيه: الشريحة والقيمة وآخر زيارة، عنوان التوصيل وزر واتساب، الحالات المفتوحة، مشتريات آخر 365 يوم، مهام المتابعة، الحجوزات، الطلبات المعلقة، وآخر المكالمات.\n'
                       '• شريط «مخاطر الشكوى» العالي (أحمر من 60) = تاريخ سلبي، اتعامل بحرص.',
                       'It holds: segment, value and last visit, delivery address and a WhatsApp button, open cases, last-365-day purchases, follow-up tasks, reservations, pending requests and recent calls.\n'
                       '• A high "Complaint risk" bar (red from 60) = negative history; handle with care.')},
            {'target': 'callcenter-operator-log', 'text': T('سجّل الغرض والاتجاه والنتيجة والملخص.',
                                              'Record the purpose, direction, outcome and summary.'),
             'more': T('• «الغرض»: سبب المكالمة (حجز، توصيل، إعادة صرف، شكوى…).\n'
                       '• «الاتجاه»: واردة، صادرة، أو واتساب.\n'
                       '• «الحالة»: أجاب، لا رد، مشغول، معاودة.\n'
                       '• «ملخص سريع» و«ملاحظات تفصيلية» لأي حد يقرا بعدك.',
                       '• "Purpose": why they called (reservation, delivery, refill, complaint…).\n'
                       '• "Direction": inbound, outbound or WhatsApp.\n'
                       '• "Status": answered, no answer, busy, call back.\n'
                       '• "Quick summary" and "Detailed notes" for whoever reads after you.')},
            {'target': 'callcenter-operator-save', 'text': T('«💾 حفظ المكالمة» — لازم كل مكالمة تتحفظ.',
                                              '"💾 Save call" — every call must be saved.'),
             'more': T('الزر بيشتغل بعد البحث برقم. بعد الحفظ بيظهر رقم المكالمة، ومعاه: «🗂️ فتح حالة»، «🔔 جدولة متابعة»، و«🤖 تلخيص AI».\n'
                       '• لو الغرض «شكوى» بيفكّرك تفتح حالة بعد الحفظ.\n'
                       '• «📞 تسجيل مكالمة أخرى» يجهّز للي بعدها.',
                       'The button works after searching a number. After saving, the call number shows with "🗂️ Open case", "🔔 Schedule follow-up" and "🤖 AI summary".\n'
                       '• If the purpose is "Complaint", it reminds you to open a case after saving.\n'
                       '• "📞 Log another call" gets ready for the next one.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
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
        'tour': [
            {'target': 'callcenter-cases-new', 'text': T('«+ حالة جديدة» لشكوى أو طلب محتاج متابعة.',
                                              '"+ New case" for a complaint or request that needs follow-up.'),
             'more': T('بيفتح نافذة: ابحث عن العميل برقم أو اسم، وبعدين التصنيف والأولوية و«عنوان الحالة» (إجباري) والوصف.\n'
                       '• الزر ظاهر للمدير والمشرف والكول سنتر والجودة.\n'
                       '• أثناء مكالمة، الأسهل تفتح الحالة من شاشة الموظف.',
                       'Opens a window: find the customer by phone or name, then category, priority, "Case title" (required) and description.\n'
                       '• The button shows for admins, supervisors, call center and quality.\n'
                       '• During a call, it is easier to open the case from the operator screen.')},
            {'target': 'callcenter-cases-filters', 'text': T('ابحث وفلتر بالحالة والتصنيف والترتيب.',
                                              'Search and filter by status, category and sort.'),
             'more': T('الحالة: مفتوحة، قيد المعالجة، انتظار، مُصعَّدة، محلولة، مغلقة.\n'
                       '• الترتيب: الأحدث، الأقدم، «SLA أقرب»، أو الأولوية.\n'
                       '• ابدأ بالمُصعَّدة و«SLA أقرب».',
                       'Status: open, working, waiting, escalated, resolved, closed.\n'
                       '• Sort: newest, oldest, "nearest SLA" or priority.\n'
                       '• Start with escalated and "nearest SLA".')},
            {'target': 'callcenter-cases-list', 'text': T('الحالات بحالتها وأولويتها.',
                                              'The cases with their status and priority.'),
             'more': T('كل كارت: رقم الحالة والعنوان والحالة والأولوية والعميل.\n'
                       '• «⏰ SLA!» بالأحمر = الحالة عدّت وقتها المسموح.\n'
                       '• تحت فيه «السابق» و«التالي» للصفحات.',
                       'Each card: case number, title, status, priority and customer.\n'
                       '• "⏰ SLA!" in red = the case is past its allowed time.\n'
                       '• At the bottom are "Previous" and "Next" for pages.')},
            {'target': 'callcenter-cases-card', 'text': T('اضغط على حالة عشان تفتح تفاصيلها جنب القائمة.',
                                              'Click a case to open its details beside the list.'),
             'more': T('التفاصيل بتفتح على الجنب من غير ما تسيب القائمة.\n'
                       '• على الموبايل التفاصيل بتاخد الشاشة كلها.',
                       'The details open on the side without leaving the list.\n'
                       '• On a phone the details take the whole screen.')},
            {'target': 'callcenter-cases-detail', 'text': T('تفاصيل الحالة وسجلها وملاحظاتها.',
                                              'The case details, history and notes.'),
             'more': T('السجل بيوضح كل حاجة حصلت ومين عملها.\n'
                       '• اكتب ملاحظة واضغط ➤؛ اكتب @ عشان تنادي زميل.\n'
                       '• تقدر ترفق صورة أو ملف أو رسالة صوتية.',
                       'The log shows everything that happened and who did it.\n'
                       '• Write a note and press ➤; type @ to mention a colleague.\n'
                       '• You can attach an image, a file or a voice note.')},
            {'target': 'callcenter-cases-actions', 'text': T('«⚙️ بدء المعالجة» ← «✅ حل الحالة» ← «🔒 إغلاق».',
                                              '"⚙️ Start working" → "✅ Resolve" → "🔒 Close".'),
             'more': T('• «بدء المعالجة» للحالة المفتوحة، وبيسندها ليك.\n'
                       '• «حل الحالة» بيطلب «اشرح طريقة الحل» ثم «✅ تأكيد الحل».\n'
                       '• بعد الحل: «🔒 إغلاق» وتقييم العميل CSAT من 1 لـ 5.',
                       '• "Start working" is for an open case and assigns it to you.\n'
                       '• "Resolve" asks you to explain the solution, then "✅ Confirm resolution".\n'
                       '• After resolving: "🔒 Close" and the customer\'s CSAT rating from 1 to 5.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
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
        'tour': [
            {'target': 'callcenter-analytics-header', 'text': T('لوحة مركز الاتصال: مراقبة جودة المكالمات والحالات وأداء المندوبين.',
                                              'The call center board: call quality, cases and agent performance.'),
             'more': T('دي شاشة المتابعة والتقييم، مش شاشة الرد على المكالمات.\n'
                       '• منها المشرف يعرف فين المشكلة: نسبة رد قليلة، معاودات متأخرة، أو موظف محتاج تدريب.',
                       'This is the monitoring and scoring screen, not the call-answering screen.\n'
                       '• From it the supervisor sees where the problem is: low answer rate, overdue callbacks, or an agent needing training.')},
            {'target': 'callcenter-analytics-tabs', 'text': T('اختر التبويب: «مؤشرات الأداء» أو «سجل المكالمات» أو «لوحة الحالات» أو «أداء المندوبين».',
                                              'Pick a tab: "KPIs", "Call log", "Cases board" or "Agent performance".'),
             'more': T('• «سجل المكالمات»: البحث وتقييم كل مكالمة.\n'
                       '• «لوحة الحالات»: المفتوحة والمُصعَّدة ومتوسط زمن الحل.\n'
                       '• «أداء المندوبين»: حجم مكالمات كل موظف وترتيبه في الجودة خلال 30 يوم.',
                       '• "Call log": search and score each call.\n'
                       '• "Cases board": open and escalated cases and average resolution time.\n'
                       '• "Agent performance": each agent\'s call volume and quality ranking over 30 days.')},
            {'target': 'callcenter-analytics-kpis', 'text': T('مؤشرات اليوم: المكالمات، نسبة الإجابة، متوسط المدة والجودة، المعاودات المتأخرة، وتحديثات العنوان.',
                                              'Today\'s indicators: calls, answer rate, average duration and quality, overdue callbacks, and address updates.'),
             'more': T('«معاودات متأخرة» = مكالمات اتسجّلت «معاودة» ولسه محدش رجع كلّم العميل — دي أول حاجة تتابعها.\n'
                       '• «متوسط جودة» جاي من تقييمات المكالمات في «سجل المكالمات».',
                       '"Overdue callbacks" = calls logged as "call back" that nobody has returned yet — follow those up first.\n'
                       '• "Average quality" comes from the call scores in the "Call log".')},
            {'target': 'callcenter-analytics-calls-search', 'text': T('في تبويب «سجل المكالمات»: ابحث بالاسم أو الهاتف أو الملاحظات.',
                                              'In the "Call log" tab: search by name, phone or notes.'),
             'more': T('مفيد لما عميل يشتكي من مكالمة معيّنة وعايز تلاقيها بسرعة.\n'
                       '• البحث بيدوّر كمان في الملاحظات المكتوبة.',
                       'Useful when a customer complains about a particular call and you want to find it fast.\n'
                       '• The search also looks in the written notes.')},
            {'target': 'callcenter-analytics-calls-filters', 'text': T('في نفس التبويب: صفِّ المكالمات حسب الغرض، وبجانبه فلاتر الحالة والاتجاه.',
                                              'In the same tab: filter calls by purpose, next to the status and direction filters.'),
             'more': T('• الغرض: حجز، توصيل، شكوى، إلخ.\n'
                       '• الحالة: تمت، لا رد، مشغول، بريد صوتي، معاودة.\n'
                       '• الاتجاه: واردة، صادرة، واتساب.\n'
                       'مثلاً: «شكوى» + «لا رد» يوريك شكاوى محتاجة رجوع.',
                       '• Purpose: reservation, delivery, complaint, etc.\n'
                       '• Status: answered, no answer, busy, voicemail, call back.\n'
                       '• Direction: inbound, outbound, WhatsApp.\n'
                       'E.g. "Complaint" + "No answer" shows complaints that need a callback.')},
            {'target': 'callcenter-analytics-score', 'text': T('زر ⭐ بجانب كل مكالمة يفتح تقييم جودتها من 100.',
                                              'The ⭐ button next to each call opens its quality score out of 100.'),
             'more': T('التقييم 4 بنود: الترحيب والتعريف (20)، حل المشكلة (30)، وضوح التواصل (25)، دقة المعلومات (25)، والنتيجة: ممتاز، جيد، مقبول، أو يحتاج تحسين.\n'
                       '• «ملاحظات التقييم» اختيارية.\n'
                       '• «حفظ التقييم» أو «تحديث التقييم» لو كان متقيّم قبل كده.',
                       'The score has 4 parts: greeting (20), problem resolution (30), communication clarity (25), information accuracy (25), with a result: excellent, good, acceptable or needs improvement.\n'
                       '• "Score notes" are optional.\n'
                       '• "Save score", or "Update score" if it was scored before.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
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
        'tour': [
            {'target': 'callcenter-pbx-header', 'text': T('لوحة المكالمات الحية: تتحدث لحظياً من السنترال.',
                                              'The live calls board: updated in real time from the PBX.'),
             'more': T('مش محتاج تعمل تحديث للصفحة — المكالمات بتظهر وتختفي لوحدها أول ما تحصل.\n'
                       '• الشاشة دي للمتابعة؛ تسجيل المكالمة نفسه بيتم من شاشة موظف الكول سنتر.',
                       'No need to refresh — calls appear and disappear by themselves as they happen.\n'
                       '• This screen is for monitoring; the call itself is logged on the operator screen.')},
            {'target': 'callcenter-pbx-status', 'text': T('حالة الاتصال المباشر؛ لو «غير متصل» أعد تحميل الصفحة.',
                                              'The live connection status; if it shows "disconnected", reload the page.'),
             'more': T('• «متصل»: البيانات بتوصل لحظي.\n'
                       '• «جاري الاتصال...»: بيحاول يوصل.\n'
                       '• «غير متصل»: اللي قدامك ممكن يكون قديم — أعد تحميل الصفحة.',
                       '• "Connected": data arrives live.\n'
                       '• "Connecting...": trying to connect.\n'
                       '• "Disconnected": what you see may be out of date — reload the page.')},
            {'target': 'callcenter-pbx-active', 'text': T('المكالمات النشطة الآن؛ اضغط بطاقة لعرض بطاقة العميل لو كان معروفاً.',
                                              'Calls active now; click a card to show the customer card when the caller is known.'),
             'more': T('الرقم جنب العنوان = عدد المكالمات النشطة (رنين، متصل، أو في الطابور).\n'
                       '• بطاقة العميل فيها الاسم والشريحة وآخر المشتريات والقسائم والحالات المفتوحة ورصيد النقاط — عشان ترد وانت عارف هو مين.',
                       'The number next to the title = active calls (ringing, connected or queued).\n'
                       '• The customer card shows name, segment, last purchases, vouchers, open cases and points balance — so you answer knowing who it is.')},
            {'target': 'callcenter-pbx-history', 'text': T('سجل آخر المكالمات: المتصل، العميل، الطابور، الموظف، الحالة ومدة الانتظار والمكالمة.',
                                              'Recent calls: caller, customer, queue, agent, status, wait and talk time.'),
             'more': T('مفيد عشان تشوف المكالمات اللي فاتت ومحدش ردّ عليها وترجع تكلّمهم.\n'
                       '• مدة «انتظار» طويلة معناها الطابور محتاج موظفين أكتر في الوقت ده.',
                       'Useful to spot missed calls nobody answered so you can call them back.\n'
                       '• A long "wait" time means the queue needs more agents at that hour.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
]
