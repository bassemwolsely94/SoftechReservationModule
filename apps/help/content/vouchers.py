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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
    },
]
