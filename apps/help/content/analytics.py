from . import T

MODULE = {
    'key': 'analytics', 'group': 'analytics', 'icon': '📈',
    'title': T('التحليلات والأهداف', 'Analytics & targets'),
    'summary': T(
        'تقارير المبيعات وأداء الموظفين والحجوزات والتحويلات من فواتير SOFTECH، والأهداف البيعية ومتابعة تحقيقها لكل فرع (لوحة «تارجت/تحقيق»)، '
        'وسيناريوهات توليد الأهداف بنماذج تنبؤ مختبرة على التاريخ، ومحرك التنبؤ بالمبيعات والموسمية، والتقارير السردية للمديرين، وإحالات الأطباء.',
        'Reports on sales, staff performance, reservations and transfers from SOFTECH invoices, sales targets and their attainment per branch (the "target/achievement" board), '
        'target-generation scenarios with forecasting models tested on history, the sales forecast engine and seasonality, narrative reports for directors, and doctor referrals.'),
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول التحليلات والأهداف', 'A tour of the Analytics & targets module'),
            'summary': T('إزاي تقرا المبيعات والأداء، وبعدين تحوّلها لأهداف: من لوحة المبيعات ← أداء الموظفين والحجوزات والتحويلات ← الأهداف ولوحة التارجت/تحقيق ← سيناريوهات توليد الأهداف ← التقارير السردية للإدارة.',
                         'How to read sales and performance and turn them into targets: the sales dashboard → staff, reservation and transfer analytics → targets and the target/achievement board → target-generation scenarios → narrative reports for management.'),
            'roles': ['admin', 'supervisor', 'purchasing'],
            'steps': [
                {'target': 'nav-analytics', 'nav': '/analytics',
                 'text': T('نبدأ من «التحليلات» ← «المبيعات والأداء».',
                           'Start at "Analytics" → "Sales & performance".'),
                 'more': T('الموديول ده للقراءة والمتابعة: كل الأرقام بتتحسب في السيرفر من فواتير SOFTECH اللي اتسحبت عندنا، ومفيش شاشة هنا بتكتب في SOFTECH.\n'
                           '• فوق الصفحة هتلاقي شريط تبويبات: المبيعات، أداء الموظفين، الحجوزات، التحويلات.\n'
                           '• باقي الشاشات (الأهداف، لوحة المؤشرات، السيناريوهات، التقارير السردية) في نفس القائمة.',
                           'This module is for reading and follow-up: every figure is computed on the server from the SOFTECH invoices pulled into our system, and no screen here writes to SOFTECH.\n'
                           '• At the top you get a tab bar: Sales, Staff performance, Reservations, Transfers.\n'
                           '• The other screens (targets, KPI board, scenarios, narrative reports) are in the same menu.')},
                {'target': 'analytics-sales-kpis', 'route': '/analytics/sales',
                 'text': T('لوحة المبيعات: صافي الإيراد والربح والخصم والفواتير للفترة.',
                           'The sales dashboard: net revenue, profit, discount and invoices for the period.'),
                 'more': T('الفترة الافتراضية آخر 30 يوم، وتقدر تغيّرها من الفلاتر فوق (الفرع، الموظف، القناة، نوع الدواء، الساعة، اليوم).\n'
                           '• صافي الإيرادات = المبيعات − المردودات، والسطر الصغير تحته بيوضح الرقمين.\n'
                           '• دي نقطة البداية لأي سؤال: «إحنا بايعين كام ومكسبنا كام؟».',
                           'The default period is the last 30 days; change it with the filters above (branch, employee, channel, medicine type, hour, weekday).\n'
                           '• Net revenue = sales − returns, and the small line under it shows both numbers.\n'
                           '• This is the starting point for any question like "how much did we sell and earn?".')},
                {'target': 'analytics-sales-tabs', 'route': '/analytics/sales',
                 'text': T('التبويبات بتقسّم نفس الأرقام: فروع، كاشيرين، قنوات، أصناف، وقت…',
                           'The tabs split the same figures: branches, cashiers, channels, items, time…'),
                 'more': T('كل تبويب بيجاوب سؤال: أنهي فرع أحسن؟ أنهي قناة أربح؟ إمتى الزحمة عشان نظبط الورديات؟\n'
                           '• «👻 العملاء الغائبون» بيطلّع قائمة عملاء بطّلوا يشتروا عشان الكول سنتر يكلمهم.\n'
                           '• «🏦 مساهمة الفروع» = ربح الفرع − مصروفاته.',
                           'Each tab answers a question: which branch is best? which channel is most profitable? when is it busy so we can plan shifts?\n'
                           '• "👻 Lapsed customers" lists customers who stopped buying so the call center can contact them.\n'
                           '• "🏦 Branch contribution" = branch profit − its expenses.')},
                {'target': 'analytics-performance-kpis', 'route': '/analytics/performance',
                 'text': T('أداء الموظفين: نفس المؤشرات لكل موظف بيعي، والأفضل أداءً.',
                           'Staff performance: the same KPIs per salesperson, and the top performer.'),
                 'more': T('الأرقام هنا متقسمة بكود مستخدم SOFTECH اللي عمل الفاتورة.\n'
                           '• تحت المؤشرات هتلاقي «المتصدرون» (أعلى 3 إيراد) وجدول الموظفين.\n'
                           '• الأرقام دي هي اللي بتتبني عليها أهداف المندوبين والحوافز بعد كده.',
                           'The figures here are split by the SOFTECH user code that issued the invoice.\n'
                           '• Below the KPIs you get the "Leaders" (top 3 by revenue) and the employee table.\n'
                           '• These figures are what salesperson targets and incentives are later built on.')},
                {'target': 'analytics-reservations-kpis', 'route': '/analytics/reservations',
                 'text': T('تحليلات الحجوزات: معدل التسليم ووقته والطلب المفقود.',
                           'Reservation analytics: fulfilment rate, time to fulfil and lost demand.'),
                 'more': T('الطلب المفقود = حجوزات اتلغت أو انتهت من غير ما تتسلّم — ده بيع ضاع علينا.\n'
                           '• تحت هتلاقي أكتر الأصناف المحجوزة والمفقودة: دي إشارة مباشرة للمشتريات إن الصنف ناقص.\n'
                           '• شاشة «التحويلات» جنبها بتوري سرعة وجودة التحويل بين الفروع.',
                           'Lost demand = reservations cancelled or expired without being fulfilled — sales we lost.\n'
                           '• Below you find the most reserved and most lost items: a direct signal to purchasing that an item is short.\n'
                           '• The "Transfers" tab next to it shows how fast and how well inter-branch transfers go.')},
                {'target': 'analytics-transfers-tabs', 'route': '/analytics/transfers',
                 'text': T('تحليلات التحويلات: «التحليلات» و«تقرير التباينات».',
                           'Transfer analytics: "Analytics" and "Discrepancy report".'),
                 'more': T('«التحليلات» بيوري عدد الطلبات ونسبة الإكمال والرفض ومتوسط الوقت وأنشط المسارات.\n'
                           '• «تقرير التباينات» فيه الطلبات اللي اتستلمت بكمية مختلفة عن المعتمد — راجعها مع الفرعين.',
                           '"Analytics" shows the request count, completion and rejection rates, average times and the busiest routes.\n'
                           '• "Discrepancy report" lists requests received in a quantity different from the approved one — review them with both branches.')},
                {'target': 'analytics-targets-header', 'route': '/targets',
                 'text': T('«الأهداف البيعية»: الهدف مقابل المحقق لحظياً.',
                           '"Sales targets": target versus live achievement.'),
                 'more': T('بعد ما فهمت الأرقام، هنا بتحط الهدف. المحقق بيتحسب في السيرفر من فواتير SOFTECH (صافي المبيعات بعد المرتجعات أو عدد الفواتير) — محدش بيكتبه بإيده.\n'
                           '• كل هدف ليه بطاقة فيها الوتيرة وشريط التحقيق.',
                           'Once you understand the figures, this is where you set the target. Achievement is computed on the server from SOFTECH invoices (net sales after returns, or invoice count) — nobody types it in.\n'
                           '• Each target has a card with its pace and attainment bar.')},
                {'target': 'analytics-targets-new', 'route': '/targets',
                 'text': T('«+ هدف جديد» لهدف يدوي للشبكة أو فرع أو مندوب.',
                           '"+ New target" for a manual target for the network, a branch or a salesperson.'),
                 'more': T('بتكتب اسم الهدف والنطاق والمؤشر والفترة والقيمة المستهدفة وتضغط «حفظ الهدف».\n'
                           '• لو عايز أهداف محسوبة لكل الفروع مرة واحدة استخدم «سيناريوهات التنبؤ» بدل ما تكتبها واحد واحد.\n'
                           '• الزر للمدير والمشرف والمشتريات، والسيرفر بيرفض أي حد غيرهم.',
                           'You enter the target name, scope, metric, period and target value, then press "Save target".\n'
                           '• For computed targets for all branches at once, use "Forecast scenarios" instead of typing them one by one.\n'
                           '• The button is for admin, supervisor and purchasing; the server refuses anyone else.')},
                {'target': 'analytics-kpi-board-period', 'route': '/kpi-board',
                 'text': T('«لوحة مؤشرات الفروع»: اختار الشهر والسنة.',
                           '"Branch KPI board": choose the month and year.'),
                 'more': T('دي نسخة الشاشة من ملف الإكسل بتاع التارجت/تحقيق: كل فرع في صف، وكل مؤشر فيه «محقق» و«تارجت» و«%».\n'
                           '• المحقق من فواتير SOFTECH، والتارجت من الأهداف البيعية لنفس الشهر.\n'
                           '• تحت الجدول «إجمالى الفروع» وقسم الكول سنتر لوحده.',
                           'This is the on-screen version of the target/achievement Excel file: one row per branch, and each metric has "Achieved", "Target" and "%".\n'
                           '• Achieved comes from SOFTECH invoices, the target from the sales targets of the same month.\n'
                           '• Below the table: the branch total and a separate call center section.')},
                {'target': 'analytics-kpi-board-legend', 'route': '/kpi-board',
                 'text': T('الملاحظة دي بتقولك مصدر كل رقم.',
                           'This note tells you where each figure comes from.'),
                 'more': T('القيم المالية بالجنيه، و«محقق» صافي بعد المرتجعات. لو التارجت فاضي يبقى مفيش هدف للفرع ده في الشهر ده.\n'
                           '• الأهداف نفسها بتتدار من «الأهداف البيعية» أو بتيجي من اعتماد سيناريو.',
                           'Money values are in pounds, and "Achieved" is net after returns. An empty target means that branch has no target for that month.\n'
                           '• The targets themselves are managed in "Sales targets" or come from committing a scenario.')},
                {'target': 'analytics-scenarios-backtest', 'route': '/forecast-scenarios',
                 'text': T('«سيناريوهات التنبؤ»: أولاً شوف أنهي نموذج أدق على التاريخ.',
                           '"Forecast scenarios": first see which model was more accurate on history.'),
                 'more': T('افتح «🏁 دقة النماذج» عشان تشوف خطأ Model A وB على الأشهر السابقة (WAPE — الأقل أحسن) والأفضل لكل مؤشر.\n'
                           '• ده بيساعدك تختار النموذج قبل ما تعمل سيناريو جديد.',
                           'Open "🏁 Model accuracy" to see the error of Model A and B on past months (WAPE — lower is better) and the better one per metric.\n'
                           '• This helps you pick the model before creating a new scenario.')},
                {'target': 'analytics-scenarios-list', 'route': '/forecast-scenarios',
                 'text': T('السيناريوهات: مسودة ← محسوب ← معتمد.',
                           'Scenarios: draft → calculated → committed.'),
                 'more': T('اختار سيناريو عشان تظبط عوامله وتضغط «⚙️ احسب التنبؤ»، وبعدين «✅ اعتماد الأهداف».\n'
                           '• الاعتماد بيكتب أهداف الشهر للفروع أو المندوبين أو الفئات في «الأهداف البيعية»، فتظهر على لوحة المؤشرات وتتقاس عليها الحوافز.',
                           'Pick a scenario to tune its factors and press "⚙️ Calculate forecast", then "✅ Commit targets".\n'
                           '• Committing writes the month targets for the branches, salespeople or categories into "Sales targets", so they show on the KPI board and incentives are measured against them.')},
                {'target': 'analytics-insights-period', 'route': '/insights',
                 'text': T('«التقارير السردية»: اختار نوع التقرير وفترته.',
                           '"Narrative reports": choose the report type and its period.'),
                 'more': T('آخر محطة: تقرير مكتوب بالعربي والإنجليزي يلخّص المبيعات والمقارنات وتحقيق الأهداف والتنبيهات، للمدير اللي مش عايز يقرا جداول.\n'
                           '• يومي، أسبوعي، حتى تاريخه، أو شهري — والتواريخ لحد إمبارح بس.',
                           'The last stop: a written report in Arabic and English summarising sales, comparisons, target attainment and alerts, for a director who does not want to read tables.\n'
                           '• Daily, weekly, month-to-date or monthly — dates go up to yesterday only.')},
                {'target': 'analytics-insights-generate', 'route': '/insights',
                 'text': T('«⚙️ توليد التقرير» وبعدين انسخه للواتساب.',
                           '"⚙️ Generate report", then copy it to WhatsApp.'),
                 'more': T('التقرير بيتولد في السيرفر من الأرقام المتزامنة وقواعد الحدود اللي الإدارة ضابطاها، وبيفتح لوحده بعد التوليد.\n'
                           '• لو فيه شريط أصفر عن أيام ناقصة، الأرقام أقل من الواقع — استنى المزامنة قبل ما تبعته.',
                           'The report is built on the server from the synced figures and the thresholds management has set, and opens by itself once generated.\n'
                           '• If a yellow bar warns about missing days, the figures are lower than reality — wait for the sync before sending it.')},
            ],
        },
    ],
}

