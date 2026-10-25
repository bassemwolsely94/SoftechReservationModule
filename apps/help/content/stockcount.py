from . import T

# Longer explanations ("more") shared by the screen tours and the module tours.
SC_MORE_TABS = T(
    'الجرد ماشي في 4 خطوات بالترتيب، وكل خطوة تبويب:\n'
    '• «الجلسات»: تفتح أو تختار جلسة.\n'
    '• «اللقطة»: تجمّد الكميات المتوقعة من SOFTECH.\n'
    '• «العد»: ورقة Excel أو العد من الموبايل.\n'
    '• «الفروق»: المتوقع مقابل المعدود والتصدير للتسوية.\n'
    'باقي التبويبات بتتقفل لحد ما تختار جلسة.',
    'A count runs in 4 steps, in order, one tab each:\n'
    '• "Sessions": open or pick a session.\n'
    '• "Snapshot": freeze the expected quantities from SOFTECH.\n'
    '• "Count": an Excel sheet or counting on the phone.\n'
    '• "Variance": expected vs counted, and the export for adjustment.\n'
    'The other tabs stay locked until you pick a session.')
SC_MORE_NEW = T(
    'بيفتح «إنشاء جلسة جرد جديدة»: اسم الجلسة وكود الفرع (إجباريين)، النوع (مبني على الحركات، جرد شامل، جرد مفلتر)، الفترة وأكواد المستندات، وفلاتر كود المستخدم والتصنيف.\n'
    '• «بدء سريع» بيملا الإعداد لحالات شائعة زي مبيعات النهارده أو جرد شامل للفرع.\n'
    '• «إنشاء الجلسة» بيحفظها «مسودة» ويختارها — لسه مفيش لقطة. الزر بيظهر لمن له الصلاحية.',
    'Opens "Create a new count session": session name and branch code (required), the type (transaction-based, full count, filtered count), the period and document codes, and user-code and category filters.\n'
    '• "Quick start" fills the setup for common cases such as today\'s sales or a full branch count.\n'
    '• "Create session" saves it as "Draft" and selects it — no snapshot yet. The button shows to those with permission.')
SC_MORE_SEARCH = T(
    'اكتب جزء من اسم الجلسة أو الفرع عشان تلاقيها بسرعة وسط الجلسات القديمة.\n'
    'البحث بيغيّر العرض بس.',
    'Type part of the session name or branch to find it quickly among older sessions.\n'
    'Search only changes the view.')
SC_MORE_STATUS = T(
    'اعرض الجلسات اللي في مرحلة معيّنة: مسودة، تم اللقطة، تم التصدير، تم الرفع، الفروق جاهزة، مغلق.\n'
    '• مثلاً «تم اللقطة» عشان تشوف الجلسات اللي مستنية عد.',
    'Show the sessions at one stage: draft, snapshot taken, exported, uploaded, variance ready, closed.\n'
    '• For example "Snapshot taken" to see sessions waiting to be counted.')
SC_MORE_LIST = T(
    'كل كارت جلسة فيه حالتها وشريط المراحل والتاريخ.\n'
    '• اضغط الجلسة عشان تختارها — بتتفتح على تبويب «اللقطة» وتكمّل منه.\n'
    '• الجلسات الأحدث فوق.',
    'Each session card shows its status, the stage bar and the date.\n'
    '• Click a session to select it — it opens on the "Snapshot" tab and you continue from there.\n'
    '• The newest sessions are on top.')
SC_MORE_PROGRESS = T(
    'شريط المراحل للجلسة المختارة: مسودة ← تم اللقطة ← تم التصدير ← تم الرفع ← الفروق جاهزة ← مغلق.\n'
    '• المرحلة الخضرا خلصت، واللي بعدها هي خطوتك الجاية.',
    'The stage bar for the selected session: draft → snapshot taken → exported → uploaded → variance ready → closed.\n'
    '• Green stages are done; the next one is your next step.')
SC_MORE_PREVIEW = T(
    'بيقرأ من SOFTECH الأصناف اللي هتدخل الجرد بكمياتها المتوقعة دلوقتي ويعرضها في جدول.\n'
    '• قراءة بس — مش بيحفظ حاجة ومش بيغيّر حالة الجلسة.\n'
    '• استخدمه تتأكد إن الفلاتر صح قبل اللقطة.',
    'Reads from SOFTECH the items that will be in the count with their current expected quantities and shows them in a table.\n'
    '• Read only — it saves nothing and does not change the session status.\n'
    '• Use it to check the filters are right before the snapshot.')
