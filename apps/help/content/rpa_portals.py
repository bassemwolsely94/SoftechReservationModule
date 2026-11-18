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
             'desc': T('الطلب مسجل في التوريد والباقي رجع للقائمة. لو بقي عليها سبب فهي تحتاج نظرة موظف.', 'The order is recorded in supply and the rest went back to the list. If a reason stays on it, a person must look.')},
            {'key': 'needs_person', 'label': T('تحتاج موظف', 'Needs a person'),
             'desc': T('الروبوت توقف أو ربما أُرسل الطلب؛ شخص يعيد المحاولة أو يربط الطلب أو يلغي.', 'The robot stopped or the order may have been sent; a person retries, links the order or cancels.'),
             'next': ['ready', 'submitted', 'cancelled']},
            {'key': 'cancelled', 'label': T('ملغاة', 'Cancelled'), 'desc': T('أُلغيت السلة.', 'The basket was cancelled.')},
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
                       'أو تؤكد أنه لم يُرسل)، «ربط بطلب» برقم الطلب، أو «إلغاء». سلة لها رقم طلب لا تُلغى إلا بتأكيد وسبب، لأن الإلغاء يعيد أصنافها للشراء. '
                       'زر «افحص سجل الطلبات» يطلب من الروبوت قراءة سجل الطلبات الآن، والنظام يطلبها يومياً تلقائياً.',
                       'Each job is cut into baskets (10 items by default) in list order. Open a basket to see its lines: wanted and accepted quantity, price, '
                       'discount and bonus, the supplier\'s expiry, and the calm flags "short expiry" (under 12 months) and "price jump" (10% or more above the '
                       'last purchase) — flags only, they change nothing. Under them: the robot\'s steps, screenshots and the difference between what was '
                       'handed over and what was recorded. "Review, then press Submit yourself": in "live" the robot stops on the review page and never presses '
                       'Submit. A basket that "needs a person" (or is recorded with a reason on it) shows under "Needs a person": "Retry" (the server refuses '
                       'it while the order may have been sent, until Order History is read or you confirm it was not sent), "Link to order" with the order '
                       'number, or "Cancel". A basket with an order number is cancelled only with a confirmation and a reason, because cancelling sends its '
                       'items back to be bought again. "Check Order History" asks the robot to read Order History now; the system also asks daily.')},
            {'key': 'remainders', 'title': T('الباقي', 'Remainders'),
             'body': T('أسطر قوائم الشراء المفتوحة التي جُرِّب لها مورد ولم يوفّر الكمية كلها. تظهر الكمية الباقية والموردون الذين جُرِّبوا. '
                       'الأسهم للتنقل وEnter يختار المورد التالي المقترح للسطر، ثم أكمل من «قوائم الشراء».',
                       'Lines of open buy lists where a supplier was tried and did not give the whole quantity. The remaining quantity and the suppliers '
                       'already tried show. Arrows move and Enter picks the next suggested supplier for the line; then carry on from "Buy lists".')},
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
             'a': T('لو لها رقم طلب فالطلب أُرسل للمورد؛ الإلغاء يمسح سجله ويعيد أصنافها للشراء. اربطها بالطلب، أو أكّد الإلغاء واكتب السبب.',
                    'If it has an order number the order went to the supplier; cancelling drops its record and sends its items back to be bought. Link it, or confirm the cancel and write the reason.')},
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
             'warn': T('سلة لها رقم طلب لا تُلغى إلا بتأكيد وسبب.', 'A basket with an order number is cancelled only with a confirmation and a reason.'),
             'open_hint': _BASKET_OPEN},
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
        'updated': '2026-11-18',
    },
]
