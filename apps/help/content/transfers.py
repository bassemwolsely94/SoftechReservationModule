from . import T

MODULE = {
    'key': 'transfers', 'group': 'operations', 'icon': '🔀',
    'title': T('التحويلات بين الفروع', 'Inter-branch transfers'),
    'summary': T(
        'التحويل له نصفان مرتبطان:\n'
        '1) «طلبات التحويل»: فرع يحتاج صنفاً يطلبه من فرع آخر (الفرع المصدر)، والفرع المصدر يعتمد أو يرفض أو يطلب تعديلاً، '
        'ثم يُصدر التحويل في SOFTECH. هذا النظام لا يحرّك المخزون بنفسه — الحركة الفعلية تتم في SOFTECH.\n'
        '2) «قيد النقل»: مستندات التحويل الصادرة فعلاً من SOFTECH (مستند 125) التي لم تُستلم بعد في الفرع المستلم (مستند 25)، '
        'مع أولوية حسب عمر الشحنة، ومطابقة الصرف بالاستلام، وأوراق التجميع والترصيص.',
        'A transfer has two linked halves:\n'
        '1) "Transfer requests": a branch that needs an item requests it from another branch (the supplying branch), which approves, '
        'rejects or asks for changes, then the transfer is issued in SOFTECH. This system never moves stock itself — the actual '
        'movement happens in SOFTECH.\n'
        '2) "In transit": transfer documents actually issued in SOFTECH (doc 125) that the receiving branch has not received yet (doc 25), '
        'with priority by shipment age, issue-vs-receipt reconciliation, and picking and stocking sheets.'),
    'workflows': [{
        'title': T('مراحل طلب التحويل', 'Transfer request stages'),
        'model': 'transfers.TransferRequest', 'field': 'status',
        'intro': T('الفرع الطالب يُنشئ ويقدّم ويلغي؛ الفرع المصدر (أو المشرف) يعتمد ويرفض ويطلب التعديل ويُرسل للـ ERP.',
                   'The requesting branch creates, submits and cancels; the supplying branch (or a supervisor) approves, rejects, asks for changes and sends to ERP.'),
        'states': [
            {'key': 'draft', 'label': T('مسودة', 'Draft'),
             'desc': T('الطلب محفوظ ولم يُقدَّم. يمكن تعديل الأصناف. «تقديم الطلب» يرسله للفرع المصدر.',
                       'Saved but not submitted. Items can still change. "Submit" sends it to the supplying branch.'),
             'next': ['pending', 'cancelled']},
            {'key': 'pending', 'label': T('بانتظار الموافقة', 'Waiting for approval'),
             'desc': T('عند الفرع المصدر ليراجعه: يعتمد (كلياً أو كمية جزئية)، أو يرفض بسبب، أو يطلب تعديلاً.',
                       'With the supplying branch to review: approve (fully or a partial quantity), reject with a reason, or ask for changes.'),
             'next': ['approved', 'rejected', 'needs_revision', 'cancelled']},
            {'key': 'needs_revision', 'label': T('يحتاج تعديل', 'Needs revision'),
             'desc': T('الفرع المصدر طلب تعديلاً (اقرأ ملاحظاته). عدّل ثم قدّم مرة أخرى.',
                       'The supplying branch asked for a change (read its notes). Edit and submit again.'),
             'next': ['pending', 'cancelled']},
            {'key': 'approved', 'label': T('معتمد', 'Approved'),
             'desc': T('تمت الموافقة بالكميات المعتمدة. المطلوب الآن: إصدار التحويل في SOFTECH ثم «إرسال للـ ERP» بمرجع المستند.',
                       'Approved with the approved quantities. Now: issue the transfer in SOFTECH, then "Send to ERP" with the document reference.'),
             'next': ['sent_to_erp']},
            {'key': 'sent_to_erp', 'label': T('تم الإرسال للـ ERP', 'Sent to ERP'),
             'desc': T('أُصدر في SOFTECH وهو في الطريق. النظام يتحقق تلقائياً كل 30 دقيقة من مستند ERP. الفرع الطالب «يؤكد الاستلام» بالكميات المستلمة فعلاً.',
                       'Issued in SOFTECH and on its way. The system checks the ERP document every 30 minutes. The requesting branch "confirms receipt" with the quantities actually received.'),
             'next': ['completed']},
            {'key': 'completed', 'label': T('مكتمل', 'Completed'), 'desc': T('تم الاستلام وأُغلق الطلب.', 'Received and closed.')},
            {'key': 'rejected', 'label': T('مرفوض', 'Rejected'), 'desc': T('رفضه الفرع المصدر مع ذكر السبب. مرحلة نهائية.', 'Rejected by the supplying branch with a reason. Final.')},
            {'key': 'cancelled', 'label': T('ملغي', 'Cancelled'), 'desc': T('ألغاه الفرع الطالب قبل الاعتماد. مرحلة نهائية.', 'Cancelled by the requesting branch before approval. Final.')},
        ],
    }],
}

