from . import T

# Longer explanations ("more") shared by the screen tours and the module tours.
DM_MORE_NEW = T(
    'استخدمه كل مرة عميل يطلب صنف مش قادرين نصرفه دلوقتي (نفد، قليل، مش متخزّن، أو بيسأل على السعر) — حتى لو العميل ماشي.\n'
    '• بيفتح نافذة «تسجيل طلب عميل جديد»: بيانات العميل، الفرع والمصدر والأولوية، والأصناف.\n'
    '• الطلب بيتسجّل «جديد» وبعدها بتتفتح صفحته، ولازم يتعيّن لموظف خلال 10 دقايق.',
    'Use it every time a customer asks for an item we cannot dispense right now (out, low, not stocked, or a price check) — even if the customer is leaving.\n'
    '• It opens the "Record a new customer request" window: customer data, branch, source and priority, and the items.\n'
    '• The request is saved as "New" and its page opens; it must be assigned to an employee within 10 minutes.')
DM_MORE_TABS = T(
    'كل تبويب بيعرض الطلبات اللي في المرحلة دي: جديد، مُعيَّن، متابعة، انتظار المخزون، للمشتريات، بيع ضائع، تم التسليم — و«الكل».\n'
    '• ابدأ بـ «جديد» عشان محدش يتعدى عليه وقت الـ SLA.\n'
    '• جنب البحث فيه فلتر «⚠ SLA تجاوز فقط» للطلبات المتأخرة.',
    'Each tab shows the requests at that stage: new, assigned, follow-up, waiting for stock, to purchasing, lost sale, fulfilled — and "All".\n'
    '• Start with "New" so nothing passes its SLA time.\n'
    '• Next to search there is an "⚠ SLA breached only" filter for late requests.')
DM_MORE_SEARCH = T(
    'اكتب رقم تليفون العميل أو اسمه أو كود PIC أو اسم الصنف.\n'
    '• مفيد لما العميل يتصل يسأل على طلبه، أو قبل ما تسجّل طلب جديد تتأكد إنه مش متسجّل.\n'
    '• جنبه فلاتر الأولوية والفرع، و«مسح» يرجّع كل الفلاتر.',
    'Type the customer\'s phone, name, PIC code or the item name.\n'
    '• Useful when a customer calls about their request, or to check a request is not already recorded before logging a new one.\n'
    '• Next to it are priority and branch filters, and "Clear" resets them all.')
DM_MORE_TABLE = T(
    'كل صف: رقم الطلب، العميل، الفرع، الأصناف، الحالة، الأولوية، وقت الـ SLA، ومين مسؤول.\n'
    '• اضغط الصف عشان تفتح الطلب وتتابعه.\n'
    '• علّم أكتر من طلب بمربع الاختيار فيظهر شريط تعيين جماعي لموظف، أو إرسال للمشتريات، أو إلغاء.',
    'Each row: request number, customer, branch, items, status, priority, SLA time and owner.\n'
    '• Click a row to open the request and follow it.\n'
    '• Tick several requests and a bar appears to assign them to an employee, send them to purchasing, or cancel them.')
DM_MORE_OPEN = T(
    'افتح أي طلب عشان تكمّل الجولة على صفحة تفاصيله (العميل، الأصناف، المتابعات، والسجلات).\n'
    '• لو القائمة فاضية اضغط «إنهاء».',
    'Open any request to continue the tour on its detail page (customer, items, follow-ups and logs).\n'
    '• If the list is empty, press "End".')
DM_MORE_RECOVERY = T(
    'بيفتح «قائمة الاسترداد»: عملاء طلبوا أصناف نفدت والمزامنة لقت إنها رجعت للمخزون.\n'
    '• الرقم الأحمر على الزر هو عدد الفرص المفتوحة.\n'
    '• اتصل بالعميل من هناك وحوّل الطلب لحجز أو سجّل البيعة المستردة.',
    'Opens the "Recovery queue": customers who asked for items that ran out and the sync found back in stock.\n'
    '• The red number on the button is how many opportunities are open.\n'
    '• Contact the customer from there and turn it into a reservation or record the recovered sale.')
DM_MORE_CUSTOMER = T(
    'ابحث عن العميل بالاسم أو الهاتف أو كود PIC عشان بياناته تتملي لوحدها، أو اكتبها يدوي.\n'
    '• رقم الهاتف إجباري: موبايل 11 رقم بيبدأ بـ 01، أو أرضي بكود المحافظة.\n'
    '• من غير رقم صحيح مش هنعرف نبلّغه لما الصنف يرجع.',
    'Search the customer by name, phone or PIC code to fill their data automatically, or type it in.\n'
    '• The phone is required: an 11-digit mobile starting 01, or a landline with its area code.\n'
    '• Without a valid number we cannot tell them when the item is back.')
DM_MORE_DETAILS = T(
    '• «الفرع» (إجباري): الفرع اللي العميل طلب منه.\n'
    '• «مصدر الطلب»: حضر للفرع، اتصال، واتساب، تطبيق توصيل، موقع، مركز الاتصالات.\n'
    '• «الأولوية»: منخفض، عادي، عالٍ، عاجل، أو «مزمن 💊».',
    '• "Branch" (required): the branch the customer asked at.\n'
    '• "Request source": walk-in, call, WhatsApp, delivery app, website, call center.\n'
    '• "Priority": low, normal, high, urgent, or "chronic 💊".')
