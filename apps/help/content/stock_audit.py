from . import T

MODULE = {
    'key': 'stock_audit', 'group': 'inventory', 'icon': '🔎',
    'title': T('تدقيق حركات المخزون', 'Stock transactions audit'),
    'summary': T(
        'فحوص ثابتة تعمل تلقائياً على كل حركات المخزون في SOFTECH (بيع، مرتجع، شراء، تحويل، تسوية) لكل الفروع، '
        'وتحل محل ملف Power Query القديم. كل ساعتين تُقرأ آخر 3 أيام من SOFTECH (قراءة فقط) ثم تعمل الفحوص: '
        'البيع بأقل من التكلفة (بعد خصم الضريبة من السعر)، المستندات المتطابقة المكررة، اختلاف سعر نفس الصنف داخل '
        'فاتورة واحدة، تذبذب تكلفة الشراء من نفس المورد، تسويات الجرد والهالك الكبيرة أو المتكررة، التسوية التي لا '
        'تطابق نتيجة الجرد، النفاد المتكرر للأدوية، المرتجعات بدون فاتورة أو أكثر من المباع، والإدخال خارج مواعيد الفرع. كل ملاحظة تذكر الفرع والصنف والمستند والموظف والقيمة، '
        'وتمر بمراجعة: مفتوحة ← تمت المراجعة / تجاهل / تصعيد. الحدود (النسب والمبالغ) يضبطها المدير والجودة للسلسلة كلها '
        'ولأي فرع على حدة. النظام لا يكتب في SOFTECH أبداً.',
        'Fixed checks that run automatically on every SOFTECH stock movement (sale, return, purchase, transfer, '
        'adjustment) in every branch, replacing the old Power Query workbook. Every two hours the last 3 days are read '
        'from SOFTECH (read only), then the checks run: sales below cost (VAT removed from the price first), identical '
        'duplicate documents, two prices for one item on the same invoice, purchase cost swings from the same supplier, '
        'large or repeated count and write-off adjustments, adjustments that do not match the count result, frequent '
        'stock-outs of medicines, returns with no invoice or above what was sold, and entries outside branch hours. Each finding names the branch, item, document, employee and value, and goes through review: '
        'open → reviewed / dismissed / escalated. The thresholds (percentages and amounts) are set by admin and quality '
        'for the whole chain and for any single branch. The system never writes to SOFTECH.'),
    'workflows': [{
        'key': 'finding',
        'title': T('دورة مراجعة الملاحظة', 'Finding review life cycle'),
        'model': 'stock_audit.StockAuditFinding', 'field': 'status',
        'transitions': 'apps.stock_audit.models.StockAuditFinding.TRANSITIONS',
        'intro': T('إعادة تشغيل الفحوص لا تغيّر حالة المراجعة. الملاحظة المتجاهلة تُفتح تلقائياً فقط إذا زادت قيمتها أكثر من 50%.',
                   'Re-running the checks never changes a review status. A dismissed finding reopens by itself only if its value grows by more than 50%.'),
        'states': [
            {'key': 'open', 'label': T('مفتوح', 'Open'),
             'desc': T('ملاحظة جديدة لم يراجعها أحد بعد.', 'A new finding nobody has reviewed yet.'),
             'next': ['reviewed', 'dismissed', 'escalated']},
            {'key': 'escalated', 'label': T('تم التصعيد', 'Escalated'),
             'desc': T('تحتاج قراراً أعلى أو تحقيقاً (مع سبب مكتوب).', 'Needs a higher decision or an investigation (with a written reason).'),
             'next': ['reviewed', 'dismissed']},
            {'key': 'reviewed', 'label': T('تمت المراجعة', 'Reviewed'),
             'desc': T('رُوجعت واتُّخذ ما يلزم. يمكن إعادة فتحها مع سبب.', 'Checked and handled. It can be reopened with a reason.'),
             'next': ['open']},
            {'key': 'dismissed', 'label': T('تم التجاهل', 'Dismissed'),
             'desc': T('ليست مشكلة (مثلاً تعاقد معروف) — مع سبب مكتوب.', 'Not a problem (for example a known contract) — with a written reason.'),
             'next': ['open']},
        ],
    }],
    'journeys': [
        {'key': 'daily_review', 'shell': 'desktop',
         'title': T('مراجعة يومية لملاحظات المخزون', 'Daily review of stock findings'),
         'summary': T('من الملخص إلى الملاحظة، ثم المراجعة والتصدير.', 'From the summary to the finding, then review and export.'),
         'steps': [
            {'screen': 'stock_audit.main', 'target': 'stock-audit-main-cards', 'perm': 'stock_audit',
             'label': T('📊 ملخص', '📊 Summary'),
             'text': T('ابدأ بالبطاقات: عدد الملاحظات المفتوحة والحرجة وقيمتها لكل فحص.',
                       'Start with the cards: open and critical findings and their value per check.')},
            {'screen': 'stock_audit.main', 'target': 'stock-audit-main-matrix', 'perm': 'stock_audit',
             'label': T('الفرع × الفحص', 'Branch × check'),
             'text': T('اضغط أي رقم لتفتح ملاحظات هذا الفحص في هذا الفرع.', 'Click any number to open that check’s findings for that branch.')},
            {'screen': 'stock_audit.main', 'target': 'stock-audit-main-grid', 'perm': 'stock_audit',
             'label': T('قائمة الملاحظات', 'Findings list'),
             'text': T('اضغط السطر (أو Enter) لترى الرسالة والسطور الأصلية من SOFTECH.', 'Click the row (or Enter) to see the message and the original SOFTECH lines.')},
            {'screen': 'stock_audit.main', 'target': 'stock-audit-main-review', 'perm': 'stock_audit',
             'label': T('✔ تمت المراجعة', '✔ Reviewed'),
             'text': T('سجّل قرارك على الملاحظة. التجاهل والتصعيد يحتاجان ملاحظة مكتوبة.', 'Record your decision. Dismiss and escalate need a written note.'),
             'open_hint': T('افتح أي ملاحظة من القائمة.', 'Open any finding from the list.')},
            {'screen': 'stock_audit.main', 'target': 'stock-audit-main-export', 'perm': 'stock_audit',
             'label': T('⬇️ تصدير Excel', '⬇️ Export Excel'),
             'text': T('ينزّل الملاحظات بالفلاتر الحالية للمتابعة مع الفرع.', 'Downloads the findings with the current filters to follow up with the branch.')},
         ]},
    ],
}

