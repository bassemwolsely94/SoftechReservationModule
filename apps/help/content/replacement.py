from . import T

MODULE = {
    'key': 'replacement', 'group': 'inventory', 'icon': '🔁',
    'title': T('بدل الروشتة وشراء أدوية العملاء', 'Prescription replacement & customer buy-back'),
    'summary': T(
        '«البدل»: عميل (غالباً مريض تأمين) يعيد أدوية روشتته أو يبيع لنا أدوية، فيحصل على «رصيد» يستبدله بمنتجات أخرى أو نقداً. '
        'في SOFTECH يُسجَّل الرصيد كفاتورة شراء على مورد افتراضي (شركات/عام) ويُستهلك بسند صرف. هذا الموديول يربط كل مستندات الحالة الواحدة '
        '(الروشتة، فاتورة التعاقد، فاتورة الشراء/الرصيد، سندات الصرف، فواتير المنتجات) في «حالة» واحدة بدفتر رصيد، ويكشف الاستثناءات '
        '(رصيد قائم، سند غير مربوط…). الحالات التاريخية مُعاد بناؤها من SOFTECH للقراءة فقط؛ والحالات الجديدة تمر بحساب واعتماد (مراجع ومعتمد مختلفان) ثم تنفيذ المستندات.',
        'A "replacement": a customer (often an insurance patient) returns prescription medicines or sells us medicines and gets a "balance" to exchange for other products or cash. '
        'In SOFTECH the balance is a purchase invoice on a virtual supplier (corporate/general) and is consumed by a payment voucher. This module links all of one case\'s documents '
        '(prescription, contract invoice, purchase/balance invoice, vouchers, product invoices) into one "case" with a balance ledger, and flags exceptions '
        '(open balance, unlinked voucher…). Historical cases are rebuilt from SOFTECH read-only; new cases go through calculation and approval (maker and checker are different people) then document execution.'),
    'workflows': [{
        'title': T('مراحل حالة البدل', 'Replacement case stages'),
        'model': 'replacement.ReplacementCase', 'field': 'status',
        'states': [
            {'key': 'draft', 'label': T('مسودة', 'Draft'), 'desc': T('أُنشئت الحالة (النوع، المريض، الأصناف).', 'Case created (type, patient, items).'), 'next': ['calculated', 'cancelled']},
            {'key': 'calculated', 'label': T('محسوبة', 'Calculated'), 'desc': T('السيرفر حسب الرصيد حسب القاعدة (يمكن خصم مختلف بسبب إلزامي).', 'The server calculated the balance by rule (a different discount needs a reason).'), 'next': ['awaiting_approval', 'approved', 'draft']},
            {'key': 'awaiting_approval', 'label': T('بانتظار الموافقة', 'Awaiting approval'), 'desc': T('ينتظر معتمداً مختصاً — منشئ الحالة لا يعتمدها.', 'Waiting for an authorized approver — the case creator cannot approve it.'), 'next': ['approved', 'draft']},
            {'key': 'approved', 'label': T('معتمدة', 'Approved'), 'desc': T('جاهزة لتنفيذ المستندات.', 'Ready to execute the documents.'), 'next': ['executing']},
            {'key': 'executing', 'label': T('جارٍ التنفيذ', 'Executing'), 'desc': T('تجهيز/ربط فاتورة الشراء (الرصيد) وفاتورة التعاقد وفواتير المنتجات وسند الصرف.', 'Preparing/linking the purchase (balance) invoice, contract invoice, product invoices and the voucher.'), 'next': ['entitlement_active']},
            {'key': 'entitlement_active', 'label': T('رصيد قائم', 'Balance open'), 'desc': T('للعميل رصيد لم يُستهلك بالكامل.', 'The customer has an unspent balance.'), 'next': ['settled']},
            {'key': 'settled', 'label': T('مستهلكة بالكامل', 'Fully used'), 'desc': T('استُهلك الرصيد بمنتجات أو نقداً.', 'The balance was used in products or cash.'), 'next': ['reconciled']},
            {'key': 'reconciled', 'label': T('مطابقة', 'Reconciled'), 'desc': T('كل المستندات مطابقة.', 'All documents match.'), 'next': ['closed']},
            {'key': 'closed', 'label': T('مغلقة', 'Closed'), 'desc': T('انتهت الحالة.', 'Case finished.')},
            {'key': 'cancelled', 'label': T('ملغاة', 'Cancelled'), 'desc': T('أُلغيت بسبب إلزامي.', 'Cancelled with a required reason.')},
            {'key': 'reversing', 'label': T('جارٍ العكس', 'Reversing'), 'desc': T('يُعكس تنفيذها.', 'Its execution is being reversed.'), 'next': ['reversed']},
            {'key': 'reversed', 'label': T('معكوسة', 'Reversed'), 'desc': T('عُكست بقيود عكسية (الدفتر لا يُعدَّل أبداً).', 'Reversed with counter-entries (the ledger is never edited).')},
        ],
    }],
}

