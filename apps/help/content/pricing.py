from . import T

# Longer explanations ("more") shared by the screen tours and the module tour.
PR_MORE_NEW = T(
    'استخدمه لما سعر صنف أو خصمه في SOFTECH محتاج يتغيّر (تسعيرة جديدة، خصم مورد اتغيّر…).\n'
    '• بيفتح نافذة «طلب تعديل سعر / خصم»: تختار الصنف، وتكتب القيمة الجديدة لحقل واحد على الأقل (سعر العبوة بدون ضريبة، خصم الصيدلية، الإضافي، الخاص، POS)، والسبب إجباري.\n'
    '• سعر الوحدة والسعر شامل الضريبة بيتحسبوا لوحدهم من سعر العبوة.\n'
    '• «إرسال الطلب» بيسجّله «في الانتظار» — مفيش أي تغيير في SOFTECH لحد ما المدير يعتمده.',
    'Use it when an item\'s price or discount in SOFTECH needs to change (new price list, a supplier discount changed…).\n'
    '• It opens the "Price / discount change request" window: pick the item and enter the new value for at least one field (pack price before VAT, pharmacy, additional, special or POS discount); the reason is required.\n'
    '• The unit price and the price with VAT are calculated automatically from the pack price.\n'
    '• "Send request" saves it as "Pending" — nothing changes in SOFTECH until a manager approves it.')
PR_MORE_TABS = T(
    '• «الطلبات»: كل الطلبات وحالتها — ده الشغل اليومي.\n'
    '• «متابعة المعلّقة (SLA)»: الطلبات اللي اعتمادها اتأخر، عشان محدش يفضل مستني.\n'
    '• «تدقيق النسخ المتماثل» و«لوحات المعلومات» بيظهروا للمدير بس: هل التعديل المنفّذ وصل لكل الفروع، وإحصاءات الطلبات وزمن الاعتماد.',
    '• "Requests": every request and its status — the daily work.\n'
    '• "Pending follow-up (SLA)": requests whose approval is late, so nobody is left waiting.\n'
    '• "Replication audit" and "Insights" show to admins only: whether an executed change reached every branch, and request statistics and approval time.')
PR_MORE_STATUS = T(
    'اختار الحالة اللي عايز تشوفها:\n'
    '• «في الانتظار»: لسه محدش راجعه.\n'
    '• «منفذ»: اتطبّق في SOFTECH.\n'
    '• «مرفوض» بملاحظة المدير، و«فشل»: اتعتمد بس التنفيذ في SOFTECH ما كملش — اقرأ الخطأ.',
    'Choose which status to show:\n'
    '• "Pending": nobody has reviewed it yet.\n'
    '• "Executed": applied in SOFTECH.\n'
    '• "Rejected" with the manager\'s note, and "Failed": approved but execution in SOFTECH did not complete — read the error.')
PR_MORE_TABLE = T(
    'كل صف طلب: الصنف وكوده، القيم القديمة والجديدة لكل حقل اتطلب تعديله، مين طلبه، التاريخ والحالة.\n'
    '• لو مش مدير هتلاقي طلباتك هنا — المدير بيراجعها ويعتمدها.\n'
    '• بعد التنفيذ بيظهر كمان القيم اللي اتطبقت فعلاً.',
    'Each row is a request: the item and its code, old and new values for each field asked to change, who asked, the date and the status.\n'
    '• If you are not a manager, your own requests show here — the manager reviews and approves them.\n'
    '• After execution the values actually applied are shown too.')
PR_MORE_HISTORY = T(
    '«🕘 السجل» جنب كود الصنف بيفتح تغييرات السعر اللي حصلت للصنف ده قبل كده.\n'
    '• مفيد قبل ما تعتمد أو تطلب تعديل: تعرف السعر اتغيّر إمتى وكام مرة.\n'
    '• للعرض بس — مش بيغيّر حاجة.',
    '"🕘 Log" next to the item code opens the price changes this item had before.\n'
    '• Useful before approving or requesting a change: see when and how often the price changed.\n'
    '• View only — it changes nothing.')
