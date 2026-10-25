from . import T

MODULE = {
    'key': 'vouchers', 'group': 'customers', 'icon': '🎫',
    'title': T('القسائم وكوبونات الهدايا', 'Vouchers & gift coupons'),
    'summary': T(
        'قسائم الخصم الإلكترونية: تُنشئها الإدارة (عامة، خاصة بعميل، أول مرة، أو مخصصة بأرقام هواتف) بأنواع خصم نسبة أو مبلغ أو رصيد نقدي أو صنف مجاني، '
        'مع شروط (حد أدنى للطلب، أصناف وفروع مؤهلة، حدود الاستخدام). الصرف عند نقطة البيع آمن برمز تحقق (OTP) يصل لهاتف العميل: '
        'الرمز صالح 3 دقائق و3 محاولات، ولا يُخزَّن أبداً كنص، ومستند الصرف صالح 15 دقيقة. '
        'وفيها أيضاً متابعة «كوبونات الهدايا» الورقية المخزّنة في SOFTECH (المورد 1268) بسريالاتها.',
        'Electronic discount vouchers: management creates them (public, private to one customer, first-time, or limited to phone numbers) as '
        'percent off, fixed amount, cash balance or a free item, with conditions (minimum order, eligible items and branches, usage limits). '
        'Redeeming at the POS is protected by a one-time code (OTP) sent to the customer\'s phone: valid 3 minutes with 3 tries, never stored as '
        'plain text, and the redemption document is valid for 15 minutes. It also tracks the paper "gift coupons" stocked in SOFTECH (supplier 1268) by serial.'),
    'workflows': [{
        'title': T('خطوات صرف القسيمة', 'Voucher redemption steps'),
        'intro': T('الصرف يمر بأربع خطوات ولا يمكن تخطي أي منها.', 'Redemption goes through four steps; none can be skipped.'),
        'states': [
            {'key': 'phone', 'label': T('1) الهاتف والأهلية', '1) Phone & eligibility'), 'desc': T('ابحث عن العميل/الهاتف وأدخل قيمة الطلب؛ النظام يتحقق من الأهلية ويحسب الخصم المتوقع.', 'Find the customer/phone and enter the order value; the system checks eligibility and calculates the expected discount.'), 'next': ['otp']},
            {'key': 'otp', 'label': T('2) إرسال الرمز', '2) Send the code'), 'desc': T('يُرسل رمز من 6 أرقام عبر واتساب (أو يُعرض QR يمسحه العميل).', 'A 6-digit code is sent on WhatsApp (or a QR is shown for the customer to scan).'), 'next': ['verify']},
            {'key': 'verify', 'label': T('3) التحقق', '3) Verify'), 'desc': T('أدخل الرمز الذي يقرأه العميل (3 دقائق، 3 محاولات).', 'Enter the code the customer reads out (3 minutes, 3 tries).'), 'next': ['document']},
            {'key': 'document', 'label': T('4) مستند الصرف', '4) Redemption document'), 'desc': T('يُنشأ مستند صرف صالح 15 دقيقة يُستخدم في نقطة البيع ثم يُعلَّم «مُستخدَم».', 'A redemption document valid for 15 minutes is created, used at the POS, then marked "used".')},
        ],
    }],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول القسائم', 'A tour of the Vouchers module'),
            'summary': T('إزاي القسيمة بتتعمل، بتوصل للعميل، بتتصرف برمز تحقق، ومستند الصرف بيتستخدم في نقطة البيع — ومتابعة الاستخدام.',
                         'How a voucher is created, reaches the customer, is redeemed with a verification code, and how the redemption document is used at the POS — plus usage follow-up.'),
            'roles': ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'supervisor', 'quality_manager'],
            'steps': [
                {'target': 'nav-vouchers', 'nav': '/vouchers',
                 'text': T('القسائم من القائمة: «العملاء» ← «القسائم».',
                           'Vouchers from the menu: "Customers" → "Vouchers".'),
                 'more': T('الموديول ده للخصومات الإلكترونية اللي بتتصرف برمز تحقق على هاتف العميل.\n'
                           '• الإدارة بتعمل القسيمة، والصيادلة والكول سنتر بيصرفوها.\n'
                           '• الصرف بيطلع «مستند صرف» يتستخدم عند الكاشير — القسيمة نفسها مش بتعدّل أي فاتورة لوحدها.',
                           'This module is for electronic discounts redeemed with a verification code on the customer\'s phone.\n'
                           '• Management creates the voucher; pharmacists and the call center redeem it.\n'
                           '• Redeeming produces a "redemption document" used at the cashier — the voucher itself changes no invoice on its own.')},
                {'target': 'vouchers-main-tabs', 'route': '/vouchers',
                 'text': T('الشاشة كلها تبويبات بترتيب الشغل: إنشاء ← صرف ← تنفيذ عند الكاشير ← تقارير.',
                           'The screen is tabs in work order: create → redeem → use at the cashier → reports.'),
                 'more': T('هنمشي عليهم بالترتيب. «🎟️ كوبونات الهدايا» (الكوبونات الورقية المخزّنة في SOFTECH بسريالاتها) بتظهر للمدير والمشرف والمشتريات والجودة بس.',
                           'We will go through them in order. "🎟️ Gift coupons" (the paper coupons stocked in SOFTECH by serial) shows only for admins, supervisors, purchasing and quality.')},
                {'target': 'vouchers-main-new', 'route': '/vouchers',
                 'text': T('١) الإنشاء: «+ قسيمة جديدة».',
                           '1) Create: "+ New voucher".'),
                 'more': T('تحدد مين يقدر يستخدمها («فئة التوزيع»: عام، خاص بعميل، أول مرة، مخصص بالهاتف)، ونوع الخصم وقيمته، والشروط (حد أدنى، أصناف وفروع مؤهلة، حدود الاستخدام والصلاحية).\n'
                           '• الحساب كله بقواعد ثابتة — النظام هو اللي بيحسب الخصم، مش الموظف.',
                           'You set who may use it ("Distribution category": public, private to a customer, first-time, phone-limited), the discount type and value, and the conditions (minimum, eligible items and branches, usage limits and validity).\n'
                           '• The calculation follows fixed rules — the system calculates the discount, not the employee.')},
                {'target': 'vouchers-main-search', 'route': '/vouchers',
                 'text': T('دوّر على القسيمة بالكود أو العنوان.',
                           'Find the voucher by code or title.'),
                 'more': T('لما عميل يجيلك بكود، اكتبه هنا تلاقي القسيمة وحالتها وقيمتها على طول.',
                           'When a customer brings a code, type it here to find the voucher, its status and value at once.')},
                {'target': 'vouchers-main-status', 'route': '/vouchers',
                 'text': T('اختار «نشط» عشان تشوف اللي ينفع يتصرف.',
                           'Choose "Active" to see what can be redeemed.'),
                 'more': T('القسيمة بتبقى «مُستخدَم» لما توصل لحدها، و«منتهي» لما تعدّي فترة صلاحيتها، و«ملغى» لو المدير وقفها.',
                           'A voucher becomes "used" when it reaches its limit, "expired" when its validity ends, and "cancelled" if a manager stops it.')},
                {'target': 'vouchers-main-table', 'route': '/vouchers',
                 'text': T('٢) التوصيل للعميل والصرف: «📱 تخصيص» و«استرداد» من صف القسيمة.',
                           '2) Reach the customer and redeem: "📱 Assign" and "Redeem" on the voucher\'s row.'),
                 'more': T('• «📱 تخصيص» يربط القسيمة برقم عميل معيّن (للقسائم المخصصة بالهاتف).\n'
                           '• «استرداد» يبدأ الأربع خطوات: الهاتف والأهلية ← إرسال الرمز (واتساب أو QR) ← التحقق ← مستند الصرف.\n'
                           '• الرمز صالح 3 دقايق و3 محاولات.',
                           '• "📱 Assign" links the voucher to a specific customer phone (for phone-limited vouchers).\n'
                           '• "Redeem" starts the four steps: phone and eligibility → send the code (WhatsApp or QR) → verify → redemption document.\n'
                           '• The code is valid for 3 minutes and 3 tries.')},
                {'target': 'vouchers-main-tabs', 'route': '/vouchers',
                 'text': T('٣) عند الكاشير: تبويب «🏪 وثائق POS».',
                           '3) At the cashier: the "🏪 POS documents" tab.'),
                 'more': T('دوّر برقم مستند الصرف، اتأكد من القسيمة والخصم والدقايق المتبقية، واضغط «✅ تفعيل الوثيقة (POS)» وقت تنفيذ البيع.\n'
                           '• المستند صالح 15 دقيقة بس ومينفعش يتستخدم مرتين.\n'
                           '• وزر «📱» يبعته للعميل واتساب.',
                           'Search by the redemption document number, check the voucher, the discount and the minutes left, and press "✅ Activate document (POS)" when the sale is made.\n'
                           '• The document is valid for 15 minutes only and cannot be used twice.\n'
                           '• The "📱" button sends it to the customer on WhatsApp.')},
                {'target': 'vouchers-main-tabs', 'route': '/vouchers',
                 'text': T('٤) المتابعة: تبويب «📊 تقارير».',
                           '4) Follow-up: the "📊 Reports" tab.'),
                 'more': T('بيوضح أكتر القسائم استخداماً وقيمتها ونشاط كل موظف في الصرف — منه تعرف القسيمة نجحت ولا لأ، وتلاحظ أي استخدام غريب.',
                           'It shows the most-used vouchers and their value, and each employee\'s redemption activity — so you can tell whether a voucher worked and spot any unusual use.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'vouchers.main',
        'routes': ['/vouchers'],
        'title': T('القسائم', 'Vouchers'),
        'summary': T('إدارة القسائم وصرفها ومستندات نقطة البيع والتقارير، وكوبونات الهدايا الورقية.', 'Manage vouchers, redeem them, POS documents and reports, and paper gift coupons.'),
        'audience': T('الإدارة تنشئ؛ الصيادلة والكول سنتر يصرفون.', 'Management creates; pharmacists and the call center redeem.'),
        'tabs': [
            {'key': 'vouchers', 'title': T('🎫 القسائم', '🎫 Vouchers'),
             'body': T('قائمة القسائم بالكود والفئة والقيمة والاستخدام والصلاحية والحالة. «قسيمة جديدة»: العنوان، الفئة (عام/خاص/أول مرة/مخصص بالهاتف)، آلية الخصم، الحد الأدنى والأقصى، فترة الصلاحية، الحد الكلي ولكل عميل ويومياً، والأصناف والفروع المؤهلة. '
                       '«تخصيص» لإضافة هواتف مسموح لها، و«إلغاء» لإيقاف القسيمة.',
                       'The voucher list with code, category, value, usage, validity and status. "New voucher": title, category (public/private/first-time/phone-limited), discount mechanism, minimum and maximum, validity, total/per-customer/daily limits, and eligible items and branches. '
                       '"Assign" adds allowed phones, "Cancel" stops the voucher.')},
            {'key': 'redeem', 'title': T('💳 استرداد', '💳 Redeem'),
             'body': T('صرف قسيمة لعميل بالخطوات الأربع (الهاتف ← الرمز ← التحقق ← المستند). لو القسيمة مقصورة على أصناف، أكّد وجود صنف منها في الطلب.',
                       'Redeem a voucher for a customer in four steps (phone → code → verify → document). If it is limited to items, confirm one of them is in the order.')},
            {'key': 'documents', 'title': T('🏪 وثائق POS', '🏪 POS documents'),
             'body': T('البحث عن مستند صرف، تعليمه «مُستخدَم» عند تنفيذ البيع، طباعته أو إرساله واتساب.', 'Find a redemption document, mark it "used" when the sale is done, print it or send it on WhatsApp.')},
            {'key': 'report', 'title': T('📊 تقارير', '📊 Reports'), 'body': T('تقرير استخدام القسائم: عدد مرات الصرف والقيمة لكل قسيمة.', 'Voucher usage report: redemptions and value per voucher.')},
            {'key': 'coupons', 'title': T('🎟️ كوبونات الهدايا', '🎟️ Gift coupons'),
             'body': T('كوبونات الهدايا الورقية: ابحث بالسريال لترى تاريخه (شراء ← صرف لعميل ← تحويل لفرع ← استخدام)، و«اختبار فحص الكوبون في POS» لمعرفة هل سيُقبل.',
                       'Paper gift coupons: search a serial to see its history (purchase → issued to a customer → transferred to a branch → used), and "test the POS coupon check" to see whether it would be accepted.')},
            {'key': 'customers', 'title': T('عملاء تجاوزوا (كوبونات)', 'Customers over the limit (coupons)'),
             'body': T('عملاء استخدموا كوبونات أكثر مما صُرف لهم — مؤشر سوء استخدام يحتاج مراجعة.', 'Customers who used more coupons than were issued to them — a misuse signal to review.')},
            {'key': 'no_serial', 'title': T('بدون سريال (كوبونات)', 'Without serial (coupons)'),
             'body': T('سطور بيع استُخدم فيها كوبون بدون سريال صحيح، حسب الفرع والمستخدم — راجعها مع الفرع.', 'Sale lines that used a coupon without a valid serial, by branch and user — review them with the branch.')},
            {'key': 'batches', 'title': T('الدفعات (كوبونات)', 'Batches (coupons)'),
             'body': T('توليد دفعة سريالات جديدة (لا يكتب في SOFTECH)، ملف الطباعة وملف DataLoad، «تجربة بدون حفظ»، ثم «إدخال في SOFTECH» (فاتورتا شراء على المورد 1268) عند تفعيله، و«تحقق من SOFTECH».',
                       'Generate a new serial batch (writes nothing to SOFTECH), the print file and DataLoad file, "rehearse without saving", then "Enter in SOFTECH" (two purchase invoices on supplier 1268) when enabled, and "Verify in SOFTECH".')},
        ],
        'steps': [
            T('لصرف قسيمة: تبويب «استرداد» أو زر «استرداد» بجانب القسيمة.', 'To redeem: the "Redeem" tab or the "Redeem" button next to the voucher.'),
            {'text': T('لإنشاء قسيمة: تبويب «القسائم» ← «قسيمة جديدة».', 'To create one: the "Vouchers" tab → "New voucher".'), 'roles': ['admin', 'supervisor', 'purchasing']},
        ],
        'tips': [
            T('لا تطلب من العميل إرسال الرمز في رسالة؛ يقرأه لك فقط.', 'Do not ask the customer to forward the code in a message; they only read it to you.'),
            T('القسيمة الخاصة تُستخدم فقط من العميل المحدد عليها.', 'A private voucher can only be used by the customer it is set for.'),
        ],
        'related': ['vouchers.mobile', 'pos.order'],
        'tour': [
            {'target': 'vouchers-main-tabs', 'text': T('التبويبات: القسائم، الاسترداد، وثائق POS، والتقارير (وكوبونات الهدايا لمن له صلاحية).',
                                              'Tabs: vouchers, redemption, POS documents and reports (and gift coupons for those allowed).'),
             'more': T('• «🎫 القسائم»: القائمة والإنشاء والتخصيص.\n'
                       '• «💳 استرداد»: صرف قسيمة لعميل بالكود.\n'
                       '• «🏪 وثائق POS»: تدوّر على مستند الصرف وتفعّله وقت البيع.\n'
                       '• «📊 تقارير»: أكتر القسائم استخداماً ونشاط الموظفين.\n'
                       '• «🎟️ كوبونات الهدايا» بتظهر للمدير والمشرف والمشتريات والجودة بس.',
                       '• "🎫 Vouchers": the list, creating and assigning.\n'
                       '• "💳 Redeem": redeem a voucher for a customer by code.\n'
                       '• "🏪 POS documents": find a redemption document and activate it at the sale.\n'
                       '• "📊 Reports": most-used vouchers and staff activity.\n'
                       '• "🎟️ Gift coupons" shows only for admins, supervisors, purchasing and quality.')},
            {'target': 'vouchers-main-new', 'text': T('«+ قسيمة جديدة» يفتح نموذج إنشاء قسيمة.',
                                              '"+ New voucher" opens the create-voucher form.'),
             'more': T('بتكتب العنوان، «فئة التوزيع» (عام، خاص، أول مرة، مخصص بالهاتف)، «آلية الخصم» (خصم %، خصم ثابت، رصيد نقدي، صنف مجاني) وقيمته.\n'
                       '• وكمان الحد الأدنى للطلب والحد الأقصى للخصم، فترة الصلاحية، حدود الاستخدام (الكلي / لكل عميل / يومياً)، والأصناف المؤهلة.\n'
                       '• الزر بيظهر بس لو صلاحيتك تسمح بالإنشاء.',
                       'You enter the title, the "Distribution category" (public, private, first-time, phone-limited), the "Discount mechanism" (percent, fixed, cash credit, free item) and its value.\n'
                       '• Also the minimum order and maximum discount, the validity period, usage limits (total / per customer / daily), and eligible items.\n'
                       '• The button shows only if your permission allows creating.')},
            {'target': 'vouchers-main-search', 'text': T('ابحث بكود القسيمة أو عنوانها.',
                                              'Search by voucher code or title.'),
             'more': T('مفيد لما العميل يقولك كود قسيمة معاه. جنبه فلتر «كل الأنواع» و«كل الفئات» لو عايز تضيّق أكتر.',
                       'Handy when a customer gives you a voucher code. Next to it, "All types" and "All categories" filters narrow it further.')},
            {'target': 'vouchers-main-status', 'text': T('فلتر الحالة: نشط، مُستخدَم، منتهي، ملغى.',
                                              'Status filter: active, used, expired, cancelled.'),
             'more': T('القسيمة «النشطة» بس هي اللي ينفع تتصرف أو تتخصص أو تتلغى. المنتهية أو المُستخدمة بالكامل بتفضل في القائمة للمتابعة.',
                       'Only an "active" voucher can be redeemed, assigned or cancelled. Expired or fully used ones stay in the list for follow-up.')},
            {'target': 'vouchers-main-table', 'text': T('جدول القسائم — الإجراءات في آخر الصف: «استرداد»، «📱 تخصيص»، «إلغاء».',
                                              'The vouchers table — actions at the end of the row: "Redeem", "📱 Assign", "Cancel".'),
             'more': T('عمود «الاستخدام» بيوضح اتصرفت كام مرة من الحد الكلي.\n'
                       '• «استرداد» بيبدأ خطوات الصرف (الهاتف ← الرمز ← التحقق ← المستند).\n'
                       '• «📱 تخصيص» يضيف رقم عميل مسموح له بالقسيمة.\n'
                       '• «إلغاء» بيوقف القسيمة نهائياً بعد تأكيد، والسيستم بيسمح بيه للمدير بس.',
                       'The "Usage" column shows how many times it was used out of the total limit.\n'
                       '• "Redeem" starts the redemption steps (phone → code → verify → document).\n'
                       '• "📱 Assign" adds a customer phone allowed to use the voucher.\n'
                       '• "Cancel" stops the voucher for good after a confirmation, and the system allows it for managers only.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'vouchers.mobile',
        'routes': ['/m/vouchers'],
        'title': T('صرف قسيمة (موبايل)', 'Redeem a voucher (mobile)'),
        'summary': T('صرف قسيمة من الموبايل: اختر القسيمة ← هاتف العميل وقيمة الطلب ← إرسال رمز التحقق ← أدخل الرمز ← يُنشأ مستند الصرف.',
                     'Redeem on the phone: pick the voucher → customer phone and order value → send the code → enter it → the redemption document is created.'),
        'audience': T('الصيادلة والمندوبون.', 'Pharmacists and salespeople.'),
        'steps': [T('بعد «تم التحقق» استخدم رقم المستند في نقطة البيع خلال 15 دقيقة.', 'After "verified", use the document number at the POS within 15 minutes.')],
        'related': ['vouchers.main'],
        'tour': [
            {'target': 'vouchers-mobile-header', 'text': T('«صرف قسيمة» من الموبايل: اختر القسيمة، أدخل بيانات العميل، ثم أكّد برمز التحقق.',
                                              '«Redeem voucher» on mobile: pick the voucher, enter the customer\'s details, then confirm with the verification code.'),
             'more': T('الشاشة دي لصرف قسيمة لعميل واقف قدامك أو على التليفون، من غير ما تفتح الكمبيوتر.\n• الخطوات بالترتيب: القسيمة ← هاتف العميل ← رمز التحقق ← مستند الصرف.\n• المستند اللي بيطلع في الآخر هو اللي بيتستخدم في نقطة البيع.',
                       "This screen redeems a voucher for a customer in front of you or on the phone, without opening the computer.\n• The steps in order: the voucher → the customer's phone → the verification code → the redemption document.\n• The document produced at the end is what gets used at the point of sale.")},
            {'target': 'vouchers-mobile-list', 'text': T('القسائم الفعّالة بكودها وقيمتها — اضغط على القسيمة التي يريد العميل صرفها.',
                                              'Active vouchers with their code and value — tap the one the customer wants to redeem.'),
             'more': T('هنا بتظهر القسائم الفعّالة بس، بالكود والقيمة. اضغط القسيمة اللي العميل عايز يستخدمها عشان تفتح خطوة بيانات العميل.\n• لو القائمة فاضية يبقى مفيش قسائم فعّالة دلوقتي.',
                       'Only active vouchers show here, with their code and value. Tap the one the customer wants to use to open the customer-details step.\n• If the list is empty, there are no active vouchers right now.')},
            {'target': 'vouchers-mobile-phone', 'text': T('بعد اختيار القسيمة: اكتب هاتف العميل، وقيمة الطلب اختيارياً، والأصناف المؤهلة إن طُلبت.',
                                              'After picking a voucher: enter the customer\'s phone, optionally the order value, and the eligible items if asked.'),
             'more': T('«هاتف العميل» إجباري — عليه بيوصل رمز التحقق. «قيمة الطلب» اختيارية لكنها بتساعد النظام يتحقق من الحد الأدنى ويحسب الخصم.\n• لو القسيمة مقصورة على أصناف، لازم تعلّم الصنف الموجود فعلاً في طلب العميل.',
                       '"Customer phone" is required — the verification code goes to it. "Order value" is optional but helps the system check the minimum and calculate the discount.\n• If the voucher is limited to certain items, you must tick the item that is really in the customer\'s order.')},
            {'target': 'vouchers-mobile-send-otp', 'text': T('«إرسال رمز التحقق» يرسل رمزاً لهاتف العميل لتأكيد الصرف.',
                                              '«Send verification code» sends a code to the customer\'s phone to confirm the redemption.'),
             'more': T('بيبعت رمز تحقق لهاتف العميل عشان نتأكد إن صاحب الرقم موافق على الصرف.\n• الرمز صالح 3 دقايق و3 محاولات.\n• لو النظام رفض (مثلاً القسيمة مش لعميل ده أو الطلب أقل من الحد الأدنى) هيظهر السبب تحت.',
                       "It sends a verification code to the customer's phone to confirm the owner of the number agrees to the redemption.\n• The code is valid for 3 minutes and 3 tries.\n• If the system refuses (e.g. the voucher is not for this customer, or the order is below the minimum) the reason shows below.")},
            {'target': 'vouchers-mobile-code', 'text': T('بعد الإرسال: أدخل الرمز الذي وصل للعميل هنا (يمكن إرساله أيضاً عبر واتساب).',
                                              'After sending: enter the code the customer received here (it can also be sent via WhatsApp).'),
             'more': T('اكتب الرمز اللي العميل يقراه لك. لو الرسالة ما وصلتش، زر «💬 إرسال عبر واتساب» يفتح الرسالة جاهزة.\n• ما تطلبش من العميل يبعتلك الرمز في رسالة — يقراه لك بس.\n• «← تغيير الرقم» يرجعك لو الهاتف غلط.',
                       'Type the code the customer reads out to you. If the message did not arrive, "💬 Send via WhatsApp" opens it ready to send.\n• Do not ask the customer to forward the code in a message — they only read it to you.\n• "← Change number" takes you back if the phone was wrong.')},
            {'target': 'vouchers-mobile-verify', 'text': T('«تحقق وصرف» يتحقق من الرمز وينشئ مستند الصرف برقمه لاستخدامه في نقطة البيع.',
                                              '«Verify and redeem» checks the code and creates the redemption document with its number for use at the POS.'),
             'more': T('لو الرمز صح، بيظهر «تم التحقق وإنشاء مستند الصرف» برقم المستند ووقت انتهائه.\n• استخدم رقم المستند في نقطة البيع خلال 15 دقيقة، وبعد كده بيتعلّم «مُستخدَم».\n• «صرف قسيمة أخرى» يرجعك للقائمة.',
                       'If the code is right, "Verified and redemption document created" shows with the document number and when it expires.\n• Use the document number at the point of sale within 15 minutes; it is then marked "used".\n• "Redeem another voucher" takes you back to the list.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
