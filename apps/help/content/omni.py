from . import T

MODULE = {
    'key': 'omni', 'group': 'callcenter', 'icon': '📥',
    'title': T('التواصل الموحّد (واتساب والمكالمات والسوشيال)', 'Unified communications (WhatsApp, calls, social)'),
    'summary': T(
        'كل قنوات التواصل مع العميل في مكان واحد: رسائل واتساب (عدة أرقام)، المكالمات، ماسنجر، إنستجرام، تيليجرام — مجمّعة لكل عميل في خط زمني واحد مع أحداث SOFTECH (حجوزات، فواتير). '
        'منها: الصندوق الموحد للرد، حسابات القنوات وحالتها، لوحة المشرف الحية، قواعد الأتمتة، وتحليلات التواصل، وحملات واتساب التسويقية.\n'
        'قاعدة واتساب المهمة: بعد آخر رسالة من العميل لديك «نافذة 24 ساعة» للرد بنص حر؛ بعد إغلاقها تُرسل فقط «قوالب» معتمدة.',
        'Every customer channel in one place: WhatsApp messages (several numbers), calls, Messenger, Instagram, Telegram — grouped per customer into one timeline with SOFTECH events (reservations, invoices). '
        'It includes the unified inbox to reply, channel accounts and their health, the live supervisor wallboard, automation rules, communication analytics, and WhatsApp marketing campaigns.\n'
        'The key WhatsApp rule: after the customer\'s last message you have a "24-hour window" to reply with free text; once it closes you can only send approved "templates".'),
    'workflows': [
        {
            'key': 'conversation',
            'title': T('حالة المحادثة', 'Conversation status'),
            'model': 'omni.Conversation', 'field': 'status',
            'states': [
                {'key': 'open', 'label': T('مفتوحة', 'Open'), 'desc': T('محادثة نشطة تحتاج رداً.', 'An active conversation that needs a reply.'), 'next': ['pending', 'snoozed', 'resolved']},
                {'key': 'pending', 'label': T('بانتظار رد', 'Pending'), 'desc': T('ننتظر رد العميل.', 'Waiting for the customer.'), 'next': ['open', 'resolved']},
                {'key': 'snoozed', 'label': T('مؤجلة', 'Snoozed'), 'desc': T('مؤجلة لوقت لاحق وتعود تلقائياً.', 'Postponed; returns automatically.'), 'next': ['open']},
                {'key': 'resolved', 'label': T('محلولة', 'Resolved'), 'desc': T('انتهى الطلب؛ رسالة جديدة من العميل تفتحها مرة أخرى.', 'Request done; a new customer message reopens it.'), 'next': ['open', 'closed']},
                {'key': 'closed', 'label': T('مغلقة', 'Closed'), 'desc': T('أُغلقت نهائياً.', 'Closed for good.')},
            ],
        },
        {
            'key': 'campaign',
            'title': T('مراحل حملة واتساب', 'WhatsApp campaign stages'),
            'model': 'campaigns.WhatsAppCampaign', 'field': 'status',
            'states': [
                {'key': 'draft', 'label': T('مسودة', 'Draft'), 'desc': T('قيد الإعداد.', 'Being set up.'), 'next': ['pending_approval', 'cancelled']},
                {'key': 'pending_approval', 'label': T('بانتظار الموافقة', 'Pending approval'), 'desc': T('أُرسلت للاعتماد.', 'Sent for approval.'), 'next': ['approved', 'rejected']},
                {'key': 'approved', 'label': T('معتمدة', 'Approved'), 'desc': T('جاهزة للإرسال أو الجدولة.', 'Ready to send or schedule.'), 'next': ['scheduled', 'running']},
                {'key': 'scheduled', 'label': T('مجدولة', 'Scheduled'), 'desc': T('ستبدأ في موعدها.', 'Will start on time.'), 'next': ['running', 'cancelled']},
                {'key': 'running', 'label': T('جارية', 'Running'), 'desc': T('تُرسل الآن.', 'Sending now.'), 'next': ['paused', 'completed']},
                {'key': 'paused', 'label': T('موقوفة', 'Paused'), 'desc': T('أُوقفت مؤقتاً.', 'Temporarily stopped.'), 'next': ['running', 'cancelled']},
                {'key': 'completed', 'label': T('مكتملة', 'Completed'), 'desc': T('انتهى الإرسال.', 'Sending finished.')},
                {'key': 'cancelled', 'label': T('ملغاة', 'Cancelled'), 'desc': T('أُلغيت.', 'Cancelled.')},
                {'key': 'rejected', 'label': T('مرفوضة', 'Rejected'), 'desc': T('رُفضت مع سبب.', 'Rejected with a reason.')},
            ],
        },
    ],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول التواصل الموحّد', 'A tour of the unified communications module'),
            'summary': T('من الرد على العميل في الصندوق الموحّد، لقوالب واتساب والحملات، لحد إدارة أرقام القنوات ومتابعة الفريق والأتمتة والتحليلات.',
                         'From replying to customers in the unified inbox, to WhatsApp templates and campaigns, to managing channel numbers, watching the team, automation and analytics.'),
            'roles': ['admin', 'supervisor'],
            'steps': [
                {'target': 'nav-omni-inbox', 'nav': '/omni/inbox',
                 'text': T('نبدأ من «مركز الاتصال» ← «الصندوق الموحد».',
                           'Start at "Call center" → "Unified inbox".'),
                 'more': T('ده المكان اللي الكول سنتر بيشتغل فيه طول اليوم: كل رسائل واتساب والمكالمات والسوشيال في قائمة واحدة.\n'
                           '• أي رسالة أو مكالمة من عميل بتعمل محادثة هنا تلقائياً.\n'
                           '• باقي الشاشات في الجولة بتخدم الصندوق ده: أرقام، قوالب، أتمتة، ومتابعة.',
                           'This is where the call center works all day: every WhatsApp message, call and social message in one list.\n'
                           '• Any customer message or call creates a conversation here automatically.\n'
                           '• The other screens in this tour serve this inbox: numbers, templates, automation and monitoring.')},
                {'target': 'omni-inbox-filters', 'route': '/omni/inbox',
                 'text': T('الفلاتر: «النشطة» شغلك اليومي، و«محادثاتي» المسند ليك.',
                           'Filters: "Active" is your daily work, "My conversations" is what is assigned to you.'),
                 'more': T('ابدأ يومك من «النشطة» (المفتوحة والمنتظرة والمؤجلة).\n'
                           '• «محادثاتي» بيخليك تركّز على اللي مسؤول عنه.\n'
                           '• «المحلولة» و«المغلقة» للرجوع لتاريخ عميل.',
                           'Start your day from "Active" (open, pending and snoozed).\n'
                           '• "My conversations" lets you focus on what you own.\n'
                           '• "Resolved" and "Closed" are for looking back at a customer\'s history.')},
                {'target': 'omni-inbox-list', 'route': '/omni/inbox',
                 'text': T('كل عميل سطر واحد مهما كلّمنا من كام قناة.',
                           'Each customer is one row, however many channels they used.'),
                 'more': T('الأيقونة بتوضح القناة اللي بدأت منها المحادثة، والأحدث نشاطاً فوق.\n'
                           '• القائمة بتتحدّث لوحدها كل شوية.\n'
                           '• اضغط سطر عشان تفتح الخط الزمني بتاعه في النص.',
                           'The icon shows the channel the conversation started on; the most recent activity is on top.\n'
                           '• The list refreshes by itself.\n'
                           '• Click a row to open its timeline in the middle.')},
                {'target': 'omni-inbox-timeline', 'route': '/omni/inbox',
                 'text': T('الخط الزمني: الرسائل والمكالمات وأحداث الحجوزات والفواتير، والرد من تحت.',
                           'The timeline: messages, calls, reservation and invoice events, and the reply box below.'),
                 'more': T('اقرا كل اللي فات قبل ما ترد — آخر حجز وفاتورة للعميل باينين.\n'
                           '• الرد بيروح من نفس الرقم اللي العميل كلّمه عليه، طول ما نافذة الـ 24 ساعة مفتوحة.\n'
                           '• على اليمين «إدارة المحادثة»: خلّيها «محلولة» لما تخلص، والتغيير بيتسجّل باسمك.',
                           'Read everything before replying — the customer\'s last reservation and invoice are visible.\n'
                           '• The reply goes from the same number the customer wrote to, while the 24-hour window is open.\n'
                           '• On the side, "Conversation management": set it to "Resolved" when done; the change is logged under your name.')},
                {'target': 'nav-whatsapp-inbox', 'nav': '/whatsapp/inbox',
                 'text': T('لو النافذة مقفولة: «صندوق واتساب» للقوالب المعتمدة.',
                           'If the window is closed: "WhatsApp inbox" for approved templates.'),
                 'more': T('بعد 24 ساعة من آخر رسالة للعميل، واتساب مبيسمحش بنص حر.\n'
                           '• من صندوق واتساب تقدر تبعت «قالب» معتمد مسبقاً (زي تذكير أو إشعار جاهزية).\n'
                           '• أول ما العميل يرد، النافذة بتتفتح وترجع ترد عادي من الصندوق الموحّد.',
                           'Once 24 hours pass since the customer\'s last message, WhatsApp does not allow free text.\n'
                           '• From the WhatsApp inbox you can send a pre-approved "template" (e.g. a reminder or ready notice).\n'
                           '• As soon as the customer replies, the window reopens and you reply normally from the unified inbox.')},
                {'target': 'omni-whatsapp-inbox-list', 'route': '/whatsapp/inbox',
                 'text': T('النقطة الخضرا = تقدر ترد بنص، والحمرا = قالب بس.',
                           'Green dot = you can reply with text; red = template only.'),
                 'more': T('افتح المحادثة؛ لو النافذة مقفولة هتلاقي زرار «إرسال قالب» في خانة الكتابة.\n'
                           '• تابع علامات التسليم ✓ و✓✓ عشان تتأكد إن الرسالة وصلت.\n'
                           '• ✗ معناها فشلت — جرّب تاني أو اتصل بالعميل.',
                           'Open the conversation; if the window is closed you get a "Send template" button in the compose area.\n'
                           '• Watch the ✓ and ✓✓ marks to make sure the message arrived.\n'
                           '• ✗ means it failed — try again or call the customer.')},
                {'target': 'nav-campaigns', 'nav': '/campaigns',
                 'text': T('رسائل لشريحة عملاء كاملة: «حملات واتساب».',
                           'Messages to a whole customer segment: "WhatsApp campaigns".'),
                 'more': T('الحملة بتبعت رسالة واحدة لمجموعة عملاء (مثلاً مرضى السكري، أو اللي مشتروش من 60 يوم).\n'
                           '• العملاء والشرائح جايين من موديول العملاء.\n'
                           '• كل حملة لازم تتعتمد قبل ما تتبعت.',
                           'A campaign sends one message to a group of customers (e.g. diabetic patients, or those who have not bought in 60 days).\n'
                           '• Customers and segments come from the customers module.\n'
                           '• Every campaign must be approved before it is sent.')},
                {'target': 'omni-campaigns-new', 'route': '/campaigns',
                 'text': T('«+ حملة جديدة»: النص والجمهور ومعاينته، وبعدين الحفظ كمسودة.',
                           '"+ New campaign": text, audience and its preview, then save as a draft.'),
                 'more': T('اكتب النص بمتغيرات زي اسم العميل، وحدد الجمهور، واضغط «معاينة الجمهور» تشوف كام عميل هيوصله.\n'
                           '• الحفظ مش بيبعت حاجة — بيعمل مسودة.\n'
                           '• بعدها «📤 طلب الموافقة» من شريط الإجراءات.',
                           'Write the text with variables such as the customer name, set the audience, and press "Preview audience" to see how many it reaches.\n'
                           '• Saving does not send anything — it creates a draft.\n'
                           '• Then "📤 Request approval" from the action bar.')},
                {'target': 'omni-campaigns-status-tabs', 'route': '/campaigns',
                 'text': T('تابع مراحل الحملة: مسودة ← بانتظار الموافقة ← معتمدة ← جارية ← مكتملة.',
                           'Follow the campaign stages: draft → pending approval → approved → running → completed.'),
                 'more': T('المعتمِد يراجع «بانتظار الموافقة» ويضغط «✅ اعتماد» أو «❌ رفض» بسبب.\n'
                           '• بعد الاعتماد: «جدولة الإرسال» بموعد أو «إرسال فوري».\n'
                           '• تبويب «الرسائل» جوه الحملة بيوضح مين وصله ومين فشل.',
                           'The approver reviews "Pending approval" and presses "✅ Approve" or "❌ Reject" with a reason.\n'
                           '• After approval: "Schedule sending" at a time, or "Send now".\n'
                           '• The "Messages" tab inside the campaign shows who was reached and who failed.')},
                {'target': 'nav-omni-accounts', 'nav': '/omni/accounts',
                 'text': T('«حسابات القنوات»: أرقام واتساب والسنترال والصفحات.',
                           '"Channel accounts": WhatsApp numbers, PBX and pages.'),
                 'more': T('كل رقم بيستقبل رسائل لازم يكون متسجّل هنا — هو اللي بيغذّي الصندوق الموحّد.\n'
                           '• لو رقم وقع، رسائل العملاء عليه مش هتوصل.\n'
                           '• الشاشة للمدير والمشرفين.',
                           'Every number that receives messages must be registered here — it feeds the unified inbox.\n'
                           '• If a number goes down, customer messages to it will not arrive.\n'
                           '• The screen is for admins and supervisors.')},
                {'target': 'omni-accounts-header', 'route': '/omni/accounts',
                 'text': T('راجع كام حساب «متصل» من الإجمالي كل يوم.',
                           'Check daily how many accounts are "connected" out of the total.'),
                 'more': T('لو العدد ناقص، دوّر على البطاقة «منقطع» أو «متدهور» واضغط «🩺 فحص الاتصال».\n'
                           '• كل بطاقة بتوضح حمل الرقم وغير المقروء فيه.\n'
                           '• «+ حساب جديد» لإضافة رقم فرع جديد.',
                           'If the count is short, find the "Disconnected" or "Degraded" card and press "🩺 Check connection".\n'
                           '• Each card shows the number\'s load and unread count.\n'
                           '• "+ New account" adds a new branch number.')},
                {'target': 'omni-wallboard-kpis', 'route': '/omni/wallboard',
                 'text': T('«لوحة المشرف»: المكالمات والمهجورة والانتظار والمحادثات غير المُسندة لحظة بلحظة.',
                           '"Supervisor board": calls, abandoned, waiting and unassigned conversations live.'),
                 'more': T('اللوحة بتتحدّث كل 5 ثواني — سيبها مفتوحة وقت الشيفت.\n'
                           '• تحت الأرقام: المكالمات الجارية مع «🎧 استماع» و«🗣️ همس»، والقوائم، وحالة كل موظف.\n'
                           '• لو «غير مُسندة» بتزيد، ارجع للصندوق الموحّد ووزّع المحادثات.',
                           'The board refreshes every 5 seconds — keep it open during the shift.\n'
                           '• Below the numbers: live calls with "🎧 Listen" and "🗣️ Whisper", the queues, and each agent\'s state.\n'
                           '• If "Unassigned" grows, go back to the unified inbox and hand out conversations.')},
                {'target': 'omni-automations-new', 'route': '/omni/automations',
                 'text': T('«الأتمتة»: قواعد بتشتغل لوحدها على كل محادثة.',
                           '"Automation": rules that run by themselves on every conversation.'),
                 'more': T('«+ قاعدة جديدة»: عند حدوث (رسالة، مكالمة فائتة، حجز…) + شروط ← إجراءات زي الأولوية أو إشعار مشرف أو رد آلي.\n'
                           '• مثال: مكالمة فائتة ← إشعار للكول سنتر عشان يرجّع الاتصال.\n'
                           '• الرد الآلي بيوصل للعميل فوراً، فجرّب القاعدة بحرص.',
                           '"+ New rule": when (message, missed call, reservation…) + conditions → actions such as priority, notify a supervisor or auto-reply.\n'
                           '• Example: missed call → notify the call center to call back.\n'
                           '• An auto-reply reaches the customer instantly, so test the rule carefully.')},
                {'target': 'omni-analytics-kpis', 'route': '/omni/analytics',
                 'text': T('«تحليلات التواصل»: كام محادثة تحوّلت لحجز وسرعة أول رد.',
                           '"Communication analytics": how many conversations became reservations and first-response speed.'),
                 'more': T('هنا بتقيس نتيجة كل اللي فات: نسبة التحويل لحجز، ومتوسط أول رد، والحجم حسب القناة ونشاط الموظفين.\n'
                           '• اختار 7 أو 30 أو 90 يوم من فوق.\n'
                           '• الحجوزات اللي بتتعمل من المحادثات بتكمّل في موديول الحجوزات.',
                           'Here you measure the result of everything above: conversion to reservations, average first response, volume by channel and staff activity.\n'
                           '• Pick 7, 30 or 90 days at the top.\n'
                           '• Reservations made from conversations continue in the reservations module.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'omni.inbox',
        'routes': ['/omni/inbox'],
        'title': T('الصندوق الموحّد', 'Unified inbox'),
        'summary': T('ثلاثة أعمدة: قائمة المحادثات من كل القنوات، الخط الزمني الموحّد للعميل (رسائل، مكالمات مع تفريغها النصي، أحداث SOFTECH)، وملف العميل 360 مع إدارة المحادثة (الحالة، الإسناد).',
                     'Three columns: the conversation list across channels, the customer\'s unified timeline (messages, calls with transcripts, SOFTECH events), and the customer 360 panel with conversation controls (status, assignment).'),
        'audience': T('الكول سنتر والمشرفون.', 'Call center and supervisors.'),
        'tabs': [
            {'key': 'active', 'title': T('النشطة', 'Active'), 'body': T('المفتوحة والمنتظرة والمؤجلة — قائمة العمل اليومية.', 'Open, pending and snoozed — the daily worklist.')},
            {'key': 'all', 'title': T('الكل', 'All'), 'body': T('كل المحادثات.', 'Every conversation.')},
            {'key': 'resolved', 'title': T('المحلولة', 'Resolved'), 'body': T('المحادثات التي انتهى طلبها.', 'Conversations whose request is done.')},
            {'key': 'closed', 'title': T('المغلقة', 'Closed'), 'body': T('المحادثات المغلقة نهائياً.', 'Closed conversations.')},
        ],
        'steps': [
            T('فعّل «محادثاتي» لترى المسند لك، وابحث بالاسم أو الرقم.', 'Turn on "My conversations" to see yours, and search by name or number.'),
            T('اقرأ الخط الزمني كاملاً قبل الرد — آخر حجز وفاتورة للعميل ظاهرة.', 'Read the whole timeline before replying — the customer\'s last reservation and invoice are shown.'),
            T('«مساعد الذكاء الاصطناعي» يلخص المحادثة ويقيّم الإلحاح ويقترح ردوداً تضغطها لاستخدامها (راجعها قبل الإرسال).', '"AI assistant" summarises the chat, rates urgency and suggests replies you click to use (review before sending).'),
            T('اكتب الرد عبر قناة المحادثة؛ لو نافذة الـ 24 ساعة مغلقة أرسل قالباً.', 'Reply through the conversation\'s channel; if the 24-hour window is closed, send a template.'),
            T('غيّر الحالة إلى «محلولة» عند الانتهاء، أو أسندها لزميل.', 'Set the status to "Resolved" when done, or assign it to a colleague.'),
        ],
        'workflows': ['conversation'],
        'related': ['omni.accounts', 'callcenter.operator', 'omni.whatsapp_inbox'],
        'tour': [
            {'target': 'omni-inbox-search', 'text': T('ابحث بالاسم أو الرقم.',
                                              'Search by name or number.'),
             'more': T('اكتب جزء من اسم العميل أو رقم تليفونه والقائمة بتتصفّى وانت بتكتب.\n'
                       '• مفيد لما عميل يتصل يسأل عن رسالة بعتها، فتلاقي محادثته بسرعة.\n'
                       '• البحث بيشتغل مع الفلتر المختار تحت (النشطة، الكل…)، فلو مش لاقيه جرّب «الكل».',
                       'Type part of the customer\'s name or phone number and the list filters as you type.\n'
                       '• Handy when a customer calls about a message they sent, so you find the chat fast.\n'
                       '• Search works together with the filter below (Active, All…), so if you cannot find it try "All".')},
            {'target': 'omni-inbox-filters', 'text': T('النشطة، الكل، المحلولة، المغلقة، أو محادثاتي.',
                                              'Active, all, resolved, closed, or my conversations.'),
             'more': T('«النشطة» هي شغلك اليومي: المفتوحة والمنتظرة والمؤجلة.\n'
                       '• «المحلولة» و«المغلقة» للرجوع لمحادثات خلصت، و«الكل» بيعرض كل حاجة.\n'
                       '• «محادثاتي» زرار تشغيل/إيقاف بيعرض بس المحادثات المسندة ليك، ويشتغل مع أي فلتر.',
                       '"Active" is your daily work: open, pending and snoozed.\n'
                       '• "Resolved" and "Closed" are for looking back at finished chats; "All" shows everything.\n'
                       '• "My conversations" is an on/off toggle that shows only chats assigned to you, together with any filter.')},
            {'target': 'omni-inbox-list', 'text': T('المحادثات من كل القنوات.',
                                              'Conversations from every channel.'),
             'more': T('كل سطر عميل واحد، والأيقونة بتقول القناة (💬 واتساب، ☎️ مكالمات، ماسنجر، إنستجرام، تيليجرام).\n'
                       '• تحت الاسم آخر رسالة أو حدث، وجنبه الوقت وحالة المحادثة.\n'
                       '• الأحدث نشاطاً فوق، والقائمة بتتحدّث لوحدها كل شوية. اضغط سطر عشان تفتحه في النص.',
                       'Each row is one customer; the icon shows the channel (💬 WhatsApp, ☎️ calls, Messenger, Instagram, Telegram).\n'
                       '• Under the name is the last message or event, with the time and the conversation status beside it.\n'
                       '• The most recently active is on top and the list refreshes by itself. Click a row to open it in the middle.')},
            {'target': 'omni-inbox-timeline', 'text': T('المحادثة المختارة.',
                                              'The selected conversation.'),
             'more': T('هنا الخط الزمني الموحّد للعميل: الرسائل الواردة والصادرة، المكالمات (والفائتة بالأحمر)، وأحداث زي الحجوزات والفواتير.\n'
                       '• المكالمة المسجّلة ليها مشغّل صوت وزرار 📝 للتفريغ النصي.\n'
                       '• فوق بيظهر هل النافذة مفتوحة أو مغلقة، وتحت «✨ مساعد الذكاء الاصطناعي» بيلخص ويقترح ردود — راجعها قبل ما تبعت.',
                       'This is the customer\'s unified timeline: incoming and outgoing messages, calls (missed ones in red), and events such as reservations and invoices.\n'
                       '• A recorded call has an audio player and a 📝 button for a text transcript.\n'
                       '• At the top you see whether the window is open or closed; below, "✨ AI assistant" summarises and suggests replies — review them before sending.')},
            {'target': 'omni-inbox-reply', 'text': T('اكتب الرد — بيتبعت على نفس القناة.',
                                              'Write the reply — it goes out on the same channel.'),
             'more': T('اكتب واضغط Enter أو ↑ — الرد بيروح من نفس رقم الشركة اللي العميل كلّمه عليه.\n'
                       '• لو نافذة الـ 24 ساعة مقفولة الخانة بتتقفل؛ ابعت قالب معتمد من «صندوق واتساب».\n'
                       '• لو المحادثة مكالمات بس من غير قناة رسائل، هتلاقي رابط «المكالمات الحية» بدل خانة الكتابة.',
                       'Type and press Enter or ↑ — the reply goes from the same company number the customer wrote to.\n'
                       '• If the 24-hour window is closed the box is locked; send an approved template from "WhatsApp inbox".\n'
                       '• If the conversation is calls only with no messaging channel, you get a "Live calls" link instead of the box.')},
            {'target': 'omni-inbox-manage', 'text': T('حالة المحادثة والمسؤول عنها.',
                                              'The conversation\'s status and assignee.'),
             'more': T('غيّر الحالة من القائمة: مفتوحة، بانتظار رد، مؤجلة، محلولة، أو مغلقة — التغيير بيتسجّل في الخط الزمني باسمك.\n'
                       '• خلّيها «محلولة» لما الطلب يخلص؛ لو العميل بعت تاني بتتفتح من جديد.\n'
                       '• «موكلة إلى» بيوضح مين ماسكها. تحتها ملف العميل وآخر حجوزاته و«الملف الكامل ←».',
                       'Change the status from the list: open, pending, snoozed, resolved or closed — the change is logged in the timeline under your name.\n'
                       '• Set it to "Resolved" when the request is done; a new customer message reopens it.\n'
                       '• "Assigned to" shows who owns it. Below are the customer card, recent reservations and "Full profile ←".')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'omni.accounts',
        'routes': ['/omni/accounts'],
        'title': T('حسابات القنوات', 'Channel accounts'),
        'summary': T('كل أرقام واتساب والسنترال وصفحات السوشيال للشركة مع حالتها (متصل، منقطع، متدهور، بانتظار QR)، آخر نبضة، حمل كل رقم (المحادثات، الوارد اليوم، غير المقروء)، وإدارة بيانات الربط لكل حساب.',
                     'Every company WhatsApp number, PBX and social page with its status (connected, disconnected, degraded, waiting for QR), last heartbeat, per-number load (conversations, inbound today, unread), and credential management per account.'),
        'audience': T('المدير والمشرفون.', 'Admins and supervisors.'),
        'steps': [
            T('«حساب جديد»: القناة، المزوّد، اسم الحساب (مثال: واتساب فرع المعادي 1)، الرقم، القسم والفروع، وهل هو الافتراضي للإرسال.', '"New account": channel, provider, account name (e.g. WhatsApp Maadi branch 1), number, department and branches, and whether it is the default sender.'),
            T('«فحص الاتصال» للتأكد من عمل الحساب.', '"Check connection" to confirm the account works.'),
        ],
        'workflows': [],
        'related': ['omni.inbox'],
        'tour': [
            {'target': 'omni-accounts-header', 'text': T('حسابات القنوات مع عدد الحسابات والمتصل منها.',
                                              'The channel accounts, with how many exist and how many are connected.'),
             'more': T('السطر ده بيقولك بسرعة عندك كام حساب وكام منهم «متصل» دلوقتي.\n'
                       '• لو المتصل أقل من العدد الكلي، فيه رقم أو صفحة مش بيستقبل رسائل — دوّر على البطاقة الحمرا أو الصفرا تحت.\n'
                       '• الصفحة بتتحدّث لوحدها كل 30 ثانية تقريباً.',
                       'This line tells you at a glance how many accounts you have and how many are "connected" right now.\n'
                       '• If connected is less than the total, a number or page is not receiving messages — look for the red or yellow card below.\n'
                       '• The page refreshes by itself about every 30 seconds.')},
            {'target': 'omni-accounts-new', 'text': T('«+ حساب جديد» لإضافة رقم واتساب أو سنترال أو صفحة.',
                                              '"+ New account" adds a WhatsApp number, PBX or page.'),
             'more': T('بيفتح نموذج فيه: القناة، المزوّد، اسم الحساب، الرقم/المعرف، Phone Number ID، Access Token، القسم، و«الحساب الافتراضي للإرسال».\n'
                       '• الاسم والرقم إجباريين، و«حفظ» مش بيشتغل من غيرهم.\n'
                       '• التوكن سري — بيتحفظ مشفّر ومش بيظهر تاني؛ لو سبته فاضي بيستخدم الإعداد الافتراضي للسيرفر.',
                       'Opens a form with: channel, provider, account name, number/handle, Phone Number ID, Access Token, department, and "Default sending account".\n'
                       '• Name and number are required; "Save" does not work without them.\n'
                       '• The token is secret — it is stored encrypted and never shown again; left empty, the server\'s default setting is used.')},
            {'target': 'omni-accounts-grid', 'text': T('بطاقة لكل حساب: الاسم، الرقم، المزوّد، آخر نبضة والفرع.',
                                              'One card per account: name, number, provider, last heartbeat and branch.'),
             'more': T('كل رقم أو صفحة للشركة ليها بطاقة. «افتراضي» جنب الاسم معناه إن الإرسال بيطلع منه لو مفيش رقم محدد.\n'
                       '• «نبضة» = آخر مرة الحساب أكّد إنه شغال؛ لو بقالها كتير يبقى فيه مشكلة اتصال.\n'
                       '• «🔐 اعتماد خاص» معناه إن له توكن خاص بيه، والفرع مكتوب تحت («كل الفروع» لو مش مربوط بفرع).',
                       'Every company number or page has a card. "Default" next to the name means sending goes from it when no number is specified.\n'
                       '• "Heartbeat" = the last time the account confirmed it works; if it is old, there is a connection problem.\n'
                       '• "🔐 Own credentials" means it has its own token; the branch is shown at the bottom ("All branches" if not tied to one).')},
            {'target': 'omni-accounts-status', 'text': T('حالة الحساب: متصل أو منقطع أو متدهور أو بانتظار QR.',
                                              'The account status: connected, disconnected, degraded or waiting for QR.'),
             'more': T('• 🟢 «متصل»: شغال طبيعي.\n'
                       '• 🔴 «منقطع»: مش بيستقبل ولا بيبعت — بلّغ المسؤول فوراً، رسائل العملاء ممكن تضيع.\n'
                       '• 🟡 «متدهور»: شغال بس فيه مشاكل. ⚪ «بانتظار QR»: الرقم محتاج يتربط من الموبايل.',
                       '• 🟢 "Connected": working normally.\n'
                       '• 🔴 "Disconnected": not receiving or sending — tell the admin straight away, customer messages may be missed.\n'
                       '• 🟡 "Degraded": working with problems. ⚪ "Waiting for QR": the number must be linked from the phone.')},
            {'target': 'omni-accounts-load', 'text': T('حمل الحساب: المحادثات، رسائل اليوم، الوارد اليوم وغير المقروء.',
                                              'The account load: conversations, messages today, inbound today and unread.'),
             'more': T('أربع أرقام توضّح الرقم ده عليه شغل قد إيه: عدد المحادثات، رسائل النهارده، الوارد النهارده، وغير المقروء.\n'
                       '• لو «غير مقروء» عالي في رقم معيّن، وزّع ناس أكتر عليه أو راجع الصندوق الموحّد.\n'
                       '• بتساعدك تقارن الفروع والأرقام ببعض.',
                       'Four numbers show how busy this account is: conversations, messages today, inbound today and unread.\n'
                       '• If "Unread" is high on one number, put more people on it or check the unified inbox.\n'
                       '• They help you compare branches and numbers with each other.')},
            {'target': 'omni-accounts-actions', 'text': T('«✏️ تعديل» لبيانات الحساب، و«🩺 فحص الاتصال» لحسابات واتساب فقط.',
                                              '"✏️ Edit" for the account details, and "🩺 Check connection" for WhatsApp accounts only.'),
             'more': T('«✏️ تعديل» بيفتح نفس النموذج؛ القناة مبتتغيرش، ولو سبت التوكن فاضي بيفضل القديم.\n'
                       '• «🩺 فحص الاتصال» بيسأل واتساب حالاً وبيعرض النتيجة في شريط فوق (✅ متصل مع الجودة، أو ❌ والسبب).\n'
                       '• من التعديل تقدر تشيل علامة «نشط» عشان توقف الحساب.',
                       '"✏️ Edit" opens the same form; the channel cannot change, and an empty token keeps the old one.\n'
                       '• "🩺 Check connection" asks WhatsApp right now and shows the result in a bar at the top (✅ connected with quality, or ❌ and the reason).\n'
                       '• From Edit you can untick "Active" to stop the account.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'omni.wallboard',
        'routes': ['/omni/wallboard'],
        'title': T('لوحة المشرف الحية', 'Live supervisor wallboard'),
        'summary': T('تتحدث كل 5 ثوانٍ: المكالمات الجارية مع «استماع صامت» و«همس للعامل دون سماع العميل»، إحصاءات القوائم اليوم (مُجابة، مهجورة، متوسط الانتظار والحديث)، حالة العمال، حمل واتساب، والمحادثات غير المُسندة.',
                     'Refreshes every 5 seconds: active calls with "silent listen" and "whisper to the agent without the customer hearing", today\'s queue stats (answered, abandoned, average wait and talk), agent states, WhatsApp load, and unassigned conversations.'),
        'audience': T('المشرفون والمدير والجودة.', 'Supervisors, admins and quality.'),
        'workflows': [],
        'related': ['callcenter.analytics', 'callcenter.pbx'],
        'tour': [
            {'target': 'omni-wallboard-header', 'text': T('لوحة المشرف الحية، تتحدث تلقائياً كل 5 ثوانٍ.',
                                              'The live supervisor board; refreshes automatically every 5 seconds.'),
             'more': T('سيبها مفتوحة على شاشة جنبك وقت الشغل — مش محتاج تعمل تحديث، الأرقام بتتجدد كل 5 ثواني.\n'
                       '• اللوحة للمشرفين والمدير والجودة بس؛ غيرهم بيشوف رسالة «لوحة المشرفين فقط».\n'
                       '• نتيجة الاستماع أو الهمس بتظهر في شريط تحت العنوان.',
                       'Keep it open on a screen beside you during the shift — no need to refresh, numbers update every 5 seconds.\n'
                       '• The board is for supervisors, admins and quality only; others see "Supervisors only".\n'
                       '• The result of a listen or whisper request appears in a bar under the title.')},
            {'target': 'omni-wallboard-kpis', 'text': T('أرقام اليوم: الجارية، المُجابة، المهجورة، متوسط الانتظار، العمال المتصلون والمحادثات غير المُسندة.',
                                              'Today\'s numbers: live, answered, abandoned, average wait, online agents and unassigned conversations.'),
             'more': T('• «مهجورة» بالأحمر = عملاء قفلوا قبل ما حد يرد — لو بتزيد محتاج ناس أكتر على التليفون.\n'
                       '• «متوسط الانتظار» دقايق:ثواني، و«عمال متصلون» = المسجّلين من الإجمالي.\n'
                       '• «غير مُسندة» بالبرتقالي لما يكون فيه محادثات محدش ماسكها — وزّعها من الصندوق الموحّد.',
                       '• "Abandoned" in red = customers who hung up before anyone answered — if it grows you need more people on the phones.\n'
                       '• "Average wait" is minutes:seconds, and "Online agents" = registered out of the total.\n'
                       '• "Unassigned" turns orange when chats have no owner — hand them out from the unified inbox.')},
            {'target': 'omni-wallboard-live', 'text': T('المكالمات الجارية؛ للمُجابة منها «🎧 استماع» صامت أو «🗣️ همس» للعامل.',
                                              'Live calls; answered ones offer silent "🎧 Listen" or "🗣️ Whisper" to the agent.'),
             'more': T('لكل مكالمة: المتصل، الحالة (يرن، في الانتظار، جارية…)، القائمة، العامل والمدة.\n'
                       '• «🎧 استماع» بيرن على تحويلتك وانت بتسمع بس؛ «🗣️ همس» العامل يسمعك والعميل لأ — مفيد لتوجيه موظف جديد.\n'
                       '• لازم تكون تحويلتك مربوطة بحسابك، وإلا هيظهر لك خطأ. فوق الجدول حالة أرقام واتساب وغير المقروء.',
                       'For each call: caller, state (ringing, queued, answered…), queue, agent and duration.\n'
                       '• "🎧 Listen" rings your extension and you only listen; "🗣️ Whisper" lets the agent hear you but not the customer — useful for coaching a new hire.\n'
                       '• Your extension must be linked to your account, otherwise you get an error. Above the table: WhatsApp numbers status and unread.')},
            {'target': 'omni-wallboard-queues', 'text': T('إحصاءات كل قائمة اليوم: المُجابة والمهجورة ومتوسط الانتظار والحديث.',
                                              'Each queue today: answered, abandoned, average wait and talk time.'),
             'more': T('كل قائمة انتظار في السنترال ليها سطر: الإجمالي، المُجابة (أخضر)، المهجورة (أحمر)، متوسط الانتظار ومتوسط الحديث.\n'
                       '• قارن القوائم ببعض: قائمة انتظارها طويل ومهجورها عالي محتاجة دعم.\n'
                       '• الأرقام من أول النهارده بس.',
                       'Each PBX queue has a row: total, answered (green), abandoned (red), average wait and average talk time.\n'
                       '• Compare queues: one with long waits and many abandoned calls needs support.\n'
                       '• Numbers cover today only.')},
            {'target': 'omni-wallboard-agents', 'text': T('حالة كل عامل: في مكالمة أو متاح أو غير مسجل.',
                                              'Each agent\'s state: on a call, available or not registered.'),
             'more': T('بطاقة لكل تحويلة: الاسم ورقم التحويلة والحالة.\n'
                       '• 📞 «في مكالمة» بالأخضر، 🟢 «متاح» جاهز يرد، ⚪ «غير مسجل» تليفونه مش متصل بالسنترال.\n'
                       '• لو موظف في الشيفت وظاهر «غير مسجل»، اطلب منه يتأكد إن التليفون أو التطبيق شغال.',
                       'A card per extension: name, extension number and state.\n'
                       '• 📞 "On a call" in green, 🟢 "Available" ready to answer, ⚪ "Not registered" means the phone is not connected to the PBX.\n'
                       '• If someone on shift shows "Not registered", ask them to check their phone or app is running.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'omni.automations',
        'routes': ['/omni/automations'],
        'title': T('قواعد الأتمتة', 'Automation rules'),
        'summary': T('قواعد بدون برمجة: «عند حدوث» (رسالة واردة، مكالمة، مكالمة فائتة، حجز، تحليل ذكي) + «الشروط» (كلمات مفتاحية، عملاء VIP، قناة) ← «الإجراءات» بالترتيب (ضبط الأولوية أو الحالة، إضافة وسم، إسناد لدور، إشعار دور، ملاحظة، رد آلي).',
                     'No-code rules: "when" (incoming message, call, missed call, reservation, AI analysis) + "conditions" (keywords, VIP customers, channel) → "actions" in order (set priority or status, add a tag, assign to a role, notify a role, add a note, auto-reply).'),
        'audience': T('المدير والمشرفون.', 'Admins and supervisors.'),
        'tips': [T('جرّب القاعدة على عدد قليل قبل تعميمها؛ الرد الآلي يصل للعميل فوراً.', 'Try a rule on a few cases before relying on it; an auto-reply reaches the customer immediately.')],
        'workflows': [],
        'tour': [
            {'target': 'omni-automations-header', 'text': T('قواعد الأتمتة وعددها.',
                                              'The automation rules and how many there are.'),
             'more': T('القواعد دي بتشتغل لوحدها على كل محادثة من غير ما حد يضغط حاجة — زي «لو رسالة فيها كلمة شكوى، خلّيها عاجلة وبلّغ المشرف».\n'
                       '• الصفحة دي للمدير والمشرفين بس.\n'
                       '• الرقم تحت العنوان = عدد القواعد كلها (المفعّلة والمعطّلة).',
                       'These rules run by themselves on every conversation without anyone clicking — e.g. "if a message contains complaint, make it urgent and notify the supervisor".\n'
                       '• This page is for admins and supervisors only.\n'
                       '• The number under the title = all rules (enabled and disabled).')},
            {'target': 'omni-automations-new', 'text': T('«+ قاعدة جديدة»: «عند حدوث» ثم الشروط ثم الإجراءات بالترتيب.',
                                              '"+ New rule": a "when" event, then conditions, then actions in order.'),
             'more': T('• «عند حدوث»: رسالة واردة، مكالمة، مكالمة فائتة، حجز، أو تحليل ذكي.\n'
                       '• الشروط (لازم كلها تتحقق): كلمات مفتاحية مفصولة بفاصلة، «عملاء VIP فقط»، والقناة.\n'
                       '• الإجراءات بالترتيب: أولوية، حالة، وسم، إسناد لدور، إشعار دور، ملاحظة، أو «رد آلي» — الرد الآلي بيوصل للعميل فوراً، فاكتبه بعناية.',
                       '• "When": incoming message, call, missed call, reservation, or AI analysis.\n'
                       '• Conditions (all must match): comma-separated keywords, "VIP customers only", and the channel.\n'
                       '• Actions in order: priority, status, tag, assign to role, notify role, note, or "auto-reply" — an auto-reply reaches the customer instantly, so write it carefully.')},
            {'target': 'omni-automations-list', 'text': T('القواعد الحالية؛ المعطّلة مكتوب بجانبها «(معطّلة)».',
                                              'The current rules; disabled ones are marked "(disabled)".'),
             'more': T('كل بطاقة قاعدة واحدة باسمها. القاعدة المعطّلة بتفضل محفوظة بس مبتشتغلش.\n'
                       '• استخدم أسماء واضحة («شكاوى واتساب → مشرف») عشان أي حد يفهم القاعدة بتعمل إيه.\n'
                       '• لو قاعدتين بيعملوا نفس الحاجة، عطّل واحدة عشان الإجراء ميتكررش.',
                       'Each card is one rule by name. A disabled rule stays saved but does not run.\n'
                       '• Use clear names ("WhatsApp complaints → supervisor") so anyone understands what the rule does.\n'
                       '• If two rules do the same thing, disable one so the action is not repeated.')},
            {'target': 'omni-automations-summary', 'text': T('لكل قاعدة: الحدث، عدد الإجراءات، وكم مرة نُفّذت.',
                                              'For each rule: the event, number of actions, and how many times it ran.'),
             'more': T('«عند: …» الحدث اللي بيشغّلها، وبعده عدد الإجراءات، و«نُفّذت X مرة».\n'
                       '• عدّاد التنفيذ بيقولك القاعدة شغالة فعلاً ولا لأ: لو صفر بعد أيام راجع الكلمات المفتاحية أو الشروط.\n'
                       '• لو بيزيد بسرعة غريبة، ممكن الشروط واسعة زيادة.',
                       '"When: …" is the triggering event, then the number of actions and "ran X times".\n'
                       '• The run counter tells you if the rule actually works: still zero after days → review the keywords or conditions.\n'
                       '• If it climbs oddly fast, the conditions may be too broad.')},
            {'target': 'omni-automations-actions', 'text': T('زر الحالة يفعّل أو يعطّل القاعدة، و✏️ للتعديل و🗑️ للحذف.',
                                              'The status button enables or disables the rule; ✏️ edits and 🗑️ deletes.'),
             'more': T('• زر «مفعّلة/معطّلة» بيقلب الحالة بضغطة واحدة — أسرع وأأمن طريقة توقف بيها قاعدة مؤقتاً.\n'
                       '• ✏️ بيفتح نفس نموذج القاعدة بقيمها الحالية.\n'
                       '• 🗑️ بيسأل «حذف القاعدة؟» وبعدها بتتمسح نهائياً — لو مش متأكد، عطّلها بدل ما تمسحها.',
                       '• The "Enabled/Disabled" button flips the state in one click — the quickest, safest way to pause a rule.\n'
                       '• ✏️ opens the same rule form with its current values.\n'
                       '• 🗑️ asks "Delete rule?" and then removes it for good — if unsure, disable it instead.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'omni.analytics',
        'routes': ['/omni/analytics'],
        'title': T('تحليلات التواصل', 'Communication analytics'),
        'summary': T('لآخر 7/30/90 يوماً: عدد المحادثات وما تحوّل لحجز ونسبة التحويل، متوسط زمن أول رد، الحجم حسب القناة ويومياً، حالات المحادثات، ونشاط الموظفين في الردود.',
                     'For the last 7/30/90 days: conversations, how many became reservations and the conversion rate, average first-response time, volume by channel and by day, conversation statuses, and staff reply activity.'),
        'audience': T('المشرفون والمدير والجودة.', 'Supervisors, admins and quality.'),
        'workflows': [],
        'tour': [
            {'target': 'omni-analytics-period', 'text': T('اختر الفترة: آخر 7 أو 30 أو 90 يوماً.',
                                              'Pick the period: last 7, 30 or 90 days.'),
             'more': T('كل الأرقام والرسوم في الصفحة بتتحسب للفترة اللي تختارها هنا (الافتراضي 30 يوم).\n'
                       '• 7 أيام لمتابعة الأسبوع الحالي، و90 يوم لمقارنة الاتجاه العام.\n'
                       '• الصفحة للمشرفين والمدير والجودة.',
                       'Every number and chart on the page is calculated for the period you pick here (30 days by default).\n'
                       '• 7 days to follow this week, 90 days to see the overall trend.\n'
                       '• The page is for supervisors, admins and quality.')},
            {'target': 'omni-analytics-kpis', 'text': T('المحادثات، ما تحوّل لحجز، نسبة التحويل، ومتوسط أول رد.',
                                              'Conversations, how many became reservations, the conversion rate, and average first response.'),
             'more': T('• «محادثات» = المحادثات اللي اتفتحت في الفترة، و«تحوّلت لحجز» = اللي اتسجّل فيها حجز.\n'
                       '• «نسبة التحويل» = تحوّلت لحجز ÷ المحادثات — مقياس إن التواصل بيجيب بيع.\n'
                       '• «متوسط أول رد» = الوقت من أول رسالة للعميل لحد أول رد مننا؛ كل ما يقلّ أحسن.',
                       '• "Conversations" = those opened in the period; "Became reservations" = those where a reservation was logged.\n'
                       '• "Conversion rate" = became reservations ÷ conversations — a measure of contact turning into sales.\n'
                       '• "Average first response" = time from the customer\'s first message to our first reply; lower is better.')},
            {'target': 'omni-analytics-breakdown', 'text': T('الحجم حسب القناة وتوزيع حالات المحادثات.',
                                              'Volume by channel and the split of conversation statuses.'),
             'more': T('• «الحجم حسب القناة»: عدد الرسائل والمكالمات لكل قناة، وجنبها الوارد منها — يوضح العملاء بيفضّلوا يكلمونا منين.\n'
                       '• «حالات المحادثات»: كام مفتوحة ومنتظرة ومحلولة ومغلقة؛ لو المفتوحة كتير فيه تراكم.\n'
                       '• تحتهم رسم «الحجم اليومي (وارد)» لكل يوم في الفترة.',
                       '• "Volume by channel": messages and calls per channel, with the inbound count beside it — shows where customers prefer to reach us.\n'
                       '• "Conversation statuses": how many are open, pending, resolved and closed; many open ones means a backlog.\n'
                       '• Below them is the "Daily volume (inbound)" chart for each day of the period.')},
            {'target': 'omni-analytics-agents', 'text': T('نشاط الموظفين: عدد الردود الصادرة لكل موظف (يظهر عند وجود بيانات).',
                                              'Staff activity: outbound replies per staff member (shown when there is data).'),
             'more': T('أعلى 15 موظف بعدد الرسائل اللي ردّوا بيها في الفترة.\n'
                       '• بيوضح توزيع الشغل على الفريق — مش مقياس جودة لوحده، الرد الواحد ممكن يكون طويل ومهم.\n'
                       '• استخدمه مع «متوسط أول رد» وأنت بتراجع الأداء.',
                       'The top 15 staff by number of replies sent in the period.\n'
                       '• It shows how work is spread across the team — not a quality measure on its own; one reply may be long and important.\n'
                       '• Use it together with "Average first response" when reviewing performance.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'omni.whatsapp_inbox',
        'routes': ['/whatsapp/inbox'],
        'title': T('صندوق واتساب', 'WhatsApp inbox'),
        'summary': T('محادثات واتساب للأعمال: القائمة يميناً والرسائل يساراً. مؤشر النافذة أخضر = يمكن الرد بنص، أحمر = النافذة مغلقة وتُرسل قالباً معتمداً فقط.',
                     'WhatsApp Business conversations: the list on one side, messages on the other. The window indicator green = you can reply with text, red = closed, send an approved template only.'),
        'audience': T('الكول سنتر والمشرفون.', 'Call center and supervisors.'),
        'tips': [T('الصندوق الموحّد يجمع واتساب مع باقي القنوات — استخدمه للعمل اليومي.', 'The unified inbox combines WhatsApp with the other channels — use it for daily work.')],
        'workflows': [],
        'related': ['omni.inbox'],
        'tour': [
            {'target': 'omni-whatsapp-inbox-search', 'text': T('ابحث برقم أو اسم.',
                                              'Search by number or name.'),
             'more': T('اكتب رقم الواتساب أو اسم العميل والقائمة بتتصفّى على طول.\n'
                       '• الصندوق ده لواتساب بس؛ للشغل اليومي على كل القنوات استخدم «الصندوق الموحّد».\n'
                       '• هنا بتيجي لما تحتاج تبعت قالب معتمد لعميل نافذته مقفولة.',
                       'Type the WhatsApp number or the customer\'s name and the list filters at once.\n'
                       '• This inbox is WhatsApp only; for daily work across all channels use the "Unified inbox".\n'
                       '• Come here when you need to send an approved template to a customer whose window is closed.')},
            {'target': 'omni-whatsapp-inbox-list', 'text': T('محادثات واتساب.',
                                              'The WhatsApp conversations.'),
             'more': T('كل سطر عميل: الاسم والرقم ووقت آخر رسالة.\n'
                       '• النقطة الخضرا = النافذة مفتوحة وتقدر ترد بنص، والحمرا = مقفولة (قالب بس).\n'
                       '• القائمة بتتحدّث لوحدها؛ اضغط سطر عشان تفتح رسائله.',
                       'Each row is a customer: name, number and time of the last message.\n'
                       '• A green dot = window open, you can reply with text; red = closed (template only).\n'
                       '• The list refreshes by itself; click a row to open its messages.')},
            {'target': 'omni-whatsapp-inbox-thread', 'text': T('المحادثة المختارة.',
                                              'The selected conversation.'),
             'more': T('رسايل العميل بالأخضر ورسايلنا بالأبيض، ومعاها علامات التسليم: ○ في الانتظار، ✓ اتبعتت، ✓✓ اتسلّمت/اتقرت، ✗ فشلت.\n'
                       '• لو رسالة فيها ✗ يبقى موصلتش — جرّب تاني أو تواصل بطريقة تانية.\n'
                       '• الرسائل بتتحدّث كل 10 ثواني تقريباً.',
                       'Customer messages in green, ours in white, with delivery marks: ○ pending, ✓ sent, ✓✓ delivered/read, ✗ failed.\n'
                       '• A message with ✗ did not arrive — try again or reach the customer another way.\n'
                       '• Messages refresh about every 10 seconds.')},
            {'target': 'omni-whatsapp-inbox-window', 'text': T('نافذة الـ24 ساعة: لو مقفولة، تقدر تبعت قالب معتمد بس.',
                                              'The 24-hour window: when closed, only an approved template can be sent.'),
             'more': T('دي قاعدة واتساب نفسه مش قاعدتنا: بعد آخر رسالة من العميل عندك 24 ساعة ترد فيها بأي نص.\n'
                       '• «نافذة مفتوحة» بالأخضر = اكتب عادي. «نافذة مغلقة» بالأحمر = خانة الكتابة بتتقفل.\n'
                       '• لما العميل يرد تاني النافذة بتتفتح من جديد.',
                       'This is WhatsApp\'s own rule, not ours: after the customer\'s last message you have 24 hours to reply with any text.\n'
                       '• Green "Window open" = type normally. Red "Window closed" = the text box is locked.\n'
                       '• When the customer writes again the window reopens.')},
            {'target': 'omni-whatsapp-inbox-compose', 'text': T('اكتب رسالتك، أو 📋 لاختيار قالب.',
                                              'Write your message, or 📋 to pick a template.'),
             'more': T('• النافذة مفتوحة: اكتب واضغط Enter أو ↑، أو 📋 لو عايز تبعت قالب.\n'
                       '• النافذة مقفولة: هتلاقي تنبيه أصفر وزرار «إرسال قالب» ← اختار القالب ← «إرسال القالب».\n'
                       '• القوالب معتمدة مسبقاً من واتساب، فمتقدرش تعدّل نصها من هنا.',
                       '• Window open: type and press Enter or ↑, or 📋 to send a template.\n'
                       '• Window closed: a yellow notice with "Send template" → pick the template → "Send template".\n'
                       '• Templates are pre-approved by WhatsApp, so their text cannot be edited here.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'omni.campaigns',
        'routes': ['/campaigns'],
        'title': T('حملات واتساب', 'WhatsApp campaigns'),
        'summary': T('رسائل تسويقية أو توعوية لشريحة عملاء: تحديد الجمهور (شريحة القيمة، خطر الانقطاع، حالة صحية مزمنة، الفرع المفضّل، تاريخ آخر شراء، حد أدنى للقيمة)، نص الرسالة بمتغيرات، معاينة الجمهور، ثم مسار اعتماد قبل الإرسال.',
                     'Marketing or awareness messages to a customer segment: choose the audience (value segment, churn risk, chronic condition, preferred branch, last purchase date, minimum value), the message text with variables, preview the audience, then an approval flow before sending.'),
        'audience': T('الكول سنتر والمشرفون والمشتريات والمدير.', 'Call center, supervisors, purchasing and admins.'),
        'tabs': [
            {'key': 'overview', 'title': T('نظرة عامة', 'Overview'), 'body': T('بيانات الحملة وحالتها وأرقام الإرسال (مُرسلة، مُسلَّمة) وأزرار الاعتماد/الرفض/الجدولة.', 'The campaign\'s data, status and send numbers (sent, delivered) and the approve/reject/schedule buttons.')},
            {'key': 'audience', 'title': T('الجمهور', 'Audience'), 'body': T('شروط الاستهداف والوصول المقدّر وعيّنة من العملاء.', 'Targeting conditions, estimated reach and a sample of customers.')},
            {'key': 'messages', 'title': T('الرسائل', 'Messages'), 'body': T('حالة كل رسالة: في الانتظار، مُرسلة، مُسلّمة، فاشلة، رفض العميل، تم التخطي.', 'Each message\'s status: pending, sent, delivered, failed, opted out, skipped.')},
        ],
        'steps': [
            T('«حملة جديدة» ← الاسم ونص الرسالة (اضغط المتغير لإضافته مثل اسم العميل) ← الجمهور ← «معاينة الجمهور» ← «حفظ الحملة».', '"New campaign" → name and message text (click a variable such as the customer name to insert it) → audience → "Preview audience" → "Save campaign".'),
            T('«طلب الموافقة»؛ بعد الاعتماد «جدولة الإرسال» أو الإرسال يدوياً.', '"Request approval"; once approved, "Schedule sending" or send manually.'),
        ],
        'tips': [T('فعّل «لديهم رقم واتساب مسجّل فقط» حتى لا تضيع رسائل.', 'Turn on "registered WhatsApp number only" so no messages are wasted.')],
        'workflows': ['campaign'],
        'related': ['omni.inbox'],
        'tour': [
            {'target': 'omni-campaigns-new', 'text': T('«+ حملة جديدة» لإنشاء حملة واتساب: النص والجمهور ثم الحفظ.',
                                              '"+ New campaign" creates a WhatsApp campaign: text and audience, then save.'),
             'more': T('بيفتح نموذج: اسم الحملة، نص الرسالة (اضغط متغير زي اسم العميل عشان يتحط في النص)، شروط الجمهور، وموعد إرسال اختياري.\n'
                       '• «معاينة الجمهور» بتقولك كام عميل مطابق وكام منهم عنده رقم، قبل ما تحفظ.\n'
                       '• «حفظ الحملة» بيحفظها «مسودة» — لسه مفيش ولا رسالة اتبعتت.',
                       'Opens a form: campaign name, message text (click a variable such as the customer name to insert it), audience conditions, and an optional send time.\n'
                       '• "Preview audience" tells you how many customers match and how many have a phone, before you save.\n'
                       '• "Save campaign" saves it as a "Draft" — no message has been sent yet.')},
            {'target': 'omni-campaigns-search', 'text': T('ابحث باسم الحملة.',
                                              'Search by campaign name.'),
             'more': T('اكتب جزء من اسم الحملة والقائمة تحت بتتصفّى.\n'
                       '• البحث بيشتغل مع تبويب الحالة المختار، فلو مش لاقيها اختار «الكل».\n'
                       '• سمّي الحملات باسم واضح فيه الشهر أو الغرض عشان تلاقيها بسهولة بعدين.',
                       'Type part of the campaign name and the list below filters.\n'
                       '• Search works with the selected status tab, so if you cannot find it choose "All".\n'
                       '• Give campaigns clear names with the month or purpose so they are easy to find later.')},
            {'target': 'omni-campaigns-status-tabs', 'text': T('صفِّ الحملات بالحالة: مسودة، بانتظار الموافقة، معتمدة، جارية، مكتملة.',
                                              'Filter campaigns by status: draft, pending approval, approved, running, completed.'),
             'more': T('الحملة بتمشي: مسودة ← بانتظار الموافقة ← معتمدة ← (مجدولة) ← جارية ← مكتملة.\n'
                       '• المعتمِد يفتح «بانتظار الموافقة» عشان يراجع اللي مستني قراره.\n'
                       '• المجدولة والموقوفة والملغاة والمرفوضة بتظهر في «الكل».',
                       'A campaign moves: draft → pending approval → approved → (scheduled) → running → completed.\n'
                       '• The approver opens "Pending approval" to review what awaits a decision.\n'
                       '• Scheduled, paused, cancelled and rejected ones show under "All".')},
            {'target': 'omni-campaigns-list', 'text': T('قائمة الحملات مع حالتها وأرقام الإرسال؛ اضغط حملة لفتح تفاصيلها.',
                                              'The campaign list with status and send numbers; click one to open its details.'),
             'more': T('لكل حملة: الاسم، تاريخ الإنشاء، شارة الحالة، و«الوصول المقدَّر» بعد معاينة الجمهور.\n'
                       '• بعد الإرسال بيظهر «X مُرسَلة · Y مُسلَّمة» — الفرق بينهم رسائل لسه موصلتش أو فشلت.\n'
                       '• اضغط الحملة عشان تفتح تفاصيلها وشريط إجراءاتها.',
                       'For each campaign: name, creation date, status badge, and "Estimated reach" after previewing the audience.\n'
                       '• After sending it shows "X sent · Y delivered" — the gap is messages not yet delivered or failed.\n'
                       '• Click a campaign to open its details and action bar.')},
            {'target': 'omni-campaigns-detail-tabs', 'text': T('بعد اختيار حملة: «نظرة عامة» و«الجمهور» و«الرسائل».',
                                              'After selecting a campaign: "Overview", "Audience" and "Messages".'),
             'more': T('• «نظرة عامة»: بيانات الحملة، مين اعتمدها أو رفضها وسبب الرفض، وأرقام الإرسال.\n'
                       '• «الجمهور»: شروط الاستهداف والوصول المقدّر وعيّنة من العملاء.\n'
                       '• «الرسائل»: حالة كل رسالة (في الانتظار، مُرسلة، مُسلّمة، فاشلة…) مع فلتر بالحالة — منها تعرف مين موصلوش.',
                       '• "Overview": campaign data, who approved or rejected it and the rejection reason, and send numbers.\n'
                       '• "Audience": targeting conditions, estimated reach and a sample of customers.\n'
                       '• "Messages": each message\'s status (pending, sent, delivered, failed…) with a status filter — shows who was not reached.')},
            {'target': 'omni-campaigns-workflow', 'text': T('شريط الإجراءات أسفل الحملة المختارة؛ أزراره تتغير حسب حالة الحملة.',
                                              'The action bar under the selected campaign; its buttons change with the campaign\'s status.'),
             'more': T('• مسودة: «📤 طلب الموافقة» (لازم يكون فيها نص رسالة).\n'
                       '• بانتظار الموافقة: «✅ اعتماد» أو «❌ رفض» مع سبب إجباري. معتمدة: اختار موعد لـ«جدولة الإرسال» أو سيبه فاضي لـ«إرسال فوري».\n'
                       '• «🚫 إلغاء الحملة» متاح قبل ما تبدأ أو وهي موقوفة. الإرسال الفوري بيبدأ على طول، فراجع النص والجمهور الأول.',
                       '• Draft: "📤 Request approval" (it must have a message text).\n'
                       '• Pending approval: "✅ Approve" or "❌ Reject" with a required reason. Approved: pick a time to "Schedule sending" or leave it empty for "Send now".\n'
                       '• "🚫 Cancel campaign" is available before it starts or while paused. Send now starts at once, so check the text and audience first.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
