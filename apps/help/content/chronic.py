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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
    },
]
