from . import T

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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
    },
]
