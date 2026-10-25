from . import T

CHANGE_NOTE = T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour')

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
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول بدل الروشتة', 'A tour of the Prescription replacement module'),
            'summary': T('من قائمة حالات البدل ومؤشراتها، لتسجيل حالة جديدة (المريض والروشتة والأصناف)، لمساحة عمل الحالة: الرصيد والمتبقي وشريط التقدم والمستندات — '
                         'وإزاي الحالة بتربط مستندات SOFTECH ببعض.',
                         'From the list of replacement cases and its indicators, to recording a new case (patient, prescription and items), to the case workspace: balance, remaining, '
                         'progress rail and documents — and how a case ties SOFTECH documents together.'),
            'roles': ['admin', 'supervisor', 'purchasing', 'quality_manager', 'pharmacist'],
            'steps': [
                {'target': 'nav-replacement', 'nav': '/replacement',
                 'text': T('نبدأ من «بدل الروشتة» في القائمة.',
                           'Start at "Prescription replacement" in the menu.'),
                 'more': T('البدل: عميل بيرجّع أدوية روشتته أو بيبيع لنا أدوية، فياخد «رصيد» يصرفه منتجات أو نقدي.\n'
                           '• في SOFTECH الرصيد بيتسجّل فاتورة شراء على مورد افتراضي وبيتصرف بسند.\n'
                           '• الموديول ده بيجمع كل مستندات الحالة الواحدة في مكان واحد ويكشف اللي ناقص.',
                           'A replacement: a customer returns prescription medicines or sells us medicines and gets a "balance" to spend on products or cash.\n'
                           '• In SOFTECH the balance is a purchase invoice on a virtual supplier, paid out by a voucher.\n'
                           '• This module brings all of one case\'s documents together and flags what is missing.')},
                {'target': 'replacement-cases-kpis', 'route': '/replacement',
                 'text': T('المؤشرات: عدد الحالات وقيمة الأرصدة وإزاي اتصرفت.',
                           'The indicators: number of cases, balance value and how it was spent.'),
                 'more': T('• منتجات / نقداً / «صرف غير مصنّف» (سندات محتاجة تأكيد فواتير المنتجات).\n'
                           '• «رصيد قائم فعلاً» = فلوس لسه للعملاء.\n'
                           '• «يُحتمل سداده بسند غير مربوط» = غالباً اتدفع بس SOFTECH مربطش السند.\n'
                           '• كل الأرقام بيحسبها السيرفر.',
                           '• Products / cash / "unclassified" (vouchers needing product-invoice confirmation).\n'
                           '• "Truly open balance" = money still owed to customers.\n'
                           '• "Probably paid by an unlinked voucher" = likely paid, but SOFTECH never linked the voucher.\n'
                           '• All figures are computed by the server.')},
                {'target': 'replacement-cases-filters', 'route': '/replacement',
                 'text': T('بحث بأي رقم، وفلاتر الفرع والمورد والحالة.',
                           'Search by any number, and branch, supplier and status filters.'),
                 'more': T('البحث بياخد رقم حالة أو PIC أو اسم أو موبايل أو أي رقم مستند أو كود صنف.\n'
                           '• «برصيد فقط» و«باستثناءات فقط» بيوصلوك للحالات اللي محتاجة شغل.',
                           'The search takes a case number, PIC, name, mobile, any document number or item code.\n'
                           '• "With balance only" and "With exceptions only" take you to the cases that need work.')},
                {'target': 'replacement-cases-new', 'route': '/replacement',
                 'text': T('«➕ حالة جديدة» لتسجيل حالة بدل تشغيلية.',
                           '"➕ New case" records a live replacement case.'),
                 'more': T('الحالات القديمة متبنية من SOFTECH للقراءة بس؛ الحالة الجديدة بتمشي: تسجيل ← حساب ← اعتماد ← تنفيذ المستندات.\n'
                           '• الإنشاء مسموح لأدوار وموظفين معيّنين، والسيرفر بيتحقق.\n'
                           '• الخطوات الجاية بتوريك صفحة الحالة الجديدة.',
                           'Old cases are rebuilt from SOFTECH read-only; a new case goes: record → calculate → approve → execute documents.\n'
                           '• Creating is allowed only for certain roles and employees, and the server checks.\n'
                           '• The next steps show the new case page.')},
                {'target': 'replacement-new-type', 'route': '/replacement/new',
                 'text': T('الفرع ونوع الحالة وطريقة التسوية.',
                           'Branch, case type and settlement mode.'),
                 'more': T('النوع: «روشتة تأمين من صرفنا»، «أدوية تأمين من خارج صرفنا»، أو «عميل غير تأمين يبيع أدوية».\n'
                           '• التسوية: منتجات، نقدي، أو مختلط.\n'
                           '• في روشتة التأمين تقدر تعلّم «الصنف ناقص / لا يمكن توفيره».',
                           'Type: "our own insurance prescription", "insurance meds not dispensed by us" or "non-insurance customer selling meds".\n'
                           '• Settlement: products, cash or mixed.\n'
                           '• For an insurance prescription you can tick "item short / cannot be supplied".')},
                {'target': 'replacement-new-patient', 'route': '/replacement/new',
                 'text': T('كود المريض PIC ← روشتات التعاقد ← الأصناف وكمياتها.',
                           'Patient PIC → contract prescriptions → items and quantities.'),
                 'more': T('«عرض روشتات التعاقد للمريض» بيجيب فواتير التعاقد بتاعته في آخر 60 يوم.\n'
                           '• اختار الفاتورة، علّم الأصناف اللي راجعة، واكتب كمية البدل (مش أكتر من كمية الروشتة).\n'
                           '• لو مفيش فواتير تقدر تضيف الأصناف يدوي تحت.',
                           '"Show patient\'s contract prescriptions" brings their contract invoices from the last 60 days.\n'
                           '• Pick the invoice, tick the items being returned, and enter the replacement quantity (no more than the prescription quantity).\n'
                           '• If there are no invoices you can add items manually below.')},
                {'target': 'replacement-new-create', 'route': '/replacement/new',
                 'text': T('«إنشاء الحالة» — والفلوس بيحسبها السيرفر بعدين.',
                           '"Create case" — the server works out the money later.'),
                 'more': T('الزر بيشتغل بعد اختيار الفرع وصنف واحد على الأقل، وجنبه عدد الأصناف وقيمة الجمهور التقريبية.\n'
                           '• مفيش أي قيمة مالية بتتكتب هنا؛ الرصيد بيتحسب بـ «احسب» في صفحة الحالة.\n'
                           '• (في الجولة مش هننشئ حالة.)',
                           'The button works once a branch and at least one item are set; next to it are the item count and the approximate public value.\n'
                           '• No money value is typed here; the balance is computed with "Calculate" on the case page.\n'
                           '• (In this tour we will not create a case.)')},
                {'target': 'replacement-cases-table', 'route': '/replacement', 'wait': '/replacement/:id',
                 'text': T('افتح أي حالة من الجدول. لو الجدول فاضي اضغط «إنهاء».',
                           'Open any case from the table. If the table is empty, press "End".'),
                 'more': T('كل صف: رقم الحالة، المريض وPIC، المورد ونسبة الخصم، فاتورة الشراء، الرصيد وطريقة صرفه، والمتبقي بالأحمر لو لسه فيه.\n'
                           '• «الثقة» = قد إيه الربط بين المستندات مؤكد.',
                           'Each row: case number, patient and PIC, supplier and discount rate, purchase invoice, balance and how it was spent, and the remaining in red if any.\n'
                           '• "Confidence" = how certain the link between documents is.')},
                {'target': 'replacement-detail-header', 'route': '/replacement/:id',
                 'text': T('رأس الحالة: الحالة والنوع والمريض والقيم.',
                           'Case header: status, type, patient and values.'),
                 'more': T('شارة «📜 تاريخية» = متبنية من SOFTECH للقراءة، و«🟢 حالة تشغيلية» = اتعملت من هنا وليها سير عمل.\n'
                           '• تحت: سعر الجمهور، قيمة التعاقد، والخصم المطبّق.',
                           'A "📜 Historical" badge = rebuilt from SOFTECH read-only; "🟢 Live case" = created here with a workflow.\n'
                           '• Below: public price, contract value and the applied discount.')},
                {'target': 'replacement-detail-balance', 'route': '/replacement/:id',
                 'text': T('«الرصيد» و«المتبقي» منه.',
                           'The "Balance" and its "Remaining".'),
                 'more': T('المتبقي بالأحمر = رصيد لسه للعميل ماتصرفش؛ بالأخضر = اتصرف كله.\n'
                           '• الرصيد بيحسبه السيرفر بالقاعدة، ومحدش بيكتبه بإيده.',
                           'Remaining in red = balance still owed to the customer; in green = fully spent.\n'
                           '• The balance is computed by the server by rule; nobody types it in.')},
                {'target': 'replacement-detail-rail', 'route': '/replacement/:id',
                 'text': T('شريط التقدم: الروشتة ← التعاقد ← الشراء ← الصرف ← استهلاك الرصيد ← المطابقة.',
                           'The progress rail: prescription → contract → purchase → redemption → balance use → reconciliation.'),
                 'more': T('كل خطوة ✓ لما مستندها يتلاقي ويتربط، و○ لسه.\n'
                           '• أول ○ في الشريط بيقولك الحالة واقفة فين.',
                           'Each step gets ✓ once its document is found and linked, ○ otherwise.\n'
                           '• The first ○ on the rail tells you where the case is stuck.')},
                {'target': 'replacement-detail-tabs', 'route': '/replacement/:id',
                 'text': T('التبويبات: سير العمل، المستندات، الأصناف، دفتر الرصيد، الاستثناءات، والمطابقة.',
                           'Tabs: workflow, documents, items, balance ledger, exceptions and reconciliation.'),
                 'more': T('• «سير العمل» للحالات التشغيلية بس: «احسب» ← «إرسال للاعتماد» ← اعتماد من شخص غير منشئ الحالة ← تنفيذ المستندات.\n'
                           '• «المستندات»: أكّد أو ارفض الربط المقترح.\n'
                           '• «دفتر الرصيد» للإضافة بس: أي تصحيح بيبقى قيد عكسي.',
                           '• "Workflow" for live cases only: "Calculate" → "Submit for approval" → approval by someone other than the creator → execute documents.\n'
                           '• "Documents": confirm or reject a proposed link.\n'
                           '• The "Balance ledger" is append-only: any correction is a counter-entry.')},
            ],
        },
    ],
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
        'tour': [
            {'target': 'replacement-cases-new', 'text': T('«➕ حالة جديدة» لتسجيل حالة بدل تشغيلية.',
                                              '"➕ New case" records a live replacement case.'),
             'more': T('بيفتح صفحة تسجيل الحالة: النوع والمريض والروشتة والأصناف.\n'
                       '• الإنشاء مسموح لأدوار وموظفين معيّنين بس، والسيرفر بيتحقق.\n'
                       '• القيم المالية مش بتتكتب — بتتحسب في صفحة الحالة بعد الإنشاء.',
                       'Opens the case entry page: type, patient, prescription and items.\n'
                       '• Creating is allowed only for certain roles and employees, and the server checks.\n'
                       '• Money values are not typed — they are computed on the case page after creation.')},
            {'target': 'replacement-cases-kpis', 'text': T('ملخص الحالات والأرصدة وإزاي اتصرفت.',
                                              'A summary of cases, balances and how they were spent.'),
             'more': T('• «صرف غير مصنّف»: سندات محتاجة تأكيد فواتير المنتجات من صفحة الحالة.\n'
                       '• «رصيد قائم فعلاً»: لسه للعملاء.\n'
                       '• «قائم — يُحتمل سداده بسند غير مربوط»: غالباً اتدفع بس السند مش مربوط في SOFTECH — راجعه من «سداد الموردين».\n'
                       '• الأرقام بتتبع الفلاتر.',
                       '• "Unclassified": vouchers needing product-invoice confirmation on the case page.\n'
                       '• "Truly open balance": still owed to customers.\n'
                       '• "Open — probably paid by an unlinked voucher": likely paid but the voucher is not linked in SOFTECH — check it in "Supplier payments".\n'
                       '• The numbers follow the filters.')},
            {'target': 'replacement-cases-exceptions', 'text': T('الاستثناءات المفتوحة — اضغط نوع عشان تفلتر بيه.',
                                              'Open exceptions — click a type to filter by it.'),
             'more': T('كل شارة نوع استثناء وعدده، ولونها بيوضح الدرجة (معلومة، تحذير، مرتفع، حرج).\n'
                       '• الضغط عليها يعرض الحالات اللي فيها الاستثناء ده بس، والضغط تاني يلغي الفلتر.\n'
                       '• الشريط ده بيظهر بس لو فيه استثناءات مفتوحة.',
                       'Each badge is an exception type and its count; its colour shows severity (info, warning, high, critical).\n'
                       '• Clicking it shows only cases with that exception; clicking again clears the filter.\n'
                       '• This strip only appears when there are open exceptions.')},
            {'target': 'replacement-cases-filters', 'text': T('بحث وفلاتر: الفرع، المورد، الحالة، برصيد، باستثناءات.',
                                              'Search and filters: branch, supplier, status, with balance, with exceptions.'),
             'more': T('البحث بأي رقم: حالة، PIC، اسم، موبايل، رقم مستند، أو كود صنف.\n'
                       '• المورد: الموردين الافتراضيين بنسبهم (25%، 30%، 40%، 50%، عام).\n'
                       '• الحالة: رصيد قائم، مستهلكة (تحتاج مراجعة)، أو مطابقة.',
                       'Search by any number: case, PIC, name, mobile, document number or item code.\n'
                       '• Supplier: the virtual suppliers with their rates (25%, 30%, 40%, 50%, general).\n'
                       '• Status: open balance, used (needs review) or reconciled.')},
            {'target': 'replacement-cases-table', 'text': T('الحالات — اضغط أي صف لفتح مساحة عمله.',
                                              'The cases — click any row to open its workspace.'),
             'more': T('كل صف: الرقم، المريض، الفرع، المورد والخصم، فاتورة الشراء، الرصيد، المصروف منتجات/نقدي/غير مصنّف، المتبقي، الوضع، والثقة.\n'
                       '• المتبقي بالأحمر = لسه فيه رصيد.\n'
                       '• عمود ⚠ = عدد الاستثناءات المفتوحة.',
                       'Each row: number, patient, branch, supplier and discount, purchase invoice, balance, spent as products/cash/unclassified, remaining, state and confidence.\n'
                       '• Remaining in red = balance still open.\n'
                       '• The ⚠ column = number of open exceptions.')},
            {'target': 'replacement-cases-pager', 'text': T('التنقل بين الصفحات.',
                                              'Move between pages.'),
             'more': T('كل صفحة فيها 50 حالة، وجنبها رقم الصفحة وإجمالي عدد الحالات.\n'
                       '• أي تغيير في الفلاتر بيرجعك لأول صفحة.',
                       'Each page holds 50 cases, with the page number and the total case count.\n'
                       '• Any filter change takes you back to page one.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
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
        'tour': [
            {'target': 'replacement-new-type', 'text': T('اختر الفرع ونوع الحالة وطريقة التسوية (منتجات/نقدي/مختلط).',
                                              'Pick the branch, case type and settlement mode (products/cash/mixed).'),
             'more': T('النوع: «روشتة تأمين من صرفنا»، «أدوية تأمين من خارج صرفنا»، أو «عميل غير تأمين يبيع أدوية».\n'
                       '• الفرع بيتحط فرعك تلقائي وتقدر تغيّره.\n'
                       '• في روشتة التأمين بيظهر اختيار «الصنف ناقص / لا يمكن توفيره».',
                       'Type: "our own insurance prescription", "insurance meds not dispensed by us" or "non-insurance customer selling meds".\n'
                       '• The branch defaults to yours and you can change it.\n'
                       '• For an insurance prescription, an "item short / cannot be supplied" option appears.')},
            {'target': 'replacement-new-patient', 'text': T('اكتب كود المريض PIC ثم «عرض روشتات التعاقد للمريض» واختر الروشتة والأصناف وكمياتها.',
                                              'Enter the patient PIC, then «Show patient\'s contract prescriptions» and pick the prescription, items and quantities.'),
             'more': T('بيجيب فواتير التعاقد للمريض في آخر 60 يوم؛ اختار الفاتورة، وعلّم الأصناف الراجعة.\n'
                       '• «كمية البدل» مش ممكن تزيد عن «كمية الروشتة».\n'
                       '• لو مفيش فواتير بتظهر رسالة، وتقدر تضيف الأصناف يدوي في القسم اللي بعده.',
                       'Brings the patient\'s contract invoices from the last 60 days; pick the invoice and tick the returned items.\n'
                       '• "Replacement qty" cannot exceed "Prescription qty".\n'
                       '• If there are none, a message says so and you can add items manually in the next section.')},
            {'target': 'replacement-new-extra-items', 'text': T('إضافة أصناف أخرى بالبحث (بدون روشتة أو من خارج صرفنا) مع الكمية.',
                                              'Add other items by search (no prescription or not dispensed by us) with quantity.'),
             'more': T('ابحث عن الصنف واختاره، بيتضاف بكمية 1 وتقدر تعدّلها.\n'
                       '• «حذف» يشيل الصنف من القائمة.\n'
                       '• نفس الصنف مش بيتضاف مرتين.',
                       'Search and pick the item; it is added with quantity 1, which you can change.\n'
                       '• "Delete" removes the item from the list.\n'
                       '• The same item is not added twice.')},
            {'target': 'replacement-new-refs', 'text': T('رقم الروشتة ورقم الموافقة والملاحظات (اختيارية).',
                                              'Prescription number, approval number and notes (optional).'),
             'more': T('أرقام مرجعية بتساعد المراجع يلاقي المستندات بسرعة بعدين.\n'
                       '• اكتب في الملاحظات أي حاجة غير عادية في الحالة.',
                       'Reference numbers that help the reviewer find the documents quickly later.\n'
                       '• Write anything unusual about the case in the notes.')},
            {'target': 'replacement-new-create', 'text': T('«إنشاء الحالة» بعد اختيار الفرع وصنف واحد على الأقل؛ القيم المالية يحسبها السيرفر لاحقاً.',
                                              '«Create case» once a branch and at least one item are set; the server calculates money values later.'),
             'more': T('جنبه عدد الأصناف وقيمة الجمهور التقريبية (للمعلومة بس).\n'
                       '• بعد الإنشاء بتتفتح صفحة الحالة كمسودة: هناك «احسب» ثم «إرسال للاعتماد».\n'
                       '• لو فيه مشكلة (زي صلاحية) بتظهر رسالة بالأحمر.',
                       'Next to it are the item count and the approximate public value (for information only).\n'
                       '• After creation the case page opens as a draft: there you "Calculate" then "Submit for approval".\n'
                       '• If there is a problem (such as permission) a red message appears.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
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
        'tour': [
            {'target': 'replacement-detail-header', 'text': T('رأس الحالة: الرقم والحالة والنوع، المريض، الفرع والتعاقد، وقيم السعر والخصم.',
                                              'Case header: number, status and type, patient, branch and contract, and price and discount values.'),
             'more': T('• «📜 تاريخية»: متبنية من SOFTECH للقراءة بس.\n'
                       '• «🟢 حالة تشغيلية v…»: اتعملت من هنا، والرقم بعد v هو نسختها — لو حد عدّلها قبلك هيظهر تعارض، أعد تحميل الصفحة.\n'
                       '• «🔒 مقفلة»: مفيش تعديل عليها.',
                       '• "📜 Historical": rebuilt from SOFTECH, read-only.\n'
                       '• "🟢 Live case v…": created here; the number after v is its version — if someone changed it before you, a conflict shows; reload the page.\n'
                       '• "🔒 Locked": it can no longer be edited.')},
            {'target': 'replacement-detail-balance', 'text': T('«الرصيد» المستحق و«المتبقي» منه؛ المتبقي بالأحمر يعني أنه لم يُستهلك بعد.',
                                              'The «Balance» due and the «Remaining»; red remaining means it is not used up yet.'),
             'more': T('الرصيد بيحسبه السيرفر بالقاعدة ومحدش بيكتبه بإيده.\n'
                       '• تحت الرأس شارات المصروف: منتجات، نقدي، غير مصنّف، وأي استثناء مفتوح.',
                       'The balance is computed by the server by rule; nobody types it in.\n'
                       '• Under the header are badges for what was spent: products, cash, unclassified, plus any open exception.')},
            {'target': 'replacement-detail-rail', 'text': T('شريط التقدم: الروشتة، فاتورة التعاقد، الشراء، الصرف، استهلاك الرصيد، والمطابقة.',
                                              'The progress rail: prescription, contract invoice, purchase, redemption, balance use and reconciliation.'),
             'more': T('✓ أخضر = المستند اتلاقى واتربط، ○ رمادي = لسه.\n'
                       '• «استهلاك الرصيد» بيتعلّم لما المتبقي يبقى صفر.\n'
                       '• أول ○ بيقولك الحالة واقفة فين.',
                       'Green ✓ = the document was found and linked; grey ○ = not yet.\n'
                       '• "Balance use" is ticked when the remaining reaches zero.\n'
                       '• The first ○ tells you where the case is stuck.')},
            {'target': 'replacement-detail-tabs', 'text': T('التبويبات: سير العمل (للحالات التشغيلية فقط)، المستندات، الأصناف، دفتر الرصيد، الاستثناءات، والمطابقة.',
                                              'Tabs: workflow (live cases only), documents, items, balance ledger, exceptions and reconciliation.'),
             'more': T('• «سير العمل»: «احسب» ← «إرسال للاعتماد» ← اعتماد من معتمد مختص (منشئ الحالة مايعتمدهاش) ← تنفيذ المستندات ← «ترحيل».\n'
                       '• «المستندات»: أكّد أو ارفض الربط المقترح.\n'
                       '• «دفتر الرصيد» مابيتعدلش؛ التصحيح قيد عكسي.',
                       '• "Workflow": "Calculate" → "Submit for approval" → approval by an authorized approver (not the creator) → execute documents → "Post".\n'
                       '• "Documents": confirm or reject a proposed link.\n'
                       '• The "Balance ledger" is never edited; a correction is a counter-entry.')},
            {'target': 'replacement-detail-rebuild', 'text': T('«⟳ إعادة البناء» يعيد بناء الحالة من بيانات SOFTECH بالقراءة فقط.',
                                              '«⟳ Rebuild» rebuilds the case from SOFTECH data, read-only.'),
             'more': T('بيقرا مستندات الحالة من جديد من نسخة SOFTECH عندنا ويحدّث الربط — مابيكتبش أي حاجة في SOFTECH.\n'
                       '• محتاج صلاحية تعديل، ولازم فاتورة الشراء تكون ظهرت في النسخة.\n'
                       '• استخدمه لما مستند جديد يتسجّل في SOFTECH ومش ظاهر هنا.',
                       'Reads the case documents again from our copy of SOFTECH and refreshes the links — it writes nothing to SOFTECH.\n'
                       '• Needs edit permission, and the purchase invoice must already be in the copy.\n'
                       '• Use it when a new document was recorded in SOFTECH and does not show here.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
]
