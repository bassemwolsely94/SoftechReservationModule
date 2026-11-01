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
    'brief': T('أي تغيير سعر أو خصم بيمر بطلب واعتماد قبل ما يتنفّذ في SOFTECH.',
               'Any price or discount change goes through a request and approval before it runs in SOFTECH.'),
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
    'journeys': [
        {'key': 'change', 'shell': 'desktop',
         'title': T('رحلة تعديل السعر: من الطلب إلى SOFTECH', 'Price change: from request to SOFTECH'),
         'summary': T('اطلب التعديل، راجع السجل، اعتمد ونفّذ في SOFTECH، ثم تأكد من وصوله للفروع.',
                      'Request the change, check the history, approve and run it in SOFTECH, then confirm it reached the branches.'),
         'steps': [
            {'screen': 'pricing.approvals', 'target': 'pricing-approvals-new', 'perm': 'approvals',
             'label': T('+ طلب تعديل جديد', '+ New change request'),
             'text': T('ابدأ من هنا لأي تعديل سعر أو خصم.', 'Start here for any price or discount change.')},
            {'screen': 'pricing.approvals', 'target': 'pricing-approvals-create-item', 'perm': 'approvals',
             'label': T('الصنف *', 'Item *'),
             'text': T('اختر الصنف واكتب القيمة الجديدة والسبب.', 'Pick the item and enter the new value and the reason.'),
             'open_hint': T('اضغط «+ طلب تعديل جديد».', 'Press "+ New change request".')},
            {'screen': 'pricing.approvals', 'target': 'pricing-approvals-create-send', 'perm': 'approvals',
             'label': T('إرسال الطلب', 'Send request'),
             'text': T('الطلب يُحفظ «في الانتظار». لا تغيير في SOFTECH بعد.', 'The request is saved as "Pending". No SOFTECH change yet.'),
             'warn': T('راجع الصنف والحقل قبل الإرسال.', 'Check the item and the field before sending.'),
             'open_hint': T('أسفل نموذج الطلب.', 'At the bottom of the request form.')},
            {'screen': 'pricing.approvals', 'target': 'pricing-approvals-history', 'perm': 'approvals',
             'label': T('🕘 السجل', '🕘 History'),
             'text': T('المدير يراجع تاريخ الصنف قبل القرار.', 'The manager checks the item history before deciding.')},
            {'screen': 'pricing.approvals', 'target': 'pricing-approvals-approve', 'perm': 'approvals',
             'label': T('اعتماد', 'Approve'),
             'text': T('يفتح نافذة المراجعة.', 'Opens the review window.'),
             'warn': T('يحتاج حساباً مربوطاً بمستخدم SOFTECH.', 'Needs an account linked to a SOFTECH user.'),
             'open_hint': T('للمدير فقط، على طلب «في الانتظار».', 'Admins only, on a "Pending" request.')},
            {'screen': 'pricing.approvals', 'target': 'pricing-approvals-review-confirm', 'perm': 'approvals',
             'label': T('اعتماد وتنفيذ في Softech', 'Approve and run in Softech'),
             'text': T('يُحدَّث الصنف في SOFTECH الرئيسي باسمك وتسحبه الفروع.', 'The item is updated in SOFTECH HQ under your name and branches pull it.'),
             'warn': T('يغيّر سعر البيع في كل الفروع فوراً.', 'Changes the selling price in every branch at once.'),
             'open_hint': T('داخل نافذة المراجعة.', 'Inside the review window.')},
            {'screen': 'pricing.approvals', 'target': 'pricing-approvals-replication-badge', 'perm': 'approvals',
             'label': T('شارة النسخ للفروع', 'Branch replication badge'),
             'text': T('تبيّن هل وصل التعديل لكل فرع. فرع متأخر؟ المدير يعيد المزامنة من الشارة.',
                       'Shows whether the change reached each branch. A branch behind? The manager resyncs from the badge.'),
             'open_hint': T('تظهر تحت حالة أي طلب «منفذ».', 'Shown under the status of any "Executed" request.')},
         ]},
        {'key': 'alignment', 'shell': 'desktop', 'roles': ['admin'],
         'title': T('مطابقة الخصومات: من التنبيه إلى الفروع', 'Discount alignment: from flag to branches'),
         'summary': T('اعرض الأصناف غير المتوافقة، طبّق التصنيف المقترح على SOFTECH، ثم دقّق وصوله للفروع.',
                      'Show incompatible items, apply the suggested class to SOFTECH, then audit that it reached the branches.'),
         'steps': [
            {'screen': 'pricing.alignment', 'target': 'pricing-alignment-only', 'perm': 'approvals',
             'label': T('غير المتوافقة فقط', 'Incompatible only'),
             'text': T('ابدأ بالأصناف التي يخالف خصمها تسميتها.', 'Start with items whose discount does not match their label.')},
            {'screen': 'pricing.alignment', 'target': 'pricing-alignment-flag', 'perm': 'approvals',
             'label': T('نوع التنبيه', 'Flag type'),
             'text': T('اختر نوعاً واحداً لتصحيحه.', 'Pick one kind to fix.')},
            {'screen': 'pricing.alignment', 'target': 'pricing-alignment-row', 'perm': 'approvals',
             'label': T('صف الصنف', 'Item row'),
             'text': T('راجع الهدف والتنبيه، وحدّد الأصناف المطلوب تصحيحها.', 'Check the target and flag, and tick the items to fix.')},
            {'screen': 'pricing.alignment', 'target': 'pricing-alignment-apply-suggested-softech', 'perm': 'approvals',
             'label': T('✨ تطبيق المقترح لكل صنف', '✨ Apply each suggestion'),
             'text': T('يكتب لكل صنف التصنيف المناسب لفئته.', 'Writes the right class for each item family.'),
             'warn': T('يكتب في SOFTECH الرئيسي باسمك وينتشر للفروع خلال نحو 30 دقيقة.',
                       'Writes to SOFTECH HQ under your name and spreads to branches in about 30 minutes.'),
             'open_hint': T('حدّد صنفاً واحداً على الأقل.', 'Select at least one item.')},
            {'screen': 'pricing.approvals', 'target': 'pricing-approvals-replication-scan', 'perm': 'approvals',
             'label': T('تشغيل الفحص الآن', 'Run scan now'),
             'text': T('بعد نصف ساعة تقريباً: افحص هل وصلت التعديلات لكل الفروع. قراءة فقط.',
                       'After about half an hour: check that the changes reached every branch. Read only.'),
             'open_hint': T('افتح تبويب «تدقيق النسخ المتماثل».', 'Open the "Replication audit" tab.')},
         ]},
    ],
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
        'audience': T('الصيدلي والمشتريات والمشرف ومدير الجودة يطلبون؛ المدير يعتمد.',
                      'Pharmacists, purchasing, supervisors and the quality manager request; the manager approves.'),
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
            {'target': 'pricing-approvals-new', 'label': T('+ طلب تعديل جديد', '+ New change request'),
             'text': T('يفتح نموذج طلب تعديل سعر العبوة أو أي خصم لصنف واحد.',
                       'Opens the form to request a change to the pack price or any discount of one item.'),
             'when': T('أي موظف يطلب؛ التنفيذ لا يحصل إلا بعد اعتماد المدير.', 'Any employee can request; nothing happens until a manager approves.'),
             'more': T(
                 'استخدمه لما سعر صنف أو خصمه في SOFTECH محتاج يتغيّر (تسعيرة جديدة، خصم مورد اتغيّر…).\n• بيفتح نافذة «طلب تعديل سعر / خصم»: تختار الصنف، وتكتب القيمة الجديدة لحقل واحد على الأقل (سعر العبوة بدون ضريبة، خصم الصيدلية، الإضافي، الخاص، POS)، والسبب إجباري.\n• سعر الوحدة والسعر شامل الضريبة بيتحسبوا لوحدهم من سعر العبوة.\n• «إرسال الطلب» بيسجّله «في الانتظار» — مفيش أي تغيير في SOFTECH لحد ما المدير يعتمده.',
                 'Use it when an item\'s price or discount in SOFTECH needs to change (new price list, a supplier discount changed…).\n• It opens the "Price / discount change request" window: pick the item and enter the new value for at least one field (pack price before VAT, pharmacy, additional, special or POS discount); the reason is required.\n• The unit price and the price with VAT are calculated automatically from the pack price.\n• "Send request" saves it as "Pending" — nothing changes in SOFTECH until a manager approves it.')},
            {'target': 'pricing-approvals-create-item', 'label': T('الصنف *', 'Item *'),
             'text': T('ابحث بالاسم أو الكود أو الباركود. تظهر القيم الحالية من SOFTECH بجانب كل حقل.',
                       'Search by name, code or barcode. The current SOFTECH values show beside each field.'),
             'when': T('اكتب القيمة الجديدة لحقل واحد على الأقل. سعر الوحدة والسعر شامل الضريبة يُحسبان تلقائياً.',
                       'Enter a new value for at least one field. Unit price and price with VAT are computed automatically.'),
             'open_hint': T('اضغط «+ طلب تعديل جديد».', 'Press "+ New change request".')},
            {'target': 'pricing-approvals-create-send', 'label': T('إرسال الطلب', 'Send request'),
             'text': T('يحفظ الطلب «في الانتظار» مع السبب. لا شيء يتغير في SOFTECH الآن.',
                       'Saves the request as "Pending" with the reason. Nothing changes in SOFTECH now.'),
             'when': T('يظهر الطلب في القائمة وفي «متابعة المعلّقة» للمدير.', 'The request shows in the list and in "Pending follow-up" for the manager.'),
             'warn': T('تأكد من الصنف والحقل قبل الإرسال — المدير يعتمد ما كتبته بالضبط.',
                       'Check the item and the field before sending — the manager approves exactly what you entered.'),
             'open_hint': T('أسفل نموذج الطلب الجديد.', 'At the bottom of the new-request form.')},
            {'target': 'pricing-approvals-import', 'label': T('📄 استيراد ملف', '📄 Import file'),
             'text': T('ينشئ طلبات كثيرة من ملف CSV أو XLSX: عمود itemcode وحقل واحد على الأقل، والسبب اختياري.',
                       'Creates many requests from a CSV or XLSX file: an itemcode column, at least one field, and an optional reason.'),
             'when': T('كل صف يصبح طلباً «في الانتظار»، والصفوف الخاطئة تُتخطى مع السبب.', 'Each row becomes a "Pending" request; bad rows are skipped with the reason.')},
            {'target': 'pricing-approvals-row', 'label': T('صف الطلب', 'Request row'),
             'text': T('القيم القديمة والجديدة، من طلب، ومن نفّذ باسم مستخدم SOFTECH، والحالة. صفِّ بالحالة من الأزرار أعلى الجدول.',
                       'Old and new values, who asked, who executed under which SOFTECH user, and the status. Filter by status with the buttons above.'),
             'when': T('طلب «فشل» يعرض سبب الخطأ تحته.', 'A "Failed" request shows the error under it.')},
            {'target': 'pricing-approvals-history', 'label': T('🕘 السجل', '🕘 History'),
             'text': T('سجل تغييرات السعر والخصم لهذا الصنف عبر الزمن.', 'The price and discount change history of this item over time.'),
             'when': T('قبل الاعتماد: تأكد أن الصنف لم يتغير مؤخراً لنفس السبب.', 'Before approving: check the item was not changed recently for the same reason.'),
             'more': T(
                 '«🕘 السجل» جنب كود الصنف بيفتح تغييرات السعر اللي حصلت للصنف ده قبل كده.\n• مفيد قبل ما تعتمد أو تطلب تعديل: تعرف السعر اتغيّر إمتى وكام مرة.\n• للعرض بس — مش بيغيّر حاجة.',
                 '"🕘 Log" next to the item code opens the price changes this item had before.\n• Useful before approving or requesting a change: see when and how often the price changed.\n• View only — it changes nothing.')},
            {'target': 'pricing-approvals-approve', 'label': T('اعتماد', 'Approve'),
             'text': T('يفتح نافذة المراجعة: ملخص التعديل ومستخدم SOFTECH الذي سيُنفَّذ باسمه. الفتح لا يكتب شيئاً.',
                       'Opens the review window: the change summary and the SOFTECH user it will run under. Opening writes nothing.'),
             'warn': T('الاعتماد يحتاج ربط حسابك بمستخدم SOFTECH؛ التعديل يظهر هناك كأنك أجريته بنفسك.',
                       'Approving needs your account linked to a SOFTECH user; the change shows there as if you made it.'),
             'open_hint': T('للمدير فقط، على طلب «في الانتظار» أو «فشل».', 'Admins only, on a "Pending" or "Failed" request.')},
            {'target': 'pricing-approvals-reject', 'label': T('رفض', 'Reject'),
             'text': T('يفتح نافذة الرفض مع ملاحظة تصل لمن طلب.', 'Opens the reject window with a note sent to the requester.'),
             'warn': T('الرفض نهائي لهذا الطلب؛ لإعادة المحاولة يلزم طلب جديد.', 'Rejecting is final for this request; trying again needs a new request.'),
             'open_hint': T('للمدير فقط، على طلب «في الانتظار».', 'Admins only, on a "Pending" request.')},
            {'target': 'pricing-approvals-review-confirm', 'label': T('اعتماد وتنفيذ في Softech', 'Approve and run in Softech'),
             'text': T('عند الاعتماد: يُحدَّث سجل الصنف في الرئيسي بـ SOFTECH باسمك، وتسحبه الفروع تلقائياً. في الرفض: «رفض الطلب».',
                       'On approve: the item record at HQ in SOFTECH is updated under your name and branches pull it automatically. On reject: "Reject request".'),
             'when': T('بعدها الحالة «منفذ في Softech» أو «فشل» مع السبب. شارة النسخ تبين وصوله للفروع.',
                       'Then the status is "Executed in Softech" or "Failed" with the reason. The replication badge shows if branches got it.'),
             'warn': T('يغيّر سعر البيع في كل الفروع فوراً. لو الكتابة معطلة من الإعدادات يُرفض ويبقى الطلب معلقاً.',
                       'Changes the selling price in every branch at once. If writes are switched off it is refused and stays pending.'),
             'open_hint': T('داخل نافذة المراجعة بعد «اعتماد» أو «رفض».', 'Inside the review window after "Approve" or "Reject".')},
            {'target': 'pricing-approvals-rollback', 'label': T('↩ تراجع', '↩ Rollback'),
             'text': T('ينشئ طلباً جديداً «في الانتظار» يعيد القيم السابقة. لا يغيّر SOFTECH حتى يُعتمد.',
                       'Creates a new "Pending" request back to the previous values. SOFTECH does not change until it is approved.'),
             'warn': T('الطلب الجديد يمر بنفس الاعتماد وينفَّذ على كل الفروع.', 'The new request goes through the same approval and runs on every branch.'),
             'open_hint': T('للمدير فقط، على طلب «منفذ».', 'Admins only, on an "Executed" request.')},
            {'target': 'pricing-approvals-sla-review', 'label': T('مراجعة', 'Review'),
             'text': T('الطلبات المتأخرة الأقدم أولاً. «مراجعة» يفتح نافذة الاعتماد مباشرة.',
                       'Late requests, oldest first. "Review" opens the approval window directly.'),
             'when': T('افتحه كل صباح — لا تترك طلباً معلقاً طويلاً.', 'Open it every morning — do not leave a request waiting long.'),
             'open_hint': T('افتح تبويب «متابعة المعلّقة (SLA)».', 'Open the "Pending follow-up (SLA)" tab.')},
            {'target': 'pricing-approvals-replication-repair', 'label': T('إعادة مزامنة كل الفجوات', 'Resync all gaps'),
             'text': T('يعيد ختم وقت التعديل في الرئيسي لكل صنف متأخر، فتسحبه الفروع في الدورة التالية. لا يغيّر القيم أو صاحب التعديل.',
                       'Re-stamps the HQ update time of every stale item, so branches pull it on the next cycle. Values and author do not change.'),
             'when': T('بعد «تشغيل الفحص الآن» واختيار فحص فيه فجوات.', 'After "Run scan now" and picking a scan that has gaps.'),
             'warn': T('يكتب في SOFTECH الرئيسي لكل أصناف الفحص؛ تأكد أن القيم في الرئيسي هي الصحيحة.',
                       'Writes to SOFTECH HQ for every item in the scan; make sure the HQ values are the right ones.'),
             'open_hint': T('للمدير: تبويب «تدقيق النسخ المتماثل»، ثم اختر فحصاً.', 'Admins: the "Replication audit" tab, then pick a scan.')},
            {'target': 'pricing-approvals-tabs',  # from the GitHub-side tour
             'label': T('الطلبات / متابعة المعلّقة (SLA)', 'Requests / Pending follow-up (SLA)'),
             'when': T('«متابعة المعلّقة» لمعرفة الطلبات اللي اتأخرت.', 'Use "Pending follow-up" to see requests that are running late.'),
             'text': T('«الطلبات» و«متابعة المعلّقة (SLA)»؛ التدقيق ولوحات المعلومات تظهر للمدير فقط.',
                       '"Requests" and "Pending follow-up (SLA)"; the audit and insights tabs show to admins only.'),
             'more': T(
                 '• «الطلبات»: كل الطلبات وحالتها — ده الشغل اليومي.\n• «متابعة المعلّقة (SLA)»: الطلبات اللي اعتمادها اتأخر، عشان محدش يفضل مستني.\n• «تدقيق النسخ المتماثل» و«لوحات المعلومات» بيظهروا للمدير بس: هل التعديل المنفّذ وصل لكل الفروع، وإحصاءات الطلبات وزمن الاعتماد.',
                 '• "Requests": every request and its status — the daily work.\n• "Pending follow-up (SLA)": requests whose approval is late, so nobody is left waiting.\n• "Replication audit" and "Insights" show to admins only: whether an executed change reached every branch, and request statistics and approval time.')},
            {'target': 'pricing-approvals-status',  # from the GitHub-side tour
             'label': T('في الانتظار / منفذ / مرفوض / فشل', 'Pending / Executed / Rejected / Failed'),
             'when': T('اختار «فشل» لمعرفة الطلبات اللي محتاجة إعادة محاولة.', 'Pick "Failed" to find requests that need another try.'),
             'text': T('في «الطلبات»: صفِّ بالحالة: في الانتظار، منفذ، مرفوض، فشل.',
                       'In "Requests": filter by status: pending, executed, rejected, failed.'),
             'more': T(
                 'اختار الحالة اللي عايز تشوفها:\n• «في الانتظار»: لسه محدش راجعه.\n• «منفذ»: اتطبّق في SOFTECH.\n• «مرفوض» بملاحظة المدير، و«فشل»: اتعتمد بس التنفيذ في SOFTECH ما كملش — اقرأ الخطأ.',
                 'Choose which status to show:\n• "Pending": nobody has reviewed it yet.\n• "Executed": applied in SOFTECH.\n• "Rejected" with the manager\'s note, and "Failed": approved but execution in SOFTECH did not complete — read the error.')},
            {'target': 'pricing-approvals-table',  # from the GitHub-side tour
             'label': T('جدول الطلبات', 'Requests table'),
             'when': T('لمراجعة كل طلب قبل الاعتماد أو الرفض.', 'To check each request before approving or rejecting it.'),
             'text': T('الطلبات مع الصنف والتعديلات المطلوبة ومن طلبها وحالتها.',
                       'Requests with the item, requested changes, requester and status.'),
             'more': T(
                 'كل صف طلب: الصنف وكوده، القيم القديمة والجديدة لكل حقل اتطلب تعديله، مين طلبه، التاريخ والحالة.\n• لو مش مدير هتلاقي طلباتك هنا — المدير بيراجعها ويعتمدها.\n• بعد التنفيذ بيظهر كمان القيم اللي اتطبقت فعلاً.',
                 'Each row is a request: the item and its code, old and new values for each field asked to change, who asked, the date and the status.\n• If you are not a manager, your own requests show here — the manager reviews and approves them.\n• After execution the values actually applied are shown too.')},
            {'target': 'pricing-approvals-review',  # from the GitHub-side tour
             'label': T('اعتماد / رفض', 'Approve / Reject'),
             'when': T('للطلبات «في الانتظار» أو «فشل» بعد مراجعة التعديل.', 'For "Pending" or "Failed" requests, after checking the change.'),
             'text': T('للمدير فقط: «اعتماد» و«رفض» و«↩ تراجع» حسب الحالة؛ تحتاج صلاحية وكل إجراء مُسجَّل.',
                       'Admins only: "Approve", "Reject" and "↩ Rollback" by status; they need permission and every action is recorded.'),
             'more': T(
                 '• «اعتماد» بيفتح نافذة فيها مستخدم SOFTECH المرتبط بحسابك، و«اعتماد وتنفيذ في Softech» بيطبّق التعديل فوراً في SOFTECH باسمك وينتشر لكل الفروع. لو حسابك مش مربوط بمستخدم SOFTECH الزر بيتقفل.\n• «رفض» بملاحظة اختيارية، والطلب «الفاشل» ممكن تعتمده تاني.\n• «↩ تراجع» على طلب منفّذ مش بيرجّع حاجة على طول: بيعمل طلب جديد «في الانتظار» بالقيم السابقة محتاج اعتماد.\n• للمدير بس، والسيرفر بيتحقق من الصلاحية، وكل إجراء متسجّل.',
                 '• "Approve" opens a window showing the SOFTECH user linked to your account, and "Approve and execute in Softech" applies the change in SOFTECH at once under your name and spreads it to every branch. If your account has no linked SOFTECH user the button is disabled.\n• "Reject" with an optional note; a "Failed" request can be approved again.\n• "↩ Rollback" on an executed request does not revert anything by itself: it creates a new "Pending" request with the previous values that needs approval.\n• Admins only; the server checks permission and every action is recorded.')},
        ],
        'updated': '2026-10-27',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
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
            {'target': 'pricing-alignment-stats', 'label': T('مفحوص · غير متوافق', 'Checked · incompatible'),
             'text': T('عدد الأصناف المفحوصة وعدد غير المتوافقة مع نسبة المنشأ أو التعاقد.',
                       'How many items were checked and how many do not match the origin or contract rate.'),
             'when': T('الهدف أن يقل «غير متوافق» مع كل تصحيح.', 'The goal is for "incompatible" to drop with each fix.'),
             'more': T(
                 '• «مفحوص»: عدد الأصناف اللي اتفحصت بالفلاتر الحالية.\n• «غير متوافق»: أصناف الخصم الأساسي الفعلي بتاعها مش مطابق لنسبة المنشأ أو تصنيف خصم التعاقد أو السياسة الرئيسية للمورد.\nالرقم ده هو حجم الشغل اللي قدامك.',
                 '• "Checked": how many items were checked with the current filters.\n• "Incompatible": items whose actual basic discount does not match the origin rate, the contract-discount class or the supplier\'s master policy.\nThis number is the size of the work in front of you.')},
            {'target': 'pricing-alignment-search', 'label': T('🔍 ابحث باسم الصنف...', '🔍 Search item name...'),
             'text': T('يحصر الجدول في صنف أو مجموعة أصناف بالاسم.', 'Narrows the table to an item or a group of items by name.')},
            {'target': 'pricing-alignment-flag', 'label': T('نوع التنبيه', 'Flag type'),
             'text': T('اعرض نوعاً واحداً: الخصم يخالف المنشأ، أو التعاقد، أو المنشأ يخالف التعاقد، أو السياسة الرئيسية.',
                       'Show one kind: discount vs origin, vs contract, origin vs contract, or vs the master policy.'),
             'when': T('صحّح نوعاً واحداً في كل مرة — أسهل في المراجعة.', 'Fix one kind at a time — easier to review.')},
            {'target': 'pricing-alignment-only', 'label': T('غير المتوافقة فقط', 'Incompatible only'),
             'text': T('مُفعّل افتراضياً: يخفي الأصناف السليمة. «تضمين الموقوفة» يضيف الأصناف الموقوفة.',
                       'On by default: hides the clean items. "Include stopped" adds stopped items.')},
            {'target': 'pricing-alignment-row', 'label': T('صف الصنف', 'Item row'),
             'text': T('الخصم الأساسي الفعلي هو المرجع، بجانبه نسبة المنشأ ونسبة التعاقد والهدف والتنبيهات.',
                       'The actual basic discount is the reference, beside the origin rate, contract rate, target and flags.'),
             'when': T('حدّد الأصناف بمربع الاختيار لتظهر أدوات التصحيح.', 'Tick items to show the fix tools.')},
            {'target': 'pricing-alignment-select-all', 'label': T('تحديد الكل', 'Select all'),
             'text': T('يحدد كل الصفوف المعروضة حالياً.', 'Selects every row shown now.'),
             'warn': T('يحدد كل المعروض حتى خارج الشاشة — صفِّ أولاً قبل أي تطبيق جماعي.',
                       'Selects everything shown, even off screen — filter first before any bulk apply.')},
            {'target': 'pricing-alignment-apply-suggested-softech', 'label': T('✨ تطبيق المقترح لكل صنف', '✨ Apply each suggestion'),
             'text': T('يكتب لكل صنف محدد المنشأ أو تصنيف التعاقد المقترح لفئته ونسبته.',
                       'Writes to each selected item the origin or contract class suggested for its family and rate.'),
             'warn': T('يكتب على أصناف الرئيسي في SOFTECH باسمك وتنتشر للفروع خلال نحو 30 دقيقة. للمدير فقط.',
                       'Writes to the HQ items in SOFTECH under your name and spreads to branches in about 30 minutes. Admins only.'),
             'open_hint': T('حدّد صنفاً واحداً على الأقل.', 'Select at least one item.')},
            {'target': 'pricing-alignment-uniform', 'label': T('أو تعيين مُوحَّد', 'Or uniform assignment'),
             'text': T('اختر منشأً جديداً و/أو تصنيف خصم جديداً لكل المحدد. علامة ✓ = نسبته تطابق الهدف.',
                       'Pick a new origin and/or discount class for all selected. A ✓ mark = its rate matches the target.'),
             'when': T('لو ظهر «خصومات مختلفة» فالمحدد لا يصلح لتعيين واحد.', 'If "different discounts" shows, the selection does not fit one assignment.'),
             'open_hint': T('حدّد صنفاً واحداً على الأقل.', 'Select at least one item.')},
            {'target': 'pricing-alignment-apply-softech', 'label': T('✔ تطبيق على SOFTECH', '✔ Apply to SOFTECH'),
             'text': T('يكتب التعيين المُوحَّد على كل الأصناف المحددة، مع قراءة تأكيد لكل صنف ونتيجة نجح/فشل.',
                       'Writes the uniform assignment to every selected item, with a read-back per item and a success/fail count.'),
             'warn': T('يغيّر تسميات الأصناف في SOFTECH الرئيسي وكل الفروع. حتى 1000 صنف في المرة، للمدير فقط.',
                       'Changes item labels in SOFTECH HQ and every branch. Up to 1000 items at a time, admins only.'),
             'open_hint': T('حدّد أصنافاً واختر المنشأ أو التصنيف الجديد.', 'Select items and pick the new origin or class.')},
            {'target': 'pricing-alignment-new-tier', 'label': T('➕ تصنيف جديد', '➕ New class'),
             'text': T('ينشئ منشأً أو تصنيف خصم تعاقدات جديداً لو لا يوجد تصنيف بالنسبة المطلوبة.',
                       'Creates a new origin or contract-discount class when none has the needed rate.'),
             'more': T(
                 'لو مفيش منشأ أو تصنيف خصم بالنسبة المطلوبة أصلاً في SOFTECH، استخدم «➕ تصنيف جديد».\n• بيعرض معاينة للصف المقترح (الكود والاسم) الأول من غير كتابة.\n• «✔ إنشاء فى SOFTECH» بعد التأكيد بينسخ صف موجود كقالب ويغيّر الكود والاسم بس. للمدير بس.',
                 'If no origin or discount class with the needed rate exists in SOFTECH yet, use "➕ New class".\n• It first shows a preview of the proposed row (code and name) without writing.\n• "✔ Create in SOFTECH", after a confirmation, copies an existing row as a template changing only the code and name. Admins only.')},
            {'target': 'pricing-alignment-tier-preview', 'label': T('👁 معاينة', '👁 Preview'),
             'text': T('قراءة فقط: يعرض الصف المقترح والكود الجديد، وينبّه لو الكود مستخدم.',
                       'Read only: shows the proposed row and the new code, and warns if the code is taken.'),
             'open_hint': T('داخل نافذة «➕ تصنيف جديد».', 'Inside the "➕ New class" window.')},
            {'target': 'pricing-alignment-tier-create-softech', 'label': T('✔ إنشاء فى SOFTECH', '✔ Create in SOFTECH'),
             'text': T('يضيف صفاً جديداً في جدول التصنيفات بـ SOFTECH، منسوخاً من صف قالب مع تغيير الكود والاسم فقط.',
                       'Adds a new row to the SOFTECH class table, copied from a template row with only code and name changed.'),
             'warn': T('صف دائم في SOFTECH ولا يُحذف من هنا — راجع الاسم والكود في المعاينة. للمدير فقط.',
                       'A permanent SOFTECH row that cannot be removed from here — check name and code in the preview. Admins only.'),
             'open_hint': T('بعد «👁 معاينة» داخل نافذة التصنيف الجديد.', 'After "👁 Preview" inside the new-class window.')},
            {'target': 'pricing-alignment-filters',  # from the GitHub-side tour
             'label': T('🔍 ابحث باسم الصنف...', '🔍 Search by item name...'),
             'when': T('لتضييق القائمة على صنف أو نوع تنبيه قبل التعديل.', 'To narrow the list to an item or alert type before editing.'),
             'text': T('ابحث باسم الصنف، اختر نوع التنبيه، و«غير المتوافقة فقط» أو «تضمين الموقوفة».',
                       'Search by item name, pick a flag type, and "incompatible only" or "include inactive".'),
             'more': T(
                 '• ابحث باسم الصنف، واختار نوع التنبيه (الخصم ≠ نسبة المنشأ، ≠ نسبة التعاقد، المنشأ ≠ التعاقد، ≠ السياسة الرئيسية).\n• «غير المتوافقة فقط» يخفي الأصناف السليمة، و«تضمين الموقوفة» يضيف الأصناف الموقوفة.\nالفلاتر بتغيّر العرض بس — مفيش كتابة.',
                 '• Search by item name and pick a flag type (discount ≠ origin rate, ≠ contract rate, origin ≠ contract, ≠ master policy).\n• "Incompatible only" hides the correct items, and "Include inactive" adds stopped items.\nFilters only change the view — nothing is written.')},
            {'target': 'pricing-alignment-table',  # from the GitHub-side tour
             'label': T('جدول الأصناف', 'Items table'),
             'when': T('حدد الأصناف اللي عايز تعدّل خصمها.', 'Tick the items whose discount you want to change.'),
             'text': T('الأصناف مع المنشأ والخصم الأساسي والنسب المقارنة؛ حدد الأصناف بمربع الاختيار.',
                       'Items with origin, basic discount and compared rates; select items with the checkbox.'),
             'more': T(
                 'كل صف: الصنف والمورد، المنشأ الحالي، الخصم الأساسي، نسبة المنشأ ونسبة التعاقد، والهدف المقترح.\n• الخصم الفعلي هو المرجع: المطلوب إن التسميات (المنشأ وتصنيف الخصم) تتعدّل عشان تطابقه — مش العكس.\n• علّم مربع الاختيار للأصناف اللي عايز تصلّحها، فيظهر شريط الإجراءات.',
                 'Each row: item and supplier, current origin, basic discount, origin rate and contract rate, and the suggested target.\n• The actual discount is the reference: the labels (origin and discount class) are changed to match it — not the other way round.\n• Tick the items you want to fix and the action bar appears.')},
            {'target': 'pricing-alignment-bulk',  # from the GitHub-side tour
             'label': T('✎ N صنف محدد', '✎ N items selected'),
             'when': T('بعد تحديد الأصناف ومراجعة المقترح لكل صنف.', 'After selecting items and checking each item\'s suggestion.'),
             'text': T('يظهر بعد تحديد أصناف: «تطبيق المقترح لكل صنف» أو تعيين موحّد؛ يكتب على SOFTECH ويحتاج صلاحية ويُسجَّل.',
                       'Appears after selecting items: "Apply each item\'s suggestion" or a uniform assignment; writes to SOFTECH, needs permission and is recorded.'),
             'more': T(
                 '• «✨ تطبيق المقترح لكل صنف» بيدّي كل صنف المنشأ/تصنيف الخصم المناسب لفئته ونسبته.\n• أو «تعيين موحّد»: اختار منشأ و/أو تصنيف خصم جديد ثم «✔ تطبيق على SOFTECH» لكل الأصناف المحددة.\n• الاتنين بيكتبوا فعلاً في SOFTECH على الرئيسي باسم مستخدم SOFTECH بتاعك وبعد تأكيد، والتغيير بينتشر للفروع (الرسالة بتقول حوالي 30 دقيقة). للمدير بس.',
                 '• "✨ Apply each item\'s suggestion" gives each item the origin/discount class that fits its category and rate.\n• Or a uniform assignment: pick a new origin and/or discount class, then "✔ Apply to SOFTECH" for all selected items.\n• Both really write to SOFTECH on HQ under your SOFTECH user after a confirmation, and the change spreads to branches (the message says about 30 minutes). Admins only.')},
        ],
        'updated': '2026-10-26',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
    },
]