SC_MORE_TAKE = T(
    'بعد تأكيد، بيقرأ الكميات من SOFTECH ويجمّدها في الجلسة كـ «الكمية المتوقعة»، والحالة تبقى «تم اللقطة».\n'
    '• خدها قبل العد على طول ولما الحركة على الرفوف تقف قد ما تقدر — أي بيع أو استلام بعدها هيظهر كفرق.\n'
    '• إعادة أخذ اللقطة بتمسح اللقطة القديمة (بالعد اللي اتسجّل عليها)، ومش مسموحة بعد «الفروق جاهزة». مفيش كتابة في SOFTECH.',
    'After a confirmation, it reads the quantities from SOFTECH and freezes them in the session as the "expected quantity"; the status becomes "Snapshot taken".\n'
    '• Take it right before counting, ideally when shelf movement has stopped — any sale or receipt after it shows as a variance.\n'
    '• Taking it again deletes the old snapshot (with any counts recorded on it), and is not allowed after "Variance ready". Nothing is written to SOFTECH.')
SC_MORE_DOWNLOAD = T(
    'بينزّل ورقة العد الفاضية (Excel) فيها أصناف اللقطة مرتّبة بترتيب الرفوف.\n'
    '• اكتب الكمية اللي عدّيتها في العمود الأصفر «الكمية المعدودة».\n'
    '• الزر مقفول لحد ما اللقطة تتاخد.',
    'Downloads the blank count sheet (Excel) with the snapshot items in shelf order.\n'
    '• Write the quantity you counted in the yellow "Counted quantity" column.\n'
    '• The button is disabled until the snapshot is taken.')
SC_MORE_UPLOAD = T(
    'اختار الملف بعد ما تملاه (xlsx أو xls أو csv) واضغط «⬆️ رفع النتائج».\n'
    '• النظام بيحسب لكل صنف الفرق مقابل اللقطة ويعرض ملخص: مطابق، زيادة، نقص.\n'
    '• الأصناف اللي مش في اللقطة بتتجاهل مع تنبيه. بديل أسرع: العد المباشر من الموبايل.',
    'Pick the filled file (xlsx, xls or csv) and press "⬆️ Upload results".\n'
    '• The system calculates each item\'s difference vs the snapshot and shows a summary: match, surplus, deficit.\n'
    '• Items not in the snapshot are ignored with a warning. Faster alternative: count live on the phone.')
SC_MORE_VSUMMARY = T(
    'إجمالي الأصناف وعدد المطابق والزيادة (المعدود أكتر من المتوقع) والنقص (المعدود أقل).\n'
    '• نسبة كبيرة من الفروق غالباً معناها حركة حصلت بعد اللقطة أو عد غلط — أعد عدّ الأصناف الكبيرة قبل التسوية.',
    'Total items and how many match, are surplus (counted more than expected) or deficit (counted less).\n'
    '• Many differences usually mean movement after the snapshot or a counting mistake — recount the big ones before adjusting.')
SC_MORE_VFILTERS = T(
    '• «الكل» / «زيادة فقط» / «نقص فقط» / «مطابق فقط».\n'
    '• حد أدنى للفارق عشان تخفي الفروق الصغيرة وتركّز على المهم.\n'
    'الفلاتر بتغيّر الجدول بس.',
    '• "All" / "Surplus only" / "Deficit only" / "Match only".\n'
    '• A minimum difference to hide small gaps and focus on what matters.\n'
    'Filters only change the table.')
SC_MORE_EXPORT = T(
    'بينزّل ملف Excel بأصناف الزيادة والنقص عشان التسوية تتدخل في SOFTECH.\n'
    '• النظام هنا مش بيعمل التسوية ولا بيكتب في SOFTECH — الملف ده هو اللي بتدخّل منه.',
    'Downloads an Excel file of the surplus and deficit items so the adjustment can be entered in SOFTECH.\n'
    '• This system does not make the adjustment or write to SOFTECH — you enter it from this file.')
SC_MORE_ERPNOTE = T(
    'التسوية بتتعمل يدوي في SOFTECH بمستندين:\n'
    '• أصناف الزيادة ← مستند 50.\n'
    '• أصناف النقص ← مستند 150.\n'
    'راجع الفروق كويس قبل ما تدخلها لأنها بتغيّر رصيد المخزون في SOFTECH.',
    'The adjustment is entered by hand in SOFTECH with two documents:\n'
    '• Surplus items → document 50.\n'
    '• Deficit items → document 150.\n'
    'Review the variances carefully first, because they change the stock balance in SOFTECH.')
