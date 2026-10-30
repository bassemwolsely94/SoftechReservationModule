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
                 'more': T(
                     'شريط المراحل للجلسة المختارة: مسودة ← تم اللقطة ← تم التصدير ← تم الرفع ← الفروق جاهزة ← مغلق.\n• المرحلة الخضرا خلصت، واللي بعدها هي خطوتك الجاية.',
                     'The stage bar for the selected session: draft → snapshot taken → exported → uploaded → variance ready → closed.\n• Green stages are done; the next one is your next step.')},
                {'target': 'stockcount-sessions-preview', 'route': '/stock-count',
                 'text': T('«🔍 معاينة الأصناف» يعرض الكميات من SOFTECH من غير ما يحفظ حاجة.',
                           '"🔍 Preview items" shows quantities from SOFTECH without saving anything.')},
                {'target': 'stockcount-sessions-snapshot', 'route': '/stock-count',
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
                 'more': T(
                     'إجمالي الأصناف وعدد المطابق والزيادة (المعدود أكتر من المتوقع) والنقص (المعدود أقل).\n• نسبة كبيرة من الفروق غالباً معناها حركة حصلت بعد اللقطة أو عد غلط — أعد عدّ الأصناف الكبيرة قبل التسوية.',
                     'Total items and how many match, are surplus (counted more than expected) or deficit (counted less).\n• Many differences usually mean movement after the snapshot or a counting mistake — recount the big ones before adjusting.')},
                {'target': 'stockcount-sessions-variance-filter', 'route': '/stock-count',
                 'text': T('فلتر الزيادة / النقص والفارق الأدنى.',
                           'Filter surplus / shortage and the minimum difference.')},
                {'target': 'stockcount-sessions-export', 'route': '/stock-count',
                 'text': T('«📋 تصدير للتسوية» ملف جاهز للتسوية.',
                           '"📋 Export for adjustment" — a file ready for the adjustment.'),
             'more': SC_MORE_EXPORT},
                {'target': 'stockcount-variance-erp-note', 'route': '/stock-count',
                 'text': T('التسوية بتتعمل في SOFTECH: الزيادة مستند 50 والنقص مستند 150.',
                           'The adjustment is made in SOFTECH: surplus document 50, shortage document 150.'),
                 'more': T(
                     'التسوية بتتعمل يدوي في SOFTECH بمستندين:\n• أصناف الزيادة ← مستند 50.\n• أصناف النقص ← مستند 150.\nراجع الفروق كويس قبل ما تدخلها لأنها بتغيّر رصيد المخزون في SOFTECH.',
                     'The adjustment is entered by hand in SOFTECH with two documents:\n• Surplus items → document 50.\n• Deficit items → document 150.\nReview the variances carefully first, because they change the stock balance in SOFTECH.')},
                {'target': 'stockcount-sessions-close', 'route': '/stock-count',
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
                 'more': T(
                     'عدد الأصناف اللي اتعدّت من إجمالي أصناف اللقطة والنسبة.\n• بيزيد مع كل صنف تسجّله — استخدمه تعرف فاضل قد إيه.',
                     'How many snapshot items are counted out of the total, and the percentage.\n• It grows with each item you record — use it to see how much is left.')},
                {'target': 'stockcount-mobile-count', 'route': '/m/stock-count/:id',
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
                 'more': T(
                     'اكتب العدد الفعلي اللي على الرف (مش الفرق).\n• لو سجّلت نفس الصنف تاني، العدد الجديد بيحل محل القديم مش بيتجمع عليه.',
                     'Type the actual quantity on the shelf (not the difference).\n• If you record the same item again, the new count replaces the old one; it is not added to it.')},
                {'target': 'stockcount-mobile-save', 'route': '/m/stock-count/:id',
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
    'journeys': [
        {'key': 'desktop_count', 'shell': 'desktop',
         'title': T('رحلة الجرد: من الجلسة للإغلاق', 'Stock count: from session to close'),
         'summary': T('افتح جلسة، خد اللقطة، عُدّ بالورقة، راجع الفروق، صدّر للتسوية، واقفل.',
                      'Open a session, take the snapshot, count with the sheet, review variances, export for adjustment, and close.'),
         'steps': [
            {'screen': 'stockcount.sessions', 'target': 'stockcount-sessions-new', 'perm': 'stockcount',
             'label': T('+ جلسة جديدة', '+ New session'),
             'text': T('ابدأ جلسة جرد للفرع، أو اختار جلسة موجودة من القائمة.', 'Start a count session for the branch, or pick an existing one from the list.'),
             'open_hint': T('يظهر لمن عنده صلاحية الإنشاء.', 'Shows for users with create permission.')},
            {'screen': 'stockcount.sessions', 'target': 'stockcount-sessions-snapshot', 'perm': 'stockcount',
             'label': T('📸 أخذ اللقطة', '📸 Take snapshot'),
             'text': T('جمّد الكميات المتوقعة قبل العد مباشرة.', 'Freeze the expected quantities right before counting.'),
             'warn': T('أي بيع بعد اللقطة هيظهر كفرق.', 'Any sale after the snapshot shows as a variance.'),
             'open_hint': T('اختار الجلسة، تبويب «📸 اللقطة».', 'Pick the session, "📸 Snapshot" tab.')},
            {'screen': 'stockcount.sessions', 'target': 'stockcount-sessions-download', 'perm': 'stockcount',
             'label': T('⬇️ تحميل Excel / CSV', '⬇️ Download Excel / CSV'),
             'text': T('حمّل ورقة العد ووزّعها على العادّين.', 'Download the count sheet and hand it to the counters.'),
             'open_hint': T('تبويب «📊 العد».', '"📊 Count" tab.')},
            {'screen': 'stockcount.sessions', 'target': 'stockcount-sessions-upload', 'perm': 'stockcount',
             'label': T('⬆️ رفع النتائج', '⬆️ Upload results'),
             'text': T('ارفع الورقة بعد ما تتملي.', 'Upload the sheet once it is filled in.'),
             'open_hint': T('تبويب «📊 العد».', '"📊 Count" tab.')},
            {'screen': 'stockcount.sessions', 'target': 'stockcount-sessions-variance-filter', 'perm': 'stockcount',
             'label': T('نقص فقط', 'Deficit only'),
             'text': T('راجع النقص والزيادة وأعد عدّ الفروق الكبيرة.', 'Review deficits and surpluses and recount the big differences.'),
             'open_hint': T('تبويب «📉 الفروق».', '"📉 Variance" tab.')},
            {'screen': 'stockcount.sessions', 'target': 'stockcount-sessions-export', 'perm': 'stockcount',
             'label': T('📋 تصدير للتسوية', '📋 Export for adjustment'),
             'text': T('صدّر الملف وأدخل التسوية في SOFTECH.', 'Export the file and enter the adjustment in SOFTECH.'),
             'warn': T('التسوية بتغيّر الرصيد في SOFTECH — بعد إعادة العد بس.', 'The adjustment changes the SOFTECH balance — only after recounting.'),
             'open_hint': T('تبويب «📉 الفروق».', '"📉 Variance" tab.')},
            {'screen': 'stockcount.sessions', 'target': 'stockcount-sessions-close', 'perm': 'stockcount',
             'label': T('🔒 إغلاق الجلسة', '🔒 Close session'),
             'text': T('اقفل الجلسة بعد التسوية.', 'Close the session after the adjustment.'),
             'warn': T('الإغلاق نهائي.', 'Closing is final.'),
             'open_hint': T('يظهر لما الحالة «الفروق جاهزة».', 'Shows when the status is "Variance ready".')},
         ]},
        {'key': 'mobile_count', 'shell': 'mobile',
         'title': T('الجرد من الموبايل بين الأرفف', 'Counting on the phone in the aisle'),
         'summary': T('افتح الجلسة، امسح الصنف، سجّل الكمية، وراجع الفروق. اللقطة لازم تكون اتاخدت من الكمبيوتر.',
                      'Open the session, scan the item, save the quantity and review differences. The snapshot must be taken on the desktop first.'),
         'steps': [
            {'screen': 'stockcount.mobile', 'target': 'stockcount-mobile-card', 'perm': 'stockcount',
             'text': T('اختار جلسة الفرع.', 'Choose the branch session.')},
            {'screen': 'stockcount.mobile', 'target': 'stockcount-mobile-count', 'perm': 'stockcount',
             'label': T('📷 جرد صنف (مسح/بحث)', '📷 Count an item (scan/search)'),
             'text': T('امسح أو ابحث عن الصنف واكتب الكمية المعدودة.', 'Scan or search the item and type the counted quantity.'),
             'open_hint': T('افتح أي جلسة اتاخدت لقطتها من القائمة.', 'Open any session with a snapshot from the list.')},
            {'screen': 'stockcount.mobile', 'target': 'stockcount-mobile-save', 'perm': 'stockcount',
             'label': T('تسجيل', 'Save'),
             'text': T('سجّل وشوف الفرق فوراً.', 'Save and see the difference at once.'),
             'warn': T('اكتب إجمالي الصنف — العدّة الجديدة بتحل محل القديمة.', 'Type the item total — a new count replaces the old one.'),
             'open_hint': T('افتح جلسة واختار صنف.', 'Open a session and pick an item.')},
            {'screen': 'stockcount.mobile', 'target': 'stockcount-mobile-filters', 'perm': 'stockcount',
             'label': T('عجز', 'Deficit'),
             'text': T('راجع العجز وأعد عدّ اللي شكله غلط. المراجعة والإغلاق من الكمبيوتر.', 'Review deficits and recount anything that looks wrong. Review and closing are on the desktop.'),
             'open_hint': T('افتح جلسة فيها أصناف متسجلة.', 'Open a session with counted items.')},
         ]},
    ],
}

