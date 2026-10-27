from . import T

MODULE = {
    'key': 'batches', 'group': 'inventory', 'icon': '🧪',
    'title': T('الدفعات والصلاحية', 'Batches & expiry'),
    'summary': T(
        'متابعة تواريخ صلاحية المخزون الفعلي في كل الفروع والمخازن (بيانات يومية من SOFTECH) حتى لا نخسر أصنافاً بانتهاء صلاحيتها: '
        'قرب الانتهاء والمنتهي، تدقيق مادي للصلاحيات المسجّلة عند الشراء، أداء الموردين في الصلاحية، مراجعة كميات الشراء، '
        'نقل التشغيلات لفروع تبيعها أسرع قبل انتهائها، وقرارات الإتلاف أو المرتجع. القاعدة: الأقرب انتهاءً يُصرف أولاً (FEFO). '
        'النظام يقترح فقط؛ أي حركة مخزون فعلية تتم في SOFTECH.',
        'Track the expiry dates of actual stock in every branch and store (daily data from SOFTECH) so we do not lose items to expiry: '
        'near-expiry and expired, a physical audit of expiry dates entered at purchase, supplier expiry performance, purchase quantity review, '
        'moving batches to branches that sell them faster before they expire, and disposal or return decisions. The rule: first expiry, first out (FEFO). '
        'The system only suggests; any real stock movement happens in SOFTECH.'),
    'journeys': [
        {'key': 'desktop_expiry', 'shell': 'desktop',
         'title': T('من قرب الانتهاء للقرار', 'From near expiry to a decision'),
         'summary': T('صفّي اللي قرب ينتهي، صدّره أو جرده، انقل اللي ممكن يتباع، وسجّل واعتمد الإتلاف أو المرتجع. التنفيذ الفعلي في SOFTECH.',
                      'Filter what is near expiry, export or count it, move what can still sell, and record and approve disposal or return. Real execution is in SOFTECH.'),
         'steps': [
            {'screen': 'batches.main', 'target': 'batches-main-scope', 'perm': 'catalog',
             'label': T('خلال 30 يوم', 'Within 30 days'),
             'text': T('اختار المدة وفرعك.', 'Pick the period and your branch.'),
             'open_hint': T('تبويب «🚨 قرب الانتهاء».', '"🚨 Near expiry" tab.')},
            {'screen': 'batches.main', 'target': 'batches-main-count', 'perm': 'catalog',
             'label': T('▶️ بدء جرد مادي', '▶️ Start physical count'),
             'text': T('اعمل جرد للأصناف المعروضة عشان تتأكد من الرف.', 'Start a count for the items shown to confirm the shelf.'),
             'open_hint': T('بعد اختيار فرع.', 'After choosing a branch.')},
            {'screen': 'batches.main', 'target': 'batches-main-rescue-transfer', 'perm': 'catalog',
             'label': T('مسودة تحويل', 'Draft transfer'),
             'text': T('انقل التشغيلات اللي فرع تاني يبيعها قبل ما تنتهي.', 'Move batches another branch can sell before they expire.'),
             'open_hint': T('تبويب «🔁 إنقاذ قبل الانتهاء».', '"🔁 Rescue before expiry" tab.')},
            {'screen': 'batches.main', 'target': 'batches-main-disposal-draft', 'perm': 'catalog',
             'label': T('🗑️ إتلاف/مرتجع', '🗑️ Dispose/Return'),
             'text': T('سجّل قرار للي مش هيتباع.', 'Record a decision for what will not sell.'),
             'open_hint': T('تبويب «📦 أرصدة الصلاحية»، وضع «منتهية».', '"📦 Expiry balances" tab, "expired" mode.')},
            {'screen': 'batches.main', 'target': 'batches-main-disposal-approve', 'perm': 'catalog',
             'label': T('اعتماد', 'Approve'),
             'text': T('المدير أو الجودة يعتمد القرار.', 'A manager or quality approves the decision.'),
             'warn': T('راجع الكمية والقرار قبل الاعتماد.', 'Check the quantity and decision before approving.'),
             'open_hint': T('تبويب «🗑️ إتلاف/مرتجع».', '"🗑️ Disposal/return" tab.')},
            {'screen': 'batches.main', 'target': 'batches-main-disposal-done', 'perm': 'catalog',
             'label': T('تم التنفيذ', 'Done'),
             'text': T('نفّذ في SOFTECH يدوياً وبعدين اقفل القرار.', 'Apply it manually in SOFTECH, then close the decision.'),
             'warn': T('بعد التنفيذ الفعلي بس — الحالة نهائية.', 'Only after it is really applied — the status is final.'),
             'open_hint': T('قرار «معتمد».', 'An "approved" decision.')},
         ]},
    ],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول الدفعات والصلاحية', 'A tour of the Batches & expiry module'),
            'summary': T('من الأرقام اليومية لقرب الانتهاء، للجرد على الرف، لحد قرار النقل أو الإتلاف/المرتجع واعتماده.',
                         'From the daily near-expiry figures, to checking the shelf, to the transfer or disposal/return decision and its approval.'),
            'roles': ['admin', 'pharmacist', 'purchasing', 'quality_manager', 'supervisor'],
            'steps': [
                {'target': 'nav-batches', 'nav': '/batches',
                 'text': T('الموديول من القائمة: «المخزون» ← «الدفعات والانتهاء».',
                           'The module from the menu: "Inventory" → "Batches & expiry".'),
                 'more': T('كل شغل الصلاحية في شاشة واحدة بتبويبات. البيانات جاية من أرصدة SOFTECH الفعلية في كل الفروع، وبتتحدّث بمزامنة يومية.\n'
                           '• الموديول ده بيرصد ويقترح؛ التنفيذ الفعلي (تحويل، إتلاف، مرتجع) بيتم في SOFTECH أو في موديول التحويلات.',
                           'All expiry work is on one screen with tabs. The data comes from the actual SOFTECH balances in every branch and is refreshed by a daily sync.\n'
                           '• This module monitors and suggests; the real action (transfer, disposal, return) happens in SOFTECH or in the Transfers module.')},
                {'target': 'batches-main-kpis', 'route': '/batches',
                 'text': T('ابدأ من الأرقام: اللي بينتهي خلال 30 و90 و180 يوم، والمنتهي بالمخزون.',
                           'Start with the figures: what expires within 30, 90 and 180 days, and what has expired in stock.'),
                 'more': T('الأرقام دي على كل الفروع مع قيمتها بالجنيه. لو «منتهية ولا تزال بالمخزون» فيها رقم، ده شغل النهارده: تتشال من الرف وياخد قرار.\n'
                           '• «خلال 30 يوم» = لسه فيه وقت للتصريف أو النقل.',
                           'These figures cover all branches with their value in EGP. If "Expired but still in stock" has a number, that is today\'s job: take it off the shelf and decide.\n'
                           '• "Within 30 days" = there is still time to sell or move it.')},
                {'target': 'batches-main-tabs', 'route': '/batches',
                 'text': T('التبويبات ماشية بترتيب الشغل: رصد ← تدقيق ← تحليل الشراء ← إنقاذ ← قرار.',
                           'The tabs follow the work order: monitor → audit → purchase analysis → rescue → decision.'),
                 'more': T('• «قرب الانتهاء» و«أرصدة الصلاحية»: إيه اللي هيخلص وفين.\n'
                           '• «تدقيق صلاحيات الشراء»: نتأكد إن التاريخ المسجّل عند الشراء مطابق للرف.\n'
                           '• «أداء الموردين» و«مراجعة الشراء»: للمشتريات — مين بيورّد قصير الأجل وإيه اللي نقلل كميته.',
                           '• "Near expiry" and "Expiry balances": what will expire and where.\n'
                           '• "Purchase-expiry audit": check that the date entered at purchase matches the shelf.\n'
                           '• "Supplier expiry performance" and "Purchase review": for purchasing — who supplies short-dated and what to order less of.')},
                {'target': 'batches-main-scope', 'route': '/batches',
                 'text': T('ضيّق القائمة: المدة والفرع والمخزن.',
                           'Narrow the list: period, branch and store.'),
                 'more': T('اختار فرعك عشان تشوف اللي على رفك إنت. «آخر مزامنة» بيوضح البيانات من إمتى؛ لو قديمة، المدير أو المشرف يقدر يضغط «🔄 مزامنة الآن».',
                           'Choose your branch to see what is on your own shelf. "Last sync" shows how old the data is; if it is old, an admin or supervisor can press "🔄 Sync now".')},
                {'target': 'batches-main-table', 'route': '/batches',
                 'text': T('الجدول: كل صنف بكميته وتكلفته وأقرب صلاحية والفروع اللي فيها.',
                           'The table: each item with its quantity, cost, earliest expiry and the branches holding it.'),
                 'more': T('رتّب بـ«قيمة معرّضة» عشان تبدأ بالأغلى. عمود «الفروع» بيوضح الصنف موجود فين — مفيد لو هتنقله.\n'
                           '• القاعدة على الرف: الأقرب انتهاءً يتصرف الأول (FEFO).',
                           'Sort by "Value at risk" to start with the most expensive. The "Branches" column shows where the item is — useful if you will move it.\n'
                           '• The shelf rule: the nearest expiry goes out first (FEFO).')},
                {'target': 'batches-main-actions', 'route': '/batches',
                 'text': T('اتأكد على الرف: «▶️ بدء جرد مادي» (بعد اختيار فرع).',
                           'Check the shelf: "▶️ Start physical count" (after choosing a branch).'),
                 'more': T('بينشئ جلسة جرد صلاحية بالأصناف المعروضة ويفتحها في «الجرد الفعلي»، فتعدّ وتسجّل التاريخ الحقيقي من على العلبة.\n'
                           '• «⬇️ تصدير Excel» لو محتاج القائمة ورق أو تبعتها لحد.',
                           'It creates an expiry count session with the listed items and opens it in "Stock count", where you count and record the real date from the pack.\n'
                           '• "⬇️ Export Excel" if you need the list on paper or to send it to someone.')},
                {'target': 'batches-main-table', 'route': '/batches',
                 'text': T('مش هيتباع في الوقت؟ «🗑️ إتلاف/مرتجع» من صف الصنف.',
                           'Will not sell in time? "🗑️ Disposal/return" on the item\'s row.'),
                 'more': T('اختار القرار (إتلاف، مرتجع للمورد، عزل، مراجعة) والكمية والسبب ثم «تسجيل القرار».\n'
                           '• بيتسجّل «مسودة» في تبويب «إتلاف/مرتجع» — لسه محتاج اعتماد.\n'
                           '• لو الصنف لسه صالح وفرع تاني بيبيعه أسرع، استخدم تبويب «إنقاذ قبل الانتهاء» اللي بينشئ مسودة طلب تحويل بدل الإتلاف.',
                           'Choose the decision (destroy, return to supplier, quarantine, review), the quantity and the reason, then "Record decision".\n'
                           '• It is saved as a "draft" in the "Disposal/return" tab — it still needs approval.\n'
                           '• If the item is still valid and another branch sells it faster, use the "Rescue before expiry" tab, which creates a draft transfer request instead.')},
                {'target': 'batches-main-tabs', 'route': '/batches',
                 'text': T('آخر محطة: تبويب «🗑️ إتلاف/مرتجع» — اعتماد ثم «تم التنفيذ».',
                           'Last stop: the "🗑️ Disposal/return" tab — approve, then "Done".'),
                 'more': T('المدير أو المشرف أو الجودة بس يقدر يضغط «اعتماد» ثم «تم التنفيذ»، و«تم التنفيذ» ما ينفعش قبل الاعتماد.\n'
                           '• اضغط «تم التنفيذ» بعد ما تطبّق القرار بإيدك في SOFTECH — النظام مش بيخصم المخزون لوحده.\n'
                           '• «⬇️ تصدير / طباعة» يطلع مستند القرارات.',
                           'Only an admin, supervisor or quality manager can press "Approve" and then "Done", and "Done" is not allowed before approval.\n'
                           '• Press "Done" after you apply the decision by hand in SOFTECH — the system never deducts stock on its own.\n'
                           '• "⬇️ Export / print" produces the decisions document.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'batches.main',
        'routes': ['/batches'],
        'title': T('الدفعات والانتهاء', 'Batches & expiry'),
        'summary': T('سبعة تبويبات لإدارة الصلاحية من الرصد حتى القرار.', 'Seven tabs to manage expiry from monitoring to decision.'),
        'audience': T('الصيادلة والجودة والمشتريات والمشرفون.', 'Pharmacists, quality, purchasing and supervisors.'),
        'tabs': [
            {'key': 'alerts', 'title': T('🚨 قرب الانتهاء', '🚨 Near expiry'),
             'body': T('الأرصدة الصالحة التي تنتهي خلال المدة المختارة في كل الفروع، مع التصدير وإنشاء جلسة جرد للتحقق. ابدأ يومك من هنا.', 'Valid stock expiring within the chosen period in every branch, with export and a count session to verify. Start your day here.')},
            {'key': 'list', 'title': T('📦 أرصدة الصلاحية (كل الفروع)', '📦 Expiry balances (all branches)'),
             'body': T('كل الأرصدة بتواريخ صلاحيتها، مع وضع «منتهية» للأصناف التي مضت صلاحيتها وما زالت بالمخزون — منها تُنشأ مسودة قرار إتلاف/مرتجع.', 'All stock with expiry dates, with an "expired" mode for items past expiry still in stock — from there you create a disposal/return draft.')},
            {'key': 'audit', 'title': T('📅 تدقيق صلاحيات الشراء', '📅 Purchase-expiry audit'),
             'body': T('الأصناف الموجودة بالمخزون الآن التي سجّل لها موزّع رئيسي أو مصنع (في أي وقت) تاريخ صلاحية داخل الفترة المحددة، مع التكلفة والقيمة المعرّضة وعمر المخزون في الفرع — لسحبها والتحقق الفعلي على الرف. «إنشاء جلسة جرد» يُنشئ جرد صلاحية.',
                       'Items in stock now for which a main distributor or manufacturer (at any time) recorded an expiry date inside the chosen range, with cost, value at risk and stock age in the branch — to pull and physically check on the shelf. "Create count session" creates an expiry audit count.')},
            {'key': 'suppliers', 'title': T('🏭 أداء الموردين (صلاحية)', '🏭 Supplier expiry performance'),
             'body': T('جودة تواريخ الصلاحية من كل موزّع رئيسي: متوسط الصلاحية المتبقية عند الاستلام ونسبة التوريد «قصير الأجل» — ورقة تفاوض لشروط التوريد والمرتجعات.', 'The expiry quality from each main distributor: average remaining shelf life on receipt and the share of "short-dated" supply — a negotiation sheet for supply and return terms.')},
            {'key': 'reorder', 'title': T('♻️ مراجعة الشراء', '♻️ Purchase review'),
             'body': T('أصناف تُشترى قصيرة الأجل بشكل متكرر مع معدل البيع الشهري — إشارة لتقليل كمية إعادة الطلب أو التفاوض أو تغيير المصدر.', 'Items repeatedly bought short-dated, with monthly sales — a signal to reduce reorder quantity, negotiate or change source.')},
            {'key': 'rebalance', 'title': T('🔁 إنقاذ قبل الانتهاء', '🔁 Rescue before expiry'),
             'body': T('تشغيلات لن تُباع في فرعها قبل انتهائها، والفروع التي تبيع الصنف أسرع وتكفي لتصريفها (الأقدم صلاحية أولاً). الزر يُنشئ «مسودة طلب تحويل» تمر بمسار التحويلات المعتاد. ما «لا يوجد فرع يستوعبه» أو «متأخر للنقل» يحتاج خصماً أو مرتجعاً.',
                       'Batches that will not sell in their branch before expiry, and branches that sell the item faster and can absorb them (oldest expiry first). The button creates a "draft transfer request" that goes through the usual transfer flow. Lines with "no branch can absorb" or "too late to move" need a discount or a return.')},
            {'key': 'disposal', 'title': T('🗑️ إتلاف/مرتجع', '🗑️ Disposal/return'),
             'body': T('سجل قرارات الإتلاف أو المرتجع للأصناف المنتهية: مسودة ← اعتماد (مدير/جودة) ← «تم التنفيذ» بعد تطبيقها يدوياً في SOFTECH. النظام لا يخصم المخزون تلقائياً.',
                       'The log of disposal or return decisions for expired items: draft → approval (manager/quality) → "Done" after applying it manually in SOFTECH. The system never deducts stock automatically.')},
        ],
        'tips': [
            T('اقتراحات الإنقاذ تحتاج تشغيل محرك الطلب لحساب معدلات البيع.', 'Rescue suggestions need the demand engine to have run to compute sales rates.'),
            T('«عزل دفعة» يضع التشغيلة في الحجر مع سبب إلزامي (مثلاً تلف أو سحب من السوق).', '"Quarantine batch" puts a batch in quarantine with a required reason (e.g. damage or a market recall).'),
        ],
        'related': ['stockcount.sessions', 'transfers.new', 'catalog.inventory'],
        'tour': [
            {'target': 'batches-main-tabs', 'label': T('🚨 قرب الانتهاء · 📦 أرصدة الصلاحية · …', '🚨 Near expiry · 📦 Expiry balances · …'),
             'text': T('سبع تبويبات من الرصد للقرار: قرب الانتهاء، الأرصدة، تدقيق الشراء، الموردين، مراجعة الشراء، الإنقاذ، والإتلاف/المرتجع.',
                       'Seven tabs from monitoring to decision: near expiry, balances, purchase audit, suppliers, purchase review, rescue, and disposal/return.'),
             'more': T(
                 '• «قرب الانتهاء» و«أرصدة الصلاحية»: الرصد اليومي.\n• «تدقيق صلاحيات الشراء» و«أداء الموردين» و«مراجعة الشراء»: هل بنشتري قصير الأجل ومن مين.\n• «إنقاذ قبل الانتهاء»: ينشئ مسودة طلب تحويل لفرع بيبيع أسرع.\n• «إتلاف/مرتجع»: اعتماد وتنفيذ القرارات.',
                 '• "Near expiry" and "Expiry balances": daily monitoring.\n• "Purchase-expiry audit", "Supplier expiry performance" and "Purchase review": are we buying short-dated, and from whom.\n• "Rescue before expiry": creates a draft transfer request to a branch that sells faster.\n• "Disposal/return": approving and completing decisions.')},
            {'target': 'batches-main-scope', 'label': T('خلال 180 يوم · كل الفروع · كل المخازن', 'Within 180 days · All branches'),
             'text': T('حدد المدة والفرع والمخزن. في «أرصدة الصلاحية» تختار كمان الوضع: قرب الانتهاء، نطاق تاريخ، منتهية، أو الكل.',
                       'Set the period, branch and store. In "Expiry balances" you also pick the mode: near expiry, date range, expired, or all.'),
             'when': T('ابدأ يومك بـ «خلال 30 يوم» لفرعك.', 'Start your day with "within 30 days" for your branch.'),
             'open_hint': T('تبويب «🚨 قرب الانتهاء» أو «📦 أرصدة الصلاحية».', '"🚨 Near expiry" or "📦 Expiry balances" tab.'),
             'more': T(
                 'المدة (30 / 90 / 180 يوم / سنة)، والفرع والمخزن بيضيّقوا القائمة، و«يشمل العزل/التالف» يضيف مخازن العزل.\n• في «أرصدة الصلاحية» تقدر تختار وضع «منتهية (متبقية)» أو «نطاق تاريخ الصلاحية».\n• «آخر مزامنة» بيقولك البيانات حديثة ولا لأ؛ «🔄 مزامنة الآن» بيسحب من SOFTECH من غير ما يكتب فيه.',
                 'The period (30 / 90 / 180 days / a year), branch and store narrow the list; "Include quarantine/damaged" adds quarantine stores.\n• In "Expiry balances" you can pick the "Expired (remaining)" or "Expiry date range" mode.\n• "Last sync" tells you how fresh the data is; "🔄 Sync now" reads from SOFTECH without writing to it.')},
            {'target': 'batches-main-sync', 'label': T('🔄 مزامنة الآن', '🔄 Sync now'),
             'text': T('يسحب أرصدة الصلاحية من SOFTECH لكل الفروع دلوقتي بدل انتظار المزامنة اليومية. قراءة بس.',
                       'Pulls expiry balances from SOFTECH for every branch now instead of waiting for the daily sync. Read only.'),
             'warn': T('بتاخد وقت وبتحمّل على سيرفرات الفروع. استخدمها لما البيانات تكون قديمة بس.', 'It takes time and loads the branch servers. Use it only when the data is stale.'),
             'open_hint': T('للمدير والمشرف فقط.', 'Admin and supervisor only.')},
            {'target': 'batches-main-filters', 'label': T('بحث بالاسم / الكود…', 'Search by name / code…'),
             'text': T('ابحث بالاسم أو الكود، وصفّي بالتصنيف العام، والمستورد، وأصناف الثلاجة. الترتيب من رأس أي عمود.',
                       'Search by name or code, and filter by general class, imported and fridge items. Sort from any column header.')},
            {'target': 'batches-main-export', 'label': T('⬇️ تصدير Excel', '⬇️ Export Excel'),
             'text': T('ينزّل الأصناف المعروضة بعد الفلاتر كملف Excel.', 'Downloads the items shown after filters as an Excel file.')},
            {'target': 'batches-main-count', 'label': T('▶️ بدء جرد مادي', '▶️ Start physical count'),
             'text': T('ينشئ جلسة جرد للأصناف المعروضة في الفرع المختار ويفتحها في شاشة الجرد.',
                       'Creates a count session for the items shown in the chosen branch and opens it on the count screen.'),
             'when': T('للتأكد من الصلاحية الفعلية على الرف قبل أي قرار.', 'To confirm the real expiry on the shelf before any decision.'),
             'open_hint': T('اختار فرع الأول — الزر مقفول على «كل الفروع».', 'Pick a branch first — the button is disabled on "All branches".')},
            {'target': 'batches-main-disposal-draft', 'label': T('🗑️ إتلاف/مرتجع', '🗑️ Dispose/Return'),
             'text': T('يفتح نموذج القرار: إتلاف، مرتجع للمورد، عزل، أو مراجعة، مع الكمية والسبب. «تسجيل القرار» يحفظه مسودة.',
                       'Opens the decision form: dispose, return to supplier, quarantine or review, with quantity and reason. "Record decision" saves a draft.'),
             'warn': T('ده سجل بس — مفيش خصم من SOFTECH. اتأكد من الكمية والفرع.', 'This is a record only — nothing is deducted in SOFTECH. Check the quantity and branch.'),
             'open_hint': T('عمود «إجراء» في أي سطر.', 'The "Action" column of any row.')},
            {'target': 'batches-main-audit-generate', 'label': T('توليد التقرير', 'Generate report'),
             'text': T('يجيب الأصناف الموجودة اللي اتسجل لها عند الشراء صلاحية داخل الفترة، مع القيمة المعرّضة وعمرها في الفرع.',
                       'Lists stocked items whose purchase-entered expiry falls in the range, with value at risk and stock age in the branch.'),
             'when': T('بعده: «⬇️ تصدير Excel» أو «▶️ بدء جرد مادي لهذه الأصناف».', 'Then: "⬇️ Export Excel" or "▶️ Start physical count for these items".'),
             'open_hint': T('تبويب «📅 تدقيق صلاحيات الشراء».', '"📅 Purchase-expiry audit" tab.')},
            {'target': 'batches-main-request-discount', 'label': T('💲 طلب خصم', '💲 Request discount'),
             'text': T('يبعت طلب خصم قرب الصلاحية للاعتماد في «اعتماد الأسعار» بعد تأكيد.',
                       'Sends a near-expiry discount request for approval in "Pricing approvals" after a confirm.'),
             'warn': T('ما بيتطبقش في SOFTECH إلا بعد الاعتماد. راجع التنبيه لو السعر أقل من التكلفة.',
                       'It is not applied in SOFTECH until approved. Read the alert if the price is below cost.'),
             'open_hint': T('في التقرير، لما يكون الخصم المقترح مفعّل للصنف.', 'In the report, when a suggested discount is enabled for the item.')},
            {'target': 'batches-main-rescue-transfer', 'label': T('مسودة تحويل', 'Draft transfer'),
             'text': T('ينشئ مسودة طلب تحويل للتشغيلة من فرعها لفرع بيبيعها أسرع، وتمشي في مسار التحويلات المعتاد.',
                       'Creates a draft transfer request for the batch from its branch to one that sells it faster, through the usual transfer flow.'),
             'when': T('الأقرب صلاحية أولاً. السطور من غير فرع يستوعبها تحتاج خصم أو مرتجع.', 'Earliest expiry first. Lines with no branch to absorb them need a discount or return.'),
             'open_hint': T('تبويب «🔁 إنقاذ قبل الانتهاء» — يحتاج تشغيل محرك الطلب.', '"🔁 Rescue before expiry" tab — needs the demand engine to have run.')},
            {'target': 'batches-main-disposal-approve', 'label': T('اعتماد', 'Approve'),
             'text': T('يعتمد قرار الإتلاف أو المرتجع عشان يتنفذ يدوياً في SOFTECH.', 'Approves the disposal or return decision so it can be applied manually in SOFTECH.'),
             'warn': T('راجع الصنف والكمية والقرار قبل الاعتماد.', 'Check the item, quantity and decision before approving.'),
             'open_hint': T('تبويب «🗑️ إتلاف/مرتجع»، قرار «مسودة» — للمدير والجودة والمشرف.', '"🗑️ Disposal/return" tab, a "draft" decision — admin, quality and supervisor.')},
            {'target': 'batches-main-disposal-done', 'label': T('تم التنفيذ', 'Done'),
             'text': T('يقفل القرار بعد ما تطبّقه بنفسك في SOFTECH. النظام ما بيخصمش المخزون.',
                       'Closes the decision after you apply it yourself in SOFTECH. The system never deducts stock.'),
             'warn': T('اضغطه بعد التنفيذ الفعلي في SOFTECH بس — الحالة نهائية.', 'Press it only after it is really applied in SOFTECH — the status is final.'),
             'open_hint': T('قرار «معتمد» — للمدير والجودة والمشرف.', 'An "approved" decision — admin, quality and supervisor.')},
            {'target': 'batches-main-header',  # from the GitHub-side tour
             'text': T('«إدارة الدفعات (FEFO)»: مراقبة الصلاحية — الأقرب انتهاءً يُصرف أولاً.',
                       '«Batch management (FEFO)»: expiry monitoring — first to expire goes out first.'),
             'more': T(
                 'الشاشة دي بتقرا أرصدة المخزون الفعلية بتواريخ صلاحيتها من SOFTECH في كل الفروع والمخازن (مزامنة يومية).\n• هدفها إننا نلحق الصنف قبل ما يخلص تاريخه: نصرفه الأول، ننقله لفرع بيبيعه أسرع، أو نقرر إتلاف/مرتجع.\n• النظام بيقترح بس — أي حركة مخزون حقيقية بتتعمل في SOFTECH.',
                 'This screen reads actual stock balances with their expiry dates from SOFTECH across every branch and store (daily sync).\n• The goal is to catch an item before it expires: sell it first, move it to a branch that sells it faster, or decide disposal/return.\n• The system only suggests — any real stock movement is done in SOFTECH.')},
            {'target': 'batches-main-kpis',  # from the GitHub-side tour
             'text': T('أصناف تنتهي خلال 30 و90 و180 يوماً، القيمة المعرّضة للخطر، والمنتهية بالمخزون.',
                       'Items expiring within 30, 90 and 180 days, value at risk, and expired items still in stock.'),
             'more': T(
                 'كل كارت فيه عدد الأصناف وقيمتها بالجنيه، محسوبة على كل الفروع.\n• «خلال 30 يوم» بالأحمر هو الأهم — دي اللي محتاجة تصرّف أو نقل فوراً.\n• «منتهية ولا تزال بالمخزون» لازم تتشال من الرف وياخد قرار إتلاف/مرتجع.',
                 'Each card shows the number of items and their value in EGP, across all branches.\n• "Within 30 days" in red matters most — these need selling or moving right away.\n• "Expired but still in stock" must come off the shelf and get a disposal/return decision.')},
            {'target': 'batches-main-actions',  # from the GitHub-side tour
             'text': T('«تصدير Excel» للقائمة، و«بدء جرد مادي» بعد اختيار فرع.',
                       '«Export Excel» for the list, and «Start physical count» once a branch is chosen.'),
             'more': T(
                 '• «⬇️ تصدير Excel» بينزّل القائمة زي ما هي معروضة (بعد الفلاتر).\n• «▶️ بدء جرد مادي» بيشتغل بس لما تختار فرع: بينشئ جلسة جرد صلاحية بالأصناف المعروضة ويفتحها في شاشة «الجرد الفعلي» عشان تتأكد من التواريخ على الرف.',
                 '• "⬇️ Export Excel" downloads the list exactly as shown (after filters).\n• "▶️ Start physical count" only works once a branch is chosen: it creates an expiry count session with the listed items and opens it in the "Stock count" screen so you can check the dates on the shelf.')},
            {'target': 'batches-main-table',  # from the GitHub-side tour
             'text': T('الأصناف بصلاحيتها وكمياتها؛ زر «إتلاف/مرتجع» يُنشئ مسودة قرار تحتاج اعتماداً.',
                       'Items with expiry and quantities; «Disposal/return» creates a draft decision that needs approval.'),
             'more': T(
                 'اضغط عنوان أي عمود للترتيب (مثلاً «قيمة معرّضة» أو «أقرب صلاحية»)، والصف الأحمر صنف منتهي.\n• «🗑️ إتلاف/مرتجع» بيفتح نافذة: القرار (إتلاف، مرتجع للمورد، عزل، مراجعة) والكمية والسبب، ثم «تسجيل القرار».\n• القرار بيتسجّل مسودة في تبويب «إتلاف/مرتجع» ومش بيخصم من SOFTECH.',
                 'Click any column title to sort (e.g. "Value at risk" or "Earliest expiry"); a red row is an expired item.\n• "🗑️ Disposal/return" opens a window: the decision (destroy, return to supplier, quarantine, review), quantity and reason, then "Record decision".\n• The decision is saved as a draft in the "Disposal/return" tab and deducts nothing in SOFTECH.')},
        ],
        'updated': '2026-10-26',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
    },
]