PR_MORE_REVIEW = T(
    '• «اعتماد» بيفتح نافذة فيها مستخدم SOFTECH المرتبط بحسابك، و«اعتماد وتنفيذ في Softech» بيطبّق التعديل فوراً في SOFTECH باسمك وينتشر لكل الفروع. لو حسابك مش مربوط بمستخدم SOFTECH الزر بيتقفل.\n'
    '• «رفض» بملاحظة اختيارية، والطلب «الفاشل» ممكن تعتمده تاني.\n'
    '• «↩ تراجع» على طلب منفّذ مش بيرجّع حاجة على طول: بيعمل طلب جديد «في الانتظار» بالقيم السابقة محتاج اعتماد.\n'
    '• للمدير بس، والسيرفر بيتحقق من الصلاحية، وكل إجراء متسجّل.',
    '• "Approve" opens a window showing the SOFTECH user linked to your account, and "Approve and execute in Softech" applies the change in SOFTECH at once under your name and spreads it to every branch. If your account has no linked SOFTECH user the button is disabled.\n'
    '• "Reject" with an optional note; a "Failed" request can be approved again.\n'
    '• "↩ Rollback" on an executed request does not revert anything by itself: it creates a new "Pending" request with the previous values that needs approval.\n'
    '• Admins only; the server checks permission and every action is recorded.')
AL_MORE_STATS = T(
    '• «مفحوص»: عدد الأصناف اللي اتفحصت بالفلاتر الحالية.\n'
    '• «غير متوافق»: أصناف الخصم الأساسي الفعلي بتاعها مش مطابق لنسبة المنشأ أو تصنيف خصم التعاقد أو السياسة الرئيسية للمورد.\n'
    'الرقم ده هو حجم الشغل اللي قدامك.',
    '• "Checked": how many items were checked with the current filters.\n'
    '• "Incompatible": items whose actual basic discount does not match the origin rate, the contract-discount class or the supplier\'s master policy.\n'
    'This number is the size of the work in front of you.')
AL_MORE_FILTERS = T(
    '• ابحث باسم الصنف، واختار نوع التنبيه (الخصم ≠ نسبة المنشأ، ≠ نسبة التعاقد، المنشأ ≠ التعاقد، ≠ السياسة الرئيسية).\n'
    '• «غير المتوافقة فقط» يخفي الأصناف السليمة، و«تضمين الموقوفة» يضيف الأصناف الموقوفة.\n'
    'الفلاتر بتغيّر العرض بس — مفيش كتابة.',
    '• Search by item name and pick a flag type (discount ≠ origin rate, ≠ contract rate, origin ≠ contract, ≠ master policy).\n'
    '• "Incompatible only" hides the correct items, and "Include inactive" adds stopped items.\n'
    'Filters only change the view — nothing is written.')
AL_MORE_TABLE = T(
    'كل صف: الصنف والمورد، المنشأ الحالي، الخصم الأساسي، نسبة المنشأ ونسبة التعاقد، والهدف المقترح.\n'
    '• الخصم الفعلي هو المرجع: المطلوب إن التسميات (المنشأ وتصنيف الخصم) تتعدّل عشان تطابقه — مش العكس.\n'
    '• علّم مربع الاختيار للأصناف اللي عايز تصلّحها، فيظهر شريط الإجراءات.',
    'Each row: item and supplier, current origin, basic discount, origin rate and contract rate, and the suggested target.\n'
    '• The actual discount is the reference: the labels (origin and discount class) are changed to match it — not the other way round.\n'
    '• Tick the items you want to fix and the action bar appears.')
AL_MORE_BULK = T(
    '• «✨ تطبيق المقترح لكل صنف» بيدّي كل صنف المنشأ/تصنيف الخصم المناسب لفئته ونسبته.\n'
    '• أو «تعيين موحّد»: اختار منشأ و/أو تصنيف خصم جديد ثم «✔ تطبيق على SOFTECH» لكل الأصناف المحددة.\n'
    '• الاتنين بيكتبوا فعلاً في SOFTECH على الرئيسي باسم مستخدم SOFTECH بتاعك وبعد تأكيد، والتغيير بينتشر للفروع (الرسالة بتقول حوالي 30 دقيقة). للمدير بس.',
    '• "✨ Apply each item\'s suggestion" gives each item the origin/discount class that fits its category and rate.\n'
    '• Or a uniform assignment: pick a new origin and/or discount class, then "✔ Apply to SOFTECH" for all selected items.\n'
    '• Both really write to SOFTECH on HQ under your SOFTECH user after a confirmation, and the change spreads to branches (the message says about 30 minutes). Admins only.')