DM_MORE_ITEMS = T(
    'ابحث بالاسم أو الكود أو الباركود (القارئ شغال) وضيف كل صنف بكميته.\n'
    '• لو الصنف مش في الكتالوج: «+ إضافة صنف غير مكوَّد (يدوي)» واكتب اسمه وسعر تقديري (مش من SOFTECH).\n'
    '• لو ظهر بديل بنفس المادة الفعّالة ممكن تعرضه على العميل — القرار للصيدلي، مفيش استبدال تلقائي.',
    'Search by name, code or barcode (the scanner works) and add each item with its quantity.\n'
    '• If the item is not in the catalog: "+ Add an uncoded item (manual)" and type its name and an estimated price (not from SOFTECH).\n'
    '• If an alternative with the same active ingredient shows, you may offer it — the pharmacist decides; there is no automatic substitution.')
DM_MORE_SUBMIT = T(
    'بيحفظ الطلب «جديد» ويفتح صفحة تفاصيله على طول.\n'
    '• الزر مقفول لحد ما تضيف صنف واحد على الأقل.\n'
    '• بعد الحفظ النظام بيدوّر على العميل في الـ ERP تلقائياً.',
    'Saves the request as "New" and opens its detail page straight away.\n'
    '• The button stays disabled until you add at least one item.\n'
    '• After saving, the system looks the customer up in the ERP automatically.')
DM_MORE_DHEADER = T(
    'رقم الطلب وحالته وأولويته، و«⚠ SLA تجاوز» لو اتأخر.\n'
    '• تحتهم اسم العميل والفرع من إمتى، وجنبهم عدّاد الـ SLA: أخضر لسه فيه وقت، أصفر قرب يخلص، أحمر اتعدّى.',
    'The request number, status and priority, and "⚠ SLA breached" if it is late.\n'
    '• Below them the customer, branch and how long ago, and next to them the SLA timer: green has time, amber is nearly out, red has passed.')
DM_MORE_DTABS = T(
    '• «📋 التفاصيل»: بيانات العميل وربطه بـ SOFTECH وتفاصيل الطلب.\n'
    '• «💊 الأصناف»: الكميات والمخزون في الفرع والبدائل.\n'
    '• «🔔 المتابعات»: مهام تواصل مجدولة بتاريخ.\n'
    '• «💬 السجلات»: ملاحظات واتصالات وتغييرات الحالة.',
    '• "📋 Details": customer data, SOFTECH link and request details.\n'
    '• "💊 Items": quantities, branch stock and alternatives.\n'
    '• "🔔 Follow-ups": scheduled contact tasks with a date.\n'
    '• "💬 Logs": notes, calls and status changes.')
DM_MORE_DCONTENT = T(
    'هنا محتوى التبويب اللي فاتحه.\n'
    '• في «المتابعات» تقدر تجدول تذكير بالتواصل الجاي وتقفله بملاحظة لما تنفّذه.\n'
    '• في «السجلات» اكتب ملاحظة أو سجل اتصال وابعته بـ Ctrl+Enter.',
    'This is the content of the open tab.\n'
    '• In "Follow-ups" you can schedule a reminder for the next contact and close it with a note when done.\n'
    '• In "Logs" write a note or a call log and send it with Ctrl+Enter.')
DM_MORE_DACTIONS = T(
    'الأزرار بتتغيّر حسب المرحلة والصلاحية:\n'
    '• «👤 تعيين» (للطلب الجديد) تختار الموظف المسؤول.\n'
    '• «📞 تواصلت مع العميل»، «⏳ ينتظر المخزون»، «تم التوريد»، «بيع ضائع» بسبب إجباري، و«إلغاء الطلب».\n'
    '• «بحث في ERP» يربط العميل بكوده في SOFTECH. كل تغيير حالة بيتسجّل في السجلات.',
    'The buttons change with the stage and your permission:\n'
    '• "👤 Assign" (for a new request) picks the responsible employee.\n'
    '• "📞 Contacted the customer", "⏳ Waiting for stock", "Supplied", "Lost sale" with a required reason, and "Cancel request".\n'
    '• "Search ERP" links the customer to their SOFTECH code. Every status change is recorded in the logs.')
DM_MORE_CONTACT = T(
    'بعد ما تكلّم العميل، اضغطه واكتب نتيجة المكالمة ثم «تأكيد».\n'
    '• الطلب بيتنقل لـ «متابعة» والملاحظة بتتسجّل في السجلات.\n'
    '• بيظهر بعد التعيين — الطلب «الجديد» لازم يتعيّن الأول.',
    'After calling the customer, press it, write the call outcome, then "Confirm".\n'
    '• The request moves to "Follow-up" and the note is saved in the logs.\n'
    '• It shows after assignment — a "New" request must be assigned first.')
