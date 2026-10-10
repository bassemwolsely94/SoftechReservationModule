from . import T

_SYNC = T('لو ظهرت «لا توجد بيانات» فالمزامنة المالية لم تُشغَّل لهذه الفترة — اطلب من المدير تشغيلها.', 'If "no data" shows, the finance sync has not run for this period — ask the admin to run it.')

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
        'updated': '2026-10-10',
    },
    {
        'key': 'finance.pnl',
        'routes': ['/finance/pnl'],
        'title': T('قائمة الأرباح والخسائر', 'Profit & loss'),
        'summary': T('الإيرادات (المبيعات − المرتجعات) ← تكلفة البضاعة (المشتريات − مرتجعاتها) ← إجمالي الربح ← المصروفات التشغيلية (رواتب، إيجارات، مرافق، أخرى) ← الربح التشغيلي وصافي الربح، موحّدة أو لفرع.',
                     'Revenue (sales − returns) → cost of goods (purchases − returns) → gross profit → operating expenses (salaries, rent, utilities, other) → operating and net profit, consolidated or per branch.'),
        'audience': T('الإدارة والمالية.', 'Management and finance.'),
        'tips': [_SYNC],
        'updated': '2026-10-10',
    },
    {
        'key': 'finance.cashflow',
        'routes': ['/finance/cashflow'],
        'title': T('التدفقات النقدية', 'Cash flows'),
        'summary': T('إجمالي الداخل والخارج والصافي حسب طريقة الدفع (نقدي، شيك، تحويل بنكي، بطاقة، آجل).', 'Total inflow, outflow and net by payment method (cash, cheque, bank transfer, card, credit).'),
        'audience': T('الإدارة والمالية.', 'Management and finance.'),
        'tips': [_SYNC],
        'updated': '2026-10-10',
    },
    {
        'key': 'finance.expenses',
        'routes': ['/finance/expenses'],
        'title': T('تحليل المصروفات', 'Expense analysis'),
        'summary': T('المصروفات حسب الفئة (رواتب، إيجارات، مرافق، صيانة، توصيل، تسويق، فاقد، منتهي الصلاحية…) والتصنيف الفرعي والفرع ومركز التكلفة، بفترة شهر/سنة أو نطاق تاريخ. اضغط فئة لتصفية التفاصيل.',
                     'Expenses by category (salaries, rent, utilities, maintenance, delivery, marketing, shrinkage, expired…), sub-category, branch and cost center, by month/year or a date range. Click a category to filter the details.'),
        'audience': T('الإدارة والمالية.', 'Management and finance.'),
        'tips': [_SYNC],
        'updated': '2026-10-10',
    },
    {
        'key': 'finance.coa',
        'routes': ['/finance/coa'],
        'title': T('دليل الحسابات', 'Chart of accounts'),
        'summary': T('الحسابات المحاسبية من SOFTECH كقائمة أو شجرة: الكود، الاسم، النوع (أصول، التزامات، حقوق ملكية، إيرادات، مصروفات، تكلفة مبيعات)، الطبيعة (مدين/دائن) والمستوى.',
                     'The SOFTECH accounts as a list or tree: code, name, type (assets, liabilities, equity, revenue, expenses, cost of sales), nature (debit/credit) and level.'),
        'audience': T('المالية.', 'Finance.'),
        'updated': '2026-10-10',
    },
    {
        'key': 'finance.schema',
        'routes': ['/finance/schema'],
        'title': T('اكتشاف المخطط المالي', 'Finance schema discovery'),
        'summary': T('للمدير: فحص جداول SOFTECH ذات الصلة المالية، تأكيد الغرض من كل جدول، وتفعيله للمزامنة. هذه خطوة إعداد قبل أن تعمل باقي الشاشات المالية.',
                     'For admins: scan SOFTECH tables with a financial purpose, confirm each table\'s purpose and enable it for syncing. A setup step before the other finance screens work.'),
        'audience': T('المدير فقط.', 'Admins only.'),
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
    },
]
