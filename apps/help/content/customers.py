from . import T

MODULE = {
    'key': 'customers', 'group': 'customers', 'icon': '👥',
    'title': T('العملاء', 'Customers'),
    'summary': T(
        'ملف كامل لكل عميل (360°) مبني على بيانات SOFTECH: مشترياته ومرتجعاته، حجوزاته، أدويته المزمنة وملفه الصحي (حساسية، حمل، أطفال)، '
        'نقاط الولاء، وقيمته وخطر انقطاعه عن الشراء. الكود الموحّد للعميل هو «PIC». يوجد أيضاً «دمج الأكواد المكررة» لنفس العميل.',
        'A complete (360°) profile per customer built from SOFTECH data: purchases and returns, reservations, chronic medicines and health '
        'profile (allergies, pregnancy, children), loyalty points, and their value and churn risk. The customer\'s unified code is the "PIC". '
        'There is also "merge duplicate codes" for the same customer.'),
    'workflows': [{
        'key': 'merge',
        'title': T('دمج الأكواد المكررة (مراجع + معتمد)', 'Merging duplicate codes (maker + checker)'),
        'model': 'customers.MergeCandidate', 'field': 'status',
        'intro': T('مراجع يعلّم الزوج، ومراجع آخر مختلف يعتمده. الاعتماد لا يكتب في SOFTECH؛ الدمج الفعلي (نقل النقاط وإغلاق الكود المكرر) خطوة منفصلة ينفذها المدير.',
                   'One reviewer marks the pair, a different reviewer approves it. Approval does not write to SOFTECH; the actual merge (moving points and closing the duplicate code) is a separate step run by the admin.'),
        'states': [
            {'key': 'proposed', 'label': T('مقترح', 'Proposed'), 'desc': T('اكتشفه الفحص الأسبوعي: نفس الاسم (أو مشابه) على رقم هاتف حقيقي مشترك.', 'Found by the weekly scan: same (or similar) name on a real shared phone.'), 'next': ['marked', 'rejected']},
            {'key': 'marked', 'label': T('معلَّم — بانتظار الاعتماد', 'Marked — awaiting approval'), 'desc': T('علّمه مراجع؛ يجب أن يعتمده مراجع آخر.', 'A reviewer marked it; another reviewer must approve.'), 'next': ['approved', 'rejected']},
            {'key': 'approved', 'label': T('معتمد — بانتظار الدمج', 'Approved — awaiting merge'), 'desc': T('جاهز للدمج الفعلي في SOFTECH.', 'Ready for the actual merge in SOFTECH.'), 'next': ['merged', 'failed']},
            {'key': 'merged', 'label': T('تم الدمج', 'Merged'), 'desc': T('نُقلت النقاط للكود الرئيسي وأُغلق الكود المكرر.', 'Points moved to the main code and the duplicate code closed.')},
            {'key': 'failed', 'label': T('فشل الدمج', 'Merge failed'), 'desc': T('توقف الدمج عند مشكلة — يراجعها المدير.', 'The merge stopped at a problem — the admin reviews it.')},
            {'key': 'rejected', 'label': T('مرفوض', 'Rejected'), 'desc': T('ليس نفس العميل (مع ذكر السبب).', 'Not the same customer (with a reason).')},
            {'key': 'stale', 'label': T('لم يعد مكرراً', 'No longer a duplicate'), 'desc': T('تغيّرت البيانات فلم يعد الزوج مكرراً.', 'The data changed so the pair is no longer a duplicate.')},
        ],
    }],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول العملاء', 'A tour of the customers module'),
            'summary': T('إزاي تلاقي أي عميل وترتّب العملاء حسب خطر الانقطاع، وبعدين تفتح ملفه الكامل (360°): مشترياته من SOFTECH وحجوزاته وأدويته المزمنة ونقاطه، وتسجّل ملاحظة أو تعمل له حجز.',
                         'How to find any customer and sort customers by churn risk, then open their full (360°) profile: SOFTECH purchases, reservations, chronic medicines and points, and add a note or create a reservation.'),
            'steps': [
                {'target': 'nav-customers', 'nav': '/customers',
                 'text': T('«العملاء» ← «العملاء».', '"Customers" → "Customers".'),
                 'more': T('قائمة كل العملاء المسجّلين، مبنية على بيانات SOFTECH (المشتريات والمرتجعات) اللي بتتزامن هنا.\n'
                           '• منها بتوصل لملف أي عميل.\n'
                           '• الملف بيجمّع بيانات من موديولات تانية: الحجوزات، متابعة المزمن، والنقاط.',
                           'The list of every registered customer, built on SOFTECH data (purchases and returns) synced here.\n'
                           '• From it you reach any customer\'s profile.\n'
                           '• The profile pulls data from other modules: reservations, chronic follow-up and points.')},
                {'target': 'customers-list-search', 'route': '/customers',
                 'text': T('ابحث بالاسم أو الهاتف أو كود SOFTECH.', 'Search by name, phone or SOFTECH code.'),
                 'more': T('اكتب جزء من الاسم أو الرقم والنتايج بتتحدّث وانت بتكتب.\n'
                           '• «مسح ✕» بيظهر جنب الفلاتر يرجّع القائمة كاملة.',
                           'Type part of the name or number and results update as you type.\n'
                           '• "Clear ✕" appears beside the filters to bring the full list back.')},
                {'target': 'customers-list-churn', 'route': '/customers',
                 'text': T('فلتر «خطر الانقطاع»: حرج، مرتفع، متوسط، مستقر.', 'The "churn risk" filter: critical, high, medium, stable.'),
                 'more': T('خطر الانقطاع بيتحسب يومياً من انتظام شراء العميل.\n'
                           '• «🚨 انقطاع حرج» = غاب أطول بكتير من عادته — دول أولى ناس بالاتصال.\n'
                           '• استخدمه قبل حملة تواصل أو متابعة.',
                           'Churn risk is calculated daily from how regularly the customer buys.\n'
                           '• "🚨 Critical churn" = absent much longer than usual — call these first.\n'
                           '• Use it before a contact campaign or follow-up.')},
                {'target': 'customers-list-sort', 'route': '/customers',
                 'text': T('الترتيب: الاسم، خطر الانقطاع، القيمة (LTV)، الغياب، أو آخر زيارة.', 'Sort: name, churn risk, value (LTV), absence or last visit.'),
                 'more': T('• «الأعلى قيمة (LTV)» يوريك أهم العملاء من ناحية إجمالي الشراء.\n'
                           '• «الأطول غياباً» يوريك اللي بقالهم كتير ما جوش.\n'
                           '• الترتيب بيرجّعك للصفحة الأولى.',
                           '• "Highest value (LTV)" shows your most important customers by total spend.\n'
                           '• "Longest absent" shows those who have not come for a long time.\n'
                           '• Changing the sort takes you back to page one.')},
                {'target': 'customers-list-table', 'route': '/customers', 'wait': '/customers/:id',
                 'text': T('افتح أي عميل — الجولة هتكمّل على ملفه. لو القائمة فاضية اضغط «إنهاء».',
                           'Open any customer — the tour continues on their profile. If the list is empty, press "End".'),
                 'more': T('الجدول فيه الاسم والهاتف والقناة/الشريحة وخطر الانقطاع وآخر زيارة والفرع.\n'
                           '• اضغط على الصف يفتح ملف العميل الكامل.',
                           'The table shows name, phone, channel/segment, churn risk, last visit and branch.\n'
                           '• Click the row to open the customer\'s full profile.')},
                {'target': 'customers-detail-identity', 'route': '/customers/:id',
                 'text': T('اسم العميل ونوعه وكود SOFTECH.', 'The customer\'s name, type and SOFTECH code.'),
                 'more': T('أول حاجة تتأكد منها إنك على العميل الصح.\n'
                           '• علامة «💊 مزمن» معناها إن عنده أدوية مزمنة متابَعة.\n'
                           '• كود SOFTECH هو اللي بيربط الملف بفواتيره ونقاطه.',
                           'First make sure you are on the right customer.\n'
                           '• The "💊 Chronic" badge means they have chronic medicines being followed.\n'
                           '• The SOFTECH code links the profile to their invoices and points.')},
                {'target': 'customers-detail-kpis', 'route': '/customers/:id',
                 'text': T('ملخص: عدد الفواتير، الإجمالي بالجنيه، والحجوزات النشطة.', 'Summary: invoices, total in EGP, and active reservations.'),
                 'more': T('تحتها البطاقة الجانبية: الشريحة، خطر الانقطاع، وأيام من آخر زيارة.\n'
                           '• لو ظهر «⚡ يُنصح بالتواصل مع هذا العميل فوراً» كلّمه.',
                           'Below it is the side card: segment, churn risk and days since the last visit.\n'
                           '• If "⚡ Contact this customer now" shows, call them.')},
                {'target': 'customers-detail-tabs', 'route': '/customers/:id',
                 'text': T('التبويبات: الجدول الزمني، المشتريات، الحجوزات، المزمن، الصحة، النقاط وغيرها.', 'Tabs: timeline, purchases, reservations, chronic, health, points and more.'),
                 'more': T('• «المشتريات»: فواتير ومرتجعات SOFTECH.\n'
                           '• «💊 المزمن»: أدويته المزمنة وميعاد الصرف الجاي (من موديول المتابعة).\n'
                           '• «🏥 الصحة»: الحساسيات والحمل والأطفال — معلومة حساسة.\n'
                           '• «🏆 النقاط»: رصيد SOFTECH وتعديله لمن عنده صلاحية.',
                           '• "Purchases": SOFTECH invoices and returns.\n'
                           '• "💊 Chronic": chronic medicines and the next refill (from the follow-up module).\n'
                           '• "🏥 Health": allergies, pregnancy and children — sensitive data.\n'
                           '• "🏆 Points": the SOFTECH balance and adjusting it, for those allowed.')},
                {'target': 'customers-detail-note', 'route': '/customers/:id',
                 'text': T('اكتب ملاحظة عن العميل — Ctrl+Enter للحفظ.', 'Write a note about the customer — Ctrl+Enter saves.'),
                 'more': T('في تبويب «الجدول الزمني»: سجّل أي حاجة زمايلك محتاجين يعرفوها (طلب خاص، تعليق طبي، شكوى).\n'
                           '• بتتحفظ بـ«إرسال» أو Ctrl+Enter وتظهر في الجدول الزمني باسمك.',
                           'On the "Timeline" tab: record anything colleagues should know (a special request, a medical comment, a complaint).\n'
                           '• It saves with "Send" or Ctrl+Enter and shows on the timeline under your name.')},
                {'target': 'customers-detail-new-reservation', 'route': '/customers/:id',
                 'text': T('«+ حجز جديد» يفتح شاشة تسجيل حجز.', '"+ New reservation" opens the new reservation screen.'),
                 'more': T('لما العميل يطلب صنف مش موجود، سجّل له حجز من هنا (موديول الحجوزات).\n'
                           '• اختار العميل في شاشة الحجز وكمّل الأصناف ورقم التواصل.\n'
                           '• الحجز بعد كده بيظهر في تبويب «الحجوزات» هنا.',
                           'When the customer asks for an item that is not available, log a reservation from here (reservations module).\n'
                           '• Pick the customer on the reservation screen and fill in the items and contact phone.\n'
                           '• The reservation then appears in the "Reservations" tab here.')},
            ],
        },
        {
            'key': 'merge',
            'title': T('دمج الأكواد المكررة', 'Merging duplicate codes'),
            'summary': T('إزاي تراجع كودين SOFTECH لنفس العميل على نفس الرقم، تعلّمهم للدمج أو ترفضهم، ومراجع تاني يعتمد.',
                         'How to review two SOFTECH codes for the same customer on the same phone, mark them for merge or reject them, and have another reviewer approve.'),
            'roles': ['admin', 'supervisor', 'call_center'],
            'steps': [
                {'target': 'nav-customers-merge', 'nav': '/customers/merge',
                 'text': T('«العملاء» ← «دمج الأكواد المكررة».', '"Customers" → "Merge duplicate codes".'),
                 'more': T('نفس العميل أحياناً بيتعمل له أكتر من كود في SOFTECH، فنقاطه وتاريخه بيتقسموا.\n'
                           '• الشاشة دي بتعرض الأزواج اللي الفحص الأسبوعي لقاها على رقم هاتف واحد.',
                           'The same customer sometimes gets more than one SOFTECH code, so their points and history get split.\n'
                           '• This screen lists the pairs the weekly scan found on one phone number.')},
                {'target': 'customers-merge-status', 'route': '/customers/merge',
                 'text': T('ابدأ بـ«مقترح»، والمعلَّم من غيرك في «بانتظار الاعتماد».', 'Start with "Proposed"; pairs marked by others are in "Awaiting approval".'),
                 'more': T('الرقم جنب كل حالة هو عدد الأزواج فيها.\n'
                           '• «معتمد» = جاهز للدمج الفعلي اللي بينفذه المدير.',
                           'The number beside each status is its pair count.\n'
                           '• "Approved" = ready for the actual merge run by the admin.')},
                {'target': 'customers-merge-list', 'route': '/customers/merge',
                 'text': T('قارن «الكود المكرر (يُغلق)» بـ«الكود الرئيسي».', 'Compare the "duplicate code (to be closed)" with the "main code".'),
                 'more': T('لكل كود: الفرع، تاريخ الإنشاء، النقاط، آخر بيع والحالة، والهاتف المشترك.\n'
                           '• اتأكد إنه فعلاً نفس الشخص مش حد من نفس الأسرة.',
                           'For each code: branch, creation date, points, last sale and status, plus the shared phone.\n'
                           '• Make sure it really is the same person, not a family member.')},
                {'target': 'customers-merge-actions', 'route': '/customers/merge',
                 'text': T('«تعليم للدمج» أو «اعتماد» أو «ليس نفس العميل».', '"Mark for merge", "Approve" or "Not the same customer".'),
                 'more': T('• اللي يعلّم ما يقدرش يعتمد نفس الزوج — لازم مراجع تاني.\n'
                           '• «ليس نفس العميل» بيطلب سبب.\n'
                           '• الاعتماد هنا ما بيكتبش في SOFTECH.',
                           '• Whoever marks a pair cannot approve it — another reviewer must.\n'
                           '• "Not the same customer" asks for a reason.\n'
                           '• Approving here does not write to SOFTECH.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'customers.list',
        'routes': ['/customers'],
        'title': T('العملاء', 'Customers'),
        'summary': T('البحث في كل العملاء المسجّلين وترتيبهم حسب خطر الانقطاع أو القيمة (LTV) أو الغياب أو آخر زيارة.',
                     'Search all registered customers and sort them by churn risk, value (LTV), absence or last visit.'),
        'audience': T('كل من يتعامل مع العملاء.', 'Everyone who deals with customers.'),
        'steps': [
            T('ابحث بالاسم أو رقم الهاتف أو كود SOFTECH.', 'Search by name, phone or SOFTECH code.'),
            T('صفِّ بخطر الانقطاع (حرج / مرتفع / متوسط / مستقر) لاستهداف من يحتاج تواصلاً.', 'Filter by churn risk (critical / high / medium / stable) to target who needs contact.'),
            T('اضغط العميل لفتح ملفه الكامل.', 'Click a customer to open their full profile.'),
        ],
        'tips': [T('«خطر الانقطاع» يُحسب يومياً من انتظام مشتريات العميل؛ «حرج» = غاب أطول بكثير من عادته.', '"Churn risk" is calculated daily from the customer\'s buying pattern; "critical" = absent much longer than usual.')],
        'related': ['customers.detail', 'customers.merge'],
        'workflows': [],
        'tour': [
            {'target': 'customers-list-search', 'text': T('ابحث بالاسم أو الهاتف أو كود SOFTECH.',
                                              'Search by name, phone or SOFTECH code.'),
             'more': T('أسرع طريقة توصل لعميل: اكتب جزء من اسمه أو رقمه أو كوده، والنتايج بتتحدّث وانت بتكتب.\n'
                       '• «مسح ✕» جنب الفلاتر بيرجّع القائمة كلها.',
                       'The fastest way to reach a customer: type part of their name, phone or code, and results update as you type.\n'
                       '• "Clear ✕" beside the filters brings the whole list back.')},
            {'target': 'customers-list-churn', 'text': T('فلتر «خطر الانقطاع» (مثلاً اللي بطّلوا يشتروا).',
                                              'The "churn risk" filter (for example those who stopped buying).'),
             'more': T('الاختيارات: «كل العملاء»، «🚨 انقطاع حرج»، «🔴 انقطاع مرتفع»، «⚠️ انقطاع متوسط»، «✅ مستقر».\n'
                       '• بيتحسب يومياً من انتظام شراء العميل.\n'
                       '• «حرج» = غاب أطول بكتير من عادته — ابدأ بيهم في الاتصالات.',
                       'Options: "All customers", "🚨 Critical churn", "🔴 High churn", "⚠️ Medium churn", "✅ Stable".\n'
                       '• It is calculated daily from how regularly the customer buys.\n'
                       '• "Critical" = absent much longer than usual — start your calls with them.')},
            {'target': 'customers-list-sort', 'text': T('الترتيب: الاسم، خطر الانقطاع، القيمة، الغياب، أو آخر زيارة.',
                                              'Sort: name, churn risk, value, absence or last visit.'),
             'more': T('• «الأعلى خطر انقطاع» للمتابعة.\n'
                       '• «الأعلى قيمة (LTV)» لأهم العملاء من ناحية إجمالي الشراء.\n'
                       '• «الأطول غياباً» و«آخر زيارة» لمعرفة مين بقاله كتير ما جاش.',
                       '• "Highest churn risk" for follow-up.\n'
                       '• "Highest value (LTV)" for your top customers by total spend.\n'
                       '• "Longest absent" and "Last visit" to see who has not come for a while.')},
            {'target': 'customers-list-table', 'text': T('العملاء — افتح أي عميل لملفه الكامل.',
                                              'The customers — open one for the full profile.'),
             'more': T('الأعمدة: الاسم، الهاتف، القناة/الشريحة، خطر الانقطاع، آخر زيارة، والفرع.\n'
                       '• اضغط على الصف يفتح ملف العميل (360°) بمشترياته وحجوزاته ونقاطه.',
                       'Columns: name, phone, channel/segment, churn risk, last visit and branch.\n'
                       '• Click a row to open the customer\'s 360° profile with purchases, reservations and points.')},
            {'target': 'customers-list-pages', 'text': T('التنقل بين الصفحات.',
                                              'Move between pages.'),
             'more': T('بيوضح «صفحة x من y» وعدد النتايج الكلي، و«← السابق» و«التالي →».\n'
                       '• لو النتايج كتير، ضيّق بالبحث أو الفلتر أحسن من التقليب.',
                       'Shows "page x of y" and the total results, with "← Previous" and "Next →".\n'
                       '• With many results, narrow by search or filter rather than paging.')},
            {'target': 'customers-list-table', 'wait': '/customers/:id',
             'text': T('افتح أي عميل — الجولة هتكمّل على ملفه. لو القائمة فاضية اضغط «إنهاء».',
                       'Open any customer — the tour continues on their profile. If the list is empty, press "End".'),
             'more': T('اضغط على أي صف في الجدول، والجولة هتكمّل على صفحة ملفه وتشرح أجزاءها.',
                       'Click any row in the table and the tour carries on on their profile page, explaining its parts.')},
        ],
        'tour_continue': 'customers.detail',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'customers.detail',
        'routes': ['/customers/:id'],
        'title': T('ملف العميل (360°)', 'Customer profile (360°)'),
        'summary': T('كل ما يخص العميل في صفحة واحدة: بطاقة العميل وقيمته وخطر انقطاعه وبيانات التواصل يميناً، والتبويبات للتفاصيل. منها تنشئ حجزاً أو تسجّل ملاحظة أو تعدّل نقاطه.',
                     'Everything about the customer on one page: their card, value, churn risk and contact data on the side, with tabs for detail. From here you create a reservation, add a note or adjust points.'),
        'audience': T('الصيادلة والكول سنتر والمشرفون.', 'Pharmacists, call center and supervisors.'),
        'tabs': [
            {'key': 'timeline', 'title': T('الجدول الزمني', 'Timeline'), 'body': T('الملاحظات والحجوزات الأخيرة، وخانة لإضافة ملاحظة أو تعليق طبي (Ctrl+Enter).', 'Recent notes and reservations, and a box to add a note or medical comment (Ctrl+Enter).')},
            {'key': 'purchases', 'title': T('المشتريات', 'Purchases'), 'body': T('فواتير المبيعات والمرتجعات المتزامنة من SOFTECH مع إجمالي المشتريات؛ صفِّ (الكل / مبيعات / مرتجعات).', 'Sales and return invoices synced from SOFTECH with the purchase total; filter (all / sales / returns).')},
            {'key': 'reservations', 'title': T('الحجوزات', 'Reservations'), 'body': T('كل حجوزات العميل وحالاتها.', 'All the customer\'s reservations and their status.')},
            {'key': 'top', 'title': T('الأدوية الأكثر شراءً', 'Most-bought medicines'), 'body': T('الأصناف التي يشتريها العميل أكثر — مفيدة للتوصية والمتابعة.', 'The items the customer buys most — useful for suggestions and follow-up.')},
            {'key': 'chronic', 'title': T('💊 المزمن', '💊 Chronic'), 'body': T('أدويته المزمنة مع آخر شراء والجرعة/الصرف التالي والمتأخر، والمتابعات النشطة.', 'Their chronic medicines with last purchase, next refill and overdue ones, and active follow-ups.')},
            {'key': 'health', 'title': T('🏥 الصحة', '🏥 Health'),
             'body': T('الملف الصحي المنظّم: الحالات المزمنة المكتشفة من المشتريات، تنبيهات خاصة (حامل، مرضعة، يشتري لطفل، أدوية متعددة)، الحساسيات، والأدوية النشطة. «بناء/تحديث الملف» يعيد حسابه؛ التعديل اليدوي يمنع إعادة الحساب التلقائي.',
                       'The structured health profile: chronic conditions found from purchases, special alerts (pregnant, breastfeeding, buys for a child, polypharmacy), allergies and active medicines. "Build/refresh" recalculates it; a manual edit stops automatic recalculation.')},
            {'key': 'fulltimeline', 'title': T('📅 التاريخ الكامل', '📅 Full history'), 'body': T('كل الأحداث مرتبة زمنياً: بيع، مرتجع، حجز، طلب، متابعة.', 'Every event in time order: sale, return, reservation, request, follow-up.')},
            {'key': 'loyalty', 'title': T('🏆 النقاط', '🏆 Points'),
             'body': T('رصيد نقاط SOFTECH (لكل الفروع) وسجل التعديلات. «تعديل النقاط» يضيف أو يخصم (برقم موجب أو سالب) مع سبب إلزامي ويُنفَّذ في SOFTECH.',
                       'The SOFTECH points balance (all branches) and the adjustment log. "Adjust points" adds or subtracts (positive or negative) with a required reason and is applied in SOFTECH.')},
        ],
        'steps': [
            T('راجع البطاقة الجانبية: الشريحة، خطر الانقطاع، وعدد الأيام منذ آخر زيارة — لو ظهر «يُنصح بالتواصل فوراً» اتصل به.', 'Check the side card: segment, churn risk and days since last visit — if "contact now" shows, call them.'),
            T('سجّل الأمراض المزمنة في البطاقة (تعديل) لو العميل أخبرك بها.', 'Record chronic conditions on the card (edit) if the customer tells you.'),
            T('استخدم الإجراءات السريعة لإنشاء حجز أو طلب له مباشرةً.', 'Use the quick actions to create a reservation or request for them directly.'),
        ],
        'tips': [
            T('الملف الصحي معلومة حساسة — لا تشاركها خارج العمل.', 'The health profile is sensitive — never share it outside work.'),
            T('تعديل النقاط يؤثر على رصيد العميل في كل الفروع ويُسجَّل باسمك.', 'Adjusting points affects the customer\'s balance in all branches and is recorded under your name.'),
        ],
        'related': ['customers.list', 'reservations.new', 'followups.tasks', 'loyalty.program'],
        'workflows': [],
        'tour': [
            {'target': 'customers-detail-identity', 'text': T('بيانات العميل ونوعه وكود SOFTECH.',
                                              'The customer\'s details, type and SOFTECH code.'),
             'more': T('الاسم ونوع العميل، وعلامة «💊 مزمن» لو عنده أدوية مزمنة متابَعة.\n'
                       '• كود SOFTECH هو اللي بيربط الملف بفواتيره ونقاطه — اتأكد منه قبل أي تعديل.\n'
                       '• السهم جنب الاسم بيرجّعك للقائمة.',
                       'The name and customer type, and a "💊 Chronic" badge if they have chronic medicines being followed.\n'
                       '• The SOFTECH code links the profile to their invoices and points — check it before any change.\n'
                       '• The arrow beside the name takes you back to the list.')},
            {'target': 'customers-detail-new-reservation', 'text': T('«+ حجز جديد» يفتح شاشة تسجيل حجز.',
                                              '"+ New reservation" opens the new reservation screen.'),
             'more': T('استخدمه لما العميل يطلب صنف مش موجود أو عايز يحجزه.\n'
                       '• في شاشة الحجز اختار العميل وكمّل الأصناف والقناة ورقم التواصل، وبعدين «✅ إنشاء الحجز».\n'
                       '• الحجز بيظهر بعد كده في تبويب «الحجوزات» هنا.',
                       'Use it when the customer asks for an item that is not available or wants it held.\n'
                       '• On the reservation screen pick the customer and fill in the items, channel and contact phone, then "✅ Create reservation".\n'
                       '• The reservation then appears in the "Reservations" tab here.')},
            {'target': 'customers-detail-tabs', 'text': T('التبويبات: الجدول الزمني، المشتريات، الحجوزات، المزمن، الصحة، النقاط وغيرها.',
                                              'Tabs: timeline, purchases, reservations, chronic, health, points and more.'),
             'more': T('• «المشتريات»: فواتير ومرتجعات SOFTECH، و«الأدوية الأكثر شراءً».\n'
                       '• «💊 المزمن» و«🏥 الصحة»: الأدوية المزمنة والحساسيات والحمل — معلومات حساسة.\n'
                       '• «📅 التاريخ الكامل»: كل حدث بالترتيب.\n'
                       '• «🏆 النقاط»: رصيد SOFTECH و«✎ تعديل النقاط» بسبب إلزامي لمن عنده صلاحية.',
                       '• "Purchases": SOFTECH invoices and returns, and "Most-bought medicines".\n'
                       '• "💊 Chronic" and "🏥 Health": chronic medicines, allergies and pregnancy — sensitive data.\n'
                       '• "📅 Full history": every event in order.\n'
                       '• "🏆 Points": the SOFTECH balance and "✎ Adjust points" with a required reason, for those allowed.')},
            {'target': 'customers-detail-note', 'text': T('اكتب ملاحظة عن العميل — Ctrl+Enter للحفظ.',
                                              'Write a note about the customer — Ctrl+Enter saves.'),
             'more': T('في تبويب «الجدول الزمني»: ملاحظة أو تعليق طبي أو تحديث، زي «بيفضّل التوصيل بعد العصر».\n'
                       '• بتتحفظ بـ«إرسال» أو Ctrl+Enter وتظهر في الجدول الزمني باسمك عشان زمايلك يشوفوها.',
                       'On the "Timeline" tab: a note, medical comment or update, like "prefers delivery in the afternoon".\n'
                       '• It saves with "Send" or Ctrl+Enter and appears on the timeline under your name for colleagues to see.')},
            {'target': 'customers-detail-kpis', 'text': T('ملخص: عدد الفواتير، الإجمالي، والحجوزات النشطة.',
                                              'Summary: invoices, total, and active reservations.'),
             'more': T('«فاتورة» = عدد فواتيره، «إجمالي (ج.م)» = قيمة مشترياته، و«حجز نشط» بيتلوّن لو عنده حجز مفتوح.\n'
                       '• تحته البطاقة الجانبية: الشريحة وخطر الانقطاع وأيام من آخر زيارة؛ ولو ظهر «⚡ يُنصح بالتواصل مع هذا العميل فوراً» كلّمه.',
                       '"Invoice" = number of invoices, "Total (EGP)" = their spend, and "Active reservation" is highlighted when one is open.\n'
                       '• Below it is the side card: segment, churn risk and days since the last visit; if "⚡ Contact this customer now" shows, call them.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'customers.merge',
        'routes': ['/customers/merge'],
        'title': T('دمج الأكواد المكررة', 'Merge duplicate codes'),
        'summary': T('أكواد SOFTECH مختلفة لنفس العميل على نفس رقم الهاتف. الأسماء المختلفة على نفس الرقم تعتبر أسرة ولا تُقترح. النظام يختار الكود الرئيسي (الأقدم إنشاءً ← الأعلى نقاطاً ← الأحدث بيعاً) ويمكن تبديله.',
                     'Different SOFTECH codes for the same customer on the same phone. Different names on one phone count as a family and are never proposed. The system picks the main code (oldest → most points → latest sale), which can be swapped.'),
        'audience': T('المدير والمشرف والكول سنتر.', 'Admin, supervisor and call center.'),
        'steps': [
            T('صفِّ بالحالة والدرجة (قوي = نفس الاسم والعنوان، نفس الاسم، للمراجعة = اسم مشابه).', 'Filter by status and strength (strong = same name and address, same name, review = similar name).'),
            T('قارن الكودين: تاريخ الإنشاء، النقاط، آخر بيع، الحالة (نشط/مغلق/متوفى).', 'Compare the two codes: creation date, points, last sale, status (active/closed/deceased).'),
            T('«تعليم للدمج» (أو «اجعل … الرئيسي» لتبديل الرئيسي)، أو «ليس نفس العميل» مع السبب.', '"Mark for merge" (or "make … the main" to swap), or "Not the same customer" with a reason.'),
            T('مراجع آخر يضغط «اعتماد» على ما علّمه غيره. يوجد زر لتعليم/اعتماد الأزواج القوية دفعة واحدة (حتى 100).', 'Another reviewer presses "Approve" on what someone else marked. A button marks/approves strong pairs in bulk (up to 100).'),
        ],
        'tips': [T('لا يمكنك اعتماد ما علّمته أنت — هذا مقصود للحماية.', 'You cannot approve what you marked yourself — this is on purpose.')],
        'related': ['customers.list'],
        'workflows': ['merge'],
        'tour': [
            {'target': 'customers-merge-header', 'text': T('دي شاشة الأكواد المكررة لنفس العميل على رقم هاتف واحد؛ الاعتماد هنا مش بيكتب في SOFTECH.',
                                              'This screen lists duplicate codes for one customer on one phone; approving here does not write to SOFTECH.'),
             'more': T('لما نفس العميل يتعمل له كودين، نقاطه وتاريخه بيتقسموا عليهم.\n'
                       '• الأسماء المختلفة على نفس الرقم بتتعتبر أسرة ومش بتتقترح.\n'
                       '• الدمج الفعلي (نقل النقاط وغلق الكود المكرر) بينفذه المدير بعد الاعتماد.',
                       'When one customer gets two codes, their points and history are split between them.\n'
                       '• Different names on the same phone count as a family and are never proposed.\n'
                       '• The actual merge (moving points and closing the duplicate) is run by the admin after approval.')},
            {'target': 'customers-merge-status', 'text': T('فلتر الحالة: «مقترح»، «بانتظار الاعتماد»، «معتمد»… والرقم جنب كل حالة هو العدد.',
                                              'Status filter: "Proposed", "Awaiting approval", "Approved"… the number beside each is the count.'),
             'more': T('• «مقترح»: لقاه الفحص ولسه محدش راجعه — ابدأ هنا.\n'
                       '• «بانتظار الاعتماد»: مراجع علّمه، ومستني مراجع تاني.\n'
                       '• «معتمد» و«تم الدمج» و«فشل الدمج» و«مرفوض» للمتابعة.',
                       '• "Proposed": found by the scan, not reviewed yet — start here.\n'
                       '• "Awaiting approval": a reviewer marked it and it waits for another.\n'
                       '• "Approved", "Merged", "Merge failed" and "Rejected" are for follow-up.')},
            {'target': 'customers-merge-strength', 'text': T('فلتر الدرجة: «قوي» أو «نفس الاسم» أو «للمراجعة».',
                                              'Strength filter: "Strong", "Same name" or "Review".'),
             'more': T('«قوي» = نفس الاسم والعنوان، «نفس الاسم»، و«للمراجعة» = اسم مشابه بس — دي محتاجة تركيز أكتر.\n'
                       '• في «مقترح» بيظهر زر «تعليم القوية (حتى 100)»، وفي «بانتظار الاعتماد» زر «اعتماد القوية التي علّمها غيري (حتى 100)».',
                       '"Strong" = same name and address, "Same name", and "Review" = only a similar name — these need the most care.\n'
                       '• Under "Proposed" a "Mark strong ones (up to 100)" button shows, and under "Awaiting approval" an "Approve strong ones marked by others (up to 100)" button.')},
            {'target': 'customers-merge-search', 'text': T('ابحث بكود العميل.',
                                              'Search by customer code.'),
             'more': T('اكتب كود PIC لما عميل يشتكي إن نقاطه ناقصة أو إن عنده كودين، وشوف لو له زوج هنا.',
                       'Type a PIC when a customer complains their points are missing or that they have two codes, and see whether they have a pair here.')},
            {'target': 'customers-merge-list', 'text': T('كل صف بيقارن الكود المكرر بالكود الرئيسي: الفرع، تاريخ الإنشاء، النقاط، آخر بيع والحالة.',
                                              'Each row compares the duplicate code with the main code: branch, creation date, points, last sale and status.'),
             'more': T('يمين «الكود المكرر (يُغلق)» وجنبه «الكود الرئيسي»، ومعاهم الدرجة والهاتف المشترك ومين علّم أو اعتمد.\n'
                       '• النظام بيختار الرئيسي: الأقدم إنشاءً ثم الأعلى نقاطاً ثم الأحدث بيعاً.',
                       'The "Duplicate code (to be closed)" sits beside the "Main code", with the strength, shared phone and who marked or approved.\n'
                       '• The system picks the main code: oldest first, then most points, then latest sale.')},
            {'target': 'customers-merge-actions', 'text': T('على الأزواج المفتوحة: «تعليم للدمج» أو «اعتماد» (مراجع غير اللي علّم) أو تبديل الرئيسي أو «ليس نفس العميل».',
                                              'On open pairs: "Mark for merge", "Approve" (by a different reviewer), swap the main code, or "Not the same customer".'),
             'more': T('• «تعليم للدمج» على المقترح، و«اعتماد» على المعلَّم — ومقفول لو انت اللي علّمته.\n'
                       '• «اجعل … الرئيسي» يبدّل الكودين لو المكرر هو الأصح.\n'
                       '• «ليس نفس العميل» بيطلب «السبب» وبعدين «رفض».',
                       '• "Mark for merge" on proposed pairs, and "Approve" on marked ones — disabled if you marked it yourself.\n'
                       '• "Make … the main" swaps the codes when the duplicate is the better one.\n'
                       '• "Not the same customer" asks for a "Reason", then "Reject".')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'customers.mobile',
        'routes': ['/m/customers'],
        'title': T('بحث العملاء (موبايل)', 'Customer lookup (mobile)'),
        'summary': T('على الكاونتر: امسح رمز QR الخاص بالعميل أو ابحث بالاسم/الهاتف/PIC لترى ملفه ونقاطه (نقاط الشراء من SOFTECH ونقاط الإحالة) وآخر حجوزاته، واستبدل النقاط بمكافأة بضغطة.',
                     'At the counter: scan the customer\'s QR code or search by name/phone/PIC to see their profile, points (SOFTECH purchase points and referral points) and recent reservations, and redeem points for a reward in one tap.'),
        'audience': T('الصيادلة والمندوبون.', 'Pharmacists and salespeople.'),
        'steps': [
            T('«مسح رمز العميل (QR)» أو اكتب في البحث.', '"Scan customer QR" or type in the search.'),
            T('«استبدال» على المكافأة المناسبة؛ يُنشأ طلب استبدال بانتظار الاعتماد.', '"Redeem" on the right reward; a redemption request is created, awaiting approval.'),
        ],
        'related': ['loyalty.program'],
        'workflows': [],
        'tour': [
            {'target': 'customers-mobile-search', 'text': T('ابحث عن العميل بالاسم أو الهاتف.',
                                              'Search the customer by name or phone.'),
             'more': T('اكتب الاسم أو الرقم واختار العميل من النتايج.\n'
                       '• بعد الاختيار بتظهر تحت نقاطه ومكافآته وآخر حجوزاته.',
                       'Type the name or number and pick the customer from the results.\n'
                       '• Once chosen, their points, rewards and latest reservations show below.')},
            {'target': 'customers-mobile-scan', 'text': T('أو امسح رمز QR بتاع العميل.',
                                              'Or scan the customer\'s QR code.'),
             'more': T('«📷 مسح رمز العميل (QR)» بيفتح الكاميرا؛ وجّهها على الرمز اللي مع العميل.\n'
                       '• لو الرمز مش معروف هتظهر رسالة «لم يُعثر على عميل بهذا الرمز».\n'
                       '• الزر بيختفي بعد ما تختار عميل.',
                       '"📷 Scan customer QR" opens the camera; point it at the customer\'s code.\n'
                       '• If the code is unknown you see "No customer found for this code".\n'
                       '• The button hides once a customer is chosen.')},
            {'target': 'customers-mobile-loyalty', 'text': T('نقاط الولاء ومستوى العميل.',
                                              'The customer\'s loyalty points and tier.'),
             'more': T('رقمين: «نقاط الشراء (SOFTECH)» اللي بيكسبها من مشترياته، و«نقاط الإحالة» الإضافية.\n'
                       '• فوقهم درجة الولاء لو العميل له درجة.',
                       'Two numbers: "Purchase points (SOFTECH)" earned from purchases, and the extra "Referral points".\n'
                       '• Above them is the loyalty tier if the customer has one.')},
            {'target': 'customers-mobile-rewards', 'text': T('استبدال النقاط بمكافأة.',
                                              'Redeem points for a reward.'),
             'more': T('كل مكافأة بعدد نقاطها؛ «استبدال» بيعمل طلب استبدال «بانتظار الاعتماد» من الكول سنتر — مش بيخصم على طول.\n'
                       '• لو النقاط مش كفاية الزر بيبقى «رصيد غير كافٍ».',
                       'Each reward shows its points cost; "Redeem" creates a redemption request "awaiting approval" by the call center — nothing is deducted straight away.\n'
                       '• If the points are not enough the button reads "Not enough balance".')},
            {'target': 'customers-mobile-reservations', 'text': T('آخر حجوزات العميل.',
                                              'The customer\'s latest reservations.'),
             'more': T('آخر 10 حجوزات بالصنف وحالته — مفيد لو العميل جاي يسأل «الصنف اللي حجزته وصل؟».',
                       'The last 10 reservations with the item and status — handy when a customer asks "has the item I reserved arrived?".')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