DM_MORE_FULFILL = T(
    'لما العميل ياخد الصنف فعلاً: اضغطه، اكتب رقم الفاتورة (اختياري) و«تأكيد».\n'
    '• الطلب بيقفل «تم التسليم» والأصناف اللي لسه مستنية بتتعلّم مُسلَّمة.\n'
    '• مرحلة نهائية، ومحتاج صلاحية الإنهاء. مش بيكتب في SOFTECH.',
    'When the customer actually gets the item: press it, enter the invoice number (optional) and "Confirm".\n'
    '• The request closes as "Fulfilled" and the still-pending items are marked fulfilled.\n'
    '• A final stage that needs the finalize permission. It does not write to SOFTECH.')
DB_MORE_DAYS = T(
    'كل الأرقام والقوائم تحت بتتحسب على الفترة دي.\n'
    '• 7 أو 14 يوم للمتابعة الأسبوعية، 30 لـ 90 يوم لقرارات الشراء.',
    'All figures and lists below are calculated over this period.\n'
    '• 7 or 14 days for weekly follow-up, 30 to 90 days for purchasing decisions.')
DB_MORE_NEW = T(
    'بيوديك لشاشة الطلب الضائع عشان تسجّل طلب عميل من هناك بـ «+ تسجيل طلب جديد».\n'
    '• اللوحة نفسها للتحليل بس.',
    'Takes you to the lost-demand screen to record a customer request there with "+ Log new request".\n'
    '• The dashboard itself is for analysis only.')
DB_MORE_KPIS = T(
    '• إجمالي الطلبات، ونسبة «تم التوريد»، و«بيع ضائع» ونسبته، و«قيمة مؤكدة ضائعة».\n'
    '• الصف التاني: النشط دلوقتي، الإيراد المُسترَد، المتابعات المتأخرة، وفرص الاسترداد المفتوحة.\n'
    'المتابعات المتأخرة والفرص المفتوحة هي شغلك النهارده.',
    '• Total requests, the "Fulfilled" rate, "Lost sales" and their share, and "Confirmed lost value".\n'
    '• Second row: active now, recovered revenue, overdue follow-ups and open recovery opportunities.\n'
    'Overdue follow-ups and open opportunities are today\'s work.')
DB_MORE_TOP = T(
    'قائمتين: الأصناف اللي اتسجلت أكتر كبيع ضائع، والأصناف الأكتر طلباً بكل الحالات.\n'
    '• الصنف اللي متكرر هنا مرشّح يتراجع رصيده الأدنى أو يتضاف للأوردر مع المشتريات.',
    'Two lists: the items most recorded as lost sales, and the most requested items in all statuses.\n'
    '• An item that repeats here is a candidate to review its minimum stock or add to the order with purchasing.')
DB_MORE_CHRONIC = T(
    '• «نقص مزمن»: صنف بيتطلب كتير ومش بيتوفّر — يتضاف للأوردر الدوري أو طلب تحويل.\n'
    '• «أصناف متوقفة مع طلب نشط»: اقفل الطلبات دي أو بلّغ العملاء إن الصنف مش متاح.',
    '• "Chronic shortage": an item asked for often and not supplied — add it to the periodic order or request a transfer.\n'
    '• "Discontinued items with active requests": close those requests or tell customers the item is unavailable.')
DB_MORE_SUGG = T(
    'أصناف طلبها عملاء حقيقيون (مفتوحة + ضائعة) مرتّبة بالقيمة الضائعة المؤكدة.\n'
    '• «⬇ تصدير CSV» بينزّل القائمة.\n'
    '• «📦 إرسال للمشتريات» بيبعتها اقتراحات شراء للوحة المشتريات — المشتريات هي اللي بتقرر تطلب ولا لأ.',
    'Items real customers asked for (open + lost), sorted by confirmed lost value.\n'
    '• "⬇ Export CSV" downloads the list.\n'
    '• "📦 Send to purchasing" sends them as purchase suggestions to the purchasing board — purchasing decides whether to order.')
RC_MORE_HEADER = T(
    'الشاشة دي شغل يومي للكول سنتر والصيادلة: كل صف عميل صنفه رجع للمخزون.\n'
    '• بتتحدث لوحدها بعد المزامنة.\n'
    '• الهدف: تكلّم العميل بسرعة وترجّع البيعة.',
    'This screen is daily work for the call center and pharmacists: each row is a customer whose item is back in stock.\n'
    '• It updates by itself after the sync.\n'
    '• The goal: contact the customer quickly and win the sale back.')
RC_MORE_KPIS = T(
    '• «إيراد مُسترَد (30 يوم)» وعدد البيعات المستردة.\n'
    '• «معدل الاسترداد» من الأصناف اللي رجعت للمخزون.\n'
    '• «فرص مفتوحة» و«قيمة الفرص المفتوحة»: اللي لسه مستني تواصل.',
    '• "Recovered revenue (30 days)" and the number of recovered sales.\n'
    '• "Recovery rate" of items that came back in stock.\n'
    '• "Open opportunities" and "Open opportunity value": what is still waiting for contact.')
RC_MORE_QUEUE = T(
    'كل صف: العميل وتليفونه ورقم الطلب، الصنف والكمية، الفرع، المخزون المتاح، القيمة، وأيام الانتظار.\n'
    '• ابدأ بأعلى قيمة والأقدم.\n'
    '• «🔕» لو العميل مش عايز يتابع الصنف، و«🚫» لاستبعاد صنف مش فرصة حقيقية (للي عنده صلاحية الاعتماد).',
    'Each row: the customer, phone and request number, the item and quantity, branch, available stock, value and days waiting.\n'
    '• Start with the highest value and the oldest.\n'
    '• "🔕" if the customer no longer wants the item, and "🚫" to exclude an item that is not a real opportunity (for those with approval permission).')