SC_MORE_CLOSE = T(
    'بعد تأكيد، الجلسة بتبقى «مغلق» نهائياً ومفيش تعديل بعد كده.\n'
    '• الزر بيظهر بس بعد تسجيل العد (رفع الملف أو العد من الموبايل)، والسيرفر بيرفض قبل كده.\n'
    '• اقفلها بعد ما تصدّر للتسوية وتراجع الفروق.',
    'After a confirmation, the session becomes "Closed" for good and cannot be changed.\n'
    '• The button only shows once counts are recorded (file upload or mobile counting); the server refuses before that.\n'
    '• Close it after exporting for adjustment and reviewing the variances.')
SC_MORE_MLIST = T(
    'أحدث جلسات الجرد، وكل كارت فيه اسم الجلسة والفرع والحالة.\n'
    '• العد من الموبايل بيشتغل بعد ما اللقطة تتاخد من شاشة الكمبيوتر، ولحد ما الجلسة تتقفل.',
    'The latest count sessions; each card shows the session name, branch and status.\n'
    '• Counting on the phone works after the snapshot is taken on the desktop screen, and until the session is closed.')
SC_MORE_MCARD = T(
    'اضغط الجلسة عشان تفتح شاشة العد بتاعتها.\n'
    '• جوه هتلاقي تقدّم الجرد، ومربع المسح/البحث، وقائمة الأصناف بفلتر عجز/فائض/مطابق.',
    'Tap the session to open its counting screen.\n'
    '• Inside you find the progress, the scan/search box, and the item list with deficit/surplus/match filters.')
