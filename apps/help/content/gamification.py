from . import T

MODULE = {
    'key': 'gamification', 'group': 'home', 'icon': '🏆',
    'title': T('التحفيز — النقاط والمستويات', 'Gamification — points & levels'),
    'summary': T(
        'كل عمل تنجزه في النظام أو في SOFTECH يُحتسب لك نقاطاً تلقائياً: فواتير البيع وربحيتها (الكاش أعلى)، المرتجعات، '
        'الحجوزات وتسليمها، الطلب الضائع واسترداده، المتابعات، طلبات التحويل والرد على الفروع الأخرى، أذون الصرف والاستلام، '
        'طلبات التوريد ISR، الجرد، النواقص والمهام. النقاط ترفع «خبرتك» فترتقي في المستويات وتحصل على لقب جديد وشارات. '
        'البنود التي تُترك متأخرة تخصم نقاطاً بسيطة من ترتيب الفترة فقط — المستوى لا ينزل أبداً. '
        'يمكن استبدال رصيدك بمكافآت من الكتالوج (بموافقة مدير الفرع ثم الإدارة) دون أن ينخفض مستواك أو ترتيبك، '
        'وكل شهر يُتوَّج الأفضل في كل دور «أبطال الشهر».',
        'Every job you do in the system or in SOFTECH earns points automatically: sale invoices and their profitability '
        '(cash scores higher), returns, reservations and their handover, lost sales and their recovery, follow-ups, '
        'transfer requests and replies to other branches, issue/receipt documents, ISR supply requests, stock counts, '
        'shortage lists and tasks. Points raise your "XP" so you climb levels with a new title and badges. Items left '
        'overdue deduct a few points from the period ranking only — your level never drops. Your balance can be spent '
        'on rewards from the catalog (approved by the branch manager, then management) — spending never lowers your '
        'level or rank. Every month the best of each role are crowned champions (بطل الشهر).'),
    'workflows': [{
        'key': 'redemption',
        'title': T('دورة طلب المكافأة', 'Reward request life cycle'),
        'model': 'gamification.Redemption', 'field': 'status',
        'transitions': 'apps.gamification.models.Redemption.TRANSITIONS',
        'intro': T('تُحجز النقاط لحظة الطلب، وتعود تلقائياً عند الرفض أو الإلغاء.',
                   'Points are held the moment you ask, and come back automatically on rejection or cancellation.'),
        'states': [
            {'key': 'pending', 'label': T('بانتظار الموافقة', 'Waiting for approval'),
             'desc': T('الطلب في صندوق الموافقات: مدير الفرع ثم الإدارة. يمكنك إلغاؤه الآن.',
                       'The request is in the approvals inbox: branch manager, then management. You can still cancel it.'),
             'next': ['approved', 'rejected', 'cancelled']},
            {'key': 'approved', 'label': T('معتمد — بانتظار التسليم', 'Approved — to be delivered'),
             'desc': T('تمت الموافقة؛ المسؤول يسلمك المكافأة ويسجل التسليم.',
                       'Approved; the person in charge hands the reward over and records the delivery.'),
             'next': ['fulfilled', 'cancelled']},
            {'key': 'fulfilled', 'label': T('تم التسليم', 'Delivered'),
             'desc': T('استلمت المكافأة — النقاط محسوبة كمستبدلة.', 'You received the reward — the points count as redeemed.'),
             'next': []},
            {'key': 'rejected', 'label': T('مرفوض — أعيدت النقاط', 'Rejected — points returned'),
             'desc': T('رُفض الطلب (أو اعتمده صاحبه بنفسه وهذا غير مسموح) وعادت النقاط لرصيدك.',
                       'The request was rejected (or approved by its own requester, which is not allowed) and the points came back.'),
             'next': []},
            {'key': 'cancelled', 'label': T('ملغي — أعيدت النقاط', 'Cancelled — points returned'),
             'desc': T('ألغيته أنت، أو ألغاه المسؤول بسبب مكتوب، أو انتهت مهلة الموافقة — عادت النقاط.',
                       'You cancelled it, a manager cancelled it with a reason, or the approval timed out — the points came back.'),
             'next': []},
        ],
    }],
}

