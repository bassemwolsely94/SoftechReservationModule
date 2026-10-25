from . import T

CHANGE_NOTE = T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour')

MODULE = {
    'key': 'catalog', 'group': 'inventory', 'icon': '💊',
    'title': T('المنتجات والمخزون', 'Products & stock'),
    'summary': T(
        'كتالوج كل الأصناف (أكثر من 37 ألف صنف) المتزامن من SOFTECH مع السعر والتوافر بالفروع، وملف شامل لكل صنف، '
        'ومحتوى تسويقي وصور، ومؤشرات المخزون (نواقص، فائض، راكد، رأس المال)، وذكاء الكتالوج (مجموعات المتغيرات، الباقات، ما يُشترى معاً، إثراء البيانات بالذكاء الاصطناعي). '
        'تنبيه: الاسم العلمي في SOFTECH غير موثوق لكثير من الأصناف — لا تعتمد عليه وحده في البدائل.',
        'The catalog of all items (over 37 thousand) synced from SOFTECH with price and availability by branch, a full file per item, '
        'marketing content and images, stock indicators (shortage, overstock, dead stock, capital), and catalog intelligence (variant groups, bundles, '
        'frequently bought together, AI data enrichment). Note: the SOFTECH scientific name is unreliable for many items — never rely on it alone for alternatives.'),
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول المنتجات والمخزون', 'A tour of the Products & stock module'),
            'summary': T('من البحث عن صنف في الكتالوج، لصحة المخزون في «لوحة المخزون»، لتنظيم الكتالوج في «ذكاء الكتالوج» و«التوصيات الذكية»، '
                         'وفي الآخر نفتح صفحة صنف وملفه الشامل — وإزاي كل شاشة بتغذي التانية.',
                         'From searching an item in the catalog, to stock health in the "Inventory dashboard", to organising the catalog in "Catalog intelligence" '
                         'and "Smart recommendations", and finally opening an item page and its full file — and how each screen feeds the next.'),
            'roles': ['admin', 'pharmacist', 'purchasing'],
            'steps': [
                {'target': 'nav-products', 'nav': '/products',
                 'text': T('نبدأ من «المنتجات» في القائمة — كتالوج كل الأصناف.',
                           'Start at "Products" in the menu — the catalog of every item.'),
                 'more': T('الكتالوج بيتحدّث من SOFTECH: الاسم والكود والباركود والسعر والتوافر في الفروع.\n'
                           '• ده المكان اللي بتبدأ منه أي سؤال عن صنف: موجود؟ بكام؟ في أنهي فرع؟\n'
                           '• الشاشة دي للقراءة والبحث — مفيش فيها أي تعديل على SOFTECH.',
                           'The catalog is updated from SOFTECH: name, code, barcode, price and availability by branch.\n'
                           '• This is where any question about an item starts: do we have it? at what price? in which branch?\n'
                           '• This screen is for search and reading — nothing here changes SOFTECH.')},
                {'target': 'catalog-products-search', 'route': '/products',
                 'text': T('اكتب الاسم أو الكود أو الباركود أو المادة الفعالة.',
                           'Type the name, code, barcode or active ingredient.'),
                 'more': T('النتائج بتظهر وانت بتكتب، من غير ما تضغط Enter. في تبويب «الكتالوج» لازم تكتب حاجة الأول عشان تظهر نتائج.\n'
                           '• جنبها 📷 لمسح الباركود بالكاميرا.\n'
                           '• افتكر: الاسم العلمي في SOFTECH مش دقيق لكل الأصناف، فمتعتمدش عليه لوحده في اختيار بديل.',
                           'Results appear as you type, no Enter needed. On the "Catalog" tab you must type something first to see results.\n'
                           '• Next to it, 📷 scans a barcode with the camera.\n'
                           '• Remember: the SOFTECH scientific name is not accurate for every item, so do not rely on it alone to pick an alternative.')},
                {'target': 'catalog-products-filters', 'route': '/products',
                 'text': T('«⚙ فلتر» يضيّق النتائج بالتوافر والتصنيف والشكل والتأمين.',
                           '"⚙ Filter" narrows results by availability, class, form and insurance.'),
                 'more': T('بيفتح لوحة جانبية: التوافر، التصنيف العلاجي، الشكل الصيدلي، التأمين الصحي، وخيارات زي ثلاجة ووصفة ومزمن وسريع التداول ولديه صورة.\n'
                           '• الرقم الأصفر على الزر = عدد الفلاتر الشغالة.\n'
                           '• زر «⬇ Excel» جنبه بيصدّر النتائج الحالية بنفس البحث والفلاتر.',
                           'Opens a side panel: availability, therapeutic class, dosage form, health insurance, and options like fridge, prescription, chronic, fast-moving and has image.\n'
                           '• The yellow number on the button = how many filters are on.\n'
                           '• The "⬇ Excel" button next to it exports the current results with the same search and filters.')},
                {'target': 'catalog-products-tabs', 'route': '/products',
                 'text': T('التبويبات: الكتالوج، سريع التداول، مخزون منخفض، الباقات، آخر تحديث.',
                           'Tabs: catalog, fast moving, low stock, bundles, recently updated.'),
                 'more': T('• «سريع التداول»: الأصناف اللي لازم ماتنقصش أبداً.\n'
                           '• «مخزون منخفض»: الأصناف اللي توافرها «كميات محدودة» — راجعها لتحويل أو طلب.\n'
                           '• «الباقات»: الباقات النشطة المتعرّفة في «ذكاء الكتالوج».\n'
                           '• «آخر تحديث»: آخر الأصناف اللي اتحدّثت من SOFTECH.',
                           '• "Fast moving": items that must never run out.\n'
                           '• "Low stock": items whose availability is "limited quantities" — review them for a transfer or an order.\n'
                           '• "Bundles": the active bundles set up in "Catalog intelligence".\n'
                           '• "Recently updated": the latest items updated from SOFTECH.')},
                {'target': 'nav-inventory', 'nav': '/inventory',
                 'text': T('بعدها «لوحة المخزون»: صحة المخزون في الشبكة كلها.',
                           'Next, the "Inventory dashboard": stock health across the whole network.'),
                 'more': T('الكتالوج بيقولك الصنف موجود ولا لأ؛ لوحة المخزون بتقولك فين المشكلة: نواقص، فائض، راكد، ورأس مال محبوس.\n'
                           '• أرقامها جاية من آخر تشغيل لمحرك الطلب في المشتريات.',
                           'The catalog tells you whether an item is there; the inventory dashboard tells you where the problem is: shortages, overstock, dead stock and tied-up capital.\n'
                           '• Its numbers come from the last run of the purchasing demand engine.')},
                {'target': 'catalog-inventory-kpis', 'route': '/inventory',
                 'text': T('المؤشرات: إجمالي الأصناف، الناقصة، الفائضة، والراكدة بلا مبيعات.',
                           'Indicators: total items, short, overstocked, and dead stock with no sales.'),
                 'more': T('تحت «أصناف ناقصة» قيمة الفجوة، وتحت «أصناف فائضة» قيمة الفائض بالجنيه.\n'
                           '• لو فيه نواقص بيظهر شريط أحمر بعددها.\n'
                           '• الأرقام بتتغير حسب فلاتر الفرع ونوع الدواء وفئة ABC اللي فوق.',
                           'Under "Short items" is the gap value, and under "Overstocked items" the excess value in pounds.\n'
                           '• If there are shortages, a red banner shows how many.\n'
                           '• The numbers follow the branch, medicine type and ABC filters above.')},
                {'target': 'catalog-inventory-tabs', 'route': '/inventory',
                 'text': T('النواقص والفائض والراكد بالتفصيل، وبالفرع وبنوع الدواء ورأس المال.',
                           'Shortages, overstock and dead stock in detail, plus by branch, by medicine type and capital.'),
                 'more': T('الفكرة: الفائض في فرع ممكن يغطي النقص في فرع تاني بتحويل بدل الشراء.\n'
                           '• التنفيذ نفسه بيتم من التحويلات أو المشتريات — اللوحة دي للمتابعة والقرار بس.',
                           'The idea: overstock in one branch can cover a shortage in another by transfer instead of buying.\n'
                           '• The action itself happens in transfers or purchasing — this board is for monitoring and deciding only.')},
                {'target': 'nav-catalog-intelligence', 'nav': '/catalog-intelligence',
                 'text': T('«ذكاء الكتالوج»: تنظيم الأصناف وتحسين بياناتها.',
                           '"Catalog intelligence": organise items and improve their data.'),
                 'more': T('هنا بتربط الأصناف اللي هي نفس المنتج بأشكال مختلفة، وتعمل باقات، وتشوف اللي بيتشترى مع بعض، وتحسّن جودة البيانات.\n'
                           '• الباقات اللي بتعملها هنا هي اللي بتظهر في تبويب «الباقات» في الكتالوج.',
                           'Here you link items that are the same product in different forms, create bundles, see what is bought together, and improve data quality.\n'
                           '• The bundles you create here are what shows in the catalog\'s "Bundles" tab.')},
                {'target': 'catalog-intelligence-tabs', 'route': '/catalog-intelligence',
                 'text': T('مجموعات المتغيرات، الباقات، يُشترى معه عادةً، وإثراء الكتالوج.',
                           'Variant groups, bundles, frequently bought together, and catalog enrichment.'),
                 'more': T('• «مجموعات المتغيرات» و«الباقات» بتتعدّل يدوياً.\n'
                           '• «يُشترى معه عادةً» للقراءة — بيحسبه محرك التوصيات.\n'
                           '• «إثراء الكتالوج»: اقتراحات الذكاء الاصطناعي بتتراجع قبل النشر، والبدائل الدوائية عمرها ما بتتطبّق تلقائياً.',
                           '• "Variant groups" and "Bundles" are edited by hand.\n'
                           '• "Frequently bought together" is read-only — computed by the recommendation engine.\n'
                           '• "Catalog enrichment": AI suggestions are reviewed before publishing, and drug alternatives are never applied automatically.')},
                {'target': 'nav-recommendations', 'nav': '/recommendations',
                 'text': T('«التوصيات الذكية»: الأصناف اللي بتتشترى مع بعض وتوصيات كل عميل.',
                           '"Smart recommendations": items bought together and per-customer suggestions.'),
                 'more': T('المحرك بيحلل الفواتير ويطلع أزواج الأصناف اللي بتتشترى سوا، ويقترح لكل عميل أصناف حسب مشترياته.\n'
                           '• فيه فلتر سلامة بيستبعد اللي يتعارض مع أدويته المزمنة — ومع ذلك أي اقتراح لمريض بيرجع لحكم الصيدلي.',
                           'The engine analyses invoices to find item pairs bought together, and suggests items to each customer from their purchases.\n'
                           '• A safety filter excludes anything that conflicts with their chronic medicines — still, any suggestion to a patient is the pharmacist\'s call.')},
                {'target': 'catalog-recommendations-engine-status', 'route': '/recommendations',
                 'text': T('حالة آخر تشغيل للمحرك ونتايجه.',
                           'The engine\'s last run status and results.'),
                 'more': T('بتشوف آخر تشغيل نجح ولا فشل وامتى، ولو نجح: عدد الاقترانات والفواتير والعملاء.\n'
                           '• «▶ تشغيل المحرك» بيظهر للمدير والمشرف بس، ومينفعش تشغيلين في نفس الوقت.',
                           'You see whether the last run succeeded or failed and when; on success: the number of pairs, invoices and customers.\n'
                           '• "▶ Run engine" shows only for admins and supervisors, and two runs cannot happen at once.')},
                {'target': 'nav-products', 'nav': '/products',
                 'text': T('نرجع للكتالوج نفتح صنف بعينه.',
                           'Back to the catalog to open one item.'),
                 'more': T('كل اللي فات بيتجمّع في صفحة الصنف: سعره وتوافره وبدائله والطلب المفتوح عليه.\n'
                           '• في الخطوة الجاية ابحث عن صنف وافتحه.',
                           'Everything so far comes together on the item page: its price, availability, alternatives and open demand.\n'
                           '• In the next step, search for an item and open it.')},
                {'target': 'catalog-products-results', 'route': '/products', 'wait': '/products/:id',
                 'text': T('ابحث عن صنف واضغط عليه عشان تفتح صفحته. لو مش عايز اضغط «إنهاء».',
                           'Search for an item and click it to open its page. If you prefer not to, press "End".'),
                 'more': T('في النتايج: الضغط على الصنف يفتح صفحته، وزر المقارنة يضيفه للمقارنة (لحد 3 أصناف) في شريط تحت الشاشة.\n'
                           '• تقدر تبدّل بين عرض الشبكة ⊞ والقائمة ≡.',
                           'In the results: clicking an item opens its page, and the compare button adds it to the comparison (up to 3 items) in a bar at the bottom.\n'
                           '• You can switch between grid ⊞ and list ≡ view.')},
                {'target': 'catalog-product-summary', 'route': '/products/:id',
                 'text': T('ملخص الصنف: التوافر والتصنيف والكود والباركود.',
                           'The item summary: availability, class, code and barcode.'),
                 'more': T('شارة التوافر بتقولك: متاح، كميات محدودة، أو غير متاح — من غير كميات.\n'
                           '• شارات «يحتاج وصفة طبية Rx» و«دواء مزمن» و«سريع التداول» لو تنطبق، وتنبيه الثلاجة لو الصنف بيتحفظ بارد.',
                           'The availability badge tells you: available, limited quantities, or unavailable — without quantities.\n'
                           '• "Prescription Rx", "Chronic" and "FMI" badges when they apply, and a fridge note when the item is kept cold.')},
                {'target': 'catalog-product-tabs', 'route': '/products/:id',
                 'text': T('تبويبات الصنف: التعليمات، التوافر بالفروع، المشابهة والمرتبطة، والطلب المفتوح.',
                           'Item tabs: instructions, branch availability, similar and related, and open demand.'),
                 'more': T('• «التوافر بالفروع» يقولك أقرب فرع عنده الصنف.\n'
                           '• «الطلب المفتوح» بيوريك طلبات العملاء والنواقص المسجّلة عليه.\n'
                           '• المنتجات المشابهة والمرتبطة للمساعدة بس — أي بديل لمريض محتاج قرار صيدلي.',
                           '• "Branch availability" tells you the nearest branch that has the item.\n'
                           '• "Open demand" shows customer requests and recorded shortages for it.\n'
                           '• Similar and related products are a help only — any alternative for a patient needs a pharmacist\'s decision.')},
                {'target': 'catalog-product-intel', 'route': '/products/:id',
                 'text': T('«🔬 ملف الصنف الشامل» فيه كل بيانات الصنف من كل الموديولات.',
                           '"🔬 Full item profile" holds all of the item\'s data from every module.'),
                 'more': T('بيفتح صفحة فيها بيانات SOFTECH (للقراءة)، والإثراء، والمواد الفعّالة، ومؤشرات الطلب، وتاريخ الشراء من الموردين.\n'
                           '• ربط المواد الفعّالة هناك هو المصدر الموثوق للبدائل، مش الاسم العلمي.',
                           'Opens a page with SOFTECH data (read-only), enrichment, active ingredients, demand indicators and supplier purchase history.\n'
                           '• The active-ingredient links there are the reliable source for alternatives, not the scientific name.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'catalog.products',
        'routes': ['/products'],
        'title': T('كتالوج المنتجات', 'Product catalog'),
        'summary': T('بحث في كل الأصناف بالاسم أو الكود أو الباركود أو المادة الفعالة (أو بكاميرا الموبايل)، مع فلاتر (التوافر، التصنيف العلاجي، الشكل، التأمين، ثلاجة، مزمن، سريع التداول، وصفة)، ومقارنة حتى 3 أصناف، وتصدير قائمة الأسعار.',
                     'Search all items by name, code, barcode or active ingredient (or the phone camera), with filters (availability, therapeutic class, form, insurance, fridge, chronic, fast-moving, prescription), compare up to 3 items, and export the price list.'),
        'audience': T('كل الموظفين.', 'Every employee.'),
        'tabs': [
            {'key': 'catalog', 'title': T('الكتالوج', 'Catalog'), 'body': T('كل الأصناف مع البحث والفلاتر والترتيب (الأكثر شهرة، السعر، أبجدي…).', 'All items with search, filters and sorting (most popular, price, A–Z…).')},
            {'key': 'fmi', 'title': T('سريع التداول', 'Fast moving'), 'body': T('الأصناف سريعة الحركة (FMI) — يجب ألا تنقص أبداً.', 'Fast-moving items (FMI) — they must never run out.')},
            {'key': 'low_stock', 'title': T('مخزون منخفض', 'Low stock'), 'body': T('أصناف قلّ مخزونها — راجعها للتحويل أو الطلب.', 'Items running low — review them for a transfer or an order.')},
            {'key': 'bundles', 'title': T('الباقات', 'Bundles'), 'body': T('الباقات النشطة (مجموعة أصناف بخصم) المُعدّة في ذكاء الكتالوج.', 'Active bundles (a set of items at a discount) set up in catalog intelligence.')},
            {'key': 'recent', 'title': T('آخر تحديث', 'Recently updated'), 'body': T('أحدث الأصناف تحديثاً من SOFTECH (أسعار أو بيانات جديدة).', 'The items most recently updated from SOFTECH (new prices or data).')},
        ],
        'steps': [
            T('ابحث أو امسح الباركود، واضغط الصنف لفتح صفحته.', 'Search or scan, and click an item to open its page.'),
            T('«إضافة للمقارنة» على حتى 3 أصناف لمقارنة السعر والهامش والتصنيف والمورد.', '"Add to compare" on up to 3 items to compare price, margin, class and supplier.'),
            T('«تصدير Excel» يصدّر قائمة الأسعار للنتائج الحالية.', '"Export Excel" exports the price list for the current results.'),
        ],
        'tips': [T('الهامش = سعر العبوة − سعر التكلفة؛ يظهر حسب صلاحيتك.', 'Margin = pack price − cost; shown according to your permissions.')],
        'related': ['catalog.product', 'catalog.inventory', 'catalog.mobile_items'],
        'tour': [
            {'target': 'catalog-products-search', 'text': T('ابحث بالاسم أو الكود أو الباركود أو المادة الفعالة.',
                                              'Search by name, code, barcode or active ingredient.'),
             'more': T('النتائج بتظهر وانت بتكتب من غير ما تضغط Enter. في تبويب «الكتالوج» لازم تكتب حاجة الأول عشان تظهر نتائج (الكتالوج كبير جداً).\n'
                       '• «×» جوه الخانة بيمسح البحث.\n'
                       '• الاسم العلمي في SOFTECH مش دقيق لكل الأصناف — متعتمدش عليه لوحده في البدائل.',
                       'Results appear as you type, no Enter needed. On the "Catalog" tab you must type something first to see results (the catalog is very large).\n'
                       '• The "×" inside the box clears the search.\n'
                       '• The SOFTECH scientific name is not accurate for every item — do not rely on it alone for alternatives.')},
            {'target': 'catalog-products-scan', 'text': T('📷 امسح الباركود بالكاميرا.',
                                              '📷 Scan a barcode with the camera.'),
             'more': T('بيفتح نافذة الكاميرا؛ وجّهها على الباركود. لو الصنف اتعرف بتفتح صفحته على طول، ولو لأ الباركود بيتحط في خانة البحث.\n'
                       '• لو المتصفح مش سامح بالكاميرا، اكتب الباركود يدوي في «أدخل الباركود يدوياً».',
                       'Opens the camera window; point it at the barcode. If the item is recognised its page opens directly; if not, the barcode goes into the search box.\n'
                       '• If the browser does not allow the camera, type the barcode in "Enter barcode manually".')},
            {'target': 'catalog-products-filters', 'text': T('«⚙ فلتر» للتوافر والتصنيف والشكل والتأمين.',
                                              '"⚙ Filter" by availability, class, form and insurance.'),
             'more': T('بيفتح لوحة «تصفية النتائج» على الجنب: التوافر، التصنيف العلاجي، الشكل الصيدلي، التأمين الصحي، وخيارات إضافية (ثلاجة، وصفة Rx، مزمن، FMI، لديه صورة).\n'
                       '• الرقم على الزر = عدد الفلاتر الشغالة.\n'
                       '• «⬇ Excel» جنبه بيصدّر النتائج الحالية بنفس البحث والفلاتر.',
                       'Opens the "Filter results" side panel: availability, therapeutic class, dosage form, health insurance, and extra options (fridge, Rx, chronic, FMI, has image).\n'
                       '• The number on the button = how many filters are on.\n'
                       '• "⬇ Excel" next to it exports the current results with the same search and filters.')},
            {'target': 'catalog-products-sort', 'text': T('الترتيب: الأكثر شهرة، آخر مزامنة، السعر، أو أبجدي.',
                                              'Sort: most popular, last synced, price, or A–Z.'),
             'more': T('بيغيّر ترتيب النتائج الحالية ويرجعك لأول صفحة.\n'
                       '• «السعر: الأقل أولاً» مفيد لما العميل يسأل عن أرخص اختيار.\n'
                       '• في تبويب «آخر تحديث» الترتيب دايماً الأحدث أولاً.',
                       'Changes the order of the current results and takes you back to page one.\n'
                       '• "Price: low first" helps when a customer asks for the cheapest option.\n'
                       '• On the "Recently updated" tab the order is always newest first.')},
            {'target': 'catalog-products-tabs', 'text': T('التبويبات: الكتالوج، سريع التداول، مخزون منخفض، الباقات، آخر تحديث.',
                                              'Tabs: catalog, fast moving, low stock, bundles, recently updated.'),
             'more': T('• «سريع التداول»: الأصناف اللي لازم ماتنقصش.\n'
                       '• «مخزون منخفض»: اللي توافرها «كميات محدودة» — راجعها لتحويل أو طلب.\n'
                       '• «الباقات»: الباقات النشطة من «ذكاء الكتالوج» — اضغط صنف فيها يفتح صفحته.\n'
                       '• «آخر تحديث»: آخر ما اتحدّث من SOFTECH.',
                       '• "Fast moving": items that must not run out.\n'
                       '• "Low stock": items with "limited quantities" — review them for a transfer or an order.\n'
                       '• "Bundles": active bundles from "Catalog intelligence" — click an item in one to open its page.\n'
                       '• "Recently updated": what was last updated from SOFTECH.')},
            {'target': 'catalog-products-results', 'text': T('النتائج — اضغط أي صنف لصفحته، أو أضفه للمقارنة.',
                                              'The results — click any item for its page, or add it to compare.'),
             'more': T('كل صنف بيظهر بسعره وشارة توافره (متاح / كميات محدودة / غير متاح).\n'
                       '• زر المقارنة يضيف الصنف لشريط المقارنة تحت (لحد 3 أصناف): السعر والهامش والتصنيف والمورد والتوافر.\n'
                       '• ⊞ و≡ فوق بيبدّلوا بين عرض الشبكة والقائمة.',
                       'Each item shows its price and availability badge (available / limited / unavailable).\n'
                       '• The compare button adds it to the comparison bar at the bottom (up to 3 items): price, margin, class, supplier and availability.\n'
                       '• ⊞ and ≡ at the top switch between grid and list view.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'catalog.product',
        'routes': ['/products/:id'],
        'title': T('صفحة المنتج', 'Product page'),
        'summary': T('ملف الصنف للعرض والبيع: الصور، السعر، الوصف، التعليمات، الخصائص، التوافر بالفروع (متاح / محدود / غير متاح فقط بدون كميات)، البدائل والمرتبطات، والطلب المفتوح عليه.',
                     'The item file for viewing and selling: images, price, description, instructions, attributes, availability by branch (available / limited / unavailable only, no quantities), alternatives and related items, and open demand.'),
        'audience': T('كل الموظفين.', 'Every employee.'),
        'tabs': [
            {'key': 'info', 'title': T('نظرة عامة', 'Overview'), 'body': T('الوصف، الفوائد، معلومات سريعة (الاسم العلمي، المادة الفعالة، الشركة، التركيز، العبوة)، والأسئلة الشائعة.', 'Description, benefits, quick facts (scientific name, active ingredient, company, strength, pack) and FAQ.')},
            {'key': 'instructions', 'title': T('التعليمات والتخزين', 'Instructions & storage'), 'body': T('طريقة الاستخدام، شروط ودرجة حرارة التخزين، مدة الصلاحية، موانع الاستخدام والتحذيرات.', 'How to use, storage conditions and temperature, shelf life, contraindications and warnings.')},
            {'key': 'attributes', 'title': T('الخصائص', 'Attributes'), 'body': T('التصنيف، المورد، البلد، التركيز، النكهة، اللون، الحجم، الباركود، كود SOFTECH، والوصفة الطبية.', 'Class, supplier, country, strength, flavour, colour, size, barcode, SOFTECH code and prescription status.')},
            {'key': 'availability', 'title': T('التوافر بالفروع', 'Branch availability'), 'body': T('حالة التوافر في كل فرع، تُحدَّث تلقائياً من SOFTECH.', 'Availability at each branch, updated automatically from SOFTECH.')},
            {'key': 'similar', 'title': T('منتجات مشابهة', 'Similar products'), 'body': T('أصناف من نفس التصنيف.', 'Items in the same class.')},
            {'key': 'related', 'title': T('منتجات مرتبطة', 'Related products'), 'body': T('موصى به، يُشترى معاً، بديل، مكمل، حزمة البداية.', 'Recommended, bought together, alternative, complementary, starter pack.')},
            {'key': 'demand', 'title': T('الطلب المفتوح', 'Open demand'), 'body': T('طلبات العملاء المفتوحة والنواقص المسجّلة على هذا الصنف.', 'Open customer requests and recorded shortages for this item.')},
        ],
        'steps': [T('«مشاركة واتساب» ينسخ وصفاً جاهزاً للصنف لإرساله للعميل. «ملف الصنف الشامل» يفتح ذكاء الصنف.', '"Share on WhatsApp" copies a ready description to send to the customer. "Full item file" opens item intelligence.')],
        'related': ['catalog.products', 'catalog.intel', 'catalog.content_admin'],
        'tour': [
            {'target': 'catalog-product-summary', 'text': T('ملخص الصنف والتوافر.',
                                              'The item summary and availability.'),
             'more': T('شارة التوافر العام (متاح / كميات محدودة / غير متاح)، والاسم بالعربي والإنجليزي، والتصنيف، وشارات «دواء مزمن» و«سريع التداول FMI» و«يحتاج وصفة طبية Rx».\n'
                       '• تحتها كود SOFTECH والباركود، وتنبيه الثلاجة ومنطقة التجميع لو موجودين.',
                       'The overall availability badge (available / limited quantities / unavailable), the Arabic and English name, the class, and the "Chronic", "FMI" and "Prescription Rx" badges.\n'
                       '• Below: the SOFTECH code and barcode, and the fridge note and pick zone when present.')},
            {'target': 'catalog-product-price', 'text': T('سعر العبوة والوحدة.',
                                              'Pack and unit price.'),
             'more': T('السعر جاي من SOFTECH ومش بيتعدّل من هنا.\n'
                       '• لو «هامش الربح» ظاهر: أخضر = 30% أو أكتر، أصفر = من 15%، أحمر = أقل من كده.',
                       'The price comes from SOFTECH and is not edited here.\n'
                       '• When "Margin" is shown: green = 30% or more, amber = from 15%, red = below that.')},
            {'target': 'catalog-product-tabs', 'text': T('التبويبات: نظرة عامة، التعليمات والتخزين، الخصائص، التوافر بالفروع، المشابهة، المرتبطة، والطلب المفتوح.',
                                              'Tabs: overview, instructions and storage, attributes, branch availability, similar, related, and open demand.'),
             'more': T('• «التعليمات والتخزين» فيها الموانع والتحذيرات — راجعها قبل ما تنصح عميل.\n'
                       '• «التوافر بالفروع» بيقولك أنهي فرع عنده الصنف (من غير كميات).\n'
                       '• «الطلب المفتوح»: طلبات العملاء والنواقص المسجّلة على الصنف.',
                       '• "Instructions & storage" holds contraindications and warnings — check them before advising a customer.\n'
                       '• "Branch availability" tells you which branch has the item (without quantities).\n'
                       '• "Open demand": customer requests and recorded shortages for the item.')},
            {'target': 'catalog-product-content', 'text': T('محتوى التبويب المختار.',
                                              'The selected tab\'s content.'),
             'more': T('بيتغيّر حسب التبويب اللي فوق.\n'
                       '• البدائل والمنتجات المرتبطة هنا للمساعدة بس — أي بديل لروشتة مريض محتاج قرار صيدلي، والنظام مبيبدّلش أصناف لوحده.',
                       'It changes with the tab above.\n'
                       '• Alternatives and related products here are a help only — any alternative for a patient\'s prescription needs a pharmacist\'s decision; the system never swaps items on its own.')},
            {'target': 'catalog-product-share', 'text': T('«📤 مشاركة واتساب» ينسخ وصف الصنف جاهز للإرسال.',
                                              '"📤 Share on WhatsApp" copies a ready item description.'),
             'more': T('بيجهّز نص الصنف وينسخه، والزر يتحول لـ «تم النسخ» — الصقه في محادثة العميل.\n'
                       '• لو النسخ مانفعش بيفتح واتساب بالنص جاهز.\n'
                       '• النص ده جاي من محتوى الصنف اللي بيتعدّل في «إدارة المحتوى».',
                       'Prepares the item text and copies it; the button turns into "Copied" — paste it into the customer chat.\n'
                       '• If copying fails, WhatsApp opens with the text ready.\n'
                       '• The text comes from the item content edited in "Content admin".')},
            {'target': 'catalog-product-intel', 'text': T('«🔬 ملف الصنف الشامل» — كل بيانات الصنف في مكان واحد.',
                                              '"🔬 Full item profile" — all the item\'s data in one place.'),
             'more': T('بيفتح صفحة فيها بيانات SOFTECH والإثراء والمواد الفعّالة ومؤشرات الطلب وتاريخ الشراء.\n'
                       '• الزر الصغير «🖼 الصور» جنبه بيفتح إدارة محتوى وصور الصنف.',
                       'Opens a page with SOFTECH data, enrichment, active ingredients, demand indicators and purchase history.\n'
                       '• The small "🖼 Images" button next to it opens the item\'s content and image admin.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'catalog.content_admin',
        'routes': ['/products/:id/admin'],
        'title': T('إدارة محتوى المنتج', 'Product content admin'),
        'summary': T('تحرير ما يظهر عن الصنف: الصور والوسائط، النصوص، الخصائص الدوائية، وبيانات SEO.', 'Edit what is shown about the item: images and media, texts, pharmaceutical attributes and SEO data.'),
        'audience': T('مسؤولو المحتوى والمدير.', 'Content managers and admins.'),
        'tabs': [
            {'key': 'media', 'title': T('🖼 الصور والوسائط', '🖼 Images & media'), 'body': T('ارفع صوراً (JPG/PNG/WebP حتى 10MB) أو فيديو أو نشرة، اعتمدها، اجعل واحدة «رئيسية»، واكتب النص البديل.', 'Upload images (JPG/PNG/WebP up to 10MB), video or leaflets, approve them, set one as "main", and write alt text.')},
            {'key': 'content', 'title': T('📝 المحتوى والوصف', '📝 Content'), 'body': T('الاسم التجاري، الوصف المختصر (يظهر في البطاقة وواتساب) والتفصيلي، التعليمات، الموانع، الفوائد، الكلمات المفتاحية، والأسئلة الشائعة، مع معاينة رسالة واتساب.', 'Brand name, short description (shown on the card and WhatsApp) and full description, instructions, contraindications, benefits, keywords and FAQ, with a WhatsApp preview.')},
            {'key': 'attributes', 'title': T('⚗️ الخصائص الدوائية', '⚗️ Pharmaceutical attributes'), 'body': T('التركيز، العبوة، العدد، درجة الحرارة، مدة الصلاحية، الوصفة الطبية، والتحذيرات.', 'Strength, pack, count, temperature, shelf life, prescription and warnings.')},
            {'key': 'seo', 'title': T('🔍 SEO والروابط', '🔍 SEO & links'), 'body': T('رابط المنتج (Slug) وعناوين وأوصاف الصفحة بالعربي والإنجليزي ومعاينة نتيجة جوجل. تغيير الرابط يكسر الروابط القديمة.', 'The product slug, page titles and descriptions in Arabic and English, and a Google result preview. Changing the slug breaks old links.')},
        ],
        'steps': [T('عدّل ثم «حفظ التغييرات» — الشاشة تنبهك لو هناك تغييرات غير محفوظة.', 'Edit then "Save changes" — the screen warns you of unsaved changes.')],
        'related': ['catalog.product'],
        'tour': [
            {'target': 'catalog-content-admin-header', 'text': T('إدارة محتوى الصنف: اسمه وكود SOFTECH، ورابط «عرض صفحة المنتج».',
                                              'Item content admin: its name and SOFTECH code, plus the «View product page» link.'),
             'more': T('هنا بتعدّل اللي بيظهر عن الصنف في الكتالوج ورسالة الواتساب، مش بيانات SOFTECH نفسها.\n'
                       '• «عرض صفحة المنتج ↗» يوريك النتيجة زي ما الموظفين هيشوفوها.',
                       'Here you edit what is shown about the item in the catalog and the WhatsApp message, not the SOFTECH data itself.\n'
                       '• "View product page ↗" shows you the result as staff will see it.')},
            {'target': 'catalog-content-admin-tabs', 'text': T('التبويبات: الصور والوسائط، المحتوى والوصف، الخصائص الدوائية، وSEO والروابط.',
                                              'Tabs: images & media, content, pharmaceutical attributes, and SEO & links.'),
             'more': T('• «المحتوى والوصف»: الوصف المختصر هو اللي بيظهر في البطاقة وواتساب.\n'
                       '• «الخصائص الدوائية»: التركيز والتخزين والوصفة والتحذيرات — اكتبها بدقة لأنها بتظهر للموظفين.\n'
                       '• «SEO والروابط»: تغيير الرابط بيكسر الروابط القديمة.',
                       '• "Content": the short description is what shows on the card and WhatsApp.\n'
                       '• "Pharmaceutical attributes": strength, storage, prescription and warnings — write them accurately since staff see them.\n'
                       '• "SEO & links": changing the slug breaks old links.')},
            {'target': 'catalog-content-admin-panel', 'text': T('هنا تظهر حقول التبويب المختار للتعديل.',
                                              'The fields of the selected tab appear here for editing.'),
             'more': T('في تبويبات النصوص والخصائص وSEO التعديل مش بيتحفظ غير لما تضغط «حفظ التغييرات».\n'
                       '• في تبويب الصور كل إجراء (رفع، رئيسية، اعتماد، حذف) بيتحفظ على طول.',
                       'In the text, attributes and SEO tabs, edits are saved only when you press "Save changes".\n'
                       '• In the images tab, every action (upload, main, approve, delete) is saved immediately.')},
            {'target': 'catalog-content-admin-upload', 'text': T('في تبويب الصور: اضغط هنا لرفع صور JPG أو PNG أو WebP حتى 10MB.',
                                              'In the images tab: click here to upload JPG, PNG or WebP images up to 10MB.'),
             'more': T('تقدر تختار أكتر من صورة مرة واحدة، وكل صورة بتترفع لوحدها.\n'
                       '• الصورة الجديدة بتظهر في القائمة تحت، وتقدر تكتب لها «النص البديل» — بيتحفظ لما تخرج من الخانة.\n'
                       '• لو الرفع فشل بتظهر الرسالة بالأحمر.',
                       'You can pick several images at once; each one is uploaded on its own.\n'
                       '• The new image appears in the list below, and you can write its "alt text" — saved when you leave the box.\n'
                       '• If an upload fails, the message shows in red.')},
            {'target': 'catalog-content-admin-media-actions', 'text': T('لكل صورة مرفوعة: ★ لجعلها رئيسية، «اعتماد» أو «إلغاء الاعتماد»، و🗑 للحذف.',
                                              'For each uploaded image: ★ to make it main, «Approve» or «Unapprove», and 🗑 to delete.'),
             'more': T('• ★ يخلي الصورة هي «رئيسية» اللي بتظهر في الكتالوج.\n'
                       '• الصورة اللي مكتوب عليها «في انتظار الاعتماد» محتاجة «اعتماد».\n'
                       '• 🗑 بيسأل «حذف هذه الصورة نهائياً؟» — الحذف مايترجعش.',
                       '• ★ makes the image the "main" one shown in the catalog.\n'
                       '• An image marked "awaiting approval" needs "Approve".\n'
                       '• 🗑 asks "Delete this image permanently?" — deletion cannot be undone.')},
            {'target': 'catalog-content-admin-save', 'text': T('يظهر عند وجود تعديلات غير محفوظة — اضغط «حفظ التغييرات».',
                                              'Appears when there are unsaved edits — press «Save changes».'),
             'more': T('الشريط ده بيظهر تحت الشاشة أول ما تعدّل حاجة في تبويبات النصوص أو الخصائص أو SEO.\n'
                       '• لو خرجت من غير ما تحفظ، التعديلات بتضيع.\n'
                       '• بعد الحفظ التغيير بيظهر في صفحة المنتج ورسالة الواتساب.',
                       'This bar appears at the bottom as soon as you change something in the text, attributes or SEO tabs.\n'
                       '• If you leave without saving, the edits are lost.\n'
                       '• After saving, the change shows on the product page and in the WhatsApp message.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'catalog.intel',
        'routes': ['/products/:id/intel'],
        'title': T('ذكاء الصنف (الملف الشامل)', 'Item intelligence (full file)'),
        'summary': T('كل بيانات الصنف من كل الموديولات في مكان واحد: بيانات SOFTECH، الإثراء، المحتوى، المواد الفعالة وتصنيف المزمن، مؤشرات الطلب، تاريخ الشراء من الموردين، وما يُشترى معه.',
                     'All the item\'s data from every module in one place: SOFTECH data, enrichment, content, active ingredients and chronic tag, demand indicators, purchase history from suppliers, and what is bought with it.'),
        'audience': T('الصيادلة والمشتريات والمدير.', 'Pharmacists, purchasing and admins.'),
        'tabs': [
            {'key': 'softech', 'title': T('🔗 بيانات SOFTECH', '🔗 SOFTECH data'), 'body': T('حقول الصنف كما هي في SOFTECH (للقراءة فقط).', 'The item fields as in SOFTECH (read-only).')},
            {'key': 'enrichment', 'title': T('🧬 الإثراء والبيانات', '🧬 Enrichment'), 'body': T('بيانات سريرية وتصنيفية مكمّلة (قابلة للتعديل) مع نسبة اكتمال البيانات وحالة النشر.', 'Supplementary clinical and classification data (editable) with a completeness score and publish status.')},
            {'key': 'content', 'title': T('📝 المحتوى والخصائص', '📝 Content & attributes'), 'body': T('نفس محتوى وخصائص صفحة الإدارة، للتعديل السريع.', 'The same content and attributes as the admin page, for quick edits.')},
            {'key': 'clinical', 'title': T('💊 المواد الفعّالة', '💊 Active ingredients'), 'body': T('ربط المواد الفعّالة بالصنف وتصنيفه كمزمن — هذا مصدر البدائل الموثوق وليس الاسم العلمي.', 'Link active ingredients to the item and tag it chronic — this is the reliable source for alternatives, not the scientific name.')},
            {'key': 'purchasing', 'title': T('📊 مؤشرات الطلب', '📊 Demand indicators'), 'body': T('فئة ABC، معدلات الطلب، والمبيعات الضائعة (للقراءة).', 'ABC class, demand rates and lost sales (read-only).')},
            {'key': 'purchase_history', 'title': T('🧾 تاريخ الشراء', '🧾 Purchase history'), 'body': T('متوسط وأقل وأعلى سعر شراء لكل مورد وأكواد الموردين.', 'Average, min and max purchase price per supplier and supplier item codes.')},
            {'key': 'fbt', 'title': T('🔀 يُشترى معاً', '🔀 Bought together'), 'body': T('الأصناف التي تُشترى عادةً مع هذا الصنف.', 'Items usually bought with this one.')},
        ],
        'related': ['catalog.product', 'chronic.composition'],
        'tour': [
            {'target': 'catalog-intel-breadcrumb', 'text': T('مسار الصفحة: الكتالوج ← الصنف ← ملف الصنف الشامل؛ اضغط أي جزء للرجوع.',
                                              'Page path: catalog → item → full item file; click any part to go back.'),
             'more': T('«الكتالوج» يرجعك لقائمة الأصناف، واسم الصنف يرجعك لصفحة المنتج.\n'
                       '• الشريط ده ثابت فوق حتى وانت بتنزل في الصفحة.',
                       '"Catalog" takes you back to the item list, and the item name back to the product page.\n'
                       '• This bar stays fixed at the top even as you scroll.')},
            {'target': 'catalog-intel-sections', 'text': T('أقسام الملف: بيانات SOFTECH، الإثراء، المحتوى، المواد الفعّالة، مؤشرات الطلب، تاريخ الشراء، ويُشترى معاً.',
                                              'File sections: SOFTECH data, enrichment, content, active ingredients, demand, purchase history and bought together.'),
             'more': T('اضغط قسم يظهر محتواه على الشمال.\n'
                       '• «المواد الفعّالة» هو المكان اللي بتربط فيه المادة الفعّالة بالصنف وتصنّفه مزمن — ده مصدر البدائل الموثوق.\n'
                       '• «تاريخ الشراء» مفيد للمشتريات: أقل وأعلى سعر من كل مورد.',
                       'Click a section to show its content on the side.\n'
                       '• "Active ingredients" is where you link the ingredient to the item and tag it chronic — the reliable source for alternatives.\n'
                       '• "Purchase history" helps purchasing: the lowest and highest price from each supplier.')},
            {'target': 'catalog-intel-quick-meta', 'text': T('معلومات سريعة: فئة ABC للصنف ونسبة اكتمال بياناته.',
                                              'Quick info: the item\'s ABC class and its data completeness.'),
             'more': T('فئة ABC جاية من محرك الطلب: A = الأهم قيمةً.\n'
                       '• شريط «اكتمال البيانات»: أخضر من 70%، أصفر من 40%، أحمر أقل — كمّل الناقص من قسم «الإثراء».',
                       'The ABC class comes from the demand engine: A = the most valuable.\n'
                       '• The "Data completeness" bar: green from 70%, amber from 40%, red below — fill the gaps in the "Enrichment" section.')},
            {'target': 'catalog-intel-links', 'text': T('روابط سريعة إلى «صفحة المنتج» و«إدارة الصور».',
                                              'Quick links to the «Product page» and «Image management».'),
             'more': T('• «🔍 صفحة المنتج» يفتح الصفحة اللي الموظفين بيشوفوها.\n'
                       '• «🖼 إدارة الصور» يفتح إدارة محتوى الصنف على تبويب الصور.',
                       '• "🔍 Product page" opens the page staff see.\n'
                       '• "🖼 Image management" opens the item content admin on the images tab.')},
            {'target': 'catalog-intel-content', 'text': T('محتوى القسم المختار؛ بيانات SOFTECH ومؤشرات الطلب للقراءة فقط، وبعض الأقسام قابلة للتعديل.',
                                              'The selected section\'s content; SOFTECH data and demand indicators are read-only, some sections are editable.'),
             'more': T('عنوان كل قسم بيقولك: «للقراءة فقط» ولا «✎ قابل للتعديل».\n'
                       '• بيانات SOFTECH مابتتعدلش من هنا أبداً.\n'
                       '• في الأقسام القابلة للتعديل اضغط «حفظ التغييرات»، وهتظهر رسالة «تم الحفظ».',
                       'Each section title tells you: "read-only" or "✎ editable".\n'
                       '• SOFTECH data is never edited from here.\n'
                       '• In editable sections press "Save changes" and a "Saved" message appears.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'catalog.inventory',
        'routes': ['/inventory'],
        'title': T('لوحة المخزون', 'Inventory dashboard'),
        'summary': T('صحة المخزون من محرك الطلب: النواقص، الفائض، الراكد، والتوزيع بالفرع وبنوع الدواء، ورأس المال المحبوس. فلترة بالفرع ونوع الدواء وفئة ABC.',
                     'Stock health from the demand engine: shortages, overstock, dead stock, by branch and by medicine type, and tied-up capital. Filter by branch, medicine type and ABC class.'),
        'audience': T('المشتريات والصيادلة والمشرفون والجودة.', 'Purchasing, pharmacists, supervisors and quality.'),
        'tabs': [
            {'key': 'shortages', 'title': T('⚠️ النواقص', '⚠️ Shortages'), 'body': T('أصناف تحت حد الأمان مرتبة بالأولوية: الفجوة، المخزون، الأمان، متوسط الشهر، التغطية.', 'Items below safety stock, sorted by priority: gap, stock, safety, monthly average, coverage.')},
            {'key': 'overstock', 'title': T('📦 الفائض', '📦 Overstock'), 'body': T('أصناف أكثر من الحاجة مرتبة بقيمة الفائض — مرشحة للتحويل لفروع تحتاجها.', 'Items above need, sorted by excess value — candidates to transfer to branches that need them.')},
            {'key': 'dead_stock', 'title': T('💤 الراكد', '💤 Dead stock'), 'body': T('أصناف بلا مبيعات ولها مخزون — رأس مال راكد؛ راجعها للتحويل أو التخفيض أو الإيقاف.', 'Items with stock and no sales — idle capital; review for transfer, discount or delisting.')},
            {'key': 'by_branch', 'title': T('🏪 بالفرع', '🏪 By branch'), 'body': T('عدد وقيمة النواقص والفائض لكل فرع.', 'Count and value of shortages and overstock per branch.')},
            {'key': 'by_medicine', 'title': T('💊 بنوع الدواء', '💊 By medicine type'), 'body': T('النواقص والفائض والتغطية لكل نوع دواء.', 'Shortages, overstock and coverage per medicine type.')},
            {'key': 'investment', 'title': T('💰 رأس المال', '💰 Capital'), 'body': T('إجمالي رأس المال في المخزون، الراكد ونسبته، المرشحون للتصفية، والتوزيع حسب فئة ABC والفرع. يتطلب تشغيل محرك الطلب أولاً.', 'Total capital in stock, dead capital and its share, liquidation candidates, and distribution by ABC class and branch. Requires the demand engine to have run.')},
        ],
        'tips': [T('فئة A = الأصناف الأهم قيمةً؛ أي نقص فيها أولوية قصوى.', 'Class A = the most valuable items; any shortage there is top priority.')],
        'related': ['purchasing.engine', 'batches.main', 'transfers.new'],
        'tour': [
            {'target': 'catalog-inventory-header', 'text': T('«لوحة المخزون» مع تاريخ آخر تشغيل لمحرك الطلب وزر «تحديث».',
                                              '«Inventory dashboard» with the demand engine\'s last run date and a «Refresh» button.'),
             'more': T('كل الأرقام هنا جاية من آخر تشغيل لمحرك الطلب في المشتريات — شوف «آخر تشغيل» عشان تعرف البيانات قديمة ولا لأ.\n'
                       '• «تحديث» بيعيد تحميل الأرقام بس، مش بيشغّل المحرك من جديد.',
                       'All the numbers here come from the last run of the purchasing demand engine — check "Last run" to know how fresh the data is.\n'
                       '• "Refresh" only reloads the numbers; it does not run the engine again.')},
            {'target': 'catalog-inventory-abc-filter', 'text': T('فلترة حسب فئة ABC؛ «مسح» يلغي الاختيار.',
                                              'Filter by ABC class; «Clear» removes the selection.'),
             'more': T('تقدر تختار أكتر من فئة مرة واحدة؛ اضغط الفئة تاني عشان تشيلها.\n'
                       '• فوقها فلاتر الفرع ونوع الدواء، وتحتها فلاتر تشغيلية للأصناف.\n'
                       '• ابدأ بفئة A: أي نقص فيها أولوية قصوى.',
                       'You can pick several classes at once; click a class again to remove it.\n'
                       '• Above it are the branch and medicine-type filters, and below it operational item filters.\n'
                       '• Start with class A: any shortage there is top priority.')},
            {'target': 'catalog-inventory-kpis', 'text': T('المؤشرات: إجمالي الأصناف، الناقصة، الفائضة، والراكدة بلا مبيعات.',
                                              'Indicators: total items, short, overstocked, and dead stock with no sales.'),
             'more': T('تحت «أصناف ناقصة» قيمة الفجوة، وتحت «أصناف فائضة» قيمة الفائض بالجنيه.\n'
                       '• لو فيه نواقص بيظهر تحتها شريط أحمر: «صنف يحتاج إعادة توريد».\n'
                       '• الأرقام بتتبع الفلاتر اللي فوق.',
                       'Under "Short items" is the gap value, and under "Overstocked items" the excess value in pounds.\n'
                       '• If there are shortages, a red banner below says how many items need restocking.\n'
                       '• The numbers follow the filters above.')},
            {'target': 'catalog-inventory-tabs', 'text': T('التبويبات: النواقص، الفائض، الراكد، بالفرع، بنوع الدواء، ورأس المال.',
                                              'Tabs: shortages, overstock, dead stock, by branch, by medicine type, and capital.'),
             'more': T('الرقم الأحمر على «النواقص» = عدد الأصناف الناقصة.\n'
                       '• الفائض في فرع ممكن يغطي نقص في فرع تاني — نفّذ ده من التحويلات قبل ما تشتري.\n'
                       '• «رأس المال» محتاج تشغيل محرك الطلب الأول.',
                       'The red number on "Shortages" = the count of short items.\n'
                       '• Overstock in one branch can cover a shortage in another — do that through transfers before buying.\n'
                       '• "Capital" needs the demand engine to have run first.')},
            {'target': 'catalog-inventory-tab-content', 'text': T('بيانات التبويب المختار؛ في «النواقص» الأصناف مرتبة حسب الأولوية تنازلياً.',
                                              'The selected tab\'s data; in «Shortages» items are sorted by priority, highest first.'),
             'more': T('في «النواقص» لكل صنف: الكود ونوع الدواء والمورد والفجوة والمخزون وحد الأمان والتغطية.\n'
                       '• اضغط عنوان أي عمود لتغيير الترتيب.\n'
                       '• الشاشة دي للعرض — الطلب أو التحويل بيتم من المشتريات أو التحويلات.',
                       'In "Shortages" each item shows code, medicine type, supplier, gap, stock, safety level and coverage.\n'
                       '• Click any column header to change the sort.\n'
                       '• This screen is for viewing — ordering or transferring happens in purchasing or transfers.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'catalog.intelligence',
        'routes': ['/catalog-intelligence'],
        'title': T('ذكاء الكتالوج', 'Catalog intelligence'),
        'summary': T('تنظيم الكتالوج وتحسين جودة بياناته.', 'Organise the catalog and improve its data quality.'),
        'audience': T('الصيادلة والمشتريات والمدير.', 'Pharmacists, purchasing and admins.'),
        'tabs': [
            {'key': 'variants', 'title': T('🔗 مجموعات المتغيرات', '🔗 Variant groups'), 'body': T('تجميع الأصناف التي هي نفس المنتج بأشكال أو أحجام مختلفة (مثلاً أقراص وشراب) في مجموعة واحدة.', 'Group items that are the same product in different forms or sizes (e.g. tablets and syrup).')},
            {'key': 'bundles', 'title': T('📦 الباقات', '📦 Bundles'), 'body': T('إنشاء باقات أصناف مع خصم اختياري (نسبة أو مبلغ ثابت) وإظهارها أو إخفاؤها.', 'Create item bundles with an optional discount (percent or fixed) and show or hide them.')},
            {'key': 'fbt', 'title': T('🧩 يُشترى معه عادةً', '🧩 Frequently bought together'), 'body': T('أزواج الأصناف التي تُشترى معاً بالتكرار والثقة (للقراءة؛ يحسبها محرك التوصيات).', 'Item pairs bought together with frequency and confidence (read-only; computed by the recommendation engine).')},
            {'key': 'enrichment', 'title': T('🤖 إثراء الكتالوج', '🤖 Catalog enrichment'), 'body': T('تقرير جودة الكتالوج (مكتمل/ناقص/فارغ)، ودفعات إثراء بالذكاء الاصطناعي لنطاق (كل الكتالوج، تصنيف، مورد، أصناف) مع حد نشر تلقائي، ومراجعة الاقتراحات المعلّقة.', 'Catalog quality report (complete/partial/empty), and AI enrichment batches for a scope (whole catalog, class, supplier, items) with an auto-publish threshold, and review of pending suggestions.')},
        ],
        'tips': [T('اقتراحات الذكاء الاصطناعي تُراجع قبل النشر؛ لا تعتمد البدائل الدوائية تلقائياً.', 'AI suggestions are reviewed before publishing; drug alternatives are never applied automatically.')],
        'related': ['catalog.images', 'catalog.recommendations'],
        'tour': [
            {'target': 'catalog-intelligence-header', 'text': T('«ذكاء الكتالوج»: تنظيم الأصناف وتحسين جودة بيانات الكتالوج.',
                                              '«Catalog intelligence»: organise items and improve catalog data quality.'),
             'more': T('الشاشة دي بتنظم الكتالوج عندنا ومابتغيّرش بيانات SOFTECH.\n'
                       '• الباقات اللي بتتعمل هنا بتظهر في تبويب «الباقات» في كتالوج المنتجات.',
                       'This screen organises our catalog and does not change SOFTECH data.\n'
                       '• Bundles made here show in the "Bundles" tab of the product catalog.')},
            {'target': 'catalog-intelligence-tabs', 'text': T('التبويبات: مجموعات المتغيرات، الباقات، يُشترى معه عادةً، وإثراء الكتالوج.',
                                              'Tabs: variant groups, bundles, frequently bought together, and catalog enrichment.'),
             'more': T('• «مجموعات المتغيرات»: نفس المنتج بأشكال أو أحجام مختلفة.\n'
                       '• «الباقات»: مجموعة أصناف بخصم اختياري.\n'
                       '• «يُشترى معه عادةً»: للقراءة من محرك التوصيات.\n'
                       '• «إثراء الكتالوج»: اقتراحات بتتراجع قبل النشر، والبدائل الدوائية مابتتطبّقش تلقائياً.',
                       '• "Variant groups": the same product in different forms or sizes.\n'
                       '• "Bundles": a set of items with an optional discount.\n'
                       '• "Frequently bought together": read-only from the recommendation engine.\n'
                       '• "Catalog enrichment": suggestions are reviewed before publishing, and drug alternatives are never applied automatically.')},
            {'target': 'catalog-intelligence-variant-search', 'text': T('في المتغيرات: ابحث في المجموعات، و«+» لإنشاء مجموعة جديدة.',
                                              'In variants: search the groups, and «+» to create a new group.'),
             'more': T('«+» بيفتح نموذج صغير: «الاسم (إنجليزي)» إجباري و«الاسم (عربي)» اختياري، وبعدين «إنشاء».\n'
                       '• «إلغاء» يقفل النموذج من غير ما يعمل حاجة.',
                       '"+" opens a small form: "Name (English)" is required and "Name (Arabic)" optional, then "Create".\n'
                       '• "Cancel" closes the form without doing anything.')},
            {'target': 'catalog-intelligence-variant-list', 'text': T('قائمة المجموعات بعدد أصناف كل منها — اضغط مجموعة لعرضها.',
                                              'The group list with each group\'s item count — click a group to open it.'),
             'more': T('كل مجموعة بتظهر باسمها وعدد الأصناف اللي فيها.\n'
                       '• اللي تضغط عليها بتتلوّن وتفتح تفاصيلها على الجنب.',
                       'Each group shows its name and how many items it holds.\n'
                       '• The one you click is highlighted and its details open on the side.')},
            {'target': 'catalog-intelligence-variant-detail', 'text': T('تفاصيل المجموعة المختارة وأصنافها، مع «حذف» للمجموعة و✕ لإزالة صنف.',
                                              'The selected group\'s details and items, with «Delete» for the group and ✕ to remove an item.'),
             'more': T('كل صنف في المجموعة بيظهر بكوده وسعره.\n'
                       '• «🗑 حذف» بيسأل تأكيد قبل حذف المجموعة.\n'
                       '• ✕ بيشيل الصنف من المجموعة على طول من غير سؤال (الصنف نفسه مابيتمسحش من الكتالوج).',
                       'Each item in the group shows its code and price.\n'
                       '• "🗑 Delete" asks for confirmation before deleting the group.\n'
                       '• ✕ removes the item from the group straight away without asking (the item itself stays in the catalog).')},
            {'target': 'catalog-intelligence-variant-add', 'text': T('بعد اختيار مجموعة: ابحث باسم الصنف أو الكود أو الباركود لإضافته إليها.',
                                              'After selecting a group: search by item name, code or barcode to add it.'),
             'more': T('أول ما تختار الصنف من نتايج البحث بيتضاف للمجموعة على طول.\n'
                       '• حط في المجموعة بس الأصناف اللي هي فعلاً نفس المنتج — التجميع ده للتنظيم ومش معناه إنها بدائل لبعض في الصرف.',
                       'As soon as you pick the item from the search results it is added to the group.\n'
                       '• Only group items that really are the same product — this grouping is for organisation and does not make them interchangeable when dispensing.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'catalog.images',
        'routes': ['/image-enrichment'],
        'title': T('صور المنتجات', 'Product images'),
        'summary': T('البحث الآلي عن صور للأصناف ومراجعتها: النظام يجد صوراً مرشحة ويقيّم جودتها وتطابقها ووجود علامة مائية؛ ما فوق حد الثقة يُعتمد تلقائياً والباقي يُراجع يدوياً.',
                     'Automatic image search for items and its review: the system finds candidate images and scores quality, match and watermarks; above the confidence threshold they are auto-approved, the rest are reviewed manually.'),
        'audience': T('مسؤولو المحتوى والصيادلة والمشتريات.', 'Content managers, pharmacists and purchasing.'),
        'tabs': [
            {'key': 'dashboard', 'title': T('📊 لوحة التحكم', '📊 Dashboard'), 'body': T('نسبة التغطية بالصور، ما ينتظر المراجعة، والمهام الجارية والفاشلة.', 'Image coverage, pending review, and running and failed jobs.')},
            {'key': 'review', 'title': T('👁️ قائمة المراجعة', '👁️ Review queue'), 'body': T('قبول أو رفض الصور المرشحة. انتبه لمؤشر العلامة المائية — الصورة المشبوهة راجعها يدوياً.', 'Accept or reject candidate images. Watch the watermark indicator — review suspicious images manually.')},
            {'key': 'batch', 'title': T('🚀 إطلاق دفعة', '🚀 Launch batch'), 'body': T('بحث لدفعة أصناف بفلاتر (بلا صور، الأعلى مبيعاً، فئة، شركة، ABC) مع حد الموافقة التلقائية وتقدير التكلفة.', 'Search for a batch of items with filters (no image, top sellers, class, company, ABC) with an auto-approval threshold and a cost estimate.')},
            {'key': 'revise', 'title': T('🔄 مراجعة شاملة', '🔄 Revise all'), 'body': T('إعادة البحث حتى للأصناف التي لها صور، لاستبدال الصور الرديئة أو ذات العلامات المائية.', 'Search again even for items that have images, to replace poor or watermarked ones.')},
            {'key': 'history', 'title': T('📋 السجل', '📋 History'), 'body': T('سجل كل المهام.', 'The log of all jobs.')},
            {'key': 'gallery', 'title': T('🖼️ معرض المنتج', '🖼️ Product gallery'), 'body': T('صور صنف معيّن وإدارتها.', 'A specific item\'s images and their management.')},
            {'key': 'insights', 'title': T('🧠 نتائج التعلم', '🧠 Learning results'), 'body': T('ما تعلّمه النظام من قراراتك لتحسين الاختيار التلقائي.', 'What the system learned from your decisions to improve automatic selection.')},
        ],
        'related': ['catalog.content_admin'],
        'tour': [
            {'target': 'catalog-images-header', 'text': T('محرك اكتساب صور المنتجات: بحث آلي عن الصور مع تقييم ومراجعة بشرية.',
                                              'The product image engine: automatic image search with scoring and human review.'),
             'more': T('النظام بيدوّر على صور مرشحة لكل صنف ويقيّم جودتها وتطابقها ووجود علامة مائية.\n'
                       '• اللي فوق حد الثقة بيتعتمد تلقائي، والباقي بيستنى مراجعتك.\n'
                       '• قراراتك في المراجعة بتعلّم النظام يختار أحسن بعد كده.',
                       'The system searches candidate images for each item and scores quality, match and watermarks.\n'
                       '• Those above the confidence threshold are auto-approved; the rest wait for your review.\n'
                       '• Your review decisions teach the system to choose better next time.')},
            {'target': 'catalog-images-tabs', 'text': T('التبويبات: لوحة التحكم، قائمة المراجعة (بعدد المنتظر)، إطلاق دفعة، مراجعة شاملة، السجل، المعرض، ونتائج التعلم.',
                                              'Tabs: dashboard, review queue (with pending count), launch batch, revise all, history, gallery and learning results.'),
             'more': T('• الرقم الأحمر على «قائمة المراجعة» = الصور اللي مستنية قرارك.\n'
                       '• «إطلاق دفعة» بيبدأ بحث لمجموعة أصناف (زي اللي مالهاش صور) مع تقدير التكلفة قبل التشغيل.\n'
                       '• «مراجعة شاملة» بتدوّر تاني حتى للأصناف اللي ليها صور، عشان تبدّل الرديء.',
                       '• The red number on "Review queue" = images waiting for your decision.\n'
                       '• "Launch batch" starts a search for a set of items (such as those with no image) with a cost estimate before running.\n'
                       '• "Revise all" searches again even for items that have images, to replace poor ones.')},
            {'target': 'catalog-images-stats', 'text': T('أرقام سريعة: المنتجات، المعتمد بصورة، نسبة التغطية، المنتظر للمراجعة، الموافقة التلقائية، والمهام الجارية والفاشلة.',
                                              'Quick numbers: products, with approved image, coverage, pending review, auto-approved, and running and failed jobs.'),
             'more': T('«تنتظر المراجعة» لو كبير يبقى روح «قائمة المراجعة».\n'
                       '• «مهام فاشلة» لو فيها أرقام راجع «السجل» عشان تعرف السبب.\n'
                       '• المهام الجارية بتظهر بالتفصيل تحت شريط التغطية.',
                       'If "Pending review" is high, go to the "Review queue".\n'
                       '• If "Failed jobs" has numbers, check "History" for the reason.\n'
                       '• Running jobs are listed in detail under the coverage bar.')},
            {'target': 'catalog-images-coverage', 'text': T('شريط التغطية البصرية: كم منتجاً له صورة معتمدة من الإجمالي.',
                                              'The coverage bar: how many products have an approved image out of the total.'),
             'more': T('تحت الشريط مكتوب العدد بالظبط: كذا من كذا منتج.\n'
                       '• الصورة المعتمدة بس هي اللي بتتحسب — الصور المرشحة اللي لسه في المراجعة مش داخلة.',
                       'Under the bar is the exact count: so many out of so many products.\n'
                       '• Only approved images count — candidates still in review are not included.')},
            {'target': 'catalog-images-review-filters', 'text': T('في «قائمة المراجعة»: حدّد حد العلامة المائية وحد النقاط لتصفية الصور المعروضة.',
                                              'In «Review queue»: set the watermark and score limits to filter the shown images.'),
             'more': T('الفلتر ده بيغيّر اللي معروض بس، مابيقبلش ولا بيرفض حاجة.\n'
                       '• «حد العلامة المائية» يخفي الصور اللي احتمال العلامة فيها أعلى من النسبة، و«حد النقاط» يخفي الأقل من الدرجة.\n'
                       '• القبول والرفض بيتم من كارت كل صورة تحت، مجمّعة بالصنف.',
                       'This filter only changes what is shown; it does not accept or reject anything.\n'
                       '• "Watermark limit" hides images whose watermark likelihood is above the percentage, and "Score limit" hides those below the score.\n'
                       '• Accepting and rejecting happens on each image card below, grouped by item.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'catalog.recommendations',
        'routes': ['/recommendations'],
        'title': T('التوصيات الذكية', 'Smart recommendations'),
        'summary': T('محرك التوصيات: يحلل الفواتير ليجد الأصناف التي تُشترى معاً، ويقترح لكل عميل أصنافاً حسب سلوكه، مع فلتر سلامة يستبعد ما يتعارض مع أدويته المزمنة.',
                     'The recommendation engine: analyses invoices to find items bought together, and suggests items per customer by their behaviour, with a safety filter that excludes anything conflicting with their chronic medicines.'),
        'audience': T('الصيادلة والكول سنتر والمشتريات.', 'Pharmacists, call center and purchasing.'),
        'tabs': [
            {'key': 'fbt', 'title': T('🔗 اقترانات الأصناف', '🔗 Item pairs'), 'body': T('الأزواج مع الدعم والثقة والرفع (Lift) — الرفع الأعلى من 1 يعني ارتباطاً حقيقياً.', 'Pairs with support, confidence and lift — lift above 1 means a real association.')},
            {'key': 'customer', 'title': T('👤 توصيات العملاء', '👤 Customer recommendations'), 'body': T('ابحث عن عميل لترى توصياته الشخصية.', 'Search a customer to see their personal recommendations.')},
            {'key': 'history', 'title': T('🕓 سجل التشغيل', '🕓 Run history'), 'body': T('مرات تشغيل المحرك ونتائجها.', 'Engine runs and their results.')},
        ],
        'steps': [{'text': T('«تشغيل المحرك» مع فترة الرصد والحد الأدنى للدعم والثقة.', '"Run engine" with the look-back period and minimum support and confidence.'), 'roles': ['admin', 'supervisor']}],
        'related': ['catalog.intelligence'],
        'tour': [
            {'target': 'catalog-recommendations-header', 'text': T('«محرك التوصيات الذكية»: اقترانات الأصناف والتوصيات الشخصية للعملاء.',
                                              '«Smart recommendations engine»: item pairs and personal customer recommendations.'),
             'more': T('المحرك بيقرا الفواتير ويطلع الأصناف اللي بتتشترى مع بعض، ويقترح لكل عميل أصناف حسب مشترياته.\n'
                       '• فيه فلتر سلامة بيستبعد اللي يتعارض مع أدويته المزمنة — ومع ذلك أي اقتراح لمريض بيرجع لحكم الصيدلي.',
                       'The engine reads invoices, finds items bought together, and suggests items to each customer from their purchases.\n'
                       '• A safety filter excludes anything conflicting with their chronic medicines — still, any suggestion to a patient is the pharmacist\'s call.')},
            {'target': 'catalog-recommendations-engine-status', 'text': T('حالة آخر تشغيل للمحرك ووقته، مع عدد الاقترانات والفواتير والعملاء عند النجاح.',
                                              'The engine\'s last run status and time, with pair, invoice and customer counts on success.'),
             'more': T('لو التشغيل نجح بتشوف عدد الاقترانات والفواتير اللي اتقرت والعملاء.\n'
                       '• لو فشل بتظهر رسالة الخطأ بالأحمر.\n'
                       '• وهو شغال الحالة بتتحدّث لوحدها كل كام ثانية.',
                       'If the run succeeded you see the number of pairs, invoices scanned and customers.\n'
                       '• If it failed, the error message shows in red.\n'
                       '• While it runs, the status refreshes by itself every few seconds.')},
            {'target': 'catalog-recommendations-run-controls', 'text': T('«⚙️ إعدادات» و«▶ تشغيل المحرك» — تظهر للمدير والمشرف فقط.',
                                              '«⚙️ Settings» and «▶ Run engine» — shown only to admins and supervisors.'),
             'more': T('«⚙️ إعدادات» بيفتح: فترة الرصد بالأيام، والحد الأدنى للدعم، والحد الأدنى للثقة.\n'
                       '• «▶ تشغيل المحرك» بيبدأ التشغيل بالإعدادات دي، ومينفعش تشغيلين في نفس الوقت.\n'
                       '• السيرفر نفسه بيرفض التشغيل من أي حد غير المدير والمشرف.',
                       '"⚙️ Settings" opens: look-back period in days, minimum support and minimum confidence.\n'
                       '• "▶ Run engine" starts a run with these settings; two runs cannot happen at once.\n'
                       '• The server itself refuses a run from anyone other than admins and supervisors.')},
            {'target': 'catalog-recommendations-tabs', 'text': T('التبويبات: اقترانات الأصناف، توصيات العملاء، وسجل التشغيل.',
                                              'Tabs: item pairs, customer recommendations, and run history.'),
             'more': T('• «اقترانات الأصناف»: الأزواج اللي بتتشترى سوا.\n'
                       '• «توصيات العملاء»: ابحث عن عميل وشوف المقترح له — مفيد للكول سنتر وقت المكالمة.\n'
                       '• «سجل التشغيل»: كل مرات التشغيل ونتايجها.',
                       '• "Item pairs": pairs bought together.\n'
                       '• "Customer recommendations": search a customer and see what is suggested — handy for the call center during a call.\n'
                       '• "Run history": every run and its results.')},
            {'target': 'catalog-recommendations-fbt-toolbar', 'text': T('في الاقترانات: ابحث باسم الصنف أو كوده، واختر الترتيب.',
                                              'In item pairs: search by item name or code, and choose the sort order.'),
             'more': T('الترتيب: الدرجة، الثقة، الرفع، أو التكرار.\n'
                       '• جنبها عدد الاقترانات الكلي.\n'
                       '• البحث بيرجعك لأول صفحة.',
                       'Sort by: score, confidence, lift or frequency.\n'
                       '• Next to it is the total number of pairs.\n'
                       '• Searching takes you back to page one.')},
            {'target': 'catalog-recommendations-fbt-table', 'text': T('الأزواج مع الثقة والرفع والدعم والتكرار والدرجة.',
                                              'The pairs with confidence, lift, support, frequency and score.'),
             'more': T('• «الثقة»: من اللي اشتروا الصنف الأساسي، كام في المية اشتروا المقترن معاه.\n'
                       '• «الرفع» أعلى من 1 يعني ارتباط حقيقي مش صدفة.\n'
                       '• «التكرار»: عدد الفواتير اللي اتجمعوا فيها.',
                       '• "Confidence": of those who bought the main item, what percent also bought the paired one.\n'
                       '• "Lift" above 1 means a real association, not chance.\n'
                       '• "Frequency": how many invoices they appeared on together.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'catalog.vision',
        'routes': ['/vision-corpus'],
        'title': T('المحرك البصري (بيانات التعلّم)', 'Vision engine (training data)'),
        'summary': T('متابعة نمو قاعدة بيانات التعلّم المملوكة لنا: كل صورة روشتة أو صوت أو فاتورة مورّد يُقرأ ثم يُؤكد بشرياً يصبح مثال تدريب للمحرك الداخلي للقراءة الآلية. تعرض الحجم، نسبة التصنيف، المصادر، ودقة المحركات.',
                     'Follow the growth of our own training dataset: every prescription photo, voice note or supplier invoice that is read then confirmed by a person becomes a training example for the in-house reading engine. Shows size, label rate, sources and engine accuracy.'),
        'audience': T('الإدارة والمشرفون.', 'Management and supervisors.'),
        'tips': [T('كلما أكّدت قراءة صحيحة في نقطة البيع أو النواقص أو الفواتير زادت دقة المحرك الداخلي.', 'Every correct reading you confirm in the POS, shortages or invoices improves the in-house engine.')],
        'tour': [
            {'target': 'catalog-vision-header', 'text': T('مجموعة بيانات المحرك البصري الداخلي — تنمو مع كل قراءة يؤكدها موظف.',
                                              'The in-house vision engine\'s dataset — it grows with every reading a staff member confirms.'),
             'more': T('الشاشة دي للمتابعة بس، مفيهاش أزرار.\n'
                       '• كل مرة موظف يأكد قراءة صورة روشتة أو صوت أو قائمة نواقص أو فاتورة مورّد، بتتحفظ كمثال تدريب.',
                       'This screen is for monitoring only; it has no buttons.\n'
                       '• Every time a staff member confirms the reading of a prescription photo, voice note, shortage list or supplier invoice, it is saved as a training example.')},
            {'target': 'catalog-vision-stats', 'text': T('إجمالي العيّنات، المُصنَّفة بتأكيد بشري، الجاهزة للتدريب، وحالة المحرك الداخلي.',
                                              'Total samples, human-confirmed ones, training-ready images, and the in-house engine status.'),
             'more': T('• «مُصنَّفة (بتأكيد بشري)» هي اللي ليها قيمة في التدريب.\n'
                       '• حالة «المحرك الداخلي»: «مُفعَّل ✓» أو «مُهيَّأ» أو «غير مُدرَّب».',
                       '• "Labelled (human-confirmed)" are the ones that matter for training.\n'
                       '• The "In-house engine" status: "active ✓", "configured" or "not trained".')},
            {'target': 'catalog-vision-breakdown', 'text': T('توزيع العيّنات حسب المصدر والمحرك والوسيط (صورة أو صوت).',
                                              'Sample breakdown by source, engine and media (image or audio).'),
             'more': T('المصادر: روشتة ونقطة البيع، صوت في نقطة البيع، النواقص، وفواتير الموردين.\n'
                       '• بيوضح أنهي جزء من الشغل بيغذي المحرك أكتر.',
                       'Sources: POS prescriptions, POS voice, shortages, and supplier invoices.\n'
                       '• It shows which part of the work feeds the engine the most.')},
            {'target': 'catalog-vision-accuracy', 'text': T('دقة كل محرك مقارنةً بالتأكيدات البشرية — تظهر عند توفر نتائج.',
                                              'Each engine\'s accuracy against human confirmations — shown when results exist.'),
             'more': T('النسبة = كام صنف من الأصناف اللي الموظفين أكدوها المحرك لقاها صح، في آخر مجموعة عيّنات.\n'
                       '• القسم ده مش بيظهر غير لما يكون فيه نتايج كفاية.',
                       'The percentage = how many of the items staff confirmed the engine found correctly, over the latest set of samples.\n'
                       '• This section only appears when there are enough results.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'catalog.mobile_items',
        'routes': ['/m/items'],
        'title': T('بحث صنف ومخزون (موبايل)', 'Item & stock lookup (mobile)'),
        'summary': T('من بين الأرفف: امسح أو ابحث عن صنف لترى سعره ومخزونه الحي في كل الفروع وإجمالي الشبكة.', 'In the aisle: scan or search an item to see its price and live stock in every branch and the network total.'),
        'audience': T('الصيادلة والمندوبون.', 'Pharmacists and salespeople.'),
        'related': ['catalog.products'],
        'tour': [
            {'target': 'catalog-mobile-items-search', 'text': T('«بحث عن صنف»: اكتب الاسم أو امسح الباركود لاختيار الصنف.',
                                              '«Item search»: type the name or scan the barcode to pick the item.'),
             'more': T('البحث بيدوّر بالاسم والاسم العلمي والكود وكل باركودات الصنف، وبيشتغل مع قارئ الباركود.\n'
                       '• الشاشة دي للقراءة بس — مفيش أي تعديل على المخزون.',
                       'The search looks up name, scientific name, code and all the item\'s barcodes, and works with a barcode scanner.\n'
                       '• This screen is read-only — nothing changes in stock.')},
            {'target': 'catalog-mobile-items-card', 'text': T('بعد اختيار الصنف: اسمه وكوده وسعره.',
                                              'After picking the item: its name, code and price.'),
             'more': T('بيظهر الاسم والاسم العلمي (لو موجود) وكود SOFTECH وسعر العبوة.\n'
                       '• اتأكد إنه نفس الصنف اللي العميل طالبه قبل ما ترد عليه.',
                       'Shows the name, the scientific name (if any), the SOFTECH code and the pack price.\n'
                       '• Make sure it is the same item the customer asked for before you answer.')},
            {'target': 'catalog-mobile-items-total', 'text': T('«إجمالي الشبكة»: مجموع المخزون في كل الفروع.',
                                              '«Network total»: the combined stock across all branches.'),
             'more': T('لو صفر يبقى الصنف مش موجود في أي فرع.\n'
                       '• في الحالة دي ممكن تسجّله في النواقص أو تعمل للعميل حجز.',
                       'If it is zero, the item is not in any branch.\n'
                       '• In that case you can record it as a shortage or make a reservation for the customer.')},
            {'target': 'catalog-mobile-items-stock', 'text': T('«المخزون حسب الفرع»: الكمية الحية في كل فرع، الأعلى أولاً.',
                                              '«Stock by branch»: the live quantity in each branch, highest first.'),
             'more': T('اللون بيوضح الحالة: أخضر متوفر، أصفر قليل، أحمر خلصان.\n'
                       '• مفيد عشان تعرف أقرب فرع تبعت له العميل أو تطلب منه تحويل.',
                       'The colour shows the status: green in stock, amber low, red out.\n'
                       '• Useful to know the nearest branch to send the customer to or to request a transfer from.')},
        ],
        'change_note': CHANGE_NOTE,
        'updated': '2026-10-25',
    },
]
