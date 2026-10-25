from . import T

MODULE = {
    'key': 'chronic', 'group': 'inventory', 'icon': '🧬',
    'title': T('الأدوية المزمنة والمواد الفعّالة', 'Chronic medicines & active ingredients'),
    'summary': T(
        'تصنيف الأصناف كأدوية مزمنة بربطها بمادة فعّالة وتصنيف مرض (سكري، ضغط، قلب، غدة…)، وتعريف «بروتوكولات المتابعة» التي تولّد مهام متابعة المرضى. '
        'وفيه تنقية بيانات المواد الفعّالة القادمة من SOFTECH (غير نظيفة) بمراجعة بشرية، والبحث المنظّم عن كل دواء يحتوي مادة معيّنة. '
        'لا يُكتب أي شيء في SOFTECH من هنا، ولا تُعتمد البدائل تلقائياً قبل التحقق.',
        'Tag items as chronic medicines by linking them to an active ingredient and a disease class (diabetes, hypertension, heart, thyroid…), and define '
        '"follow-up protocols" that generate patient follow-up tasks. It also cleans the active-ingredient data coming from SOFTECH (which is dirty) by human review, '
        'and offers a structured search for every medicine containing a molecule. Nothing is written to SOFTECH from here, and alternatives are never applied automatically before verification.'),
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول الأدوية المزمنة والمواد الفعّالة', 'A tour of the chronic medicines & active ingredients module'),
            'summary': T('إزاي البيانات بتتنضّف: تنقية المواد الفعّالة الجاية من SOFTECH، وبعدين تصنيف الأصناف كمزمنة عشان مهام متابعة المرضى تتولّد، وأخيراً البحث بالمادة الفعّالة.',
                         'How the data gets cleaned: cleaning the active ingredients coming from SOFTECH, then tagging items as chronic so patient follow-up tasks are generated, and finally searching by active ingredient.'),
            'roles': ['admin', 'pharmacist', 'supervisor'],
            'steps': [
                {'target': 'nav-composition', 'nav': '/composition',
                 'text': T('«المخزون» ← «تنقية المواد الفعّالة».', '"Inventory" → "Active-ingredient cleanup".'),
                 'more': T('البداية: أسماء المواد الفعّالة في SOFTECH مش نظيفة، فالنظام بيحلّلها ويقترح المادة والتركيز، وصيدلي بيراجع ويعتمد.\n'
                           '• مفيش أي تعديل بيتكتب في SOFTECH من الموديول ده.',
                           'The starting point: active-ingredient names in SOFTECH are not clean, so the system parses them and proposes molecule and strength, and a pharmacist reviews and approves.\n'
                           '• Nothing is written to SOFTECH from this module.')},
                {'target': 'chronic-composition-filters', 'route': '/composition',
                 'text': T('ابدأ بحالة «يحتاج مراجعة».', 'Start with the "Needs review" status.'),
                 'more': T('دي السطور اللي ثقة التحليل فيها قليلة أو محتاجة عين صيدلي.\n'
                           '• تقدر تبحث بالاسم أو تعرض «تركيبات فقط».',
                           'These are rows whose parsing confidence is low or that need a pharmacist\'s eye.\n'
                           '• You can search by name or show "Combinations only".')},
                {'target': 'chronic-composition-list', 'route': '/composition',
                 'text': T('كل سطر: المادة ومكوّناتها ونسبة الثقة وعدد الأصناف.', 'Each row: the ingredient, its components, confidence and item count.'),
                 'more': T('«✎ تعديل» يصحّح المكوّنات والتركيز، وزر «x صنف ▼» يعرض الأصناف المرتبطة عشان تتأكد.',
                           '"✎ Edit" corrects the components and strength, and the "x items ▼" button lists the linked items so you can check.')},
                {'target': 'chronic-composition-row-actions', 'route': '/composition',
                 'text': T('اختار التصنيف ثم «اعتماد» أو «غير دوائي…» أو «رفض».', 'Pick the class, then "Approve", "Non-drug…" or "Reject".'),
                 'more': T('المعتمد بس هو اللي بيظهر كـ«معتمد» في بحث المواد الفعّالة.\n'
                           '• بعد دفعة اعتمادات اضغط «🔄 تحديث فهرس البحث».',
                           'Only approved rows show as "Approved" in active-ingredient search.\n'
                           '• After a batch of approvals press "🔄 Refresh search index".')},
                {'target': 'nav-chronic-classifier', 'nav': '/chronic-classifier',
                 'text': T('«المخزون» ← «الأدوية المزمنة».', '"Inventory" → "Chronic medicines".'),
                 'more': T('هنا بتحدد أي الأصناف أدوية مزمنة وتربطها بمادتها الفعّالة وتصنيف المرض.\n'
                           '• الأصناف المزمنة هي اللي بتتولّد لها مهام متابعة المرضى في «متابعة المزمن».',
                           'Here you decide which items are chronic medicines and link them to their active ingredient and disease class.\n'
                           '• Chronic items are the ones that generate patient follow-up tasks in "Chronic follow-up".')},
                {'target': 'chronic-classifier-tabs', 'route': '/chronic-classifier',
                 'text': T('أربع تبويبات: الأصناف، المواد الفعّالة، توليد المهام، والإثراء الذكي.', 'Four tabs: items, active ingredients, generate tasks and AI enrichment.'),
                 'more': T('• «💊 المواد الفعّالة»: فيها «بروتوكولات المتابعة» — إمتى تتعمل مهمة ووسيلة التواصل.\n'
                           '• «⚡ توليد المهام»: تشغيل التوليد يدوياً (وبيشتغل يومياً لوحده).\n'
                           '• «🤖 الإثراء الذكي»: اقتراحات لازم تتراجع وتتعتمد بإيد صيدلي.',
                           '• "💊 Active ingredients": holds the "follow-up protocols" — when a task is created and the contact method.\n'
                           '• "⚡ Generate tasks": run generation by hand (it also runs daily by itself).\n'
                           '• "🤖 AI enrichment": suggestions a pharmacist must review and approve.')},
                {'target': 'chronic-classifier-filters', 'route': '/chronic-classifier',
                 'text': T('دوّر على الصنف واختار «غير مصنَّف» عشان تشوف اللي فاضل.', 'Find the item and choose "Unclassified" to see what is left.'),
                 'more': T('البحث بالاسم أو كود SOFTECH أو الباركود.\n'
                           '• الكروت فوق بتوضح نسبة التصنيف — هدفك تقلل «غير مصنَّف».',
                           'Search by name, SOFTECH code or barcode.\n'
                           '• The cards above show the classification rate — your aim is to shrink "Unclassified".')},
                {'target': 'chronic-classifier-table', 'route': '/chronic-classifier',
                 'text': T('«تصنيف» على الصنف يفتح لوحة التصنيف.', '"Classify" on an item opens the classify panel.'),
                 'more': T('في اللوحة: اربطه بـ«مادة موجودة» أو «إنشاء جديد»، علّم «دواء مزمن» واختار تصنيف المرض، وبعدين «حفظ التصنيف».\n'
                           '• ده تصنيف بس — مش موافقة على بديل.',
                           'In the panel: link it to an "Existing ingredient" or "Create new", tick "Chronic medicine" and pick the disease class, then "Save classification".\n'
                           '• This is classification only — not approval of a substitute.')},
                {'target': 'nav-ingredient-search', 'nav': '/ingredient-search',
                 'text': T('«المخزون» ← «بحث المواد الفعّالة».', '"Inventory" → "Active-ingredient search".'),
                 'more': T('نتيجة الشغل اللي فات: تقدر تلاقي كل صنف فيه مادة معيّنة بتركيز أو شكل معيّن.\n'
                           '• للاطلاع بس — مفيش استبدال تلقائي.',
                           'The payoff of the work above: find every item containing a given molecule at a given strength or form.\n'
                           '• For lookup only — there is no automatic substitution.')},
                {'target': 'chronic-ingredient-search-source', 'route': '/ingredient-search',
                 'text': T('اختار «معتمد فقط» للنتائج المؤكدة.', 'Choose "Approved only" for confirmed results.'),
                 'more': T('«مقترح» = لسه صيدلي ما راجعهوش في شاشة التنقية.\n'
                           '• سلامة المريض أولاً: اتأكد قبل ما تقترح أي بديل للعميل.',
                           '"Suggested" = not yet reviewed by a pharmacist on the cleanup screen.\n'
                           '• Patient safety first: verify before offering any alternative to a customer.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'chronic.classifier',
        'routes': ['/chronic-classifier'],
        'title': T('مصنّف الأدوية المزمنة', 'Chronic medicine classifier'),
        'summary': T('تحديد أي الأصناف أدوية مزمنة، وإدارة المواد الفعّالة وبروتوكولات المتابعة، وتوليد مهام المتابعة من تاريخ الشراء.',
                     'Decide which items are chronic medicines, manage active ingredients and follow-up protocols, and generate follow-up tasks from purchase history.'),
        'audience': T('الصيادلة والمدير والمشرفون.', 'Pharmacists, admins and supervisors.'),
        'tabs': [
            {'key': 'classifier', 'title': T('🔬 مصنّف الأصناف', '🔬 Item classifier'),
             'body': T('ابحث عن صنف (اسم، كود، باركود) وصفِّ (غير مصنَّف / مصنَّف / مزمن). «تصنيف»: اربطه بمادة فعّالة موجودة أو أنشئ جديدة (الاسم، ATC، التركيز)، وحدد هل هو دواء مزمن وتصنيف المرض ووسوم الوصفة.',
                       'Search an item (name, code, barcode) and filter (unclassified / classified / chronic). "Classify": link it to an existing active ingredient or create one (name, ATC, strength), and set whether it is chronic, the disease class and prescription tags.')},
            {'key': 'ingredients', 'title': T('💊 المواد الفعّالة', '💊 Active ingredients'),
             'body': T('الجدول الرئيسي للمواد الفعّالة مع وسومها والأصناف المرتبطة بها، و«بروتوكولات المتابعة» لكل مادة: متى تُنشأ المهمة (بعد الشراء بـ X يوم، قبل نفاد العبوة، عند النفاد، شهري…)، نوع العميل، وسيلة التواصل (اتصال/واتساب/رسالة)، الأولوية، وقالب الرسالة.',
                       'The master table of active ingredients with tags and linked items, and the "follow-up protocols" per ingredient: when a task is created (X days after purchase, before the pack runs out, on run-out day, monthly…), customer type, contact method (call/WhatsApp/SMS), priority and message template.')},
            {'key': 'tasks', 'title': T('⚡ توليد المهام', '⚡ Generate tasks'),
             'body': T('تشغيل توليد مهام المتابعة من تاريخ مشتريات العملاء حسب البروتوكولات (يعمل يومياً تلقائياً أيضاً).', 'Run follow-up task generation from customers\' purchase history according to the protocols (it also runs daily automatically).')},
            {'key': 'enrichment', 'title': T('🤖 الإثراء الذكي', '🤖 AI enrichment'),
             'body': T('اقتراحات بالذكاء الاصطناعي للتصنيف والمواد الفعّالة تُراجع وتُعتمد يدوياً.', 'AI suggestions for classification and ingredients, reviewed and approved manually.')},
        ],
        'tips': [T('الاسم العلمي في SOFTECH غالباً غير دقيق؛ اعتمد على المادة الفعّالة المعتمدة.', 'The SOFTECH scientific name is often inaccurate; rely on the approved active ingredient.')],
        'related': ['followups.tasks', 'chronic.composition'],
        'tour': [
            {'target': 'chronic-classifier-header', 'text': T('«مصنّف الأدوية المزمنة»: ربط الأصناف بمادتها الفعّالة وتحديد المزمن منها للمتابعة.',
                                              '«Chronic medicine classifier»: link items to their active ingredient and mark chronic ones for follow-up.'),
             'more': T('الأصناف اللي بتتعلّم «مزمن» هنا هي اللي بيتولّد لعملائها مهام متابعة (تذكير بميعاد الصرف).\n'
                       '• مفيش حاجة بتتكتب في SOFTECH من هنا.',
                       'Items marked "chronic" here are the ones whose customers get follow-up tasks (refill reminders).\n'
                       '• Nothing is written to SOFTECH from here.')},
            {'target': 'chronic-classifier-tabs', 'text': T('التبويبات: مصنّف الأصناف، المواد الفعّالة، توليد المهام، والإثراء الذكي.',
                                              'Tabs: item classifier, active ingredients, generate tasks, and AI enrichment.'),
             'more': T('• «🔬 مصنّف الأصناف»: تصنيف صنف صنف.\n'
                       '• «💊 المواد الفعّالة»: المواد وبروتوكولات المتابعة (إمتى المهمة تتعمل ووسيلة التواصل).\n'
                       '• «⚡ توليد المهام»: تشغيل التوليد يدوياً، وهو كمان بيشتغل يومياً.\n'
                       '• «🤖 الإثراء الذكي»: اقتراحات بتتراجع وتتعتمد يدوياً.',
                       '• "🔬 Item classifier": classify item by item.\n'
                       '• "💊 Active ingredients": ingredients and follow-up protocols (when a task is created and the contact method).\n'
                       '• "⚡ Generate tasks": run generation by hand; it also runs daily.\n'
                       '• "🤖 AI enrichment": suggestions that are reviewed and approved by hand.')},
            {'target': 'chronic-classifier-summary', 'text': T('إجمالي الأصناف، المصنَّف، غير المصنَّف، والمزمن مع نسبة التصنيف.',
                                              'Total items, classified, unclassified, and chronic with the classification rate.'),
             'more': T('مقياس التقدّم: كل ما «غير مصنَّف» قلّ، كل ما متابعة المرضى بقت أدق.\n'
                       '• «مزمن» = عدد الأصناف اللي هتولّد مهام متابعة.',
                       'Your progress gauge: the smaller "Unclassified" gets, the more accurate patient follow-up becomes.\n'
                       '• "Chronic" = the number of items that will generate follow-up tasks.')},
            {'target': 'chronic-classifier-filters', 'text': T('ابحث بالاسم أو كود SOFTECH أو الباركود، وصفِّ حسب حالة التصنيف.',
                                              'Search by name, SOFTECH code or barcode, and filter by classification status.'),
             'more': T('الفلتر: «جميع الأصناف»، «غير مصنَّف»، «مصنَّف»، «مزمن»، «مصنَّف / غير مزمن».\n'
                       '• ابدأ بـ«غير مصنَّف» وامسك الأصناف الأكتر بيعاً الأول.',
                       'The filter: "All items", "Unclassified", "Classified", "Chronic", "Classified / not chronic".\n'
                       '• Start with "Unclassified" and handle the best-selling items first.')},
            {'target': 'chronic-classifier-table', 'text': T('الأصناف بمادتها الفعّالة وتصنيفها؛ «تصنيف» أو «تعديل» يفتح لوحة التصنيف.',
                                              'Items with their active ingredient and class; «Classify» or «Edit» opens the classify panel.'),
             'more': T('الأعمدة: اسم الصنف، الكود، المادة الفعّالة، والتصنيف.\n'
                       '• الصنف المصنَّف بيظهر له «تعديل» بدل «تصنيف» لو محتاج تصحيح.',
                       'Columns: item name, code, active ingredient and class.\n'
                       '• A classified item shows "Edit" instead of "Classify" when it needs a correction.')},
            {'target': 'chronic-classifier-panel', 'text': T('بعد اختيار صنف: اربطه بمادة موجودة أو جديدة وحدد هل هو مزمن — تصنيف فقط وليس بديلاً.',
                                              'After selecting an item: link it to an existing or new ingredient and set if it is chronic — classification only, not substitution.'),
             'more': T('• «مادة موجودة» تختار من القائمة، أو «إنشاء جديد» بالاسم الإنجليزي (مطلوب) والعربي وكود ATC والتركيز.\n'
                       '• علّم «دواء مزمن» واختار «تصنيف المرض المزمن» ووسوم الوصفة.\n'
                       '• مفيش حاجة بتتحفظ غير بـ«حفظ التصنيف».',
                       '• "Existing ingredient" picks from the list, or "Create new" with the English name (required), Arabic name, ATC code and strength.\n'
                       '• Tick "Chronic medicine" and pick the "Chronic disease class" and prescription tags.\n'
                       '• Nothing is saved until "Save classification".')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'chronic.composition',
        'routes': ['/composition'],
        'title': T('تنقية المواد الفعّالة', 'Active-ingredient cleanup'),
        'summary': T('مراجعة واعتماد تحليل نصوص المواد الفعّالة القادمة من SOFTECH: لكل سطر تفتح الأصناف المرتبطة، تنظّف اسم المادة وتحتفظ بكل مكوّن أو تحذفه، تختار التصنيف، ثم «اعتماد» أو «رفض» أو «غير دوائي» (مستحضر تجميل، مستلزم طبي، لبن أطفال).',
                     'Review and approve the parsing of active-ingredient text coming from SOFTECH: per row, open the linked items, clean the molecule name and keep or drop each component, choose the class, then "approve", "reject" or "non-drug" (cosmetic, medical supply, infant formula).'),
        'audience': T('الصيادلة والمشتريات.', 'Pharmacists and purchasing.'),
        'steps': [
            T('ابدأ بفلتر «يحتاج مراجعة» ثم «بانتظار المراجعة».', 'Start with "needs review", then "pending review".'),
            T('افتح الأصناف المرتبطة للتأكد، صحّح المكوّنات والتركيز، واختر التصنيف (أو أضف تصنيفاً جديداً).', 'Open the linked items to check, correct components and strength, and pick a class (or add a new one).'),
            T('«اعتماد». بعد دفعة اعتمادات اضغط «تحديث فهرس البحث» ليظهر أثرها في بحث المواد الفعّالة.', '"Approve". After a batch of approvals press "Refresh search index" so they appear in ingredient search.'),
        ],
        'tips': [T('لا يتم أي تعديل على SOFTECH من هذه الشاشة.', 'Nothing in SOFTECH is changed from this screen.')],
        'related': ['chronic.ingredient_search', 'catalog.intel'],
        'tour': [
            {'target': 'chronic-composition-header', 'text': T('«تنقية المواد الفعّالة»: مراجعة تحليل بيانات SOFTECH واعتماده — لا يُعدَّل شيء في SOFTECH.',
                                              '«Active-ingredient cleanup»: review and approve the parsing of SOFTECH data — nothing in SOFTECH is changed.'),
             'more': T('النظام بيحلّل نص المادة الفعّالة في SOFTECH ويقترح المكوّنات والتركيز؛ انت كصيدلي بتأكد أو تصحّح.\n'
                       '• الاعتماد هنا هو اللي بيخلّي بحث المواد الفعّالة موثوق.',
                       'The system parses the SOFTECH ingredient text and proposes components and strength; you as a pharmacist confirm or correct.\n'
                       '• Approval here is what makes active-ingredient search trustworthy.')},
            {'target': 'chronic-composition-rebuild', 'text': T('«تحديث فهرس البحث» بعد دفعة اعتمادات ليظهر أثرها في بحث المواد الفعّالة.',
                                              '«Refresh search index» after a batch of approvals so they show in ingredient search.'),
             'more': T('بعد ما يخلص بتظهر رسالة خضرا بعدد السطور والأصناف والمواد والمعتمد منها.\n'
                       '• فوقه «＋ إضافة تصنيف جديد» لو التصنيف اللي محتاجه مش موجود.',
                       'When it finishes a green message shows the rows, items, molecules and how many are approved.\n'
                       '• Above it, "＋ Add new class" if the class you need does not exist.')},
            {'target': 'chronic-composition-stats', 'text': T('أرقام المراجعة: سطور سوفتك، التركيبات، الجزيئات المقترحة، الأصناف المغطاة، ونسبة الاعتماد.',
                                              'Review numbers: SOFTECH rows, combinations, proposed molecules, items covered and approval rate.'),
             'more': T('«نسبة الاعتماد» هي مقياس التقدّم.\n'
                       '• «قيم عامة/فارغة» = سطور في SOFTECH مفيهاش مادة حقيقية.',
                       '"Approval rate" is your progress gauge.\n'
                       '• "Generic/empty values" = SOFTECH rows with no real molecule.')},
            {'target': 'chronic-composition-filters', 'text': T('ابحث بالاسم، واختر الحالة (يبدأ بـ«يحتاج مراجعة»)، أو «تركيبات فقط».',
                                              'Search by name, pick the status (starts at «Needs review»), or «Combinations only».'),
             'more': T('الحالات: «يحتاج مراجعة»، «بانتظار المراجعة»، «معتمد»، «مرفوض»، «الكل».\n'
                       '• «تركيبات فقط» للأدوية اللي فيها أكتر من مادة — محتاجة تدقيق أكتر.',
                       'Statuses: "Needs review", "Pending review", "Approved", "Rejected", "All".\n'
                       '• "Combinations only" for medicines with more than one molecule — they need extra care.')},
            {'target': 'chronic-composition-list', 'text': T('كل سطر مادة فعّالة بمكوّناتها وثقتها؛ «✎ تعديل» للتصحيح وعدد الأصناف لعرضها.',
                                              'Each ingredient row with components and confidence; «✎ Edit» to correct and the item count to show items.'),
             'more': T('• النسبة الملوّنة = ثقة التحليل؛ «مركّب» و«غير دوائي» علامات.\n'
                       '• «✎ تعديل» يفتح محرر المكوّنات: صحّح الاسم والتركيز أو استبعد مكوّن.\n'
                       '• «x صنف ▼» يعرض الأصناف المرتبطة عشان تتأكد قبل الاعتماد.',
                       '• The coloured percentage = parsing confidence; "Combination" and "Non-drug" are badges.\n'
                       '• "✎ Edit" opens the component editor: fix the name and strength or drop a component.\n'
                       '• "x items ▼" lists the linked items so you can check before approving.')},
            {'target': 'chronic-composition-row-actions', 'text': T('لكل سطر: اختر التصنيف ثم «اعتماد» أو «غير دوائي…» أو «رفض».',
                                              'Per row: pick the class, then «Approve», «Non-drug…» or «Reject».'),
             'more': T('• «اعتماد»: التحليل صح ويظهر «معتمد» في البحث.\n'
                       '• «غير دوائي…»: مستحضر تجميل أو مستلزم طبي أو لبن أطفال.\n'
                       '• «رفض»: التحليل غلط.\n'
                       'ولا واحد منهم بيغيّر حاجة في SOFTECH.',
                       '• "Approve": the parsing is right and shows as "Approved" in search.\n'
                       '• "Non-drug…": cosmetic, medical supply or infant formula.\n'
                       '• "Reject": the parsing is wrong.\n'
                       'None of them changes anything in SOFTECH.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'chronic.ingredient_search',
        'routes': ['/ingredient-search'],
        'title': T('بحث المواد الفعّالة', 'Active-ingredient search'),
        'summary': T('ابحث عن كل الأدوية التي تحتوي مادة فعّالة معيّنة، بتركيز معيّن، أو شكل صيدلي، أو تصنيف — مفيد لإيجاد بديل متوفر. اختر «معتمد فقط» للنتائج المؤكدة.',
                     'Find every medicine containing a given active ingredient, at a given strength, form or class — useful to find an available alternative. Choose "approved only" for confirmed results.'),
        'audience': T('الصيادلة والكول سنتر والمشتريات.', 'Pharmacists, call center and purchasing.'),
        'tips': [T('النتائج «المقترحة» لم يراجعها صيدلي بعد — تأكد قبل اقتراح بديل للعميل.', '"Suggested" results are not reviewed by a pharmacist yet — verify before offering an alternative.')],
        'related': ['chronic.composition'],
        'tour': [
            {'target': 'chronic-ingredient-search-header', 'text': T('«بحث المواد الفعّالة»: بحث للاطلاع فقط عن الأصناف التي تحتوي مادة معيّنة.',
                                              '«Active-ingredient search»: a lookup of items that contain a given molecule.'),
             'more': T('مفيد لما صنف ناقص وعايز تعرف إيه الأصناف التانية اللي فيها نفس المادة.\n'
                       '• الشاشة للاطلاع بس — أي بديل لازم صيدلي يتأكد منه قبل ما يتعرض على العميل.',
                       'Useful when an item is short and you want to know which other items have the same molecule.\n'
                       '• The screen is lookup only — any alternative must be verified by a pharmacist before it is offered.')},
            {'target': 'chronic-ingredient-search-molecule', 'text': T('اكتب اسم المادة الفعّالة (مثل AMLODIPINE) واختر من الاقتراحات.',
                                              'Type the active ingredient (e.g. AMLODIPINE) and pick from the suggestions.'),
             'more': T('الاقتراحات بتظهر وانت بتكتب، وجنب كل مادة عدد الأصناف اللي فيها.\n'
                       '• اكتب بالإنجليزي زي ما المادة مسجّلة.',
                       'Suggestions appear as you type, each with the number of items containing it.\n'
                       '• Type in English as the molecule is recorded.')},
            {'target': 'chronic-ingredient-search-filters', 'text': T('ضيّق البحث بالتركيز والوحدة والشكل الصيدلي والتصنيف؛ «مسح» يعيد الفلاتر.',
                                              'Narrow by strength, unit, dosage form and class; «Clear» resets the filters.'),
             'more': T('مثلاً: AMLODIPINE بتركيز 5 والوحدة mg وشكل أقراص، عشان تلاقي المكافئ بالظبط.\n'
                       '• تقدر كمان تختار شكل أو تصنيف من غير مادة.',
                       'For example: AMLODIPINE at 5 mg as tablets, to find the exact equivalent.\n'
                       '• You can also pick a form or class without a molecule.')},
            {'target': 'chronic-ingredient-search-source', 'text': T('المصدر: «معتمد فقط» للنتائج التي راجعها صيدلي؛ «مقترح» لم يُراجَع بعد.',
                                              'Source: «Approved only» for pharmacist-reviewed results; «Suggested» is not reviewed yet.'),
             'more': T('الاختيارات: «معتمد + مقترح»، «معتمد فقط»، «مقترح فقط».\n'
                       '• لأي كلام مع العميل استخدم «معتمد فقط» — سلامة المريض أولاً.',
                       'Options: "Approved + suggested", "Approved only", "Suggested only".\n'
                       '• For anything you tell a customer, use "Approved only" — patient safety first.')},
            {'target': 'chronic-ingredient-search-results', 'text': T('النتائج بعد كتابة مادة أو اختيار شكل/تصنيف: الصنف، المادة، التركيز، الشكل، والمصدر.',
                                              'Results after entering a molecule or picking a form/class: item, molecule, strength, form and source.'),
             'more': T('عمود «المصدر» بيقولك النتيجة معتمدة ولا مقترحة.\n'
                       '• «السابق» و«التالي» تحت للصفحات.\n'
                       '• النتيجة مش معناها إن الصنف متوفر — اتأكد من المخزون.',
                       'The "Source" column tells you whether a result is approved or suggested.\n'
                       '• "Previous" and "Next" at the bottom for pages.\n'
                       '• A result does not mean the item is in stock — check stock.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
