from . import T

MODULE = {
    'key': 'pos', 'group': 'operations', 'icon': '🧾',
    'title': T('نقطة البيع (POS غير المباشر)', 'Point of sale (indirect POS)'),
    'summary': T(
        'شاشة البيع في النظام تطابق شاشة «نقطة البيع غير المباشرة» في SOFTECH حقلاً بحقل، بنفس الاختصارات. '
        'الصيدلي أو المندوب أو الكول سنتر يجهّز «أمر البيع» هنا (القناة، العميل، الأصناف والتشغيلات، الخصم، السداد)، ثم يُرسل '
        'كأمر معلّق إلى شاشة الكاشير في SOFTECH، والكاشير يحصّل ويُصدر الفاتورة النهائية. لو انقطع الاتصال بالفرع يدخل الأمر '
        '«طابور» ويُرسل تلقائياً عند عودة الاتصال، ولا يمكن أن يُرسل الأمر مرتين.',
        'The sales screen mirrors the SOFTECH "Indirect point of sale" screen field for field, with the same shortcuts. '
        'A pharmacist, salesperson or the call center prepares the "sales order" here (channel, customer, items and batches, discount, '
        'payment), then it is sent as a pending order to the cashier screen in SOFTECH, where the cashier collects and issues the final '
        'invoice. If the branch connection is down the order joins a "queue" and is sent automatically when it is back; an order can '
        'never be sent twice.'),
    'workflows': [{
        'key': 'order',
        'title': T('مراحل أمر البيع', 'Sales order stages'),
        'model': 'pos_orders.SoftechSalesOrder', 'field': 'status',
        'states': [
            {'key': 'draft', 'label': T('مسودة', 'Draft'), 'desc': T('الأمر قيد الإعداد على الشاشة.', 'Being prepared on the screen.')},
            {'key': 'ready', 'label': T('جاهز للإرسال', 'Ready to send'), 'desc': T('اكتملت البيانات ومرّ بالتحقق.', 'Data complete and validated.')},
            {'key': 'queued', 'label': T('بانتظار الاتصال (طابور)', 'Queued (waiting for connection)'),
             'desc': T('الفرع أو SOFTECH غير متاح؛ سيُرسل تلقائياً عند عودة الاتصال (أو من «إعادة إرسال الطابور»).', 'The branch or SOFTECH is unreachable; it will be sent automatically when back (or via "resend queue").')},
            {'key': 'pushing', 'label': T('جارٍ الإرسال', 'Sending'), 'desc': T('يُكتب الآن في SOFTECH.', 'Being written to SOFTECH now.')},
            {'key': 'pushed', 'label': T('بانتظار الكاشير', 'Waiting for the cashier'),
             'desc': T('وصل لشاشة الكاشير في SOFTECH كأمر معلّق. العميل يتوجه للكاشير للسداد.', 'It reached the SOFTECH cashier screen as a pending order. The customer goes to the cashier to pay.')},
            {'key': 'push_failed', 'label': T('فشل الإرسال', 'Send failed'), 'desc': T('حدث خطأ أثناء الكتابة — يظهر في «مركز الاستثناءات» للمراجعة أو إعادة المحاولة أو الإلغاء.', 'An error during writing — it appears in the "Exception center" to review, retry or cancel.')},
            {'key': 'settled', 'label': T('تم التحصيل (الكاشير)', 'Settled (cashier)'), 'desc': T('الكاشير حصّل وأُصدرت الفاتورة النهائية في SOFTECH؛ يُقرأ رقمها تلقائياً.', 'The cashier collected and the final SOFTECH invoice exists; its number is read back automatically.')},
            {'key': 'cancelled', 'label': T('ملغى', 'Cancelled'), 'desc': T('أُلغي قبل التحصيل.', 'Cancelled before collection.')},
        ],
    }],
}

