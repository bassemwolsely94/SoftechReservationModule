from . import T

MODULE = {
    'key': 'reservations', 'group': 'operations', 'icon': '📋',
    'title': T('الحجوزات', 'Reservations'),
    'summary': T(
        'الحجز = عميل طلب صنفاً غير متوفر الآن (أو يريد تجهيزه)، فنسجّل طلبه ونتابعه حتى يُصرف له. '
        'الحجز يمر بمراحل واضحة: انتظار مخزون ← المخزون متاح ← التواصل مع العميل ← تأكيد قدومه ← الصرف. '
        'كل حجز له سجل محادثة (ملاحظات، صور، رسائل صوتية) ويمكن مطابقته مع فاتورة البيع في SOFTECH '
        'للتأكد أن الصرف تم فعلاً.',
        'A reservation = a customer asked for an item that is not available now (or wants it prepared), so we '
        'record the request and follow it until it is dispensed. It moves through clear stages: waiting for stock '
        '→ stock available → customer contacted → arrival confirmed → dispensed. Every reservation has a chat log '
        '(notes, photos, voice notes) and can be matched with the sales invoice in SOFTECH to confirm the dispense '
        'really happened.'),
    'workflows': [{
        'title': T('مراحل الحجز', 'Reservation stages'),
        'model': 'reservations.Reservation', 'field': 'status',
        'transitions': 'apps.reservations.views.ReservationViewSet._VALID_TRANSITIONS',
        'intro': T('النظام لا يسمح إلا بالانتقالات الصحيحة أدناه؛ المدير والكول سنتر يمكنهم الإلغاء من أي مرحلة.',
                   'The system only allows the moves below; admins and the call center can cancel from any stage.'),
        'states': [
            {'key': 'pending', 'label': T('قيد الانتظار — انتظار مخزون', 'Pending — waiting for stock'),
             'desc': T('تم تسجيل الطلب والصنف غير متوفر في الفرع. تابع وصول المخزون أو اطلب تحويلاً من فرع آخر.',
                       'The request is recorded and the item is not at the branch. Watch for stock or request a transfer from another branch.'),
             'next': ['available', 'cancelled', 'expired']},
            {'key': 'available', 'label': T('المخزون متاح — اتصل بالعميل', 'Available — call the customer'),
             'desc': T('الصنف وصل أو أصبح متوفراً. المطلوب الآن: الاتصال بالعميل وإبلاغه.',
                       'The item arrived or is in stock. Now: call the customer and tell them.'),
             'next': ['contacted', 'confirmed', 'cancelled', 'expired']},
            {'key': 'contacted', 'label': T('تم التواصل — العميل على علم', 'Contacted — customer informed'),
             'desc': T('تم إبلاغ العميل ولم يؤكد موعد قدومه بعد.', 'The customer was told but has not confirmed when they will come.'),
             'next': ['confirmed', 'available', 'cancelled', 'expired']},
            {'key': 'confirmed', 'label': T('مؤكد — العميل قادم', 'Confirmed — customer coming'),
             'desc': T('العميل أكد أنه سيحضر أو سيُوصَّل له. جهّز الصنف.',
                       'The customer confirmed they will come or have it delivered. Prepare the item.'),
             'next': ['fulfilled', 'cancelled', 'expired']},
            {'key': 'fulfilled', 'label': T('تم التسليم — الصنف صُرف', 'Fulfilled — dispensed'),
             'desc': T('تم صرف الصنف للعميل. مرحلة نهائية؛ يمكن بعدها مطابقة الحجز مع فاتورة SOFTECH.',
                       'The item was dispensed. Final stage; the reservation can then be matched with the SOFTECH invoice.')},
            {'key': 'cancelled', 'label': T('ملغي', 'Cancelled'),
             'desc': T('ألغاه العميل أو الفرع. مرحلة نهائية — اكتب السبب في الملاحظة.',
                       'Cancelled by the customer or the branch. Final stage — write the reason in the note.')},
            {'key': 'expired', 'label': T('منتهي — لا استجابة', 'Expired — no response'),
             'desc': T('العميل لم يرد أو لم يحضر. يمكن إعادة فتحه فيرجع «قيد الانتظار».',
                       'The customer did not answer or come. It can be reopened, returning it to "Pending".'),
             'next': ['pending']},
        ],
    }],
}

