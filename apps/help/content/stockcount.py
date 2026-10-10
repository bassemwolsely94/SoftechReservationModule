from . import T

MODULE = {
    'key': 'stockcount', 'group': 'operations', 'icon': '📦',
    'title': T('الجرد الفعلي', 'Physical stock count'),
    'summary': T(
        'جرد المخزون الفعلي ومقارنته بأرصدة SOFTECH. الفكرة الأساسية «اللقطة»: نجمّد الكميات المتوقعة من SOFTECH في لحظة بعينها، '
        'ثم نعدّ الأرفف (بورقة Excel أو مباشرةً من الموبايل بالمسح)، فيحسب النظام الفروق (زيادة / نقص / مطابق) مقابل اللقطة. '
        'الكمية المتوقعة لا تتغير بعد اللقطة حتى لو تغيّرت SOFTECH. التسوية نفسها تتم في SOFTECH من ملف «تصدير للتسوية».\n'
        'أنواع الجرد: مبني على الحركات (الأصناف التي تحركت بمستندات محددة في فترة)، شامل للفرع، مفلتر (تصنيف/أصناف محددة)، '
        'وجرد صلاحية (تدقيق مادي لتواريخ الانتهاء — يُنشأ من شاشة الدفعات والانتهاء).',
        'Count the physical stock and compare it with SOFTECH balances. The core idea is the "snapshot": we freeze the expected '
        'quantities from SOFTECH at one moment, then count the shelves (with an Excel sheet or directly on the phone by scanning), and '
        'the system calculates the variances (surplus / deficit / match) against the snapshot. Expected quantities never change after '
        'the snapshot, even if SOFTECH changes. The adjustment itself is done in SOFTECH from the "Export for adjustment" file.\n'
        'Count types: transaction-based (items moved by given documents in a period), full branch, filtered (category/specific items), '
        'and expiry audit (a physical check of expiry dates — created from the Batches & expiry screen).'),
    'workflows': [{
        'title': T('مراحل جلسة الجرد', 'Count session stages'),
        'model': 'stockcount.StockCountSession', 'field': 'status',
        'states': [
            {'key': 'draft', 'label': T('مسودة', 'Draft'), 'desc': T('الجلسة مُعدّة (النوع، الفرع، الفترة، الفلاتر). عاين الأصناف قبل اللقطة.', 'Set up (type, branch, period, filters). Preview items before the snapshot.'), 'next': ['snapshot_taken']},
            {'key': 'snapshot_taken', 'label': T('تم أخذ اللقطة', 'Snapshot taken'), 'desc': T('الكميات المتوقعة مجمّدة. ابدأ العد فوراً.', 'Expected quantities are frozen. Start counting right away.'), 'next': ['exported', 'uploaded']},
            {'key': 'exported', 'label': T('تم التصدير', 'Exported'), 'desc': T('ورقة العد الفارغة حُمّلت ووُزّعت على العادّين.', 'The blank count sheet was downloaded and handed to the counters.'), 'next': ['uploaded']},
            {'key': 'uploaded', 'label': T('تم رفع النتائج', 'Results uploaded'), 'desc': T('رُفع ملف الكميات المعدودة.', 'The counted quantities file was uploaded.'), 'next': ['variance_ready']},
            {'key': 'variance_ready', 'label': T('الفروق جاهزة', 'Variance ready'), 'desc': T('تقرير الفروق جاهز للمراجعة والتصدير للتسوية.', 'The variance report is ready to review and export for adjustment.'), 'next': ['closed']},
            {'key': 'closed', 'label': T('مغلق', 'Closed'), 'desc': T('أُغلقت نهائياً — لا تعديل بعد ذلك.', 'Closed for good — no more changes.')},
        ],
    }],
}