_FILTERS = T('الفلاتر أعلى الصفحة (الفرع، نوع المستند، الموظف، القناة، نوع الدواء، التاريخ والساعة واليوم) تنطبق على كل التبويبات.',
             'The filters at the top (branch, document type, employee, channel, medicine type, date, hour and weekday) apply to every tab.')

_NOTE = T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour')

SCREENS = [
    {
        'key': 'analytics.sales',
        'routes': ['/analytics/sales'],
        'title': T('لوحة المبيعات', 'Sales dashboard'),
        'summary': T('ذكاء المبيعات: صافي الإيراد والربح والهامش والخصومات والفواتير والعملاء والأصناف والمرتجعات، مع تحليل بالفرع والكاشير والقناة ونوع الدواء والصنف والوقت.',
                     'Sales intelligence: net revenue, profit, margin, discounts, invoices, customers, items and returns, analysed by branch, cashier, channel, medicine type, item and time.'),
        'audience': T('الإدارة والمشتريات والصيادلة والمشرفون والجودة.', 'Management, purchasing, pharmacists, supervisors and quality.'),
        'tabs': [
            {'key': 'overview', 'title': T('📊 نظرة عامة', '📊 Overview'), 'body': T('مؤشرات الفترة والاتجاه اليومي للإيرادات والإيرادات حسب التصنيف العلاجي.', 'Period KPIs, the daily revenue trend and revenue by therapeutic class.')},
            {'key': 'branches', 'title': T('🏪 الفروع', '🏪 Branches'), 'body': T('الإيراد والربح والهامش والخصم والفواتير والعملاء والأصناف لكل فرع.', 'Revenue, profit, margin, discount, invoices, customers and items per branch.')},
            {'key': 'users', 'title': T('👤 الكاشيرون', '👤 Cashiers'), 'body': T('نفس المؤشرات لكل كاشير/مستخدم SOFTECH.', 'The same KPIs per cashier/SOFTECH user.')},
            {'key': 'channels', 'title': T('🛒 قنوات البيع', '🛒 Sales channels'), 'body': T('نقدي، توصيل، تعاقد، تأمين… حصة كل قناة وربحيتها.', 'Cash, delivery, contract, insurance… each channel\'s share and profitability.')},
            {'key': 'medicine', 'title': T('💊 أنواع الأدوية', '💊 Medicine types'), 'body': T('المبيعات حسب نوع الدواء.', 'Sales by medicine type.')},
            {'key': 'items', 'title': T('📦 أفضل الأصناف', '📦 Top items'), 'body': T('الأصناف الأعلى إيراداً وربحاً مع المورد والمنتج والعائلة.', 'Top items by revenue and profit with supplier, producer and family.')},
            {'key': 'time', 'title': T('🕐 التوزيع الزمني', '🕐 Time distribution'), 'body': T('المبيعات بالساعة ويوم الأسبوع — لتنظيم الورديات.', 'Sales by hour and weekday — to plan shifts.')},
            {'key': 'contribution', 'title': T('🏦 مساهمة الفروع', '🏦 Branch contribution'), 'body': T('هامش المساهمة لكل فرع = إجمالي الربح − مصروفات الفرع.', 'Each branch\'s contribution margin = gross profit − branch expenses.')},
            {'key': 'churn', 'title': T('👻 العملاء الغائبون', '👻 Lapsed customers'), 'body': T('عملاء انقطعوا عن الشراء مع الخسارة السنوية المقدّرة — قائمة للتواصل.', 'Customers who stopped buying with the estimated annual loss — a contact list.')},
        ],
        'tips': [_FILTERS],
        'related': ['analytics.performance', 'finance.dashboard'],
        'tour': [
            {'target': 'analytics-sales-refresh', 'text': T('«تحديث» يعيد تحميل الأرقام بالفلاتر الحالية.',
                                              '"Refresh" reloads the figures with the current filters.'),
             'more': T('الأرقام بتتحدّث لوحدها أول ما تغيّر أي فلتر، فـ«تحديث» مفيد لو الصفحة مفتوحة من بدري وعايز آخر فواتير اتسحبت من SOFTECH.\n'
                       '• الفترة الافتراضية آخر 30 يوم.\n'
                       '• الأرقام محسوبة في السيرفر — الصفحة بتعرضها بس ومفيش حاجة هنا بتتعدّل.',
                       'The figures update by themselves as soon as you change a filter, so "Refresh" is useful when the page has been open a while and you want the latest invoices pulled from SOFTECH.\n'
                       '• The default period is the last 30 days.\n'
                       '• The figures are computed on the server — the page only shows them and nothing here is edited.')},
            {'target': 'analytics-sales-kpis', 'text': T('المؤشرات الرئيسية: صافي الإيرادات، صافي الربح، وغيرها للفترة المختارة.',
                                              'The headline figures: net revenue, net profit and more for the chosen period.'),
             'more': T('• «صافي الإيرادات» = المبيعات − المردودات، والسطر الصغير تحته بيوضح الرقمين.\n'
                       '• «صافي الربح» وهامشه، «تكلفة البضاعة»، «إجمالي الخصومات»، «عدد الفواتير» ومتوسطها، العملاء الفريدون بكود PIC، و«صنف/فاتورة».\n'
                       '• الصف اللي تحته: فواتير المبيعات والمردودات و«معدل الإرجاع» (بيحمرّ لو عدّى 5%).',
                       '• "Net revenue" = sales − returns, and the small line under it shows both numbers.\n'
                       '• "Net profit" and its margin, "Cost of goods", "Total discounts", "Invoices" and their average, unique PIC customers, and "Items/invoice".\n'
                       '• The row below: sales invoices, returns and the "Return rate" (turns red above 5%).')},
            {'target': 'analytics-sales-tabs', 'text': T('التبويبات: نظرة عامة، الفروع، الكاشيرون، قنوات البيع، الأصناف، الوقت…',
                                              'Tabs: overview, branches, cashiers, sales channels, items, time…'),
             'more': T('كل تبويب بيقسّم نفس الأرقام بطريقة مختلفة: الفروع، الكاشيرين، قنوات البيع، أنواع الأدوية، أفضل الأصناف، والتوزيع بالساعة واليوم عشان تنظيم الورديات.\n'
                       '• «🏦 مساهمة الفروع» بيستخدم فلتر التاريخ بس.\n'
                       '• «👻 العملاء الغائبون» محسوب بالنسبة لانهارده ومش بيتأثر بالفلاتر.',
                       'Each tab splits the same figures a different way: branches, cashiers, sales channels, medicine types, top items, and the hour/weekday spread for shift planning.\n'
                       '• "🏦 Branch contribution" uses only the date filter.\n'
                       '• "👻 Lapsed customers" is measured relative to today and ignores the filters.')},
            {'target': 'analytics-sales-tab-panel', 'text': T('محتوى التبويب المفتوح — في البداية الاتجاه اليومي للإيرادات.',
                                              'The open tab\'s content — first the daily revenue trend.'),
             'more': T('في «نظرة عامة» هتلاقي الاتجاه اليومي للإيرادات والإيرادات حسب التصنيف العلاجي.\n'
                       '• الجداول في باقي التبويبات تقدر ترتّبها بالضغط على عنوان العمود.\n'
                       '• في «العملاء الغائبون» القائمة جاهزة للتواصل مع العملاء اللي بطّلوا يشتروا.',
                       'On "Overview" you see the daily revenue trend and revenue by therapeutic class.\n'
                       '• Tables in the other tabs can be sorted by clicking a column title.\n'
                       '• On "Lapsed customers" the list is ready for contacting customers who stopped buying.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'analytics.performance',
        'routes': ['/analytics/performance'],
        'title': T('أداء الموظفين', 'Staff performance'),
        'summary': T('أداء كل موظف بيعي: الإيراد، الربح، الهامش، الخصم، الفواتير، متوسط الفاتورة، الأصناف لكل فاتورة، والعملاء الفريدون، مع المتصدرين.',
                     'Each salesperson\'s performance: revenue, profit, margin, discount, invoices, average invoice, items per invoice and unique customers, with the leaders.'),
        'audience': T('الإدارة والمشرفون.', 'Management and supervisors.'),
        'tabs': [
            {'key': 'employees', 'title': T('👤 الموظفون', '👤 Employees'), 'body': T('جدول الموظفين مرتباً بالإيراد.', 'The employee table sorted by revenue.')},
            {'key': 'branches', 'title': T('🏪 الفروع', '🏪 Branches'), 'body': T('عدد الموظفين وتوزيع الإيراد عليهم لكل فرع.', 'Number of employees and revenue distribution per branch.')},
            {'key': 'time', 'title': T('🕐 التوزيع الزمني', '🕐 Time distribution'), 'body': T('الإيراد بالساعة ويوم الأسبوع.', 'Revenue by hour and weekday.')},
        ],
        'tips': [_FILTERS],
        'related': ['incentives.programs', 'analytics.targets'],
        'tour': [
            {'target': 'analytics-performance-header', 'text': T('لوحة أداء الموظفين؛ زر «تحديث» يعيد تحميل الأرقام بالفلاتر الحالية.',
                                              'The staff performance board; «تحديث» (Refresh) reloads the figures with the current filters.'),
             'more': T('الأداء هنا متقسم بكود مستخدم SOFTECH اللي عمل الفاتورة، والفترة الافتراضية آخر 30 يوم.\n'
                       '• الفلاتر تحت العنوان زي لوحة المبيعات، والأرقام بتتحدّث لوحدها مع أي تغيير.\n'
                       '• استخدمها في متابعة المندوبين وقبل حساب الحوافز.',
                       'Performance here is split by the SOFTECH user code that issued the invoice, and the default period is the last 30 days.\n'
                       '• The filters under the title work like the sales dashboard, and the figures update by themselves on any change.\n'
                       '• Use it to follow up salespeople and before working out incentives.')},
            {'target': 'analytics-performance-kpis', 'text': T('مؤشرات الفترة: الإيرادات، صافي الربح والهامش، الخصومات، الفواتير، العملاء الفريدون، والأفضل أداءً.',
                                              'Period KPIs: revenue, net profit and margin, discounts, invoices, unique customers and the top performer.'),
             'more': T('دي إجماليات كل الموظفين في الفترة والفلاتر المختارة.\n'
                       '• «عملاء فريدون (PIC)» عدد أكواد العملاء المختلفة، وتحته عدد الحسابات.\n'
                       '• «الأفضل أداءً» بيعرض كود واسم الموظف صاحب أعلى إيراد.',
                       'These are the totals for all employees in the chosen period and filters.\n'
                       '• "Unique customers (PIC)" is the number of different customer codes, with the account count under it.\n'
                       '• "Top performer" shows the code and name of the employee with the highest revenue.')},
            {'target': 'analytics-performance-podium', 'text': T('«المتصدرون»: أعلى ثلاثة موظفين إيراداً — يظهر عند وجود ثلاثة موظفين على الأقل.',
                                              '«المتصدرون» (Leaders): the top three employees by revenue — shown when there are at least three employees.'),
             'more': T('منصة 🥇🥈🥉 بكود واسم وإيراد كل واحد من الثلاثة الأوائل.\n'
                       '• الترتيب بالإيراد بس — للربح أو الخصم رتّب الجدول تحت.\n'
                       '• مفيدة في اجتماع الفريق أو تحفيز الموظفين.',
                       'A 🥇🥈🥉 podium with the code, name and revenue of each of the top three.\n'
                       '• The ranking is by revenue only — sort the table below for profit or discount.\n'
                       '• Handy for a team meeting or to motivate staff.')},
            {'target': 'analytics-performance-tabs', 'text': T('اختر العرض: «الموظفون» أو «الفروع» أو «التوزيع الزمني».',
                                              'Choose the view: «الموظفون» (Employees), «الفروع» (Branches) or «التوزيع الزمني» (Time distribution).'),
             'more': T('• «الموظفون»: جدول بكل موظف.\n'
                       '• «الفروع»: عدد الموظفين وتوزيع الإيراد عليهم في كل فرع.\n'
                       '• «التوزيع الزمني»: الإيراد بالساعة ويوم الأسبوع، عشان تعرف إمتى محتاج موظفين أكتر.',
                       '• "Employees": a table with every employee.\n'
                       '• "Branches": the number of employees and how revenue is spread among them in each branch.\n'
                       '• "Time distribution": revenue by hour and weekday, so you know when you need more staff.')},
            {'target': 'analytics-performance-content', 'text': T('محتوى التبويب المختار: جدول الموظفين مرتباً بالإيراد افتراضياً، أو الفروع، أو الإيراد بالساعة ويوم الأسبوع.',
                                              'The selected tab: the employee table sorted by revenue by default, the branches, or revenue by hour and weekday.'),
             'more': T('أول 3 صفوف في جدول الموظفين متلوّنة بلون خفيف.\n'
                       '• اضغط عنوان أي عمود عشان ترتّب بيه (الربح، الخصم، متوسط الفاتورة…).\n'
                       '• الأرقام للعرض بس — مفيش تعديل هنا.',
                       'The first 3 rows of the employee table are lightly highlighted.\n'
                       '• Click any column title to sort by it (profit, discount, average invoice…).\n'
                       '• The figures are read-only — nothing is edited here.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'analytics.reservations',
        'routes': ['/analytics/reservations'],
        'title': T('تحليلات الحجوزات', 'Reservation analytics'),
        'summary': T('إجمالي الحجوزات ومعدل التسليم ومتوسط وقت التسليم والطلب المفقود (ملغي/منتهي)، معدل التسليم بالفرع، أكثر 20 صنفاً محجوزاً، التحويل حسب القناة، والطلب المفقود حسب الصنف.',
                     'Total reservations, fulfilment rate, average time to fulfil and lost demand (cancelled/expired), fulfilment by branch, the top 20 reserved items, conversion by channel, and lost demand by item.'),
        'audience': T('الإدارة والمشرفون.', 'Management and supervisors.'),
        'related': ['reservations.board'],
        'tour': [
            {'target': 'analytics-reservations-filters', 'text': T('حدد الفترة من/إلى والفرع؛ «مسح» يلغي الفلاتر و«🔄 تحديث» يعيد التحميل.',
                                              'Set the from/to dates and branch; «مسح» (Clear) resets the filters and «🔄 تحديث» (Refresh) reloads.'),
             'more': T('التاريخ هنا تاريخ إنشاء الحجز، ولو سبت التواريخ فاضية بيحسب كل الحجوزات.\n'
                       '• لو إنت مش مدير أو مشتريات أو كول سنتر، بتشوف حجوزات فرعك بس.\n'
                       '• الأرقام بتتحسب في السيرفر من الحجوزات المسجلة عندنا.',
                       'The date here is the reservation creation date; leaving the dates empty counts all reservations.\n'
                       '• If you are not admin, purchasing or call center, you see your own branch only.\n'
                       '• The figures are computed on the server from the reservations recorded in our system.')},
            {'target': 'analytics-reservations-kpis', 'text': T('إجمالي الحجوزات، معدل التسليم، متوسط وقت التسليم، والطلب المفقود (ملغي/منتهي).',
                                              'Total reservations, fulfilment rate, average time to fulfil, and lost demand (cancelled/expired).'),
             'more': T('• «معدل التسليم» = المُسلَّم ÷ الإجمالي.\n'
                       '• «متوسط وقت التسليم» بالساعات من إنشاء الحجز لحد ما حالته بقت «تم التسليم».\n'
                       '• «طلب مفقود» = ملغي + منتهي — بيع ضاع.\n'
                       '• الصف اللي تحته بيوضح الحجوزات المفتوحة حسب حالتها (قيد الانتظار، مخزون متاح، تم التواصل، مؤكد).',
                       '• "Fulfilment rate" = fulfilled ÷ total.\n'
                       '• "Average time to fulfil" is in hours from creating the reservation until its status became "Fulfilled".\n'
                       '• "Lost demand" = cancelled + expired — lost sales.\n'
                       '• The row below shows open reservations by status (pending, stock available, contacted, confirmed).')},
            {'target': 'analytics-reservations-by-branch', 'text': T('عدد الحجوزات ونسبة التسليم لكل فرع.',
                                              'Reservation count and fulfilment rate per branch.'),
             'more': T('بيقارن الفروع ببعض: فرع عنده حجوزات كتير ونسبة تسليم واطية معناه إن العملاء بيستنوا ومش بيستلموا.\n'
                       '• راجع معاه لوحة الحجوزات عشان تشوف الحجوزات المتأخرة.',
                       'Compares branches: a branch with many reservations and a low fulfilment rate means customers wait and do not receive their items.\n'
                       '• Check the reservations board with it to see the late reservations.')},
            {'target': 'analytics-reservations-top-items', 'text': T('أكثر 20 صنفاً محجوزاً مع عدد الحجوزات لكل صنف.',
                                              'The 20 most reserved items with the reservation count for each.'),
             'more': T('الصنف اللي بيتحجز كتير غالباً ناقص في الفروع أو عليه طلب عالي.\n'
                       '• ابعت القائمة دي للمشتريات عشان يزوّدوا الكمية أو يراجعوا حد الطلب.',
                       'An item reserved often is usually short in the branches or in high demand.\n'
                       '• Send this list to purchasing so they raise the quantity or review the reorder level.')},
            {'target': 'analytics-reservations-channels', 'text': T('لكل قناة: الإجمالي، المُسلَّم، ونسبة التحويل.',
                                              'Per channel: total, fulfilled and conversion rate.'),
             'more': T('بيوضح أنهي قناة (الفرع، التليفون، واتساب…) حجوزاتها بتتحول لبيع فعلاً.\n'
                       '• نسبة التحويل = المُسلَّم ÷ إجمالي حجوزات القناة.',
                       'Shows which channel (branch, phone, WhatsApp…) has reservations that actually turn into sales.\n'
                       '• Conversion rate = fulfilled ÷ the channel total.')},
            {'target': 'analytics-reservations-lost', 'text': T('الأصناف الأكثر في الطلب المفقود (ملغي + منتهي).',
                                              'The items with the most lost demand (cancelled + expired).'),
             'more': T('أعلى 15 صنف في الحجوزات اللي اتلغت أو انتهت.\n'
                       '• ده أوضح مؤشر على بيع ضاع بسبب النقص — ابدأ بيه مع المشتريات أو بالتحويل من فرع تاني.',
                       'The top 15 items among cancelled or expired reservations.\n'
                       '• This is the clearest sign of sales lost to shortages — start with it with purchasing or with a transfer from another branch.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'analytics.transfers',
        'routes': ['/analytics/transfers'],
        'title': T('تحليلات طلبات التحويل', 'Transfer analytics'),
        'summary': T('أداء وسير عمل التحويلات بين الفروع لآخر 7/30/90 يوماً أو سنة.', 'Performance and flow of inter-branch transfers for the last 7/30/90 days or a year.'),
        'audience': T('الإدارة والمشرفون والمشتريات.', 'Management, supervisors and purchasing.'),
        'tabs': [
            {'key': 'analytics', 'title': T('📊 التحليلات', '📊 Analytics'), 'body': T('إجمالي الطلبات، نسب الإكمال والرفض، متوسط دورة الطلب ووقت الاستجابة، أكثر الأصناف تحويلاً، أنشط المسارات، ومعدل الرفض بالفرع المصدر.', 'Total requests, completion and rejection rates, average cycle and response time, most-transferred items, busiest routes, and rejection rate by supplying branch.')},
            {'key': 'discrepancy', 'title': T('⚠️ تقرير التباينات', '⚠️ Discrepancy report'), 'body': T('طلبات استُلمت كمياتها مختلفة عن المعتمد — راجعها مع الفرعين.', 'Requests received in quantities different from approved — review them with both branches.')},
        ],
        'related': ['transfers.list'],
        'tour': [
            {'target': 'analytics-transfers-tabs', 'text': T('بدّل بين «التحليلات» و«تقرير التباينات».',
                                              'Switch between «التحليلات» (Analytics) and «تقرير التباينات» (Discrepancy report).'),
             'more': T('• «التحليلات»: سرعة وجودة التحويلات بين الفروع.\n'
                       '• «تقرير التباينات»: طلبات اتستلمت بكمية مختلفة عن المعتمد، برقم الطلب والصنف والمعتمد والمستلم والفرق — راجعها مع الفرعين.\n'
                       '• لو إنت مش مدير أو مشتريات أو كول سنتر بتشوف تحويلات فرعك بس.',
                       '• "Analytics": how fast and how well transfers between branches go.\n'
                       '• "Discrepancy report": requests received in a quantity different from the approved one, with request number, item, approved, received and the difference — review them with both branches.\n'
                       '• If you are not admin, purchasing or call center you see your own branch transfers only.')},
            {'target': 'analytics-transfers-period', 'text': T('الفترة: آخر 7 أو 30 أو 90 يوماً أو سنة — تظهر في تبويب «التحليلات» فقط.',
                                              'The period: last 7, 30 or 90 days or a year — shown on the «التحليلات» (Analytics) tab only.'),
             'more': T('الافتراضي آخر 30 يوم، والفترة بتتحسب من تاريخ إنشاء الطلب.\n'
                       '• أول ما تغيّرها الأرقام كلها بتتحسب تاني في السيرفر.',
                       'The default is the last 30 days, counted from the request creation date.\n'
                       '• As soon as you change it, all figures are recomputed on the server.')},
            {'target': 'analytics-transfers-kpis', 'text': T('إجمالي الطلبات، نسبة الإكمال، نسبة الرفض، ومتوسط دورة الطلب ووقت الاستجابة.',
                                              'Total requests, completion rate, rejection rate, and average cycle and response time.'),
             'more': T('• «متوسط دورة الطلب»: الساعات من إرسال الطلب لحد ما اكتمل.\n'
                       '• «متوسط الاستجابة»: الساعات من الإرسال لحد ما الفرع المصدر راجعه.\n'
                       '• نسبة رفض عالية معناها طلبات بتتبعت لفرع مفيهوش الصنف — راجع المخزون قبل الطلب.',
                       '• "Average cycle": hours from sending the request until it was completed.\n'
                       '• "Average response": hours from sending until the supplying branch reviewed it.\n'
                       '• A high rejection rate means requests go to a branch without the item — check stock before requesting.')},
            {'target': 'analytics-transfers-top-items', 'text': T('أكثر الأصناف تحويلاً بعدد الطلبات وإجمالي الوحدات.',
                                              'The most transferred items by request count and total units.'),
             'more': T('صنف بيتحوّل كتير بين الفروع ممكن يكون توزيعه على الفروع محتاج مراجعة.\n'
                       '• شاركها مع المشتريات عشان التوريد يروح للفرع اللي بيبيع فعلاً.',
                       'An item transferred a lot between branches may need its distribution reviewed.\n'
                       '• Share it with purchasing so supply goes to the branch that actually sells it.')},
            {'target': 'analytics-transfers-routes', 'text': T('أنشط مسارات التحويل من الفرع الطالب إلى الفرع المصدر.',
                                              'The busiest transfer routes from requesting to supplying branch.'),
             'more': T('كل سطر «الفرع الطالب ← الفرع المصدر» وعدد الطلبات.\n'
                       '• تحت هتلاقي جدول نسبة الرفض لكل فرع مصدر — مفيد لو فرع بيرفض كتير.',
                       'Each line is "requesting branch → supplying branch" with the request count.\n'
                       '• Below you find the rejection rate per supplying branch — useful when one branch rejects a lot.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'analytics.forecasting',
        'routes': ['/forecasting'],
        'title': T('محرك التنبؤ بالمبيعات', 'Sales forecast engine'),
        'summary': T('تشغيل التنبؤ بالمبيعات للأصناف ومتابعة دقته ومؤشرات الموسمية.', 'Run the item sales forecast and follow its accuracy and seasonality indices.'),
        'audience': T('المشتريات والإدارة والصيادلة والجودة.', 'Purchasing, management, pharmacists and quality.'),
        'tabs': [
            {'key': 'runs', 'title': T('🏃 سجل التشغيلات', '🏃 Run history'), 'body': T('كل تشغيل: البداية والنهاية والأصناف المعالجة والحالة. «تشغيل التنبؤ الآن» لتشغيل جديد.', 'Each run: start, end, items processed and status. "Run forecast now" starts a new one.')},
            {'key': 'accuracy', 'title': T('🎯 دقة التنبؤ', '🎯 Accuracy'), 'body': T('التنبؤ مقابل الفعلي لكل صنف وفترة، ومتوسط الخطأ (MAPE) — الأقل أفضل.', 'Forecast vs actual per item and period, and the average error (MAPE) — lower is better.')},
            {'key': 'seasonality', 'title': T('📅 مؤشرات الموسمية', '📅 Seasonality'), 'body': T('مؤشر كل شهر لكل صنف أو تصنيف: أكبر من 1 = موسم مرتفع، أقل من 1 = موسم منخفض. «إعادة حساب الموسمية» بعد بيانات جديدة.', 'A monthly index per item or class: above 1 = high season, below 1 = low season. "Recalculate seasonality" after new data.')},
        ],
        'related': ['analytics.scenarios', 'purchasing.engine'],
        'tour': [
            {'target': 'analytics-forecasting-run', 'text': T('«▶ تشغيل التنبؤ الآن» يبدأ تشغيلاً جديداً لتنبؤ المبيعات.',
                                              '«▶ تشغيل التنبؤ الآن» (Run forecast now) starts a new sales forecast run.'),
             'more': T('بيحسب في السيرفر تنبؤ مبيعات الأصناف من تاريخ البيع، والزر بيفضل «⏳ جاري التشغيل...» لحد ما يخلص وبعدين تظهر رسالة.\n'
                       '• السيرفر بيسمح بيه للمدير والمشرف والمشتريات بس؛ أي حد تاني هتظهر له «غير مصرح».\n'
                       '• التشغيل الجديد بيظهر في «سجل التشغيلات».',
                       'It computes the item sales forecast on the server from sales history; the button stays "⏳ Running..." until it finishes, then a message appears.\n'
                       '• The server allows it for admin, supervisor and purchasing only; anyone else gets "Not authorised".\n'
                       '• The new run appears in "Run history".')},
            {'target': 'analytics-forecasting-kpis', 'text': T('آخر تشغيل وحالته، عدد التشغيلات المكتملة، ومتوسط الخطأ (MAPE).',
                                              'Last run and its status, completed runs count, and the average error (MAPE).'),
             'more': T('• حالة آخر تشغيل بتتلوّن: أخضر مكتمل، أحمر فشل.\n'
                       '• «متوسط دقة التنبؤ (MAPE)» متوسط نسبة الخطأ بين التنبؤ والفعلي — كل ما يقل كل ما التنبؤ أدق.\n'
                       '• لو الحالة فشل لأكتر من مرة بلّغ مدير النظام.',
                       '• The last run status is coloured: green completed, red failed.\n'
                       '• "Average accuracy (MAPE)" is the average error percentage between forecast and actual — the lower, the more accurate.\n'
                       '• If the status fails more than once, tell the system admin.')},
            {'target': 'analytics-forecasting-tabs', 'text': T('التبويبات: «سجل التشغيلات» و«دقة التنبؤ» و«مؤشرات الموسمية».',
                                              'Tabs: «سجل التشغيلات» (Run history), «دقة التنبؤ» (Accuracy) and «مؤشرات الموسمية» (Seasonality).'),
             'more': T('• «سجل التشغيلات»: كل تشغيل اتعمل.\n'
                       '• «دقة التنبؤ»: التنبؤ مقابل الفعلي لكل صنف وفترة مع MAPE وMAE.\n'
                       '• «مؤشرات الموسمية»: مؤشر كل شهر — أكبر من 1 يعني موسم عالي، أقل من 1 موسم واطي.',
                       '• "Run history": every run made.\n'
                       '• "Accuracy": forecast vs actual per item and period with MAPE and MAE.\n'
                       '• "Seasonality": a monthly index — above 1 means high season, below 1 low season.')},
            {'target': 'analytics-forecasting-runs', 'text': T('كل تشغيل: البداية والنهاية والأصناف المعالجة والحالة ومن شغّله — يظهر عند وجود تشغيلات.',
                                              'Each run: start, end, items processed, status and who triggered it — shown once runs exist.'),
             'more': T('التشغيل اللي لسه شغال بيبان في عمود «انتهى في» كـ«⏳ جاري...».\n'
                       '• عمود «بواسطة» بيوضح مين شغّله، و«ملاحظات» فيها أي رسالة من المحرك.\n'
                       '• لو مفيش تشغيلات هتلاقي زر «تشغيل أول تنبؤ».',
                       'A run still in progress shows "⏳ Running..." in the "Finished at" column.\n'
                       '• The "By" column shows who triggered it, and "Notes" holds any message from the engine.\n'
                       '• With no runs yet you will see a "Run first forecast" button.')},
            {'target': 'analytics-forecasting-seasonality-recalc', 'text': T('في تبويب «مؤشرات الموسمية»: «↺ إعادة حساب الموسمية» يطلب إعادة حساب المؤشرات.',
                                              'On the «مؤشرات الموسمية» (Seasonality) tab: «↺ إعادة حساب الموسمية» (Recalculate seasonality) asks to recompute the indices.'),
             'more': T('استخدمه بعد ما شهور مبيعات جديدة تتسحب، عشان المؤشرات تعكس آخر سنة.\n'
                       '• السيرفر بيسمح بيه للمدير والمشرف والمشتريات بس.\n'
                       '• بعد الطلب الجدول بيتحمّل تاني.',
                       'Use it after new months of sales are pulled, so the indices reflect the latest year.\n'
                       '• The server allows it for admin, supervisor and purchasing only.\n'
                       '• After the request the table reloads.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'analytics.targets',
        'routes': ['/targets'],
        'title': T('الأهداف البيعية', 'Sales targets'),
        'summary': T('تحديد هدف (للشبكة أو فرع أو مندوب بكوده في SOFTECH) بقيمة صافي المبيعات أو عدد الفواتير، ومتابعة التحقيق لحظياً: المحقق، الباقي، المتوقع حتى اليوم، وهل الأداء متقدّم أم متأخّر.',
                     'Set a target (for the network, a branch or a salesperson by SOFTECH code) as net sales or invoice count, and follow attainment live: achieved, remaining, expected by today, and whether performance is ahead or behind.'),
        'audience': T('الإدارة والمشرفون والمشتريات والصيادلة.', 'Management, supervisors, purchasing and pharmacists.'),
        'related': ['analytics.kpi_board', 'analytics.scenarios'],
        'tour': [
            {'target': 'analytics-targets-header', 'text': T('الأهداف البيعية: المحقق لحظياً مقابل الهدف لكل هدف.',
                                              'Sales targets: live achievement versus target for each goal.'),
             'more': T('المحقق بيتحسب في السيرفر كل ما تفتح الصفحة من فواتير SOFTECH المسحوبة: صافي المبيعات = مبيعات − مرتجعات، أو عدد فواتير البيع.\n'
                       '• محدش بيكتب المحقق بإيده — اللي بيتكتب هو الهدف بس.\n'
                       '• الأهداف اللي بتيجي من اعتماد سيناريو بتظهر هنا كمان.',
                       'Achievement is computed on the server each time you open the page, from the pulled SOFTECH invoices: net sales = sales − returns, or the count of sales invoices.\n'
                       '• Nobody types the achievement — only the target is entered.\n'
                       '• Targets that come from committing a scenario also show here.')},
            {'target': 'analytics-targets-new', 'text': T('«+ هدف جديد» يفتح نموذج الهدف — يظهر للمدير والمشرف والمشتريات فقط.',
                                              '«+ هدف جديد» (New target) opens the target form — shown to admin, supervisor and purchasing only.'),
             'more': T('النموذج فيه: اسم الهدف، النطاق («الشبكة كاملة» أو «فرع» أو «مندوب» بكوده في SOFTECH)، المؤشر («صافي المبيعات» أو «عدد الفواتير»)، من/إلى، والقيمة المستهدفة.\n'
                       '• «حفظ الهدف» بيشتغل بعد ما تكمّل الحقول المطلوبة، والزر نفسه بيتحول لـ«إغلاق».\n'
                       '• السيرفر بيرفض أي حد مش مدير أو مشرف أو مشتريات.',
                       'The form has: target name, scope ("Whole network", "Branch" or "Salesperson" by SOFTECH code), metric ("Net sales" or "Invoice count"), from/to, and the target value.\n'
                       '• "Save target" works once the required fields are filled, and the button itself turns into "Close".\n'
                       '• The server refuses anyone who is not admin, supervisor or purchasing.')},
            {'target': 'analytics-targets-list', 'text': T('بطاقة لكل هدف: النطاق والمؤشر والفترة والأيام الباقية — تظهر عند وجود أهداف.',
                                              'A card per target: scope, metric, period and days left — shown once targets exist.'),
             'more': T('كل بطاقة فيها المحقق «من» الهدف والنسبة، والمتوقع حتى اليوم.\n'
                       '• ✕ في ركن البطاقة بيحذف الهدف على طول من غير سؤال تأكيد — اتأكد قبل ما تضغط.\n'
                       '• الحذف متاح للمدير والمشرف والمشتريات بس.',
                       'Each card shows the achieved value "of" the target, the percentage, and the expected-to-date value.\n'
                       '• The ✕ in the card corner deletes the target straight away without a confirmation — be sure before pressing.\n'
                       '• Deleting is for admin, supervisor and purchasing only.')},
            {'target': 'analytics-targets-pace', 'text': T('حالة الوتيرة: متقدّم، متأخّر، تحقّق، أو لم يتحقق.',
                                              'Pace status: ahead, behind, met, or missed.'),
             'more': T('• أثناء الفترة: «متقدّم» لو المحقق ≥ المتوقع حتى اليوم، وإلا «متأخّر».\n'
                       '• بعد نهاية الفترة: «تحقّق» لو المحقق ≥ الهدف، وإلا «لم يتحقق».\n'
                       '• «متأخّر» بدري في الشهر إشارة تتحرك فيها قبل ما الشهر يخلص.',
                       '• During the period: "Ahead" if achieved ≥ expected to date, otherwise "Behind".\n'
                       '• After the period ends: "Met" if achieved ≥ target, otherwise "Missed".\n'
                       '• "Behind" early in the month is a signal to act before the month ends.')},
            {'target': 'analytics-targets-progress', 'text': T('شريط التحقيق؛ الخط الرمادي هو المتوقّع حتى اليوم.',
                                              'The attainment bar; the grey line marks the expected-to-date value.'),
             'more': T('المتوقع حتى اليوم = الهدف × الأيام اللي فاتت ÷ أيام الفترة كلها.\n'
                       '• الشريط أخضر لو متقدّم أو متحقق، وبرتقالي لو متأخر أو لم يتحقق.\n'
                       '• لو الشريط عدّى الخط الرمادي يبقى إنت سابق الوتيرة.',
                       'Expected to date = target × days elapsed ÷ total days in the period.\n'
                       '• The bar is green when ahead or met, and amber when behind or missed.\n'
                       '• If the bar passes the grey line you are ahead of pace.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'analytics.kpi_board',
        'routes': ['/kpi-board'],
        'title': T('لوحة مؤشرات الفروع (تارجت/تحقيق)', 'Branch KPI board (target/achievement)'),
        'summary': T('مصفوفة فرع × مؤشر لشهر (مثل ملف Excel للتارجت والتحقيق): المحقق من فواتير SOFTECH (صافي بعد المرتجعات) مقابل التارجت من الأهداف البيعية، مع الوتيرة وإجمالي الفروع والكول سنتر.',
                     'A branch × KPI matrix for a month (like the target/achievement Excel): achieved from SOFTECH invoices (net after returns) vs target from sales targets, with pace, the branch total and the call center.'),
        'audience': T('الإدارة والمشرفون.', 'Management and supervisors.'),
        'tips': [T('لو «لا توجد بيانات محسوبة لهذا الشهر» يجب تشغيل حساب مؤشرات الشهر أولاً.', 'If "no computed data for this month", the month\'s KPI calculation must run first.')],
        'related': ['analytics.targets'],
        'tour': [
            {'target': 'analytics-kpi-board-period', 'text': T('اختار الشهر والسنة.',
                                              'Choose the month and year.'),
             'more': T('اللوحة بتتحمّل لوحدها أول ما تغيّر الشهر أو السنة.\n'
                       '• لو ظهر «لا توجد بيانات محسوبة لهذا الشهر» يبقى حساب مؤشرات الشهر لسه ما اتعملش — بلّغ مدير النظام.\n'
                       '• في نص الشهر الوتيرة بتقارن بالمتوقع حتى انهارده.',
                       'The board loads by itself as soon as you change the month or year.\n'
                       '• If "No computed data for this month" shows, the month KPI calculation has not run yet — tell the system admin.\n'
                       '• Mid-month, the pace compares against the expected value up to today.')},
            {'target': 'analytics-kpi-board-table', 'text': T('كل فرع: المحقق مقابل التارجت والنسبة لكل مؤشر.',
                                              'Each branch: achieved vs target and the percentage for each metric.'),
             'more': T('المؤشرات: «نقدى + توصيل»، «آجل»، «معامل الربحية»، «عدد العملاء»، «التجميل».\n'
                       '• «محقق» محسوب في السيرفر من فواتير SOFTECH، و«تارجت» من هدف الفرع للشهر ده.\n'
                       '• لون النسبة: أخضر من 90% وفوق، برتقالي من 75%، أحمر أقل من كده، وتحتها الوتيرة.',
                       'Metrics: "Cash + delivery", "Credit", "Profitability", "Customer count", "Beauty".\n'
                       '• "Achieved" is computed on the server from SOFTECH invoices, "Target" from the branch target for that month.\n'
                       '• Percentage colour: green from 90% up, amber from 75%, red below, with the pace under it.')},
            {'target': 'analytics-kpi-board-totals', 'text': T('«إجمالى الفروع»: مجموع المحقق مقابل تارجت الشبكة.',
                                              '"Branch total": the summed achievement against the network target.'),
             'more': T('المحقق = مجموع محقق الفروع اللي في الجدول.\n'
                       '• التارجت = هدف «الشبكة كاملة» لو موجود، ولو مش موجود بيتجمع من أهداف الفروع.\n'
                       '• الكول سنتر مش داخل في الإجمالي ده.',
                       'Achieved = the sum of the branches in the table.\n'
                       '• Target = the "Whole network" target if one exists, otherwise the sum of the branch targets.\n'
                       '• The call center is not included in this total.')},
            {'target': 'analytics-kpi-board-call-center', 'text': T('أداء الكول سنتر في جدول لوحده.',
                                              'The call center\'s performance in its own table.'),
             'more': T('بيظهر بس لو الكول سنتر عنده بيانات في الشهر ده.\n'
                       '• مؤشراته: «نقدى + توصيل»، «معامل الربحية»، «التجميل»، «عدد الطلبات» و«عدد المكالمات»، كل واحد محقق مقابل تارجت.',
                       'It shows only when the call center has data for that month.\n'
                       '• Its metrics: "Cash + delivery", "Profitability", "Beauty", "Order count" and "Call count", each achieved vs target.')},
            {'target': 'analytics-kpi-board-legend', 'text': T('ملاحظة عن وحدات الأرقام ومصدرها.',
                                              'A note on the units of the figures and their source.'),
             'more': T('القيم المالية بالجنيه، و«محقق» صافي بعد المرتجعات، و«تارجت» من الأهداف البيعية.\n'
                       '• الرابط فيها بيوديك لصفحة «الأهداف البيعية» لو عايز تضيف أو تراجع هدف.',
                       'Money values are in pounds, "Achieved" is net after returns, and "Target" comes from sales targets.\n'
                       '• Its link takes you to the "Sales targets" page if you want to add or review a target.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'analytics.scenarios',
        'routes': ['/forecast-scenarios'],
        'title': T('سيناريوهات التنبؤ بالأهداف', 'Target forecast scenarios'),
        'summary': T('توليد الأهداف بالعوامل بدل التخمين: أنشئ سيناريو لشهر، اضبط العوامل (النمو، التضخم، رفع العروض…)، «احسب التنبؤ» بنموذجين (A: نمو الهدف، B: مزيج مرجّح) ومتوسطهما، راجع لكل فرع/مندوب/فئة، ثم «اعتماد الأهداف» فتظهر في لوحة المؤشرات. «اختبار رجعي» يقارن دقة النموذجين على الأشهر السابقة ويختار الأفضل.',
                     'Generate targets from factors instead of guesses: create a scenario for a month, tune factors (growth, inflation, promo uplift…), "Calculate forecast" with two models (A: target growth, B: weighted blend) and their average, review by branch/salesperson/category, then "Commit targets" so they show on the KPI board. A "backtest" compares both models on past months and picks the better one.'),
        'audience': T('الإدارة والمشرفون والمشتريات.', 'Management, supervisors and purchasing.'),
        'related': ['analytics.kpi_board', 'incentives.programs'],
        'tour': [
            {'target': 'analytics-scenarios-new', 'text': T('«+ سيناريو جديد»: الاسم والنطاق والشهر والسنة والنموذج — للمدير والمشرف والمشتريات.',
                                              '«+ سيناريو جديد» (New scenario): name, scope, month, year and model — for admin, supervisor and purchasing.'),
             'more': T('النطاق: «الفروع» أو «المندوبين» أو «الفئات»، والنموذج: A (نمو الهدف) أو B (مزيج مرجّح) أو متوسطهم.\n'
                       '• «إنشاء» بيحفظ السيناريو كـ«مسودة» ويفتحه على طول.\n'
                       '• مفيش أي هدف بيتغير لحد ما تعتمد السيناريو.',
                       'Scope: "Branches", "Salespeople" or "Categories"; model: A (target growth), B (weighted blend) or their average.\n'
                       '• "Create" saves the scenario as a "Draft" and opens it straight away.\n'
                       '• No target changes until you commit the scenario.')},
            {'target': 'analytics-scenarios-backtest', 'text': T('دقة النموذجين على الأشهر السابقة (WAPE)؛ افتحها للعرض، و«تشغيل اختبار جديد» حسب الصلاحية.',
                                              'Both models\' accuracy on past months (WAPE); expand to view, and «تشغيل اختبار جديد» (Run new test) depends on permission.'),
             'more': T('اضغط العنوان «🏁 دقة النماذج» عشان يتفتح: لكل مؤشر خطأ A وB (WAPE%) والأفضل والانحياز.\n'
                       '• WAPE الأقل = النموذج أدق، فاختاره في السيناريو.\n'
                       '• «تشغيل اختبار جديد» بيعيد المقارنة على الأشهر السابقة.',
                       'Click the "🏁 Model accuracy" title to expand it: per metric, the A and B error (WAPE%), the better one and the bias.\n'
                       '• Lower WAPE = more accurate model, so pick it in the scenario.\n'
                       '• "Run new test" repeats the comparison on past months.')},
            {'target': 'analytics-scenarios-list', 'text': T('قائمة السيناريوهات بحالتها (مسودة/محسوب/معتمد)؛ اختر سيناريو لعرض تفاصيله.',
                                              'The scenarios with their status (draft/calculated/committed); pick one to see its details.'),
             'more': T('• «مسودة»: اتعمل ولسه ما اتحسبش.\n'
                       '• «محسوب»: النتائج جاهزة للمراجعة.\n'
                       '• «معتمد»: أهدافه اتكتبت في الأهداف البيعية.\n'
                       'التفاصيل بتفتح جنب القائمة، وفيها زر «حذف» بعد تأكيد.',
                       '• "Draft": created but not calculated yet.\n'
                       '• "Calculated": results ready for review.\n'
                       '• "Committed": its targets were written to sales targets.\n'
                       'Details open next to the list, with a "Delete" button after confirmation.')},
            {'target': 'analytics-scenarios-knobs', 'text': T('بعد اختيار سيناريو: النموذج وحد الحافز والنمو المرجعي والتضخم ورفع العروض.',
                                              'After picking a scenario: model, incentive threshold, benchmark growth, inflation and promotion lift.'),
             'more': T('دي مدخلات المعادلة مش النتيجة — اضبطها واضغط «حفظ العوامل العامة».\n'
                       '• تحتها جدول عوامل كل مؤشر (هدف النمو، أوزان الشهور، المؤشر الموسمي) وليه زر حفظ لوحده؛ أوزان Model B يُفضل مجموعها 1.0.\n'
                       '• بعد أي تعديل لازم تحسب تاني.',
                       'These are inputs to the formula, not the result — tune them and press "Save global factors".\n'
                       '• Below is the per-metric factor table (growth target, month weights, seasonal index) with its own save button; Model B weights should add up to 1.0.\n'
                       '• After any change you must calculate again.')},
            {'target': 'analytics-scenarios-actions', 'text': T('«⚙️ احسب التنبؤ» ثم «✅ اعتماد الأهداف» بعد الحساب — حسب الصلاحية.',
                                              '«⚙️ احسب التنبؤ» (Calculate forecast), then «✅ اعتماد الأهداف» (Commit targets) after calculating — permission-dependent.'),
             'more': T('• «⚙️ احسب التنبؤ»: السيرفر بيحسب النتائج بالعوامل المحفوظة، والحالة تبقى «محسوب».\n'
                       '• «✅ اعتماد الأهداف» (بعد رسالة تأكيد): بيكتب هدف الشهر لكل فرع/مندوب/فئة في «الأهداف البيعية» ويستبدل هدف موجود لنفس النطاق والمؤشر والشهر.\n'
                       '• بعد الاعتماد الأهداف بتظهر على لوحة المؤشرات.',
                       '• "⚙️ Calculate forecast": the server computes the results with the saved factors, and the status becomes "Calculated".\n'
                       '• "✅ Commit targets" (after a confirmation): writes the month target for each branch/salesperson/category into "Sales targets", replacing an existing target for the same scope, metric and month.\n'
                       '• After committing, the targets show on the KPI board.')},
            {'target': 'analytics-scenarios-results', 'text': T('النتائج بعد الحساب: الأساس وModel A وB والتنبؤ والهدف، ثم التفصيل حسب النطاق.',
                                              'Results after calculating: base, Model A and B, forecast and target, then the breakdown by scope.'),
             'more': T('• «الأساس» = نفس الشهر في السنة اللي فاتت.\n'
                       '• الهدف = التنبؤ ÷ حد الحافز (المكتوب تحت الجدول).\n'
                       '• تحت الإجمالي تفصيل أعلى 12 فرع/مندوب/فئة بالأساس والشهر السابق والتنبؤ والهدف — راجعهم قبل الاعتماد.',
                       '• "Base" = the same month last year.\n'
                       '• Target = forecast ÷ the incentive threshold (shown under the table).\n'
                       '• Under the total is the breakdown of the top 12 branches/salespeople/categories with base, previous month, forecast and target — review them before committing.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'analytics.insights',
        'routes': ['/insights'],
        'title': T('التقارير السردية', 'Narrative reports'),
        'summary': T('تقارير مكتوبة بلغة واضحة بالعربي والإنجليزي (يومي، أسبوعي، حتى تاريخه، شهري) تلخص المبيعات والخصومات والمقارنات والإنجازات والتنبيهات (حرج/تنبيه/معلومة) — للمديرين غير التقنيين، وتُنسخ لواتساب.',
                     'Plain-language reports in Arabic and English (daily, weekly, month-to-date, monthly) summarising sales, discounts, comparisons, achievements and alerts (critical/warning/info) — for non-technical directors, copyable to WhatsApp.'),
        'audience': T('الإدارة والمشرفون والجودة.', 'Management, supervisors and quality.'),
        'tabs': [
            {'key': 'reports', 'title': T('التقارير', 'Reports'), 'body': T('اختر نوع التقرير والفترة ← «توليد» ← اقرأ بالعربي أو الإنجليزي وانسخه.', 'Choose the report type and period → "Generate" → read in Arabic or English and copy it.')},
            {'key': 'rules', 'title': T('القواعد والحدود', 'Rules & thresholds'), 'body': T('الحدود التي تولّد التنبيهات: انخفاض مبيعات الفرع بنسبة، حدود الخصم لكل قناة، الفاتورة النقدية الكبيرة، المرتجعات، تراجع الهامش، فروق الجرد، الراكد، تغيّر المشتريات… اضبطها حسب سياسة الإدارة.', 'The thresholds that trigger alerts: branch sales drop %, discount limits per channel, large cash invoice, returns, margin drop, count variances, dead stock, purchase changes… tune them to management policy.')},
        ],
        'tour': [
            {'target': 'analytics-insights-domain', 'text': T('اختر المجال: «🧾 المبيعات» أو «📦 المشتريات والتموين».',
                                              'Choose the domain: «🧾 المبيعات» (Sales) or «📦 المشتريات والتموين» (Purchasing & supply).'),
             'more': T('كل مجال ليه تقاريره الخاصة؛ القائمة والتوليد بيتبعوا المجال المختار.\n'
                       '• «المبيعات»: أداء الفروع ومسئولي البيع والخصومات.\n'
                       '• «المشتريات والتموين»: حركة الشراء والتموين.',
                       'Each domain has its own reports; the list and the generation follow the chosen domain.\n'
                       '• "Sales": branch and salesperson performance and discounts.\n'
                       '• "Purchasing & supply": purchasing and supply activity.')},
            {'target': 'analytics-insights-view', 'text': T('«📋 التقارير» أو «⚙️ القواعد والحدود» — يظهر للمدير والمشرف فقط.',
                                              '«📋 التقارير» (Reports) or «⚙️ القواعد والحدود» (Rules & thresholds) — shown to admin and supervisor only.'),
             'more': T('«⚙️ القواعد والحدود» فيها الحدود اللي بتطلّع التنبيهات (انخفاض مبيعات الفرع، حدود الخصم لكل قناة، الفاتورة النقدية الكبيرة، المرتجعات…).\n'
                       '• أي تعديل بيأثر على التقارير اللي هتتولد بعد كده بس.\n'
                       '• السيرفر بيقبل التعديل من المدير والمشرف فقط.',
                       '"⚙️ Rules & thresholds" holds the limits that raise alerts (branch sales drop, discount limits per channel, large cash invoice, returns…).\n'
                       '• Any change affects only reports generated afterwards.\n'
                       '• The server accepts changes from admin and supervisor only.')},
            {'target': 'analytics-insights-period', 'text': T('نوع التقرير: يومي، أسبوعي، حتى تاريخه، أو شهري، ثم حدد التاريخ بجانبه.',
                                              'Report type: daily, weekly, month-to-date or monthly, then set the date next to it.'),
             'more': T('التواريخ لحد إمبارح بس. الأسبوعي لازم 7 أيام بالظبط، و«حتى تاريخه» بيبدأ من أول الشهر، والشهري لحد 31 يوم.\n'
                       '• تحت الشريط هتلاقي حالة البيانات: أخضر لو مكتملة، وأصفر لو فيه أيام ناقصة (الأرقام ساعتها أقل من الواقع).',
                       'Dates go up to yesterday only. Weekly must be exactly 7 days, month-to-date starts on the 1st, and monthly is up to 31 days.\n'
                       '• Below the bar is the data status: green when complete, yellow when days are missing (the figures are then lower than reality).')},
            {'target': 'analytics-insights-generate', 'text': T('«⚙️ توليد التقرير» للفترة المحددة — حسب الصلاحية، ويتعطل إذا كانت المدة غير صالحة.',
                                              '«⚙️ توليد التقرير» (Generate report) for the chosen period — permission-dependent, disabled if the span is invalid.'),
             'more': T('السيرفر بيكتب التقرير من الأرقام المتزامنة والحدود المضبوطة، وبيفتحه لوحده بعد التوليد.\n'
                       '• متاح للمدير والمشرف والمشتريات والجودة.\n'
                       '• لو البيانات ناقصة استنى المزامنة أو اطلب تعبئة الأيام الناقصة قبل ما تولّد.',
                       'The server writes the report from the synced figures and the set thresholds, and opens it by itself once generated.\n'
                       '• Available to admin, supervisor, purchasing and quality.\n'
                       '• If data is missing, wait for the sync or ask for the missing days to be filled before generating.')},
            {'target': 'analytics-insights-list', 'text': T('التقارير السابقة بعدد الملاحظات؛ اختر تقريراً لعرضه.',
                                              'Previous reports with their findings count; pick one to view it.'),
             'more': T('القائمة بتعرض تقارير نوع الفترة والمجال المختارين بس، بتاريخها وعدد الملاحظات فيها.\n'
                       '• اضغط أي تقرير عشان يفتح جنب القائمة.',
                       'The list shows only the reports of the chosen period type and domain, with their date and findings count.\n'
                       '• Click any report to open it next to the list.')},
            {'target': 'analytics-insights-report', 'text': T('بعد اختيار تقرير: النص بالعربي أو English، و«📋 نسخ (واتساب)» لنسخه.',
                                              'After picking a report: the text in Arabic or English, and «📋 نسخ (واتساب)» (Copy for WhatsApp) to copy it.'),
             'more': T('بدّل بين «عربي» و«English»، و«📋 نسخ (واتساب)» بينسخ النص عشان تلزقه في الجروب.\n'
                       '• تحت النص قائمة «الملاحظات» متلوّنة حسب الخطورة، وليها زر «📋 نسخ الملاحظات».',
                       'Switch between "Arabic" and "English"; "📋 Copy (WhatsApp)" copies the text so you can paste it in the group.\n'
                       '• Under the text is the "Findings" list coloured by severity, with a "📋 Copy findings" button.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'analytics.referral_stats',
        'routes': ['/referral-stats'],
        'title': T('إحصاءات إحالات الأطباء', 'Doctor referral statistics'),
        'summary': T('أداء الأطباء المُحيلين من مبيعات نقطة البيع المُرحَّلة: عدد الطلبات، صافي القيمة، عدد المرضى، وآخر إحالة لكل طبيب في الفترة.', 'Referring doctors\' performance from posted POS sales: orders, net value, patients and last referral per doctor in the period.'),
        'audience': T('الإدارة والمشرفون والصيادلة والجودة.', 'Management, supervisors, pharmacists and quality.'),
        'related': ['loyalty.referral', 'pos.order'],
        'tour': [
            {'target': 'analytics-referral-stats-filters', 'text': T('حدد الفترة «من تاريخ» و«إلى تاريخ».',
                                              'Set the period «من تاريخ» (From) and «إلى تاريخ» (To).'),
             'more': T('الصفحة بتفتح على كل الفترات؛ حدد تاريخين لو عايز شهر أو موسم معيّن.\n'
                       '• التاريخ هنا تاريخ مستند البيع.\n'
                       '• التغيير مش بيتطبق غير لما تضغط «تطبيق».',
                       'The page opens on all periods; set two dates for a specific month or season.\n'
                       '• The date here is the sale document date.\n'
                       '• Changes apply only when you press "Apply".')},
            {'target': 'analytics-referral-stats-apply', 'text': T('«تطبيق» يعيد تحميل الإحصاءات للفترة المحددة.',
                                              '«تطبيق» (Apply) reloads the statistics for the chosen period.'),
             'more': T('بيحسب في السيرفر من طلبات نقطة البيع اللي ليها طبيب مُحيل.\n'
                       '• بيحسب بس الطلبات المؤكدة (في انتظار الترحيل أو اترحّلت لـ SOFTECH) — المسودات والملغي مش داخلين.',
                       'It computes on the server from POS orders that have a referring doctor.\n'
                       '• Only committed orders count (queued for posting or posted to SOFTECH) — drafts and cancelled orders are excluded.')},
            {'target': 'analytics-referral-stats-summary', 'text': T('عدد الأطباء المُحيلين، عدد الطلبات، وإجمالي الصافي.',
                                              'Number of referring doctors, number of orders, and total net value.'),
             'more': T('ملخص سريع للفترة: كام طبيب بعتلنا مرضى، كام طلب، وقيمتهم الصافية.\n'
                       '• مفيد لمتابعة برامج التعاون مع الأطباء.',
                       'A quick summary for the period: how many doctors sent us patients, how many orders, and their net value.\n'
                       '• Useful for following up doctor partnership programs.')},
            {'target': 'analytics-referral-stats-table', 'text': T('لكل طبيب: الكود، الطلبات، إجمالي الصافي، عدد المرضى، وآخر إحالة.',
                                              'Per doctor: code, orders, total net, patients and last referral.'),
             'more': T('مرتب بعدد الطلبات وبعدين بالصافي.\n'
                       '• «عدد المرضى» = أكواد عملاء مختلفة، و«آخر إحالة» = آخر تاريخ بيع.\n'
                       '• طبيب «آخر إحالة» بتاعه قديمة ممكن يستاهل متابعة.',
                       'Sorted by order count, then by net value.\n'
                       '• "Patients" = different customer codes, and "Last referral" = the latest sale date.\n'
                       '• A doctor whose last referral is old may deserve a follow-up.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
]
