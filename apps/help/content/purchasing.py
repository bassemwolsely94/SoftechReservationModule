from . import T

_HUB_NOTE = T(
    'شريط الفلاتر أعلى «ذكاء المشتريات» مشترك بين كل تبويباته: الفترة (اليوم، الأسبوع، الشهر، الربع، السنة، الكل، مخصص)، الفروع، فئات الموردين، وخصائص الأصناف — غيّره مرة فيتغير كل تبويب.',
    'The filter bar at the top of "Procurement intelligence" is shared by all its tabs: period (today, week, month, quarter, year, all, custom), branches, supplier categories and item attributes — change it once and every tab follows.')

MODULE = {
    'key': 'purchasing', 'group': 'purchasing', 'icon': '🛒',
    'title': T('المشتريات والتوريد', 'Purchasing & supply'),
    'summary': T(
        '«محرك الطلب» يحسب لكل صنف في كل فرع معدل البيع الموزون (30/90/365 يوماً)، فئة ABC (الأصناف الأهم قيمة)، حد الأمان، التغطية بالشهور، '
        'والفجوة التي تحتاج شراء — ويقترح تحويلات بين الفروع قبل الشراء. فوقه: «ذكاء المشتريات» لتحليل الموردين والأسعار والهوامش والبونص، '
        '«التوريد والمعدلات» لمتابعة عروض الموردين والنواقص اليومية وطلبات التوريد ومعدلات البيع في SOFTECH، و«تحسين الكاش» لمنع الشراء الزائد.',
        'The "demand engine" calculates, per item per branch, the weighted sales rate (30/90/365 days), ABC class (most valuable items), safety stock, coverage in months, '
        'and the gap that needs buying — and suggests transfers between branches before buying. On top: "Procurement intelligence" to analyse suppliers, prices, margins and bonuses, '
        '"Supply & rates" to follow supplier offers, daily shortages, supply requests and SOFTECH sales rates, and "Cash optimization" to prevent over-buying.'),
    'flows': [
        {
            'key': 'cycle',
            'title': T('دورة الشراء: من التوصية للفاتورة', 'Purchasing cycle: from recommendation to invoice'),
            'summary': T('توصيات الشراء ← إتاحة الموردين وطلبات التوريد ← استلام فاتورة المورد ومراجعتها.',
                         'Purchase recommendations → supplier availability and supply requests → receiving and reviewing the supplier invoice.'),
            'roles': ['admin', 'purchasing'],
            'steps': [
                {'target': 'nav-purchasing', 'nav': '/purchasing',
                 'text': T('نبدأ من «المشتريات» ← «توصيات الشراء».',
                           'Start at "Purchasing" → "Purchase recommendations".'),
                 'more': T('دورة الشراء بتبدأ من «توصيات الشراء»: المحرك بيقولك نشتري إيه وكام قبل ما تكلّم أي مورد.\n'
                           '• الأرقام محسوبة من مبيعات ومخزون SOFTECH لكل فرع.\n'
                           '• بعدها هنقارن بعروض الموردين، وفي الآخر نستلم الفاتورة ونراجعها.',
                           'The purchasing cycle starts at "Purchase recommendations": the engine tells you what and how much to buy before you talk to any supplier.\n'
                           '• Numbers are calculated from SOFTECH sales and stock per branch.\n'
                           '• Then we compare with supplier offers, and finally receive and review the invoice.')},
                {'target': 'purchasing-engine-summary', 'route': '/purchasing',
                 'text': T('المحرك بيحسب المطلوب لكل صنف من المبيعات والمخزون — الملخص حسب الفئة وقيمة الفجوة.',
                           'The engine works out what each item needs from sales and stock — summary by class and gap value.'),
                 'more': T('البطاقات بتلخّص الشبكة: إجمالي الأصناف، عدد A وB وC، «أصناف تحتاج شراء» و«قيمة الفجوة» بالجنيه.\n'
                           '• «قيمة الفجوة» = تقدير فلوس اللي محتاج يتشرى.\n'
                           '• لو فيه «صنف غير مربوط»، أصناف من SOFTECH مش متطابقة مع الكتالوج.',
                           'The cards summarise the network: total items, A, B and C counts, "Items needing purchase" and the "Gap value" in EGP.\n'
                           '• "Gap value" = an estimate of the money needed for what must be bought.\n'
                           '• If "unlinked items" appears, some SOFTECH items are not matched to the catalog.')},
                {'target': 'purchasing-engine-view-tabs', 'route': '/purchasing',
                 'text': T('العروض: الشبكة (ABC)، بالفرع، التحويلات المقترحة (قبل ما تشتري: يمكن فرع تاني عنده)، والمبيعات الضائعة.',
                           'Views: network (ABC), by branch, suggested transfers (before buying: another branch may have it), lost sales.'),
                 'more': T('قبل ما تشتري، افتح «🔄 التحويلات المقترحة»: يمكن فرع عنده فائض يغطي فرع ناقص — أرخص من الشراء.\n'
                           '• الموافقة على اقتراح بتعمل طلب تحويل في موديول التحويلات.\n'
                           '• «💸 مبيعات ضائعة» بتقدّر اللي ضاع علينا بسبب النفاد.',
                           'Before buying, open "🔄 Suggested transfers": a branch with excess may cover one that is short — cheaper than buying.\n'
                           '• Approving a suggestion creates a transfer request in the transfers module.\n'
                           '• "💸 Lost sales" estimates what we lost to stock-outs.')},
                {'target': 'purchasing-engine-abc-filter', 'route': '/purchasing',
                 'text': T('ابدأ بالفئة A — الأكثر تأثيراً.',
                           'Start with class A — the highest impact.'),
                 'more': T('فئة A = الأصناف اللي بتعمل حوالي 70% من قيمة المبيعات — نقصها بيأثر أكتر.\n'
                           '• خلّص فجوة A الأول، وبعدها B ثم C.\n'
                           '• X = أصناف من غير مبيعات؛ متشتريهاش إلا لسبب واضح.',
                           'Class A = the items making up about 70% of sales value — running short of them hurts most.\n'
                           '• Close the A gap first, then B, then C.\n'
                           '• X = items with no sales; do not buy them without a clear reason.')},
                {'target': 'purchasing-engine-export', 'route': '/purchasing',
                 'text': T('«⬇ تصدير» يطلع القائمة Excel للمراجعة.',
                           '"⬇ Export" downloads the list to Excel for review.'),
                 'more': T('التصدير بيطلع القائمة Excel أو CSV بفلتر الفئة (والفرع في عرض «بالفرع»).\n'
                           '• فيه كمان «Pivot Excel (أولويات النواقص)» وخانة «تعبئة الطلب لـ X شهر» لو عايز طلب أقل أو أعمق من شهر.\n'
                           '• الشيت ده اللي بتراجعه وتبني عليه طلبك للمورد.',
                           'Export gives the list as Excel or CSV, filtered by class (and branch in the "By branch" view).\n'
                           '• There is also "Pivot Excel (shortage priorities)" and an "Order fill for X months" box for a smaller or deeper order than one month.\n'
                           '• This sheet is what you review and build your supplier order on.')},
                {'target': 'nav-supply', 'nav': '/supply',
                 'text': T('بعدها «التوريد والمعدلات».',
                           'Next, "Supply & rates".'),
                 'more': T('«التوريد والمعدلات» هي مساحة الشغل اليومية للمشتريات.\n'
                           '• فيها عروض الموردين، متابعة النواقص، معدلات البيع، طلبات التوريد، وطلبات واتساب من الفروع.\n'
                           '• مفيش حاجة هنا بتكتب في SOFTECH من غير اعتماد صريح وبوابة مفعّلة.',
                           '"Supply & rates" is purchasing\'s daily workspace.\n'
                           '• It holds supplier offers, shortage follow-up, sales rates, supply requests and branch WhatsApp requests.\n'
                           '• Nothing here writes to SOFTECH without explicit approval and an enabled gate.')},
                {'target': 'purchasing-supply-tabs', 'route': '/supply',
                 'text': T('«صندوق الإتاحة» لعروض الموردين، و«طلبات التوريد / ISR» لمتابعة الطلبات.',
                           '"Availability inbox" for supplier offers, "Supply requests / ISR" to follow requests.'),
                 'more': T('• «صندوق الإتاحة»: قوائم الموردين المتاح عندهم إيه وبكام.\n'
                           '• «متابعة النواقص»: كل احتياج مفتوح بيفضل حالة لحد ما يتحل بتحويل أو شراء.\n'
                           '• «طلبات التوريد / ISR» للمعاينة، و«تلبية طلبات الفروع» لخطة تلبية طلبات الفروع من الفائض والرئيسي.',
                           '• "Availability inbox": supplier lists of what they have and at what price.\n'
                           '• "Shortage follow-up": every open need stays a case until solved by a transfer or a purchase.\n'
                           '• "Supply requests / ISR" is a preview, and "Fill branch requests" plans filling branch requests from excess and HQ.')},
                {'target': 'purchasing-supply-import', 'route': '/supply',
                 'text': T('استورد قائمة إتاحة المورد: صورة أو ملف Excel / CSV.',
                           'Import the supplier\'s availability list: an image or an Excel / CSV file.'),
                 'more': T('اكتب اسم المورد زي ما هو في الرسالة، واختار المصدر، وارفع «📷 صورة / لقطة شاشة» أو «📄 Excel / CSV».\n'
                           '• الملف بيتقري على طول ويتعمل منه قائمة جديدة؛ ملف Excel جديد الشكل ممكن يطلب منك تحدد الأعمدة.\n'
                           '• القائمة بتظهر في شريط «القوائم» فوق.',
                           'Enter the supplier name as in the message, choose the source, and upload "📷 Image / screenshot" or "📄 Excel / CSV".\n'
                           '• The file is read at once and becomes a new list; an Excel file in a new layout may ask you to map the columns.\n'
                           '• The list then appears in the "Lists" strip above.')},
                {'target': 'purchasing-supply-paste', 'route': '/supply',
                 'text': T('أو الصق نص رسالة المورد.',
                           'Or paste the supplier\'s message text.'),
                 'more': T('الصق رسالة الواتساب زي ما هي، سطر لكل صنف (مثال: «Zinnat 250 10+2 @ 90»).\n'
                           '• النص الأصلي بيتحفظ زي ما هو عشان ترجع له وقت المراجعة.\n'
                           '• Ctrl+Enter بيحلّل على طول.',
                           'Paste the WhatsApp message as is, one line per item (e.g. "Zinnat 250 10+2 @ 90").\n'
                           '• The original text is saved as is so you can go back to it during review.\n'
                           '• Ctrl+Enter analyses straight away.')},
                {'target': 'purchasing-supply-analyze', 'route': '/supply',
                 'text': T('«تحليل القائمة» يطابق أصناف المورد مع الكتالوج ويقارنها بالاحتياج.',
                           '"Analyze list" matches the supplier\'s items to the catalog and compares them with the need.'),
                 'more': T('النظام بيطابق كل سطر بصنف من الكتالوج ويحسب: محتاجينه؟ كام؟ بتكلفة فعلية كام؟ وهل المخزون الداخلي يغطيه؟\n'
                           '• راجع المطابقة وأكّدها — التأكيد بيعلّم النظام أكواد المورد ده للمرة الجاية.\n'
                           '• اطلب اللي محتاجينه فعلاً بس، مش كل اللي المورد عارضه.',
                           'The system matches each line to a catalog item and works out: do we need it, how many, at what real cost, and does internal stock cover it?\n'
                       "• Review and confirm the matches — confirming teaches the system this supplier's codes for next time.\n"
                           '• Order only what we actually need, not everything the supplier offers.')},
                {'target': 'nav-invoices', 'nav': '/invoices',
                 'text': T('لما البضاعة توصل: «فواتير الموردين».',
                           'When the goods arrive: "Supplier invoices".'),
                 'more': T('لما البضاعة توصل، فاتورة المورد بتتسجّل في «فواتير الموردين».\n'
                           '• هنا بنتأكد إن اللي جه هو اللي اتطلب وبالسعر الصح.\n'
                           '• بعد المراجعة الفاتورة بتترحّل لـ SOFTECH كمستند شراء — مرة واحدة بس.',
                           'When the goods arrive, the supplier invoice is recorded in "Supplier invoices".\n'
                           '• Here we check that what arrived is what was ordered, at the right price.\n'
                           '• After review the invoice is posted to SOFTECH as a purchase document — once only.')},
                {'target': 'invoices-main-new', 'route': '/invoices',
                 'text': T('«+ فاتورة جديدة»: الفرع والمورد ونوع المستند وصورة الفاتورة.',
                           '"+ New invoice": branch, supplier, document type and the invoice image.'),
                 'more': T('اختار الفرع والمورد ونوع المستند وارفع صورة الفاتورة.\n'
                           '• النظام بيقرا الصورة ويطلّع السطور تلقائياً (الحالة «جاري المعالجة»).\n'
                           '• بعدها الفاتورة بتبقى «قيد المراجعة».',
                           'Choose the branch, supplier and document type and upload the invoice image.\n'
                           '• The system reads the image and extracts the lines automatically (status "Processing").\n'
                           '• It then becomes "Under review".')},
                {'target': 'invoices-main-list', 'route': '/invoices',
                 'text': T('الفواتير وحالتها — افتح فاتورة لمراجعتها.',
                           'The invoices and their status — open one to review it.'),
                 'more': T('كل بطاقة فاتورة بحالتها: في الانتظار، قيد المراجعة، مُأكَّدة، بانتظار الترحيل، مُرحّلة إلى ERP، أو فشل الترحيل.\n'
                           '• فوق تقدر تفلتر بالفرع والحالة.\n'
                           '• اضغط الفاتورة عشان تفتح سطورها.',
                           'Each invoice card has its status: pending, under review, confirmed, queued, posted to ERP, or posting failed.\n'
                           '• At the top you can filter by branch and status.\n'
                           '• Click an invoice to open its lines.')},
                {'target': 'invoices-main-lines', 'route': '/invoices',
                 'text': T('داخل الفاتورة: راجع كل سطر — الصنف المطابق والكمية والسعر.',
                           'Inside an invoice: review each line — matched item, quantity and price.'),
                 'more': T('لكل سطر: الصنف اللي اتطابق، الكمية، البونص والسعر — قارنهم بالفاتورة الورق.\n'
                           '• صحّح أي مطابقة غلط قبل التأكيد.\n'
                           '• الخطأ هنا بيوصل لـ SOFTECH لو اترحّل.',
                           'For each line: the matched item, quantity, bonus and price — compare them with the paper invoice.\n'
                           '• Fix any wrong match before confirming.\n'
                           '• A mistake here reaches SOFTECH if it is posted.')},
                {'target': 'invoices-main-actions', 'route': '/invoices',
                 'text': T('«⚠ فحص الانحرافات» ثم «✓ تأكيد الفاتورة». الترحيل لـ SOFTECH لمن عنده الصلاحية بعد المراجعة، والأخطاء بتمنعه.',
                           '"⚠ Check deviations" then "✓ Confirm invoice". Posting to SOFTECH is for authorised users after review, and errors block it.'),
                 'more': T('«⚠ فحص الانحرافات» بيطلّع الأسعار أو الكميات الغريبة، و«✓ تأكيد الفاتورة» بيقفل المراجعة.\n'
                           '• «🛡 فحص التحقق» بيراجع قواعد SOFTECH، و«⇪ ترحيل إلى ERP» بيعرض معاينة قبل الترحيل.\n'
                           '• بعد الترحيل بيظهر «✓ مُرحّلة — مستند #…»، والفاتورة متترحّلش مرتين.',
                           '"⚠ Check deviations" flags odd prices or quantities, and "✓ Confirm invoice" closes the review.\n'
                           '• "🛡 Validate" checks SOFTECH rules, and "⇪ Post to ERP" shows a preview before posting.\n'
                           '• After posting, "✓ Posted — document #…" appears, and the invoice cannot be posted twice.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'purchasing.engine',
        'routes': ['/purchasing'],
        'title': T('توصيات الشراء (محرك الطلب)', 'Purchase recommendations (demand engine)'),
        'summary': T('نتائج محرك الطلب: ما يجب شراؤه ومن أين يمكن التحويل بدل الشراء، مرتبة بفئة ABC، مع حالة آخر تشغيل وتاريخ آخر بيانات مبيعات.',
                     'The demand engine\'s output: what must be bought and where a transfer can replace buying, by ABC class, with the last run status and the date of the latest sales data.'),
        'audience': T('المشتريات والمدير.', 'Purchasing and admins.'),
        'tabs': [
            {'key': 'agg', 'title': T('📦 الشبكة (ABC)', '📦 Network (ABC)'), 'body': T('نظرة مجمعة على كل الفروع: المعدل الشهري، المخزون، الفجوة، القيمة، الهامش الإجمالي والصافي، والنسبة التراكمية (باريتو). صفِّ بفئة A/B/C/X.', 'An aggregate view across branches: monthly rate, stock, gap, value, gross and net margin, and cumulative % (Pareto). Filter by class A/B/C/X.')},
            {'key': 'branch', 'title': T('🏭 بالفرع', '🏭 By branch'), 'body': T('لكل فرع: المتوسط الشهري، الأمان، البضاعة في الطريق (تُخصم من الفجوة)، التغطية، الأولوية، الحالة (نفد/حرج/منخفض/مقبول/جيد) وآخر بيع. «يحتاج شراء فقط» يختصر القائمة.', 'Per branch: monthly average, safety stock, goods in transit (deducted from the gap), coverage, priority, status (out/critical/low/ok/good) and last sale. "Needs purchase only" shortens the list.')},
            {'key': 'transfer', 'title': T('🔄 التحويلات المقترحة', '🔄 Suggested transfers'), 'body': T('توصيات نقل من فرع عنده فائض لفرع عنده نقص مع الكمية والقيمة والأولوية. راجع وافق أو ارفض؛ الموافقة تتحول لطلب تحويل.', 'Suggestions to move stock from a branch with excess to one with a shortage, with quantity, value and priority. Review and approve or reject; approval becomes a transfer request.')},
            {'key': 'lostsales', 'title': T('💸 مبيعات ضائعة', '💸 Lost sales'), 'body': T('تقدير المبيعات الضائعة بسبب نفاد المخزون.', 'Estimated sales lost to stock-outs.')},
        ],
        'steps': [
            T('تأكد أن «المبيعات حتى» حديثة؛ لو متأخرة اضغط «تعويض المبيعات المتأخرة» أو «مزامنة كاملة 365 يوم» ثم «تشغيل».', 'Make sure "sales up to" is recent; if behind press "Catch up late sales" or "Full 365-day sync", then "Run".'),
            T('ابدأ بالتحويلات المقترحة (أرخص من الشراء)، ثم الفجوة المتبقية في فئة A.', 'Start with suggested transfers (cheaper than buying), then the remaining gap in class A.'),
        ],
        'tips': [T('المعادلة الحالية مكتوبة أسفل الصفحة: موزون = معدل30×% + معدل90×% + معدل365×%.', 'The current formula is shown at the bottom: weighted = rate30×% + rate90×% + rate365×%.')],
        'related': ['purchasing.supply', 'catalog.inventory', 'shortage.market', 'purchasing.cash'],
        'tour': [
            {'target': 'purchasing-engine-run', 'text': T('«▶ تشغيل» يحسب التوصيات من جديد.',
                                              '"▶ Run" recalculates the recommendations.'),
             'more': T('تشغيل سريع: بيزامن مبيعات SOFTECH من آخر تاريخ عنده بس، ويعيد حساب التوصيات — عادةً أقل من دقيقة.\n'
                       '• أثناء التشغيل بيظهر شريط تقدّم فوق.\n'
                       '• لو المبيعات متأخرة أيام، استخدم «⟳ تعويض المبيعات» أو «🔄 مزامنة كاملة» (365 يوم، 5–8 دقايق).',
                       'Quick run: syncs SOFTECH sales only from the last date it has, and recalculates the recommendations — usually under a minute.\n'
                       '• While running, a progress bar appears at the top.\n'
                       '• If sales are days behind, use "⟳ Catch up sales" or "🔄 Full sync" (365 days, 5–8 minutes).')},
            {'target': 'purchasing-engine-summary', 'text': T('الملخص: عدد الأصناف حسب الفئة وقيمة الفجوة.',
                                              'The summary: items per class and the gap value.'),
             'more': T('• «فئة A/B/C»: الأصناف حسب نصيبها من قيمة المبيعات (A أعلى 70%).\n'
                       '• «أصناف تحتاج شراء» و«قيمة الفجوة (ج.م)»: حجم الشراء المطلوب.\n'
                       '• «قيمة مبيعات/شهر» للشبكة كلها، أو عدد الأصناف غير المربوطة لو موجودة.',
                       '• "Class A/B/C": items by share of sales value (A is the top 70%).\n'
                       '• "Items needing purchase" and "Gap value (EGP)": the size of the buying needed.\n'
                       '• "Monthly sales value" for the whole network, or the number of unlinked items if any.')},
            {'target': 'purchasing-engine-view-tabs', 'text': T('العروض: الشبكة (ABC)، بالفرع، التحويلات المقترحة، المبيعات الضائعة.',
                                              'Views: network (ABC), by branch, suggested transfers, lost sales.'),
             'more': T('• «📦 الشبكة (ABC)»: كل الفروع مجمّعة مع الهامش والنسبة التراكمية.\n'
                       '• «🏭 بالفرع»: لكل فرع التغطية والأولوية والحالة (نفد/حرج/منخفض…)، والبضاعة في الطريق بتتخصم من الفجوة.\n'
                       '• «🔄 التحويلات المقترحة» قبل الشراء، و«💸 مبيعات ضائعة» لتقدير خسارة النفاد.',
                       '• "📦 Network (ABC)": all branches combined, with margin and cumulative %.\n'
                       '• "🏭 By branch": per branch coverage, priority and status (out/critical/low…); goods in transit are deducted from the gap.\n'
                       '• "🔄 Suggested transfers" before buying, and "💸 Lost sales" to estimate stock-out losses.')},
            {'target': 'purchasing-engine-abc-filter', 'text': T('فلتر الفئة A / B / C والفلاتر المتقدمة.',
                                              'Filter by class A / B / C and advanced filters.'),
             'more': T('الأزرار بتفلتر القائمة: «كل الأصناف»، A الأكثر أهمية، B، C، أو X (بلا مبيعات).\n'
                       '• «🔍 فلاتر متقدمة» بتفتح فلاتر إضافية لخصائص الأصناف.\n'
                       '• الشريط ده مش موجود في عرضي التحويلات والمبيعات الضائعة.',
                       'The buttons filter the list: "All items", A most important, B, C, or X (no sales).\n'
                       '• "🔍 Advanced filters" opens extra filters on item attributes.\n'
                       '• This bar is hidden in the transfers and lost-sales views.')},
            {'target': 'purchasing-engine-search', 'text': T('ابحث عن صنف.',
                                              'Search an item.'),
             'more': T('اكتب اسم الصنف أو جزء منه والجدول بيتصفّى.\n'
                       '• مفيد لما فرع يسأل عن صنف معيّن: محتاج شراء ولا لأ، وكام.\n'
                       '• البحث بيشتغل مع فلتر الفئة المختار.',
                       'Type the item name or part of it and the table filters.\n'
                       '• Useful when a branch asks about a specific item: does it need buying, and how much.\n'
                       '• Search works together with the selected class filter.')},
            {'target': 'purchasing-engine-export', 'text': T('«⬇ تصدير» يطلع القائمة Excel.',
                                              '"⬇ Export" downloads the list to Excel.'),
             'more': T('بيفتح خيارات: الفئة، الفرع (في عرض «بالفرع»)، و«تعبئة الطلب لـ X شهر» (فاضي = الطلب الشهري المعتاد).\n'
                       '• «📊 Excel» و«📄 CSV» للقائمة، و«🗂 Pivot Excel (أولويات النواقص)» بنموذج المحوري.\n'
                       '• التصدير قراءة بس — مش بيغيّر أي حاجة في SOFTECH.',
                       'Opens options: class, branch (in the "By branch" view), and "Order fill for X months" (empty = the usual monthly order).\n'
                       '• "📊 Excel" and "📄 CSV" for the list, and "🗂 Pivot Excel (shortage priorities)" in the pivot layout.\n'
                       '• Export is read-only — it changes nothing in SOFTECH.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'purchasing.cash',
        'routes': ['/cash-optimization'],
        'title': T('تحسين الكاش والمخزون', 'Cash & stock optimization'),
        'summary': T('رصد وتحرير الكاش المجمّد ومنع الشراء الزائد. التبويب المتاح «ذروة الطلب»: قفزة طلب حديثة قد لا تدوم — لو اشترينا لملاحقتها يركد المخزون. الذروة «القوية» يؤكدها إنسان فتصبح قابلة لتقليل الكمية المطلوبة؛ «المراقبة» للرصد فقط. التقليل يظهر على شيت النواقص فقط عند تفعيله في تشغيل المحرك.',
                     'Spot and free frozen cash and prevent over-buying. The available tab is "Demand spike": a recent jump in demand that may not last — buying to chase it leaves dead stock. A person confirms a "strong" spike so its order quantity can be reduced; "watch" spikes are monitor-only. The reduction shows on the shortage sheet only when enabled for the engine run.'),
        'audience': T('المشتريات والمشرفون والجودة.', 'Purchasing, supervisors and quality.'),
        'tabs': [
            {'key': 'spike', 'title': T('📈 ذروة الطلب', '📈 Demand spike'), 'body': T('لكل صنف: الدرجة، المضاعف (المعدل الحديث ÷ السابق)، الرصيد، المطلوب، وما بعد التقليل والتوفير المحتمل. «تأكيد (طبّق التقليل)» أو «إلغاء التأكيد».', 'Per item: grade, multiplier (recent ÷ previous rate), stock, required qty, after reduction and potential saving. "Confirm (apply reduction)" or "Unconfirm".')},
        ],
        'related': ['purchasing.engine'],
        'tour': [
            {'target': 'purchasing-cash-tabs', 'text': T('التبويبات: ذروة الطلب، والباقي قريباً.',
                                              'Tabs: demand spikes, the others coming soon.'),
             'more': T('«📈 ذروة الطلب» هو التبويب الشغال دلوقتي؛ «🧊 مخزون راكد» و«📦 فائض» مكتوب جنبهم «(قريبًا)».\n'
                       '• الفكرة: منشتريش كميات كبيرة ورا قفزة طلب مؤقتة فيركد المخزون والفلوس.\n'
                       '• النتائج بتظهر على شيت النواقص كتنبيهات.',
                       '"📈 Demand spike" is the working tab now; "🧊 Dead stock" and "📦 Overstock" are marked "(soon)".\n'
                       '• The idea: do not buy large amounts chasing a temporary jump in demand, which freezes stock and cash.\n'
                       '• Results show on the shortage sheet as alerts.')},
            {'target': 'purchasing-cash-kpis', 'text': T('ذروات مكتشفة، قوية، للمراقبة، ومؤكدة، والتوفير.',
                                              'Spikes found, strong, to watch, confirmed, and the saving.'),
             'more': T('• «📈 مكتشفة»: كل الأصناف اللي فيها ذروة. «قوية»: قابلة للتقليل بعد تأكيدك. «للمراقبة»: للمتابعة بس.\n'
                       '• «✓ مؤكَّدة»: اللي أكّدها حد، و«توفير الطلب المؤكَّد» = قيمة الشراء اللي اتفادينا.\n'
                       '• الشارة فوق بتقول هل «التقليل مُفعَّل» في تشغيل المحرك ولا «رصد فقط».',
                       '• "📈 Found": all items with a spike. "Strong": can be reduced after you confirm. "Watch": monitor only.\n'
                       '• "✓ Confirmed": those someone confirmed, and "Confirmed order saving" = the purchase value avoided.\n'
                       '• The badge above says whether "Reduction is enabled" in the engine run or "monitor only".')},
            {'target': 'purchasing-cash-filters', 'text': T('فلتر القوة والتصنيف والبحث.',
                                              'Filter by strength, category and search.'),
             'more': T('فلتر القوة: «الكل» أو «قوية» أو «مراقبة»، وقائمة التصنيف، وبحث بالكود أو الاسم.\n'
                       '• ابدأ بـ«قوية» — دي اللي ممكن تقلّل طلبها فعلاً.\n'
                       '• الفلاتر بتغيّر الجدول بس، مش الملخص فوق.',
                       'Strength filter: "All", "Strong" or "Watch", a category list, and search by code or name.\n'
                       '• Start with "Strong" — those are the ones whose order can actually be reduced.\n'
                       '• Filters change the table only, not the summary above.')},
            {'target': 'purchasing-cash-table', 'text': T('الأصناف اللي مبيعاتها الأخيرة فيها ذروة غير طبيعية.',
                                              'Items whose recent sales show an abnormal spike.'),
             'more': T('لكل صنف: الدرجة، «المضاعف» (المعدل الحديث ÷ السابق — «جديد» لو مكانش بيتباع)، المعدلين، الرصيد والمطلوب.\n'
                       '• بعد التأكيد بيظهر «بعد التقليل» و«توفير محتمل».\n'
                       '• اسأل نفسك: القفزة دي ليها سبب دائم (صنف جديد في السوق، نقص عند المنافسين) ولا مؤقتة؟',
                       'For each item: grade, "multiplier" (recent ÷ previous rate — "new" if it was not selling), both rates, stock and required qty.\n'
                       '• After confirming, "After reduction" and "Potential saving" appear.\n'
                       '• Ask yourself: does this jump have a lasting reason (new on the market, competitor shortage) or is it temporary?')},
            {'target': 'purchasing-cash-confirm', 'text': T('«تأكيد» بعد مراجعتك — بيطبّق التقليل على توصية الشراء.',
                                              '"Confirm" after your review — it applies the reduction to the purchase recommendation.'),
             'more': T('بيأكّد إن الذروة مؤقتة فيبقى الصنف قابل لتقليل كمية الشراء.\n'
                       '• التقليل بيوصل لشيت النواقص بس لما يكون مفعّل في تشغيل المحرك.\n'
                       '• لو غيّرت رأيك، «إلغاء التأكيد» بيرجّعه. أصناف «مراقبة» مفيهاش زرار تأكيد.',
                       "Confirms the spike is temporary so the item's purchase quantity can be reduced.\n"
                       '• The reduction reaches the shortage sheet only when enabled in the engine run.\n'
                       '• If you change your mind, "Unconfirm" reverts it. "Watch" items have no confirm button.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'purchasing.supply',
        'routes': ['/supply'],
        'title': T('التوريد والمعدلات', 'Supply & rates'),
        'summary': T('مساحة عمل يومية للمشتريات: عروض الموردين، متابعة النواقص، معدلات البيع في SOFTECH، طلبات التوريد، تلبية طلبات الفروع، طلبات واتساب، والتوزيعة. النظام يحسب كل الأرقام؛ الكتابة في SOFTECH مقيدة بمفاتيح تشغيل ومسار اعتماد.',
                     'A daily workspace for purchasing: supplier offers, shortage follow-up, SOFTECH sales rates, supply requests, filling branch requests, WhatsApp requests and distribution. The system computes every number; writing to SOFTECH is behind switches and an approval flow.'),
        'audience': T('المشتريات والمشرفون.', 'Purchasing and supervisors.'),
        'tabs': [
            {'key': 'inbox', 'title': T('صندوق الإتاحة', 'Availability inbox'),
             'body': T('الصق قائمة عرض المورد من واتساب أو ارفع صورة/Excel ← النظام يطابق الأصناف ويحسب لكل صنف: هل نحتاجه، كم، بأي تكلفة فعلية، وهل يغطيه المخزون الداخلي ← اختر ما نحتاجه فعلاً (لا تطلب كل ما عرضه المورد) ← نسخ/واتساب/Excel للطلب وتسجيله.',
                       'Paste the supplier\'s offer list from WhatsApp or upload a photo/Excel → the system matches items and computes per item: do we need it, how many, at what real cost, and does internal stock cover it → pick what we actually need (never everything offered) → copy/WhatsApp/Excel the order and record it.')},
            {'key': 'cases', 'title': T('متابعة النواقص', 'Shortage follow-up'),
             'body': T('كل احتياج غير محلول حالة تستمر يوماً بعد يوم، مرتبة (عاجل ← ندرة ← الأقدم ← الأكبر فجوة) مع شرح سبب التوصية. اعتمد التحويل الداخلي (مسودة طلب تحويل) أو اطلب الباقي من مورد.',
                       'Every unresolved need is a case that carries over day to day, ordered (urgent → scarcity → oldest → biggest gap) with why the engine recommends it. Approve the internal transfer (a draft transfer request) or order the rest from a supplier.')},
            {'key': 'rates', 'title': T('معدلات البيع', 'Sales rates'),
             'body': T('دفع المعدل الشهري المحسوب من محرك الطلب إلى SOFTECH: مقترح ← معتمد ← مُنفّذ. اختر الفروع والأصناف وطريقة الحساب (محورية / متقدمة Croston) ووجهة الكتابة (سيرفر الفرع، نسخة الرئيسي، أو الاثنان). التنفيذ محجوب حتى تفعيل البوابة.',
                       'Push the engine\'s monthly rate to SOFTECH: proposed → approved → executed. Choose branches, items, method (pivot / advanced Croston) and target (branch server, HQ copy, or both). Execution is blocked until the gate is enabled.')},
            {'key': 'isr', 'title': T('طلبات التوريد / ISR', 'Supply requests (ISR)'),
             'body': T('معاينة طلبات التوريد المقترحة من الرئيسي للفروع (للقراءة حالياً).', 'Preview of proposed supply requests from HQ to branches (read-only for now).')},
            {'key': 'isrfill', 'title': T('تلبية طلبات الفروع', 'Fill branch requests'),
             'body': T('لطلبات التوريد التي رفعتها الفروع في SOFTECH: لكل صنف حالة الفرع الطالب وكل الفروع والرئيسي، وخطة التلبية (فائض الفروع ← الرئيسي ← نقص للشراء). «تحديث من SOFTECH» يعيد قراءة المخزون، والتصدير Excel قابل للتعديل.',
                       'For supply requests branches raised in SOFTECH: per item the requesting branch, every other branch and HQ, and the fill plan (other branches\' excess → HQ → shortage to buy). "Refresh from SOFTECH" re-reads stock; the Excel export is editable.')},
            {'key': 'wa', 'title': T('طلبات واتساب', 'WhatsApp requests'),
             'body': T('الصق محادثة مجموعة واتساب الفرع (أو صورة) ← تُقسَّم الرسائل وتُطابق الأصناف ← راجع سطراً سطراً (Enter للتأكيد) ← تحليل التوافر وExcel ← «إنشاء قائمة النواقص» للفرع.',
                       'Paste the branch WhatsApp group chat (or a photo) → messages are split and items matched → review line by line (Enter confirms) → availability analysis and Excel → "Create shortage list" for the branch.')},
            {'key': 'dist', 'title': T('التوزيعة', 'Distribution'),
             'body': T('توزيع استباقي: أصناف جديدة بلا معدل، أصناف غير مُدرجة بفرع، متكدسة بفرع، أو راكدة بالرئيسي — مع اقتراح توزيعها.', 'Proactive distribution: new items with no rate, items never stocked at a branch, piled up at a branch, or dormant at HQ — with a suggested distribution.')},
        ],
        'tips': [T('لا شيء في هذه الشاشة يكتب في SOFTECH بدون اعتماد صريح وبوابة مفعّلة.', 'Nothing on this screen writes to SOFTECH without explicit approval and an enabled gate.')],
        'related': ['purchasing.engine', 'shortage.list', 'transfers.list'],
        'tour': [
            {'target': 'purchasing-supply-tabs', 'text': T('التبويبات: صندوق الإتاحة، متابعة النواقص، معدلات البيع، طلبات التوريد…',
                                              'Tabs: availability inbox, shortage follow-up, sales rates, supply requests…'),
             'more': T('كل تبويب شغلانة يومية: الإتاحة، النواقص، معدلات البيع، طلبات التوريد، تلبية طلبات الفروع، طلبات واتساب، والتوزيعة.\n'
                       '• الشاشة بتفتكر آخر تبويب فتحته.\n'
                       '• «معدلات البيع» بتكتب في SOFTECH بس بعد اعتماد وبوابة مفعّلة.',
                       'Each tab is a daily job: availability, shortages, sales rates, supply requests, filling branch requests, WhatsApp requests, and distribution.\n'
                       '• The screen remembers the last tab you opened.\n'
                       '• "Sales rates" writes to SOFTECH only after approval and with the gate enabled.')},
            {'target': 'purchasing-supply-batches', 'text': T('القوائم المستوردة من الموردين.',
                                              'The lists imported from suppliers.'),
             'more': T('كل قائمة مورد اتستوردت ليها زرار: المورد، رقمها، عدد السطور والمطابق والمؤكد، والتاريخ.\n'
                       '• 🔒 = قائمة نهائية مقفولة. اضغط القائمة تفتح مراجعتها تحت.\n'
                       '• «+ قائمة جديدة» يرجّع خانة الإدخال، و«📊 مطابقة الأكواد» بيوضح نسبة المطابقة بأكواد المورد.',
                       'Each imported supplier list has a button: supplier, its number, line, matched and confirmed counts, and date.\n'
                       '• 🔒 = a final locked list. Click a list to open its review below.\n'
                       '• "+ New list" brings back the input box, and "📊 Code matching" shows how many lines match by supplier code.')},
            {'target': 'purchasing-supply-import', 'text': T('اختار المورد والمصدر، وارفع صورة أو ملف Excel / CSV.',
                                              'Choose the supplier and source, and upload an image or an Excel / CSV file.'),
             'more': T('«المورد (كما في الرسالة)» والمصدر (واتساب، نص، بريد، يدوي)، وبعدين ارفع صورة أو Excel/CSV.\n'
                       '• الملف بيتقري ويعمل قائمة جديدة فوراً.\n'
                       '• لو شكل ملف Excel جديد بيطلب تحديد الأعمدة مرة، وبيفتكرها للمورد ده.',
                       '"Supplier (as in the message)" and the source (WhatsApp, text, email, manual), then upload an image or Excel/CSV.\n'
                       '• The file is read and a new list is created at once.\n'
                       '• A new Excel layout asks you to map the columns once and remembers them for that supplier.')},
            {'target': 'purchasing-supply-paste', 'text': T('أو الصق نص رسالة المورد هنا.',
                                              'Or paste the supplier\'s message text here.'),
             'more': T('الصق نص رسالة المورد زي ما هو — سطر لكل صنف، بالعربي أو الإنجليزي.\n'
                       '• النص الأصلي بيتحفظ للمراجعة.\n'
                       '• لو نفس المحتوى اتضاف قبل كده، هيظهر تنبيه إنه مكرر.',
                       "Paste the supplier's message as is — one line per item, Arabic or English.\n"
                       '• The original text is kept for review.\n'
                       '• If the same content was added before, a duplicate warning appears.')},
            {'target': 'purchasing-supply-analyze', 'text': T('«تحليل القائمة» يطابق الأصناف ويعرض المتاح.',
                                              '"Analyze list" matches the items and shows what is available.'),
             'more': T('بيحلل النص ويطابق كل سطر بصنف ويعرض لكل صنف الاحتياج والكمية والتكلفة الفعلية.\n'
                       '• الزرار شغال بس لو فيه نص. Ctrl+Enter اختصاره.\n'
                       '• بعد التحليل راجع وأكّد المطابقات، واطلب اللي محتاجينه بس.',
                       'It analyses the text, matches each line to an item, and shows need, quantity and real cost per item.\n'
                       '• The button works only when there is text. Ctrl+Enter is the shortcut.\n'
                       '• After analysis, review and confirm the matches, and order only what we need.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'purchasing.overview',
        'routes': ['/procurement/overview'],
        'title': T('ذكاء المشتريات — نظرة عامة', 'Procurement intelligence — overview'),
        'summary': T('مؤشرات المشتريات: صافي المشتريات والكميات والأصناف والموردون والفواتير ومتوسط الهامش (30 و365 يوماً)، تركّز أعلى 3 موردين، المرتجعات، الاتجاه الشهري، التنبيهات المفتوحة، وأفضل الموردين بالدرجة.',
                     'Purchasing KPIs: net purchases, quantities, items, suppliers, invoices and average margin (30 and 365 days), top-3 supplier concentration, returns, the monthly trend, open alerts, and the best suppliers by score.'),
        'audience': T('المشتريات والمدير.', 'Purchasing and admins.'),
        'steps': [{'text': T('«تشغيل المحرك» يعيد حساب المؤشرات وخرائط المورد-صنف والتنبيهات.', '"Run engine" recalculates KPIs, supplier-item maps and alerts.'), 'roles': ['admin', 'purchasing']}],
        'tips': [_HUB_NOTE],
        'related': ['purchasing.suppliers', 'purchasing.optimization'],
        'tour': [
            {'target': 'purchasing-overview-header', 'text': T('ذكاء المشتريات مع تاريخ آخر تحديث للبيانات.',
                                              'Procurement intelligence, with the date of the last data update.'),
             'more': T('«آخر تحديث» = تاريخ آخر لقطة حسبها المحرك؛ لو قديم الأرقام مش محدّثة.\n'
                       '• «🔄 تحديث» بيعيد تحميل الصفحة بس.\n'
                       '• تحت العنوان بيظهر آخر تشغيل للمحرك ونجح ولا لأ.',
                       '"Last update" = the date of the engine\'s last snapshot; if old, the numbers are stale.\n'
                       '• "🔄 Refresh" only reloads the page.\n'
                       "• Under the title you see the engine's last run and whether it succeeded.")},
            {'target': 'purchasing-overview-engine', 'text': T('«▶ تشغيل المحرك» يعيد حساب المؤشرات والتنبيهات؛ متاح للمشتريات والمدير.',
                                              '"▶ Run engine" recalculates KPIs and alerts; available to purchasing and admins.'),
             'more': T('بيعيد حساب المؤشرات وخرائط المورد-صنف والتنبيهات من بيانات المشتريات.\n'
                       '• وهو شغال الزرار بيبقى «⏳ المحرك يعمل…» ومينفعش تشغّله تاني.\n'
                       '• القراءة بس من SOFTECH — مفيش كتابة.',
                       'Recalculates KPIs, supplier-item maps and alerts from purchase data.\n'
                       '• While it runs the button shows "⏳ Engine running…" and cannot be started again.\n'
                       '• It only reads from SOFTECH — nothing is written.')},
            {'target': 'purchasing-overview-kpis', 'text': T('مؤشرات آخر 30 يوماً: صافي المشتريات، الكميات، الأصناف، الموردون، الفواتير ومتوسط الهامش.',
                                              'Last 30 days: net purchases, quantities, items, suppliers, invoices and average margin.'),
             'more': T('• «صافي المشتريات» مع سهم النمو عن الشهر اللي فات.\n'
                       '• الكميات، الأصناف المختلفة، الموردون النشطين، وعدد الفواتير.\n'
                       '• «متوسط الهامش» بالأخضر لو 20% أو أكتر وبالأحمر لو أقل. تحتهم نفس المؤشرات لـ 365 يوم.',
                       '• "Net purchases" with the growth arrow versus last month.\n'
                       '• Quantities, distinct items, active suppliers and invoice count.\n'
                       '• "Average margin" is green at 20% or more and red below. Below them are the same KPIs for 365 days.')},
            {'target': 'purchasing-overview-alerts', 'text': T('التنبيهات المفتوحة حسب الخطورة؛ «عرض الكل ←» يفتح صفحة التنبيهات.',
                                              'Open alerts by severity; "View all ←" opens the alerts page.'),
             'more': T('عدد التنبيهات المفتوحة حسب الخطورة: 🔴 حرجة، تحذير، ومعلومة (زي قفزة سعر أو تركّز على مورد).\n'
                       '• «عرض الكل ←» بيفتح تبويب التنبيهات في «تحسين المشتريات».\n'
                       '• عالج الحرجة الأول وعلّمها «حل ✓» هناك.',
                       'Open alerts by severity: 🔴 critical, warning and info (such as a price jump or supplier concentration).\n'
                       '• "View all ←" opens the alerts tab in "Procurement optimization".\n'
                       '• Handle the critical ones first and mark them "Resolve ✓" there.')},
            {'target': 'purchasing-overview-suppliers', 'text': T('أفضل الموردين بالدرجة؛ اضغط مورداً لتفاصيل أدائه.',
                                              'The best suppliers by score; click one for its performance details.'),
             'more': T('الموردين مرتبين بالدرجة (هامش، توافر، مرتجعات، استقرار أسعار)، وفوقهم «أعلى 3 موردين» ونصيبهم من الإجمالي.\n'
                       '• نسبة تركّز عالية = اعتماد كبير على مورد واحد.\n'
                       '• «عرض جميع الموردين ←» أو اضغط مورد لتفاصيله.',
                       'Suppliers ranked by score (margin, availability, returns, price stability), with "Top 3 suppliers" and their share above.\n'
                       '• A high concentration = heavy dependence on one supplier.\n'
                       '• "View all suppliers ←" or click a supplier for details.')},
            {'target': 'purchasing-overview-nav', 'text': T('اختصارات: أداء الموردين، الهوامش، خريطة المورد-صنف، والتحسين والتنبيهات.',
                                              'Shortcuts: supplier performance, margins, supplier-item map, and optimization & alerts.'),
             'more': T('اختصارات للشاشات التفصيلية: «أداء الموردين»، «تحليل الهوامش»، «خريطة المورد-صنف»، و«التحسين والتنبيهات».\n'
                       '• الفلتر اللي فوق (الفترة والفروع…) مشترك بين كل شاشات ذكاء المشتريات.\n'
                       '• كلها قراءة وتحليل — مفيش حاجة بتتغير في SOFTECH.',
                       'Shortcuts to the detail screens: "Supplier performance", "Margin analysis", "Supplier-item map", and "Optimization & alerts".\n'
                       '• The filter bar at the top (period, branches…) is shared by all procurement intelligence screens.\n'
                       '• All are read and analysis only — nothing changes in SOFTECH.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'purchasing.history',
        'routes': ['/procurement/history'],
        'title': T('سجل المشتريات المتقدم', 'Advanced purchase history'),
        'summary': T('كل سطور الشراء والمرتجعات من SOFTECH مع فلاتر كاملة (المورد، الصنف، المشتري، الهامش، التكلفة الفعلية، القيمة، البونص، المرتجع التالف أو العادي) وشريط إجماليات للنتائج كلها.',
                     'Every purchase and return line from SOFTECH with full filters (supplier, item, buyer, margin, effective cost, value, bonus, damaged or normal return) and a totals bar for all matches.'),
        'audience': T('المشتريات والمدير.', 'Purchasing and admins.'),
        'tips': [T('«التكلفة الفعلية» = بعد البونص والضريبة؛ هي الأصدق لمقارنة الموردين.', '"Effective cost" = after bonus and VAT; it is the fairest way to compare suppliers.'), _HUB_NOTE],
        'related': ['purchasing.foc'],
        'tour': [
            {'target': 'purchasing-history-totals', 'text': T('إجماليات كل النتائج المطابقة: السطور، صافي المشتريات، البونص، الضريبة، المرتجعات والهامش.',
                                              'Totals for all matches: lines, net purchases, bonus, VAT, returns and margin.'),
             'more': T('الإجماليات محسوبة على كل السطور المطابقة للفلاتر، حتى لو الجدول عارض أول 1,000 بس.\n'
                       '• فيها: السطور والفواتير، صافي المشتريات، البونص بالوحدات، الضريبة، المرتجعات ومتوسط الهامش.\n'
                       '• القيم الكبيرة مكتوبة بالألف (K).',
                       'Totals are calculated over all lines matching the filters, even when the table shows only the first 1,000.\n'
                       '• They include: lines and invoices, net purchases, bonus units, VAT, returns and average margin.\n'
                       '• Large values are shown in thousands (K).')},
            {'target': 'purchasing-history-search', 'text': T('بحث عام باسم أو كود الصنف أو رقم الفاتورة، وبجانبه أكواد المورد والصنف والمشتري.',
                                              'General search by item name or code or invoice number, next to supplier, item and buyer codes.'),
             'more': T('«بحث عام» بالاسم أو كود الصنف أو رقم الفاتورة، وجنبه «كود المورد» و«كود الصنف» و«كود المشتري» والترتيب.\n'
                       '• Enter في خانة البحث بيطبّق على طول.\n'
                       '• الأكواد هي أكواد SOFTECH.',
                       '"General search" by item name or code or invoice number, next to "Supplier code", "Item code", "Buyer code" and ordering.\n'
                       '• Enter in the search box applies at once.\n'
                       '• The codes are SOFTECH codes.')},
            {'target': 'purchasing-history-ranges', 'text': T('حدود رقمية: الهامش، التكلفة الفعلية، والقيمة.',
                                              'Numeric ranges: margin, effective cost and value.'),
             'more': T('حدود من/إلى لـ: الهامش %، التكلفة الفعلية، والقيمة.\n'
                       '• مثال: هامش من 0 لـ 5 يطلّع المشتريات اللي هامشها ضعيف.\n'
                       '• «التكلفة الفعلية» = بعد البونص والضريبة، وهي الأصدق للمقارنة.',
                       'From/to limits for: margin %, effective cost, and value.\n'
                       '• Example: margin 0 to 5 shows purchases with a weak margin.\n'
                       '• "Effective cost" = after bonus and VAT, the fairest for comparison.')},
            {'target': 'purchasing-history-toggles', 'text': T('اختر نوع الحركة، أو «🎁 بونص فقط»، أو نوع المرتجع (تالف/عادي).',
                                              'Pick the movement type, "🎁 Bonus only", or the return type (damaged/normal).'),
             'more': T('• «كل الحركات» أو «مشتريات فقط» أو «مرتجعات فقط».\n'
                       '• «🎁 بونص فقط» للسطور اللي فيها بضاعة مجانية.\n'
                       '• نوع المرتجع: ⚠️ تالف أو ↩️ عادي — الضغطة التانية بتلغيه.',
                       '• "All movements", "Purchases only" or "Returns only".\n'
                       '• "🎁 Bonus only" for lines with free goods.\n'
                       '• Return type: ⚠️ damaged or ↩️ normal — a second click clears it.')},
            {'target': 'purchasing-history-apply', 'text': T('«بحث» يطبّق الفلاتر، و«إعادة ضبط» بجانبه يمسحها.',
                                              '"Search" applies the filters; "Reset" next to it clears them.'),
             'more': T('«بحث» بيطبّق كل الفلاتر مرة واحدة ويحدّث الإجماليات والجدول.\n'
                       '• جنبه عدد الفلاتر النشطة.\n'
                       '• «إعادة ضبط» بيمسح كل الفلاتر ويرجّع القائمة الكاملة.',
                       '"Search" applies all filters at once and updates the totals and table.\n'
                       '• Beside it is the number of active filters.\n'
                       '• "Reset" clears all filters and brings back the full list.')},
            {'target': 'purchasing-history-table', 'text': T('سطور الشراء والمرتجعات؛ يُعرض أول 1,000 سطر فقط.',
                                              'The purchase and return lines; only the first 1,000 lines are shown.'),
             'more': T('لكل سطر: التاريخ، رقم الفاتورة، الفرع، المورد وفئته، الصنف، الاتجاه، الكمية والبونص، السعر والتكلفة الفعلية، الهامش والضريبة ونوع المرتجع.\n'
                       '• الجدول بيعرض أول 1,000 سطر؛ ضيّق الفلاتر لو محتاج تشوف الباقي.\n'
                       '• البيانات من SOFTECH للقراءة بس.',
                       'For each line: date, invoice number, branch, supplier and category, item, direction, quantity and bonus, price and effective cost, margin, VAT and return type.\n'
                       '• The table shows the first 1,000 lines; narrow the filters to see the rest.\n'
                       '• The data comes from SOFTECH and is read-only.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'purchasing.segments',
        'routes': ['/procurement/segments'],
        'title': T('تصنيف الموردين', 'Supplier segmentation'),
        'summary': T('توزيع المشتريات على فئات الموردين (موزّع رئيسي، مصنع…) مبني على أكواد SOFTECH، مع قيمة الشراء والفواتير ومعدل البونص والمرتجعات لكل مورد. «تعديل» يغيّر فئة مورد يدوياً ويثبتها.',
                     'Purchases split by supplier category (main distributor, manufacturer…) based on SOFTECH codes, with value, invoices, bonus and return rate per supplier. "Edit" changes a supplier\'s category manually and pins it.'),
        'audience': T('المشتريات والمدير.', 'Purchasing and admins.'),
        'tips': [T('التعديل اليدوي يوقف التصنيف التلقائي لهذا المورد.', 'A manual edit stops automatic classification for that supplier.'), _HUB_NOTE],
        'related': ['purchasing.categories'],
        'tour': [
            {'target': 'purchasing-segments-cards', 'text': T('بطاقة لكل فئة موردين بنصيبها من المشتريات؛ اضغطها لتصفية القائمة.',
                                              'One card per supplier category with its share of purchases; click it to filter the list.'),
             'more': T('كل بطاقة فئة موردين (موزّع رئيسي، مصنع…) بقيمة مشترياتها ونصيبها.\n'
                       '• الضغط على بطاقة بيفلتر قائمة الموردين تحت على الفئة دي، والضغطة التانية بتلغي.\n'
                       '• الفئات نفسها بتتدار من «فئات وقواعد تصنيف الموردين».',
                       'Each card is a supplier category (main distributor, manufacturer…) with its purchase value and share.\n'
                       '• Clicking a card filters the supplier list below to that category; clicking again clears it.\n'
                       '• The categories themselves are managed in "Supplier categories & rules".')},
            {'target': 'purchasing-segments-distribution', 'text': T('شريط توزيع قيمة المشتريات على الفئات.',
                                              'A bar showing how purchase value splits across categories.'),
             'more': T('شريط ملوّن بيوضح كل فئة واخدة كام في المية من قيمة المشتريات.\n'
                       '• يوضح بسرعة إحنا معتمدين على الموزعين ولا الشراء المباشر من المصانع.\n'
                       '• النسبة مكتوبة جنب كل لون تحت الشريط.',
                       'A coloured bar shows what percent of purchase value each category takes.\n'
                       '• It shows at a glance whether we rely on distributors or buy direct from manufacturers.\n'
                       '• The percentage is written next to each colour below the bar.')},
            {'target': 'purchasing-segments-search', 'text': T('ابحث عن مورد بالاسم أو الكود.',
                                              'Search for a supplier by name or code.'),
             'more': T('اكتب اسم المورد أو كوده والقائمة بتتصفّى.\n'
                       '• البحث بيشتغل مع فلتر الفئة لو مختار؛ «إلغاء الفلتر» بيرجّع الكل.\n'
                       '• مفيد قبل ما تعدّل فئة مورد معيّن.',
                       'Type the supplier name or code and the list filters.\n'
                       '• Search works with the category filter if one is selected; "Clear filter" brings back all.\n'
                       "• Useful before changing a particular supplier's category.")},
            {'target': 'purchasing-segments-list', 'text': T('الموردون مع الفئة وأكواد SOFTECH وقيمة الشراء ومعدل البونص والمرتجعات، ونوع التصنيف يدوي أو آلي.',
                                              'Suppliers with category, SOFTECH codes, purchase value, bonus and return rates, and manual or automatic type.'),
             'more': T('لكل مورد: الفئة، أكواد SOFTECH، قيمة الشراء والفواتير، معدل FOC (البونص)، معدل الإرجاع، والنوع.\n'
                       '• النوع «آلي» = اتصنّف بالقواعد، «يدوي» = حد ثبّته بإيده.\n'
                       '• معدل إرجاع عالي يستاهل مراجعة مع المورد.',
                       'For each supplier: category, SOFTECH codes, purchase value and invoices, FOC (bonus) rate, return rate, and type.\n'
                       '• Type "automatic" = classified by the rules, "manual" = someone pinned it.\n'
                       '• A high return rate is worth reviewing with the supplier.')},
            {'target': 'purchasing-segments-edit', 'text': T('«تعديل» يغيّر فئة المورد يدوياً ويثبتها؛ يظهر للمدير فقط.',
                                              '"Edit" changes a supplier\'s category manually and pins it; shown to admins only.'),
             'more': T('بيفتح نافذة تغيّر فيها فئة المورد وتكتب ملاحظة.\n'
                       '• التعديل اليدوي بيثبّت الفئة: «إعادة تصنيف الموردين» مش هتغيّرها بعد كده.\n'
                       '• الزرار والعمود بيظهروا للمدير بس.',
                       "Opens a window to change the supplier's category and write a note.\n"
                       '• A manual edit pins the category: "Reclassify suppliers" will not change it afterwards.\n'
                       '• The button and column show for admins only.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'purchasing.categories',
        'routes': ['/procurement/categories'],
        'title': T('فئات وقواعد تصنيف الموردين', 'Supplier categories & rules'),
        'summary': T('إدارة فئات الموردين (الاسم، الكود، اللون، الترتيب، الفئة الافتراضية) وقواعد ربط أكواد SOFTECH (نوع الشخص ptcode + التصنيف ptclassifcode) بالفئات بأولوية (الأقل يفوز). «إعادة تصنيف الموردين» يطبق القواعد من جديد.',
                     'Manage supplier categories (name, code, colour, order, default) and the rules mapping SOFTECH codes (person type ptcode + classification ptclassifcode) to categories with priority (lowest wins). "Reclassify suppliers" re-applies the rules.'),
        'audience': T('المدير والمشتريات.', 'Admins and purchasing.'),
        'tips': [T('الفئة «الموزّع الرئيسي/المصنع» تُستخدم في تقارير الصلاحية — صنّف الموردين بدقة.', 'The "main distributor/manufacturer" category feeds the expiry reports — classify suppliers carefully.')],
        'related': ['purchasing.segments', 'batches.main'],
        'tour': [
            {'target': 'purchasing-categories-reclassify', 'text': T('«🔄 إعادة تصنيف الموردين» يعيد تطبيق القواعد في الخلفية.',
                                              '"🔄 Reclassify suppliers" re-applies the rules in the background.'),
             'more': T('بيطبّق قواعد التصنيف من جديد على كل الموردين في الخلفية — النتيجة بتتحدّث خلال دقيقة تقريباً.\n'
                       '• استخدمه بعد ما تضيف أو تعدّل قاعدة.\n'
                       '• الموردين المثبّتين يدوياً مش بيتغيّروا.',
                       'Re-applies the classification rules to all suppliers in the background — results update within about a minute.\n'
                       '• Use it after adding or editing a rule.\n'
                       '• Manually pinned suppliers are not changed.')},
            {'target': 'purchasing-categories-list', 'text': T('الفئات: الاسم، الكود، عدد الموردين والقواعد، والحالة.',
                                              'The categories: name, code, supplier and rule counts, and status.'),
             'more': T('لكل فئة: الترتيب، الاسم، الكود، عدد الموردين، عدد القواعد، والحالة.\n'
                       '• من السطر تقدر تعدّل أو تحذف الفئة (الحذف بيسأل تأكيد).\n'
                       '• فئة «الموزّع الرئيسي/المصنع» بتدخل في تقارير الصلاحية، فصنّف بدقة.',
                       'For each category: order, name, code, supplier count, rule count, and status.\n'
                       '• From the row you can edit or delete the category (delete asks for confirmation).\n'
                       '• The "main distributor/manufacturer" category feeds the expiry reports, so classify carefully.')},
            {'target': 'purchasing-categories-new', 'text': T('«+ فئة جديدة» لإضافة فئة بالاسم والكود واللون والترتيب.',
                                              '"+ New category" adds one with name, code, colour and order.'),
             'more': T('بيفتح نموذج: الاسم، الكود، اللون، الترتيب، والحالة.\n'
                       '• اللون بيظهر في بطاقات وشريط «تصنيف الموردين».\n'
                       '• الفئة الجديدة فاضية لحد ما تعمل لها قاعدة أو تعدّل موردين يدوياً.',
                       'Opens a form: name, code, colour, order, and status.\n'
                       '• The colour shows in the "Supplier segmentation" cards and bar.\n'
                       '• A new category is empty until you create a rule for it or edit suppliers manually.')},
            {'target': 'purchasing-categories-rules', 'text': T('قواعد ربط نوع الشخص والتصنيف في SOFTECH بالفئات؛ الأولوية الأقل تفوز.',
                                              'Rules mapping SOFTECH person type and classification to categories; the lowest priority wins.'),
             'more': T('كل قاعدة بتربط «نوع الشخص» (ptcode) و«التصنيف» (ptclassifcode) في SOFTECH بفئة.\n'
                       '• لو أكتر من قاعدة تنطبق على مورد، صاحبة الأولوية الأقل هي اللي بتكسب.\n'
                       '• تقدر تعدّل أو تحذف أي قاعدة من سطرها.',
                       'Each rule maps a SOFTECH "person type" (ptcode) and "classification" (ptclassifcode) to a category.\n'
                       '• If several rules match a supplier, the one with the lowest priority wins.\n'
                       '• You can edit or delete any rule from its row.')},
            {'target': 'purchasing-categories-new-rule', 'text': T('«+ قاعدة جديدة» لإضافة قاعدة ربط.',
                                              '"+ New rule" adds a mapping rule.'),
             'more': T('بيفتح نموذج القاعدة: نوع الشخص، التصنيف، الفئة، الأولوية، والحالة.\n'
                       '• القاعدة مش بتتطبّق على الموردين الحاليين لوحدها — اضغط «🔄 إعادة تصنيف الموردين» بعدها.\n'
                       '• خلّي الأولوية أقل للقواعد الأدق.',
                       'Opens the rule form: person type, classification, category, priority, and status.\n'
                       '• The rule does not apply to existing suppliers by itself — press "🔄 Reclassify suppliers" afterwards.\n'
                       '• Give more specific rules a lower priority.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'purchasing.foc',
        'routes': ['/procurement/foc'],
        'title': T('البونص (FOC) والتكلفة الفعلية', 'Bonus (FOC) & effective cost'),
        'summary': T('تحليل التكلفة الحقيقية والكفاءة الشرائية.', 'Analysis of real cost and buying efficiency.'),
        'audience': T('المشتريات والمدير.', 'Purchasing and admins.'),
        'tabs': [
            {'key': 'foc', 'title': T('🎁 تحليل FOC', '🎁 FOC analysis'), 'body': T('نسبة البضاعة المجانية، أكثر الموردين كرماً، الاتجاه الشهري، ومقارنة التكلفة الاسمية بالفعلية بعد البونص والضريبة.', 'Free-goods rate, most generous suppliers, the monthly trend, and nominal vs effective cost after bonus and VAT.')},
            {'key': 'expiry', 'title': T('⚠️ مرتجعات التالف', '⚠️ Damaged returns'), 'body': T('المرتجعات التالفة مقابل العادية، نسبتها وقيمتها، وأكثر الأصناف والفروع في مرتجعات التالف.', 'Damaged vs normal returns, their rate and value, and the items and branches with the most damaged returns.')},
            {'key': 'tax', 'title': T('🧾 العبء الضريبي', '🧾 Tax burden'), 'body': T('إجمالي ضريبة القيمة المضافة على المشتريات ونسبتها واتجاهها.', 'Total VAT on purchases, its rate and trend.')},
        ],
        'tips': [_HUB_NOTE],
        'tour': [
            {'target': 'purchasing-foc-kpis', 'text': T('ملخص: البضاعة المجانية، نسبة مرتجعات التالف، نسبة الضريبة، وفرق التكلفة الفعلية.',
                                              'Summary: free goods, damaged-return rate, VAT rate, and the effective-cost difference.'),
             'more': T('• «البضاعة المجانية (بونص)»: الوحدات المجانية ونسبتها من الكمية.\n'
                       '• «مرتجعات التالف»: نسبة التالف من كل المرتجعات (بالأحمر فوق 30%). «نسبة الضريبة (VAT)» على المشتريات.\n'
                       '• «فرق التكلفة الفعلية»: التكلفة بعد البونص والضريبة مقارنة بسعر الوحدة.',
                       '• "Free goods (bonus)": free units and their share of quantity.\n'
                       '• "Damaged returns": damaged share of all returns (red above 30%). "VAT rate" on purchases.\n'
                       '• "Effective cost difference": cost after bonus and VAT compared with the unit price.')},
            {'target': 'purchasing-foc-tabs', 'text': T('اختر: «🎁 تحليل FOC» أو «⚠️ مرتجعات التالف» أو «🧾 العبء الضريبي».',
                                              'Pick: "🎁 FOC analysis", "⚠️ Damaged returns" or "🧾 Tax burden".'),
             'more': T('• «🎁 تحليل FOC»: البونص والموردين الأكرم ومقارنة التكلفة.\n'
                       '• «⚠️ مرتجعات التالف»: التالف مقابل العادي، وأكتر الأصناف والفروع.\n'
                       '• «🧾 العبء الضريبي»: الضريبة على المشتريات واتجاهها.',
                       '• "🎁 FOC analysis": bonus, most generous suppliers and cost comparison.\n'
                       '• "⚠️ Damaged returns": damaged versus normal, and the top items and branches.\n'
                       '• "🧾 Tax burden": VAT on purchases and its trend.')},
            {'target': 'purchasing-foc-suppliers', 'text': T('أكثر الموردين منحاً للبونص مع نسبة FOC لكل منهم.',
                                              'The suppliers giving the most bonus, with each one\'s FOC rate.'),
             'more': T('أعلى 10 موردين في البونص مع نسبة FOC لكل واحد.\n'
                       '• البونص بيقلّل التكلفة الفعلية، فمورد سعره أعلى ممكن يطلع أرخص بعد البونص.\n'
                       '• قارن دايماً بالتكلفة الفعلية مش بالسعر المكتوب بس.',
                       "The top 10 suppliers by bonus, with each one's FOC rate.\n"
                       '• Bonus lowers the effective cost, so a supplier with a higher price may come out cheaper after bonus.\n'
                       '• Always compare on effective cost, not just the listed price.')},
            {'target': 'purchasing-foc-cost', 'text': T('مقارنة متوسط سعر الوحدة الاسمي بالتكلفة الفعلية بعد البونص والضريبة.',
                                              'Average nominal unit price compared with effective cost after bonus and VAT.'),
             'more': T('تلات أرقام: «متوسط سعر الوحدة (اسمي)»، «التكلفة الفعلية (بعد FOC + ضريبة)»، و«الفرق (تأثير FOC)».\n'
                       '• فرق بالسالب أخضر = البونص مخفّض التكلفة فعلاً.\n'
                       '• فرق موجب أحمر = الضريبة أكبر من أثر البونص.',
                       'Three figures: "Average unit price (nominal)", "Effective cost (after FOC + VAT)", and "Difference (FOC effect)".\n'
                       '• A negative difference in green = the bonus really lowered the cost.\n'
                       '• A positive difference in red = VAT outweighs the bonus effect.')},
            {'target': 'purchasing-foc-expiry', 'text': T('في تبويب «⚠️ مرتجعات التالف»: ملخص المرتجعات التالفة مقابل العادية.',
                                              'In the "⚠️ Damaged returns" tab: damaged versus normal returns summary.'),
             'more': T('ملخص المرتجعات التالفة مقابل العادية: العدد والقيمة والنسبة.\n'
                       '• تحتها أكتر الأصناف والفروع في مرتجعات التالف.\n'
                       '• تالف كتير في صنف = بنشتري أكتر من اللي بيتباع قبل الصلاحية.',
                       'Summary of damaged versus normal returns: count, value and share.\n'
                       '• Below are the items and branches with the most damaged returns.\n'
                       '• Many damaged returns on an item = we buy more than sells before expiry.')},
            {'target': 'purchasing-foc-tax', 'text': T('في تبويب «🧾 العبء الضريبي»: إجمالي الضريبة على المشتريات ونسبتها.',
                                              'In the "🧾 Tax burden" tab: total VAT on purchases and its rate.'),
             'more': T('إجمالي ضريبة القيمة المضافة على المشتريات ونسبتها من القيمة واتجاهها.\n'
                       '• بيساعد في التخطيط المالي ومقارنة الموردين.\n'
                       '• الأرقام للفترة والفلاتر المختارة في الشريط اللي فوق.',
                       'Total VAT on purchases, its share of value and its trend.\n'
                       '• It helps financial planning and supplier comparison.\n'
                       '• Figures follow the period and filters chosen in the top bar.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'purchasing.suppliers',
        'routes': ['/procurement/suppliers', '/procurement/suppliers/:supplierCode'],
        'title': T('أداء الموردين', 'Supplier performance'),
        'summary': T('ترتيب الموردين بالدرجة (هامش الربح، التوافر/التكرار، معدل المرتجعات، استقرار الأسعار) مع صفحة لكل مورد: المشتريات الشهرية، الأصناف، الفروع المُزوّدة، وتفصيل الدرجة.',
                     'Suppliers ranked by score (margin, availability/frequency, return rate, price stability) with a page per supplier: monthly purchases, items, branches supplied, and the score breakdown.'),
        'audience': T('المشتريات والمدير.', 'Purchasing and admins.'),
        'related': ['purchasing.overview'],
        'tour': [
            {'target': 'purchasing-suppliers-search', 'text': T('ابحث باسم أو كود المورد.',
                                              'Search by supplier name or code.'),
             'more': T('اكتب اسم المورد أو كوده والجدول بيتصفّى.\n'
                       '• عدد الموردين مكتوب جنب العنوان.\n'
                       '• «🔄 تحديث» بيعيد تحميل البيانات.',
                       'Type the supplier name or code and the table filters.\n'
                       '• The supplier count is shown beside the title.\n'
                       '• "🔄 Refresh" reloads the data.')},
            {'target': 'purchasing-suppliers-sort', 'text': T('الترتيب (الدرجة وغيرها).',
                                              'Sort (score and more).'),
             'more': T('رتّب بـ: الدرجة، الأعلى شراءً، أعلى هامش، أقل مرتجعات، أو شراء 30 يوم.\n'
                       '• «الدرجة» بتجمع الهامش والتوافر والمرتجعات واستقرار الأسعار.\n'
                       '• جرّب «أقل مرتجعات» لما تختار مورد لصنف حساس.',
                       'Sort by: score, highest purchases, highest margin, fewest returns, or 30-day purchases.\n'
                       '• "Score" combines margin, availability, returns and price stability.\n'
                       '• Try "Fewest returns" when choosing a supplier for a sensitive item.')},
            {'target': 'purchasing-suppliers-table', 'text': T('الموردين ودرجة أدائهم.',
                                              'The suppliers and their performance score.'),
             'more': T('لكل مورد: الاسم والكود، الدرجة، شراء 30 و365 يوم، الهامش، وباقي المؤشرات.\n'
                       '• الدرجة العالية = مورد مربح ومنتظم ومرتجعاته قليلة.\n'
                       '• الأرقام من مشتريات SOFTECH.',
                       'For each supplier: name and code, score, 30- and 365-day purchases, margin, and the other indicators.\n'
                       '• A high score = a profitable, regular supplier with few returns.\n'
                       '• Figures come from SOFTECH purchases.')},
            {'target': 'purchasing-suppliers-row', 'text': T('اضغط على مورد لتفصيل درجته.',
                                              'Click a supplier for its score breakdown.'),
             'more': T('الضغط على مورد بيفتح صفحته: أول وآخر شراء، المشتريات الشهرية، الأصناف، الفروع اللي بيورّد لها.\n'
                       '• «تفصيل الدرجة»: هامش الربح ×0.30، التوافر ×0.25، المرتجعات ×0.25، استقرار الأسعار ×0.20.\n'
                       '• يوضح المورد ضعيف في أنهي نقطة بالظبط.',
                       'Clicking a supplier opens its page: first and last purchase, monthly purchases, items, branches supplied.\n'
                       '• "Score breakdown": margin ×0.30, availability ×0.25, returns ×0.25, price stability ×0.20.\n'
                       '• It shows exactly where the supplier is weak.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'purchasing.margins',
        'routes': ['/procurement/margins'],
        'title': T('الهوامش ومراقبة الأسعار', 'Margins & price control'),
        'summary': T('تحليل هوامش المشتريات ومراقبة تذبذب أسعار الشراء.', 'Purchase margin analysis and purchase-price volatility monitoring.'),
        'audience': T('المشتريات والمدير.', 'Purchasing and admins.'),
        'tabs': [
            {'key': 'margin', 'title': T('تحليل الهوامش', 'Margin analysis'), 'body': T('توزيع الهامش، أدنى الأصناف هامشاً، والهوامش حسب المورد للفترة المختارة.', 'Margin distribution, lowest-margin items, and margins by supplier for the chosen period.')},
            {'key': 'price', 'title': T('مراقبة الأسعار', 'Price control'), 'body': T('أصناف تذبذب سعر شرائها أكثر من الحد: أدنى وأعلى ومتوسط وآخر سعر — فرصة تفاوض أو خطأ إدخال.', 'Items whose purchase price varies more than the threshold: min, max, average and last price — a negotiation opportunity or an entry error.')},
        ],
        'related': ['pricing.approvals'],
        'tour': [
            {'target': 'purchasing-margins-period', 'text': T('الفترة: 30 أو 90 أو 180 أو 365 يوماً (في تبويب «تحليل الهوامش»).',
                                              'The period: 30, 90, 180 or 365 days (in the "Margin analysis" tab).'),
             'more': T('اختار 30 أو 90 أو 180 أو 365 يوم — كل أرقام «تحليل الهوامش» بتتحسب على الفترة دي.\n'
                       '• الأزرار دي بتظهر في تبويب «تحليل الهوامش» بس.\n'
                       '• فترة أطول بتدّي صورة أثبت، وأقصر بتكشف التغيير الحديث.',
                       'Pick 30, 90, 180 or 365 days — all "Margin analysis" figures use this period.\n'
                       '• These buttons show in the "Margin analysis" tab only.\n'
                       '• A longer period gives a steadier picture; a shorter one reveals recent change.')},
            {'target': 'purchasing-margins-tabs', 'text': T('«تحليل الهوامش» أو «مراقبة الأسعار».',
                                              '"Margin analysis" or "Price control".'),
             'more': T('• «تحليل الهوامش»: متوسط الهامش وأضعف الأصناف والهوامش حسب المورد.\n'
                       '• «مراقبة الأسعار»: أصناف سعر شرائها بيتذبذب أكتر من حد تحدده.\n'
                       '• التذبذب ممكن يكون فرصة تفاوض أو غلطة إدخال.',
                       '• "Margin analysis": average margin, weakest items and margins by supplier.\n'
                       '• "Price control": items whose purchase price varies more than a threshold you set.\n'
                       '• Volatility may be a negotiation opportunity or an entry error.')},
            {'target': 'purchasing-margins-kpis', 'text': T('متوسط الهامش وصافي قيمة المشتريات وعدد السطور للفترة.',
                                              'Average margin, net purchase value and line count for the period.'),
             'more': T('«متوسط الهامش» (بالأحمر لو أقل من 15%)، «صافي قيمة المشتريات»، وعدد السطور للفترة.\n'
                       '• لو المتوسط نازل، شوف أدنى الأصناف هامشاً تحت.\n'
                       '• الهامش هنا هامش المشتريات (سعر البيع مقابل تكلفة الشراء).',
                       '"Average margin" (red below 15%), "Net purchase value", and line count for the period.\n'
                       '• If the average is falling, check the lowest-margin items below.\n'
                       '• Margin here is the purchase margin (selling price versus purchase cost).')},
            {'target': 'purchasing-margins-low', 'text': T('الأصناف ذات أدنى هامش مع قيمتها.',
                                              'The lowest-margin items with their value.'),
             'more': T('الأصناف اللي هامشها أقل حاجة: الكود والهامش % والقيمة.\n'
                       '• صنف قيمته عالية وهامشه ضعيف أولى بالتفاوض أو مراجعة التسعير.\n'
                       '• أي تغيير في سعر البيع بيمشي من «موافقات الأسعار»، مش من هنا.',
                       'The items with the lowest margin: code, margin % and value.\n'
                       '• A high-value item with a weak margin deserves negotiation or a pricing review.\n'
                       '• Any selling-price change goes through "Pricing approvals", not here.')},
            {'target': 'purchasing-margins-suppliers', 'text': T('الهوامش حسب المورد للفترة المختارة.',
                                              'Margins by supplier for the chosen period.'),
             'more': T('لكل مورد: الكود، متوسط الهامش، صافي القيمة، وعدد الأصناف.\n'
                       '• قارن الموردين اللي بيبيعوا أصناف شبه بعض.\n'
                       '• مورد هامشه ضعيف على حجم كبير بيأثر على الربح كله.',
                       'For each supplier: code, average margin, net value, and item count.\n'
                       '• Compare suppliers that sell similar items.\n'
                       '• A supplier with a weak margin on large volume affects overall profit.')},
            {'target': 'purchasing-margins-price-filters', 'text': T('في «مراقبة الأسعار»: حدد حد التذبذب وأدنى عدد مشتريات ثم «تطبيق».',
                                              'In "Price control": set the volatility threshold and minimum purchases, then "Apply".'),
             'more': T('حدد «حد التذبذب المئوي» و«أدنى عدد مشتريات» واضغط «تطبيق».\n'
                       '• مثال: تذبذب 10% وأدنى 3 مشتريات يطلّع الأصناف اللي سعرها اتغيّر كتير بين فواتير متكررة.\n'
                       '• لكل صنف: أدنى وأعلى ومتوسط وآخر سعر.',
                       'Set the "Volatility threshold %" and "Minimum purchases" and press "Apply".\n'
                       '• Example: 10% volatility and at least 3 purchases shows items whose price changed a lot across repeated invoices.\n'
                       '• For each item: minimum, maximum, average and last price.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'purchasing.optimization',
        'routes': ['/procurement/optimization', '/procurement/mappings'],
        'title': T('تحسين المشتريات والتنبيهات', 'Procurement optimization & alerts'),
        'summary': T('أين نوفّر: الموردون الموصى بهم والمحذورون، فرص توفير السعر للأصناف التي لها عدة موردين، خريطة المورد-صنف، وتنبيهات المشتريات.',
                     'Where to save: recommended and avoided suppliers, price-saving opportunities for items with several suppliers, the supplier-item map, and purchasing alerts.'),
        'audience': T('المشتريات والمدير.', 'Purchasing and admins.'),
        'tabs': [
            {'key': 'optimization', 'title': T('🎯 التحسين', '🎯 Optimization'), 'body': T('الموردون الموصى بهم (هامش عالٍ) والمحذورون (مرتجعات عالية)، وفرص التوفير: أقل وأعلى سعر لنفس الصنف من موردين مختلفين.', 'Recommended suppliers (high margin) and avoided ones (high returns), and savings: lowest vs highest price for the same item from different suppliers.')},
            {'key': 'mapping', 'title': T('🔗 خريطة المورد-صنف', '🔗 Supplier-item map'), 'body': T('لكل صنف: مورّدوه، درجة الثقة، المورد الرئيسي، متوسط السعر وتذبذبه وآخر شراء.', 'Per item: its suppliers, confidence, the main supplier, average price, volatility and last purchase.')},
            {'key': 'alerts', 'title': T('🚨 التنبيهات', '🚨 Alerts'), 'body': T('تنبيهات حرجة/تحذير/معلومة (ارتفاع سعر، تركّز مورد…) — «تم الحل» بعد المعالجة.', 'Critical/warning/info alerts (price jump, supplier concentration…) — mark "resolved" after handling.')},
        ],
        'related': ['purchasing.overview'],
        'tour': [
            {'target': 'purchasing-optimization-period', 'text': T('الفترة: 30 أو 90 أو 365 يوماً (في تبويب «🎯 التحسين»).',
                                              'The period: 30, 90 or 365 days (in the "🎯 Optimization" tab).'),
             'more': T('اختار 30 أو 90 أو 365 يوم لتبويب «🎯 التحسين».\n'
                       '• بتغيّر الموردين الموصى بهم وفرص التوفير حسب الفترة.\n'
                       '• مش موجودة في تبويبي الخريطة والتنبيهات.',
                       'Pick 30, 90 or 365 days for the "🎯 Optimization" tab.\n'
                       '• It changes the recommended suppliers and savings opportunities by period.\n'
                       '• It is not shown in the map and alerts tabs.')},
            {'target': 'purchasing-optimization-tabs', 'text': T('«🎯 التحسين» أو «🔗 خريطة المورد-صنف» أو «🚨 التنبيهات».',
                                              '"🎯 Optimization", "🔗 Supplier-item map" or "🚨 Alerts".'),
             'more': T('• «🎯 التحسين»: موردين نفضّلهم ونتجنبهم وفرص التوفير.\n'
                       '• «🔗 خريطة المورد-صنف»: مين بيورّد كل صنف وبكام.\n'
                       '• «🚨 التنبيهات»: تحذيرات المشتريات اللي محتاجة تصرّف.',
                       '• "🎯 Optimization": suppliers to prefer and avoid, and savings opportunities.\n'
                       '• "🔗 Supplier-item map": who supplies each item and at what price.\n'
                       '• "🚨 Alerts": purchasing warnings that need action.')},
            {'target': 'purchasing-optimization-suppliers', 'text': T('الموردون الموصى بهم والمحذورون.',
                                              'Recommended and avoided suppliers.'),
             'more': T('«✅ الموردون الموصى بهم» (هامش عالي) والمحذورون (مرتجعات عالية).\n'
                       '• اضغط أي مورد يفتح صفحة أدائه.\n'
                       '• القرار النهائي بتاعك — دي توصيات من الأرقام.',
                       '"✅ Recommended suppliers" (high margin) and avoided ones (high returns).\n'
                       '• Click any supplier to open its performance page.\n'
                       '• The final decision is yours — these are recommendations from the numbers.')},
            {'target': 'purchasing-optimization-savings', 'text': T('فرص توفير السعر لأصناف لها أكثر من مورد.',
                                              'Price-saving opportunities for items with more than one supplier.'),
             'more': T('أصناف بتتشرى من أكتر من مورد: عدد الموردين، أقل سعر وأعلى سعر.\n'
                       '• الفرق الكبير = ممكن نوفّر لو اشترينا من الأرخص.\n'
                       '• اتأكد من البونص والصلاحية والتوافر قبل ما تغيّر المورد.',
                       'Items bought from more than one supplier: supplier count, lowest and highest price.\n'
                       '• A big gap = we may save by buying from the cheapest.\n'
                       '• Check bonus, expiry and availability before switching supplier.')},
            {'target': 'purchasing-optimization-mapping-filters', 'text': T('في «🔗 خريطة المورد-صنف»: ابحث بالصنف أو المورد، حد الثقة، أو «مورد رئيسي فقط».',
                                              'In "🔗 Supplier-item map": search by item or supplier, confidence threshold, or "Main supplier only".'),
             'more': T('ابحث بالصنف أو المورد، أو بكود المورد، وحدد «حد الثقة» أو «مورد رئيسي فقط»، واضغط «🔍 بحث».\n'
                       '• لكل صنف: مورّدينه، درجة الثقة، الرئيسي، متوسط السعر وتذبذبه وآخر شراء.\n'
                       '• مفيد لما صنف ينقص وعايز تعرف تطلبه من مين.',
                       'Search by item or supplier, or by supplier code, set a "Confidence threshold" or "Main supplier only", and press "🔍 Search".\n'
                       '• For each item: its suppliers, confidence, the main one, average price, volatility and last purchase.\n'
                       '• Useful when an item runs short and you want to know whom to order from.')},
            {'target': 'purchasing-optimization-alert-filters', 'text': T('في «🚨 التنبيهات»: صفِّ بالمستوى والحالة؛ «حل ✓» يغلق التنبيه بعد معالجته.',
                                              'In "🚨 Alerts": filter by severity and state; "Resolve ✓" closes an alert once handled.'),
             'more': T('فلتر بالمستوى (حرجة، تحذير، معلومة) والحالة («مفتوحة فقط» افتراضياً، أو محلولة، أو الكل).\n'
                       '• بعد ما تعالج التنبيه اضغط «حل ✓» — بيتقفل ويتسجّل إنه اتحل يدوياً.\n'
                       '• عدد التنبيهات مكتوب على الشمال.',
                       'Filter by severity (critical, warning, info) and state ("Open only" by default, resolved, or all).\n'
                       '• Once you have handled an alert, press "Resolve ✓" — it closes and is logged as resolved manually.\n'
                       '• The alert count is shown at the end of the bar.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
