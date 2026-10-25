from . import T

CHANGE_NOTE = T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour')

MODULE = {
    'key': 'shortage', 'group': 'inventory', 'icon': '🚨',
    'title': T('النواقص', 'Shortages'),
    'summary': T(
        'تسجيل الأصناف الناقصة في الفرع (يدوياً، بالصوت، بصورة لقائمة مكتوبة، أو بلصق قائمة) — النظام يطابق كل سطر مع صنف من الكتالوج ويطلب منك تأكيد المطابقة، '
        'ثم يفحص المخزون الداخلي ليقترح تحويلاً من فرع آخر بدل الشراء، ويصدّر أمر شراء لمورد. '
        'وفيه كشف «نواقص السوق» (أصناف ناقصة من السوق كله وليس عندنا فقط) و«المبيعات الوهمية» (أصناف تعاقد يُعاد شراؤها من المرضى) حتى لا نطلب كميات لا نحتاجها.',
        'Record items short at the branch (manually, by voice, by a photo of a written list, or by pasting a list) — the system matches each line to a catalog item and asks you to confirm, '
        'then checks internal stock to suggest a transfer from another branch instead of buying, and exports a purchase order for a supplier. '
        'It also detects "market shortages" (items short in the whole market, not only with us) and "phantom sales" (contract items bought back from patients) so we do not order quantities we do not need.'),
    'workflows': [{
        'key': 'list',
        'title': T('مراحل قائمة النواقص', 'Shortage list stages'),
        'model': 'shortage.ShortageList', 'field': 'status',
        'states': [
            {'key': 'open', 'label': T('مفتوحة', 'Open'), 'desc': T('الفرع يضيف الأصناف ويؤكد المطابقات.', 'The branch adds items and confirms matches.'), 'next': ['submitted']},
            {'key': 'submitted', 'label': T('مُرسَلة', 'Submitted'), 'desc': T('أُرسلت للمشتريات للمراجعة والتوفير.', 'Sent to purchasing to review and source.'), 'next': ['resolved']},
            {'key': 'resolved', 'label': T('محلولة', 'Resolved'), 'desc': T('عولجت الأصناف (تحويل أو شراء أو غير متوفر).', 'The items were handled (transfer, purchase or unavailable).')},
        ],
    }],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول النواقص', 'A tour of the Shortages module'),
            'summary': T('من تسجيل نواقص الفرع ومتابعتها، للعرض المجمّع للمشتريات، لكشف «نواقص السوق» ومراجعتها، لـ«المبيعات الوهمية» اللي بتقلل الكميات المطلوبة — '
                         'وإزاي كل جزء بيأثر على اللي بيتطلب من الموردين.',
                         'From recording and following a branch\'s shortages, to the aggregated view for purchasing, to detecting and reviewing "market shortages", to "phantom sales" '
                         'that reduce ordered quantities — and how each part affects what is ordered from suppliers.'),
            'roles': ['admin', 'pharmacist', 'purchasing', 'supervisor', 'quality_manager'],
            'steps': [
                {'target': 'nav-shortage', 'nav': '/shortage',
                 'text': T('نبدأ من «النواقص»: قوائم نواقص الفروع.',
                           'Start at "Shortages": the branches\' shortage lists.'),
                 'more': T('كل فرع بيسجّل هنا الأصناف اللي خلصت عنده أو العملاء طلبوها ومش موجودة.\n'
                           '• القائمة بتمشي: مفتوحة ← مُرسَلة للمشتريات ← محلولة.\n'
                           '• المشتريات بتشوف القوائم دي وتقرر: تحويل من فرع تاني، شراء، أو غير متوفر.',
                           'Each branch records here the items it ran out of or that customers asked for and we do not have.\n'
                           '• A list goes: open → submitted to purchasing → resolved.\n'
                           '• Purchasing reviews these lists and decides: transfer from another branch, buy, or unavailable.')},
                {'target': 'shortage-list-new', 'route': '/shortage',
                 'text': T('«+ قائمة جديدة» تبدأ تسجيل نواقص فرعك.',
                           '"+ New list" starts recording your branch\'s shortages.'),
                 'more': T('بتختار الفرع (إجباري) وعنوان وملاحظات (اختياري)، و«إنشاء» يفتح القائمة على طول.\n'
                           '• جوه القائمة تضيف الأصناف: يدوي، صوت، صورة لقائمة مكتوبة، أو لصق.\n'
                           '• النظام بيطابق كل سطر مع صنف من الكتالوج، وانت لازم تأكد المطابقة.',
                           'Choose the branch (required) and a title and notes (optional); "Create" opens the list straight away.\n'
                           '• Inside the list you add items: manual, voice, a photo of a written list, or paste.\n'
                           '• The system matches each line to a catalog item, and you must confirm the match.')},
                {'target': 'shortage-list-grid', 'route': '/shortage',
                 'text': T('القوائم الموجودة بحالتها ونسبة التأكيد.',
                           'The existing lists with their status and confirmation rate.'),
                 'more': T('كل كارت فيه: الفرع والتاريخ والحالة، وعدد الأصناف، و✓ المؤكد، و✕ اللي لسه مش متطابق.\n'
                           '• شريط «تأكيد» الأخضر بيوضح نسبة الأصناف اللي اتأكدت مطابقتها.',
                           'Each card shows: branch, date and status, the item count, ✓ confirmed, and ✕ still unmatched.\n'
                           '• The green "Confirmed" bar shows the share of items whose match is confirmed.')},
                {'target': 'shortage-list-card', 'route': '/shortage',
                 'text': T('افتح قائمة عشان تضيف أصناف أو تأكد المطابقات أو ترسلها.',
                           'Open a list to add items, confirm matches or submit it.'),
                 'more': T('جوه القائمة: راجع المطابقة لكل سطر (النظام بيعرض أفضل احتمالات)، وبعدين «فحص المخزون» يقولك لو ينفع تحويل من فرع تاني بدل الشراء، وبعدين «إرسال».\n'
                           '• متأكدش مطابقة مش متأكد منها — صنف غلط يعني طلب صنف غلط.',
                           'Inside the list: review the match for each line (the system shows the best candidates), then "Check stock" tells you whether a transfer from another branch can replace buying, then "Submit".\n'
                           '• Never confirm a match you are unsure of — a wrong item means ordering the wrong item.')},
                {'target': 'shortage-list-aggregate', 'route': '/shortage',
                 'text': T('«📊 عرض مجمع» يجمع نواقص كل الفروع للمشتريات.',
                           '"📊 Aggregate view" combines all branches\' shortages for purchasing.'),
                 'more': T('بتختار الحالة والفترة وتضغط «🔍 تجميع»: كل صنف بيظهر بالكمية الكلية وتوزيعها على الفروع.\n'
                           '• «📊 تصدير Excel» يطلعها ملف للمشتريات.\n'
                           '• ده الجسر بين نواقص الفروع وطلبات الشراء.',
                           'Choose the status and date range and press "🔍 Aggregate": each item shows its total quantity and split across branches.\n'
                           '• "📊 Export Excel" downloads it as a file for purchasing.\n'
                           '• This is the bridge between branch shortages and purchase orders.')},
                {'target': 'nav-market-shortage', 'nav': '/market-shortage',
                 'text': T('بعدها «نواقص السوق»: أصناف ناقصة من السوق كله.',
                           'Next, "Market shortages": items short across the whole market.'),
                 'more': T('دي غير نواقص الفرع: صنف عليه طلب عالي بس صعب توريده أو بييجي بكوتة.\n'
                           '• المحرك بيكتشفها من المخزون والمبيعات، والإنسان هو اللي بيأكد أو يستبعد.',
                           'These differ from branch shortages: an item in high demand that is hard to source or comes in quotas.\n'
                           '• The engine detects them from stock and sales; a person confirms or dismisses.')},
                {'target': 'shortage-market-run', 'route': '/market-shortage',
                 'text': T('«🔄 تشغيل المحرك ومزامنة البيانات» يحدّث التحليل.',
                           '"🔄 Run engine and sync data" refreshes the analysis.'),
                 'more': T('قبل التشغيل بص على «المبيعات حتى»: لو متأخرة بيظهر زر «⏬ مزامنة المبيعات».\n'
                           '• التشغيل بياخد وقت والتقدم بيظهر جنبه؛ لما يخلص القوائم بتتحدث لوحدها.\n'
                           '• التشغيل مسموح لأدوار معيّنة بس.',
                           'Before running, check "Sales up to": if it is behind, a "⏬ Sync sales" button appears.\n'
                           '• A run takes a while and its progress shows next to it; when done the lists refresh by themselves.\n'
                           '• Only certain roles may run it.')},
                {'target': 'shortage-market-kpis', 'route': '/market-shortage',
                 'text': T('المؤكدة، الجديدة، اللي ممكن توفّرت، والخسارة الشهرية.',
                           'Confirmed, new, possibly available again, and the monthly loss.'),
                 'more': T('«💸 خسارة شهرية» = قيمة الطلب اللي مش بنقدر نلبّيه بسبب النواقص المؤكدة.\n'
                           '• «🔄 قد توفّرت» أصناف مؤكدة رجع مخزونها ومبيعاتها — راجعها وشيل النقص لو اتوفرت.',
                           '"💸 Monthly loss" = the value of demand we cannot meet because of confirmed shortages.\n'
                           '• "🔄 May be available" are confirmed items whose stock and sales recovered — review them and remove the shortage if available.')},
                {'target': 'shortage-market-tabs', 'route': '/market-shortage',
                 'text': T('التغييرات، المرشحون، المؤكدة، المستبعدة، والاتجاهات.',
                           'Changes, candidates, confirmed, dismissed and trends.'),
                 'more': T('• ابدأ بـ «التغييرات»: الجديد من آخر تشغيل.\n'
                           '• «المرشحون»: كل المشتبه فيهم للمراجعة.\n'
                           '• «المؤكدة»: تتصدّر Excel أو واتساب للمورد.\n'
                           '• «المستبعدة»: بسببها وتقدر ترجّعها.',
                           '• Start with "Changes": what is new since the last run.\n'
                           '• "Candidates": all suspects to review.\n'
                           '• "Confirmed": export to Excel or WhatsApp for the supplier.\n'
                           '• "Dismissed": with their reason, and can be restored.')},
                {'target': 'shortage-market-table', 'route': '/market-shortage',
                 'text': T('لكل صنف: «تأكيد» أو «ليس نقصًا» أو «استبعاد».',
                           'For each item: "Confirm", "Not a shortage" or "Dismiss".'),
                 'more': T('القرار هنا إنساني: المحرك بيرشّح بس.\n'
                           '• «تأكيد» بيضيفه للنواقص المؤكدة، ولو الربط مع SOFTECH مفعّل بيتعلّم على كارت الصنف هناك كـ «صنف نواقص».\n'
                           '• «استبعاد» بيطلب سبب، ويقدر يحدد صنف بديل متاح.',
                           'The decision here is human: the engine only suggests.\n'
                           '• "Confirm" adds it to the confirmed shortages, and when the SOFTECH link is on it is flagged on the item card there as a shortage item.\n'
                           '• "Dismiss" asks for a reason and can name an available matching product.')},
                {'target': 'nav-phantom-sales', 'nav': '/phantom-sales',
                 'text': T('وفي الآخر «مبيعات وهمية».',
                           'Finally, "Phantom sales".'),
                 'more': T('أصناف تعاقد معظم مبيعاتها بيرجع يتشترى من المرضى نفسهم، مش من الموردين.\n'
                           '• لو اتحسبت مبيعات عادية هنطلب كميات مش محتاجينها — عشان كده كميتها بتقل في شيت النواقص.',
                           'Contract items whose sales are mostly bought back from the patients themselves, not from suppliers.\n'
                           '• Counted as normal sales, they would make us order quantities we do not need — so their quantity is reduced on the shortage sheet.')},
                {'target': 'shortage-phantom-stats', 'route': '/phantom-sales',
                 'text': T('المُكتشفة، بانتظار المراجعة، المؤكَّدة، المستبعدة، وتخفيض الطلب التقديري.',
                           'Detected, pending review, confirmed, excluded, and the estimated order reduction.'),
                 'more': T('الكشف تلقائي لما نسبة إعادة الشراء توصل للحد المكتوب في رأس الصفحة.\n'
                           '• «بانتظار المراجعة» هي اللي محتاجة قرارك.\n'
                           '• «تخفيض الطلب» = قيمة الشراء اللي هنوفّرها تقديرياً.',
                           'Detection is automatic once the buy-back ratio reaches the threshold shown in the page header.\n'
                           '• "Pending review" are the ones that need your decision.\n'
                           '• "Order reduction" = the estimated purchase value we will save.')},
                {'target': 'shortage-phantom-tabs', 'route': '/phantom-sales',
                 'text': T('«المُكتشفة» للمراجعة، و«المستبعدة» لما حُكم إنه مش وهمي.',
                           '"Detected" for review, and "Excluded" for items judged not phantom.'),
                 'more': T('في «المُكتشفة»: «تأكيد» أو «ليست وهمية». في «المستبعدة»: «إرجاع للتلقائي» يرجّع الحكم للمحرك.\n'
                           '• قراراتك هنا بتأثر على الكميات اللي المشتريات هتطلبها.',
                           'In "Detected": "Confirm" or "Not phantom". In "Excluded": "Back to automatic" returns the decision to the engine.\n'
                           '• Your decisions here affect the quantities purchasing will order.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'shortage.list',
        'routes': ['/shortage'],
        'title': T('النواقص', 'Shortages'),
        'summary': T('قوائم نواقص الفروع: إنشاء قائمة، إضافة الأصناف بأربع طرق، تأكيد المطابقة، فحص المخزون الداخلي، الإرسال، والتصدير (CSV/Excel، مصفوفة الموردين، أمر شراء لمورد). وفيها عرض مجمّع لكل القوائم المفتوحة.',
                     'Branch shortage lists: create a list, add items four ways, confirm matches, check internal stock, submit, and export (CSV/Excel, supplier matrix, purchase order for a supplier). Includes an aggregated view of all open lists.'),
        'audience': T('الصيادلة والمشتريات والمشرفون.', 'Pharmacists, purchasing and supervisors.'),
        'tabs': [
            {'key': 'manual', 'title': T('يدوي', 'Manual'), 'body': T('اكتب جزءاً من اسم الصنف واختره من الاقتراحات مع الكمية.', 'Type part of the item name and pick it from the suggestions with a quantity.')},
            {'key': 'voice', 'title': T('صوتي', 'Voice'), 'body': T('اضغط للتسجيل وقل أسماء الأصناف (عربي أو إنجليزي) مع وقفة قصيرة بين كل صنف، ثم راجع قبل الإضافة. يعمل على Chrome أو Edge.', 'Press to record and say the item names (Arabic or English) with a short pause between items, then review before adding. Works in Chrome or Edge.')},
            {'key': 'ocr', 'title': T('صورة', 'Photo'), 'body': T('ارفع صورة لقائمة مكتوبة؛ النظام يستخرج السطور لتراجعها وتستوردها. استخدم صورة واضحة.', 'Upload a photo of a written list; the system extracts the lines for you to review and import. Use a clear photo.')},
            {'key': 'bulk', 'title': T('نصي', 'Paste'), 'body': T('الصق قائمة: سطر لكل صنف مع الكمية اختيارياً (مثال: بنادول 10).', 'Paste a list: one line per item with an optional quantity (e.g. Panadol 10).')},
        ],
        'steps': [
            T('بعد الإضافة راجع «المطابقة»: النظام يعرض أفضل 3 احتمالات ويجب أن تؤكد الصحيح أو تختار غيره. المطابقات التي صححتها سابقاً يتذكرها («متعلّم»).',
              'After adding, review the "match": the system shows the top 3 candidates and you must confirm the right one or choose another. Matches you corrected before are remembered ("learned").'),
            T('«فحص المخزون»: لكل صنف مؤكد يظهر هل يمكن تحويله من فرع آخر (كلياً أو جزئياً) أو يحتاج شراء.', '"Check stock": for each confirmed item it shows whether it can be transferred from another branch (fully or partly) or needs buying.'),
            T('«إرسال» القائمة للمشتريات.', '"Submit" the list to purchasing.'),
            {'text': T('المشتريات: «مصفوفة الموردين» (كود كل مورد رئيسي + آخر شراء وأقل سعر) أو «أمر شراء لمورد» بأكواد مورد محدد.', 'Purchasing: "Supplier matrix" (each main supplier\'s code + last purchase and lowest price) or "Purchase order for a supplier" with that supplier\'s codes.'),
             'roles': ['admin', 'purchasing']},
        ],
        'tips': [T('لا تؤكد مطابقة لست متأكداً منها — اختيار صنف خطأ يعني طلب صنف خطأ.', 'Never confirm a match you are unsure of — a wrong item means ordering the wrong item.')],
        'related': ['shortage.market', 'transfers.new', 'demand.list'],
        'tour': [
            {'target': 'shortage-list-new', 'text': T('«+ قائمة جديدة» لتسجيل نواقص فرعك.',
                                              '"+ New list" records your branch\'s shortages.'),
             'more': T('بيفتح نافذة «قائمة نواقص جديدة»: الفرع (إجباري)، والعنوان والملاحظات (اختياري).\n'
                       '• «إنشاء» يفتح القائمة الجديدة على طول عشان تبدأ تضيف أصناف.\n'
                       '• مثال للعنوان: «زيارة المندوب — مايو».',
                       'Opens the "New shortage list" window: branch (required), title and notes (optional).\n'
                       '• "Create" opens the new list straight away so you can start adding items.\n'
                       '• Title example: "Rep visit — May".')},
            {'target': 'shortage-list-filters', 'text': T('فلتر الفرع والحالة.',
                                              'Branch and status filters.'),
             'more': T('اختار فرع أو «كل الفروع»، والحالة: مفتوحة، مُرسَلة، أو محلولة.\n'
                       '• «مفتوحة» = لسه الفرع بيضيف ويأكد.\n'
                       '• «مُرسَلة» = مستنية المشتريات تتصرف.',
                       'Pick a branch or "All branches", and the status: open, submitted or resolved.\n'
                       '• "Open" = the branch is still adding and confirming.\n'
                       '• "Submitted" = waiting for purchasing to act.')},
            {'target': 'shortage-list-aggregate', 'text': T('«📊 عرض مجمع» يجمع النواقص من كل القوائم للمشتريات.',
                                              '"📊 Aggregate view" combines shortages from all lists for purchasing.'),
             'more': T('بتختار الحالة والفترة (من تاريخ / إلى تاريخ) وتضغط «🔍 تجميع».\n'
                       '• كل صنف بيظهر بالكمية الكلية وتوزيعها على الفروع ومصادرها.\n'
                       '• «📊 تصدير Excel» يطلع النتيجة ملف، و«← رجوع» يرجعك للقوائم.',
                       'Choose the status and period (from / to date) and press "🔍 Aggregate".\n'
                       '• Each item shows its total quantity, its split across branches and its sources.\n'
                       '• "📊 Export Excel" downloads the result, and "← Back" returns to the lists.')},
            {'target': 'shortage-list-grid', 'text': T('القوائم الموجودة بحالتها وعدد أصنافها ونسبة التأكيد.',
                                              'The existing lists with their status, item count and confirmation rate.'),
             'more': T('كل كارت: العنوان أو اسم الفرع، والتاريخ، والحالة، وعدد الأصناف، و✓ المؤكد، و✕ غير المطابق.\n'
                       '• شريط «تأكيد» بيوضح كام في المية من الأصناف اتأكدت مطابقتها.\n'
                       '• لو مفيش قوائم بيظهر زر «+ قائمة جديدة» في النص.',
                       'Each card: title or branch name, date, status, item count, ✓ confirmed and ✕ unmatched.\n'
                       '• The "Confirmed" bar shows what percentage of items have a confirmed match.\n'
                       '• If there are no lists, a "+ New list" button shows in the middle.')},
            {'target': 'shortage-list-card', 'text': T('افتح أي قائمة لإضافة أصناف أو تأكيد المطابقات أو متابعة حالتها.',
                                              'Open any list to add items, confirm matches or follow its status.'),
             'more': T('جوه القائمة: الإضافة (يدوي، صوت، صورة، لصق)، ومراجعة المطابقة، و«فحص المخزون» للتحويل بدل الشراء، و«إرسال» للمشتريات.\n'
                       '• متأكدش مطابقة مش متأكد منها — صنف غلط يعني طلب صنف غلط.',
                       'Inside the list: adding (manual, voice, photo, paste), match review, "Check stock" for a transfer instead of buying, and "Submit" to purchasing.\n'
                       '• Never confirm a match you are unsure of — a wrong item means ordering the wrong item.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'shortage.market',
        'routes': ['/market-shortage'],
        'title': T('نواقص السوق', 'Market shortages'),
        'summary': T('محرك يكتشف الأصناف الناقصة من السوق (تغطية منخفضة، أيام نفاد، انخفاض مبيعات آخر 30 يوماً عن المعدل) مع مراجعة بشرية: تأكيد أو استبعاد بسبب (مع البديل المتاح)، وتقدير الخسارة الشهرية.',
                     'An engine that detects items short in the market (low coverage, stock-out days, last-30-day sales below the yearly rate) with human review: confirm or dismiss with a reason (and the available alternative), plus the estimated monthly loss.'),
        'audience': T('المشتريات والصيادلة والمشرفون والجودة.', 'Purchasing, pharmacists, supervisors and quality.'),
        'tabs': [
            {'key': 'changes', 'title': T('التغييرات', 'Changes'), 'body': T('ما تغيّر منذ آخر تشغيل: نواقص جديدة للمراجعة، وأصناف مؤكدة عاد مخزونها ومبيعاتها للطبيعي (أزل النقص إن توفّرت).', 'What changed since the last run: new shortages to review, and confirmed items whose stock and sales are back to normal (remove the shortage if available).')},
            {'key': 'candidates', 'title': T('المرشحون', 'Candidates'), 'body': T('الأصناف المشتبه بنقصها (نفاد مؤكد، نقص حاد، مراقبة) مرتبة بالشدة أو الخسارة. «تأكيد» أو «ليس نقصاً» (ينقلها للمستبعدة).', 'Suspected shortage items (confirmed out, severe, watch) sorted by severity or loss. "Confirm" or "Not a shortage" (moves it to dismissed).')},
            {'key': 'confirmed', 'title': T('المؤكدة', 'Confirmed'), 'body': T('النواقص المؤكدة — تصدير Excel أو نسخها لرسالة واتساب للمورد.', 'Confirmed shortages — export to Excel or copy them into a WhatsApp message to the supplier.')},
            {'key': 'dismissed', 'title': T('المستبعدة', 'Dismissed'), 'body': T('ما استُبعد مع سببه (مقاس بديل متاح، يُطلب عند الحاجة، غير متوفر بمصر، موقوف/موسمي، اكتشاف خاطئ). يمكن استرجاعها.', 'What was dismissed and why (alternative size available, ordered on demand, unavailable in Egypt, discontinued/seasonal, false detection). Can be restored.')},
            {'key': 'trends', 'title': T('📈 الاتجاهات', '📈 Trends'), 'body': T('تطور النواقص عبر الوقت.', 'How shortages evolve over time.')},
        ],
        'steps': [{'text': T('«تشغيل المحرك ومزامنة البيانات» لتحديث القائمة (تأكد أن المبيعات غير متأخرة).', '"Run engine and sync data" to refresh the list (make sure sales data is not behind).'), 'roles': ['admin', 'purchasing']}],
        'workflows': [],
        'related': ['shortage.list', 'shortage.phantom', 'purchasing.engine'],
        'tour': [
            {'target': 'shortage-market-kpis', 'text': T('النواقص المؤكدة والجديدة واللي ممكن توفّرت والخسارة الشهرية.',
                                              'Confirmed and new shortages, ones that may be available again, and the monthly loss.'),
             'more': T('• «مؤكدة (في نقص)»: اللي اتأكد نقصها.\n'
                       '• «🆕 نواقص جديدة»: ظهرت في آخر تشغيل ومحتاجة مراجعة.\n'
                       '• «🔄 قد توفّرت»: مؤكدة رجع مخزونها ومبيعاتها — راجعها.\n'
                       '• «💸 خسارة شهرية»: قيمة الطلب اللي مش بنلبّيه بالجنيه في الشهر.',
                       '• "Confirmed (short)": items confirmed as short.\n'
                       '• "🆕 New shortages": appeared in the last run and need review.\n'
                       '• "🔄 May be available": confirmed items whose stock and sales recovered — review them.\n'
                       '• "💸 Monthly loss": unmet demand value in pounds per month.')},
            {'target': 'shortage-market-tabs', 'text': T('التغييرات، المرشحون، المؤكدة، المستبعدة، والاتجاهات.',
                                              'Changes, candidates, confirmed, dismissed and trends.'),
             'more': T('الرقم جنب كل تبويب = عدد أصنافه.\n'
                       '• ابدأ يومك بـ «التغييرات» (الجديد من آخر تشغيل).\n'
                       '• «المرشحون» فيه فلتر بالشدة (نفاد مؤكد، نقص حاد، مراقبة) وترتيب «الأشد» أو «الأعلى خسارة».',
                       'The number next to each tab = its item count.\n'
                       '• Start your day with "Changes" (what is new since the last run).\n'
                       '• "Candidates" has a severity filter (confirmed out, severe, watch) and "Most severe" or "Highest loss" sorting.')},
            {'target': 'shortage-market-toolbar', 'text': T('فلتر بالتصنيف، بحث بالكود أو الاسم، وتصدير Excel أو واتساب.',
                                              'Filter by class, search by code or name, and export to Excel or WhatsApp.'),
             'more': T('الفلتر والبحث بيطبقوا على التبويب المفتوح.\n'
                       '• «📥 Excel» يطلع ملف بالأصناف المعروضة.\n'
                       '• «📱 واتساب» يجهّز رسالة: تنسخها أو تكتب رقم المورد وتفتح واتساب بيها.',
                       'The filter and search apply to the open tab.\n'
                       '• "📥 Excel" downloads a file with the shown items.\n'
                       '• "📱 WhatsApp" prepares a message: copy it, or enter the supplier\'s number and open WhatsApp with it.')},
            {'target': 'shortage-market-table', 'text': T('الأصناف — راجع ثم «تأكيد» أو «ليس نقصًا» أو «استبعاد».',
                                              'The items — review, then "Confirm", "Not a shortage" or "Dismiss".'),
             'more': T('الأعمدة: الخسارة الشهرية، التغطية (المخزون ÷ متوسط الطلب الشهري)، القمع (نزول مبيعات آخر 30 يوم عن المعدل)، وأيام النفاد.\n'
                       '• «تأكيد» يضيفه للمؤكدة، ولو الربط مع SOFTECH مفعّل بيتعلّم «صنف نواقص» على كارت الصنف هناك.\n'
                       '• «استبعاد» بيطلب سبب ويقدر يحدد صنف بديل متاح.',
                       'Columns: monthly loss, coverage (stock ÷ average monthly demand), suppression (last-30-day sales drop versus the yearly rate) and stock-out days.\n'
                       '• "Confirm" adds it to confirmed; when the SOFTECH link is on, the item card there is flagged as a shortage item.\n'
                       '• "Dismiss" asks for a reason and can name an available matching product.')},
            {'target': 'shortage-market-run', 'text': T('«🔄 تشغيل المحرك ومزامنة البيانات» يحدّث التحليل.',
                                              '"🔄 Run engine and sync data" refreshes the analysis.'),
             'more': T('جنبه «آخر تشغيل» و«المبيعات حتى» — لو المبيعات متأخرة بيظهر بالأصفر ومعاه زر «⏬ مزامنة المبيعات».\n'
                       '• وقت التشغيل بيظهر «جارٍ تشغيل المحرك…» بالنسبة، والقوائم بتتحدث لما يخلص.\n'
                       '• التشغيل مسموح لأدوار معيّنة بس.',
                       'Next to it are "Last run" and "Sales up to" — if sales are behind it turns amber with a "⏬ Sync sales" button.\n'
                       '• While running it shows "Running the engine…" with a percentage, and the lists refresh when done.\n'
                       '• Only certain roles may run it.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'shortage.phantom',
        'routes': ['/phantom-sales'],
        'title': T('المبيعات الوهمية', 'Phantom sales'),
        'summary': T('أصناف تعاقد يُعاد شراء معظم مبيعاتها من المرضى (حسابات إعادة الشراء الداخلية) لا من الموردين؛ تُكتشف تلقائياً عندما تكون نسبة إعادة الشراء ≥ 50%، وتُقلَّل كميتها في شيت النواقص حتى لا نطلب ما لا نحتاجه. الإنسان يؤكد أو يستبعد.',
                     'Contract items whose sales are mostly bought back from patients (internal buy-back accounts), not from suppliers; auto-detected when buy-back ≥ 50%, and their quantity is reduced on the shortage sheet so we do not order what we do not need. A person confirms or excludes.'),
        'audience': T('المشتريات والصيادلة.', 'Purchasing and pharmacists.'),
        'tabs': [
            {'key': 'flagged', 'title': T('المُكتشفة', 'Detected'), 'body': T('الأصناف المُكتشفة مع نسبة الوهمية والنسبة الموصى بطلبها والطلب الحقيقي وقيمة التخفيض. «تأكيد» أو «ليست وهمية».', 'Detected items with phantom ratio, recommended order %, genuine need and reduction value. "Confirm" or "Not phantom".')},
            {'key': 'excluded', 'title': T('المستبعدة', 'Excluded'), 'body': T('ما استُبعد (ليس وهمياً) — «إرجاع للتلقائي» لإعادة الحكم للمحرك.', 'What was excluded (not phantom) — "Back to automatic" returns the decision to the engine.')},
        ],
        'workflows': [],
        'related': ['shortage.market', 'replacement.cases'],
        'tour': [
            {'target': 'shortage-phantom-header', 'text': T('«مبيعات وهمية»: أصناف يُعاد شراء معظم مبيعاتها من المرضى لا من الموردين.',
                                              '«Phantom sales»: items mostly bought back from patients rather than from suppliers.'),
             'more': T('تحت العنوان مكتوب الحد (نسبة إعادة الشراء من المبيعات) والفترة اللي بيتحسب عليها.\n'
                       '• الأصناف دي كميتها بتقل في شيت النواقص عشان منطلبش اللي مش محتاجينه.',
                       'Under the title is the threshold (buy-back as a share of sales) and the period it is measured over.\n'
                       '• These items get a reduced quantity on the shortage sheet so we do not order what we do not need.')},
            {'target': 'shortage-phantom-stats', 'text': T('المُكتشفة، بانتظار المراجعة، المؤكَّدة، المستبعدة، وتخفيض الطلب التقديري.',
                                              'Detected, pending review, confirmed, excluded, and the estimated order reduction.'),
             'more': T('• «⏳ بانتظار المراجعة»: محتاجة قرارك.\n'
                       '• «تخفيض الطلب (تقديري)»: قيمة الشراء اللي هنوفّرها بالجنيه.',
                       '• "⏳ Pending review": needs your decision.\n'
                       '• "Order reduction (estimate)": the purchase value saved, in pounds.')},
            {'target': 'shortage-phantom-tabs', 'text': T('«المُكتشفة» للمراجعة، و«المستبعدة» لما حُكم أنه ليس وهمياً.',
                                              '«Detected» for review, and «Excluded» for items judged not phantom.'),
             'more': T('الرقم جنب كل تبويب = عدد أصنافه.\n'
                       '• الصنف اللي تقول عليه «ليست وهمية» بينتقل لـ «المستبعدة» وبيرجع يتطلب بكميته العادية.',
                       'The number next to each tab = its item count.\n'
                       '• An item you mark "Not phantom" moves to "Excluded" and is ordered at its normal quantity again.')},
            {'target': 'shortage-phantom-toolbar', 'text': T('فلترة بالتصنيف وبحث بالكود أو الاسم.',
                                              'Filter by class and search by code or name.'),
             'more': T('الفلتر والبحث بيطبقوا على التبويب المفتوح.\n'
                       '• مفيد لو عايز تراجع تصنيف معيّن مرة واحدة.',
                       'The filter and search apply to the open tab.\n'
                       '• Useful to review one class at a time.')},
            {'target': 'shortage-phantom-table', 'text': T('الأصناف بنسبة الوهمية والنسبة الموصى بطلبها والطلب الحقيقي؛ اضغط عنوان العمود للترتيب.',
                                              'Items with phantom ratio, recommended order % and genuine need; click a column header to sort.'),
             'more': T('• «نسبة الوهمية» = إعادة الشراء ÷ المبيعات.\n'
                       '• «النسبة الموصى بطلبها» و«الطلب الحقيقي»: اللي فعلاً محتاجين نشتريه.\n'
                       '• شارة «شديد» أو «مراقبة» جنب الاسم، و«📉 نقص سوق» لو الصنف كمان ناقص من السوق.',
                       '• "Phantom ratio" = buy-back ÷ sales.\n'
                       '• "Recommended order %" and "Genuine need": what we really need to buy.\n'
                       '• A "Severe" or "Watch" badge next to the name, and "📉 Market shortage" if the item is also short in the market.')},
            {'target': 'shortage-phantom-row-actions', 'text': T('في «المُكتشفة»: «تأكيد» أو «ليست وهمية»؛ وفي «المستبعدة» يظهر «إرجاع للتلقائي».',
                                              'In «Detected»: «Confirm» or «Not phantom»; in «Excluded» you get «Back to automatic».'),
             'more': T('• «تأكيد»: الحالة تبقى «مؤكَّد» والتخفيض يفضل مطبّق.\n'
                       '• «ليست وهمية»: بيسألك عن سبب (اختياري) وينقله للمستبعدة.\n'
                       '• «إرجاع للتلقائي»: يلغي قرارك ويرجّع الحكم للمحرك.',
                       '• "Confirm": the status becomes "Confirmed" and the reduction stays applied.\n'
                       '• "Not phantom": asks for an (optional) reason and moves it to Excluded.\n'
                       '• "Back to automatic": cancels your decision and hands it back to the engine.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'shortage.mobile',
        'routes': ['/m/shortage', '/m/shortage/new', '/m/shortage/:id'],
        'title': T('النواقص (موبايل)', 'Shortages (mobile)'),
        'summary': T('تسجيل النواقص من بين الأرفف: افتح قائمة (أو أنشئ واحدة بعنوان اختياري)، أضف الصنف الناقص بسرعة، أو الصق قائمة، أو بالصوت، أو بصورة، ثم «إرسال القائمة». يعمل بدون إنترنت مؤقتاً.',
                     'Record shortages in the aisle: open a list (or create one with an optional title), add missing items quickly, or paste a list, use voice or a photo, then "Submit list". Works briefly offline.'),
        'audience': T('العاملون في الفروع.', 'Branch staff.'),
        'steps': [
            T('«قائمة نواقص جديدة» ← «إنشاء وبدء التسجيل».', '"New shortage list" → "Create and start".'),
            T('اكتب اسم الصنف الناقص ← «إضافة» (يبقى المؤشر في الخانة للإضافة السريعة).', 'Type the missing item name → "Add" (the cursor stays for quick entry).'),
            T('راجع «غير مطابق» و«بحاجة لمراجعة»، ثم «إرسال القائمة».', 'Check "no match" and "needs review", then "Submit list".'),
        ],
        'related': ['shortage.list'],
        'tour': [
            {'target': 'shortage-mobile-filters', 'text': T('فلترة قوائم النواقص: مفتوحة، الكل، مُرسَلة، محلولة.',
                                              'Filter shortage lists: open, all, submitted, resolved.'),
             'more': T('اسحب الأزرار يمين وشمال لو مش ظاهرة كلها.\n'
                       '• «مفتوحة» = لسه بتضيف فيها؛ «مُرسَلة» = راحت للمتابعة؛ «محلولة» = اتعاملت.',
                       'Swipe the buttons sideways if they do not all fit.\n'
                       '• "Open" = still adding; "Submitted" = sent for follow-up; "Resolved" = handled.')},
            {'target': 'shortage-mobile-lists', 'text': T('قوائم النواقص بعدد أصنافها والمؤكد منها — اضغط قائمة لفتحها.',
                                              'Shortage lists with item and confirmed counts — tap a list to open it.'),
             'more': T('لو القوايم كتير، «تحميل المزيد» تحت بيجيب الباقي.\n'
                       '• اضغط القائمة المفتوحة عشان تكمّل إضافة فيها.',
                       'If there are many lists, "Load more" at the bottom brings the rest.\n'
                       '• Tap an open list to keep adding to it.')},
            {'target': 'shortage-mobile-new', 'text': T('زر «+» لإنشاء قائمة نواقص جديدة.',
                                              'The «+» button creates a new shortage list.'),
             'more': T('الزر العائم ده بيفتح شاشة «قائمة نواقص جديدة».\n'
                       '• قبل ما تعمل قائمة جديدة شوف لو فيه قائمة مفتوحة لنفس الفرع تكمّل فيها.',
                       'This floating button opens the "New shortage list" screen.\n'
                       '• Before creating a new list, check whether there is an open list for the same branch to continue.')},
            {'target': 'shortage-mobile-create', 'text': T('في شاشة القائمة الجديدة: «إنشاء وبدء التسجيل» بعد تحديد الفرع والعنوان الاختياري.',
                                              'On the new-list screen: «Create and start» after setting the branch and optional title.'),
             'more': T('لو صلاحيتك تسمح بتختار الفرع؛ غير كده بيتحط فرعك تلقائي.\n'
                       '• بعد الإنشاء بتتفتح القائمة على طول عشان تبدأ تضيف.\n'
                       '• «إلغاء» يرجعك من غير ما يعمل قائمة.',
                       'If your permissions allow, you choose the branch; otherwise your own branch is set automatically.\n'
                       '• After creating, the list opens straight away so you can start adding.\n'
                       '• "Cancel" goes back without creating a list.')},
            {'target': 'shortage-mobile-quick-add', 'text': T('داخل قائمة مفتوحة: اكتب الصنف والكمية ثم «+ إضافة»، أو «لصق قائمة» أو صوت أو صورة.',
                                              'Inside an open list: type the item and quantity then «+ Add», or «Paste list», voice or photo.'),
             'more': T('بعد «+ إضافة» المؤشر بيفضل في الخانة عشان تضيف اللي بعده بسرعة. لو النت فاصل بيتضاف لما يرجع.\n'
                       '• «📋 لصق قائمة»: سطر لكل صنف مع الكمية، و«🎤 صوت» و«📷 صورة» بيحطوا السطور للمراجعة.\n'
                       '• كل سطر بيتطابق مع الكتالوج؛ «غير مطابق» محتاج مراجعة.',
                       'After "+ Add" the cursor stays in the box so you can add the next one quickly. If offline, it is added when the connection returns.\n'
                       '• "📋 Paste list": one line per item with quantity; "🎤 Voice" and "📷 Photo" put the lines up for review.\n'
                       '• Each line is matched to the catalog; "no match" needs review.')},
            {'target': 'shortage-mobile-submit', 'text': T('بعد إضافة أصناف: «✅ إرسال القائمة» لإرسالها للمتابعة.',
                                              'Once items are added: «✅ Submit list» sends it for follow-up.'),
             'more': T('الزر بيوضح عدد الأصناف اللي هتتبعت.\n'
                       '• بعد الإرسال القائمة بتبقى «مُرسَلة» ومش هتقدر تضيف فيها تاني.\n'
                       '• راجع الأصناف «غير مطابق» قبل ما ترسل.',
                       'The button shows how many items will be sent.\n'
                       '• After submitting, the list becomes "Submitted" and you can no longer add to it.\n'
                       '• Review the "no match" items before submitting.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
]
