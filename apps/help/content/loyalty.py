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
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول النقاط والولاء والإحالات', 'A tour of the points, loyalty & referrals module'),
            'summary': T('إزاي تشوف رصيد نقاط العميل الحي من SOFTECH وتعدّله بسبب، وكتالوج المكافآت، وبعدين إزاي تتابع الإحالات من الدعوة لحد مكافأة المُحيل.',
                         'How to see a customer\'s live SOFTECH points balance and adjust it with a reason, the reward catalog, and then how to follow referrals from the invite to rewarding the referrer.'),
            'roles': ['admin', 'call_center', 'supervisor'],
            'steps': [
                {'target': 'nav-loyalty', 'nav': '/loyalty',
                 'text': T('«العملاء» ← «النقاط والولاء».', '"Customers" → "Points & loyalty".'),
                 'more': T('الرصيد الأساسي للعميل محفوظ في SOFTECH وبيكسبه من مشتريات النقدي والتوصيل.\n'
                           '• الشاشة دي للكول سنتر والمشرفين: عرض الرصيد وتعديله.\n'
                           '• موظف الفرع عنده شاشة أبسط للاستعلام بس: «استعلام نقاط الفرع».',
                           'The customer\'s main balance lives in SOFTECH and is earned on cash and delivery purchases.\n'
                           '• This screen is for the call center and supervisors: view and adjust the balance.\n'
                           '• Branch staff have a simpler look-up-only screen: "Branch points lookup".')},
                {'target': 'loyalty-program-customer', 'route': '/loyalty',
                 'text': T('ابحث عن العميل بالاسم أو الهاتف أو PIC.', 'Search the customer by name, phone or PIC.'),
                 'more': T('اختار العميل من النتايج، وتحت بيظهر كارت رصيده وسجل معاملاته وسجل تعديلات SOFTECH.\n'
                           '• «×» جنب اسمه بيمسح الاختيار.',
                           'Pick the customer from the results; below appear their balance card, transaction log and SOFTECH adjustment log.\n'
                           '• "×" beside the name clears the choice.')},
                {'target': 'loyalty-program-account', 'route': '/loyalty',
                 'text': T('بعد اختيار العميل: «رصيد SOFTECH (الأساسي)» ودرجته.', 'After choosing a customer: "SOFTECH balance (main)" and their tier.'),
                 'more': T('الرقم الكبير هو الرصيد الرسمي من SOFTECH، وتحته «نقاط إضافية (إحالات / حملات)» لو موجودة.\n'
                           '• «⚠ لا يوجد PIC» = العميل مالوش رصيد في SOFTECH — لازم يتربط بكوده الأول.',
                           'The big number is the official SOFTECH balance, with "Extra points (referrals / campaigns)" below it when present.\n'
                           '• "⚠ No PIC" = the customer has no SOFTECH balance — link their code first.')},
                {'target': 'loyalty-program-adjust', 'route': '/loyalty',
                 'text': T('«تعديل نقاط SOFTECH» — رقم موجب للإضافة أو سالب للخصم، وسبب إلزامي.', '"Adjust SOFTECH points" — a positive number adds, negative deducts, with a required reason.'),
                 'more': T('بعد «تنفيذ في SOFTECH» التعديل بيتكتب فعلاً في SOFTECH ويأثر على رصيد العميل في كل الفروع.\n'
                           '• بيتسجّل باسمك والسبب في «سجل تعديلات SOFTECH».\n'
                           '• متاح لمن عنده صلاحية تعديل النقاط بس.',
                           'After "Apply in SOFTECH" the change is really written to SOFTECH and affects the customer\'s balance in all branches.\n'
                           '• It is logged under your name with the reason in the "SOFTECH adjustment log".\n'
                           '• Only users with the points-adjustment permission can do it.')},
                {'target': 'loyalty-program-rewards', 'route': '/loyalty',
                 'text': T('«كتالوج المكافآت» بعدد نقاط كل مكافأة.', 'The "Reward catalog" with each reward\'s points cost.'),
                 'more': T('دي المكافآت اللي العميل يقدر يستبدل بيها نقاطه.\n'
                           '• الاستبدال بيتطلب من شاشة بحث العملاء على الموبايل، وبيبقى طلب بانتظار الاعتماد.\n'
                           '• تحت الكتالوج «درجات الولاء» والحد الأدنى لكل درجة.',
                           'These are the rewards a customer can redeem points for.\n'
                           '• Redemption is requested from the mobile customer lookup and becomes a request awaiting approval.\n'
                           '• Under the catalog are the "Loyalty tiers" and each tier\'s minimum.')},
                {'target': 'nav-referral', 'nav': '/referral',
                 'text': T('«العملاء» ← «الإحالات».', '"Customers" → "Referrals".'),
                 'more': T('العميل أو الموظف بيحيل حد جديد بكوده، والإحالة بتمشي: دعوة ← تسجيل ← تحقق ← مكافأة المُحيل بنقاط إضافية.\n'
                           '• النقاط دي بتظهر في «نقاط إضافية» في شاشة النقاط.',
                           'A customer or employee refers someone new with their code, and the referral moves: invite → register → validate → the referrer is rewarded with extra points.\n'
                           '• Those points show as "Extra points" on the points screen.')},
                {'target': 'loyalty-referral-tabs', 'route': '/referral',
                 'text': T('«قائمة الإحالات» و«كودي».', '"Referral list" and "My code".'),
                 'more': T('• «قائمة الإحالات»: متابعة كل الإحالات وإجراءاتها.\n'
                           '• «كودي»: كود الإحالة بتاعك مع QR ورابط مشاركة، وعدد إحالاتك ونقاطك.',
                           '• "Referral list": follow every referral and act on it.\n'
                           '• "My code": your referral code with a QR and share link, and your referral count and points.')},
                {'target': 'loyalty-referral-status-filter', 'route': '/referral',
                 'text': T('فلتر الحالة: الكل، بانتظار، مدعو، مسجَّل، محقق.', 'Status filter: all, pending, invited, registered, validated.'),
                 'more': T('اشتغل عليها بالترتيب: «بانتظار» محتاجة دعوة، و«مسجَّل» محتاجة تحقق.',
                           'Work through them in order: "Pending" needs an invite, and "Registered" needs validation.')},
                {'target': 'loyalty-referral-table', 'route': '/referral',
                 'text': T('جدول الإحالات: المُحال، المُحيل، الحالة، الاحتيال، التاريخ.', 'The referral table: referred person, referrer, status, fraud, date.'),
                 'more': T('عمود «الاحتيال» درجة بتتلوّن: أصفر من 40 وأحمر من 80.\n'
                           '• الدرجة العالية معناها رقم مشكوك فيه أو تكرار — راجع «الأحداث» قبل أي تحقق.',
                           'The "Fraud" column is a coloured score: yellow from 40 and red from 80.\n'
                           '• A high score means a suspicious or repeated number — check "Events" before validating.')},
                {'target': 'loyalty-referral-row-actions', 'route': '/referral',
                 'text': T('«دعوة» و«تحقق» و«الأحداث».', '"Invite", "Validate" and "Events".'),
                 'more': T('• «دعوة» (للمنتظرة) بيطلب تأكيد ويبعت دعوة واتساب للشخص المُحال.\n'
                           '• «تحقق» (للمسجَّلة) بتكتب فيه «نقاط المكافأة للمُحيل» (افتراضي 100) وبعدين «تأكيد التحقق».\n'
                           '• «الأحداث» بيعرض سجل الإحالة.',
                           '• "Invite" (pending ones) asks for confirmation and sends a WhatsApp invite to the referred person.\n'
                           '• "Validate" (registered ones) lets you set the "Reward points for the referrer" (default 100), then "Confirm validation".\n'
                           '• "Events" shows the referral\'s log.')},
            ],
        },
    ],
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
                                              'The points and loyalty program.'),
             'more': T('هنا بتشوف رصيد أي عميل وتعدّله، وتراجع المكافآت ودرجات الولاء.\n'
                       '• الرصيد الأساسي محفوظ في SOFTECH؛ أي تعديل من هنا بيتكتب هناك ويتسجّل باسمك.',
                       'Here you see and adjust any customer\'s balance, and review rewards and loyalty tiers.\n'
                       '• The main balance lives in SOFTECH; any adjustment here is written there and logged under your name.')},
            {'target': 'loyalty-program-customer', 'text': T('ابحث عن العميل بالاسم أو الهاتف أو PIC.',
                                              'Search the customer by name, phone or PIC.'),
             'more': T('اختار العميل من النتايج، وتحت بيظهر كارت الرصيد و«سجل المعاملات» و«سجل تعديلات SOFTECH».\n'
                       '• «×» جنب الاسم بيمسح الاختيار عشان تدوّر على غيره.',
                       'Pick the customer from the results; below appear the balance card, the "Transaction log" and the "SOFTECH adjustment log".\n'
                       '• "×" beside the name clears it so you can search for someone else.')},
            {'target': 'loyalty-program-account', 'text': T('رصيد نقاط العميل من SOFTECH.',
                                              'The customer\'s points balance from SOFTECH.'),
             'more': T('«رصيد SOFTECH (الأساسي)» هو الرصيد الرسمي، وجنبه درجة الولاء وكود PIC.\n'
                       '• «نقاط إضافية (إحالات / حملات)» بتظهر تحته لو موجودة.\n'
                       '• «⚠ لا يوجد PIC» = مالوش رصيد في SOFTECH ومش هينفع تعدّل.',
                       '"SOFTECH balance (main)" is the official balance, with the loyalty tier and PIC beside it.\n'
                       '• "Extra points (referrals / campaigns)" show below it when present.\n'
                       '• "⚠ No PIC" = no SOFTECH balance and no adjustment possible.')},
            {'target': 'loyalty-program-adjust', 'text': T('«تعديل نقاط SOFTECH» — لمن عنده الصلاحية، والسبب بيتسجّل.',
                                              '"Adjust SOFTECH points" — for those with permission; the reason is recorded.'),
             'more': T('بيفتح نافذة: «النقاط» (موجب = إضافة، سالب = خصم، مثال 100 أو -50) و«السبب (إلزامي)».\n'
                       '• «تنفيذ في SOFTECH» بيكتب التعديل فعلاً ويأثر على الرصيد في كل الفروع.\n'
                       '• الزر مقفول لو العميل مالوش PIC.',
                       'Opens a window: "Points" (positive = add, negative = deduct, e.g. 100 or -50) and "Reason (required)".\n'
                       '• "Apply in SOFTECH" really writes the change and affects the balance in all branches.\n'
                       '• The button is disabled when the customer has no PIC.')},
            {'target': 'loyalty-program-ledger', 'text': T('سجل معاملات النقاط.',
                                              'The points transaction log.'),
             'more': T('كل معاملة بالسبب والتاريخ والمصدر، والنقاط (+ أو −) والرصيد بعدها.\n'
                       '• استخدمه لما عميل يسأل «النقاط دي جت منين؟».',
                       'Each transaction with its reason, date and source, the points (+ or −) and the balance after.\n'
                       '• Use it when a customer asks "where did these points come from?".')},
            {'target': 'loyalty-program-rewards', 'text': T('كتالوج المكافآت.',
                                              'The rewards catalog.'),
             'more': T('المكافآت المتاحة بوصفها وعدد نقاطها — للعرض هنا.\n'
                       '• الاستبدال نفسه بيتطلب من بحث العملاء على الموبايل ويبقى طلب بانتظار الاعتماد.\n'
                       '• تحته «درجات الولاء» بالحد الأدنى لكل درجة.',
                       'The available rewards with their description and points cost — view only here.\n'
                       '• Redemption itself is requested from the mobile customer lookup and becomes a request awaiting approval.\n'
                       '• Below it are the "Loyalty tiers" with each tier\'s minimum.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
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
                                              'Search the customer who is at the branch.'),
             'more': T('للرد على سؤال «كام عندي نقاط؟»: اكتب اسم العميل أو رقمه أو PIC في البحث تحت العنوان واختاره.\n'
                       '• الشاشة دي للاستعلام بس — مفيش فيها تعديل.',
                       'To answer "how many points do I have?": type the customer\'s name, phone or PIC in the search under the title and pick them.\n'
                       '• This screen is look-up only — no changes.')},
            {'target': 'loyalty-branch-balance', 'text': T('رصيد نقاطه.',
                                              'Their points balance.'),
             'more': T('الرصيد بيتجاب من SOFTECH مباشرة، مع اسم العميل ورقمه وكود PIC.\n'
                       '• لو ظهرت رسالة صفرا (مثلاً العميل مالوش PIC) يبقى مفيش رصيد يتعرض.',
                       'The balance is fetched from SOFTECH directly, with the customer\'s name, phone and PIC.\n'
                       '• If a yellow message shows (e.g. the customer has no PIC), there is no balance to show.')},
            {'target': 'loyalty-branch-refresh', 'text': T('«↻ تحديث من SOFTECH» لو الرصيد مش محدّث.',
                                              '"↻ Refresh from SOFTECH" if the balance looks old.'),
             'more': T('بيجيب الرصيد تاني من SOFTECH — مفيد لو العميل لسه دافع فاتورة.\n'
                       '• جنبه وقت «آخر تحديث».',
                       'Fetches the balance again from SOFTECH — useful if the customer has just paid an invoice.\n'
                       '• The "Last updated" time is beside it.')},
            {'target': 'loyalty-branch-tip', 'text': T('جملة جاهزة تقولها للعميل.',
                                              'A ready sentence to tell the customer.'),
             'more': T('«رصيدك الحالي هو … نقطة. للاستفادة بالنقاط، يرجى التواصل مع خدمة العملاء.»\n'
                       '• الاستبدال مش من الفرع — وجّه العميل لخدمة العملاء.',
                       '"Your current balance is … points. To use your points, please contact customer service."\n'
                       '• Redemption is not done at the branch — send the customer to customer service.')},
            {'target': 'loyalty-branch-new-search', 'text': T('بحث عن عميل تاني.',
                                              'Search another customer.'),
             'more': T('«← بحث عن عميل آخر» بيمسح العميل الحالي ويرجّعك للبحث للعميل اللي بعده.',
                       '"← Search another customer" clears the current customer and returns you to the search for the next one.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
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
        'tour': [
            {'target': 'loyalty-referral-header', 'text': T('«نظام الإحالات»: متابعة العملاء المُحالين وكود الإحالة الخاص بك.',
                                              '«Referrals»: follow up referred customers and your own referral code.'),
             'more': T('الإحالة بتمشي: دعوة ← تسجيل ← تحقق ← مكافأة المُحيل بنقاط إضافية.\n'
                       '• فيه حماية من الاحتيال (أرقام وهمية أو مكررة)، فراجع قبل ما تتحقق.',
                       'A referral moves: invite → register → validate → the referrer is rewarded with extra points.\n'
                       '• There is fraud protection (fake or repeated numbers), so review before validating.')},
            {'target': 'loyalty-referral-tabs', 'text': T('«قائمة الإحالات» لمتابعة الإحالات، و«كودي» لعرض كودك وQR ورابط المشاركة وإحصاءاتك.',
                                              '«Referral list» to follow referrals, and «My code» for your code, QR, share link and stats.'),
             'more': T('• «قائمة الإحالات»: الجدول والإجراءات (للكول سنتر والمشرفين).\n'
                       '• «كودي»: ابعت الرابط أو الـQR للعميل عشان يحيل معارفه، وشوف إحالاتك الناجحة ونقاطك.',
                       '• "Referral list": the table and actions (for the call center and supervisors).\n'
                       '• "My code": send the link or QR to a customer so they refer people they know, and see your successful referrals and points.')},
            {'target': 'loyalty-referral-status-filter', 'text': T('فلترة الإحالات حسب الحالة: الكل، بانتظار، مدعو، مسجَّل، محقق.',
                                              'Filter referrals by status: all, pending, invited, registered, validated.'),
             'more': T('• «بانتظار»: محتاجة «دعوة».\n'
                       '• «مسجَّل»: محتاجة «تحقق» بعد ما تتأكد إنه اشترى فعلاً.\n'
                       '• «مدعو» و«محقق» للمتابعة.',
                       '• "Pending": needs an "Invite".\n'
                       '• "Registered": needs "Validate" once you confirm they actually bought.\n'
                       '• "Invited" and "Validated" are for follow-up.')},
            {'target': 'loyalty-referral-table', 'text': T('جدول الإحالات: الشخص المُحال، المُحيل، الحالة، درجة الاحتيال، والتاريخ.',
                                              'The referral table: referred person, referrer, status, fraud score and date.'),
             'more': T('درجة الاحتيال بتتلوّن: أصفر من 40 وأحمر من 80.\n'
                       '• الدرجة العالية = رقم مشكوك فيه أو تكرار — افتح «الأحداث» قبل ما تكافئ حد.',
                       'The fraud score is coloured: yellow from 40 and red from 80.\n'
                       '• A high score = a suspicious or repeated number — open "Events" before rewarding anyone.')},
            {'target': 'loyalty-referral-row-actions', 'text': T('«دعوة» يظهر للإحالة المنتظرة لإرسال دعوة واتساب، «تحقق» للمسجَّلة، و«الأحداث» لسجل الإحالة.',
                                              '«Invite» shows for pending referrals to send a WhatsApp invite, «Validate» for registered ones, and «Events» for the referral log.'),
             'more': T('• «دعوة» بيطلب تأكيد قبل ما يبعت دعوة الواتساب للاسم والرقم.\n'
                       '• «تحقق» بتحدد فيه «نقاط المكافأة للمُحيل» (افتراضي 100) وبعدين «تأكيد التحقق».\n'
                       '• «الأحداث» بيعرض كل اللي حصل في الإحالة.',
                       '• "Invite" asks for confirmation before sending the WhatsApp invite to the name and number.\n'
                       '• "Validate" lets you set the "Reward points for the referrer" (default 100), then "Confirm validation".\n'
                       '• "Events" shows everything that happened on the referral.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
