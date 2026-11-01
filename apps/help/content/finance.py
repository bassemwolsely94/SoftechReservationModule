from . import T

_SYNC = T('لو ظهرت «لا توجد بيانات» فالمزامنة المالية لم تُشغَّل لهذه الفترة — اطلب من المدير تشغيلها.', 'If "no data" shows, the finance sync has not run for this period — ask the admin to run it.')

_NOTE = T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour')

MODULE = {
    'key': 'finance', 'group': 'finance', 'icon': '💹',
    'brief': T('لوحة المالية: الإيرادات والربح والمصروفات والتدفق النقدي وسداد الموردين.',
               'The finance board: revenue, profit, expenses, cash flow and supplier payments.'),
    'title': T('المالية', 'Finance'),
    'summary': T(
        'الذكاء المالي مبني على بيانات SOFTECH المحاسبية: لوحة قيادة (الإيرادات، الأرباح، المشتريات، المصروفات، التدفق النقدي، المخزون)، قائمة الأرباح والخسائر، '
        'التدفقات النقدية بطريقة الدفع، تحليل المصروفات، ودليل الحسابات. وأدوات تشغيلية: تخطيط الشيكات المؤجلة، تتبع المدفوعات الخارجية (انستاباي، فودافون كاش…)، '
        'مراجعة كشوف الحساب البنكية، ومطابقة سداد فواتير الموردين. هذه الشاشات لا تكتب في SOFTECH.',
        'Financial intelligence built on SOFTECH accounting data: an executive dashboard (revenue, profit, purchases, expenses, cash flow, stock), the profit & loss statement, '
        'cash flows by payment method, expense analysis and the chart of accounts. And operational tools: post-dated cheque planning, external payment tracking (Instapay, Vodafone Cash…), '
        'bank statement review, and supplier invoice payment reconciliation. These screens do not write to SOFTECH.'),
    'journeys': [
        {'key': 'monthly_review', 'shell': 'desktop',
         'title': T('مراجعة الشهر: من المؤشرات إلى التفاصيل', 'Month review: from KPIs to details'),
         'summary': T('اختر الشهر، اقرأ المؤشرات والفروع، ثم انزل للأرباح والخسائر والمصروفات والتدفق النقدي.',
                      'Pick the month, read the KPIs and branches, then drill into P&L, expenses and cash flow.'),
         'steps': [
            {'screen': 'finance.dashboard', 'target': 'finance-dashboard-period', 'perm': 'finance',
             'label': T('السنة والشهر', 'Year and month'),
             'text': T('ابدأ باختيار الشهر الذي تراجعه.', 'Start by picking the month you are reviewing.'),
             'when': T('كل الأرقام تحت تتغير مع الاختيار.', 'Every figure below follows this choice.')},
            {'screen': 'finance.dashboard', 'target': 'finance-dashboard-kpis', 'perm': 'finance',
             'label': T('المؤشرات المالية', 'Financial KPIs'),
             'text': T('صافي الإيرادات، الربح وهامشه، المشتريات، المصروفات، التدفق النقدي.', 'Net revenue, profit and margin, purchases, expenses, cash flow.'),
             'when': T('رقم غير طبيعي؟ انزل للتفاصيل في الخطوات التالية.', 'A figure looks odd? Drill into it in the next steps.')},
            {'screen': 'finance.dashboard', 'target': 'finance-dashboard-branches', 'perm': 'finance',
             'label': T('تفصيل الفروع', 'Branch breakdown'),
             'text': T('قارن الفروع: الهامش الأحمر أقل من 10%.', 'Compare branches: a red margin is under 10%.'),
             'open_hint': T('يظهر لما يكون للشهر بيانات فروع.', 'Shown when the month has branch data.')},
            {'screen': 'finance.pnl', 'target': 'finance-pnl-period', 'perm': 'finance',
             'label': T('السنة والشهر', 'Year and month'),
             'text': T('اختر نفس الشهر في قائمة الأرباح والخسائر.', 'Pick the same month in the profit & loss.'),
             'when': T('الاختيار هنا مستقل عن لوحة القيادة.', 'This choice is separate from the dashboard.')},
            {'screen': 'finance.pnl', 'target': 'finance-pnl-statement', 'perm': 'finance',
             'label': T('قائمة الأرباح والخسائر', 'P&L statement'),
             'text': T('اقرأها من فوق لتحت: الإيرادات ← التكلفة ← إجمالي الربح ← المصروفات ← صافي الربح.', 'Read it top-down: revenue → cost → gross profit → expenses → net profit.'),
             'when': T('المصروفات عالية؟ افتح «المصروفات».', 'Expenses high? Open "Expenses".')},
            {'screen': 'finance.expenses', 'target': 'finance-expenses-categories', 'perm': 'finance',
             'label': T('التوزيع بالفئة الرئيسية', 'Breakdown by main category'),
             'text': T('اضغط الفئة الأكبر لتصفية السجلات عليها.', 'Click the largest category to filter the records to it.'),
             'when': T('اضغطها تاني لإلغاء التصفية.', 'Click it again to clear the filter.')},
            {'screen': 'finance.expenses', 'target': 'finance-expenses-table', 'perm': 'finance',
             'label': T('تفاصيل المصروفات', 'Expense details'),
             'text': T('كل مصروف بتاريخه وبيانه ومركز التكلفة والفرع.', 'Each expense with its date, description, cost center and branch.')},
            {'screen': 'finance.cash', 'target': 'finance-cash-kpis', 'perm': 'finance',
             'label': T('أقل رصيد متوقع', 'Lowest projected balance'),
             'text': T('اختم بالنقدية لـ 13 أسبوع: هل فيه أسبوع الرصيد فيه تحت الصفر؟', 'Finish with the 13-week cash view: does any week go below zero?'),
             'when': T('أدخل رصيد النقدية الافتتاحي الأسبوعي أولاً.', 'Enter the weekly opening cash balance first.')},
         ]},
        {'key': 'cheque_plan', 'shell': 'desktop', 'roles': ['admin', 'purchasing', 'pharmacist'],
         'title': T('خطة شيكات: من الإنشاء إلى الصرف', 'Cheque plan: from creation to clearing'),
         'summary': T('أنشئ جدول شيكات مؤجلة، عاينه، فعّله، ثم سجّل حالة كل شيك حتى الصرف.',
                      'Create a post-dated cheque schedule, preview it, activate it, then record each cheque until it clears.'),
         'steps': [
            {'screen': 'finance.cheques', 'target': 'finance-cheques-new', 'perm': 'cheques',
             'label': T('+ خطة جديدة', '+ New plan'),
             'text': T('يفتح نموذج خطة جديدة على اليسار.', 'Opens a new-plan form on the side.')},
            {'screen': 'finance.cheques', 'target': 'finance-cheques-form-schedule', 'perm': 'cheques',
             'label': T('جدول السداد', 'Payment schedule'),
             'text': T('الإجمالي وعدد الشيكات وتاريخ الأول والفترة بينها.', 'Total, number of cheques, first date and the interval.'),
             'open_hint': T('اضغط «+ خطة جديدة».', 'Press "+ New plan".')},
            {'screen': 'finance.cheques', 'target': 'finance-cheques-preview', 'perm': 'cheques',
             'label': T('📅 معاينة جدول الشيكات', '📅 Preview cheque schedule'),
             'text': T('يحسب التواريخ والمبالغ ويرحّل أي تاريخ يقع في إجازة. لا يحفظ شيئاً.', 'Works out dates and amounts and moves any holiday date. Saves nothing.'),
             'open_hint': T('داخل نموذج الخطة الجديدة.', 'Inside the new-plan form.')},
            {'screen': 'finance.cheques', 'target': 'finance-cheques-create', 'perm': 'cheques',
             'label': T('إنشاء الخطة', 'Create plan'),
             'text': T('يحفظ الخطة «مسودة» بشيكاتها.', 'Saves the plan as a "draft" with its cheques.'),
             'open_hint': T('داخل نموذج الخطة الجديدة.', 'Inside the new-plan form.')},
            {'screen': 'finance.cheques', 'target': 'finance-cheques-activate', 'perm': 'cheques',
             'label': T('✅ تفعيل الخطة', '✅ Activate plan'),
             'text': T('يجعل الخطة «نشطة» فتدخل مؤشرات الخزينة.', 'Makes the plan "active" so it counts in the treasury figures.'),
             'when': T('بعد مراجعة الجدول. يحتاج صلاحية «اعتماد».', 'After checking the schedule. Needs "approve" permission.'),
             'open_hint': T('افتح خطة «مسودة» من القائمة.', 'Open a "draft" plan from the list.')},
            {'screen': 'finance.cheques', 'target': 'finance-cheques-edit-cheque', 'perm': 'cheques',
             'label': T('تعديل', 'Edit'),
             'text': T('سجّل رقم الشيك وحالته: صادر ← مُقدَّم للبنك ← تمّ الصرف.', 'Record the cheque number and status: issued → presented → cleared.'),
             'open_hint': T('افتح خطة «نشطة» — الزر بجانب كل شيك غير مصروف.', 'Open an "active" plan — the button is beside each uncleared cheque.')},
            {'screen': 'finance.cheques', 'target': 'finance-cheques-save-cheque', 'perm': 'cheques',
             'label': T('حفظ', 'Save'),
             'text': T('يحفظ حالة الشيك. لما تُصرف كل الشيكات تكتمل الخطة تلقائياً.', 'Saves the cheque status. When all cheques clear, the plan completes by itself.'),
             'warn': T('«تمّ الصرف» نهائي ولا يُعدَّل بعده.', '"Cleared" is final and cannot be edited afterwards.'),
             'open_hint': T('اضغط «تعديل» على شيك.', 'Press "Edit" on a cheque.')},
         ]},
        {'key': 'payment_check', 'shell': 'desktop', 'roles': ['admin', 'purchasing'],
         'title': T('الدفعات الخارجية: تسجيل ثم مطابقة بالبنك', 'External payments: record then match to the bank'),
         'summary': T('سجّل دفعة انستاباي/فودافون كاش، أكّدها، ثم ارفع كشف البنك وطابقه وعالج الاستثناءات.',
                      'Record an Instapay/Vodafone Cash payment, confirm it, then upload the bank statement, match it and handle exceptions.'),
         'steps': [
            {'screen': 'finance.payments', 'target': 'finance-payments-new', 'perm': 'finance',
             'label': T('+ تسجيل دفعة', '+ Record payment'),
             'text': T('يفتح نموذج الدفعة: الطريقة والمبلغ والفرع والمرجع والإيصال.', 'Opens the payment form: method, amount, branch, reference and receipt.')},
            {'screen': 'finance.payments', 'target': 'finance-payments-new-save', 'perm': 'finance',
             'label': T('تسجيل الدفعة', 'Record payment'),
             'text': T('يحفظ الدفعة «في الانتظار».', 'Saves the payment as "pending".'),
             'open_hint': T('اضغط «+ تسجيل دفعة».', 'Press "+ Record payment".')},
            {'screen': 'finance.payments', 'target': 'finance-payments-confirm', 'perm': 'finance',
             'label': T('تأكيد ✓', 'Confirm ✓'),
             'text': T('بعد ما تتأكد إن الفلوس وصلت فعلاً، أكّد الدفعة.', 'Once you are sure the money really arrived, confirm the payment.'),
             'warn': T('بعد التأكيد لا تعديل ولا حذف.', 'No edits or deletion after confirming.'),
             'open_hint': T('يظهر على الدفعات «في الانتظار».', 'Shown on "pending" payments.')},
            {'screen': 'finance.payment_audit', 'target': 'finance-payment-audit-upload', 'perm': 'finance',
             'label': T('+ رفع كشف حساب', '+ Upload statement'),
             'text': T('ارفع كشف البنك (CSV أو Excel) للفترة.', 'Upload the bank statement (CSV or Excel) for the period.')},
            {'screen': 'finance.payment_audit', 'target': 'finance-payment-audit-run-matching', 'perm': 'finance',
             'label': T('تشغيل المطابقة', 'Run matching'),
             'text': T('يطابق سطور الكشف بالدفعات المسجّلة ويحسب نسبة المطابقة.', 'Matches statement lines to recorded payments and computes the match rate.'),
             'open_hint': T('تبويب «🏦 الكشوف البنكية»، على كشف حالته pending.', 'The "🏦 Bank statements" tab, on a pending statement.')},
            {'screen': 'finance.payment_audit', 'target': 'finance-payment-audit-handle', 'perm': 'finance',
             'label': T('معالجة', 'Handle'),
             'text': T('افتح الاستثناء: غير مسجّل، مكرر، فرع خاطئ، تباين في المبلغ…', 'Open the exception: unrecorded, duplicate, wrong branch, amount mismatch…'),
             'open_hint': T('تبويب «⚠️ الاستثناءات».', 'The "⚠️ Exceptions" tab.')},
            {'screen': 'finance.payment_audit', 'target': 'finance-payment-audit-resolve', 'perm': 'finance',
             'label': T('حل الاستثناء', 'Resolve'),
             'text': T('يغلق الاستثناء «تم الحل» باسمك.', 'Closes the exception as "resolved" under your name.'),
             'warn': T('نهائي — تأكد من السبب قبل الإغلاق.', 'Final — check the cause before closing it.'),
             'open_hint': T('اضغط «معالجة» على استثناء.', 'Press "Handle" on an exception.')},
         ]},
        {'key': 'supplier_settlement', 'shell': 'desktop', 'roles': ['admin', 'purchasing'],
         'title': T('سداد الموردين: مراجعة واعتماد المطابقات', 'Supplier payments: review and approve links'),
         'summary': T('حدد المورد والفترة، راجع مقترحات الربط بين السندات والفواتير، اعتمد الواضح، ثم صدّر غير المسدد للمالية.',
                      'Set the supplier and period, review voucher-to-invoice proposals, approve the clear ones, then export the unpaid for finance.'),
         'steps': [
            {'screen': 'finance.reconciliation', 'target': 'finance-reconciliation-filters', 'perm': 'finance',
             'label': T('الفلاتر', 'Filters'),
             'text': T('اختر المورد وتاريخ الفاتورة أو السند والقيمة.', 'Pick the supplier, invoice or voucher date, and value.'),
             'when': T('الفلاتر تنطبق على كل التبويبات والتصدير والإجراءات الجماعية.', 'Filters apply to every tab, export and bulk action.')},
            {'screen': 'finance.reconciliation', 'target': 'finance-reconciliation-confidence', 'perm': 'finance',
             'label': T('الثقة', 'Confidence'),
             'text': T('ابدأ بالثقة العالية، ثم المتوسطة والمنخفضة.', 'Start with high confidence, then medium and low.'),
             'open_hint': T('تبويب «المقترحات».', 'The "Proposals" tab.')},
            {'screen': 'finance.reconciliation', 'target': 'finance-reconciliation-row', 'perm': 'finance',
             'label': T('صف المقترح', 'Proposal row'),
             'text': T('افتح الصف: الفاتورة والسند والمرتجعات والدليل جنباً لجنب.', 'Open the row: invoice, voucher, returns and evidence side by side.'),
             'open_hint': T('في عرض «☰ جدول».', 'In the "☰ Table" view.')},
            {'screen': 'finance.reconciliation', 'target': 'finance-reconciliation-approve', 'perm': 'finance',
             'label': T('✓ اعتماد', '✓ Approve'),
             'text': T('ينشئ الربط في المرآة لدينا فقط ويخفّض «المتبقي».', 'Creates the link in our mirror only and lowers "remaining".'),
             'warn': T('اعتماد ربط خاطئ يُظهر الفاتورة مسددة وهي لا.', 'Approving a wrong link shows the invoice as paid when it is not.'),
             'open_hint': T('افتح صف مقترح بحالة «مقترحة».', 'Open a "proposed" row.')},
            {'screen': 'finance.reconciliation', 'target': 'finance-reconciliation-unpaid-export', 'perm': 'finance',
             'label': T('⬇ تصدير Excel للإدارة المالية', '⬇ Excel export for finance'),
             'text': T('ملف بالفواتير التي ما زال عليها رصيد بعد الربط.', 'A file of the invoices still carrying a balance after linking.'),
             'open_hint': T('تبويب «غير المسددة (للمالية)».', 'The "Unpaid (for finance)" tab.')},
         ]},
    ],

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
                {'target': 'finance-cash-kpis', 'route': '/finance/cash',
                 'text': T('«النقدية 13 أسبوع»: الداخل والخارج المتوقع كل أسبوع والرصيد.',
                           '"13-week cash": expected money in and out each week, and the balance.'),
                 'more': T('الداخل: مبيعات نقدي وتوصيل وتحصيل التعاقدات. الخارج: شيكات الموردين المؤجلة ومستحقاتهم ومشتريات جديدة ومصروفات ثابتة.\n'
                           '• الرصيد بثلاث حالات: متشائم وأساسي ومتفائل.',
                           'In: cash and delivery sales and contract collections. Out: post-dated supplier cheques, supplier payables, new purchases and fixed outflows.\n'
                           '• The balance in three cases: low, base and high.')},
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
                {'target': 'finance-reconciliation-party-type', 'route': '/reconciliation',
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
        'tips': [
            T('الشريط فوق تبويبات المالية بيقول البيانات اتحدّثت إمتى: الأرباح والخسائر مع كل مزامنة، والقيود والمصروفات كل ليلة ٢:١٥ لآخر ٣ شهور. لو أصفر يبقى قديمة — المدير يقدر يضغط «🔄 تحديث الآن» يحدّث الشهر الحالي.', 'The bar above the finance tabs says when the data was refreshed: P&L with every sync, journal and expenses every night at 02:15 for the last 3 months. Amber means old — an admin can press "🔄 Refresh now" to update the current month.'),_SYNC, T('«بيانات غير مكتملة» تعني أن بعض المصادر لم تُزامن بعد لهذه الفترة.', '"Incomplete data" means some sources are not synced yet for this period.')],
        'related': ['finance.pnl', 'finance.cash'],
        'tour': [
            {'target': 'finance-freshness', 'label': T('عمر البيانات المالية', 'Finance data age'),
             'text': T('إمتى اتحدّثت الأرباح والمصروفات والقيود آخر مرة.', 'When P&L, expenses and the journal were last refreshed.'),
             'when': T('قبل ما تاخد أي رقم من الشاشة دي.', 'Before taking any figure from this screen.')},
            {'target': 'finance-dashboard-tabs',
             'label': T('تبويبات الذكاء المالي', 'Finance tabs'),
             'text': T('تنقّل بين لوحة القيادة والأرباح والخسائر والتدفق النقدي والمصروفات ودليل الحسابات.',
                       'Move between the dashboard, P&L, cash flow, expenses and the chart of accounts.'),
             'when': T('«اكتشاف المخطط» يظهر للمدير فقط.', '"Schema discovery" shows to admins only.')},
            {'target': 'finance-dashboard-period',
             'label': T('السنة والشهر', 'Year and month'),
             'text': T('اختر الفترة. كل المؤشرات والفروع تتبعها.', 'Pick the period. All KPIs and branches follow it.'),
             'when': T('آخر 5 سنوات متاحة.', 'The last 5 years are available.'),
             'more': T('اللوحة بتتحمّل لوحدها مع أي تغيير. الأرقام جاية من ملخص الشهر اللي المزامنة المالية بتحسبه من بيانات SOFTECH المحاسبية.\n'
                       '• لو الشهر ما اتزامنش هتظهر رسالة «تعذّر تحميل البيانات» — اطلب من المدير يشغّل المزامنة.\n'
                       '• جنبها بيظهر اسم الفترة.',
                       'The board loads by itself on any change. The figures come from the month summary the finance sync computes from SOFTECH accounting data.\n'
                       '• If the month was not synced, a "Could not load data" message shows — ask the admin to run the sync.\n'
                       '• The period name appears next to it.'),
         },
            {'target': 'finance-dashboard-refresh',
             'label': T('تحديث', 'Refresh'),
             'text': T('يعيد قراءة الأرقام من بياناتنا. لا يشغّل مزامنة SOFTECH.', 'Re-reads the figures from our data. It does not run a SOFTECH sync.'),
             'when': T('بعد ما المدير يشغّل المزامنة المالية.', 'After the admin runs the finance sync.'),
             'more': T('مفيد بعد ما مزامنة مالية جديدة تخلص والصفحة مفتوحة.\n'
                       '• لو ظهر جنبه «⚠ بيانات غير مكتملة» يبقى فيه مصادر لسه ما اتزامنتش للشهر ده، والأرقام ممكن تتغير.\n'
                       '• التحديث بيقرا بس، مش بيعيد الحساب.',
                       'Useful after a new finance sync finishes while the page is open.\n'
                       '• If "⚠ Incomplete data" shows next to it, some sources are not synced yet for that month and the figures may change.\n'
                       '• Refreshing only reads; it does not recompute.'),
         },
            {'target': 'finance-dashboard-incomplete',
             'label': T('⚠ بيانات غير مكتملة', '⚠ Incomplete data'),
             'text': T('بعض المصادر لم تُزامن بعد لهذه الفترة.', 'Some sources are not synced yet for this period.'),
             'warn': T('لا تبني قراراً على أرقام فترة غير مكتملة.', 'Do not base a decision on an incomplete period.'),
             'open_hint': T('يظهر فقط لما تكون الفترة ناقصة.', 'Shown only when the period is incomplete.')},
            {'target': 'finance-dashboard-kpis',
             'label': T('المؤشرات المالية', 'Financial KPIs'),
             'text': T('صافي الإيرادات، إجمالي وصافي الربح وهامشهما، المشتريات، المصروفات، التدفق النقدي، المخزون، المرتجعات.',
                       'Net revenue, gross and net profit with margins, purchases, expenses, cash flow, stock, returns.'),
             'when': T('التدفق النقدي يتلوّن أحمر لو سالب. قيمة المخزون تقدير تراكمي.', 'Cash flow turns red when negative. Stock value is a running estimate.'),
             'more': T('• صافي الإيرادات (وتحته الإجمالي)، إجمالي الربح وهامشه، صافي الربح وهامشه.\n'
                       '• صافي المشتريات، إجمالي المصروفات، صافي التدفق النقدي، قيمة المخزون («تقدير تراكمي»)، والمرتجعات.\n'
                       'كلها محسوبة في المزامنة — مفيش رقم هنا بيتكتب باليد.',
                       '• Net revenue (with gross under it), gross profit and margin, net profit and margin.\n'
                       '• Net purchases, total expenses, net cash flow, stock value ("cumulative estimate") and returns.\n'
                       'All are computed by the sync — no figure here is typed by hand.'),
         },
            {'target': 'finance-dashboard-trend',
             'label': T('الاتجاه الشهري', 'Monthly trend'),
             'text': T('صافي الإيرادات لكل شهر في السنة المختارة.', 'Net revenue for each month of the chosen year.'),
             'open_hint': T('يظهر لما يكون للسنة بيانات.', 'Shown when the year has data.'),
             'more': T('عمود لكل شهر اتزامن من نفس السنة، لكل الفروع مع بعض.\n'
                       '• بيبيّن الموسمية والشهور اللي فيها نزول عشان تسأل عن السبب.',
                       'One bar per synced month of the same year, for all branches together.\n'
                       '• It shows seasonality and the months with a drop so you can ask why.'),
         },
            {'target': 'finance-dashboard-branches',
             'label': T('تفصيل الفروع', 'Branch breakdown'),
             'text': T('إيرادات وربح وهامش كل فرع. الهامش: أخضر ≥ 20%، أصفر ≥ 10%، أحمر أقل.',
                       'Each branch\'s revenue, profit and margin. Margin: green ≥ 20%, yellow ≥ 10%, red below.'),
             'when': T('النقطة الصفراء في «مكتمل» = بيانات الفرع ناقصة.', 'A yellow dot under "Complete" = the branch data is partial.'),
             'open_hint': T('يظهر لما يكون للشهر بيانات فروع.', 'Shown when the month has branch data.'),
             'more': T('لكل فرع: صافي الإيرادات، إجمالي الربح، هامش الربح، صافي الربح، وهل بياناته «مكتمل».\n'
                       '• فرع مش مكتمل ممكن أرقامه أقل من الحقيقة لحد ما المزامنة تخلص.',
                       'Per branch: net revenue, gross profit, profit margin, net profit, and whether its data is "Complete".\n'
                       '• An incomplete branch may show lower figures until the sync finishes.'),
         },
            {'target': 'finance-dashboard-last-sync',
             'label': T('آخر مزامنة', 'Last sync'),
             'text': T('حالة ووقت آخر مزامنة مالية.', 'The status and time of the last finance sync.'),
             'when': T('قديمة؟ اطلب من المدير تشغيل المزامنة.', 'Old? Ask the admin to run the sync.')},
        ],
        'updated': '2026-10-30',
    
        'change_note': T('شريط عمر البيانات + مزامنة مالية ليلية', 'Data-age bar + nightly finance sync'),
    },
    {
        'key': 'finance.pnl',
        'routes': ['/finance/pnl'],
        'title': T('قائمة الأرباح والخسائر', 'Profit & loss'),
        'summary': T('الإيرادات (المبيعات − المرتجعات) ← تكلفة البضاعة (المشتريات − مرتجعاتها) ← إجمالي الربح ← المصروفات التشغيلية (رواتب، إيجارات، مرافق، أخرى) ← الربح التشغيلي وصافي الربح، موحّدة أو لفرع.',
                     'Revenue (sales − returns) → cost of goods (purchases − returns) → gross profit → operating expenses (salaries, rent, utilities, other) → operating and net profit, consolidated or per branch.'),
        'audience': T('الإدارة والمالية.', 'Management and finance.'),
        'tips': [
            T('الشريط فوق تبويبات المالية بيقول البيانات اتحدّثت إمتى: الأرباح والخسائر مع كل مزامنة، والقيود والمصروفات كل ليلة ٢:١٥ لآخر ٣ شهور. لو أصفر يبقى قديمة — المدير يقدر يضغط «🔄 تحديث الآن» يحدّث الشهر الحالي.', 'The bar above the finance tabs says when the data was refreshed: P&L with every sync, journal and expenses every night at 02:15 for the last 3 months. Amber means old — an admin can press "🔄 Refresh now" to update the current month.'),_SYNC,
            T('أرقام الشركة كلها وأرباح كل الفروع للإدارة ومدير الجودة والمركز الرئيسي. موظف الفرع بيشوف أرقام فرعه بس.',
              'Company-wide figures and the P&L of every branch are for management, the quality manager and HQ. A branch user sees the figures of their own branch only.')],
        'tour': [
            {'target': 'finance-freshness', 'label': T('عمر البيانات المالية', 'Finance data age'),
             'text': T('إمتى اتحدّثت الأرباح والمصروفات والقيود آخر مرة.', 'When P&L, expenses and the journal were last refreshed.'),
             'when': T('قبل ما تاخد أي رقم من الشاشة دي.', 'Before taking any figure from this screen.')},
            {'target': 'finance-pnl-period',
             'label': T('السنة والشهر', 'Year and month'),
             'text': T('اختر الشهر الذي تريد قائمته.', 'Pick the month you want the statement for.'),
             'when': T('القائمة تتحدّث فوراً.', 'The statement updates at once.'),
             'more': T('القائمة بتتحمّل لوحدها مع تغيير الشهر.\n'
                       '• لو ظهر «تعذّر التحميل» يبقى الشهر ده ما اتزامنش ماليّاً لسه.\n'
                       '• قارن شهرين ورا بعض عشان تشوف اتجاه الربح.',
                       'The statement loads by itself when you change the month.\n'
                       '• If "Could not load" shows, that month has not been finance-synced yet.\n'
                       '• Compare two months in a row to see the profit trend.'),
         },
            {'target': 'finance-pnl-header',
             'label': T('قائمة الأرباح والخسائر', 'Profit & loss'),
             'text': T('الفترة والنطاق: «موحد (جميع الفروع)» أو فرع واحد.', 'The period and scope: "Consolidated (all branches)" or one branch.'),
             'more': T('القائمة هنا موحّدة لكل الفروع.\n'
                       '• لو عايز أرقام فرع فرع شوف جدول الفروع في «لوحة القيادة».',
                       'The statement here is consolidated for all branches.\n'
                       '• For branch-by-branch figures see the branch table on the "Dashboard".'),
         },
            {'target': 'finance-pnl-statement',
             'label': T('بنود القائمة', 'Statement lines'),
             'text': T('الإيرادات ← تكلفة البضاعة ← إجمالي الربح ← المصروفات ← الربح التشغيلي وEBITDA ← صافي الربح.',
                       'Revenue → cost of goods → gross profit → expenses → operating profit and EBITDA → net profit.'),
             'when': T('الأرقام بين أقواس تُطرح. الأحمر = خسارة.', 'Figures in brackets are deducted. Red = a loss.'),
             'more': T('• الإيرادات: إجمالي المبيعات − المرتجعات = صافي الإيرادات.\n'
                       '• التكلفة: المشتريات − مرتجعات المشتريات.\n'
                       '• المصروفات: رواتب، إيجارات، مرافق، أخرى.\n'
                       'الأرقام بين قوسين بتتخصم، وكلها محسوبة في المزامنة.',
                       '• Revenue: gross sales − returns = net revenue.\n'
                       '• Cost: purchases − purchase returns.\n'
                       '• Expenses: salaries, rent, utilities, other.\n'
                       'Figures in brackets are deducted, and all are computed by the sync.'),
         },
            {'target': 'finance-pnl-incomplete',
             'label': T('⚠ بيانات جزئية', '⚠ Partial data'),
             'text': T('بعض المصادر لم تُزامن بعد.', 'Some sources are not synced yet.'),
             'warn': T('صافي الربح هنا غير نهائي — لا تعتمد عليه.', 'Net profit here is not final — do not rely on it.'),
             'open_hint': T('يظهر أسفل القائمة لما تكون الفترة ناقصة.', 'Shown under the statement when the period is partial.'),
             'more': T('معناه إن القائمة ممكن تتغير بعد المزامنة الجاية.\n'
                       '• متعتمدش على الأرقام دي في قرار نهائي غير لما التنبيه يختفي.',
                       'It means the statement may change after the next sync.\n'
                       '• Do not rely on these figures for a final decision until the note disappears.'),
         },
        ],
        'updated': '2026-10-30',
    
        'change_note': T('شريط عمر البيانات + مزامنة مالية ليلية', 'Data-age bar + nightly finance sync'),
    },
    {
        'key': 'finance.expenses',
        'routes': ['/finance/expenses'],
        'title': T('تحليل المصروفات', 'Expense analysis'),
        'summary': T('المصروفات حسب الفئة (رواتب، إيجارات، مرافق، صيانة، توصيل، تسويق، فاقد، منتهي الصلاحية…) والتصنيف الفرعي والفرع ومركز التكلفة، بفترة شهر/سنة أو نطاق تاريخ. اضغط فئة لتصفية التفاصيل.',
                     'Expenses by category (salaries, rent, utilities, maintenance, delivery, marketing, shrinkage, expired…), sub-category, branch and cost center, by month/year or a date range. Click a category to filter the details.'),
        'audience': T('الإدارة والمالية.', 'Management and finance.'),
        'tips': [
            T('الشريط فوق تبويبات المالية بيقول البيانات اتحدّثت إمتى: الأرباح والخسائر مع كل مزامنة، والقيود والمصروفات كل ليلة ٢:١٥ لآخر ٣ شهور. لو أصفر يبقى قديمة — المدير يقدر يضغط «🔄 تحديث الآن» يحدّث الشهر الحالي.', 'The bar above the finance tabs says when the data was refreshed: P&L with every sync, journal and expenses every night at 02:15 for the last 3 months. Amber means old — an admin can press "🔄 Refresh now" to update the current month.'),_SYNC],
        'tour': [
            {'target': 'finance-freshness', 'label': T('عمر البيانات المالية', 'Finance data age'),
             'text': T('إمتى اتحدّثت الأرباح والمصروفات والقيود آخر مرة.', 'When P&L, expenses and the journal were last refreshed.'),
             'when': T('قبل ما تاخد أي رقم من الشاشة دي.', 'Before taking any figure from this screen.')},
            {'target': 'finance-expenses-mode',
             'label': T('شهر / سنة · نطاق تاريخ', 'Month / year · Date range'),
             'text': T('اختر طريقة تحديد الفترة: شهر بعينه أو من تاريخ إلى تاريخ.', 'Choose how to set the period: one month, or from a date to a date.'),
             'when': T('النطاق مفيد لربع سنة أو موسم.', 'A range suits a quarter or a season.'),
             'more': T('• «شهر / سنة»: شهر كامل.\n'
                       '• «نطاق تاريخ»: من يوم ليوم، مفيد لربع سنة أو موسم.\n'
                       'التبديل بيرجعك لأول صفحة في الجدول.',
                       '• "Month / year": a whole month.\n'
                       '• "Date range": from one day to another, useful for a quarter or a season.\n'
                       'Switching takes you back to the first page of the table.'),
         },
            {'target': 'finance-expenses-filters',
             'label': T('الفلاتر', 'Filters'),
             'text': T('الفترة والفئة والتصنيف الفرعي والفرع.', 'Period, category, sub-category and branch.'),
             'when': T('التصنيفات الفرعية تتقيد بالفئة المختارة.', 'Sub-categories narrow to the chosen category.'),
             'more': T('الفلاتر المختارة بتظهر كشرائح تقدر تشيل أي واحدة منها، و«مسح الكل» بيلغيهم مرة واحدة.\n'
                       '• كل الأرقام والتوزيع والجدول بيتبعوا الفلاتر.',
                       'The chosen filters show as chips you can remove one by one, and "Clear all" removes them at once.\n'
                       '• All the figures, the breakdown and the table follow the filters.'),
         },
            {'target': 'finance-expenses-chips',
             'label': T('مرشحات نشطة', 'Active filters'),
             'text': T('كل فلتر مفعّل كشريحة؛ «×» يلغيه و«مسح الكل» يلغيها كلها.', 'Each active filter as a chip; "×" removes it and "Clear all" removes them all.'),
             'open_hint': T('تظهر بعد اختيار أي فلتر.', 'Shown after you pick any filter.')},
            {'target': 'finance-expenses-kpis',
             'label': T('إجمالي المصروفات', 'Total expenses'),
             'text': T('الإجمالي للفترة وعدد الفئات وعدد السجلات.', 'The period total, the number of categories and of records.'),
             'more': T('الإجمالي محسوب في السيرفر من سجلات المصروفات المتزامنة من SOFTECH، وتحته الفترة.\n'
                       '• «عدد السجلات» هو عدد قيود المصروف في الجدول تحت.',
                       'The total is computed on the server from the expense records synced from SOFTECH, with the period under it.\n'
                       '• "Records" is the number of expense entries in the table below.'),
         },
            {'target': 'finance-expenses-breakdown',
             'label': T('التوزيع بالفئة الرئيسية', 'Breakdown by main category'),
             'when': T('لمعرفة أكبر بنود المصروفات والدخول في تفاصيلها.', 'To find the largest expense heads and drill into them.'),
             'text': T('التوزيع حسب الفئة الرئيسية — اضغط فئة لتصفية التفاصيل.',
                                              'The breakdown by main category — click a category to filter the details.'),
             'more': T('الضغط على فئة بيفلتر الصفحة عليها ويظهر جنبها توزيع التصنيفات الفرعية، والضغط تاني بيلغي الفلتر.\n'
                       '• كمان تقدر تضغط تصنيف فرعي عشان تضيّق أكتر.',
                       'Clicking a category filters the page to it and shows the sub-category breakdown next to it; clicking again removes the filter.\n'
                       '• You can also click a sub-category to narrow further.')},
            {'target': 'finance-expenses-categories',
             'label': T('التوزيع بالفئة الرئيسية', 'Breakdown by main category'),
             'text': T('اضغط فئة لتصفية التصنيفات الفرعية والسجلات عليها.', 'Click a category to filter the sub-categories and records to it.'),
             'when': T('اضغطها تاني لإلغاء التصفية.', 'Click it again to clear the filter.')},
            {'target': 'finance-expenses-subcategories',
             'label': T('التصنيفات الفرعية', 'Sub-categories'),
             'text': T('المبلغ والعدد والنسبة لكل تصنيف فرعي. اضغط واحداً لتصفية الجدول.', 'Amount, count and share per sub-category. Click one to filter the table.'),
             'open_hint': T('يظهر لما تكون للفترة تصنيفات فرعية.', 'Shown when the period has sub-categories.')},
            {'target': 'finance-expenses-table',
             'label': T('تفاصيل المصروفات', 'Expense details'),
             'text': T('التاريخ والفئة والتصنيف والبيان ومركز التكلفة والفرع والمبلغ.', 'Date, category, sub-category, description, cost center, branch and amount.'),
             'when': T('شارات الفئة والتصنيف في الجدول قابلة للضغط كفلتر.', 'The category and sub-category badges in the table click to filter.'),
             'more': T('الأعمدة: التاريخ، الفئة، التصنيف الفرعي، البيان، مركز التكلفة، الفرع، المبلغ.\n'
                       '• استخدمه لما رقم في التوزيع يبان غريب وعايز تعرف القيود اللي وراه.',
                       'Columns: date, category, sub-category, description, cost center, branch, amount.\n'
                       '• Use it when a figure in the breakdown looks odd and you want the entries behind it.'),
         },
            {'target': 'finance-expenses-pagination',
             'label': T('السابق · التالي', 'Previous · Next'),
             'text': T('40 سجلاً في الصفحة.', '40 records per page.'),
             'more': T('كل صفحة فيها 40 سجل؛ «→ التالي» و«← السابق» للتنقل ورقم الصفحة في النص.\n'
                       '• لتقليل الصفحات ضيّق الفلاتر.',
                       'Each page holds 40 records; "Next →" and "← Previous" to move, with the page number in the middle.\n'
                       '• To get fewer pages, narrow the filters.'),
         },
        ],
        'updated': '2026-10-30',
    
        'change_note': T('شريط عمر البيانات + مزامنة مالية ليلية', 'Data-age bar + nightly finance sync'),
    },
    {
        'key': 'finance.receivables',
        'routes': ['/finance/receivables'],
        'title': T('مستحقات التعاقدات', 'Contract receivables'),
        'summary': T('مين مديون لنا على التعاقد ومن إمتى: فواتير البيع المفتوحة لحسابات التعاقد (من SOFTECH، قراءة فقط) مقسّمة حسب العمر، مع تاريخ الاستحقاق المتوقع = نهاية شهر الفاتورة + الأيام المتفق عليها، والمتأخر، والمقبوضات اللي على الحساب، والفرق مع رصيد SOFTECH. حسابات شركات التأمين بنسب التحمل المختلفة (D M S 10%، 20%…) مجمّعة تحت الشركة.',
                     'Who owes us on contract and since when: the open sales invoices of the contract accounts (from SOFTECH, read only) by age, with the expected date = end of the invoice month + the agreed days, what is overdue, receipts on account, and the difference with the SOFTECH balance. Insurance companies\' co-pay accounts (D M S 10%, 20%…) are grouped under the company.'),
        'audience': T('المالية والإدارة (الإدارة فقط — بيانات على مستوى الشركة).', 'Finance and management (management only — company-level data).'),
        'tips': [
            T('«أيام متفق عليها» تُكتب لكل حساب من عقده، وتُحسب من نهاية شهر الفاتورة. لو مش مكتوبة، الاستحقاق المتوقع = تاريخ الفاتورة + الأيام المقاسة ويتعلّم «مقاس — غير متفق عليه». كل تعديل يتسجّل باسمك.',
              'Enter each account\'s «agreed days» from its contract; they count from the end of the invoice month. Without them, the expected date = invoice date + the measured days, labelled «measured — not agreed». Every change is logged under your name.'),
            T('«أيام مقاسة»: لو SOFTECH رابط 70% أو أكثر من مبيعات الحساب بمقبوضات، تُحسب من الربط نفسه؛ لو أقل، «تقدير — أقدم فاتورة أولاً»: كل مقبوض يسدد أقدم الفواتير.',
              '«Measured days»: when SOFTECH links 70% or more of the account\'s sales to receipts, they come from those links; below that, an estimate where each receipt pays the oldest invoices first.'),
            T('الشاشة دي قراءة بس: مفيش أي كتابة في SOFTECH. «🔄 تحديث الآن» بيقرا حسابات التعاقد المتابَعة لآخر 120 يوم، وفيه تحديث تلقائي كل يوم الصبح.',
              'This screen only reads: nothing is written to SOFTECH. «🔄 Refresh now» re-reads the tracked contract accounts for the last 120 days; it also refreshes every morning.'),
        ],
        'tour': [
            {'target': 'finance-receivables-freshness', 'label': T('عمر بيانات المستحقات', 'Receivables data age'),
             'text': T('آخر مرة اتقرت حسابات التعاقد من SOFTECH، وزر التحديث.', 'When the contract accounts were last read from SOFTECH, and the refresh button.')},
            {'target': 'finance-receivables-kpis', 'label': T('صافي المستحق · المتأخر', 'Net receivable · Overdue'),
             'text': T('الإجمالي: المفتوح ناقص اللي على الحساب والمرتجعات، والمتأخر، ومتوسط أيام التحصيل.', 'Totals: open minus on-account and returns, overdue, and average collection days.')},
            {'target': 'finance-receivables-table', 'label': T('الجهة / الحساب', 'Company / account'),
             'text': T('اضغط الجهة تشوف حساباتها، والحساب تشوف فواتيره المفتوحة وآخر مقبوضاته. اكتب «أيام متفق عليها» في الخانة.', 'Click a company to see its accounts, and an account to see its open invoices and latest receipts. Type the «agreed days» in the box.'),
             'when': T('«الفرق» بالبرتقالي = المستحق عندنا مختلف عن رصيد SOFTECH — راجعه.', 'An amber «difference» = our receivable differs from the SOFTECH balance — check it.')},
            {'target': 'finance-receivables-export', 'label': T('⬇️ تصدير Excel', '⬇️ Export Excel'),
             'text': T('ملف بكل الحسابات وأعمار الديون والأيام.', 'A file with every account, the ageing and the days.')},
        ],
        'updated': '2026-10-31',
        'change_note': T('شاشة جديدة: مستحقات التعاقدات', 'New screen: contract receivables'),
    },
    {
        'key': 'finance.supplier_terms',
        'routes': ['/finance/supplier-terms'],
        'title': T('شروط الموردين', 'Supplier terms'),
        'summary': T('أيام الائتمان لكل مورد حسب نوع الصنف (محلي / مستورد) وخصم الدفع المبكر. كل فاتورة مورد مفتوحة تتقسم محلي ومستورد حسب سطورها، وكل جزء ياخد تاريخ استحقاق من الشروط. منها: تقويم السداد بالأسابيع، وفرص الدفع المبكر، والسداد في الموعد، والبنود المفتوحة أكتر من سنة.',
                     'Each supplier\'s credit days by item type (local / imported) and any early-pay discount. Every open supplier invoice is split local / imported from its lines, and each part gets a due date from the terms. From that: the weekly payment calendar, early-pay opportunities, paid on time, and items open more than a year.'),
        'audience': T('المالية والإدارة (الإدارة فقط — بيانات على مستوى الشركة).', 'Finance and management (management only — company-level data).'),
        'tabs': [
            {'key': 'terms', 'title': T('الشروط', 'Terms'),
             'body': T('اكتب أيام الائتمان في خانة الفئة. «كل الأصناف» تنطبق لما مفيش شرط للفئة. اضغط اسم المورد لباقي الشروط: الأيام من تاريخ الفاتورة أو نهاية الشهر، الدفع المبكر، ساري حتى. كل تعديل يتسجل باسمك.',
                       'Type the credit days in the category box. «All items» applies when a category has no term. Click the supplier for the rest: days from the invoice date or month end, early pay, valid until. Every change is logged under your name.')},
            {'key': 'calendar', 'title': T('تقويم السداد', 'Payment calendar'),
             'body': T('المستحق للموردين الفعليين أسبوع بأسبوع (الأسبوع يبدأ السبت)، مع المتأخر و«بدون شروط». الحسابات الداخلية (كوبونات، شراء من مرضى، بدل) في جدول منفصل.',
                       'What real suppliers are due week by week (weeks start Saturday), with overdue and «no terms». Internal accounts (coupons, patient buy-back, replacements) are in a separate table.')},
            {'key': 'early', 'title': T('فرص الدفع المبكر', 'Early-pay opportunities'),
             'body': T('الفواتير اللي لو اتدفعت قبل آخر موعد تاخد خصم، مرتبة بالعائد السنوي. «خصم فات» = فاتورة لسه مفتوحة بعد آخر موعد. للاسترشاد — المالية تقرر.',
                       'Invoices that earn a discount if paid by the deadline, ranked by annual return. «Missed discount» = an invoice still open after its deadline. Advisory — finance decides.')},
            {'key': 'ontime', 'title': T('السداد في الموعد', 'Paid on time'),
             'body': T('متوسط أيام الدفع مقابل الشروط للفواتير المسددة بالكامل عبر ربط SOFTECH في آخر سنة. موجب = متأخر. «تغطية الربط» توضح قد إيه من المدفوع مربوط بفواتير.',
                       'Average days paid against terms for invoices fully settled through SOFTECH links in the last year. Positive = late. «Link coverage» shows how much of what was paid is linked to invoices.')},
            {'key': 'residue', 'title': T('البواقي القديمة', 'Old residue'),
             'body': T('بنود مفتوحة أكتر من سنة، الموردين الفعليين منفصلين عن الحسابات الداخلية، مع المطابقة المقترحة. للقراءة: الإغلاق يتم في SOFTECH.',
                       'Items open more than a year, real suppliers apart from internal accounts, with the proposed matches. Read only: they are closed in SOFTECH.')},
        ],
        'tips': [
            T('مفيش شرط = مفيش تاريخ استحقاق. البرنامج مش بيخمّن، والمبلغ بيظهر في «بدون شروط». ابدأ بأكبر 10 موردين.',
              'No term = no due date. Nothing is guessed; the amount shows under «no terms». Start with the top 10 suppliers.'),
            T('الفاتورة اللي مالهاش سطور شراء في البرنامج بتبقى «غير مصنف» وتاخد شرط «كل الأصناف».',
              'An invoice with no purchase lines in the system is «unclassified» and takes the «all items» term.'),
            T('مفيش أي كتابة في SOFTECH. التقسيم والاستحقاق بيتحسبوا كل ليلة بعد تحديث الموردين، وبعد أي تعديل في شروط مورد.',
              'Nothing is written to SOFTECH. The split and due dates are recomputed every night after the supplier update, and after any change to a supplier\'s terms.'),
        ],
        'tour': [
            {'target': 'finance-supplier-terms-freshness', 'label': T('عمر البيانات', 'Data age'),
             'text': T('آخر تحديث لحسابات الموردين وسطور الشراء، وزر إعادة الحساب.', 'When supplier accounts and purchase lines were last updated, and the recompute button.')},
            {'target': 'finance-supplier-terms-tabs', 'label': T('الشروط · التقويم · الدفع المبكر', 'Terms · Calendar · Early pay'),
             'text': T('خمس تبويبات: الشروط، تقويم السداد، فرص الدفع المبكر، السداد في الموعد، البواقي القديمة.', 'Five tabs: terms, payment calendar, early-pay opportunities, paid on time, old residue.')},
            {'target': 'finance-supplier-terms-export', 'label': T('⬇️ تصدير Excel', '⬇️ Export Excel'),
             'text': T('ملف للتبويب المفتوح.', 'A file for the open tab.')},
        ],
        'updated': '2026-10-31',
        'change_note': T('شاشة جديدة: شروط الموردين', 'New screen: supplier terms'),
    },
    {
        'key': 'finance.cash',
        'routes': ['/finance/cash'],
        'title': T('النقدية ١٣ أسبوع', '13-week cash view'),
        'summary': T('الفلوس الداخلة والخارجة المتوقعة كل أسبوع لـ 13 أسبوع (الأسبوع يبدأ السبت) والرصيد المتوقع. الداخل: مبيعات نقدي وتوصيل وتحصيل التعاقدات. الخارج: شيكات الموردين المؤجلة، ومستحقات الموردين حسب الشروط، ومشتريات جديدة، ومصروفات ثابتة، وشيكات مخططة. للاسترشاد — المالية تقرر.',
                     'Money expected in and out each week for 13 weeks (weeks start Saturday) and the projected balance. In: cash and delivery sales and contract collections. Out: post-dated supplier cheques, supplier payables by terms, new purchases, fixed outflows and planned cheques. Advisory — finance decides.'),
        'audience': T('المالية والإدارة (الإدارة فقط — بيانات على مستوى الشركة).', 'Finance and management (management only — company-level data).'),
        'tabs': [
            {'key': 'view', 'title': T('العرض', 'View'),
             'body': T('كل بند في صف وكل أسبوع في عمود. اضغط أي رقم تشوف الفواتير أو الشيكات أو البنود اللي وراه. الرصيد بثلاث حالات: متشائم (التحصيل متأخر + المستحقات بدون شروط في أول أسبوع)، أساسي، متفائل (أعلى أسبوع مبيعات). خانة «لو اشترينا أسبوعيًا» بتجرّب ميزانية مشتريات ومش بتتحفظ.',
                       'Each line is a row and each week a column. Click any figure to see the invoices, cheques or items behind it. The balance has three cases: low (late collections + payables without terms in week 1), base, and high (best sales week). The «if we buy weekly» box tries a purchase budget and is not saved.')},
            {'key': 'inputs', 'title': T('المدخلات', 'Inputs'),
             'body': T('رصيد النقدية الافتتاحي (الخزائن والبنوك) كل أسبوع، والمصروفات الثابتة: مرتبات، إيجار، مرافق، ضرائب، قروض — أسبوعي أو شهري أو مرة واحدة. كل تعديل يتسجل باسمك.',
                       'The opening cash balance (boxes and banks) each week, and the fixed outflows: salaries, rent, utilities, taxes, loans — weekly, monthly or one-off. Every change is logged under your name.')},
        ],
        'tips': [
            T('من غير رصيد افتتاحي الشاشة بتعرض صافي كل أسبوع بس، من غير رصيد.', 'Without an opening balance the screen shows each week\'s net only, with no balance.'),
            T('شيك المورد المؤجل اللي مش مربوط بفاتورة بيتخصم من مستحقات نفس المورد (الأقدم استحقاقًا أولاً)، عشان المبلغ مايتحسبش مرتين.',
              'A post-dated supplier cheque not linked to an invoice is taken off that supplier\'s payables (earliest due first), so the amount is not counted twice.'),
            T('الحسابات الداخلية (كوبونات، شراء من مرضى، بدل) وخصم الدفع المبكر والمستحقات بدون شروط «للعلم» ومش داخلة في الرصيد الأساسي.',
              'Internal accounts (coupons, patient buy-back, replacements), early-pay discounts and payables without terms are «for information» and not in the base balance.'),
            T('مفيش أي كتابة في SOFTECH. لقطة من العرض بتتحفظ كل سبت الساعة 6 الصبح عشان نقارن التوقع بالفعلي.',
              'Nothing is written to SOFTECH. A snapshot is kept every Saturday at 6 am to compare the forecast with the actual.'),
        ],
        'tour': [
            {'target': 'finance-cash-freshness', 'label': T('عمر البيانات', 'Data age'),
             'text': T('آخر تحديث لحسابات الموردين والتعاقدات والمبيعات والمشتريات.', 'When supplier and contract accounts, sales and purchases were last updated.')},
            {'target': 'finance-cash-kpis', 'label': T('أقل رصيد متوقع', 'Lowest projected balance'),
             'text': T('أقل أسبوع في الحالة الأساسية والمتشائمة، وعدد الأسابيع تحت الصفر، وتغطية المدخلات.', 'The lowest week in the base and low cases, weeks below zero, and input coverage.')},
            {'target': 'finance-cash-table', 'label': T('البنود × الأسابيع', 'Lines × weeks'),
             'text': T('اضغط أي رقم تشوف اللي وراه في اللوحة الجانبية.', 'Click any figure to see what is behind it in the side panel.'),
             'when': T('الرصيد بالبرتقالي = تحت الصفر.', 'An orange balance = below zero.')},
            {'target': 'finance-cash-export', 'label': T('⬇️ تصدير Excel', '⬇️ Export Excel'),
             'text': T('ملف بالبنود والأسابيع والرصيد.', 'A file with the lines, weeks and balance.')},
        ],
        'updated': '2026-10-31',
        'change_note': T('شاشة جديدة: النقدية ١٣ أسبوع (بدل صفحة التدفق النقدي)', 'New screen: 13-week cash view (replaces the cash-flow page)'),
    },
    {
        'key': 'finance.coa',
        'routes': ['/finance/coa'],
        'title': T('دليل الحسابات', 'Chart of accounts'),
        'summary': T('الحسابات المحاسبية من SOFTECH كقائمة أو شجرة: الكود، الاسم، النوع (أصول، التزامات، حقوق ملكية، إيرادات، مصروفات، تكلفة مبيعات)، الطبيعة (مدين/دائن) والمستوى.',
                     'The SOFTECH accounts as a list or tree: code, name, type (assets, liabilities, equity, revenue, expenses, cost of sales), nature (debit/credit) and level.'),
        'audience': T('المالية.', 'Finance.'),
        'tour': [
            {'target': 'finance-coa-view',
             'label': T('قائمة · شجرة', 'List · Tree'),
             'text': T('«قائمة» جدول مسطح قابل للبحث، و«شجرة» الهيكل الأب والأبناء.', '"List" is a flat searchable table; "Tree" is the parent/child structure.'),
             'more': T('• «قائمة»: جدول مسطح فيه بحث وفلتر.\n'
                       '• «شجرة»: الحسابات تحت بعض حسب المستوى.\n'
                       'الدليل للقراءة بس — التعديل بيتم في SOFTECH نفسه.',
                       '• "List": a flat table with search and filter.\n'
                       '• "Tree": accounts nested by level.\n'
                       'The chart is read-only — changes are made in SOFTECH itself.'),
         },
            {'target': 'finance-coa-search',
             'label': T('بحث بالاسم أو الكود', 'Search by name or code'),
             'text': T('اكتب جزءاً من اسم الحساب أو كوده.', 'Type part of the account name or code.'),
             'open_hint': T('في عرض «قائمة».', 'In the "List" view.'),
             'more': T('اكتب جزء من اسم الحساب أو كوده والقائمة بتتفلتر.\n'
                       '• مفيد لما تشوف كود حساب في قيد وعايز تعرف اسمه.',
                       'Type part of the account name or code and the list filters.\n'
                       '• Handy when you see an account code in an entry and want its name.'),
         },
            {'target': 'finance-coa-type',
             'label': T('جميع الأنواع', 'All types'),
             'text': T('أصول، التزامات، حقوق ملكية، إيرادات، مصروفات، تكلفة مبيعات.', 'Assets, liabilities, equity, revenue, expenses, cost of sales.'),
             'open_hint': T('في عرض «قائمة».', 'In the "List" view.'),
             'more': T('بيقصر القائمة على نوع واحد، مثلاً «مصروفات» عشان تشوف كل حسابات المصروف.\n'
                       '• اختار «الكل» عشان ترجع القائمة كاملة.',
                       'It narrows the list to one type, for example "Expenses" to see every expense account.\n'
                       '• Choose "All" to get the full list back.'),
         },
            {'target': 'finance-coa-table',
             'label': T('جدول الحسابات', 'Accounts table'),
             'text': T('الكود والاسم والنوع والطبيعة (مدين/دائن) والمستوى. «ورقة ✓» = حساب بلا أبناء.', 'Code, name, type, nature (debit/credit) and level. "Leaf ✓" = an account with no children.'),
             'when': T('للعرض فقط — التعديل يتم في SOFTECH.', 'View only — changes are made in SOFTECH.'),
             'more': T('«ورقة» يعني حساب نهائي بتتسجل عليه القيود، وغير كده حساب تجميعي.\n'
                       '• «الطبيعة» بتقولك الرصيد الطبيعي للحساب مدين ولا دائن.',
                       '"Leaf" means a final account that entries are posted to; otherwise it is a grouping account.\n'
                       '• "Nature" tells you whether the account normal balance is debit or credit.'),
         },
            {'target': 'finance-coa-tree',
             'label': T('الشجرة', 'Tree'),
             'text': T('اضغط حساباً أباً لفتح أو طي حساباته الفرعية.', 'Click a parent account to open or fold its sub-accounts.'),
             'open_hint': T('اضغط «شجرة».', 'Press "Tree".'),
             'more': T('أول مستويين مفتوحين؛ اضغط أي حساب ليه فروع عشان تفتحه أو تقفله.\n'
                       '• بيوضح كل حساب تابع لأنهي مجموعة.',
                       'The first two levels are open; click any account with children to open or close it.\n'
                       '• It shows which group each account belongs to.'),
         },
        ],
        'updated': '2026-10-30',
    
        'change_note': _NOTE,
    },
    {
        'key': 'finance.schema',
        'routes': ['/finance/schema'],
        'title': T('اكتشاف المخطط المالي', 'Finance schema discovery'),
        'summary': T('للمدير: فحص جداول SOFTECH ذات الصلة المالية، تأكيد الغرض من كل جدول، وتفعيله للمزامنة. هذه خطوة إعداد قبل أن تعمل باقي الشاشات المالية.',
                     'For admins: scan SOFTECH tables with a financial purpose, confirm each table\'s purpose and enable it for syncing. A setup step before the other finance screens work.'),
        'audience': T('المدير فقط.', 'Admins only.'),
        'tour': [
            {'target': 'finance-schema-filters',
             'label': T('بحث باسم الجدول…', 'Search by table name…'),
             'when': T('لما تدور على جدول معيّن أو فئة جداول.', 'When looking for a specific table or table category.'),
             'text': T('بحث باسم الجدول، وفلتر الفئة وحالة التأكيد.',
                                              'Search by table name, and filter by category and confirmation status.'),
             'more': T('استخدم «غير مؤكد» عشان تلاقي الجداول اللي لسه محتاجة مراجعة.\n'
                       '• الفئة هي التصنيف اللي الاكتشاف استنتجه (خزينة، مصروفات…).',
                       'Use "Unconfirmed" to find the tables that still need review.\n'
                       '• The category is the classification the discovery inferred (treasury, expenses…).')},
            {'target': 'finance-schema-discover',
             'label': T('🔍 تشغيل الاكتشاف', '🔍 Run discovery'),
             'text': T('يفحص جداول SOFTECH في الخلفية (قراءة فقط) ويحدّث القائمة هنا.', 'Scans SOFTECH tables in the background (read only) and updates the list here.'),
             'when': T('خذ 2–3 دقائق ثم أعد تحميل الصفحة.', 'Allow 2–3 minutes, then reload the page.'),
             'warn': T('يقرأ كل جداول SOFTECH — شغّله مرة وانتظر النتيجة.', 'It reads every SOFTECH table — run it once and wait for the result.'),
             'more': T('الفحص بيقرا هيكل جداول SOFTECH بس ومبيكتبش فيها، وبيشتغل في الخلفية فممكن ياخد وقت.\n'
                       '• بعد ما يخلص الجداول بتظهر في القائمة.\n'
                       '• الشاشة دي للمدير بس.',
                       'The scan only reads the structure of SOFTECH tables and does not write to them; it runs in the background so it may take a while.\n'
                       '• When it finishes, the tables show in the list.\n'
                       '• This screen is for the admin only.'),
         },
            {'target': 'finance-schema-search',
             'label': T('بحث باسم الجدول', 'Search by table name'),
             'text': T('اكتب جزءاً من اسم الجدول.', 'Type part of the table name.')},
            {'target': 'finance-schema-category',
             'label': T('كل الفئات', 'All categories'),
             'text': T('يومية، حسابات، خزينة، بنك، مصروفات، رواتب…', 'Journal, accounts, cash, bank, expenses, payroll…')},
            {'target': 'finance-schema-confirmed-filter',
             'label': T('الكل · مؤكد · غير مؤكد', 'All · Confirmed · Unconfirmed'),
             'text': T('اعرض الجداول التي راجعتها أو التي لم تراجعها بعد.', 'Show the tables you have reviewed, or not yet.')},
            {'target': 'finance-schema-stats',
             'label': T('إجمالي · مؤكد · مفعّل للمزامنة', 'Total · Confirmed · Sync enabled'),
             'text': T('عدد الجداول المكتشفة وما تم تأكيده وما يُزامن.', 'How many tables were found, confirmed and synced.'),
             'more': T('هدفك إن كل جدول مالي مهم يبقى مؤكد ومفعّل.\n'
                       '• لو المفعّل صفر، شاشات المالية التانية هتفضل فاضية.',
                       'Your goal is that every important financial table is confirmed and enabled.\n'
                       '• If enabled is zero, the other finance screens stay empty.'),
         },
            {'target': 'finance-schema-row',
             'label': T('صف الجدول', 'Table row'),
             'text': T('اضغطه لترى الغرض المستنتج وأعمدة الجدول.', 'Click it to see the inferred purpose and the table columns.'),
             'more': T('اقرا الغرض المستنتج والأعمدة قبل ما تأكد — الاستنتاج آلي وممكن يغلط.\n'
                       '• الصف بيتلوّن أخضر بعد التأكيد.',
                       'Read the inferred purpose and columns before confirming — the inference is automatic and can be wrong.\n'
                       '• The row turns green after confirmation.'),
         },
            {'target': 'finance-schema-confirm',
             'label': T('تأكيد · ✓ مؤكد', 'Confirm · ✓ Confirmed'),
             'text': T('يسجّل أنك راجعت غرض الجدول. اضغط تاني للإلغاء.', 'Records that you checked the table\'s purpose. Click again to undo.'),
             'more': T('الضغط بيبدّل الحالة: «تأكيد» يعني إنك راجعت وموافق على الغرض، والضغط على «✓ مؤكد» بيلغيه.\n'
                       '• التأكيد بيتسجل في نظامنا بس، مش في SOFTECH.',
                       'Pressing toggles the state: "Confirm" means you reviewed and agree with the purpose, and pressing "✓ Confirmed" clears it.\n'
                       '• Confirmation is stored in our system only, not in SOFTECH.'),
         },
            {'target': 'finance-schema-sync-toggle',
             'label': T('تفعيل · ⟲ مزامنة', 'Enable · ⟲ Sync'),
             'text': T('يضيف الجدول للمزامنة المالية أو يوقفه.', 'Adds the table to the finance sync, or stops it.'),
             'warn': T('إيقاف جدول مستخدم يوقف تحديث أرقامه في الشاشات المالية.', 'Disabling a table in use stops its figures updating in the finance screens.'),
             'more': T('المفعّل بس هو اللي المزامنة المالية بتقرا بياناته وتحسب منها لوحة القيادة والقوائم.\n'
                       '• المزامنة قراءة من SOFTECH بس.\n'
                       '• فعّل الجدول بعد ما تأكد غرضه.',
                       'Only enabled tables are read by the finance sync to compute the dashboard and statements.\n'
                       '• Syncing only reads from SOFTECH.\n'
                       '• Enable a table after confirming its purpose.'),
         },
        ],
        'updated': '2026-10-30',
    
        'change_note': _NOTE,
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
            {'target': 'finance-cheques-status-tabs', 'text': T('فلتر الحالة: الكل، مسودة، نشطة، مكتملة.',
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
            T('الشيكات اللي لسه «لم يُصدَر» في خطة نشطة بتظهر في «النقدية ١٣ أسبوع» في أسبوع استحقاقها؛ الصادر منها بيظهر من SOFTECH.',
              'Cheques still «not issued» in an active plan show in the «13-week cash view» in their due week; issued ones come from SOFTECH.'),
            T('كل إجراء بيتحقق من صلاحيتك على السيرفر (مصفوفة الصلاحيات، موديول الشيكات): التفعيل والإلغاء يحتاجوا «اعتماد»، وتسجيل شيك «تمّ الصرف» أو «ارتدّ» يحتاج «إنهاء».',
              'Every action is checked on the server (Permissions Matrix, cheques module): activating and cancelling need "approve", and marking a cheque "cleared" or "bounced" needs "finalize".'),
            T('الشيك «تمّ الصرف» أو «ملغي» نهائي، وشيكات الخطة لا تتعدل إلا والخطة «نشطة».',
              'A "cleared" or "cancelled" cheque is final, and the cheques of a plan change only while it is "active".'),
        ],
        'tour': [
            {'target': 'finance-cheques-treasury',
             'label': T('مؤشرات الخزينة', 'Treasury KPIs'),
             'text': T('الخطط النشطة، إجمالي المتبقي، شيكات الـ 30 يوماً القادمة، والمتأخرة.', 'Active plans, total outstanding, cheques due in 30 days, and overdue ones.'),
             'when': T('النقطة الحمراء النابضة = شيكات متأخرة تحتاج متابعة.', 'A pulsing red dot = overdue cheques to follow up.')},
            {'target': 'finance-cheques-new',
             'label': T('+ خطة جديدة', '+ New plan'),
             'text': T('يفتح نموذج خطة شيكات جديدة.', 'Opens a new cheque-plan form.')},
            {'target': 'finance-cheques-search',
             'label': T('بحث بالاسم أو المستفيد', 'Search by name or payee'),
             'text': T('اكتب جزءاً من عنوان الخطة أو اسم المستفيد.', 'Type part of the plan title or payee name.')},
            {'target': 'finance-cheques-status-tabs',
             'label': T('الكل · مسودة · نشطة · مكتملة', 'All · Draft · Active · Completed'),
             'text': T('صفِّ الخطط بحالتها.', 'Filter plans by status.')},
            {'target': 'finance-cheques-plan',
             'label': T('بطاقة الخطة', 'Plan card'),
             'text': T('العنوان والمستفيد والإجمالي وعدد الشيكات وتاريخ الشيك التالي. اضغط لفتح التفاصيل.',
                       'Title, payee, total, number of cheques and the next due date. Click to open the details.')},
            {'target': 'finance-cheques-preview',
             'label': T('📅 معاينة جدول الشيكات', '📅 Preview cheque schedule'),
             'text': T('يحسب التواريخ والمبالغ ويرحّل التواريخ الواقعة في إجازة. لا يحفظ شيئاً.', 'Works out dates and amounts and moves holiday dates. Saves nothing.'),
             'when': T('⚠️ بجانب التاريخ = اتعدّل تلقائياً.', 'A ⚠️ beside a date = it was moved automatically.'),
             'open_hint': T('اضغط «+ خطة جديدة» واملأ الإجمالي والعدد وتاريخ الأول.', 'Press "+ New plan" and fill the total, count and first date.')},
            {'target': 'finance-cheques-create',
             'label': T('إنشاء الخطة', 'Create plan'),
             'text': T('يحفظ الخطة «مسودة» بشيكاتها.', 'Saves the plan as a "draft" with its cheques.'),
             'when': T('المسودة تتعدّل أو تُلغى قبل التفعيل.', 'A draft can be changed or cancelled before activation.'),
             'open_hint': T('داخل نموذج الخطة الجديدة.', 'Inside the new-plan form.')},
            {'target': 'finance-cheques-activate',
             'label': T('✅ تفعيل الخطة', '✅ Activate plan'),
             'text': T('يجعل الخطة «نشطة» فتدخل مؤشرات الخزينة وتُفتح شيكاتها للتحديث.', 'Makes the plan "active": it enters the treasury KPIs and its cheques open for updates.'),
             'when': T('يحتاج صلاحية «اعتماد».', 'Needs "approve" permission.'),
             'open_hint': T('افتح خطة «مسودة».', 'Open a "draft" plan.')},
            {'target': 'finance-cheques-cancel-plan',
             'label': T('إلغاء', 'Cancel'),
             'text': T('يلغي الخطة بعد سؤال تأكيد.', 'Cancels the plan after a confirm question.'),
             'warn': T('لا رجوع بعد الإلغاء. مرفوض لو فيه شيك «تمّ الصرف».', 'No way back after cancelling. Refused if any cheque is "cleared".'),
             'open_hint': T('افتح خطة «مسودة» أو «نشطة».', 'Open a "draft" or "active" plan.')},
            {'target': 'finance-cheques-plan-kpis',
             'label': T('ملخص الخطة', 'Plan summary'),
             'text': T('الإجمالي، ما تمّ صرفه، الشيكات المتبقية، ونسبة الإنجاز.', 'Total, cleared so far, cheques remaining and progress.'),
             'open_hint': T('افتح أي خطة.', 'Open any plan.')},
            {'target': 'finance-cheques-schedule',
             'label': T('جدول الشيكات', 'Cheque schedule'),
             'text': T('كل شيك بتاريخه ومبلغه ورقمه وحالته. الأحمر = متأخر، الأصفر = مستحق اليوم.', 'Each cheque with date, amount, number and status. Red = overdue, yellow = due today.'),
             'open_hint': T('افتح أي خطة.', 'Open any plan.')},
            {'target': 'finance-cheques-edit-cheque',
             'label': T('تعديل', 'Edit'),
             'text': T('يفتح رقم الشيك وحالته وملاحظاته للتعديل.', 'Opens the cheque number, status and notes for editing.'),
             'open_hint': T('في خطة «نشطة»، بجانب شيك غير مصروف ولا ملغي.', 'In an "active" plan, beside a cheque not cleared or cancelled.')},
            {'target': 'finance-cheques-save-cheque',
             'label': T('حفظ', 'Save'),
             'text': T('يحفظ الشيك. لما تُصرف كل الشيكات تصبح الخطة «مكتملة».', 'Saves the cheque. When all cheques clear the plan becomes "completed".'),
             'warn': T('«تمّ الصرف» نهائي، ويحتاج هو و«ارتدّ» صلاحية «إنهاء».', '"Cleared" is final; it and "bounced" need "finalize" permission.'),
             'open_hint': T('اضغط «تعديل» على شيك.', 'Press "Edit" on a cheque.')},
        ],
        'updated': '2026-10-31',
        'change_note': T('الشيكات المخططة بتظهر في النقدية ١٣ أسبوع', 'Planned cheques now show in the 13-week cash view'),
    },
    {
        'key': 'finance.payments',
        'routes': ['/payments'],
        'title': T('تتبع المدفوعات', 'Payment tracking'),
        'summary': T('تسجيل ومطابقة المدفوعات الخارجية (كاش، انستاباي، فودافون كاش، تحويل بنكي): المبلغ، الفاتورة، العميل، رقم العملية، الفرع، وصورة الإيصال، ثم تأكيدها أو الاعتراض عليها.',
                     'Record and reconcile external payments (cash, Instapay, Vodafone Cash, bank transfer): amount, invoice, customer, transaction number, branch and a receipt photo, then confirm or dispute them.'),
        'audience': T('المالية (المشتريات والمدير)؛ الصيدلي للعرض فقط.', 'Finance (purchasing and admins); pharmacists can only view.'),
        'steps': [
            T('«تسجيل دفعة»: طريقة الدفع والمبلغ وإجمالي الفاتورة (أو «دفعة جزئية» مع المتبقي)، كود فاتورة SOFTECH، رقم المرجع، الفرع والتاريخ، وصورة الإيصال.', '"Record payment": method, amount and invoice total (or "partial" with the remaining), SOFTECH invoice code, reference number, branch and date, and the receipt photo.'),
            T('المالية: «تأكيد» بعد التحقق، أو «اعتراض» بسبب.', 'Finance: "Confirm" after checking, or "Dispute" with a reason.'),
        ],
        'tips': [
            T('الصفحة دي مخفية من القائمة لحد ما المالية تحتاجها — الرابط لسه شغال.', 'This page is hidden from the menu until finance needs it — the link still works.'),
            T('تعديل الدفعة مسموح وهي «انتظار» أو «متنازع عليه» فقط؛ بعد التأكيد أو التسوية تُقفل، والحذف للدفعة المنتظرة فقط.',
              'A payment can be edited only while "pending" or "disputed"; once confirmed or reconciled it is closed, and only a pending payment can be deleted.'),
        ],
        'related': ['finance.payment_audit'],
        'tour': [
            {'target': 'finance-payments-new',
             'label': T('+ تسجيل دفعة', '+ Record payment'),
             'text': T('يفتح نموذج دفعة خارجية جديدة.', 'Opens a new external-payment form.'),
             'more': T('استخدمه لما عميل يدفع انستاباي أو فودافون كاش أو تحويل بنكي أو كاش خارج الكاشير.\n'
                       '• النموذج فيه طريقة الدفع والمبلغ وإجمالي الفاتورة وكود فاتورة SOFTECH ورقم المرجع والفرع وصورة الإيصال؛ لو «دفعة جزئية» بتسجّل المتبقي زي ما هو.\n'
                       '• الدفعة بتتسجل «في الانتظار» ومبتكتبش حاجة في SOFTECH.',
                       'Use it when a customer pays by Instapay, Vodafone Cash, bank transfer or cash outside the till.\n'
                       '• The form has the method, amount, invoice total, SOFTECH invoice code, reference number, branch and receipt photo; for a "Partial payment" you record the remaining as stated.\n'
                       '• The payment is saved as "Pending" and writes nothing to SOFTECH.'),
         },
            {'target': 'finance-payments-new-method',
             'label': T('طريقة الدفع', 'Payment method'),
             'text': T('كاش، انستاباي، فودافون كاش، تحويل بنكي…', 'Cash, Instapay, Vodafone Cash, bank transfer…'),
             'when': T('غير الكاش يطلب رقم المرجع ويقبل صورة الإيصال.', 'Non-cash asks for the reference number and accepts a receipt photo.'),
             'open_hint': T('اضغط «+ تسجيل دفعة».', 'Press "+ Record payment".')},
            {'target': 'finance-payments-new-partial',
             'label': T('دفعة جزئية', 'Partial payment'),
             'text': T('فعّله لو العميل دفع جزءاً، واكتب المتبقي.', 'Turn it on if the customer paid part, and type the remaining.'),
             'open_hint': T('داخل نموذج الدفعة.', 'Inside the payment form.')},
            {'target': 'finance-payments-new-receipt',
             'label': T('📎 اختر صورة', '📎 Choose image'),
             'text': T('أرفق لقطة شاشة التحويل أو صورة الإيصال.', 'Attach the transfer screenshot or receipt photo.'),
             'open_hint': T('داخل النموذج، لطرق الدفع غير الكاش.', 'Inside the form, for non-cash methods.')},
            {'target': 'finance-payments-new-save',
             'label': T('تسجيل الدفعة', 'Record payment'),
             'text': T('يحفظ الدفعة «في الانتظار». يلزم المبلغ والفرع.', 'Saves the payment as "pending". Amount and branch are required.'),
             'when': T('لا يُكتب شيء في SOFTECH.', 'Nothing is written to SOFTECH.'),
             'open_hint': T('داخل نموذج الدفعة.', 'Inside the payment form.')},
            {'target': 'finance-payments-summary',
             'label': T('ملخص اليوم', "Today's summary"),
             'text': T('إجمالي اليوم وتوزيعه بطريقة الدفع، وأعداد المنتظر والمؤكد.', "Today's total and its split by method, with pending and confirmed counts."),
             'when': T('يتحدّث كل 30 ثانية.', 'Updates every 30 seconds.'),
             'more': T('كلها محسوبة في السيرفر من الدفعات المسجلة.\n'
                       '• «في الانتظار» = دفعات لسه محتاجة تأكيد.\n'
                       '• «مؤكد اليوم» = اللي اتأكد انهارده.',
                       'All computed on the server from the recorded payments.\n'
                       '• "Pending" = payments still awaiting confirmation.\n'
                       '• "Confirmed today" = those confirmed today.'),
         },
            {'target': 'finance-payments-filters',
             'label': T('الفلاتر', 'Filters'),
             'text': T('من/إلى، طريقة الدفع، الحالة، والفرع.', 'From/to, method, status and branch.'),
             'when': T('الافتراضي آخر 7 أيام.', 'The default is the last 7 days.'),
             'more': T('الفترة الافتراضية آخر 7 أيام.\n'
                       '• الحالات: في الانتظار، مؤكد، تمت المطابقة، متنازع، ملغي.\n'
                       '• البحث برقم المرجع أسرع طريقة تلاقي بيها تحويل معيّن.',
                       'The default period is the last 7 days.\n'
                       '• Statuses: pending, confirmed, reconciled, disputed, cancelled.\n'
                       '• Searching by reference number is the fastest way to find a specific transfer.'),
         },
            {'target': 'finance-payments-search',
             'label': T('بحث', 'Search'),
             'text': T('بالاسم أو الهاتف أو رقم المرجع.', 'By name, phone or reference number.')},
            {'target': 'finance-payments-time-filters',
             'label': T('🕐 وقت', '🕐 Time'),
             'text': T('اختصارات (اليوم، أمس، 7 و30 يوماً)، يوم بعينه، الساعة، وأيام الأسبوع.', 'Shortcuts (today, yesterday, 7 and 30 days), one day, hour, and weekdays.'),
             'when': T('مفيد لكشف دفعات في ساعات أو أيام غريبة.', 'Useful to spot payments at odd hours or days.'),
             'more': T('مفيد لما تراجع وردية معيّنة أو تدوّر على دفعة اتعملت في ساعة معروفة.\n'
                       '• اضغطه تاني عشان تقفل الفلاتر الإضافية.',
                       'Useful when reviewing a specific shift or looking for a payment made at a known hour.\n'
                       '• Press it again to close the extra filters.'),
         },
            {'target': 'finance-payments-refresh',
             'label': T('تحديث', 'Refresh'),
             'text': T('يعيد تحميل القائمة والملخص.', 'Reloads the list and the summary.')},
            {'target': 'finance-payments-list',
             'label': T('قائمة الدفعات', 'Payments list'),
             'text': T('المبلغ والطريقة والحالة والعميل والفاتورة والمرجع والفرع، و«📷 إيصال» لو مرفق.', 'Amount, method, status, customer, invoice, reference, branch, and "📷 Receipt" if attached.'),
             'more': T('كل كارت فيه العميل وتليفونه وكود الفاتورة والمرجع والفرع والتاريخ، والمتبقي لو الدفعة جزئية.\n'
                       '• «📷 إيصال» بيفتح صورة الإيصال لو موجودة.',
                       'Each card shows the customer and phone, invoice code, reference, branch and date, and the remaining if the payment is partial.\n'
                       '• "📷 Receipt" opens the receipt photo when there is one.'),
         },
            {'target': 'finance-payments-actions',
             'label': T('تأكيد ✓ / اعتراض', 'Confirm ✓ / Dispute'),
             'when': T('للدفعات المنتظرة بعد مراجعة بياناتها.', 'For pending payments, after checking their details.'),
             'text': T('للدفعات المنتظرة: «تأكيد ✓» أو «اعتراض» — التأكيد للمدير والمشتريات فقط.',
                                              'For pending payments: «تأكيد ✓» (Confirm) or «اعتراض» (Dispute) — confirming is for admin and purchasing only.'),
             'more': T('• «تأكيد ✓» بعد ما تتأكد إن الفلوس وصلت فعلاً؛ بيتسجل اسمك والوقت.\n'
                       '• «اعتراض» بيطلب سبب وبيحوّل الدفعة «متنازع».\n'
                       'السيرفر بيرفض التأكيد من أي حد غير المدير والمشتريات؛ الصيدلي بيشوف بس.',
                       '• "Confirm ✓" once you are sure the money really arrived; your name and the time are recorded.\n'
                       '• "Dispute" asks for a reason and turns the payment "Disputed".\n'
                       'The server refuses confirmation from anyone but admin and purchasing; pharmacists can only view.')},
            {'target': 'finance-payments-confirm',
             'label': T('تأكيد ✓', 'Confirm ✓'),
             'text': T('يؤكد أن الدفعة وصلت فعلاً ويسجّل اسمك.', 'Confirms the payment really arrived and records your name.'),
             'warn': T('أكّد بعد التحقق من الحساب فقط — بعده لا تعديل ولا حذف.', 'Confirm only after checking the account — no edit or delete afterwards.'),
             'open_hint': T('على الدفعات «في الانتظار». يحتاج صلاحية «اعتماد».', 'On "pending" payments. Needs "approve" permission.')},
            {'target': 'finance-payments-dispute',
             'label': T('اعتراض', 'Dispute'),
             'text': T('يفتح نافذة لكتابة سبب الاعتراض.', 'Opens a box to write the dispute reason.'),
             'open_hint': T('على الدفعات «في الانتظار».', 'On "pending" payments.')},
            {'target': 'finance-payments-dispute-confirm',
             'label': T('تأكيد الاعتراض', 'Confirm dispute'),
             'text': T('يحوّل الدفعة إلى «متنازع عليه» ويسجّل السبب.', 'Moves the payment to "disputed" and records the reason.'),
             'when': T('الدفعة المتنازع عليها تبقى قابلة للتعديل حتى تُحل.', 'A disputed payment stays editable until it is sorted out.'),
             'open_hint': T('اضغط «اعتراض» على دفعة.', 'Press "Dispute" on a payment.')},
        ],
        'updated': '2026-10-30',
    
        'change_note': T('مخفية من القائمة', 'Hidden from the menu'),
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
            {'target': 'finance-payment-audit-run-matching', 'text': T('«تشغيل المطابقة» يظهر للكشوف المعلقة ليطابق سطورها بالمدفوعات المسجلة.',
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
        'tour': [
            {'target': 'finance-payment-audit-upload',
             'label': T('+ رفع كشف حساب', '+ Upload statement'),
             'text': T('يفتح نافذة رفع كشف الحساب البنكي.', 'Opens the bank statement upload box.')},
            {'target': 'finance-payment-audit-upload-file',
             'label': T('الملف (CSV / Excel)', 'File (CSV / Excel)'),
             'text': T('اختر ملف الكشف، واكتب المرجع البنكي لو موجود.', 'Pick the statement file, and type the bank reference if you have one.'),
             'open_hint': T('اضغط «+ رفع كشف حساب».', 'Press "+ Upload statement".')},
            {'target': 'finance-payment-audit-upload-save',
             'label': T('رفع', 'Upload'),
             'text': T('يحفظ الكشف بحالة pending في تبويب «🏦 الكشوف البنكية».', 'Saves the statement as pending in the "🏦 Bank statements" tab.'),
             'when': T('المطابقة لا تبدأ وحدها — شغّلها من التبويب.', 'Matching does not start by itself — run it from the tab.'),
             'open_hint': T('داخل نافذة الرفع، بعد اختيار الملف.', 'Inside the upload box, after picking the file.')},
            {'target': 'finance-payment-audit-tabs',
             'label': T('⚠️ الاستثناءات · 🏦 الكشوف البنكية', '⚠️ Exceptions · 🏦 Bank statements'),
             'text': T('الرقم الأحمر = عدد الاستثناءات المفتوحة.', 'The red number = open exceptions.')},
            {'target': 'finance-payment-audit-statements',
             'label': T('الكشوف البنكية', 'Bank statements'),
             'text': T('كل كشف بعدد السطور والمطابق ونسبة المطابقة وحالته.', 'Each statement with line count, matched lines, match rate and status.'),
             'open_hint': T('تبويب «🏦 الكشوف البنكية».', 'The "🏦 Bank statements" tab.')},
            {'target': 'finance-payment-audit-run-matching',
             'label': T('تشغيل المطابقة', 'Run matching'),
             'text': T('يطابق سطور الكشف بالدفعات المسجّلة ويحسب النسبة.', 'Matches statement lines to recorded payments and computes the rate.'),
             'when': T('بعد الرفع مباشرة. لا يكتب في SOFTECH.', 'Right after uploading. It does not write to SOFTECH.'),
             'open_hint': T('على كشف بحالة pending في تبويب الكشوف.', 'On a pending statement in the statements tab.')},
            {'target': 'finance-payment-audit-exceptions',
             'label': T('الاستثناءات المفتوحة', 'Open exceptions'),
             'text': T('النوع والمبلغ والمرجع والتاريخ لكل حركة تحتاج قراراً.', 'Type, amount, reference and date of each line needing a decision.'),
             'when': T('ابدأ بـ «🚨 مؤشر إساءة» و«مكرر».', 'Start with "🚨 Abuse signal" and "Duplicate".'),
             'open_hint': T('تبويب «⚠️ الاستثناءات» — يظهر لو فيه مفتوح.', 'The "⚠️ Exceptions" tab — shown when any are open.')},
            {'target': 'finance-payment-audit-handle',
             'label': T('معالجة', 'Handle'),
             'text': T('يفتح نافذة القرار للاستثناء.', 'Opens the decision box for the exception.'),
             'open_hint': T('على استثناء مفتوح.', 'On an open exception.')},
            {'target': 'finance-payment-audit-note',
             'label': T('ملاحظة التسوية', 'Settlement note'),
             'text': T('اكتب ما وجدته وما فعلته.', 'Write what you found and what you did.'),
             'open_hint': T('داخل نافذة «معالجة».', 'Inside the "Handle" box.')},
            {'target': 'finance-payment-audit-resolve',
             'label': T('حل الاستثناء', 'Resolve'),
             'text': T('يغلق الاستثناء «تم الحل» باسمك.', 'Closes the exception as "resolved" under your name.'),
             'warn': T('نهائي — لا يُعاد فتحه من الشاشة.', 'Final — it cannot be reopened from the screen.'),
             'open_hint': T('داخل نافذة «معالجة». يحتاج صلاحية «اعتماد».', 'Inside the "Handle" box. Needs "approve" permission.')},
            {'target': 'finance-payment-audit-dismiss',
             'label': T('تجاهل', 'Ignore'),
             'text': T('يغلق الاستثناء «متجاهل» بلا حل.', 'Closes the exception as "dismissed" without a fix.'),
             'warn': T('لا تتجاهل مؤشر إساءة أو تبايناً في المبلغ بلا تحقق.', 'Never ignore an abuse signal or amount mismatch unchecked.'),
             'open_hint': T('داخل نافذة «معالجة». يحتاج صلاحية «اعتماد».', 'Inside the "Handle" box. Needs "approve" permission.')},
        ],
        'updated': '2026-10-30',
    
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
    },
    {
        'key': 'finance.reconciliation',
        'routes': ['/reconciliation'],
        'title': T('سداد فواتير الموردين (المطابقة)', 'Supplier invoice payments (reconciliation)'),
        'summary': T('ربط سندات الصرف للموردين بالفواتير التي تسددها: النظام يقترح الربط بدرجة ثقة، والمسؤول يعتمد أو يرفض. الاعتماد يُكتب في المرآة لدينا فقط؛ الكتابة في SOFTECH خطوة منفصلة («🖊 كتابة في SOFTECH») للمدير فقط وتعمل فقط حين يُفعَّل مفتاح الكتابة. «المتبقي» حقل محسوب (قيمة الفاتورة − المسدد في SOFTECH − المعتمد بانتظار الكتابة).',
                     'Link supplier payment vouchers to the invoices they pay: the system proposes links with a confidence level, and the responsible person approves or rejects. Approval is written only to our mirror; writing to SOFTECH is a separate admin-only step ("🖊 Write to SOFTECH") that works only when the write switch is on. "Remaining" is computed (invoice value − paid in SOFTECH − approved awaiting write).'),
        'audience': T('المالية والمشتريات (الإدارة فقط — تسوية الموردين بيانات على مستوى الشركة).', 'Finance and purchasing (management only — supplier reconciliation is company-level data).'),
        'tabs': [
            {'key': 'candidates', 'title': T('المقترحات', 'Proposals'), 'body': T('مقترحات الربط (ثقة عالية/متوسطة/منخفضة/تعارض) مع الفاتورة وتاريخها وقيمتها والسند ومبلغه والمتبقي. افتح الصف لترى أصناف الفاتورة والمرتجعات المرتبطة، ثم اعتمد أو ارفض.', 'Link proposals (high/medium/low confidence/conflict) with the invoice, date, value, voucher, amount and remaining. Open a row to see the invoice items and linked returns, then approve or reject.')},
            {'key': 'exceptions', 'title': T('الاستثناءات', 'Exceptions'), 'body': T('حالات تحتاج مراجعة: سند مكرر محتمل، سند يسمي فاتورة أخرى، مقبوضات تحتاج تحديد (استرداد أم خصم)، وغيرها.', 'Cases needing review: possible duplicate voucher, voucher naming another invoice, receipts needing a decision (refund or deduction), and others.')},
            {'key': 'unpaid', 'title': T('غير المسددة (للمالية)', 'Unpaid (for finance)'), 'body': T('الفواتير التي ما زال عليها رصيد بعد الربط — قائمة عمل للمالية.', 'Invoices still with a balance after linking — a worklist for finance.')},
            {'key': 'parties', 'title': T('الحصر', 'Parties & ledger'), 'body': T('الموردون وحساباتهم: الفواتير، السندات، السندات بلا ربط، وكشف الحساب.', 'Suppliers and their accounts: invoices, vouchers, unlinked vouchers and the ledger.')},
        ],
        'related': ['invoices.main', 'replacement.cases'],
        'tips': [
            T('جانب العملاء (التعاقدات) بيتقرا لحسابات التعاقد المتابَعة بس، ومقترحات الربط مش بتشتغل له — المستحقات في «المالية» ← «مستحقات التعاقدات».',
              'The customer (contract) side is read for the tracked contract accounts only, and link proposals are not run for it — receivables are in «Finance» → «Contract receivables».'),
            T('الشريط فوق بيقول آخر تشغيل للتسوية إمتى (بيشتغل كل يوم الصبح بعد سحب السداد من SOFTECH). لو أصفر يبقى المقترحات ممكن تكون قديمة.', 'The bar at the top says when reconciliation last ran (every morning after the payments are pulled from SOFTECH). Amber means the proposals may be out of date.'),
            T('«🖊 كتابة في SOFTECH» خطوة منفصلة بعد الاعتماد، للمدير فقط. وهي معطّلة بإعداد في السيرفر: تعرض «تشغيل تجريبي» ولا تكتب شيئاً.',
              '"🖊 Write to SOFTECH" is a separate step after approval, admins only. While a server setting keeps it off it shows a "dry run" and writes nothing.'),
        ],
        'tour': [
            {'target': 'finance-reconciliation-freshness', 'label': T('آخر تشغيل للتسوية', 'Last reconciliation run'),
             'text': T('إمتى اتحسبت المقترحات آخر مرة.', 'When the proposals were last computed.')},
            {'target': 'finance-reconciliation-party-type',
             'label': T('موردون · عملاء', 'Suppliers · Customers'),
             'text': T('اختر نوع الطرف: سداد فواتير الموردين أو مقبوضات العملاء.', 'Pick the party type: supplier invoice payments or customer receipts.'),
             'when': T('تغييره يمسح فلتر الأطراف.', 'Changing it clears the party filter.')},
            {'target': 'finance-reconciliation-filters',
             'label': T('الفلاتر', 'Filters'),
             'text': T('المورد، تاريخ الفاتورة، تاريخ السند، ونطاق القيمة.', 'Supplier, invoice date, voucher date and value range.'),
             'when': T('تنطبق على كل التبويبات والإجماليات والتصدير والإجراءات الجماعية.', 'They apply to every tab, total, export and bulk action.'),
             'more': T('تقدر تختار أكتر من مورد، وتحدد مدى تاريخ الفاتورة ومدى تاريخ السند (السداد) والقيمة من/إلى.\n'
                       '• زر المسح بيرجّع كل الفلاتر.\n'
                       '• اشتغل مورد مورد عشان المراجعة تبقى أوضح.',
                       'You can pick several suppliers, and set an invoice date range, a voucher (payment) date range and an amount from/to.\n'
                       '• The clear button resets all filters.\n'
                       '• Work supplier by supplier for a clearer review.'),
         },
            {'target': 'finance-reconciliation-kpis',
             'label': T('الإجماليات', 'Totals'),
             'text': T('الفواتير، السندات، سندات بلا ربط، المقترحات وقيمتها، والاستثناءات.', 'Invoices, vouchers, unlinked vouchers, proposals and their value, and exceptions.'),
             'more': T('كلها محسوبة في السيرفر حسب الفلاتر.\n'
                       '• «سندات بلا ربط» بتتلوّن تحذير: فلوس اتدفعت ومش معروف سددت أنهي فاتورة.\n'
                       '• «قيمة مقترحة» = مجموع المقترحات القابلة للاعتماد.',
                       'All computed on the server according to the filters.\n'
                       '• "Unlinked vouchers" is highlighted as a warning: money paid with no known invoice.\n'
                       '• "Proposed value" = the total of proposals that can be approved.'),
         },
            {'target': 'finance-reconciliation-tabs',
             'label': T('المقترحات · الاستثناءات · …', 'Proposals · Exceptions · …'),
             'text': T('أربع مساحات عمل لنفس النطاق المفلتر.', 'Four workspaces over the same filtered scope.'),
             'more': T('• «المقترحات»: هنا بتعتمد أو ترفض.\n'
                       '• «الاستثناءات»: سند مكرر محتمل أو بيسمي فاتورة تانية وغيرها.\n'
                       '• «غير المسددة»: فواتير لسه عليها رصيد.\n'
                       '• «الحصر»: حساب كل مورد وكشفه.',
                       '• "Proposals": where you approve or reject.\n'
                       '• "Exceptions": a possible duplicate voucher, one naming another invoice, and more.\n'
                       '• "Unpaid": invoices still carrying a balance.\n'
                       '• "Parties": each supplier account and ledger.'),
         },
            {'target': 'finance-reconciliation-status',
             'label': T('الحالة', 'Status'),
             'text': T('يحتاج مراجعة، مقترحة، معتمدة، مكتوبة، مرفوضة.', 'Needs review, proposed, approved, written, rejected.'),
             'when': T('«⚠ يحتاج مراجعة» = محجوزة لا يشملها الاعتماد الجماعي.', '"⚠ Needs review" = held back; bulk approval skips them.'),
             'open_hint': T('تبويب «المقترحات».', 'The "Proposals" tab.'),
             'more': T('• «⚠ يحتاج مراجعة»: مقترحات محجوزة لازم تتراجع واحدة واحدة.\n'
                       '• «معتمدة»: اتربطت عندنا ولسه ما اتكتبتش في SOFTECH.\n'
                       '• «مكتوبة»: اتكتبت في SOFTECH.\n'
                       'زر «✓ اعتماد كل الثقة العالية» بيعتمد العالية بس ويسيب المحجوزة.',
                       '• "⚠ Needs review": held proposals that must be reviewed one by one.\n'
                       '• "Approved": linked in our system and not yet written to SOFTECH.\n'
                       '• "Written": written to SOFTECH.\n'
                       'The "✓ Approve all high confidence" button approves only the high ones and leaves the held ones.'),
         },
            {'target': 'finance-reconciliation-list',
             'label': T('قائمة المقترحات', 'Suggestions list'),
             'when': T('لمراجعة كل مقترح تسوية قبل اعتماده أو رفضه.', 'To review each matching suggestion before approving or rejecting it.'),
             'text': T('المقترحات بدرجة الثقة والفاتورة والسند والمتبقي؛ افتح الصف للتفاصيل، والاعتماد أو الرفض حسب الصلاحية.',
                                              'Proposals with confidence, invoice, voucher and remaining; open a row for details — approving or rejecting depends on permission.'),
             'more': T('افتح الصف عشان تشوف أصناف الفاتورة والمرتجعات المرتبطة، وبعدين «✓ اعتماد» أو «✕ رفض» (أو للمجموعة كاملة).\n'
                       '• «المتبقي» محسوب: قيمة الفاتورة − المسدد في SOFTECH − المعتمد بانتظار الكتابة.\n'
                       '• الاعتماد للمدير والصيدلي، والكتابة في SOFTECH للمدير بس.',
                       'Open the row to see the invoice items and linked returns, then "✓ Approve" or "✕ Reject" (or the whole group).\n'
                       '• "Remaining" is computed: invoice value − paid in SOFTECH − approved awaiting write.\n'
                       '• Approving is for the admin and pharmacist; writing to SOFTECH is for the admin only.')},
            {'target': 'finance-reconciliation-confidence',
             'label': T('الثقة', 'Confidence'),
             'text': T('عالية، متوسطة، منخفضة، أو تعارض بين أكثر من فاتورة.', 'High, medium, low, or a conflict between several invoices.'),
             'open_hint': T('تبويب «المقترحات».', 'The "Proposals" tab.')},
            {'target': 'finance-reconciliation-strategy',
             'label': T('طريقة المطابقة', 'Matching method'),
             'text': T('كيف وُجد الربط: مباشر، مبلغ فريد، مجموع متتالٍ، أقساط…', 'How the link was found: direct, unique amount, running sum, installments…'),
             'open_hint': T('تبويب «المقترحات».', 'The "Proposals" tab.')},
            {'target': 'finance-reconciliation-view',
             'label': T('العرض', 'View'),
             'text': T('جدول، أو مجمّع حسب الفاتورة، أو حسب السند.', 'Table, grouped by invoice, or grouped by voucher.'),
             'when': T('المجمّع يكشف الفاتورة التي تتجاوز مقترحاتها قيمتها.', 'Grouped view reveals invoices whose proposals exceed their value.'),
             'open_hint': T('تبويب «المقترحات».', 'The "Proposals" tab.')},
            {'target': 'finance-reconciliation-export-review',
             'label': T('⬇ تصدير المتوسطة والمنخفضة للمراجعة', '⬇ Export medium & low for review'),
             'text': T('ملف Excel بالمقترحات التي تحتاج عيناً بشرية.', 'An Excel file of the proposals that need a human eye.'),
             'open_hint': T('تبويب «المقترحات».', 'The "Proposals" tab.')},
            {'target': 'finance-reconciliation-row',
             'label': T('صف المقترح', 'Proposal row'),
             'text': T('اضغطه لترى الفاتورة والسند والمرتجعات والدليل. المربع يحدده لإجراء جماعي.', 'Click to see invoice, voucher, returns and evidence. The box selects it for a bulk action.'),
             'open_hint': T('في عرض «☰ جدول».', 'In the "☰ Table" view.')},
            {'target': 'finance-reconciliation-invoice-items',
             'label': T('📦 أصناف الفاتورة', '📦 Invoice items'),
             'text': T('يقرأ أصناف الفاتورة من SOFTECH عند الضغط فقط.', 'Reads the invoice items from SOFTECH only when pressed.'),
             'open_hint': T('افتح صف مقترح.', 'Open a proposal row.')},
            {'target': 'finance-reconciliation-approve',
             'label': T('✓ اعتماد', '✓ Approve'),
             'text': T('ينشئ الربط في المرآة لدينا فقط ويخفّض «المتبقي».', 'Creates the link in our mirror only and lowers "remaining".'),
             'warn': T('اعتماد ربط خاطئ يُظهر الفاتورة مسددة وهي لا.', 'Approving a wrong link shows the invoice as paid when it is not.'),
             'open_hint': T('افتح صف مقترح بحالة «مقترحة».', 'Open a "proposed" row.')},
            {'target': 'finance-reconciliation-reject',
             'label': T('✕ رفض', '✕ Reject'),
             'text': T('يرفض هذا الربط فلا يُقترح كما هو.', 'Rejects this link so it is not proposed as is.'),
             'warn': T('لا ترفض ربطاً صحيحاً — الفاتورة ستظهر غير مسددة.', 'Do not reject a correct link — the invoice will show unpaid.'),
             'open_hint': T('افتح صف مقترح بحالة «مقترحة».', 'Open a "proposed" row.')},
            {'target': 'finance-reconciliation-approve-group',
             'label': T('✓ اعتماد المجموعة كاملة', '✓ Approve whole group'),
             'text': T('يعتمد كل سندات/فواتير الربط المركّب معاً.', 'Approves every voucher/invoice of a combined link together.'),
             'warn': T('راجع المجموعة كلها أولاً — خطأ واحد يفسدها.', 'Review the whole group first — one mistake spoils it.'),
             'open_hint': T('يظهر على المقترحات المركّبة (ليست مباشرة).', 'Shown on combined (not direct) proposals.')},
            {'target': 'finance-reconciliation-approve-high',
             'label': T('✓ اعتماد كل الثقة العالية', '✓ Approve all high confidence'),
             'text': T('يعتمد كل المقترحات عالية الثقة في النطاق ما عدا المحجوزة للمراجعة.', 'Approves every high-confidence proposal in scope except those held for review.'),
             'warn': T('يشمل كل النطاق المفلتر — ضيّق الفلاتر أولاً لو مش متأكد.', 'It covers the whole filtered scope — narrow the filters first if unsure.'),
             'open_hint': T('اختر الحالة «مقترحة».', 'Pick the "proposed" status.')},
            {'target': 'finance-reconciliation-selection',
             'label': T('شريط المحدد', 'Selection bar'),
             'text': T('اعتماد، رفض، كتابة، عكس، أو إرسال للمراجعة للصفوف المحددة، مع ملاحظة.', 'Approve, reject, write, reverse or send to review for the ticked rows, with a note.'),
             'warn': T('الكتابة والعكس في SOFTECH تحتاج ضغطة ثانية للتأكيد.', 'Writing and reversing in SOFTECH need a second click to confirm.'),
             'open_hint': T('يظهر بعد تحديد صف أو أكثر.', 'Shown after ticking one or more rows.')},
            {'target': 'finance-reconciliation-write-softech',
             'label': T('🖊 كتابة في SOFTECH', '🖊 Write to SOFTECH'),
             'text': T('يسجّل الربط المعتمد كسداد في SOFTECH. للمدير فقط.', 'Records the approved link as a payment in SOFTECH. Admins only.'),
             'warn': T('حين يكون مفعّلاً يغيّر رصيد الفاتورة في SOFTECH. محمي ضد التكرار.', 'When enabled it changes the invoice balance in SOFTECH. Protected against duplicates.'),
             'open_hint': T('افتح صفاً بحالة «معتمدة».', 'Open an "approved" row.')},
            {'target': 'finance-reconciliation-write-softech-all',
             'label': T('🖊 كتابة كل المعتمد في SOFTECH', '🖊 Write all approved to SOFTECH'),
             'text': T('يكتب كل المعتمد في النطاق دفعات متتالية؛ ما ترفضه الحمايات يُتخطّى.', 'Writes all approved links in scope in batches; anything the guards refuse is skipped.'),
             'warn': T('يشمل كل النطاق المفلتر. يُرفض وهو معطّل بإعداد السيرفر.', 'It covers the whole filtered scope. Refused while the server setting is off.'),
             'open_hint': T('اختر الحالة «معتمدة».', 'Pick the "approved" status.')},
            {'target': 'finance-reconciliation-reverse-softech',
             'label': T('↩ عكس من SOFTECH (مطابقة خاطئة)', '↩ Reverse from SOFTECH (wrong match)'),
             'text': T('يلغي الربط المكتوب في SOFTECH فتعود الفاتورة مفتوحة ويُرفض المقترح.', 'Undoes the written link in SOFTECH: the invoice reopens and the proposal is rejected.'),
             'warn': T('للمطابقة الخاطئة فقط — يغيّر رصيد الفاتورة في SOFTECH.', 'Only for a wrong match — it changes the invoice balance in SOFTECH.'),
             'open_hint': T('افتح صفاً بحالة «مكتوبة».', 'Open a "written" row.')},
            {'target': 'finance-reconciliation-exception-type',
             'label': T('النوع · الخطورة', 'Type · Severity'),
             'text': T('صفِّ الاستثناءات: سند مكرر، دفع زائد، مرتجع مستحق، سند بلا فاتورة…', 'Filter exceptions: duplicate voucher, overpayment, open return, orphan voucher…'),
             'when': T('ابدأ بالحرج.', 'Start with critical.'),
             'open_hint': T('تبويب «الاستثناءات».', 'The "Exceptions" tab.')},
            {'target': 'finance-reconciliation-unpaid-filter',
             'label': T('غير مسددة فعلياً · تحت المراجعة · …', 'Truly unpaid · Under review · …'),
             'text': T('اختر أي فواتير تُعرض: بلا سند، تحت المراجعة، كل المفتوح، أو المسددة جزئياً.', 'Choose which invoices show: no voucher, under review, all open, or partly paid.'),
             'open_hint': T('تبويب «غير المسددة (للمالية)».', 'The "Unpaid (for finance)" tab.')},
            {'target': 'finance-reconciliation-unpaid-export',
             'label': T('⬇ تصدير Excel للإدارة المالية', '⬇ Excel export for finance'),
             'text': T('ملف بالفواتير التي ما زال عليها رصيد، لكل مورد.', 'A file of invoices still carrying a balance, per supplier.'),
             'open_hint': T('تبويب «غير المسددة (للمالية)».', 'The "Unpaid (for finance)" tab.')},
            {'target': 'finance-reconciliation-parties-search',
             'label': T('بحث بالكود أو الاسم', 'Search by code or name'),
             'text': T('ابحث عن مورد لعرض حصره.', 'Find a supplier to show its ledger.'),
             'open_hint': T('تبويب «الحصر».', 'The "Parties & ledger" tab.')},
            {'target': 'finance-reconciliation-party-type',
             'label': T('حصر ›', 'Ledger ›'),
             'text': T('اضغط المورد لفتح كشف حسابه بالرصيد بعد كل حركة.', 'Click the supplier to open its ledger with the balance after each movement.'),
             'open_hint': T('تبويب «الحصر».', 'The "Parties & ledger" tab.'),
             'more': T('كل الصفحة (الفلاتر والكروت والتبويبات) بتتبع الطرف المختار.\n'
                       '• جنبها ملاحظة مهمة: الاعتماد بيعمل ربط داخلي عندنا بس، والكتابة في SOFTECH خطوة منفصلة قابلة للعكس.',
                       'The whole page (filters, cards and tabs) follows the chosen party.\n'
                       '• Next to it is an important note: approving creates an internal link in our system only, and writing to SOFTECH is a separate, reversible step.'),
         },
        ],
        'updated': '2026-10-31',
        'change_note': T('جانب التعاقدات للقراءة فقط، والمستحقات في شاشتها', 'Contract side read-only; receivables have their own screen'),
    },
]