RC_MORE_WA = T(
    'بيفتح محادثة واتساب مع العميل في تبويب جديد، وفي نفس الوقت بيسجّل إنك تواصلت معاه.\n'
    '• بيظهر بس لو للعميل رقم صالح.',
    'Opens a WhatsApp chat with the customer in a new tab and records at the same time that you contacted them.\n'
    '• Shown only when the customer has a valid number.')
RC_MORE_RESERVE = T(
    'لو العميل عايز الصنف: بيعمل حجز باسم العميل للصنف ده ويفتح صفحة الحجز على طول.\n'
    '• بيظهر ويشتغل بس لو عندك صلاحية إنشاء الحجوزات (السيرفر بيتحقق).\n'
    '• بعدها الحجز بيمشي في موديول الحجوزات العادي.',
    'If the customer wants the item: creates a reservation for them for this item and opens the reservation page.\n'
    '• Shown and allowed only with reservation-create permission (the server checks).\n'
    '• From then on it follows the normal reservations module.')
RC_MORE_RECOVER = T(
    'لما العميل يشتري فعلاً: بيفتح «💰 تأكيد استرداد البيعة» بقيمة مقترحة (السعر المجمّد × الكمية).\n'
    '• عدّل القيمة عشان تطابق الفاتورة الفعلية ثم «تأكيد الاسترداد».\n'
    '• الصنف بيتعلّم «تم الاسترداد» ويتحسب في الإيراد المسترد ويختفي من القائمة.',
    'When the customer actually buys: opens "💰 Confirm sale recovery" with a suggested value (frozen price × quantity).\n'
    '• Adjust the value to match the real invoice, then "Confirm recovery".\n'
    '• The item is marked "Recovered", counts in recovered revenue and leaves the list.')
MB_MORE_FILTERS = T(
    'شرائح الحالة: «جديد» (الافتراضي)، الكل، متابعة، انتظار مخزون، تم التسليم، ضائعة.\n'
    '• ابدأ بـ «جديد» — دي اللي محتاجة حد يمسكها.',
    'Status chips: "New" (the default), all, follow-up, waiting for stock, fulfilled, lost.\n'
    '• Start with "New" — those need someone to take them.')
MB_MORE_CARD = T(
    'الكارت فيه رقم الطلب والحالة، و«SLA» بالأحمر لو الطلب اتأخر.\n'
    '• اضغطه يفتح التفاصيل: الاتصال بالعميل والأصناف والملاحظات.',
    'The card shows the request number and status, and a red "SLA" if the request is late.\n'
    '• Tap it to open the details: call the customer, the items and the notes.')
MB_MORE_NEW = T(
    'بيفتح نموذج سريع لتسجيل الطلب قدام العميل على الكاونتر.\n'
    '• الهاتف إجباري، والأصناف من البحث أو مكتوبة يدوي.',
    'Opens a quick form to record the request in front of the customer at the counter.\n'
    '• The phone is required; items come from search or are typed in.')
MB_MORE_CUSTOMER = T(
    '«رقم الهاتف» إجباري و«الاسم» اختياري.\n'
    '• الرقم ده اللي هنكلّم عليه العميل لما الصنف يرجع، فاتأكد منه.',
    '"Phone number" is required and "Name" is optional.\n'
    '• This is the number we call when the item is back, so double-check it.')
MB_MORE_ITEMS = T(
    'ابحث عن الصنف أو امسح الباركود وضيفه، أو اكتب اسم صنف غير مكوَّد واضغط «إضافة».\n'
    '• لازم صنف واحد على الأقل.',
    'Search or scan the item and add it, or type an uncoded item name and press "Add".\n'
    '• At least one item is required.')
MB_MORE_DETAILS = T(
    '• الفرع بيتحط فرعك تلقائياً (بعض الأدوار تقدر تختار فرع تاني).\n'
    '• اختار الأولوية والمصدر بالضغط، وضيف ملاحظات لو فيه تفاصيل.',
    '• The branch is set to yours automatically (some roles can pick another).\n'
    '• Tap to choose the priority and the source, and add notes if there are details.')
MB_MORE_SUBMIT = T(
    'بيسجّل الطلب ويفتح صفحته.\n'
    '• لو النت قاطع الطلب بيتحفظ على الجهاز ويتبعت لوحده لما النت يرجع، وبترجع للقائمة.\n'
    '• «إلغاء» يرجعك من غير حفظ.',
    'Records the request and opens its page.\n'
    '• If offline, the request is kept on the device and sent automatically when the connection returns, and you go back to the list.\n'
    '• "Cancel" goes back without saving.')
MD_MORE_HEADER = T(
    'رقم الطلب وحالته، و«SLA» بالأحمر لو اتأخر.\n'
    '• تغيير المراحل المتقدمة (تعيين، تم التوريد، بيع ضائع) بيتعمل من شاشة الكمبيوتر.',
    'The request number and status, and a red "SLA" if it is late.\n'
    '• Advanced stage changes (assign, supplied, lost sale) are done on the desktop screen.')