_STEPS_NEW = [
    T('ابحث عن العميل بالاسم أو الموبايل أو كود SOFTECH (اختياري لكن مفضّل حتى يظهر الحجز في ملفه).',
      'Search the customer by name, mobile or SOFTECH code (optional but preferred, so the reservation shows on their profile).'),
    T('ابحث عن الصنف بالاسم أو الكود أو الباركود (يعمل مع الماسح). لو الصنف غير مكوَّد في SOFTECH اكتب اسمه يدوياً.',
      'Search the item by name, code or barcode (scanner works). If the item is not in SOFTECH, type its name manually.'),
    T('راجع لوحة المخزون: الكمية في هذا الفرع وإجمالي الشبكة والفروع التي بها مخزون — قد يكون الأسرع تحويلاً من فرع قريب.',
      'Check the stock panel: quantity at this branch, the network total and branches that have it — a transfer from a nearby branch may be fastest.'),
    T('حدد الكمية، ويمكنك «إضافة صنف آخر» لنفس العميل.', 'Set the quantity; you can "Add another item" for the same customer.'),
    T('املأ التفاصيل: الفرع، اسم وهاتف التواصل (مطلوبة)، قناة الطلب (نقدي/توصيل/كنتراكت)، الأولوية، مصدر الطلب وطريقة التسليم.',
      'Fill the details: branch, contact name and phone (required), order channel (cash/delivery/contract), priority, order source and fulfilment method.'),
    T('أرفق صورة الروشتة لو موجودة، ثم «إنشاء الحجز».', 'Attach the prescription photo if any, then "Create reservation".'),
]

_TIPS_NEW = [
    T('لو ظهر «حجز مكرر محتمل» فهناك حجز مفتوح لنفس العميل والصنف — افتحه بدل إنشاء حجز جديد، إلا لو الطلب مختلف فعلاً.',
      'If "possible duplicate" appears, an open reservation exists for the same customer and item — open it instead of creating a new one, unless the request really is different.'),
    T('اختر «مريض مزمن» كأولوية لمرضى العلاج المستمر، و«عاجل» لما يحتاجه العميل اليوم.',
      'Use "Chronic patient" priority for long-term therapy patients and "Urgent" for what the customer needs today.'),
    T('قناة «كنتراكت» تطلب نوع العميل (تأمين صحي، تعاقدات، موظفين…) — نفس اختيار شاشة POS في SOFTECH.',
      'The "Contract" channel asks for the customer type (health insurance, contracts, employees…) — the same choice as the SOFTECH POS screen.'),
]

