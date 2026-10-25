from . import T

MODULE = {
    'key': 'delivery', 'group': 'operations', 'icon': '🚚',
    'title': T('توصيل الطلبات', 'Home delivery'),
    'summary': T(
        'إدارة طلبات التوصيل من الإنشاء حتى التسليم والتحصيل: الطلب يأتي من الكول سنتر أو الفرع، يُجهَّز في الفرع، '
        'يُكلَّف به سائق (فردياً أو ضمن «مسار» يجمع عدة طلبات)، السائق يقبل ويخرج ويسلّم مع إثبات التسليم (اسم المستلم، صورة، وموقعه)، '
        'ثم يُطابَق النقد المحصَّل. العميل يستطيع متابعة طلبه برابط تتبع بدون تسجيل دخول.',
        'Manage delivery orders from creation to delivery and cash collection: an order comes from the call center or a branch, '
        'is prepared at the branch, assigned to a driver (alone or in a "route" of several orders), the driver accepts, goes out and '
        'delivers with proof of delivery (recipient name, photo and location), then the collected cash is reconciled. The customer '
        'can follow the order with a tracking link, no login needed.'),
    'workflows': [{
        'title': T('مراحل طلب التوصيل', 'Delivery order stages'),
        'model': 'delivery.DeliveryOrder', 'field': 'status',
        'transitions': 'apps.delivery.views.VALID_TRANSITIONS',
        'states': [
            {'key': 'created', 'label': T('جديد', 'New'), 'desc': T('سُجّل الطلب.', 'Order recorded.'),
             'next': ['pending_review', 'preparing', 'cancelled']},
            {'key': 'pending_review', 'label': T('بانتظار المراجعة', 'Pending review'),
             'desc': T('يحتاج مراجعة (أصناف، سعر، عنوان) قبل التحضير.', 'Needs a check (items, price, address) before preparing.'),
             'next': ['preparing', 'cancelled']},
            {'key': 'preparing', 'label': T('جاري التحضير', 'Preparing'), 'desc': T('الفرع يجهّز الأصناف ويصدر مستند التجهيز.', 'The branch prepares the items and issues the preparation document.'),
             'next': ['ready', 'cancelled']},
            {'key': 'ready', 'label': T('جاهز للتسليم', 'Ready'), 'desc': T('مُغلَّف وينتظر سائقاً.', 'Packed and waiting for a driver.'),
             'next': ['assigned', 'cancelled']},
            {'key': 'assigned', 'label': T('تم التكليف', 'Assigned'), 'desc': T('كُلِّف سائق وينتظر قبوله.', 'A driver is assigned and must accept.'),
             'next': ['driver_accepted', 'cancelled']},
            {'key': 'driver_accepted', 'label': T('السائق قبل الطلب', 'Driver accepted'), 'desc': T('السائق قبل وسيستلم من الفرع (الموقع بيتطلب عند «انطلقت» لو نطاق الفرع مفعّل).', 'The driver accepted and will collect from the branch (location is checked at "Set off" when the branch geofence is on).'),
             'next': ['out_for_delivery', 'cancelled']},
            {'key': 'out_for_delivery', 'label': T('في الطريق', 'Out for delivery'), 'desc': T('السائق في الطريق للعميل.', 'The driver is on the way.'),
             'next': ['delivered', 'partial_delivery', 'customer_unavailable', 'failed']},
            {'key': 'delivered', 'label': T('تم التسليم', 'Delivered'), 'desc': T('سُلّم بإثبات تسليم ومبلغ محصَّل.', 'Delivered with proof and the collected amount.'),
             'next': ['closed']},
            {'key': 'partial_delivery', 'label': T('تسليم جزئي', 'Partial delivery'), 'desc': T('العميل استلم جزءاً فقط — سجّل ما سُلّم وما رجع.', 'The customer took only part — record what was delivered and returned.'),
             'next': ['closed']},
            {'key': 'customer_unavailable', 'label': T('العميل غير متاح', 'Customer unavailable'), 'desc': T('لم يرد أو غير موجود — حاول مرة أخرى أو سجّل فشلاً.', 'No answer or not there — retry or record a failure.'),
             'next': ['out_for_delivery', 'failed', 'cancelled']},
            {'key': 'failed', 'label': T('فشل التسليم', 'Failed'), 'desc': T('لم يتم التسليم — إما يُعاد إنشاؤه أو يُرجَع للفرع.', 'Not delivered — either recreate it or return to the branch.'),
             'next': ['created', 'returned']},
            {'key': 'returned', 'label': T('مُعاد', 'Returned'), 'desc': T('الأصناف رجعت للفرع.', 'The items came back to the branch.'), 'next': ['closed']},
            {'key': 'cancelled', 'label': T('ملغى', 'Cancelled'), 'desc': T('أُلغي قبل الخروج. نهائي.', 'Cancelled before leaving. Final.')},
            {'key': 'closed', 'label': T('مغلق', 'Closed'), 'desc': T('أُغلق بعد التسليم أو الإرجاع ومطابقة النقد. نهائي.', 'Closed after delivery or return and cash reconciliation. Final.')},
        ],
    }],
    'flows': [
        {
            'key': 'lifecycle',
            'title': T('طلب توصيل من التسجيل للتسليم', 'A delivery order, from logging to handover'),
            'summary': T('تسجيل الطلب، توزيعه على الطيار في مسار، وإزاي الطيار بيسلّمه.',
                         'Logging the order, dispatching it to a rider on a route, and how the rider hands it over.'),
            'roles': ['admin', 'call_center', 'supervisor', 'quality_manager'],
            'steps': [
                {'target': 'nav-delivery', 'nav': '/delivery',
                 'text': T('«العمليات» ← «توصيل الطلبات».',
                           '"Operations" → "Deliveries".'),
                 'more': T('هنا بتبدأ أي رحلة توصيل: لوحة فيها كل طلبات التوصيل بحالتها من التسجيل لحد الإغلاق.\n'
                           '• منها بتسجّل الطلب، بتكلّف سائق، وبتتابع التسليم والتحصيل.\n'
                           '• التوزيع على مسارات بيتم من «لوحة التوزيع» اللي هنروح لها بعد شوية.',
                           'Every delivery journey starts here: a board with all delivery orders and their status from logging to closing.\n'
                           '• From it you log the order, assign a driver, and follow delivery and cash collection.\n'
                           '• Grouping orders into routes is done on the "Dispatch board", which we visit in a moment.')},
                {'target': 'delivery-dashboard-new', 'route': '/delivery',
                 'text': T('«+ طلب جديد» لطلب توصيل.',
                           '"+ New order" for a delivery order.'),
                 'more': T('اضغطه لما عميل يطلب توصيل بالتليفون أو من الفرع.\n'
                           '• بيفتح نموذج: مصدر الطلب، الفرع، اسم العميل (مطلوبين)، الهاتف والعنوان والمنطقة، قيمة الطلب ورسوم التوصيل وطريقة الدفع.\n'
                           '• بعد «إنشاء الطلب» بيظهر في القائمة بحالة «جديد».',
                           'Press it when a customer asks for delivery by phone or at the branch.\n'
                           '• It opens a form: order source, branch, customer name (required), phone, address and area, order value, delivery fee and payment method.\n'
                           '• After "Create order" it shows in the list as "New".')},
                {'target': 'delivery-dashboard-status', 'route': '/delivery',
                 'text': T('فلتر الحالة: جديد، مكلَّف، في الطريق…',
                           'Status filter: new, assigned, on the way…'),
                 'more': T('كل زر بيعرض الطلبات اللي في المرحلة دي بس، و«الكل» بيرجّع كل حاجة.\n'
                           '• «جديد» عشان تشوف اللي لسه محتاج تجهيز وتكليف.\n'
                           '• «في الطريق» و«غير متاح» عشان تتابع اللي خرج فعلاً.',
                           'Each chip shows only the orders at that stage; "All" brings everything back.\n'
                           '• "New" shows what still needs preparing and assigning.\n'
                           '• "On the way" and "Unavailable" let you follow what has already left.')},
                {'target': 'delivery-dashboard-orders', 'route': '/delivery',
                 'text': T('اضغط على أي طلب يفتح تفاصيله جنب القائمة.',
                           'Click any order to open its details beside the list.'),
                 'more': T('التفاصيل فيها العميل والعنوان على الخريطة والمبالغ والأصناف وسجل الحالات.\n'
                           '• أزرار الإجراء على كل صف بتتغير حسب الحالة: «تكليف سائق»، «السائق قبل ✓»، «تسليم ✓»، «تحصيل نقدي 💵»، «إغلاق».\n'
                           '• الطلب المتأخر بيتعلّم «⚠️ متأخر».',
                           'The details show the customer, the address on the map, the amounts, the items and the status log.\n'
                           '• The action buttons on each row change with the status: "Assign driver", "Driver accepted ✓", "Deliver ✓", "Cash collection 💵", "Close".\n'
                           '• A late order is marked "⚠️ Late".')},
                {'target': 'nav-delivery-dispatch', 'nav': '/delivery/dispatch',
                 'text': T('التوزيع: «العمليات» ← «لوحة التوزيع».',
                           'Dispatch: "Operations" → "Dispatch board".'),
                 'more': T('لما يبقى عندك كذا طلب جاهز لنفس المنطقة، جمّعهم في «مسار» واحد لسائق واحد بدل ما تكلّف كل طلب لوحده.\n'
                           '• اللوحة بتعرض الطلبات اللي حالتها «جاهز» بس.',
                           'When several ready orders go to the same area, group them in one "route" for one driver instead of assigning each order alone.\n'
                           '• The board only shows orders whose status is "Ready".')},
                {'target': 'delivery-dispatch-ready', 'route': '/delivery/dispatch',
                 'text': T('الطلبات الجاهزة — علّم اللي هتطلع مع بعض.',
                           'Ready orders — tick the ones going out together.'),
                 'more': T('كل سطر فيه اسم العميل والمبلغ والمنطقة وطريقة الدفع.\n'
                           '• علّم الطلبات القريبة من بعض؛ ترتيب علامتك هو ترتيب المحطات عند السائق.\n'
                           '• القائمة بتتحدّث لوحدها كل شوية.',
                           'Each line shows the customer, amount, area and payment method.\n'
                           '• Tick orders that are close to each other; the order you tick them in becomes the stop order for the driver.\n'
                           '• The list refreshes by itself every little while.')},
                {'target': 'delivery-dispatch-driver', 'route': '/delivery/dispatch',
                 'text': T('اختار الطيار.',
                           'Choose the rider.'),
                 'more': T('القائمة فيها السائقين النشطين بس، والرقم جنب الاسم هو عدد طلباته النهارده.\n'
                           '• اختار اللي حمله أقل أو الأقرب للمنطقة.',
                           'The list holds active drivers only; the number beside a name is their order count today.\n'
                           '• Pick the one with the lightest load or closest to the area.')},
                {'target': 'delivery-dispatch-create', 'route': '/delivery/dispatch',
                 'text': T('«إنشاء مسار».',
                           '"Create route".'),
                 'more': T('مش بيشتغل غير لما تختار سائق وطلب واحد على الأقل.\n'
                           '• بيكلّف السائق بكل الطلبات المعلَّمة (حالتها تبقى «مكلَّف») ويحفظ ترتيبها.\n'
                           '• المسار بيظهر في «مسارات اليوم» بحالة «مُخطّط».',
                           'It only works once you pick a driver and at least one order.\n'
                           '• It assigns the driver to every ticked order (their status becomes "Assigned") and saves their order.\n'
                           '• The route appears under "Today\'s routes" as "Planned".')},
                {'target': 'delivery-dispatch-launch', 'route': '/delivery/dispatch',
                 'text': T('«🚚 إطلاق المسار» لما الطيار يتحرك — بيوصله على تطبيقه.',
                           '"🚚 Launch route" when the rider leaves — it reaches their app.'),
                 'more': T('اضغطه لحظة ما السائق يخرج من الفرع فعلاً.\n'
                           '• كل طلبات المسار بتتحول مرة واحدة لـ«في الطريق»، والمسار يبقى «في الطريق 🚚».\n'
                           '• بعدها تتابع شريط التقدّم «تم x/y» والنقدي المتوقّع للمسار.',
                           'Press it the moment the driver actually leaves the branch.\n'
                           '• All the route\'s orders switch to "Out for delivery" at once, and the route becomes "On the way 🚚".\n'
                           '• Then follow the "done x/y" progress bar and the route\'s expected cash.')},
                {'target': 'delivery-driver-header', 'route': '/delivery/my',
                 'text': T('ده اللي الطيار بيشوفه: مهامه بالترتيب، يقبل، «انطلقت»، و«تم التسليم».',
                           'This is what the rider sees: tasks in order — accept, "On my way", "Delivered".'),
                 'more': T('شاشة السائق على موبايله: محطاته بالترتيب مع زر اتصال وخريطة.\n'
                           '• عند العميل يضغط «تم التسليم ✅» ويكتب اسم المستلم والمبلغ المحصَّل، وموقعه بيتسجّل كإثبات.\n'
                           '• الحالة بتتحدّث عندك في لوحة التوصيل لوحدها.',
                           'The driver\'s phone screen: stops in order with a call button and a map.\n'
                           '• At the customer they press "Delivered ✅", enter the recipient name and the cash collected, and their location is saved as proof.\n'
                           '• The status updates on your delivery board by itself.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'delivery.dashboard',
        'routes': ['/delivery'],
        'title': T('لوحة التوصيل', 'Delivery board'),
        'summary': T(
            'إدارة كل طلبات التوصيل بدورة حياتها الكاملة: مؤشرات اليوم (إجمالي، في الانتظار، مكلّف، في الطريق، مُسلَّم، فشل)، فلترة بالحالة، '
            'إنشاء طلب جديد، وتفاصيل كل طلب (العميل والعنوان على خرائط جوجل، المالية، مراجع SOFTECH، الأصناف، سجل الحالات) مع أزرار الإجراء حسب الحالة.',
            'Manage every delivery order through its whole life: today\'s numbers (total, waiting, assigned, on the way, delivered, failed), status filters, '
            'creating a new order, and each order\'s details (customer and address on Google Maps, money, SOFTECH references, items, status log) with actions by status.'),
        'audience': T('الكول سنتر، الصيادلة، المشرفون، مسؤول التوزيع.', 'Call center, pharmacists, supervisors, the dispatcher.'),
        'tabs': [
            {'key': 'details', 'title': T('الأصناف 📦', 'Items 📦'),
             'body': T('أصناف الطلب من SOFTECH: الكمية، سعر الوحدة، الخصم، السعر الفعلي والإجمالي، وكم وفّر العميل.',
                       'Order items from SOFTECH: quantity, unit price, discount, net price and total, and how much the customer saved.')},
            {'key': 'timeline', 'title': T('سجل الحالات 📋', 'Status log 📋'),
             'body': T('كل تغيير حالة بالوقت ومن قام به. «إدخال يدوي» يعني أن الحالة سُجّلت من اللوحة لأن السائق لم يسجلها.',
                       'Every status change with time and who did it. "Manual entry" means it was recorded from the board because the driver did not.')},
        ],
        'steps': [
            T('«طلب جديد»: اختر المصدر (كول سنتر/الفرع) والفرع، بيانات العميل والهاتف والعنوان والمنطقة، قيمة الطلب ورسوم التوصيل، ثم «إنشاء الطلب».',
              '"New order": choose the source (call center/branch) and branch, customer, phone, address and area, order value and delivery fee, then "Create order".'),
            T('افتح الطلب وحرّكه حسب المرحلة: تحضير ← جاهز ← «تكليف سائق» (من قائمة السائقين أو بالاسم والمركبة).',
              'Open the order and move it through the stages: preparing → ready → "Assign driver" (from the list or by name and vehicle).'),
            T('«إبلاغ العميل عبر واتساب» يرسل له حالة الطلب ورابط التتبع.', '"Notify customer on WhatsApp" sends the status and the tracking link.'),
            T('بعد التسليم: «تحصيل نقدي» وأدخل المبلغ المحصَّل — النظام يحسب العجز أو الزيادة مقابل (قيمة الأصناف + رسوم التوصيل).',
              'After delivery: "Cash collection" and enter the collected amount — the system shows any shortage or excess vs (items + delivery fee).'),
        ],
        'tips': [
            T('لو السائق لم يسجل حالة من تطبيقه يمكنك تسجيلها يدوياً من هنا، وتظهر «إدخال يدوي» في السجل.',
              'If the driver did not record a status in their app, you can record it here; it shows as "manual entry".'),
        ],
        'related': ['delivery.dispatch', 'delivery.analytics', 'delivery.driver'],
        'tour': [
            {'target': 'delivery-dashboard-new', 'text': T('«+ طلب جديد» لطلب توصيل.',
                                              '"+ New order" for a delivery order.'),
             'more': T('بيفتح نموذج تسجيل طلب توصيل: «مصدر الطلب» (كول سنتر أو POS الفرع)، الفرع واسم العميل (مطلوبين)، الهاتف والهاتف البديل، العنوان والمنطقة والمحافظة، قيمة الطلب ورسوم التوصيل وطريقة الدفع.\n'
                       '• مفيش حاجة بتتحفظ غير لما تضغط «إنشاء الطلب».\n'
                       '• الطلب الجديد بيظهر في القائمة بحالة «جديد».',
                       'Opens the new delivery order form: "Order source" (call center or branch POS), branch and customer name (required), phone and alternate phone, address, area and governorate, order value, delivery fee and payment method.\n'
                       '• Nothing is saved until you press "Create order".\n'
                       '• The new order shows in the list as "New".')},
            {'target': 'delivery-dashboard-kpis', 'text': T('أرقام اليوم: الإجمالي، المنتظر، وهكذا.',
                                              'Today\'s numbers: total, waiting, and so on.'),
             'more': T('نظرة سريعة على يوم التوصيل:\n'
                       '• «إجمالي اليوم»، «في الانتظار»، «مكلَّف»، «في الطريق»، «مُسلَّم اليوم»، «فشل اليوم».\n'
                       '• «معدل النجاح» ومعاه متوسط وقت التسليم بالدقايق.\n'
                       '• «متأخرة الآن» ومعاه «نقدي معلق» — لو الرقم أحمر ابدأ بالطلبات المتأخرة.',
                       'A quick look at the delivery day:\n'
                       '• "Total today", "Waiting", "Assigned", "On the way", "Delivered today", "Failed today".\n'
                       '• "Success rate" with the average delivery time in minutes.\n'
                       '• "Late now" with "Cash outstanding" — if it is red, start with the late orders.')},
            {'target': 'delivery-dashboard-search', 'text': T('ابحث بالاسم أو الهاتف أو رقم الطلب.',
                                              'Search by name, phone or order number.'),
             'more': T('أسرع طريقة لما عميل يتصل يسأل عن طلبه: اكتب رقمه أو اسمه والقائمة بتتفلتر على طول.\n'
                       '• جنبه فلتر المصدر وزر «🗓️ التاريخ» لو عايز يوم أو فترة تانية غير النهارده.',
                       'The fastest way when a customer calls about their order: type their phone or name and the list filters straight away.\n'
                       '• Next to it are the source filter and the "🗓️ Date" button if you need another day or period.')},
            {'target': 'delivery-dashboard-branch', 'text': T('فلتر الفرع.',
                                              'Branch filter.'),
             'more': T('اختار فرع عشان تشوف طلباته بس، أو «كل الفروع» للصورة الكاملة.\n'
                       '• مفيد للصيدلي اللي بيجهّز طلبات فرعه ولمسؤول التوزيع اللي ماسك كذا فرع.',
                       'Choose a branch to see only its orders, or "All branches" for the full picture.\n'
                       '• Useful for the pharmacist preparing their branch\'s orders and for the dispatcher covering several branches.')},
            {'target': 'delivery-dashboard-status', 'text': T('شرائح الحالة: جديد، مكلَّف، في الطريق…',
                                              'Status chips: new, assigned, on the way…'),
             'more': T('كل شريحة بتعرض مرحلة واحدة: «جديد»، «مكلَّف»، «قبل السائق»، «في الطريق»، «مُسلَّم»، «غير متاح»، «فشل»، «ملغى»، و«الكل».\n'
                       '• اشتغل عليها بالترتيب: الجديد يتكلّف، والغير متاح يتعاد أو يتسجّل فشل.',
                       'Each chip shows one stage: "New", "Assigned", "Driver accepted", "On the way", "Delivered", "Unavailable", "Failed", "Cancelled" and "All".\n'
                       '• Work through them in order: new ones get assigned, unavailable ones get retried or marked failed.')},
            {'target': 'delivery-dashboard-orders', 'text': T('الطلبات — افتح أي طلب لتكليف طيار أو تحديث الحالة.',
                                              'The orders — open one to assign a rider or update its status.'),
             'more': T('اضغط على اسم الطلب يفتح لوحة التفاصيل: العنوان على الخريطة، المبالغ، الأصناف وسجل الحالات.\n'
                       '• الأزرار على الصف بتتغير بالحالة: «تكليف سائق» و«إلغاء» قبل الخروج، «تسليم ✓» و«جزئي» و«غير متاح» و«فشل ✗» وهو في الطريق، و«تحصيل نقدي 💵» و«إغلاق» بعد التسليم.\n'
                       '• «فشل» و«إلغاء» بيطلبوا سبب.',
                       'Click the order to open the details panel: address on the map, amounts, items and status log.\n'
                       '• The row buttons change with the status: "Assign driver" and "Cancel" before leaving, "Deliver ✓", "Partial", "Unavailable" and "Fail ✗" while on the way, and "Cash collection 💵" and "Close" after delivery.\n'
                       '• "Fail" and "Cancel" ask for a reason.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'delivery.dispatch',
        'routes': ['/delivery/dispatch'],
        'title': T('لوحة التوزيع (المسارات)', 'Dispatch board (routes)'),
        'summary': T('جمّع الطلبات الجاهزة في «مسار» لسائق واحد ثم أطلق المسار دفعة واحدة، وتابع حالة مسارات اليوم والنقد المتوقع لكل مسار.',
                     'Group ready orders into one driver\'s "route", launch the whole route at once, and watch today\'s routes and the cash expected per route.'),
        'audience': T('مسؤول التوزيع، الكول سنتر، المشرفون.', 'The dispatcher, call center, supervisors.'),
        'steps': [
            T('من «جاهزة للتكليف» حدد الطلبات المتقاربة جغرافياً.', 'From "Ready to assign" select orders that are close to each other.'),
            T('اختر السائق ثم «إنشاء مسار».', 'Choose the driver, then "Create route".'),
            T('«إطلاق المسار» يكلّف السائق بكل طلباته مرة واحدة؛ تظهر في تطبيقه بالترتيب.', '"Launch route" assigns all its orders to the driver at once; they appear in their app in order.'),
        ],
        'related': ['delivery.dashboard', 'delivery.driver'],
        'tour': [
            {'target': 'delivery-dispatch-header', 'text': T('لوحة توزيع الطلبات على الطيارين.',
                                              'The board for dispatching orders to riders.'),
             'more': T('هنا بتجمّع الطلبات الجاهزة في «مسار» لسائق واحد بدل ما تكلّف كل طلب لوحده.\n'
                       '• يمين: الطلبات الجاهزة وبناء المسار. شمال: مسارات النهارده وحالتها.\n'
                       '• الطلب لازم يكون «جاهز» في لوحة التوصيل عشان يظهر هنا.',
                       'Here you group ready orders into one driver\'s "route" instead of assigning each order alone.\n'
                       '• One side: ready orders and building the route. The other: today\'s routes and their status.\n'
                       '• An order must be "Ready" on the delivery board to show here.')},
            {'target': 'delivery-dispatch-ready', 'text': T('الطلبات الجاهزة — علّم اللي هتطلع مع بعض.',
                                              'Ready orders — tick the ones going out together.'),
             'more': T('كل سطر: اسم العميل والمبلغ شامل التوصيل، والمنطقة وطريقة الدفع.\n'
                       '• علّم الطلبات القريبة من بعض؛ ترتيب ما علّمتها هو ترتيب المحطات في تطبيق السائق.\n'
                       '• فوق القائمة بيظهر عدد المحدد.',
                       'Each line: customer, amount including delivery, area and payment method.\n'
                       '• Tick orders that are close together; the order you tick them in is the stop order in the driver\'s app.\n'
                       '• The selected count shows above the list.')},
            {'target': 'delivery-dispatch-driver', 'text': T('اختار الطيار.',
                                              'Choose the rider.'),
             'more': T('بتظهر هنا السائقين النشطين بس، والرقم بين القوسين هو عدد طلباته النهارده.\n'
                       '• وزّع الحمل: ما تديش سائق واحد كل الطلبات وغيره فاضي.',
                       'Only active drivers appear; the number in brackets is their order count today.\n'
                       '• Spread the load: do not give one driver everything while another is free.')},
            {'target': 'delivery-dispatch-create', 'text': T('«إنشاء مسار».',
                                              '"Create route".'),
             'more': T('بيشتغل بعد ما تختار سائق وطلب واحد على الأقل.\n'
                       '• الطلبات المعلَّمة بتتكلّف للسائق (حالتها «مكلَّف») وبتختفي من قائمة الجاهز.\n'
                       '• المسار بيتسجّل في «مسارات اليوم» بحالة «مُخطّط 📝» لحد ما تطلقه.',
                       'It works once you pick a driver and at least one order.\n'
                       '• The ticked orders are assigned to the driver (status "Assigned") and leave the ready list.\n'
                       '• The route is saved under "Today\'s routes" as "Planned 📝" until you launch it.')},
            {'target': 'delivery-dispatch-routes', 'text': T('مسارات النهارده.',
                                              'Today\'s routes.'),
             'more': T('كل كارت مسار فيه: السائق وعدد الطلبات، الحالة («مُخطّط»، «في الطريق»، «مكتمل»)، النقدي المتوقّع، و«تم x/y» مع شريط التقدّم.\n'
                       '• القائمة بتتحدّث لوحدها، فتقدر تسيبها مفتوحة وتتابع.',
                       'Each route card shows the driver and order count, the status ("Planned", "On the way", "Completed"), the expected cash, and "done x/y" with a progress bar.\n'
                       '• The list refreshes by itself, so you can keep it open and watch.')},
            {'target': 'delivery-dispatch-launch', 'text': T('«🚚 إطلاق المسار» لما الطيار يتحرك.',
                                              '"🚚 Launch route" when the rider leaves.'),
             'more': T('بيظهر على المسارات «المُخطّطة» بس. اضغطه لحظة خروج السائق من الفرع.\n'
                       '• كل طلبات المسار بتتحول مرة واحدة لـ«في الطريق»، والمسار يبقى «في الطريق 🚚».\n'
                       '• بعدها السائق بيسجّل التسليم لكل محطة من تطبيقه.',
                       'It shows only on "Planned" routes. Press it the moment the driver leaves the branch.\n'
                       '• All the route\'s orders switch to "Out for delivery" at once and the route becomes "On the way 🚚".\n'
                       '• The driver then records each stop\'s delivery from their app.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'delivery.driver',
        'routes': ['/delivery/my', '/rider'],
        'title': T('مهام السائق', "Driver's tasks"),
        'summary': T('شاشة السائق على الموبايل: طلبات اليوم بترتيب المسار، مع اتصال بالعميل وفتح الخريطة، وخطوات: قبول ← انطلقت ← تم التسليم مع إثبات التسليم.',
                     'The driver\'s phone screen: today\'s orders in route order, with a call button and map, and the steps: accept → out → delivered with proof of delivery.'),
        'audience': T('السائقون (والمشرف للمتابعة).', 'Drivers (and supervisors to follow).'),
        'steps': [
            T('«قبول الطلب» لكل طلب مكلَّف به، وبعد الاستلام من الفرع «انطلقت 🚚» — ولو نطاق الفرع مفعّل، «انطلقت» محتاجة تفعيل الموقع وإنك تكون جنب الفرع.', '"Accept" each assigned order, then "Set off 🚚" after collecting from the branch — when the branch geofence is on, "Set off" needs your location on and you near the branch.'),
            T('«انطلقت» عند الخروج للعميل.', '"Out" when leaving for the customer.'),
            T('عند العميل: «تم التسليم» ← اسم المستلم، المبلغ المحصَّل، صورة اختيارية وملاحظة (مثال: سُلّم للبواب) ← «تأكيد التسليم». موقعك يُسجَّل تلقائياً كإثبات.',
              'At the customer: "Delivered" → recipient name, amount collected, optional photo and note (e.g. left with the doorman) → "Confirm". Your location is recorded automatically as proof.'),
        ],
        'tips': [T('«متوقّع نقدي» أعلى الشاشة = إجمالي النقد الذي يجب أن تحصّله في مسار اليوم.', '"Expected cash" at the top = the total cash you should collect on today\'s route.')],
        'tour': [
            {'target': 'delivery-driver-header', 'text': T('مهامك النهارده وملخص المسار.',
                                              'Your tasks today and the route summary.'),
             'more': T('لو عندك مسار النهارده هتلاقي رقمه، و«تم x/y» من المحطات، و«متوقّع نقدي» = الفلوس اللي المفروض تحصّلها في المسار كله.\n'
                       '• الشاشة بتتحدّث لوحدها كل نص دقيقة تقريباً.',
                       'If you have a route today you see its number, "done x/y" stops, and "Expected cash" = the money you should collect on the whole route.\n'
                       '• The screen refreshes by itself about every half minute.')},
            {'target': 'delivery-driver-stops', 'text': T('المحطات بالترتيب.',
                                              'The stops in order.'),
             'more': T('كل كارت = عميل: رقم المحطة، الاسم، العنوان، المبلغ وطريقة الدفع (كاش 💵)، وحالة الطلب.\n'
                       '• امشي بالترتيب اللي مسؤول التوزيع حدده.\n'
                       '• لو مفيش مسار، بتظهر الطلبات المكلَّف بيها لوحدها.',
                       'Each card = one customer: stop number, name, address, amount and payment (cash 💵), and the order status.\n'
                       '• Follow the order set by the dispatcher.\n'
                       '• If there is no route, your individually assigned orders show instead.')},
            {'target': 'delivery-driver-call', 'text': T('«📞 اتصال» بالعميل.',
                                              '"📞 Call" the customer.'),
             'more': T('بيفتح الاتصال على رقم العميل مباشرة من موبايلك.\n'
                       '• اتصل قبل ما توصل بشوية تتأكد إنه موجود، أو لو العنوان مش واضح.',
                       'It dials the customer\'s number straight from your phone.\n'
                       '• Call a little before you arrive to check they are in, or if the address is unclear.')},
            {'target': 'delivery-driver-map', 'text': T('«🗺️ خريطة» للعنوان.',
                                              '"🗺️ Map" to the address.'),
             'more': T('بيفتح عنوان العميل على خرائط جوجل في صفحة جديدة عشان تمشي بالملاحة.\n'
                       '• الزر بيظهر بس لو الطلب متسجّل له موقع.',
                       'Opens the customer\'s address on Google Maps in a new page so you can navigate.\n'
                       '• The button shows only when the order has a saved location.')},
            {'target': 'delivery-driver-next', 'text': T('اقبل الطلب بـ«قبول الطلب»، وبعدين «انطلقت 🚚».',
                                              'Accept the order with "Accept order", then "Set off 🚚".'),
             'more': T('الزر بيتغيّر مع الحالة:\n'
                       '• «قبول الطلب» على الطلب المكلَّف — كده الكول سنتر يعرف إنك شفته.\n'
                       '• «انطلقت 🚚» وانت في الفرع ومعاك الطلب: لازم تفعّل الموقع، والنظام ممكن يرفض لو انت بعيد عن الفرع.\n'
                       '• طلبات المسار اللي اتطلق بتوصلك «في الطريق» على طول.',
                       'The button changes with the status:\n'
                       '• "Accept order" on an assigned order — so the call center knows you saw it.\n'
                       '• "Set off 🚚" while at the branch with the order: location must be on, and the system may refuse if you are far from the branch.\n'
                       '• Orders on a launched route reach you already "On the way".')},
            {'target': 'delivery-driver-deliver', 'text': T('«تم التسليم ✅» عند العميل.',
                                              '"Delivered ✅" at the customer.'),
             'more': T('بيفتح «إثبات التسليم»: اسم المستلِم، المبلغ المحصَّل (متعبّي بقيمة الطلب لو كاش)، صورة اختيارية، وملاحظة زي «سُلّم للبواب».\n'
                       '• «تأكيد التسليم» بيسجّل موقعك الحالي كإثبات، وممكن يرفض لو انت بعيد عن عنوان العميل.\n'
                       '• بعدها الطلب يبقى «تم التسليم» في لوحة التوصيل.',
                       'Opens "Proof of delivery": recipient name, amount collected (pre-filled with the order value for cash), optional photo, and a note like "left with the doorman".\n'
                       '• "Confirm delivery" saves your current location as proof, and may refuse if you are far from the customer\'s address.\n'
                       '• The order then shows as "Delivered" on the delivery board.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'delivery.analytics',
        'routes': ['/delivery/analytics'],
        'title': T('تحليلات التوصيل', 'Delivery analytics'),
        'summary': T('أداء التوصيل خلال فترة (اليوم، 7، 30، 90 يوماً) ولكل فرع أو كل الفروع.', 'Delivery performance over a period (today, 7, 30, 90 days) for one or all branches.'),
        'audience': T('المشرفون والإدارة والجودة.', 'Supervisors, management and quality.'),
        'tabs': [
            {'key': 'drivers', 'title': T('🚴 أداء السائقين', '🚴 Driver performance'),
             'body': T('لكل سائق: إجمالي الطلبات، المُسلَّم، معدل النجاح، متوسط وقت التسليم، والنقد المحصَّل.', 'Per driver: total orders, delivered, success rate, average delivery time and cash collected.')},
            {'key': 'heatmap', 'title': T('🗺️ خريطة المناطق', '🗺️ Area map'),
             'body': T('الطلبات حسب المحافظة وأكثر 20 منطقة طلباً — لتوزيع السائقين والفروع.', 'Orders by governorate and the top 20 areas — to plan drivers and branches.')},
            {'key': 'shifts', 'title': T('⏰ تقرير الورديات', '⏰ Shift report'),
             'body': T('توزيع الطلبات على ساعات اليوم وساعة الذروة — لتحديد عدد السائقين في كل وردية.', 'Orders by hour of day and the peak hour — to plan drivers per shift.')},
            {'key': 'csat', 'title': T('⭐ رضا العملاء', '⭐ Customer satisfaction'),
             'body': T('متوسط تقييم العملاء بعد التسليم، توزيع التقييمات، والتقييمات المنخفضة (1-2) لمتابعتها.', 'Average customer rating after delivery, the distribution, and low ratings (1-2) to follow up.')},
        ],
        'related': ['delivery.dashboard'],
        'tour': [
            {'target': 'delivery-analytics-header', 'text': T('«تحليلات التوصيل»: أداء السائقين والمناطق والورديات ورضا العملاء لفترة تختارها.',
                                              '"Delivery analytics": driver, area, shift and customer-satisfaction performance for a period you choose.'),
             'more': T('شاشة قراءة بس — مفيش فيها أي تعديل على الطلبات.\n'
                       '• استخدمها في مراجعة الأسبوع أو الشهر: مين من السائقين محتاج متابعة، وأي منطقة أو ساعة محتاجة سائقين أكتر.',
                       'A read-only screen — it changes nothing on the orders.\n'
                       '• Use it in the weekly or monthly review: which drivers need follow-up, and which area or hour needs more drivers.')},
            {'target': 'delivery-analytics-period', 'text': T('اختار الفترة: «اليوم» أو 7 أو 30 أو 90 يوم، أو حدد من تاريخ لتاريخ.',
                                              'Choose the period: "Today", 7, 30 or 90 days, or set a from–to date range.'),
             'more': T('الأزرار الجاهزة بتملأ التاريخين لوحدها، والزر المختار بيتلوّن.\n'
                       '• لو عايز فترة معيّنة (زي شهر فات) اكتب «من» و«إلى» بنفسك.\n'
                       '• كل التبويبات بتتحسب على نفس الفترة.',
                       'The preset buttons fill both dates for you, and the chosen one is highlighted.\n'
                       '• For a specific period (like last month) type the "from" and "to" dates yourself.\n'
                       '• Every tab is calculated for the same period.')},
            {'target': 'delivery-analytics-branch', 'text': T('اختار فرع معيّن أو «كل الفروع».',
                                              'Choose one branch or "All branches".'),
             'more': T('بيقصر كل الأرقام على طلبات الفرع ده بس.\n'
                       '• قارن الفروع ببعض بإنك تبدّل الفرع وتبص على نفس التبويب.',
                       'Limits every figure to that branch\'s orders.\n'
                       '• Compare branches by switching the branch while looking at the same tab.')},
            {'target': 'delivery-analytics-tabs', 'text': T('التبويبات: «🚴 أداء السائقين»، «🗺️ خريطة المناطق»، «⏰ تقرير الورديات»، «⭐ رضا العملاء».',
                                              'Tabs: "🚴 Driver performance", "🗺️ Area map", "⏰ Shift report", "⭐ Customer satisfaction".'),
             'more': T('• «أداء السائقين»: الطلبات والمُسلَّم ومعدل النجاح ومتوسط الوقت والنقد المحصَّل لكل سائق.\n'
                       '• «خريطة المناطق»: الطلبات حسب المحافظة وأكتر المناطق طلباً.\n'
                       '• «تقرير الورديات»: الطلبات على ساعات اليوم وساعة الذروة.\n'
                       '• «رضا العملاء»: متوسط التقييم والتقييمات المنخفضة لمتابعتها.',
                       '• "Driver performance": orders, delivered, success rate, average time and cash collected per driver.\n'
                       '• "Area map": orders by governorate and the busiest areas.\n'
                       '• "Shift report": orders by hour of day and the peak hour.\n'
                       '• "Customer satisfaction": the average rating and low ratings to follow up.')},
            {'target': 'delivery-analytics-content', 'text': T('هنا بيانات التبويب المفتوح للفترة والفرع اللي اخترتهم.',
                                              'The open tab\'s data for the chosen period and branch shows here.'),
             'more': T('المحتوى بيتغيّر على طول لما تغيّر الفترة أو الفرع أو التبويب.\n'
                       '• لو مفيش طلبات في الفترة دي هتلاقي المساحة فاضية — جرّب فترة أطول.',
                       'The content changes straight away when you change the period, branch or tab.\n'
                       '• If there are no orders in that period the area is empty — try a longer period.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'delivery.mobile_board',
        'routes': ['/m/delivery', '/m/delivery/:id'],
        'title': T('حالة التوصيل (موبايل)', 'Delivery status (mobile)'),
        'summary': T('متابعة طلبات التوصيل من الموبايل: الحالة، علامة «متأخر»، وتفاصيل الطلب (اتصال، واتساب، الموقع، الأصناف، السائق، سجل الحالة) '
                     'وإرسال رابط التتبع للعميل. إجراءات تغيير الحالة تتم من لوحة التوزيع وتطبيق السائق.',
                     'Follow delivery orders on the phone: status, "late" flag, and order details (call, WhatsApp, location, items, driver, status log), '
                     'and send the tracking link to the customer. Status changes are done from the dispatch board and the driver app.'),
        'audience': T('مسؤول التوزيع والمديرون والكول سنتر.', 'The dispatcher, managers and the call center.'),
        'steps': [T('اضغط طلباً ثم «إرسال رابط التتبع للعميل» لو سأل عن طلبه.', 'Tap an order, then "Send tracking link" if the customer asks about it.')],
        'related': ['delivery.dashboard'],
        'tour': [
            {'target': 'delivery-mobile-board-filters', 'text': T('فلتر حالة الطلبات.',
                                              'Order status filter.'),
             'more': T('الشرائح: «النشطة» (الافتراضي)، «جاهز»، «في الطريق»، «تم التسليم»، و«الكل».\n'
                       '• «النشطة» بتوريك اللي لسه ما خلصش — ابدأ بيها.',
                       'The chips: "Active" (the default), "Ready", "On the way", "Delivered" and "All".\n'
                       '• "Active" shows what is not finished yet — start there.')},
            {'target': 'delivery-mobile-board-list', 'text': T('طلبات التوصيل.',
                                              'The delivery orders.'),
             'more': T('الأحدث فوق، والقائمة بتتحدّث لوحدها كل دقيقة.\n'
                       '• في الآخر «تحميل المزيد» لو الطلبات كتير.\n'
                       '• الشاشة دي للمتابعة بس؛ تغيير الحالة بيتم من لوحة التوزيع وتطبيق السائق.',
                       'Newest at the top, and the list refreshes by itself every minute.\n'
                       '• At the bottom, "Load more" when there are many orders.\n'
                       '• This screen is for following only; status changes happen on the dispatch board and in the driver app.')},
            {'target': 'delivery-mobile-board-card', 'text': T('اضغط على طلب لتفاصيله: اتصال، واتساب، الموقع، ورابط التتبع.',
                                              'Tap an order for its details: call, WhatsApp, location and the tracking link.'),
             'more': T('الكارت فيه رقم الطلب وحالته وعلامة «متأخر»، والعميل والمنطقة والسائق ومن إمتى اتسجّل.\n'
                       '• جوه التفاصيل «📍 إرسال رابط التتبع للعميل» بيفتح واتساب برابط يتابع بيه طلبه من غير تسجيل دخول.',
                       'The card shows the order number, status and "late" flag, the customer, area, driver and how long ago it was logged.\n'
                       '• Inside the details, "📍 Send tracking link" opens WhatsApp with a link the customer can follow without logging in.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