SC_MORE_MSTATUS = T(
    'حالة الجلسة زي ما في الكمبيوتر.\n'
    '• «مسودة»: لسه اللقطة ما اتاخدتش — العد مقفول.\n'
    '• «مغلق»: خلصت — العد مقفول.\n'
    '• أي حالة بينهم: تقدر تعدّ.',
    'The session status, same as on the desktop.\n'
    '• "Draft": the snapshot is not taken yet — counting is locked.\n'
    '• "Closed": finished — counting is locked.\n'
    '• Any status in between: you can count.')

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
    'flows': [
        {
            'key': 'session',
            'title': T('الجرد: جلسة ← لقطة ← عد ← فروق', 'Stock count: session → snapshot → count → variances'),
            'summary': T('من فتح جلسة جرد لحد تقرير الفروق وإغلاق الجلسة. النظام هنا مش بيكتب في SOFTECH — التسوية بتتعمل هناك.',
                         'From opening a count session to the variance report and closing it. Nothing here writes to SOFTECH — the adjustment is made there.'),
            'roles': ['admin', 'pharmacist', 'supervisor', 'quality_manager'],
            'steps': [
                {'target': 'nav-stock-count', 'nav': '/stock-count',
                 'text': T('«المخزون» ← «الجرد الفعلي».',
                           '"Inventory" → "Stock count".'),
             'more': T('الجرد بيقارن رفوف الفرع بأرصدة SOFTECH: لقطة ← عد ← فروق ← تسوية في SOFTECH.\n'
                           '• النظام هنا بيقرأ من SOFTECH بس ومش بيكتب فيه.\n'
                           '• الجرد الفعلي متاح للمدير والصيادلة والمشرفين والجودة.',
                           'A stock count compares the branch shelves with SOFTECH balances: snapshot → count → variances → adjustment in SOFTECH.\n'
                           '• This system only reads from SOFTECH and never writes to it.\n'
                           '• Stock count is available to admins, pharmacists, supervisors and quality.')},
                {'target': 'stockcount-sessions-tabs', 'route': '/stock-count',
                 'text': T('الخطوات بالترتيب: الجلسات ← اللقطة ← العد ← الفروق. التبويبات بتتفتح بعد اختيار جلسة.',
                           'The steps in order: sessions → snapshot → count → variances. The tabs open once a session is selected.'),
             'more': SC_MORE_TABS},
                {'target': 'stockcount-sessions-new', 'route': '/stock-count',
                 'text': T('«+ جلسة جديدة» يبدأ جرد لفرع.',
                           '"+ New session" starts a count for a branch.'),
             'more': SC_MORE_NEW},
                {'target': 'stockcount-sessions-row', 'route': '/stock-count',
                 'text': T('اضغط على جلسة — بتفتح على تبويب «اللقطة». لو مفيش جلسات اضغط «إنهاء».',
                           'Click a session — it opens on the "Snapshot" tab. If there are no sessions, press "End".'),
             'more': SC_MORE_LIST},
                {'target': 'stockcount-session-progress', 'route': '/stock-count',
                 'text': T('مراحل الجلسة: مسودة ← تم اللقطة ← تم التصدير ← تم الرفع ← الفروق جاهزة ← مغلق.',
                           'Session stages: draft → snapshot taken → exported → uploaded → variances ready → closed.'),
             'more': SC_MORE_PROGRESS},
                {'target': 'stockcount-snapshot-preview', 'route': '/stock-count',
                 'text': T('«🔍 معاينة الأصناف» يعرض الكميات من SOFTECH من غير ما يحفظ حاجة.',
                           '"🔍 Preview items" shows quantities from SOFTECH without saving anything.'),
             'more': SC_MORE_PREVIEW},
                {'target': 'stockcount-snapshot-take', 'route': '/stock-count',
                 'text': T('«📸 أخذ اللقطة» يثبّت الكميات المتوقعة في لحظة واحدة — ابدأ العد بعدها على طول.',
                           '"📸 Take snapshot" freezes the expected quantities at one moment — start counting right after.'),
             'more': SC_MORE_TAKE},
                {'target': 'stockcount-sessions-tabs', 'route': '/stock-count',
                 'text': T('افتح تبويب «العد» وبعدين «التالي».',
                           'Open the "Count" tab, then "Next".'),
             'more': T('اضغط تبويب «📊 العد» فوق، وبعدين «التالي» في الجولة.\n'
                           '• التبويب بيبقى متاح بعد ما تختار جلسة، والتحميل والرفع بيشتغلوا بعد اللقطة.',
                           'Click the "📊 Count" tab above, then "Next" in the tour.\n'
                           '• The tab is available once a session is selected; download and upload work after the snapshot.')},
                {'target': 'stockcount-count-download', 'route': '/stock-count',
                 'text': T('العد بالورق: «⬇️ تحميل Excel / CSV» — ورقة العد الفارغة مرتّبة حسب الرفوف.',
                           'Counting on paper: "⬇️ Download Excel / CSV" — the blank count sheet in shelf order.'),
             'more': SC_MORE_DOWNLOAD},
                {'target': 'stockcount-count-upload', 'route': '/stock-count',
                 'text': T('بعد العد: «⬆️ رفع النتائج». (أو اعدّ مباشرة من الموبايل.)',
                           'After counting: "⬆️ Upload results". (Or count directly on mobile.)'),
             'more': SC_MORE_UPLOAD},
                {'target': 'stockcount-sessions-tabs', 'route': '/stock-count',
                 'text': T('افتح تبويب «الفروق» وبعدين «التالي».',
                           'Open the "Variances" tab, then "Next".'),
             'more': T('اضغط تبويب «📉 الفروق»، وبعدين «التالي».\n'
                           '• تقرير الفروق بيظهر بعد تسجيل العد (رفع الملف أو العد من الموبايل).',
                           'Click the "📉 Variance" tab, then "Next".\n'
                           '• The variance report appears once counts are recorded (file upload or mobile counting).')},
                {'target': 'stockcount-variance-summary', 'route': '/stock-count',
                 'text': T('ملخص: مطابق، زيادة، نقص.',
                           'Summary: matching, surplus, shortage.'),
             'more': SC_MORE_VSUMMARY},
                {'target': 'stockcount-variance-filters', 'route': '/stock-count',
                 'text': T('فلتر الزيادة / النقص والفارق الأدنى.',
                           'Filter surplus / shortage and the minimum difference.'),
             'more': SC_MORE_VFILTERS},
                {'target': 'stockcount-variance-export', 'route': '/stock-count',
                 'text': T('«📋 تصدير للتسوية» ملف جاهز للتسوية.',
                           '"📋 Export for adjustment" — a file ready for the adjustment.'),
             'more': SC_MORE_EXPORT},
                {'target': 'stockcount-variance-erp-note', 'route': '/stock-count',
                 'text': T('التسوية بتتعمل في SOFTECH: الزيادة مستند 50 والنقص مستند 150.',
                           'The adjustment is made in SOFTECH: surplus document 50, shortage document 150.'),
             'more': SC_MORE_ERPNOTE},
                {'target': 'stockcount-variance-close', 'route': '/stock-count',
                 'text': T('«🔒 إغلاق الجلسة» بعد ما العد يتسجّل (رفع الملف أو العد من الموبايل) والفروق تتراجع.',
                           '"🔒 Close session" once the count is recorded (file upload or mobile counting) and the variances are reviewed.'),
             'more': SC_MORE_CLOSE},
            ],
        },
        {
            'key': 'mobile',
            'title': T('الجرد من الموبايل', 'Counting on mobile'),
            'summary': T('عدّ الأصناف صنف صنف من الموبايل — حتى لو النت قطع.',
                         'Count items one by one on mobile — even if the connection drops.'),
            'roles': ['admin', 'pharmacist', 'supervisor', 'quality_manager'],
            'mobile': True,
            'steps': [
                {'target': 'mshell-tabs',
                 'text': T('الشاشات في الشريط اللي تحت. اللي مش ظاهر تلاقيه في «المزيد».',
                           'Screens are in the bottom bar. Anything not shown is under "More".'),
             'more': T('شاشات الموبايل في الشريط اللي تحت؛ لو «الجرد» مش ظاهر هتلاقيه في «المزيد».\n'
                           '• الموبايل مخصوص للعد بين الرفوف؛ إنشاء الجلسة وأخذ اللقطة بيتعملوا من الكمبيوتر.',
                           'Mobile screens are in the bottom bar; if stock count is not shown, it is under "More".\n'
                           '• The phone is for counting in the aisles; creating the session and taking the snapshot are done on the desktop.')},
                {'target': 'stockcount-mobile-list', 'route': '/m/stock-count',
                 'text': T('جلسات الجرد (الأحدث أولاً). العد متاح بعد ما اللقطة تتاخد من النظام.',
                           'The count sessions (newest first). Counting is available once the snapshot is taken in the system.'),
             'more': SC_MORE_MLIST},
                {'target': 'stockcount-mobile-card', 'route': '/m/stock-count', 'wait': '/m/stock-count/:id',
                 'text': T('افتح جلسة. لو مفيش جلسات اضغط «إنهاء».',
                           'Open a session. If there are none, press "End".'),
             'more': SC_MORE_MCARD},
                {'target': 'stockcount-mcount-progress', 'route': '/m/stock-count/:id',
                 'text': T('تقدّم الجرد: اتعدّ كام من كام.',
                           'Progress: how many counted out of how many.'),
             'more': T('عدد الأصناف اللي اتعدّت من إجمالي أصناف اللقطة والنسبة.\n'
                           '• بيزيد مع كل صنف تسجّله — استخدمه تعرف فاضل قد إيه.',
                           'How many snapshot items are counted out of the total, and the percentage.\n'
                           '• It grows with each item you record — use it to see how much is left.')},
                {'target': 'stockcount-mcount-scan', 'route': '/m/stock-count/:id',
                 'text': T('«📷 جرد صنف»: امسح الباركود أو ابحث.',
                           '"📷 Count an item": scan the barcode or search.'),
             'more': T('امسح باركود الصنف بالكاميرا/القارئ أو اكتب اسمه أو كوده واختاره.\n'
                           '• بعد الاختيار خانة الكمية بتتفتح والمؤشر بيروح فيها على طول.\n'
                           '• لو الصنف مش ضمن اللقطة السيرفر هيرفض ويقولك إنه مش ضمن نطاق الجلسة.',
                           'Scan the item barcode with the camera/scanner, or type its name or code and pick it.\n'
                           '• After picking, the quantity box opens with the cursor in it.\n'
                           '• If the item is not in the snapshot, the server refuses and says it is outside the session.')},
                {'target': 'stockcount-mcount-qty', 'route': '/m/stock-count/:id',
                 'text': T('اكتب الكمية اللي عدّيتها.',
                           'Type the quantity you counted.'),
             'more': T('اكتب العدد الفعلي اللي على الرف (مش الفرق).\n'
                           '• لو سجّلت نفس الصنف تاني، العدد الجديد بيحل محل القديم مش بيتجمع عليه.',
                           'Type the actual quantity on the shelf (not the difference).\n'
                           '• If you record the same item again, the new count replaces the old one; it is not added to it.')},
                {'target': 'stockcount-mcount-save', 'route': '/m/stock-count/:id',
                 'text': T('«تسجيل» (أو Enter). لو النت قاطع بيتسجّل لما يرجع.',
                           '"Record" (or Enter). If offline, it is recorded when the connection returns.'),
             'more': T('«تسجيل» (أو Enter) بيحفظ العد ويحسب الفرق مقابل اللقطة فوراً.\n'
                           '• لو النت قاطع بيظهر «📴 سيُسجَّل عند عودة الاتصال» وبيتبعت لوحده لما النت يرجع.\n'
                           '• العد بيغيّر بيانات الجلسة بس — مش رصيد SOFTECH.',
                           '"Record" (or Enter) saves the count and calculates the difference vs the snapshot at once.\n'
                           '• If offline, "📴 will be recorded when the connection returns" shows and it is sent automatically later.\n'
                           '• Counting only changes the session data — not the SOFTECH balance.')},
                {'target': 'stockcount-mcount-result', 'route': '/m/stock-count/:id',
                 'text': T('آخر نتيجة: المتوقع والمعدود والفرق.',
                           'The last result: expected, counted and the difference.'),
             'more': T('آخر صنف اتسجّل: المتوقع من اللقطة، والمعدود، والفرق ملوّن (زيادة / نقص / مطابق).\n'
                           '• لو الفرق كبير وغريب أعد العد قبل ما تكمّل.',
                           'The last recorded item: expected from the snapshot, counted, and the coloured difference (surplus / deficit / match).\n'
                           '• If the difference is big and odd, recount before moving on.')},
            ],
        },
    ],
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
            T('الجلسة تتقفل بعد تسجيل العد — سواء برفع ملف العد أو بالعد المباشر من الموبايل. قبل كده زر «🔒 إغلاق الجلسة» مش بيظهر والسيرفر بيرفض.',
              'A session can be closed once counts are recorded — by uploading the count file or by counting live on mobile. Before that the "🔒 Close session" button is hidden and the server refuses.'),
            T('مخازن الحجر (102، 103، 105) لا تدخل في أرصدة الجرد التشغيلي.', 'Quarantine stores (102, 103, 105) are excluded from operational count balances.'),
            T('أي بيع أو استلام بين اللقطة والعد يظهر كفرق — جمّد الحركة أو اجرد بسرعة بعد اللقطة.', 'Any sale or receipt between the snapshot and the count shows as a variance — pause movement or count quickly after the snapshot.'),
        ],
        'related': ['stockcount.mobile', 'batches.main', 'transfers.pick_zones'],
        'tour': [
            {'target': 'stockcount-sessions-tabs', 'text': T('خطوات الجرد بالترتيب: الجلسات ← اللقطة ← العد ← الفروق.',
                                              'The count steps in order: Sessions → Snapshot → Count → Variances.'),
             'more': SC_MORE_TABS},
            {'target': 'stockcount-sessions-new', 'text': T('«+ جلسة جديدة» يبدأ جرد لفرع.',
                                              '"+ New session" starts a count for a branch.'),
             'more': SC_MORE_NEW},
            {'target': 'stockcount-sessions-search', 'text': T('ابحث بالاسم أو الفرع.',
                                              'Search by name or branch.'),
             'more': SC_MORE_SEARCH},
            {'target': 'stockcount-sessions-status', 'text': T('فلتر حسب حالة الجلسة.',
                                              'Filter by session status.'),
             'more': SC_MORE_STATUS},
            {'target': 'stockcount-sessions-list', 'text': T('الجلسات — اختار جلسة عشان تكمل اللقطة والعد والفروق بتاعتها.',
                                              'The sessions — select one to continue its snapshot, count and variances.'),
             'more': SC_MORE_LIST},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
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
            {'target': 'stockcount-mobile-title', 'text': T('جلسات الجرد — الأحدث أولاً.',
                                              'The count sessions — newest first.'),
             'more': T('دي قائمة جلسات الجرد على الموبايل، الأحدث أولاً.\n'
                           '• منها تفتح جلسة وتعدّ بالمسح وانت ماشي بين الرفوف.',
                           'This is the list of count sessions on the phone, newest first.\n'
                           '• From here you open a session and count by scanning as you walk the aisles.')},
            {'target': 'stockcount-mobile-list', 'text': T('قائمة الجلسات.',
                                              'The list of sessions.'),
             'more': SC_MORE_MLIST},
            {'target': 'stockcount-mobile-card', 'text': T('اضغط على الجلسة عشان تبدأ العد.',
                                              'Tap a session to start counting.'),
             'more': SC_MORE_MCARD},
            {'target': 'stockcount-mobile-status', 'text': T('حالة الجلسة — العد متاح بس في الجلسات المفتوحة.',
                                              'The session status — counting is only possible in open sessions.'),
             'more': SC_MORE_MSTATUS},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