AL_MORE_TIER = T(
    'لو مفيش منشأ أو تصنيف خصم بالنسبة المطلوبة أصلاً في SOFTECH، استخدم «➕ تصنيف جديد».\n'
    '• بيعرض معاينة للصف المقترح (الكود والاسم) الأول من غير كتابة.\n'
    '• «✔ إنشاء فى SOFTECH» بعد التأكيد بينسخ صف موجود كقالب ويغيّر الكود والاسم بس. للمدير بس.',
    'If no origin or discount class with the needed rate exists in SOFTECH yet, use "➕ New class".\n'
    '• It first shows a preview of the proposed row (code and name) without writing.\n'
    '• "✔ Create in SOFTECH", after a confirmation, copies an existing row as a template changing only the code and name. Admins only.')

MODULE = {
    'key': 'pricing', 'group': 'purchasing', 'icon': '🏷️',
    'title': T('الأسعار والخصومات', 'Prices & discounts'),
    'summary': T(
        'أي تعديل في سعر صنف أو خصوماته يمر بطلب واعتماد: الموظف يطلب، والمدير يعتمد فيُنفَّذ مباشرة في SOFTECH باسم مستخدم SOFTECH الخاص بالمعتمد وينتشر لكل الفروع تلقائياً. '
        'سعر العبوة (بدون ضريبة) هو الأساس؛ سعر الوحدة والسعر شامل الضريبة يُحسبان تلقائياً. الخصومات (الصيدلية، الإضافي، الخاص، POS) مستقلة. '
        'وفيه «مطابقة الخصومات»: الخصم الفعلي هو المرجع وتُصحَّح تسميات المنشأ وتصنيف خصم التعاقدات لتطابقه.',
        'Any change to an item\'s price or discounts goes through a request and approval: an employee requests, a manager approves, and it is executed directly in SOFTECH under the approver\'s own SOFTECH user and spreads to every branch automatically. '
        'The pack price (before VAT) is the master; unit price and price with VAT are derived automatically. The discounts (pharmacy, additional, special, POS) are independent. '
        'It also has "Discount alignment": the actual discount is the reference and the origin and contract-discount labels are corrected to match it.'),
    'workflows': [{
        'title': T('مراحل طلب تعديل السعر', 'Price change request stages'),
        'model': 'discount_approvals.ItemPriceChangeRequest', 'field': 'status',
        'states': [
            {'key': 'pending', 'label': T('في الانتظار', 'Pending'), 'desc': T('ينتظر مراجعة المدير.', 'Waiting for a manager.'), 'next': ['approved', 'rejected']},
            {'key': 'approved', 'label': T('معتمد', 'Approved'), 'desc': T('اعتُمد ويُنفَّذ في SOFTECH.', 'Approved and being executed in SOFTECH.'), 'next': ['executed', 'failed']},
            {'key': 'executed', 'label': T('منفذ في Softech', 'Executed in SOFTECH'), 'desc': T('طُبّق في SOFTECH وانتشر للفروع. يمكن إنشاء «طلب تراجع» للقيم السابقة.', 'Applied in SOFTECH and replicated to branches. A "rollback request" to the previous values can be created.')},
            {'key': 'rejected', 'label': T('مرفوض', 'Rejected'), 'desc': T('رُفض مع ملاحظة.', 'Rejected with a note.')},
            {'key': 'failed', 'label': T('فشل في التنفيذ', 'Execution failed'), 'desc': T('لم يُطبَّق في SOFTECH — راجع الخطأ.', 'Not applied in SOFTECH — check the error.')},
        ],
    }],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول الأسعار والخصومات', 'A tour of the Prices & discounts module'),
            'summary': T('إزاي تعديل سعر أو خصم صنف بيمشي من طلب لاعتماد لتنفيذ في SOFTECH، وإزاي «مطابقة الخصومات» بتصلّح تسميات المنشأ وتصنيف الخصم.',
                         'How an item price or discount change goes from request to approval to execution in SOFTECH, and how "Discount alignment" fixes origin and discount-class labels.'),
            'roles': ['admin', 'purchasing', 'pharmacist'],
            'steps': [
                {'target': 'nav-pricing-approvals', 'nav': '/pricing-approvals',
                 'text': T('«المشتريات» ← «موافقات الأسعار».', '"Purchasing" → "Price approvals".'),
                 'more': T('أي تغيير في سعر صنف أو خصوماته بيبدأ من هنا — مفيش تعديل مباشر.\n'
                           '• الموظف يطلب، والمدير يعتمد، والتنفيذ بيحصل في SOFTECH باسم مستخدم SOFTECH بتاع المعتمد وينتشر لكل الفروع.\n'
                           '• كل طلب واعتماد ورفض متسجّل بمين وإمتى وإيه القيم قبل وبعد.',
                           'Every change to an item\'s price or discounts starts here — there is no direct edit.\n'
                           '• An employee requests, a manager approves, and execution happens in SOFTECH under the approver\'s SOFTECH user and spreads to every branch.\n'
                           '• Every request, approval and rejection is recorded with who, when and the before/after values.')},
                {'target': 'pricing-approvals-new', 'route': '/pricing-approvals',
                 'text': T('«طلب تعديل جديد» — بداية أي تغيير سعر أو خصم.', '"New change request" — where any price or discount change starts.'),
                 'more': PR_MORE_NEW},
                {'target': 'pricing-approvals-tabs', 'route': '/pricing-approvals',
                 'text': T('التبويبات: الطلبات، والمعلّقة، وتبويبات المدير.', 'The tabs: requests, pending follow-up, and the admin tabs.'),
                 'more': PR_MORE_TABS},
                {'target': 'pricing-approvals-status', 'route': '/pricing-approvals',
                 'text': T('فلتر الحالة: في الانتظار، منفذ، مرفوض، فشل.', 'Status filter: pending, executed, rejected, failed.'),
                 'more': PR_MORE_STATUS},
                {'target': 'pricing-approvals-table', 'route': '/pricing-approvals',
                 'text': T('جدول الطلبات: القيم القديمة والجديدة ومين طلب.', 'The requests table: old and new values and who asked.'),
                 'more': PR_MORE_TABLE},
                {'target': 'pricing-approvals-history', 'route': '/pricing-approvals',
                 'text': T('«🕘 السجل» لتاريخ أسعار الصنف.', '"🕘 Log" for the item\'s price history.'),
                 'more': PR_MORE_HISTORY},
                {'target': 'pricing-approvals-review', 'route': '/pricing-approvals',
                 'text': T('المدير: «اعتماد» و«رفض» و«↩ تراجع».', 'Manager: "Approve", "Reject" and "↩ Rollback".'),
                 'more': PR_MORE_REVIEW},
                {'target': 'nav-discount-alignment', 'nav': '/discount-alignment',
                 'text': T('الشاشة التانية: «المشتريات» ← «مطابقة الخصومات».', 'The second screen: "Purchasing" → "Discount alignment".'),
                 'more': T('هنا مش بنغيّر الخصم نفسه — بنصلّح تسميات الصنف (المنشأ محلي/مستورد وتصنيف خصم التعاقد) عشان تطابق الخصم الفعلي.\n'
                           '• لو الخصم نفسه محتاج يتغيّر، ارجع لـ «موافقات الأسعار» واعمل طلب.',
                           'Here we do not change the discount itself — we fix the item\'s labels (local/imported origin and contract-discount class) to match the actual discount.\n'
                           '• If the discount itself must change, go back to "Price approvals" and make a request.')},
                {'target': 'pricing-alignment-stats', 'route': '/discount-alignment',
                 'text': T('كام صنف اتفحص وكام غير متوافق.', 'How many items were checked and how many are incompatible.'),
                 'more': AL_MORE_STATS},
                {'target': 'pricing-alignment-filters', 'route': '/discount-alignment',
                 'text': T('ضيّق القائمة بنوع التنبيه و«غير المتوافقة فقط».', 'Narrow the list by flag type and "Incompatible only".'),
                 'more': AL_MORE_FILTERS},
                {'target': 'pricing-alignment-table', 'route': '/discount-alignment',
                 'text': T('علّم الأصناف اللي هتصلّحها.', 'Tick the items you will fix.'),
                 'more': AL_MORE_TABLE},
                {'target': 'pricing-alignment-bulk', 'route': '/discount-alignment',
                 'text': T('شريط التصليح بيظهر بعد التحديد — بيكتب في SOFTECH.', 'The fix bar appears after selecting — it writes to SOFTECH.'),
                 'more': AL_MORE_BULK},
                {'target': 'pricing-alignment-new-tier', 'route': '/discount-alignment',
                 'text': T('«➕ تصنيف جديد» لو مفيش تصنيف بالنسبة المطلوبة.', '"➕ New class" when no class has the needed rate.'),
                 'more': AL_MORE_TIER},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'pricing.approvals',
        'routes': ['/pricing-approvals'],
        'title': T('موافقات الأسعار والخصومات', 'Price & discount approvals'),
        'summary': T('طلب تعديل سعر أو خصم لصنف، ومراجعة واعتماد الطلبات وتنفيذها في SOFTECH، ومتابعة المعلّق والتدقيق.',
                     'Request a price or discount change for an item, review and approve requests and execute them in SOFTECH, and follow pending items and the audit.'),
        'audience': T('أي موظف يطلب؛ المدير يعتمد.', 'Any employee requests; the manager approves.'),
        'tabs': [
            {'key': 'requests', 'title': T('الطلبات', 'Requests'), 'body': T('الطلبات حسب الحالة مع التعديلات المطلوبة ومن طلبها. «اعتماد» أو «رفض»، و«سجل تغييرات السعر» لكل صنف، و«تراجع» لطلب منفّذ.', 'Requests by status with the requested changes and who asked. "Approve" or "Reject", "Price change log" per item, and "Rollback" for an executed request.')},
            {'key': 'sla', 'title': T('متابعة المعلّقة (SLA)', 'Pending follow-up (SLA)'), 'body': T('الطلبات التي تأخر اعتمادها — لا تترك طلباً معلقاً طويلاً.', 'Requests whose approval is late — do not leave a request waiting long.')},
            {'key': 'replication', 'title': T('تدقيق النسخ المتماثل', 'Replication audit'), 'body': T('هل وصل التعديل المنفّذ من الرئيسي لكل الفروع في SOFTECH.', 'Whether an executed change reached every branch in SOFTECH from HQ.')},
            {'key': 'insights', 'title': T('لوحات المعلومات', 'Insights'), 'body': T('إحصاءات الطلبات وزمن الاعتماد والتعديلات.', 'Request statistics, approval time and changes.')},
        ],
        'steps': [
            T('«طلب تعديل جديد»: ابحث عن الصنف، أدخل القيمة الجديدة لحقل واحد على الأقل (سعر العبوة أو أي خصم)، واكتب السبب ← «إرسال الطلب». «استيراد ملف» لطلبات كثيرة.',
              '"New change request": find the item, enter a new value for at least one field (pack price or any discount) and the reason → "Send". "Import file" for many requests.'),
            {'text': T('للاعتماد يجب ربط حسابك بمستخدم SOFTECH (من إعدادات المستخدم)؛ التعديل يظهر في SOFTECH كأنك أجريته بنفسك.', 'To approve, your account must be linked to a SOFTECH user (in user settings); the change appears in SOFTECH as if you made it yourself.'),
             'roles': ['admin']},
        ],
        'tips': [T('لا تعدّل سعر الوحدة أو السعر شامل الضريبة — يُحسبان من سعر العبوة.', 'Never edit the unit price or the price with VAT — they are derived from the pack price.')],
        'related': ['pricing.alignment', 'pos.offers'],
        'tour': [
            {'target': 'pricing-approvals-new', 'text': T('«طلب تعديل جديد» لطلب تغيير سعر أو خصم صنف؛ الطلب يُراجع قبل التنفيذ ويُسجَّل.',
                                              '"New change request" asks to change an item\'s price or discount; it is reviewed before execution and recorded.'),
             'more': PR_MORE_NEW},
            {'target': 'pricing-approvals-tabs', 'text': T('«الطلبات» و«متابعة المعلّقة (SLA)»؛ التدقيق ولوحات المعلومات تظهر للمدير فقط.',
                                              '"Requests" and "Pending follow-up (SLA)"; the audit and insights tabs show to admins only.'),
             'more': PR_MORE_TABS},
            {'target': 'pricing-approvals-status', 'text': T('في «الطلبات»: صفِّ بالحالة: في الانتظار، منفذ، مرفوض، فشل.',
                                              'In "Requests": filter by status: pending, executed, rejected, failed.'),
             'more': PR_MORE_STATUS},
            {'target': 'pricing-approvals-table', 'text': T('الطلبات مع الصنف والتعديلات المطلوبة ومن طلبها وحالتها.',
                                              'Requests with the item, requested changes, requester and status.'),
             'more': PR_MORE_TABLE},
            {'target': 'pricing-approvals-history', 'text': T('«🕘 السجل» يعرض تغييرات السعر السابقة للصنف.',
                                              '"🕘 Log" shows the item\'s previous price changes.'),
             'more': PR_MORE_HISTORY},
            {'target': 'pricing-approvals-review', 'text': T('للمدير فقط: «اعتماد» و«رفض» و«↩ تراجع» حسب الحالة؛ تحتاج صلاحية وكل إجراء مُسجَّل.',
                                              'Admins only: "Approve", "Reject" and "↩ Rollback" by status; they need permission and every action is recorded.'),
             'more': PR_MORE_REVIEW},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'pricing.alignment',
        'routes': ['/discount-alignment'],
        'title': T('مطابقة الخصومات', 'Discount alignment'),
        'summary': T('يفحص كل صنف: هل الخصم الأساسي الفعلي يطابق نسبة المنشأ (محلي/مستورد) ونسبة تصنيف خصم التعاقدات والسياسة الرئيسية للمورد؟ الخصم الفعلي هو المرجع، والتسميات القديمة تُصحَّح لتطابقه وتُكتب على SOFTECH (الرئيسي ثم تنتشر للفروع).',
                     'Checks each item: does the actual basic discount match the origin rate (local/imported), the contract-discount classification rate and the supplier\'s master policy? The actual discount is the reference; old labels are corrected to match and written to SOFTECH (HQ, then replicated to branches).'),
        'audience': T('المشتريات والمدير.', 'Purchasing and admins.'),
        'steps': [
            T('فعّل «غير المتوافقة فقط» وصفِّ بنوع التنبيه (الخصم ≠ نسبة المنشأ، ≠ نسبة التعاقد، المنشأ ≠ التعاقد، ≠ السياسة الرئيسية).', 'Turn on "incompatible only" and filter by flag (discount ≠ origin rate, ≠ contract rate, origin ≠ contract, ≠ master policy).'),
            T('حدد الأصناف ثم «تطبيق المقترح لكل صنف» أو «تعيين موحّد» لمنشأ/تصنيف خصم جديد ← «تطبيق على SOFTECH».', 'Select items then "Apply each item\'s suggestion" or "Uniform assignment" of a new origin/discount class → "Apply to SOFTECH".'),
            T('لو لا يوجد تصنيف مطابق: «تصنيف جديد» ← معاينة الصف المقترح ← «إنشاء في SOFTECH» (يُنسخ صف قالب مع تغيير الكود والاسم فقط).', 'If no matching class exists: "New class" → preview the proposed row → "Create in SOFTECH" (a template row is copied, changing only code and name).'),
        ],
        'tips': [T('التغييرات تصل للفروع خلال دقائق بعد الكتابة على الرئيسي.', 'Changes reach branches within minutes after writing to HQ.')],
        'workflows': [],
        'related': ['pricing.approvals'],
        'tour': [
            {'target': 'pricing-alignment-stats', 'text': T('عدد الأصناف المفحوصة وغير المتوافقة.',
                                              'How many items were checked and how many are incompatible.'),
             'more': AL_MORE_STATS},
            {'target': 'pricing-alignment-filters', 'text': T('ابحث باسم الصنف، اختر نوع التنبيه، و«غير المتوافقة فقط» أو «تضمين الموقوفة».',
                                              'Search by item name, pick a flag type, and "incompatible only" or "include inactive".'),
             'more': AL_MORE_FILTERS},
            {'target': 'pricing-alignment-table', 'text': T('الأصناف مع المنشأ والخصم الأساسي والنسب المقارنة؛ حدد الأصناف بمربع الاختيار.',
                                              'Items with origin, basic discount and compared rates; select items with the checkbox.'),
             'more': AL_MORE_TABLE},
            {'target': 'pricing-alignment-bulk', 'text': T('يظهر بعد تحديد أصناف: «تطبيق المقترح لكل صنف» أو تعيين موحّد؛ يكتب على SOFTECH ويحتاج صلاحية ويُسجَّل.',
                                              'Appears after selecting items: "Apply each item\'s suggestion" or a uniform assignment; writes to SOFTECH, needs permission and is recorded.'),
             'more': AL_MORE_BULK},
            {'target': 'pricing-alignment-new-tier', 'text': T('«➕ تصنيف جديد» عند عدم وجود تصنيف مطابق؛ معاينة أولاً، ويحتاج صلاحية ويُسجَّل.',
                                              '"➕ New class" when no matching class exists; preview first, needs permission and is recorded.'),
             'more': AL_MORE_TIER},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