SCREENS = [
    {
        'key': 'stockcount.sessions',
        'routes': ['/stock-count'],
        'title': T('جرد المخزون', 'Stock count'),
        'summary': T('إنشاء جلسات الجرد ومتابعتها خطوة بخطوة عبر أربعة تبويبات: الجلسات ← اللقطة ← العد ← الفروق.',
                     'Create count sessions and run them step by step through four tabs: sessions → snapshot → count → variance.'),
        'audience': T('الصيادلة والمشرفون يفتحون الجرد ويعدّون؛ الجودة والمشتريات يتابعون ويصدّرون.',
                      'Pharmacists and supervisors open and count; quality and purchasing follow and export.'),
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
            {'target': 'stockcount-sessions-tabs', 'label': T('📋 الجلسات · 📸 اللقطة · 📊 العد · 📉 الفروق', 'Sessions · Snapshot · Count · Variance'),
             'text': T('خطوات الجرد بالترتيب. التبويبات التانية بتشتغل بعد ما تختار جلسة.', 'The count steps in order. The other tabs work once you pick a session.'),
             'more': T(
                 'الجرد ماشي في 4 خطوات بالترتيب، وكل خطوة تبويب:\n• «الجلسات»: تفتح أو تختار جلسة.\n• «اللقطة»: تجمّد الكميات المتوقعة من SOFTECH.\n• «العد»: ورقة Excel أو العد من الموبايل.\n• «الفروق»: المتوقع مقابل المعدود والتصدير للتسوية.\nباقي التبويبات بتتقفل لحد ما تختار جلسة.',
                 'A count runs in 4 steps, in order, one tab each:\n• "Sessions": open or pick a session.\n• "Snapshot": freeze the expected quantities from SOFTECH.\n• "Count": an Excel sheet or counting on the phone.\n• "Variance": expected vs counted, and the export for adjustment.\nThe other tabs stay locked until you pick a session.')},
            {'target': 'stockcount-sessions-new', 'label': T('+ جلسة جديدة', '+ New session'),
             'text': T('نموذج جلسة جرد: الاسم، كود الفرع، النوع، الفترة، المستندات والفلاتر. الأكواد حروف وأرقام فقط (مثل 130 أو IT001).',
                       'Count session form: name, branch code, type, period, documents, filters. Codes are letters and digits only (e.g. 130, IT001).'),
             'open_hint': T('يظهر لمن عنده صلاحية الإنشاء.', 'Shows for users with create permission.'),
             'more': T(
                 'بيفتح «إنشاء جلسة جرد جديدة»: اسم الجلسة وكود الفرع (إجباريين)، النوع (مبني على الحركات، جرد شامل، جرد مفلتر)، الفترة وأكواد المستندات، وفلاتر كود المستخدم والتصنيف.\n• «بدء سريع» بيملا الإعداد لحالات شائعة زي مبيعات النهارده أو جرد شامل للفرع.\n• «إنشاء الجلسة» بيحفظها «مسودة» ويختارها — لسه مفيش لقطة. الزر بيظهر لمن له الصلاحية.',
                 'Opens "Create a new count session": session name and branch code (required), the type (transaction-based, full count, filtered count), the period and document codes, and user-code and category filters.\n• "Quick start" fills the setup for common cases such as today\'s sales or a full branch count.\n• "Create session" saves it as "Draft" and selects it — no snapshot yet. The button shows to those with permission.')},
            {'target': 'stockcount-sessions-presets', 'label': T('بدء سريع', 'Quick start'),
             'text': T('يملأ الإعداد للحالات المتكررة: مبيعات اليوم، مرتجعات الموردين، تحويل وارد، مشتريات اليوم، تحويلات صادرة، جرد شامل.',
                       'Fills the setup for common cases: today\'s sales, supplier returns, incoming transfer, today\'s purchases, outgoing transfers, full count.'),
             'when': T('بعد الاختيار اكتب الاسم وكود الفرع واضغط «إنشاء الجلسة».', 'After choosing, type the name and branch code and press "Create session".'),
             'open_hint': T('اضغط «+ جلسة جديدة».', 'Press "+ New session".')},
            {'target': 'stockcount-sessions-search', 'label': T('بحث بالاسم أو الفرع...', 'Search by name or branch...'),
             'text': T('ابحث عن جلسة بالاسم أو كود الفرع.', 'Find a session by name or branch code.'),
             'more': T(
                 'اكتب جزء من اسم الجلسة أو الفرع عشان تلاقيها بسرعة وسط الجلسات القديمة.\nالبحث بيغيّر العرض بس.',
                 'Type part of the session name or branch to find it quickly among older sessions.\nSearch only changes the view.')},
            {'target': 'stockcount-sessions-list',
             'text': T('كل جلسة بحالتها ومراحلها وعدد الأصناف والزيادة والنقص والمطابق. اضغطها تفتح على «📸 اللقطة».',
                       'Each session with its status, stages, item count, surplus, deficit and matches. Click it to open on "📸 Snapshot".'),
             'more': T(
                 'كل كارت جلسة فيه حالتها وشريط المراحل والتاريخ.\n• اضغط الجلسة عشان تختارها — بتتفتح على تبويب «اللقطة» وتكمّل منه.\n• الجلسات الأحدث فوق.',
                 'Each session card shows its status, the stage bar and the date.\n• Click a session to select it — it opens on the "Snapshot" tab and you continue from there.\n• The newest sessions are on top.')},
            {'target': 'stockcount-sessions-preview', 'label': T('🔍 معاينة الأصناف', '🔍 Preview items'),
             'text': T('يعرض الأصناف اللي هتدخل الجرد وكمياتها المتوقعة من SOFTECH دلوقتي، من غير ما يجمّد حاجة.',
                       'Shows the items that will be counted and their expected quantities from SOFTECH now, without freezing anything.'),
             'when': T('اتأكد إن النطاق صح قبل اللقطة.', 'Check the scope is right before the snapshot.'),
             'open_hint': T('اختار جلسة من القائمة، تبويب «📸 اللقطة».', 'Pick a session from the list, "📸 Snapshot" tab.')},
            {'target': 'stockcount-sessions-snapshot', 'label': T('📸 أخذ اللقطة', '📸 Take snapshot'),
             'text': T('يجمّد الكميات المتوقعة من SOFTECH في اللحظة دي. الفروق كلها هتتحسب على اللقطة دي.',
                       'Freezes the expected quantities from SOFTECH at this moment. All variances are calculated against it.'),
             'when': T('خدها قبل العد مباشرة، وبعد ما الحركة على الأرفف تقف قدر الإمكان.', 'Take it right before counting, ideally once shelf movement has stopped.'),
             'warn': T('إعادة اللقطة بتمسح اللقطة السابقة واللي اتعد عليها. أي بيع بعدها هيظهر كفرق.',
                       'Re-taking the snapshot deletes the previous one and anything counted on it. Any sale after it shows as a variance.'),
             'open_hint': T('تبويب «📸 اللقطة» — يختفي بعد ما الفروق تجهز.', '"📸 Snapshot" tab — hidden once the variance is ready.')},
            {'target': 'stockcount-sessions-download', 'label': T('⬇️ تحميل Excel / CSV', '⬇️ Download Excel / CSV'),
             'text': T('ورقة العد الفاضية بترتيب الأرفف. اكتب الكمية المعدودة في العمود الأصفر.', 'The blank count sheet in shelf order. Write the counted quantity in the yellow column.'),
             'when': T('بديل أسرع: العد من الموبايل بالمسح من شاشة الجرد على الموبايل.', 'Faster alternative: count on the phone by scanning, from the mobile count screen.'),
             'open_hint': T('تبويب «📊 العد» بعد أخذ اللقطة.', '"📊 Count" tab after the snapshot is taken.')},
            {'target': 'stockcount-sessions-upload', 'label': T('⬆️ رفع النتائج', '⬆️ Upload results'),
             'text': T('اختار الملف المتعبي واضغط. يحسب الزيادة والنقص والمطابق، والأصناف اللي مش في اللقطة بتتجاهل مع تنبيه.',
                       'Choose the filled file and press. It calculates surplus, deficit and matches; items not in the snapshot are ignored with a warning.'),
             'warn': T('ارفع الملف الصح للجلسة دي — الكميات المرفوعة بتكتب فوق الكميات المعدودة.',
                       'Upload the right file for this session — uploaded quantities overwrite the counted ones.'),
             'open_hint': T('تبويب «📊 العد» بعد أخذ اللقطة.', '"📊 Count" tab after the snapshot is taken.')},
            {'target': 'stockcount-sessions-variance-filter', 'label': T('الكل · زيادة فقط · نقص فقط · مطابق فقط', 'All · Surplus · Deficit · Match only'),
             'text': T('صفّي الفروق حسب النوع، و«فارق أدنى (كمية)» يخفي الفروق الصغيرة.', 'Filter variances by type; "Minimum difference (qty)" hides small differences.'),
             'when': T('ابدأ بالنقص الكبير وأعد عدّه قبل التسوية.', 'Start with big deficits and recount them before the adjustment.'),
             'open_hint': T('تبويب «📉 الفروق» بعد رفع النتائج أو العد من الموبايل.', '"📉 Variance" tab after uploading results or counting on the phone.')},
            {'target': 'stockcount-sessions-export', 'label': T('📋 تصدير للتسوية', '📋 Export for adjustment'),
             'text': T('ملف أصناف الزيادة والنقص لإدخال التسوية يدوياً في SOFTECH. الشاشة نفسها مبتكتبش حاجة في SOFTECH.',
                       'A file of surplus and deficit items to enter the adjustment by hand in SOFTECH. This screen writes nothing to SOFTECH.'),
             'warn': T('صدّر بعد إعادة عدّ الفروق الكبيرة — التسوية في SOFTECH بتغيّر الرصيد فعلاً.',
                       'Export after recounting big differences — the SOFTECH adjustment really changes the balance.'),
             'open_hint': T('تبويب «📉 الفروق».', '"📉 Variance" tab.')},
            {'target': 'stockcount-sessions-close', 'label': T('🔒 إغلاق الجلسة', '🔒 Close session'),
             'text': T('يقفل الجلسة نهائياً بعد ما تخلص المراجعة والتسوية.', 'Closes the session for good after review and adjustment are done.'),
             'warn': T('الإغلاق نهائي — مفيش تعديل أو رفع بعده.', 'Closing is final — no edits or uploads after it.'),
             'open_hint': T('تبويب «📉 الفروق» لما الحالة «الفروق جاهزة» (بعد رفع ملف النتائج).', '"📉 Variance" tab when the status is "Variance ready" (after uploading the results file).')},
            {'target': 'stockcount-sessions-status',  # from the GitHub-side tour
             'text': T('فلتر حسب حالة الجلسة.',
                       'Filter by session status.'),
             'more': T(
                 'اعرض الجلسات اللي في مرحلة معيّنة: مسودة، تم اللقطة، تم التصدير، تم الرفع، الفروق جاهزة، مغلق.\n• مثلاً «تم اللقطة» عشان تشوف الجلسات اللي مستنية عد.',
                 'Show the sessions at one stage: draft, snapshot taken, exported, uploaded, variance ready, closed.\n• For example "Snapshot taken" to see sessions waiting to be counted.')},
        ],
        'updated': '2026-10-29',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
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
            {'target': 'stockcount-mobile-title', 'label': T('جلسات الجرد', 'Count sessions'),
             'text': T('جلسات الجرد اللي اتعملت من الكمبيوتر.', 'The count sessions created on the desktop.'),
             'more': T(
                 'دي قائمة جلسات الجرد على الموبايل، الأحدث أولاً.\n• منها تفتح جلسة وتعدّ بالمسح وانت ماشي بين الرفوف.',
                 'This is the list of count sessions on the phone, newest first.\n• From here you open a session and count by scanning as you walk the aisles.')},
            {'target': 'stockcount-mobile-card',
             'text': T('اضغط الجلسة عشان تبدأ العد فيها.', 'Tap a session to start counting in it.'),
             'more': T(
                 'اضغط الجلسة عشان تفتح شاشة العد بتاعتها.\n• جوه هتلاقي تقدّم الجرد، ومربع المسح/البحث، وقائمة الأصناف بفلتر عجز/فائض/مطابق.',
                 'Tap the session to open its counting screen.\n• Inside you find the progress, the scan/search box, and the item list with deficit/surplus/match filters.')},
            {'target': 'stockcount-mobile-status',
             'text': T('حالة الجلسة. العد متاح بعد أخذ اللقطة ولحد الإغلاق.', 'The session status. Counting is open after the snapshot and until closing.'),
             'when': T('«مسودة» يعني اللقطة لسه متاخدتش من الكمبيوتر.', '"Draft" means the snapshot was not taken on the desktop yet.'),
             'more': T(
                 'حالة الجلسة زي ما في الكمبيوتر.\n• «مسودة»: لسه اللقطة ما اتاخدتش — العد مقفول.\n• «مغلق»: خلصت — العد مقفول.\n• أي حالة بينهم: تقدر تعدّ.',
                 'The session status, same as on the desktop.\n• "Draft": the snapshot is not taken yet — counting is locked.\n• "Closed": finished — counting is locked.\n• Any status in between: you can count.')},
            {'target': 'stockcount-mobile-progress',
             'text': T('اسم الجلسة وحالتها وتقدّم العد: تم جرد كام صنف من كام.', 'Session name, status and count progress: how many items counted out of how many.'),
             'open_hint': T('افتح أي جلسة من القائمة.', 'Open any session from the list.')},
            {'target': 'stockcount-mobile-count', 'label': T('📷 جرد صنف (مسح/بحث)', '📷 Count an item (scan/search)'),
             'text': T('امسح الباركود أو ابحث عن الصنف، واكتب «الكمية المعدودة».', 'Scan the barcode or search the item, then type the "Counted quantity".'),
             'open_hint': T('افتح جلسة اتاخدت لقطتها ومش مقفولة.', 'Open a session whose snapshot is taken and that is not closed.')},
            {'target': 'stockcount-mobile-save', 'label': T('تسجيل', 'Save'),
             'text': T('يسجّل العدّة ويوريك فوراً المتوقع والمعدود والفرق. من غير إنترنت بتتسجل لما الاتصال يرجع.',
                       'Saves the count and shows expected, counted and the difference at once. Offline, it is saved when the connection returns.'),
             'warn': T('العدّة الجديدة لنفس الصنف بتحل محل القديمة — اكتب الإجمالي مش الزيادة.',
                       'A new count for the same item replaces the old one — type the total, not the extra.'),
             'open_hint': T('اختار صنف الأول عشان يظهر.', 'Pick an item first to make it appear.')},
            {'target': 'stockcount-mobile-filters', 'label': T('الكل · عجز · فائض · مطابق', 'All · Deficit · Surplus · Match'),
             'text': T('قائمة الأصناف بفلتر العجز والفائض والمطابق. أعد عدّ أي فرق شكله غلط.', 'The item list filtered by deficit, surplus or match. Recount any difference that looks wrong.'),
             'open_hint': T('تظهر بعد أول صنف يتسجل في الجلسة.', 'Shows after the first item is counted in the session.')},
            {'target': 'stockcount-mobile-list',  # from the GitHub-side tour
             'text': T('قائمة الجلسات.',
                       'The list of sessions.'),
             'more': T(
                 'أحدث جلسات الجرد، وكل كارت فيه اسم الجلسة والفرع والحالة.\n• العد من الموبايل بيشتغل بعد ما اللقطة تتاخد من شاشة الكمبيوتر، ولحد ما الجلسة تتقفل.',
                 'The latest count sessions; each card shows the session name, branch and status.\n• Counting on the phone works after the snapshot is taken on the desktop screen, and until the session is closed.')},
        ],
        'updated': '2026-10-26',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
    },
]