_TABS = [
    {'key': 'items', 'title': T('الأصناف', 'Items'),
     'body': T('جدول الأصناف بنفس أعمدة SOFTECH: الكود، الصنف، الكمية، العبوة (علبة/شريط)، السعر، الخصم %، الضريبة، الصافي، رصيد متاح، رصيد صلاحية، وتاريخ الصلاحية ورقم الباتش. '
               'F2 للبحث وإضافة صنف (بالاسم أو الكود أو الباركود)، Q لإدخال الكمية بالشرائط/الوحدات، F4 أو Delete لحذف السطر. اختر التشغيلة من نافذة الباتشات (الأقرب انتهاءً أولاً). '
               'لو ظهر «خصم مقترح» اضغط لتطبيقه. يمكن إضافة الأصناف من صورة الروشتة (OCR) أو من سجل معاملات العميل، ويظهر «يُشترى معه عادةً».',
               'The items grid with the same columns as SOFTECH: code, item, quantity, pack (box/strip), price, discount %, VAT, net, available stock, expiry stock, expiry date and batch. '
               'F2 to search and add an item (name, code or barcode), Q to enter quantity in strips/units, F4 or Delete to remove the line. Pick the batch in the batch window (nearest expiry first). '
               'If a "suggested discount" appears, click to apply it. Items can be added from a prescription photo (OCR) or the customer\'s history, and "often bought with" is shown.')},
    {'key': 'payment', 'title': T('السداد', 'Payment'),
     'body': T('طرق السداد: نقدى أو آجل فقط (تفاصيل الفيزا والشيك تُسجل على شاشة الكاشير في SOFTECH). المدفوع يجب أن يساوي الصافي؛ النظام يعرض «متبقٍّ» أو «فكة». خصم الفكة له حد أقصى 0.50 جنيه.',
               'Payment methods: cash or credit only (card and cheque details are taken on the SOFTECH cashier screen). Paid must equal net; the system shows "still due" or "change". The rounding (fakka) discount is capped at 0.50 EGP.')},
    {'key': 'query', 'title': T('نافذة العميل — إستعلام', 'Customer pop-up — Query'),
     'body': T('من زر «إسم العميل»: ابحث بالاسم أو الهاتف أو كود PIC واختر العميل من النتائج.', 'From the "Customer name" button: search by name, phone or PIC and pick the customer from the results.')},
    {'key': 'add', 'title': T('نافذة العميل — إضافة جديد', 'Customer pop-up — Add new'),
     'body': T('إنشاء عميل سريع (الاسم، الهاتف، العنوان، تاريخ الميلاد، نسبة الخصم، نظام النقاط…) ثم «تخزين» (Ctrl+S). البيانات الكاملة للعميل تُدار من موديول العملاء.', 'Quick-create a customer (name, phone, address, birth date, discount %, points system…) then "Save" (Ctrl+S). The full customer record is managed in the Customers module.')},
    {'key': 'contract', 'title': T('بيانات التعاقد', 'Contract data'),
     'body': T('يظهر لقنوات التعاقد والتأمين والموظفين والعميل الدائم: بيانات المريض، تاريخ المطالبة، الطبيب المُحيل وكوده، صورة الروشتة، وما يسدده المريض مقابل ما يتحمله التعاقد. لا يمكن الإرسال قبل اكتمالها.',
               'Shown for contract, insurance, employee and permanent-customer channels: patient data, claim date, referring doctor and code, prescription photo, and the patient\'s share vs the contract\'s share. The order cannot be sent until it is complete.')},
]