SCREENS = [
    {
        'key': 'stockcount.sessions',
        'routes': ['/stock-count'],
        'title': T('جرد المخزون', 'Stock count'),
        'summary': T('إنشاء جلسات الجرد ومتابعتها خطوة بخطوة عبر أربعة تبويبات: الجلسات ← اللقطة ← العد ← الفروق.',
                     'Create count sessions and run them step by step through four tabs: sessions → snapshot → count → variance.'),
        'audience': T('الصيادلة ومديرو الفروع والجودة والمشرفون.', 'Pharmacists, branch managers, quality and supervisors.'),
        'tabs': [
            {'key': 'sessions', 'title': T('📋 الجلسات', '📋 Sessions'),
             'body': T('كل جلسات الجرد بحالتها وعدد الأصناف والزيادة والنقص والمطابق. «جلسة جديدة»: اسم، كود الفرع، النوع، الفترة، أكواد المستندات، وفلاتر المستخدم والتصنيف. '
                       '«بدء سريع» يملأ الإعداد لحالات شائعة: مبيعات اليوم، مرتجعات الموردين اليوم، استلام تحويل وارد، مشتريات اليوم، تحويلات صادرة، جرد شامل للفرع. اختر جلسة لتنتقل لباقي التبويبات.',
                       'All count sessions with status, item count, surplus, deficit and matches. "New session": name, branch code, type, period, document codes, user and category filters. '
                       '"Quick start" fills the setup for common cases: today\'s sales, today\'s supplier returns, incoming transfers, today\'s purchases, outgoing transfers, full branch count. Pick a session to use the other tabs.')},
            {'key': 'snapshot', 'title': T('📸 اللقطة', '📸 Snapshot'),
             'body': T('«معاينة الأصناف» تعرض ما سيدخل الجرد بكمياته المتوقعة. «أخذ اللقطة» يجمّد الكميات المتوقعة من SOFTECH الآن — خذها مباشرةً قبل بدء العد وبعد توقف الحركة على الأرفف قدر الإمكان.',
                       '"Preview items" shows what will be counted with expected quantities. "Take snapshot" freezes the expected quantities from SOFTECH now — take it right before counting, ideally when shelf movement has stopped.')},
            {'key': 'count', 'title': T('📊 العد', '📊 Count'),
             'body': T('«تحميل ورقة العد الفارغة» (Excel/CSV) مرتبة بترتيب الأرفف، اكتب الكمية المعدودة في العمود الأصفر، ثم «رفع النتائج». الأصناف غير الموجودة في اللقطة يتم تجاهلها مع تنبيه. '
                       'بديل أسرع: الجرد المباشر من الموبايل (شاشة الجرد على /m) بالمسح.',
                       '"Download blank count sheet" (Excel/CSV) in shelf order, write the counted quantity in the yellow column, then "Upload results". Items not in the snapshot are ignored with a warning. '
                       'Faster alternative: count directly on the phone (the /m count screen) by scanning.')},
            {'key': 'variance', 'title': T('📉 الفروق', '📉 Variance'),
             'body': T('لكل صنف: المتوقع، المعدود، الفارق. صفِّ (الكل / زيادة فقط / نقص فقط / مطابق) وبحد أدنى للفارق. «تصدير للتسوية» يعطي ملف أصناف الزيادة والنقص لإدخال التسوية في SOFTECH. «إغلاق الجلسة» نهائي.',
                       'Per item: expected, counted, difference. Filter (all / surplus / deficit / match) with a minimum difference. "Export for adjustment" gives the surplus and deficit file to enter the adjustment in SOFTECH. "Close session" is final.')},
        ],
        'steps': [
            T('أنشئ الجلسة من «الجلسات» (أو «بدء سريع»).', 'Create the session from "Sessions" (or "Quick start").'),
            T('في «اللقطة» عاين ثم خذ اللقطة.', 'In "Snapshot" preview, then take the snapshot.'),
            T('في «العد» حمّل الورقة، عُدّ، وارفع النتائج — أو عُدّ من الموبايل.', 'In "Count" download the sheet, count and upload — or count on the phone.'),
            T('في «الفروق» راجع، أعد عدّ الأصناف ذات الفروق الكبيرة، صدّر للتسوية، ثم أغلق.', 'In "Variance" review, recount big differences, export for adjustment, then close.'),
        ],
        'tips': [
            T('مخازن الحجر (102، 103، 105) لا تدخل في أرصدة الجرد التشغيلي.', 'Quarantine stores (102, 103, 105) are excluded from operational count balances.'),
            T('أي بيع أو استلام بين اللقطة والعد يظهر كفرق — جمّد الحركة أو اجرد بسرعة بعد اللقطة.', 'Any sale or receipt between the snapshot and the count shows as a variance — pause movement or count quickly after the snapshot.'),
        ],
        'related': ['stockcount.mobile', 'batches.main', 'transfers.pick_zones'],
        'tour': [
            {'target': 'stockcount-sessions-tabs', 'text': T('خطوات الجرد بالترتيب: الجلسات ← اللقطة ← العد ← الفروق.',
                                              'The count steps in order: Sessions → Snapshot → Count → Variances.')},
            {'target': 'stockcount-sessions-new', 'text': T('«+ جلسة جديدة» يبدأ جرد لفرع.',
                                              '"+ New session" starts a count for a branch.')},
            {'target': 'stockcount-sessions-search', 'text': T('ابحث بالاسم أو الفرع.',
                                              'Search by name or branch.')},
            {'target': 'stockcount-sessions-status', 'text': T('فلتر حسب حالة الجلسة.',
                                              'Filter by session status.')},
            {'target': 'stockcount-sessions-list', 'text': T('الجلسات — اختار جلسة عشان تكمل اللقطة والعد والفروق بتاعتها.',
                                              'The sessions — select one to continue its snapshot, count and variances.')},
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'stockcount.mobile',
        'routes': ['/m/stock-count', '/m/stock-count/:id'],
        'title': T('الجرد من الموبايل', 'Stock count on the phone'),
        'summary': T('قائمة جلسات الجرد، وداخل الجلسة جرد مباشر بين الأرفف: امسح أو ابحث عن الصنف، اكتب الكمية المعدودة، فيظهر الفرق مقابل اللقطة فوراً. '
                     'يعمل بدون إنترنت مؤقتاً — يُسجَّل عند عودة الاتصال.',
                     'The list of count sessions, and inside a session live counting in the aisle: scan or search the item, type the counted quantity, and the difference vs the snapshot shows at once. '
                     'Works briefly offline — it is saved when the connection returns.'),
        'audience': T('العادّون في الفرع.', 'Counters at the branch.'),
        'steps': [
            T('افتح الجلسة (يجب أن تكون اللقطة مأخوذة من الكمبيوتر).', 'Open the session (the snapshot must already be taken on the desktop).'),
            T('«جرد صنف (مسح/بحث)» ← اكتب الكمية المعدودة ← «تسجيل».', '"Count an item (scan/search)" → type the counted quantity → "Save".'),
            T('راجع القائمة بفلتر عجز / فائض / مطابق وأعد عدّ ما يبدو خطأ.', 'Review the list with deficit / surplus / match filters and recount anything that looks wrong.'),
        ],
        'related': ['stockcount.sessions'],
        'tour': [
            {'target': 'stockcount-mobile-title', 'text': T('جلسات الجرد المفتوحة لفرعك.',
                                              'The count sessions for your branch.')},
            {'target': 'stockcount-mobile-list', 'text': T('قائمة الجلسات.',
                                              'The list of sessions.')},
            {'target': 'stockcount-mobile-card', 'text': T('اضغط على الجلسة عشان تبدأ العد.',
                                              'Tap a session to start counting.')},
            {'target': 'stockcount-mobile-status', 'text': T('حالة الجلسة — العد متاح بس في الجلسات المفتوحة.',
                                              'The session status — counting is only possible in open sessions.')},
        ],
        'updated': '2026-10-10',
    },
]
