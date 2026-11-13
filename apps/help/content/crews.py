from . import T

_CREW_ROW = T('في تبويب «👥 الأطقم» اضغط اسم طاقم في القائمة فيظهر محرره بجانبها.',
              'On the "👥 Crews" tab, click a crew in the list and its editor opens beside it.')
_EDIT_ONLY = T('يظهر لمن لديه صلاحية تعديل الأطقم فقط.', 'Shows only for people allowed to edit crews.')
_UNATTRIBUTED_TAB = T('افتح تبويب «🧾 بائع غير محدد».', 'Open the "🧾 Unknown seller" tab.')

MODULE = {
    'key': 'crews', 'group': 'hr', 'icon': '👥',
    'brief': T('الأطقم: مَن يعمل معًا (كول سنتر، وظيفة، مخصص) بعضوية مؤرخة، ونسبة المبيعات بلا بائع محدد.',
               'Crews: who works together (call center, job, custom) with dated membership, and the share of sales with no known seller.'),
    'title': T('الأطقم', 'Crews'),
    'summary': T(
        'الطاقم يحدد «مَن» والفرع يحدد «أين»: الطاقم مجموعة أشخاص يعملون معًا مثل الكول سنتر أو كل الصيادلة، '
        'وأعضاؤه يأتون من قواعد (وظيفة، فرع، قسم، إدارة) ومن إضافات أو استبعادات يدوية. العضوية مؤرخة: '
        'كل قاعدة وكل سطر يدوي له تاريخ بداية ونهاية، فتعرف من كان في الطاقم في أي يوم. أي تعديل يبدأ من تاريخ '
        'تختاره، ولا يمكن أن يبدأ قبل أول الشهر الحالي، فلا يغيّر الشهور المقفلة أبدًا. الشخص غير الموجود في كشف '
        'الرواتب (كود مستخدم SOFTECH أو رقم داخلي فقط) يظهر بعلامة «خارج كشف الرواتب». تبويب «بائع غير محدد» '
        'يبيّن نسبة المبيعات المسجلة على حساب عام أو حساب جهاز كاشير بدل البائع الحقيقي؛ إصلاحها أمر تشغيلي '
        '(أن يسجل كل بائع بحسابه) وليس من هذه الشاشة. كل تغيير يُسجّل في سجل المراجعة، والشاشة لا تقرأ من SOFTECH ولا تكتب فيه.',
        'A crew says "who" and a branch says "where": a crew is a set of people who work together, such as the call '
        'center or all pharmacists, and its members come from rules (job title, branch, department, section) and from '
        'manual additions or exclusions. Membership is dated: every rule and every manual row has a start and an end '
        'date, so you can tell who was in the crew on any day. Every change starts from a date you choose and cannot '
        'start before the first of the current month, so closed months never change. Someone not on the payroll (a '
        'SOFTECH user code or a phone extension only) carries an «off payroll» badge. The "Unknown seller" tab shows the '
        'share of sales recorded on a generic or cashier-station account instead of the real seller; fixing it is an '
        'operations matter (every seller signing in with their own account), not something this screen does. Every '
        'change is written to the audit log, and the screen never reads from or writes to SOFTECH.'),
    'journeys': [
        {'key': 'build_crew', 'shell': 'desktop', 'roles': ['admin'],
         'title': T('بناء طاقم جديد', 'Building a new crew'),
         'summary': T('من إنشاء الطاقم إلى قواعده ثم مراجعة أعضائه.', 'From creating the crew to its rules, then checking its members.'),
         'steps': [
            {'screen': 'crews.main', 'target': 'crews-list', 'perm': 'crews',
             'label': T('قائمة الأطقم', 'Crew list'),
             'text': T('«+ طاقم جديد» فوق القائمة: الاسم والنوع ثم «إنشاء». بعدها اضغط الطاقم لفتح محرره.',
                       '"+ New crew" above the list: name and type, then "Create". Then click the crew to open its editor.')},
            {'screen': 'crews.main', 'target': 'crews-editor-rules', 'perm': 'crews',
             'label': T('القواعد', 'Rules'),
             'text': T('اختر الوظائف والفروع والأقسام، وتاريخ البداية، ثم «إضافة القاعدة».',
                       'Pick job titles, branches and departments, the start date, then "Add rule".'),
             'open_hint': _CREW_ROW},
            {'screen': 'crews.main', 'target': 'crews-editor-preview', 'perm': 'crews',
             'label': T('المعاينة', 'Preview'),
             'text': T('قبل الحفظ ترى عدد وأسماء من سيكونون في الطاقم من التاريخ المختار.',
                       'Before saving you see how many people, and who, will be in the crew from the chosen date.'),
             'open_hint': _CREW_ROW},
            {'screen': 'crews.main', 'target': 'crews-members-grid', 'perm': 'crews',
             'label': T('👤 الأعضاء', '👤 Members'),
             'text': T('راجع أعضاء الطاقم في أي يوم. «خارج كشف الرواتب» = كود أو رقم داخلي بلا موظف.',
                       'Check the crew’s members on any day. «Off payroll» = a code or extension with no employee.'),
             'open_hint': T('افتح تبويب «👤 الأعضاء».', 'Open the "👤 Members" tab.')},
         ]},
    ],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في الأطقم', 'A tour of crews'),
            'summary': T('القائمة، والقواعد المؤرخة، والأعضاء، والبائع غير المحدد.',
                         'The list, the dated rules, the members, and the unknown seller.'),
            'roles': ['admin'],
            'steps': [
                {'target': 'nav-crews', 'nav': '/crews',
                 'text': T('«الموارد البشرية» ← «الأطقم».', '"Human resources" → "Crews".'),
                 'more': T('الطاقم = مَن (مجموعة أشخاص)، والفرع = أين.\n'
                           '• الشاشة دي بتحدد مين في كل طاقم في كل يوم، عشان الأهداف والتقارير بعد كده.',
                           'A crew = who (a set of people), a branch = where.\n'
                           '• This screen decides who is in each crew on each day, for targets and reports later.')},
                {'target': 'crews-list', 'route': '/crews',
                 'text': T('كل طاقم بنوعه وعدد أعضائه اليوم وآخر تغيير.', 'Every crew with its type, today’s member count and last change.'),
                 'more': T('«إظهار المؤرشفة» يعرض الأطقم المؤرشفة بدل الحالية.\n'
                           '• الطاقم الذي له تاريخ يُؤرشف ولا يُحذف.',
                           '"Show archived" lists archived crews instead of the live ones.\n'
                           '• A crew with history is archived, never deleted.')},
                {'target': 'crews-main-tabs', 'route': '/crews',
                 'text': T('الأعضاء في يوم، والسجل، والبائع غير المحدد في تبويبات منفصلة.',
                           'Members on a day, the history, and the unknown seller are separate tabs.'),
                 'more': T('أي تعديل يبدأ من تاريخ تختاره، ولا يبدأ قبل أول الشهر الحالي.\n'
                           '• الشهور المقفلة لا تتغير أبدًا.',
                           'Every change starts from a date you choose, never before the first of the current month.\n'
                           '• Closed months never change.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'crews.main',
        'routes': ['/crews'],
        'title': T('الأطقم', 'Crews'),
        'summary': T('الأطقم وقواعد عضويتها المؤرخة، والأعضاء في أي يوم، والسجل، ونسبة المبيعات بلا بائع محدد.',
                     'Crews and their dated membership rules, the members on any day, the history, and the share of sales with no known seller.'),
        'audience': T('المدير، ومن يُمنح صلاحية «الأطقم» من مصفوفة الصلاحيات. التعديل يحتاج صلاحية التعديل.',
                      'Admin, and anyone granted the "Crews" module in the permission matrix. Changes need the edit permission.'),
        'tabs': [
            {'key': 'crews', 'title': T('👥 الأطقم', '👥 Crews'),
             'body': T('قائمة الأطقم (اسم ونوع وعدد الأعضاء اليوم وآخر تغيير) وبجانبها محرر الطاقم المختار: الاسم والنوع '
                       'والوصف، ثم القواعد، ثم الإضافات والاستبعادات اليدوية. القاعدة تختار الناس بالوظيفة والفرع والقسم '
                       'والإدارة؛ كل تغيير في الاختيارات يحدّث المعاينة (عدد وأسماء من سيكونون في الطاقم من التاريخ المختار). '
                       'تاريخ البداية افتراضيًا اليوم ولا يقبل ما قبل أول الشهر الحالي. «تعديل» على قاعدة يُنهيها ويبدأ قاعدة '
                       'جديدة من التاريخ. «إنهاء» يوقف السطر من تاريخ؛ السطر الذي يبدأ في هذا التاريخ أو بعده يُلغى من بدايته '
                       'حتى لو طُبق أيامًا من هذا الشهر، وتظهر حالته «إلغاء من بدايته». الأسطر المنتهية والملغاة '
                       'تبقى ظاهرة باهتة بتواريخها. الإضافة اليدوية: ابحث عن موظف بالاسم أو الرقم الوظيفي أو كود المستخدم، أو '
                       'اختر «خارج كشف الرواتب» واكتب كود مستخدم و/أو رقم داخلي واسمًا؛ السبب إلزامي. «حذف / أرشفة» يحذف '
                       'الطاقم الذي لم يكن له أعضاء قط، ويؤرشف غيره.',
                       'The crew list (name, type, today’s member count and last change) with the selected crew’s editor beside '
                       'it: name, type and description, then the rules, then the manual additions and exclusions. A rule picks '
                       'people by job title, branch, department and section; every change to the picks refreshes the preview '
                       '(how many people, and who, will be in the crew from the chosen date). The start date is today by '
                       'default and cannot be before the first of the current month. "Edit" on a rule ends it and starts a new '
                       'rule from the date. "End" stops a row from a date; a row that starts on or after that date is cancelled from its start '
                       'even if it applied for some days this month, and shows "cancelled from its start". Ended and '
                       'voided rows stay visible, faded, with their dates. Manual add: search an employee by name, HR number or '
                       'user code, or choose «off payroll» and type a user code and/or an extension and a label; a reason is '
                       'required. "Delete / archive" deletes a crew that never had members and archives any other.')},
            {'key': 'members', 'title': T('👤 الأعضاء', '👤 Members'),
             'body': T('أعضاء الطاقم المختار في يوم تختاره (افتراضيًا اليوم): الاسم، والرقم الوظيفي، والوظيفة، والفرع، '
                       'وأكواد المستخدم، والأرقام الداخلية، ومصدر العضوية (قاعدة أو يدوي). من ليس في كشف الرواتب يظهر '
                       'بعلامة «خارج كشف الرواتب». الجدول يترتب بالضغط على العنوان ويُتنقل فيه بالأسهم.',
                       'The selected crew’s members on a day you choose (today by default): name, HR number, job title, branch, '
                       'user codes, extensions, and where the membership comes from (rule or manual). Someone not on the payroll '
                       'carries an «off payroll» badge. The table sorts by clicking a header and moves with the arrow keys.')},
            {'key': 'history', 'title': T('📜 السجل', '📜 History'),
             'body': T('لفترة تختارها (افتراضيًا آخر 12 شهرًا، ثلاث سنوات على الأكثر): فترات عضوية كل شخص (من – إلى)، '
                       'وكل تغيير على الطاقم: متى، ومن، وماذا (قبل وبعد).',
                       'For a period you choose (the last 12 months by default, three years at most): each person’s membership '
                       'spans (from – to), and every change to the crew: when, who, and what (before and after).')},
            {'key': 'unattributed', 'title': T('🧾 بائع غير محدد', '🧾 Unknown seller'),
             'body': T('لكل فرع في الفترة: عدد الفواتير والمبلغ، والمبلغ المسجل على حساب عام أو حساب جهاز كاشير، ونسبته. '
                       'تحته أكبر حسابات البيع بالمبلغ، ومن لديه صلاحية التعديل يعلّم الحساب «حساب عام» فيُحسب ضمن غير المحدد. '
                       'الحساب العام بسبب مجموعته في SOFTECH يظهر معلّمًا ولا يُفك من هنا. خفض النسبة أمر تشغيلي: أن يبيع كل '
                       'شخص بحسابه.',
                       'For each branch in the period: invoices and amount, the amount recorded on a generic or cashier-station '
                       'account, and its share. Below, the biggest selling accounts by amount; someone with the edit permission '
                       'marks an account "Generic account" so it counts as unknown. An account that is generic because of its '
                       'SOFTECH group shows ticked and cannot be unticked here. Lowering the share is an operations matter: '
                       'everyone selling under their own account.')},
        ],
        'tips': [
            T('تعديلات الأطقم تبدأ من تاريخ، ولا تبدأ قبل أول الشهر الحالي — السيرفر يرفض غير ذلك.',
              'Crew changes start from a date, never before the first of the current month — the server refuses otherwise.'),
            T('كل الجداول تترتب بالضغط على عنوان العمود.', 'Every table sorts by clicking a column header.'),
        ],
        'related': ['hr.attendance_zk'],
        'tour': [
            {'target': 'crews-main-tabs', 'label': T('الأطقم · الأعضاء · السجل · بائع غير محدد', 'Crews · Members · History · Unknown'),
             'text': T('أربعة تبويبات للطاقم المختار وللمبيعات بلا بائع محدد.', 'Four tabs for the selected crew and for sales with no known seller.')},
            {'target': 'crews-list', 'label': T('قائمة الأطقم', 'Crew list'),
             'text': T('اضغط طاقمًا لفتح محرره. «إظهار المؤرشفة» يعرض المؤرشفة فقط.',
                       'Click a crew to open its editor. "Show archived" lists archived crews only.')},
            {'target': 'crews-editor-rules', 'label': T('القواعد', 'Rules'),
             'text': T('مَن في الطاقم بالوظيفة والفرع والقسم، من تاريخ. المنتهية والملغاة تبقى ظاهرة باهتة.',
                       'Who is in the crew by job, branch and department, from a date. Ended and voided rows stay, faded.'),
             'warn': T('لا يمكن البدء قبل أول الشهر الحالي — الشهور السابقة مقفلة.',
                       'A change cannot start before the first of the current month — earlier months are closed.'),
             'open_hint': _CREW_ROW},
            {'target': 'crews-editor-preview', 'label': T('المعاينة', 'Preview'),
             'text': T('عدد وأسماء من سيكونون في الطاقم من التاريخ المختار. لا يحفظ شيئًا.',
                       'How many people, and who, will be in the crew from the chosen date. Saves nothing.'),
             'open_hint': _EDIT_ONLY},
            {'target': 'crews-editor-manual', 'label': T('إضافة / استبعاد يدوي', 'Manual add / exclude'),
             'text': T('موظف بالاسم أو الرقم أو الكود، أو «خارج كشف الرواتب» بكود أو رقم داخلي. السبب إلزامي.',
                       'An employee by name, number or code, or «off payroll» by code or extension. A reason is required.'),
             'open_hint': _CREW_ROW},
            {'target': 'crews-members-grid', 'label': T('👤 الأعضاء', '👤 Members'),
             'text': T('أعضاء الطاقم في اليوم المختار ومصدر كل عضوية (قاعدة أو يدوي).',
                       'The crew’s members on the chosen day and where each membership comes from (rule or manual).'),
             'open_hint': T('افتح تبويب «👤 الأعضاء».', 'Open the "👤 Members" tab.')},
            {'target': 'crews-history', 'label': T('📜 السجل', '📜 History'),
             'text': T('فترات العضوية لكل شخص وكل تغيير بمن ومتى وقبل وبعد.',
                       'Each person’s membership spans and every change with who, when, before and after.'),
             'open_hint': T('افتح تبويب «📜 السجل».', 'Open the "📜 History" tab.')},
            {'target': 'crews-unattributed-branches', 'label': T('نسبة غير المحدد', 'Unknown share'),
             'text': T('لكل فرع: الفواتير والمبلغ والمبلغ بلا بائع حقيقي ونسبته.',
                       'For each branch: invoices, amount, the amount with no real seller and its share.'),
             'open_hint': _UNATTRIBUTED_TAB},
            {'target': 'crews-unattributed-sellers', 'label': T('حسابات البيع', 'Selling accounts'),
             'text': T('أكبر الحسابات بالمبلغ. «حساب عام» يحسب الحساب ضمن غير المحدد.',
                       'The biggest accounts by amount. "Generic account" counts the account as unknown.'),
             'open_hint': _UNATTRIBUTED_TAB},
        ],
        'updated': '2026-11-13',
    },
]