SCREENS = [
    {
        'key': 'reservations.board',
        'routes': ['/reservations'],
        'title': T('لوحة الحجوزات (كانبان)', 'Reservations board (Kanban)'),
        'summary': T(
            'كل الحجوزات النشطة كأعمدة حسب المرحلة: قيد الانتظار، المخزون متاح، تم التواصل، مؤكد، تم التسليم، ملغي/منتهي. '
            'تعرف بنظرة واحدة ما المطلوب منك الآن — أهمها عمود «المخزون متاح» لأنه ينتظر اتصالاً بالعميل.',
            'All active reservations as columns by stage: pending, available, contacted, confirmed, fulfilled, cancelled/expired. '
            'One look tells you what needs doing now — most important is the "Available" column, which is waiting for a call to the customer.'),
        'audience': T('الصيادلة، مركز الاتصال، المندوبون، المشرفون.', 'Pharmacists, call center, salespeople, supervisors.'),
        'steps': [
            T('استخدم البحث والفلاتر (الفرع، الأولوية، الحالة، التاريخ) لتضييق القائمة.',
              'Use search and filters (branch, priority, status, date) to narrow the list.'),
            T('ابدأ بعمود «المخزون متاح»: اتصل بالعميل ثم افتح البطاقة وغيّر الحالة إلى «تم التواصل» أو «مؤكد».',
              'Start with the "Available" column: call the customer, then open the card and move it to "Contacted" or "Confirmed".'),
            T('اضغط أي بطاقة لفتح تفاصيل الحجز وسجله.', 'Click any card to open the reservation details and its log.'),
            T('«حجز جديد» لتسجيل طلب جديد، و«قائمة» للتحويل لعرض الجدول مع الإجراءات الجماعية.',
              '"New reservation" to record a new request; "List" to switch to the table view with bulk actions.'),
        ],
        'tips': [
            T('البطاقة الحمراء (عاجل) والبنفسجي (مزمن) لها أولوية في المتابعة.', 'Red (urgent) and purple (chronic) cards come first.'),
            T('علامة «يحتوي صورة» تعني وجود روشتة أو صورة مرفقة.', 'The "has image" mark means a prescription or photo is attached.'),
        ],
        'related': ['reservations.list', 'reservations.new', 'demand.list'],
        'tour': [
            {'target': 'reservations-board-new', 'text': T('«+ حجز جديد» يفتح شاشة تسجيل حجز.',
                                              '"+ New reservation" opens the new reservation screen.')},
            {'target': 'reservations-board-view', 'text': T('بدّل بين عرض «كانبان» (أعمدة حسب الحالة) و«قائمة».',
                                              'Switch between the "Kanban" view (columns by status) and the "List" view.')},
            {'target': 'reservations-board-search', 'text': T('ابحث برقم الحجز أو اسم العميل أو الهاتف أو الصنف.',
                                              'Search by reservation number, customer name, phone or item.')},
            {'target': 'reservations-board-status', 'text': T('فلتر الحالة يعرض حالة واحدة بس.',
                                              'The status filter shows a single status only.')},
            {'target': 'reservations-board-columns', 'text': T('كل عمود حالة. افتح أي كارت عشان تشوف التفاصيل وتحرّك الحجز للخطوة اللي بعدها.',
                                              'Each column is a status. Open any card to see the details and move the reservation to its next step.')},
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'reservations.list',
        'routes': ['/reservations/list'],
        'title': T('قائمة الحجوزات', 'Reservations list'),
        'summary': T(
            'نفس الحجوزات في جدول، مع تحديد عدة حجوزات وتغيير حالتها مرة واحدة، والتصدير إلى Excel.',
            'The same reservations as a table, where you can select several and change their status at once, and export to Excel.'),
        'audience': T('المشرفون ومركز الاتصال ومن يتابع أعداداً كبيرة.', 'Supervisors, call center and anyone handling many reservations.'),
        'steps': [
            T('صفِّ بالاسم أو الرقم أو الحالة أو الأولوية أو الفرع.', 'Filter by name or number, status, priority or branch.'),
            T('حدد الحجوزات ثم اختر من «تغيير الحالة…» واضغط «تطبيق».', 'Select reservations, pick from "Change status…" and press "Apply".'),
            T('«تصدير Excel» يصدّر النتائج الحالية بنفس الفلاتر.', '"Export Excel" exports the current results with the same filters.'),
        ],
        'tips': [
            T('الحجوزات التي لا تسمح حالتها بالانتقال المختار يتم تخطيها تلقائياً، والنظام يخبرك بعددها.',
              'Reservations whose status does not allow the chosen move are skipped automatically, and the system tells you how many.'),
        ],
        'related': ['reservations.board'],
        'updated': '2026-10-10',
    },
    {
        'key': 'reservations.new',
        'routes': ['/reservations/new', '/m/reservations/new'],
        'title': T('حجز جديد', 'New reservation'),
        'summary': T(
            'نموذج تسجيل طلب عميل لصنف أو أكثر، مع رؤية المخزون في الفرع وكل الشبكة أثناء التسجيل.',
            'The form to record a customer\'s request for one or more items, showing stock at the branch and across the network while you type.'),
        'audience': T('الصيادلة، مركز الاتصال، المندوبون.', 'Pharmacists, call center, salespeople.'),
        'steps': _STEPS_NEW,
        'tips': _TIPS_NEW,
        'faq': [
            {'q': T('الصنف موجود في فرع آخر، هل أسجّل حجزاً؟', 'The item is at another branch — should I still reserve?'),
             'a': T('نعم سجّل الحجز، ثم من صفحة الحجز اطلب «تحويل مخزون» من الفرع الذي لديه الصنف؛ الحجز يرتبط بطلب التحويل.',
                    'Yes, record it, then from the reservation page request a "stock transfer" from the branch that has it; the reservation is linked to the transfer.')},
            {'q': T('هل الحجز يخصم من المخزون في SOFTECH؟', 'Does a reservation deduct stock in SOFTECH?'),
             'a': T('لا. الحجز متابعة فقط؛ الصرف الفعلي يتم بفاتورة في SOFTECH (أو من شاشة نقطة البيع).',
                    'No. A reservation is tracking only; the actual dispense is an invoice in SOFTECH (or from the POS screen).')},
        ],
        'related': ['reservations.board', 'transfers.new'],
        'tour': [
            {'target': 'reservations-new-customer', 'text': T('اختار العميل (اختياري) — لو موجود بتتملى بياناته تلقائي.',
                                              'Choose the customer (optional) — an existing customer fills the details automatically.')},
            {'target': 'reservations-new-item', 'text': T('ابحث عن الصنف المطلوب وحدد الكمية. تقدر تضيف أكتر من صنف.',
                                              'Search the requested item and set the quantity. You can add more than one item.')},
            {'target': 'reservations-new-details', 'text': T('تفاصيل الحجز: الفرع والأولوية والموعد.',
                                              'Reservation details: branch, priority and timing.')},
            {'target': 'reservations-new-channel', 'text': T('القناة: بيع نقدي، توصيل، أو كنتراكت.',
                                              'Channel: cash sale, delivery or contract.')},
            {'target': 'reservations-new-contact', 'text': T('اسم ورقم التواصل — رقم الهاتف إجباري عشان نبلّغ العميل.',
                                              'Contact name and phone — the phone is required so the customer can be notified.')},
            {'target': 'reservations-new-submit', 'text': T('«✅ إنشاء الحجز» يحفظ الحجز ويبدأ دورته.',
                                              '"✅ Create reservation" saves it and starts its workflow.')},
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'reservations.detail',
        'routes': ['/reservations/:id', '/m/reservations/:id'],
        'title': T('تفاصيل الحجز', 'Reservation details'),
        'summary': T(
            'كل ما يخص حجزاً واحداً: بيانات العميل والأصناف، المخزون الحالي في الفروع، تغيير الحالة، سجل المحادثة، '
            'طباعة إيصال الحجز أو إرساله واتساب، طلب تحويل، ومطابقة الصرف مع مستند SOFTECH.',
            'Everything about one reservation: customer and items, current stock across branches, status changes, the chat '
            'log, printing the reservation receipt or sending it on WhatsApp, requesting a transfer, and matching the '
            'dispense with the SOFTECH document.'),
        'audience': T('كل من يتابع الحجز.', 'Everyone who follows the reservation.'),
        'steps': [
            T('أعلى الصفحة: الحالة الحالية وأزرار الانتقال المسموح بها فقط (مثلاً «المخزون متاح» ← «تم التواصل»). اكتب ملاحظة بسبب التغيير.',
              'At the top: the current status and only the allowed next moves (e.g. "Available" → "Contacted"). Write a note with the reason.'),
            T('في سجل المحادثة سجّل كل ما حدث: مكالمة أُجريت، رد العميل، فحص المخزون… ويمكنك إرفاق صورة أو تسجيل ملاحظة صوتية (Ctrl+Enter للإرسال).',
              'In the chat log record everything: call made, customer reply, stock check… You can attach a photo or record a voice note (Ctrl+Enter to send).'),
            T('«طلب تحويل» ينشئ طلب تحويل مرتبطاً بالحجز لو الصنف في فرع آخر.',
              '"Request transfer" creates a transfer request linked to the reservation when the item is at another branch.'),
            T('اطبع «إيصال حجز» للعميل أو أرسله واتساب — فيه رقم الحجز والأصناف وموعد التوفر المتوقع.',
              'Print the "Reservation receipt" for the customer or send it on WhatsApp — it has the reservation number, items and expected date.'),
            T('بعد الصرف: قسم «مطابقة مستند ERP» يبحث عن فاتورة البيع في SOFTECH (برقم المستند أو تلقائياً بالأصناف والتاريخ) ويعرض هل الصرف متطابق أو جزئي أو غير موجود.',
              'After dispensing: the "ERP document match" section looks for the sales invoice in SOFTECH (by document number or automatically by items and date) and shows whether it is matched, partial or not found.'),
        ],
        'tips': [
            T('الحجز في حالة نهائية (تم التسليم / ملغي) لا يمكن تغيير حالته.', 'A reservation in a final state (fulfilled / cancelled) cannot change status.'),
            T('المطابقة مع SOFTECH تُعاد بعد فترة انتظار قصيرة بين كل محاولة؛ لو «غير موجود» تأكد من رقم المستند.',
              'The SOFTECH match can be retried after a short wait between attempts; if "not found", check the document number.'),
        ],
        'related': ['reservations.board', 'customers.detail', 'transfers.detail'],
        'tour': [
            {'target': 'reservations-detail-header', 'text': T('رقم الحجز وحالته الحالية.',
                                              'The reservation number and its current status.')},
            {'target': 'reservations-detail-customer', 'text': T('بيانات العميل.',
                                              'The customer\'s details.')},
            {'target': 'reservations-detail-items', 'text': T('أصناف الحجز وكمياتها.',
                                              'The reserved items and quantities.')},
            {'target': 'reservations-detail-actions', 'text': T('طباعة، واتساب للعميل، وأزرار الخطوة التالية.',
                                              'Print, WhatsApp the customer, and the next-step buttons.')},
            {'target': 'reservations-detail-status', 'text': T('«تغيير الحالة» يحرّك الحجز للخطوة اللي بعدها (حسب صلاحيتك).',
                                              '"Change status" moves the reservation to its next step (depending on your permission).')},
            {'target': 'reservations-detail-chatter', 'text': T('سجل الأنشطة: كل تغيير ومين عمله، وتقدر تكتب ملاحظة.',
                                              'The activity log: every change and who made it; you can add a note.')},
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'reservations.mobile_list',
        'routes': ['/m/reservations'],
        'title': T('الحجوزات (موبايل)', 'Reservations (mobile)'),
        'summary': T(
            'قائمة الحجوزات على الموبايل كبطاقات، مع فلاتر سريعة حسب الحالة. للفروع تظهر حجوزات فرعك فقط.',
            'The reservations list on the phone as cards, with quick status filters. Branch users see only their branch.'),
        'audience': T('العاملون في الفرع ومركز الاتصال من الموبايل.', 'Branch staff and the call center on the phone.'),
        'steps': [
            T('اختر شريحة الحالة: «النشطة» (الافتراضي)، أو حالة محددة، أو «الكل».', 'Pick a status chip: "Active" (default), a specific status, or "All".'),
            T('اضغط بطاقة لفتح الحجز وتغيير حالته.', 'Tap a card to open the reservation and change its status.'),
            T('زر «+» أسفل الشاشة لحجز جديد.', 'The "+" button at the bottom creates a new reservation.'),
        ],
        'related': ['reservations.new', 'reservations.detail'],
        'tour': [
            {'target': 'reservations-mobile-list-new', 'text': T('زر «+» لحجز جديد.',
                                              'The "+" button makes a new reservation.')},
            {'target': 'reservations-mobile-list-filters', 'text': T('شرائح الفلتر: النشطة، الكل، قيد الانتظار…',
                                              'Filter chips: active, all, pending…')},
            {'target': 'reservations-mobile-list-list', 'text': T('الحجوزات حسب الفلتر.',
                                              'The reservations matching the filter.')},
            {'target': 'reservations-mobile-list-card', 'text': T('اضغط على أي حجز لتفاصيله وتحريكه للخطوة اللي بعدها.',
                                              'Tap any reservation for its details and to move it to its next step.')},
        ],
        'updated': '2026-10-10',
    },
]