_STEPS = [
    T('اختر «نوع العميل/القناة» (نقدى Ctrl+F2، توصيل Ctrl+F3، تعاقد، تأمين، موظفين، VIP، عميل دائم) ومسؤول البيع.',
      'Choose the "customer type/channel" (cash Ctrl+F2, delivery Ctrl+F3, contract, insurance, employees, VIP, permanent) and the salesperson.'),
    T('حدد العميل (PIC) — إجباري للتوصيل وقنوات التعاقد. شريط العميل يعرض نقاطه وتنبيهاته الصحية (حساسية، حمل…) أولاً.',
      'Pick the customer (PIC) — required for delivery and contract channels. The customer bar shows their points and health alerts (allergy, pregnancy…) first.'),
    T('أضف الأصناف (F2) واختر التشغيلة والكمية، وطبّق الخصم المقترح لو مناسب.', 'Add items (F2), pick the batch and quantity, and apply the suggested discount if appropriate.'),
    T('أكمل «بيانات التعاقد» لو القناة تتطلبها، ثم «السداد» حتى يتوازن المدفوع مع الصافي.', 'Complete "Contract data" if the channel needs it, then "Payment" until paid equals net.'),
    T('شريط سير العمل أعلى الشاشة يوضح الخطوة التالية وأي تنبيه يمنع الحفظ. «الوضع الموجّه» يأخذك خطوة بخطوة للمبتدئين.',
      'The workflow bar at the top shows the next step and any warning that blocks saving. "Guided mode" takes beginners step by step.'),
    T('F9 «معاينة الإرسال» (تجريبي لا يكتب شيئاً) ثم F10 «إرسال فعلي للكاشير». «معاينة الإيصال» لطباعة إيصال للعميل.',
      'F9 "Preview send" (a dry run that writes nothing), then F10 "Live send to the cashier". "Receipt preview" prints a receipt for the customer.'),
    T('«تعليق السلة» يحفظ الأمر جانباً لخدمة عميل آخر، و«السلال المعلّقة» لاسترجاعه.', '"Park basket" sets the order aside to serve another customer; "Parked baskets" brings it back.'),
]

_TIPS = [
    T('التنبيه الصحي للعميل (حساسية، حمل، طفل) يظهر قبل أي اقتراح بيع — لا تتجاهله.', 'The customer\'s health alert (allergy, pregnancy, child) shows before any sales suggestion — never ignore it.'),
    T('المرتجع يتطلب رقم الفاتورة الأصلية، وخلال 90 يوماً كحد أقصى.', 'A return needs the original invoice number and must be within 90 days.'),
    T('قنوات النقدى والتوصيل فقط تكتسب نقاط ولاء؛ التعاقد والتأمين لا.', 'Only cash and delivery channels earn loyalty points; contract and insurance do not.'),
    T('لو زر «إرسال فعلي» مُعطّل فالكتابة في SOFTECH غير مفعّلة بعد لهذا الفرع — استخدم المعاينة وبلّغ المسؤول.', 'If "Live send" is disabled, SOFTECH writing is not switched on for this branch yet — use the preview and tell the admin.'),
    T('كوبون الهدية: أدخل السريال المطبوع عليه، والفاتورة تكون على كود صاحب الكوبون.', 'Gift coupon: enter the serial printed on it; the invoice goes on the coupon owner\'s code.'),
]

