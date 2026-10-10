from . import T

MODULE = {
    'key': 'demand', 'group': 'operations', 'icon': '🔍',
    'title': T('الطلب الضائع (طلبات العملاء غير المُلبّاة)', 'Lost demand (unmet customer requests)'),
    'summary': T(
        'كل مرة يطلب عميل صنفاً ولا نستطيع صرفه (نفد، منخفض، غير مُخزَّن، أو استفسار سعر) نسجّله هنا بدل أن ينصرف بصمت. '
        'الهدف ثلاثي: (1) نتابع العميل حتى نوفّر له الصنف أو بديلاً، (2) لما يرجع الصنف للمخزون نتواصل معه ونسترد البيعة، '
        '(3) نعطي المشتريات إشارة حقيقية عن الأصناف المطلوبة. لكل طلب زمن استجابة (SLA): يجب تعيينه لموظف خلال 10 دقائق '
        'والتواصل مع العميل خلال 20 دقيقة من التعيين، وإلا يصل تنبيه تصعيد.',
        'Every time a customer asks for an item we cannot dispense (out of stock, low, not stocked, or a price check) we record '
        'it here instead of letting them leave silently. Three goals: (1) follow the customer until we get the item or an '
        'alternative, (2) when the item is back in stock, contact them and recover the sale, (3) give purchasing a real signal '
        'of what customers want. Each request has a response time (SLA): it must be assigned within 10 minutes and the customer '
        'contacted within 20 minutes of assignment, otherwise an escalation alert is sent.'),
    'workflows': [
        {
            'title': T('مراحل الطلب', 'Request stages'),
            'model': 'demand.DemandRecord', 'field': 'status',
            'transitions': 'apps.demand.service.VALID_TRANSITIONS',
            'intro': T('تبدأ «جديد» ثم تُعيَّن لموظف، ومنها تتفرع حسب ما يحتاجه الصنف حتى تنتهي «تم التسليم» أو «بيع ضائع» أو «ملغي».',
                       'Starts "New", is assigned to an employee, then branches by what the item needs until it ends "Fulfilled", "Lost" or "Cancelled".'),
            'states': [
                {'key': 'new', 'label': T('جديد — لم يُعالَج', 'New — not handled'),
                 'desc': T('سُجّل الطلب ولم يستلمه أحد. عيّنه لموظف خلال 10 دقائق.', 'Recorded but nobody took it. Assign it within 10 minutes.'),
                 'next': ['assigned', 'cancelled']},
                {'key': 'assigned', 'label': T('مُعيَّن — جارٍ المتابعة', 'Assigned — in progress'),
                 'desc': T('موظف مسؤول عنه الآن. تواصل مع العميل خلال 20 دقيقة وحدد الخطوة التالية.',
                           'An employee owns it. Contact the customer within 20 minutes and choose the next step.'),
                 'next': ['follow_up', 'stock_eta', 'transfer_suggested', 'purchasing_flagged', 'fulfilled', 'lost', 'cancelled']},
                {'key': 'follow_up', 'label': T('متابعة — في الانتظار', 'Follow-up — waiting'),
                 'desc': T('تم التواصل وننتظر شيئاً (رد العميل، موعد…). جدولة متابعة تذكّرك.',
                           'Contacted and waiting for something (customer reply, a date…). Schedule a follow-up to remind you.'),
                 'next': ['follow_up', 'stock_eta', 'transfer_suggested', 'purchasing_flagged', 'fulfilled', 'lost', 'cancelled']},
                {'key': 'stock_eta', 'label': T('في انتظار المخزون', 'Waiting for stock'),
                 'desc': T('الصنف قادم (طلبية أو توريد) والعميل ينتظر.', 'The item is coming (order or supply) and the customer is waiting.'),
                 'next': ['follow_up', 'fulfilled', 'lost', 'cancelled']},
                {'key': 'transfer_suggested', 'label': T('تم اقتراح تحويل', 'Transfer suggested'),
                 'desc': T('الصنف متوفر بفرع آخر وتم اقتراح تحويله.', 'The item is at another branch and a transfer was suggested.'),
                 'next': ['follow_up', 'fulfilled', 'lost', 'cancelled']},
                {'key': 'purchasing_flagged', 'label': T('مُرسَل للمشتريات', 'Sent to purchasing'),
                 'desc': T('غير متوفر في الشبكة؛ أُبلغت المشتريات لتوفيره.', 'Not in the network; purchasing was asked to source it.'),
                 'next': ['follow_up', 'stock_eta', 'fulfilled', 'lost', 'cancelled']},
                {'key': 'fulfilled', 'label': T('تم التسليم', 'Fulfilled'),
                 'desc': T('العميل حصل على الصنف (يمكن ذكر رقم الفاتورة). مرحلة نهائية.', 'The customer got the item (invoice number optional). Final.')},
                {'key': 'lost', 'label': T('مبيعة ضائعة', 'Lost sale'),
                 'desc': T('العميل لن يشتري منا — اختر السبب (لا يوجد مخزون، تأخر، اشترى من مكان آخر، صنف متوقف، لا رد، رفض السعر…). مرحلة نهائية.',
                           'The customer will not buy from us — choose the reason (no stock, delay, bought elsewhere, discontinued, no answer, price refused…). Final.')},
                {'key': 'cancelled', 'label': T('ملغي', 'Cancelled'),
                 'desc': T('سُجّل بالخطأ أو لم يعد مطلوباً. مرحلة نهائية.', 'Recorded by mistake or no longer needed. Final.')},
            ],
        },
        {
            'title': T('حالة كل صنف داخل الطلب', 'Status of each item in a request'),
            'model': 'demand.DemandItem', 'field': 'item_status',
            'intro': T('الطلب قد يحتوي عدة أصناف؛ كل صنف له حالته، ومنها حلقة «الاسترداد» عند عودة الصنف للمخزون.',
                       'A request may hold several items; each has its own status, including the "recovery" loop when the item is back in stock.'),
            'states': [
                {'key': 'pending', 'label': T('قيد الانتظار', 'Pending'), 'desc': T('لم يُتخذ إجراء بعد.', 'No action yet.')},
                {'key': 'sourcing', 'label': T('جارٍ التوفير', 'Sourcing'), 'desc': T('جاري توفيره بتحويل أو شراء.', 'Being sourced by transfer or purchase.')},
                {'key': 'available_again', 'label': T('عاد للمخزون', 'Back in stock'),
                 'desc': T('اكتشفت المزامنة أن الصنف عاد للمخزون — يظهر العميل في «قائمة الاسترداد» للتواصل معه.',
                           'The sync found the item is back in stock — the customer appears in the "Recovery queue" to be contacted.')},
                {'key': 'recovered', 'label': T('تم الاسترداد', 'Recovered'),
                 'desc': T('العميل رجع واشترى — البيعة استُردت وتُحسب في إيراد الاسترداد.', 'The customer came back and bought — counted as recovered revenue.')},
                {'key': 'fulfilled', 'label': T('تم التسليم', 'Fulfilled'), 'desc': T('صُرف الصنف.', 'Dispensed.')},
                {'key': 'lost', 'label': T('ضاعت المبيعة', 'Lost'), 'desc': T('لن يُصرف.', 'Will not be dispensed.')},
                {'key': 'cancelled', 'label': T('ملغي', 'Cancelled'), 'desc': T('أُلغي هذا الصنف.', 'This item was cancelled.')},
            ],
        },
    ],
}