SCREENS = [
    {
        'key': 'replacement.cases',
        'routes': ['/replacement'],
        'title': T('حالات البدل', 'Replacement cases'),
        'summary': T('كل حالات البدل مع مؤشرات: عدد الحالات، قيمة الأرصدة، ما صُرف منتجات ونقداً وغير مصنّف، والرصيد القائم فعلاً (مفصولاً عن «يُحتمل سداده بسند غير مربوط»). بحث شامل بأي رقم: حالة، PIC، اسم، موبايل، مستند، كود صنف.',
                     'All replacement cases with KPIs: number of cases, balance value, spent as products, cash or unclassified, and the truly open balance (separated from "probably paid by an unlinked voucher"). Universal search by any number: case, PIC, name, mobile, document, item code.'),
        'audience': T('المدير والمشرفون والمشتريات والجودة والصيادلة.', 'Admin, supervisors, purchasing, quality and pharmacists.'),
        'steps': [
            T('صفِّ بالمورد والحالة (رصيد قائم، مستهلكة تحتاج مراجعة، مطابقة) أو «باستثناءات فقط».', 'Filter by supplier and state (open balance, used needing review, reconciled) or "with exceptions only".'),
            T('اضغط الحالة لفتح مساحة عملها.', 'Click a case to open its workspace.'),
            {'text': T('«حالة جديدة» لفتح حالة بدل تشغيلية.', '"New case" opens a live replacement case.'), 'roles': ['admin', 'supervisor', 'pharmacist']},
        ],
        'tips': [T('«سندات تحتاج تأكيد فواتير المنتجات» = سندات صرف يُقترح ربطها بفواتير منتجات؛ أكّدها من صفحة الحالة.', '"Vouchers needing product-invoice confirmation" = vouchers proposed to link to product invoices; confirm them on the case page.')],
        'related': ['replacement.new', 'replacement.detail', 'finance.reconciliation'],
        'updated': '2026-10-10',
    },
    {
        'key': 'replacement.new',
        'routes': ['/replacement/new'],
        'title': T('حالة بدل جديدة', 'New replacement case'),
        'summary': T('صفحة واحدة لتسجيل الحقائق: النوع (روشتة تأمين من صرفنا / أدوية تأمين من خارج صرفنا / عميل غير تأمين يبيع أدوية) وطريقة التسوية (منتجات/نقدي/مختلط)، المريض بكود PIC، اختيار الروشتة من فواتير التعاقد خلال 60 يوماً والأصناف المستبدلة وكمياتها، أو إضافة أصناف بالبحث.',
                     'One page to record the facts: type (our own insurance prescription / insurance meds not dispensed by us / non-insurance customer selling meds) and settlement (products/cash/mixed), the patient by PIC, picking the prescription from contract invoices in the last 60 days and the replaced items and quantities, or adding items by search.'),
        'audience': T('المدير والمشرف والصيادلة المصرح لهم.', 'Admin, supervisors and authorized pharmacists.'),
        'tips': [T('القيم المالية لا تُكتب هنا — يحسبها السيرفر في صفحة الحالة بعد الإنشاء.', 'Money values are not entered here — the server calculates them on the case page after creation.')],
        'related': ['replacement.detail'],
        'updated': '2026-10-10',
    },
    {
        'key': 'replacement.detail',
        'routes': ['/replacement/:id'],
        'title': T('مساحة عمل حالة البدل', 'Replacement case workspace'),
        'summary': T('حالة واحدة: الرأس والقيم (سعر الجمهور، قيمة التعاقد، الخصم، الرصيد، المتبقي)، شريط التقدم، والتبويبات.', 'One case: header and values (public price, contract value, discount, balance, remaining), the progress rail, and the tabs.'),
        'audience': T('المدير والمشرفون والصيادلة.', 'Admin, supervisors and pharmacists.'),
        'tabs': [
            {'key': 'workflow', 'title': T('سير العمل', 'Workflow'),
             'body': T('للحالات التشغيلية فقط: «احسب» الرصيد ← «إرسال للاعتماد» (أو اعتماد تلقائي ضمن الحدود) ← اعتماد/رفض بملاحظة ← تنفيذ المستندات: فاتورة الشراء من المورد الافتراضي، فاتورة التعاقد، منتجات البدل، سند الصرف ← «ترحيل». في الوضع التجريبي «ترحيل» يعرض الخطة فقط.',
                       'Live cases only: "Calculate" the balance → "Submit for approval" (or auto-approve within limits) → approve/reject with a note → execute documents: purchase invoice from the virtual supplier, contract invoice, replacement products, payment voucher → "Post". In trial mode "Post" only shows the plan.')},
            {'key': 'docs', 'title': T('المستندات', 'Documents'),
             'body': T('شجرة كل مستندات SOFTECH المرتبطة بالحالة (روشتة، فاتورة تعاقد، شراء، صرف، استهلاك الرصيد). للربط «المقترح»: «تأكيد أنها فاتورة المريض» أو «ليست لها علاقة».',
                       'The tree of every SOFTECH document linked to the case (prescription, contract invoice, purchase, payment, balance use). For a "proposed" link: "Confirm it is the patient\'s invoice" or "Not related".')},
            {'key': 'items', 'title': T('الأصناف', 'Items'), 'body': T('الأصناف بكميات الروشتة والبدل وأسعار الجمهور والتعاقد والشراء والخصم والقيمة المؤهلة.', 'Items with prescription and replacement quantities, public, contract and purchase prices, discount and eligible value.')},
            {'key': 'ledger', 'title': T('دفتر الرصيد', 'Balance ledger'), 'body': T('دفتر للإضافة فقط: أي تصحيح يظهر كقيد عكسي ولا يُعدَّل أي قيد.', 'Append-only: any correction appears as a counter-entry; no entry is ever edited.')},
            {'key': 'exceptions', 'title': T('الاستثناءات', 'Exceptions'), 'body': T('مشكلات مكتشفة (رصيد بلا صرف، سند غير مربوط…) بدرجتها — «قيد المتابعة» أو «تم الحل» مع ملاحظة.', 'Detected problems (balance not used, unlinked voucher…) by severity — "Following up" or "Resolved" with a note.')},
            {'key': 'recon', 'title': T('المطابقة', 'Reconciliation'), 'body': T('المتوقع مقابل الفعلي لكل بند.', 'Expected vs actual for each line.')},
        ],
        'tips': [T('كل إجراء يتحقق من نسخة الحالة؛ لو ظهر تعارض فشخص آخر عدّلها — أعد تحميل الصفحة.', 'Every action checks the case version; a conflict means someone else changed it — reload the page.')],
        'related': ['replacement.cases'],
        'updated': '2026-10-10',
    },
]