SCREENS = [
    {
        'key': 'pos.order',
        'routes': ['/pos'],
        'title': T('نقطة البيع', 'Point of sale'),
        'summary': T('تجهيز أمر بيع وإرساله لكاشير الفرع في SOFTECH، بنفس شكل واختصارات شاشة SOFTECH: القناة والخيارات يميناً، الأصناف والسداد وبيانات التعاقد في المنتصف، ولوحة الأرقام يساراً (يمكن طيّ الجانبين).',
                     'Prepare a sales order and send it to the branch cashier in SOFTECH, with the same layout and shortcuts as SOFTECH: channel and options on the right, items, payment and contract data in the middle, the numpad on the left (both sides fold away).'),
        'audience': T('الصيادلة، المندوبون، الكول سنتر، المشرفون.', 'Pharmacists, salespeople, call center, supervisors.'),
        'tabs': _TABS,
        'steps': _STEPS,
        'tips': _TIPS,
        'faq': [
            {'q': T('ما الفرق بين المعاينة والإرسال الفعلي؟', 'What is the difference between preview and live send?'),
             'a': T('المعاينة (F9) تعرض بالضبط ما سيُكتب في SOFTECH بدون كتابة. الإرسال الفعلي (F10) يكتب الأمر المعلّق لشاشة الكاشير.',
                    'Preview (F9) shows exactly what would be written to SOFTECH without writing. Live send (F10) writes the pending order to the cashier screen.')},
            {'q': T('انقطع الإنترنت أثناء الإرسال، هل يتكرر الأمر؟', 'The connection dropped while sending — will the order duplicate?'),
             'a': T('لا. كل أمر له مفتاح فريد يمنع التكرار؛ يدخل الطابور ويُرسل مرة واحدة عند عودة الاتصال.',
                    'No. Each order has a unique key that prevents duplicates; it joins the queue and is sent once when the connection returns.')},
        ],
        'related': ['pos.mobile', 'pos.exceptions', 'pos.offers', 'customers.detail'],
        'workflows': ['order'],
        'updated': '2026-10-10',
    },
    {
        'key': 'pos.mobile',
        'routes': ['/m/pos'],
        'title': T('نقطة البيع (موبايل)', 'Point of sale (mobile)'),
        'summary': T('نفس منطق نقطة البيع على الموبايل في عمود واحد: البحث أو مسح الباركود، الأصناف، ونوافذ سفلية للسداد وبيانات التعاقد وبيانات الرأس، مع وضع موجّه وتعليق السلال والإيصال.',
                     'The same POS logic on the phone in one column: search or scan, items, and bottom sheets for payment, contract data and header data, with guided mode, parked baskets and receipts.'),
        'audience': T('المندوبون والصيادلة على الأرض.', 'Salespeople and pharmacists on the floor.'),
        'tabs': _TABS,
        'steps': [
            T('اختر نوع العميل والعميل (PIC) من الأعلى.', 'Choose the customer type and the customer (PIC) at the top.'),
            T('امسح الباركود أو ابحث وأضف الأصناف؛ «روشتة / صوت» لإضافة الأصناف من صورة الروشتة.', 'Scan or search to add items; "Prescription / voice" adds items from a prescription photo.'),
            T('افتح «السداد» من الأسفل، ثم «معاينة» أو «فعلي» للإرسال.', 'Open "Payment" at the bottom, then "Preview" or "Live" to send.'),
        ],
        'tips': _TIPS[:3],
        'related': ['pos.order'],
        'workflows': ['order'],
        'updated': '2026-10-10',
    },
    {
        'key': 'pos.exceptions',
        'routes': ['/pos/exceptions'],
        'title': T('مركز الاستثناءات (أوامر البيع)', 'Exception center (sales orders)'),
        'summary': T(
            'الأوامر التي تحتاج تدخّل مدير: فشل الإرسال، المتوقفة أثناء الإرسال، العالقة في الطابور، والمرسلة للكاشير منذ مدة ولم تُحصَّل (خطر تسريب). '
            'مع «القيمة المعرّضة للخطر»، واتجاه «الفرص الضائعة» (أصناف دخلت الشاشة بسعر ثم أُلغيت قبل الحفظ) حسب الفرع والكاشير.',
            'Orders that need a manager: send failed, stuck while sending, stuck in the queue, and sent to the cashier long ago but not collected (leakage risk). '
            'With the "value at risk", and the "lost opportunities" trend (items entered with a price then removed before saving) by branch and cashier.'),
        'audience': T('المديرون والمشرفون والصيادلة المسؤولون.', 'Managers, supervisors and responsible pharmacists.'),
        'steps': [
            T('راجع كل استثناء: الفرع، العميل، القيمة، العمر، والتفاصيل.', 'Review each exception: branch, customer, value, age and details.'),
            T('«إعادة إرسال الطابور» بعد عودة اتصال الفرع؛ أو «إلغاء الأمر» لو لن يُحصَّل.', '"Resend queue" once the branch is back online; or "Cancel order" if it will not be collected.'),
            T('الأوامر «بانتظار الكاشير متأخر» تحتاج اتصالاً بالفرع: هل حصّل الكاشير بدون الأمر؟', '"Awaiting cashier — late" orders need a call to the branch: did the cashier collect without the order?'),
            T('قسم «المبيعات غير المخزنة» (اختر فرعاً): أكثر الأصناف ضياعاً والإلغاءات حسب الكاشير.', 'The "unsaved sales" section (pick a branch): most-lost items and removals by cashier.'),
        ],
        'tips': [T('الصفحة تتحدّث تلقائياً كل 30 ثانية، ولا تكتب في SOFTECH من نفسها.', 'The page refreshes every 30 seconds and never writes to SOFTECH on its own.')],
        'related': ['pos.order'],
        'workflows': ['order'],
        'updated': '2026-10-10',
    },
    {
        'key': 'pos.offers',
        'routes': ['/offers'],
        'title': T('العروض والتخفيضات', 'Offers & promotions'),
        'summary': T(
            'محرّك عروض مرن تُطبَّق عبر نقطة البيع: 8 أنواع (خصم نسبة، خصم مبلغ، اشترِ X واحصل على Y، خصم متدرّج بالكمية، صنف هدية، مكافأة عند تجاوز مبلغ، باقة بسعر ثابت، اختر أي N من مجموعة). '
            'تحدد الأصناف بأي حقل من الكتالوج (الشركة، المورد، العائلة، الشكل، السعر…) وترى معاينة حية بالأصناف المطابقة، مع لوحة «تعارضات» (بيع بخسارة، تداخل، أولوية).',
            'A flexible offers engine applied through the POS: 8 types (percent off, fixed amount off, buy X get Y, quantity tiers, gift item, reward over a spend, fixed-price bundle, pick any N from a group). '
            'Target items by any catalog field (company, supplier, family, form, price…) with a live preview of matching items, and a "contradictions" panel (selling at a loss, overlaps, priority).'),
        'audience': T('الإدارة والمشتريات والمشرفون.', 'Management, purchasing and supervisors.'),
        'steps': [
            T('«عرض جديد» ← الأساسيات (الاسم بالعربي والإنجليزي، النوع، الحالة، الأولوية، القنوات: كاش/توصيل/تعاقد).', '"New offer" → basics (Arabic and English name, type, status, priority, channels: cash/delivery/contract).'),
            T('حدد الأصناف بشروط «يتضمن / لا يتضمن / يحتوي» على حقول الكتالوج، وراجع قائمة المطابق — يمكنك استبعاد أصناف منها.',
              'Select items with "includes / excludes / contains" conditions on catalog fields, and review the match list — you can exclude items from it.'),
            T('حدد قيمة العرض ومصدرها، وقواعد التجميع مع عروض أخرى والموافقة، وحدود الاستخدام، وفترة الصلاحية.', 'Set the value and its source, stacking and approval rules, usage limits and the validity window.'),
            T('راجع لوحة التعارضات قبل التفعيل، ثم «حفظ العرض» وغيّر الحالة إلى «فعّال».', 'Check the contradictions panel before activating, then "Save offer" and set status to "Active".'),
        ],
        'tips': [
            T('الاسم العلمي في الكتالوج قد يكون غير دقيق — راجع قائمة الأصناف المطابقة دائماً.', 'The scientific name in the catalog may be inaccurate — always review the matched item list.'),
            T('تنفيذ العروض داخل SOFTECH مُقيَّد بمفتاح تشغيل؛ النظام يحسب العرض ويعرضه في نقطة البيع.', 'Executing offers inside SOFTECH is behind a switch; the system calculates the offer and shows it at the POS.'),
        ],
        'related': ['pos.order', 'pricing.approvals'],
        'workflows': ['offer'],
        'updated': '2026-10-10',
    },
]

# offers have their own status list (shown with the module's workflows)
MODULE['workflows'].append({
    'key': 'offer',
    'title': T('حالة العرض', 'Offer status'),
    'model': 'offers.Offer', 'field': 'status',
    'states': [
        {'key': 'draft', 'label': T('مسودة', 'Draft'), 'desc': T('قيد الإعداد ولا يُطبَّق.', 'Being set up; not applied.'), 'next': ['active']},
        {'key': 'active', 'label': T('فعّال', 'Active'), 'desc': T('يُطبَّق في نقطة البيع خلال فترة صلاحيته.', 'Applied at the POS during its validity.'), 'next': ['paused', 'expired']},
        {'key': 'paused', 'label': T('موقوف', 'Paused'), 'desc': T('أُوقف مؤقتاً.', 'Temporarily stopped.'), 'next': ['active']},
        {'key': 'expired', 'label': T('منتهي', 'Expired'), 'desc': T('انتهت فترة صلاحيته.', 'Its validity window ended.')},
    ],
})
