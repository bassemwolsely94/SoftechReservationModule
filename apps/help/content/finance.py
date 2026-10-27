from . import T

_SYNC = T('لو ظهرت «لا توجد بيانات» فالمزامنة المالية لم تُشغَّل لهذه الفترة — اطلب من المدير تشغيلها.', 'If "no data" shows, the finance sync has not run for this period — ask the admin to run it.')

_NOTE = T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour')

MODULE = {
    'key': 'finance', 'group': 'finance', 'icon': '💹',
    'title': T('المالية', 'Finance'),
    'summary': T(
        'الذكاء المالي مبني على بيانات SOFTECH المحاسبية: لوحة قيادة (الإيرادات، الأرباح، المشتريات، المصروفات، التدفق النقدي، المخزون)، قائمة الأرباح والخسائر، '
        'التدفقات النقدية بطريقة الدفع، تحليل المصروفات، ودليل الحسابات. وأدوات تشغيلية: تخطيط الشيكات المؤجلة، تتبع المدفوعات الخارجية (انستاباي، فودافون كاش…)، '
        'مراجعة كشوف الحساب البنكية، ومطابقة سداد فواتير الموردين. هذه الشاشات لا تكتب في SOFTECH.',
        'Financial intelligence built on SOFTECH accounting data: an executive dashboard (revenue, profit, purchases, expenses, cash flow, stock), the profit & loss statement, '
        'cash flows by payment method, expense analysis and the chart of accounts. And operational tools: post-dated cheque planning, external payment tracking (Instapay, Vodafone Cash…), '
        'bank statement review, and supplier invoice payment reconciliation. These screens do not write to SOFTECH.'),
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول المالية', 'A tour of the Finance module'),
            'summary': T('جزئين: «الذكاء المالي» للقراءة (لوحة القيادة، الأرباح والخسائر، التدفق النقدي، المصروفات، دليل الحسابات) — وأدوات التشغيل اليومي: الشيكات، المدفوعات الخارجية، مراجعة كشوف البنك، وسداد الموردين.',
                         'Two parts: "Financial intelligence" for reading (dashboard, profit & loss, cash flow, expenses, chart of accounts) — and the daily tools: cheques, external payments, bank statement review and supplier payments.'),
            'roles': ['admin', 'purchasing', 'pharmacist'],
            'steps': [
                {'target': 'nav-finance', 'nav': '/finance',
                 'text': T('نبدأ من «المالية» ← «الذكاء المالي».',
                           'Start at "Finance" → "Financial intelligence".'),
                 'more': T('كل أرقام الذكاء المالي بتتحسب في السيرفر من بيانات SOFTECH المحاسبية بعد المزامنة المالية — محدش بيكتب إجمالي بإيده، والشاشات دي مبتكتبش في SOFTECH.\n'
                           '• فوق الصفحة تبويبات: لوحة القيادة، الأرباح والخسائر، التدفق النقدي، المصروفات، دليل الحسابات.',
                           'Every financial intelligence figure is computed on the server from SOFTECH accounting data after the finance sync — nobody types a total, and these screens do not write to SOFTECH.\n'
                           '• At the top are tabs: Dashboard, Profit & loss, Cash flow, Expenses, Chart of accounts.')},
                {'target': 'finance-dashboard-period', 'route': '/finance/dashboard',
                 'text': T('لوحة القيادة: اختار السنة والشهر.',
                           'The dashboard: choose the year and month.'),
                 'more': T('الأرقام بتتحمّل لوحدها مع تغيير الشهر. لو الشهر ما اتزامنش هتظهر رسالة إن البيانات مش موجودة.\n'
                           '• لو ظهر «⚠ بيانات غير مكتملة» يبقى فيه مصادر لسه ما اتزامنتش للشهر ده.',
                           'Figures load by themselves when you change the month. If the month was not synced, a message says there is no data.\n'
                           '• "⚠ Incomplete data" means some sources are not synced yet for that month.')},
                {'target': 'finance-dashboard-kpis', 'route': '/finance/dashboard',
                 'text': T('المؤشرات: الإيرادات والأرباح والمشتريات والمصروفات والتدفق والمخزون.',
                           'The KPIs: revenue, profit, purchases, expenses, cash flow and stock.'),
                 'more': T('صورة سريعة للشهر لكل الفروع مع بعض. تحت كل رقم سطر صغير بيوضح الإجمالي أو الهامش.\n'
                           '• تحت الكروت: الاتجاه الشهري للسنة وتفصيل كل فرع.',
                           'A quick picture of the month for all branches together. Under each figure a small line shows the gross amount or the margin.\n'
                           '• Below the cards: the monthly trend for the year and a breakdown per branch.')},
                {'target': 'finance-pnl-statement', 'route': '/finance/pnl',
                 'text': T('«الأرباح والخسائر»: من الإيرادات لحد صافي الربح.',
                           '"Profit & loss": from revenue down to net profit.'),
                 'more': T('القائمة مرتبة زي أي قائمة دخل: الإيرادات ← تكلفة البضاعة ← إجمالي الربح ← المصروفات ← الربح التشغيلي وصافي الربح.\n'
                           '• الأرقام بين قوسين خصم (مرتجعات أو مصروفات).',
                           'The statement is ordered like any income statement: revenue → cost of goods → gross profit → expenses → operating and net profit.\n'
                           '• Figures in brackets are deductions (returns or expenses).')},
                {'target': 'finance-cashflow-kpis', 'route': '/finance/cashflow',
                 'text': T('«التدفق النقدي»: الداخل والخارج والصافي للشهر.',
                           '"Cash flow": inflow, outflow and net for the month.'),
                 'more': T('تحت الأرقام دي توزيع الداخل والخارج بطريقة الدفع (نقدي، شيك، تحويل، بطاقة، آجل).\n'
                           '• الصافي بالأزرق لو موجب وبالبرتقالي لو سالب.',
                           'Below these figures is the inflow and outflow split by payment method (cash, cheque, transfer, card, credit).\n'
                           '• Net is blue when positive and orange when negative.')},
                {'target': 'finance-expenses-mode', 'route': '/finance/expenses',
                 'text': T('«المصروفات»: بالشهر أو بنطاق تاريخ، وتقدر تدوس على أي فئة.',
                           '"Expenses": by month or by date range, and you can click any category.'),
                 'more': T('بتوري المصروفات حسب الفئة (رواتب، إيجارات، مرافق، صيانة، توصيل…) والتصنيف الفرعي والفرع، وتحت جدول بكل مصروف.\n'
                           '• اضغط على فئة في التوزيع عشان التفاصيل تتفلتر عليها.',
                           'It shows expenses by category (salaries, rent, utilities, maintenance, delivery…), sub-category and branch, with a table of every expense below.\n'
                           '• Click a category in the breakdown to filter the details to it.')},
                {'target': 'finance-coa-view', 'route': '/finance/coa',
                 'text': T('«دليل الحسابات»: حسابات SOFTECH كقائمة أو شجرة.',
                           '"Chart of accounts": SOFTECH accounts as a list or a tree.'),
                 'more': T('مرجع للقراءة بس: كود الحساب واسمه ونوعه وطبيعته (مدين/دائن) ومستواه.\n'
                           '• مفيد لما تحب تعرف رقم معيّن في القوائم جاي من أنهي حساب.',
                           'A read-only reference: account code, name, type, nature (debit/credit) and level.\n'
                           '• Handy when you want to know which account a figure in the statements comes from.')},
                {'target': 'finance-cheques-treasury', 'route': '/cheques',
                 'text': T('«تخطيط الشيكات»: الخطط النشطة والمتبقي والمستحق قريب والمتأخر.',
                           '"Cheque planning": active plans, outstanding, due soon and overdue.'),
                 'more': T('ننتقل لأدوات الشغل اليومي. هنا بتخطط سداد مورد أو التزام بشيكات مؤجلة.\n'
                           '• الكروت بتتحسب من الخطط: «شيكات متأخرة» بتحمرّ لو فيه شيك عدّى ميعاده ولسه ما اتصرفش.',
                           'Now to the daily tools. Here you plan paying a supplier or an obligation with post-dated cheques.\n'
                           '• The cards are computed from the plans: "Overdue cheques" turns red when a cheque is past due and not cleared.')},
                {'target': 'finance-cheques-new', 'route': '/cheques',
                 'text': T('«+ خطة جديدة»: الإجمالي وعدد الشيكات وتاريخ أول شيك والفترة.',
                           '"+ New plan": total, number of cheques, first date and interval.'),
                 'more': T('«📅 معاينة جدول الشيكات» بيوريك التواريخ والمبالغ قبل الحفظ؛ النظام بيقسم الإجمالي بالتساوي وبيرحّل أي تاريخ واقع في إجازة.\n'
                           '• «إنشاء الخطة» بيحفظها مسودة، و«✅ تفعيل الخطة» بيبدأ متابعتها.',
                           '"📅 Preview cheque schedule" shows dates and amounts before saving; the system splits the total evenly and moves any date that falls on a holiday.\n'
                           '• "Create plan" saves it as a draft, and "✅ Activate plan" starts tracking it.')},
                {'target': 'finance-payments-new', 'route': '/payments',
                 'text': T('«تتبع المدفوعات»: «+ تسجيل دفعة» لأي دفعة خارجية.',
                           '"Payment tracking": "+ Record payment" for any external payment.'),
                 'more': T('لما عميل يدفع انستاباي أو فودافون كاش أو تحويل بنكي، سجّلها هنا بالمبلغ وكود فاتورة SOFTECH ورقم العملية وصورة الإيصال.\n'
                           '• الدفعة بتبدأ «في الانتظار» لحد ما المدير أو الصيدلي يأكدها.',
                           'When a customer pays by Instapay, Vodafone Cash or bank transfer, record it here with the amount, SOFTECH invoice code, transaction number and receipt photo.\n'
                           '• The payment starts as "Pending" until the admin or pharmacist confirms it.')},
                {'target': 'finance-payments-summary', 'route': '/payments',
                 'text': T('ملخص اليوم: الإجمالي وكل طريقة دفع والمنتظر والمؤكد.',
                           'Today summary: total, each payment method, pending and confirmed.'),
                 'more': T('أرقام محسوبة في السيرفر من الدفعات المسجلة.\n'
                           '• «في الانتظار» العالي معناه دفعات محتاجة حد يراجعها ويأكدها.',
                           'Figures computed on the server from the recorded payments.\n'
                           '• A high "Pending" means payments that need someone to review and confirm them.')},
                {'target': 'finance-payment-audit-upload', 'route': '/payment-audit',
                 'text': T('«مراجعة الكشوف»: ارفع كشف البنك وقارنه بالمدفوعات المسجلة.',
                           '"Statement review": upload the bank statement and compare it with recorded payments.'),
                 'more': T('دي الخطوة اللي بتتأكد إن كل دفعة اتسجلت فعلاً دخلت البنك، وإن كل حركة في البنك ليها دفعة مسجلة.\n'
                           '• ارفع ملف CSV أو Excel، وبعدين «تشغيل المطابقة» من تبويب الكشوف.',
                           'This is the step that checks that every recorded payment really reached the bank, and that every bank line has a recorded payment.\n'
                           '• Upload a CSV or Excel file, then "Run matching" from the statements tab.')},
                {'target': 'finance-payment-audit-tabs', 'route': '/payment-audit',
                 'text': T('«⚠️ الاستثناءات» اللي محتاجة قرار، و«🏦 الكشوف البنكية».',
                           '"⚠️ Exceptions" that need a decision, and "🏦 Bank statements".'),
                 'more': T('أي حركة ما اتطابقتش أو فيها شبهة بتتحول استثناء: غير مسجّلة، مكررة، فرع غلط، فرق في المبلغ…\n'
                           '• افتح الاستثناء واكتب ملاحظة وحلّه أو تجاهله — القرار بيتسجّل باسمك.',
                           'Any line that did not match or looks suspicious becomes an exception: unrecorded, duplicate, wrong branch, amount mismatch…\n'
                           '• Open the exception, write a note, and resolve or ignore it — the decision is recorded under your name.')},
                {'target': 'finance-reconciliation-party', 'route': '/reconciliation',
                 'text': T('«سداد الموردين»: ربط سندات الصرف بالفواتير اللي بتسددها.',
                           '"Supplier payments": link payment vouchers to the invoices they pay.'),
                 'more': T('النظام بيقترح ربط كل سند صرف بفاتورة أو أكتر بدرجة ثقة، وإنت بتعتمد أو ترفض.\n'
                           '• اختار «موردون» أو «عملاء» حسب الطرف.',
                           'The system proposes linking each payment voucher to one or more invoices with a confidence level, and you approve or reject.\n'
                           '• Choose "Suppliers" or "Customers" depending on the party.')},
                {'target': 'finance-reconciliation-kpis', 'route': '/reconciliation',
                 'text': T('الفواتير والسندات والسندات بلا ربط والمقترحات والاستثناءات.',
                           'Invoices, vouchers, unlinked vouchers, proposals and exceptions.'),
                 'more': T('الكروت دي محسوبة في السيرفر حسب الفلاتر.\n'
                           '• «سندات بلا ربط» فلوس اتدفعت ولسه مش معروف سددت أنهي فاتورة — دي أهم حاجة تتراجع.',
                           'These cards are computed on the server according to the filters.\n'
                           '• "Unlinked vouchers" is money paid that is not yet known to settle which invoice — the most important thing to review.')},
                {'target': 'finance-reconciliation-tabs', 'route': '/reconciliation',
                 'text': T('المقترحات ← الاستثناءات ← غير المسددة ← الحصر.',
                           'Proposals → Exceptions → Unpaid → Parties.'),
                 'more': T('الاعتماد بيعمل ربط داخلي عندنا بس؛ الكتابة في SOFTECH خطوة منفصلة للمدير وقابلة للعكس.\n'
                           '• «غير المسددة (للمالية)» قائمة شغل المالية بالفواتير اللي لسه عليها رصيد.\n'
                           '• مطالبات التأمين ليها موديول لوحده في نفس القائمة.',
                           'Approving creates an internal link in our system only; writing to SOFTECH is a separate, reversible step for the admin.\n'
                           '• "Unpaid (for finance)" is the finance worklist of invoices that still carry a balance.\n'
                           '• Insurance claims have their own module in the same menu.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'finance.dashboard',
        'routes': ['/finance/dashboard'],
        'title': T('لوحة القيادة المالية', 'Finance dashboard'),
        'summary': T('مؤشرات الفترة المختارة: صافي الإيرادات، إجمالي الربح وهامشه، صافي الربح، صافي المشتريات، المصروفات، صافي التدفق النقدي، قيمة المخزون، المرتجعات، الاتجاه الشهري، وتفصيل الفروع.',
                     'KPIs for the chosen period: net revenue, gross profit and margin, net profit, net purchases, expenses, net cash flow, stock value, returns, the monthly trend and a branch breakdown.'),
        'audience': T('الإدارة والمالية والمشتريات والجودة.', 'Management, finance, purchasing and quality.'),
        'tips': [_SYNC, T('«بيانات غير مكتملة» تعني أن بعض المصادر لم تُزامن بعد لهذه الفترة.', '"Incomplete data" means some sources are not synced yet for this period.')],
        'related': ['finance.pnl', 'finance.cashflow'],
        'tour': [
            {'target': 'finance-dashboard-period', 'text': T('اختار السنة والشهر.',
                                              'Choose the year and month.'),
             'more': T('اللوحة بتتحمّل لوحدها مع أي تغيير. الأرقام جاية من ملخص الشهر اللي المزامنة المالية بتحسبه من بيانات SOFTECH المحاسبية.\n'
                       '• لو الشهر ما اتزامنش هتظهر رسالة «تعذّر تحميل البيانات» — اطلب من المدير يشغّل المزامنة.\n'
                       '• جنبها بيظهر اسم الفترة.',
                       'The board loads by itself on any change. The figures come from the month summary the finance sync computes from SOFTECH accounting data.\n'
                       '• If the month was not synced, a "Could not load data" message shows — ask the admin to run the sync.\n'
                       '• The period name appears next to it.')},
            {'target': 'finance-dashboard-refresh', 'text': T('«تحديث» يعيد تحميل الأرقام.',
                                              '"Refresh" reloads the figures.'),
             'more': T('مفيد بعد ما مزامنة مالية جديدة تخلص والصفحة مفتوحة.\n'
                       '• لو ظهر جنبه «⚠ بيانات غير مكتملة» يبقى فيه مصادر لسه ما اتزامنتش للشهر ده، والأرقام ممكن تتغير.\n'
                       '• التحديث بيقرا بس، مش بيعيد الحساب.',
                       'Useful after a new finance sync finishes while the page is open.\n'
                       '• If "⚠ Incomplete data" shows next to it, some sources are not synced yet for that month and the figures may change.\n'
                       '• Refreshing only reads; it does not recompute.')},
            {'target': 'finance-dashboard-kpis', 'text': T('المؤشرات المالية للفترة لكل الفروع مع بعض.',
                                              'The period financial figures for all branches together.'),
             'more': T('• صافي الإيرادات (وتحته الإجمالي)، إجمالي الربح وهامشه، صافي الربح وهامشه.\n'
                       '• صافي المشتريات، إجمالي المصروفات، صافي التدفق النقدي، قيمة المخزون («تقدير تراكمي»)، والمرتجعات.\n'
                       'كلها محسوبة في المزامنة — مفيش رقم هنا بيتكتب باليد.',
                       '• Net revenue (with gross under it), gross profit and margin, net profit and margin.\n'
                       '• Net purchases, total expenses, net cash flow, stock value ("cumulative estimate") and returns.\n'
                       'All are computed by the sync — no figure here is typed by hand.')},
            {'target': 'finance-dashboard-trend', 'text': T('الاتجاه الشهري لصافي الإيرادات في السنة المختارة.',
                                              'The monthly net revenue trend for the chosen year.'),
             'more': T('عمود لكل شهر اتزامن من نفس السنة، لكل الفروع مع بعض.\n'
                       '• بيبيّن الموسمية والشهور اللي فيها نزول عشان تسأل عن السبب.',
                       'One bar per synced month of the same year, for all branches together.\n'
                       '• It shows seasonality and the months with a drop so you can ask why.')},
            {'target': 'finance-dashboard-branches', 'text': T('التفصيل حسب الفرع.',
                                              'The breakdown by branch.'),
             'more': T('لكل فرع: صافي الإيرادات، إجمالي الربح، هامش الربح، صافي الربح، وهل بياناته «مكتمل».\n'
                       '• فرع مش مكتمل ممكن أرقامه أقل من الحقيقة لحد ما المزامنة تخلص.',
                       'Per branch: net revenue, gross profit, profit margin, net profit, and whether its data is "Complete".\n'
                       '• An incomplete branch may show lower figures until the sync finishes.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'finance.pnl',
        'routes': ['/finance/pnl'],
        'title': T('قائمة الأرباح والخسائر', 'Profit & loss'),
        'summary': T('الإيرادات (المبيعات − المرتجعات) ← تكلفة البضاعة (المشتريات − مرتجعاتها) ← إجمالي الربح ← المصروفات التشغيلية (رواتب، إيجارات، مرافق، أخرى) ← الربح التشغيلي وصافي الربح، موحّدة أو لفرع.',
                     'Revenue (sales − returns) → cost of goods (purchases − returns) → gross profit → operating expenses (salaries, rent, utilities, other) → operating and net profit, consolidated or per branch.'),
        'audience': T('الإدارة والمالية.', 'Management and finance.'),
        'tips': [_SYNC],
        'tour': [
            {'target': 'finance-pnl-period', 'text': T('اختر السنة والشهر لعرض القائمة.',
                                              'Choose the year and month to show the statement.'),
             'more': T('القائمة بتتحمّل لوحدها مع تغيير الشهر.\n'
                       '• لو ظهر «تعذّر التحميل» يبقى الشهر ده ما اتزامنش ماليّاً لسه.\n'
                       '• قارن شهرين ورا بعض عشان تشوف اتجاه الربح.',
                       'The statement loads by itself when you change the month.\n'
                       '• If "Could not load" shows, that month has not been finance-synced yet.\n'
                       '• Compare two months in a row to see the profit trend.')},
            {'target': 'finance-pnl-header', 'text': T('الفترة والفرع، أو «موحد (جميع الفروع)».',
                                              'The period and branch, or «موحد (جميع الفروع)» (Consolidated, all branches).'),
             'more': T('القائمة هنا موحّدة لكل الفروع.\n'
                       '• لو عايز أرقام فرع فرع شوف جدول الفروع في «لوحة القيادة».',
                       'The statement here is consolidated for all branches.\n'
                       '• For branch-by-branch figures see the branch table on the "Dashboard".')},
            {'target': 'finance-pnl-statement', 'text': T('الإيرادات ← تكلفة البضاعة ← إجمالي الربح ← المصروفات التشغيلية ← الربح التشغيلي وصافي الربح.',
                                              'Revenue → cost of goods → gross profit → operating expenses → operating and net profit.'),
             'more': T('• الإيرادات: إجمالي المبيعات − المرتجعات = صافي الإيرادات.\n'
                       '• التكلفة: المشتريات − مرتجعات المشتريات.\n'
                       '• المصروفات: رواتب، إيجارات، مرافق، أخرى.\n'
                       'الأرقام بين قوسين بتتخصم، وكلها محسوبة في المزامنة.',
                       '• Revenue: gross sales − returns = net revenue.\n'
                       '• Cost: purchases − purchase returns.\n'
                       '• Expenses: salaries, rent, utilities, other.\n'
                       'Figures in brackets are deducted, and all are computed by the sync.')},
            {'target': 'finance-pnl-partial', 'text': T('تنبيه «بيانات جزئية» يظهر عندما لم تُزامن بعض مصادر البيانات بعد.',
                                              'A «بيانات جزئية» (Partial data) note appears when some data sources are not yet synced.'),
             'more': T('معناه إن القائمة ممكن تتغير بعد المزامنة الجاية.\n'
                       '• متعتمدش على الأرقام دي في قرار نهائي غير لما التنبيه يختفي.',
                       'It means the statement may change after the next sync.\n'
                       '• Do not rely on these figures for a final decision until the note disappears.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'finance.cashflow',
        'routes': ['/finance/cashflow'],
        'title': T('التدفقات النقدية', 'Cash flows'),
        'summary': T('إجمالي الداخل والخارج والصافي حسب طريقة الدفع (نقدي، شيك، تحويل بنكي، بطاقة، آجل).', 'Total inflow, outflow and net by payment method (cash, cheque, bank transfer, card, credit).'),
        'audience': T('الإدارة والمالية.', 'Management and finance.'),
        'tips': [_SYNC],
        'tour': [
            {'target': 'finance-cashflow-period', 'text': T('اختر السنة والشهر.',
                                              'Choose the year and month.'),
             'more': T('الأرقام بتتحمّل لوحدها مع تغيير الشهر.\n'
                       '• لو ظهر «لا توجد بيانات حركات الخزينة» يبقى الشهر ما اتزامنش.',
                       'Figures load by themselves when you change the month.\n'
                       '• If "No treasury movement data" shows, the month was not synced.')},
            {'target': 'finance-cashflow-kpis', 'text': T('إجمالي التدفق الداخل والخارج وصافي التدفق للفترة.',
                                              'Total inflow, outflow and net cash flow for the period.'),
             'more': T('محسوبة في المزامنة من حركات الخزينة في SOFTECH.\n'
                       '• الصافي = الداخل − الخارج؛ بالأزرق لو موجب وبالبرتقالي لو سالب.\n'
                       '• صافي سالب معناه إن الخارج أكتر من الداخل في الشهر ده.',
                       'Computed by the sync from SOFTECH treasury movements.\n'
                       '• Net = inflow − outflow; blue when positive and orange when negative.\n'
                       '• A negative net means more went out than came in that month.')},
            {'target': 'finance-cashflow-inflow', 'text': T('التدفق الداخل موزعاً بطريقة الدفع — يظهر بعد اكتشاف جداول الخزينة.',
                                              'Inflow by payment method — shown once treasury tables are discovered.'),
             'more': T('شريط لكل طريقة دفع بالمبلغ.\n'
                       '• لو ظهرت رسالة إن جداول الخزينة ما اتكتشفتش، المدير لازم يشغّل «اكتشاف المخطط» ويفعّل جداول الدفع الأول.',
                       'One bar per payment method with its amount.\n'
                       '• If a message says the treasury tables were not discovered, the admin must run "Schema discovery" and enable the payment tables first.')},
            {'target': 'finance-cashflow-outflow', 'text': T('التدفق الخارج موزعاً بطريقة الدفع.',
                                              'Outflow by payment method.'),
             'more': T('بيوضح الفلوس خرجت إزاي: نقدي، شيكات، تحويلات…\n'
                       '• قارنه بتخطيط الشيكات عشان تتوقع ضغط السيولة في الشهور الجاية.',
                       'Shows how money went out: cash, cheques, transfers…\n'
                       '• Compare it with cheque planning to anticipate cash pressure in the coming months.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'finance.expenses',
        'routes': ['/finance/expenses'],
        'title': T('تحليل المصروفات', 'Expense analysis'),
        'summary': T('المصروفات حسب الفئة (رواتب، إيجارات، مرافق، صيانة، توصيل، تسويق، فاقد، منتهي الصلاحية…) والتصنيف الفرعي والفرع ومركز التكلفة، بفترة شهر/سنة أو نطاق تاريخ. اضغط فئة لتصفية التفاصيل.',
                     'Expenses by category (salaries, rent, utilities, maintenance, delivery, marketing, shrinkage, expired…), sub-category, branch and cost center, by month/year or a date range. Click a category to filter the details.'),
        'audience': T('الإدارة والمالية.', 'Management and finance.'),
        'tips': [_SYNC],
        'tour': [
            {'target': 'finance-expenses-mode', 'text': T('اختار «شهر / سنة» أو «نطاق تاريخ».',
                                              'Choose "Month / year" or "Date range".'),
             'more': T('• «شهر / سنة»: شهر كامل.\n'
                       '• «نطاق تاريخ»: من يوم ليوم، مفيد لربع سنة أو موسم.\n'
                       'التبديل بيرجعك لأول صفحة في الجدول.',
                       '• "Month / year": a whole month.\n'
                       '• "Date range": from one day to another, useful for a quarter or a season.\n'
                       'Switching takes you back to the first page of the table.')},
            {'target': 'finance-expenses-filters', 'text': T('فلتر الفترة والفئة والتصنيف الفرعي والفرع.',
                                              'Filter by period, category, sub-category and branch.'),
             'more': T('الفلاتر المختارة بتظهر كشرائح تقدر تشيل أي واحدة منها، و«مسح الكل» بيلغيهم مرة واحدة.\n'
                       '• كل الأرقام والتوزيع والجدول بيتبعوا الفلاتر.',
                       'The chosen filters show as chips you can remove one by one, and "Clear all" removes them at once.\n'
                       '• All the figures, the breakdown and the table follow the filters.')},
            {'target': 'finance-expenses-kpis', 'text': T('إجمالي المصروفات وعدد الفئات والسجلات.',
                                              'Total expenses and the number of categories and records.'),
             'more': T('الإجمالي محسوب في السيرفر من سجلات المصروفات المتزامنة من SOFTECH، وتحته الفترة.\n'
                       '• «عدد السجلات» هو عدد قيود المصروف في الجدول تحت.',
                       'The total is computed on the server from the expense records synced from SOFTECH, with the period under it.\n'
                       '• "Records" is the number of expense entries in the table below.')},
            {'target': 'finance-expenses-breakdown', 'text': T('التوزيع حسب الفئة الرئيسية — اضغط فئة لتصفية التفاصيل.',
                                              'The breakdown by main category — click a category to filter the details.'),
             'more': T('الضغط على فئة بيفلتر الصفحة عليها ويظهر جنبها توزيع التصنيفات الفرعية، والضغط تاني بيلغي الفلتر.\n'
                       '• كمان تقدر تضغط تصنيف فرعي عشان تضيّق أكتر.',
                       'Clicking a category filters the page to it and shows the sub-category breakdown next to it; clicking again removes the filter.\n'
                       '• You can also click a sub-category to narrow further.')},
            {'target': 'finance-expenses-table', 'text': T('تفاصيل كل مصروف.',
                                              'The detail of each expense.'),
             'more': T('الأعمدة: التاريخ، الفئة، التصنيف الفرعي، البيان، مركز التكلفة، الفرع، المبلغ.\n'
                       '• استخدمه لما رقم في التوزيع يبان غريب وعايز تعرف القيود اللي وراه.',
                       'Columns: date, category, sub-category, description, cost center, branch, amount.\n'
                       '• Use it when a figure in the breakdown looks odd and you want the entries behind it.')},
            {'target': 'finance-expenses-pagination', 'text': T('التنقل بين الصفحات.',
                                              'Move between pages.'),
             'more': T('كل صفحة فيها 40 سجل؛ «→ التالي» و«← السابق» للتنقل ورقم الصفحة في النص.\n'
                       '• لتقليل الصفحات ضيّق الفلاتر.',
                       'Each page holds 40 records; "Next →" and "← Previous" to move, with the page number in the middle.\n'
                       '• To get fewer pages, narrow the filters.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'finance.coa',
        'routes': ['/finance/coa'],
        'title': T('دليل الحسابات', 'Chart of accounts'),
        'summary': T('الحسابات المحاسبية من SOFTECH كقائمة أو شجرة: الكود، الاسم، النوع (أصول، التزامات، حقوق ملكية، إيرادات، مصروفات، تكلفة مبيعات)، الطبيعة (مدين/دائن) والمستوى.',
                     'The SOFTECH accounts as a list or tree: code, name, type (assets, liabilities, equity, revenue, expenses, cost of sales), nature (debit/credit) and level.'),
        'audience': T('المالية.', 'Finance.'),
        'tour': [
            {'target': 'finance-coa-view', 'text': T('اعرض الحسابات «قائمة» أو «شجرة».',
                                              'Show the accounts as «قائمة» (List) or «شجرة» (Tree).'),
             'more': T('• «قائمة»: جدول مسطح فيه بحث وفلتر.\n'
                       '• «شجرة»: الحسابات تحت بعض حسب المستوى.\n'
                       'الدليل للقراءة بس — التعديل بيتم في SOFTECH نفسه.',
                       '• "List": a flat table with search and filter.\n'
                       '• "Tree": accounts nested by level.\n'
                       'The chart is read-only — changes are made in SOFTECH itself.')},
            {'target': 'finance-coa-search', 'text': T('بحث بالاسم أو الكود — في عرض «قائمة» فقط.',
                                              'Search by name or code — in «قائمة» (List) view only.'),
             'more': T('اكتب جزء من اسم الحساب أو كوده والقائمة بتتفلتر.\n'
                       '• مفيد لما تشوف كود حساب في قيد وعايز تعرف اسمه.',
                       'Type part of the account name or code and the list filters.\n'
                       '• Handy when you see an account code in an entry and want its name.')},
            {'target': 'finance-coa-type', 'text': T('فلتر نوع الحساب: أصول، التزامات، إيرادات، مصروفات…',
                                              'Filter by account type: assets, liabilities, revenue, expenses…'),
             'more': T('بيقصر القائمة على نوع واحد، مثلاً «مصروفات» عشان تشوف كل حسابات المصروف.\n'
                       '• اختار «الكل» عشان ترجع القائمة كاملة.',
                       'It narrows the list to one type, for example "Expenses" to see every expense account.\n'
                       '• Choose "All" to get the full list back.')},
            {'target': 'finance-coa-list', 'text': T('الكود، الاسم، النوع، الطبيعة (مدين/دائن)، المستوى، وهل الحساب ورقة.',
                                              'Code, name, type, nature (debit/credit), level, and whether the account is a leaf.'),
             'more': T('«ورقة» يعني حساب نهائي بتتسجل عليه القيود، وغير كده حساب تجميعي.\n'
                       '• «الطبيعة» بتقولك الرصيد الطبيعي للحساب مدين ولا دائن.',
                       '"Leaf" means a final account that entries are posted to; otherwise it is a grouping account.\n'
                       '• "Nature" tells you whether the account normal balance is debit or credit.')},
            {'target': 'finance-coa-tree', 'text': T('الهيكل الشجري للحسابات — يظهر في عرض «شجرة».',
                                              'The account hierarchy — shown in «شجرة» (Tree) view.'),
             'more': T('أول مستويين مفتوحين؛ اضغط أي حساب ليه فروع عشان تفتحه أو تقفله.\n'
                       '• بيوضح كل حساب تابع لأنهي مجموعة.',
                       'The first two levels are open; click any account with children to open or close it.\n'
                       '• It shows which group each account belongs to.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'finance.schema',
        'routes': ['/finance/schema'],
        'title': T('اكتشاف المخطط المالي', 'Finance schema discovery'),
        'summary': T('للمدير: فحص جداول SOFTECH ذات الصلة المالية، تأكيد الغرض من كل جدول، وتفعيله للمزامنة. هذه خطوة إعداد قبل أن تعمل باقي الشاشات المالية.',
                     'For admins: scan SOFTECH tables with a financial purpose, confirm each table\'s purpose and enable it for syncing. A setup step before the other finance screens work.'),
        'audience': T('المدير فقط.', 'Admins only.'),
        'tour': [
            {'target': 'finance-schema-filters', 'text': T('بحث باسم الجدول، وفلتر الفئة وحالة التأكيد.',
                                              'Search by table name, and filter by category and confirmation status.'),
             'more': T('استخدم «غير مؤكد» عشان تلاقي الجداول اللي لسه محتاجة مراجعة.\n'
                       '• الفئة هي التصنيف اللي الاكتشاف استنتجه (خزينة، مصروفات…).',
                       'Use "Unconfirmed" to find the tables that still need review.\n'
                       '• The category is the classification the discovery inferred (treasury, expenses…).')},
            {'target': 'finance-schema-discover', 'text': T('«🔍 تشغيل الاكتشاف» يفحص جداول SOFTECH ذات الصلة المالية في الخلفية.',
                                              '«🔍 تشغيل الاكتشاف» (Run discovery) scans SOFTECH tables with a financial purpose in the background.'),
             'more': T('الفحص بيقرا هيكل جداول SOFTECH بس ومبيكتبش فيها، وبيشتغل في الخلفية فممكن ياخد وقت.\n'
                       '• بعد ما يخلص الجداول بتظهر في القائمة.\n'
                       '• الشاشة دي للمدير بس.',
                       'The scan only reads the structure of SOFTECH tables and does not write to them; it runs in the background so it may take a while.\n'
                       '• When it finishes, the tables show in the list.\n'
                       '• This screen is for the admin only.')},
            {'target': 'finance-schema-stats', 'text': T('إجمالي الجداول المكتشفة، والمؤكد منها، والمفعّل للمزامنة.',
                                              'Total discovered tables, how many are confirmed, and how many are enabled for sync.'),
             'more': T('هدفك إن كل جدول مالي مهم يبقى مؤكد ومفعّل.\n'
                       '• لو المفعّل صفر، شاشات المالية التانية هتفضل فاضية.',
                       'Your goal is that every important financial table is confirmed and enabled.\n'
                       '• If enabled is zero, the other finance screens stay empty.')},
            {'target': 'finance-schema-row', 'text': T('صف لكل جدول بفئته وعدد أعمدته وصفوفه؛ اضغطه لرؤية الغرض المستنتج والأعمدة.',
                                              'A row per table with category, columns and rows; click it to see the inferred purpose and columns.'),
             'more': T('اقرا الغرض المستنتج والأعمدة قبل ما تأكد — الاستنتاج آلي وممكن يغلط.\n'
                       '• الصف بيتلوّن أخضر بعد التأكيد.',
                       'Read the inferred purpose and columns before confirming — the inference is automatic and can be wrong.\n'
                       '• The row turns green after confirmation.')},
            {'target': 'finance-schema-confirm', 'text': T('«تأكيد» / «✓ مؤكد» يسجّل تأكيد غرض الجدول أو يلغيه.',
                                              '«تأكيد» / «✓ مؤكد» (Confirm / Confirmed) records or clears confirmation of the table\'s purpose.'),
             'more': T('الضغط بيبدّل الحالة: «تأكيد» يعني إنك راجعت وموافق على الغرض، والضغط على «✓ مؤكد» بيلغيه.\n'
                       '• التأكيد بيتسجل في نظامنا بس، مش في SOFTECH.',
                       'Pressing toggles the state: "Confirm" means you reviewed and agree with the purpose, and pressing "✓ Confirmed" clears it.\n'
                       '• Confirmation is stored in our system only, not in SOFTECH.')},
            {'target': 'finance-schema-sync', 'text': T('«تفعيل» / «⟲ مزامنة» يشغّل أو يوقف مزامنة هذا الجدول.',
                                              '«تفعيل» / «⟲ مزامنة» (Enable / Syncing) turns syncing of this table on or off.'),
             'more': T('المفعّل بس هو اللي المزامنة المالية بتقرا بياناته وتحسب منها لوحة القيادة والقوائم.\n'
                       '• المزامنة قراءة من SOFTECH بس.\n'
                       '• فعّل الجدول بعد ما تأكد غرضه.',
                       'Only enabled tables are read by the finance sync to compute the dashboard and statements.\n'
                       '• Syncing only reads from SOFTECH.\n'
                       '• Enable a table after confirming its purpose.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'finance.cheques',
        'routes': ['/cheques'],
        'title': T('تخطيط الشيكات والخزينة', 'Cheque planning & treasury'),
        'summary': T('جداول سداد بشيكات مؤجلة مع مراعاة أيام العمل البنكية في مصر: الخطط النشطة، إجمالي المتبقي، شيكات الـ 30 يوماً القادمة، والمتأخرة.',
                     'Post-dated cheque payment schedules aware of Egyptian banking days: active plans, total outstanding, cheques due in the next 30 days, and overdue ones.'),
        'audience': T('المالية والمشتريات والمدير.', 'Finance, purchasing and admins.'),
        'steps': [
            T('«خطة جديدة»: العنوان، المستفيد، المستند المرجعي، البنك والحساب والفرع، الإجمالي وعدد الشيكات وتاريخ الأول والفترة بينها ← «معاينة جدول الشيكات».', '"New plan": title, beneficiary, reference document, bank, account and branch, total, number of cheques, first date and interval → "Preview cheque schedule".'),
            T('التواريخ التي تقع في إجازة أو عطلة تُرحَّل تلقائياً ويظهر التاريخ الأصلي. ثم «إنشاء الخطة» و«تفعيل الخطة».', 'Dates falling on a holiday or weekend shift automatically and show the original date. Then "Create plan" and "Activate plan".'),
            T('حدّث حالة كل شيك: لم يُصدر ← صادر ← مُقدَّم للبنك ← تمّ الصرف (أو ارتدّ/رُفض).', 'Update each cheque: not issued → issued → presented → cleared (or bounced/rejected).'),
        ],
        'tour': [
            {'target': 'finance-cheques-treasury', 'text': T('الخطط النشطة، إجمالي المتبقي، شيكات الـ 30 يوماً القادمة، والمتأخرة.',
                                              'Active plans, total outstanding, cheques due in the next 30 days, and overdue ones.'),
             'more': T('الكروت محسوبة في السيرفر من الخطط والشيكات.\n'
                       '• «شيكات خلال 30 يوم» عددها ومبلغها عشان تجهّز الرصيد في البنك.\n'
                       '• «شيكات متأخرة» بتحمرّ لو فيه شيك عدّى ميعاده ولسه ما اتصرفش — تابعه فوراً.',
                       'The cards are computed on the server from the plans and cheques.\n'
                       '• "Cheques within 30 days" gives their count and amount so you can prepare the bank balance.\n'
                       '• "Overdue cheques" turns red when a cheque is past due and not cleared — follow it up straight away.')},
            {'target': 'finance-cheques-new', 'text': T('«+ خطة جديدة» يفتح نموذج جدول سداد بالشيكات.',
                                              '«+ خطة جديدة» (New plan) opens the cheque payment schedule form.'),
             'more': T('بتكتب العنوان والمستفيد والمستند المرجعي والبنك والإجمالي وعدد الشيكات وتاريخ أول شيك والفترة بينهم.\n'
                       '• «📅 معاينة جدول الشيكات»: النظام بيقسم الإجمالي بالتساوي (آخر شيك ياخد فرق التقريب) وبيرحّل التواريخ اللي في إجازة.\n'
                       '• «إنشاء الخطة» بيحفظها «مسودة».',
                       'You enter the title, beneficiary, reference document, bank, total, number of cheques, first cheque date and the interval.\n'
                       '• "📅 Preview cheque schedule": the system splits the total evenly (the last cheque takes the rounding difference) and moves dates that fall on holidays.\n'
                       '• "Create plan" saves it as a "Draft".')},
            {'target': 'finance-cheques-search', 'text': T('بحث في الخطط بالاسم أو المستفيد.',
                                              'Search plans by name or beneficiary.'),
             'more': T('اكتب اسم المورد أو جزء من عنوان الخطة والقائمة بتتفلتر.\n'
                       '• مفيد لما مورد يسأل عن شيكاته الجاية.',
                       'Type the supplier name or part of the plan title and the list filters.\n'
                       '• Handy when a supplier asks about their upcoming cheques.')},
            {'target': 'finance-cheques-status', 'text': T('فلتر الحالة: الكل، مسودة، نشطة، مكتملة.',
                                              'Status filter: all, draft, active, completed.'),
             'more': T('• «مسودة»: اتعملت ولسه ما اتفعلتش.\n'
                       '• «نشطة»: شيكاتها شغالة ومتابعة.\n'
                       '• «مكتملة»: كل شيكاتها خلصت.',
                       '• "Draft": created but not activated yet.\n'
                       '• "Active": its cheques are running and tracked.\n'
                       '• "Completed": all its cheques are done.')},
            {'target': 'finance-cheques-detail', 'text': T('تفاصيل الخطة المختارة أو نموذج الخطة الجديدة يظهر هنا.',
                                              'The selected plan\'s details, or the new plan form, appear here.'),
             'more': T('اضغط أي خطة في القائمة عشان تفتح هنا.\n'
                       '• الخطة المسودة فيها «✅ تفعيل الخطة».\n'
                       '• المسودة والنشطة فيها «إلغاء» بعد رسالة تأكيد.',
                       'Click any plan in the list to open it here.\n'
                       '• A draft plan has "✅ Activate plan".\n'
                       '• Draft and active plans have "Cancel" after a confirmation message.')},
            {'target': 'finance-cheques-schedule', 'text': T('بعد اختيار خطة: جدول الشيكات بالاستحقاق والمبلغ والحالة، و«تعديل» لكل شيك في الخطط النشطة.',
                                              'After picking a plan: the cheque schedule with due date, amount and status, and «تعديل» (Edit) for each cheque of an active plan.'),
             'more': T('⚠️ جنب التاريخ يعني إنه اترحّل عن التاريخ الأصلي بسبب إجازة، والتاريخ الأحمر يعني متأخر.\n'
                       '• «تعديل» بيفتح رقم الشيك والحالة والملاحظات: لم يُصدر ← صادر ← مُقدَّم للبنك ← تمّ الصرف أو ارتدّ.\n'
                       '• المبلغ نفسه محسوب من الخطة ومبيتعدلش هنا.',
                       '⚠️ next to the date means it moved from the original date because of a holiday, and a red date means overdue.\n'
                       '• "Edit" opens the cheque number, status and notes: not issued → issued → presented → cleared or bounced.\n'
                       '• The amount itself is computed from the plan and is not edited here.')},
        ],
        'tips': [
            T('كل إجراء بيتحقق من صلاحيتك على السيرفر (مصفوفة الصلاحيات، موديول الشيكات): التفعيل والإلغاء يحتاجوا «اعتماد»، وتسجيل شيك «تمّ الصرف» أو «ارتدّ» يحتاج «إنهاء».',
              'Every action is checked on the server (Permissions Matrix, cheques module): activating and cancelling need "approve", and marking a cheque "cleared" or "bounced" needs "finalize".'),
        ],
        'updated': '2026-10-26',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
    },
    {
        'key': 'finance.payments',
        'routes': ['/payments'],
        'title': T('تتبع المدفوعات', 'Payment tracking'),
        'summary': T('تسجيل ومطابقة المدفوعات الخارجية (كاش، انستاباي، فودافون كاش، تحويل بنكي): المبلغ، الفاتورة، العميل، رقم العملية، الفرع، وصورة الإيصال، ثم تأكيدها أو الاعتراض عليها.',
                     'Record and reconcile external payments (cash, Instapay, Vodafone Cash, bank transfer): amount, invoice, customer, transaction number, branch and a receipt photo, then confirm or dispute them.'),
        'audience': T('المالية والصيادلة.', 'Finance and pharmacists.'),
        'steps': [
            T('«تسجيل دفعة»: طريقة الدفع والمبلغ وإجمالي الفاتورة (أو «دفعة جزئية» مع المتبقي)، كود فاتورة SOFTECH، رقم المرجع، الفرع والتاريخ، وصورة الإيصال.', '"Record payment": method, amount and invoice total (or "partial" with the remaining), SOFTECH invoice code, reference number, branch and date, and the receipt photo.'),
            T('المالية: «تأكيد» بعد التحقق، أو «اعتراض» بسبب.', 'Finance: "Confirm" after checking, or "Dispute" with a reason.'),
        ],
        'related': ['finance.payment_audit'],
        'tour': [
            {'target': 'finance-payments-new', 'text': T('«+ تسجيل دفعة» يفتح نموذج تسجيل دفعة خارجية.',
                                              '«+ تسجيل دفعة» (Record payment) opens the external payment form.'),
             'more': T('استخدمه لما عميل يدفع انستاباي أو فودافون كاش أو تحويل بنكي أو كاش خارج الكاشير.\n'
                       '• النموذج فيه طريقة الدفع والمبلغ وإجمالي الفاتورة وكود فاتورة SOFTECH ورقم المرجع والفرع وصورة الإيصال؛ لو «دفعة جزئية» بتسجّل المتبقي زي ما هو.\n'
                       '• الدفعة بتتسجل «في الانتظار» ومبتكتبش حاجة في SOFTECH.',
                       'Use it when a customer pays by Instapay, Vodafone Cash, bank transfer or cash outside the till.\n'
                       '• The form has the method, amount, invoice total, SOFTECH invoice code, reference number, branch and receipt photo; for a "Partial payment" you record the remaining as stated.\n'
                       '• The payment is saved as "Pending" and writes nothing to SOFTECH.')},
            {'target': 'finance-payments-summary', 'text': T('إجمالي اليوم وحسب طريقة الدفع، وما في الانتظار، والمؤكد اليوم.',
                                              'Today\'s total and by payment method, pending, and confirmed today.'),
             'more': T('كلها محسوبة في السيرفر من الدفعات المسجلة.\n'
                       '• «في الانتظار» = دفعات لسه محتاجة تأكيد.\n'
                       '• «مؤكد اليوم» = اللي اتأكد انهارده.',
                       'All computed on the server from the recorded payments.\n'
                       '• "Pending" = payments still awaiting confirmation.\n'
                       '• "Confirmed today" = those confirmed today.')},
            {'target': 'finance-payments-filters', 'text': T('فلتر التاريخ وطريقة الدفع والحالة والفرع، وبحث بالاسم أو الهاتف أو المرجع.',
                                              'Filter by date, method, status and branch, and search by name, phone or reference.'),
             'more': T('الفترة الافتراضية آخر 7 أيام.\n'
                       '• الحالات: في الانتظار، مؤكد، تمت المطابقة، متنازع، ملغي.\n'
                       '• البحث برقم المرجع أسرع طريقة تلاقي بيها تحويل معيّن.',
                       'The default period is the last 7 days.\n'
                       '• Statuses: pending, confirmed, reconciled, disputed, cancelled.\n'
                       '• Searching by reference number is the fastest way to find a specific transfer.')},
            {'target': 'finance-payments-time', 'text': T('«🕐 وقت» يفتح فلاتر إضافية: فترات سريعة، يوم بعينه، الساعة، وأيام الأسبوع.',
                                              '«🕐 وقت» (Time) opens extra filters: quick ranges, a specific day, hour and weekdays.'),
             'more': T('مفيد لما تراجع وردية معيّنة أو تدوّر على دفعة اتعملت في ساعة معروفة.\n'
                       '• اضغطه تاني عشان تقفل الفلاتر الإضافية.',
                       'Useful when reviewing a specific shift or looking for a payment made at a known hour.\n'
                       '• Press it again to close the extra filters.')},
            {'target': 'finance-payments-list', 'text': T('المدفوعات المطابقة بالمبلغ والطريقة والحالة والفاتورة والمرجع؛ «تحديث» لإعادة التحميل.',
                                              'Matching payments with amount, method, status, invoice and reference; «تحديث» (Refresh) reloads.'),
             'more': T('كل كارت فيه العميل وتليفونه وكود الفاتورة والمرجع والفرع والتاريخ، والمتبقي لو الدفعة جزئية.\n'
                       '• «📷 إيصال» بيفتح صورة الإيصال لو موجودة.',
                       'Each card shows the customer and phone, invoice code, reference, branch and date, and the remaining if the payment is partial.\n'
                       '• "📷 Receipt" opens the receipt photo when there is one.')},
            {'target': 'finance-payments-actions', 'text': T('للدفعات المنتظرة: «تأكيد ✓» أو «اعتراض» — التأكيد للمدير والصيدلي فقط.',
                                              'For pending payments: «تأكيد ✓» (Confirm) or «اعتراض» (Dispute) — confirming is for admin and pharmacist only.'),
             'more': T('• «تأكيد ✓» بعد ما تتأكد إن الفلوس وصلت فعلاً؛ بيتسجل اسمك والوقت.\n'
                       '• «اعتراض» بيطلب سبب وبيحوّل الدفعة «متنازع».\n'
                       'السيرفر بيرفض التأكيد من أي حد غير المدير والصيدلي.',
                       '• "Confirm ✓" once you are sure the money really arrived; your name and the time are recorded.\n'
                       '• "Dispute" asks for a reason and turns the payment "Disputed".\n'
                       'The server refuses confirmation from anyone but the admin and pharmacist.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
    {
        'key': 'finance.payment_audit',
        'routes': ['/payment-audit'],
        'title': T('مراجعة الكشوف البنكية', 'Bank statement review'),
        'summary': T('رفع كشف الحساب البنكي (CSV/Excel) ومطابقته تلقائياً بالمدفوعات المسجّلة، ومعالجة الاستثناءات.', 'Upload the bank statement (CSV/Excel) and match it automatically to recorded payments, then handle exceptions.'),
        'audience': T('المالية.', 'Finance.'),
        'tabs': [
            {'key': 'exceptions', 'title': T('⚠️ الاستثناءات', '⚠️ Exceptions'), 'body': T('حركات تحتاج قراراً: غير مسجّلة، مكررة، تسوية متأخرة، فرع خاطئ، تباين في المبلغ، مؤشر إساءة. «معالجة» ← ملاحظة التسوية ← «حل الاستثناء» أو «تجاهل».', 'Lines that need a decision: unrecorded, duplicate, late settlement, wrong branch, amount mismatch, abuse signal. "Handle" → settlement note → "Resolve" or "Ignore".')},
            {'key': 'statements', 'title': T('🏦 الكشوف البنكية', '🏦 Bank statements'), 'body': T('الكشوف المرفوعة بعدد السطور والمطابق ونسبة المطابقة؛ «رفع كشف حساب» و«تشغيل المطابقة».', 'Uploaded statements with line count, matched and match rate; "Upload statement" and "Run matching".')},
        ],
        'related': ['finance.payments'],
        'tour': [
            {'target': 'finance-payment-audit-upload', 'text': T('«+ رفع كشف حساب» لرفع كشف بنكي (CSV/Excel) مع مرجع اختياري.',
                                              '«+ رفع كشف حساب» (Upload statement) uploads a bank statement (CSV/Excel) with an optional reference.'),
             'more': T('بتختار الملف من البنك وتكتب المرجع البنكي لو حابب، وتضغط رفع.\n'
                       '• الكشف بيظهر في «🏦 الكشوف البنكية» بحالة معلّقة.\n'
                       '• المطابقة مش بتشتغل لوحدها — شغّلها من زر «تشغيل المطابقة».',
                       'You choose the file from the bank, add the bank reference if you like, and upload.\n'
                       '• The statement appears in "🏦 Bank statements" as pending.\n'
                       '• Matching does not start by itself — run it with "Run matching".')},
            {'target': 'finance-payment-audit-tabs', 'text': T('«⚠️ الاستثناءات» المفتوحة بعددها، و«🏦 الكشوف البنكية».',
                                              '«⚠️ الاستثناءات» (Exceptions) with their open count, and «🏦 الكشوف البنكية» (Bank statements).'),
             'more': T('• «⚠️ الاستثناءات»: الحاجات اللي محتاجة قرار منك.\n'
                       '• «🏦 الكشوف البنكية»: كل كشف اترفع ونسبة مطابقته.\n'
                       'ابدأ يومك بالاستثناءات.',
                       '• "⚠️ Exceptions": things that need your decision.\n'
                       '• "🏦 Bank statements": every uploaded statement and its match rate.\n'
                       'Start your day with the exceptions.')},
            {'target': 'finance-payment-audit-exceptions', 'text': T('الاستثناءات المفتوحة: النوع والمبلغ والمرجع والحالة والتاريخ — تظهر عند وجودها.',
                                              'Open exceptions: type, amount, reference, status and date — shown when there are any.'),
             'more': T('الأنواع: غير مسجّلة (في البنك ومش متسجلة عندنا)، مكررة، تسوية متأخرة، فرع خاطئ، تباين في المبلغ، ومؤشر إساءة.\n'
                       '• مؤشر الإساءة بيطلع لما دفعة تبعد كتير عن المعتاد للكاشير أو طريقة الدفع — راجعه بعناية.',
                       'Types: unrecorded (in the bank but not recorded here), duplicate, late settlement, wrong branch, amount mismatch and abuse signal.\n'
                       '• An abuse signal appears when a payment is far from the usual for that cashier or payment method — review it carefully.')},
            {'target': 'finance-payment-audit-handle', 'text': T('«معالجة» تفتح نافذة لكتابة ملاحظة ثم «حل الاستثناء» أو «تجاهل».',
                                              '«معالجة» (Handle) opens a window to add a note, then «حل الاستثناء» (Resolve) or «تجاهل» (Ignore).'),
             'more': T('اكتب في الملاحظة عملت إيه (اتسجلت الدفعة، اتصلحت، اتكلمنا مع الفرع…).\n'
                       '• «حل الاستثناء» و«تجاهل» الاتنين بيقفلوا الاستثناء وبيسجلوا اسمك والوقت.',
                       'Write in the note what you did (payment recorded, fixed, talked to the branch…).\n'
                       '• "Resolve" and "Ignore" both close the exception and record your name and the time.')},
            {'target': 'finance-payment-audit-statements', 'text': T('في تبويب الكشوف: المرجع والسطور والمطابق ونسبة المطابقة والحالة.',
                                              'On the statements tab: reference, lines, matched, match rate and status.'),
             'more': T('نسبة مطابقة واطية معناها إن فيه حركات كتير في البنك مش لاقية دفعة مسجلة — هتلاقيها استثناءات.\n'
                       '• الحالات: في الانتظار، قيد المعالجة، مكتمل، فشل.',
                       'A low match rate means many bank lines have no recorded payment — you will find them as exceptions.\n'
                       '• Statuses: pending, processing, completed, failed.')},
            {'target': 'finance-payment-audit-match', 'text': T('«تشغيل المطابقة» يظهر للكشوف المعلقة ليطابق سطورها بالمدفوعات المسجلة.',
                                              '«تشغيل المطابقة» (Run matching) appears for pending statements to match their lines to recorded payments.'),
             'more': T('القواعد ثابتة: نفس المرجع ونفس المبلغ = مطابقة أكيدة، أو فرق مبلغ لحد 1% وفرق تاريخ لحد يومين = مطابقة تقريبية، وغير كده استثناء «غير مسجّلة».\n'
                       '• السيرفر بيسمح بيها للمدير والمشرف والمشتريات.',
                       'The rules are fixed: same reference and same amount = certain match, or an amount difference up to 1% and a date difference up to 2 days = approximate match; anything else becomes an "Unrecorded" exception.\n'
                       '• The server allows it for admin, supervisor and purchasing.')},
        ],
        'tips': [
            T('كل إجراء بيتحقق من صلاحيتك على السيرفر (مصفوفة الصلاحيات، موديول المالية): العرض يحتاج «عرض»، «حل الاستثناء» و«تجاهل» يحتاجوا «اعتماد»، الإسناد يحتاج «إسناد» أو «اعتماد»، ورفع كشف يحتاج «إضافة».',
              'Every action is checked on the server (Permissions Matrix, finance module): viewing needs "view", "Resolve" and "Ignore" need "approve", assigning needs "assign" or "approve", and uploading a statement needs "create".'),
        ],
        'updated': '2026-10-26',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
    },
    {
        'key': 'finance.reconciliation',
        'routes': ['/reconciliation'],
        'title': T('سداد فواتير الموردين (المطابقة)', 'Supplier invoice payments (reconciliation)'),
        'summary': T('ربط سندات الصرف للموردين بالفواتير التي تسددها: النظام يقترح الربط بدرجة ثقة، والمسؤول يعتمد أو يرفض. الاعتماد يُكتب في المرآة لدينا فقط، وليس في SOFTECH. «المتبقي» حقل محسوب (قيمة الفاتورة − المسدد في SOFTECH − المعتمد بانتظار الكتابة).',
                     'Link supplier payment vouchers to the invoices they pay: the system proposes links with a confidence level, and the responsible person approves or rejects. Approval is written only to our mirror, not to SOFTECH. "Remaining" is computed (invoice value − paid in SOFTECH − approved awaiting write).'),
        'audience': T('المالية والمشتريات.', 'Finance and purchasing.'),
        'tabs': [
            {'key': 'candidates', 'title': T('المقترحات', 'Proposals'), 'body': T('مقترحات الربط (ثقة عالية/متوسطة/منخفضة/تعارض) مع الفاتورة وتاريخها وقيمتها والسند ومبلغه والمتبقي. افتح الصف لترى أصناف الفاتورة والمرتجعات المرتبطة، ثم اعتمد أو ارفض.', 'Link proposals (high/medium/low confidence/conflict) with the invoice, date, value, voucher, amount and remaining. Open a row to see the invoice items and linked returns, then approve or reject.')},
            {'key': 'exceptions', 'title': T('الاستثناءات', 'Exceptions'), 'body': T('حالات تحتاج مراجعة: سند مكرر محتمل، سند يسمي فاتورة أخرى، مقبوضات تحتاج تحديد (استرداد أم خصم)، وغيرها.', 'Cases needing review: possible duplicate voucher, voucher naming another invoice, receipts needing a decision (refund or deduction), and others.')},
            {'key': 'unpaid', 'title': T('غير المسددة (للمالية)', 'Unpaid (for finance)'), 'body': T('الفواتير التي ما زال عليها رصيد بعد الربط — قائمة عمل للمالية.', 'Invoices still with a balance after linking — a worklist for finance.')},
            {'key': 'parties', 'title': T('الحصر', 'Parties & ledger'), 'body': T('الموردون وحساباتهم: الفواتير، السندات، السندات بلا ربط، وكشف الحساب.', 'Suppliers and their accounts: invoices, vouchers, unlinked vouchers and the ledger.')},
        ],
        'related': ['invoices.main', 'replacement.cases'],
        'tour': [
            {'target': 'finance-reconciliation-party', 'text': T('اختر الطرف: «موردون» أو «عملاء».',
                                              'Choose the party: «موردون» (Suppliers) or «عملاء» (Customers).'),
             'more': T('كل الصفحة (الفلاتر والكروت والتبويبات) بتتبع الطرف المختار.\n'
                       '• جنبها ملاحظة مهمة: الاعتماد بيعمل ربط داخلي عندنا بس، والكتابة في SOFTECH خطوة منفصلة قابلة للعكس.',
                       'The whole page (filters, cards and tabs) follows the chosen party.\n'
                       '• Next to it is an important note: approving creates an internal link in our system only, and writing to SOFTECH is a separate, reversible step.')},
            {'target': 'finance-reconciliation-filters', 'text': T('فلتر المورد وتاريخ الفاتورة وتاريخ السند والقيمة — ينطبق على كل التبويبات والإجماليات.',
                                              'Filter by supplier, invoice date, voucher date and amount — applies to all tabs and totals.'),
             'more': T('تقدر تختار أكتر من مورد، وتحدد مدى تاريخ الفاتورة ومدى تاريخ السند (السداد) والقيمة من/إلى.\n'
                       '• زر المسح بيرجّع كل الفلاتر.\n'
                       '• اشتغل مورد مورد عشان المراجعة تبقى أوضح.',
                       'You can pick several suppliers, and set an invoice date range, a voucher (payment) date range and an amount from/to.\n'
                       '• The clear button resets all filters.\n'
                       '• Work supplier by supplier for a clearer review.')},
            {'target': 'finance-reconciliation-kpis', 'text': T('الفواتير، السندات، السندات بلا ربط، المقترحات، القيمة المقترحة، والاستثناءات.',
                                              'Invoices, vouchers, unlinked vouchers, proposals, proposed value and exceptions.'),
             'more': T('كلها محسوبة في السيرفر حسب الفلاتر.\n'
                       '• «سندات بلا ربط» بتتلوّن تحذير: فلوس اتدفعت ومش معروف سددت أنهي فاتورة.\n'
                       '• «قيمة مقترحة» = مجموع المقترحات القابلة للاعتماد.',
                       'All computed on the server according to the filters.\n'
                       '• "Unlinked vouchers" is highlighted as a warning: money paid with no known invoice.\n'
                       '• "Proposed value" = the total of proposals that can be approved.')},
            {'target': 'finance-reconciliation-tabs', 'text': T('التبويبات: «المقترحات»، «الاستثناءات»، «غير المسددة (للمالية)»، و«الحصر».',
                                              'Tabs: «المقترحات» (Proposals), «الاستثناءات» (Exceptions), «غير المسددة (للمالية)» (Unpaid) and «الحصر» (Parties).'),
             'more': T('• «المقترحات»: هنا بتعتمد أو ترفض.\n'
                       '• «الاستثناءات»: سند مكرر محتمل أو بيسمي فاتورة تانية وغيرها.\n'
                       '• «غير المسددة»: فواتير لسه عليها رصيد.\n'
                       '• «الحصر»: حساب كل مورد وكشفه.',
                       '• "Proposals": where you approve or reject.\n'
                       '• "Exceptions": a possible duplicate voucher, one naming another invoice, and more.\n'
                       '• "Unpaid": invoices still carrying a balance.\n'
                       '• "Parties": each supplier account and ledger.')},
            {'target': 'finance-reconciliation-status', 'text': T('في «المقترحات»: فلتر الحالة (يحتاج مراجعة، مقترحة، معتمدة، مكتوبة، مرفوضة…).',
                                              'In «المقترحات» (Proposals): the status filter (needs review, proposed, approved, written, rejected…).'),
             'more': T('• «⚠ يحتاج مراجعة»: مقترحات محجوزة لازم تتراجع واحدة واحدة.\n'
                       '• «معتمدة»: اتربطت عندنا ولسه ما اتكتبتش في SOFTECH.\n'
                       '• «مكتوبة»: اتكتبت في SOFTECH.\n'
                       'زر «✓ اعتماد كل الثقة العالية» بيعتمد العالية بس ويسيب المحجوزة.',
                       '• "⚠ Needs review": held proposals that must be reviewed one by one.\n'
                       '• "Approved": linked in our system and not yet written to SOFTECH.\n'
                       '• "Written": written to SOFTECH.\n'
                       'The "✓ Approve all high confidence" button approves only the high ones and leaves the held ones.')},
            {'target': 'finance-reconciliation-list', 'text': T('المقترحات بدرجة الثقة والفاتورة والسند والمتبقي؛ افتح الصف للتفاصيل، والاعتماد أو الرفض حسب الصلاحية.',
                                              'Proposals with confidence, invoice, voucher and remaining; open a row for details — approving or rejecting depends on permission.'),
             'more': T('افتح الصف عشان تشوف أصناف الفاتورة والمرتجعات المرتبطة، وبعدين «✓ اعتماد» أو «✕ رفض» (أو للمجموعة كاملة).\n'
                       '• «المتبقي» محسوب: قيمة الفاتورة − المسدد في SOFTECH − المعتمد بانتظار الكتابة.\n'
                       '• الاعتماد للمدير والصيدلي، والكتابة في SOFTECH للمدير بس.',
                       'Open the row to see the invoice items and linked returns, then "✓ Approve" or "✕ Reject" (or the whole group).\n'
                       '• "Remaining" is computed: invoice value − paid in SOFTECH − approved awaiting write.\n'
                       '• Approving is for the admin and pharmacist; writing to SOFTECH is for the admin only.')},
        ],
        'change_note': _NOTE,
        'updated': '2026-10-25',
    },
]
