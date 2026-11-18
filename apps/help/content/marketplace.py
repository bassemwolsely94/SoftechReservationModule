from . import T

_ORDER_ROW = T('في تبويب «📦 الطلبات» اضغط طلبًا في الجدول فتفتح تفاصيله بجانبه.',
               'On the "📦 Orders" tab, click an order in the table and its details open beside it.')
_CHANNELS_TAB = T('افتح تبويب «🔌 المنصات والفروع» واختر منصة.', 'Open the "🔌 Platforms & branches" tab and pick a platform.')

MODULE = {
    'key': 'marketplace', 'group': 'operations', 'icon': '🛍️',
    'brief': T('طلبات تطبيقات التوصيل (طلبات، إنستاشوب…): الأصناف المعتمدة، الطلبات، المخزون المعروض، والتسويات.',
               'Delivery-app orders (Talabat, Instashop…): approved items, orders, listed stock and payouts.'),
    'title': T('المنصات والتطبيقات', 'Marketplaces & delivery apps'),
    'summary': T(
        'بيع أصنافنا على تطبيقات التوصيل. لا يُعرض أي صنف على أي منصة إلا بعد أن يعتمده مشرف لهذه المنصة، '
        'وأدوية الروشتة لا تُعرض أبدًا إلا باعتماد مشرف صريح لكل صنف، والصنف الممنوع أو المقيد أو الثلاجة لا يُباع. '
        'الطلب يصل من المنصة أو يُدخل يدويًا، يُراجع ثم يُقبل أو يُرفض. القبول يحوّل الطلب إلى مسودة في نقطة البيع '
        'على حساب المنصة في SOFTECH (بيع آجل)، وتُرسَل للكاشير من زر 🛵 «طلبات المنصات» في نقطة البيع — هذه الشاشة لا تكتب في SOFTECH. '
        'طالما مفتاح الإرسال مقفول لا يُرسل أي شيء لأي منصة: إرسال المخزون والحالات يُسجَّل فقط كتجربة. '
        'ملف التسوية من المنصة يُرفع ويُطابق مع طلباتنا ويظهر ما لا يطابق.',
        'Sell our items on delivery apps. No item shows on any platform until a supervisor approves it for that '
        'platform; prescription medicines are never listed unless a supervisor approves each one explicitly, and a '
        'blocked, restricted or fridge item is not sold. An order arrives from the platform or is entered by hand, is '
        'checked, then accepted or rejected. Accepting turns it into a POS draft on the platform’s SOFTECH account (a '
        'credit sale), and it is sent to the cashier from the 🛵 "Platform orders" button on the POS screen — this screen writes nothing to SOFTECH. '
        'While the send switch is off nothing is sent to any platform: stock and status pushes are only logged as a '
        'dry run. The platform’s payout file is uploaded and matched to our orders, and what does not match is shown.'),
    'workflows': [{
        'key': 'external_order',
        'title': T('مراحل طلب المنصة', 'Platform order stages'),
        'model': 'marketplace.ExternalOrder', 'field': 'status',
        'transitions': 'apps.marketplace.intake.ALLOWED',
        'states': [
            {'key': 'received', 'label': T('جديد', 'New'),
             'desc': T('وصل الطلب ويحتاج مراجعة: الأصناف ومشاكلها.', 'The order arrived and needs a check: its items and their problems.'),
             'next': ['accepted', 'rejected', 'cancelled']},
            {'key': 'accepted', 'label': T('مقبول', 'Accepted'),
             'desc': T('قُبل وأصبح مسودة في نقطة البيع على حساب المنصة.', 'Accepted and now a POS draft on the platform account.'),
             'next': ['preparing', 'cancelled']},
            {'key': 'rejected', 'label': T('مرفوض', 'Rejected'),
             'desc': T('رُفض بسبب مكتوب. نهائي.', 'Rejected with a written reason. Final.')},
            {'key': 'preparing', 'label': T('جاري التحضير', 'Preparing'),
             'desc': T('الفرع يجهّز الأصناف.', 'The branch is preparing the items.'), 'next': ['ready', 'cancelled']},
            {'key': 'ready', 'label': T('جاهز للتسليم', 'Ready'),
             'desc': T('مُغلَّف وينتظر المندوب.', 'Packed and waiting for the rider.'), 'next': ['handed_over', 'cancelled']},
            {'key': 'handed_over', 'label': T('سُلِّم للمندوب', 'Handed over'),
             'desc': T('خرج مع مندوب المنصة أو مندوبنا.', 'Left with the platform’s rider or ours.'), 'next': ['delivered']},
            {'key': 'delivered', 'label': T('تم التوصيل', 'Delivered'),
             'desc': T('وصل للعميل. نهائي.', 'Reached the customer. Final.')},
            {'key': 'cancelled', 'label': T('ملغى', 'Cancelled'),
             'desc': T('أُلغي قبل التسليم للمندوب بسبب مكتوب. نهائي.',
                       'Cancelled before the handover, with a written reason. Final.')},
        ],
    }],
    'journeys': [
        {'key': 'first_order', 'shell': 'desktop', 'roles': ['admin'],
         'title': T('من اعتماد الصنف إلى الطلب', 'From approving an item to an order'),
         'summary': T('اعتماد صنف على منصة، ثم إدخال طلب، ثم قبوله ليصبح مسودة في نقطة البيع.',
                      'Approve an item on a platform, enter an order, then accept it so it becomes a POS draft.'),
         'steps': [
            {'screen': 'marketplace.main', 'target': 'marketplace-listings-grid', 'perm': 'marketplace',
             'label': T('🏷️ الأصناف المعروضة', '🏷️ Listed items'),
             'text': T('أضف الصنف للمنصة ثم اعتمده. لا يُعرض شيء بدون اعتماد.',
                       'Add the item to the platform, then approve it. Nothing is listed without approval.'),
             'open_hint': T('افتح تبويب «🏷️ الأصناف المعروضة».', 'Open the "🏷️ Listed items" tab.')},
            {'screen': 'marketplace.main', 'target': 'marketplace-manual-form', 'perm': 'marketplace',
             'label': T('✍️ إدخال طلب', '✍️ Enter an order'),
             'text': T('المنصة والفرع ورقم الطلب عند المنصة، ثم الأصناف والكميات.',
                       'Platform, branch and the platform’s order number, then the items and quantities.'),
             'open_hint': T('افتح تبويب «✍️ إدخال طلب».', 'Open the "✍️ Enter an order" tab.')},
            {'screen': 'marketplace.main', 'target': 'marketplace-order-actions', 'perm': 'marketplace',
             'label': T('قبول / رفض', 'Accept / Reject'),
             'text': T('القبول يحوّل الطلب لمسودة في نقطة البيع على حساب المنصة؛ الكاشير يكمّلها.',
                       'Accepting turns the order into a POS draft on the platform account; the cashier completes it.'),
             'open_hint': _ORDER_ROW},
         ]},
    ],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في المنصات والتطبيقات', 'A tour of marketplaces'),
            'summary': T('الطلبات، والإدخال اليدوي، والأصناف المعتمدة، وإعداد المنصات، والتسويات.',
                         'Orders, manual entry, approved items, platform setup and payouts.'),
            'roles': ['admin'],
            'steps': [
                {'target': 'nav-marketplace', 'nav': '/marketplace',
                 'text': T('«العمليات» ← «المنصات والتطبيقات».', '"Operations" → "Marketplaces".'),
                 'more': T('الشاشة تظهر فقط لما مفتاح المنصات يكون مفتوح ويكون عندك صلاحية «المنصات والتطبيقات».\n'
                           '• لا شيء هنا يكتب في SOFTECH.',
                           'The screen shows only when the marketplace switch is on and you hold the "Marketplaces" permission.\n'
                           '• Nothing here writes to SOFTECH.')},
                {'target': 'marketplace-tabs', 'route': '/marketplace',
                 'text': T('خمسة تبويبات: الطلبات، إدخال طلب، الأصناف المعروضة، المنصات والفروع، التسويات.',
                           'Five tabs: orders, enter an order, listed items, platforms & branches, payouts.')},
                {'target': 'marketplace-orders-grid', 'route': '/marketplace',
                 'text': T('طلبات فروعك بحالتها؛ اضغط طلبًا لقبوله أو رفضه أو تحريك حالته.',
                           'Your branches’ orders with their status; click one to accept, reject or move it.'),
                 'more': T('القبول ينشئ مسودة في نقطة البيع على حساب المنصة في SOFTECH (بيع آجل)، والكاشير يكمّلها ويسويها.\n'
                           '• لو فيه صنف غير معتمد أو ممنوع أو غير متوفر يُرفض القبول ويظهر السبب.',
                           'Accepting creates a POS draft on the platform’s SOFTECH account (a credit sale); the cashier completes and settles it.\n'
                           '• If an item is not approved, blocked or out of stock, accepting is refused and the reason shows.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'marketplace.main',
        'routes': ['/marketplace'],
        'title': T('المنصات والتطبيقات', 'Marketplaces & delivery apps'),
        'summary': T(
            'طلبات تطبيقات التوصيل والأصناف المعتمدة لكل منصة وإعداد المنصات وفروعها والتسويات. '
            'لا يُرسل أي شيء لأي منصة طالما مفتاح الإرسال مقفول، والطلب المقبول يصبح مسودة في نقطة البيع '
            'على حساب المنصة في SOFTECH والكاشير يسويها. أدوية الروشتة لا تُعرض إلا باعتماد مشرف لكل صنف.',
            'Delivery-app orders, the items approved per platform, platform and branch setup, and payouts. '
            'Nothing is sent to any platform while the send switch is off, and an accepted order becomes a POS draft '
            'on the platform’s SOFTECH account that the cashier settles. Prescription medicines are listed only when '
            'a supervisor approves each one.'),
        'audience': T('الصيادلة والكول سنتر للطلبات؛ الاعتماد للمشرف؛ إعداد المنصات والتسويات لمن لديه صلاحية التعديل.',
                      'Pharmacists and the call center for orders; approval for supervisors; platform setup and '
                      'payouts for those with the edit permission.'),
        'tabs': [
            {'key': 'orders', 'title': T('📦 الطلبات', '📦 Orders'),
             'body': T('كل طلبات المنصات لفروعك بحالتها، تُفلتر بالحالة والمنصة. اضغط طلبًا فتفتح تفاصيله بجانب الجدول: '
                       'الأصناف ومشكلة كل صنف (غير معتمد، ممنوع، غير متوفر)، وسجل الحالات. «قبول» يحوّل الطلب لمسودة في '
                       'نقطة البيع على حساب المنصة (بيع آجل) — الكاشير يكمّلها ويسويها؛ لو فيه صنف بمشكلة يُرفض القبول '
                       'ويظهر السبب. «رفض» يحتاج سببًا. بعد القبول حرّك الحالة: تحضير ← جاهز ← سُلِّم للمندوب ← تم التوصيل. '
                       '«إلغاء الطلب» يحتاج سبب الإلغاء في الخانة بجانبه؛ لو المسودة لسه ما وصلتش للكاشير تُلغى معه، ولو '
                       'وصلت يظهر الطلب «يحتاج مراجعة» ⚠ وتُلغى من نقطة البيع أو يُعمل مرتجع. الكمية تفضل محجوزة من المخزون '
                       'المعروض حتى يسوي الكاشير البيع. رقم العميل يظهر مخفيًا في القائمة.',
                       'Every platform order for your branches with its status, filtered by status and platform. Click an '
                       'order and its details open beside the table: the items and each item’s problem (not approved, '
                       'blocked, out of stock), and the status history. "Accept" turns the order into a POS draft on the '
                       'platform account (a credit sale) — the cashier completes and settles it; if an item has a problem '
                       'accepting is refused and the reason shows. "Reject" needs a reason. After accepting, move the '
                       'status: preparing → ready → handed over → delivered. "Cancel order" needs a reason in the box '
                       'beside it; a draft that has not reached the cashier is cancelled with it, and if it has, the order '
                       'shows "Needs review" ⚠ and is cancelled in the POS or returned. The quantity stays held from the '
                       'listed stock until the cashier settles the sale. The customer number is masked in the list.')},
            {'key': 'manual', 'title': T('✍️ إدخال طلب', '✍️ Enter an order'),
             'body': T('لطلب وصل بالتليفون أو من لوحة المنصة: اختر المنصة والفرع، واكتب رقم الطلب عند المنصة، '
                       'ثم ابحث عن الصنف (نفس بحث النظام، * أو % بين الأجزاء) واكتب الكمية واضغط Enter لإضافته. '
                       'سعر المنصة يُملأ تلقائيًا من قاعدة سعر المنصة، ولا يُضاف صنف بدون سعر. '
                       'اختر طريقة الدفع ثم «حفظ الطلب». نفس رقم الطلب مرتين لا يُنشئ طلبًا ثانيًا. الطلب يدخل «جديد» '
                       'ويحتاج قبولًا من تبويب الطلبات.',
                       'For an order that came by phone or from the platform’s panel: pick the platform and branch, type '
                       'the platform’s order number, then search the item (the system search, * or % between parts), type '
                       'the quantity and press Enter to add it. The platform price fills in from the platform’s price '
                       'rule, and no line is added without a price. Pick the payment mode, then "Save order". The same order '
                       'number twice never makes a second order. The order starts as "New" and needs accepting on the Orders tab.')},
            {'key': 'listings', 'title': T('🏷️ الأصناف المعروضة', '🏷️ Listed items'),
             'body': T('الأصناف المضافة لكل منصة، والمعتمد منها، والمشكلة والكمية المتاحة في الفرع المختار وسعر المنصة. '
                       'لا يُعرض أي صنف بدون اعتماد مشرف، وأدوية الروشتة لا تُعتمد إلا بقرار صريح لكل صنف. الصنف الممنوع '
                       'أو المقيد أو الثلاجة (إلا لو مسموح) لا يُباع حتى لو معتمد. عمود «ثلاجة» يظهر لأصناف الثلاجة، '
                       'و«❄ يسمح» يحدده المشرف فقط (ويعتمد الصنف معه). ↑↓ للتنقل وEnter لاعتماد الصف أو فك اعتماده.',
                       'The items added to each platform, which are approved, and the problem, available quantity in the '
                       'chosen branch and the platform price. No item is listed without a supervisor’s approval, and '
                       'prescription medicines are approved only by an explicit decision per item. A blocked, restricted or '
                       'fridge item (unless allowed) is not sold even when approved. The "Fridge" column shows for fridge '
                       'items, and "❄ allow" is set by a supervisor only (it approves the item too). ↑↓ to move and Enter '
                       'to approve or unapprove the row.')},
            {'key': 'channels', 'title': T('🔌 المنصات والفروع', '🔌 Platforms & branches'),
             'body': T('إعداد كل منصة: الاسم، كود حسابها في SOFTECH — عميل دائم (كل طلباتها تُسجَّل بيعًا آجلًا بالكامل عليه، ونقطة البيع ترفض أي سداد نقدي أو بطاقة على هذا الحساب)، قاعدة السعر '
                       '(سعر الرف = سعر العبوة + ضريبته مقربًا للقرش، أو سعر الرف + نسبة مقربًا لأقرب ربع جنيه)، احتياطي '
                       'المخزون وأقصى كمية للصنف. كود المنصة لا يتغير بعد وصول طلبات عليها، والفرع المغلق لا يُربط. '
                       'تحتها فروع المنصة: كود المتجر عند '
                       'المنصة وطريقة التوصيل وتفعيله. «إرسال المخزون» يرسل الكميات المتاحة؛ وطالما مفتاح الإرسال مقفول يظهر '
                       '«تجريبي — لا يُرسل» ولا يخرج شيء. سجل الإرسال تحته.',
                       'Each platform’s setup: name, its SOFTECH account code — a «permanent customer» account (all its orders post as a 100% credit sale on it; the POS refuses any cash or card payment on that account), '
                       'the price rule (shelf price = pack price plus its tax, to the piastre; or shelf price + a '
                       'percentage, to the nearest quarter pound), the stock buffer and the most per item. The platform '
                       'code is fixed once orders exist, and a closed branch cannot be linked. '
                       'Below, the platform’s branches: the store code on the platform, the delivery mode and whether it is '
                       'on. "Push stock" sends the available quantities; while the send switch is off it shows "Dry run — '
                       'not sent" and nothing leaves. The push log is below.')},
            {'key': 'settlement', 'title': T('💰 التسويات', '💰 Payouts'),
             'body': T('ارفع ملف التسوية من المنصة (CSV أو Excel) مع الفترة، واكتب اسم عمود كل قيمة في الملف (رقم الطلب، '
                       'الإجمالي، العمولة، التوصيل، الصافي). النظام يطابق كل سطر مع طلباتنا ويعرض العدد: مطابق، غير موجود، '
                       'اختلاف مبلغ، وطلباتنا غير الموجودة بالملف. السطر يُعتبر مطابقًا فقط لطلب سُلِّم للمندوب أو تم توصيله؛ '
                       'غير ذلك يظهر «اختلاف مبلغ» مع حالة الطلب. اضغط تسوية لعرض أسطرها غير المطابقة.',
                       'Upload the platform’s payout file (CSV or Excel) with its period, and type the file’s column name for '
                       'each value (order number, gross, commission, delivery, net). Each line is matched to our orders and '
                       'the counts show: matched, not found, amount mismatch, and our orders missing from the file. A line '
                       'matches only an order that was handed over or delivered; otherwise it shows as a mismatch with the '
                       'order’s status. Click a payout to see its unmatched lines.')},
        ],
        'workflows': ['external_order'],
        'tips': [
            T('لا يُرسل أي شيء لأي منصة طالما مفتاح الإرسال مقفول.', 'Nothing is sent to any platform while the send switch is off.'),
            T('القبول ينشئ مسودة فقط؛ الكاشير هو من يكمّل البيع في SOFTECH.',
              'Accepting only makes a draft; the cashier completes the sale in SOFTECH.'),
            T('كل الجداول تترتب بالضغط على عنوان العمود.', 'Every table sorts by clicking a column header.'),
        ],
        'related': ['pos.order'],
        'tour': [
            {'target': 'marketplace-tabs', 'label': T('التبويبات', 'Tabs'),
             'text': T('الطلبات، إدخال طلب، الأصناف المعروضة، المنصات والفروع، التسويات.',
                       'Orders, enter an order, listed items, platforms & branches, payouts.')},
            {'target': 'marketplace-orders-grid', 'label': T('📦 الطلبات', '📦 Orders'),
             'text': T('طلبات فروعك بحالتها. اضغط طلبًا لفتح تفاصيله.', 'Your branches’ orders with their status. Click one to open it.')},
            {'target': 'marketplace-order-actions', 'label': T('قبول / رفض / الحالة', 'Accept / Reject / Status'),
             'text': T('القبول = مسودة في نقطة البيع على حساب المنصة. الرفض يحتاج سببًا.',
                       'Accept = a POS draft on the platform account. Rejecting needs a reason.'),
             'open_hint': _ORDER_ROW},
            {'target': 'marketplace-manual-form', 'label': T('✍️ إدخال طلب', '✍️ Enter an order'),
             'text': T('المنصة والفرع ورقم الطلب، ثم الأصناف بالبحث وEnter.', 'Platform, branch and order number, then items by search and Enter.'),
             'open_hint': T('افتح تبويب «✍️ إدخال طلب».', 'Open the "✍️ Enter an order" tab.')},
            {'target': 'marketplace-listings-grid', 'label': T('🏷️ الأصناف المعروضة', '🏷️ Listed items'),
             'text': T('اعتماد المشرف شرط للعرض؛ الروشتة باعتماد صريح لكل صنف. Enter يعتمد الصف.',
                       'A supervisor’s approval is required; prescription items need an explicit one each. Enter approves the row.'),
             'open_hint': T('افتح تبويب «🏷️ الأصناف المعروضة».', 'Open the "🏷️ Listed items" tab.')},
            {'target': 'marketplace-channel-settings', 'label': T('إعداد المنصة', 'Platform setup'),
             'text': T('كود حساب المنصة في SOFTECH وقاعدة السعر والاحتياطي وفروع المنصة.',
                       'The platform’s SOFTECH account code, price rule, buffer and the platform’s branches.'),
             'open_hint': _CHANNELS_TAB},
            {'target': 'marketplace-push-stock', 'label': T('إرسال المخزون', 'Push stock'),
             'text': T('يرسل الكميات المتاحة للمنصة ويسجلها في سجل الإرسال.', 'Sends the available quantities to the platform and logs them.'),
             'warn': T('مع مفتاح الإرسال مقفول يظهر «تجريبي — لا يُرسل» ولا يخرج شيء.',
                       'With the send switch off it shows "Dry run — not sent" and nothing leaves.'),
             'open_hint': _CHANNELS_TAB},
            {'target': 'marketplace-settlement-upload', 'label': T('رفع التسوية', 'Upload payout'),
             'text': T('الملف والفترة وأسماء الأعمدة، ثم المطابقة مع طلباتنا.', 'The file, period and column names, then matching to our orders.'),
             'open_hint': T('افتح تبويب «💰 التسويات».', 'Open the "💰 Payouts" tab.')},
        ],
        'updated': '2026-11-19',
    },
]
