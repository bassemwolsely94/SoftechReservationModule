from . import T

MODULE = {
    'key': 'loyalty', 'group': 'customers', 'icon': '🏆',
    'title': T('النقاط والولاء والإحالات', 'Points, loyalty & referrals'),
    'summary': T(
        'رصيد نقاط العميل الأساسي يُحفظ في SOFTECH ويكتسبه من مشتريات قنوات النقدي والتوصيل (التعاقد والتأمين لا يكتسبان نقاطاً). '
        'فوقه نقاط إضافية من الإحالات والحملات، ودرجات ولاء، وكتالوج مكافآت يُستبدل بطلب يعتمده الكول سنتر. '
        'نظام الإحالة: لكل موظف/عميل كود إحالة؛ العميل الجديد المُحال يُدعى ويسجّل ثم يُتحقق منه فيكافأ المُحيل، مع حماية من الاحتيال.',
        'The customer\'s main points balance lives in SOFTECH and is earned on cash and delivery purchases (contract and insurance earn no points). '
        'On top of it are extra points from referrals and campaigns, loyalty tiers, and a reward catalog redeemed by a request the call center approves. '
        'Referrals: every employee/customer has a referral code; a referred new customer is invited, registers, is validated, and the referrer is rewarded, with fraud protection.'),
    'workflows': [{
        'title': T('مراحل الإحالة', 'Referral stages'),
        'model': 'referral.ReferralLead', 'field': 'status',
        'states': [
            {'key': 'pending', 'label': T('بانتظار الاتصال', 'Waiting for contact'), 'desc': T('إحالة جديدة لم تُدعَ بعد.', 'A new referral not invited yet.'), 'next': ['invited', 'rejected', 'expired']},
            {'key': 'invited', 'label': T('تم إرسال الدعوة', 'Invited'), 'desc': T('أُرسلت دعوة واتساب للشخص المُحال.', 'A WhatsApp invite was sent to the referred person.'), 'next': ['registered', 'expired']},
            {'key': 'registered', 'label': T('سجّل', 'Registered'), 'desc': T('سجّل الشخص المُحال.', 'The referred person registered.'), 'next': ['validated', 'rejected']},
            {'key': 'validated', 'label': T('تم التحقق', 'Validated'), 'desc': T('تحقق الموظف أنه عميل حقيقي (اشترى فعلاً)، ويحدد نقاط مكافأة المُحيل.', 'Staff confirmed a real customer (who actually bought) and set the referrer\'s reward points.'), 'next': ['rewarded']},
            {'key': 'rewarded', 'label': T('تم المكافأة', 'Rewarded'), 'desc': T('حصل المُحيل على نقاطه.', 'The referrer got their points.')},
            {'key': 'rejected', 'label': T('مرفوض (احتيال)', 'Rejected (fraud)'), 'desc': T('رُفضت لاشتباه احتيال (مثلاً رقم وهمي أو تكرار).', 'Rejected for suspected fraud (e.g. fake or repeated number).')},
            {'key': 'expired', 'label': T('انتهت الصلاحية', 'Expired'), 'desc': T('لم يُكمل خلال المدة.', 'Not completed in time.')},
            {'key': 'frozen', 'label': T('مجمّد', 'Frozen'), 'desc': T('جُمّد بسبب إساءة استخدام رموز التحقق.', 'Frozen for abuse of verification codes.')},
        ],
    }],
}