SCREENS = [
    {
        'key': 'stock_audit.main',
        'routes': ['/stock-audit'],
        'title': T('تدقيق حركات المخزون', 'Stock transactions audit'),
        'summary': T('ملاحظات تسعة فحوص ثابتة على حركات SOFTECH، مع المراجعة والحدود وصلاحيات مديري الفروع.',
                     'Findings from nine fixed checks on SOFTECH movements, with review, thresholds and branch-manager access.'),
        'audience': T('الإدارة والمشرفون والجودة لكل الفروع، ومديرو الفروع المسموح لهم بالاسم لفروعهم فقط.',
                      'Admin, supervisors and quality for every branch, and named branch managers for their own branches only.'),
        'tabs': [
            {'key': 'summary', 'title': T('📊 ملخص', '📊 Summary'),
             'body': T('لكل فحص: الملاحظات المفتوحة والحرجة وقيمتها، والإجمالي مقارنة بالفترة السابقة بنفس الطول. '
                       'تحتها جدول الفروع × الفحوص — اضغط أي رقم لتفتح الملاحظات مفلترة.',
                       'For each check: open and critical findings and their value, and the total against the previous period of the same length. '
                       'Below it, a branches × checks table — click any number to open the findings already filtered.')},
            {'key': 'sales', 'title': T('🧾 المبيعات والأسعار', '🧾 Sales & prices'),
             'body': T('الفحص 1 بيع بأقل من التكلفة: سعر البيع بعد خصم الضريبة أقل من تكلفة الصنف بنسبة وقيمة أكبر من الحد '
                       '(عملاء الهدايا المجانية والتعاقدات مستبعدون). الفحص 2 مستندات متطابقة: مستندان لنفس العميل بنفس الأصناف '
                       'والكميات والأسعار خلال 20 دقيقة، إلا إذا رُدّت إحداهما بمرتجع. الفحص 3 سعران مختلفان لنفس الصنف في فاتورة واحدة. '
                       'الفحص 4 تكلفة شراء الصنف من نفس المورد تغيّرت أكثر من 20% عن آخر شراء خلال 90 يوماً (سطور البونص '
                       'المجاني وموردو بدل الروشتة مستبعدون).',
                       'Check 1, sales below cost: the sale price net of VAT is below the item cost by more than the threshold percentage and amount '
                       '(free-pack and contract customers are excluded). Check 2, identical documents: two documents for the same customer with the same '
                       'items, quantities and prices within 20 minutes, unless one was returned. Check 3: two prices for the same item on one invoice. '
                       'Check 4: the purchase cost of an item from the same supplier moved more than 20% from its last purchase within '
                       '90 days (free-goods lines and the prescription-replacement suppliers are excluded).')},
            {'key': 'adjustments', 'title': T('⚖️ تسويات المخزون', '⚖️ Stock adjustments'),
             'body': T('الفحص 5: أي فائض أو عجز جرد أو صرف هالك بقيمة 500 ج.م أو أكثر بالتكلفة، أو 3 تسويات أو أكثر لنفس الصنف '
                       'خلال 30 يوماً. الفحص 11: فائض أو عجز أُدخل خلال 48 ساعة من جرد شمل الصنف ولا يساوي فرق الجرد '
                       '(إدخال فرق الجرد نفسه طبيعي). تحتها ترتيب كل المستخدمين بعدد وقيمة تسوياتهم في الفترة (بدون حد).',
                       'Check 5: any count surplus, deficit or write-off worth 500 EGP or more at cost, or 3 or more adjustments of the same item '
                       'within 30 days. Check 11: a surplus or deficit entered within 48 hours of a count that covered the item and not equal '
                       'to the counted difference (posting the counted difference itself is normal). Below it, every user ranked by the '
                       'number and value of their adjustments in the period (no threshold).')},
            {'key': 'availability', 'title': T('📦 توافر المخزون', '📦 Stock availability'),
             'body': T('الفحص 6: دواء وصل رصيده صفر 3 مرات أو أكثر خلال 30 يوماً ومعدل بيعه شهرياً 1 أو أكثر — إشارة لتعديل '
                       'حد الطلب أو التوريد. الفائض (الفحص 7) موجود في لوحة المخزون، تبويب «📦 الفائض».',
                       'Check 6: a medicine whose stock hit zero 3 or more times in 30 days and sells 1 or more a month — a sign '
                       'to adjust the reorder level or supply. Overstock (check 7) is on the inventory dashboard, "📦 Overstock" tab.')},
            {'key': 'returns', 'title': T('↩️ المرتجعات', '↩️ Returns'),
             'body': T('الفحص 10: مرتجع بدون رقم فاتورة بيع، أو لصنف غير موجود في الفاتورة المذكورة، أو مرتجع أكثر من المباع '
                       'في الفاتورة (محسوب على كل المرتجعات السابقة عليها — حرج). الفواتير الأقدم من سنة لا تُفحص.',
                       'Check 10: a return with no sale invoice number, or for an item not on the stated invoice, or more returned than '
                       'sold on that invoice (counting every earlier return on it — critical). Invoices older than a year are not checked.')},
            {'key': 'timing', 'title': T('🕘 مواعيد الإدخال', '🕘 Entry times'),
             'body': T('الفحص 9: مستند أُدخل خارج مواعيد عمل فرعه بأكثر من 30 دقيقة (ملاحظة واحدة لكل مستند؛ تنبيه بعد ساعتين). '
                       'المواعيد تُضبط لكل فرع من الإعدادات ← الفروع، ويمكن أن تنطبق فترة على مستندات معينة فقط '
                       '(مثل الكول سنتر في الرئيسي حتى منتصف الليل). الفروع التي تعمل 24 ساعة لا تُفحص.',
                       'Check 9: a document entered more than 30 minutes outside its branch\'s working hours (one finding per document; '
                       'a warning after two hours). Hours are set per branch in Settings → branches, and a window can apply to some '
                       'document types only (like the HQ call center until midnight). Branches open 24 hours are not checked.')},
            {'key': 'settings', 'title': T('⚙️ الإعدادات', '⚙️ Settings'),
             'body': T('حدود كل فحص للسلسلة كلها، وحدود خاصة لأي فرع (الخانة الفارغة = كالعام). التعديل للمدير والجودة، '
                       'وكل تغيير يُسجّل قبل وبعد. المدير فقط يمنح أو يسحب صلاحية مديري الفروع بالاسم.',
                       'Each check’s thresholds for the whole chain, and special values for any branch (an empty field = same as the chain). '
                       'Admin and quality edit them, and every change is logged before and after. Only admin grants or removes named branch managers.')},
        ],
        'tips': [
            T('القيم بالتكلفة قبل الضريبة. سعر البيع في SOFTECH يشمل الضريبة، فيُخصم قبل المقارنة.',
              'Values are at cost before VAT. The SOFTECH sale price includes VAT, so it is removed before comparing.'),
            T('تكرار نفس السطر داخل فاتورة واحدة متوقف افتراضياً: هو طريقة SOFTECH في حفظ الصنف الممسوح وحدة وحدة.',
              'The same line repeated inside one invoice is off by default: it is how SOFTECH saves an item scanned one unit at a time.'),
            T('الملاحظة تبقى على حالتها بعد كل تشغيل؛ زيادة قيمة المتجاهلة أكثر من 50% تعيد فتحها مع ملاحظة.',
              'A finding keeps its status after every run; a dismissed one whose value grows by over 50% is reopened with a note.'),
        ],
        'related': ['stockcount.sessions', 'batches.main'],
        'tour': [
            {'target': 'stock-audit-main-tabs',
             'text': T('سبع تبويبات: الملخص، المبيعات، التسويات، توافر المخزون، المرتجعات، مواعيد الإدخال، والإعدادات.',
                       'Seven tabs: summary, sales, adjustments, availability, returns, entry times, and settings.')},
            {'target': 'stock-audit-main-refresh',
             'text': T('يقرأ آخر 3 أيام من SOFTECH الآن ويعيد تشغيل الفحوص بدل انتظار الدورة كل ساعتين. قراءة فقط.',
                       'Reads the last 3 days from SOFTECH now and re-runs the checks instead of waiting for the 2-hour cycle. Read only.')},
            {'target': 'stock-audit-main-filters',
             'text': T('حدد الفترة والفرع والحالة والخطورة، أو ابحث بكود الصنف أو اسمه أو رقم المستند.',
                       'Set the period, branch, status and severity, or search by item code, name or document number.')},
            {'target': 'stock-audit-main-cards',
             'text': T('المفتوح والحرج وقيمته لكل فحص. اضغط البطاقة لتفتح ملاحظاتها.',
                       'Open, critical and their value per check. Click a card to open its findings.')},
            {'target': 'stock-audit-main-matrix',
             'text': T('أين تتركز الملاحظات المفتوحة، مرتبة بالقيمة.',
                       'Where the open findings are, sorted by value.')},
            {'target': 'stock-audit-main-rules',
             'text': T('اختر فحصاً واحداً أو اعرضها كلها.',
                       'Pick one check or show them all.')},
            {'target': 'stock-audit-main-grid',
             'text': T('↑↓ للتنقل، Space للتحديد، Enter لفتح التفاصيل والسطور الأصلية.',
                       '↑↓ to move, Space to tick, Enter to open the details and original lines.')},
            {'target': 'stock-audit-main-review',
             'text': T('سجّل قرارك. التجاهل والتصعيد وإعادة الفتح تحتاج ملاحظة مكتوبة.',
                       'Record your decision. Dismiss, escalate and reopen need a written note.')},
            {'target': 'stock-audit-main-bulk',
             'text': T('نفس القرار والملاحظة لكل الملاحظات المحددة مرة واحدة.',
                       'The same decision and note for all selected findings at once.')},
            {'target': 'stock-audit-main-export',
             'text': T('ينزّل الملاحظات بالفلاتر الحالية (بأسماء الفروع).',
                       'Downloads the findings with the current filters (with branch names).')},
            {'target': 'stock-audit-main-overstock',
             'text': T('الفائض والتغطية الزائدة تُتابع في لوحة المخزون، ولا تتكرر هنا.',
                       'Overstock and excess cover are followed on the inventory dashboard, not repeated here.')},
            {'target': 'stock-audit-main-hours',
             'text': T('مواعيد كل فرع تُضبط من الإعدادات. الفرع بلا مواعيد لا يُفحص.',
                       'Each branch’s hours are set in Settings. A branch with no hours is not checked.')},
            {'target': 'stock-audit-main-ranking',
             'text': T('كل مستخدم بعدد تسوياته وقيمتها بالتكلفة في الفترة.',
                       'Each user with the number and cost value of their adjustments in the period.')},
            {'target': 'stock-audit-main-thresholds',
             'text': T('حدود السلسلة كلها، وحدود خاصة لأي فرع. الخانة الفارغة في الفرع = كالعام.',
                       'Chain-wide thresholds, and special values for any branch. An empty branch field = same as the chain.')},
            {'target': 'stock-audit-main-save',
             'text': T('يحفظ الحدود ويطبقها من التشغيل القادم. يُسجّل التغيير قبل وبعد.',
                       'Saves the thresholds; they apply from the next run. The change is logged before and after.')},
            {'target': 'stock-audit-main-access',
             'text': T('امنح موظفاً بالاسم صلاحية رؤية ومراجعة ملاحظات فرعه فقط.',
                       'Give a named employee access to see and review only their own branch’s findings.')},
            {'target': 'stock-audit-main-access-revoke',
             'text': T('يوقف وصول مدير الفرع فوراً. يبقى سجل المنح والسحب.',
                       'Stops the branch manager’s access at once. The grant and removal stay on record.')},
        ],
        'updated': '2026-10-26',
    },
]