MD_MORE_CALL = T(
    'بيفتح الاتصال برقم العميل من الموبايل على طول.\n'
    '• بعد المكالمة اكتب النتيجة في «💬 الملاحظات» تحت عشان الكل يشوفها.',
    'Starts a call to the customer\'s number straight from the phone.\n'
    '• After the call, write the outcome in "💬 Notes" below so everyone sees it.')

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
    'flows': [
        {
            'key': 'lifecycle',
            'title': T('دورة الطلب الضائع', 'A missed request, start to finish'),
            'summary': T('تسجيل طلب لصنف مش موجود، ومتابعته لحد ما العميل ياخده.',
                         'Logging a request for an item we do not have, and following it until the customer gets it.'),
            'roles': ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor'],
            'steps': [
                {'target': 'nav-demand', 'nav': '/demand',
                 'text': T('«العمليات» ← «الطلب الضائع».',
                           '"Operations" → "Missed demand".'),
             'more': T('هنا بنسجّل كل طلب عميل ما قدرناش نلبّيه بدل ما يمشي ساكت.\n'
                           '• الرحلة: تسجيل ← تعيين لموظف خلال 10 دقايق ← تواصل مع العميل خلال 20 دقيقة ← توفير الصنف أو بديل ← «تم التسليم» أو «بيع ضائع».\n'
                           '• لما الصنف يرجع للمخزون العميل بيظهر في «قائمة الاسترداد»، والطلبات المتكررة بتوصل للمشتريات كإشارة.',
                           'Here we record every customer request we could not meet, instead of letting the customer leave silently.\n'
                           '• The journey: record → assign to an employee within 10 minutes → contact the customer within 20 minutes → get the item or an alternative → "Fulfilled" or "Lost sale".\n'
                           '• When the item is back in stock the customer appears in the "Recovery queue", and repeated requests reach purchasing as a signal.')},
                {'target': 'demand-list-tabs', 'route': '/demand',
                 'text': T('كل طلب بيمشي في المراحل دي لحد ما يتقفل.',
                           'Every request moves through these stages until closed.'),
             'more': DM_MORE_TABS},
                {'target': 'demand-list-new', 'route': '/demand',
                 'text': T('اضغط «+ تسجيل طلب جديد» وبعدين «التالي».',
                           'Click "+ Log new request", then "Next".'),
             'more': DM_MORE_NEW},
                {'target': 'demand-new-customer', 'route': '/demand',
                 'text': T('رقم واسم العميل — عشان نبلّغه لما الصنف يوصل.',
                           'The customer\'s phone and name — so we can tell them when it arrives.'),
             'more': DM_MORE_CUSTOMER},
                {'target': 'demand-new-details', 'route': '/demand',
                 'text': T('الفرع ومصدر الطلب والأولوية.',
                           'Branch, request source and priority.'),
             'more': DM_MORE_DETAILS},
                {'target': 'demand-new-items', 'route': '/demand',
                 'text': T('الأصناف المطلوبة (ولو مش في الكتالوج اكتبها يدوي).',
                           'The requested items (type them in if not in the catalog).'),
             'more': DM_MORE_ITEMS},
                {'target': 'demand-new-submit', 'route': '/demand',
                 'text': T('«📋 تسجيل الطلب». (في الجولة مش هنسجّل — اقفل النافذة.)',
                           '"📋 Log request". (In this tour we will not save — close the window.)'),
             'more': DM_MORE_SUBMIT},
                {'target': 'demand-list-table', 'route': '/demand', 'wait': '/demand/:id',
                 'text': T('افتح أي طلب عشان نشوف المتابعة. لو القائمة فاضية اضغط «إنهاء».',
                           'Open any request to see the follow-up. If the list is empty, press "End".'),
             'more': DM_MORE_OPEN},
                {'target': 'demand-detail-header', 'route': '/demand/:id',
                 'text': T('رقم الطلب وحالته وأولويته.',
                           'The request number, status and priority.'),
             'more': DM_MORE_DHEADER},
                {'target': 'demand-detail-contact', 'route': '/demand/:id',
                 'text': T('«📞 تواصلت مع العميل» وسجّل النتيجة.',
                           '"📞 Contacted the customer" and record the outcome.'),
             'more': DM_MORE_CONTACT},
                {'target': 'demand-detail-fulfill', 'route': '/demand/:id',
                 'text': T('«تم التوريد» لما العميل ياخد الصنف — بيقفل الطلب «تم التسليم».',
                           '"Supplied" when the customer gets the item — closes the request as "Fulfilled".'),
             'more': DM_MORE_FULFILL},
            ],
        },
        {
            'key': 'mobile',
            'title': T('الطلب الضائع من الموبايل', 'Missed demand on mobile'),
            'summary': T('تسجيل طلب ومتابعته من الموبايل.',
                         'Logging and following a request on mobile.'),
            'roles': ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor', 'quality_manager'],
            'mobile': True,
            'steps': [
                {'target': 'mshell-tabs',
                 'text': T('الشاشات في الشريط اللي تحت. اللي مش ظاهر تلاقيه في «المزيد».',
                           'Screens are in the bottom bar. Anything not shown is under "More".'),
             'more': T('شاشات الموبايل في الشريط اللي تحت؛ لو «الطلب الضائع» مش ظاهر هتلاقيه في «المزيد».\n'
                           '• الموبايل للتسجيل السريع قدام العميل والمتابعة؛ تغيير المراحل المتقدمة من الكمبيوتر.',
                           'Mobile screens are in the bottom bar; if "Lost demand" is not shown, it is under "More".\n'
                           '• The phone is for quick recording in front of the customer and follow-up; advanced stage changes are on the desktop.')},
                {'target': 'demand-mobile-list-filters', 'route': '/m/demand',
                 'text': T('فلتر الحالة.',
                           'Status filter.'),
             'more': MB_MORE_FILTERS},
                {'target': 'demand-mobile-list-new', 'route': '/m/demand', 'wait': '/m/demand/new',
                 'text': T('زر «+» لطلب جديد.',
                           'The "+" button for a new request.'),
             'more': MB_MORE_NEW},
                {'target': 'demand-mobile-new-customer', 'route': '/m/demand/new',
                 'text': T('رقم واسم العميل.',
                           'The customer\'s phone and name.'),
             'more': MB_MORE_CUSTOMER},
                {'target': 'demand-mobile-new-items', 'route': '/m/demand/new',
                 'text': T('الأصناف المطلوبة.',
                           'The requested items.'),
             'more': MB_MORE_ITEMS},
                {'target': 'demand-mobile-new-details', 'route': '/m/demand/new',
                 'text': T('الفرع والأولوية والمصدر.',
                           'Branch, priority and source.'),
             'more': MB_MORE_DETAILS},
                {'target': 'demand-mobile-new-submit', 'route': '/m/demand/new',
                 'text': T('«✅ تسجيل الطلب». (في الجولة مش هنسجّل.)',
                           '"✅ Log request". (In this tour we will not save.)'),
             'more': MB_MORE_SUBMIT},
                {'target': 'demand-mobile-list-card', 'route': '/m/demand', 'wait': '/m/demand/:id',
                 'text': T('افتح أي طلب. لو القائمة فاضية اضغط «إنهاء».',
                           'Open any request. If the list is empty, press "End".'),
             'more': MB_MORE_CARD},
                {'target': 'demand-mobile-detail-header', 'route': '/m/demand/:id',
                 'text': T('رقم الطلب وحالته.',
                           'The request number and status.'),
             'more': MD_MORE_HEADER},
                {'target': 'demand-mobile-detail-call', 'route': '/m/demand/:id',
                 'text': T('اتصل بالعميل.',
                           'Call the customer.'),
             'more': MD_MORE_CALL},
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
                                              '"+ Log new request" when a customer asks for an item we do not have.'),
             'more': DM_MORE_NEW},
            {'target': 'demand-list-tabs', 'text': T('تبويبات الحالة — كل طلب بيمشي من التسجيل لحد ما يتقفل.',
                                              'Status tabs — every request moves from logged until closed.'),
             'more': DM_MORE_TABS},
            {'target': 'demand-list-search', 'text': T('ابحث بالهاتف أو اسم العميل أو PIC أو الصنف.',
                                              'Search by phone, customer name, PIC or item.'),
             'more': DM_MORE_SEARCH},
            {'target': 'demand-list-table', 'text': T('قائمة الطلبات — افتح أي طلب لتفاصيله ومتابعته.',
                                              'The requests list — open any request for its details and follow-up.'),
             'more': DM_MORE_TABLE},
            {'target': 'demand-list-recovery', 'text': T('«🔔 عاد للمخزون» يوريك الطلبات اللي صنفها رجع، عشان تكلّم العميل.',
                                              '"🔔 Back in stock" shows requests whose item came back, so you can call the customer.'),
             'more': DM_MORE_RECOVERY},
            {'target': 'demand-list-table', 'wait': '/demand/:id',
             'text': T('افتح أي طلب — الجولة هتكمّل على صفحة تفاصيله. لو القائمة فاضية اضغط «إنهاء».',
                       'Open any request — the tour continues on its detail page. If the list is empty, press "End".'),
             'more': DM_MORE_OPEN},
        ],
        'tour_continue': 'demand.detail',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
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
                                              'The request number, status and priority.'),
             'more': DM_MORE_DHEADER},
            {'target': 'demand-detail-tabs', 'text': T('التبويبات: التفاصيل، الأصناف، المتابعات، السجلات.',
                                              'Tabs: details, items, follow-ups, logs.'),
             'more': DM_MORE_DTABS},
            {'target': 'demand-detail-content', 'text': T('محتوى التبويب المفتوح.',
                                              'The open tab\'s content.'),
             'more': DM_MORE_DCONTENT},
            {'target': 'demand-detail-actions', 'text': T('الإجراءات المتاحة للحالة الحالية.',
                                              'The actions available in the current status.'),
             'more': DM_MORE_DACTIONS},
            {'target': 'demand-detail-contact', 'text': T('«📞 تواصلت مع العميل» وسجّل النتيجة.',
                                              '"📞 Contacted the customer" and record the outcome.'),
             'more': DM_MORE_CONTACT},
            {'target': 'demand-detail-fulfill', 'text': T('«تم التوريد» لما العميل ياخد الصنف — بيقفل الطلب «تم التسليم».',
                                              '"Supplied" when the customer gets the item — closes the request as "Fulfilled".'),
             'more': DM_MORE_FULFILL},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
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
        'tour': [
            {'target': 'demand-dashboard-days', 'text': T('اختار الفترة (7، 14، 30، 60 أو 90 يوم) اللي الأرقام بتتحسب عليها.',
                                              'Choose the period (7, 14, 30, 60 or 90 days) the figures are calculated over.'),
             'more': DB_MORE_DAYS},
            {'target': 'demand-dashboard-new', 'text': T('«+ تسجيل طلب جديد» يوديك لشاشة الطلب الضائع لتسجيل طلب عميل.',
                                              '"+ Record new request" takes you to the lost-demand screen to record a customer request.'),
             'more': DB_MORE_NEW},
            {'target': 'demand-dashboard-kpis', 'text': T('ابدأ بالأرقام: إجمالي الطلبات، نسبة التوريد، البيع الضائع وقيمته المؤكدة.',
                                              'Start with the figures: total requests, fulfilment rate, lost sales and their confirmed value.'),
             'more': DB_MORE_KPIS},
            {'target': 'demand-dashboard-top-items', 'text': T('الأصناف الأكثر تسجيلاً كبيع ضائع، والأكثر طلباً بكل الحالات.',
                                              'The items most recorded as lost sales, and the most requested in all statuses.'),
             'more': DB_MORE_TOP},
            {'target': 'demand-dashboard-chronic', 'text': T('أصناف النقص المزمن (طلب متكرر غير مُستوفى)، والأصناف المتوقفة اللي عليها طلب نشط.',
                                              'Chronic shortage items (repeated unmet demand), and discontinued items that still have active requests.'),
             'more': DB_MORE_CHRONIC},
            {'target': 'demand-dashboard-suggestions', 'text': T('في «اقتراحات الشراء»: «⬇ تصدير CSV» أو «📦 إرسال للمشتريات» — بيظهر لو فيه اقتراحات.',
                                              'In "Purchase suggestions": "⬇ Export CSV" or "📦 Send to purchasing" — shown when there are suggestions.'),
             'more': DB_MORE_SUGG},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
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
            T('ابدأ بأعلى قيمة. اضغط «واتساب» لفتح المحادثة مع العميل وتسجيل التواصل تلقائياً (يظهر لو له رقم).',
              'Start with the highest value. Press "WhatsApp" to open the chat with the customer and log the contact automatically (shown when there is a number).'),
            T('لو العميل يريد الصنف: «حجز» يحوّل الطلب لحجز له (حسب صلاحية إنشاء الحجوزات).',
              'If the customer wants it: "Reserve" turns it into a reservation for them (needs reservation-create permission).'),
            T('لو اشترى فعلاً: «استرداد» وأكّد الإيراد المسترد (القيمة المقترحة = السعر المجمّد × الكمية، عدّلها لتطابق الفاتورة).',
              'If they bought: "Recover" and confirm the recovered revenue (suggested = frozen price × qty; adjust to match the invoice).'),
            T('لو رفض: زر «🔕» (رفض التواصل بخصوص هذا الصنف) مع السبب (لم يعد بحاجته، انتقل…).',
              'If they decline: the "🔕" button (customer declined about this item) with the reason (no longer needed, moved…).'),
            T('للأصناف التي لن تكون فرصة حقيقية (غير متوفرة في مصر، متوقفة، غير مسموح بيعها): زر «🚫» (استبعاد) — لمن لديه صلاحية الاعتماد.',
              'For items that are not a real opportunity (unavailable in Egypt, discontinued, not allowed): the "🚫" button (exclude) — for those with approval permission.'),
        ],
        'related': ['demand.dashboard', 'demand.list'],
        'tour': [
            {'target': 'demand-recovery-header', 'text': T('«قائمة الاسترداد»: عملاء طلبوا أصناف نفدت ورجعت للمخزون — بيظهروا هنا تلقائياً بعد المزامنة.',
                                              '"Recovery queue": customers who asked for items that ran out and are back in stock — they appear here automatically after sync.'),
             'more': RC_MORE_HEADER},
            {'target': 'demand-recovery-kpis', 'text': T('الأرقام: الإيراد المُسترَد (30 يوم)، معدل الاسترداد، الفرص المفتوحة وقيمتها.',
                                              'Figures: recovered revenue (30 days), recovery rate, open opportunities and their value.'),
             'more': RC_MORE_KPIS},
            {'target': 'demand-recovery-queue', 'text': T('جدول الفرص: العميل، الصنف، الفرع، المخزون المتاح، القيمة وأيام الانتظار.',
                                              'The opportunity table: customer, item, branch, available stock, value and days waiting.'),
             'more': RC_MORE_QUEUE},
            {'target': 'demand-recovery-whatsapp', 'text': T('«واتساب» يفتح المحادثة مع العميل ويسجّل التواصل تلقائياً (لو له رقم).',
                                              '"WhatsApp" opens the chat with the customer and logs the contact automatically (when there is a number).'),
             'more': RC_MORE_WA},
            {'target': 'demand-recovery-reserve', 'text': T('«حجز» يحوّل الطلب لحجز للعميل ويفتحه — حسب صلاحية إنشاء الحجوزات.',
                                              '"Reserve" turns the request into a reservation and opens it — depends on reservation-create permission.'),
             'more': RC_MORE_RESERVE},
            {'target': 'demand-recovery-recover', 'text': T('لو العميل اشترى: «استرداد» وأكّد الإيراد المُسترَد عشان يتسجل.',
                                              'If the customer bought: "Recover" and confirm the recovered revenue so it is recorded.'),
             'more': RC_MORE_RECOVER},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
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
        'tour': [
            {'target': 'demand-mobile-list-filters', 'text': T('فلتر الحالة.',
                                              'Status filter.'),
             'more': MB_MORE_FILTERS},
            {'target': 'demand-mobile-list-list', 'text': T('الطلبات.',
                                              'The requests.'),
             'more': T('طلبات الطلب الضائع اللي بتطابق الفلتر، والأحدث فوق.\n'
                           '• «تحميل المزيد» في الآخر لو فيه طلبات أكتر.',
                           'The lost-demand requests matching the filter, newest on top.\n'
                           '• "Load more" at the end when there are more requests.')},
            {'target': 'demand-mobile-list-card', 'text': T('اضغط على طلب لتفاصيله.',
                                              'Tap a request for its details.'),
             'more': MB_MORE_CARD},
            {'target': 'demand-mobile-list-new', 'text': T('زر «+» لتسجيل طلب ضائع جديد.',
                                              'The "+" button logs a new missed request.'),
             'more': MB_MORE_NEW},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
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
                                              'The customer\'s phone and name so we can tell them when the item arrives.'),
             'more': MB_MORE_CUSTOMER},
            {'target': 'demand-mobile-new-items', 'text': T('ابحث عن الصنف المطلوب، أو ضيفه يدوي لو مش موجود في الكتالوج.',
                                              'Search the requested item, or add it manually if it is not in the catalog.'),
             'more': MB_MORE_ITEMS},
            {'target': 'demand-mobile-new-lines', 'text': T('الأصناف المضافة للطلب.',
                                              'The items added to the request.'),
             'more': T('الأصناف اللي ضفتها، وجنب كل صنف كوده (أو «غير مكوَّد») وخانة الكمية.\n'
                           '• عدّل الكمية أو شيل الصنف قبل التسجيل.',
                           'The items you added, each with its code (or "uncoded") and a quantity box.\n'
                           '• Change the quantity or remove the item before recording.')},
            {'target': 'demand-mobile-new-details', 'text': T('الفرع والأولوية والمصدر وأي ملاحظات.',
                                              'Branch, priority, source and any notes.'),
             'more': MB_MORE_DETAILS},
            {'target': 'demand-mobile-new-submit', 'text': T('«✅ تسجيل الطلب» يحفظه ويبدأ متابعته.',
                                              '"✅ Log request" saves it and starts its follow-up.'),
             'more': MB_MORE_SUBMIT},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'demand.mobile_detail',
        'routes': ['/m/demand/:id'],
        'title': T('تفاصيل الطلب (موبايل)', 'Request details (mobile)'),
        'summary': T('عرض الطلب على الموبايل: العميل (اضغط للاتصال)، الأصناف، الحالة، وسجل الملاحظات مع إمكانية الكتابة.',
                     'The request on the phone: the customer (tap to call), items, status and the notes thread where you can write.'),
        'audience': T('العاملون في الفرع.', 'Branch staff.'),
        'steps': [T('اتصل بالعميل من الزر، ثم اكتب نتيجة التواصل في الملاحظات.', 'Call the customer from the button, then write the outcome in the notes.')],
        'tour': [
            {'target': 'demand-mobile-detail-header', 'text': T('رقم الطلب وحالته.',
                                              'The request number and status.'),
             'more': MD_MORE_HEADER},
            {'target': 'demand-mobile-detail-call', 'text': T('اتصل بالعميل مباشرة.',
                                              'Call the customer directly.'),
             'more': MD_MORE_CALL},
            {'target': 'demand-mobile-detail-info', 'text': T('العميل والفرع والأولوية والمصدر.',
                                              'Customer, branch, priority and source.'),
             'more': T('العميل والفرع والأولوية والمصدر، والقيمة المتوقعة والملاحظات لو موجودة.\n'
                           '• للعرض — التعديل من شاشة الكمبيوتر.',
                           'Customer, branch, priority and source, plus the expected value and notes when present.\n'
                           '• View only — editing is on the desktop screen.')},
            {'target': 'demand-mobile-detail-items', 'text': T('الأصناف المطلوبة.',
                                              'The requested items.'),
             'more': T('الأصناف المطلوبة بكمياتها.\n'
                           '• قولها للعميل وانت بتأكد معاه الطلب.',
                           'The requested items with their quantities.\n'
                           '• Read them to the customer while confirming the request.')},
            {'target': 'demand-mobile-detail-back', 'text': T('الرجوع للقائمة.',
                                              'Back to the list.'),
             'more': T('بيرجّعك لقائمة الطلبات على الموبايل.\n'
                           '• الملاحظة اللي كتبتها بتفضل محفوظة على الطلب.',
                           'Takes you back to the requests list on the phone.\n'
                           '• Any note you wrote stays saved on the request.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