SCREENS = [
    {
        'key': 'loyalty.program',
        'routes': ['/loyalty'],
        'title': T('النقاط والولاء', 'Points & loyalty'),
        'summary': T('ابحث عن عميل لترى رصيد نقاطه في SOFTECH والنقاط الإضافية وسجل معاملاته، وعدّل النقاط، واعتمد طلبات استبدال المكافآت المعلّقة.',
                     'Search a customer to see their SOFTECH points, extra points and transaction log, adjust points, and approve pending reward redemptions.'),
        'audience': T('الكول سنتر والمشرفون (التعديل والاعتماد).', 'Call center and supervisors (adjusting and approving).'),
        'steps': [
            T('ابحث بالاسم أو الهاتف أو كود PIC.', 'Search by name, phone or PIC.'),
            T('«تعديل نقاط SOFTECH»: رقم موجب للإضافة أو سالب للخصم (مثال 100 أو -50) مع سبب إلزامي ← «تنفيذ في SOFTECH». يؤثر على رصيد كل الفروع.',
              '"Adjust SOFTECH points": a positive number to add or negative to deduct (e.g. 100 or -50) with a required reason → "Apply in SOFTECH". It affects the balance in all branches.'),
            T('يمين الصفحة: كتالوج المكافآت وطلبات الاستبدال المعلّقة للاعتماد، ودرجات الولاء.', 'On the side: the reward catalog, pending redemptions to approve, and loyalty tiers.'),
        ],
        'tips': [T('العميل بدون PIC لا يملك رصيداً في SOFTECH — اربطه بكوده أولاً.', 'A customer without a PIC has no SOFTECH balance — link their code first.')],
        'workflows': [],
        'related': ['loyalty.branch', 'customers.detail'],
        'tour': [
            {'target': 'loyalty-program-header', 'text': T('نظام النقاط والولاء.',
                                              'The points and loyalty program.')},
            {'target': 'loyalty-program-customer', 'text': T('ابحث عن العميل بالاسم أو الهاتف أو PIC.',
                                              'Search the customer by name, phone or PIC.')},
            {'target': 'loyalty-program-account', 'text': T('رصيد نقاط العميل من SOFTECH.',
                                              'The customer\'s points balance from SOFTECH.')},
            {'target': 'loyalty-program-adjust', 'text': T('تعديل النقاط — لمن عنده الصلاحية، والسبب بيتسجّل.',
                                              'Adjust points — for those with permission; the reason is recorded.')},
            {'target': 'loyalty-program-ledger', 'text': T('سجل معاملات النقاط.',
                                              'The points transaction log.')},
            {'target': 'loyalty-program-rewards', 'text': T('كتالوج المكافآت.',
                                              'The rewards catalog.')},
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'loyalty.branch',
        'routes': ['/loyalty/branch'],
        'title': T('استعلام نقاط الفرع', 'Branch points lookup'),
        'summary': T('للرد على سؤال العميل في الفرع «كام عندي نقاط؟»: بحث وعرض الرصيد الحي من SOFTECH فقط، بدون تعديل.',
                     'To answer the walk-in question "how many points do I have?": search and show the live SOFTECH balance only, no changes.'),
        'audience': T('موظفو الفرع.', 'Branch staff.'),
        'steps': [
            T('ابحث بالاسم أو الهاتف أو PIC، ثم «تحديث من SOFTECH» لأحدث رصيد.', 'Search by name, phone or PIC, then "Refresh from SOFTECH" for the latest balance.'),
            T('لاستبدال النقاط وجّه العميل لخدمة العملاء.', 'To redeem points, send the customer to customer service.'),
        ],
        'workflows': [],
        'related': ['loyalty.program'],
        'tour': [
            {'target': 'loyalty-branch-header', 'text': T('ابحث عن العميل اللي في الفرع.',
                                              'Search the customer who is at the branch.')},
            {'target': 'loyalty-branch-balance', 'text': T('رصيد نقاطه.',
                                              'Their points balance.')},
            {'target': 'loyalty-branch-refresh', 'text': T('«↻ تحديث من SOFTECH» لو الرصيد مش محدّث.',
                                              '"↻ Refresh from SOFTECH" if the balance looks old.')},
            {'target': 'loyalty-branch-tip', 'text': T('جملة جاهزة تقولها للعميل.',
                                              'A ready sentence to tell the customer.')},
            {'target': 'loyalty-branch-new-search', 'text': T('بحث عن عميل تاني.',
                                              'Search another customer.')},
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'loyalty.referral',
        'routes': ['/referral'],
        'title': T('نظام الإحالات', 'Referrals'),
        'summary': T('قائمة الإحالات بحالاتها مع إجراءات الدعوة والتحقق، وكود الإحالة الخاص بك (QR ورابط) لتشاركه.',
                     'The referral list by status with invite and validate actions, and your own referral code (QR and link) to share.'),
        'audience': T('الكول سنتر والمشرفون؛ كل موظف يرى كوده.', 'Call center and supervisors; every employee sees their own code.'),
        'tabs': [
            {'key': 'leads', 'title': T('قائمة الإحالات', 'Referral list'),
             'body': T('الإحالات حسب الحالة. «دعوة» يرسل دعوة واتساب، «تحقق» يؤكد الإحالة ويحدد نقاط المكافأة للمُحيل، و«الأحداث» تعرض سجلها وإشارات الاحتيال.',
                       'Referrals by status. "Invite" sends a WhatsApp invite, "Validate" confirms it and sets the referrer\'s reward points, and "Events" shows its log and fraud signals.')},
            {'key': 'mycode', 'title': T('كودي', 'My code'),
             'body': T('كود الإحالة الخاص بك مع QR ورابط للمشاركة، وإجمالي إحالاتك والتحويلات الناجحة والنقاط المكتسبة.', 'Your referral code with a QR and a share link, and your total referrals, successful conversions and points earned.')},
        ],
        'related': ['analytics.referral_stats'],
        'updated': '2026-10-10',
    },
]
