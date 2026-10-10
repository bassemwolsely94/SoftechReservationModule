from . import T

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
                                              '"+ New list" records your branch\'s shortages.')},
            {'target': 'shortage-list-filters', 'text': T('فلتر الفرع والحالة.',
                                              'Branch and status filters.')},
            {'target': 'shortage-list-aggregate', 'text': T('«📊 عرض مجمع» يجمع النواقص من كل القوائم للمشتريات.',
                                              '"📊 Aggregate view" combines shortages from all lists for purchasing.')},
            {'target': 'shortage-list-grid', 'text': T('القوائم الموجودة.',
                                              'The existing lists.')},
            {'target': 'shortage-list-card', 'text': T('افتح أي قائمة لإضافة أصناف أو متابعة حالتها.',
                                              'Open any list to add items or follow its status.')},
        ],
        'updated': '2026-10-10',
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
                                              'Confirmed and new shortages, ones that may be available again, and the monthly loss.')},
            {'target': 'shortage-market-tabs', 'text': T('التغييرات، المرشحون، المؤكدة، المستبعدة، والاتجاهات.',
                                              'Changes, candidates, confirmed, excluded and trends.')},
            {'target': 'shortage-market-toolbar', 'text': T('فلتر وبحث وتصدير Excel أو واتساب.',
                                              'Filter, search and export to Excel or WhatsApp.')},
            {'target': 'shortage-market-table', 'text': T('الأصناف — راجع وأكّد أو استبعد.',
                                              'The items — review and confirm or exclude.')},
            {'target': 'shortage-market-run', 'text': T('«🔄 تشغيل المحرك» يحدّث التحليل.',
                                              '"🔄 Run the engine" refreshes the analysis.')},
        ],
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
    },
]