_NEW_STEPS = [
    T('اختر «الفرع الطالب» (فرعك عادةً) و«الفرع المصدر» الذي لديه المخزون — لا يمكن أن يكونا نفس الفرع.',
      'Choose the "requesting branch" (usually yours) and the "supplying branch" that has the stock — they cannot be the same.'),
    T('ابحث عن الأصناف بالاسم أو الكود أو الباركود وأدخل الكمية لكل صنف؛ يظهر بجانب كل صنف مخزونه في الفرع المصدر.',
      'Search items by name, code or barcode and enter a quantity for each; each item shows its stock at the supplying branch.'),
    T('اكتب سبب الطلب في الملاحظات (مثلاً: لحجز عميل، نقص متكرر).', 'Write the reason in the notes (e.g. for a customer reservation, repeated shortage).'),
    T('«حفظ كمسودة» لو ستراجعه لاحقاً، أو «حفظ وتقديم» لإرساله للفرع المصدر مباشرةً.',
      '"Save as draft" to review later, or "Save and submit" to send it to the supplying branch now.'),
]

SCREENS = [
    {
        'key': 'transfers.list',
        'routes': ['/transfers'],
        'title': T('طلبات التحويل', 'Transfer requests'),
        'summary': T(
            'كل طلبات التحويل الداخلية بين الفروع حسب الحالة، كقائمة أو كانبان، مع البحث والفلترة بالفرع الطالب والمصدر. '
            'الشريط العلوي ينقلك بين «طلبات التحويل» و«قيد النقل».',
            'All internal transfer requests between branches by status, as a list or Kanban, with search and filters by requesting and supplying branch. '
            'The switcher at the top moves between "Transfer requests" and "In transit".'),
        'audience': T('الصيادلة والمشتريات والمشرفون ومركز الاتصال.', 'Pharmacists, purchasing, supervisors and the call center.'),
        'steps': [
            T('شرائح الحالة أعلى القائمة (مسودة، بانتظار الموافقة، معتمد…) تعرض ما في كل مرحلة. «مسوداتي» تعرض ما لم تقدّمه بعد.',
              'The status chips (draft, waiting, approved…) show what is in each stage. "My drafts" shows what you have not submitted yet.'),
            T('لو فرعك هو المصدر: راجع «بانتظار الموافقة» أولاً — هذه طلبات فروع أخرى تنتظرك.',
              'If your branch is the supplier: check "Waiting for approval" first — other branches are waiting on you.'),
            T('«طلب تحويل جديد» لإنشاء طلب.', '"New transfer request" to create one.'),
            T('اضغط رقم الطلب لفتح تفاصيله واتخاذ الإجراء.', 'Click a request number to open it and act.'),
        ],
        'tips': [
            T('الطلب لا يؤثر على المخزون حتى يُصدر فعلاً في SOFTECH.', 'A request does not affect stock until it is actually issued in SOFTECH.'),
        ],
        'related': ['transfers.new', 'transfers.detail', 'transfers.transits'],
        'updated': '2026-10-10',
    },
    {
        'key': 'transfers.new',
        'routes': ['/transfers/new', '/m/transfers/new'],
        'title': T('طلب تحويل جديد', 'New transfer request'),
        'summary': T('نموذج طلب أصناف من فرع آخر، بعدة أصناف في طلب واحد.', 'The form to request items from another branch, several items per request.'),
        'audience': T('الفرع الذي يحتاج الصنف، أو المشرف.', 'The branch that needs the item, or a supervisor.'),
        'steps': _NEW_STEPS,
        'tips': [
            T('لو صنف «لا يوجد مخزون في أي فرع» فالتحويل لن يفيد — سجّله كطلب ضائع أو نقص للمشتريات.',
              'If an item shows "no stock in any branch", a transfer will not help — record it as lost demand or a shortage for purchasing.'),
        ],
        'related': ['transfers.list', 'demand.list', 'shortage.list'],
        'updated': '2026-10-10',
    },
    {
        'key': 'transfers.detail',
        'routes': ['/transfers/:id', '/m/transfers/:id'],
        'title': T('تفاصيل طلب التحويل', 'Transfer request details'),
        'summary': T(
            'طلب تحويل واحد: الفرعان، الأصناف بالكميات المطلوبة والمعتمدة والمستلمة ومخزونها في الفروع، مسار الطلب (إنشاء ← تقديم ← مراجعة ← إرسال ERP ← اكتمال)، '
            'المحادثة، ومطابقة مستند SOFTECH. الأزرار المعروضة هي فقط المسموح لك بها حسب فرعك والحالة.',
            'One transfer request: both branches, items with requested, approved and received quantities and their stock, the request path '
            '(created → submitted → reviewed → sent to ERP → completed), the chat, and the SOFTECH document match. Only the buttons you are allowed to use '
            'for your branch and the current status are shown.'),
        'audience': T('الفرع الطالب والفرع المصدر والمشرف.', 'The requesting branch, the supplying branch and supervisors.'),
        'steps': [
            T('الفرع الطالب: أضف/عدّل الأصناف في المسودة ثم «تقديم الطلب».', 'Requesting branch: add/edit items in the draft, then "Submit".'),
            T('الفرع المصدر: «اعتماد» وأدخل الكمية المعتمدة لكل صنف (يمكن جزئياً)، أو «رفض» بسبب، أو «طلب تعديل» بملاحظات.',
              'Supplying branch: "Approve" with the approved quantity per item (partial allowed), or "Reject" with a reason, or "Request changes" with notes.'),
            T('بعد الاعتماد: أصدر التحويل في SOFTECH ثم «إرسال للـ ERP» واكتب مرجع المستند. يمكنك «تسجيل الإرسال» باسم مندوب التوصيل.',
              'After approval: issue the transfer in SOFTECH, then "Send to ERP" with the document reference. You can "Record dispatch" with the courier name.'),
            T('الفرع الطالب عند وصول الشحنة: «تأكيد الاستلام» بالكمية المستلمة فعلاً لكل صنف — هذا يغلق الطلب.',
              'Requesting branch when the shipment arrives: "Confirm receipt" with the quantity actually received per item — this closes the request.'),
            T('قسم «مطابقة مستند ERP» يعرض هل المستند في SOFTECH مطابق أو جزئي أو غير موجود، ويُفحص تلقائياً كل 30 دقيقة.',
              'The "ERP document match" section shows whether the SOFTECH document is matched, partial or missing; it is checked every 30 minutes.'),
        ],
        'tips': [
            T('لو الطلب مرتبط بشحنة «قيد النقل» يظهر رابط «قيد النقل ←» لفتحها مباشرة.', 'If the request is linked to an in-transit shipment, a "In transit ←" link opens it.'),
            T('لا تعتمد كمية أكبر من المتاح فعلاً في فرعك.', 'Do not approve more than you actually have.'),
        ],
        'related': ['transfers.list', 'transfers.transits'],
        'updated': '2026-10-10',
    },
    {
        'key': 'transfers.transits',
        'routes': ['/transits'],
        'title': T('التحويلات قيد النقل', 'Transfers in transit'),
        'summary': T(
            'الشحنات التي صدرت فعلاً من SOFTECH بين الفروع (مستند 125) ولم تُستلم بعد. كل شحنة لها لون أولوية حسب عمرها '
            '(طازج ← مراقبة ← متابعة ← طارئ ← حرج)، ومهلة إلغاء، وتنبيه للأصناف قريبة الانتهاء (FEFO). '
            'منها تُصدَّر «ورقة التجميع» للمخزن المصدر و«ورقة الترصيص» للفرع المستلم.',
            'Shipments actually issued in SOFTECH between branches (doc 125) that have not been received yet. Each has a priority colour by age '
            '(fresh → watch → follow-up → urgent → critical), a cancellation deadline, and a warning for near-expiry items (FEFO). '
            'From here you export the "picking sheet" for the supplying store and the "stocking sheet" for the receiving branch.'),
        'audience': T('الفروع (الإرسال والاستلام)، المخزن، المشتريات، المشرفون.', 'Branches (sending and receiving), the warehouse, purchasing, supervisors.'),
        'tabs': [
            {'key': 'items', 'title': T('الأصناف', 'Items'),
             'body': T('أصناف الشحنة المختارة: الكمية، تاريخ الصلاحية، التشغيلات، والتكلفة. الأصناف قريبة الانتهاء تظهر بتحذير FEFO — استلمها وصرّفها أولاً.',
                       'Items of the selected shipment: quantity, expiry date, batches and cost. Near-expiry items carry a FEFO warning — receive and sell them first.')},
            {'key': 'recon', 'title': T('مطابقة 125↔25', 'Reconcile 125↔25'),
             'body': T('يظهر بعد استلام الشحنة في SOFTECH: يقارن الصرف (125) بالاستلام (25) — أصناف ناقصة، فروق كميات، أصناف زائدة، وفرق القيمة. أي تباين يحتاج تحقيقاً.',
                       'Shows once the shipment is received in SOFTECH: compares the issue (125) with the receipt (25) — missing items, quantity differences, extra items and the value gap. Any mismatch needs investigation.')},
            {'key': 'notes', 'title': T('الملاحظات', 'Notes'),
             'body': T('ملاحظات داخلية على الشحنة (تأخير، نقص في الكرتونة، مكالمة مع الفرع).', 'Internal notes on the shipment (delay, missing carton, call with the branch).')},
            {'key': 'timeline', 'title': T('السجل', 'Timeline'),
             'body': T('سجل كل ما حدث على الشحنة: الإصدار، الملاحظات، الاستلام، الإغلاق.', 'Everything that happened: issue, notes, receipt, closing.')},
        ],
        'steps': [
            T('شريط المؤشرات أعلى الصفحة: عدد الشحنات وقيمتها، الحرج/الطارئ، ما تنتهي مهلة إلغائه خلال 24 ساعة، وما استُلم وصدر اليوم.',
              'The KPI strip at the top: number and value of shipments, critical/urgent, those whose cancellation window ends within 24 hours, and today\'s receipts and issues.'),
            T('رتّب وصفِّ بالأولوية والحالة وفرع المصدر والمستلم والعمر. ابدأ بالحرج.', 'Sort and filter by priority, status, source and receiving branch and age. Start with critical.'),
            T('اضغط شحنة لفتح لوحة تفاصيلها (التبويبات أعلاه).', 'Click a shipment to open its detail panel (tabs above).'),
            T('«ورقة التجميع» (Excel): بمسار مخزن المصدر لتجهيز الشحنة. حدد عدة شحنات لورقة تجميع موحدة.',
              '"Picking sheet" (Excel): ordered by the supplying store\'s walk path to prepare the shipment. Select several shipments for one combined sheet.'),
            T('«ورقة الترصيص» (Excel): بترتيب أرفف الفرع المستلم لتسريع وضع الأصناف على الأرفف.',
              '"Stocking sheet" (Excel): in the receiving branch\'s shelf order to put items away faster.'),
            T('«تسجيل الاستلام» عند الاستلام، أو «إغلاق قسري» بسبب مكتوب (10 أحرف على الأقل) للحالات الاستثنائية.',
              '"Record receipt" on arrival, or "Force close" with a written reason (at least 10 characters) for exceptional cases.'),
        ],
        'tips': [
            T('الشحنة يجب أن تُستلم في SOFTECH قبل انتهاء مهلة الإلغاء، وإلا تظهر «انتهت مهلة الإلغاء — يجب الاستلام».',
              'The shipment must be received in SOFTECH before its cancellation window ends, otherwise "cancellation window over — must receive" appears.'),
            T('«بطاقة مساءلة الفروع» أسفل الصفحة تعرض أداء كل فرع في الاستلام والمخزون العائم.', 'The "branch accountability card" at the bottom shows each branch\'s receiving performance and floating stock.'),
        ],
        'related': ['transfers.list', 'transfers.pick_zones'],
        'updated': '2026-10-10',
    },
    {
        'key': 'transfers.pick_zones',
        'routes': ['/pick-zones'],
        'title': T('مناطق التجميع والترصيص', 'Picking & stocking zones'),
        'summary': T(
            'إعداد كيف تُرتَّب الأصناف في «ورقة التجميع» (مسار السير في المخزن المورد) و«ورقة الترصيص» (ترتيب أرفف الفرع المستلم، ويُستخدم أيضاً في أوراق الجرد). '
            'كل صنف يُصنَّف في منطقة بهذا الترتيب: تخصيص يدوي للصنف ← ثلاجة ← حد الغوالي ← القواعد بالترتيب (أول تطابق يفوز) ← غير مصنف.',
            'Configure how items are ordered on the "picking sheet" (the walk path in the supplying store) and the "stocking sheet" (the receiving branch\'s shelf order, also used on stock-count sheets). '
            'Each item gets a zone in this order: manual item assignment → fridge → high-value threshold → rules in order (first match wins) → uncategorized.'),
        'audience': T('الجميع يرى؛ التعديل للمدير والمشتريات.', 'Everyone can view; admin and purchasing edit.'),
        'tabs': [
            {'key': 'zones', 'title': T('المناطق', 'Zones'),
             'body': T('المناطق (مثل: ممر 2، رف B) بترتيب المسار — الأصغر يُجمَّع أولاً. لكل منطقة موقع وتفعيل وأدوار خاصة: «غوالي» (الأصناف فوق حد السعر)، «ثلاجة»، «غير مصنف».',
                       'Zones (e.g. aisle 2, shelf B) in path order — the lowest is picked first. Each has a location, an on/off switch and special roles: "high-value" (items above the price threshold), "fridge", "uncategorized".')},
            {'key': 'rules', 'title': T('القواعد', 'Rules'),
             'body': T('قواعد تضع الصنف في منطقة: بكلمات في اسم الصنف أو بأعمدة الكتالوج (شكل الصنف، نوع الدواء، العائلة، الشركة، المنشأ، الوحدة). '
                       'الترتيب مهم (أول قاعدة تتطابق تفوز) — استخدم الأسهم لإعادة الترتيب، و«اختبار التصنيف الحي» لتجربة اسم صنف.',
                       'Rules that put an item in a zone: by words in the item name or by catalog columns (form, drug type, family, company, origin, unit). '
                       'Order matters (the first matching rule wins) — use the arrows to reorder, and the "live classification test" to try an item name.')},
            {'key': 'uncategorized', 'title': T('❓ غير مصنف', '❓ Uncategorized'),
             'body': T('أصناف الكتالوج التي لم تطابق أي قاعدة — خصّص لها منطقة أو أضف قاعدة تغطيها.', 'Catalog items that matched no rule — assign them a zone or add a rule that covers them.')},
            {'key': 'overrides', 'title': T('التخصيصات', 'Item assignments'),
             'body': T('تخصيص صنف معيّن لمنطقة يدوياً (يتغلب على كل القواعد) مع وسوم وموقع.', 'Manually assign a specific item to a zone (beats all rules), with tags and a location.')},
        ],
        'steps': [
            T('اختر الغرض: «تجميع» (مخزن المصدر) أو «ترصيص» (أرفف الفرع).', 'Choose the purpose: "Picking" (supplying store) or "Stocking" (branch shelves).'),
            T('اختر الموقع: الإعداد الافتراضي أو مخزن/فرع بعينه. «نسخ الإعداد الافتراضي» يبدأ إعداد فرع من الافتراضي.',
              'Choose the location: the default setup or a specific store/branch. "Copy default setup" starts a branch setup from the default.'),
            T('حدد «حد سعر الغوالي» (ج.م): الأصناف بسعر أعلى أو يساويه تذهب لمنطقة الغوالي.', 'Set the "high-value price threshold" (EGP): items priced at or above it go to the high-value zone.'),
        ],
        'related': ['transfers.transits', 'stockcount.sessions'],
        'updated': '2026-10-10',
    },
    {
        'key': 'transfers.mobile_list',
        'routes': ['/m/transfers'],
        'title': T('طلبات التحويل (موبايل)', 'Transfer requests (mobile)'),
        'summary': T('طلبات التحويل التي فرعك طالب فيها أو مصدر لها، على الموبايل، مع شرائح الحالة.',
                     'Transfer requests where your branch is requesting or supplying, on the phone, with status chips.'),
        'audience': T('العاملون في الفرع.', 'Branch staff.'),
        'steps': [
            T('اضغط طلباً لعرضه والقيام بالإجراء المتاح لك (تقديم، اعتماد، رفض، استلام…).', 'Tap a request to view it and take the action available to you (submit, approve, reject, receive…).'),
            T('زر «+» لطلب تحويل جديد.', 'The "+" button creates a new transfer request.'),
        ],
        'related': ['transfers.new', 'transfers.detail'],
        'updated': '2026-10-10',
    },
]