SCREENS = [
    {
        'key': 'gamification.main',
        'routes': ['/gamification', '/m/gamification'],
        'title': T('التحفيز والمستويات', 'Gamification & levels'),
        'summary': T(
            'ملفك في نظام التحفيز: مستواك ولقبك، نقاطك اليوم والأسبوع والشهر، سلسلة الأيام النظيفة، ترتيبك في فرعك وعلى الشبكة، '
            'الشارات، وما زال ينتظرك من أعمال. يُحدَّث كل نصف ساعة، ويُغلق اليوم كل ليلة.',
            'Your gamification profile: level and title, points today / this week / this month, clean-day streak, rank in '
            'your branch and on the network, badges, and the work still waiting for you. Updated every 30 minutes; each day '
            'is closed overnight.'),
        'audience': T('كل الموظفين. التقارير للمديرين، والإعدادات لمن لديه صلاحية التعديل.',
                      'Every employee. Reports for managers; settings for those allowed to edit.'),
        'steps': [
            T('ابدأ من «ملفي»: أنجز ما في قائمة «لا تترك شيئاً خلفك» — الأحمر منها يخصم نقاطاً عند إغلاق اليوم.',
              'Start from "My profile": clear the "Leave nothing behind" list — red items deduct points at day close.'),
            T('اليوم الذي تعمل فيه بدون أي بند متأخر يمنحك «يوم نظيف» (+10)، وكل 7 أيام نظيفة متتالية مكافأة إضافية.',
              'A working day with nothing overdue gives a "clean day" (+10), and every 7 clean days in a row adds a bonus.'),
            T('تابع ترتيبك في «الترتيب» واطّلع على «كيف تكسب النقاط» لتعرف قيمة كل عمل.',
              'Follow your rank in "Leaderboard" and read "How to earn" to see what each job is worth.'),
        ],
        'tabs': [
            {'key': 'me', 'title': T('🙋 ملفي', '🙋 My profile'),
             'body': T('المستوى وشريط التقدم للترقية التالية، نقاطك، ترتيبك، قائمة الأعمال المعلقة، سلّم المستويات وآخر النقاط.',
                       'Level and progress to the next promotion, your points, rank, pending work, the level ladder and recent points.')},
            {'key': 'leaderboard', 'title': T('🏆 الترتيب', '🏆 Leaderboard'),
             'body': T('ترتيب كامل لزملاء فرعك، وأفضل 10 على كل الفروع (يمكن التصفية بالدور والفترة). المديرون يرون الترتيب كاملاً.',
                       'The full ranking of your branch colleagues, and the network top 10 (filter by role and period). Managers see everything.')},
            {'key': 'branches', 'title': T('🏢 ترتيب الفروع', '🏢 Branches'),
             'body': T('الفروع مرتبة بمتوسط نقاط الموظف النشط — عادل بين الفروع الكبيرة والصغيرة — مع نسبة الأيام النظيفة والبنود المتأخرة.',
                       'Branches ranked by average points per active employee — fair to big and small branches — with clean-day % and items left behind.')},
            {'key': 'badges', 'title': T('🏅 الشارات', '🏅 Badges'),
             'body': T('الشارات المكتسبة وتقدمك نحو الباقي (مثل 100 فاتورة، صديق الفروع، حارس المخزون، أسبوع بلا تأخير).',
                       'Badges you earned and your progress to the rest (e.g. 100 invoices, branch friend, stock guardian, week without delays).')},
            {'key': 'rules', 'title': T('📜 كيف تكسب النقاط', '📜 How to earn'),
             'body': T('كل قاعدة بنقاطها وحدّها اليومي. مبيعات: نقاط لكل فاتورة + لكل 500 جنيه + لكل 100 جنيه ربح (الكاش ×1.5)، بحد يومي حتى لا تطغى الفروع الكبيرة.',
                       'Every rule with its points and daily cap. Sales: points per invoice + per 500 EGP + per 100 EGP of profit (cash ×1.5), capped daily so big branches do not dominate.')},
            {'key': 'champions', 'title': T('👑 أبطال الشهر', '👑 Champions'),
             'body': T('سباق الشهر الحالي لحظياً (المتصدرون لكل دور في فرعك وعلى الشبكة) ولوحة أبطال الأشهر السابقة. أول كل شهر يُتوَّج تلقائياً: بطل كل دور في كل فرع (+200)، وأفضل 3 لكل دور على الشبكة (+500 للأول و+200 للثاني والثالث)، وفرع الشهر، مع إعلان مثبّت للجميع. مكافآت الأبطال تزيد الخبرة والرصيد لكنها لا تدخل في الترتيب. من عليه ملاحظة مراجعة مؤكدة في الشهر لا يُتوَّج. يمكن للإدارة سحب لقب بسبب مكتوب فتُخصم مكافأته.',
                       'This month\'s live race (leaders per role in your branch and on the network) and the hall of fame of past months. On the 1st of each month champions are crowned automatically: each role\'s #1 in each branch (+200), the network top 3 per role (+500 for first, +200 for second and third), and the branch of the month, with a pinned announcement for everyone. Champion bonuses raise XP and balance but never count in the ranking. Anyone with a confirmed audit flag that month is not crowned. Management can revoke a title with a written reason, which reverses its bonus.')},
            {'key': 'rewards', 'title': T('🎁 المكافآت', '🎁 Rewards'),
             'body': T('رصيدك المتاح (صافي ما كسبته ناقص المحجوز والمستبدل) وكتالوج المكافآت. اضغط «استبدال» ثم «تأكيد»؛ يظهر سبب عدم الإتاحة إن وُجد (الرصيد، المستوى، الحد الشهري، الكمية). أسفلها «طلباتي» بحالاتها.',
                       'Your available balance (net earned minus held and redeemed) and the reward catalog. Press "Redeem" then "Confirm"; if a reward is not available the reason shows (balance, level, monthly limit, stock). Below it, "My requests" with their status.')},
            {'key': 'redemptions', 'title': T('📦 طلبات المكافآت', '📦 Reward requests'),
             'body': T('للمديرين: كل طلبات المكافآت. الموافقة من صندوق الموافقات؛ هنا «تم التسليم» مع التفاصيل (التاريخ، كود القسيمة) أو «إلغاء» بسبب مكتوب فتعود النقاط.',
                       'For managers: every reward request. Approval happens in the approvals inbox; here you "Mark delivered" with details (date, voucher code) or "Cancel" with a written reason, which returns the points.')},
            {'key': 'reports', 'title': T('📊 التقارير', '📊 Reports'),
             'body': T('للمديرين: المشاركون، النقاط والخصومات، نسبة الأيام النظيفة، الأفضل ومن يحتاج دعماً، الفئات، توزيع المستويات، الفروع والترقيات، وتصدير Excel.',
                       'For managers: participants, points and deductions, clean-day %, top performers and who needs support, categories, level distribution, branches and promotions, and Excel export.')},
            {'key': 'settings', 'title': T('⚙️ الإعدادات', '⚙️ Settings'),
             'body': T('كتالوج المكافآت (إضافة، تعديل التكلفة والكمية والحد الشهري وأقل مستوى، إتاحة/إيقاف)، نقاط كل قاعدة وحدّها اليومي، ألقاب المستويات وحدودها، تقدير يدوي بسبب مكتوب، وإعادة الاحتساب. كل تعديل يُسجَّل في «سجل التعديلات».',
                       'The reward catalog (add, edit cost, stock, monthly limit and minimum level, switch on/off), each rule\'s points and daily cap, level titles and thresholds, manual recognition with a written reason, and recalculation. Every edit is recorded in the "Change log".')},
        ],
        'tips': [
            T('المبيعات تُحتسب من كود المستخدم في SOFTECH — اطلب من مدير النظام ربط كودك بحسابك وإلا لن تظهر نقاط مبيعاتك.',
              'Sales are counted by your SOFTECH user code — ask the system admin to link your code to your account, otherwise your sales will not score.'),
            T('لا يمكن احتساب نفس العمل مرتين، ولا يمكن لأحد منح نفسه نقاطاً.',
              'The same work can never be counted twice, and nobody can award points to themselves.'),
        ],
        'faq': [
            {'q': T('هل ينزل مستواي إذا خُصمت نقاط؟', 'Can my level drop if points are deducted?'),
             'a': T('لا. المستوى يُبنى على النقاط المكتسبة فقط؛ الخصومات تؤثر على ترتيب الفترة فقط.',
                    'No. Your level is built on earned points only; deductions only affect the period ranking.')},
            {'q': T('كيف أصبح بطل الشهر؟', 'How do I become champion of the month?'),
             'a': T('كن الأول بين زملاء دورك في فرعك بنهاية الشهر (يحتاج زميلاً واحداً على الأقل في نفس الدور)، أو من أفضل 3 لدورك على كل الفروع. يُحتسب صافي نقاط الشهر بدون مكافآت الأبطال، وبشرط عدم وجود ملاحظة مراجعة مؤكدة. الإدارة لا تنافس على الألقاب.',
                    'Be first among your role in your branch at month end (you need at least one colleague in the same role), or in the top 3 for your role across all branches. The month\'s net points count, without champion bonuses, and with no confirmed audit flag. Management (admin) does not compete.')},
            {'q': T('هل الاستبدال يخفض مستواي أو ترتيبي؟', 'Does redeeming lower my level or rank?'),
             'a': T('لا. ينقص رصيد المكافآت فقط؛ المستوى والترتيب يبقيان كما هما.',
                    'No. Only your reward balance goes down; level and rank stay as they are.')},
            {'q': T('متى تظهر نقاطي؟', 'When do my points show?'),
             'a': T('خلال نصف ساعة من تسجيل العمل. «اليوم النظيف» والخصومات تُحتسب بعد منتصف الليل.',
                    'Within 30 minutes of the work being recorded. The "clean day" and deductions are applied after midnight.')},
        ],
        'related': ['general.dashboard', 'general.me', 'incentives.mine'],
        'updated': '2026-10-10',
    },
]