_NEW_STEPS = [
    T('رقم الهاتف إجباري (موبايل 11 رقماً يبدأ بـ 01 أو أرضي بكود المحافظة). ابحث عن العميل بالاسم أو الهاتف أو كود PIC لتُملأ بياناته.',
      'The phone is required (11-digit mobile starting 01, or a landline with area code). Search the customer by name, phone or PIC code to fill their data.'),
    T('أضف الأصناف بالبحث أو الباركود. لو الصنف غير مكوَّد أضفه «يدوي» واكتب اسمه وسعراً تقديرياً.',
      'Add items by search or barcode. If an item is not coded, add it "manually" with its name and an estimated price.'),
    T('لو ظهر «بدائل متوفرة بنفس المادة الفعّالة» يمكنك عرض البديل على العميل — «حوّل البيع الآن» يسجّل أن العميل قبل البديل.',
      'If "alternatives with the same active ingredient" appears you can offer it — "Convert the sale now" records that the customer accepted the alternative.'),
    T('اختر الفرع ومصدر الطلب (حضر للفرع، اتصال، واتساب…) والأولوية، ثم «تسجيل الطلب».',
      'Choose the branch, the source (walk-in, call, WhatsApp…) and the priority, then "Record request".'),
]

SCREENS = [
    {
        'key': 'demand.list',
        'routes': ['/demand'],
        'title': T('طلبات العملاء والطلب الضائع', 'Customer requests & lost demand'),
        'summary': T(
            'قائمة كل طلبات العملاء غير المُلبّاة مع حالتها ومسؤولها وزمن SLA، وتسجيل طلب جديد، وإجراءات جماعية (تعيين، إرسال للمشتريات).',
            'The list of all unmet customer requests with their status, owner and SLA timer, a form to record a new request, and bulk actions (assign, send to purchasing).'),
        'audience': T('الصيادلة، المندوبون، مركز الاتصال، المشرفون.', 'Pharmacists, salespeople, call center, supervisors.'),
        'steps': [
            T('«تسجيل طلب جديد» عند أي طلب لم نستطع تلبيته فوراً.', '"Record new request" whenever a request could not be met right away.'),
            *_NEW_STEPS,
            T('في القائمة: صفِّ بالحالة أو الأولوية أو الفرع، أو ابحث بالهاتف أو الاسم أو PIC أو الصنف.',
              'In the list: filter by status, priority or branch, or search by phone, name, PIC or item.'),
            T('حدد عدة طلبات ثم «تعيين إلى…» لموظف أو «إرسال للمشتريات».', 'Select several requests, then "Assign to…" an employee or "Send to purchasing".'),
            T('اضغط أي طلب لفتح تفاصيله ومتابعته.', 'Click a request to open and follow it.'),
        ],
        'tips': [
            T('علامة «تجاوز» تعني أن الطلب تخطى زمن SLA — عالجه فوراً.', 'The "breached" mark means the request passed its SLA time — handle it now.'),
            T('سجّل الطلب حتى لو العميل سيمشي؛ الطلب المسجّل باسم عميل حقيقي هو «خسارة مؤكدة» وهي أقوى إشارة للمشتريات.',
              'Record the request even if the customer is leaving; a request under a real customer is a "confirmed loss", the strongest signal for purchasing.'),
        ],
        'related': ['demand.detail', 'demand.dashboard', 'demand.recovery', 'reservations.new'],
        'tour': [
            {'target': 'demand-list-new', 'text': T('«+ تسجيل طلب جديد» لما عميل يطلب صنف مش موجود.',
                                              '"+ Log new request" when a customer asks for an item we do not have.')},
            {'target': 'demand-list-tabs', 'text': T('تبويبات الحالة — كل طلب بيمشي من التسجيل لحد ما يتقفل.',
                                              'Status tabs — every request moves from logged until closed.')},
            {'target': 'demand-list-search', 'text': T('ابحث بالهاتف أو اسم العميل أو PIC أو الصنف.',
                                              'Search by phone, customer name, PIC or item.')},
            {'target': 'demand-list-table', 'text': T('قائمة الطلبات — افتح أي طلب لتفاصيله ومتابعته.',
                                              'The requests list — open any request for its details and follow-up.')},
            {'target': 'demand-list-recovery', 'text': T('«🔔 عاد للمخزون» يوريك الطلبات اللي صنفها رجع، عشان تكلّم العميل.',
                                              '"🔔 Back in stock" shows requests whose item came back, so you can call the customer.')},
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'demand.detail',
        'routes': ['/demand/:id'],
        'title': T('تفاصيل طلب العميل', 'Customer request details'),
        'summary': T(
            'متابعة طلب واحد من البداية للنهاية: بيانات العميل وربطه بـ SOFTECH، الأصناف ومخزونها، المتابعات المجدولة، وسجل التواصل، '
            'مع أزرار الإجراء حسب المرحلة (تعيين، تواصلت مع العميل، ينتظر المخزون، تم التوريد، بيع ضائع، إلغاء).',
            'Follow one request end to end: the customer and their SOFTECH link, the items and their stock, scheduled follow-ups and '
            'the contact log, with action buttons by stage (assign, contacted, waiting for stock, fulfilled, lost, cancel).'),
        'audience': T('الموظف المعيَّن والمشرف.', 'The assigned employee and the supervisor.'),
        'tabs': [
            {'key': 'details', 'title': T('📋 التفاصيل', '📋 Details'),
             'body': T('بيانات العميل (الهاتف، الاسم، كود PIC، ربط ERP)، تفاصيل الطلب (الفرع، الحالة، الأولوية، المصدر، من أنشأه ولمن عُيّن)، '
                       'ومسار SLA (وقت الإنشاء ← التعيين ← التواصل). لو الطلب «بيع ضائع» يظهر السبب والقيمة المقدرة. «بحث في ERP» يربط العميل بكوده في SOFTECH.',
                       'Customer data (phone, name, PIC, ERP link), request details (branch, status, priority, source, creator, assignee) and the SLA path '
                       '(created → assigned → contacted). For a lost sale the reason and estimated value show. "Search ERP" links the customer to their SOFTECH code.')},
            {'key': 'items', 'title': T('💊 الأصناف', '💊 Items'),
             'body': T('الأصناف المطلوبة مع الكمية والمخزون بالفرع والقيمة المقدرة، وعلامة «نقص طويل الأمد» للأصناف المتكررة. '
                       'يمكنك إضافة صنف، وتظهر البدائل المتوفرة بنفس المادة الفعّالة. السعر «يدوي» يعني تقديرياً وليس من SOFTECH.',
                       'Requested items with quantity, branch stock and estimated value, and a "long-term shortage" mark for repeated items. '
                       'You can add an item, and alternatives with the same active ingredient are shown. A "manual" price is an estimate, not from SOFTECH.')},
            {'key': 'followups', 'title': T('🔔 المتابعات', '🔔 Follow-ups'),
             'body': T('مهام متابعة مجدولة (اتصال، واتساب، زيارة، فحص مخزون) بتاريخ استحقاق. أكملها بملاحظة عند التنفيذ؛ المتأخرة تظهر «فائت». '
                       '«جدولة متابعة جديدة» لتذكير نفسك بموعد التواصل التالي.',
                       'Scheduled follow-up tasks (call, WhatsApp, visit, stock check) with a due date. Complete them with a note; overdue ones show "missed". '
                       '"Schedule a follow-up" to remind yourself of the next contact.')},
            {'key': 'logs', 'title': T('💬 السجلات', '💬 Logs'),
             'body': T('سجل كل ما حدث على الطلب: ملاحظات، سجلات اتصال، رسائل واتساب، وتغييرات الحالة التلقائية. اكتب وCtrl+Enter للإرسال.',
                       'The log of everything on the request: notes, call logs, WhatsApp messages and automatic status changes. Type and press Ctrl+Enter to send.')},
        ],
        'steps': [
            T('لو الطلب «جديد»: اضغط «تعيين» واختر الموظف (أو نفسك).', 'If "New": press "Assign" and pick the employee (or yourself).'),
            T('بعد الاتصال: «تواصلت مع العميل» واكتب نتيجة المكالمة.', 'After calling: "Contacted customer" and write the outcome.'),
            T('اختر الخطوة: «ينتظر المخزون»، أو اقترح تحويلاً، أو أرسله للمشتريات.', 'Pick the next step: "Waiting for stock", suggest a transfer, or send to purchasing.'),
            T('في النهاية: «تم التوريد» (مع رقم الفاتورة اختيارياً) أو «بيع ضائع» مع اختيار السبب.',
              'At the end: "Fulfilled" (invoice number optional) or "Lost" with a reason.'),
        ],
        'tips': [
            T('اختيار سبب البيع الضائع بدقة مهم؛ التقارير والمشتريات تعتمد عليه.', 'Choosing the exact lost-sale reason matters; reports and purchasing rely on it.'),
        ],
        'related': ['demand.list', 'demand.recovery'],
        'tour': [
            {'target': 'demand-detail-header', 'text': T('رقم الطلب وحالته وأولويته.',
                                              'The request number, status and priority.')},
            {'target': 'demand-detail-tabs', 'text': T('التبويبات: التفاصيل، الأصناف، المتابعات، السجلات.',
                                              'Tabs: details, items, follow-ups, logs.')},
            {'target': 'demand-detail-content', 'text': T('محتوى التبويب المفتوح.',
                                              'The open tab\'s content.')},
            {'target': 'demand-detail-actions', 'text': T('الإجراءات المتاحة للحالة الحالية.',
                                              'The actions available in the current status.')},
            {'target': 'demand-detail-contact', 'text': T('«📞 تواصلت مع العميل» وسجّل النتيجة.',
                                              '"📞 Contacted the customer" and record the outcome.')},
            {'target': 'demand-detail-fulfill', 'text': T('«تم التوريد» لما الصنف يوصل.',
                                              '"Supplied" when the item arrives.')},
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'demand.dashboard',
        'routes': ['/demand/dashboard'],
        'title': T('لوحة الطلب الضائع والتحليلات', 'Lost demand dashboard'),
        'summary': T(
            'تحليل الطلب غير المُلبّى لتحسين المشتريات ورفع الإيراد: إجمالي الطلبات، ما تم توريده، القيمة الضائعة المؤكدة، الإيراد المُسترَد، '
            'أكثر الأصناف ضياعاً، أسباب الضياع، أداء الفروع، أصناف النقص المزمن، ومقارنة الخسارة «المؤكدة» (باسم عميل) بالخسارة «التقديرية» من محرك المشتريات.',
            'Analysis of unmet demand to improve purchasing and revenue: total requests, fulfilled, confirmed lost value, recovered revenue, '
            'most-lost items, loss reasons, branch performance, chronic shortage items, and "confirmed" losses (under a customer) vs the purchasing engine\'s "estimated" losses.'),
        'audience': T('المشرفون، المشتريات، الإدارة.', 'Supervisors, purchasing, management.'),
        'steps': [
            T('ابدأ بالأرقام العلوية: نسبة التوريد وقيمة الخسارة المؤكدة والإيراد المسترد.', 'Start with the top numbers: fulfilment rate, confirmed lost value, recovered revenue.'),
            T('«اقتراحات الشراء المدفوعة بطلب العملاء»: أصناف طلبها عملاء حقيقيون مرتبة بالقيمة — اضغط «إرسال للمشتريات» أو «تصدير CSV».',
              '"Customer-driven purchase suggestions": items real customers asked for, sorted by value — press "Send to purchasing" or "Export CSV".'),
            T('«أصناف نقص مزمن»: طلب متكرر غير مُستوفى — يُنصح بإضافتها للأوردر الدوري أو طلب تحويل.',
              '"Chronic shortage items": repeated unmet demand — add them to the periodic order or request a transfer.'),
            T('«أصناف متوقفة مع طلب نشط»: يجب إغلاق هذه الطلبات أو إبلاغ العملاء بعدم التوفر.',
              '"Discontinued items with active requests": close these requests or tell customers the item is unavailable.'),
            T('«لوحة تسجيل الطلب»: من يسجّل طلبات العملاء من الموظفين — انضباط التسجيل يرفع دقة كل المؤشرات.',
              '"Recording board": which employees record unmet requests — recording discipline improves every indicator.'),
        ],
        'tips': [
            T('«نسبة الالتقاط» = كم من الخسارة التقديرية ربطناها بعميل حقيقي؛ ارتفاعها يعني تحسّن تسجيل الطلب الضائع.',
              '"Capture rate" = how much of the estimated loss we tied to a real customer; higher means better recording.'),
        ],
        'related': ['demand.list', 'demand.recovery', 'purchasing.engine'],
        'updated': '2026-10-10',
    },
    {
        'key': 'demand.recovery',
        'routes': ['/demand/recovery'],
        'title': T('قائمة الاسترداد (عاد للمخزون)', 'Recovery queue (back in stock)'),
        'summary': T(
            'عملاء طلبوا أصنافاً نفدت ثم عادت للمخزون — تظهر هنا تلقائياً بعد المزامنة مرتبة بالقيمة، لتتواصل معهم وتسترد البيعة. '
            'أعلى الصفحة: الإيراد المسترد خلال 30 يوماً، معدل الاسترداد، وقيمة الفرص المفتوحة.',
            'Customers who asked for items that ran out and are now back in stock — they appear here automatically after the sync, '
            'sorted by value, so you can contact them and recover the sale. At the top: recovered revenue (30 days), recovery rate and open opportunity value.'),
        'audience': T('مركز الاتصال والصيادلة.', 'Call center and pharmacists.'),
        'steps': [
            T('ابدأ بأعلى قيمة. اضغط «واتساب» لفتح المحادثة وتسجيل التواصل تلقائياً، أو «تواصل» بعد الاتصال.',
              'Start with the highest value. Press "WhatsApp" to open the chat and log the contact automatically, or "Contact" after calling.'),
            T('لو العميل يريد الصنف: «تحويل إلى حجز للعميل» لتجهيزه له.', 'If the customer wants it: "Convert to a reservation" to prepare it.'),
            T('لو اشترى فعلاً: «استرداد» وأكّد الإيراد المسترد (القيمة المقترحة = السعر المجمّد × الكمية، عدّلها لتطابق الفاتورة).',
              'If they bought: "Recover" and confirm the recovered revenue (suggested = frozen price × qty; adjust to match the invoice).'),
            T('لو رفض: «رفض التواصل بخصوص هذا الصنف» مع السبب (لم يعد بحاجته، انتقل…).',
              'If they decline: "Customer declined" with the reason (no longer needed, moved…).'),
            T('للأصناف التي لن تكون فرصة حقيقية (غير متوفرة في مصر، متوقفة، غير مسموح بيعها): «استبعاد» — يحتاج اعتماداً.',
              'For items that are not a real opportunity (unavailable in Egypt, discontinued, not allowed): "Exclude" — needs approval.'),
        ],
        'related': ['demand.dashboard', 'demand.list'],
        'updated': '2026-10-10',
    },
    {
        'key': 'demand.mobile_list',
        'routes': ['/m/demand'],
        'title': T('الطلب الضائع (موبايل)', 'Lost demand (mobile)'),
        'summary': T('قائمة طلبات فرعك على الموبايل مع شرائح الحالة وعلامة تجاوز SLA، وزر لتسجيل طلب من على الكاونتر.',
                     'Your branch\'s requests on the phone with status chips and SLA-breach flags, and a button to record a request at the counter.'),
        'audience': T('العاملون في الفرع.', 'Branch staff.'),
        'steps': [
            T('زر «تسجيل طلب ضائع» لتسجيل الطلب فوراً أمام العميل.', '"Record lost demand" to record the request in front of the customer.'),
            T('اضغط طلباً لعرض تفاصيله وكتابة ملاحظة.', 'Tap a request to see it and add a note.'),
        ],
        'tips': [T('تغييرات المراحل المتقدمة تتم من شاشة الكمبيوتر؛ الموبايل للتسجيل السريع والمتابعة.',
                   'Advanced stage changes are done on the desktop; the phone is for quick recording and follow-up.')],
        'related': ['demand.mobile_new'],
        'updated': '2026-10-10',
    },
    {
        'key': 'demand.mobile_new',
        'routes': ['/m/demand/new'],
        'title': T('تسجيل طلب ضائع (موبايل)', 'Record lost demand (mobile)'),
        'summary': T('نسخة سريعة من نموذج تسجيل الطلب للموبايل: الهاتف إجباري، والأصناف من البحث أو مكتوبة يدوياً.',
                     'A quick phone version of the request form: phone required, items from search or typed manually.'),
        'audience': T('العاملون في الفرع.', 'Branch staff.'),
        'steps': [
            T('اكتب رقم هاتف العميل (والاسم اختيارياً).', 'Type the customer\'s phone (name optional).'),
            T('ابحث عن الصنف وأضفه، أو اكتب اسم صنف غير مكوَّد ثم «إضافة».', 'Search and add the item, or type an uncoded item name then "Add".'),
            T('الفرع يُختار تلقائياً (فرعك). حدد الأولوية والمصدر ثم «تسجيل الطلب».', 'The branch defaults to yours. Set priority and source, then "Record request".'),
        ],
        'tour': [
            {'target': 'demand-mobile-new-customer', 'text': T('رقم وإسم العميل عشان نبلّغه لما الصنف يوصل.',
                                              'The customer\'s phone and name so we can tell them when the item arrives.')},
            {'target': 'demand-mobile-new-items', 'text': T('ابحث عن الصنف المطلوب، أو ضيفه يدوي لو مش موجود في الكتالوج.',
                                              'Search the requested item, or add it manually if it is not in the catalog.')},
            {'target': 'demand-mobile-new-lines', 'text': T('الأصناف المضافة للطلب.',
                                              'The items added to the request.')},
            {'target': 'demand-mobile-new-details', 'text': T('الفرع والأولوية والمصدر وأي ملاحظات.',
                                              'Branch, priority, source and any notes.')},
            {'target': 'demand-mobile-new-submit', 'text': T('«✅ تسجيل الطلب» يحفظه ويبدأ متابعته.',
                                              '"✅ Log request" saves it and starts its follow-up.')},
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'demand.mobile_detail',
        'routes': ['/m/demand/:id'],
        'title': T('تفاصيل الطلب (موبايل)', 'Request details (mobile)'),
        'summary': T('عرض الطلب على الموبايل: العميل (اضغط للاتصال)، الأصناف، الحالة، وسجل الملاحظات مع إمكانية الكتابة.',
                     'The request on the phone: the customer (tap to call), items, status and the notes thread where you can write.'),
        'audience': T('العاملون في الفرع.', 'Branch staff.'),
        'steps': [T('اتصل بالعميل من الزر، ثم اكتب نتيجة التواصل في الملاحظات.', 'Call the customer from the button, then write the outcome in the notes.')],
        'updated': '2026-10-10',
    },
]
