from . import T

CHANGE_NOTE = T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour')

MODULE = {
    'key': 'callcenter', 'group': 'callcenter', 'icon': '📞',
    'brief': T('شغل الكول سنتر: رقم المتصل يفتح ملف العميل، والحالات تتسجّل وتتابع.',
               'Call-center work: the caller\'s number opens the customer file, and cases are logged and followed.'),
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
    'journeys': [
        {'key': 'incoming-call', 'shell': 'desktop',
         'title': T('مكالمة واردة: من الرنة لحل الطلب', 'An incoming call: from ring to resolution'),
         'summary': T('تعرّف على المتصل، سجّل المكالمة، حوّل طلبه لحجز أو حالة، وتابع لحد الحل.',
                      'Identify the caller, log the call, turn the request into a reservation or a case, and follow up until solved.'),
         'steps': [
            {'screen': 'callcenter.operator', 'target': 'callcenter-operator-screenpop', 'perm': 'callcenter',
             'label': T('📲 مكالمة واردة', '📲 Incoming call'),
             'text': T('السنترال بيرن والرقم بيتبحث لوحده.', 'The PBX rings and the number is searched for you.'),
             'open_hint': T('بيظهر وقت مكالمة واردة بس؛ غير كده اكتب الرقم.', 'Shows only during an incoming call; otherwise type the number.')},
            {'screen': 'callcenter.operator', 'target': 'callcenter-operator-profile', 'perm': 'callcenter',
             'label': T('ملف العميل', 'Customer profile'),
             'text': T('اتأكد من العميل وشوف حالاته وحجوزاته المفتوحة قبل ما ترد.', 'Confirm the customer and check their open cases and reservations before answering.'),
             'open_hint': T('ابحث برقم الأول.', 'Search for a number first.')},
            {'screen': 'callcenter.operator', 'target': 'callcenter-operator-log', 'perm': 'callcenter',
             'label': T('📝 تسجيل المكالمة', '📝 Log the call'),
             'text': T('الغرض والحالة وملخص قصير.', 'Purpose, status and a short summary.'),
             'open_hint': T('ابحث برقم الأول.', 'Search for a number first.')},
            {'screen': 'callcenter.operator', 'target': 'callcenter-operator-items', 'perm': 'callcenter',
             'label': T('📦 الأصناف', '📦 Items'),
             'text': T('ضيف الأصناف اللي طلبها.', 'Add the items they asked for.'),
             'open_hint': T('بيظهر بعد البحث برقم.', 'Appears after searching for a number.')},
            {'screen': 'callcenter.operator', 'target': 'callcenter-operator-save', 'perm': 'callcenter',
             'label': T('💾 حفظ المكالمة', '💾 Save call'),
             'text': T('احفظ. الأصناف بتتحفظ مع المكالمة.', 'Save. The items are saved with the call.'),
             'open_hint': T('ابحث برقم الأول.', 'Search for a number first.')},
            {'screen': 'callcenter.operator', 'target': 'callcenter-operator-convert', 'perm': 'callcenter',
             'label': T('📋 تحويل لحجوزات', '📋 To reservations'),
             'text': T('حوّل الأصناف لحجوزات في الفرع المناسب، أو لطلب نقل.', 'Turn the items into reservations at the right branch, or a transfer request.'),
             'warn': T('بيعمل حجوزات حقيقية فوراً. اتأكد من الفرع.', 'Creates real reservations at once. Check the branch.'),
             'open_hint': T('بعد حفظ مكالمة فيها أصناف.', 'After saving a call that has items.')},
            {'screen': 'callcenter.operator', 'target': 'callcenter-operator-quick', 'perm': 'callcenter',
             'label': T('🗂️ فتح حالة جديدة', '🗂️ Open new case'),
             'text': T('شكوى أو طلب محتاج متابعة؟ افتح حالة.', 'A complaint or request needing follow-up? Open a case.'),
             'open_hint': T('بعد تحديد العميل وقبل الحفظ؛ بعد الحفظ استخدم «🗂️ فتح حالة».', 'After identifying the customer, before saving; after saving use "🗂️ Open case".')},
            {'screen': 'callcenter.cases', 'target': 'callcenter-cases-start', 'perm': 'callcenter',
             'label': T('⚙️ بدء المعالجة', '⚙️ Start working'),
             'text': T('الحالة تتسند لك وتبقى «قيد المعالجة».', 'The case is assigned to you and becomes "Working".'),
             'open_hint': T('افتح الحالة الجديدة من القائمة.', 'Open the new case from the list.')},
            {'screen': 'callcenter.cases', 'target': 'callcenter-cases-note', 'perm': 'callcenter',
             'label': T('أضف ملاحظة...', 'Add a note...'),
             'text': T('سجّل كل خطوة، و@ لزميل محتاج يساعد.', 'Log every step, and @ a colleague who needs to help.'),
             'open_hint': T('افتح أي حالة من القائمة.', 'Open any case from the list.')},
            {'screen': 'callcenter.cases', 'target': 'callcenter-cases-resolve', 'perm': 'callcenter',
             'label': T('✅ حل الحالة', '✅ Resolve case'),
             'text': T('اكتب الحل، وسجّل تقييم العميل، وبعدين «🔒 إغلاق».', 'Write the solution, record the customer rating, then "🔒 Close".'),
             'warn': T('ماتقفلش قبل ما العميل يتأكد إن طلبه اتحل.', 'Do not close before the customer confirms it is solved.'),
             'open_hint': T('افتح حالة لسه ما اتحلّتش.', 'Open a case that is not resolved yet.')},
         ]},
        {'key': 'callbacks', 'shell': 'desktop',
         'title': T('معاودة الاتصال بالعملاء', 'Calling customers back'),
         'summary': T('من طابور المعاودة: اتصل بالعميل، سجّل النتيجة، وشيله من الطابور.',
                      'From the callback queue: call the customer, log the result, and clear it from the queue.'),
         'steps': [
            {'screen': 'callcenter.operator', 'target': 'callcenter-operator-callbacks', 'perm': 'callcenter',
             'label': T('🔄 المعاودة', '🔄 Callbacks'),
             'text': T('الرقم الأحمر عدد المتأخرة. افتح الطابور.', 'The red number is the overdue count. Open the queue.')},
            {'screen': 'callcenter.callbacks', 'target': 'callcenter-callbacks-mode', 'perm': 'callcenter',
             'label': T('⚠ متأخرة فقط', '⚠ Overdue only'),
             'text': T('ابدأ بالمتأخرة.', 'Start with the overdue ones.')},
            {'screen': 'callcenter.callbacks', 'target': 'callcenter-callbacks-dial', 'perm': 'callcenter',
             'label': T('📞 اتصال', '📞 Dial'),
             'text': T('تليفونك بيرن، ولما ترد بيتصل بالعميل.', 'Your phone rings; when you answer it calls the customer.'),
             'open_hint': T('على أي كارت في الطابور.', 'On any card in the queue.')},
            {'screen': 'callcenter.operator', 'target': 'callcenter-operator-save', 'perm': 'callcenter',
             'label': T('💾 حفظ المكالمة', '💾 Save call'),
             'text': T('سجّل نتيجة المكالمة الجديدة في شاشة الموظف.', 'Log the result of the new call on the operator screen.'),
             'open_hint': T('ابحث برقم العميل الأول.', 'Search for the customer number first.')},
            {'screen': 'callcenter.callbacks', 'target': 'callcenter-callbacks-done', 'perm': 'callcenter',
             'label': T('✓ تم', '✓ Done'),
             'text': T('وصلت للعميل؟ شيل المعاودة من الطابور.', 'Reached the customer? Clear the callback from the queue.'),
             'warn': T('بعد ما توصل للعميل فعلاً بس.', 'Only after you really reached the customer.'),
             'open_hint': T('على أي كارت في الطابور.', 'On any card in the queue.')},
         ]},
        {'key': 'supervisor-board', 'shell': 'desktop', 'roles': ['admin', 'supervisor'],
         'title': T('يوم المشرف: الطابور والجودة والسنترال', 'The supervisor day: queue, quality and PBX'),
         'summary': T('راقب المكالمات الحية، قيّم جودة المكالمات، تابع الحالات المُصعَّدة، واتأكد إن السنترال شغّال.',
                      'Watch live calls, score call quality, chase escalated cases, and make sure the PBX is working.'),
         'steps': [
            {'screen': 'callcenter.pbx', 'target': 'callcenter-pbx-active', 'perm': 'callcenter',
             'label': T('مكالمات نشطة', 'Active calls'),
             'text': T('شوف مين بيرن ومين متصل دلوقتي.', 'See who is ringing and who is connected right now.')},
            {'screen': 'callcenter.pbx', 'target': 'callcenter-pbx-diagnose', 'perm': 'callcenter',
             'label': T('🩺 فحص الاتصال', '🩺 Test connection'),
             'text': T('السنترال مش متصل؟ افحص، وأول خطوة حمرا هي السبب.', 'PBX not connected? Test it; the first red step is the cause.'),
             'open_hint': T('تبويب «⚙️ إعدادات السنترال».', 'The "⚙️ PBX settings" tab.')},
            {'screen': 'callcenter.analytics', 'target': 'callcenter-analytics-kpis', 'perm': 'callcenter',
             'label': T('مؤشرات الأداء', 'KPIs'),
             'text': T('نسبة الإجابة والمعاودات المتأخرة ومتوسط الجودة.', 'Answer rate, overdue callbacks and average quality.'),
             'open_hint': T('تبويب «📊 مؤشرات الأداء».', 'The "📊 KPIs" tab.')},
            {'screen': 'callcenter.analytics', 'target': 'callcenter-analytics-score', 'perm': 'callcenter',
             'label': T('⭐', '⭐'),
             'text': T('قيّم عينة من مكالمات اليوم.', 'Score a sample of today calls.'),
             'open_hint': T('تبويب «📞 سجل المكالمات».', 'The "📞 Call log" tab.')},
            {'screen': 'callcenter.analytics', 'target': 'callcenter-analytics-case-filters', 'perm': 'callcenter',
             'label': T('مُصعَّدة', 'Escalated'),
             'text': T('اعرض المُصعَّدة وتابعها مع الموظف المسؤول.', 'Show escalated cases and chase them with the assignee.'),
             'open_hint': T('تبويب «📋 لوحة الحالات».', 'The "📋 Cases board" tab.')},
            {'screen': 'callcenter.analytics', 'target': 'callcenter-analytics-agents', 'perm': 'callcenter',
             'label': T('أداء المندوبين', 'Agent performance'),
             'text': T('مين محتاج تدريب أو دعم.', 'Who needs coaching or support.'),
             'open_hint': T('تبويب «👤 أداء المندوبين».', 'The "👤 Agent performance" tab.')},
         ]},
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
        'tips': [
            T('«مخاطر الشكوى» تظهر للعملاء ذوي التاريخ السلبي — تعامل بعناية.', '"Complaint risk" shows for customers with a negative history — handle with care.'),
            T('بعد «🤖 تلخيص AI» يظهر الملخص ومشاعر العميل ودرجة الأهمية والإجراء المقترح تحت الأزرار خلال ثوانٍ.',
              'After "🤖 AI summary" the summary, customer sentiment, urgency and suggested next action appear under the buttons within seconds.'),
            T('في «آخر المكالمات»: «📝 تفريغ» يحوّل تسجيل المكالمة إلى نص ثم يلخصها تلقائياً. ويمكن للمدير تفعيل التفريغ التلقائي بعد كل مكالمة.',
              'In "Recent calls": "📝 Transcribe" turns the call recording into text and then summarizes it. The admin can also switch on automatic transcription after every call.'),
        ],
        'related': ['callcenter.cases', 'omni.inbox', 'customers.detail'],
        'workflows': [],
        'tour': [
            {'target': 'callcenter-operator-screenpop', 'label': T('📲 مكالمة واردة', '📲 Incoming call'),
             'text': T('لما السنترال يرن، الشريط ده بيظهر برقم المتصل والطابور واسم العميل، والرقم بيتكتب ويتبحث لوحده.',
                       'When the PBX rings, this banner shows the caller number, queue and customer name, and the number is filled in and searched for you.'),
             'when': T('لو انت لسه ما حفظتش مكالمة شغّال عليها. ✕ يقفل الشريط بس.', 'Only while you have no saved call open. ✕ just hides the banner.'),
             'open_hint': T('بيظهر بس وقت مكالمة واردة من السنترال.', 'Appears only during an incoming call from the PBX.')},
            {'target': 'callcenter-operator-mode', 'label': T('📞 بحث بالهاتف · 👤 بحث بالاسم / PIC', '📞 By phone · 👤 By name / PIC'),
             'text': T('اختار تدوّر بالرقم أو بالاسم / كود PIC. اختيار عميل من نتايج الاسم بيحمّل ملفه برقمه على طول.',
                       'Search by number or by name / PIC code. Picking a customer from the name results loads their profile by their phone.'),
             'more': T(
                 'العادي البحث بالهاتف وقت المكالمة.\n• لو المتصل من رقم تاني، ابحث بالاسم أو كود PIC؛ أول ما تختار العميل ملفه بيتحمّل برقم تليفونه.',
                 'Normally you search by phone during the call.\n• If the caller uses another number, search by name or PIC code; once you pick the customer, their profile loads by their phone number.')},
            {'target': 'callcenter-operator-phone', 'label': T('رقم الهاتف', 'Phone number'),
             'text': T('اكتب رقم المتصل. البحث بيشتغل لوحده بعد 8 أرقام، أو Enter.', 'Type the caller number. The search runs by itself after 8 digits, or press Enter.'),
             'when': T('«مسح» يفضّي الرقم والملف عشان تبدأ مكالمة جديدة.', '"Clear" empties the number and profile to start a new call.'),
             'more': T(
                 'البحث مش بيشتغل غير لما الرقم يبقى 8 أرقام على الأقل.\n• Enter في الخانة بيعمل بحث على طول.\n• «مسح» جنبه بيفضّي الشاشة للمكالمة الجاية.',
                 'Search only works once the number has at least 8 digits.\n• Enter in the box searches straight away.\n• "Clear" next to it empties the screen for the next call.')},
            {'target': 'callcenter-operator-dial', 'label': T('📞 اتصل', '📞 Call'),
             'text': T('تليفونك بيرن الأول، ولما ترد السنترال بيتصل بالرقم. اتجاه المكالمة بيتغير لـ«صادرة».',
                       'Your desk phone rings first; when you answer, the PBX dials the number. The call direction switches to "Outbound".'),
             'warn': T('لازم تحويلتك تكون مربوطة بحسابك، وإلا هيظهر خطأ ومحدش هيتصل.', 'Your extension must be mapped to your account, otherwise you get an error and nothing is dialled.')},
            {'target': 'callcenter-operator-profile', 'label': T('ملف العميل', 'Customer profile'),
             'text': T('بيانات العميل والفرع والقيمة، الحالات المفتوحة، مشتريات 365 يوم، الحجوزات والمتابعات والطلبات وآخر المكالمات.',
                       'Customer details, branch and value, open cases, 365-day purchases, reservations, follow-ups, requests and recent calls.'),
             'when': T('لو أكتر من عميل على نفس الرقم اختار واحد، أو «👤 متصل غير محدد».', 'If several customers share the number pick one, or "👤 Unidentified caller".'),
             'open_hint': T('ابحث برقم الأول.', 'Search for a number first.'),
             'more': T(
                 'فيه: الشريحة والقيمة وآخر زيارة، عنوان التوصيل وزر واتساب، الحالات المفتوحة، مشتريات آخر 365 يوم، مهام المتابعة، الحجوزات، الطلبات المعلقة، وآخر المكالمات.\n• شريط «مخاطر الشكوى» العالي (أحمر من 60) = تاريخ سلبي، اتعامل بحرص.',
                 'It holds: segment, value and last visit, delivery address and a WhatsApp button, open cases, last-365-day purchases, follow-up tasks, reservations, pending requests and recent calls.\n• A high "Complaint risk" bar (red from 60) = negative history; handle with care.')},
            {'target': 'callcenter-operator-log', 'label': T('📝 تسجيل المكالمة', '📝 Log the call'),
             'text': T('اختار الغرض والاتجاه والحالة (أجاب، لا رد، مشغول، معاودة) واكتب ملخص سريع وملاحظات.',
                       'Pick the purpose, direction and status (answered, no answer, busy, callback) and write a short summary and notes.'),
             'when': T('الحالة «🔄 معاودة» بتحط المكالمة في طابور المعاودة.', 'Status "🔄 Callback" puts the call in the callback queue.'),
             'open_hint': T('ابحث برقم الأول.', 'Search for a number first.'),
             'more': T(
                 '• «الغرض»: سبب المكالمة (حجز، توصيل، إعادة صرف، شكوى…).\n• «الاتجاه»: واردة، صادرة، أو واتساب.\n• «الحالة»: أجاب، لا رد، مشغول، معاودة.\n• «ملخص سريع» و«ملاحظات تفصيلية» لأي حد يقرا بعدك.',
                 '• "Purpose": why they called (reservation, delivery, refill, complaint…).\n• "Direction": inbound, outbound or WhatsApp.\n• "Status": answered, no answer, busy, call back.\n• "Quick summary" and "Detailed notes" for whoever reads after you.')},
            {'target': 'callcenter-operator-save', 'label': T('💾 حفظ المكالمة', '💾 Save call'),
             'text': T('بيسجّل المكالمة باسمك ويربطها بمكالمة السنترال لو جت من الشريط. بعدها تظهر أزرار الحالة والمتابعة والتلخيص.',
                       'Records the call under your name and links it to the PBX call if it came from the banner. Then the case, follow-up and summary buttons appear.'),
             'warn': T('سجّل كل مكالمة قبل ما تقفل. الشكوى بعد الحفظ محتاجة «🗂️ فتح حالة».', 'Log every call before you hang up. A complaint still needs "🗂️ Open case" after saving.'),
             'open_hint': T('ابحث برقم الأول.', 'Search for a number first.'),
             'more': T(
                 'الزر بيشتغل بعد البحث برقم. بعد الحفظ بيظهر رقم المكالمة، ومعاه: «🗂️ فتح حالة»، «🔔 جدولة متابعة»، و«🤖 تلخيص AI».\n• لو الغرض «شكوى» بيفكّرك تفتح حالة بعد الحفظ.\n• «📞 تسجيل مكالمة أخرى» يجهّز للي بعدها.',
                 'The button works after searching a number. After saving, the call number shows with "🗂️ Open case", "🔔 Schedule follow-up" and "🤖 AI summary".\n• If the purpose is "Complaint", it reminds you to open a case after saving.\n• "📞 Log another call" gets ready for the next one.')},
            {'target': 'callcenter-operator-quick', 'label': T('🗂️ فتح حالة جديدة · 🔔 جدولة متابعة', '🗂️ Open new case · 🔔 Schedule follow-up'),
             'text': T('حالة لأي شكوى أو طلب محتاج متابعة لحد الحل، أو متابعة بموعد (إعادة صرف، مزمن، طلب، مهمة).',
                       'A case for any complaint or request that needs work until solved, or a dated follow-up (refill, chronic, request, task).'),
             'when': T('متاحين قبل الحفظ، وبعده من نفس الأزرار تحت «تم التسجيل بنجاح».', 'Available before saving, and after it from the same buttons under "Logged successfully".'),
             'open_hint': T('بيظهر بعد تحديد العميل وقبل حفظ المكالمة.', 'Appears once a customer is identified and before the call is saved.')},
            {'target': 'callcenter-operator-items', 'label': T('📦 الأصناف', '📦 Items'),
             'text': T('سجّل الأصناف اللي العميل طلبها: «🔍 بحث» من الكتالوج أو «✏️ يدوي». قبل الحفظ بتفضل «في الانتظار».',
                       'Record the items the customer asked for: "🔍 Search" the catalog or "✏️ Manual". Before saving they stay "pending".'),
             'open_hint': T('بيظهر بعد البحث برقم.', 'Appears after searching for a number.')},
            {'target': 'callcenter-operator-convert', 'label': T('📋 تحويل لحجوزات · 🔄 تحويل لطلب نقل', '📋 Reservations · 🔄 Transfer request'),
             'text': T('حجز لكل صنف في الفرع اللي تختاره (أولوية وقناة)، أو طلب نقل بين الفروع. الأصناف اليدوية ماتتنقلش.',
                       'One reservation per item at the branch you pick (priority and channel), or a transfer request between branches. Manual items cannot be transferred.'),
             'warn': T('الضغط على «إنشاء» بيعمل حجوزات أو طلب نقل حقيقي فوراً. اتأكد من الفرع والأصناف.',
                       'Pressing "Create" makes real reservations or a transfer request at once. Check the branch and items.'),
             'open_hint': T('احفظ المكالمة وفيها صنف واحد على الأقل لسه ما اتحوّلش.', 'Save the call with at least one item not converted yet.')},
            {'target': 'callcenter-operator-ai', 'label': T('🤖 تلخيص AI', '🤖 AI summary'),
             'text': T('بيبعت المكالمة للذكاء الاصطناعي، وخلال ثواني يظهر ملخص ومشاعر العميل والأهمية وإجراء مقترح.',
                       'Sends the call to AI; within seconds a summary, customer sentiment, urgency and a suggested action appear.'),
             'when': T('اقتراح للمساعدة بس، والقرار ليك.', 'A suggestion only; the decision stays yours.'),
             'open_hint': T('بيظهر بعد «💾 حفظ المكالمة».', 'Appears after "💾 Save call".')},
            {'target': 'callcenter-operator-callbacks', 'label': T('🔄 المعاودة', '🔄 Callbacks'),
             'text': T('يفتح طابور المعاودة. الرقم الأحمر عدد المعاودات المتأخرة.', 'Opens the callback queue. The red number is the count of overdue callbacks.')},
            {'target': 'callcenter-operator-search', 'label': T('🔍 بحث', '🔍 Search'), 'when': T('بعد ما تكتب رقم المتصل.', 'After typing the caller\'s number.'),  # from the GitHub-side tour
             'text': T('«🔍 بحث» يجيب ملف العميل.',
                       '"🔍 Search" brings up the customer\'s profile.'),
             'more': T(
                 'لو أكتر من عميل بنفس الرقم بتختار العميل الأول، أو تسجّل المكالمة كـ «👤 متصل غير محدد».\n• لو الرقم مش مسجّل بيظهر «عميل جديد — لا توجد بيانات سابقة».',
                 'If several customers share the number you pick one first, or log the call as "👤 Unknown caller".\n• If the number is not registered, "New customer — no previous data" appears.')},
        ],
        'updated': '2026-10-26',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
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
        'tips': [
            T('لكل حالة موعد SLA تلقائي حسب الأولوية: عاجلة 4 ساعات، مرتفعة 8، عادية 24، منخفضة 72 (يمكن تحديد موعد آخر عند الفتح).',
              'Every case gets an automatic SLA deadline by priority: urgent 4 hours, high 8, normal 24, low 72 (a different deadline can be set when opening).'),
            T('كل ساعة: الحالة «مفتوحة» أو «قيد المعالجة» التي تجاوزت موعدها تُصعَّد تلقائياً ويُبلَّغ المسؤول والمشرفون. «انتظار العميل» لا تُصعَّد.',
              'Every hour: an "Open" or "Working" case past its deadline is escalated automatically and the assignee and supervisors are notified. "Waiting for customer" cases are not escalated.'),
        ],
        'related': ['callcenter.operator', 'callcenter.analytics'],
        'tour': [
            {'target': 'callcenter-cases-new', 'label': T('+ حالة جديدة', '+ New case'),
             'text': T('دوّر على العميل بالرقم أو الاسم، واختار التصنيف والأولوية واكتب العنوان، وبعدين «🗂️ فتح الحالة».',
                       'Find the customer by number or name, pick the type and priority, write the title, then "🗂️ Open case".'),
             'when': T('موعد SLA بيتحسب لوحده من الأولوية: عاجلة 4 ساعات لحد منخفضة 72.', 'The SLA deadline is set from the priority: urgent 4 hours down to low 72.'),
             'open_hint': T('للمدير والمشرف والكول سنتر ومدير الجودة.', 'For admin, supervisor, call center and quality manager.'),
             'more': T(
                 'بيفتح نافذة: ابحث عن العميل برقم أو اسم، وبعدين التصنيف والأولوية و«عنوان الحالة» (إجباري) والوصف.\n• الزر ظاهر للمدير والمشرف والكول سنتر والجودة.\n• أثناء مكالمة، الأسهل تفتح الحالة من شاشة الموظف.',
                 'Opens a window: find the customer by phone or name, then category, priority, "Case title" (required) and description.\n• The button shows for admins, supervisors, call center and quality.\n• During a call, it is easier to open the case from the operator screen.')},
            {'target': 'callcenter-cases-filters', 'label': T('بحث... · الحالة · التصنيف · الترتيب', 'Search · status · type · sort'),
             'text': T('ابحث برقم الحالة أو العنوان أو اسم / رقم العميل، وفلتر بالحالة والتصنيف.', 'Search by case number, title or customer name / phone, and filter by status and type.'),
             'when': T('رتّب «SLA أقرب» عشان تبدأ باللي موعده قرّب.', 'Sort by "SLA nearest" to start with the closest deadlines.'),
             'more': T(
                 'الحالة: مفتوحة، قيد المعالجة، انتظار، مُصعَّدة، محلولة، مغلقة.\n• الترتيب: الأحدث، الأقدم، «SLA أقرب»، أو الأولوية.\n• ابدأ بالمُصعَّدة و«SLA أقرب».',
                 'Status: open, working, waiting, escalated, resolved, closed.\n• Sort: newest, oldest, "nearest SLA" or priority.\n• Start with escalated and "nearest SLA".')},
            {'target': 'callcenter-cases-card', 'label': T('كارت الحالة', 'Case card'),
             'text': T('رقم الحالة ومرحلتها والعميل والفرع والمسؤول وعمرها بالساعات. «⏰ SLA!» يعني الموعد عدّى.',
                       'Case number, stage, customer, branch, assignee and age in hours. "⏰ SLA!" means the deadline has passed.'),
             'when': T('اضغط الكارت يفتح التفاصيل جنب القائمة.', 'Click the card to open its details beside the list.'),
             'more': T(
                 'التفاصيل بتفتح على الجنب من غير ما تسيب القائمة.\n• على الموبايل التفاصيل بتاخد الشاشة كلها.',
                 'The details open on the side without leaving the list.\n• On a phone the details take the whole screen.')},
            {'target': 'callcenter-cases-detail', 'label': T('تفاصيل الحالة', 'Case details'),
             'text': T('الوصف والحل والسبب الجذري وتقييم العميل، وسجل الأحداث بكل خطوة ومين عملها.',
                       'Description, solution, root cause and customer rating, plus the event log of every step and who did it.'),
             'open_hint': T('اضغط أي حالة في القائمة.', 'Click any case in the list.'),
             'more': T(
                 'السجل بيوضح كل حاجة حصلت ومين عملها.\n• اكتب ملاحظة واضغط ➤؛ اكتب @ عشان تنادي زميل.\n• تقدر ترفق صورة أو ملف أو رسالة صوتية.',
                 'The log shows everything that happened and who did it.\n• Write a note and press ➤; type @ to mention a colleague.\n• You can attach an image, a file or a voice note.')},
            {'target': 'callcenter-cases-note', 'label': T('أضف ملاحظة... · 📎 · 🎙️ · ➤', 'Add a note... · 📎 · 🎙️ · ➤'),
             'text': T('اكتب كل خطوة هنا. @ يذكر زميل ويوصله إشعار. 📎 صورة أو مستند، 🎙️ رسالة صوتية، ➤ أو Enter للإرسال.',
                       'Log every step here. @ mentions a colleague and notifies them. 📎 image or document, 🎙️ voice note, ➤ or Enter to send.'),
             'open_hint': T('افتح أي حالة من القائمة.', 'Open any case from the list.')},
            {'target': 'callcenter-cases-start', 'label': T('⚙️ بدء المعالجة', '⚙️ Start working'),
             'text': T('بيسند الحالة ليك وينقلها لـ«قيد المعالجة»، ويتسجل في سجل الأحداث.', 'Assigns the case to you and moves it to "Working"; it is logged in the event log.'),
             'open_hint': T('افتح حالة «مفتوحة».', 'Open a case in "Open" status.')},
            {'target': 'callcenter-cases-resolve', 'label': T('✅ حل الحالة', '✅ Resolve case'),
             'text': T('اكتب طريقة الحل وبعدين «✅ تأكيد الحل». الحالة تبقى «محلولة».', 'Write how it was solved, then "✅ Confirm resolution". The case becomes "Resolved".'),
             'warn': T('اكتب الحل الحقيقي بوضوح، ده اللي بيتراجع بعدين ويتقاس عليه.', 'Write the real solution clearly; it is what gets reviewed and measured later.'),
             'open_hint': T('افتح حالة مفتوحة أو قيد المعالجة أو في انتظار العميل.', 'Open a case that is Open, Working or Waiting for customer.')},
            {'target': 'callcenter-cases-csat', 'label': T('CSAT ➤', 'CSAT ➤'),
             'text': T('سجّل تقييم العميل من 1 لـ 5 نجوم بعد الحل.', 'Record the customer rating, 1 to 5 stars, after the resolution.'),
             'open_hint': T('افتح حالة «محلولة» لسه من غير تقييم.', 'Open a "Resolved" case with no rating yet.')},
            {'target': 'callcenter-cases-close', 'label': T('🔒 إغلاق', '🔒 Close'),
             'text': T('يقفل الحالة نهائياً. مايشتغلش غير على حالة محلولة.', 'Closes the case for good. Works only on a resolved case.'),
             'warn': T('مافيش زرار إعادة فتح هنا. سجّل التقييم وأي ملاحظة قبل الإغلاق.', 'There is no reopen button here. Record the rating and any note before closing.'),
             'open_hint': T('افتح حالة «محلولة».', 'Open a "Resolved" case.')},
            {'target': 'callcenter-cases-list', 'label': T('🗂️ إدارة الحالات', '🗂️ Case management'), 'when': T('لما تحب تختار حالة تشتغل عليها.', 'When you want to pick a case to work on.'),  # from the GitHub-side tour
             'text': T('الحالات.',
                       'The cases.'),
             'more': T(
                 'كل كارت: رقم الحالة والعنوان والحالة والأولوية والعميل.\n• «⏰ SLA!» بالأحمر = الحالة عدّت وقتها المسموح.\n• تحت فيه «السابق» و«التالي» للصفحات.',
                 'Each card: case number, title, status, priority and customer.\n• "⏰ SLA!" in red = the case is past its allowed time.\n• At the bottom are "Previous" and "Next" for pages.')},
            {'target': 'callcenter-cases-actions', 'label': T('⚙️ بدء المعالجة', '⚙️ Start working'), 'when': T('بعد ما تفتح الحالة.', 'After opening the case.'),  # from the GitHub-side tour
             'text': T('«بدء المعالجة» ← «حل الحالة» ← «إغلاق».',
                       '"Start handling" → "Resolve" → "Close".'),
             'more': T(
                 '• «بدء المعالجة» للحالة المفتوحة، وبيسندها ليك.\n• «حل الحالة» بيطلب «اشرح طريقة الحل» ثم «✅ تأكيد الحل».\n• بعد الحل: «🔒 إغلاق» وتقييم العميل CSAT من 1 لـ 5.',
                 '• "Start working" is for an open case and assigns it to you.\n• "Resolve" asks you to explain the solution, then "✅ Confirm resolution".\n• After resolving: "🔒 Close" and the customer\'s CSAT rating from 1 to 5.')},
        ],
        'updated': '2026-10-26',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
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
            {'target': 'callcenter-analytics-tabs', 'label': T('📊 مؤشرات · 📞 سجل · 📋 حالات · 👤 مندوبين', '📊 KPIs · 📞 Calls · 📋 Cases · 👤 Agents'),
             'text': T('أربع تبويبات: المؤشرات، سجل المكالمات وتقييمها، لوحة الحالات، وأداء المندوبين.',
                       'Four tabs: KPIs, the call log with scoring, the cases board, and agent performance.'),
             'open_hint': T('الصفحة للمدير والمشرف ومدير الجودة والكول سنتر.', 'The page is for admin, supervisor, quality manager and call center.'),
             'more': T(
                 '• «سجل المكالمات»: البحث وتقييم كل مكالمة.\n• «لوحة الحالات»: المفتوحة والمُصعَّدة ومتوسط زمن الحل.\n• «أداء المندوبين»: حجم مكالمات كل موظف وترتيبه في الجودة خلال 30 يوم.',
                 '• "Call log": search and score each call.\n• "Cases board": open and escalated cases and average resolution time.\n• "Agent performance": each agent\'s call volume and quality ranking over 30 days.')},
            {'target': 'callcenter-analytics-kpis', 'label': T('مكالمات اليوم · نسبة الإجابة · …', 'Calls today · answer rate · …'),
             'text': T('مكالمات اليوم ونسبة الإجابة ومتوسط المدة ومتوسط الجودة والمعاودات المتأخرة وتحديثات العنوان المعلّقة.',
                       'Calls today, answer rate, average duration, average quality, overdue callbacks and pending address updates.'),
             'when': T('المعاودات المتأخرة الحمرا معناها حد لازم يتصل دلوقتي.', 'Red overdue callbacks mean someone needs to call now.'),
             'open_hint': T('تبويب «📊 مؤشرات الأداء».', 'The "📊 KPIs" tab.'),
             'more': T(
                 '«معاودات متأخرة» = مكالمات اتسجّلت «معاودة» ولسه محدش رجع كلّم العميل — دي أول حاجة تتابعها.\n• «متوسط جودة» جاي من تقييمات المكالمات في «سجل المكالمات».',
                 '"Overdue callbacks" = calls logged as "call back" that nobody has returned yet — follow those up first.\n• "Average quality" comes from the call scores in the "Call log".')},
            {'target': 'callcenter-analytics-breakdown', 'label': T('توزيع الأغراض · تحليل المشاعر', 'Purposes · sentiment'),
             'text': T('أغراض المكالمات في آخر 30 يوم، ومشاعر العملاء من تلخيص الذكاء الاصطناعي.', 'Call purposes over the last 30 days, and customer sentiment from the AI summaries.'),
             'open_hint': T('تبويب «📊 مؤشرات الأداء».', 'The "📊 KPIs" tab.')},
            {'target': 'callcenter-analytics-call-filters', 'label': T('بحث · الحالة · الغرض · الاتجاه', 'Search · status · purpose · direction'),
             'text': T('دوّر في المكالمات بالاسم أو الرقم أو الملاحظات، وفلتر بالحالة والغرض والاتجاه.', 'Search calls by name, phone or notes, and filter by status, purpose and direction.'),
             'open_hint': T('تبويب «📞 سجل المكالمات».', 'The "📞 Call log" tab.')},
            {'target': 'callcenter-analytics-score', 'label': T('⭐', '⭐'),
             'text': T('يفتح تقييم جودة المكالمة دي.', 'Opens the quality scoring for this call.'),
             'open_hint': T('تبويب «📞 سجل المكالمات»، آخر عمود في أي صف.', 'The "📞 Call log" tab, last column of any row.'),
             'more': T(
                 'التقييم 4 بنود: الترحيب والتعريف (20)، حل المشكلة (30)، وضوح التواصل (25)، دقة المعلومات (25)، والنتيجة: ممتاز، جيد، مقبول، أو يحتاج تحسين.\n• «ملاحظات التقييم» اختيارية.\n• «حفظ التقييم» أو «تحديث التقييم» لو كان متقيّم قبل كده.',
                 'The score has 4 parts: greeting (20), problem resolution (30), communication clarity (25), information accuracy (25), with a result: excellent, good, acceptable or needs improvement.\n• "Score notes" are optional.\n• "Save score", or "Update score" if it was scored before.')},
            {'target': 'callcenter-analytics-score-save', 'label': T('حفظ التقييم', 'Save score'),
             'text': T('الدرجة من 100: الترحيب 20، حل المشكلة 30، وضوح التواصل 25، دقة المعلومات 25، مع ملاحظات.',
                       'The score out of 100: greeting 20, problem resolution 30, clarity 25, information accuracy 25, plus notes.'),
             'warn': T('التقييم بيتسجل باسمك وبيدخل في متوسط جودة الموظف. لكل مكالمة تقييم واحد والتعديل بيستبدله.',
                       'The score is saved under your name and counts in the agent average. One score per call; editing replaces it.'),
             'open_hint': T('اضغط ⭐ على أي مكالمة.', 'Press ⭐ on any call.')},
            {'target': 'callcenter-analytics-case-filters', 'label': T('مفتوحة · قيد المعالجة · … · الكل', 'Open · Working · … · All'),
             'text': T('اعرض الحالات حسب مرحلتها. ابدأ بـ«مُصعَّدة».', 'Show cases by stage. Start with "Escalated".'),
             'open_hint': T('تبويب «📋 لوحة الحالات».', 'The "📋 Cases board" tab.')},
            {'target': 'callcenter-analytics-agents', 'label': T('أداء المندوبين — آخر 30 يوم', 'Agent performance — last 30 days'),
             'text': T('ترتيب الموظفين بعدد المكالمات وجودتها في آخر 30 يوم.', 'Agents ranked by call count and quality over the last 30 days.'),
             'open_hint': T('تبويب «👤 أداء المندوبين».', 'The "👤 Agent performance" tab.')},
            {'target': 'callcenter-analytics-header', 'label': T('لوحة مركز الاتصال', 'Call center dashboard'), 'when': T('لما تحب تراجع أداء الكول سنتر.', 'When you want to review call center performance.'),  # from the GitHub-side tour
             'text': T('لوحة مركز الاتصال: مراقبة جودة المكالمات والحالات وأداء المندوبين.',
                       'The call center board: call quality, cases and agent performance.'),
             'more': T(
                 'دي شاشة المتابعة والتقييم، مش شاشة الرد على المكالمات.\n• منها المشرف يعرف فين المشكلة: نسبة رد قليلة، معاودات متأخرة، أو موظف محتاج تدريب.',
                 'This is the monitoring and scoring screen, not the call-answering screen.\n• From it the supervisor sees where the problem is: low answer rate, overdue callbacks, or an agent needing training.')},
            {'target': 'callcenter-analytics-calls-search', 'label': T('بحث باسم / هاتف / ملاحظات…', 'Search by name / phone / notes…'), 'when': T('لما تدوّر على مكالمة معيّنة.', 'When looking for a specific call.'),  # from the GitHub-side tour
             'text': T('في تبويب «سجل المكالمات»: ابحث بالاسم أو الهاتف أو الملاحظات.',
                       'In the "Call log" tab: search by name, phone or notes.'),
             'more': T(
                 'مفيد لما عميل يشتكي من مكالمة معيّنة وعايز تلاقيها بسرعة.\n• البحث بيدوّر كمان في الملاحظات المكتوبة.',
                 'Useful when a customer complains about a particular call and you want to find it fast.\n• The search also looks in the written notes.')},
            {'target': 'callcenter-analytics-calls-filters', 'label': T('كل الأغراض', 'All purposes'), 'when': T('لما تحب تشوف نوع مكالمات واحد.', 'When you want to see one kind of call.'),  # from the GitHub-side tour
             'text': T('في نفس التبويب: صفِّ المكالمات حسب الغرض، وبجانبه فلاتر الحالة والاتجاه.',
                       'In the same tab: filter calls by purpose, next to the status and direction filters.'),
             'more': T(
                 '• الغرض: حجز، توصيل، شكوى، إلخ.\n• الحالة: تمت، لا رد، مشغول، بريد صوتي، معاودة.\n• الاتجاه: واردة، صادرة، واتساب.\nمثلاً: «شكوى» + «لا رد» يوريك شكاوى محتاجة رجوع.',
                 '• Purpose: reservation, delivery, complaint, etc.\n• Status: answered, no answer, busy, voicemail, call back.\n• Direction: inbound, outbound, WhatsApp.\nE.g. "Complaint" + "No answer" shows complaints that need a callback.')},
        ],
        'updated': '2026-10-26',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
    },
    {
        'key': 'callcenter.callbacks',
        'routes': ['/callcenter/callbacks'],
        'title': T('طابور المعاودة', 'Callback queue'),
        'summary': T(
            'قائمة المكالمات التي طلب أصحابها معاودة الاتصال، مرتبة بالأقدم أولاً. '
            'المتأخرة تظهر باللون الأحمر. اضغط «📞 اتصال» لتبدأ المكالمة من التحويلة مباشرة، '
            'أو «عرض» لفتح سجل المكالمة في شاشة مركز الاتصال، أو «✓ تم» بعد الانتهاء.',
            'List of calls whose customers requested a callback, sorted oldest first. '
            'Overdue entries show in red. Click "📞 Dial" to start the call from your extension, '
            '"View" to open the call log in the call center screen, or "✓ Done" when finished.'),
        'audience': T('موظفو الكول سنتر والمشرفون.', 'Call center agents and supervisors.'),
        'steps': [
            T('افتح الطابور وابدأ بالمتأخرة (الأحمر) أولاً.', 'Open the queue and start with the overdue (red) entries first.'),
            T('اضغط «📞 اتصال» — سيرن هاتفك ثم يتصل بالعميل.', 'Click "📞 Dial" — your phone will ring then connect to the customer.'),
            T('بعد الاتصال اضغط «✓ تم» لإزالتها من الطابور.', 'After the call press "✓ Done" to remove it from the queue.'),
        ],
        'tips': [
            T('«متأخرة فقط» يعرض المتأخرة عن موعدها؛ «الكل» يعرض القادمة أيضاً.', '"Overdue only" shows past-due entries; "All" also shows upcoming ones.'),
        ],
        'workflows': [],
        'related': ['callcenter.operator', 'callcenter.cases'],
        'tour': [
            {'target': 'callcenter-callbacks-back', 'label': T('← مركز الاتصال', '← Call center'),
             'text': T('يرجّعك لشاشة موظف الكول سنتر.', 'Takes you back to the operator screen.')},
            {'target': 'callcenter-callbacks-mode', 'label': T('⚠ متأخرة فقط · 📋 الكل', '⚠ Overdue only · 📋 All'),
             'text': T('«متأخرة فقط» اللي موعدها عدّى، و«الكل» كل المكالمات المطلوب معاودتها بالأقدم أولاً.',
                       '"Overdue only" shows past-due callbacks; "All" shows every requested callback, oldest first.'),
             'when': T('ابدأ يومك بالمتأخرة.', 'Start your day with the overdue ones.')},
            {'target': 'callcenter-callbacks-card', 'label': T('كارت المعاودة', 'Callback card'),
             'text': T('اسم العميل والغرض والرقم والملاحظات ومين سجّل المكالمة والموعد. الإطار الأحمر يعني متأخرة.',
                       'Customer name, purpose, phone, notes, who logged the call and the due time. A red border means overdue.'),
             'open_hint': T('بيظهر لما يكون فيه مكالمات حالتها «معاودة».', 'Shows when there are calls with status "Callback".')},
            {'target': 'callcenter-callbacks-dial', 'label': T('📞 اتصال', '📞 Dial'),
             'text': T('تليفونك بيرن الأول، ولما ترد السنترال بيتصل بالعميل.', 'Your desk phone rings first; when you answer, the PBX calls the customer.'),
             'warn': T('محتاج تحويلة مربوطة بحسابك. لو مافيش رقم الزرار بيبقى مقفول.', 'Needs an extension mapped to your account. With no phone number the button is disabled.'),
             'open_hint': T('على أي كارت في الطابور.', 'On any card in the queue.')},
            {'target': 'callcenter-callbacks-view', 'label': T('📋 عرض', '📋 View'),
             'text': T('يفتح شاشة الموظف عشان تدوّر بالرقم وتسجّل نتيجة المكالمة الجديدة.', 'Opens the operator screen so you can search the number and log the new call.'),
             'open_hint': T('على أي كارت في الطابور.', 'On any card in the queue.')},
            {'target': 'callcenter-callbacks-done', 'label': T('✓ تم', '✓ Done'),
             'text': T('بيغيّر حالة المكالمة لـ«أجاب» فتختفي من الطابور.', 'Changes the call status to "Answered", so it leaves the queue.'),
             'warn': T('ماتضغطش إلا بعد ما توصل للعميل فعلاً، لأنها بتختفي من الطابور عند الكل.', 'Press only after you really reached the customer; it disappears from the queue for everyone.'),
             'open_hint': T('على أي كارت في الطابور.', 'On any card in the queue.')},
        ],
        'updated': '2026-10-26',
    },
    {
        'key': 'callcenter.pbx',
        'routes': ['/pbx/live'],
        'title': T('المكالمات الحية', 'Live calls'),
        'summary': T('لحظياً من السنترال: المكالمات النشطة (رنين، متصل، في الطابور) وسجل المكالمات الأخيرة. عند مكالمة واردة تظهر بطاقة العميل: الاسم، الشريحة، آخر المشتريات، القسائم والحالات المفتوحة، ورصيد النقاط.',
                     'Live from the PBX: active calls (ringing, connected, queued) and recent calls. On an incoming call the customer card shows: name, segment, last purchases, open vouchers and cases, and points balance.'),
        'audience': T('الكول سنتر والمشرفون.', 'Call center and supervisors.'),
        'tabs': [
            {'key': 'live', 'title': T('📞 المكالمات', '📞 Calls'),
             'body': T('المكالمات النشطة وسجل المكالمات الأخيرة لحظياً.', 'Active calls and the recent call log, live.')},
            {'key': 'config', 'title': T('⚙️ إعدادات السنترال', '⚙️ PBX settings'),
             'body': T('للمدير والمشرف: حالة الربط مع السنترال (متصل منذ، آخر نبضة، آخر خطأ، مرات إعادة الاتصال) وزر «🩺 فحص الاتصال» '
                       'الذي يفحص الإعدادات ← الوصول للسيرفر ← AMI ← تسجيل الدخول ← زمن الاستجابة ← تعريف القنوات ← عملية استقبال الأحداث ← التسجيلات، '
                       'ويشرح سبب أي عطل وطريقة إصلاحه. أول خطوة حمراء هي سبب المشكلة.\n\n'
                       '«التحويلات والهواتف»: كل تحويلة وحالة تسجيل هاتفها لحظياً (متصل / غير متصل / في مكالمة، عنوان IP، زمن الاستجابة)، '
                       'والموظف المرتبط بها، مع شرح أي مشكلة (هاتف مطفأ، تحويلة غير موجودة في السنترال، تحويلة غير مرتبطة بموظف). '
                       '«ربط» يربط التحويلة بموظف عندنا فقط ولا يغيّر شيئاً في Issabel؛ الموظف له تحويلة واحدة فيُنقل من تحويلته السابقة تلقائياً.\n\n'
                       'التفريغ المحلي للمكالمات (Whisper): يعمل ليلاً في نافذته (افتراضياً 2–6 صباحاً) بأولوية منخفضة، وما لا يكتمل يُستكمل الليلة التالية. '
                       'يمكن الإيقاف المؤقت / الاستئناف / إيقاف التشغيل الحالي، وتغيير النافذة والنموذج وعدد أنوية المعالج. '
                       '«مقارنة وتصحيح» يعرض نص Whisper ونص Gemini جنباً إلى جنب؛ حفظ النص الصحيح يعلّم Whisper أسماء الأدوية والكلمات التي يخطئ فيها.',
                       'For admin and supervisors: the PBX link status (connected since, last heartbeat, last error, reconnect count) and the "🩺 Test connection" button, '
                       'which checks settings → server reachability → AMI → login → response time → channel driver → the event process → recordings, '
                       'and explains the cause and fix of any fault. The first red step is the cause.\n\n'
                       '"Extensions and phones": every extension and its phone\'s live registration (online / offline / on a call, IP address, response time), '
                       'the staff member mapped to it, and an explanation of any problem (phone off, extension missing from the PBX, extension not mapped to anyone). '
                       '"Map" links an extension to a staff member in our system only and changes nothing in Issabel; a staff member has one extension, so they are moved off their previous one automatically.\n\n'
                       'Local call transcription (Whisper): runs nightly in its window (default 2–6 AM) at low priority; whatever doesn\'t finish '
                       'continues the next night. Pause / resume / stop the current run, change the window, model and CPU cores. '
                       '"Compare and correct" shows Whisper and Gemini side by side; saving the correct text teaches Whisper drug names and words '
                       'it keeps getting wrong.')},
        ],
        'tips': [
            T('«السنترال: متصل» يعني أن السيرفر يستقبل أحداث المكالمات من Issabel. «التحديث اللحظي» يعني اتصال متصفحك بالسيرفر فقط.',
              '"PBX: connected" means the server is receiving call events from Issabel. "Live updates" is only your browser\'s link to the server.'),
            T('لو «التحديث اللحظي» غير متصل أعد تحميل الصفحة.', 'If "Live updates" is disconnected, reload the page.'),
        ],
        'workflows': [],
        'related': ['callcenter.operator', 'omni.wallboard'],
        'tour': [
            {'target': 'callcenter-pbx-tabs', 'label': T('📞 المكالمات · ⚙️ إعدادات السنترال', '📞 Calls · ⚙️ PBX settings'),
             'text': T('المكالمات الحية، وإعدادات الربط مع السنترال.', 'Live calls, and the PBX link settings.'),
             'open_hint': T('التبويبات بتظهر للمدير والمشرف بس.', 'The tabs show for admin and supervisor only.')},
            {'target': 'callcenter-pbx-status', 'label': T('السنترال · التحديث اللحظي', 'PBX · Live updates'),
             'text': T('«السنترال» يعني السيرفر بيستقبل أحداث المكالمات. «التحديث اللحظي» اتصال متصفحك بالسيرفر بس.',
                       '"PBX" means the server receives call events. "Live updates" is only your browser link to the server.'),
             'when': T('لو التحديث اللحظي غير متصل اعمل تحميل للصفحة.', 'If live updates are disconnected, reload the page.'),
             'more': T(
                 '• «متصل»: البيانات بتوصل لحظي.\n• «جاري الاتصال...»: بيحاول يوصل.\n• «غير متصل»: اللي قدامك ممكن يكون قديم — أعد تحميل الصفحة.',
                 '• "Connected": data arrives live.\n• "Connecting...": trying to connect.\n• "Disconnected": what you see may be out of date — reload the page.')},
            {'target': 'callcenter-pbx-active', 'label': T('مكالمات نشطة', 'Active calls'),
             'text': T('كل مكالمة بترن أو متصلة: الحالة والوقت والمتصل والطابور والموظف.', 'Every ringing or connected call: state, timer, caller, queue and agent.'),
             'when': T('اضغط كارت عميل معروف يفتح بطاقته.', 'Click the card of a known customer to open their card.'),
             'more': T(
                 'الرقم جنب العنوان = عدد المكالمات النشطة (رنين، متصل، أو في الطابور).\n• بطاقة العميل فيها الاسم والشريحة وآخر المشتريات والقسائم والحالات المفتوحة ورصيد النقاط — عشان ترد وانت عارف هو مين.',
                 'The number next to the title = active calls (ringing, connected or queued).\n• The customer card shows name, segment, last purchases, vouchers, open cases and points balance — so you answer knowing who it is.')},
            {'target': 'callcenter-pbx-customer', 'label': T('بطاقة العميل', 'Customer card'),
             'text': T('الشريحة ونقاط الولاء وآخر المشتريات والقسائم النشطة والحالات المفتوحة. × يقفلها.',
                       'Segment, loyalty points, last purchases, active vouchers and open cases. × closes it.'),
             'open_hint': T('بتظهر لوحدها مع مكالمة واردة من عميل معروف.', 'Pops up by itself on an incoming call from a known customer.')},
            {'target': 'callcenter-pbx-history', 'label': T('سجل المكالمات الأخيرة', 'Recent calls'),
             'text': T('آخر 50 مكالمة: المتصل والعميل والطابور والموظف والحالة ووقت الانتظار والمكالمة.',
                       'The last 50 calls: caller, customer, queue, agent, state, wait time and talk time.'),
             'when': T('كتير «مهجور» أو انتظار طويل معناه الطابور محتاج موظفين أكتر.', 'Many "Abandoned" or long waits mean the queue needs more agents.'),
             'more': T(
                 'مفيد عشان تشوف المكالمات اللي فاتت ومحدش ردّ عليها وترجع تكلّمهم.\n• مدة «انتظار» طويلة معناها الطابور محتاج موظفين أكتر في الوقت ده.',
                 'Useful to spot missed calls nobody answered so you can call them back.\n• A long "wait" time means the queue needs more agents at that hour.')},
            {'target': 'callcenter-pbx-diagnose', 'label': T('🩺 فحص الاتصال', '🩺 Test connection'),
             'text': T('بيفحص الإعدادات والشبكة وAMI والدخول والأحداث والتسجيلات ويشرح سبب أي عطل. أول خطوة حمرا هي السبب.',
                       'Checks settings, network, AMI, login, events and recordings and explains any fault. The first red step is the cause.'),
             'open_hint': T('تبويب «⚙️ إعدادات السنترال» (مدير أو مشرف).', 'The "⚙️ PBX settings" tab (admin or supervisor).')},
            {'target': 'callcenter-pbx-extensions', 'label': T('التحويلات والهواتف · ربط', 'Extensions and phones · Map'),
             'text': T('حالة كل تحويلة وهاتفها لحظياً والموظف المربوط بيها. «ربط» بيربط التحويلة بموظف عندنا بس، مش في Issabel.',
                       'Each extension and its phone status live, and its staff member. "Map" links it to a staff member here only, not in Issabel.'),
             'warn': T('الربط الغلط بيبعت المكالمات والاتصال لموظف تاني. الموظف بيتنقل من تحويلته القديمة.',
                       'A wrong mapping sends screen pops and dial-outs to the wrong person. The staff member leaves their old extension.'),
             'open_hint': T('تبويب «⚙️ إعدادات السنترال» (مدير أو مشرف).', 'The "⚙️ PBX settings" tab (admin or supervisor).')},
            {'target': 'callcenter-pbx-whisper', 'label': T('تفريغ المكالمات المحلي (Whisper)', 'Local call transcription (Whisper)'),
             'text': T('التفريغ الليلي: ⏸ إيقاف مؤقت، ▶ استئناف، النافذة والنموذج والأنوية. «مقارنة وتصحيح» يعلّمه الكلمات الصح.',
                       'Nightly transcription: ⏸ pause, ▶ resume, window, model and cores. "Compare and correct" teaches it the right words.'),
             'warn': T('«⏹ إيقاف التشغيل الحالي» بيوقف التفريغ الشغّال، والباقي بيكمل الليلة الجاية.', '"⏹ Stop current run" halts the running job; the rest continues the next night.'),
             'open_hint': T('تبويب «⚙️ إعدادات السنترال» (مدير أو مشرف).', 'The "⚙️ PBX settings" tab (admin or supervisor).')},
            {'target': 'callcenter-pbx-header', 'label': T('لوحة المكالمات الحية', 'Live calls board'), 'when': T('لما تحب تتابع المكالمات وهي شغالة.', 'When you want to watch calls as they happen.'),  # from the GitHub-side tour
             'text': T('لوحة المكالمات الحية: تتحدث لحظياً من السنترال.',
                       'The live calls board: updated in real time from the PBX.'),
             'more': T(
                 'مش محتاج تعمل تحديث للصفحة — المكالمات بتظهر وتختفي لوحدها أول ما تحصل.\n• الشاشة دي للمتابعة؛ تسجيل المكالمة نفسه بيتم من شاشة موظف الكول سنتر.',
                 'No need to refresh — calls appear and disappear by themselves as they happen.\n• This screen is for monitoring; the call itself is logged on the operator screen.')},
        ],
        'updated': '2026-10-26',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
    },
]
