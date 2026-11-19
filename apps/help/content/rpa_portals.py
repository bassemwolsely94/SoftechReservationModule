from . import T

_JOB_OPEN = T('اختر قائمة شراء من الجدول، ثم مهمة من «المهام».', 'Pick a buy list in the grid, then a job under "Jobs".')
_BASKET_OPEN = T('افتح تبويب «السلال» واضغط على سلة.', 'Open the "Baskets" tab and click a basket.')

MODULE = {
    'key': 'rpa_portals', 'group': 'purchasing', 'icon': '🛒',
    'brief': T('روبوت يملأ سلة الطلب في موقع المورد من قائمة الشراء، وأنت تراجع وتضغط Submit بنفسك.',
               'A robot fills the order basket on the supplier\'s site from the buy list; you review and press Submit yourself.'),
    'title': T('مواقع الموردين', 'Supplier portals'),
    'summary': T(
        'قائمة الشراء (من البيفوت أو طلب التوريد أو ملف Excel) تُقسَّم على الموردين. لكل سطر تختار المورد، ويقترح النظام الأرخص أولاً. '
        'الموردون الذين لهم موقع (مثل فارما أوفرسيز) يذهبون للروبوت في «مهمة»: تختار حساب الموقع وترى آخر رصيد ائتمان له، ثم تعتمد المهمة. '
        'الروبوت يعمل على جهازك أنت، يبحث عن أكواد الأصناف في الموقع (شخص يؤكد الكود)، ثم يملأ السلة 10 أصناف في كل مرة. '
        'في «التجربة» يملأ ثم يمسح ولا يُرسل شيئاً. في «الفعلي» يتوقف عند صفحة المراجعة: راجع ثم اضغط Submit بنفسك — الروبوت لا يضغطه أبداً. '
        'بعدها يقرأ الروبوت سجل الطلبات ويسجّل الطلب، وما لم يوفّره المورد يرجع «الباقي» لتختار له مورداً آخر. '
        'أي سلة غير واضحة تظهر «تحتاج موظف» ويحسمها من له صلاحية التعديل.',
        'The buy list (from the pivot, a supply request or an Excel file) is split between suppliers. For each line you pick the supplier; '
        'the system suggests the cheapest first. Suppliers with a site (such as Pharma Overseas) go to the robot in a "job": you pick the site '
        'account and see its last credit, then approve the job. The robot runs on your own PC, looks up the item codes on the site (a person '
        'confirms the code), then fills the basket 10 items at a time. In a "dry run" it fills and then clears, sending nothing. In "live" it '
        'stops at the review page: review, then press Submit yourself — the robot never presses it. Then the robot reads Order History and '
        'records the order, and whatever the supplier could not give comes back as "remainders" for you to pick another supplier. Any unclear '
        'basket shows "needs a person" and someone with the edit right settles it.'),
    'workflows': [{
        'title': T('مراحل سلة الروبوت', 'Robot basket stages'),
        'model': 'rpa.PortalBasket', 'field': 'status',
        'states': [
            {'key': 'pending', 'label': T('تنتظر الأكواد', 'Waiting for codes'),
             'desc': T('بعض الأصناف بلا كود في موقع المورد؛ الروبوت يبحث وشخص يؤكد.', 'Some items have no supplier code yet; the robot searches and a person confirms.'),
             'next': ['ready', 'cancelled']},
            {'key': 'ready', 'label': T('جاهزة', 'Ready'),
             'desc': T('كل الأصناف لها كود؛ تنتظر جهازك.', 'Every item has a code; waiting for your PC.'), 'next': ['in_progress', 'cancelled']},
            {'key': 'in_progress', 'label': T('الروبوت يملأ', 'Robot filling'),
             'desc': T('الروبوت يضيف الأصناف في السلة الآن.', 'The robot is adding the items to the cart now.'),
             'next': ['dry_run_ok', 'awaiting_submit', 'needs_person']},
            {'key': 'dry_run_ok', 'label': T('نجحت التجربة', 'Dry run OK'),
             'desc': T('ملأ الروبوت ثم مسح السلة؛ لم يُرسل شيء. الأسعار والصلاحية والعلامات محفوظة للمراجعة.', 'The robot filled and then cleared the cart; nothing was sent. Prices, expiry and flags are kept for review.')},
            {'key': 'awaiting_submit', 'label': T('راجع واضغط Submit', 'Review and press Submit'),
             'desc': T('السلة ممتلئة على صفحة المراجعة؛ راجع ثم اضغط Submit بنفسك.', 'The cart is full on the review page; review, then press Submit yourself.'),
             'next': ['submitted', 'needs_person']},
            {'key': 'submitted', 'label': T('أُرسلت', 'Submitted'),
             'desc': T('ظهر رقم الطلب؛ يُسجَّل الآن.', 'The order number showed; it is being recorded.'), 'next': ['recorded', 'needs_person']},
            {'key': 'recorded', 'label': T('مسجلة', 'Recorded'),
             'desc': T('الطلب مسجل في التوريد والباقي رجع للقائمة. لو بقي عليها سبب (مثل رقم طلب ثانٍ) فهي تحتاج نظرة موظف: راجعها ثم «تمت المراجعة — أزل التنبيه».',
                       'The order is recorded in supply and the rest went back to the list. If a reason stays on it (such as a second order number), a person must look: check it, then "Checked — clear the warning".')},
            {'key': 'needs_person', 'label': T('تحتاج موظف', 'Needs a person'),
             'desc': T('الروبوت توقف أو ربما أُرسل الطلب؛ شخص يعيد المحاولة أو يربط الطلب أو يلغي.', 'The robot stopped or the order may have been sent; a person retries, links the order or cancels.'),
             'next': ['ready', 'submitted', 'cancelled']},
            {'key': 'cancelled', 'label': T('ملغاة', 'Cancelled'),
             'desc': T('أُلغيت السلة. لو ظهر رقم طلب لها بعد الإلغاء ترجع «تحتاج موظف».', 'The basket was cancelled. If an order number shows for it after the cancel, it goes back to "needs a person".'),
             'next': ['needs_person']},
        ],
    }],
    'journeys': [
        {'key': 'portal_order', 'shell': 'desktop',
         'title': T('من قائمة الشراء إلى طلب الموقع', 'From the buy list to the site order'),
         'summary': T('قائمة شراء، اختيار المورد، مهمة واعتماد، ثم مراجعة السلال.',
                      'A buy list, picking suppliers, a job and its approval, then the baskets.'),
         'steps': [
            {'screen': 'rpa_portals.main', 'target': 'rpa-portals-new-list', 'perm': 'rpa',
             'label': T('قائمة جديدة', 'New list'),
             'text': T('ارفع ملف Excel بعمودي الكود والكمية، أو ابدأ من البيفوت أو طلب توريد.',
                       'Upload an Excel with the code and quantity columns, or start from the pivot or a supply request.')},
            {'screen': 'rpa_portals.main', 'target': 'rpa-portals-buylist', 'perm': 'rpa',
             'label': T('أسطر القائمة', 'List lines'),
             'text': T('اختر المورد لكل سطر من القائمة المرتبة بالأرخص أولاً.',
                       'Pick each line\'s supplier from the list ranked cheapest first.'),
             'open_hint': T('اضغط على قائمة شراء في الجدول.', 'Click a buy list in the grid.')},
            {'screen': 'rpa_portals.main', 'target': 'rpa-portals-account', 'perm': 'rpa',
             'label': T('حساب الموقع', 'Site account'),
             'text': T('اختر الحساب وانظر آخر رصيد ائتمان، ثم «إنشاء مهمة».',
                       'Pick the account and check its last credit, then "Create job".'),
             'open_hint': T('يظهر تحت أسطر قائمة مفتوحة.', 'Shows under the lines of an open list.')},
            {'screen': 'rpa_portals.main', 'target': 'rpa-portals-job-approve', 'perm': 'rpa',
             'label': T('اعتماد المهمة', 'Approve job'),
             'text': T('اعتمد المهمة؛ السطر الأكبر من الاحتياج يحتاج سبباً.',
                       'Approve the job; a line above the need needs a reason.'),
             'warn': T('فوق حد القيمة يعتمدها شخص آخر له صلاحية الموافقة.',
                       'Above the value limit another person with the approve right approves it.'),
             'open_hint': _JOB_OPEN},
         ]},
    ],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في مواقع الموردين', 'A tour of supplier portals'),
            'summary': T('من قائمة الشراء إلى السلال والباقي.', 'From the buy list to the baskets and the remainders.'),
            'steps': [
                {'target': 'nav-rpa-portals', 'nav': '/rpa/portals',
                 'text': T('«المشتريات» ← «مواقع الموردين».', '"Purchasing" → "Supplier portals".'),
                 'more': T('الشاشة دي بتجهز طلبيات مواقع الموردين وتتابع الروبوت وهو بيملأ السلة.\n'
                           '• الروبوت لا يضغط Submit أبداً: أنت تراجع وتضغطه بنفسك.',
                           'This screen prepares supplier-site orders and follows the robot filling the basket.\n'
                           '• The robot never presses Submit: you review and press it yourself.')},
                {'target': 'rpa-portals-status', 'route': '/rpa/portals',
                 'text': T('الشريط يوضح هل الروبوت شغّال، وكل موقع «تجربة» أم «فعلي».',
                           'The strip shows whether the robot is on, and whether each site is "dry run" or "live".'),
                 'more': T('لو كتب «الروبوت متوقف من الإعدادات» فلن يستلم جهازك أي سلة.\n'
                           '• «تجربة» = يملأ ثم يمسح، لا يُرسل شيء. «فعلي» يفتحه المدير فقط.',
                           'If it says "the robot is off in settings", your PC takes no basket.\n'
                           '• "Dry run" = fills then clears, nothing is sent. Only the admin opens "live".')},
                {'target': 'rpa-portals-tabs', 'route': '/rpa/portals',
                 'text': T('التبويبات: قوائم الشراء، الأكواد، السلال، الباقي، والحسابات للمدير.',
                           'Tabs: buy lists, codes, baskets, remainders, and accounts for the admin.'),
                 'more': T('ابدأ من «قوائم الشراء»، ثم تابع «الأكواد» و«السلال».\n'
                           '• «الباقي» = أصناف لم يوفرها المورد، تختار لها مورداً آخر.',
                           'Start from "Buy lists", then follow "Codes" and "Baskets".\n'
                           '• "Remainders" = items the supplier could not give; pick another supplier.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'rpa_portals.main',
        'routes': ['/rpa/portals'],
        'title': T('مواقع الموردين', 'Supplier portals'),
        'summary': T('قائمة الشراء، اختيار المورد، مهام الروبوت على موقع المورد، تأكيد الأكواد، السلال، والباقي.',
                     'The buy list, picking suppliers, robot jobs on the supplier site, confirming codes, baskets and remainders.'),
        'audience': T('من لديه صلاحية «روبوت الإدخال» ويرى كل الفروع (بيانات على مستوى الشركة): عرض / إنشاء / تعديل / موافقة. '
                      'الحسابات وتشغيل «الفعلي» للمدير فقط. الخادم يفرض كل صلاحية.',
                      'Anyone with the "Entry robot" permission who sees every branch (company-level data): view / create / edit / approve. '
                      'Accounts and switching "live" on are admin only. The server enforces every right.'),
        'tabs': [
            {'key': 'buylists', 'title': T('قوائم الشراء', 'Buy lists'),
             'body': T('قائمة الشراء هي الأصناف التي تريد طلبها بالعلبة الكاملة (الكسر يُقرّب لأعلى). ابدأها من «رفع ملف» (Excel أو CSV بعمودي «كود الصنف» و«الكمية»)، '
                       'أو من البيفوت أو طلب توريد برقمه. الصنف غير المعروف أو الكمية غير المفهومة يظهر في «أسطر لم تُقبل» ولا يُخمَّن. '
                       'افتح القائمة لترى أسطرها: لكل سطر المورد المختار وترتيب الموردين من الأرخص (من سجل المشتريات)، اختر بالقائمة المنسدلة. '
                       'السطر داخل مهمة معتمدة يظهر «مقفول» ولا يتغير. لكل مورد بدون موقع اضغط «قائمة واتساب» لنسخ النص أو «Excel» لتنزيل الطلبية؛ '
                       'يُسجَّل الطلب في التوريد مرة واحدة. لمورد له موقع اختر الحساب (يظهر آخر رصيد ائتمان رآه الروبوت) ثم «إنشاء مهمة»، '
                       'وبعد مراجعة أسطرها «اعتماد المهمة». السطر الأكبر من الاحتياج الحالي يحتاج سبباً تكتبه في خانته. '
                       'فوق حد القيمة المحدد في الإعدادات يعتمد المهمة شخص آخر له صلاحية الموافقة (قاعدة العينين). '
                       'المهمة «تجربة» طالما الموقع ليس «فعلي».',
                       'A buy list is the items you want to order in whole packs (a fraction is rounded up). Start one with "Upload file" (Excel or CSV with '
                       '"item code" and "quantity" columns), or from the pivot or a supply request by its number. An unknown item or an unreadable quantity '
                       'shows under "lines not taken" and is never guessed. Open the list to see its lines: each has the chosen supplier and the suppliers '
                       'ranked cheapest first (from purchase history); pick from the drop-down. A line inside an approved job shows "locked" and cannot change. '
                       'For each supplier without a site press "WhatsApp list" to copy the text or "Excel" to download the order; the order is recorded '
                       'in supply once. For a supplier with a site pick the account (it shows the last credit the robot saw), then "Create job", and after '
                       'reviewing its lines "Approve job". A line above the current need needs a reason typed in its box. Above the value limit set in '
                       'settings another person with the approve right approves the job (four eyes). The job is a "dry run" while the site is not "live".')},
            {'key': 'discovery', 'title': T('الأكواد', 'Codes'),
             'body': T('صنف بلا كود في موقع المورد: الروبوت يبحث باسمه ويعرض المرشحين، وشخص له صلاحية التعديل يختار. '
                       'الأسهم للتنقل، Enter = تأكيد المرشح المختار (يتعلم النظام الكود للمرة القادمة)، M = «لا شيء منها» (يرجع السطر للمشتري). '
                       'الكود المسجل لصنف آخر يظهر «كود مستخدم» ولا يُعتمد تلقائياً. '
                       'لو فشلت القراءة 3 مرات يتوقف الروبوت عن المحاولة وتظهر المهمة «تحتاج موظف»: أكّد الأكواد بنفسك أو اختر «لا شيء» أو ألغِ المهمة.',
                       'An item with no code on the supplier site: the robot searches by its name and shows the candidates, and a person with the edit right '
                       'picks. Arrows move, Enter = confirm the chosen candidate (the system learns the code for next time), M = "none of these" (the line '
                       'goes back to the buyer). A code already confirmed for another item shows "code in use" and is never taken automatically. '
                       'If the read fails 3 times the robot stops trying and the job shows "needs a person": confirm the codes yourself, pick "none", or '
                       'cancel the job.')},
            {'key': 'baskets', 'title': T('السلال', 'Baskets'),
             'body': T('كل مهمة تُقسَّم سلالاً (10 أصناف افتراضياً) بترتيب القائمة. افتح سلة لترى أسطرها: الكمية المطلوبة والمقبولة، السعر والخصم والبونص، '
                       'وصلاحية المورد، والعلامات الهادئة «صلاحية قصيرة» (أقل من 12 شهراً) و«قفزة سعر» (10% فأكثر فوق آخر شراء) — علامات فقط، لا تغيّر شيئاً. '
                       'وتحتها خطوات الروبوت ولقطات الشاشة والفرق بين ما سُلِّم وما سُجِّل. '
                       '«راجع ثم اضغط Submit بنفسك»: في «الفعلي» يقف الروبوت على صفحة المراجعة ولا يضغط Submit أبداً. '
                       'سلة «تحتاج موظف» (أو مسجلة وعليها سبب) تظهر في «تحتاج موظف»: «إعادة المحاولة» (يرفضها الخادم لو ربما أُرسل الطلب حتى يقرأ سجل الطلبات '
                       'أو تؤكد أنه لم يُرسل)، «ربط بطلب» برقم الطلب، أو «إلغاء». '
                       '«ربط مع كتابة الأسطر» يفتح جدولاً تحت الزر: كل صنف وكميته في الطلب كما في سجل الطلبات بالموقع (عبوات كاملة؛ صفر = لم يُطلب ويرجع للباقي)، '
                       'مملوءاً مما قرأه الروبوت أو من الكمية المُسلَّمة — استعمله حين لا يقرأ الروبوت الأسطر أو يجد أسطراً لا تخص السلة. '
                       'لو وجد سجل الطلبات طلباً قد يكون لهذه السلة فلا تُعاد المحاولة بتأكيد «لم يُرسل» إلا مع كتابة السبب. '
                       'السبب «history_unclear» يعني أن قراءة سجل الطلبات لم تستطع التأكد: طلب في المدة لا يخص سلة أخرى ولا يشارك هذه السلة أي كود '
                       '(other_orders)، أو لم يثبت الروبوت أنه قرأ كل الصفحات (not_complete — وهذا دائماً حتى نتأكد من أزرار الصفحات على الموقع)، '
                       'أو وصلت القراءة للحد الأقصى من الطلبات (truncated)، أو طلب في المدة لم يُقرأ رقمه (unreadable_orders). '
                       'السلة تبقى «تحتاج موظف» ولا تُعاد المحاولة: افتح سجل الطلبات في الموقع، '
                       'ثم اربطها بطلبها، أو أكّد «لم يُرسل» مع كتابة السبب. وتنتهي «history_unclear» أيضاً بقراءة لاحقة كاملة لا تجد طلباً '
                       '(مثلاً بعد ربط الطلب الآخر بسلته ثم «افحص سجل الطلبات»). '
                       'لا تُعاد المحاولة بينما الروبوت يقرأ سجل الطلبات للسلة: انتظر النتيجة. ونتيجة قراءة تصل بعد قرارك وتجد طلباً تُرجع السلة «تحتاج موظف». '
                       'لو ظهر Submit متأخراً لسلة أُلغيت دون حجز أصنافها، تُحجز أصنافها الآن (تخرج من المورد وتظهر «ربما طُلبت» في «الباقي») '
                       'وترجع السلة «تحتاج موظف»، وكل سلة أحدث لنفس الأصناف على نفس الموقع لم تُرسل بعد ترجع «تحتاج موظف» أيضاً '
                       '(السبب submit_seen_other ورقم السلة الملغاة) حتى لا تُطلب الأصناف مرتين. '
                       'سلة مهمتها مُلغاة لا يقرأ لها الروبوت سجل الطلبات تلقائياً: يقرر لها شخص. '
                       'سلة طُلبت أو ربما طُلبت لا تُلغى إلا بتأكيد وسبب، وبعد إلغائها لا تُطلب أصنافها مرة ثانية من تلقاء نفسها: تظهر في «الباقي» '
                       'بعلامة «ربما طُلبت» حتى يختار لها شخص مورداً من جديد. '
                       'سلة «مسجلة» عليها تنبيه (مثل رقم طلب ثانٍ ظهر بعد التسجيل): راجعها ثم «تمت المراجعة — أزل التنبيه» مع كتابة ما راجعته. '
                       'زر «افحص سجل الطلبات» يطلب من الروبوت قراءة سجل الطلبات الآن، والنظام يطلبها يومياً تلقائياً.',
                       'Each job is cut into baskets (10 items by default) in list order. Open a basket to see its lines: wanted and accepted quantity, price, '
                       'discount and bonus, the supplier\'s expiry, and the calm flags "short expiry" (under 12 months) and "price jump" (10% or more above the '
                       'last purchase) — flags only, they change nothing. Under them: the robot\'s steps, screenshots and the difference between what was '
                       'handed over and what was recorded. "Review, then press Submit yourself": in "live" the robot stops on the review page and never presses '
                       'Submit. A basket that "needs a person" (or is recorded with a reason on it) shows under "Needs a person": "Retry" (the server refuses '
                       'it while the order may have been sent, until Order History is read or you confirm it was not sent), "Link to order" with the order '
                       'number, or "Cancel". "Link and type the lines" opens a grid under the button: each item and its quantity in the order as Order History '
                       'on the site shows it (whole packs; zero = not ordered, it goes back to the remainders), prefilled from what the robot read or from the '
                       'handed-over quantity — use it when the robot could not read the lines or found lines that are not this basket\'s. If Order History '
                       'found an order that may be this basket\'s, a retry with "not sent" needs a written reason. '
                       'The reason "history_unclear" means the Order History read could not be sure: an order in the window that is on no other basket '
                       'and shares no code with this one (other_orders), or the robot could not prove it read every page (not_complete — always so '
                       'until the site\'s page buttons are confirmed), or the read reached the most orders it carries (truncated), or an order in the '
                       'window had a number that could not be read (unreadable_orders). The basket stays under '
                       '"Needs a person" and is not retried: open Order History on the site, then link it to its order, or confirm "not sent" with a '
                       'written reason. "history_unclear" is also cleared by a later complete read that finds no order (for example after the other '
                       'order is linked to its basket and you press "Check Order History"). No retry while the robot is reading Order History for the '
                       'basket: wait for the result. A read that comes back after your decision and finds an order sends the basket back to "Needs a person". '
                       'If Submit is seen late for a basket that was cancelled without holding its items, its items are held now (off '
                       'the supplier, "may have been ordered" under "Remainders") and the basket goes back to "Needs a person"; every newer basket of the '
                       'same items on the same site that has not been sent goes to "Needs a person" too (reason submit_seen_other and the cancelled '
                       'basket\'s number), so nothing is ordered twice. A basket whose job was cancelled gets no automatic Order History read: a person decides. '
                       'A basket that was or may have been '
                       'ordered is cancelled only with a confirmation and a reason, and its items are then never ordered again by themselves: they show under '
                       '"Remainders" marked "may have been ordered" until a person picks a supplier for them again. A "recorded" basket with a warning (such '
                       'as a second order number seen after it was recorded): check it, then "Checked — clear the warning" with what you checked. '
                       '"Check Order History" asks the robot to read Order History now; the system also asks daily.')},
            {'key': 'remainders', 'title': T('الباقي', 'Remainders'),
             'body': T('أسطر قوائم الشراء المفتوحة التي جُرِّب لها مورد ولم يوفّر الكمية كلها. تظهر الكمية الباقية والموردون الذين جُرِّبوا. '
                       'الأسهم للتنقل وEnter يختار المورد التالي المقترح للسطر، ثم أكمل من «قوائم الشراء». '
                       'سطر من سلة أُلغيت وربما طُلبت يظهر «ربما طُلبت» بلا مورد مقترح: راجع موقع المورد أولاً، ثم اختر مورده من «قوائم الشراء».',
                       'Lines of open buy lists where a supplier was tried and did not give the whole quantity. The remaining quantity and the suppliers '
                       'already tried show. Arrows move and Enter picks the next suggested supplier for the line; then carry on from "Buy lists". '
                       'A line from a cancelled basket that may have been ordered shows "may have been ordered" with no suggested supplier: check the '
                       'supplier\'s site first, then pick its supplier under "Buy lists".')},
            {'key': 'accounts', 'title': T('الحسابات', 'Accounts'),
             'body': T('للمدير فقط. حساب الموقع اسم يظهر في القائمة، و«اسم الحساب كما يظهر في الموقع» الذي يتأكد منه الروبوت قبل أن يلمس السلة، وفرع الورق. '
                       'لا تُحفظ أي كلمة سر أو كوكي: تسجّل الدخول بنفسك على جهازك. هنا أيضاً لكل موقع: «مفعّل»، حجم السلة، و«فعلي» — '
                       'المكان الوحيد الذي يُفتح فيه الإدخال الفعلي، وكل تغيير يُسجَّل في سجل التدقيق.',
                       'Admin only. A site account is a label shown in the list, the "account name as shown on the site" the robot checks before it touches '
                       'the cart, and the paper branch. No password or cookie is stored: you sign in yourself on your PC. Here too, per site: "enabled", '
                       'basket size and "live" — the only place live entry is switched on, and every change goes into the audit log.')},
        ],
        'steps': [
            T('أنشئ قائمة شراء من ملف أو من البيفوت أو طلب توريد، وراجع «أسطر لم تُقبل».',
              'Create a buy list from a file, the pivot or a supply request, and review "lines not taken".'),
            T('اختر المورد لكل سطر. للموردين بدون موقع أرسل قائمة واتساب أو Excel.',
              'Pick each line\'s supplier. For suppliers without a site send a WhatsApp list or an Excel.'),
            T('لمورد له موقع: اختر الحساب وانظر رصيده، ثم «إنشاء مهمة» و«اعتماد المهمة».',
              'For a supplier with a site: pick the account and check its credit, then "Create job" and "Approve job".'),
            T('شغّل برنامج الروبوت على جهازك وسجّل الدخول للموقع بنفسك. أكّد الأكواد في «الأكواد» إن طُلب.',
              'Run the robot program on your PC and sign in to the site yourself. Confirm the codes under "Codes" if asked.'),
            T('في «الفعلي»: راجع السلة على صفحة المراجعة ثم اضغط Submit بنفسك.',
              'In "live": review the basket on the review page, then press Submit yourself.'),
            T('تابع «تحتاج موظف» و«الباقي» حتى تنتهي القائمة.', 'Follow "Needs a person" and "Remainders" until the list is done.'),
        ],
        'tips': [
            T('الروبوت لا يضغط Submit ولا يكتب كلمة سر ولا يسجل خروج أبداً، مهما كانت الخطة.',
              'The robot never presses Submit, never types a password and never signs out, whatever the plan says.'),
            T('العلامات (صلاحية قصيرة، قفزة سعر) للعرض فقط: القرار لك.', 'The flags (short expiry, price jump) are for display only: the decision is yours.'),
            T('«ربما أُرسل الطلب» يعني أن الروبوت وصل لصفحة Submit. لا تعد المحاولة قبل أن يقرأ سجل الطلبات، حتى لا يُطلب الصنف مرتين.',
              '"The order may have been sent" means the robot reached the Submit page. Do not retry before Order History is read, so nothing is ordered twice.'),
            T('كل جدول يترتب بالضغط على عنوان العمود.', 'Every grid sorts by clicking a column header.'),
        ],
        'faq': [
            {'q': T('لماذا لا أستطيع إلغاء سلة؟', 'Why can I not cancel a basket?'),
             'a': T('لو طُلبت أو ربما طُلبت (ظهر رقم طلب، أو وصل الروبوت لصفحة Submit) فالإلغاء يحتاج تأكيداً وسبباً. اربطها بالطلب، أو أكّد الإلغاء واكتب السبب؛ '
                    'أصنافها بعدها تظهر في «الباقي» بعلامة «ربما طُلبت» ولا تُطلب حتى يختار لها شخص مورداً.',
                    'If it was or may have been ordered (an order number showed, or the robot reached the Submit page) cancelling needs a confirmation and a reason. '
                    'Link it, or confirm the cancel and write the reason; its items then show under "Remainders" marked "may have been ordered" and are not ordered until a person picks a supplier.')},
            {'q': T('الروبوت قرأ رقم الطلب لكن لم يقرأ أسطره — ماذا أفعل؟', 'The robot read the order number but not its lines — what do I do?'),
             'a': T('افتح سجل الطلبات في الموقع، ثم «ربط مع كتابة الأسطر» واكتب كمية كل صنف كما فيه. لا تلغِ السلة: الطلب أُرسل.',
                    'Open Order History on the site, then "Link and type the lines" and type each item\'s quantity as it shows. Do not cancel the basket: the order was sent.')},
            {'q': T('لماذا لا أرى مهام زملائي؟', 'Why can I not see my colleagues\' jobs?'),
             'a': T('كل مشترٍ يرى مهامه؛ من له صلاحية الموافقة يرى الكل.', 'Each buyer sees their own jobs; whoever holds the approve right sees all.')},
        ],
        'related': ['rpa.main'],
        'tour': [
            {'target': 'rpa-portals-status', 'label': T('حالة الروبوت', 'Robot status'),
             'text': T('هل الروبوت شغّال، وكل موقع «تجربة» أم «فعلي».', 'Whether the robot is on, and whether each site is "dry run" or "live".')},
            {'target': 'rpa-portals-tabs', 'label': T('التبويبات', 'Tabs'),
             'text': T('قوائم الشراء · الأكواد · السلال · الباقي · الحسابات (للمدير).', 'Buy lists · Codes · Baskets · Remainders · Accounts (admin).')},
            {'target': 'rpa-portals-new-list', 'label': T('قائمة جديدة', 'New list'),
             'text': T('رفع ملف، أو من البيفوت، أو من طلب توريد.', 'Upload a file, or from the pivot, or from a supply request.')},
            {'target': 'rpa-portals-buylist', 'label': T('أسطر القائمة', 'List lines'),
             'text': T('المورد لكل سطر من القائمة المرتبة بالأرخص.', 'Each line\'s supplier from the list ranked cheapest first.'),
             'open_hint': T('اضغط على قائمة شراء في الجدول.', 'Click a buy list in the grid.')},
            {'target': 'rpa-portals-account', 'label': T('حساب الموقع', 'Site account'),
             'text': T('الحساب وآخر رصيد ائتمان، ثم «إنشاء مهمة».', 'The account and its last credit, then "Create job".'),
             'open_hint': T('يظهر تحت أسطر قائمة مفتوحة.', 'Shows under the lines of an open list.')},
            {'target': 'rpa-portals-job-approve', 'label': T('اعتماد المهمة', 'Approve job'),
             'text': T('بعد مراجعة الأسطر؛ السطر الأكبر من الاحتياج يحتاج سبباً.', 'After reviewing the lines; a line above the need needs a reason.'),
             'warn': T('فوق حد القيمة يعتمدها شخص آخر له صلاحية الموافقة.', 'Above the value limit another person with the approve right approves it.'),
             'open_hint': _JOB_OPEN},
            {'target': 'rpa-portals-discovery', 'label': T('الأكواد', 'Codes'),
             'text': T('Enter يؤكد المرشح، M = لا شيء منها.', 'Enter confirms the candidate, M = none of these.'),
             'open_hint': T('افتح تبويب «الأكواد».', 'Open the "Codes" tab.')},
            {'target': 'rpa-portals-baskets', 'label': T('السلال', 'Baskets'),
             'text': T('حالة كل سلة؛ «تحتاج موظف» بشارة هادئة.', 'Each basket\'s state; "needs a person" as a calm badge.'),
             'open_hint': T('افتح تبويب «السلال».', 'Open the "Baskets" tab.')},
            {'target': 'rpa-portals-resolve', 'label': T('حسم السلة', 'Settle basket'),
             'text': T('إعادة المحاولة، أو ربط برقم الطلب، أو إلغاء.', 'Retry, link to the order number, or cancel.'),
             'warn': T('سلة طُلبت أو ربما طُلبت لا تُلغى إلا بتأكيد وسبب، ولا تُطلب أصنافها ثانية حتى يختار لها شخص مورداً.',
                       'A basket that may have been ordered is cancelled only with a confirmation and a reason; its items wait until a person picks a supplier.'),
             'open_hint': _BASKET_OPEN},
            {'target': 'rpa-portals-link-lines', 'label': T('ربط مع كتابة الأسطر', 'Link and type the lines'),
             'text': T('كمية كل صنف في الطلب كما في سجل الطلبات، بعبوات كاملة.', 'Each item\'s quantity in the order as Order History shows it, in whole packs.'),
             'open_hint': T('في سلة «تحتاج موظف» اكتب رقم الطلب ثم «ربط مع كتابة الأسطر».',
                            'In a basket that needs a person, type the order number, then "Link and type the lines".')},
            {'target': 'rpa-portals-acknowledge', 'label': T('أزل التنبيه', 'Clear the warning'),
             'text': T('سلة مسجلة عليها تنبيه: اكتب ما راجعته ثم أزله.', 'A recorded basket with a warning: write what you checked, then clear it.'),
             'open_hint': T('يظهر في سلة «مسجلة» عليها سبب.', 'Shows on a "recorded" basket that has a reason.')},
            {'target': 'rpa-portals-history-refresh', 'label': T('افحص سجل الطلبات', 'Check Order History'),
             'text': T('يطلب من الروبوت قراءة سجل الطلبات الآن.', 'Asks the robot to read Order History now.'),
             'open_hint': _BASKET_OPEN},
            {'target': 'rpa-portals-remainders', 'label': T('الباقي', 'Remainders'),
             'text': T('ما لم يوفره المورد؛ Enter يختار المورد التالي.', 'What the supplier could not give; Enter picks the next supplier.'),
             'open_hint': T('افتح تبويب «الباقي».', 'Open the "Remainders" tab.')},
            {'target': 'rpa-portals-live', 'label': T('فعلي', 'Live'),
             'text': T('للمدير: المكان الوحيد لفتح الإدخال الفعلي على موقع.', 'Admin: the only place to switch a site to live entry.'),
             'warn': T('في «الفعلي» تراجع وتضغط Submit بنفسك؛ كل تغيير مُسجَّل.', 'In "live" you review and press Submit yourself; every change is logged.'),
             'open_hint': T('افتح تبويب «الحسابات» (للمدير).', 'Open the "Accounts" tab (admin).')},
        ],
        'updated': '2026-11-19',
    },
]
